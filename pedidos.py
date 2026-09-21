"""
pedidos.py
-----------
Gestión de pedidos de clientes: ítems (receta + cantidad), estado,
fecha de entrega y su conexión con el flujo de caja.

Un pedido puede incluir varias recetas distintas. El precio de cada
ítem queda "congelado" al momento de agregarlo (snapshot del
precio_venta de la receta en ese instante), para que un cambio de
precio posterior no altere pedidos ya tomados.

Cada pedido pertenece a un cliente de la ficha de clientes (ver
clientes.py) — ya no se guarda como texto libre.

Al marcar un pedido como entregado y pagado (`entregar_y_cobrar`), se
genera automáticamente el ingreso correspondiente en Flujo de caja
(ver caja.py) con el medio de pago indicado, para no tener que
registrarlo dos veces.
"""

from datetime import date, datetime, timedelta
from db import conectar
import caja as mod_caja

ESTADOS_VALIDOS = ("pendiente", "confirmado", "entregado", "cancelado")


def crear_pedido(cliente_id: int, fecha_entrega: str, notas: str | None = None) -> int:
    """Crea un nuevo pedido (sin ítems todavía) y retorna su id."""
    fecha_creacion = datetime.now().isoformat(timespec="seconds")
    conn = conectar()
    try:
        cliente = conn.execute("SELECT id FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if cliente is None:
            raise ValueError(f"No existe un cliente con id {cliente_id}")

        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO pedidos (cliente_id, fecha_entrega, estado, pagado, notas, fecha_creacion)
               VALUES (?, ?, 'pendiente', 0, ?, ?)""",
            (cliente_id, fecha_entrega, notas, fecha_creacion),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def agregar_item_pedido(pedido_id: int, receta_id: int, cantidad: int) -> None:
    """Agrega (o actualiza la cantidad de) un ítem al pedido. El precio
    unitario se toma del precio_venta actual de la receta y queda fijo
    para este pedido desde este momento."""
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a 0")

    conn = conectar()
    try:
        receta = conn.execute(
            "SELECT precio_venta FROM recetas WHERE id = ?", (receta_id,)
        ).fetchone()
        if receta is None:
            raise ValueError(f"No existe una receta con id {receta_id}")

        conn.execute(
            """INSERT INTO pedido_items (pedido_id, receta_id, cantidad, precio_unitario)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(pedido_id, receta_id)
               DO UPDATE SET cantidad = excluded.cantidad""",
            (pedido_id, receta_id, cantidad, receta["precio_venta"]),
        )
        conn.commit()
    finally:
        conn.close()


def quitar_item_pedido(pedido_id: int, receta_id: int) -> None:
    conn = conectar()
    try:
        conn.execute(
            "DELETE FROM pedido_items WHERE pedido_id = ? AND receta_id = ?",
            (pedido_id, receta_id),
        )
        conn.commit()
    finally:
        conn.close()


def _obtener_pedido(conn, pedido_id: int) -> dict:
    fila = conn.execute(
        """SELECT p.*, c.nombre AS cliente_nombre, c.telefono AS cliente_telefono
           FROM pedidos p
           JOIN clientes c ON c.id = p.cliente_id
           WHERE p.id = ?""",
        (pedido_id,),
    ).fetchone()
    if fila is None:
        raise ValueError(f"No existe un pedido con id {pedido_id}")
    return dict(fila)


def detalle_pedido(pedido_id: int) -> dict:
    """Retorna el pedido con sus ítems y el total calculado."""
    conn = conectar()
    try:
        pedido = _obtener_pedido(conn, pedido_id)
        filas = conn.execute(
            """SELECT r.nombre, pi.receta_id, pi.cantidad, pi.precio_unitario
               FROM pedido_items pi
               JOIN recetas r ON r.id = pi.receta_id
               WHERE pi.pedido_id = ?
               ORDER BY r.nombre ASC""",
            (pedido_id,),
        ).fetchall()
    finally:
        conn.close()

    items = []
    total = 0.0
    for f in filas:
        subtotal = f["cantidad"] * f["precio_unitario"]
        total += subtotal
        items.append({
            "receta_id": f["receta_id"],
            "nombre": f["nombre"],
            "cantidad": f["cantidad"],
            "precio_unitario": f["precio_unitario"],
            "subtotal": round(subtotal, 2),
        })

    pedido["items"] = items
    pedido["total"] = round(total, 2)
    pedido["pagado"] = bool(pedido["pagado"])
    return pedido


def _formato_pesos(monto: float) -> str:
    return f"${monto:,.0f}".replace(",", ".")


def _encabezado_whatsapp(pedido: dict, pedido_id: int, intro: str) -> list[str]:
    fecha = datetime.strptime(pedido["fecha_entrega"], "%Y-%m-%d").strftime("%d-%m-%Y")
    primer_nombre = pedido["cliente_nombre"].split()[0]
    return [
        f"👋 ¡Hola {primer_nombre}! Somos *La PanaderIA* 🥖",
        "",
        intro,
        "",
        f"🛒 *Pedido #{pedido_id}*",
        f"📅 Entrega: {fecha}",
        "",
    ]


def generar_resumen_whatsapp(pedido_id: int) -> str:
    """Genera un mensaje de confirmación del pedido (ítems, total, fecha de
    entrega), con tono cercano y listo para copiar y pegar en WhatsApp."""
    pedido = detalle_pedido(pedido_id)

    lineas = _encabezado_whatsapp(pedido, pedido_id, "Te escribimos para confirmar tu pedido:")
    for item in pedido["items"]:
        lineas.append(f"- {item['cantidad']} x {item['nombre']} — {_formato_pesos(item['subtotal'])}")
    lineas.append("")
    lineas.append(f"💰 *Total: {_formato_pesos(pedido['total'])}*")
    if pedido["notas"]:
        lineas.append("")
        lineas.append(f"📝 Notas: {pedido['notas']}")
    lineas.append("")
    lineas.append("¿Confirmamos así? ¡Gracias por tu compra! 😊")
    return "\n".join(lineas)


def generar_mensaje_cobro_whatsapp(pedido_id: int) -> str:
    """Genera un mensaje de aviso de entrega con el monto a pagar al
    recibir el pedido, con tono cercano y listo para copiar y pegar en
    WhatsApp. Pensado para cuando el cobro se hace al momento de entregar."""
    pedido = detalle_pedido(pedido_id)

    lineas = _encabezado_whatsapp(pedido, pedido_id, "¡Hoy te llevamos tu pedido! 🚴")
    for item in pedido["items"]:
        lineas.append(f"- {item['cantidad']} x {item['nombre']} — {_formato_pesos(item['subtotal'])}")
    lineas.append("")
    lineas.append(f"💰 *Total a pagar al recibir: {_formato_pesos(pedido['total'])}*")
    lineas.append("")
    lineas.append(
        "¿Qué medio de pago prefieres tener listo (efectivo, transferencia, "
        "débito o crédito)? ¡Nos vemos pronto! 😊"
    )
    return "\n".join(lineas)


def generar_mensaje_datos_transferencia_whatsapp(nombre: str, rut: str, tipo_cuenta: str,
                                                  numero_cuenta: str, email: str) -> str:
    """Genera el mensaje con los datos bancarios para transferencia, listo
    para copiar y pegar cuando el cliente indique que pagará así. No va
    ligado a un pedido en particular.

    Los datos bancarios no se guardan en este módulo (ver .streamlit/secrets.toml,
    nunca versionado) — quien llama a esta función es responsable de leerlos
    desde la configuración y pasarlos como argumento."""
    return "\n".join([
        "💳 ¡Perfecto! Estos son mis datos para transferir:",
        "",
        nombre,
        f"RUT: {rut}",
        tipo_cuenta,
        f"N° de cuenta: {numero_cuenta}",
        email,
        "",
        "Apenas hagas la transferencia me avisas para confirmar 😊",
    ])


def listar_pedidos(desde: str | None = None, hasta: str | None = None,
                    estado: str | None = None) -> list[dict]:
    """Lista pedidos (con su total ya calculado), por fecha de entrega
    ascendente. Filtros opcionales por rango de fecha_entrega y estado."""
    condiciones = []
    parametros = []
    if desde:
        condiciones.append("fecha_entrega >= ?")
        parametros.append(desde)
    if hasta:
        condiciones.append("fecha_entrega <= ?")
        parametros.append(hasta)
    if estado:
        condiciones.append("estado = ?")
        parametros.append(estado)

    query = "SELECT id FROM pedidos"
    if condiciones:
        query += " WHERE " + " AND ".join(condiciones)
    query += " ORDER BY fecha_entrega ASC, id ASC"

    conn = conectar()
    try:
        ids = [f["id"] for f in conn.execute(query, parametros).fetchall()]
    finally:
        conn.close()

    return [detalle_pedido(pid) for pid in ids]


def actualizar_estado(pedido_id: int, nuevo_estado: str) -> None:
    if nuevo_estado not in ESTADOS_VALIDOS:
        raise ValueError(f"estado debe ser uno de {ESTADOS_VALIDOS}")
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM pedidos WHERE id = ?", (pedido_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"No existe un pedido con id {pedido_id}")
        cursor.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (nuevo_estado, pedido_id))
        conn.commit()
    finally:
        conn.close()


def cancelar_pedido(pedido_id: int) -> None:
    actualizar_estado(pedido_id, "cancelado")


def eliminar_pedido(pedido_id: int) -> None:
    """Elimina un pedido y sus ítems por completo (a diferencia de
    cancelar_pedido, que solo cambia el estado y deja el registro).
    Pensado para pedidos mal tomados o de prueba.

    No se puede eliminar un pedido ya cobrado (pagado = 1), porque generó
    un ingreso en Flujo de caja: primero hay que anular ese movimiento en
    Caja, o usar cancelar_pedido si se prefiere conservar el registro."""
    conn = conectar()
    try:
        fila = conn.execute("SELECT pagado FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if fila is None:
            raise ValueError(f"No existe un pedido con id {pedido_id}")
        if fila["pagado"]:
            raise ValueError(
                "No se puede eliminar: este pedido ya fue cobrado y generó un ingreso en "
                "Flujo de caja. Anula ese movimiento en Caja primero, o usa 'Cancelar pedido' "
                "si prefieres conservar el registro."
            )

        conn.execute("DELETE FROM pedidos WHERE id = ?", (pedido_id,))
        conn.commit()
    finally:
        conn.close()


def reagendar_pedido(pedido_id: int, nueva_fecha_entrega: str) -> None:
    """Cambia la fecha de entrega de un pedido (lo reagenda) sin tocar su
    estado, ítems ni pagos. No se puede reagendar un pedido ya entregado
    o cancelado."""
    conn = conectar()
    try:
        pedido = conn.execute("SELECT estado FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if pedido is None:
            raise ValueError(f"No existe un pedido con id {pedido_id}")
        if pedido["estado"] in ("entregado", "cancelado"):
            raise ValueError(f"No se puede reagendar un pedido '{pedido['estado']}'")

        conn.execute(
            "UPDATE pedidos SET fecha_entrega = ? WHERE id = ?",
            (nueva_fecha_entrega, pedido_id),
        )
        conn.commit()
    finally:
        conn.close()


def reagendar_pedidos_por_fecha(fecha_actual: str, nueva_fecha_entrega: str) -> list[int]:
    """Reagenda de una sola vez todos los pedidos con fecha_entrega =
    fecha_actual (que no estén entregados ni cancelados) a la nueva
    fecha. Retorna los ids de los pedidos reagendados. Pensado para el
    caso de fuerza mayor en que hay que mover varios pedidos del mismo
    día a otra fecha."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT id FROM pedidos
               WHERE fecha_entrega = ? AND estado NOT IN ('entregado', 'cancelado')""",
            (fecha_actual,),
        ).fetchall()
        ids = [f["id"] for f in filas]
        if ids:
            conn.execute(
                """UPDATE pedidos SET fecha_entrega = ?
                   WHERE fecha_entrega = ? AND estado NOT IN ('entregado', 'cancelado')""",
                (nueva_fecha_entrega, fecha_actual),
            )
            conn.commit()
        return ids
    finally:
        conn.close()


def entregar_y_cobrar(pedido_id: int, medio_pago: str, fecha: str | None = None) -> dict:
    """Marca el pedido como entregado y pagado, y genera automáticamente
    el ingreso correspondiente en Flujo de caja por el total del pedido.

    Si se cobra con débito o crédito, además registra un gasto aparte por
    la comisión que descuenta el medio de pago electrónico (ver
    caja.calcular_comision y caja.actualizar_configuracion_comisiones),
    para que el ingreso bruto y el costo de la comisión queden visibles
    por separado en Caja.

    Retorna un dict con movimiento_ingreso_id, comision (0 si no aplica)
    y movimiento_gasto_comision_id (None si no aplica).

    No se puede llamar dos veces sobre el mismo pedido (evita duplicar
    el ingreso en caja), ni sobre un pedido cancelado o sin ítems.
    """
    if medio_pago not in mod_caja.MEDIOS_VALIDOS:
        raise ValueError(f"medio_pago debe ser uno de {mod_caja.MEDIOS_VALIDOS}")

    detalle = detalle_pedido(pedido_id)
    if detalle["estado"] == "entregado" and detalle["pagado"]:
        raise ValueError("Este pedido ya fue marcado como entregado y pagado")
    if detalle["estado"] == "cancelado":
        raise ValueError("No se puede cobrar un pedido cancelado")
    if not detalle["items"]:
        raise ValueError("El pedido no tiene ítems, no hay nada que cobrar")

    fecha = fecha or date.today().isoformat()

    conn = conectar()
    try:
        conn.execute(
            "UPDATE pedidos SET estado = 'entregado', pagado = 1, medio_pago = ? WHERE id = ?",
            (medio_pago, pedido_id),
        )
        conn.commit()
    finally:
        conn.close()

    movimiento_ingreso_id = mod_caja.registrar_movimiento(
        "ingreso", detalle["total"], medio_pago,
        categoria="Pedido",
        descripcion=f"Pedido #{pedido_id} - {detalle['cliente_nombre']}",
        fecha=fecha,
    )

    comision = mod_caja.calcular_comision(detalle["total"], medio_pago)
    movimiento_gasto_comision_id = None
    if comision > 0:
        movimiento_gasto_comision_id = mod_caja.registrar_movimiento(
            "gasto", comision, medio_pago,
            categoria="Comisión Mercado Pago",
            descripcion=f"Comisión {medio_pago} - Pedido #{pedido_id} - {detalle['cliente_nombre']}",
            fecha=fecha,
        )

    return {
        "movimiento_ingreso_id": movimiento_ingreso_id,
        "comision": comision,
        "movimiento_gasto_comision_id": movimiento_gasto_comision_id,
    }


def reporte_productos_populares(limite: int = 10) -> list[dict]:
    """Ranking de recetas por unidades pedidas (pedidos no cancelados).
    Responde "qué pan se pide más"."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT r.nombre, SUM(pi.cantidad) AS unidades_pedidas,
                      COALESCE(SUM(pi.cantidad * pi.precio_unitario), 0) AS monto_total
               FROM pedido_items pi
               JOIN pedidos p ON p.id = pi.pedido_id
               JOIN recetas r ON r.id = pi.receta_id
               WHERE p.estado != 'cancelado'
               GROUP BY r.id
               ORDER BY unidades_pedidas DESC
               LIMIT ?""",
            (limite,),
        ).fetchall()
    finally:
        conn.close()

    resultado = [dict(f) for f in filas]
    for r in resultado:
        r["monto_total"] = round(r["monto_total"], 2)
    return resultado


def resumen_dia(fecha: str) -> dict:
    """Resumen de producción para una fecha de entrega: los pedidos de
    ese día (no cancelados) y el total de unidades a preparar por
    receta, para planificar la jornada de un vistazo."""
    pedidos_dia = [p for p in listar_pedidos(desde=fecha, hasta=fecha) if p["estado"] != "cancelado"]

    agregados = {}
    for p in pedidos_dia:
        for item in p["items"]:
            agregados[item["nombre"]] = agregados.get(item["nombre"], 0) + item["cantidad"]

    items_agregados = [
        {"receta": nombre, "cantidad_total": cantidad}
        for nombre, cantidad in sorted(agregados.items(), key=lambda kv: -kv[1])
    ]

    return {
        "fecha": fecha,
        "pedidos": pedidos_dia,
        "cantidad_pedidos": len(pedidos_dia),
        "total_a_cobrar": round(sum(p["total"] for p in pedidos_dia), 2),
        "items_agregados": items_agregados,
    }


def resumen_proximos_dias(dias: int = 14) -> list[dict]:
    """Resumen día a día de los próximos `dias` días (desde hoy): cantidad
    de pedidos, unidades totales y monto a cobrar. Solo cuenta pedidos no
    cancelados. Útil para ver de un vistazo qué días vienen más cargados."""
    hoy = date.today()
    hasta = (hoy + timedelta(days=dias - 1)).isoformat()
    pedidos_rango = [
        p for p in listar_pedidos(desde=hoy.isoformat(), hasta=hasta) if p["estado"] != "cancelado"
    ]

    por_fecha = {}
    for p in pedidos_rango:
        f = p["fecha_entrega"]
        acumulado = por_fecha.setdefault(
            f, {"fecha": f, "cantidad_pedidos": 0, "unidades_totales": 0, "total_a_cobrar": 0.0}
        )
        acumulado["cantidad_pedidos"] += 1
        acumulado["unidades_totales"] += sum(i["cantidad"] for i in p["items"])
        acumulado["total_a_cobrar"] += p["total"]

    resultado = []
    for i in range(dias):
        f = (hoy + timedelta(days=i)).isoformat()
        dia = por_fecha.get(f, {"fecha": f, "cantidad_pedidos": 0, "unidades_totales": 0, "total_a_cobrar": 0.0})
        dia["total_a_cobrar"] = round(dia["total_a_cobrar"], 2)
        resultado.append(dia)
    return resultado
