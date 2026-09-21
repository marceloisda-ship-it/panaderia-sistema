"""
recetas.py
-----------
Gestión de recetas (panes): composición de ingredientes, cálculo
automático de costo, y control de margen de ganancia respecto al
precio de venta.

Concepto clave — el costo final de una receta tiene tres componentes:
    costo_directo    = suma( cantidad_ingrediente * precio_actual_ingrediente )
    costo_indirecto  = costo_luz                          (consumo del programa de esta receta x tarifa, ver costos_indirectos.py)
                      + costo_empaque_unidad               (fijo, igual para todas las recetas)
                      + costo_mano_obra                     (tiempo de esta receta x tu valor hora)
    costo_total      = costo_directo + costo_indirecto
    margen_real      = (precio_venta - costo_total) / precio_venta

El costo de luz y el de mano de obra son propios de cada receta, pero se
prorratean distinto porque cada pan se hornea en su propia panificadora:
- Luz: consumo del programa de esa receta (`consumo_kwh_programa`, kWh) x
  tarifa — NO se divide por `unidades_por_lote`, porque cada pan gasta su
  propio ciclo completo de energía sin importar cuántos se preparen juntos.
- Mano de obra: tiempo activo para dejar lista una sesión de preparación
  (`tiempo_preparacion_min`) dividido por cuántos panes rinde esa sesión
  (`unidades_por_lote`) — ese tiempo sí se comparte entre los panes,
  porque preparas varias panificadoras a la vez en la misma sesión.

Si margen_real < margen_objetivo, la receta queda marcada como
"bajo margen" en los reportes, para que sea fácil detectar cuándo
un pan dejó de ser rentable por la subida de algún insumo o de los
costos indirectos.
"""

from db import conectar
import costos_indirectos


def crear_receta(nombre: str, precio_venta: float, margen_objetivo: float = 0.4,
                  notas: str | None = None, tiempo_preparacion_min: float = 0.0,
                  unidades_por_lote: int = 1, consumo_kwh_programa: float = 0.0) -> int:
    """Crea una nueva receta (sin ingredientes todavía) y retorna su id."""
    if precio_venta < 0:
        raise ValueError("El precio de venta no puede ser negativo")
    if not (0 <= margen_objetivo < 1):
        raise ValueError("El margen objetivo debe ser un valor entre 0 y 1 (ej. 0.4 = 40%)")
    if tiempo_preparacion_min < 0:
        raise ValueError("El tiempo de preparación no puede ser negativo")
    if unidades_por_lote < 1:
        raise ValueError("Las unidades por lote deben ser al menos 1")
    if consumo_kwh_programa < 0:
        raise ValueError("El consumo del programa no puede ser negativo")

    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO recetas (nombre, precio_venta, margen_objetivo, notas,
                                     tiempo_preparacion_min, unidades_por_lote, consumo_kwh_programa)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (nombre, precio_venta, margen_objetivo, notas, tiempo_preparacion_min,
             unidades_por_lote, consumo_kwh_programa),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar_mano_obra(receta_id: int, tiempo_preparacion_min: float, unidades_por_lote: int) -> None:
    """Actualiza cuánto tiempo toma preparar un lote de esta receta y cuántas
    unidades rinde ese lote (base del costo de mano de obra de la receta)."""
    if tiempo_preparacion_min < 0:
        raise ValueError("El tiempo de preparación no puede ser negativo")
    if unidades_por_lote < 1:
        raise ValueError("Las unidades por lote deben ser al menos 1")

    conn = conectar()
    try:
        conn.execute(
            "UPDATE recetas SET tiempo_preparacion_min = ?, unidades_por_lote = ? WHERE id = ?",
            (tiempo_preparacion_min, unidades_por_lote, receta_id),
        )
        conn.commit()
    finally:
        conn.close()


def actualizar_luz(receta_id: int, consumo_kwh_programa: float) -> None:
    """Actualiza cuánto consume (en kWh por lote) el programa de la máquina
    de pan que usa esta receta (base del costo de luz propio de la receta)."""
    if consumo_kwh_programa < 0:
        raise ValueError("El consumo del programa no puede ser negativo")

    conn = conectar()
    try:
        conn.execute(
            "UPDATE recetas SET consumo_kwh_programa = ? WHERE id = ?",
            (consumo_kwh_programa, receta_id),
        )
        conn.commit()
    finally:
        conn.close()


def agregar_ingrediente_a_receta(receta_id: int, ingrediente_id: int, cantidad: float) -> None:
    """Agrega (o actualiza, si ya existía) un ingrediente dentro de una receta.

    `cantidad` debe estar en la unidad_base del ingrediente (gr, ml o unidad).
    """
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a 0")

    conn = conectar()
    try:
        conn.execute(
            """INSERT INTO receta_ingredientes (receta_id, ingrediente_id, cantidad)
               VALUES (?, ?, ?)
               ON CONFLICT(receta_id, ingrediente_id)
               DO UPDATE SET cantidad = excluded.cantidad""",
            (receta_id, ingrediente_id, cantidad),
        )
        conn.commit()
    finally:
        conn.close()


def quitar_ingrediente_de_receta(receta_id: int, ingrediente_id: int) -> None:
    """Quita un ingrediente de una receta."""
    conn = conectar()
    try:
        conn.execute(
            "DELETE FROM receta_ingredientes WHERE receta_id = ? AND ingrediente_id = ?",
            (receta_id, ingrediente_id),
        )
        conn.commit()
    finally:
        conn.close()


def _obtener_receta(conn, receta_id: int) -> dict:
    fila = conn.execute("SELECT * FROM recetas WHERE id = ?", (receta_id,)).fetchone()
    if fila is None:
        raise ValueError(f"No existe una receta con id {receta_id}")
    return dict(fila)


def detalle_receta(receta_id: int) -> dict:
    """Retorna el detalle completo de una receta: datos generales,
    lista de ingredientes, desglose de costo directo e indirecto,
    costo total, margen real y si está por debajo del margen objetivo."""
    conn = conectar()
    try:
        receta = _obtener_receta(conn, receta_id)

        filas = conn.execute(
            """SELECT i.nombre, i.unidad_base, i.precio_actual, ri.cantidad
               FROM receta_ingredientes ri
               JOIN ingredientes i ON i.id = ri.ingrediente_id
               WHERE ri.receta_id = ?
               ORDER BY i.nombre ASC""",
            (receta_id,),
        ).fetchall()

        ingredientes = []
        costo_directo = 0.0
        for f in filas:
            subtotal = f["cantidad"] * f["precio_actual"]
            costo_directo += subtotal
            ingredientes.append({
                "nombre": f["nombre"],
                "cantidad": f["cantidad"],
                "unidad_base": f["unidad_base"],
                "precio_unitario": f["precio_actual"],
                "subtotal": round(subtotal, 2),
            })

        config = costos_indirectos.obtener_configuracion()
        # La luz NO se divide por unidades_por_lote: cada pan se hornea en su
        # propia panificadora con su propio ciclo completo, así que el
        # consumo eléctrico no se abarata por preparar varios panes en la
        # misma sesión de trabajo (a diferencia de la mano de obra, que sí
        # se reparte porque el tiempo activo de preparación es compartido).
        costo_indirecto_luz = (
            receta["consumo_kwh_programa"] * config["tarifa_electrica_kwh"] * config["factor_descuento_luz"]
        )
        costo_empaque = config["costo_empaque_unidad"]
        costo_mano_obra = (
            receta["tiempo_preparacion_min"] / 60 * config["valor_hora_mano_obra"]
            / receta["unidades_por_lote"]
        )
        costo_total = costo_directo + costo_indirecto_luz + costo_empaque + costo_mano_obra

        precio_venta = receta["precio_venta"]
        if precio_venta > 0:
            margen_real = (precio_venta - costo_total) / precio_venta
        else:
            margen_real = 0.0

        return {
            "id": receta["id"],
            "nombre": receta["nombre"],
            "precio_venta": precio_venta,
            "margen_objetivo": receta["margen_objetivo"],
            "activo": bool(receta["activo"]),
            "notas": receta["notas"],
            "tiempo_preparacion_min": receta["tiempo_preparacion_min"],
            "unidades_por_lote": receta["unidades_por_lote"],
            "consumo_kwh_programa": receta["consumo_kwh_programa"],
            "ingredientes": ingredientes,
            "costo_directo": round(costo_directo, 2),
            "costo_indirecto_luz": round(costo_indirecto_luz, 2),
            "costo_empaque": round(costo_empaque, 2),
            "costo_mano_obra": round(costo_mano_obra, 2),
            "costo_total": round(costo_total, 2),
            "ganancia": round(precio_venta - costo_total, 2),
            "margen_real": round(margen_real, 4),
            "bajo_margen": margen_real < receta["margen_objetivo"],
        }
    finally:
        conn.close()


def listar_recetas(solo_activas: bool = True) -> list[dict]:
    """Retorna todas las recetas con su costo y margen ya calculados.
    Útil para el reporte general de rentabilidad."""
    conn = conectar()
    try:
        query = "SELECT id FROM recetas"
        if solo_activas:
            query += " WHERE activo = 1"
        query += " ORDER BY nombre ASC"
        ids = [f["id"] for f in conn.execute(query).fetchall()]
    finally:
        conn.close()

    return [detalle_receta(receta_id) for receta_id in ids]


def actualizar_precio_venta(receta_id: int, nuevo_precio: float) -> None:
    """Actualiza el precio de venta de una receta."""
    if nuevo_precio < 0:
        raise ValueError("El precio de venta no puede ser negativo")
    conn = conectar()
    try:
        conn.execute("UPDATE recetas SET precio_venta = ? WHERE id = ?", (nuevo_precio, receta_id))
        conn.commit()
    finally:
        conn.close()


def actualizar_margen_objetivo(receta_id: int, nuevo_margen: float) -> None:
    """Actualiza el margen de ganancia objetivo (ej. 0.35 = 35%) de una receta."""
    if not (0 <= nuevo_margen < 1):
        raise ValueError("El margen debe ser un valor entre 0 y 1 (ej. 0.4 = 40%)")
    conn = conectar()
    try:
        conn.execute("UPDATE recetas SET margen_objetivo = ? WHERE id = ?", (nuevo_margen, receta_id))
        conn.commit()
    finally:
        conn.close()
