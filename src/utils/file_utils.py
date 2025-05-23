# d:\Datos\Desktop\Asistente Contable\src\utils\file_utils.py
import os
import shutil
import zipfile
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

def cleanup_temp_folder(folder_path: str):
    """
    Elimina una carpeta y todo su contenido.
    """
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        try:
            shutil.rmtree(folder_path)
            logger.info(f"Carpeta temporal eliminada: {folder_path}")
        except Exception as e:
            logger.error(f"Error al eliminar la carpeta temporal {folder_path}: {e}")
    else:
        logger.warning(f"La carpeta temporal no existe o no es un directorio: {folder_path}")

def create_zip_archive(files_to_add: List[Tuple[str, str]], zip_filepath: str) -> bool:
    """
    Crea un archivo ZIP con los archivos especificados.

    Args:
        files_to_add: Una lista de tuplas, donde cada tupla contiene:
                      (ruta_completa_al_archivo, nombre_del_archivo_en_el_zip)
        zip_filepath: La ruta completa donde se guardará el archivo ZIP.

    Returns:
        True si el ZIP se creó exitosamente, False en caso contrario.
    """
    try:
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path, arcname in files_to_add:
                if os.path.exists(file_path):
                    zipf.write(file_path, arcname)
                    logger.debug(f"Añadido al ZIP '{zip_filepath}': '{file_path}' como '{arcname}'")
                else:
                    logger.warning(f"Archivo no encontrado, no se añadió al ZIP '{zip_filepath}': {file_path}")
        logger.info(f"Archivo ZIP creado exitosamente: {zip_filepath}")
        return True
    except Exception as e:
        logger.error(f"Error al crear el archivo ZIP '{zip_filepath}': {e}")
        # Asegurarse de eliminar un ZIP parcialmente creado si falla
        if os.path.exists(zip_filepath):
            try:
                os.remove(zip_filepath)
            except Exception as e_remove:
                logger.error(f"Error al intentar eliminar ZIP parcialmente creado '{zip_filepath}': {e_remove}")
        return False
