"""
whatsapp.py
-----------
Envío de mensajes de WhatsApp Business (Meta Cloud API) en los puntos
clave del ciclo de vida de un pedido: creado, confirmado, recordatorio
de pago y pagado.

Siempre se manda como "plantilla" (template) pre-aprobada por Meta, no
como texto libre: WhatsApp exige plantillas para mensajes que inicia el
negocio cuando el cliente no le escribió en las últimas 24h, que es el
caso normal de estos avisos. Las 4 plantillas deben existir, estar
aprobadas y tener exactamente estas variables (en este orden) en el
Meta Business Manager antes de poder enviar algo:

    pedido_creado       {{1}} nombre  {{2}} pedido_id  {{3}} fecha
                        {{4}} ítems   {{5}} total
    pedido_confirmado   {{1}} nombre  {{2}} pedido_id  {{3}} fecha
    recordatorio_pago   {{1}} nombre  {{2}} pedido_id  {{3}} fecha
                        {{4}} ítems   {{5}} total
    pedido_pagado       {{1}} nombre  {{2}} pedido_id  {{3}} total
                        {{4}} medio_pago

Credenciales en .streamlit/secrets.toml, sección [whatsapp]:
    phone_number_id = "..."  (Phone Number ID de Meta, no el número en sí)
    access_token    = "..."  (token permanente de un System User de Meta)
    api_version     = "v21.0"  (opcional; por defecto v21.0)

Cada intento de envío (exitoso o fallido) queda registrado en la tabla
mensajes_whatsapp (ver db.py) para poder revisar después qué mensajes
no llegaron y por qué, y para no perder el rastro de reenvíos.

Los teléfonos de clientes hoy se guardan como texto libre (ver
clientes.py) — `normalizar_telefono` asume que todos son celulares
chilenos y los deja en formato E.164 (+569XXXXXXXX) antes de enviar.
"""

import re
from datetime import datetime

import requests
import streamlit as st

from db import conectar, cache_lectura
import pedidos as mod_pedidos

TIPOS_MENSAJE = ("pedido_creado", "pedido_confirmado", "recordatorio_pago", "pedido_pagado")

_API_VERSION_POR_DEFECTO = "v21.0"


class ErrorEnvioWhatsapp(Exception):
    """Envío fallido (teléfono inválido, credenciales mal configuradas,
    plantilla no aprobada, error de la Cloud API, etc.). El mensaje
    queda en español y listo para mostrarlo tal cual en la UI."""


def normalizar_telefono(telefono: str | None) -> str:
    """Convierte un teléfono chileno tipeado de cualquier forma común
    (con o sin +56, con espacios o guiones, con o sin el 9 inicial del
    celular) a formato E.164: +569XXXXXXXX.

    Lanza ValueError si no queda un celular chileno válido (9 dígitos:
    un 9 seguido de 8 dígitos, sin contar el 56)."""
    if not telefono or not telefono.strip():
        raise ValueError("El cliente no tiene teléfono registrado")

    digitos = re.sub(r"\D", "", telefono)

    if digitos.startswith("56") and len(digitos) == 11:
        celular = digitos[2:]
    else:
        celular = digitos.lstrip("0")

    if not re.fullmatch(r"9\d{8}", celular):
        raise ValueError(
            f"El teléfono '{telefono}' no parece un celular chileno válido "
            f"(se interpretó como '{celular}', sin contar +56)"
        )

    return f"+56{celular}"


def _formato_pesos(monto: float) -> str:
    return f"${monto:,.0f}".replace(",", ".")


def _bloque_items(items: list[dict]) -> str:
    # En una sola línea: Meta rechaza variables de plantilla con saltos de
    # línea, tabs o más de 4 espacios seguidos (error 132018).
    return " · ".join(
        f"{item['cantidad']} x {item['nombre']} ({_formato_pesos(item['subtotal'])})"
        for item in items
    )


_MEDIOS_PAGO_LEGIBLES = {
    "efectivo": "efectivo",
    "debito": "débito",
    "credito": "crédito",
    "transferencia": "transferencia",
}


def _fecha_legible(fecha_iso: str) -> str:
    return datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d-%m-%Y")


def _credenciales() -> tuple[str, str, str]:
    cfg = st.secrets.get("whatsapp")
    if not cfg or not cfg.get("phone_number_id") or not cfg.get("access_token"):
        raise ErrorEnvioWhatsapp(
            "Faltan las credenciales de WhatsApp en .streamlit/secrets.toml "
            "(sección [whatsapp]: phone_number_id y access_token)"
        )
    return cfg["phone_number_id"], cfg["access_token"], cfg.get("api_version", _API_VERSION_POR_DEFECTO)


def _enviar_plantilla(telefono_e164: str, nombre_plantilla: str, parametros: list[str]) -> str:
    """Llama a la Cloud API con un mensaje de plantilla. Retorna el id
    del mensaje (wamid) si Meta lo aceptó. Lanza ErrorEnvioWhatsapp con
    un detalle legible si falla (credenciales, plantilla, número, red)."""
    phone_number_id, access_token, api_version = _credenciales()

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_e164.lstrip("+"),
        "type": "template",
        "template": {
            "name": nombre_plantilla,
            "language": {"code": "es"},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in parametros],
            }],
        },
    }

    try:
        respuesta = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
            timeout=15,
        )
    except requests.RequestException as e:
        raise ErrorEnvioWhatsapp(f"No se pudo conectar con WhatsApp: {e}") from e

    cuerpo = {}
    if respuesta.content:
        try:
            cuerpo = respuesta.json()
        except ValueError:
            pass

    if respuesta.status_code >= 400:
        detalle = cuerpo.get("error", {}).get("message", respuesta.text or f"HTTP {respuesta.status_code}")
        raise ErrorEnvioWhatsapp(f"WhatsApp rechazó el mensaje: {detalle}")

    try:
        return cuerpo["messages"][0]["id"]
    except (KeyError, IndexError, TypeError):
        return ""


def _registrar_envio(conn, pedido_id: int, tipo: str, telefono: str, estado: str, error: str | None) -> None:
    conn.execute(
        """INSERT INTO mensajes_whatsapp (pedido_id, tipo, telefono, estado, error, fecha_envio)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (pedido_id, tipo, telefono, estado, error, datetime.now().isoformat(timespec="seconds")),
    )


def _enviar_y_registrar(pedido_id: int, tipo: str, telefono: str | None, parametros: list[str]) -> dict:
    """Normaliza el teléfono, envía la plantilla y deja registro en
    mensajes_whatsapp sin importar si salió bien o mal. Si falla
    (teléfono inválido o rechazo de la API), registra el fallo y
    relanza ErrorEnvioWhatsapp para que quien llamó lo muestre en la UI
    — el estado del pedido en sí nunca depende de esto."""
    conn = conectar()
    try:
        try:
            telefono_e164 = normalizar_telefono(telefono)
            wamid = _enviar_plantilla(telefono_e164, tipo, parametros)
        except (ValueError, ErrorEnvioWhatsapp) as e:
            _registrar_envio(conn, pedido_id, tipo, telefono or "(sin teléfono)", "fallido", str(e))
            conn.commit()
            raise ErrorEnvioWhatsapp(str(e)) from e

        _registrar_envio(conn, pedido_id, tipo, telefono_e164, "enviado", None)
        conn.commit()
        return {"telefono": telefono_e164, "wamid": wamid}
    finally:
        conn.close()


def enviar_pedido_creado(pedido_id: int) -> dict:
    """Avisa al cliente el detalle del pedido recién armado (ítems y
    total) y le pide confirmar. Pensado para cuando ya se le agregaron
    todos los ítems, no apenas se crea el pedido vacío."""
    pedido = mod_pedidos.detalle_pedido(pedido_id)
    if not pedido["items"]:
        raise ErrorEnvioWhatsapp("El pedido no tiene ítems todavía — agrégalos antes de enviarlo.")

    return _enviar_y_registrar(
        pedido_id, "pedido_creado", pedido["cliente_telefono"],
        [
            pedido["cliente_nombre"].split()[0],
            str(pedido_id),
            _fecha_legible(pedido["fecha_entrega"]),
            _bloque_items(pedido["items"]),
            _formato_pesos(pedido["total"]),
        ],
    )


def enviar_pedido_confirmado(pedido_id: int) -> dict:
    """Avisa que el pedido quedó confirmado y recuerda la fecha de entrega."""
    pedido = mod_pedidos.detalle_pedido(pedido_id)
    return _enviar_y_registrar(
        pedido_id, "pedido_confirmado", pedido["cliente_telefono"],
        [
            pedido["cliente_nombre"].split()[0],
            str(pedido_id),
            _fecha_legible(pedido["fecha_entrega"]),
        ],
    )


def enviar_recordatorio_pago(pedido_id: int) -> dict:
    """Recordatorio de pago pendiente. A diferencia de los otros 3
    mensajes, este no está atado a un cambio de estado del pedido: se
    manda a mano, las veces que haga falta, mientras el pedido no esté
    pagado (sea cual sea su estado — confirmado, entregado, etc.)."""
    pedido = mod_pedidos.detalle_pedido(pedido_id)
    if pedido["pagado"]:
        raise ErrorEnvioWhatsapp("Este pedido ya está pagado, no corresponde mandar un recordatorio.")
    if not pedido["items"]:
        raise ErrorEnvioWhatsapp("El pedido no tiene ítems, no hay nada que cobrar.")

    return _enviar_y_registrar(
        pedido_id, "recordatorio_pago", pedido["cliente_telefono"],
        [
            pedido["cliente_nombre"].split()[0],
            str(pedido_id),
            _fecha_legible(pedido["fecha_entrega"]),
            _bloque_items(pedido["items"]),
            _formato_pesos(pedido["total"]),
        ],
    )


def enviar_pedido_pagado(pedido_id: int, medio_pago: str) -> dict:
    """Confirma al cliente que su pedido quedó pagado y entregado."""
    pedido = mod_pedidos.detalle_pedido(pedido_id)
    return _enviar_y_registrar(
        pedido_id, "pedido_pagado", pedido["cliente_telefono"],
        [
            pedido["cliente_nombre"].split()[0],
            str(pedido_id),
            _formato_pesos(pedido["total"]),
            _MEDIOS_PAGO_LEGIBLES.get(medio_pago, medio_pago),
        ],
    )


@cache_lectura
def historial_mensajes(pedido_id: int) -> list[dict]:
    """Mensajes de WhatsApp enviados (o intentados) para un pedido,
    más reciente primero. Para mostrar en el detalle del pedido y
    evitar reenvíos a ciegas."""
    conn = conectar()
    try:
        filas = conn.execute(
            """SELECT tipo, telefono, estado, error, fecha_envio
               FROM mensajes_whatsapp
               WHERE pedido_id = %s
               ORDER BY fecha_envio DESC""",
            (pedido_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()
