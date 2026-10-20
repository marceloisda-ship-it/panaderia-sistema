"""
Abre la app con un navegador real (Chromium sin pantalla) para que
Streamlit Community Cloud la cuente como visitada y no la duerma.

Un curl no sirve: la URL .streamlit.app responde al instante con una
página estática aunque la app esté dormida, sin llegar a levantar
Python. Acá se espera a que cargue la app de verdad (la pantalla de
login, "Panadería · Ingresar"), y si estaba dormida se aprieta el botón
para despertarla.

Si la app no carga, el script termina con error: la ejecución queda
en rojo en GitHub Actions y GitHub avisa por correo.
"""

import sys

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

URL = "https://panaderia-sistema-uumamth9pioq35cftmxjuc.streamlit.app/"
TEXTO_APP_CARGADA = "Ingresar"
BOTON_DESPERTAR = "Yes, get this app back up"
ESPERA_MAX_MS = 5 * 60 * 1000  # despertar desde cero puede tomar un par de minutos


def app_cargada(page) -> bool:
    # La app corre dentro de un iframe de la página de Streamlit Cloud.
    for frame in page.frames:
        try:
            if frame.get_by_text(TEXTO_APP_CARGADA, exact=False).count() > 0:
                return True
        except Exception:
            pass
    return False


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        transcurrido = 0
        desperto = False
        while transcurrido < ESPERA_MAX_MS:
            if app_cargada(page):
                # Unos segundos más con la sesión abierta para que cuente como visita.
                page.wait_for_timeout(15_000)
                print("App activa" + (" (estaba dormida, se despertó)" if desperto else "") + ".")
                browser.close()
                return 0

            boton = page.get_by_role("button", name=BOTON_DESPERTAR)
            if not desperto and boton.count() > 0:
                print("La app estaba dormida: apretando el botón para despertarla...")
                try:
                    boton.first.click(timeout=10_000)
                    desperto = True
                except PlaywrightTimeout:
                    pass

            page.wait_for_timeout(5_000)
            transcurrido += 5_000

        page.screenshot(path="keepalive-error.png", full_page=True)
        print(f"La app no cargó en {ESPERA_MAX_MS // 60000} minutos.", file=sys.stderr)
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
