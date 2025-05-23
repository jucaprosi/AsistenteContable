# d:\Datos\Desktop\Asistente Contable\src\core\pdf_base.py

import os
import sys # Necesario para resource_path
from fpdf import FPDF, FPDFException
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime, timezone # Importar datetime y timezone
import logging # Importar logging

logger = logging.getLogger(__name__) # Obtener logger para este módulo

if TYPE_CHECKING: # Solo para type hinting
    from fpdf import FPDF # Para el type hint de _draw_c_two_col_row

try:
    import barcode
    from barcode.writer import ImageWriter
    import io
    BARCODE_SUPPORT = True
except ImportError:
    BARCODE_SUPPORT = False
    logger.warning("Biblioteca 'python-barcode' no instalada. No se generarán códigos de barras.")

# --- Constantes de Estilo ---
MARGIN_LEFT = 10; MARGIN_RIGHT = 10; MARGIN_TOP = 15; MARGIN_BOTTOM = 15
BASE_FONT_SIZE = 8; BASE_LINE_HEIGHT = 4.0 
BODY_FONT_SIZE = BASE_FONT_SIZE; TABLE_LINE_HEIGHT = 3.8 # Aumentado TABLE_LINE_HEIGHT
LINE_HEIGHT = BASE_LINE_HEIGHT; SMALL_FONT_SIZE = 7; ACCESS_KEY_FONT_SIZE = 5
SUMMARY_TABLE_FONT_SIZE = 7; SUMMARY_TABLE_LINE_HEIGHT = 3.2
COLOR_BLACK = (0, 0, 0)

ROW_V_PADDING_AFTER = 1.0 # Constante que también podría ser necesaria globalmente

BORDER_THICKNESS_PT = 0.4
BORDER_THICKNESS_MM = BORDER_THICKNESS_PT * (25.4 / 72) # Conversión de puntos a mm
FONT_FAMILY_NAME = 'Helvetica' # Cambiado a Helvetica
FONT_FALLBACK = 'Helvetica' # Mantener o cambiar a otra core si Helvetica falla (raro)

def resource_path(relative_path: str) -> str:
    """ Obtiene la ruta absoluta a un recurso, funciona para desarrollo y para PyInstaller """
    try:
        # PyInstaller crea una carpeta temporal y almacena la ruta en _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError: # Cambiado de Exception a AttributeError que es más específico para _MEIPASS
        base_path = os.path.abspath(".") # Para desarrollo normal o si no está empaquetado

    return os.path.join(base_path, relative_path)

FONTS_DIR = resource_path(os.path.join('assets', 'fonts'))
TABLE_FONT_SIZE = 6 # Reducido TABLE_FONT_SIZE

# --- Mapas de Catálogos ---
PAYMENT_METHOD_MAP = {
    "01": "SIN UTILIZACION DEL SISTEMA FINANCIERO", "15": "COMPENSACIÓN DE DEUDAS",
    "16": "TARJETA DE DÉBITO", "17": "DINERO ELECTRÓNICO", "18": "TARJETA PREPAGO",
    "19": "TARJETA DE CRÉDITO", "20": "OTROS CON UTILIZACION DEL SISTEMA FINANCIERO",
    "21": "ENDOSO DE TÍTULOS"
}
COD_DOC_SUSTENTO_MAP = {
    "01": "FACTURA", "02": "NOTA DE VENTA", "03": "LIQ. DE COMPRA",
    "04": "NOTA DE CRÉDITO", "05": "NOTA DE DÉBITO", "06": "GUÍA DE REMISIÓN",
    "07": "COMP. DE RETENCIÓN"
}
IMPUESTO_RETENCION_MAP = {
    "1": "RENTA", "2": "IVA", "6": "ISD"
}

class InvoicePDF(FPDF):
    _font_name: str = FONT_FALLBACK
    _draw_border: bool = False 

    def set_doc_font(self, font_name: str):
        self._font_name = font_name

    def header(self):
        pass

    def add_page(self, orientation: str = '', format: str = '', same: bool = False):
        super().add_page(orientation, format, same)
        self.set_draw_color(*COLOR_BLACK) 
        self.set_line_width(BORDER_THICKNESS_MM) 
        if self._draw_border:
            original_draw_color_r, original_draw_color_g, original_draw_color_b = self.draw_color.r, self.draw_color.g, self.draw_color.b
            original_line_width = self.line_width
            original_font_family = self.font_family
            original_font_style = self.font_style
            
            self.set_draw_color(204, 204, 204) 
            self.set_line_width(0.2)
            self.rect(MARGIN_LEFT / 2, MARGIN_TOP / 2, self.w - MARGIN_LEFT, self.h - MARGIN_TOP)
            
            self.set_draw_color(original_draw_color_r, original_draw_color_g, original_draw_color_b)
            self.set_line_width(original_line_width)
            if original_font_family: 
                self.set_font(original_font_family, original_font_style)

    def footer(self):
        if hasattr(self, 'page_no') and self.page_no() != 0: 
            self.set_y(-MARGIN_BOTTOM + 5) 
            self.set_font(self._font_name, 'I', 7) 
            self.set_text_color(128, 128, 128) 
            self.cell(0, 10, f'Página {self.page_no()} / {{nb}}', 0, 0, 'C')
            self.set_text_color(*COLOR_BLACK) 

# --- Funciones Auxiliares Comunes ---
def _parse_fecha_pdf(fecha_str: Optional[str]) -> str:
    """Parsea una cadena de fecha en varios formatos y devuelve 'dd/mm/yyyy' o la original."""
    if not fecha_str:
        return ""
    try:
        dt_obj = None
        val_to_parse = fecha_str.replace('Z', '+00:00') # Manejar Z para UTC
        
        possible_formats = [
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z", # Formato con offset de zona horaria
            "%Y-%m-%dT%H:%M:%S",   # Formato sin offset de zona horaria
            "%d/%m/%Y",
        ]
        
        for fmt in possible_formats:
            try:
                tz_offset_char = None
                if '%z' in fmt: # Solo relevante para formatos con %z
                    if '+' in val_to_parse[-6:]: tz_offset_char = '+'
                    elif '-' in val_to_parse[-6:]: tz_offset_char = '-'

                # Lógica para manejar el ':' en el offset de zona horaria
                if '%z' in fmt and tz_offset_char and ':' in val_to_parse[-3:]:
                    # Formato como "2023-10-26T10:00:00-05:00"
                    dt_obj = datetime.strptime(val_to_parse[:-3] + val_to_parse[-2:], fmt)
                elif '%z' in fmt and tz_offset_char and ':' not in val_to_parse[-3:]:
                    # Formato como "2023-10-26T10:00:00-0500"
                    dt_obj = datetime.strptime(val_to_parse, fmt)
                elif '%z' not in fmt:
                     # Formatos sin información de zona horaria explícita
                     dt_obj = datetime.strptime(val_to_parse, fmt)
                
                if dt_obj: break # Si se parsea correctamente, salir del bucle
            except ValueError:
                continue # Probar el siguiente formato
        
        # Devolver formateado si se parseó, sino la parte de la fecha de la cadena original
        return dt_obj.strftime('%d/%m/%Y') if dt_obj else fecha_str.split('T')[0]
    except Exception:
        # Fallback muy genérico si todo lo demás falla
        return fecha_str.split('T')[0] if 'T' in fecha_str else fecha_str

def _safe_get(data: Dict, keys: List[str], default: Any = '') -> Any:
    """Obtiene un valor de un diccionario anidado de forma segura."""
    temp = data
    for key in keys:
        if isinstance(temp, dict) and key in temp:
            temp = temp[key]
        else:
            return default
    return temp if temp is not None else default

def _format_currency_pdf(value: Any, default: float = 0.0) -> str:
    """Formatea un valor como moneda para el PDF (ej. 123.45)."""
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return f"{default:.2f}"

def _format_summary_value(value: Any, default: float = 0.0) -> str:
    """Formatea un valor para la sección de resumen, con separador de miles (ej. 1,234.56)."""
    try:
        return f"{float(value):,.2f}"
    except (ValueError, TypeError):
        return f"{default:,.2f}"

def _format_integer_pdf(value: Any, default: int = 0) -> str:
    """Formatea un valor como entero para el PDF (ej. 123)."""
    try:
        return f"{int(float(value))}" 
    except (ValueError, TypeError):
        return f"{default}"

def _draw_c_two_col_row(pdf: 'FPDF', label: str, value: str, current_y: float, start_x: float, width1: float, width2: float, line_height: float, row_spacing: float, font_to_use: str, font_size: int):
    y_before = current_y
    pdf.set_font(font_to_use, '', font_size)
    pdf.set_xy(start_x, y_before)
    pdf.multi_cell(width1, line_height, label, 0, 'L')
    y_after_col1 = pdf.get_y()

    pdf.set_xy(start_x + width1, y_before)
    pdf.multi_cell(width2, line_height, value, 0, 'L')
    y_after_col2 = pdf.get_y()

    new_y = max(y_after_col1, y_after_col2) + row_spacing
    pdf.set_y(new_y)
    return new_y
        
# --- Funciones de Cálculo Comunes ---
def _calculate_totals(invoice_data: Dict[str, Any]) -> Dict[str, float]:
    """
    Calcula varios totales y subtotales basados en los datos del documento.
    """
    totals = {
        "subtotal_iva_15": 0.0, "subtotal_iva_12": 0.0, "subtotal_iva_5": 0.0, "subtotal_iva_0": 0.0,
        "subtotal_iva_diferenciado": 0.0, "subtotal_no_objeto": 0.0, "subtotal_exento": 0.0,
        "iva_15": 0.0, "iva_12": 0.0, "iva_5": 0.0, "iva_diferenciado": 0.0,
        "total_ice": 0.0, "total_irbpnr": 0.0, "total_devolucion_iva": 0.0
    }
    impuestos_resumen = _safe_get(invoice_data, ['totales', 'impuestos_resumen'], [])
    if isinstance(impuestos_resumen, list):
        for imp in impuestos_resumen:
            if isinstance(imp, dict):
                codigo = str(imp.get('codigo', '')) 
                codigo_porcentaje = str(imp.get('codigo_porcentaje', '')) 
                
                try: base_imponible = float(imp.get('base_imponible', '0.0'))
                except (ValueError, TypeError): base_imponible = 0.0
                try: valor = float(imp.get('valor', '0.0'))
                except (ValueError, TypeError): valor = 0.0
                try: valor_devolucion = float(imp.get('valor_devolucion_iva', '0.0'))
                except (ValueError, TypeError): valor_devolucion = 0.0

                if codigo == '2': # IVA
                    if codigo_porcentaje == '0': totals["subtotal_iva_0"] += base_imponible
                    elif codigo_porcentaje == '2': totals["subtotal_iva_12"] += base_imponible; totals["iva_12"] += valor
                    elif codigo_porcentaje in ['3', '4']: totals["subtotal_iva_15"] += base_imponible; totals["iva_15"] += valor 
                    elif codigo_porcentaje == '5': totals["subtotal_iva_5"] += base_imponible; totals["iva_5"] += valor
                    elif codigo_porcentaje == '6': totals["subtotal_no_objeto"] += base_imponible
                    elif codigo_porcentaje == '7': totals["subtotal_exento"] += base_imponible
                    elif codigo_porcentaje == '8': totals["subtotal_iva_diferenciado"] += base_imponible; totals["iva_diferenciado"] += valor
                elif codigo == '3': totals["total_ice"] += valor
                elif codigo == '5': totals["total_irbpnr"] += valor
                
                if valor_devolucion != 0.0 : totals["total_devolucion_iva"] += valor_devolucion

    try: totals["total_sin_impuestos"] = float(_safe_get(invoice_data, ['totales', 'total_sin_impuestos'], '0.0'))
    except (ValueError, TypeError): totals["total_sin_impuestos"] = 0.0
    try: totals["total_descuento"] = float(_safe_get(invoice_data, ['totales', 'total_descuento'], '0.0'))
    except (ValueError, TypeError): totals["total_descuento"] = 0.0
    try: totals["propina"] = float(_safe_get(invoice_data, ['totales', 'propina'], '0.0'))
    except (ValueError, TypeError): totals["propina"] = 0.0
    try: totals["importe_total"] = float(_safe_get(invoice_data, ['totales', 'importe_total'], '0.0'))
    except (ValueError, TypeError): totals["importe_total"] = 0.0

    total_subsidio_calculado = 0.0
    detalles_list = _safe_get(invoice_data, ['detalles'], [])
    if isinstance(detalles_list, list):
        for item in detalles_list:
            if isinstance(item, dict):
                detalles_adicionales = item.get('detalles_adicionales', {});
                try: valor_subsidio_item = float(detalles_adicionales.get('valorSubsidio', '0.0')) 
                except (ValueError, TypeError): valor_subsidio_item = 0.0
                
                try: cantidad_item = float(item.get('cantidad', '0.0'))
                except (ValueError, TypeError): cantidad_item = 0.0
                
                total_subsidio_calculado += valor_subsidio_item * cantidad_item
                
    totals["total_subsidio_calculado"] = total_subsidio_calculado
    totals["valor_total_sin_subsidio"] = totals["importe_total"] + total_subsidio_calculado
    return totals
