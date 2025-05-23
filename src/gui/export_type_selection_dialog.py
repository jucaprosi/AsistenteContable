# d:\Datos\Desktop\Asistente Contable\src\gui\export_type_selection_dialog.py
import logging
from typing import Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QRadioButton, QButtonGroup, QDialogButtonBox
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

class ExportTypeSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar Tipo de Exportación")
        self.setModal(True)
        self.setMinimumWidth(450) # Ajustar ancho para textos más largos
        self.setObjectName("ExportTypeSelectionDialog")

        self.selected_export_type: Optional[str] = None # "pdf_xml_by_type", "pdf_xml_by_date", "pdf_only_by_date"

        layout = QVBoxLayout(self)

        main_label = QLabel("¿Cómo desea exportar los archivos en el ZIP?")
        main_label.setWordWrap(True)
        layout.addWidget(main_label)

        self.radio_button_group = QButtonGroup(self)

        self.radio_pdf_xml_by_type = QRadioButton("Exportar PDF y XML (en subcarpetas por tipo de documento)")
        self.radio_pdf_xml_by_date = QRadioButton("Exportar PDF y XML (en subcarpetas por fecha de autorización)")
        self.radio_pdf_only_by_date = QRadioButton("Exportar solo PDF (en subcarpetas por fecha de autorización)")

        # Opción predeterminada
        self.radio_pdf_xml_by_type.setChecked(True)

        self.radio_button_group.addButton(self.radio_pdf_xml_by_type)
        self.radio_button_group.addButton(self.radio_pdf_xml_by_date)
        self.radio_button_group.addButton(self.radio_pdf_only_by_date)

        # Añadir radios al layout
        layout.addWidget(self.radio_pdf_xml_by_type)
        layout.addWidget(self.radio_pdf_xml_by_date)
        layout.addWidget(self.radio_pdf_only_by_date)
        layout.addSpacing(10)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.adjustSize()

    def accept_selection(self):
        if self.radio_pdf_xml_by_type.isChecked():
            self.selected_export_type = "pdf_xml_by_type"
        elif self.radio_pdf_xml_by_date.isChecked():
            self.selected_export_type = "pdf_xml_by_date"
        elif self.radio_pdf_only_by_date.isChecked():
            self.selected_export_type = "pdf_only_by_date"
        else:
            self.selected_export_type = None
            
        logger.info(f"Tipo de exportación seleccionada: {self.selected_export_type}")
        super().accept()

    def get_selected_export_type(self) -> Optional[str]:
        return self.selected_export_type
