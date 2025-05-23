# d:\Datos\Desktop\Asistente Contable\src\gui\download_thread.py
import logging
import urllib.request
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

class DownloadThread(QThread):
    download_progress = Signal(int, int)  # bytes_downloaded, total_bytes
    download_finished = Signal(bool, str, str)  # success, saved_filepath, error_message

    def __init__(self, download_url: str, save_path: str, parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.save_path = save_path
        self._is_interruption_requested = False

    def run(self):
        try:
            logger.info(f"Iniciando descarga desde: {self.download_url} hacia {self.save_path}")
            req = urllib.request.Request(self.download_url, headers={'User-Agent': 'AsistenteContableDownloader/1.0'})
            
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.getheader('Content-Length', 0))
                block_size = 8192  # 8KB
                bytes_downloaded = 0
                
                with open(self.save_path, 'wb') as out_file:
                    while True:
                        if self._is_interruption_requested:
                            logger.info("Descarga interrumpida por el usuario.")
                            self.download_finished.emit(False, self.save_path, "Descarga cancelada.")
                            return
                        
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        out_file.write(buffer)
                        bytes_downloaded += len(buffer)
                        self.download_progress.emit(bytes_downloaded, total_size)
            
            if self._is_interruption_requested: # Doble chequeo por si se interrumpe justo al final
                logger.info("Descarga interrumpida por el usuario (post-bucle).")
                self.download_finished.emit(False, self.save_path, "Descarga cancelada.")
            else:
                logger.info(f"Descarga completada: {self.save_path}")
                self.download_finished.emit(True, self.save_path, "")

        except urllib.error.URLError as e:
            logger.error(f"Error de URL durante la descarga: {e.reason}")
            self.download_finished.emit(False, self.save_path, f"Error de red: {e.reason}")
        except Exception as e:
            logger.exception(f"Error inesperado durante la descarga a {self.save_path}:")
            self.download_finished.emit(False, self.save_path, f"Error inesperado: {e}")

    def request_interruption(self):
        self._is_interruption_requested = True
