# d:\Datos\Desktop\Asistente Contable\src\config.py
import os
import logging

# --- Información de la Aplicación ---
APP_NAME = "AsistenteContable"
APP_AUTHOR = "Business & Services" # O tu nombre/organización

# --- Directorios ---
# Directorio base para datos de la aplicación (logs, settings, etc.)
# Usamos os.path.join para compatibilidad entre OS

# Para Windows, AppData\Local es un buen lugar
if os.name == 'nt': # Windows
    _app_data_base = os.getenv('LOCALAPPDATA', os.path.expanduser("~"))
else: # macOS, Linux
    _app_data_base = os.path.join(os.path.expanduser("~"), ".local", "share")

APP_DATA_DIR = os.path.join(_app_data_base, APP_AUTHOR, APP_NAME)
LOG_DIR = os.path.join(APP_DATA_DIR, "Logs")

# Crear directorios si no existen (se puede hacer aquí o en main.py al inicio)
os.makedirs(LOG_DIR, exist_ok=True)

# --- Configuración de Logging (Ejemplo básico) ---
LOG_FILE_PATH = os.path.join(LOG_DIR, f"{APP_NAME.lower()}.log")
LOG_LEVEL = logging.DEBUG # Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)

# Handlers (pueden ser configurados más detalladamente en main.py o un módulo de logging)
# LOG_FILE_HANDLER = logging.FileHandler(LOG_FILE_PATH, encoding='utf-8')
# CONSOLE_HANDLER = logging.StreamHandler()

settings = locals() # Exporta todas las variables locales como un diccionario