"""
db.py
-----
Módulo central de acceso a la base de datos del sistema de gestión
de la panadería. Toda la aplicación usa una única base SQLite local
llamada `panaderia.db`, ubicada en la misma carpeta que este archivo.

Diseño pensado para crecer: cada módulo futuro (caja, pedidos, clientes)
agregará sus propias tablas aquí, pero todos comparten esta misma
conexión y el mismo archivo de base de datos.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

# Ruta del archivo de base de datos (siempre junto a este script)
DB_PATH = Path(__file__).parent / "panaderia.db"


def conectar() -> sqlite3.Connection:
    """Abre y retorna una conexión a la base de datos SQLite.

    Se activa el soporte de llaves foráneas (SQLite lo trae desactivado
    por defecto) y se configura row_factory para poder acceder a las
    columnas de los resultados por nombre (ej. fila["nombre"]).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            unidad_base TEXT NOT NULL CHECK (unidad_base IN ('gr', 'ml', 'unidad')),
            precio_actual REAL NOT NULL CHECK (precio_actual >= 0),
            proveedor TEXT,
            fecha_actualizacion TEXT NOT NULL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historial_precios_ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingrediente_id INTEGER NOT NULL,
            precio REAL NOT NULL,
            fecha TEXT NOT NULL,
            FOREIGN KEY (ingrediente_id) REFERENCES ingredientes(id) ON DELETE CASCADE
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            precio_venta REAL NOT NULL CHECK (precio_venta >= 0),
            margen_objetivo REAL NOT NULL DEFAULT 0.4,
            activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
            notas TEXT
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receta_ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receta_id INTEGER NOT NULL,
            ingrediente_id INTEGER NOT NULL,
            cantidad REAL NOT NULL CHECK (cantidad > 0),
            FOREIGN KEY (receta_id) REFERENCES recetas(id) ON DELETE CASCADE,
            FOREIGN KEY (ingrediente_id) REFERENCES ingredientes(id) ON DELETE RESTRICT,
            UNIQUE (receta_id, ingrediente_id)
        );
    """)

    # Migración: columnas de mano de obra en recetas (tiempo que toma
    # preparar un lote y cuántas unidades rinde ese lote). Se agregan con
    # ALTER TABLE porque la tabla `recetas` ya pudo existir de antes.
    columnas_recetas = {f["name"] for f in cursor.execute("PRAGMA table_info(recetas)").fetchall()}
    if "tiempo_preparacion_min" not in columnas_recetas:
        cursor.execute(
            "ALTER TABLE recetas ADD COLUMN tiempo_preparacion_min REAL NOT NULL DEFAULT 0"
        )
    if "unidades_por_lote" not in columnas_recetas:
        cursor.execute(
            "ALTER TABLE recetas ADD COLUMN unidades_por_lote INTEGER NOT NULL DEFAULT 1"
        )

    # Migración: consumo eléctrico del programa de la máquina de pan que usa
    # esta receta (kWh por lote), para calcular su costo de luz propio en vez
    # de un % genérico sobre el costo directo (ver configuracion_costos más abajo).
    if "consumo_kwh_programa" not in columnas_recetas:
        cursor.execute(
            "ALTER TABLE recetas ADD COLUMN consumo_kwh_programa REAL NOT NULL DEFAULT 0"
        )

    # --- Módulo de Flujo de caja -------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_caja (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL CHECK (tipo IN ('ingreso', 'gasto')),
            monto REAL NOT NULL CHECK (monto > 0),
            medio_pago TEXT NOT NULL CHECK (medio_pago IN ('efectivo', 'debito', 'credito', 'transferencia')),
            categoria TEXT,
            descripcion TEXT,
            fecha TEXT NOT NULL
        );
    """)

    # Migración: agregar 'credito' como medio de pago válido. SQLite no
    # permite modificar un CHECK existente con ALTER TABLE, así que la
    # tabla se reconstruye siguiendo el procedimiento que recomienda SQLite
    # para cambios de esquema (crear tabla nueva, copiar datos, reemplazar).
    def _check_admite_credito(nombre_tabla: str) -> bool:
        fila = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (nombre_tabla,)
        ).fetchone()
        return fila is not None and "'credito'" in fila["sql"]

    if not _check_admite_credito("movimientos_caja"):
        # PRAGMA foreign_keys es un no-op si hay una transacción implícita
        # pendiente (ej. abierta por un INSERT anterior) — hay que cerrarla
        # con commit() antes, o el toggle a OFF se ignora silenciosamente.
        conn.commit()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("DROP TABLE IF EXISTS movimientos_caja_new")
        cursor.execute("""
            CREATE TABLE movimientos_caja_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL CHECK (tipo IN ('ingreso', 'gasto')),
                monto REAL NOT NULL CHECK (monto > 0),
                medio_pago TEXT NOT NULL CHECK (medio_pago IN ('efectivo', 'debito', 'credito', 'transferencia')),
                categoria TEXT,
                descripcion TEXT,
                fecha TEXT NOT NULL
            );
        """)
        cursor.execute(
            """INSERT INTO movimientos_caja_new (id, tipo, monto, medio_pago, categoria, descripcion, fecha)
               SELECT id, tipo, monto, medio_pago, categoria, descripcion, fecha FROM movimientos_caja"""
        )
        cursor.execute("DROP TABLE movimientos_caja")
        cursor.execute("ALTER TABLE movimientos_caja_new RENAME TO movimientos_caja")
        conn.commit()
        cursor.execute("PRAGMA foreign_keys=ON")

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
        INSERT OR IGNORE INTO configuracion_comisiones (id, tasa_debito_pct, tasa_credito_pct, iva_pct)
        VALUES (1, 0.0219, 0.0269, 0.19);
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
    # Migración: la luz dejó de calcularse como % global sobre el costo
    # directo (`recargo_luz_pct`) y pasó a calcularse por receta según el
    # consumo de su programa (`recetas.consumo_kwh_programa`) — ver
    # costos_indirectos.py y recetas.py. La columna vieja `recargo_luz_pct`
    # puede quedar en bases existentes sin usarse; acá solo se agregan las
    # columnas nuevas si faltan (tiene que ir antes del INSERT de más abajo,
    # porque en bases existentes la tabla ya existía sin estas columnas).
    columnas_costos = {f["name"] for f in cursor.execute("PRAGMA table_info(configuracion_costos)").fetchall()}
    if "tarifa_electrica_kwh" not in columnas_costos:
        cursor.execute(
            "ALTER TABLE configuracion_costos ADD COLUMN tarifa_electrica_kwh REAL NOT NULL DEFAULT 0"
        )
    if "factor_descuento_luz" not in columnas_costos:
        cursor.execute(
            "ALTER TABLE configuracion_costos ADD COLUMN factor_descuento_luz REAL NOT NULL DEFAULT 1"
        )

    cursor.execute("""
        INSERT OR IGNORE INTO configuracion_costos
            (id, costo_empaque_unidad, valor_hora_mano_obra, tarifa_electrica_kwh, factor_descuento_luz)
        VALUES (1, 0, 0, 0, 1);
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
        INSERT OR IGNORE INTO configuracion_produccion (id, horas_disponibles_dia)
        VALUES (1, 0);
    """)

    # --- Módulo de Clientes --------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            fecha_entrega TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente', 'confirmado', 'entregado', 'cancelado')),
            pagado INTEGER NOT NULL DEFAULT 0 CHECK (pagado IN (0, 1)),
            medio_pago TEXT CHECK (medio_pago IN ('efectivo', 'debito', 'credito', 'transferencia')),
            notas TEXT,
            fecha_creacion TEXT NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE RESTRICT
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pedido_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            receta_id INTEGER NOT NULL,
            cantidad INTEGER NOT NULL CHECK (cantidad > 0),
            precio_unitario REAL NOT NULL CHECK (precio_unitario >= 0),
            FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE,
            FOREIGN KEY (receta_id) REFERENCES recetas(id) ON DELETE RESTRICT,
            UNIQUE (pedido_id, receta_id)
        );
    """)

    # Migración: pedidos guardaba antes el cliente como texto libre
    # (cliente_nombre/cliente_telefono). Se convierte cada combinación ya
    # usada en un cliente real de la tabla `clientes`, se enlazan los
    # pedidos existentes por cliente_id, y se eliminan las columnas viejas.
    columnas_pedidos = {f["name"] for f in cursor.execute("PRAGMA table_info(pedidos)").fetchall()}
    if "cliente_nombre" in columnas_pedidos:
        if "cliente_id" not in columnas_pedidos:
            cursor.execute("ALTER TABLE pedidos ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)")

        combinaciones = cursor.execute(
            """SELECT DISTINCT TRIM(cliente_nombre) AS nombre, TRIM(cliente_telefono) AS telefono
               FROM pedidos WHERE cliente_id IS NULL"""
        ).fetchall()

        ahora = datetime.now().isoformat(timespec="seconds")
        for combinacion in combinaciones:
            nombre = combinacion["nombre"]
            telefono = combinacion["telefono"] or None

            cliente = cursor.execute(
                "SELECT id FROM clientes WHERE nombre = ? AND IFNULL(telefono, '') = IFNULL(?, '')",
                (nombre, telefono),
            ).fetchone()
            if cliente is None:
                cursor.execute(
                    "INSERT INTO clientes (nombre, telefono, fecha_creacion) VALUES (?, ?, ?)",
                    (nombre, telefono, ahora),
                )
                cliente_id = cursor.lastrowid
            else:
                cliente_id = cliente["id"]

            cursor.execute(
                """UPDATE pedidos SET cliente_id = ?
                   WHERE TRIM(cliente_nombre) = ? AND IFNULL(TRIM(cliente_telefono), '') = IFNULL(?, '')
                     AND cliente_id IS NULL""",
                (cliente_id, nombre, telefono),
            )

        cursor.execute("ALTER TABLE pedidos DROP COLUMN cliente_nombre")
        cursor.execute("ALTER TABLE pedidos DROP COLUMN cliente_telefono")

    # Migración: agregar 'credito' como medio de pago válido en pedidos
    # (mismo motivo y procedimiento que en movimientos_caja, más arriba).
    if not _check_admite_credito("pedidos"):
        conn.commit()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("DROP TABLE IF EXISTS pedidos_new")
        cursor.execute("""
            CREATE TABLE pedidos_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                fecha_entrega TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'confirmado', 'entregado', 'cancelado')),
                pagado INTEGER NOT NULL DEFAULT 0 CHECK (pagado IN (0, 1)),
                medio_pago TEXT CHECK (medio_pago IN ('efectivo', 'debito', 'credito', 'transferencia')),
                notas TEXT,
                fecha_creacion TEXT NOT NULL,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE RESTRICT
            );
        """)
        cursor.execute(
            """INSERT INTO pedidos_new
                   (id, cliente_id, fecha_entrega, estado, pagado, medio_pago, notas, fecha_creacion)
               SELECT id, cliente_id, fecha_entrega, estado, pagado, medio_pago, notas, fecha_creacion
               FROM pedidos"""
        )
        cursor.execute("DROP TABLE pedidos")
        cursor.execute("ALTER TABLE pedidos_new RENAME TO pedidos")
        conn.commit()
        cursor.execute("PRAGMA foreign_keys=ON")

        problemas = cursor.execute("PRAGMA foreign_key_check").fetchall()
        if problemas:
            raise RuntimeError(
                f"Migración de 'pedidos' dejó referencias rotas, revisar antes de continuar: {problemas}"
            )

    conn.commit()
    conn.close()
