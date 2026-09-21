"""
caja.py
--------
Gestión de flujo de caja: registro de ingresos y gastos, diferenciando
medio de pago (efectivo, débito, transferencia), y reportes por período.

Concepto clave:
    saldo_periodo = total_ingresos - total_gastos (dentro de un rango de fechas)

Cada movimiento queda con su medio de pago para poder responder preguntas
como "¿cuánta plata tengo en efectivo?" o "¿cuánto entró por transferencia
este mes?".
"""

from datetime import date
from db import conectar

TIPOS_VALIDOS = ("ingreso", "gasto")
MEDIOS_VALIDOS = ("transferencia", "debito", "credito", "efectivo")
MEDIOS_CON_COMISION = ("debito", "credito")


def registrar_movimiento(tipo: str, monto: float, medio_pago: str,
                          categoria: str | None = None, descripcion: str | None = None,
                          fecha: str | None = None, conn=None) -> int:
    """Registra un ingreso o gasto en la caja. Retorna el id del movimiento.

    `fecha` debe ir en formato YYYY-MM-DD; si no se indica, se usa hoy.

    `conn` es opcional: si se pasa una conexión ya abierta (por ejemplo
    desde pedidos.entregar_y_cobrar, para que la actualización del pedido
    y el ingreso en caja queden en una sola transacción), se usa esa
    misma conexión sin comitear ni cerrarla — es responsabilidad de quien
    la pasó. Si no se pasa, se abre y cierra una conexión propia, como
    siempre.
    """
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"tipo debe ser uno de {TIPOS_VALIDOS}")
    if medio_pago not in MEDIOS_VALIDOS:
        raise ValueError(f"medio_pago debe ser uno de {MEDIOS_VALIDOS}")
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a 0")

    fecha = fecha or date.today().isoformat()

    conexion_propia = conn is None
    if conexion_propia:
        conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO movimientos_caja (tipo, monto, medio_pago, categoria, descripcion, fecha)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (tipo, monto, medio_pago, categoria, descripcion, fecha),
        )
        movimiento_id = cursor.fetchone()["id"]
        if conexion_propia:
            conn.commit()
        return movimiento_id
    finally:
        if conexion_propia:
            conn.close()


def eliminar_movimiento(movimiento_id: int) -> None:
    """Elimina un movimiento de caja (ej. si se registró por error)."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM movimientos_caja WHERE id = %s", (movimiento_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"No existe un movimiento con id {movimiento_id}")
        cursor.execute("DELETE FROM movimientos_caja WHERE id = %s", (movimiento_id,))
        conn.commit()
    finally:
        conn.close()


def listar_movimientos(desde: str | None = None, hasta: str | None = None,
                        tipo: str | None = None, medio_pago: str | None = None) -> list[dict]:
    """Lista movimientos de caja, más recientes primero.

    Todos los filtros son opcionales: `desde`/`hasta` en formato YYYY-MM-DD
    (rango inclusivo), `tipo` ('ingreso'/'gasto'), `medio_pago`.
    """
    condiciones = []
    parametros = []

    if desde:
        condiciones.append("fecha >= %s")
        parametros.append(desde)
    if hasta:
        condiciones.append("fecha <= %s")
        parametros.append(hasta)
    if tipo:
        condiciones.append("tipo = %s")
        parametros.append(tipo)
    if medio_pago:
        condiciones.append("medio_pago = %s")
        parametros.append(medio_pago)

    query = "SELECT * FROM movimientos_caja"
    if condiciones:
        query += " WHERE " + " AND ".join(condiciones)
    query += " ORDER BY fecha DESC, id DESC"

    conn = conectar()
    try:
        filas = conn.execute(query, parametros).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def resumen_periodo(desde: str | None = None, hasta: str | None = None) -> dict:
    """Retorna un resumen de ingresos y gastos en un período (o de toda la
    historia, si no se indican fechas), desglosado por medio de pago.
    """
    movimientos = listar_movimientos(desde=desde, hasta=hasta)

    total_ingresos = 0.0
    total_gastos = 0.0
    por_medio_pago = {m: {"ingresos": 0.0, "gastos": 0.0} for m in MEDIOS_VALIDOS}
    por_categoria = {}

    for mov in movimientos:
        monto = mov["monto"]
        medio = mov["medio_pago"]
        categoria = mov["categoria"] or "(sin categoría)"

        if categoria not in por_categoria:
            por_categoria[categoria] = {"ingresos": 0.0, "gastos": 0.0}

        if mov["tipo"] == "ingreso":
            total_ingresos += monto
            por_medio_pago[medio]["ingresos"] += monto
            por_categoria[categoria]["ingresos"] += monto
        else:
            total_gastos += monto
            por_medio_pago[medio]["gastos"] += monto
            por_categoria[categoria]["gastos"] += monto

    return {
        "desde": desde,
        "hasta": hasta,
        "total_ingresos": round(total_ingresos, 2),
        "total_gastos": round(total_gastos, 2),
        "saldo": round(total_ingresos - total_gastos, 2),
        "por_medio_pago": {
            m: {"ingresos": round(v["ingresos"], 2), "gastos": round(v["gastos"], 2)}
            for m, v in por_medio_pago.items()
        },
        "por_categoria": {
            c: {"ingresos": round(v["ingresos"], 2), "gastos": round(v["gastos"], 2)}
            for c, v in por_categoria.items()
        },
        "cantidad_movimientos": len(movimientos),
    }


def saldo_actual() -> float:
    """Retorna el saldo acumulado de caja (todos los ingresos menos todos
    los gastos), considerando toda la historia."""
    resumen = resumen_periodo()
    return resumen["saldo"]


# --- Comisiones de medios de pago (ej. Mercado Pago Point) -----------------

def obtener_configuracion_comisiones() -> dict:
    """Retorna las tasas de comisión configuradas para débito y crédito
    (como fracción, ej. 0.0219 = 2,19%) y el IVA que se les aplica encima."""
    conn = conectar()
    try:
        fila = conn.execute(
            "SELECT tasa_debito_pct, tasa_credito_pct, iva_pct "
            "FROM configuracion_comisiones WHERE id = 1"
        ).fetchone()
        return dict(fila)
    finally:
        conn.close()


def actualizar_configuracion_comisiones(tasa_debito_pct: float, tasa_credito_pct: float,
                                         iva_pct: float) -> None:
    """Actualiza las tasas de comisión de débito/crédito y el IVA que se
    les aplica. Los tres valores van como fracción (ej. 0.0219 = 2,19%)."""
    if tasa_debito_pct < 0 or tasa_credito_pct < 0 or iva_pct < 0:
        raise ValueError("Las tasas no pueden ser negativas")

    conn = conectar()
    try:
        conn.execute(
            """UPDATE configuracion_comisiones
               SET tasa_debito_pct = %s, tasa_credito_pct = %s, iva_pct = %s
               WHERE id = 1""",
            (tasa_debito_pct, tasa_credito_pct, iva_pct),
        )
        conn.commit()
    finally:
        conn.close()


def calcular_comision(monto: float, medio_pago: str) -> float:
    """Calcula la comisión (ya con IVA incluido) que descuenta el medio de
    pago electrónico por un cobro con `medio_pago`. Retorna 0 si ese medio
    no tiene comisión configurada (ej. efectivo o transferencia)."""
    if medio_pago not in MEDIOS_CON_COMISION:
        return 0.0

    config = obtener_configuracion_comisiones()
    tasa = config["tasa_debito_pct"] if medio_pago == "debito" else config["tasa_credito_pct"]
    comision = monto * tasa * (1 + config["iva_pct"])
    return round(comision, 2)
