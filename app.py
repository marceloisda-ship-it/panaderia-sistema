"""
app.py
-------
Interfaz visual (Streamlit) del sistema de gestión de la panadería.
No contiene lógica de negocio: solo llama a las funciones ya definidas
en db.py, ingredientes.py, recetas.py y caja.py y las muestra en pantalla.

Para ejecutar:
    streamlit run app.py
"""

import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from db import inicializar_db, VERSION_ESQUEMA
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
def _inicializar_db_una_vez(version_esquema: int):
    # Streamlit vuelve a ejecutar todo este script en cada interacción
    # (incluido cambiar de pestaña en el sidebar) — sin este cache,
    # inicializar_db() mandaría ~14 sentencias SQL (crear las 11 tablas +
    # 3 inserts de configuración) contra Supabase en cada click, aunque
    # el esquema ya exista (~2s de más por navegación). Con @st.cache_resource
    # corre una sola vez por proceso, no una vez por rerun.
    #
    # `version_esquema` es la clave del caché: al subir VERSION_ESQUEMA en
    # db.py vuelve a correr aunque Streamlit Cloud no reinicie el proceso
    # tras un push (que solo recarga el código y conserva el caché).
    inicializar_db()
    return True


_inicializar_db_una_vez(VERSION_ESQUEMA)


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
    recetas = mod_rec.listar_recetas_resumen(solo_activas=solo_activas)
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


def selector_pedido(label: str, key: str, estado: str | None = None, filtro=None):
    """`filtro` (opcional) recibe cada pedido resumido y decide si se
    muestra, para filtros que no son un solo estado (ej. "por cobrar")."""
    pedidos = mod_pedidos.listar_pedidos_resumen(estado=estado)
    if filtro is not None:
        pedidos = [p for p in pedidos if filtro(p)]
    if not pedidos:
        st.info("No hay pedidos para mostrar.")
        return None
    opciones = {
        f"#{p['id']} · {p['cliente_nombre']} · entrega {p['fecha_entrega']} · "
        f"{mod_pedidos.etiqueta_estado(p['estado'])}{_marca_pago(p)}": p["id"]
        for p in pedidos
    }
    elegido = st.selectbox(label, list(opciones.keys()), key=key)
    return opciones[elegido]


def _marca_pago(p: dict) -> str:
    """Sufijo para títulos de pedidos: pagado, o por cobrar si ya se
    entregó sin pago."""
    if p["pagado"]:
        return " · pagado"
    if p["estado"] == "entregado":
        return " · por cobrar"
    return ""


def _es_por_cobrar(p: dict) -> bool:
    return p["estado"] == "entregado" and not p["pagado"]


# Filtros de pedidos que no son un estado único (Agenda y Detalle).
_FILTRO_POR_COBRAR = "Por cobrar (entregados sin pago)"
_FILTRO_TODOS = "(todos)"


def _opciones_filtro_pedidos() -> list[str]:
    return [_FILTRO_TODOS] + [
        mod_pedidos.etiqueta_estado(e) for e in mod_pedidos.ESTADOS_VALIDOS
    ] + [_FILTRO_POR_COBRAR]


def _aplicar_filtro_pedidos(opcion: str):
    """Traduce una opción de `_opciones_filtro_pedidos` a (estado, filtro)
    para `listar_pedidos` / `selector_pedido`."""
    if opcion == _FILTRO_POR_COBRAR:
        return "entregado", lambda p: not p["pagado"]
    if opcion == _FILTRO_TODOS:
        return None, None
    estado = next(e for e in mod_pedidos.ESTADOS_VALIDOS if mod_pedidos.etiqueta_estado(e) == opcion)
    return estado, None


# --- Sección: Ingredientes ------------------------------------------------

def seccion_ingredientes():
    st.header("🧂 Ingredientes")
    # Selector en vez de st.tabs: st.tabs ejecuta el contenido de TODAS las
    # pestañas en cada interacción, y contra Supabase eso son consultas de
    # más por click. Con este selector solo corre la sección activa.
    vista = st.radio(
        "Sección",
        ["Listado", "Agregar", "Actualizar precio", "Historial de precio", "Eliminar"],
        horizontal=True,
        label_visibility="collapsed",
        key="vista_ingredientes",
    )

    if vista == "Listado":
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

    elif vista == "Agregar":
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

    elif vista == "Actualizar precio":
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

    elif vista == "Historial de precio":
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

    elif vista == "Eliminar":
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
    # Selector en vez de st.tabs: st.tabs ejecuta el contenido de TODAS las
    # pestañas en cada interacción, y contra Supabase eso son consultas de
    # más por click. Con este selector solo corre la sección activa.
    vista = st.radio(
        "Sección",
        ["Reporte de rentabilidad", "Crear receta", "Editar ingredientes", "Detalle de receta"],
        horizontal=True,
        label_visibility="collapsed",
        key="vista_recetas",
    )

    if vista == "Reporte de rentabilidad":
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
            df["bajo_margen"] = df["bajo_margen"].map({True: "⚠ Bajo margen", False: "OK"})

            def resaltar_bajo_margen(fila):
                # Rojo semitransparente (no un rosado claro fijo): se mezcla con
                # el fondo del tema, así el texto (que sigue el color del tema)
                # contrasta igual en modo claro y oscuro. El texto "⚠ Bajo margen"
                # deja la alerta legible aunque no se distinga el color.
                if fila["bajo_margen"] == "OK":
                    return [""] * len(fila)
                return ["background-color: rgba(255, 75, 75, 0.28)"] * len(fila)

            st.dataframe(
                df.style.apply(resaltar_bajo_margen, axis=1),
                width='stretch',
                hide_index=True,
                column_config={"bajo_margen": st.column_config.TextColumn("Estado")},
            )

    elif vista == "Crear receta":
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

    elif vista == "Editar ingredientes":
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

    elif vista == "Detalle de receta":
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
    # Selector en vez de st.tabs: st.tabs ejecuta el contenido de TODAS las
    # pestañas en cada interacción, y contra Supabase eso son consultas de
    # más por click. Con este selector solo corre la sección activa.
    vista = st.radio(
        "Sección",
        ["Registrar ingreso", "Registrar gasto", "Movimientos", "Reporte por período", "Comisiones"],
        horizontal=True,
        label_visibility="collapsed",
        key="vista_caja",
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

    if vista == "Registrar ingreso":
        form_movimiento("ingreso", "ingreso")

    elif vista == "Registrar gasto":
        form_movimiento("gasto", "gasto")

    elif vista == "Movimientos":
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

            st.subheader("Corregir o eliminar un movimiento")
            opciones_mov = {
                f"#{m['id']} · {m['fecha']} · {m['tipo']} · ${m['monto']:,.0f} · {m['categoria'] or 'sin categoría'}": m
                for m in movimientos
            }
            mov = opciones_mov[st.selectbox("Movimiento", list(opciones_mov.keys()), key="mov_editar")]

            if mov["categoria"] in ("Pedido", "Comisión Mercado Pago"):
                st.warning(
                    "Este movimiento lo generó automáticamente el cobro de un pedido. Si lo "
                    "corriges aquí, el total del pedido en Pedidos no cambia."
                )

            # La key incluye el id para que, al elegir otro movimiento, el
            # formulario se vuelva a llenar con los datos de ese movimiento.
            with st.form(f"form_editar_mov_{mov['id']}"):
                col_t, col_m = st.columns(2)
                tipo = col_t.selectbox(
                    "Tipo", mod_caja.TIPOS_VALIDOS, index=mod_caja.TIPOS_VALIDOS.index(mov["tipo"])
                )
                monto = col_m.number_input("Monto", min_value=0.0, step=100.0, value=float(mov["monto"]))
                col_p, col_f = st.columns(2)
                medio = col_p.selectbox(
                    "Medio de pago", mod_caja.MEDIOS_VALIDOS,
                    index=mod_caja.MEDIOS_VALIDOS.index(mov["medio_pago"]),
                )
                fecha = col_f.date_input("Fecha", value=date.fromisoformat(mov["fecha"]))
                categoria = st.text_input("Categoría (opcional)", value=mov["categoria"] or "")
                descripcion = st.text_input("Descripción (opcional)", value=mov["descripcion"] or "")
                guardar = st.form_submit_button("Guardar corrección")
            if guardar:
                try:
                    mod_caja.actualizar_movimiento(
                        mov["id"], tipo, monto, medio, categoria or None, descripcion or None,
                        fecha.isoformat(),
                    )
                    st.success(f"Movimiento #{mov['id']} corregido.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

            confirmar = st.checkbox(f"Confirmo que quiero eliminar el movimiento #{mov['id']}", key="mov_conf_eliminar")
            if st.button("Eliminar movimiento", type="secondary", disabled=not confirmar):
                try:
                    mod_caja.eliminar_movimiento(mov["id"])
                    st.success("Movimiento eliminado.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

    elif vista == "Reporte por período":
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

    elif vista == "Comisiones":
        st.caption(
            "Tasas que cobra el medio de pago electrónico (ej. Mercado Pago Point) al "
            "cobrar con tarjeta. Al registrar el pago de un pedido con débito "
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

_ESTADOS_CALENDARIO = (
    ("recibido", "Recibido", "#e0a100", "🟡"),
    ("confirmado", "Confirmado", "#2f7fd8", "🔵"),
    ("en_produccion", "En producción", "#e06a1f", "🟠"),
    ("listo", "Listo", "#8a4fd0", "🟣"),
    ("entregado", "Entregado", "#2e9e5b", "🟢"),
)
_DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _plural_estado(nombre: str, cantidad: int) -> str:
    """'2 listos', '3 en producción' (lo que lleva 'en' no se pluraliza)."""
    nombre = nombre.lower()
    if cantidad > 1 and not nombre.startswith("en "):
        nombre += "s"
    return nombre


def _calendario_html(anio: int, mes: int, pedidos_por_dia: dict, minutos_por_dia: dict,
                     disponible_min: float, seleccionado: date | None) -> str:
    """Grilla mensual en HTML: por día, un chip de color por estado con su
    cantidad de pedidos. Borde rojo si el día está sobrevendido. Sin
    indentación ni líneas en blanco para que markdown no lo trate como código."""
    hoy = date.today()
    partes = [
        "<style>"
        ".cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;}"
        ".cal-h{text-align:center;font-weight:600;font-size:.8rem;opacity:.7;padding:2px 0;}"
        ".cal-d{min-height:78px;border:1px solid rgba(128,128,128,.3);border-radius:6px;padding:4px 6px;"
        "font-size:.8rem;overflow:hidden;}"
        ".cal-d.vacio{border:none;}"
        ".cal-d.hoy{border:2px solid #2f7fd8;}"
        ".cal-d.sel{background:rgba(47,127,216,.12);}"
        ".cal-d.sobre{border:2px solid #d83a3a;}"
        ".cal-n{font-weight:600;opacity:.85;}"
        ".chip{display:block;color:#fff;border-radius:10px;padding:0 6px;margin-top:2px;font-size:.7rem;"
        "white-space:nowrap;}"
        "@media(max-width:640px){.cal-d{min-height:56px;padding:2px 3px}.chip{padding:0 3px;font-size:.62rem}}"
        "</style>",
        '<div class="cal">',
    ]
    partes += [f'<div class="cal-h">{d}</div>' for d in _DIAS_SEMANA]

    for semana in calendar.Calendar(firstweekday=0).monthdatescalendar(anio, mes):
        for d in semana:
            if d.month != mes:
                partes.append('<div class="cal-d vacio"></div>')
                continue
            iso = d.isoformat()
            clases = "cal-d"
            if d == hoy:
                clases += " hoy"
            if d == seleccionado:
                clases += " sel"
            if disponible_min > 0 and minutos_por_dia.get(iso, 0) > disponible_min:
                clases += " sobre"
            chips = "".join(
                f'<span class="chip" style="background:{color}">{pedidos_por_dia[iso][clave]} {_plural_estado(nombre, pedidos_por_dia[iso][clave])}</span>'
                for clave, nombre, color, _ in _ESTADOS_CALENDARIO
                if pedidos_por_dia.get(iso, {}).get(clave)
            )
            partes.append(f'<div class="{clases}"><span class="cal-n">{d.day}</span>{chips}</div>')
    partes.append("</div>")
    return "".join(partes)


def _vista_planificacion():
    hoy = date.today()
    if "plan_mes_ref" not in st.session_state:
        st.session_state["plan_mes_ref"] = hoy.replace(day=1)
    ref: date = st.session_state["plan_mes_ref"]

    col_prev, col_titulo, col_hoy, col_next = st.columns([1, 4, 1.4, 1])
    nuevo_mes = None
    if col_prev.button("◀", key="plan_prev", help="Mes anterior", width="stretch"):
        nuevo_mes = (ref - timedelta(days=1)).replace(day=1)
    if col_next.button("▶", key="plan_next", help="Mes siguiente", width="stretch"):
        nuevo_mes = (ref + timedelta(days=32)).replace(day=1)
    if col_hoy.button("Hoy", key="plan_hoy", width="stretch"):
        nuevo_mes = hoy.replace(day=1)
    if nuevo_mes is not None:
        st.session_state["plan_mes_ref"] = nuevo_mes
        # Al cambiar de mes, el día seleccionado pasa a hoy (si cae en ese mes) o al día 1.
        st.session_state["plan_dia_sel"] = hoy if nuevo_mes == hoy.replace(day=1) else nuevo_mes
        st.rerun()
    col_titulo.markdown(f"### {NOMBRES_MESES[ref.month - 1]} {ref.year}")

    primer_dia = ref
    ultimo_dia = ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])

    pedidos_mes = [
        p for p in mod_pedidos.listar_pedidos(desde=primer_dia.isoformat(), hasta=ultimo_dia.isoformat())
        if p["estado"] != "cancelado"
    ]
    pedidos_por_dia: dict[str, dict[str, int]] = {}
    for p in pedidos_mes:
        por_estado = pedidos_por_dia.setdefault(p["fecha_entrega"], {})
        por_estado[p["estado"]] = por_estado.get(p["estado"], 0) + 1

    minutos_por_dia = mod_prod.tiempo_comprometido_rango(primer_dia.isoformat(), ultimo_dia.isoformat())
    disponible_dia_min = mod_prod.obtener_configuracion()["horas_disponibles_dia"] * 60

    dia_sel = st.session_state.get("plan_dia_sel", hoy)
    if not (primer_dia <= dia_sel <= ultimo_dia):
        dia_sel = hoy if primer_dia <= hoy <= ultimo_dia else primer_dia
    st.session_state["plan_dia_sel"] = dia_sel

    st.markdown(
        _calendario_html(ref.year, ref.month, pedidos_por_dia, minutos_por_dia, disponible_dia_min, dia_sel),
        unsafe_allow_html=True,
    )
    st.caption(
        " · ".join(f"{emoji} {nombre}" for _, nombre, _, emoji in _ESTADOS_CALENDARIO)
        + " — borde rojo: día sobrevendido (más trabajo que horas disponibles). "
        "Los pedidos cancelados no se cuentan."
    )

    # --- Resumen del mes ---------------------------------------------------
    st.divider()
    st.subheader(f"Resumen de {NOMBRES_MESES[ref.month - 1].lower()}")
    conteo = {clave: sum(1 for p in pedidos_mes if p["estado"] == clave) for clave, *_ in _ESTADOS_CALENDARIO}
    por_cobrar = [p for p in pedidos_mes if _es_por_cobrar(p)]
    c1, c2, c3 = st.columns(3)
    c1.metric("Pedidos del mes", len(pedidos_mes))
    c2.metric("🟡 Recibidos", conteo["recibido"])
    c3.metric("🔵 Confirmados", conteo["confirmado"])
    c4, c5, c6 = st.columns(3)
    c4.metric("🟠 En producción", conteo["en_produccion"])
    c5.metric("🟣 Listos", conteo["listo"])
    c6.metric("🟢 Entregados", conteo["entregado"])
    if por_cobrar:
        monto_por_cobrar = f"${sum(p['total'] for p in por_cobrar):,.0f}".replace(",", ".")
        st.caption(f"💸 {len(por_cobrar)} pedido(s) entregado(s) sin pagar este mes, por {monto_por_cobrar}.")

    # Tiempo: solo de hoy en adelante (lo ya pasado no se puede "usar").
    desde_tiempo = max(primer_dia, hoy)
    if desde_tiempo > ultimo_dia:
        st.caption("Este mes ya terminó: no queda tiempo por planificar.")
    else:
        dias_restantes = (ultimo_dia - desde_tiempo).days + 1
        requerido_min = sum(m for f, m in minutos_por_dia.items() if f >= desde_tiempo.isoformat())
        disponible_min = disponible_dia_min * dias_restantes
        restante_min = disponible_min - requerido_min
        t1, t2, t3 = st.columns(3)
        t1.metric("Tiempo requerido", f"{requerido_min / 60:.1f} h",
                  help="Horas de preparación de los pedidos de hoy en adelante este mes.")
        t2.metric("Tiempo disponible", f"{disponible_min / 60:.1f} h",
                  help=f"{dias_restantes} día(s) × {disponible_dia_min / 60:.1f} h/día (configurable en Capacidad de producción).")
        t3.metric("Tiempo restante", f"{restante_min / 60:.1f} h",
                  delta="sobrevendido" if restante_min < 0 else None, delta_color="inverse")
        if disponible_min > 0:
            st.progress(min(max(requerido_min / disponible_min, 0.0), 1.0),
                        text=f"{requerido_min / disponible_min * 100:.0f}% del tiempo del mes comprometido")
        else:
            st.info("Configura las horas disponibles por día en 'Capacidad de producción' para ver el tiempo restante.")

    # --- Detalle del día ---------------------------------------------------
    st.divider()
    st.subheader("Detalle de un día")
    dia_sel = st.date_input("Día", min_value=primer_dia, max_value=ultimo_dia, key="plan_dia_sel")
    resumen = mod_pedidos.resumen_dia(dia_sel.isoformat())

    col1, col2 = st.columns(2)
    col1.metric("Pedidos ese día", resumen["cantidad_pedidos"])
    col2.metric("Total a cobrar", f"${resumen['total_a_cobrar']:.2f}")

    cap = mod_prod.capacidad_dia(dia_sel.isoformat())
    texto_capacidad = f"Capacidad: {cap['comprometido_min']:.0f} / {cap['disponible_min']:.0f} min usados"
    if cap["sobrevendido"]:
        st.warning(f"⚠ {texto_capacidad} — este día está sobrevendido.")
    else:
        st.caption(texto_capacidad)

    if resumen["items_agregados"]:
        st.markdown("**Qué preparar ese día**")
        df_items = pd.DataFrame(resumen["items_agregados"]).set_index("receta")
        st.dataframe(df_items, width='stretch')

        st.markdown("**Pedidos de ese día**")
        for p in resumen["pedidos"]:
            with st.expander(f"#{p['id']} · {p['cliente_nombre']} · ${p['total']:.2f} · "
                             f"{mod_pedidos.etiqueta_estado(p['estado'])}{_marca_pago(p)}"):
                st.dataframe(pd.DataFrame(p["items"]), width='stretch', hide_index=True)
                if p["notas"]:
                    st.caption(f"Notas: {p['notas']}")
    else:
        st.info("No hay pedidos para este día.")


_PASOS_FLUJO = ("recibido", "confirmado", "en_produccion", "listo", "entregado")

# Botón y explicación para avanzar al estado siguiente (ver SIGUIENTE_ESTADO).
_TEXTO_AVANZAR = {
    "confirmado": ("✅ Confirmar pedido", "El cliente ya recibió el detalle del pedido y lo aceptó."),
    "en_produccion": ("🔥 Pasar a producción", "Las cubetas ya están armadas y el pan horneando."),
    "listo": ("🥖 Marcar listo", "El pan ya salió. Después avísale al cliente para coordinar la entrega."),
}


# --- Línea de tiempo del pedido (componente v2: HTML/CSS/JS propio) --------
# Cada paso es un botón; al tocarlo, el JS manda la clave del estado elegido
# a Python como "trigger" (dura un solo rerun) y Python cambia el estado.

_CSS_LINEA_TIEMPO = """
.lt { font-family: var(--st-font); color: var(--st-text-color); padding: 4px 0 2px; }
.lt-pasos { display: grid; grid-template-columns: repeat(var(--n), 1fr); position: relative; }
.lt-paso { display: flex; flex-direction: column; align-items: center; position: relative;
  background: none; border: none; padding: 0 2px; font: inherit; color: inherit; cursor: default; }
.lt-paso.clic { cursor: pointer; }
.lt-paso::before { content: ""; position: absolute; top: 17px; right: 50%; width: 100%; height: 4px;
  background: var(--st-border-color, rgba(128,128,128,.35)); z-index: 0; }
.lt-paso:first-child::before { display: none; }
.lt-paso.hecho::before, .lt-paso.actual::before { background: var(--c); }
.lt-nodo { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; font-size: 15px; z-index: 1; position: relative;
  border: 3px solid var(--st-border-color, rgba(128,128,128,.45));
  background: var(--st-background-color); color: var(--st-gray-text-color, #888);
  transition: transform .12s ease, box-shadow .12s ease; }
.lt-paso.hecho .lt-nodo { background: var(--c); border-color: var(--c); color: #fff; }
.lt-paso.actual .lt-nodo { background: var(--c); border-color: var(--c); color: #fff;
  box-shadow: 0 0 0 5px color-mix(in srgb, var(--c) 28%, transparent); transform: scale(1.12); }
.lt-paso.clic:hover .lt-nodo, .lt-paso.clic:focus-visible .lt-nodo { transform: scale(1.15);
  border-color: var(--c); }
.lt-paso:focus-visible { outline: none; }
.lt-paso:focus-visible .lt-etq { text-decoration: underline; }
.lt-etq { margin-top: 8px; font-size: .78rem; line-height: 1.15; text-align: center; opacity: .75; }
.lt-paso.actual .lt-etq { font-weight: 700; opacity: 1; }
.lt-paso.hecho .lt-etq { opacity: .95; }
.lt-aviso { margin-top: 10px; font-size: .8rem; color: var(--st-red-text-color, #d83a3a); text-align: center; }
.lt.cancelado .lt-pasos { opacity: .45; filter: grayscale(1); }
@media (max-width: 480px) { .lt-nodo { width: 26px; height: 26px; font-size: 12px; }
  .lt-paso::before { top: 14px; } .lt-etq { font-size: .66rem; } }
"""

_JS_LINEA_TIEMPO = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector("#lt")
  if (!root || !data) return
  const pasos = data.pasos || []
  const iActual = pasos.findIndex((p) => p.clave === data.actual)
  root.className = "lt" + (data.cancelado ? " cancelado" : "")
  root.innerHTML = ""
  const fila = document.createElement("div")
  fila.className = "lt-pasos"
  fila.style.setProperty("--n", String(pasos.length))
  pasos.forEach((p, i) => {
    const b = document.createElement("button")
    b.type = "button"
    let clase = "lt-paso"
    if (!data.cancelado && iActual >= 0) {
      if (i < iActual) clase += " hecho"
      else if (i === iActual) clase += " actual"
    }
    const clickeable = data.editable && i !== iActual
    if (clickeable) clase += " clic"
    b.className = clase
    b.style.setProperty("--c", p.color)
    b.disabled = !clickeable
    b.title = clickeable ? "Mover el pedido a: " + p.etiqueta : p.etiqueta
    const nodo = document.createElement("span")
    nodo.className = "lt-nodo"
    nodo.textContent = (!data.cancelado && i < iActual) ? "✓" : p.emoji
    const etq = document.createElement("span")
    etq.className = "lt-etq"
    etq.textContent = p.etiqueta
    b.append(nodo, etq)
    if (clickeable) b.onclick = () => setTriggerValue("elegido", p.clave)
    fila.appendChild(b)
  })
  root.appendChild(fila)
  if (data.cancelado) {
    const aviso = document.createElement("div")
    aviso.className = "lt-aviso"
    aviso.textContent = "✖ Pedido cancelado"
    root.appendChild(aviso)
  }
}
"""

_LINEA_TIEMPO = st.components.v2.component(
    "linea_tiempo_pedido",
    html='<div id="lt" class="lt"></div>',
    css=_CSS_LINEA_TIEMPO,
    js=_JS_LINEA_TIEMPO,
)

_ICONOS_PASO = {"recibido": "📥", "confirmado": "✅", "en_produccion": "🔥", "listo": "🥖", "entregado": "📦"}


def linea_tiempo_pedido(pedido: dict, editable: bool, key: str) -> str | None:
    """Dibuja la línea de tiempo del pedido. Retorna la clave del estado
    que se tocó en este rerun (o None)."""
    colores = {clave: color for clave, _, color, _ in _ESTADOS_CALENDARIO}
    resultado = _LINEA_TIEMPO(
        data={
            "pasos": [
                {"clave": e, "etiqueta": mod_pedidos.etiqueta_estado(e),
                 "color": colores[e], "emoji": _ICONOS_PASO[e]}
                for e in _PASOS_FLUJO
            ],
            "actual": pedido["estado"],
            "cancelado": pedido["estado"] == "cancelado",
            "editable": editable,
        },
        key=key,
        on_elegido_change=lambda: None,
    )
    return resultado.elegido



def _linea_estado_pago(pedido: dict) -> str:
    partes = [f"Estado: {mod_pedidos.etiqueta_estado(pedido['estado'])}"]
    if pedido["pagado"]:
        detalle_pago = f"Pagado ({pedido['medio_pago']}"
        if pedido.get("fecha_pago"):
            detalle_pago += f", {pedido['fecha_pago']}"
        partes.append(detalle_pago + ")")
    else:
        partes.append("Sin pagar" if pedido["estado"] != "entregado" else "💸 Por cobrar")
    if pedido.get("fecha_entregado"):
        partes.append(f"Entregado el {pedido['fecha_entregado']}")
    if pedido.get("canal_origen"):
        partes.append(f"Llegó por {mod_pedidos.ETIQUETAS_CANAL[pedido['canal_origen']]}")
    return " · ".join(partes)


def _avisar_pago(pedido_id: int, medio: str, resultado: dict):
    """Mensaje de éxito tras registrar un pago (con la comisión, si hubo)."""
    mensaje = f"Pago registrado. Ingreso #{resultado['movimiento_ingreso_id']} en Caja."
    if resultado["comision"] > 0:
        mensaje += (
            f" Además, gasto de ${resultado['comision']:.2f} por comisión de {medio} "
            f"(#{resultado['movimiento_gasto_comision_id']})."
        )
    st.toast(mensaje)


def _bloque_estado_pedido(pedido_id: int, pedido: dict):
    """Línea de tiempo del pedido. Si está abierto, tocar un paso lo mueve
    a ese estado (también hacia atrás, para corregir); tocar "Entregado"
    abre el formulario de entrega, que pide si pagó o no."""
    estado = pedido["estado"]
    abierto = estado in mod_pedidos.ESTADOS_ABIERTOS
    clave_entrega = "entregar_pedido_id"

    st.subheader("Avance del pedido")
    elegido = linea_tiempo_pedido(pedido, editable=abierto, key=f"linea_tiempo_{pedido_id}")

    if elegido == "entregado":
        st.session_state[clave_entrega] = pedido_id
    elif elegido:
        try:
            mod_pedidos.actualizar_estado(pedido_id, elegido)
            st.session_state.pop(clave_entrega, None)
            st.toast(f"Pedido #{pedido_id}: {mod_pedidos.etiqueta_estado(elegido)}.")
        except Exception as e:
            mostrar_error(e)
        else:
            st.rerun()

    if not abierto:
        return

    if st.session_state.get(clave_entrega) == pedido_id:
        with st.container(border=True):
            _bloque_entregar_pedido(pedido_id, pedido)
            if st.button("Cerrar", key="btn_cerrar_entrega"):
                st.session_state.pop(clave_entrega, None)
                st.rerun()
        return

    siguiente = mod_pedidos.SIGUIENTE_ESTADO[estado]
    if siguiente in _TEXTO_AVANZAR:
        boton, ayuda = _TEXTO_AVANZAR[siguiente]
        st.caption(f"Toca un paso para mover el pedido. Siguiente: **{boton}** — {ayuda}")
    else:
        st.caption("Ya está listo: avísale al cliente y toca **Entregado** cuando lo entregues.")


def _bloque_entregar_pedido(pedido_id: int, pedido: dict):
    """Marcar entregado, con o sin pago en el momento."""
    st.subheader("Entregar")
    if pedido["pagado"]:
        st.caption("Este pedido ya está pagado: solo queda marcarlo como entregado.")
    else:
        st.caption(
            "Si el cliente paga al recibir, márcalo aquí mismo y se registra el ingreso en Caja. "
            "Si no, queda como **por cobrar** y el pago se registra después."
        )

    with st.form("form_entregar_pedido"):
        pago_al_recibir = False
        medio = None
        if not pedido["pagado"]:
            pago_al_recibir = st.radio(
                "¿Pagó al recibir?", [False, True],
                format_func=lambda v: "Sí, pagó al recibir" if v else "No, queda por cobrar",
                horizontal=True,
            )
            medio = st.selectbox("Medio de pago (si pagó)", mod_caja.MEDIOS_VALIDOS)
        fecha = st.date_input("Fecha de entrega", value=date.today(), max_value=date.today())
        enviado = st.form_submit_button("Marcar entregado")
    if enviado:
        try:
            if pago_al_recibir:
                resultado = mod_pedidos.entregar_y_cobrar(pedido_id, medio, fecha.isoformat())
            else:
                mod_pedidos.marcar_entregado(pedido_id, fecha.isoformat())
        except Exception as e:
            mostrar_error(e)
        else:
            if pago_al_recibir:
                _avisar_pago(pedido_id, medio, resultado)
            else:
                st.toast(f"Pedido #{pedido_id} entregado.")
            st.session_state.pop("entregar_pedido_id", None)
            st.rerun()


def _bloque_registrar_pago(pedido_id: int, pedido: dict):
    """Registrar el pago por separado: de un pedido ya entregado (por
    cobrar) o por adelantado, antes de entregarlo."""
    if pedido["estado"] == "entregado":
        st.subheader("💸 Registrar pago")
        dias = None
        if pedido.get("fecha_entregado"):
            dias = (date.today() - date.fromisoformat(pedido["fecha_entregado"])).days
        st.caption(
            "Entregado sin pago"
            + (f" hace {dias} día(s)" if dias is not None else "")
            + "."
        )
        contenedor = st.container()
    else:
        contenedor = st.expander("💸 Registrar pago por adelantado (antes de entregar)")

    with contenedor:
        _form_registrar_pago(pedido_id, "detalle")


def _form_registrar_pago(pedido_id: int, sufijo: str):
    """Formulario medio + fecha → registrar_pago. `sufijo` distingue las
    claves cuando hay varios en la misma pantalla (lista Por cobrar)."""
    with st.form(f"form_registrar_pago_{sufijo}_{pedido_id}"):
        col_medio, col_fecha = st.columns(2)
        medio = col_medio.selectbox("Medio de pago", mod_caja.MEDIOS_VALIDOS,
                                    key=f"medio_pago_{sufijo}_{pedido_id}")
        fecha = col_fecha.date_input("Fecha del pago", value=date.today(), max_value=date.today(),
                                     key=f"fecha_pago_{sufijo}_{pedido_id}")
        enviado = st.form_submit_button("Registrar pago")
    if enviado:
        try:
            resultado = mod_pedidos.registrar_pago(pedido_id, medio, fecha.isoformat())
        except Exception as e:
            mostrar_error(e)
        else:
            _avisar_pago(pedido_id, medio, resultado)
            st.rerun()


def _vista_por_cobrar():
    """Pedidos entregados sin pagar: cuánto se debe, hace cuántos días se
    entregó y a cuáles ya toca recordarles el pago."""
    config = mod_pedidos.obtener_configuracion_cobranza()
    pedidos = mod_pedidos.listar_por_cobrar()

    total = sum(p["total"] for p in pedidos)
    a_recordar = [p for p in pedidos if p["toca_recordar"]]
    c1, c2, c3 = st.columns(3)
    c1.metric("Pedidos por cobrar", len(pedidos))
    c2.metric("Monto adeudado", f"${total:,.0f}".replace(",", "."))
    c3.metric("🔔 Toca recordar", len(a_recordar),
              help=f"Entregados hace {config['dias_recordatorio']} día(s) o más.")

    with st.expander(f"⚙️ Avisar a los {config['dias_recordatorio']} día(s) de la entrega"):
        with st.form("form_config_cobranza"):
            dias = st.number_input(
                "Días desde la entrega para recordar el pago", min_value=0, step=1,
                value=int(config["dias_recordatorio"]),
                help="No es un plazo de pago: solo cuándo el sistema marca el pedido como 'toca recordar'.",
            )
            if st.form_submit_button("Guardar"):
                try:
                    mod_pedidos.actualizar_dias_recordatorio(int(dias))
                    st.toast("Configuración de cobranza guardada.")
                    st.rerun()
                except Exception as e:
                    mostrar_error(e)

    if not pedidos:
        st.success("No hay pedidos por cobrar. 🎉")
        return

    st.caption("Del más antiguo al más reciente. Abre uno para registrar el pago.")
    for p in pedidos:
        marca = "🔔 " if p["toca_recordar"] else ""
        dias_txt = "hoy" if p["dias_desde_entrega"] == 0 else f"hace {p['dias_desde_entrega']} día(s)"
        monto = f"${p['total']:,.0f}".replace(",", ".")
        with st.expander(f"{marca}#{p['id']} · {p['cliente_nombre']} · {monto} · entregado {dias_txt}"):
            if p["cliente_telefono"]:
                st.caption(f"Teléfono: {p['cliente_telefono']}")
            _form_registrar_pago(p["id"], "por_cobrar")


def seccion_pedidos():
    st.header("📋 Pedidos")
    a_recordar = [p for p in mod_pedidos.listar_por_cobrar() if p["toca_recordar"]]
    if a_recordar:
        st.warning(
            f"🔔 {len(a_recordar)} pedido(s) entregado(s) sin pagar ya pasaron el plazo de aviso. "
            "Revísalos en **Por cobrar**."
        )
    # Selector en vez de st.tabs: st.tabs ejecuta el contenido de TODAS las
    # pestañas en cada interacción, y contra Supabase eso son decenas de
    # consultas por click. Con este selector solo corre la sección activa.
    vista = st.radio(
        "Sección",
        ["Planificación", "Agenda", "Crear pedido", "Agregar ítems", "Detalle / Cobrar", "Por cobrar",
         "Capacidad de producción"],
        horizontal=True,
        label_visibility="collapsed",
        key="vista_pedidos",
    )

    if vista == "Planificación":
        _vista_planificacion()

    elif vista == "Por cobrar":
        _vista_por_cobrar()

    elif vista == "Agenda":
        col1, col2, col3 = st.columns(3)
        desde = col1.date_input("Desde", value=None, key="ped_desde")
        hasta = col2.date_input("Hasta", value=None, key="ped_hasta")
        opcion_filtro = col3.selectbox("Estado", _opciones_filtro_pedidos(), key="ped_filtro_estado")
        estado, filtro = _aplicar_filtro_pedidos(opcion_filtro)
        pedidos = mod_pedidos.listar_pedidos(
            desde=desde.isoformat() if desde else None,
            hasta=hasta.isoformat() if hasta else None,
            estado=estado,
        )
        if filtro is not None:
            pedidos = [p for p in pedidos if filtro(p)]

        if not pedidos:
            st.info("No hay pedidos en ese rango.")
        else:
            st.caption(f"{len(pedidos)} pedido(s), agrupados por fecha de entrega. Abre uno para ver su desglose de ítems.")
            fecha_agrupada = None
            for p in pedidos:
                if p["fecha_entrega"] != fecha_agrupada:
                    fecha_agrupada = p["fecha_entrega"]
                    st.markdown(f"**📅 {fecha_agrupada}**")

                titulo = (f"#{p['id']} · {p['cliente_nombre']} · ${p['total']:.2f} · "
                          f"{mod_pedidos.etiqueta_estado(p['estado'])}{_marca_pago(p)}")
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
                    if p.get("canal_origen"):
                        st.caption(f"Llegó por: {mod_pedidos.ETIQUETAS_CANAL[p['canal_origen']]}")

            with st.expander("Ver como tabla resumen"):
                df = pd.DataFrame(pedidos)[
                    ["id", "fecha_entrega", "cliente_nombre", "cliente_telefono",
                     "estado", "pagado", "total"]
                ]
                df["estado"] = df["estado"].map(mod_pedidos.etiqueta_estado)
                st.dataframe(df, width='stretch', hide_index=True)

        st.divider()
        st.subheader("Reagendar varios pedidos de un mismo día")
        st.caption(
            "Por ejemplo, si un día se cae la producción por fuerza mayor: mueve de una "
            "sola vez todos los pedidos de ese día (los que no estén entregados ni cancelados) a otra fecha."
        )
        col1, col2 = st.columns(2)
        fecha_origen = col1.date_input("Fecha actual de esos pedidos", value=date.today(), key="ped_reag_origen")
        fecha_destino = col2.date_input("Nueva fecha de entrega", value=date.today(), key="ped_reag_destino")

        pedidos_a_mover = [
            p for p in mod_pedidos.listar_pedidos(desde=fecha_origen.isoformat(), hasta=fecha_origen.isoformat())
            if p["estado"] not in ("entregado", "cancelado")
        ]
        if not pedidos_a_mover:
            st.info(f"No hay pedidos sin entregar el {fecha_origen.isoformat()} para reagendar.")
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
            canal = st.selectbox(
                "¿Por dónde llegó el pedido?", mod_pedidos.CANALES_VALIDOS,
                format_func=lambda c: mod_pedidos.ETIQUETAS_CANAL[c], key="canal_pedido",
            )
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

                pedido_id = mod_pedidos.crear_pedido(
                    cliente_id, fecha_entrega.isoformat(), notas or None, canal_origen=canal
                )
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
                st.warning(f"Este pedido ya está '{mod_pedidos.etiqueta_estado(pedido['estado'])}', no se puede seguir editando.")
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
        opcion_filtro = st.selectbox(
            "Filtrar por estado", _opciones_filtro_pedidos(), index=0, key="detalle_filtro_estado"
        )
        estado_filtro, filtro = _aplicar_filtro_pedidos(opcion_filtro)
        pedido_id = selector_pedido("Pedido", "sel_pedido_detalle", estado=estado_filtro, filtro=filtro)
        if pedido_id is not None:
            pedido = mod_pedidos.detalle_pedido(pedido_id)

            col1, col2, col3 = st.columns(3)
            col1.metric("Cliente", pedido["cliente_nombre"])
            col2.metric("Fecha de entrega", pedido["fecha_entrega"])
            col3.metric("Total", f"${pedido['total']:.2f}")
            st.caption(_linea_estado_pago(pedido))
            if pedido["notas"]:
                st.caption(f"Notas: {pedido['notas']}")

            if pedido["items"]:
                st.dataframe(pd.DataFrame(pedido["items"]), width='stretch', hide_index=True)
            else:
                st.info("Este pedido todavía no tiene ítems.")

            abierto = pedido["estado"] in mod_pedidos.ESTADOS_ABIERTOS

            st.divider()
            _bloque_estado_pedido(pedido_id, pedido)

            if abierto:
                st.divider()
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
                        st.toast(f"Pedido #{pedido_id} reagendado al {nueva_fecha.isoformat()}.")
                        st.rerun()
                    except Exception as e:
                        mostrar_error(e)

            if not pedido["pagado"] and pedido["estado"] != "cancelado" and pedido["items"]:
                st.divider()
                _bloque_registrar_pago(pedido_id, pedido)

            if abierto:
                st.divider()
                if pedido["pagado"]:
                    st.caption(
                        "⚠ Este pedido ya está pagado: si lo cancelas, el ingreso sigue en Caja "
                        "(registra ahí la devolución si corresponde)."
                    )
                if st.button("Cancelar pedido", type="secondary"):
                    try:
                        mod_pedidos.cancelar_pedido(pedido_id)
                        st.toast("Pedido cancelado.")
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
    # Selector en vez de st.tabs: st.tabs ejecuta el contenido de TODAS las
    # pestañas en cada interacción, y contra Supabase eso son consultas de
    # más por click. Con este selector solo corre la sección activa.
    vista = st.radio(
        "Sección",
        ["Listado", "Agregar", "Ficha / Historial", "Reportes"],
        horizontal=True,
        label_visibility="collapsed",
        key="vista_clientes",
    )

    if vista == "Listado":
        clientes = mod_clientes.listar_clientes()
        if not clientes:
            st.info("No hay clientes registrados todavía.")
        else:
            df = pd.DataFrame(clientes)[["id", "nombre", "telefono", "direccion", "fecha_creacion"]]
            st.dataframe(df, width='stretch', hide_index=True)

    elif vista == "Agregar":
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

    elif vista == "Ficha / Historial":
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

    elif vista == "Reportes":
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

    datos = mod_dash.datos_dashboard(int(anio), int(mes))
    ped, ped_ant = datos["pedidos"], datos["pedidos_anterior"]
    fin, fin_ant = datos["financiero"], datos["financiero_anterior"]

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
            [{"estado": mod_pedidos.etiqueta_estado(e), "cantidad": c} for e, c in ped["por_estado"].items()]
        ).set_index("estado")
        st.bar_chart(df_estado["cantidad"])

    bajo_margen = datos["recetas_bajo_margen"]
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
        ranking_ventas = datos["ranking_ventas"]
        if not ranking_ventas:
            st.info("Sin ventas este mes.")
        else:
            st.dataframe(pd.DataFrame(ranking_ventas), width='stretch', hide_index=True)
    with col_der:
        st.markdown("**Más rentables (ganancia estimada)**")
        ranking_rentabilidad = datos["ranking_rentabilidad"]
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
