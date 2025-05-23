# d:\Datos\Desktop\Asistente Contable\src\gui\progress_popup.py
import logging
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QDialogButtonBox, QProgressBar
from PySide6.QtCore import Qt, Slot

logger = logging.getLogger(__name__)

class ProgressPopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Procesando...")
        self.setModal(True) # Bloquea la ventana principal mientras está visible
        self.setMinimumWidth(350)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint) # Quitar botón de ayuda

        self.layout = QVBoxLayout(self)

        self.message_label = QLabel("Iniciando proceso...")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.layout.addWidget(self.message_label)

        # Opcional: Barra de progreso (inicialmente oculta o indeterminada)
        # self.progress_bar = QProgressBar(self)
        # self.progress_bar.setRange(0, 0) # Modo indeterminado
        # self.progress_bar.setVisible(False) # Ocultar hasta que se necesite
        # self.layout.addWidget(self.progress_bar)

        self.button_box = QDialogButtonBox()
        # Inicialmente no tiene botones, se añadirán cuando el proceso termine o se cancele
        self.layout.addWidget(self.button_box)

        self.ok_button = None # Para referencia si se añade

        self.adjustSize() # Ajustar tamaño al contenido

    @Slot(str)
    def set_message(self, message: str):
        """Actualiza el mensaje mostrado en el popup."""
        self.message_label.setText(message)
        logger.debug(f"ProgressPopup mensaje actualizado: {message}")
        self.adjustSize()

    @Slot(int)
    def set_total_files(self, total_files: int):
        """
        Configura el mensaje para indicar el total de archivos (si es relevante).
        Podría usarse para configurar una barra de progreso si se implementa.
        """
        self.set_message(f"Procesando {total_files} archivos XML...")
        # if self.progress_bar:
        #     self.progress_bar.setRange(0, total_files)
        #     self.progress_bar.setValue(0)
        #     self.progress_bar.setVisible(True)

    def processing_finished(self):
        """Configura el popup para indicar que el proceso ha finalizado."""
        logger.debug(f"ProgressPopup.processing_finished() llamado. Título actual: {self.windowTitle()}")
        # El título se establece desde MainWindow.handle_processing_complete
        # self.setWindowTitle("Proceso Completado") 
        
        # Evitar re-añadir el botón si ya existe y es el correcto
        if hasattr(self, 'ok_button') and self.ok_button and self.ok_button.text() == "Cerrar":
            logger.debug("ProgressPopup.processing_finished: Botón 'Cerrar' ya existe. No se hace nada.")
            return

        # Limpiar botones existentes si los hubiera
        self.button_box.clear()
        self.ok_button = self.button_box.addButton("Cerrar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_button.clicked.connect(self.accept)
        self.adjustSize()
        logger.debug(f"ProgressPopup.processing_finished: Botón 'Cerrar' añadido y popup ajustado.")