"""
migrar_datos.py
----------------
Script de un solo uso (no forma parte de la app) para migrar los datos
reales de `panaderia.db` (SQLite local) a Supabase (Postgres) — Etapa 4
de la migración a la nube.

No borra ni toca `panaderia.db` en ningún momento: solo lo lee.

Uso:
    python migrar_datos.py [ruta_a_panaderia.db]

Si no se pasa ruta, usa por defecto la carpeta hermana del proyecto
principal: ../panaderia_sistema/panaderia.db

Seguridad: si alguna tabla de datos en Supabase ya tiene filas, el
script aborta sin tocar nada (evita duplicar datos en una corrida
repetida). Todo corre en una sola transacción: si la verificación final
de conteos no coincide, se hace rollback completo.
"""

import sys
import sqlite3
from pathlib import Path

import toml
import psycopg2

# Orden de inserción: tablas padre antes que las que tienen FK hacia ellas.
TABLAS_DATOS = [
    "ingredientes",
    "historial_precios_ingredientes",
    "recetas",
    "receta_ingredientes",
    "clientes",
    "pedidos",
    "pedido_items",
    "movimientos_caja",
]

# Columnas a copiar por tabla (en este orden). Se listan explícitamente
# en vez de usar SELECT * para no arrastrar columnas viejas/obsoletas
# que puedan quedar en el SQLite local (ej. recargo_luz_pct).
COLUMNAS = {
    "ingredientes": ["id", "nombre", "unidad_base", "precio_actual", "proveedor", "fecha_actualizacion"],
    "historial_precios_ingredientes": ["id", "ingrediente_id", "precio", "fecha"],
    "recetas": ["id", "nombre", "precio_venta", "margen_objetivo", "activo", "notas",
                "tiempo_preparacion_min", "unidades_por_lote", "consumo_kwh_programa"],
    "receta_ingredientes": ["id", "receta_id", "ingrediente_id", "cantidad"],
    "clientes": ["id", "nombre", "telefono", "direccion", "notas", "fecha_creacion"],
    "pedidos": ["id", "cliente_id", "fecha_entrega", "estado", "pagado", "medio_pago", "notas", "fecha_creacion"],
    "pedido_items": ["id", "pedido_id", "receta_id", "cantidad", "precio_unitario"],
    "movimientos_caja": ["id", "tipo", "monto", "medio_pago", "categoria", "descripcion", "fecha"],
}

# Columnas que son booleanas en Postgres pero 0/1 (INTEGER) en SQLite.
COLUMNAS_BOOLEANAS = {
    "recetas": ["activo"],
    "pedidos": ["pagado"],
}

# Tablas de configuración: fila única (id=1) que inicializar_db() ya
# sembró con valores por defecto. Acá se actualiza (no se inserta) con
# los valores reales del negocio.
TABLAS_CONFIG = {
    "configuracion_comisiones": ["tasa_debito_pct", "tasa_credito_pct", "iva_pct"],
    "configuracion_costos": ["costo_empaque_unidad", "valor_hora_mano_obra",
                              "tarifa_electrica_kwh", "factor_descuento_luz"],
    "configuracion_produccion": ["horas_disponibles_dia"],
}


def convertir_valor(tabla, columna, valor):
    if valor is not None and columna in COLUMNAS_BOOLEANAS.get(tabla, []):
        return bool(valor)
    return valor


def main():
    ruta_sqlite = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "panaderia_sistema" / "panaderia.db"
    if not ruta_sqlite.exists():
        print(f"No se encontró la base SQLite en: {ruta_sqlite}")
        sys.exit(1)

    secrets = toml.load(Path(__file__).parent / ".streamlit" / "secrets.toml")
    pg_url = secrets["postgres"]["url"]

    print(f"Origen (SQLite):  {ruta_sqlite}")
    print("Destino (Postgres): Supabase\n")

    origen = sqlite3.connect(ruta_sqlite)
    origen.row_factory = sqlite3.Row

    destino = psycopg2.connect(pg_url)
    destino.autocommit = False
    cur = destino.cursor()

    try:
        # --- Chequeo de seguridad: no pisar datos ya migrados -----------
        for tabla in TABLAS_DATOS:
            cur.execute(f"SELECT COUNT(*) FROM {tabla}")
            n = cur.fetchone()[0]
            if n > 0:
                print(f"ABORTADO: la tabla '{tabla}' en Supabase ya tiene {n} fila(s).")
                print("Este script es para la primera carga; no está pensado para correr dos veces.")
                destino.rollback()
                sys.exit(1)

        conteos_origen = {}

        # --- Copiar tablas de datos ---------------------------------------
        for tabla in TABLAS_DATOS:
            cols = COLUMNAS[tabla]
            filas = origen.execute(f"SELECT {', '.join(cols)} FROM {tabla}").fetchall()
            conteos_origen[tabla] = len(filas)

            if filas:
                placeholders = ", ".join(["%s"] * len(cols))
                columnas_sql = ", ".join(cols)
                sql = (
                    f"INSERT INTO {tabla} ({columnas_sql}) "
                    f"OVERRIDING SYSTEM VALUE VALUES ({placeholders})"
                )
                for fila in filas:
                    valores = [convertir_valor(tabla, c, fila[c]) for c in cols]
                    cur.execute(sql, valores)

                # Reacomodar la secuencia de la identity column para que
                # el próximo INSERT normal (sin id explícito) siga desde
                # el máximo id migrado, no desde 1.
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    "(SELECT COALESCE(MAX(id), 1) FROM " + tabla + "), true)",
                    (tabla,),
                )

            print(f"  {tabla}: {len(filas)} fila(s) copiadas")

        # --- Actualizar tablas de configuración con valores reales --------
        for tabla, cols in TABLAS_CONFIG.items():
            fila = origen.execute(f"SELECT {', '.join(cols)} FROM {tabla} WHERE id = 1").fetchone()
            if fila:
                set_sql = ", ".join(f"{c} = %s" for c in cols)
                cur.execute(f"UPDATE {tabla} SET {set_sql} WHERE id = 1", [fila[c] for c in cols])
                print(f"  {tabla}: actualizada con los valores reales")

        # --- Verificación: comparar conteos origen vs destino -------------
        print("\nVerificación de conteos:")
        todo_ok = True
        for tabla in TABLAS_DATOS:
            cur.execute(f"SELECT COUNT(*) FROM {tabla}")
            n_destino = cur.fetchone()[0]
            n_origen = conteos_origen[tabla]
            estado = "OK" if n_destino == n_origen else "MISMATCH"
            if n_destino != n_origen:
                todo_ok = False
            print(f"  {tabla}: origen={n_origen} destino={n_destino}  [{estado}]")

        if not todo_ok:
            print("\nHay diferencias de conteo — se hace ROLLBACK, no se guarda nada.")
            destino.rollback()
            sys.exit(1)

        destino.commit()
        print("\nMigración completada y confirmada (commit). panaderia.db no fue modificado.")

    except Exception as e:
        destino.rollback()
        print(f"\nERROR durante la migración, se hizo ROLLBACK (no se guardó nada parcial): {e}")
        raise
    finally:
        cur.close()
        destino.close()
        origen.close()


if __name__ == "__main__":
    main()
