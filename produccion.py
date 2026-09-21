"""
produccion.py
--------------
Capacidad de producción diaria y control de sobreventa para el módulo
de Pedidos.

La capacidad se mide en **tiempo** (minutos disponibles por día), no
en unidades, porque cada receta toma un tiempo distinto de preparar
(reusa `tiempo_preparacion_min` / `unidades_por_lote` que ya se
configuran en recetas.py para el costeo de mano de obra).

Este módulo solo informa si un pedido cabe en la capacidad de un día;
no bloquea nada — la decisión de sobrevender o no queda en manos del
usuario (ver pedidos.py y app.py).
"""

from db import conectar


def obtener_configuracion() -> dict:
    """Retorna la configuración actual de capacidad diaria."""
    conn = conectar()
    try:
        fila = conn.execute(
            "SELECT horas_disponibles_dia FROM configuracion_produccion WHERE id = 1"
        ).fetchone()
        return dict(fila)
    finally:
        conn.close()


def actualizar_configuracion(horas_disponibles_dia: float) -> None:
    if horas_disponibles_dia < 0:
        raise ValueError("Las horas disponibles no pueden ser negativas")
    conn = conectar()
    try:
        conn.execute(
            "UPDATE configuracion_produccion SET horas_disponibles_dia = %s WHERE id = 1",
            (horas_disponibles_dia,),
        )
        conn.commit()
    finally:
        conn.close()


def tiempo_comprometido_dia(fecha: str, excluir_pedido_id: int | None = None) -> float:
    """Minutos de preparación ya comprometidos por pedidos no cancelados
    con fecha_entrega = fecha. `excluir_pedido_id` permite recalcular al
    editar un pedido existente sin contarlo dos veces."""
    query = """
        SELECT pi.cantidad, r.tiempo_preparacion_min, r.unidades_por_lote
        FROM pedido_items pi
        JOIN pedidos p ON p.id = pi.pedido_id
        JOIN recetas r ON r.id = pi.receta_id
        WHERE p.fecha_entrega = %s AND p.estado != 'cancelado'
    """
    parametros = [fecha]
    if excluir_pedido_id is not None:
        query += " AND p.id != %s"
        parametros.append(excluir_pedido_id)

    conn = conectar()
    try:
        filas = conn.execute(query, parametros).fetchall()
    finally:
        conn.close()

    total_min = 0.0
    for f in filas:
        if f["unidades_por_lote"] > 0:
            total_min += (f["tiempo_preparacion_min"] / f["unidades_por_lote"]) * f["cantidad"]
    return total_min


def capacidad_dia(fecha: str) -> dict:
    """Retorna el estado de capacidad de un día: minutos disponibles,
    comprometidos y libres, y si ya está sobrevendido."""
    config = obtener_configuracion()
    disponible_min = config["horas_disponibles_dia"] * 60
    comprometido_min = tiempo_comprometido_dia(fecha)
    return {
        "fecha": fecha,
        "disponible_min": round(disponible_min, 1),
        "comprometido_min": round(comprometido_min, 1),
        "libre_min": round(disponible_min - comprometido_min, 1),
        "sobrevendido": comprometido_min > disponible_min,
    }


def verificar_disponibilidad(fecha: str, receta_id: int, cantidad: float,
                              excluir_pedido_id: int | None = None) -> dict:
    """Indica si agregar `cantidad` unidades de una receta a una fecha
    entra dentro de la capacidad disponible ese día. Es solo informativo:
    no impide agregar el ítem, para que quien use el sistema decida si
    sobrevender a propósito (ej. quedarse hasta más tarde ese día)."""
    conn = conectar()
    try:
        receta = conn.execute(
            "SELECT tiempo_preparacion_min, unidades_por_lote FROM recetas WHERE id = %s",
            (receta_id,),
        ).fetchone()
    finally:
        conn.close()
    if receta is None:
        raise ValueError(f"No existe una receta con id {receta_id}")

    tiempo_por_unidad = (
        receta["tiempo_preparacion_min"] / receta["unidades_por_lote"]
        if receta["unidades_por_lote"] > 0 else 0.0
    )
    tiempo_necesario = tiempo_por_unidad * cantidad

    config = obtener_configuracion()
    disponible_min = config["horas_disponibles_dia"] * 60
    comprometido_min = tiempo_comprometido_dia(fecha, excluir_pedido_id=excluir_pedido_id)
    libre_min = disponible_min - comprometido_min

    return {
        "tiempo_necesario_min": round(tiempo_necesario, 1),
        "libre_min": round(libre_min, 1),
        "cabe": tiempo_necesario <= libre_min,
    }
