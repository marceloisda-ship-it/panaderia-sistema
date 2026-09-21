"""
dashboard.py
-------------
KPIs de negocio para el resumen mensual: pedidos, ventas y rentabilidad.
No introduce datos nuevos ni tablas propias — combina lo que ya calculan
pedidos.py, recetas.py y caja.py para responder, de un vistazo, cómo
viene el mes.

Definiciones clave:
- "Pedidos del mes" se cuenta por fecha de creación del pedido (cuándo
  se tomó el pedido), no por fecha de entrega — esa segunda fecha ya se
  usa para planificación de producción en pedidos.py/produccion.py y
  responde una pregunta distinta ("qué hay que preparar tal día").
- La rentabilidad por receta usa el margen_real vigente HOY (el costo
  actual de ingredientes), no el costo histórico de cada pedido — sirve
  para decidir qué impulsar de ahora en adelante, no para reconstruir
  la ganancia exacta de pedidos ya tomados.
"""

from calendar import monthrange
from datetime import date

from db import conectar
import pedidos as mod_pedidos
import recetas as mod_rec
import caja as mod_caja

ESTADOS_PEDIDOS = ("pendiente", "confirmado", "entregado", "cancelado")


def _rango_mes(anio: int, mes: int) -> tuple[str, str]:
    desde = date(anio, mes, 1).isoformat()
    ultimo_dia = monthrange(anio, mes)[1]
    hasta = date(anio, mes, ultimo_dia).isoformat()
    return desde, hasta


def mes_anterior(anio: int, mes: int) -> tuple[int, int]:
    """Retorna (año, mes) del mes calendario anterior."""
    if mes == 1:
        return anio - 1, 12
    return anio, mes - 1


def _pedidos_creados_entre(desde: str, hasta: str) -> list[dict]:
    """Pedidos cuya fecha_creacion (no fecha_entrega) cae en el rango."""
    conn = conectar()
    try:
        ids = [
            f["id"] for f in conn.execute(
                """SELECT id FROM pedidos
                   WHERE date(fecha_creacion) >= ? AND date(fecha_creacion) <= ?
                   ORDER BY fecha_creacion ASC""",
                (desde, hasta),
            ).fetchall()
        ]
    finally:
        conn.close()
    return [mod_pedidos.detalle_pedido(pid) for pid in ids]


def resumen_pedidos_mes(anio: int, mes: int) -> dict:
    """KPIs de pedidos tomados durante el mes: total, desglose por
    estado, tasa de cumplimiento/cancelación y ticket promedio."""
    desde, hasta = _rango_mes(anio, mes)
    pedidos_mes = _pedidos_creados_entre(desde, hasta)

    total = len(pedidos_mes)
    por_estado = {estado: 0 for estado in ESTADOS_PEDIDOS}
    for p in pedidos_mes:
        por_estado[p["estado"]] += 1

    no_cancelados = [p for p in pedidos_mes if p["estado"] != "cancelado"]
    monto_no_cancelado = sum(p["total"] for p in no_cancelados)

    return {
        "anio": anio,
        "mes": mes,
        "desde": desde,
        "hasta": hasta,
        "total_pedidos": total,
        "por_estado": por_estado,
        "tasa_cumplimiento": round(por_estado["entregado"] / total, 4) if total else 0.0,
        "tasa_cancelacion": round(por_estado["cancelado"] / total, 4) if total else 0.0,
        "ticket_promedio": round(monto_no_cancelado / len(no_cancelados), 2) if no_cancelados else 0.0,
        "monto_total_no_cancelado": round(monto_no_cancelado, 2),
    }


def ranking_productos_mes(anio: int, mes: int, limite: int = 10) -> list[dict]:
    """Ranking de recetas más vendidas (unidades y monto) entre los
    pedidos no cancelados creados en el mes."""
    desde, hasta = _rango_mes(anio, mes)
    pedidos_mes = [p for p in _pedidos_creados_entre(desde, hasta) if p["estado"] != "cancelado"]

    agregados = {}
    for p in pedidos_mes:
        for item in p["items"]:
            acumulado = agregados.setdefault(
                item["nombre"], {"nombre": item["nombre"], "unidades": 0, "monto_total": 0.0}
            )
            acumulado["unidades"] += item["cantidad"]
            acumulado["monto_total"] += item["subtotal"]

    resultado = sorted(agregados.values(), key=lambda r: -r["unidades"])[:limite]
    for r in resultado:
        r["monto_total"] = round(r["monto_total"], 2)
    return resultado


def rentabilidad_productos_mes(anio: int, mes: int, limite: int = 10) -> list[dict]:
    """Ranking de recetas por ganancia estimada del mes (margen real
    vigente x unidades vendidas en el mes) — no siempre coincide con el
    ranking de popularidad: un pan muy pedido puede dejar poca ganancia
    total si su margen es bajo."""
    ventas_mes = ranking_productos_mes(anio, mes, limite=10_000)
    recetas_por_nombre = {r["nombre"]: r for r in mod_rec.listar_recetas(solo_activas=False)}

    resultado = []
    for v in ventas_mes:
        receta = recetas_por_nombre.get(v["nombre"])
        if receta is None:
            continue
        resultado.append({
            "nombre": v["nombre"],
            "unidades_vendidas": v["unidades"],
            "margen_real_pct": round(receta["margen_real"] * 100, 1),
            "ganancia_estimada": round(receta["ganancia"] * v["unidades"], 2),
        })

    resultado.sort(key=lambda r: -r["ganancia_estimada"])
    return resultado[:limite]


def resumen_financiero_mes(anio: int, mes: int) -> dict:
    """Ingresos, gastos, saldo y comisiones del mes (por fecha del
    movimiento de caja)."""
    desde, hasta = _rango_mes(anio, mes)
    resumen = mod_caja.resumen_periodo(desde=desde, hasta=hasta)
    comisiones = resumen["por_categoria"].get("Comisión Mercado Pago", {"gastos": 0.0})["gastos"]

    return {
        "anio": anio,
        "mes": mes,
        "total_ingresos": resumen["total_ingresos"],
        "total_gastos": resumen["total_gastos"],
        "saldo": resumen["saldo"],
        "comisiones_pagadas": round(comisiones, 2),
        "por_medio_pago": resumen["por_medio_pago"],
    }


def recetas_bajo_margen(solo_activas: bool = True) -> list[dict]:
    """Recetas cuyo margen real está por debajo del objetivo — para no
    perder de vista cuáles panes dejaron de ser rentables."""
    return [r for r in mod_rec.listar_recetas(solo_activas=solo_activas) if r["bajo_margen"]]
