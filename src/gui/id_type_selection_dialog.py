# d:\Datos\Desktop\Asistente Contable\src\gui\id_type_selection_dialog.py
import logging
from typing import Optional, List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QRadioButton, QButtonGroup, QDialogButtonBox, QWidget, QHBoxLayout
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

class IdTypeSelectionDialog(QDialog):
    def __init__(self, razon_social: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Seleccionar Tipo de ID para {razon_social}")
        self.setModal(True)
        self.setMinimumWidth(400)

        self.selected_id_type: Optional[str] = None # "ruc", "cedula", "ambos"

        layout = QVBoxLayout(self)

        main_label_text = (
            f"Para {razon_social}, ha seleccionado comprobantes con RUC Y Cédula.\n"
            "PROCESAR DOCUMENTOS CON:"
        )
        main_label = QLabel(main_label_text)
        main_label.setWordWrap(True)
        layout.addWidget(main_label)

        self.radio_button_group = QButtonGroup(self)

        self.radio_ruc = QRadioButton("RUC")
        self.radio_cedula = QRadioButton("CÉDULA")
        self.radio_ambos = QRadioButton("AMBOS")

        # Establecer "Ambos" como opción predeterminada
        self.radio_ambos.setChecked(True)

        self.radio_button_group.addButton(self.radio_ruc)
        self.radio_button_group.addButton(self.radio_cedula)
        self.radio_button_group.addButton(self.radio_ambos)

        radio_layout = QVBoxLayout() # Usar QVBoxLayout para que los radios estén uno debajo del otro
        radio_layout.addWidget(self.radio_ruc)
        radio_layout.addWidget(self.radio_cedula)
        radio_layout.addWidget(self.radio_ambos)
        layout.addLayout(radio_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def accept_selection(self):
        if self.radio_ruc.isChecked(): self.selected_id_type = "ruc"
        elif self.radio_cedula.isChecked(): self.selected_id_type = "cedula"
        elif self.radio_ambos.isChecked(): self.selected_id_type = "ambos"
        logger.info(f"Tipo de ID seleccionado para procesamiento: {self.selected_id_type}")
        super().accept()