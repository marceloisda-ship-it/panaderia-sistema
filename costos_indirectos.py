"""
costos_indirectos.py
----------------------
Configuración global de costos indirectos: luz, empaque y mano de obra.

Estos parámetros se guardan una sola vez (fila única en configuracion_costos)
y se usan en recetas.py para calcular el costo final de cada receta:

    costo_indirecto_luz = receta.consumo_kwh_programa * tarifa_electrica_kwh * factor_descuento_luz
    costo_empaque        = costo_empaque_unidad  (monto fijo, igual para todas las recetas)
    costo_mano_obra      = (tiempo_preparacion_min / 60 * valor_hora_mano_obra) / unidades_por_lote

`consumo_kwh_programa`, `tiempo_preparacion_min` y `unidades_por_lote` son
propios de cada receta (ver recetas.py); `tarifa_electrica_kwh`,
`factor_descuento_luz` y `valor_hora_mano_obra` viven acá porque son
parámetros generales del negocio, no algo que cambie receta a receta.

Ojo: `unidades_por_lote` sólo divide la mano de obra, no la luz. El usuario
tiene 3 panificadoras y prepara varios panes en la misma sesión de trabajo
(por eso el tiempo se reparte entre ellos), pero cada pan se hornea en su
propia máquina con su propio ciclo completo — la energía no se abarata por
lote, cada unidad sigue consumiendo su `consumo_kwh_programa` entero.

`factor_descuento_luz` existe porque el consumo teórico de cada programa
(potencia nominal x tiempo) es un techo: la resistencia de horneado cicla
por termostato y no tira la potencia nominal todo el ciclo, así que el
consumo real es menor. Mientras no haya una medición real con medidor
enchufable, se aplica este factor (ej. 0.65 = se estima que el consumo real
es un 65% del teórico) para no sobreestimar el costo de luz.
"""

from db import conectar


def obtener_configuracion() -> dict:
    """Retorna la configuración actual de costos indirectos."""
    conn = conectar()
    try:
        fila = conn.execute(
            "SELECT costo_empaque_unidad, valor_hora_mano_obra, "
            "tarifa_electrica_kwh, factor_descuento_luz "
            "FROM configuracion_costos WHERE id = 1"
        ).fetchone()
        return dict(fila)
    finally:
        conn.close()


def actualizar_configuracion(costo_empaque_unidad: float, valor_hora_mano_obra: float,
                              tarifa_electrica_kwh: float, factor_descuento_luz: float) -> None:
    """Actualiza los cuatro parámetros de costos indirectos.

    `factor_descuento_luz` va como fracción entre 0 y 1 (ej. 0.65 = se estima
    que el consumo real de luz es un 65% del teórico de cada programa).
    """
    if costo_empaque_unidad < 0:
        raise ValueError("El costo de empaque no puede ser negativo")
    if valor_hora_mano_obra < 0:
        raise ValueError("El valor hora de mano de obra no puede ser negativo")
    if tarifa_electrica_kwh < 0:
        raise ValueError("La tarifa eléctrica no puede ser negativa")
    if not (0 <= factor_descuento_luz <= 1):
        raise ValueError("El factor de descuento de luz debe ser un valor entre 0 y 1 (ej. 0.65 = 65%)")

    conn = conectar()
    try:
        conn.execute(
            """UPDATE configuracion_costos
               SET costo_empaque_unidad = ?, valor_hora_mano_obra = ?,
                   tarifa_electrica_kwh = ?, factor_descuento_luz = ?
               WHERE id = 1""",
            (costo_empaque_unidad, valor_hora_mano_obra, tarifa_electrica_kwh, factor_descuento_luz),
        )
        conn.commit()
    finally:
        conn.close()
