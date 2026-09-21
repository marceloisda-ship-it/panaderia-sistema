#!/bin/bash
# iniciar_app.sh
# ---------------
# Levanta la interfaz visual (Streamlit) del sistema de gestión de la
# panadería. Se puede ejecutar desde cualquier carpeta.
#
# Uso:
#   ./iniciar_app.sh

set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

if ! python -m streamlit --version >/dev/null 2>&1; then
    echo "Streamlit no está instalado todavía, instalando dependencias..."
    python -m pip install -r requirements.txt
fi

python -m streamlit run app.py "$@"
