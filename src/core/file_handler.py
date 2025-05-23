# d:\Datos\Desktop\Asistente Contable\src\core\file_handler.py
import os
import zipfile
import tempfile
import shutil
import logging
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, ParseError
from typing import List, Tuple, Optional, Callable, Dict, Any
# from PySide6.QtCore import QStandardPaths # No se usa actualmente aquí
from reportlab.lib import colors
# Importar funciones de parseo y generación de PDF
from .xml_parser import parse_xml
from .pdf_invoice_generator import generate_invoice_pdf # Para Facturas
from .pdf_generator import generate_other_document_pdf # Para otros documentos
from reportlab.platypus.flowables import Flowable

# Importar FONTS_DIR desde pdf_base para consistencia
from .pdf_base import FONTS_DIR


logger = logging.getLogger(__name__)

# --- Excepción personalizada para interrupciones (si se usa aquí) ---
class InterruptionRequestedError(Exception):
    pass

# --- Funciones auxiliares para parseo de XML (movidas o duplicadas de main_window) ---
def _get_text_from_element(element: Optional[ET.Element], default: str = "") -> str:
    return element.text.strip() if element is not None and element.text else default

def _parse_cdata_comprobante(xml_path: str) -> Optional[ET.Element]:
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        comprobante_cdata_element = root.find('.//comprobante')
        if comprobante_cdata_element is not None and comprobante_cdata_element.text:
            cdata_content = comprobante_cdata_element.text.strip()
            # Intentar parsear el contenido CDATA como XML
            comprobante_root = ET.fromstring(cdata_content)
            return comprobante_root
    except ET.ParseError as e_parse:
        logger.error(f"Error de parseo XML (CDATA o principal) en {xml_path}: {e_parse}")
    except Exception as e_gen:
        logger.error(f"Error inesperado procesando CDATA de {xml_path}: {e_gen}")
    return None

def _get_numero_autorizacion_from_xml(xml_path: str) -> Optional[str]:
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        num_auth_element = root.find('.//numeroAutorizacion')
        if num_auth_element is not None and num_auth_element.text:
            return num_auth_element.text.strip()
        # Fallback: intentar buscar claveAcceso si numeroAutorizacion no está
        clave_acceso_element = root.find('.//claveAcceso')
        if clave_acceso_element is not None and clave_acceso_element.text:
            logger.warning(f"No se encontró 'numeroAutorizacion', usando 'claveAcceso' para {os.path.basename(xml_path)}")
            return clave_acceso_element.text.strip()
            
        logger.warning(f"No se encontró 'numeroAutorizacion' ni 'claveAcceso' en {os.path.basename(xml_path)}")
        return None
    except ET.ParseError as e_parse:
        logger.error(f"Error de parseo XML al obtener número de autorización de: {xml_path}: {e_parse}")
        return None # O un valor especial de error si se prefiere
    except Exception as e_gen:
        logger.error(f"Error inesperado al obtener número de autorización de: {xml_path}: {e_gen}")
        return None


# --- Clase para dibujar línea horizontal ---
class HorizontalLine(Flowable):
    def __init__(self, width, thickness=0.5, color=colors.black, dash=None):
        Flowable.__init__(self)
        self.width = width
        self.thickness = thickness
        self.color = color
        self.dash = dash

    def draw(self):
        self.canv.saveState()
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        if self.dash:
            self.canv.setDash(self.dash)
        self.canv.line(0, 0, self.width, 0)
        self.canv.restoreState()

def process_xmls_to_temp_pdfs(
    xml_files: List[str],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[str], List[str]]: # Cambiado el tipo de retorno para la lista de paths
    """
    Procesa una lista de archivos XML, genera un PDF para cada uno en una carpeta temporal
    y devuelve las rutas de los PDFs generados y una lista de errores.

    Args:
        xml_files: Lista de rutas a los archivos XML a procesar.
        progress_callback: Función opcional para reportar progreso.

    Returns:
        Tuple[List[str], List[str]]:
            - Un diccionario mapeando la ruta del XML original a la ruta del PDF generado.
            - Una lista de mensajes de error/advertencia.
    """
    xml_to_pdf_map: Dict[str, str] = {} # XML path -> PDF path
    errors = []
    temp_pdf_dir = "" # Inicializar para que esté disponible en finally si se usa
    
    if not xml_files:
        return {}, ["No se proporcionaron archivos XML para procesar."]

    try:
        # Crear un directorio temporal único para los PDFs de esta ejecución
        # Usar un prefijo específico para identificar fácilmente estas carpetas
        temp_pdf_dir = tempfile.mkdtemp(prefix="ac_pdfs_")
        logger.info(f"Directorio temporal para PDFs creado en: {temp_pdf_dir}")

        total_files = len(xml_files)
        for i, xml_file_path in enumerate(xml_files):
            if progress_callback:
                 try:
                     progress_callback(i, total_files, os.path.basename(xml_file_path))
                 except InterruptionRequestedError as ire_cb: # Capturar interrupción desde el callback
                     logger.info(f"Proceso interrumpido por el usuario durante callback: {ire_cb}")
                     errors.append(str(ire_cb))
                     return list(xml_to_pdf_map.values()), errors # Devolver lo generado hasta ahora como lista

            parsed_data = parse_xml(xml_file_path)

            try:
                if parsed_data:
                    doc_type = parsed_data.get('tipo_documento')
                    generated_pdf_path = None
                    if doc_type == 'Factura': # generate_invoice_pdf ya no espera logo_path
                        generated_pdf_path = generate_invoice_pdf(parsed_data, temp_pdf_dir)
                    elif doc_type in ['Nota de Crédito', 'Nota de Débito', 'Comprobante de Retención', 'Liquidación de Compra de Bienes y Prestación de Servicios', 'Guía de Remisión']:
                         generated_pdf_path = generate_other_document_pdf(parsed_data, temp_pdf_dir)
                    else:
                        error_msg = f"Tipo de documento '{doc_type}' no soportado para generación de PDF: {os.path.basename(xml_file_path)}"
                        logger.warning(error_msg)
                        errors.append(error_msg)

                    if generated_pdf_path:
                        xml_to_pdf_map[xml_file_path] = generated_pdf_path # Mantener el mapa temporalmente

            except InterruptionRequestedError as ire:
                logger.info(f"Generación de PDF interrumpida por el usuario: {ire}")
                errors.append(str(ire))
                return xml_to_pdf_map, errors # Devolver lo generado hasta ahora
            except Exception as e:
                error_msg = f"Error generando PDF para {os.path.basename(xml_file_path)}: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)
            except Exception as e_gen: # Capturar otros errores durante la generación
                 error_msg = f"Error inesperado durante la generación de PDF para {os.path.basename(xml_file_path)}: {e_gen}"
                 logger.exception(error_msg)
                 errors.append(error_msg)
        
        # Este es el return si el bucle for se completa sin un return temprano (por interrupción)
        return list(xml_to_pdf_map.values()), errors # Devolver la lista de paths generados

    except Exception as e_main_process: # Clausula except para el try principal
        logger.exception(f"Error mayor durante el procesamiento de PDFs: {e_main_process}")
        errors.append(f"Error crítico en el proceso: {e_main_process}")
        return list(xml_to_pdf_map.values()), errors # Devolver lo que se haya acumulado como lista
    finally: # Clausula finally para el try principal
        # La limpieza del directorio temporal se maneja externamente por MainWindow.
        # Si se quisiera limpiar aquí, se podría añadir lógica, pero es mejor mantenerlo como está.
        # Por ejemplo:
        # if temp_pdf_dir and os.path.isdir(temp_pdf_dir) and not xml_to_pdf_map: # Limpiar solo si no se generaron PDFs
        #     cleanup_temp_folder(temp_pdf_dir)
        pass

def cleanup_temp_folder(folder_path: str):
    """Elimina la carpeta temporal y su contenido."""
    if folder_path and os.path.isdir(folder_path):
        try:
            shutil.rmtree(folder_path)
            logger.info(f"Carpeta temporal {folder_path} eliminada.")
        except Exception as e:
            logger.error(f"No se pudo eliminar la carpeta temporal {folder_path}: {e}")
    else:
        logger.warning(f"Intento de limpiar una carpeta temporal no válida o inexistente: {folder_path}")


def create_zip_archive(files_to_add: List[Tuple[str, str]], zip_path: str) -> bool:
    """
    Crea un archivo ZIP con los archivos especificados.

    Args:
        files_to_add: Lista de tuplas, donde cada tupla es 
                      (ruta_completa_al_archivo, nombre_del_archivo_en_el_zip).
        zip_path: Ruta completa donde se guardará el archivo ZIP.

    Returns:
        True si el ZIP se creó con éxito, False en caso contrario.
    """
    if not files_to_add:
        logger.warning("No hay archivos para agregar al ZIP.")
        return False
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path, arcname in files_to_add:
                if os.path.exists(file_path):
                    zipf.write(file_path, arcname)
                else:
                    logger.warning(f"Archivo no encontrado, no se agregará al ZIP: {file_path}")
        logger.info(f"Archivo ZIP creado exitosamente en: {zip_path}")
        return True
    except Exception as e:
        logger.error(f"Error creando archivo ZIP en {zip_path}: {e}")
        return False
