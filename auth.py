"""
auth.py
-------
Login del sistema vía Supabase Auth (email + contraseña). Solo controla
quién puede entrar a la app: todos los usuarios logueados ven y editan
los mismos datos (no hay separación de datos por usuario, es un único
negocio con 2 o más personas trabajando sobre la misma información).

Los usuarios se crean a mano en Supabase → Authentication → Users, no
hay auto-registro desde la app.
"""

import logging

import streamlit as st
from supabase import create_client

logger = logging.getLogger(__name__)


@st.cache_resource
def _cliente():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["anon_key"])


def mostrar_login():
    st.title("🥖 Panadería · Ingresar")
    with st.form("login"):
        email = st.text_input("Correo")
        password = st.text_input("Contraseña", type="password")
        enviado = st.form_submit_button("Ingresar")

    if enviado:
        try:
            resultado = _cliente().auth.sign_in_with_password({"email": email, "password": password})
            st.session_state["usuario"] = {"email": resultado.user.email, "id": resultado.user.id}
            st.rerun()
        except Exception:
            # Log del error real (visible en "Manage app" → logs de Streamlit
            # Cloud) para poder diagnosticar sin exponer detalles a quien
            # está intentando entrar (que solo ve el mensaje genérico).
            logger.exception("Fallo al iniciar sesión con email=%r", email)
            st.error("Correo o contraseña incorrectos.")


def mostrar_sesion_activa():
    """Nombre del usuario logueado y botón de cerrar sesión, en el sidebar."""
    usuario = st.session_state.get("usuario")
    if not usuario:
        return

    st.sidebar.caption(f"Sesión: {usuario['email']}")
    if st.sidebar.button("Cerrar sesión"):
        try:
            _cliente().auth.sign_out()
        except Exception:
            pass
        st.session_state.pop("usuario", None)
        st.rerun()
