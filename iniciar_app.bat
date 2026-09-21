@echo off
REM iniciar_app.bat
REM ---------------
REM Levanta la interfaz visual (Streamlit) del sistema de gestion de la
REM panaderia. Se puede ejecutar con doble clic desde cualquier carpeta.

cd /d "%~dp0"

python -m streamlit --version >nul 2>&1
if errorlevel 1 (
    echo Streamlit no esta instalado todavia, instalando dependencias...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Error instalando dependencias.
        pause
        exit /b 1
    )
)

python -m streamlit run app.py %*
pause
