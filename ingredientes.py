"""
ingredientes.py
----------------
Gestión de ingredientes: alta, listado, y actualización de precios
con historial. El "precio_actual" de un ingrediente siempre está en
costo por unidad_base (gramo, mililitro o unidad), para que el cálculo
de costo de una receta sea una simple multiplicación.
"""

from datetime import datetime
from db import conectar, cache_lectura

UNIDADES_VALIDAS = ("gr", "ml", "unidad")


TIPOS_VALIDOS = ("ingrediente", "insumo")
# Ingrediente = lo que lleva el pan. Insumo = todo lo demás que se compra y
# se gasta (empaque, papel mantequilla, guantes, limpieza…), con categoría.
# Solo los insumos de categoría 'empaque' se asignan a las recetas como bolsa.
CATEGORIAS_INSUMO = ("empaque", "papel", "proteccion", "limpieza", "otro")
ETIQUETAS_CATEGORIA = {
    "empaque": "Empaque (bolsas, cajas, etiquetas)",
    "papel": "Papel (mantequilla, etc.)",
    "proteccion": "Protección (guantes, cofias)",
    "limpieza": "Limpieza",
    "otro": "Otro",
}


def normalizar_categoria(tipo: str, categoria: str | None) -> str | None:
    """Valida el par tipo/categoría: un ingrediente no lleva categoría y un
    insumo siempre (si no se indica, 'otro')."""
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"tipo debe ser uno de {TIPOS_VALIDOS}")
    if tipo == "ingrediente":
        return None
    categoria = categoria or "otro"
    if categoria not in CATEGORIAS_INSUMO:
        raise ValueError(f"categoria debe ser una de {CATEGORIAS_INSUMO}")
    return categoria


def etiqueta_tipo(item: dict) -> str:
    """Texto corto para tablas: 'Ingrediente' o 'Insumo · Empaque'."""
    if item["tipo"] == "ingrediente":
        return "Ingrediente"
    return f"Insumo · {(item.get('categoria') or 'otro').capitalize()}"


def agregar_ingrediente(nombre: str, unidad_base: str, precio_actual: float,
                         proveedor: str | None = None, tipo: str = "ingrediente",
                         stock_minimo: float = 0, categoria: str | None = None) -> int:
    """Registra un nuevo ingrediente (o insumo: empaque, papel, guantes…) y
    guarda su primer precio en el historial.

    Retorna el id del ingrediente creado.
    """
    if unidad_base not in UNIDADES_VALIDAS:
        raise ValueError(f"unidad_base debe ser una de {UNIDADES_VALIDAS}")
    categoria = normalizar_categoria(tipo, categoria)
    if tipo == "insumo" and categoria == "empaque" and unidad_base != "unidad":
        raise ValueError("Un empaque debe estar en 'unidad' (se usa 1 por pan vendido)")
    if precio_actual < 0:
        raise ValueError("El precio no puede ser negativo")
    if stock_minimo < 0:
        raise ValueError("El stock mínimo no puede ser negativo")

    fecha = datetime.now().isoformat(timespec="seconds")
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO ingredientes
                   (nombre, unidad_base, precio_actual, proveedor, fecha_actualizacion, tipo, stock_minimo,
                    categoria)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (nombre, unidad_base, precio_actual, proveedor, fecha, tipo, stock_minimo, categoria),
        )
        ingrediente_id = cursor.fetchone()["id"]
        cursor.execute(
            """INSERT INTO historial_precios_ingredientes (ingrediente_id, precio, fecha)
               VALUES (%s, %s, %s)""",
            (ingrediente_id, precio_actual, fecha),
        )
        conn.commit()
        return ingrediente_id
    finally:
        conn.close()


def actualizar_precio(ingrediente_id: int, nuevo_precio: float) -> None:
    """Actualiza el precio actual de un ingrediente y deja registro en el historial.

    Esto es lo que permite, más adelante, ver la evolución de precios
    de cada insumo en el tiempo.
    """
    if nuevo_precio < 0:
        raise ValueError("El precio no puede ser negativo")

    fecha = datetime.now().isoformat(timespec="seconds")
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ingredientes WHERE id = %s", (ingrediente_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"No existe un ingrediente con id {ingrediente_id}")

        cursor.execute(
            "UPDATE ingredientes SET precio_actual = %s, fecha_actualizacion = %s WHERE id = %s",
            (nuevo_precio, fecha, ingrediente_id),
        )
        cursor.execute(
            """INSERT INTO historial_precios_ingredientes (ingrediente_id, precio, fecha)
               VALUES (%s, %s, %s)""",
            (ingrediente_id, nuevo_precio, fecha),
        )
        conn.commit()
    finally:
        conn.close()


@cache_lectura
def listar_ingredientes() -> list[dict]:
    """Retorna todos los ingredientes registrados, ordenados por nombre."""
    conn = conectar()
    try:
        filas = conn.execute(
            "SELECT * FROM ingredientes ORDER BY nombre ASC"
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


@cache_lectura
def buscar_ingrediente_por_nombre(nombre: str) -> dict | None:
    """Busca un ingrediente por nombre exacto. Retorna None si no existe."""
    conn = conectar()
    try:
        fila = conn.execute(
            "SELECT * FROM ingredientes WHERE nombre = %s", (nombre,)
        ).fetchone()
        return dict(fila) if fila else None
    finally:
        conn.close()


@cache_lectura
def historial_de_precio(ingrediente_id: int) -> list[dict]:
    """Retorna el historial de precios de un ingrediente, del más antiguo al más reciente."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT id, precio, fecha FROM historial_precios_ingredientes
               WHERE ingrediente_id = %s ORDER BY fecha ASC""",
            (ingrediente_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def eliminar_registro_historial(historial_id: int) -> None:
    """Elimina un registro puntual del historial de precios (ej. un precio
    cargado por error). No afecta el precio_actual del ingrediente, que se
    guarda aparte en la tabla `ingredientes`."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM historial_precios_ingredientes WHERE id = %s", (historial_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"No existe un registro de historial con id {historial_id}")
        cursor.execute("DELETE FROM historial_precios_ingredientes WHERE id = %s", (historial_id,))
        conn.commit()
    finally:
        conn.close()


def actualizar_proveedor(ingrediente_id: int, nuevo_proveedor: str | None) -> None:
    """Actualiza el proveedor de un ingrediente sin tocar su precio ni el
    historial de precios."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ingredientes WHERE id = %s", (ingrediente_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"No existe un ingrediente con id {ingrediente_id}")
        cursor.execute(
            "UPDATE ingredientes SET proveedor = %s WHERE id = %s",
            (nuevo_proveedor or None, ingrediente_id),
        )
        conn.commit()
    finally:
        conn.close()


@cache_lectura
def recetas_que_usan_ingrediente(ingrediente_id: int) -> list[dict]:
    """Retorna las recetas (id, nombre) que usan este ingrediente. Sirve
    para explicar por qué no se puede eliminar, o qué hay que revisar antes."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT r.id, r.nombre
               FROM receta_ingredientes ri
               JOIN recetas r ON r.id = ri.receta_id
               WHERE ri.ingrediente_id = %s
               ORDER BY r.nombre ASC""",
            (ingrediente_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def eliminar_ingrediente(ingrediente_id: int) -> None:
    """Elimina un ingrediente (y su historial de precios). Falla si está
    siendo usado en alguna receta (esto es intencional: evita romper el
    costeo de un pan existente) — en ese caso, usa
    recetas_que_usan_ingrediente para saber cuáles hay que revisar."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ingredientes WHERE id = %s", (ingrediente_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"No existe un ingrediente con id {ingrediente_id}")

        cursor.execute("DELETE FROM ingredientes WHERE id = %s", (ingrediente_id,))
        conn.commit()
    except ValueError:
        raise
    except Exception as exc:
        conn.rollback()
        raise ValueError(
            "No se puede eliminar: este ingrediente está siendo usado en una o más recetas."
        ) from exc
    finally:
        conn.close()
