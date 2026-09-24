"""
app.py
-------
Interfaz visual (Streamlit) del sistema de gestión de la panadería.
No contiene lógica de negocio: solo llama a las funciones ya definidas
en db.py, ingredientes.py, recetas.py y caja.py y las muestra en pantalla.

Para ejecutar:
    streamlit run app.py
"""

from datetime import date

import pandas as pd
import streamlit as st

from db import inicializar_db
import auth
import ingredientes as mod_ing
import recetas as mod_rec
import caja as mod_caja
import costos_indirectos as mod_costos
import produccion as mod_prod
import pedidos as mod_pedidos
import clientes as mod_clientes
import dashboard as mod_dash

st.set_page_config(page_title="Panadería · Gestión", page_icon="🥖", layout="wide")

if not st.session_state.get("usuario"):
    auth.mostrar_login()
    st.stop()


@st.cache_resource
def _inicializar_db_una_vez():
    # Streamlit vuelve a ejecutar todo este script en cada interacción
    # (incluido cambiar de pestaña en el sidebar) — sin este cache,
    # inicializar_db() mandaría ~14 sentencias SQL (crear las 11 tablas +
    # 3 inserts de configuración) contra Supabase en cada click, aunque
    # el esquema ya exista (~2s de más por navegación). Con @st.cache_resource
    # corre una sola vez por proceso, no una vez por rerun.
    inicializar_db()
    return True


_inicializar_db_una_vez()


# --- Helpers comunes -----------------------------------------------------

def mostrar_error(e: Exception):
    st.error(f"Error: {e}")


def selector_ingrediente(label: str, key: str):
    """Devuelve (id, dict) del ingrediente elegido en un selectbox, o (None, None)."""
    ings = mod_ing.listar_ingredientes()
    if not ings:
        st.info("No hay ingredientes registrados todavía.")
        return None, None
    opciones = {f"{i['nombre']} (#{i['id']})": i for i in ings}
    elegido = st.selectbox(label, list(opciones.keys()), key=key)
    ing = opciones[elegido]
    return ing["id"], ing


def selector_receta(label: str, key: str, solo_activas: bool = False):
    recetas = mod_rec.listar_recetas(solo_activas=solo_activas)
    if not recetas:
        st.info("No hay recetas registradas todavía.")
        return None
    opciones = {f"{r['nombre']} (#{r['id']})": r["id"] for r in recetas}
    elegida = st.selectbox(label, list(opciones.keys()), key=key)
    return opciones[elegida]


def selector_cliente(label: str, key: str):
    clientes = mod_clientes.listar_clientes()
    if not clientes:
        st.info("No hay clientes registrados todavía. Agrega uno en la sección Clientes.")
        return None
    opciones = {f"{c['nombre']} (#{c['id']})": c["id"] for c in clientes}
    elegido = st.selectbox(label, list(opciones.keys()), key=key)
    return opciones[elegido]


def selector_pedido(label: str, key: str, estado: str | None = None):
    pedidos = mod_pedidos.listar_pedidos(estado=estado)
    if not pedidos:
        st.info("No hay pedidos para mostrar.")
        return None
    opciones = {
        f"#{p['id']} · {p['cliente_nombre']} · entrega {p['fecha_entrega']} · {p['estado']}": p["id"]
        for p in pedidos
    }
    elegido = st.selectbox(label, list(opciones.keys()), key=key)
    return opciones[elegido]


# --- Sección: Ingredientes ------------------------------------------------

def seccion_ingredientes():
    st.header("🧂 Ingredientes")
    tab_listado, tab_agregar, tab_precio, tab_historial, tab_eliminar = st.tabs(
        ["Listado", "Agregar", "Actualizar precio", "Historial de precio", "Eliminar"]
    )

    with tab_listado:
        ings = mod_ing.listar_ingredientes()
        if not ings:
            st.info("No hay ingredientes cargados todavía.")
        else:
            busqueda = st.text_input("Buscar por nombre", key="buscar_ingrediente")
            if busqueda.strip():
                ings = [i for i in ings if busqueda.strip().lower() in i["nombre"].lower()]
            if not ings:
                st.info("Ningún ingrediente coincide con la búsqueda.")
            else:
                df = pd.DataFrame(ings)[
                    ["id", "nombre", "unidad_base", "precio_actual", "proveedor", "fecha_actualizacion"]
                ]
                st.dataframe(df, width='stretch', hide_index=True)

    with tab_agregar:
        with st.form("form_agregar_ingrediente", clear_on_submit=True):
            nombre = st.text_input("Nombre (ej. Harina 000)")
            unidad = st.selectbox("Unidad base", ["gr", "ml", "unidad"])
            precio = st.number_input("Precio actual", min_value=0.0, step=1.0)
            proveedor = st.text_input("Proveedor (opcional)")
            enviado = st.form_submit_button("Guardar ingrediente")
        if enviado:
            try:
                ing_id = mod_ing.agregar_ingrediente(nombre, unidad, precio, proveedor or None)
                st.success(f"Ingrediente creado con id {ing_id}")
            except Exception as e:
                mostrar_error(e)

    with tab_precio:
        ing_id, ing = selector_ingrediente("Ingrediente a actualizar", "sel_precio")
        if ing_id is not None:
            st.caption(f"Precio actual: ${ing['precio_actual']:.2f} / {ing['unidad_base']}")
            with st.form("form_actualizar_precio"):
                nuevo_precio = st.number_input("Nuevo precio", min_value=0.0, step=1.0)
                enviado = st.form_submit_button("Actualizar precio")
            if enviado:
                try:
                    mod_ing.actualizar_precio(ing_id, nuevo_precio)
                    st.success("Precio actualizado (queda registrado en el historial).")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

            st.divider()
            st.caption(f"Proveedor actual: {ing['proveedor'] or '—'}")
            with st.form("form_actualizar_proveedor"):
                nuevo_proveedor = st.text_input("Proveedor", value=ing["proveedor"] or "")
                enviado_prov = st.form_submit_button("Actualizar proveedor")
            if enviado_prov:
                try:
                    mod_ing.actualizar_proveedor(ing_id, nuevo_proveedor or None)
                    st.success("Proveedor actualizado.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

    with tab_historial:
        ing_id, _ = selector_ingrediente("Ingrediente", "sel_historial")
        if ing_id is not None:
            historial = mod_ing.historial_de_precio(ing_id)
            if not historial:
                st.info("Sin historial todavía.")
            else:
                df = pd.DataFrame(historial)
                st.line_chart(df.set_index("fecha")["precio"])
                st.dataframe(df, width='stretch', hide_index=True)

                st.subheader("Eliminar un registro (ej. un precio cargado por error)")
                opciones_borrar = {f"#{h['id']} · {h['fecha']} · ${h['precio']:.2f}": h["id"] for h in historial}
                col_sel, col_btn = st.columns([3, 1])
                registro_a_borrar = col_sel.selectbox(
                    "Registro a eliminar", list(opciones_borrar.keys()), key="sel_borrar_historial"
                )
                if col_btn.button("Eliminar registro", type="secondary"):
                    try:
                        mod_ing.eliminar_registro_historial(opciones_borrar[registro_a_borrar])
                        st.success("Registro eliminado del historial.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

    with tab_eliminar:
        ing_id, ing = selector_ingrediente("Ingrediente a eliminar", "sel_eliminar_ing")
        if ing_id is not None:
            st.caption(
                f"{ing['nombre']} · {ing['unidad_base']} · ${ing['precio_actual']:.2f} · "
                f"proveedor: {ing['proveedor'] or '—'}"
            )
            recetas_usan = mod_ing.recetas_que_usan_ingrediente(ing_id)
            if recetas_usan:
                nombres = ", ".join(r["nombre"] for r in recetas_usan)
                st.warning(
                    f"No se puede eliminar: está en uso en {len(recetas_usan)} receta(s): {nombres}. "
                    "Quítalo de esas recetas (pestaña Recetas → Agregar ingrediente) si de verdad quieres borrarlo."
                )
            else:
                st.info("Este ingrediente no está siendo usado en ninguna receta, se puede eliminar.")
                confirmar = st.checkbox(f"Confirmo que quiero eliminar '{ing['nombre']}' definitivamente")
                if st.button("Eliminar ingrediente", type="secondary", disabled=not confirmar):
                    try:
                        mod_ing.eliminar_ingrediente(ing_id)
                        st.success(f"Ingrediente '{ing['nombre']}' eliminado.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)


# --- Sección: Recetas -------------------------------------------------

def seccion_recetas():
    st.header("🍞 Recetas")
    tab_reporte, tab_crear, tab_ingredientes, tab_detalle = st.tabs(
        ["Reporte de rentabilidad", "Crear receta", "Editar ingredientes", "Detalle de receta"]
    )

    with tab_reporte:
        solo_activas = st.checkbox("Solo recetas activas", value=True)
        recetas = mod_rec.listar_recetas(solo_activas=solo_activas)
        if not recetas:
            st.info("No hay recetas para mostrar.")
        else:
            df = pd.DataFrame(recetas)[
                ["nombre", "costo_directo", "costo_total", "precio_venta", "ganancia",
                 "margen_real", "margen_objetivo", "bajo_margen"]
            ]
            df["margen_real"] = (df["margen_real"] * 100).round(1)
            df["margen_objetivo"] = (df["margen_objetivo"] * 100).round(1)

            def resaltar_bajo_margen(fila):
                color = "background-color: #ffe3e3" if fila["bajo_margen"] else ""
                return [color] * len(fila)

            st.dataframe(
                df.style.apply(resaltar_bajo_margen, axis=1),
                width='stretch',
                hide_index=True,
            )

    with tab_crear:
        with st.form("form_crear_receta", clear_on_submit=True):
            nombre = st.text_input("Nombre del pan (ej. Marraqueta)")
            precio_venta = st.number_input("Precio de venta", min_value=0.0, step=1.0)
            margen = st.number_input("Margen objetivo (%)", min_value=0.0, max_value=99.0, value=40.0, step=1.0)
            notas = st.text_area("Notas (opcional)")
            st.caption("Mano de obra y luz (opcional, se puede completar después en 'Detalle de receta')")
            col_t, col_u = st.columns(2)
            tiempo = col_t.number_input("Minutos para preparar un lote", min_value=0.0, step=5.0)
            unidades_lote = col_u.number_input("Unidades que rinde ese lote", min_value=1, step=1, value=1)
            consumo_kwh = st.number_input(
                "Consumo del programa de la máquina para esta receta (kWh por lote)",
                min_value=0.0, step=0.1,
            )
            enviado = st.form_submit_button("Crear receta")
        if enviado:
            try:
                receta_id = mod_rec.crear_receta(
                    nombre, precio_venta, margen / 100, notas or None, tiempo, unidades_lote, consumo_kwh
                )
                st.success(f"Receta creada con id {receta_id}. Ahora agrégale ingredientes en la pestaña siguiente.")
            except Exception as e:
                mostrar_error(e)

    with tab_ingredientes:
        receta_id = selector_receta("Receta", "sel_receta_ing")
        if receta_id is not None:
            try:
                d = mod_rec.detalle_receta(receta_id)
            except Exception as e:
                mostrar_error(e)
                return

            st.subheader("Ingredientes actuales")
            if d["ingredientes"]:
                st.dataframe(pd.DataFrame(d["ingredientes"]), width='stretch', hide_index=True)

                col_sel, col_btn = st.columns([3, 1])
                opciones_quitar = {i["nombre"]: i["nombre"] for i in d["ingredientes"]}
                nombre_a_quitar = col_sel.selectbox(
                    "Ingrediente a quitar", list(opciones_quitar.keys()), key="sel_quitar_ing_receta"
                )
                if col_btn.button("Quitar de la receta", type="secondary"):
                    ing_a_quitar = mod_ing.buscar_ingrediente_por_nombre(nombre_a_quitar)
                    try:
                        mod_rec.quitar_ingrediente_de_receta(receta_id, ing_a_quitar["id"])
                        st.success(f"'{nombre_a_quitar}' quitado de la receta.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)
            else:
                st.info("Esta receta todavía no tiene ingredientes.")

            st.subheader("Agregar o actualizar cantidad")
            ing_id, ing = selector_ingrediente("Ingrediente", "sel_ing_para_receta")
            if ing_id is not None:
                unidad = ing["unidad_base"]
                with st.form("form_agregar_ing_receta"):
                    cantidad = st.number_input(f"Cantidad usada (en {unidad})", min_value=0.0, step=1.0)
                    enviado = st.form_submit_button("Agregar/actualizar en la receta")
                if enviado:
                    try:
                        mod_rec.agregar_ingrediente_a_receta(receta_id, ing_id, cantidad)
                        st.success("Ingrediente agregado/actualizado en la receta.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

    with tab_detalle:
        receta_id = selector_receta("Receta", "sel_receta_detalle")
        if receta_id is not None:
            try:
                d = mod_rec.detalle_receta(receta_id)
            except Exception as e:
                mostrar_error(e)
                return

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Costo total", f"${d['costo_total']:.2f}")
            col2.metric("Precio de venta", f"${d['precio_venta']:.2f}")
            col3.metric("Ganancia", f"${d['ganancia']:.2f}")
            col4.metric(
                "Margen real",
                f"{d['margen_real'] * 100:.1f}%",
                delta=f"objetivo {d['margen_objetivo'] * 100:.1f}%",
            )
            if d["bajo_margen"]:
                st.warning("⚠ Esta receta está por debajo del margen objetivo.")

            col_precio, col_margen = st.columns(2)

            with col_precio:
                st.subheader("Precio de venta")
                with st.form("form_precio_venta_detalle"):
                    nuevo_precio_venta = st.number_input(
                        "Nuevo precio de venta", min_value=0.0, step=1.0,
                        value=float(d["precio_venta"]),
                    )
                    enviado_precio = st.form_submit_button("Actualizar precio de venta")
                if enviado_precio:
                    try:
                        mod_rec.actualizar_precio_venta(receta_id, nuevo_precio_venta)
                        st.success("Precio de venta actualizado.")
                        st.caption("Los pedidos ya tomados no cambian: quedan con el precio congelado al momento de agregarse.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

            with col_margen:
                st.subheader("Margen objetivo")
                with st.form("form_margen_objetivo_detalle"):
                    nuevo_margen = st.number_input(
                        "Nuevo margen objetivo (%)", min_value=0.0, max_value=99.0, step=1.0,
                        value=float(d["margen_objetivo"] * 100),
                    )
                    enviado_margen = st.form_submit_button("Actualizar margen objetivo")
                if enviado_margen:
                    try:
                        mod_rec.actualizar_margen_objetivo(receta_id, nuevo_margen / 100)
                        st.success("Margen objetivo actualizado.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

            st.subheader("Desglose del costo")
            df_desglose = pd.DataFrame([
                {"Componente": "Ingredientes (directo)", "Monto": d["costo_directo"]},
                {"Componente": "Luz", "Monto": d["costo_indirecto_luz"]},
                {"Componente": "Empaque", "Monto": d["costo_empaque"]},
                {"Componente": "Mano de obra", "Monto": d["costo_mano_obra"]},
                {"Componente": "Costo total", "Monto": d["costo_total"]},
            ])
            st.dataframe(df_desglose, width='stretch', hide_index=True)

            if d["ingredientes"]:
                st.subheader("Ingredientes")
                st.dataframe(pd.DataFrame(d["ingredientes"]), width='stretch', hide_index=True)
            else:
                st.info("Esta receta todavía no tiene ingredientes.")

            st.subheader("Mano de obra de esta receta")
            st.caption(
                f"Actual: {d['tiempo_preparacion_min']:.0f} min por lote de {d['unidades_por_lote']} unidades"
            )
            with st.form("form_mano_obra_detalle"):
                col_t, col_u = st.columns(2)
                tiempo = col_t.number_input(
                    "Minutos para preparar un lote", min_value=0.0, step=5.0,
                    value=float(d["tiempo_preparacion_min"]),
                )
                unidades_lote = col_u.number_input(
                    "Unidades que rinde ese lote", min_value=1, step=1,
                    value=int(d["unidades_por_lote"]),
                )
                enviado = st.form_submit_button("Actualizar mano de obra")
            if enviado:
                try:
                    mod_rec.actualizar_mano_obra(receta_id, tiempo, unidades_lote)
                    st.success("Mano de obra actualizada.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

            st.subheader("Luz de esta receta")
            st.caption(
                f"Actual: {d['consumo_kwh_programa']:.2f} kWh por lote de {d['unidades_por_lote']} unidades "
                f"(programa de la máquina de pan que usa esta receta)"
            )
            with st.form("form_luz_detalle"):
                consumo_kwh = st.number_input(
                    "Consumo del programa (kWh por lote)", min_value=0.0, step=0.1,
                    value=float(d["consumo_kwh_programa"]),
                )
                enviado = st.form_submit_button("Actualizar luz")
            if enviado:
                try:
                    mod_rec.actualizar_luz(receta_id, consumo_kwh)
                    st.success("Luz actualizada.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)


# --- Sección: Flujo de caja ------------------------------------------------

def seccion_caja():
    st.header("💰 Flujo de caja")
    tab_ingreso, tab_gasto, tab_movs, tab_reporte, tab_comisiones = st.tabs(
        ["Registrar ingreso", "Registrar gasto", "Movimientos", "Reporte por período", "Comisiones"]
    )

    def form_movimiento(tipo: str, key_prefix: str):
        with st.form(f"form_{key_prefix}", clear_on_submit=True):
            monto = st.number_input("Monto", min_value=0.0, step=100.0)
            medio = st.selectbox("Medio de pago", mod_caja.MEDIOS_VALIDOS)
            categoria = st.text_input("Categoría (opcional)")
            descripcion = st.text_input("Descripción (opcional)")
            fecha = st.date_input("Fecha", value=date.today())
            enviado = st.form_submit_button(f"Registrar {tipo}")
        if enviado:
            try:
                mov_id = mod_caja.registrar_movimiento(
                    tipo, monto, medio, categoria or None, descripcion or None, fecha.isoformat()
                )
                st.success(f"{tipo.capitalize()} registrado con id {mov_id}")
            except Exception as e:
                mostrar_error(e)

    with tab_ingreso:
        form_movimiento("ingreso", "ingreso")

    with tab_gasto:
        form_movimiento("gasto", "gasto")

    with tab_movs:
        col1, col2 = st.columns(2)
        desde = col1.date_input("Desde", value=None, key="movs_desde")
        hasta = col2.date_input("Hasta", value=None, key="movs_hasta")
        movimientos = mod_caja.listar_movimientos(
            desde=desde.isoformat() if desde else None,
            hasta=hasta.isoformat() if hasta else None,
        )
        if not movimientos:
            st.info("No hay movimientos en ese rango.")
        else:
            st.dataframe(pd.DataFrame(movimientos), width='stretch', hide_index=True)
            ids = [m["id"] for m in movimientos]
            col_a, col_b = st.columns([3, 1])
            mov_a_eliminar = col_a.selectbox("Id a eliminar", ids, key="mov_eliminar")
            if col_b.button("Eliminar", type="secondary"):
                try:
                    mod_caja.eliminar_movimiento(mov_a_eliminar)
                    st.success("Movimiento eliminado.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

    with tab_reporte:
        col1, col2 = st.columns(2)
        desde = col1.date_input("Desde", value=None, key="rep_desde")
        hasta = col2.date_input("Hasta", value=None, key="rep_hasta")
        r = mod_caja.resumen_periodo(
            desde=desde.isoformat() if desde else None,
            hasta=hasta.isoformat() if hasta else None,
        )

        col1, col2, col3 = st.columns(3)
        col1.metric("Total ingresos", f"${r['total_ingresos']:.2f}")
        col2.metric("Total gastos", f"${r['total_gastos']:.2f}")
        col3.metric("Saldo", f"${r['saldo']:.2f}")
        st.caption(f"{r['cantidad_movimientos']} movimientos en el período")

        col_izq, col_der = st.columns(2)
        with col_izq:
            st.subheader("Por medio de pago")
            df_medio = pd.DataFrame(r["por_medio_pago"]).T
            st.bar_chart(df_medio)
            st.dataframe(df_medio, width='stretch')
        with col_der:
            st.subheader("Por categoría")
            df_cat = pd.DataFrame(r["por_categoria"]).T
            if df_cat.empty:
                st.info("Sin movimientos categorizados en el período.")
            else:
                st.dataframe(df_cat, width='stretch')

    with tab_comisiones:
        st.caption(
            "Tasas que cobra el medio de pago electrónico (ej. Mercado Pago Point) al "
            "cobrar con tarjeta. Al marcar un pedido como 'entregado y cobrado' con débito "
            "o crédito, se registra automáticamente un gasto aparte por esta comisión, "
            "junto al ingreso por el total del pedido. Actualiza estos valores el día que "
            "cambies de tramo de ventas con el proveedor. La transferencia y el efectivo "
            "no tienen comisión."
        )
        config_comisiones = mod_caja.obtener_configuracion_comisiones()
        with st.form("form_comisiones"):
            tasa_debito = st.number_input(
                "Comisión débito, % del monto cobrado (sin IVA)",
                min_value=0.0, max_value=100.0, step=0.01,
                value=float(config_comisiones["tasa_debito_pct"] * 100),
            )
            tasa_credito = st.number_input(
                "Comisión crédito, % del monto cobrado (sin IVA)",
                min_value=0.0, max_value=100.0, step=0.01,
                value=float(config_comisiones["tasa_credito_pct"] * 100),
            )
            iva = st.number_input(
                "IVA sobre la comisión, %",
                min_value=0.0, max_value=100.0, step=1.0,
                value=float(config_comisiones["iva_pct"] * 100),
            )
            enviado = st.form_submit_button("Guardar")
        if enviado:
            try:
                mod_caja.actualizar_configuracion_comisiones(tasa_debito / 100, tasa_credito / 100, iva / 100)
                st.success("Comisiones actualizadas.")
                st.rerun()
            except Exception as e:
                mostrar_error(e)

        ejemplo_monto = 10000
        comision_debito_ejemplo = mod_caja.calcular_comision(ejemplo_monto, "debito")
        comision_credito_ejemplo = mod_caja.calcular_comision(ejemplo_monto, "credito")
        st.caption(
            f"Ejemplo: por un cobro de \\${ejemplo_monto:,.0f}, la comisión sería "
            f"\\${comision_debito_ejemplo:,.2f} con débito o \\${comision_credito_ejemplo:,.2f} con crédito."
        )


# --- Sección: Costos indirectos --------------------------------------------

def seccion_costos_indirectos():
    st.header("⚡ Costos indirectos")
    st.caption(
        "Estos valores se aplican automáticamente al costeo de todas las recetas "
        "(ver el desglose en Recetas → Detalle de receta)."
    )
    config = mod_costos.obtener_configuracion()

    with st.form("form_costos_indirectos"):
        tarifa_electrica = st.number_input(
            "Tarifa eléctrica ($/kWh)",
            min_value=0.0, step=1.0,
            value=float(config["tarifa_electrica_kwh"]),
        )
        factor_descuento_luz = st.number_input(
            "Factor de descuento sobre el consumo teórico del programa (%) — "
            "la resistencia cicla por termostato así que el consumo real es menor al nominal",
            min_value=0.0, max_value=100.0, step=5.0,
            value=float(config["factor_descuento_luz"] * 100),
        )
        costo_empaque = st.number_input(
            "Costo de empaque por unidad vendida (bolsa, caja, etc.) — igual para todas las recetas",
            min_value=0.0, step=1.0,
            value=float(config["costo_empaque_unidad"]),
        )
        valor_hora = st.number_input(
            "Valor de tu hora de trabajo (mano de obra)",
            min_value=0.0, step=100.0,
            value=float(config["valor_hora_mano_obra"]),
        )
        enviado = st.form_submit_button("Guardar configuración")

    if enviado:
        try:
            mod_costos.actualizar_configuracion(
                costo_empaque, valor_hora, tarifa_electrica, factor_descuento_luz / 100
            )
            st.success("Configuración de costos indirectos actualizada.")
            st.rerun()
        except Exception as e:
            mostrar_error(e)

    st.info(
        "El costo de luz (consumo del programa de la máquina, en kWh) y el de mano de "
        "obra (minutos por lote y unidades que rinde) son propios de cada receta y se "
        "configuran en Recetas → Detalle de receta."
    )


# --- Sección: Pedidos ------------------------------------------------------

def seccion_pedidos():
    st.header("📋 Pedidos")
    # Selector en vez de st.tabs: st.tabs ejecuta el contenido de TODAS las
    # pestañas en cada interacción, y contra Supabase eso son decenas de
    # consultas por click. Con este selector solo corre la sección activa.
    vista = st.radio(
        "Sección",
        ["Planificación", "Agenda", "Crear pedido", "Agregar ítems", "Detalle / Cobrar", "Capacidad de producción"],
        horizontal=True,
        label_visibility="collapsed",
        key="vista_pedidos",
    )

    if vista == "Planificación":
        st.subheader("Próximos días")
        dias = st.slider("Ver los próximos... días", min_value=7, max_value=30, value=14, key="dias_planificacion")
        resumen_dias = mod_pedidos.resumen_proximos_dias(dias)
        df_dias = pd.DataFrame(resumen_dias).set_index("fecha")
        st.bar_chart(df_dias["unidades_totales"])
        st.caption("Unidades totales pedidas por día de entrega (no cuenta pedidos cancelados).")
        st.dataframe(df_dias, width='stretch')

        st.divider()
        st.subheader("Detalle de un día")
        fecha_sel = st.date_input("Fecha de entrega", value=date.today(), key="fecha_planificacion_detalle")
        resumen = mod_pedidos.resumen_dia(fecha_sel.isoformat())

        col1, col2 = st.columns(2)
        col1.metric("Pedidos ese día", resumen["cantidad_pedidos"])
        col2.metric("Total a cobrar", f"${resumen['total_a_cobrar']:.2f}")

        cap = mod_prod.capacidad_dia(fecha_sel.isoformat())
        texto_capacidad = f"Capacidad: {cap['comprometido_min']:.0f} / {cap['disponible_min']:.0f} min usados"
        if cap["sobrevendido"]:
            st.warning(f"⚠ {texto_capacidad} — este día está sobrevendido.")
        else:
            st.caption(texto_capacidad)

        if resumen["items_agregados"]:
            st.subheader("Qué preparar ese día")
            df_items = pd.DataFrame(resumen["items_agregados"]).set_index("receta")
            st.bar_chart(df_items["cantidad_total"])
            st.dataframe(df_items, width='stretch')

            st.subheader("Pedidos de ese día")
            for p in resumen["pedidos"]:
                with st.expander(f"#{p['id']} · {p['cliente_nombre']} · ${p['total']:.2f} · {p['estado']}"):
                    st.dataframe(pd.DataFrame(p["items"]), width='stretch', hide_index=True)
                    if p["notas"]:
                        st.caption(f"Notas: {p['notas']}")
        else:
            st.info("No hay pedidos para este día.")

    elif vista == "Agenda":
        col1, col2, col3 = st.columns(3)
        desde = col1.date_input("Desde", value=None, key="ped_desde")
        hasta = col2.date_input("Hasta", value=None, key="ped_hasta")
        opciones_estado = ["Pendientes y confirmados", "(todos)"] + list(mod_pedidos.ESTADOS_VALIDOS)
        estado = col3.selectbox("Estado", opciones_estado, key="ped_filtro_estado")

        if estado == "Pendientes y confirmados":
            pedidos = [
                p for p in mod_pedidos.listar_pedidos(
                    desde=desde.isoformat() if desde else None,
                    hasta=hasta.isoformat() if hasta else None,
                )
                if p["estado"] not in ("entregado", "cancelado")
            ]
        else:
            pedidos = mod_pedidos.listar_pedidos(
                desde=desde.isoformat() if desde else None,
                hasta=hasta.isoformat() if hasta else None,
                estado=None if estado == "(todos)" else estado,
            )

        if not pedidos:
            st.info("No hay pedidos en ese rango.")
        else:
            st.caption(f"{len(pedidos)} pedido(s), agrupados por fecha de entrega. Abre uno para ver su desglose de ítems.")
            fecha_agrupada = None
            for p in pedidos:
                if p["fecha_entrega"] != fecha_agrupada:
                    fecha_agrupada = p["fecha_entrega"]
                    st.markdown(f"**📅 {fecha_agrupada}**")

                titulo = f"#{p['id']} · {p['cliente_nombre']} · ${p['total']:.2f} · {p['estado']}"
                if p["pagado"]:
                    titulo += " · pagado"
                with st.expander(titulo):
                    if p["items"]:
                        st.dataframe(
                            pd.DataFrame(p["items"])[["nombre", "cantidad", "precio_unitario", "subtotal"]],
                            width='stretch', hide_index=True,
                        )
                    else:
                        st.caption("Este pedido todavía no tiene ítems.")
                    if p["notas"]:
                        st.caption(f"Notas: {p['notas']}")
                    if p["cliente_telefono"]:
                        st.caption(f"Teléfono: {p['cliente_telefono']}")

            with st.expander("Ver como tabla resumen"):
                df = pd.DataFrame(pedidos)[
                    ["id", "fecha_entrega", "cliente_nombre", "cliente_telefono",
                     "estado", "pagado", "total"]
                ]
                st.dataframe(df, width='stretch', hide_index=True)

        st.divider()
        st.subheader("Reagendar varios pedidos de un mismo día")
        st.caption(
            "Por ejemplo, si un día se cae la producción por fuerza mayor: mueve de una "
            "sola vez todos los pedidos de ese día (pendientes/confirmados) a otra fecha."
        )
        col1, col2 = st.columns(2)
        fecha_origen = col1.date_input("Fecha actual de esos pedidos", value=date.today(), key="ped_reag_origen")
        fecha_destino = col2.date_input("Nueva fecha de entrega", value=date.today(), key="ped_reag_destino")

        pedidos_a_mover = [
            p for p in mod_pedidos.listar_pedidos(desde=fecha_origen.isoformat(), hasta=fecha_origen.isoformat())
            if p["estado"] not in ("entregado", "cancelado")
        ]
        if not pedidos_a_mover:
            st.info(f"No hay pedidos pendientes/confirmados el {fecha_origen.isoformat()} para reagendar.")
        else:
            st.write(f"Se reagendarán **{len(pedidos_a_mover)}** pedido(s):")
            df_mover = pd.DataFrame(pedidos_a_mover)[
                ["id", "cliente_nombre", "estado", "total"]
            ]
            st.dataframe(df_mover, width='stretch', hide_index=True)

            if st.button(f"Reagendar estos {len(pedidos_a_mover)} pedidos al {fecha_destino.isoformat()}"):
                try:
                    ids = mod_pedidos.reagendar_pedidos_por_fecha(
                        fecha_origen.isoformat(), fecha_destino.isoformat()
                    )
                    st.success(f"Pedidos reagendados: {', '.join('#' + str(i) for i in ids)}.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

    elif vista == "Crear pedido":
        clientes_existentes = mod_clientes.listar_clientes()
        modo_cliente = st.radio(
            "Cliente",
            ["Elegir existente", "Crear nuevo"],
            horizontal=True,
            index=0 if clientes_existentes else 1,
            key="modo_cliente_pedido",
        )

        cliente_id = None
        if modo_cliente == "Elegir existente":
            cliente_id = selector_cliente("Cliente", "sel_cliente_pedido")
        else:
            st.caption("Se creará una ficha nueva en Clientes con estos datos.")

        with st.form("form_crear_pedido", clear_on_submit=True):
            if modo_cliente == "Crear nuevo":
                nuevo_nombre = st.text_input("Nombre del cliente", key="nuevo_cliente_nombre_pedido")
                nuevo_telefono = st.text_input("Teléfono (opcional)", key="nuevo_cliente_telefono_pedido")
                nuevo_direccion = st.text_input("Dirección (opcional)", key="nuevo_cliente_direccion_pedido")
            fecha_entrega = st.date_input("Fecha de entrega", value=date.today())
            notas = st.text_area("Notas (opcional)")
            enviado = st.form_submit_button("Crear pedido")

        if enviado:
            try:
                if modo_cliente == "Crear nuevo":
                    cliente_id = mod_clientes.crear_cliente(
                        nuevo_nombre, nuevo_telefono or None, nuevo_direccion or None
                    )
                elif cliente_id is None:
                    raise ValueError("Selecciona un cliente")

                pedido_id = mod_pedidos.crear_pedido(cliente_id, fecha_entrega.isoformat(), notas or None)
                mensaje = f"Pedido #{pedido_id} creado. Agrégale ítems aquí mismo abajo."
                if modo_cliente == "Crear nuevo":
                    mensaje = f"Cliente '{nuevo_nombre}' creado. " + mensaje
                st.success(mensaje)
                st.session_state["pedido_en_construccion"] = pedido_id
            except Exception as e:
                mostrar_error(e)

        pedido_nuevo_id = st.session_state.get("pedido_en_construccion")
        if pedido_nuevo_id is not None:
            try:
                pedido_nuevo = mod_pedidos.detalle_pedido(pedido_nuevo_id)
            except ValueError:
                # El pedido ya no existe (por ejemplo, se eliminó desde Detalle / Cobrar).
                del st.session_state["pedido_en_construccion"]
                pedido_nuevo = None

            if pedido_nuevo is not None:
                st.divider()
                st.subheader(f"Ítems del pedido #{pedido_nuevo_id} · {pedido_nuevo['cliente_nombre']}")
                st.caption(f"Entrega: {pedido_nuevo['fecha_entrega']}")

                receta_id = selector_receta("Receta", "sel_receta_pedido_nuevo")
                if receta_id is not None:
                    cantidad = st.number_input("Cantidad", min_value=1, step=1, key="cant_item_pedido_nuevo")

                    disponibilidad = mod_prod.verificar_disponibilidad(
                        pedido_nuevo["fecha_entrega"], receta_id, cantidad, excluir_pedido_id=pedido_nuevo_id
                    )
                    if not disponibilidad["cabe"]:
                        st.warning(
                            f"⚠ Esto sobrepasa tu capacidad para el {pedido_nuevo['fecha_entrega']}: "
                            f"necesita {disponibilidad['tiempo_necesario_min']:.0f} min y solo "
                            f"quedan {disponibilidad['libre_min']:.0f} min libres ese día. "
                            "Puedes agregarlo igual si decides sobrevender a propósito."
                        )

                    if st.button("Agregar/actualizar ítem", key="btn_agregar_item_pedido_nuevo"):
                        try:
                            mod_pedidos.agregar_item_pedido(pedido_nuevo_id, receta_id, cantidad)
                            st.success("Ítem agregado/actualizado en el pedido.")
                            st.rerun()
                        except Exception as e:
                            mostrar_error(e)

                if pedido_nuevo["items"]:
                    st.dataframe(pd.DataFrame(pedido_nuevo["items"]), width='stretch', hide_index=True)
                    st.metric("Total del pedido", f"${pedido_nuevo['total']:.2f}")

                if st.button("Terminar y crear otro pedido"):
                    del st.session_state["pedido_en_construccion"]
                    st.rerun()

    elif vista == "Agregar ítems":
        pedido_id = selector_pedido("Pedido", "sel_pedido_items")
        if pedido_id is not None:
            pedido = mod_pedidos.detalle_pedido(pedido_id)
            if pedido["estado"] in ("entregado", "cancelado"):
                st.warning(f"Este pedido ya está '{pedido['estado']}', no se puede seguir editando.")
            else:
                receta_id = selector_receta("Receta", "sel_receta_para_pedido")
                if receta_id is not None:
                    cantidad = st.number_input("Cantidad", min_value=1, step=1, key="cant_item_pedido")

                    disponibilidad = mod_prod.verificar_disponibilidad(
                        pedido["fecha_entrega"], receta_id, cantidad, excluir_pedido_id=pedido_id
                    )
                    if not disponibilidad["cabe"]:
                        st.warning(
                            f"⚠ Esto sobrepasa tu capacidad para el {pedido['fecha_entrega']}: "
                            f"necesita {disponibilidad['tiempo_necesario_min']:.0f} min y solo "
                            f"quedan {disponibilidad['libre_min']:.0f} min libres ese día. "
                            "Puedes agregarlo igual si decides sobrevender a propósito."
                        )

                    if st.button("Agregar/actualizar ítem"):
                        try:
                            mod_pedidos.agregar_item_pedido(pedido_id, receta_id, cantidad)
                            st.success("Ítem agregado/actualizado en el pedido.")
                            st.rerun()
                        except Exception as e:
                            mostrar_error(e)

            if pedido["items"]:
                st.subheader("Ítems actuales del pedido")
                st.dataframe(pd.DataFrame(pedido["items"]), width='stretch', hide_index=True)
                st.metric("Total del pedido", f"${pedido['total']:.2f}")

                if pedido["estado"] not in ("entregado", "cancelado"):
                    col_sel, col_btn = st.columns([3, 1])
                    opciones_quitar = {i["nombre"]: i["receta_id"] for i in pedido["items"]}
                    nombre_a_quitar = col_sel.selectbox(
                        "Ítem a quitar", list(opciones_quitar.keys()), key="sel_quitar_item_pedido"
                    )
                    if col_btn.button("Quitar ítem", type="secondary"):
                        try:
                            mod_pedidos.quitar_item_pedido(pedido_id, opciones_quitar[nombre_a_quitar])
                            st.success(f"'{nombre_a_quitar}' quitado del pedido.")
                            st.rerun()
                        except Exception as e:
                            mostrar_error(e)

    elif vista == "Detalle / Cobrar":
        opciones_estado_detalle = list(mod_pedidos.ESTADOS_VALIDOS) + ["(todos)"]
        estado_filtro_detalle = st.selectbox(
            "Filtrar por estado", opciones_estado_detalle, index=0, key="detalle_filtro_estado"
        )
        pedido_id = selector_pedido(
            "Pedido", "sel_pedido_detalle",
            estado=None if estado_filtro_detalle == "(todos)" else estado_filtro_detalle,
        )
        if pedido_id is not None:
            pedido = mod_pedidos.detalle_pedido(pedido_id)

            col1, col2, col3 = st.columns(3)
            col1.metric("Cliente", pedido["cliente_nombre"])
            col2.metric("Fecha de entrega", pedido["fecha_entrega"])
            col3.metric("Total", f"${pedido['total']:.2f}")
            st.caption(f"Estado: {pedido['estado']} · Pagado: {'sí' if pedido['pagado'] else 'no'}")
            if pedido["notas"]:
                st.caption(f"Notas: {pedido['notas']}")

            if pedido["items"]:
                st.dataframe(pd.DataFrame(pedido["items"]), width='stretch', hide_index=True)

                st.subheader("Resumen para WhatsApp")
                st.caption("Cópialo y pégalo en el chat del cliente para confirmar el pedido.")
                st.code(mod_pedidos.generar_resumen_whatsapp(pedido_id), language=None)
            else:
                st.info("Este pedido todavía no tiene ítems.")

            if pedido["estado"] not in ("entregado", "cancelado"):
                st.subheader("Reagendar")
                st.caption("Cambia la fecha de entrega sin perder el pedido, sus ítems ni su estado.")
                with st.form("form_reagendar_pedido"):
                    nueva_fecha = st.date_input(
                        "Nueva fecha de entrega",
                        value=date.fromisoformat(pedido["fecha_entrega"]),
                    )
                    enviado = st.form_submit_button("Reagendar pedido")
                if enviado:
                    try:
                        mod_pedidos.reagendar_pedido(pedido_id, nueva_fecha.isoformat())
                        st.success(f"Pedido #{pedido_id} reagendado al {nueva_fecha.isoformat()}.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

                if pedido["estado"] == "pendiente":
                    st.divider()
                    st.subheader("Confirmar pedido")
                    st.caption("Marca el pedido como confirmado con el cliente (sin cobrarlo todavía).")
                    if st.button("Confirmar pedido"):
                        try:
                            mod_pedidos.actualizar_estado(pedido_id, "confirmado")
                            st.success(f"Pedido #{pedido_id} confirmado.")
                            st.rerun()
                        except Exception as e:
                            mostrar_error(e)

                st.divider()
                st.subheader("Entregar y cobrar")
                st.caption("Marca el pedido como entregado y genera el ingreso en Flujo de caja automáticamente.")

                st.caption("Mensaje para avisar la entrega y el monto a pagar:")
                st.code(mod_pedidos.generar_mensaje_cobro_whatsapp(pedido_id), language=None)

                with st.expander("Si el cliente va a transferir: datos para copiar"):
                    datos_transferencia = st.secrets.get("datos_transferencia")
                    if datos_transferencia:
                        mensaje_transferencia = mod_pedidos.generar_mensaje_datos_transferencia_whatsapp(
                            datos_transferencia["nombre"],
                            datos_transferencia["rut"],
                            datos_transferencia["tipo_cuenta"],
                            datos_transferencia["numero_cuenta"],
                            datos_transferencia["email"],
                        )
                        st.code(mensaje_transferencia, language=None)
                    else:
                        st.warning(
                            "Configura tus datos de transferencia en .streamlit/secrets.toml "
                            "(sección [datos_transferencia]) para que aparezcan aquí."
                        )

                with st.form("form_cobrar_pedido"):
                    medio = st.selectbox("Medio de pago", mod_caja.MEDIOS_VALIDOS)
                    enviado = st.form_submit_button("Marcar entregado y cobrado")
                if enviado:
                    try:
                        resultado = mod_pedidos.entregar_y_cobrar(pedido_id, medio)
                        mensaje = (
                            f"Pedido entregado y cobrado. Ingreso "
                            f"#{resultado['movimiento_ingreso_id']} registrado en Caja."
                        )
                        if resultado["comision"] > 0:
                            mensaje += (
                                f" Se registró además un gasto de ${resultado['comision']:.2f} "
                                f"por comisión de {medio} (#{resultado['movimiento_gasto_comision_id']})."
                            )
                        st.success(mensaje)
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

                st.divider()
                if st.button("Cancelar pedido", type="secondary"):
                    try:
                        mod_pedidos.cancelar_pedido(pedido_id)
                        st.success("Pedido cancelado.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

            st.divider()
            st.subheader("Eliminar pedido")
            st.caption(
                "Para pedidos mal tomados o de prueba: borra el pedido y sus ítems por completo "
                "(a diferencia de Cancelar, no queda registro). No se puede si ya fue cobrado."
            )
            if pedido["pagado"]:
                st.warning(
                    "Este pedido ya fue cobrado y generó un ingreso en Flujo de caja. "
                    "Anula ese movimiento en Caja primero si de verdad quieres eliminarlo, "
                    "o usa 'Cancelar pedido' en su lugar."
                )
            else:
                confirmar_eliminar = st.checkbox(
                    f"Confirmo que quiero eliminar el pedido #{pedido_id} definitivamente"
                )
                if st.button("Eliminar pedido", type="secondary", disabled=not confirmar_eliminar):
                    try:
                        mod_pedidos.eliminar_pedido(pedido_id)
                        st.success(f"Pedido #{pedido_id} eliminado.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

    elif vista == "Capacidad de producción":
        config = mod_prod.obtener_configuracion()
        with st.form("form_capacidad"):
            horas = st.number_input(
                "Horas al día dedicadas a producir",
                min_value=0.0, step=0.5, value=float(config["horas_disponibles_dia"]),
            )
            enviado = st.form_submit_button("Guardar")
        if enviado:
            try:
                mod_prod.actualizar_configuracion(horas)
                st.success("Capacidad diaria actualizada.")
                st.rerun()
            except Exception as e:
                mostrar_error(e)

        st.divider()
        fecha_consulta = st.date_input("Ver capacidad de un día", value=date.today(), key="fecha_capacidad")
        cap = mod_prod.capacidad_dia(fecha_consulta.isoformat())
        col1, col2, col3 = st.columns(3)
        col1.metric("Disponible (min)", f"{cap['disponible_min']:.0f}")
        col2.metric("Comprometido (min)", f"{cap['comprometido_min']:.0f}")
        col3.metric("Libre (min)", f"{cap['libre_min']:.0f}")
        if cap["sobrevendido"]:
            st.warning("⚠ Este día ya está sobrevendido según tu capacidad configurada.")


# --- Sección: Clientes ------------------------------------------------------

def seccion_clientes():
    st.header("👥 Clientes")
    tab_listado, tab_agregar, tab_ficha, tab_reportes = st.tabs(
        ["Listado", "Agregar", "Ficha / Historial", "Reportes"]
    )

    with tab_listado:
        clientes = mod_clientes.listar_clientes()
        if not clientes:
            st.info("No hay clientes registrados todavía.")
        else:
            df = pd.DataFrame(clientes)[["id", "nombre", "telefono", "direccion", "fecha_creacion"]]
            st.dataframe(df, width='stretch', hide_index=True)

    with tab_agregar:
        with st.form("form_agregar_cliente", clear_on_submit=True):
            nombre = st.text_input("Nombre")
            telefono = st.text_input("Teléfono (opcional)")
            direccion = st.text_input("Dirección (opcional)")
            notas = st.text_area("Notas (opcional)")
            enviado = st.form_submit_button("Guardar cliente")
        if enviado:
            try:
                cliente_id = mod_clientes.crear_cliente(nombre, telefono or None, direccion or None, notas or None)
                st.success(f"Cliente creado con id {cliente_id}.")
            except Exception as e:
                mostrar_error(e)

    with tab_ficha:
        cliente_id = selector_cliente("Cliente", "sel_cliente_ficha")
        if cliente_id is not None:
            hist = mod_clientes.historial_cliente(cliente_id)

            col1, col2, col3 = st.columns(3)
            col1.metric("Pedidos totales", hist["cantidad_pedidos"])
            col2.metric("Total gastado (pagado)", f"${hist['total_gastado']:.2f}")
            col3.metric("Receta favorita", hist["receta_favorita"] or "—")
            if hist["telefono"] or hist["direccion"]:
                st.caption(f"Tel: {hist['telefono'] or '—'} · Dirección: {hist['direccion'] or '—'}")
            if hist["notas"]:
                st.caption(f"Notas: {hist['notas']}")

            st.subheader("Editar ficha")
            with st.form("form_editar_cliente"):
                nombre = st.text_input("Nombre", value=hist["nombre"])
                telefono = st.text_input("Teléfono", value=hist["telefono"] or "")
                direccion = st.text_input("Dirección", value=hist["direccion"] or "")
                notas = st.text_area("Notas", value=hist["notas"] or "")
                enviado = st.form_submit_button("Guardar cambios")
            if enviado:
                try:
                    mod_clientes.actualizar_cliente(
                        cliente_id, nombre, telefono or None, direccion or None, notas or None
                    )
                    st.success("Ficha actualizada.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

            st.subheader("Historial de pedidos")
            if hist["pedidos"]:
                st.dataframe(pd.DataFrame(hist["pedidos"]), width='stretch', hide_index=True)
            else:
                st.info("Este cliente todavía no tiene pedidos.")

    with tab_reportes:
        col_izq, col_der = st.columns(2)
        with col_izq:
            st.subheader("Quién compra más")
            top_clientes = mod_clientes.reporte_top_clientes()
            if not top_clientes:
                st.info("Todavía no hay pedidos pagados para armar este ranking.")
            else:
                st.dataframe(pd.DataFrame(top_clientes), width='stretch', hide_index=True)
        with col_der:
            st.subheader("Qué pan se pide más")
            productos = mod_pedidos.reporte_productos_populares()
            if not productos:
                st.info("Todavía no hay pedidos para armar este ranking.")
            else:
                df_prod = pd.DataFrame(productos).set_index("nombre")
                st.bar_chart(df_prod["unidades_pedidas"])
                st.dataframe(df_prod, width='stretch')


# --- Sección: Dashboard ----------------------------------------------------

NOMBRES_MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def seccion_dashboard():
    st.header("📊 Dashboard · Resumen del mes")

    col_mes, col_anio = st.columns(2)
    hoy = date.today()
    mes = col_mes.selectbox(
        "Mes", list(range(1, 13)), index=hoy.month - 1,
        format_func=lambda m: NOMBRES_MESES[m - 1], key="dash_mes",
    )
    anio = col_anio.number_input("Año", min_value=2020, max_value=2100, value=hoy.year, step=1, key="dash_anio")

    anio_ant, mes_ant = mod_dash.mes_anterior(anio, mes)

    ped = mod_dash.resumen_pedidos_mes(anio, mes)
    ped_ant = mod_dash.resumen_pedidos_mes(anio_ant, mes_ant)
    fin = mod_dash.resumen_financiero_mes(anio, mes)
    fin_ant = mod_dash.resumen_financiero_mes(anio_ant, mes_ant)

    st.caption(
        f"{NOMBRES_MESES[mes - 1]} {anio} · comparado contra "
        f"{NOMBRES_MESES[mes_ant - 1]} {anio_ant} · \"Pedidos\" cuenta por fecha en que se tomó el pedido."
    )

    if ped["total_pedidos"] == 0:
        st.info("No se tomaron pedidos este mes.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(
            "Pedidos tomados", ped["total_pedidos"],
            delta=ped["total_pedidos"] - ped_ant["total_pedidos"],
        )
        col2.metric(
            "Tasa de cumplimiento", f"{ped['tasa_cumplimiento'] * 100:.0f}%",
            delta=f"{(ped['tasa_cumplimiento'] - ped_ant['tasa_cumplimiento']) * 100:+.0f} pp",
        )
        col3.metric(
            "Ticket promedio", f"${ped['ticket_promedio']:.2f}",
            delta=f"${ped['ticket_promedio'] - ped_ant['ticket_promedio']:.2f}",
        )
        col4.metric(
            "Saldo de caja del mes", f"${fin['saldo']:.2f}",
            delta=f"${fin['saldo'] - fin_ant['saldo']:.2f}",
        )

        if ped["tasa_cancelacion"] > 0:
            st.caption(f"⚠ {ped['tasa_cancelacion'] * 100:.0f}% de los pedidos del mes se cancelaron.")

        st.subheader("Pedidos por estado")
        df_estado = pd.DataFrame(
            [{"estado": e, "cantidad": c} for e, c in ped["por_estado"].items()]
        ).set_index("estado")
        st.bar_chart(df_estado["cantidad"])

    bajo_margen = mod_dash.recetas_bajo_margen()
    if bajo_margen:
        nombres = ", ".join(r["nombre"] for r in bajo_margen)
        st.warning(f"⚠ {len(bajo_margen)} receta(s) por debajo de su margen objetivo: {nombres}")

    st.divider()
    st.subheader("Qué se vendió vs. qué dejó plata")
    st.caption(
        "El producto más pedido no siempre es el más rentable — este segundo ranking usa "
        "el margen actual de cada receta, no el costo histórico de cada pedido."
    )
    col_izq, col_der = st.columns(2)
    with col_izq:
        st.markdown("**Más vendidos (unidades)**")
        ranking_ventas = mod_dash.ranking_productos_mes(anio, mes)
        if not ranking_ventas:
            st.info("Sin ventas este mes.")
        else:
            st.dataframe(pd.DataFrame(ranking_ventas), width='stretch', hide_index=True)
    with col_der:
        st.markdown("**Más rentables (ganancia estimada)**")
        ranking_rentabilidad = mod_dash.rentabilidad_productos_mes(anio, mes)
        if not ranking_rentabilidad:
            st.info("Sin ventas este mes.")
        else:
            st.dataframe(pd.DataFrame(ranking_rentabilidad), width='stretch', hide_index=True)

    st.divider()
    st.subheader("Flujo de caja del mes")
    col1, col2, col3 = st.columns(3)
    col1.metric("Ingresos", f"${fin['total_ingresos']:.2f}")
    col2.metric("Gastos", f"${fin['total_gastos']:.2f}")
    col3.metric("Comisiones pagadas", f"${fin['comisiones_pagadas']:.2f}")
    df_medio = pd.DataFrame(fin["por_medio_pago"]).T
    st.dataframe(df_medio, width='stretch')


# --- Navegación principal ------------------------------------------------

st.sidebar.title("🥖 Panadería")
auth.mostrar_sesion_activa()
seccion = st.sidebar.radio(
    "Módulo",
    ["Dashboard", "Ingredientes", "Recetas", "Flujo de caja", "Costos indirectos", "Pedidos", "Clientes"],
)

if seccion == "Dashboard":
    seccion_dashboard()
elif seccion == "Ingredientes":
    seccion_ingredientes()
elif seccion == "Recetas":
    seccion_recetas()
elif seccion == "Flujo de caja":
    seccion_caja()
elif seccion == "Costos indirectos":
    seccion_costos_indirectos()
elif seccion == "Pedidos":
    seccion_pedidos()
elif seccion == "Clientes":
    seccion_clientes()
