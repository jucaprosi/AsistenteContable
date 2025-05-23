# d:\Datos\Desktop\Asistente Contable\src\gui\tipo_identificacion_dialog.py
import logging
from typing import List, Dict, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox, QPushButton
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

class TipoIdentificacionDialog(QDialog):
    def __init__(self, entity_razon_social: str, available_doc_codes: List[str], doc_code_map: Dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar Tipo de Documento")
        self.setModal(True)
        self.setMinimumWidth(400)

        self.available_doc_codes = available_doc_codes
        self.doc_code_map = doc_code_map # Mapa de código a nombre legible
        self.selected_tipo_identificacion: Optional[str] = None # Código del tipo de documento (e.g., "01")

        layout = QVBoxLayout(self)

        instruction_label = QLabel(
            f"Para la entidad '{entity_razon_social}', se encontraron los siguientes tipos de documentos en los archivos seleccionados.\n"
            "Por favor, elija el tipo de documento que desea procesar en este lote:"
        )
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        self.combo_box_doc_types = QComboBox()
        # Llenar el ComboBox con "Nombre Legible (Código)"
        # Guardar el código como data asociada al item
        for code in sorted(self.available_doc_codes):
            name = self.doc_code_map.get(code, f"Tipo Desconocido ({code})")
            display_text = f"{name} (Código: {code})"
            self.combo_box_doc_types.addItem(display_text, userData=code)
        layout.addWidget(self.combo_box_doc_types)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.adjustSize()

    def accept_selection(self):
        if self.combo_box_doc_types.currentIndex() >= 0:
            self.selected_tipo_identificacion = self.combo_box_doc_types.currentData()
        logger.info(f"Tipo de documento seleccionado para procesamiento: {self.selected_tipo_identificacion}")
        super().accept()