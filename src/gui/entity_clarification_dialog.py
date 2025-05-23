# d:\Datos\Desktop\Asistente Contable\src\gui\entity_clarification_dialog.py
import logging
from typing import Dict, Any, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox, QPushButton
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

class EntityClarificationDialog(QDialog):
    def __init__(self, opciones_id_base: Dict[str, str], parent=None): # opciones_id_base es Dict[id_raw, razon_social_str]
        super().__init__(parent)
        self.setWindowTitle("Clarificación de Entidad")
        self.setModal(True)
        self.setMinimumWidth(500) # Un poco más de ancho para nombres largos

        self.opciones_id_base = opciones_id_base # Usar el nombre del parámetro
        self.selected_entity_id_raw: Optional[str] = None # ID raw del XML

        layout = QVBoxLayout(self)

        instruction_label = QLabel(
            "Se han detectado múltiples entidades (o variaciones de la misma) en los archivos XML.\n"
            "Por favor, seleccione la entidad principal con la que desea trabajar:"
        )
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        self.combo_box_entities = QComboBox()
        # Llenar el ComboBox con "Razón Social (ID Display) - N archivos"
        # Guardar el ID raw como data asociada al item
        # Ahora 'opciones_id_base'
        # es un diccionario de id_raw -> razon_social_string.
        # La información de 'count' y 'id_display' no está directamente aquí,
        # pero el id_raw es suficiente para la selección.
        # Ordenamos por razón social (el valor del diccionario).
        for id_raw, razon_social_str in sorted(opciones_id_base.items(), key=lambda item: item[1]):
            # El texto a mostrar será "Razón Social (ID)"
            display_text = f"{razon_social_str} ({id_raw})"
            self.combo_box_entities.addItem(display_text, userData=id_raw)
        layout.addWidget(self.combo_box_entities)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.adjustSize()

    def accept_selection(self):
        if self.combo_box_entities.currentIndex() >= 0:
            self.selected_entity_id_raw = self.combo_box_entities.currentData()
        logger.info(f"Entidad seleccionada para clarificación: {self.selected_entity_id_raw}")
        super().accept()

