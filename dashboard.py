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

Rendimiento: todo el dashboard (mes elegido + mes anterior) sale de UNA
sola consulta a Supabase (`_cargar_datos`), que arma los datos como JSON
del lado de Postgres. La base está en São Paulo y la app en Streamlit
Cloud, así que cada consulta es un viaje de red largo: antes eran ~11
consultas (y al principio, cientos) cada vez que el caché estaba vacío.
"""

from calendar import monthrange
from datetime import date

from db import conectar, cache_lectura
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


def _cargar_datos(desde: str, hasta: str) -> dict:
    """Trae en una sola consulta todo lo que necesita el dashboard: los
    pedidos creados en el rango (con sus ítems), los movimientos de caja
    del rango, todas las recetas con sus ingredientes y la configuración
    de costos indirectos."""
    conn = conectar()
    try:
        fila = conn.execute(
            """WITH ped AS (
                   SELECT p.id, p.estado, p.fecha_creacion,
                          COALESCE((
                              SELECT json_agg(json_build_object(
                                         'nombre', r.nombre,
                                         'cantidad', pi.cantidad,
                                         'precio_unitario', pi.precio_unitario))
                              FROM pedido_items pi
                              JOIN recetas r ON r.id = pi.receta_id
                              WHERE pi.pedido_id = p.id
                          ), '[]'::json) AS items
                   FROM pedidos p
                   WHERE p.fecha_creacion::date >= %(desde)s AND p.fecha_creacion::date <= %(hasta)s
               )
               SELECT
                   (SELECT COALESCE(json_agg(ped), '[]'::json) FROM ped) AS pedidos,
                   (SELECT COALESCE(json_agg(json_build_object(
                               'tipo', m.tipo, 'monto', m.monto, 'medio_pago', m.medio_pago,
                               'categoria', m.categoria, 'fecha', m.fecha)), '[]'::json)
                    FROM movimientos_caja m
                    WHERE m.fecha >= %(desde)s AND m.fecha <= %(hasta)s) AS movimientos,
                   (SELECT COALESCE(json_agg(r ORDER BY r.nombre), '[]'::json) FROM recetas r) AS recetas,
                   (SELECT COALESCE(json_agg(json_build_object(
                               'receta_id', ri.receta_id, 'nombre', i.nombre,
                               'unidad_base', i.unidad_base, 'precio_actual', i.precio_actual,
                               'cantidad', ri.cantidad) ORDER BY i.nombre), '[]'::json)
                    FROM receta_ingredientes ri
                    JOIN ingredientes i ON i.id = ri.ingrediente_id) AS ingredientes,
                   (SELECT row_to_json(c) FROM configuracion_costos c WHERE c.id = 1) AS config""",
            {"desde": desde, "hasta": hasta},
        ).fetchone()
    finally:
        conn.close()
    return dict(fila)


def _resumen_pedidos(pedidos_mes: list[dict]) -> dict:
    """KPIs de pedidos tomados durante el mes: total, desglose por
    estado, tasa de cumplimiento/cancelación y ticket promedio."""
    total = len(pedidos_mes)
    por_estado = {estado: 0 for estado in ESTADOS_PEDIDOS}
    for p in pedidos_mes:
        por_estado[p["estado"]] += 1

    no_cancelados = [p for p in pedidos_mes if p["estado"] != "cancelado"]
    monto_no_cancelado = sum(p["total"] for p in no_cancelados)

    return {
        "total_pedidos": total,
        "por_estado": por_estado,
        "tasa_cumplimiento": round(por_estado["entregado"] / total, 4) if total else 0.0,
        "tasa_cancelacion": round(por_estado["cancelado"] / total, 4) if total else 0.0,
        "ticket_promedio": round(monto_no_cancelado / len(no_cancelados), 2) if no_cancelados else 0.0,
        "monto_total_no_cancelado": round(monto_no_cancelado, 2),
    }


def _ranking_productos(pedidos_mes: list[dict]) -> list[dict]:
    """Recetas más vendidas (unidades y monto) entre los pedidos no
    cancelados del mes, de más a menos unidades."""
    agregados = {}
    for p in pedidos_mes:
        if p["estado"] == "cancelado":
            continue
        for item in p["items"]:
            acumulado = agregados.setdefault(
                item["nombre"], {"nombre": item["nombre"], "unidades": 0, "monto_total": 0.0}
            )
            acumulado["unidades"] += item["cantidad"]
            acumulado["monto_total"] += item["subtotal"]

    resultado = sorted(agregados.values(), key=lambda r: -r["unidades"])
    for r in resultado:
        r["monto_total"] = round(r["monto_total"], 2)
    return resultado


def _rentabilidad_productos(ventas_mes: list[dict], recetas: list[dict]) -> list[dict]:
    """Recetas por ganancia estimada del mes (margen real vigente x
    unidades vendidas en el mes) — no siempre coincide con el ranking de
    popularidad: un pan muy pedido puede dejar poca ganancia total si su
    margen es bajo."""
    recetas_por_nombre = {r["nombre"]: r for r in recetas}

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
    return resultado


def _resumen_financiero(movimientos_mes: list[dict]) -> dict:
    """Ingresos, gastos, saldo y comisiones del mes (por fecha del
    movimiento de caja)."""
    resumen = mod_caja.resumir_movimientos(movimientos_mes)
    comisiones = resumen["por_categoria"].get("Comisión Mercado Pago", {"gastos": 0.0})["gastos"]
    return {
        "total_ingresos": resumen["total_ingresos"],
        "total_gastos": resumen["total_gastos"],
        "saldo": resumen["saldo"],
        "comisiones_pagadas": round(comisiones, 2),
        "por_medio_pago": resumen["por_medio_pago"],
    }


@cache_lectura
def datos_dashboard(anio: int, mes: int, limite_ranking: int = 10) -> dict:
    """Todo lo que muestra el dashboard para un mes, comparado contra el
    mes calendario anterior, a partir de una sola consulta a la base.

    Retorna: pedidos / pedidos_anterior (KPIs de pedidos), financiero /
    financiero_anterior (caja), ranking_ventas, ranking_rentabilidad y
    recetas_bajo_margen (solo recetas activas)."""
    anio_ant, mes_ant = mes_anterior(anio, mes)
    desde_ant, hasta_ant = _rango_mes(anio_ant, mes_ant)
    desde, hasta = _rango_mes(anio, mes)
    datos = _cargar_datos(desde_ant, hasta)

    for p in datos["pedidos"]:
        for item in p["items"]:
            item["subtotal"] = round(item["cantidad"] * item["precio_unitario"], 2)
        p["total"] = round(sum(i["subtotal"] for i in p["items"]), 2)
    pedidos_mes = [p for p in datos["pedidos"] if p["fecha_creacion"][:10] >= desde]
    pedidos_ant = [p for p in datos["pedidos"] if p["fecha_creacion"][:10] <= hasta_ant]
    movimientos_mes = [m for m in datos["movimientos"] if m["fecha"] >= desde]
    movimientos_ant = [m for m in datos["movimientos"] if m["fecha"] <= hasta_ant]

    ingredientes_por_receta = {}
    for f in datos["ingredientes"]:
        ingredientes_por_receta.setdefault(f["receta_id"], []).append(f)
    recetas = [
        mod_rec._calcular_costo(r, ingredientes_por_receta.get(r["id"], []), datos["config"])
        for r in datos["recetas"]
    ]

    ranking_ventas = _ranking_productos(pedidos_mes)
    return {
        "pedidos": _resumen_pedidos(pedidos_mes),
        "pedidos_anterior": _resumen_pedidos(pedidos_ant),
        "financiero": _resumen_financiero(movimientos_mes),
        "financiero_anterior": _resumen_financiero(movimientos_ant),
        "ranking_ventas": ranking_ventas[:limite_ranking],
        "ranking_rentabilidad": _rentabilidad_productos(ranking_ventas, recetas)[:limite_ranking],
        "recetas_bajo_margen": [r for r in recetas if r["activo"] and r["bajo_margen"]],
    }
