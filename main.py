"""
main.py
--------
Punto de entrada del sistema. Menú de consola para gestionar
ingredientes y recetas (Módulo de Costeo).

Para ejecutar:
    python3 main.py
"""

from datetime import date

from db import inicializar_db
import ingredientes as mod_ing
import recetas as mod_rec
import caja as mod_caja


def pedir_float(mensaje: str) -> float:
    while True:
        try:
            return float(input(mensaje).replace(",", "."))
        except ValueError:
            print("  Por favor ingresa un número válido.")


def pedir_int(mensaje: str) -> int:
    while True:
        try:
            return int(input(mensaje))
        except ValueError:
            print("  Por favor ingresa un número entero válido.")


def pedir_fecha(mensaje: str) -> str:
    """Pide una fecha en formato YYYY-MM-DD. Enter vacío = hoy."""
    while True:
        texto = input(mensaje).strip()
        if not texto:
            return date.today().isoformat()
        try:
            return date.fromisoformat(texto).isoformat()
        except ValueError:
            print("  Formato inválido, usa YYYY-MM-DD (ej. 2026-09-01).")


# --- Pantallas: Ingredientes -----------------------------------------------

def menu_agregar_ingrediente():
    print("\n--- Nuevo ingrediente ---")
    nombre = input("Nombre (ej. Harina 000): ").strip()
    print("Unidad base -> 1) gramos (gr)  2) mililitros (ml)  3) unidad")
    opcion = input("Elige 1/2/3: ").strip()
    unidad = {"1": "gr", "2": "ml", "3": "unidad"}.get(opcion)
    if unidad is None:
        print("  Opción inválida, se cancela.")
        return
    precio = pedir_float(f"Precio actual por {unidad}: $")
    proveedor = input("Proveedor (opcional, enter para omitir): ").strip() or None
    try:
        ing_id = mod_ing.agregar_ingrediente(nombre, unidad, precio, proveedor)
        print(f"  ✔ Ingrediente creado con id {ing_id}")
    except Exception as e:
        print(f"  ✘ Error: {e}")


def menu_listar_ingredientes():
    print("\n--- Ingredientes registrados ---")
    ings = mod_ing.listar_ingredientes()
    if not ings:
        print("  (no hay ingredientes cargados todavía)")
        return
    for i in ings:
        print(f"  [{i['id']}] {i['nombre']:<20} ${i['precio_actual']:>10.2f} / {i['unidad_base']:<7} "
              f"(actualizado: {i['fecha_actualizacion']})")


def menu_actualizar_precio_ingrediente():
    print("\n--- Actualizar precio de ingrediente ---")
    menu_listar_ingredientes()
    ing_id = pedir_int("\nId del ingrediente a actualizar: ")
    nuevo_precio = pedir_float("Nuevo precio: $")
    try:
        mod_ing.actualizar_precio(ing_id, nuevo_precio)
        print("  ✔ Precio actualizado (queda registrado en el historial).")
    except Exception as e:
        print(f"  ✘ Error: {e}")


def menu_ver_historial_ingrediente():
    print("\n--- Historial de precio de un ingrediente ---")
    menu_listar_ingredientes()
    ing_id = pedir_int("\nId del ingrediente: ")
    historial = mod_ing.historial_de_precio(ing_id)
    if not historial:
        print("  (sin historial)")
        return
    for h in historial:
        print(f"  {h['fecha']}  ->  ${h['precio']:.2f}")


# --- Pantallas: Recetas -------------------------------------------------

def menu_crear_receta():
    print("\n--- Nueva receta (pan) ---")
    nombre = input("Nombre del pan (ej. Marraqueta): ").strip()
    precio_venta = pedir_float("Precio de venta: $")
    margen = pedir_float("Margen de ganancia objetivo, en % (ej. 40): ") / 100
    notas = input("Notas (opcional): ").strip() or None
    try:
        receta_id = mod_rec.crear_receta(nombre, precio_venta, margen, notas)
        print(f"  ✔ Receta creada con id {receta_id}. Ahora agrégale ingredientes desde el menú.")
    except Exception as e:
        print(f"  ✘ Error: {e}")


def menu_agregar_ingrediente_a_receta():
    print("\n--- Agregar ingrediente a una receta ---")
    print("Recetas disponibles:")
    for r in mod_rec.listar_recetas(solo_activas=False):
        print(f"  [{r['id']}] {r['nombre']}")
    receta_id = pedir_int("\nId de la receta: ")

    print("\nIngredientes disponibles:")
    menu_listar_ingredientes()
    ing_id = pedir_int("\nId del ingrediente: ")

    ing = None
    for i in mod_ing.listar_ingredientes():
        if i["id"] == ing_id:
            ing = i
            break
    unidad = ing["unidad_base"] if ing else "unidad"

    cantidad = pedir_float(f"Cantidad usada en la receta (en {unidad}): ")
    try:
        mod_rec.agregar_ingrediente_a_receta(receta_id, ing_id, cantidad)
        print("  ✔ Ingrediente agregado/actualizado en la receta.")
    except Exception as e:
        print(f"  ✘ Error: {e}")


def menu_ver_costo_receta():
    print("\n--- Costo y margen de una receta ---")
    for r in mod_rec.listar_recetas(solo_activas=False):
        print(f"  [{r['id']}] {r['nombre']}")
    receta_id = pedir_int("\nId de la receta: ")
    try:
        d = mod_rec.detalle_receta(receta_id)
    except Exception as e:
        print(f"  ✘ Error: {e}")
        return

    print(f"\n  Receta: {d['nombre']}")
    print("  Ingredientes:")
    for ing in d["ingredientes"]:
        print(f"    - {ing['nombre']:<18} {ing['cantidad']:>8} {ing['unidad_base']:<6} "
              f"x ${ing['precio_unitario']:.2f} = ${ing['subtotal']:.2f}")
    print(f"\n  Costo total:     ${d['costo_total']:.2f}")
    print(f"  Precio de venta: ${d['precio_venta']:.2f}")
    print(f"  Ganancia:        ${d['ganancia']:.2f}")
    print(f"  Margen real:     {d['margen_real'] * 100:.1f}%  (objetivo: {d['margen_objetivo'] * 100:.1f}%)")
    if d["bajo_margen"]:
        print("  ⚠ ALERTA: esta receta está por debajo del margen objetivo.")


def menu_reporte_general():
    print("\n--- Reporte general de rentabilidad (recetas activas) ---")
    recetas = mod_rec.listar_recetas(solo_activas=True)
    if not recetas:
        print("  (no hay recetas activas)")
        return
    print(f"  {'Pan':<20}{'Costo':>10}{'Venta':>10}{'Margen':>10}   Estado")
    for r in recetas:
        estado = "⚠ BAJO MARGEN" if r["bajo_margen"] else "OK"
        print(f"  {r['nombre']:<20}{r['costo_total']:>10.2f}{r['precio_venta']:>10.2f}"
              f"{r['margen_real'] * 100:>9.1f}%   {estado}")


# --- Pantallas: Flujo de caja -------------------------------------------

def _elegir_medio_pago() -> str | None:
    print("Medio de pago -> 1) transferencia  2) débito  3) crédito  4) efectivo")
    opcion = input("Elige 1/2/3/4: ").strip()
    medio = {"1": "transferencia", "2": "debito", "3": "credito", "4": "efectivo"}.get(opcion)
    if medio is None:
        print("  Opción inválida, se cancela.")
    return medio


def menu_registrar_ingreso():
    print("\n--- Registrar ingreso ---")
    monto = pedir_float("Monto: $")
    medio = _elegir_medio_pago()
    if medio is None:
        return
    categoria = input("Categoría (ej. Venta mostrador, opcional): ").strip() or None
    descripcion = input("Descripción (opcional): ").strip() or None
    fecha = pedir_fecha("Fecha (YYYY-MM-DD, enter = hoy): ")
    try:
        mov_id = mod_caja.registrar_movimiento("ingreso", monto, medio, categoria, descripcion, fecha)
        print(f"  ✔ Ingreso registrado con id {mov_id}")
    except Exception as e:
        print(f"  ✘ Error: {e}")


def menu_registrar_gasto():
    print("\n--- Registrar gasto ---")
    monto = pedir_float("Monto: $")
    medio = _elegir_medio_pago()
    if medio is None:
        return
    categoria = input("Categoría (ej. Insumos, arriendo, servicios, opcional): ").strip() or None
    descripcion = input("Descripción (opcional): ").strip() or None
    fecha = pedir_fecha("Fecha (YYYY-MM-DD, enter = hoy): ")
    try:
        mov_id = mod_caja.registrar_movimiento("gasto", monto, medio, categoria, descripcion, fecha)
        print(f"  ✔ Gasto registrado con id {mov_id}")
    except Exception as e:
        print(f"  ✘ Error: {e}")


def menu_listar_movimientos():
    print("\n--- Movimientos de caja ---")
    print("Filtrar por fecha (enter para omitir el filtro)")
    desde = input("  Desde (YYYY-MM-DD): ").strip() or None
    hasta = input("  Hasta (YYYY-MM-DD): ").strip() or None
    movimientos = mod_caja.listar_movimientos(desde=desde, hasta=hasta)
    if not movimientos:
        print("  (no hay movimientos en ese rango)")
        return
    for m in movimientos:
        signo = "+" if m["tipo"] == "ingreso" else "-"
        categoria = m["categoria"] or "-"
        print(f"  [{m['id']}] {m['fecha']}  {signo}${m['monto']:>10.2f}  "
              f"{m['medio_pago']:<13} {categoria:<20} {m['descripcion'] or ''}")


def menu_eliminar_movimiento():
    print("\n--- Eliminar movimiento de caja ---")
    menu_listar_movimientos()
    mov_id = pedir_int("\nId del movimiento a eliminar: ")
    try:
        mod_caja.eliminar_movimiento(mov_id)
        print("  ✔ Movimiento eliminado.")
    except Exception as e:
        print(f"  ✘ Error: {e}")


def menu_reporte_caja():
    print("\n--- Reporte de flujo de caja por período ---")
    print("Enter para omitir y considerar toda la historia")
    desde = input("  Desde (YYYY-MM-DD): ").strip() or None
    hasta = input("  Hasta (YYYY-MM-DD): ").strip() or None
    r = mod_caja.resumen_periodo(desde=desde, hasta=hasta)

    periodo = f"{r['desde'] or 'inicio'} → {r['hasta'] or 'hoy'}"
    print(f"\n  Período: {periodo}  ({r['cantidad_movimientos']} movimientos)")
    print(f"  Total ingresos: ${r['total_ingresos']:>10.2f}")
    print(f"  Total gastos:   ${r['total_gastos']:>10.2f}")
    print(f"  Saldo:          ${r['saldo']:>10.2f}")

    print("\n  Por medio de pago:")
    print(f"  {'Medio':<15}{'Ingresos':>12}{'Gastos':>12}")
    for medio, v in r["por_medio_pago"].items():
        print(f"  {medio:<15}{v['ingresos']:>12.2f}{v['gastos']:>12.2f}")

    print("\n  Por categoría:")
    print(f"  {'Categoría':<20}{'Ingresos':>12}{'Gastos':>12}")
    for categoria, v in r["por_categoria"].items():
        print(f"  {categoria:<20}{v['ingresos']:>12.2f}{v['gastos']:>12.2f}")


# --- Menú principal ----------------------------------------------------

MENU = """
====================================
  SISTEMA DE GESTIÓN - PANADERÍA
  Costeo de recetas · Flujo de caja
====================================
 1) Agregar ingrediente
 2) Listar ingredientes
 3) Actualizar precio de ingrediente
 4) Ver historial de precio de un ingrediente
 -----
 5) Crear receta (pan)
 6) Agregar/actualizar ingrediente en una receta
 7) Ver costo y margen de una receta
 8) Reporte general de rentabilidad
 -----
 9) Registrar ingreso
10) Registrar gasto
11) Listar movimientos de caja
12) Eliminar movimiento de caja
13) Reporte de flujo de caja por período
 -----
 0) Salir
====================================
"""


def main():
    inicializar_db()
    acciones = {
        "1": menu_agregar_ingrediente,
        "2": menu_listar_ingredientes,
        "3": menu_actualizar_precio_ingrediente,
        "4": menu_ver_historial_ingrediente,
        "5": menu_crear_receta,
        "6": menu_agregar_ingrediente_a_receta,
        "7": menu_ver_costo_receta,
        "8": menu_reporte_general,
        "9": menu_registrar_ingreso,
        "10": menu_registrar_gasto,
        "11": menu_listar_movimientos,
        "12": menu_eliminar_movimiento,
        "13": menu_reporte_caja,
    }
    while True:
        print(MENU)
        opcion = input("Elige una opción: ").strip()
        if opcion == "0":
            print("Hasta luego 👋")
            break
        accion = acciones.get(opcion)
        if accion:
            accion()
        else:
            print("  Opción inválida.")


if __name__ == "__main__":
    main()
