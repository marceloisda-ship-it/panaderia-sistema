"""
stock.py
---------
Stock de ingredientes e insumos (bolsas, cajas, etiquetas), por movimientos.

La cantidad actual de un ítem NO se guarda ni se edita a mano: es la suma
de sus movimientos (tabla `movimientos_stock`), todos en la unidad base del
ingrediente (gr, ml o unidad). Tipos de movimiento:

    compra  (+)  entra mercadería; guarda formato y precio pagado
    uso     (-)  se gasta al producir: lo genera solo el pedido al pasar a
                 'en producción' (con su pedido_id) y se devuelve si vuelve atrás
    merma   (-)  se pierde o se echa a perder
    ajuste  (+/-) corrige una diferencia contra un conteo físico

Las compras se ingresan "por su naturaleza", en el formato en que se
compró: una botella de 500 ml, otra de 2000 ml, un saco de 1 kg, un pack
de 100 bolsas. El sistema lo convierte a unidad base y, de paso, deja el
precio por unidad base como precio actual del ingrediente (con su registro
en el historial de precios), que es el que usa el costeo de recetas.

Bolsas: cada modelo (papel, plástica, otra) es un ítem propio de tipo
`insumo`, en unidades. Las cajas, si algún día se usan, se agregan igual.
"""

from datetime import datetime
from db import conectar, cache_lectura

# Cómo se puede expresar el tamaño de un formato de compra, según la unidad
# base del ingrediente, y su equivalente en esa unidad base.
UNIDADES_FORMATO = {
    "gr": {"gr": 1, "kg": 1000},
    "ml": {"ml": 1, "l": 1000},
    "unidad": {"unidad": 1, "docena": 12},
}

ESTADOS_STOCK = ("sin_stock", "queda_poco", "hay")
ETIQUETAS_ESTADO_STOCK = {
    "sin_stock": "🔴 Sin stock",
    "queda_poco": "🟡 Queda poco",
    "hay": "🟢 Hay",
}


def convertir_a_base(cantidad: float, unidad_formato: str, unidad_base: str) -> float:
    """Convierte una cantidad expresada en `unidad_formato` (ej. 1 kg) a la
    unidad base del ingrediente (ej. 1000 gr)."""
    equivalencias = UNIDADES_FORMATO.get(unidad_base)
    if equivalencias is None:
        raise ValueError(f"Unidad base desconocida: {unidad_base}")
    if unidad_formato not in equivalencias:
        raise ValueError(
            f"Un ingrediente en '{unidad_base}' no se puede comprar en '{unidad_formato}' "
            f"(opciones: {', '.join(equivalencias)})"
        )
    return cantidad * equivalencias[unidad_formato]


def estado_stock(stock_actual: float, stock_minimo: float) -> str:
    """'sin_stock' (0 o menos), 'queda_poco' (hasta el mínimo) o 'hay'."""
    if stock_actual <= 0:
        return "sin_stock"
    if stock_minimo > 0 and stock_actual <= stock_minimo:
        return "queda_poco"
    return "hay"


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _obtener_ingrediente(cursor, ingrediente_id: int) -> dict:
    cursor.execute(
        "SELECT id, nombre, unidad_base, precio_actual, proveedor FROM ingredientes WHERE id = %s",
        (ingrediente_id,),
    )
    fila = cursor.fetchone()
    if fila is None:
        raise ValueError(f"No existe un ingrediente con id {ingrediente_id}")
    return dict(fila)


def _stock_de(cursor, ingrediente_id: int) -> float:
    cursor.execute(
        "SELECT COALESCE(SUM(cantidad), 0) AS total FROM movimientos_stock WHERE ingrediente_id = %s",
        (ingrediente_id,),
    )
    return round(float(cursor.fetchone()["total"]), 4)


# --- Escritura ---------------------------------------------------------------

def registrar_compra(ingrediente_id: int, cantidad_formatos: float, tamano_formato: float,
                     unidad_formato: str, precio_por_formato: float,
                     proveedor: str | None = None, nota: str | None = None) -> dict:
    """Registra una compra en el formato en que se hizo.

    Ej. 2 botellas de aceite de 500 ml a $4.500 c/u:
        cantidad_formatos=2, tamano_formato=500, unidad_formato="ml",
        precio_por_formato=4500
    Ej. 1 saco de harina de 25 kg a $20.000:
        cantidad_formatos=1, tamano_formato=25, unidad_formato="kg",
        precio_por_formato=20000

    En una sola transacción: suma el stock, actualiza el precio actual del
    ingrediente (precio por unidad base de esta compra, con registro en el
    historial si cambió) y, si se indica, el proveedor.

    Retorna {"cantidad_base", "precio_por_unidad_base", "stock_actual"}.
    """
    if cantidad_formatos <= 0:
        raise ValueError("La cantidad comprada debe ser mayor que cero")
    if tamano_formato <= 0:
        raise ValueError("El tamaño del formato debe ser mayor que cero")
    if precio_por_formato < 0:
        raise ValueError("El precio no puede ser negativo")

    fecha = _ahora()
    conn = conectar()
    try:
        cursor = conn.cursor()
        ing = _obtener_ingrediente(cursor, ingrediente_id)
        base_por_formato = convertir_a_base(tamano_formato, unidad_formato, ing["unidad_base"])
        cantidad_base = cantidad_formatos * base_por_formato
        precio_unitario = precio_por_formato / base_por_formato
        precio_total = precio_por_formato * cantidad_formatos
        formato = f"{cantidad_formatos:g} × {tamano_formato:g} {unidad_formato}"

        cursor.execute(
            """INSERT INTO movimientos_stock
                   (ingrediente_id, tipo, cantidad, formato, precio_total, nota, fecha)
               VALUES (%s, 'compra', %s, %s, %s, %s, %s)""",
            (ingrediente_id, cantidad_base, formato, precio_total, nota or None, fecha),
        )

        # El costeo usa el precio de la última compra.
        if abs(precio_unitario - float(ing["precio_actual"])) > 1e-9:
            cursor.execute(
                "UPDATE ingredientes SET precio_actual = %s, fecha_actualizacion = %s WHERE id = %s",
                (precio_unitario, fecha, ingrediente_id),
            )
            cursor.execute(
                """INSERT INTO historial_precios_ingredientes (ingrediente_id, precio, fecha)
                   VALUES (%s, %s, %s)""",
                (ingrediente_id, precio_unitario, fecha),
            )
        if proveedor and proveedor != ing["proveedor"]:
            cursor.execute(
                "UPDATE ingredientes SET proveedor = %s WHERE id = %s", (proveedor, ingrediente_id)
            )

        stock = _stock_de(cursor, ingrediente_id)
        conn.commit()
        return {
            "cantidad_base": cantidad_base,
            "precio_por_unidad_base": precio_unitario,
            "stock_actual": stock,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def registrar_merma(ingrediente_id: int, cantidad: float, nota: str | None = None) -> None:
    """Descuenta `cantidad` (en unidad base, positiva) por pérdida o deterioro."""
    if cantidad <= 0:
        raise ValueError("La cantidad de merma debe ser mayor que cero")
    _registrar_simple(ingrediente_id, "merma", -cantidad, nota)


def registrar_conteo(ingrediente_id: int, cantidad_real: float, nota: str | None = None) -> float:
    """Ajusta el stock para que coincida con un conteo físico: registra un
    movimiento `ajuste` por la diferencia. Retorna la diferencia aplicada
    (0 si ya coincidía, y en ese caso no registra nada). Sirve también para
    cargar el stock inicial."""
    if cantidad_real < 0:
        raise ValueError("La cantidad contada no puede ser negativa")
    conn = conectar()
    try:
        cursor = conn.cursor()
        _obtener_ingrediente(cursor, ingrediente_id)
        diferencia = round(cantidad_real - _stock_de(cursor, ingrediente_id), 4)
        if diferencia != 0:
            cursor.execute(
                """INSERT INTO movimientos_stock (ingrediente_id, tipo, cantidad, nota, fecha)
                   VALUES (%s, 'ajuste', %s, %s, %s)""",
                (ingrediente_id, diferencia, nota or "Conteo físico", _ahora()),
            )
            conn.commit()
        return diferencia
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _registrar_simple(ingrediente_id: int, tipo: str, cantidad: float, nota: str | None) -> None:
    conn = conectar()
    try:
        cursor = conn.cursor()
        _obtener_ingrediente(cursor, ingrediente_id)
        cursor.execute(
            """INSERT INTO movimientos_stock (ingrediente_id, tipo, cantidad, nota, fecha)
               VALUES (%s, %s, %s, %s, %s)""",
            (ingrediente_id, tipo, cantidad, nota or None, _ahora()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def configurar_item(ingrediente_id: int, tipo: str, stock_minimo: float) -> None:
    """Define si es ingrediente o insumo y su stock mínimo (en unidad base)."""
    if tipo not in ("ingrediente", "insumo"):
        raise ValueError("tipo debe ser 'ingrediente' o 'insumo'")
    if stock_minimo < 0:
        raise ValueError("El stock mínimo no puede ser negativo")
    conn = conectar()
    try:
        cursor = conn.cursor()
        _obtener_ingrediente(cursor, ingrediente_id)
        cursor.execute(
            "UPDATE ingredientes SET tipo = %s, stock_minimo = %s WHERE id = %s",
            (tipo, stock_minimo, ingrediente_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Pedidos: consumo de stock ---------------------------------------------------
# Las recetas guardan la cantidad de cada ingrediente por unidad (un pan), igual
# que el costeo; la bolsa de la receta cuenta 1 por unidad. Consumo de un
# pedido = cantidad del ítem × (ingredientes de la receta + su bolsa).
#
# Las funciones `*_en_cursor` reciben el cursor de la transacción del caller
# (pedidos.py), para que el cambio de estado y el movimiento de stock se
# confirmen juntos o no se confirmen.

def _consumo_pedido(cursor, pedido_id: int) -> dict[int, float]:
    """{ingrediente_id: cantidad total en unidad base} que necesita el pedido."""
    cursor.execute(
        """SELECT ri.ingrediente_id, SUM(ri.cantidad * pi.cantidad) AS total
           FROM pedido_items pi
           JOIN receta_ingredientes ri ON ri.receta_id = pi.receta_id
           WHERE pi.pedido_id = %s
           GROUP BY ri.ingrediente_id""",
        (pedido_id,),
    )
    consumo = {f["ingrediente_id"]: float(f["total"]) for f in cursor.fetchall()}
    cursor.execute(
        """SELECT r.empaque_ingrediente_id AS ingrediente_id, SUM(pi.cantidad) AS total
           FROM pedido_items pi
           JOIN recetas r ON r.id = pi.receta_id
           WHERE pi.pedido_id = %s AND r.empaque_ingrediente_id IS NOT NULL
           GROUP BY r.empaque_ingrediente_id""",
        (pedido_id,),
    )
    for f in cursor.fetchall():
        consumo[f["ingrediente_id"]] = consumo.get(f["ingrediente_id"], 0.0) + float(f["total"])
    return consumo


def _uso_neto_pedido(cursor, pedido_id: int) -> dict[int, float]:
    """{ingrediente_id: cantidad neta ya descontada (positiva)} de este pedido."""
    cursor.execute(
        """SELECT ingrediente_id, -SUM(cantidad) AS descontado
           FROM movimientos_stock WHERE pedido_id = %s AND tipo = 'uso'
           GROUP BY ingrediente_id""",
        (pedido_id,),
    )
    return {f["ingrediente_id"]: round(float(f["descontado"]), 4)
            for f in cursor.fetchall() if round(float(f["descontado"]), 4) != 0}


def faltantes_pedido_en_cursor(cursor, pedido_id: int) -> list[dict]:
    """Ingredientes cuyo stock no alcanza para producir el pedido, contra el
    stock de hoy. Si el pedido ya tiene su stock descontado, no falta nada.
    Cada fila: nombre, unidad_base, necesario, disponible, falta."""
    if _uso_neto_pedido(cursor, pedido_id):
        return []
    faltantes = []
    for ing_id, necesario in _consumo_pedido(cursor, pedido_id).items():
        ing = _obtener_ingrediente(cursor, ing_id)
        disponible = _stock_de(cursor, ing_id)
        if disponible < necesario - 1e-9:
            faltantes.append({
                "nombre": ing["nombre"],
                "unidad_base": ing["unidad_base"],
                "necesario": round(necesario, 4),
                "disponible": max(disponible, 0.0),
                "falta": round(necesario - max(disponible, 0.0), 4),
            })
    return sorted(faltantes, key=lambda f: f["nombre"])


def descontar_pedido_en_cursor(cursor, pedido_id: int, fecha: str | None = None) -> bool:
    """Descuenta del stock lo que consume el pedido. Una sola vez: si ya está
    descontado, no hace nada. Permite stock negativo (el stock del sistema
    puede estar desactualizado y no debe frenar la producción; el aviso de
    faltantes ya se dio). Retorna True si descontó."""
    if _uso_neto_pedido(cursor, pedido_id):
        return False
    consumo = {k: v for k, v in _consumo_pedido(cursor, pedido_id).items() if v > 0}
    if not consumo:
        return False
    fecha = fecha or _ahora()
    for ing_id, cantidad in consumo.items():
        cursor.execute(
            """INSERT INTO movimientos_stock (ingrediente_id, tipo, cantidad, nota, fecha, pedido_id)
               VALUES (%s, 'uso', %s, %s, %s, %s)""",
            (ing_id, -cantidad, f"Pedido #{pedido_id}", fecha, pedido_id),
        )
    return True


def revertir_pedido_en_cursor(cursor, pedido_id: int, fecha: str | None = None) -> bool:
    """Devuelve al stock lo descontado por el pedido (ej. volvió de 'en
    producción' a 'confirmado'). Deja un movimiento compensatorio, no borra
    el original. Retorna True si devolvió algo."""
    descontado = _uso_neto_pedido(cursor, pedido_id)
    fecha = fecha or _ahora()
    for ing_id, cantidad in descontado.items():
        cursor.execute(
            """INSERT INTO movimientos_stock (ingrediente_id, tipo, cantidad, nota, fecha, pedido_id)
               VALUES (%s, 'uso', %s, %s, %s, %s)""",
            (ing_id, cantidad, f"Devolución pedido #{pedido_id}", fecha, pedido_id),
        )
    return bool(descontado)


@cache_lectura
def faltantes_pedido(pedido_id: int) -> list[dict]:
    """Versión de lectura (para mostrar en pantalla) de
    `faltantes_pedido_en_cursor`."""
    conn = conectar()
    try:
        return faltantes_pedido_en_cursor(conn.cursor(), pedido_id)
    finally:
        conn.close()


# --- Lectura -------------------------------------------------------------------

@cache_lectura
def listar_stock() -> list[dict]:
    """Todos los ítems con su `stock_actual`, `estado` (sin_stock /
    queda_poco / hay) y `valor_stock` (stock × precio actual)."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT i.id, i.nombre, i.tipo, i.unidad_base, i.precio_actual, i.proveedor,
                      i.stock_minimo, COALESCE(SUM(m.cantidad), 0) AS stock_actual
               FROM ingredientes i
               LEFT JOIN movimientos_stock m ON m.ingrediente_id = i.id
               GROUP BY i.id
               ORDER BY i.nombre ASC"""
        ).fetchall()
    finally:
        conn.close()
    resultado = []
    for f in filas:
        d = dict(f)
        d["stock_actual"] = round(float(d["stock_actual"]), 4)
        d["estado"] = estado_stock(d["stock_actual"], d["stock_minimo"])
        d["valor_stock"] = max(d["stock_actual"], 0) * d["precio_actual"]
        resultado.append(d)
    return resultado


@cache_lectura
def listar_por_reponer() -> list[dict]:
    """Ítems sin stock o con poco, con la cantidad que falta para llegar al
    mínimo (`faltante`) y su costo estimado según el último precio. Solo
    cuenta ítems con mínimo definido (> 0): sin mínimo no hay cómo saber
    cuándo reponer."""
    por_reponer = []
    for d in listar_stock():
        if d["stock_minimo"] > 0 and d["estado"] in ("sin_stock", "queda_poco"):
            d["faltante"] = round(d["stock_minimo"] - max(d["stock_actual"], 0), 4)
            d["costo_estimado"] = d["faltante"] * d["precio_actual"]
            por_reponer.append(d)
    return por_reponer


@cache_lectura
def listar_movimientos(ingrediente_id: int, limite: int = 100) -> list[dict]:
    """Movimientos de un ítem, del más reciente al más antiguo."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT id, fecha, tipo, cantidad, formato, precio_total, nota
               FROM movimientos_stock WHERE ingrediente_id = %s
               ORDER BY fecha DESC, id DESC LIMIT %s""",
            (ingrediente_id, limite),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()
