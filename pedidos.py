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

Flujo de estados (ver README, "Flujo ideal de un pedido"):

    recibido → confirmado → en_produccion → listo → entregado
    (cualquiera de los abiertos puede pasar a cancelado)

El pago es un eje aparte del estado: un pedido puede estar entregado y
todavía sin pagar, o pagado por adelantado antes de entregarse.
`marcar_entregado` y `registrar_pago` son acciones independientes;
`entregar_y_cobrar` hace las dos juntas (el caso de pago al recibir).
Al registrar el pago se genera automáticamente el ingreso en Flujo de
caja (ver caja.py) y, si aplica, el gasto por comisión.
"""

from datetime import date, datetime, timedelta
from db import conectar, cache_lectura
import caja as mod_caja

ESTADOS_VALIDOS = ("recibido", "confirmado", "en_produccion", "listo", "entregado", "cancelado")
# Estados de un pedido "vivo": todavía se puede editar, reagendar o cancelar.
ESTADOS_ABIERTOS = ("recibido", "confirmado", "en_produccion", "listo")
ETIQUETAS_ESTADO = {
    "recibido": "Recibido",
    "confirmado": "Confirmado",
    "en_produccion": "En producción",
    "listo": "Listo",
    "entregado": "Entregado",
    "cancelado": "Cancelado",
}
# Paso siguiente natural de cada estado abierto (para el botón "avanzar").
SIGUIENTE_ESTADO = {
    "recibido": "confirmado",
    "confirmado": "en_produccion",
    "en_produccion": "listo",
    "listo": "entregado",
}

CANALES_VALIDOS = ("whatsapp", "presencial", "instagram", "otro")
ETIQUETAS_CANAL = {
    "whatsapp": "WhatsApp",
    "presencial": "Presencial",
    "instagram": "Instagram",
    "otro": "Otro",
}


def etiqueta_estado(estado: str) -> str:
    return ETIQUETAS_ESTADO.get(estado, estado)


def crear_pedido(cliente_id: int, fecha_entrega: str, notas: str | None = None,
                 canal_origen: str | None = None) -> int:
    """Crea un nuevo pedido (sin ítems todavía) en estado 'recibido' y
    retorna su id. `canal_origen` indica por dónde llegó (WhatsApp,
    presencial, Instagram u otro)."""
    if canal_origen is not None and canal_origen not in CANALES_VALIDOS:
        raise ValueError(f"canal_origen debe ser uno de {CANALES_VALIDOS}")
    fecha_creacion = datetime.now().isoformat(timespec="seconds")
    conn = conectar()
    try:
        cliente = conn.execute("SELECT id FROM clientes WHERE id = %s", (cliente_id,)).fetchone()
        if cliente is None:
            raise ValueError(f"No existe un cliente con id {cliente_id}")

        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO pedidos (cliente_id, fecha_entrega, estado, pagado, notas,
                                    fecha_creacion, canal_origen)
               VALUES (%s, %s, 'recibido', FALSE, %s, %s, %s)
               RETURNING id""",
            (cliente_id, fecha_entrega, notas, fecha_creacion, canal_origen),
        )
        pedido_id = cursor.fetchone()["id"]
        conn.commit()
        return pedido_id
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
            "SELECT precio_venta FROM recetas WHERE id = %s", (receta_id,)
        ).fetchone()
        if receta is None:
            raise ValueError(f"No existe una receta con id {receta_id}")

        conn.execute(
            """INSERT INTO pedido_items (pedido_id, receta_id, cantidad, precio_unitario)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (pedido_id, receta_id)
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
            "DELETE FROM pedido_items WHERE pedido_id = %s AND receta_id = %s",
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
           WHERE p.id = %s""",
        (pedido_id,),
    ).fetchone()
    if fila is None:
        raise ValueError(f"No existe un pedido con id {pedido_id}")
    return dict(fila)


@cache_lectura
def detalle_pedido(pedido_id: int) -> dict:
    """Retorna el pedido con sus ítems y el total calculado."""
    return _detalle_pedido_sin_cache(pedido_id)


def _detalle_pedido_sin_cache(pedido_id: int) -> dict:
    """Igual que `detalle_pedido`, pero leyendo siempre de la base. Para
    validaciones antes de escribir (ej. no cobrar dos veces un pedido),
    donde no conviene arriesgar un dato cacheado."""
    conn = conectar()
    try:
        pedido = _obtener_pedido(conn, pedido_id)
        filas = conn.execute(
            """SELECT r.nombre, pi.receta_id, pi.cantidad, pi.precio_unitario
               FROM pedido_items pi
               JOIN recetas r ON r.id = pi.receta_id
               WHERE pi.pedido_id = %s
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


def generar_mensaje_listo_whatsapp(pedido_id: int) -> str:
    """Genera el aviso de que el pedido ya está listo (paso 4 del flujo),
    para coordinar la entrega."""
    pedido = detalle_pedido(pedido_id)

    lineas = _encabezado_whatsapp(pedido, pedido_id, "¡Tu pedido ya está listo! 🥖✨")
    for item in pedido["items"]:
        lineas.append(f"- {item['cantidad']} x {item['nombre']}")
    lineas.append("")
    lineas.append(f"💰 *Total: {_formato_pesos(pedido['total'])}*")
    lineas.append("")
    lineas.append("Te escribimos para coordinar la entrega. ¡Gracias! 😊")
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


def generar_recordatorio_pago_whatsapp(pedido_id: int) -> str:
    """Genera un recordatorio amable de pago pendiente, listo para copiar
    y pegar (o abrir directo) en WhatsApp."""
    pedido = detalle_pedido(pedido_id)

    lineas = _encabezado_whatsapp(pedido, pedido_id, "Te escribimos para recordarte el pago de tu pedido:")
    for item in pedido["items"]:
        lineas.append(f"- {item['cantidad']} x {item['nombre']} — {_formato_pesos(item['subtotal'])}")
    lineas.append("")
    lineas.append(f"💰 *Total pendiente: {_formato_pesos(pedido['total'])}*")
    lineas.append("")
    lineas.append(
        "💳 Puedes pagar por transferencia, en efectivo o con débito/crédito. "
        "Si prefieres transferir, avísame y te envío los datos."
    )
    lineas.append("")
    lineas.append("Si ya lo pagaste, ignora este mensaje. ¡Muchas gracias! 😊")
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


@cache_lectura
def listar_pedidos(desde: str | None = None, hasta: str | None = None,
                    estado: str | None = None) -> list[dict]:
    """Lista pedidos (con su total ya calculado), por fecha de entrega
    ascendente. Filtros opcionales por rango de fecha_entrega y estado.

    Trae los pedidos y sus ítems en 2 consultas (no 1 por pedido llamando
    a `detalle_pedido`) y reutiliza una sola conexión — con SQLite local
    esto no importaba, pero contra Supabase cada conexión de más suma
    latencia de red real, y esta función se llama seguido (dashboard,
    resúmenes de días, la sección de Pedidos)."""
    condiciones = []
    parametros = []
    if desde:
        condiciones.append("p.fecha_entrega >= %s")
        parametros.append(desde)
    if hasta:
        condiciones.append("p.fecha_entrega <= %s")
        parametros.append(hasta)
    if estado:
        condiciones.append("p.estado = %s")
        parametros.append(estado)
    return _listar_pedidos_con_items(condiciones, parametros, "p.fecha_entrega ASC, p.id ASC")


def _listar_pedidos_con_items(condiciones: list[str], parametros: list, orden: str) -> list[dict]:
    query = """SELECT p.*, c.nombre AS cliente_nombre, c.telefono AS cliente_telefono
               FROM pedidos p
               JOIN clientes c ON c.id = p.cliente_id"""
    if condiciones:
        query += " WHERE " + " AND ".join(condiciones)
    query += " ORDER BY " + orden

    conn = conectar()
    try:
        pedidos = [dict(f) for f in conn.execute(query, parametros).fetchall()]
        ids = [p["id"] for p in pedidos]

        items_por_pedido = {pid: [] for pid in ids}
        if ids:
            filas_items = conn.execute(
                """SELECT pi.pedido_id, r.nombre, pi.receta_id, pi.cantidad, pi.precio_unitario
                   FROM pedido_items pi
                   JOIN recetas r ON r.id = pi.receta_id
                   WHERE pi.pedido_id = ANY(%s)
                   ORDER BY r.nombre ASC""",
                (ids,),
            ).fetchall()
            for f in filas_items:
                subtotal = f["cantidad"] * f["precio_unitario"]
                items_por_pedido[f["pedido_id"]].append({
                    "receta_id": f["receta_id"],
                    "nombre": f["nombre"],
                    "cantidad": f["cantidad"],
                    "precio_unitario": f["precio_unitario"],
                    "subtotal": round(subtotal, 2),
                })
    finally:
        conn.close()

    for p in pedidos:
        p["items"] = items_por_pedido[p["id"]]
        p["total"] = round(sum(i["subtotal"] for i in p["items"]), 2)
        p["pagado"] = bool(p["pagado"])

    return pedidos


@cache_lectura
def obtener_configuracion_cobranza() -> dict:
    conn = conectar()
    try:
        fila = conn.execute(
            "SELECT dias_recordatorio FROM configuracion_cobranza WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    return dict(fila) if fila else {"dias_recordatorio": 3}


def actualizar_dias_recordatorio(dias: int) -> None:
    """A los cuántos días desde la entrega un pedido sin pagar pasa a
    "toca recordar". No es un plazo de pago: solo el umbral del aviso."""
    if dias < 0:
        raise ValueError("Los días no pueden ser negativos")
    conn = conectar()
    try:
        conn.execute(
            """INSERT INTO configuracion_cobranza (id, dias_recordatorio) VALUES (1, %s)
               ON CONFLICT (id) DO UPDATE SET dias_recordatorio = excluded.dias_recordatorio""",
            (int(dias),),
        )
        conn.commit()
    finally:
        conn.close()


@cache_lectura
def listar_por_cobrar() -> list[dict]:
    """Pedidos entregados y todavía sin pagar, del más antiguo al más
    reciente. Cada uno trae `dias_desde_entrega` y `toca_recordar` (si ya
    pasaron los días configurados en `configuracion_cobranza`)."""
    pedidos = _listar_pedidos_con_items(
        ["p.estado = 'entregado'", "NOT p.pagado"], [],
        "COALESCE(p.fecha_entregado, p.fecha_entrega) ASC, p.id ASC",
    )
    umbral = obtener_configuracion_cobranza()["dias_recordatorio"]
    hoy = date.today()
    for p in pedidos:
        entregado = date.fromisoformat(p["fecha_entregado"] or p["fecha_entrega"])
        p["dias_desde_entrega"] = (hoy - entregado).days
        p["toca_recordar"] = p["dias_desde_entrega"] >= umbral
    return pedidos


@cache_lectura
def listar_pedidos_resumen(estado: str | None = None) -> list[dict]:
    """Retorna id, cliente, fecha de entrega y estado de cada pedido, sin
    traer ítems ni calcular el total.

    Pensada para selectores/desplegables (ej. elegir un pedido en un
    formulario). `listar_pedidos()` trae los ítems de cada pedido con JOIN
    a recetas — correcto para las vistas que muestran el detalle, pero de
    más para solo armar una lista de nombres en un `st.selectbox` (cada
    connect/query de más contra Supabase suma latencia real de red)."""
    query = """SELECT p.id, p.fecha_entrega, p.estado, p.pagado, c.nombre AS cliente_nombre
               FROM pedidos p
               JOIN clientes c ON c.id = p.cliente_id"""
    parametros = []
    if estado:
        query += " WHERE p.estado = %s"
        parametros.append(estado)
    query += " ORDER BY p.fecha_entrega ASC, p.id ASC"

    conn = conectar()
    try:
        return [dict(f) for f in conn.execute(query, parametros).fetchall()]
    finally:
        conn.close()


def actualizar_estado(pedido_id: int, nuevo_estado: str) -> None:
    """Mueve un pedido abierto a otro estado abierto (recibido,
    confirmado, en producción, listo) o lo cancela. Se permite volver
    atrás (ej. de 'listo' a 'en producción') para corregir un error.

    Para entregar se usa `marcar_entregado` (o `entregar_y_cobrar`), que
    además registran la fecha de entrega. Un pedido ya entregado o
    cancelado no cambia de estado."""
    if nuevo_estado not in ESTADOS_VALIDOS:
        raise ValueError(f"estado debe ser uno de {ESTADOS_VALIDOS}")
    if nuevo_estado == "entregado":
        raise ValueError("Para entregar un pedido usa 'Marcar entregado'")
    conn = conectar()
    try:
        fila = conn.execute("SELECT estado FROM pedidos WHERE id = %s", (pedido_id,)).fetchone()
        if fila is None:
            raise ValueError(f"No existe un pedido con id {pedido_id}")
        if fila["estado"] not in ESTADOS_ABIERTOS:
            raise ValueError(f"El pedido ya está '{etiqueta_estado(fila['estado'])}', no cambia de estado")
        conn.execute("UPDATE pedidos SET estado = %s WHERE id = %s", (nuevo_estado, pedido_id))
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
        fila = conn.execute("SELECT pagado FROM pedidos WHERE id = %s", (pedido_id,)).fetchone()
        if fila is None:
            raise ValueError(f"No existe un pedido con id {pedido_id}")
        if fila["pagado"]:
            raise ValueError(
                "No se puede eliminar: este pedido ya fue cobrado y generó un ingreso en "
                "Flujo de caja. Anula ese movimiento en Caja primero, o usa 'Cancelar pedido' "
                "si prefieres conservar el registro."
            )

        conn.execute("DELETE FROM pedidos WHERE id = %s", (pedido_id,))
        conn.commit()
    finally:
        conn.close()


def reagendar_pedido(pedido_id: int, nueva_fecha_entrega: str) -> None:
    """Cambia la fecha de entrega de un pedido (lo reagenda) sin tocar su
    estado, ítems ni pagos. No se puede reagendar un pedido ya entregado
    o cancelado."""
    conn = conectar()
    try:
        pedido = conn.execute("SELECT estado FROM pedidos WHERE id = %s", (pedido_id,)).fetchone()
        if pedido is None:
            raise ValueError(f"No existe un pedido con id {pedido_id}")
        if pedido["estado"] in ("entregado", "cancelado"):
            raise ValueError(f"No se puede reagendar un pedido '{pedido['estado']}'")

        conn.execute(
            "UPDATE pedidos SET fecha_entrega = %s WHERE id = %s",
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
               WHERE fecha_entrega = %s AND estado NOT IN ('entregado', 'cancelado')""",
            (fecha_actual,),
        ).fetchall()
        ids = [f["id"] for f in filas]
        if ids:
            conn.execute(
                """UPDATE pedidos SET fecha_entrega = %s
                   WHERE fecha_entrega = %s AND estado NOT IN ('entregado', 'cancelado')""",
                (nueva_fecha_entrega, fecha_actual),
            )
            conn.commit()
        return ids
    finally:
        conn.close()


def _validar_entregable(detalle: dict) -> None:
    if detalle["estado"] == "entregado":
        raise ValueError("Este pedido ya fue marcado como entregado")
    if detalle["estado"] == "cancelado":
        raise ValueError("No se puede entregar un pedido cancelado")
    if not detalle["items"]:
        raise ValueError("El pedido no tiene ítems, no hay nada que entregar")


def _validar_cobrable(detalle: dict, medio_pago: str) -> None:
    if medio_pago not in mod_caja.MEDIOS_VALIDOS:
        raise ValueError(f"medio_pago debe ser uno de {mod_caja.MEDIOS_VALIDOS}")
    if detalle["pagado"]:
        raise ValueError("Este pedido ya está pagado")
    if detalle["estado"] == "cancelado":
        raise ValueError("No se puede cobrar un pedido cancelado")
    if not detalle["items"]:
        raise ValueError("El pedido no tiene ítems, no hay nada que cobrar")


def _registrar_pago_en_conn(conn, detalle: dict, pedido_id: int, medio_pago: str, fecha: str) -> dict:
    """Marca el pedido como pagado y genera el ingreso (y la comisión, si
    aplica) en Caja, usando la conexión/transacción de quien llama."""
    comision = mod_caja.calcular_comision(detalle["total"], medio_pago)
    conn.execute(
        "UPDATE pedidos SET pagado = TRUE, medio_pago = %s, fecha_pago = %s WHERE id = %s",
        (medio_pago, fecha, pedido_id),
    )
    movimiento_ingreso_id = mod_caja.registrar_movimiento(
        "ingreso", detalle["total"], medio_pago,
        categoria="Pedido",
        descripcion=f"Pedido #{pedido_id} - {detalle['cliente_nombre']}",
        fecha=fecha,
        conn=conn,
    )
    movimiento_gasto_comision_id = None
    if comision > 0:
        movimiento_gasto_comision_id = mod_caja.registrar_movimiento(
            "gasto", comision, medio_pago,
            categoria="Comisión Mercado Pago",
            descripcion=f"Comisión {medio_pago} - Pedido #{pedido_id} - {detalle['cliente_nombre']}",
            fecha=fecha,
            conn=conn,
        )
    return {
        "movimiento_ingreso_id": movimiento_ingreso_id,
        "comision": comision,
        "movimiento_gasto_comision_id": movimiento_gasto_comision_id,
    }


def marcar_entregado(pedido_id: int, fecha: str | None = None) -> None:
    """Marca el pedido como entregado (sin tocar el pago). Si todavía no
    está pagado queda "por cobrar" hasta que se use `registrar_pago`."""
    detalle = _detalle_pedido_sin_cache(pedido_id)
    _validar_entregable(detalle)
    fecha = fecha or date.today().isoformat()
    conn = conectar()
    try:
        conn.execute(
            "UPDATE pedidos SET estado = 'entregado', fecha_entregado = %s WHERE id = %s",
            (fecha, pedido_id),
        )
        conn.commit()
    finally:
        conn.close()


def registrar_pago(pedido_id: int, medio_pago: str, fecha: str | None = None) -> dict:
    """Registra el pago de un pedido (entregado o no: puede ser un pago
    por adelantado) y genera automáticamente el ingreso en Flujo de caja
    por el total del pedido.

    Si se cobra con débito o crédito, además registra un gasto aparte por
    la comisión que descuenta el medio de pago electrónico (ver
    caja.calcular_comision y caja.actualizar_configuracion_comisiones),
    para que el ingreso bruto y el costo de la comisión queden visibles
    por separado en Caja.

    Retorna un dict con movimiento_ingreso_id, comision (0 si no aplica)
    y movimiento_gasto_comision_id (None si no aplica).

    No se puede pagar dos veces el mismo pedido (evita duplicar el
    ingreso en caja), ni un pedido cancelado o sin ítems. Marcar pagado +
    movimiento(s) en caja van en una sola transacción: nunca queda un
    pedido pagado sin su ingreso, ni viceversa.
    """
    detalle = _detalle_pedido_sin_cache(pedido_id)
    _validar_cobrable(detalle, medio_pago)
    fecha = fecha or date.today().isoformat()

    conn = conectar()
    try:
        resultado = _registrar_pago_en_conn(conn, detalle, pedido_id, medio_pago, fecha)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return resultado


def entregar_y_cobrar(pedido_id: int, medio_pago: str, fecha: str | None = None) -> dict:
    """Atajo para el caso en que el cliente paga al recibir: marca el
    pedido como entregado y registra el pago (ingreso en Caja + comisión)
    en una sola transacción. Retorna lo mismo que `registrar_pago`."""
    detalle = _detalle_pedido_sin_cache(pedido_id)
    _validar_entregable(detalle)
    _validar_cobrable(detalle, medio_pago)
    fecha = fecha or date.today().isoformat()

    conn = conectar()
    try:
        conn.execute(
            "UPDATE pedidos SET estado = 'entregado', fecha_entregado = %s WHERE id = %s",
            (fecha, pedido_id),
        )
        resultado = _registrar_pago_en_conn(conn, detalle, pedido_id, medio_pago, fecha)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return resultado


@cache_lectura
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
               LIMIT %s""",
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
