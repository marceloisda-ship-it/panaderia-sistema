"""
db.py
-----
Módulo central de acceso a la base de datos del sistema de gestión
de la panadería. La base de datos vive en Supabase (Postgres) para
que el equipo pueda usar el sistema desde varios dispositivos a la vez.

La cadena de conexión se lee desde `st.secrets["postgres"]["url"]`
(ver .streamlit/secrets.toml en desarrollo, o los "Secrets" del panel
de Streamlit Community Cloud en producción) — nunca queda en el código.
"""

import streamlit as st
import psycopg2
import psycopg2.extras


class _ConexionConExecute:
    """Envuelve una conexión psycopg2 para agregarle un método `.execute()`
    a nivel de conexión, igual que trae sqlite3 nativamente. psycopg2 solo
    permite ejecutar consultas desde un cursor — sin este envoltorio,
    habría que reescribir cada `conn.execute(...)` de los 8 módulos de
    negocio por `cursor = conn.cursor(); cursor.execute(...)`. Todo lo
    demás (placeholders %s, RETURNING en vez de lastrowid, etc.) sí hubo
    que ajustarlo módulo por módulo — esto solo evita ese cambio en
    particular, que era puramente mecánico."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=None):
        cursor = self._conn.cursor()
        cursor.execute(query, params or ())
        return cursor

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def conectar() -> _ConexionConExecute:
    """Abre y retorna una conexión a la base de datos Postgres (Supabase).

    Se usa `RealDictCursor` para poder seguir accediendo a las columnas
    de los resultados por nombre (ej. fila["nombre"]), igual que con
    sqlite3.Row en la versión anterior local.
    """
    conn = psycopg2.connect(
        st.secrets["postgres"]["url"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return _ConexionConExecute(conn)


def inicializar_db() -> None:
    """Crea todas las tablas del sistema si es que no existen aún.

    Es seguro llamar esta función cada vez que arranca el programa:
    no borra ni duplica datos existentes.
    """
    conn = conectar()
    cursor = conn.cursor()

    # --- Módulo de Costeo -------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredientes (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            unidad_base TEXT NOT NULL CHECK (unidad_base IN ('gr', 'ml', 'unidad')),
            precio_actual REAL NOT NULL CHECK (precio_actual >= 0),
            proveedor TEXT,
            fecha_actualizacion TEXT NOT NULL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historial_precios_ingredientes (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ingrediente_id INTEGER NOT NULL REFERENCES ingredientes(id) ON DELETE CASCADE,
            precio REAL NOT NULL,
            fecha TEXT NOT NULL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recetas (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            precio_venta REAL NOT NULL CHECK (precio_venta >= 0),
            margen_objetivo REAL NOT NULL DEFAULT 0.4,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            notas TEXT,
            tiempo_preparacion_min REAL NOT NULL DEFAULT 0,
            unidades_por_lote INTEGER NOT NULL DEFAULT 1,
            consumo_kwh_programa REAL NOT NULL DEFAULT 0
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receta_ingredientes (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            receta_id INTEGER NOT NULL REFERENCES recetas(id) ON DELETE CASCADE,
            ingrediente_id INTEGER NOT NULL REFERENCES ingredientes(id) ON DELETE RESTRICT,
            cantidad REAL NOT NULL CHECK (cantidad > 0),
            UNIQUE (receta_id, ingrediente_id)
        );
    """)

    # --- Módulo de Flujo de caja -------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_caja (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tipo TEXT NOT NULL CHECK (tipo IN ('ingreso', 'gasto')),
            monto REAL NOT NULL CHECK (monto > 0),
            medio_pago TEXT NOT NULL CHECK (medio_pago IN ('efectivo', 'debito', 'credito', 'transferencia')),
            categoria TEXT,
            descripcion TEXT,
            fecha TEXT NOT NULL
        );
    """)

    # --- Módulo de Comisiones de medios de pago -----------------------------
    # Fila única (id = 1) con las tasas de comisión que cobra el medio de
    # pago electrónico (ej. Mercado Pago Point) por cobrar con tarjeta.
    # Se usan para registrar automáticamente un gasto por comisión en Caja
    # cuando se cobra un pedido con débito o crédito (ver pedidos.py).
    # Los porcentajes se guardan como fracción (ej. 0.0219 = 2,19%).

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_comisiones (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            tasa_debito_pct REAL NOT NULL DEFAULT 0 CHECK (tasa_debito_pct >= 0),
            tasa_credito_pct REAL NOT NULL DEFAULT 0 CHECK (tasa_credito_pct >= 0),
            iva_pct REAL NOT NULL DEFAULT 0 CHECK (iva_pct >= 0)
        );
    """)
    cursor.execute("""
        INSERT INTO configuracion_comisiones (id, tasa_debito_pct, tasa_credito_pct, iva_pct)
        VALUES (1, 0.0219, 0.0269, 0.19)
        ON CONFLICT (id) DO NOTHING;
    """)

    # --- Módulo de Costos indirectos ---------------------------------------
    # Fila única (id = 1) con los parámetros globales para prorratear
    # costos indirectos al costeo de cada receta.

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_costos (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            costo_empaque_unidad REAL NOT NULL DEFAULT 0 CHECK (costo_empaque_unidad >= 0),
            valor_hora_mano_obra REAL NOT NULL DEFAULT 0 CHECK (valor_hora_mano_obra >= 0),
            tarifa_electrica_kwh REAL NOT NULL DEFAULT 0 CHECK (tarifa_electrica_kwh >= 0),
            factor_descuento_luz REAL NOT NULL DEFAULT 1 CHECK (factor_descuento_luz >= 0 AND factor_descuento_luz <= 1)
        );
    """)
    cursor.execute("""
        INSERT INTO configuracion_costos
            (id, costo_empaque_unidad, valor_hora_mano_obra, tarifa_electrica_kwh, factor_descuento_luz)
        VALUES (1, 0, 0, 0, 1)
        ON CONFLICT (id) DO NOTHING;
    """)

    # --- Módulo de Producción (capacidad diaria) ----------------------------
    # Fila única (id = 1): cuántas horas al día se dedican a producir,
    # usada junto con tiempo_preparacion_min/unidades_por_lote de cada
    # receta para calcular cuánto se puede comprometer por día (Pedidos).

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_produccion (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            horas_disponibles_dia REAL NOT NULL DEFAULT 0 CHECK (horas_disponibles_dia >= 0)
        );
    """)
    cursor.execute("""
        INSERT INTO configuracion_produccion (id, horas_disponibles_dia)
        VALUES (1, 0)
        ON CONFLICT (id) DO NOTHING;
    """)

    # --- Módulo de Clientes --------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nombre TEXT NOT NULL,
            telefono TEXT,
            direccion TEXT,
            notas TEXT,
            fecha_creacion TEXT NOT NULL
        );
    """)

    # --- Módulo de Pedidos ---------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
            fecha_entrega TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente', 'confirmado', 'entregado', 'cancelado')),
            pagado BOOLEAN NOT NULL DEFAULT FALSE,
            medio_pago TEXT CHECK (medio_pago IN ('efectivo', 'debito', 'credito', 'transferencia')),
            notas TEXT,
            fecha_creacion TEXT NOT NULL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pedido_items (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            pedido_id INTEGER NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
            receta_id INTEGER NOT NULL REFERENCES recetas(id) ON DELETE RESTRICT,
            cantidad INTEGER NOT NULL CHECK (cantidad > 0),
            precio_unitario REAL NOT NULL CHECK (precio_unitario >= 0),
            UNIQUE (pedido_id, receta_id)
        );
    """)

    conn.commit()
    cursor.close()
    conn.close()
