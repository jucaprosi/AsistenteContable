# d:\Datos\Desktop\Asistente Contable\src\gui\main_window.py
from datetime import datetime
import os
import sys
from typing import List, Optional, Dict, Any, Tuple, Set
import logging
import subprocess # Añadido para abrir PDFs y carpetas
import re # Añadido para expresiones regulares en nombres de carpeta ZIP
from collections import defaultdict

from concurrent.futures import ProcessPoolExecutor, as_completed
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QDialog, QProgressDialog,
    QPushButton, QFileDialog, QLabel, QMessageBox, QDialogButtonBox, QStyle, QStyleOptionHeader,
    QTableWidget, QTableWidgetItem, QHeaderView, QStyledItemDelegate, QStyleOptionViewItem
)

import urllib.request # Para comprobar actualizaciones
import urllib.parse # Para parsear URLs en start_update_download
from PySide6.QtCore import Qt, QThread, Signal, Slot, QModelIndex, QSize, QRect, QSettings, QStandardPaths, QMutex, QWaitCondition, QUrl
from PySide6.QtGui import QColor, QPainter, QPalette, QBrush, QFontMetrics, QDesktopServices
import threading # Para ejecutar la comprobación en segundo plano

from src.core import xml_parser # Para multiprocesamiento
from src.core.pdf_generator import create_temp_folder
from src.utils.file_utils import cleanup_temp_folder, create_zip_archive
from src.gui.progress_popup import ProgressPopup # Asegúrate que esta línea esté antes de la siguiente si ProgressPopup usa algo de exporter
from src.utils.exporter import export_to_excel, ExcelExportStatus
from src.gui.entity_clarification_dialog import EntityClarificationDialog
from src.core.worker_tasks import process_single_xml_file_task # Importar la tarea del worker
from src.gui.export_type_selection_dialog import ExportTypeSelectionDialog
from src.gui.id_type_selection_dialog import IdTypeSelectionDialog
from src.gui.download_thread import DownloadThread # <--- AÑADIR IMPORTACIÓN

logger = logging.getLogger(__name__)

ORGANIZATION_NAME = "Business & Services"
APPLICATION_NAME = "AsistenteContable"
SETTINGS_LAST_XML_DIR = "paths/last_xml_dir"
SETTINGS_LAST_ZIP_DIR = "paths/last_zip_dir"

# Mapping for month numbers to Spanish names for folder creation
MONTH_NAMES_SPANISH = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
    7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE"
}

# Regex to clean up folder names
FOLDER_NAME_CLEAN_REGEX = re.compile(r'[^\w\s-]') # Keep alphanumeric, space, hyphen
SPACE_HYPHEN_NORM_REGEX = re.compile(r'[-\s]+') # Replace multiple spaces/hyphens with a single space

# --- Configuración de Actualizaciones ---
APP_VERSION = "1.1.3" # <--- Define aquí la versión actual de tu aplicación
UPDATE_CHECK_URL = "https://contabilidadsri.com/latest_version.txt"

# --- Constantes para Hipervínculos en Tabla ---
USER_ROLE_PDF_PATH = Qt.UserRole + 1 # Usar un rol de usuario para guardar la ruta del PDF


def _is_value_significant_for_display(value: Any) -> bool:
    """
    Determina si un valor es 'significativo' para la visualización o exportación.
    Un valor no es significativo si es None, una cadena vacía/espacios en blanco,
    o una colección vacía. Los números (incluido el 0) se consideran significativos.
    """
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


class InterruptionRequestedError(Exception):
    pass

class WorkerThread(QThread):
    initial_info_to_popup = Signal(str)
    progress_total_files_to_popup = Signal(int)
    entity_base_clarification_needed = Signal(dict)
    id_type_for_entity_base_clarification_needed = Signal(str, list)
    entity_determined = Signal(dict, bool, str, dict, set)
    row_processed = Signal(dict, str, object)
    entity_id_mismatch_on_add_more = Signal(str, str, str)
    processing_complete = Signal(list, list, list, bool, str, int, int, list, int, dict, dict)
    log_message_to_gui = Signal(str)

    _mutex = QMutex()
    _wait_condition = QWaitCondition()
    _selected_id_base_from_gui: Optional[str] = None
    _selected_id_type_for_base_from_gui: Optional[str] = None
    _is_interruption_requested: bool = False
    _worker_was_cancelled_by_user: bool = False
    _temp_pdf_dir_created_by_this_run: str = ""

    def __init__(self, xml_files: List[str],
                 current_gui_entity_id_display: Optional[str],
                 current_gui_entity_rs: Optional[str],
                 is_gui_initial_process_done: bool,
                 already_processed_ids_for_entity: Set[str]): # logo_path (asesor) eliminado
        super().__init__()
        self.xml_files = xml_files
        self.current_gui_entity_id_display = current_gui_entity_id_display
        self.current_gui_entity_rs = current_gui_entity_rs
        self.is_gui_initial_process_done = is_gui_initial_process_done
        self.already_processed_ids = already_processed_ids_for_entity
        # self.logo_path (asesor) eliminado
        self._is_interruption_requested = False
        self._worker_was_cancelled_by_user = False
        self._compradores_info_map: Dict[str, Dict[str, Any]] = {}
        self.processed_counts_by_type = defaultdict(int)

    def request_interruption(self):
        logger.info("Solicitud de interrupción para el hilo de trabajo.")
        self._mutex.lock()
        try:
            self._is_interruption_requested = True
            self._worker_was_cancelled_by_user = True
            self._wait_condition.wakeAll()
        finally:
            self._mutex.unlock()

    def _check_interruption(self):
        if self._is_interruption_requested:
            raise InterruptionRequestedError("Interrupción solicitada.")

    def set_selected_id_base(self, selected_id_base: Optional[str]):
        self._mutex.lock()
        try:
            self._selected_id_base_from_gui = selected_id_base
            self._wait_condition.wakeAll()
        finally:
            self._mutex.unlock()

    def set_selected_id_type_for_base(self, selected_id_type: Optional[str]):
        self._mutex.lock()
        try:
            self._selected_id_type_for_base_from_gui = selected_id_type.lower() if selected_id_type else None
            self._wait_condition.wakeAll()
        finally:
            self._mutex.unlock()

    def _pre_analyze_xmls_for_compradores(self):
        self.initial_info_to_popup.emit("Analizando archivos XML para identificar compradores...")
        self._compradores_info_map.clear()
        def classify_id(id_str: str) -> str:
            if not id_str: return "desconocido"
            if id_str.isdigit():
                if len(id_str) == 10: return "cedula"
                if len(id_str) == 13 and id_str.endswith("001"): return "ruc_persona_natural"
                if len(id_str) == 13: return "ruc_sociedad"
            return "otro"
        def get_id_base(id_str: str, id_type: str) -> str:
            if id_type == "ruc_persona_natural": return id_str[:10]
            return id_str
        for i, xml_path in enumerate(self.xml_files):
            self._check_interruption()
            try:
                parsed_data = xml_parser.parse_xml(xml_path)
                if parsed_data:
                    id_c_raw = parsed_data.get("id_comprador_raw", "N/A")
                    rs_c = parsed_data.get("comprador", {}).get("razon_social", "N/A")
                    if id_c_raw != "N/A" and rs_c != "N/A":
                        rs_c = rs_c.strip()
                        id_type = classify_id(id_c_raw)
                        id_base_for_map = get_id_base(id_c_raw, id_type)
                        if id_base_for_map not in self._compradores_info_map:
                            self._compradores_info_map[id_base_for_map] = {"razon_social_canonica": rs_c, "ids_especificos": {}}
                        current_canonical_rs = self._compradores_info_map[id_base_for_map]["razon_social_canonica"].upper()
                        if "CONSUMIDOR FINAL" in current_canonical_rs and "CONSUMIDOR FINAL" not in rs_c.upper():
                            self._compradores_info_map[id_base_for_map]["razon_social_canonica"] = rs_c
                        elif not current_canonical_rs and rs_c:
                             self._compradores_info_map[id_base_for_map]["razon_social_canonica"] = rs_c
                        if id_c_raw not in self._compradores_info_map[id_base_for_map]["ids_especificos"]:
                            self._compradores_info_map[id_base_for_map]["ids_especificos"][id_c_raw] = {"tipo": id_type, "paths": []}
                        self._compradores_info_map[id_base_for_map]["ids_especificos"][id_c_raw]["paths"].append(xml_path)
            except Exception as e_pre: logger.error(f"Error en pre-análisis de {os.path.basename(xml_path)}: {e_pre}")
        if not self._compradores_info_map:
            self.log_message_to_gui.emit("No se pudo extraer información de comprador válida de ningún archivo XML.")
            return None
        return self._compradores_info_map

    def run(self):
        self._selected_id_base_from_gui = None
        self._selected_id_type_for_base_from_gui = None
        self._is_interruption_requested = False
        self._worker_was_cancelled_by_user = False
        self._temp_pdf_dir_created_by_this_run = ""
        all_conversion_errors_for_run: List[str] = []
        critical_file_processing_errors_for_run: List[Dict[str,str]] = []
        all_pdf_gen_errors_for_run: List[str] = []
        xml_to_pdf_map_generated_for_run: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {}
        newly_processed_count = 0
        skipped_duplicate_files_count = 0
        newly_added_identifiers_this_run: List[str] = []
        self.processed_counts_by_type = defaultdict(int)
        xml_files_to_process_final_batch: List[str] = []

        try:
            if not self._pre_analyze_xmls_for_compradores(): return
            self._check_interruption()

            id_base_to_process: Optional[str] = None
            if len(self._compradores_info_map) == 1:
                id_base_to_process = list(self._compradores_info_map.keys())[0]
            else:
                opciones_para_dialogo = {idb: data["razon_social_canonica"] for idb, data in self._compradores_info_map.items()}
                self.entity_base_clarification_needed.emit(opciones_para_dialogo)
                self._mutex.lock();
                try:
                    while self._selected_id_base_from_gui is None and not self._is_interruption_requested: self._wait_condition.wait(self._mutex)
                    self._check_interruption(); id_base_to_process = self._selected_id_base_from_gui
                finally: self._mutex.unlock()
            if not id_base_to_process: raise InterruptionRequestedError("Selección de ID base cancelada o fallida.")

            if self.is_gui_initial_process_done:
                # Ensure current_gui_entity_id_display is not None before splitting
                current_gui_id_parts = [p.strip() for p in (self.current_gui_entity_id_display or "").split('/') if p.strip()]
                current_gui_id_base_for_check = current_gui_id_parts[0][:10] if current_gui_id_parts and len(current_gui_id_parts[0]) == 13 and current_gui_id_parts[0].endswith("001") else (current_gui_id_parts[0] if current_gui_id_parts else None)
                
                if current_gui_id_base_for_check and id_base_to_process != current_gui_id_base_for_check:
                    self.entity_id_mismatch_on_add_more.emit(
                        str(self.current_gui_entity_rs), str(self.current_gui_entity_id_display),
                        self._compradores_info_map[id_base_to_process]["razon_social_canonica"]
                    )
                    self.request_interruption(); return

            comprador_data_seleccionado = self._compradores_info_map[id_base_to_process]
            razon_social_canonica_seleccionada = comprador_data_seleccionado["razon_social_canonica"]
            ids_especificos_del_base = comprador_data_seleccionado["ids_especificos"]
            id_type_to_process_final: Optional[str] = None
            es_cedula_base = ids_especificos_del_base.get(id_base_to_process, {}).get("tipo") == "cedula"
            ruc_pn_derivado_de_base = f"{id_base_to_process}001"
            tiene_ruc_pn_asociado = ruc_pn_derivado_de_base in ids_especificos_del_base and ids_especificos_del_base[ruc_pn_derivado_de_base].get("tipo") == "ruc_persona_natural"

            if es_cedula_base and tiene_ruc_pn_asociado:
                self.id_type_for_entity_base_clarification_needed.emit(razon_social_canonica_seleccionada, ["RUC", "Cédula", "Ambos"])
                self._mutex.lock();
                try:
                    while self._selected_id_type_for_base_from_gui is None and not self._is_interruption_requested: self._wait_condition.wait(self._mutex)
                    self._check_interruption(); id_type_to_process_final = self._selected_id_type_for_base_from_gui
                finally: self._mutex.unlock()
                if not id_type_to_process_final: raise InterruptionRequestedError("Selección de tipo de ID (Cédula/RUC) cancelada.")

            xml_files_for_selected_entity_and_id_type: List[str] = []
            id_display_for_gui = id_base_to_process
            if id_type_to_process_final == "ambos":
                if es_cedula_base: xml_files_for_selected_entity_and_id_type.extend(ids_especificos_del_base[id_base_to_process]["paths"])
                if tiene_ruc_pn_asociado: xml_files_for_selected_entity_and_id_type.extend(ids_especificos_del_base[ruc_pn_derivado_de_base]["paths"])
                id_display_for_gui = f"{id_base_to_process} / {ruc_pn_derivado_de_base}"
            elif id_type_to_process_final == "ruc" and tiene_ruc_pn_asociado and ruc_pn_derivado_de_base in ids_especificos_del_base:
                xml_files_for_selected_entity_and_id_type.extend(ids_especificos_del_base[ruc_pn_derivado_de_base]["paths"])
            else: # Si no hay clarificación de Cédula/RUC, o no aplica, tomar todos los paths del ID base
                for id_xml, data_id_xml in ids_especificos_del_base.items():
                    xml_files_for_selected_entity_and_id_type.extend(data_id_xml["paths"])

            if not xml_files_for_selected_entity_and_id_type:
                self.log_message_to_gui.emit(f"No hay archivos para la selección de entidad/tipo ID: {id_display_for_gui}"); return

            xml_files_to_process_final_batch = list(set(xml_files_for_selected_entity_and_id_type))

            header_data_for_gui_final = {
                "id_comprador": id_display_for_gui,
                "razon_social_comprador": razon_social_canonica_seleccionada,
                "id_comprador_raw": id_base_to_process,
                "cod_doc": "Varios"
            }

            try: self._temp_pdf_dir_created_by_this_run = create_temp_folder()
            except Exception as e_temp:
                critical_file_processing_errors_for_run.append({"file": "N/A", "message": f"Error creando dir. temporal: {e_temp}"})
                self._temp_pdf_dir_created_by_this_run = ""

            current_gui_id_parts_check = [p.strip() for p in (self.current_gui_entity_id_display or "").split('/') if p.strip()]
            new_batch_id_parts_check = [p.strip() for p in (header_data_for_gui_final.get("id_comprador", "")).split('/') if p.strip()]
            is_new_entity_for_gui_final = not self.is_gui_initial_process_done or not any(gui_part in new_batch_id_parts_check for gui_part in current_gui_id_parts_check)

            self.initial_info_to_popup.emit(f"Procesando {len(xml_files_to_process_final_batch)} archivos para {razon_social_canonica_seleccionada} ({id_display_for_gui})...")
            self.progress_total_files_to_popup.emit(len(xml_files_to_process_final_batch))
            current_processed_ids_for_entity_determination = self.already_processed_ids if not is_new_entity_for_gui_final else set()
            self.entity_determined.emit(header_data_for_gui_final, is_new_entity_for_gui_final, self._temp_pdf_dir_created_by_this_run, xml_to_pdf_map_generated_for_run, current_processed_ids_for_entity_determination)
            self.msleep(150); self._check_interruption()
            ids_for_current_batch_processing = set() if is_new_entity_for_gui_final else self.already_processed_ids.copy()

            num_workers = os.cpu_count() or 2
            logger.info(f"Iniciando procesamiento con ProcessPoolExecutor (workers: {num_workers})")

            with ProcessPoolExecutor(max_workers=num_workers) as executor:
                future_to_xml_path = {
                    # Llamada a process_single_xml_file_task sin el logo del asesor.
                    # Si se necesita pasar el logo del EMISOR, se haría aquí, pero actualmente
                    # MainWindow no gestiona un logo de emisor global.
                    # El logo del emisor se maneja si está en parsed_data o si generate_pdf_from_xml lo recibe.
                    executor.submit(process_single_xml_file_task, xml_path, self._temp_pdf_dir_created_by_this_run, None): xml_path
                    for xml_path in xml_files_to_process_final_batch
                }

                for i, future in enumerate(as_completed(future_to_xml_path)):
                    self._check_interruption()
                    xml_file_path_original = future_to_xml_path[future]
                    self.initial_info_to_popup.emit(f"Procesando archivo {i+1}/{len(xml_files_to_process_final_batch)}: {os.path.basename(xml_file_path_original)}")

                    try:
                        result = future.result()

                        if result.get("error"):
                            critical_file_processing_errors_for_run.append({"file": os.path.basename(result.get("xml_path", "N/A")), "message": result["error"]})
                            continue

                        temp_pdf_path_result = result.get("temp_pdf_path")
                        cod_doc_result = result.get("cod_doc")
                        backup_pdf_path_result = result.get("backup_pdf_path")

                        if temp_pdf_path_result:
                            xml_to_pdf_map_generated_for_run[result["xml_path"]] = (temp_pdf_path_result, cod_doc_result, backup_pdf_path_result)

                        if result.get("pdf_error"):
                            all_pdf_gen_errors_for_run.append(f"{os.path.basename(result.get('xml_path', 'N/A'))}: {result['pdf_error']}")
                        if result.get("conversion_errors"):
                            all_conversion_errors_for_run.extend(result["conversion_errors"])

                        unique_id_for_table = result.get("unique_id")
                        if unique_id_for_table and unique_id_for_table in ids_for_current_batch_processing:
                            skipped_duplicate_files_count += 1
                            continue

                        row_data_result = result.get("row_data")
                        if not row_data_result:
                             critical_file_processing_errors_for_run.append({"file": os.path.basename(result.get("xml_path", "N/A")), "message": "Worker no devolvió row_data."})
                             continue

                        self.row_processed.emit(row_data_result, cod_doc_result, backup_pdf_path_result)
                        self.processed_counts_by_type[cod_doc_result] += 1
                        if unique_id_for_table:
                            newly_added_identifiers_this_run.append(unique_id_for_table)
                            ids_for_current_batch_processing.add(unique_id_for_table)
                        newly_processed_count += 1

                    except Exception as e_future:
                        critical_file_processing_errors_for_run.append({"file": os.path.basename(xml_file_path_original), "message": f"Error en futuro: {e_future}"})

        except InterruptionRequestedError as ire: logger.info(f"Worker interrumpido: {str(ire)}")
        except Exception as e_general:
            logger.exception(f"Error general en WorkerThread.run: {e_general}")
            if not critical_file_processing_errors_for_run: critical_file_processing_errors_for_run.append({"file": "N/A", "message": f"Error general del worker: {e_general}"})
        finally:
            self.processing_complete.emit(
                all_conversion_errors_for_run, all_pdf_gen_errors_for_run, critical_file_processing_errors_for_run,
                self._worker_was_cancelled_by_user, self._temp_pdf_dir_created_by_this_run,
                newly_processed_count, skipped_duplicate_files_count, newly_added_identifiers_this_run,
                len(xml_files_to_process_final_batch), dict(self.processed_counts_by_type),
                xml_to_pdf_map_generated_for_run
            )

class NoColumnDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_color = QColor("#005cbf")
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if index.column() == 0:
            painter.save(); painter.fillRect(option.rect, self.background_color)
            text = index.data(Qt.ItemDataRole.DisplayRole); font = index.data(Qt.ItemDataRole.FontRole)
            text_color_brush = index.data(Qt.ItemDataRole.ForegroundRole)
            alignment = Qt.AlignmentFlag(index.data(Qt.ItemDataRole.TextAlignmentRole) or (Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter))
            if text_color_brush: painter.setPen(text_color_brush.color())
            else: painter.setPen(Qt.GlobalColor.white)
            if font: painter.setFont(font)
            painter.drawText(option.rect, alignment, str(text))
            if option.state & QStyle.StateFlag.State_HasFocus:
                focus_option = QStyleOptionViewItem(option)
                focus_option.palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
                focus_option.palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.transparent)
                focus_option.palette.setColor(QPalette.ColorRole.Highlight, QColor(0,0,0,0))
                focus_option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0,0,0,0))
                style = option.widget.style() if option.widget else QApplication.style()
                style.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, focus_option, painter, option.widget)
            painter.restore()
        else: super().paint(painter, option, index)

class CustomHeaderView(QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._summation_data: Dict[int, str] = {}; self.setSectionsClickable(True)
        self._single_line_height = QFontMetrics(self.font()).height() + 8
    def setSummationData(self, sums: Dict[int, str]):
        self._summation_data = sums
        if self.count() > 0: self.headerDataChanged(self.orientation(), 0, self.count() - 1)
    def sizeHint(self) -> QSize:
        original_hint = super().sizeHint(); return QSize(original_hint.width(), self._single_line_height * 2 + 4)
    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int):
        painter.save(); opt = QStyleOptionHeader(); self.initStyleOption(opt)
        opt.rect = rect; opt.section = logicalIndex
        self.style().drawControl(QStyle.ControlElement.CE_HeaderSection, opt, painter, self)
        padding = 3; text_height = self._single_line_height - padding
        top_rect = QRect(rect.x() + padding, rect.y() + padding, rect.width() - 2 * padding, text_height)
        internal_line_y = rect.y() + text_height + padding
        bottom_rect_y_start = internal_line_y + 1
        bottom_rect = QRect(rect.x() + padding, bottom_rect_y_start, rect.width() - 2 * padding, text_height)
        painter.setPen(QColor("#003366")); painter.drawLine(rect.x(), internal_line_y, rect.x() + rect.width(), internal_line_y)
        sum_text = self._summation_data.get(logicalIndex, "")
        if logicalIndex == 0: sum_text = "Total"
        if sum_text:
            painter.setPen(Qt.GlobalColor.white); painter.setFont(self.font())
            painter.drawText(top_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, sum_text)
        original_header_text = self.model().headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DisplayRole)
        if original_header_text is not None:
            painter.setPen(Qt.GlobalColor.white); painter.setFont(self.font())
            painter.drawText(bottom_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, str(original_header_text))
        if opt.sortIndicator != QStyleOptionHeader.SortIndicator.None_:
            opt_indicator = QStyleOptionHeader(opt); opt_indicator.rect = bottom_rect
            self.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorHeaderArrow, opt_indicator, painter, self)
        painter.restore()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Asistente Contable"); self.setGeometry(100, 100, 1300, 700)
        self.xml_to_pdf_map: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {};
        self.tracked_temp_pdf_dirs: set[str] = set()

        self.COLUMN_DEFINITIONS: Dict[str, Dict[str, Any]] = {
            "FC": {"name": "Facturas", "coddoc": "01", "type": "received", "group": "received",
                   "headers": [
                       "No.", "Fecha", "RUC Emisor", "Razón Social Emisor", "Nro.Secuencial",
                       "TipoId.", "Id.Comprador", "Razón Social Comprador",
                       "Formas de Pago",
                                "Descuento", "Total Sin Impuestos",
                                "Base IVA 0%", "Base IVA 5%", "Base IVA 8%", "Base IVA 12%", "Base IVA 13%", "Base IVA 14%", "Base IVA 15%",
                                "No Objeto IVA", "Exento IVA",
                       "Desc. Adicional",
                       "Devol. IVA",
                       "Monto IVA",
                       "Base ICE", "Monto ICE",
                       "Base IRBPNR", "Monto IRBPNR",
                       "Propina",
                       "Monto Total",
                       "Guia de Remisión",
                       "Primeros 3 Articulos",
                       "Nro de Autorización"
                   ],
                   "sum_cols": [
                       "Descuento", "Total Sin Impuestos",
                                "Base IVA 0%", "Base IVA 5%", "Base IVA 8%", "Base IVA 12%", "Base IVA 13%", "Base IVA 14%", "Base IVA 15%",
                       "No Objeto IVA", "Exento IVA",
                       "Desc. Adicional", "Devol. IVA", "Monto IVA",
                       "Base ICE", "Monto ICE", "Base IRBPNR", "Monto IRBPNR",
                       "Propina", "Monto Total"
                   ]},
            "ND_R": {"name": "N. Débito", "coddoc": "05", "type": "received", "group": "received",
                     "headers": ["No.", "Fecha", "RUC Emisor", "Razón Social Emisor", "Nro.Secuencial", "Total Sin Impuestos", "Monto IVA", "Monto Total", "Nro de Autorización"],
                     "sum_cols": ["Total Sin Impuestos", "Monto IVA", "Monto Total"]},
            "NC_R": {"name": "N. Crédito", "coddoc": "04", "type": "received", "group": "received",
                     "headers": ["No.", "Fecha", "RUC Emisor", "Razón Social Emisor", "Nro.Secuencial",
                                 "TipoId.", "Id.Comprador", "Razón Social Comprador",
                                 "CodDoc",
                                 "Fecha D.M.", "CodDocMod", "Num.Doc.Modificado", "N.A.Doc.Modificado",
                                 "Valor Mod.",
                                 "Base IVA 0%", "Base IVA 5%", "Base IVA 8%", "Base IVA 12%", "Base IVA 13%", "Base IVA 14%", "Base IVA 15%",
                                 "No Objeto IVA", "Exento IVA", "Devol. IVA", "Monto IVA",
                                 "Base ICE", "Monto ICE", "Base IRBPNR", "Monto IRBPNR",
                                 "Monto Total", "Nro de Autorización"],
                     "sum_cols": ["Valor Mod.",
                                  "Base IVA 0%", "Base IVA 5%", "Base IVA 8%", "Base IVA 12%", "Base IVA 13%", "Base IVA 14%", "Base IVA 15%",
                                  "No Objeto IVA", "Exento IVA", "Devol. IVA", "Monto IVA",
                                  "Base ICE", "Monto ICE", "Base IRBPNR", "Monto IRBPNR",
                                  "Monto Total"]},
            "RET_R": {"name": "Retenciones", "coddoc": "07", "type": "received", "group": "received",
                      "headers": ["No.", "Fecha", "RUC Emisor", "Razón Social Emisor", "Nro.Secuencial",
                                  "TipoId.", "Id.Sujeto Retenido", "Razón Social Sujeto Retenido",
                                  "Periodo Fiscal",
                                  "CodDocSust", "Fecha D.S.", "Num.Doc.Sustento", "Autorización Doc Sust.",
                                  "Tipo Impuesto Ret.", "Codigo Ret.", "Base Imponible Ret.", "Porcentaje Ret.", "Valor Retenido",
                                  "Ret. Renta Pres.", "Ret. IVA Pres.", "Total Ret. ISD",
                                  "Monto Total", "Nro de Autorización"],
                      "sum_cols": ["Base Imponible Ret.", "Valor Retenido",
                                   "Ret. Renta Pres.", "Ret. IVA Pres.", "Total Ret. ISD",
                                   "Monto Total"]},
            "LC_R": {"name": "Liq. Compra", "coddoc": "03", "type": "received", "group": "received",
                     "headers": ["No.", "Fecha", "RUC Emisor", "Razón Social Emisor", "Nro.Secuencial", "Total Sin Impuestos", "Monto IVA", "Monto Total", "Nro de Autorización"],
                     "sum_cols": ["Total Sin Impuestos", "Monto IVA", "Monto Total"]},
            "GR_R": {"name": "Guías Remisión", "coddoc": "06", "type": "received", "group": "received",
                   "headers": ["No.", "Fecha", "RUC Emisor", "Razón Social Emisor", "Nro.Secuencial", "Nro de Autorización"],
                   "sum_cols": []}
        }
        self.DOC_TYPE_ORDER = ["FC", "ND_R", "NC_R", "RET_R", "LC_R", "GR_R"]

        self.doc_type_buttons: Dict[str, QPushButton] = {}; self.initial_process_done: bool = False
        self.active_doc_key: Optional[str] = None; self.all_data_by_coddoc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.selected_entity_details = { "id_display": "", "razon_social": "", "ids_to_match": [] }
        self.processed_xml_identifiers_for_current_entity: Set[str] = set() # self.logo_path (asesor) eliminado
        
        # Mover la definición de métodos de exportación ANTES de _init_ui_layout
        # para que estén disponibles cuando _init_ui_layout los conecte.
        # Los métodos worker_thread y progress_popup se inicializan a None aquí.
        self.worker_thread: Optional[WorkerThread] = None
        self.progress_popup: Optional[ProgressPopup] = None
        
        self._init_ui_layout() # Ahora _init_ui_layout puede encontrar handle_export_files

        self.download_thread: Optional[DownloadThread] = None
        self.download_progress_dialog: Optional[QProgressDialog] = None
        self.BASE_REPORT_COLUMN_HEADERS: List[str] = xml_parser.ALL_CSV_FIELDS
        self._cols_to_exclude_from_view = ["original_xml_path", "Formas de Pago"]
        _desired_order_prefix = ["No.", "Fecha", "RUC Emisor", "Razón Social Emisor", "Nro.Secuencial",
                                 "TipoId.", "Id.Comprador", "Razón Social Comprador",
                                 "Id.Sujeto Retenido", "Razón Social Sujeto Retenido", "Periodo Fiscal",
                                 "Fecha D.M.", "CodDocMod", "Num.Doc.Modificado", "N.A.Doc.Modificado", "Valor Mod.",
                                 "CodDocSust", "Fecha D.S.", "Num.Doc.Sustento", "Autorización Doc Sust.", "Tipo Impuesto Ret.", "Codigo Ret." ]
        _desired_order_suffix = ["Primeros 3 Articulos", "Nro de Autorización"]
        _other_headers = [
            h for h in self.BASE_REPORT_COLUMN_HEADERS
            if h not in _desired_order_prefix
            and h not in _desired_order_suffix
        ]
        _master_header_list_for_order = _desired_order_prefix + sorted(_other_headers) + _desired_order_suffix
        self.HEADER_ORDER_MAP: Dict[str, int] = {
            name: i for i, name in enumerate(_master_header_list_for_order)
        }
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.default_directory = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        self.last_xml_directory = self.settings.value(SETTINGS_LAST_XML_DIR, self.default_directory, type=str)
        self.last_zip_directory = self.settings.value(SETTINGS_LAST_ZIP_DIR, self.default_directory, type=str)
        if not os.path.isdir(self.last_xml_directory): self.last_xml_directory = self.default_directory
        if not os.path.isdir(self.last_zip_directory): self.last_zip_directory = self.default_directory
        self.update_available_signal.connect(self._show_update_dialog)
        self._start_update_check_thread()
        self._apply_styles(); self._update_button_visibility_and_default_selection()

        # Mapa para traducir nombres de cabecera de visualización a claves de datos internas
        self.HEADER_TO_DATA_KEY_MAP: Dict[str, Optional[str]] = {
            "No.": None, # El "No." es generado, no es una clave de datos directa
            "Fecha": "Fecha", "Fecha Emisión": "Fecha",
            "Tipo Doc": "tipo_documento_display", # Generado en _populate_report_table
            "Nro Comprobante": "Nro.Secuencial", "Nro.Secuencial": "Nro.Secuencial",
            "Nro de Autorización": "Nro de Autorización",
            "RUC Emisor": "RUC Emisor", "Razón Social Emisor": "Razón Social Emisor",
            "TipoId.": "TipoId.",
            "Id.Comprador": "Id.Comprador", "ID Comprador": "Id.Comprador",
            "Razón Social Comprador": "Razón Social Comprador",
            "Id.Sujeto Retenido": "Id.Sujeto Retenido", "Razón Social Sujeto Retenido": "Razón Social Sujeto Retenido",
            "Periodo Fiscal": "Periodo Fiscal",
            "Fecha D.M.": "Fecha D.M.", "CodDocMod": "CodDocMod", "Num.Doc.Modificado": "Num.Doc.Modificado",
            "N.A.Doc.Modificado": "N.A.Doc.Modificado", "Valor Mod.": "Valor Mod.",
            "CodDocSust": "CodDocSust", "Fecha D.S.": "Fecha D.S.", "Num.Doc.Sustento": "Num.Doc.Sustento",
            "Autorización Doc Sust.": "Autorización Doc Sust.",
            "Tipo Impuesto Ret.": "Tipo Impuesto Ret.", "Codigo Ret.": "Codigo Ret.",
            "Base Imponible Ret.": "Base Imponible Ret.", "Porcentaje Ret.": "Porcentaje Ret.", "Valor Retenido": "Valor Retenido",
            # Las claves de IVA, ICE, IRBPNR, etc., suelen ser iguales al nombre de visualización si no están aquí
            "Monto Total": "Monto Total", "Total": "Monto Total",
        }

    # --- Métodos auxiliares refactorizados ---
    def _get_save_file_dialog(self, title: str, default_filename_template: str, entity_rs: Optional[str],
                              file_filter: str, last_dir_setting_key: str) -> Optional[str]:
        entity_rs_safe = "General"
        if entity_rs:
            entity_rs_safe = entity_rs.replace(" ", "_").replace(".", "")
            if not entity_rs_safe or "generico" in entity_rs_safe.lower():
                entity_rs_safe = "General"

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_filename = default_filename_template.format(entity=entity_rs_safe, timestamp=timestamp)

        start_dir = self.settings.value(last_dir_setting_key, self.default_directory, type=str)
        if not os.path.isdir(start_dir):
            start_dir = self.default_directory

        file_path, _ = QFileDialog.getSaveFileName(
            self, title, os.path.join(start_dir, default_filename), file_filter
        )

        if file_path:
            chosen_dir = os.path.dirname(file_path)
            self.settings.setValue(last_dir_setting_key, chosen_dir)
            if file_filter.endswith("(*.xlsx)") and not file_path.lower().endswith('.xlsx'): # Específico para Excel
                file_path += '.xlsx'
        return file_path

    # --- Métodos de exportación y manejo de archivos movidos aquí ---
    @Slot()
    def handle_export_files(self):
        """
        Maneja la acción de exportar archivos (ZIP).
        Muestra un diálogo para seleccionar el tipo de exportación.
        """
        has_any_pdf = any(temp_pdf_path is not None or backup_pdf_path is not None
                          for temp_pdf_path, cod_doc, backup_pdf_path in self.xml_to_pdf_map.values())

        if not has_any_pdf:
            QMessageBox.information(self, "Exportar Archivos", "No hay PDFs generados para exportar.")
            return

        dialog = ExportTypeSelectionDialog(self)
        if dialog.exec() == QDialog.Accepted:
            export_type = dialog.get_selected_export_type()
            if export_type:
                self._perform_zip_export(export_type)
        else:
            logger.info("Exportación de archivos cancelada por el usuario.")

    def _perform_zip_export(self, export_type: str):
        """
        Realiza la exportación de archivos (XML y/o PDF) a un archivo ZIP.
        Organiza los archivos dentro del ZIP según el tipo de exportación seleccionado.
        """
        xml_path_to_row_data: Dict[str, Dict[str, Any]] = {}
        for cod_doc_key_ignored, rows in self.all_data_by_coddoc.items():
            for row in rows:
                original_xml_path = row.get("original_xml_path")
                if original_xml_path:
                    xml_path_to_row_data[original_xml_path] = row

        main_zip_filepath = self._get_save_file_dialog(
            title="Guardar Archivo ZIP",
            default_filename_template="Comprobantes_{entity}_{timestamp}.zip",
            entity_rs=self.selected_entity_details.get("razon_social"),
            file_filter="Archivos ZIP (*.zip)",
            last_dir_setting_key=SETTINGS_LAST_XML_DIR # Usar la carpeta de los últimos XML procesados
        )

        if not main_zip_filepath: return
        main_zip_filename = os.path.basename(main_zip_filepath) # Para el mensaje final
        chosen_dir = os.path.dirname(main_zip_filepath) # Ya guardado por _get_save_file_dialog

        files_to_add_to_main_zip: List[Tuple[str, str]] = []
        logger.info(f"Iniciando preparación de archivos para ZIP: {main_zip_filepath} (Tipo: {export_type})")

        for xml_path, (temp_pdf_path, cod_doc, backup_pdf_path) in self.xml_to_pdf_map.items():
            logger.debug(f"Procesando para ZIP: XML={os.path.basename(xml_path)}, TempPDF={os.path.basename(temp_pdf_path) if temp_pdf_path else 'N/A'}, BackupPDF={os.path.basename(backup_pdf_path) if backup_pdf_path else 'N/A'}")
            try:
                row_data_for_file = xml_path_to_row_data.get(xml_path)
                if not cod_doc:
                    logger.warning(f"  - No se pudo obtener cod_doc para {os.path.basename(xml_path)}. Omitiendo.")
                    continue
                if export_type.endswith("_by_date") and not row_data_for_file:
                    logger.warning(f"  - No se encontraron datos (row_data) para {os.path.basename(xml_path)} para exportación por fecha. Omitiendo.")
                    continue

                custom_folder_names = {
                    "01": "FACTURAS DE COMPRA", "04": "NOTAS DE CREDITO RECIBIDAS", "07": "RETENCIONES RECIBIDAS",
                    "03": "LIQUIDACIONES DE COMPRA", "06": "GUIAS DE REMISION RECIBIDAS", "05": "NOTAS DE DEBITO RECIBIDAS"
                }
                doc_type_subfolder_base = custom_folder_names.get(cod_doc)
                if not doc_type_subfolder_base:
                    temp_name = xml_parser.COD_DOC_MAP.get(cod_doc, f"Tipo {cod_doc}").upper()
                    temp_name = FOLDER_NAME_CLEAN_REGEX.sub('', temp_name).strip()
                    doc_type_subfolder_base = SPACE_HYPHEN_NORM_REGEX.sub(' ', temp_name)
                    if "RECIBIDAS" not in doc_type_subfolder_base.upper() and "RECIBIDA" not in doc_type_subfolder_base.upper():
                        doc_type_subfolder_base += " RECIBIDAS"
                if not doc_type_subfolder_base: doc_type_subfolder_base = f"Tipo_{cod_doc}_RECIBIDAS"

                final_subfolder_path_in_zip = doc_type_subfolder_base

                if export_type.endswith("_by_date"):
                    year_month_folder = "Fecha Desconocida"
                    fecha_autorizacion_str = row_data_for_file.get("fechaAutorizacion") if row_data_for_file else None
                    if fecha_autorizacion_str:
                        try:
                            date_part_str = fecha_autorizacion_str.split('T')[0]
                            date_obj = datetime.strptime(date_part_str, '%Y-%m-%d')
                            year = date_obj.year
                            month_name = MONTH_NAMES_SPANISH.get(date_obj.month, f"Mes_{date_obj.month}")
                            year_month_folder = os.path.join(str(year), month_name)
                        except Exception as e_date:
                            logger.warning(f"  - Error parseando fechaAutorizacion '{fecha_autorizacion_str}' para {os.path.basename(xml_path)} para exportación por fecha: {e_date}")
                    final_subfolder_path_in_zip = os.path.join(doc_type_subfolder_base, year_month_folder)

                logger.debug(f"  - Subcarpeta en ZIP: {final_subfolder_path_in_zip}")
                include_xml = export_type.startswith("pdf_xml_")
                pdf_source_path = backup_pdf_path if backup_pdf_path and os.path.exists(backup_pdf_path) else (temp_pdf_path if temp_pdf_path and os.path.exists(temp_pdf_path) else None)

                if include_xml:
                    if os.path.exists(xml_path):
                        arcname_xml = os.path.join(final_subfolder_path_in_zip, os.path.basename(xml_path))
                        files_to_add_to_main_zip.append((xml_path, arcname_xml))
                        logger.debug(f"  - Añadido XML: {arcname_xml}")
                    else: logger.warning(f"  - XML no encontrado: {xml_path}")

                if pdf_source_path:
                    arcname_pdf = os.path.join(final_subfolder_path_in_zip, os.path.basename(pdf_source_path))
                    files_to_add_to_main_zip.append((pdf_source_path, arcname_pdf))
                    logger.debug(f"  - Añadido PDF: {arcname_pdf}")
                else: logger.warning(f"  - PDF (temporal o respaldo) no encontrado para {os.path.basename(xml_path)}. No se añadió PDF al ZIP.")

            except Exception as e: logger.error(f"Error procesando archivo {os.path.basename(xml_path)} para ZIP: {e}")

        logger.info(f"Total de archivos preparados para añadir al ZIP: {len(files_to_add_to_main_zip)}")

        if files_to_add_to_main_zip:
            if create_zip_archive(files_to_add_to_main_zip, main_zip_filepath):
                export_content_msg = "PDFs y XMLs" if export_type.startswith("pdf_xml_") else "solo PDFs"
                folder_structure_msg = "por tipo de documento" if export_type.endswith("_by_type") else "por fecha de autorización"
                logger.info(f"Archivo ZIP ({export_content_msg}, carpetas {folder_structure_msg}) creado: {main_zip_filepath}")
                QMessageBox.information(self, "Exportación Completa", f"Archivo ZIP '{main_zip_filename}' generado con {export_content_msg} (carpetas {folder_structure_msg}) en:\n{chosen_dir}")
                self._open_directory_or_select_file(chosen_dir)
            else:
                logger.error("Fallo al crear el archivo ZIP principal.")
                QMessageBox.warning(self, "Error en Exportación", f"No se pudo crear el archivo ZIP: {main_zip_filepath}")
        elif self.xml_to_pdf_map:
             logger.warning("xml_to_pdf_map no está vacío, pero no se prepararon archivos para el ZIP. Verifique la lógica de filtrado o datos (ej. fechaAutorizacion).")
             QMessageBox.warning(self, "Exportación Fallida", "No se pudo agrupar ningún archivo para el ZIP (ver log para detalles).")
        else:
            logger.info("xml_to_pdf_map está vacío. No hay archivos para exportar.")
            QMessageBox.information(self, "Exportar ZIP", "No hay archivos procesados para exportar.")
    # --- Fin de métodos de exportación movidos ---

    def _open_directory_or_select_file(self, path: str, select: bool = False):
        try:
            norm_path = os.path.normpath(path)
            if sys.platform == "win32":
                if select and os.path.isfile(norm_path): subprocess.Popen(['explorer', '/select,', norm_path])
                elif os.path.isdir(norm_path): subprocess.Popen(['explorer', norm_path])
                elif os.path.isfile(norm_path) and not select: subprocess.Popen(['explorer', os.path.dirname(norm_path)])
                else: logger.warning(f"Ruta no válida o no manejada para abrir: {norm_path}"); return
            elif sys.platform == "darwin": # macOS
                if select and os.path.isfile(norm_path): subprocess.Popen(['open', '-R', norm_path])
                else: subprocess.Popen(['open', norm_path if os.path.isdir(norm_path) else os.path.dirname(norm_path)])
            else: # Linux y otros
                dir_to_open = norm_path if os.path.isdir(norm_path) else os.path.dirname(norm_path)
                if os.path.exists(dir_to_open): subprocess.Popen(['xdg-open', dir_to_open])
                else: logger.warning(f"Directorio no existe para xdg-open: {dir_to_open}"); return
            logger.info(f"Intentando abrir {'y seleccionar ' if select else ''}{'directorio de ' if not os.path.isdir(norm_path) and not select else ''}'{norm_path}'")
        except Exception as e: logger.error(f"Error al abrir la ubicación '{path}': {e}")

    @Slot()
    def reset_interface(self):
        self._clear_report_data_for_new_entity()
        self.selected_entity_details = { "id_display": "", "razon_social": "", "ids_to_match": [] }
        self.initial_process_done = False; self.processed_xml_identifiers_for_current_entity.clear()
        self._update_button_visibility_and_default_selection(); self.process_xml_button.setEnabled(True)
        logger.info("Interfaz reseteada.")

    @Slot(str)
    def handle_worker_log_message(self, message: str):
        logger.info(f"Mensaje del WorkerThread (GUI): {message}")


    def _init_ui_layout(self):
        main_layout = QVBoxLayout()
        info_comprador_layout = QHBoxLayout(); info_comprador_layout.setSpacing(10)
        self.id_label_title = QLabel("<b>ID:</b>"); self.id_comprador_label = QLabel("N/A")
        id_group_layout = QHBoxLayout(); id_group_layout.addWidget(self.id_label_title); id_group_layout.addWidget(self.id_comprador_label)
        info_comprador_layout.addLayout(id_group_layout)
        self.rs_label_title = QLabel("<b>Razón Social:</b>"); self.razon_social_comprador_label = QLabel("N/A")
        rs_group_layout = QHBoxLayout(); rs_group_layout.addWidget(self.rs_label_title); rs_group_layout.addWidget(self.razon_social_comprador_label)
        info_comprador_layout.addLayout(rs_group_layout); info_comprador_layout.addStretch(1)
        main_layout.addLayout(info_comprador_layout)
        table_area_layout = QHBoxLayout()
        left_buttons_layout = QVBoxLayout(); left_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.process_xml_button = QPushButton("Procesar XML"); self.process_xml_button.clicked.connect(self.select_xml_files)
        left_buttons_layout.addWidget(self.process_xml_button)
        self.export_excel_button = QPushButton("Exportar a Excel"); self.export_excel_button.clicked.connect(self.handle_export_to_excel)
        left_buttons_layout.addWidget(self.export_excel_button)
        self.export_files_button = QPushButton("Exportar Archivos"); self.export_files_button.clicked.connect(self.handle_export_files)
        left_buttons_layout.addWidget(self.export_files_button)
        self.reset_button = QPushButton("Reiniciar"); self.reset_button.clicked.connect(self.reset_interface)
        left_buttons_layout.addWidget(self.reset_button)
        buttons_to_standardize = [self.process_xml_button, self.export_excel_button, self.export_files_button, self.reset_button]
        max_hint_width = 0
        for button in buttons_to_standardize: max_hint_width = max(max_hint_width, button.sizeHint().width())
        for button in buttons_to_standardize: button.setMinimumWidth(max_hint_width + 10)
        table_area_layout.addLayout(left_buttons_layout, 0)
        self.report_table = QTableWidget(); self._setup_report_table()
        self.custom_header = CustomHeaderView(Qt.Orientation.Horizontal, self.report_table)
        self.report_table.setHorizontalHeader(self.custom_header)
        self.no_column_delegate = NoColumnDelegate(self.report_table)
        self.report_table.setItemDelegateForColumn(0, self.no_column_delegate)
        table_area_layout.addWidget(self.report_table, 1)
        main_layout.addLayout(table_area_layout)
        self.doc_type_buttons_layout = self._create_doc_type_buttons_layout()
        main_layout.addLayout(self.doc_type_buttons_layout)
        central_widget = QWidget(); central_widget.setLayout(main_layout); self.setCentralWidget(central_widget)

    def _apply_styles(self):
        self.setStyleSheet(""" QMainWindow { background-color: #f0f4f8; } QLabel { color: #333333; padding: 2px; } QLabel[font-weight="bold"] { color: #004a99; } QPushButton { background-color: #007bff; color: white; border-radius: 4px; padding: 8px 12px; font-size: 10pt; } QPushButton:hover { background-color: #0056b3; } QPushButton:disabled { background-color: #c0c0c0; color: #666666; } QTableWidget { border: 1px solid #d0d0d0; gridline-color: #e0e0e0; background-color: white; alternate-background-color: #f7faff; } QTableWidget::item { padding-top: 2px; padding-bottom: 2px; padding-left: 4px; padding-right: 4px; border-bottom: 1px solid #f0f0f0; } QHeaderView::section { background-color: #005cbf; color: white; padding: 4px; font-size: 9pt; font-weight: bold; border-style: solid; border-width: 1px; border-top-color: #3399ff; border-left-color: #3399ff; border-bottom-color: #003366; border-right-color: #003366; } QDialog#ProgressPopup { background-color: #e9eff5; border: 1px solid #007bff; } QDialog#ProgressPopup QLabel { color: #003366; } QPushButton#DocTypeButton { font-size: 8pt; padding: 6px 10px; margin: 1px; border: 1px solid #cccccc; border-radius: 3px; } QPushButton[docGroup="received"] { background-color: #e6f7ff; color: #005cbf; } QPushButton[docGroup="received"]:checked { background-color: #005cbf; color: white; border-color: #004a99;} QPushButton[docGroup="emitted"] { background-color: #e6ffe6; color: #006400; } QPushButton[docGroup="emitted"]:checked { background-color: #006400; color: white; border-color: #004d00;} """)
        if hasattr(self, 'id_label_title'): self.id_label_title.setProperty("font-weight", "bold")
        if hasattr(self, 'rs_label_title'): self.rs_label_title.setProperty("font-weight", "bold")

    def _create_doc_type_buttons_layout(self) -> QHBoxLayout:
        layout = QHBoxLayout(); layout.setSpacing(5); layout.setContentsMargins(5, 5, 5, 5)
        received_widget = QWidget(); received_layout = QHBoxLayout(received_widget)
        received_layout.setContentsMargins(0,0,0,0); received_layout.setSpacing(2)
        for key in self.DOC_TYPE_ORDER:
            doc_info = self.COLUMN_DEFINITIONS.get(key)
            if not doc_info: continue
            button = QPushButton(doc_info["name"])
            button.setObjectName("DocTypeButton"); button.setProperty("docGroup", doc_info["group"])
            button.setCheckable(True); button.clicked.connect(lambda checked, k=key: self._on_doc_type_button_clicked(k))
            button.setVisible(False); self.doc_type_buttons[key] = button
            received_layout.addWidget(button)
        layout.addWidget(QLabel("<b>Documentos Recibidos:</b>")); layout.addWidget(received_widget)
        layout.addStretch(1); return layout

    update_available_signal = Signal(str, str)

    def _start_update_check_thread(self):
        logger.info("Iniciando hilo de comprobación de actualizaciones...")
        update_thread = threading.Thread(target=self._check_for_updates_task, daemon=True)
        update_thread.start()

    def _check_for_updates_task(self):
        try:
            logger.info(f"Comprobando actualizaciones en: {UPDATE_CHECK_URL}")
            req = urllib.request.Request(UPDATE_CHECK_URL, headers={'User-Agent': 'AsistenteContableUpdateChecker/1.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                content = response.read().decode('utf-8')
            latest_version = None; download_url = None
            for line in content.splitlines():
                if line.strip().startswith("version="): latest_version = line.strip().split("=", 1)[1]
                elif line.strip().startswith("download_url="): download_url = line.strip().split("=", 1)[1]
            if latest_version and download_url:
                logger.info(f"Versión local: {APP_VERSION}, Versión remota: {latest_version}")
                try:
                    local_parts = list(map(int, APP_VERSION.split('.')))
                    remote_parts = list(map(int, latest_version.split('.')))
                    if remote_parts > local_parts:
                        self.update_available_signal.emit(latest_version, download_url)
                        logger.info(f"Actualización disponible: {latest_version}")
                    else: logger.info("La aplicación está actualizada.")
                except ValueError: logger.warning(f"Error al parsear versiones (local: {APP_VERSION}, remota: {latest_version}). No se pudo comparar.")
            else: logger.warning("El archivo de actualización remoto no contiene 'version' o 'download_url'.")
        except urllib.error.URLError as e: logger.warning(f"No se pudo conectar para comprobar actualizaciones: {e.reason}")
        except Exception as e: logger.error(f"Error inesperado al comprobar actualizaciones: {e}")

    @Slot(str, str)
    def _show_update_dialog(self, latest_version: str, download_url: str):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Actualización Disponible")
        msg_box.setText(f"Hay una nueva versión ({latest_version}) disponible.\n¿Desea descargarla ahora?")
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            self.start_update_download(download_url)

    def start_update_download(self, download_url: str):
        if self.download_thread and self.download_thread.isRunning():
            QMessageBox.information(self, "Descarga en Progreso", "Ya hay una descarga de actualización en curso.")
            return
        suggested_filename = os.path.basename(urllib.parse.urlparse(download_url).path)
        if not suggested_filename:
            suggested_filename = "asistente_contable_actualizacion.zip" if ".zip" in download_url.lower() else "asistente_contable_actualizacion.exe"
        initial_dir_for_update = self.default_directory
        if os.path.isdir(self.last_xml_directory):
            initial_dir_for_update = self.last_xml_directory
        save_filepath, _ = QFileDialog.getSaveFileName(
            self, "Guardar Actualización",
            os.path.join(initial_dir_for_update, suggested_filename),
            f"Archivos de Instalación (*.{suggested_filename.split('.')[-1] if '.' in suggested_filename else 'exe'});;Todos los archivos (*)"
        )
        if not save_filepath:
            logger.info("Descarga de actualización cancelada por el usuario (diálogo guardar).")
            return
        self.download_progress_dialog = QProgressDialog("Descargando actualización...", "Cancelar", 0, 100, self)
        self.download_progress_dialog.setWindowTitle("Progreso de Descarga")
        self.download_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.download_progress_dialog.setAutoClose(False)
        self.download_progress_dialog.setAutoReset(False)
        self.download_thread = DownloadThread(download_url, save_filepath)
        self.download_thread.download_progress.connect(self.update_download_progress)
        self.download_thread.download_finished.connect(self.handle_download_finished)
        self.download_progress_dialog.canceled.connect(self.download_thread.request_interruption)
        self.download_thread.start()
        self.download_progress_dialog.show()

    @Slot(int, int)
    def update_download_progress(self, bytes_downloaded: int, total_bytes: int):
        if self.download_progress_dialog:
            if total_bytes > 0: self.download_progress_dialog.setMaximum(total_bytes); self.download_progress_dialog.setValue(bytes_downloaded)
            else: self.download_progress_dialog.setMaximum(0); self.download_progress_dialog.setValue(0)

    def _setup_report_table(self):
        self.report_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.report_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.report_table.verticalHeader().setVisible(False); self.report_table.setMinimumHeight(300)
        self.report_table.setAlternatingRowColors(True)
        self.report_table.cellClicked.connect(self.on_report_table_cell_clicked)

    @Slot(bool, str, str)
    def handle_download_finished(self, success: bool, filepath: str, error_message: str):
        if self.download_progress_dialog:
            self.download_progress_dialog.close()
            self.download_progress_dialog.deleteLater()
            self.download_progress_dialog = None
        if success:
            QMessageBox.information(self, "Descarga Completa",
                                    f"La actualización se ha descargado exitosamente en:\n{filepath}\n\n"
                                    "Por favor, cierre esta aplicación, ejecute el archivo descargado para actualizar "
                                    "y luego inicie la aplicación nuevamente.")
            self._open_directory_or_select_file(filepath, select=True)
        elif error_message != "Descarga cancelada.":
            QMessageBox.critical(self, "Error de Descarga",
                                 f"No se pudo descargar la actualización.\nError: {error_message}")
        self.download_thread = None

    @Slot(str)
    def _on_doc_type_button_clicked(self, doc_key: str):
        if self.active_doc_key == doc_key and self.doc_type_buttons[doc_key].isChecked():
            self.doc_type_buttons[doc_key].setChecked(True); return
        self.active_doc_key = doc_key
        for key, button in self.doc_type_buttons.items(): button.setChecked(key == doc_key)
        self._update_displayed_report()

    def _update_button_visibility_and_default_selection(self):
        default_selected = False; first_visible_key = None
        for key_ordered in self.DOC_TYPE_ORDER:
            button = self.doc_type_buttons.get(key_ordered)
            if not button: continue
            has_data = bool(self._get_data_for_view(key_ordered))
            button.setVisible(has_data)
            if has_data and not first_visible_key: first_visible_key = key_ordered
            if key_ordered == "FC" and has_data and not default_selected:
                self._on_doc_type_button_clicked("FC"); default_selected = True
        if not default_selected and first_visible_key: self._on_doc_type_button_clicked(first_visible_key)
        elif not default_selected and not first_visible_key: self.active_doc_key = None; self._update_displayed_report()
        has_any_data_in_table = any(b.isVisible() for b in self.doc_type_buttons.values())
        can_export = bool(self.xml_to_pdf_map)
        has_any_data_for_excel = self.initial_process_done and any(
            bool(self._get_data_for_view(key)) for key in self.DOC_TYPE_ORDER
        )
        self.export_files_button.setVisible(can_export); self.export_files_button.setEnabled(can_export)
        self.export_excel_button.setVisible(has_any_data_for_excel); self.export_excel_button.setEnabled(has_any_data_for_excel)
        self.reset_button.setVisible(has_any_data_in_table or can_export or self.initial_process_done)
        self.process_xml_button.setText("Procesar XML" if not self.initial_process_done else "Procesar más")
        self.process_xml_button.setEnabled(self.worker_thread is None or not self.worker_thread.isRunning())

    @Slot()
    def select_xml_files(self):
        file_dialog = QFileDialog(self); file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("Archivos XML (*.xml)")
        start_dir = self.last_xml_directory if os.path.isdir(self.last_xml_directory) else self.default_directory
        file_dialog.setDirectory(start_dir)
        if file_dialog.exec():
            xml_files = file_dialog.selectedFiles()
            if xml_files:
                self.last_xml_directory = os.path.dirname(xml_files[0])
                self.settings.setValue(SETTINGS_LAST_XML_DIR, self.last_xml_directory)
                self.start_processing(xml_files)

    def start_processing(self, xml_files: List[str]):
        if self.worker_thread and self.worker_thread.isRunning(): QMessageBox.warning(self, "Proceso en curso", "Espere a que termine el proceso actual."); return
        self.process_xml_button.setEnabled(False)
        if self.progress_popup: self.progress_popup.reject(); self.progress_popup = None
        self.progress_popup = ProgressPopup(self); self.progress_popup.setObjectName("ProgressPopup")
        current_entity_id = self.selected_entity_details.get("id_display", "")
        current_entity_rs = self.selected_entity_details.get("razon_social", "")
        # Instanciación de WorkerThread sin self.logo_path (asesor)
        self.worker_thread = WorkerThread(xml_files, 
                                          current_entity_id, 
                                          current_entity_rs, 
                                          self.initial_process_done, 
                                          self.processed_xml_identifiers_for_current_entity)
        self.worker_thread.initial_info_to_popup.connect(self.update_progress_popup_message)
        self.worker_thread.progress_total_files_to_popup.connect(self.update_progress_popup_total_files)
        self.worker_thread.entity_base_clarification_needed.connect(self.handle_entity_base_clarification_from_worker)
        self.worker_thread.id_type_for_entity_base_clarification_needed.connect(self.handle_id_type_for_entity_base_clarification_from_worker)
        self.worker_thread.entity_determined.connect(self.handle_entity_determined)
        self.worker_thread.row_processed.connect(self.add_row_to_table)
        self.worker_thread.entity_id_mismatch_on_add_more.connect(self.handle_entity_id_mismatch_on_add_more)
        self.worker_thread.processing_complete.connect(self.handle_processing_complete)
        self.worker_thread.log_message_to_gui.connect(self.handle_worker_log_message)
        self.worker_thread.finished.connect(self.on_worker_finished_cleanup); self.worker_thread.start()

    def _ensure_progress_popup_visible(self, message: Optional[str] = None):
        if self.progress_popup:
            if not self.progress_popup.isVisible():
                self.progress_popup.show()
            if message:
                self.progress_popup.set_message(message)

    @Slot(str)
    def update_progress_popup_message(self, message: str):
        if self.progress_popup:
            if not self.progress_popup.isVisible(): self.progress_popup.show()
            self.progress_popup.set_message(message)

    @Slot(int)
    def update_progress_popup_total_files(self, total_files: int):
         if self.progress_popup:
             if not self.progress_popup.isVisible(): self.progress_popup.show()
             self.progress_popup.set_total_files(total_files)

    def _check_worker_active_or_handle_error(self) -> bool:
        if not self.worker_thread or not self.worker_thread.isRunning():
            logger.warning("Llamada a método de GUI que depende del worker, pero el worker no está activo.")
            if self.progress_popup:
                self._ensure_progress_popup_visible("Error: El proceso de fondo ya no está activo o finalizó inesperadamente.")
                self.progress_popup.setWindowTitle("Error de Proceso")
                self.progress_popup.processing_finished()
            return False
        return True

    @Slot(dict)
    def handle_entity_base_clarification_from_worker(self, opciones_id_base: dict):
        if not self._check_worker_active_or_handle_error(): return
        self._ensure_progress_popup_visible("Selección de Comprador Principal requerida...")
        dialog = EntityClarificationDialog(opciones_id_base, self)
        selected_id_base_final = None
        dialog_result = dialog.exec()
        if dialog_result == QDialog.Accepted:
            selected_id_base_final = dialog.selected_entity_id_raw
            logger.info(f"Diálogo de clarificación aceptado. ID seleccionado: {selected_id_base_final}")
        else:
            logger.info("El diálogo de clarificación de entidad fue cancelado/cerrado por el usuario.")
            if self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.request_interruption()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.set_selected_id_base(selected_id_base_final)
        elif selected_id_base_final is None:
            logger.info("El worker ya no corría cuando el diálogo de clarificación fue cancelado/cerrado. El popup debería haberse actualizado.")
            if self.progress_popup and self.progress_popup.isVisible():
                 if not (hasattr(self.progress_popup, 'ok_button') and self.progress_popup.ok_button and self.progress_popup.ok_button.text() == "Cerrar"):
                    logger.warning("Forzando actualización del ProgressPopup a estado cancelado porque el worker no corre.")
                    self.progress_popup.set_message("Proceso cancelado o interrumpido.")
                    self.progress_popup.setWindowTitle("Proceso Interrumpido")
                    self.progress_popup.processing_finished()

    @Slot(str, list)
    def handle_id_type_for_entity_base_clarification_from_worker(self, razon_social: str, tipos_id_opciones: list):
        if not self._check_worker_active_or_handle_error(): return
        self._ensure_progress_popup_visible(f"Seleccionar tipo de ID para '{razon_social}'...")
        dialog = IdTypeSelectionDialog(razon_social, self)
        selected_option = None
        if dialog.exec() == QDialog.Accepted: selected_option = dialog.selected_id_type
        else:
            logger.info(f"El diálogo de selección de tipo de ID para '{razon_social}' fue cancelado.")
            if self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.request_interruption()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.set_selected_id_type_for_base(selected_option)
        elif selected_option is None:
            logger.info("El worker ya no corría cuando el diálogo de tipo de ID fue cancelado.")

    @Slot(dict, bool, str, dict, set)
    def handle_entity_determined(self, header_data: dict, is_new_entity: bool, temp_dir_path_this_run: str, xml_to_pdf_map_this_run: dict, processed_ids_for_entity_from_worker: set):
        if is_new_entity:
            self._clear_report_data_for_new_entity(); self.processed_xml_identifiers_for_current_entity.clear()
        else: self.processed_xml_identifiers_for_current_entity = processed_ids_for_entity_from_worker.copy()
        self.selected_entity_details["id_display"] = header_data.get("id_comprador", "")
        self.selected_entity_details["razon_social"] = header_data.get("razon_social_comprador", "")
        raw_id_display = self.selected_entity_details["id_display"]
        self.selected_entity_details["ids_to_match"] = [id_part.strip() for id_part in raw_id_display.split('/') if id_part.strip()]
        if not self.selected_entity_details["ids_to_match"] and raw_id_display: self.selected_entity_details["ids_to_match"].append(raw_id_display)
        self.id_comprador_label.setText(self.selected_entity_details["id_display"])
        self.razon_social_comprador_label.setText(self.selected_entity_details["razon_social"])
        if temp_dir_path_this_run and os.path.isdir(temp_dir_path_this_run): self.tracked_temp_pdf_dirs.add(temp_dir_path_this_run)
        self.initial_process_done = True

    @Slot(dict, str, object)
    def add_row_to_table(self, row_data: Dict[str, Any], cod_doc: str, backup_pdf_path: Optional[str]):
        if not self.initial_process_done: return
        if not (row_data and cod_doc): return
        unique_id_of_row = row_data.get("Nro de Autorización")
        if unique_id_of_row and unique_id_of_row in self.processed_xml_identifiers_for_current_entity: return
        if "original_xml_path" not in row_data and "xml_path" in row_data:
            row_data["original_xml_path"] = row_data["xml_path"]
        row_data['backup_pdf_path'] = backup_pdf_path
        self.all_data_by_coddoc[cod_doc].append(row_data)
        if unique_id_of_row: self.processed_xml_identifiers_for_current_entity.add(unique_id_of_row)
        doc_definition = self.COLUMN_DEFINITIONS.get(self.active_doc_key)
        if doc_definition and doc_definition.get("coddoc") == cod_doc:
             self._update_displayed_report()

    @Slot(str, str, str)
    def handle_entity_id_mismatch_on_add_more(self, current_gui_rs: str, current_gui_id: str, new_entity_rs: str):
        if self.progress_popup and self.progress_popup.isVisible(): pass
        QMessageBox.critical(
            self, "Error de Procesamiento - Entidad Inconsistente",
            f"Está intentando procesar comprobantes para '{new_entity_rs}', "
            f"pero la interfaz ya muestra datos para '{current_gui_rs}' (ID: {current_gui_id}).\n\n"
            f"Por favor, presione el botón 'Reiniciar' para limpiar la interfaz actual y luego "
            f"seleccione los archivos correspondientes para procesar los comprobantes de '{new_entity_rs}'."
        )
        self.process_xml_button.setEnabled(True)

    @Slot(list, list, list, bool, str, int, int, list, int, dict, dict)
    def handle_processing_complete(self, conversion_errors: List[str], errors_pdf_gen: List[str], critical_file_errors: List[dict], was_cancelled_by_user: bool, temp_dir_of_this_worker: str, newly_processed_count: int, skipped_duplicate_files_count: int, newly_added_ids_list: List[str], total_files_attempted_for_table: int, processed_counts_by_type: dict, final_xml_to_pdf_map: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]]):
        final_message_parts = []
        if was_cancelled_by_user:
            final_message_parts = ["--- Proceso Cancelado por el Usuario ---"]
            if temp_dir_of_this_worker and temp_dir_of_this_worker in self.tracked_temp_pdf_dirs:
                 self.tracked_temp_pdf_dirs.remove(temp_dir_of_this_worker)
        else:
            final_message_parts = ["--- Proceso Finalizado ---"]
            self.xml_to_pdf_map.update(final_xml_to_pdf_map)
            if total_files_attempted_for_table > 0 or newly_processed_count > 0 or skipped_duplicate_files_count > 0 or critical_file_errors: final_message_parts.append(f"{total_files_attempted_for_table} archivo(s) XML considerados.")
            if newly_processed_count > 0: final_message_parts.append(f"  - {newly_processed_count} nuevo(s) registrado(s).")
            elif total_files_attempted_for_table > 0: final_message_parts.append(f"  - 0 nuevos registrados.")
            if skipped_duplicate_files_count > 0: final_message_parts.append(f"  - {skipped_duplicate_files_count} duplicado(s) omitido(s).")
            if processed_counts_by_type and newly_processed_count > 0:
                final_message_parts.append("\nDetalle de comprobantes registrados:")
                for code, count in processed_counts_by_type.items():
                    if count > 0: final_message_parts.append(f"  - {xml_parser.COD_DOC_MAP.get(code, f'Tipo {code}')}: {count}")
        if conversion_errors:
            final_message_parts.append(f"\nAdvertencias de conversión ({len(conversion_errors)}):");
            for i, err in enumerate(conversion_errors[:3]): final_message_parts.append(f"  - {err}")
            if len(conversion_errors) > 3: final_message_parts.append(f"  ...y {len(conversion_errors) - 3} más (ver log).")
        if errors_pdf_gen:
            final_message_parts.append(f"\nAdvertencias PDF ({len(errors_pdf_gen)}):")
            for i, err in enumerate(errors_pdf_gen[:3]): final_message_parts.append(f"  - {err}")
            if len(errors_pdf_gen) > 3: final_message_parts.append(f"  ...y {len(errors_pdf_gen) - 3} más (ver log).")
        if critical_file_errors:
            final_message_parts.append(f"\nErrores críticos ({len(critical_file_errors)}):")
            for i, err in enumerate(critical_file_errors[:3]): final_message_parts.append(f"  - {err.get('file', 'N/A')}: {err.get('message', 'Desconocido')}")
            if len(critical_file_errors) > 3: final_message_parts.append(f"  ...y {len(critical_file_errors) - 3} más (ver log).")
        if self.progress_popup:
            if not self.progress_popup.isVisible() and (final_message_parts or errors_pdf_gen or critical_file_errors): self.progress_popup.show()
            self.progress_popup.set_message("\n".join(final_message_parts)); self.progress_popup.processing_finished()
        else: QMessageBox.information(self, "Estado del Proceso", "\n".join(final_message_parts))
        self._update_button_visibility_and_default_selection(); self.process_xml_button.setEnabled(True)

    @Slot()
    def on_worker_finished_cleanup(self):
        if self.worker_thread: self.worker_thread.deleteLater(); self.worker_thread = None
        if not self.process_xml_button.isEnabled(): self.process_xml_button.setEnabled(True)
        self._update_button_visibility_and_default_selection()

    def _clear_report_data_for_new_entity(self):
        self.id_comprador_label.setText("N/A"); self.razon_social_comprador_label.setText("N/A")
        self.report_table.setRowCount(0); self.report_table.setColumnCount(0)
        if hasattr(self, 'custom_header') and self.custom_header: self.custom_header.setSummationData({})
        self.xml_to_pdf_map.clear(); self.all_data_by_coddoc.clear()
        for temp_dir in list(self.tracked_temp_pdf_dirs):
            if os.path.exists(temp_dir): cleanup_temp_folder(temp_dir)
        self.tracked_temp_pdf_dirs.clear()

    def _get_data_for_view(self, doc_key_filter: str) -> List[Dict[str, Any]]:
        doc_info = self.COLUMN_DEFINITIONS.get(doc_key_filter)
        if not doc_info: return []
        return self.all_data_by_coddoc.get(doc_info["coddoc"], [])

    def _get_display_headers_for_doc_type(self, doc_key: str, data_rows: List[Dict[str, Any]], include_no_column: bool = True) -> List[str]:
        doc_definition = self.COLUMN_DEFINITIONS.get(doc_key)
        if not doc_definition:
            return []

        base_headers_for_doc_type = [h for h in doc_definition.get("headers", []) if h != "No."]
        headers_with_data = []

        if data_rows:
            for header_name in base_headers_for_doc_type:
                if header_name in self._cols_to_exclude_from_view:
                    continue
                
                data_key_for_check = self.HEADER_TO_DATA_KEY_MAP.get(header_name, header_name)
                has_data = any(
                    _is_value_significant_for_display(row_data.get(data_key_for_check))
                    for row_data in data_rows
                )
                if has_data:
                    headers_with_data.append(header_name)

        if doc_key == "RET_R" and "Primeros 3 Articulos" in headers_with_data:
            headers_with_data.remove("Primeros 3 Articulos")

        sorted_headers_with_data = sorted(
            headers_with_data, 
            key=lambda h: self.HEADER_ORDER_MAP.get(h, len(self.HEADER_ORDER_MAP))
        )

        final_display_headers = []
        if include_no_column and data_rows and headers_with_data:
            final_display_headers.append("No.")
        final_display_headers.extend(sorted_headers_with_data)
        
        return final_display_headers

    def _create_table_item(self, header_name_display: str, original_row_data: Dict[str, Any], row_idx: int) -> QTableWidgetItem:
        table_item = QTableWidgetItem()
        item_value_str = ""

        if header_name_display == "No.":
            prefix = self.active_doc_key[:2].upper() if self.active_doc_key else "N"
            item_value_str = f"{prefix}{row_idx + 1}"
            backup_pdf_path = original_row_data.get('backup_pdf_path')
            if backup_pdf_path and os.path.exists(backup_pdf_path):
                table_item.setData(USER_ROLE_PDF_PATH, backup_pdf_path)
                table_item.setForeground(QColor("blue")) # El delegado NoColumn anulará esto por blanco
                font = table_item.font(); font.setItalic(True); font.setUnderline(True); table_item.setFont(font)
                table_item.setForeground(Qt.GlobalColor.white)
                table_item.setToolTip(f"Abrir PDF: {os.path.basename(backup_pdf_path)}")
            else:
                table_item.setData(USER_ROLE_PDF_PATH, None)
                font = table_item.font(); font.setUnderline(False); table_item.setFont(font)
                table_item.setToolTip("")
            table_item.setData(Qt.ItemDataRole.UserRole, original_row_data.get("original_xml_path"))
            font = table_item.font(); font.setBold(True); table_item.setFont(font)
            table_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        else:
            data_key = self.HEADER_TO_DATA_KEY_MAP.get(header_name_display, header_name_display)
            item_value = original_row_data.get(data_key, "")
            if isinstance(item_value, float):
                if any(substring in header_name_display.lower() for substring in 
                       ["base", "monto", "total", "valor", "descuento", "ret.", "propina", "iva", "ice", "irbpnr"]):
                    item_value_str = f"{item_value:.2f}"
                else: item_value_str = str(item_value)
            else: item_value_str = str(item_value)
        
        table_item.setText(item_value_str)
        return table_item

    def _calculate_column_sums(self, data_rows: List[Dict[str, Any]], display_column_headers: List[str], sum_column_names: List[str]) -> Dict[int, str]:
        sum_values_for_header: Dict[int, str] = {}
        if not data_rows or not display_column_headers or not sum_column_names:
            return sum_values_for_header

        header_to_index_map = {name: i for i, name in enumerate(display_column_headers)}

        for col_name_to_sum_display in sum_column_names:
            col_idx_in_display = header_to_index_map.get(col_name_to_sum_display)
            if col_idx_in_display is None: continue

            current_sum = 0.0
            data_key_for_sum = self.HEADER_TO_DATA_KEY_MAP.get(col_name_to_sum_display, col_name_to_sum_display)
            
            for row_data in data_rows:
                value_from_data = row_data.get(data_key_for_sum, 0.0)
                try:
                    if isinstance(value_from_data, (int, float)): current_sum += float(value_from_data)
                    elif isinstance(value_from_data, str):
                        cleaned_value_str = value_from_data.replace(',', '.').strip()
                        if cleaned_value_str: current_sum += float(cleaned_value_str)
                except (ValueError, TypeError):
                    logger.debug(f"Suma: No se pudo convertir '{value_from_data}' (tipo: {type(value_from_data)}) "
                                 f"para la suma de '{col_name_to_sum_display}' (data key: {data_key_for_sum}).")
            sum_values_for_header[col_idx_in_display] = f"{current_sum:.2f}"
        return sum_values_for_header

    def _populate_report_table(self, data_rows: List[dict], display_column_headers: List[str], sum_column_names: List[str]):
        self.report_table.setRowCount(0)
        if not display_column_headers:
            self.report_table.setColumnCount(0); self.report_table.setHorizontalHeaderLabels([])
            self.report_table.horizontalHeader().setVisible(False)
            if hasattr(self, 'custom_header') and self.custom_header: self.custom_header.setSummationData({})
            return
        self.report_table.setColumnCount(len(display_column_headers))
        self.report_table.setHorizontalHeaderLabels(display_column_headers)
        self.report_table.horizontalHeader().setVisible(len(display_column_headers) > 0)

        for row_idx, original_row_data in enumerate(data_rows):
            self.report_table.insertRow(row_idx)
            if "tipo_documento_display" not in original_row_data:
                cod_doc_original = original_row_data.get("CodDoc", "")
                original_row_data["tipo_documento_display"] = xml_parser.COD_DOC_MAP.get(cod_doc_original, f"Tipo {cod_doc_original}")
            for col_idx, header_name_display in enumerate(display_column_headers):
                table_item = self._create_table_item(header_name_display, original_row_data, row_idx)
                self.report_table.setItem(row_idx, col_idx, table_item)
        self.report_table.resizeColumnsToContents()
        if hasattr(self, 'custom_header') and self.custom_header and self.report_table.rowCount() > 0:
            desired_row_height = self.custom_header._single_line_height
            if desired_row_height <= 0: self.report_table.resizeRowsToContents()
            else:
                for r_idx in range(self.report_table.rowCount()): self.report_table.setRowHeight(r_idx, desired_row_height)
        else: self.report_table.resizeRowsToContents()
        sum_values = self._calculate_column_sums(data_rows, display_column_headers, sum_column_names)
        if hasattr(self, 'custom_header') and self.custom_header: self.custom_header.setSummationData(sum_values)

    def _update_displayed_report(self):
        if not self.active_doc_key:
            self._populate_report_table([], [], [])
            return

        doc_definition = self.COLUMN_DEFINITIONS[self.active_doc_key]
        data_for_current_view = self._get_data_for_view(self.active_doc_key)
        display_column_headers = self._get_display_headers_for_doc_type(self.active_doc_key, data_for_current_view)

        sum_cols_for_view = []
        defined_sum_cols = doc_definition.get("sum_cols", [])
        if display_column_headers:
            sum_cols_for_view = [col for col in defined_sum_cols if col in display_column_headers]
        self._populate_report_table(data_for_current_view, display_column_headers, sum_cols_for_view)

    @Slot(int, int)
    def on_report_table_cell_clicked(self, row, column):
        if column == 0:
            item = self.report_table.item(row, column)
            if item:
                pdf_path = item.data(USER_ROLE_PDF_PATH)
                if pdf_path and isinstance(pdf_path, str) and os.path.exists(pdf_path):
                    try:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path))
                        logger.info(f"Abriendo PDF desde la tabla: {pdf_path}")
                    except Exception as e:
                        logger.error(f"Error al intentar abrir PDF desde la tabla: {pdf_path}", exc_info=True)
                        QMessageBox.warning(self, "Error al abrir PDF", f"No se pudo abrir el archivo PDF:\n{pdf_path}\n\nError: {e}")

    @Slot()
    def handle_export_to_excel(self):
        if not self.initial_process_done:
            QMessageBox.warning(self, "Exportar a Excel", "No se han procesado datos para exportar.")
            return
        data_by_sheet_to_export: Dict[str, Dict[str, Any]] = {}
        any_data_found = False
        for doc_key in self.DOC_TYPE_ORDER:
            doc_definition = self.COLUMN_DEFINITIONS.get(doc_key)
            if not doc_definition: continue
            data_for_this_sheet = self._get_data_for_view(doc_key) # Reutilizar la misma lógica de obtención de datos
            final_display_headers_excel = self._get_display_headers_for_doc_type(doc_key, data_for_this_sheet, include_no_column=True)

            if data_for_this_sheet:
                sheet_name_base = doc_definition.get("name", f"Reporte_{doc_key}")[:31].strip()
                sheet_name = sheet_name_base; count = 1
                while sheet_name in data_by_sheet_to_export:
                    sheet_name = f"{sheet_name_base[:28]}_{count}"
                    if len(sheet_name) > 31: sheet_name = sheet_name[:31]
                    count += 1
                sum_display_names_for_sheet = doc_definition.get("sum_cols", [])
                doc_key_prefix_for_no = doc_key[:2].upper() if doc_key else "N"
                prepared_data_for_excel_sheet = []
                for i, row_data_original in enumerate(data_for_this_sheet):
                    row_for_excel = {}
                    for display_name in final_display_headers_excel:
                        if display_name == "No.":
                            no_value_display = f"{doc_key_prefix_for_no}{i + 1}"
                            backup_pdf_path = row_data_original.get('backup_pdf_path')
                            if backup_pdf_path and os.path.exists(backup_pdf_path):
                                excel_link_url = f"external:{os.path.normpath(backup_pdf_path)}"
                                row_for_excel[display_name] = ("HYPERLINK", (excel_link_url, no_value_display))
                            else:
                                row_for_excel[display_name] = no_value_display
                        else:
                            data_key = self.HEADER_TO_DATA_KEY_MAP.get(display_name, display_name)
                            value = row_data_original.get(data_key)
                            if isinstance(value, float):
                                row_for_excel[display_name] = value
                            else:
                                row_for_excel[display_name] = value
                    prepared_data_for_excel_sheet.append(row_for_excel)
                data_by_sheet_to_export[sheet_name] = {
                    "data": prepared_data_for_excel_sheet,
                    "sum_display_names": sum_display_names_for_sheet,
                    "doc_key_prefix": doc_key_prefix_for_no,
                    "doc_key_original": doc_key,
                    "final_ordered_display_names": final_display_headers_excel
                }
                any_data_found = True
        if not any_data_found:
            QMessageBox.information(self, "Exportar a Excel", "No hay datos en ninguna pestaña para exportar.")
            return ExcelExportStatus.NO_DATA_OR_COLUMNS

        file_path = self._get_save_file_dialog(
            title="Guardar Reporte Excel Consolidado",
            default_filename_template="Reporte_{entity}_{timestamp}.xlsx",
            entity_rs=self.selected_entity_details.get("razon_social"),
            file_filter="Archivos Excel (*.xlsx)",
            last_dir_setting_key=SETTINGS_LAST_XML_DIR # Usar la carpeta de los últimos XML procesados
        )

        if not file_path: return ExcelExportStatus.INVALID_PATH

        export_status = export_to_excel(data_by_sheet=data_by_sheet_to_export, file_path=file_path)
        if export_status == ExcelExportStatus.SUCCESS:
            QMessageBox.information(self, "Exportación Exitosa", f"Reporte consolidado exportado exitosamente a:\n{file_path}")
            self._open_directory_or_select_file(os.path.dirname(file_path))
        elif export_status == ExcelExportStatus.ERROR_PERMISSION:
            QMessageBox.warning(self, "Error de Permiso",
                                f"No se pudo guardar el archivo en:\n{file_path}\n\n"
                                "Por favor, verifique lo siguiente:\n"
                                "1. El archivo no está abierto en otro programa (ej. Excel).\n"
                                "2. Tiene permisos para escribir en la carpeta seleccionada.\n"
                                "3. El nombre del archivo es válido.")
        elif export_status == ExcelExportStatus.ERROR_IMPORT_XLSXWRITER:
            QMessageBox.critical(self, "Error de Dependencia",
                                 "La biblioteca 'xlsxwriter' es necesaria para exportar a Excel con formato avanzado.\n"
                                 "Por favor, instálala ejecutando en la terminal:\n"
                                 "pip install xlsxwriter\n\n"
                                 "Luego, reinicie la aplicación.")
        elif export_status == ExcelExportStatus.NO_DATA_OR_COLUMNS:
            QMessageBox.information(self, "Exportar a Excel",
                                    "No se encontraron datos significativos o columnas válidas para exportar en las pestañas seleccionadas.")
        elif export_status == ExcelExportStatus.INVALID_PATH:
             pass
        else:
            QMessageBox.critical(self, "Error de Exportación", "Ocurrió un error desconocido al exportar los datos a Excel. Revise los logs para más detalles.")
        return export_status

    def _cleanup_tracked_temp_dirs(self):
        for temp_dir in list(self.tracked_temp_pdf_dirs):
            if os.path.exists(temp_dir):
                try: cleanup_temp_folder(temp_dir); self.tracked_temp_pdf_dirs.discard(temp_dir)
                except Exception as e: logger.error(f"Error limpiando dir temp {temp_dir}: {e}")
            else: self.tracked_temp_pdf_dirs.discard(temp_dir)

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, 'Proceso en Curso', "Proceso en ejecución. ¿Salir?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: event.ignore(); return
            else:
                self.worker_thread.request_interruption()
                if not self.worker_thread.wait(3000):
                    logger.warning("El hilo de trabajo no terminó en 3 segundos, terminando forzosamente.")
                    self.worker_thread.terminate(); self.worker_thread.wait()
        if self.progress_popup and self.progress_popup.isVisible(): self.progress_popup.reject()
        self._cleanup_tracked_temp_dirs(); self.settings.sync(); event.accept()

def main():
    import sys
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
