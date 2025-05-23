import sys
import os
import logging
from logging.handlers import RotatingFileHandler

# Añadir estas importaciones para el perfilado
import cProfile
import multiprocessing # Necesario para freeze_support()
import pstats

# Añadir el directorio 'src' al PYTHONPATH para que se puedan importar los módulos
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QStandardPaths

# Importar MainWindow después de ajustar el path
from gui.main_window import MainWindow # Asegúrate que esta ruta sea correcta

# --- Configuración del Logging ---
ORGANIZATION_NAME = "Business & Services"
APPLICATION_NAME = "AsistenteContable"

def setup_logging():
    # ... (tu configuración de logging existente) ...
    log_dir_path = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if not log_dir_path: # Fallback si AppLocalDataLocation no está disponible
        log_dir_path = os.path.join(os.path.expanduser("~"), ".local", "share", ORGANIZATION_NAME, APPLICATION_NAME, "Logs")
    
    # Asegurar que el nombre de la carpeta de la organización y aplicación sean válidos para nombres de directorio
    safe_org_name = "".join(c if c.isalnum() else "_" for c in ORGANIZATION_NAME)
    safe_app_name = "".join(c if c.isalnum() else "_" for c in APPLICATION_NAME)

    # Reconstruir log_dir_path con nombres seguros si es necesario, o usar la estructura original
    # Esto es un ejemplo, ajusta según cómo quieras la ruta final
    if QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation):
         # Si se usa QStandardPaths, ya debería manejar bien los nombres.
         # Pero si construyes manualmente, la limpieza es buena idea.
         log_dir_path = os.path.join(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation), "Logs")
    else: # Fallback
        log_dir_path = os.path.join(os.path.expanduser("~"), ".local", "share", safe_org_name, safe_app_name, "Logs")


    if not os.path.exists(log_dir_path):
        try:
            os.makedirs(log_dir_path, exist_ok=True)
        except OSError as e:
            print(f"Error al crear directorio de logs {log_dir_path}: {e}", file=sys.stderr)
            # Usar un directorio temporal como último recurso
            import tempfile
            log_dir_path = tempfile.mkdtemp(prefix=f"{safe_app_name}_logs_")
            print(f"Usando directorio de logs temporal: {log_dir_path}", file=sys.stderr)


    log_file_path = os.path.join(log_dir_path, "asistentecontable.log")

    # Configuración del logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG) # Capturar todos los niveles desde DEBUG hacia arriba

    # Formateador
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - [%(filename)s:%(lineno)d] - %(message)s')

    # Manejador para la consola (solo INFO y superior)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    if not any(isinstance(h, logging.StreamHandler) and h.stream == sys.stdout for h in root_logger.handlers):
        root_logger.addHandler(console_handler)

    # Manejador para el archivo (DEBUG y superior, con rotación)
    try:
        file_handler = RotatingFileHandler(log_file_path, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == os.path.abspath(log_file_path) for h in root_logger.handlers):
            root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error al configurar el logging a archivo {log_file_path}: {e}", file=sys.stderr)


    logging.info(f"--- Iniciando {APPLICATION_NAME} ---")
    logging.info(f"Directorio de logs: {log_dir_path}")
    logging.info(f"Archivo de log: {log_file_path}")


if __name__ == "__main__":
    # Es CRUCIAL para aplicaciones empaquetadas con PyInstaller que usan multiprocessing en Windows
    # Debe ser una de las primeras cosas en el bloque if __name__ == "__main__":
    multiprocessing.freeze_support()

    setup_logging()

    # Iniciar el perfilador
    profiler = cProfile.Profile()
    profiler.enable()

    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        logging.info("Interfaz gráfica iniciada.")
        exit_code = app.exec() # Guardar el código de salida
    except Exception as e:
        logging.critical("Excepción no controlada en el nivel principal de la aplicación.", exc_info=True)
        exit_code = 1 # Indicar un error
    finally:
        # Detener el perfilador y mostrar estadísticas
        profiler.disable()
        logging.info("Generando estadísticas de perfilado...")
        # Crear un stream para las estadísticas si quieres guardarlas en un archivo
        # o simplemente imprimirlas a la consola.
        # stats_file_path = os.path.join(os.path.dirname(logging.getLogger().handlers[-1].baseFilename) if logging.getLogger().handlers else ".", "profile_stats.txt")
        # with open(stats_file_path, "w") as f:
        #     ps = pstats.Stats(profiler, stream=f).sort_stats('cumulative')
        #     ps.print_stats(30) # Imprime las 30 funciones que más tiempo consumen
        # logging.info(f"Estadísticas de perfilado guardadas en: {stats_file_path}")
        
        # O imprimir a la consola:
        ps = pstats.Stats(profiler, stream=sys.stdout).sort_stats('cumulative')
        ps.print_stats(30)
        logging.info("Estadísticas de perfilado impresas en consola.")

        sys.exit(exit_code)
