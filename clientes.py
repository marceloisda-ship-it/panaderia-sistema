"""
clientes.py
------------
Ficha de clientes: alta, datos de contacto, e inteligencia de negocio
derivada de sus pedidos (total gastado, cantidad de pedidos, receta
favorita, ranking de clientes que más compran).

No duplica datos de pedidos: todo el historial se calcula al vuelo
haciendo join contra `pedidos` y `pedido_items`.
"""

from datetime import datetime
from db import conectar


def crear_cliente(nombre: str, telefono: str | None = None,
                   direccion: str | None = None, notas: str | None = None) -> int:
    if not nombre.strip():
        raise ValueError("El nombre no puede estar vacío")

    fecha_creacion = datetime.now().isoformat(timespec="seconds")
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO clientes (nombre, telefono, direccion, notas, fecha_creacion)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id""",
            (nombre.strip(), telefono or None, direccion or None, notas or None, fecha_creacion),
        )
        cliente_id = cursor.fetchone()["id"]
        conn.commit()
        return cliente_id
    finally:
        conn.close()


def actualizar_cliente(cliente_id: int, nombre: str, telefono: str | None = None,
                        direccion: str | None = None, notas: str | None = None) -> None:
    if not nombre.strip():
        raise ValueError("El nombre no puede estar vacío")
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM clientes WHERE id = %s", (cliente_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"No existe un cliente con id {cliente_id}")
        cursor.execute(
            """UPDATE clientes SET nombre = %s, telefono = %s, direccion = %s, notas = %s
               WHERE id = %s""",
            (nombre.strip(), telefono or None, direccion or None, notas or None, cliente_id),
        )
        conn.commit()
    finally:
        conn.close()


def listar_clientes() -> list[dict]:
    conn = conectar()
    try:
        filas = conn.execute("SELECT * FROM clientes ORDER BY nombre ASC").fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def _obtener_cliente(conn, cliente_id: int) -> dict:
    fila = conn.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,)).fetchone()
    if fila is None:
        raise ValueError(f"No existe un cliente con id {cliente_id}")
    return dict(fila)


def historial_cliente(cliente_id: int) -> dict:
    """Ficha completa de un cliente: sus datos, su historial de pedidos
    y métricas simples (cantidad de pedidos, total gastado, receta
    favorita)."""
    conn = conectar()
    try:
        cliente = _obtener_cliente(conn, cliente_id)

        pedidos_filas = conn.execute(
            """SELECT p.id, p.fecha_entrega, p.estado, p.pagado,
                      COALESCE(SUM(pi.cantidad * pi.precio_unitario), 0) AS total
               FROM pedidos p
               LEFT JOIN pedido_items pi ON pi.pedido_id = p.id
               WHERE p.cliente_id = %s
               GROUP BY p.id
               ORDER BY p.fecha_entrega DESC""",
            (cliente_id,),
        ).fetchall()

        receta_favorita = conn.execute(
            """SELECT r.nombre, SUM(pi.cantidad) AS unidades
               FROM pedido_items pi
               JOIN pedidos p ON p.id = pi.pedido_id
               JOIN recetas r ON r.id = pi.receta_id
               WHERE p.cliente_id = %s AND p.estado != 'cancelado'
               GROUP BY r.id
               ORDER BY unidades DESC
               LIMIT 1""",
            (cliente_id,),
        ).fetchone()
    finally:
        conn.close()

    pedidos_list = []
    total_gastado = 0.0
    for f in pedidos_filas:
        p = dict(f)
        p["pagado"] = bool(p["pagado"])
        p["total"] = round(p["total"], 2)
        if p["pagado"]:
            total_gastado += p["total"]
        pedidos_list.append(p)

    cliente["pedidos"] = pedidos_list
    cliente["cantidad_pedidos"] = len(pedidos_list)
    cliente["total_gastado"] = round(total_gastado, 2)
    cliente["receta_favorita"] = receta_favorita["nombre"] if receta_favorita else None
    return cliente


def reporte_top_clientes(limite: int = 10) -> list[dict]:
    """Ranking de clientes por total gastado (solo pedidos pagados y no
    cancelados). Responde "quién compra más"."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT c.id, c.nombre, c.telefono,
                      COUNT(DISTINCT p.id) AS cantidad_pedidos,
                      COALESCE(SUM(pi.cantidad * pi.precio_unitario), 0) AS total_gastado
               FROM clientes c
               JOIN pedidos p ON p.cliente_id = c.id AND p.pagado = TRUE AND p.estado != 'cancelado'
               JOIN pedido_items pi ON pi.pedido_id = p.id
               GROUP BY c.id
               ORDER BY total_gastado DESC
               LIMIT %s""",
            (limite,),
        ).fetchall()
    finally:
        conn.close()

    resultado = [dict(f) for f in filas]
    for r in resultado:
        r["total_gastado"] = round(r["total_gastado"], 2)
    return resultado
