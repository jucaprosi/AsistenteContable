# d:\Datos\Desktop\Asistente Contable\src\core\worker_tasks.py
import os
import logging
import shutil # Importar shutil para copiar archivos
from typing import List, Optional, Dict, Any
from datetime import datetime # Importar datetime para obtener el año actual
from PySide6.QtCore import QStandardPaths # Importar QStandardPaths para obtener la ruta de AppData

# Importa directamente los módulos que la tarea necesita,
# evitando cualquier importación de la GUI.
from src.core import xml_parser
from src.core.pdf_generator import generate_pdf_from_xml # generate_pdf_from_xml ahora devuelve la ruta del PDF temporal
# No necesitamos create_temp_folder aquí si temp_pdf_dir_arg ya es una ruta creada

logger = logging.getLogger(__name__) # Esto usará la configuración de logging del proceso principal

# Constante para el nombre de la carpeta de respaldo (debe coincidir con MainWindow)
BACKUP_FOLDER_NAME = "contribuyentes"

def process_single_xml_file_task(
    xml_path_arg: str, 
    temp_pdf_dir_arg: str, 
    # emisor_logo_path_arg eliminado
) -> Dict[str, Any]:
    """
    Procesa un único archivo XML: parsea, extrae datos, genera PDF y realiza respaldo.
    Esta función se ejecuta en un proceso hijo.
    """
    try:
        conversion_errors_this_file: List[str] = []
        parsed_data = xml_parser.parse_xml(xml_path_arg)
        if not parsed_data:
            return {"xml_path": xml_path_arg, "error": "Error de parseo XML."}

        actual_cod_doc = parsed_data.get('info_tributaria', {}).get('cod_doc')
        actual_id_raw = parsed_data.get("id_comprador_raw")
        unique_id = xml_parser.get_unique_identifier(parsed_data)

        row_data = xml_parser.extract_data_from_xml(
            parsed_data, xml_path_arg, actual_cod_doc, actual_id_raw, conversion_errors_this_file
        )
        if not row_data:
            return {"xml_path": xml_path_arg, "error": "No se pudieron extraer datos para la tabla."}
        # Asegurar que unique_id y fechaAutorizacion estén en row_data para la GUI/Exportación
        row_data["Nro de Autorización"] = unique_id
        row_data["fechaAutorizacion"] = parsed_data.get('fecha_autorizacion') # Fecha de autorización del XML principal

        temp_pdf_path_result = None
        pdf_error_result = None
        if temp_pdf_dir_arg:
            try:
                # generate_pdf_from_xml ya no toma el logo del emisor
                temp_pdf_path_result = generate_pdf_from_xml(xml_path_arg, temp_pdf_dir_arg)
            except Exception as e_pdf_process:
                pdf_error_result = f"Error PDF: {e_pdf_process}"

        # --- Lógica de Respaldo ---
        backup_pdf_path_result = None # Inicializar la ruta del PDF de respaldo
        backup_xml_path_result = None # Inicializar la ruta del XML de respaldo

        # Necesitamos el año y el ID del comprador para la estructura de respaldo
        year = None
        # Intentar obtener el año de la fecha de autorización
        fecha_autorizacion_dt = parsed_data.get('fecha_autorizacion_dt')
        if isinstance(fecha_autorizacion_dt, datetime):
             year = str(fecha_autorizacion_dt.year)
        else:
            # Fallback: intentar obtener el año de la fecha de emisión si la fecha de autorización no está
            fecha_emision_str = parsed_data.get('doc_especifico', {}).get('fecha_emision')
            if fecha_emision_str:
                try:
                    # Asumir formato DD/MM/YYYY para fechaEmision
                    date_obj_emision = datetime.strptime(fecha_emision_str, '%d/%m/%Y')
                    year = str(date_obj_emision.year)
                except ValueError:
                    logger.warning(f"Worker: No se pudo parsear fechaEmision '{fecha_emision_str}' para año de respaldo en {os.path.basename(xml_path_arg)}.")

        # Fallback final al año actual si no se pudo determinar
        if not year:
            year = str(datetime.now().year)
            logger.warning(f"Worker: No se pudo determinar el año para {os.path.basename(xml_path_arg)}. Usando año actual ({year}) para respaldo.")


        # Obtener el ID del comprador/sujeto retenido
        buyer_id = parsed_data.get('comprador', {}).get('identificacion')
        if not buyer_id:
             logger.warning(f"Worker: No se encontró ID de comprador/sujeto retenido para {os.path.basename(xml_path_arg)}. Usando 'Desconocido' para respaldo.")
             buyer_id = "Desconocido"

        # Usar el número de autorización como nombre de archivo base para el respaldo
        backup_filename_base = unique_id
        if not backup_filename_base:
             # Fallback si no hay número de autorización ni clave de acceso
             backup_filename_base = f"SIN_AUT_{os.path.basename(xml_path_arg).replace('.xml', '')}"
             logger.warning(f"Worker: No se encontró número de autorización para {os.path.basename(xml_path_arg)}. Usando '{backup_filename_base}' como nombre base para respaldo.")


        if year and buyer_id and backup_filename_base:
            try:
                # Obtener la ruta de AppData
                appdata_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
                if not appdata_dir:
                    logger.error("Worker: No se pudo encontrar la ubicación de AppData para el respaldo.")
                else:
                    backup_base_dir = os.path.join(appdata_dir, BACKUP_FOLDER_NAME)
                    # Limpiar el ID del comprador para usarlo como nombre de carpeta
                    buyer_id_safe_folder = "".join(c if c.isalnum() else "_" for c in buyer_id)
                    if not buyer_id_safe_folder: buyer_id_safe_folder = "ID_Desconocido" # Fallback si el ID limpiado queda vacío

                    backup_year_dir = os.path.join(backup_base_dir, year)
                    backup_buyer_dir = os.path.join(backup_year_dir, buyer_id_safe_folder)

                    # Crear directorios si no existen
                    os.makedirs(backup_buyer_dir, exist_ok=True)
                    logger.debug(f"Worker: Directorio de respaldo asegurado: {backup_buyer_dir}")

                    # Rutas de destino para el respaldo
                    backup_xml_path_result = os.path.join(backup_buyer_dir, f"{backup_filename_base}.xml")
                    backup_pdf_path_result = os.path.join(backup_buyer_dir, f"{backup_filename_base}.pdf")

                    # Verificar si el archivo XML de respaldo ya existe para evitar duplicados
                    if not os.path.exists(backup_xml_path_result):
                        try:
                            # Copiar el archivo XML original
                            shutil.copy2(xml_path_arg, backup_xml_path_result)
                            logger.debug(f"Worker: XML respaldado en: {backup_xml_path_result}")

                            # Copiar el archivo PDF temporal si se generó exitosamente
                            if temp_pdf_path_result and os.path.exists(temp_pdf_path_result):
                                shutil.copy2(temp_pdf_path_result, backup_pdf_path_result)
                                logger.debug(f"Worker: PDF respaldado en: {backup_pdf_path_result}")
                            elif temp_pdf_path_result:
                                logger.warning(f"Worker: PDF temporal no encontrado para respaldo: {temp_pdf_path_result}")
                            else:
                                logger.warning(f"Worker: No se generó PDF temporal para respaldo de {os.path.basename(xml_path_arg)}.")

                        except Exception as backup_copy_error:
                            logger.error(f"Worker: Error durante la copia de respaldo para {os.path.basename(xml_path_arg)}: {backup_copy_error}")
                            # Si falla la copia, no reportar la ruta de respaldo exitosa
                            backup_xml_path_result = None
                            backup_pdf_path_result = None
                    else:
                        logger.info(f"Worker: Respaldo para {os.path.basename(xml_path_arg)} (Num Aut: {backup_filename_base}) ya existe. Omitiendo copia.")
                        # Si el XML ya existe, verificar si el PDF también existe y reportar la ruta si es así
                        if os.path.exists(backup_pdf_path_result):
                             logger.debug(f"Worker: PDF de respaldo existente encontrado: {backup_pdf_path_result}")
                        else:
                             # Si el XML existe pero el PDF no, esto podría indicar un respaldo incompleto previo.
                             # Podríamos intentar copiar solo el PDF aquí si temp_pdf_path_result existe.
                             # Por ahora, solo logueamos y no reportamos la ruta del PDF de respaldo.
                             logger.warning(f"Worker: XML de respaldo existe pero PDF no para {os.path.basename(xml_path_arg)}. PDF de respaldo no reportado.")
                             backup_pdf_path_result = None # No reportar la ruta del PDF de respaldo si no existe

            except Exception as general_backup_setup_error:
                logger.error(f"Worker: Error general configurando respaldo para {os.path.basename(xml_path_arg)}: {general_backup_setup_error}")
                backup_xml_path_result = None
                backup_pdf_path_result = None
        else:
            logger.warning(f"Worker: Datos insuficientes (año, buyer_id o unique_id) para realizar respaldo de {os.path.basename(xml_path_arg)}. Respaldo omitido.")


        # --- Fin Lógica de Respaldo ---


        return {
            "xml_path": xml_path_arg,
            "temp_pdf_path": temp_pdf_path_result, # Ruta del PDF temporal
            "backup_pdf_path": backup_pdf_path_result, # Ruta del PDF de respaldo (si se realizó)
            "row_data": row_data,
            "cod_doc": actual_cod_doc,
            "unique_id": unique_id,
            "conversion_errors": conversion_errors_this_file,
            "pdf_error": pdf_error_result,
            "error": None # No hay error crítico de procesamiento si llegamos aquí
        }
    except Exception as e_process_file:
        logger.exception(f"Error procesando archivo {os.path.basename(xml_path_arg)} en proceso hijo (worker_tasks):")
        return {"xml_path": xml_path_arg, "error": f"Child Crash in worker_tasks: {type(e_process_file).__name__}: {e_process_file}"}
