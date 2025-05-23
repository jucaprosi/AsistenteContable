# d:\Datos\Desktop\Asistente Contable\src\core\pdf_invoice_generator.py
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional, TYPE_CHECKING
from fpdf import FPDFException 
import logging 

# Importaciones desde pdf_base.py
from .pdf_base import (
    InvoicePDF, _safe_get, _format_currency_pdf, _format_summary_value, _format_integer_pdf,
    MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM,
    BASE_FONT_SIZE, BASE_LINE_HEIGHT, BODY_FONT_SIZE, TABLE_LINE_HEIGHT, 
    LINE_HEIGHT, SMALL_FONT_SIZE, ACCESS_KEY_FONT_SIZE,
    _parse_fecha_pdf, _draw_c_two_col_row, # Importar funciones movidas a pdf_base
    SUMMARY_TABLE_FONT_SIZE, SUMMARY_TABLE_LINE_HEIGHT, TABLE_FONT_SIZE, 
    ROW_V_PADDING_AFTER, 
    COLOR_BLACK, BORDER_THICKNESS_MM, FONT_FAMILY_NAME, FONT_FALLBACK, FONTS_DIR, 
    PAYMENT_METHOD_MAP, BARCODE_SUPPORT, _calculate_totals
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING: 
    from fpdf import FPDF


if BARCODE_SUPPORT:
    import barcode
    from barcode.writer import ImageWriter
    import io

# --- Funciones de Dibujo Específicas para Factura ---

def _draw_header_factura(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str) -> float:
    header_start_y = pdf.get_y()
    block_padding_sides = 0.5 # Definir block_padding_sides
    block_padding_top = 2.0
    block_col_padding = 2
    block_font_size = BASE_FONT_SIZE
    block_line_height = BASE_LINE_HEIGHT
    block_row_spacing = block_line_height
    
    BARCODE_HEIGHT_CONST = 12 
    BARCODE_TEXT_SPACING = 0.5
    COLUMN_SPACING = 5
    page_width_available = pdf.w - MARGIN_LEFT - MARGIN_RIGHT
    col_width = (page_width_available - COLUMN_SPACING) / 2
    if col_width <= 0: raise ValueError("Ancho de columna inválido para la cabecera.")

    col_izq_start_x = MARGIN_LEFT
    col_der_start_x = MARGIN_LEFT + col_width + COLUMN_SPACING
    b_content_start_y = 0
    b_content_end_y = 0
    c_content_start_y = header_start_y
    c_content_end_y = 0

    col_izq_current_y = header_start_y
    logo_height = 15 # Altura reservada para el espacio del logo
    logo_spacing_after = 2
    logo_drawn_y = col_izq_current_y
    logo_actual_height = logo_height
    
    # Lógica de carga y dibujo del logo del emisor eliminada.
    # Siempre mostrar la frase "NO TIENE LOGO" en el espacio reservado.
    pdf.set_xy(col_izq_start_x, logo_drawn_y); pdf.set_font(font_to_use, 'B', 25); pdf.set_text_color(255,0,0); pdf.cell(col_width, logo_height, "NO TIENE LOGO", 0, 0, 'C'); pdf.set_text_color(*COLOR_BLACK)
    col_izq_current_y = logo_drawn_y + logo_actual_height + logo_spacing_after
    b_content_start_y = col_izq_current_y

    try:
        pdf.set_font(font_to_use, '', block_font_size)
        pdf.set_text_color(*COLOR_BLACK)
        b_razon_social = _safe_get(invoice_data, ['emisor', 'razon_social'])
        b_nombre_comercial = _safe_get(invoice_data, ['emisor', 'nombre_comercial'])
        b_dir_matriz = _safe_get(invoice_data, ['emisor', 'dir_matriz'])
        b_dir_estab = _safe_get(invoice_data, ['emisor', 'dir_establecimiento'])
        b_contrib_esp = _safe_get(invoice_data, ['emisor', 'contribuyente_especial'])
        b_obligado = _safe_get(invoice_data, ['emisor', 'obligado_contabilidad'])
        
        b_label_r3 = "Dirección\nMatríz:"
        b_label_r4 = "Dirección\nSucursal:"
        b_label_r5 = "Contribuyente Especial"
        b_label_r6 = "OBLIGADO A LLEVAR CONTABILIDAD"
        b_value_r3 = b_dir_matriz
        b_value_r4 = b_dir_estab
        b_value_r5 = b_contrib_esp if b_contrib_esp else ""
        b_value_r6 = b_obligado.upper() if b_obligado and str(b_obligado).strip() else ""

        b_single_col_width = col_width - (block_padding_sides * 2)
        b_text_start_x = col_izq_start_x + block_padding_sides
        b_text_start_y_inner = b_content_start_y + block_padding_top
        pdf.set_xy(b_text_start_x, b_text_start_y_inner)

        pdf.multi_cell(b_single_col_width, block_line_height, b_razon_social, 0, 'L'); pdf.ln(block_row_spacing)
        if b_nombre_comercial and b_nombre_comercial.strip():
            pdf.set_x(b_text_start_x); pdf.multi_cell(b_single_col_width, block_line_height, b_nombre_comercial, 0, 'L'); pdf.ln(block_row_spacing)

        def draw_b_two_col_row(label, value, current_y_func, width1_func, width2_func):
            y_before_row = current_y_func
            pdf.set_xy(b_text_start_x, y_before_row)
            pdf.multi_cell(width1_func, block_line_height, label, 0, 'L')
            y_after_col1_func = pdf.get_y()
            pdf.set_xy(b_text_start_x + width1_func + block_col_padding, y_before_row)
            pdf.multi_cell(width2_func, block_line_height, value, 0, 'L')
            y_after_col2_func = pdf.get_y()
            new_y_row = max(y_after_col1_func, y_after_col2_func) + block_row_spacing
            pdf.set_y(new_y_row)
            return new_y_row

        b_current_y_inner = pdf.get_y()
        pdf.set_font(font_to_use, '', block_font_size)
        label_cell_internal_padding = 1.0
        width_text_matriz = max(pdf.get_string_width(line_m) for line_m in b_label_r3.split('\n'))
        width_text_sucursal = max(pdf.get_string_width(line_s) for line_s in b_label_r4.split('\n'))
        dir_label_cell_width = max(width_text_matriz, width_text_sucursal) + (label_cell_internal_padding * 2)
        dir_value_cell_width = b_single_col_width - dir_label_cell_width - block_col_padding
        min_cell_width_allowed = 5
        if dir_value_cell_width < min_cell_width_allowed:
            dir_value_cell_width = min_cell_width_allowed
            dir_label_cell_width = b_single_col_width - dir_value_cell_width - block_col_padding
            if dir_label_cell_width < min_cell_width_allowed:
                dir_label_cell_width = b_single_col_width * 0.3
                dir_value_cell_width = b_single_col_width - dir_label_cell_width - block_col_padding

        b_current_y_inner = draw_b_two_col_row(b_label_r3, b_value_r3, b_current_y_inner, dir_label_cell_width, dir_value_cell_width)
        b_current_y_inner = draw_b_two_col_row(b_label_r4, b_value_r4, b_current_y_inner, dir_label_cell_width, dir_value_cell_width)

        b_col1_width_r56 = (b_single_col_width - block_col_padding) * 2 / 3
        b_col2_width_r56 = (b_single_col_width - block_col_padding) / 3
        if b_contrib_esp:
            b_current_y_inner = draw_b_two_col_row(f"{b_label_r5}:", b_value_r5, b_current_y_inner, b_col1_width_r56, b_col2_width_r56)
        b_current_y_inner = draw_b_two_col_row(b_label_r6, b_value_r6, b_current_y_inner, b_col1_width_r56, b_col2_width_r56)

        b_content_end_y = b_current_y_inner - block_row_spacing
    except Exception as e_b:
        logger.exception(f"Error dibujando bloque B (Emisor): {e_b}")
        b_content_end_y = pdf.get_y()

    try:
        pdf.set_text_color(*COLOR_BLACK)
        c_ruc = _safe_get(invoice_data, ['emisor', 'ruc'])
        doc_type_str = "FACTURA"
        c_num_factura = _safe_get(invoice_data, ['factura_info', 'numero_factura'])
        c_num_autorizacion = _safe_get(invoice_data, ['numero_autorizacion'])
        c_fecha_autorizacion_fmt = _parse_fecha_pdf(_safe_get(invoice_data, ['fecha_autorizacion'])) # Usar función centralizada

        c_ambiente_val = _safe_get(invoice_data, ['ambiente'])
        c_ambiente_str = "PRODUCCIÓN" if c_ambiente_val == "2" else "PRUEBAS" if c_ambiente_val == "1" else c_ambiente_val
        c_tipo_emision_val = _safe_get(invoice_data, ['factura_info', 'tipo_emision_doc'])
        c_emision_str = "NORMAL" if c_tipo_emision_val == "1" else c_tipo_emision_val
        c_clave_acceso = _safe_get(invoice_data, ['factura_info', 'clave_acceso'])
        
        c_available_internal_width = col_width - (block_padding_sides * 2)
        c_text_start_x = col_der_start_x + block_padding_sides
        c_text_start_y_inner = c_content_start_y + block_padding_top
        pdf.set_xy(c_text_start_x, c_text_start_y_inner)
        c_current_y_inner = c_text_start_y_inner

        pdf.set_font(font_to_use, 'B', 12)
        pdf.set_x(c_text_start_x)
        pdf.multi_cell(c_available_internal_width, block_line_height, f"R.U.C.: {c_ruc}", 0, 'L')
        c_current_y_inner = pdf.get_y() + block_row_spacing
        pdf.set_y(c_current_y_inner)

        pdf.set_x(c_text_start_x)
        pdf.multi_cell(c_available_internal_width, block_line_height, doc_type_str.upper(), 0, 'L')
        c_current_y_inner = pdf.get_y() + block_row_spacing
        pdf.set_y(c_current_y_inner)
        pdf.set_font(font_to_use, '', block_font_size)
        pdf.set_x(c_text_start_x)
        pdf.multi_cell(c_available_internal_width, block_line_height, f"No. {c_num_factura}", 0, 'L')
        c_current_y_inner = pdf.get_y() + block_row_spacing
        pdf.set_y(c_current_y_inner)
        pdf.set_x(c_text_start_x)

        label_fecha_auth_text = "FECHA DE\nAUTORIZACIÓN"
        label_ambiente_text = "AMBIENTE:"
        label_emision_text = "EMISIÓN:"

        pdf.set_font(font_to_use, '', block_font_size)
        max_w_label_fecha = 0
        for line in label_fecha_auth_text.split('\n'):
            max_w_label_fecha = max(max_w_label_fecha, pdf.get_string_width(line))
        w_label_ambiente = pdf.get_string_width(label_ambiente_text)
        w_label_emision = pdf.get_string_width(label_emision_text)
        max_etiqueta_ancho_real = max(max_w_label_fecha, w_label_ambiente, w_label_emision)
        padding_entre_etiqueta_y_valor = 2
        calculated_c_col1_width = max_etiqueta_ancho_real + padding_entre_etiqueta_y_valor
        c_col1_width_for_rows = min(calculated_c_col1_width, c_available_internal_width * 0.50)
        c_col2_width_for_rows = c_available_internal_width - c_col1_width_for_rows
        if c_col2_width_for_rows < c_available_internal_width * 0.20:
            c_col2_width_for_rows = c_available_internal_width * 0.20
            c_col1_width_for_rows = c_available_internal_width - c_col2_width_for_rows

        pdf.set_font(font_to_use, '', block_font_size); pdf.set_x(c_text_start_x); pdf.multi_cell(c_available_internal_width, block_line_height, "NÚMERO DE AUTORIZACIÓN", 0, 'L');
        c_current_y_inner = pdf.get_y() + block_row_spacing; pdf.set_y(c_current_y_inner)

        pdf.set_font(font_to_use, '', SMALL_FONT_SIZE); pdf.set_x(c_text_start_x); pdf.multi_cell(c_available_internal_width, block_line_height, c_num_autorizacion, 0, 'L');
        c_current_y_inner = pdf.get_y() + block_row_spacing; pdf.set_y(c_current_y_inner)
        
        # Dibujar Fecha/Ambiente/Emisión usando la función centralizada
        c_current_y_inner = _draw_c_two_col_row(pdf, label_fecha_auth_text, c_fecha_autorizacion_fmt, c_current_y_inner, c_text_start_x, c_col1_width_for_rows, c_col2_width_for_rows, block_line_height, block_row_spacing, font_to_use, block_font_size)
        c_current_y_inner = _draw_c_two_col_row(pdf, label_ambiente_text, c_ambiente_str, c_current_y_inner, c_text_start_x, c_col1_width_for_rows, c_col2_width_for_rows, block_line_height, block_row_spacing, font_to_use, block_font_size)
        c_current_y_inner = _draw_c_two_col_row(pdf, label_emision_text, c_emision_str, c_current_y_inner, c_text_start_x, c_col1_width_for_rows, c_col2_width_for_rows, block_line_height, block_row_spacing, font_to_use, block_font_size)

        pdf.set_font(font_to_use, '', block_font_size); pdf.set_x(c_text_start_x); pdf.multi_cell(c_available_internal_width, block_line_height, "CLAVE DE ACCESO", 0, 'L'); 
        c_current_y_inner = pdf.get_y() + 0.5; pdf.set_y(c_current_y_inner)

        barcode_buffer = None; barcode_w_mm = 0
        if BARCODE_SUPPORT and c_clave_acceso:
            try:
                code128_cls = barcode.get_barcode_class('code128') 
                writer_options = {'module_height': BARCODE_HEIGHT_CONST, 'write_text': False, 'quiet_zone': 1}
                barcode_buffer = io.BytesIO()
                code128_cls(c_clave_acceso, writer=ImageWriter()).write(barcode_buffer, options=writer_options)
                barcode_buffer.seek(0)
                barcode_w_mm = c_available_internal_width
            except Exception as bc_err:
                logger.warning(f"Al generar barcode: {bc_err}"); barcode_buffer = None

        if barcode_buffer:
            barcode_x = c_text_start_x
            pdf.image(barcode_buffer, x=barcode_x, y=c_current_y_inner, w=barcode_w_mm, h=BARCODE_HEIGHT_CONST, type='PNG')
            c_current_y_inner += BARCODE_HEIGHT_CONST + BARCODE_TEXT_SPACING
        else:
            c_current_y_inner += BARCODE_HEIGHT_CONST + BARCODE_TEXT_SPACING

        pdf.set_y(c_current_y_inner)
        pdf.set_font(font_to_use, '', ACCESS_KEY_FONT_SIZE)
        pdf.set_x(c_text_start_x)
        pdf.cell(c_available_internal_width, block_line_height, c_clave_acceso, 0, 1, 'C')
        c_current_y_inner = pdf.get_y()
        c_content_end_y = c_current_y_inner
    except Exception as e_c:
        logger.exception(f"Error dibujando bloque C (Documento): {e_c}")
        c_content_end_y = pdf.get_y()

    b_content_height_actual = (b_content_end_y - b_content_start_y)
    c_content_height_actual = (c_content_end_y - c_content_start_y)
    target_bottom_y = max(b_content_start_y + b_content_height_actual, c_content_start_y + c_content_height_actual)

    b_rect_height_aligned = target_bottom_y - b_content_start_y
    c_rect_height_aligned = target_bottom_y - c_content_start_y

    pdf.rect(col_izq_start_x, b_content_start_y, col_width, b_rect_height_aligned)
    pdf.rect(col_der_start_x, c_content_start_y, col_width, c_rect_height_aligned)

    pdf.set_y(target_bottom_y + 5)
    return pdf.get_y()

def _draw_buyer_info_factura(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str) -> float:
    buyer_section_start_y = pdf.get_y()
    buyer_padding = 2
    buyer_line_height = BASE_LINE_HEIGHT + 1.5
    buyer_font_size = BASE_FONT_SIZE
    content_start_x = MARGIN_LEFT + buyer_padding
    content_start_y = buyer_section_start_y + buyer_padding
    current_y = content_start_y
    page_width_available = pdf.w - MARGIN_LEFT - MARGIN_RIGHT
    content_width_available = page_width_available - (buyer_padding * 2)

    buyer_razon_social = _safe_get(invoice_data, ['comprador', 'razon_social'], '')
    buyer_identificacion = _safe_get(invoice_data, ['comprador', 'identificacion'], '')
    doc_fecha_emision = _safe_get(invoice_data, ['factura_info', 'fecha_emision'], '')

    def draw_buyer_line(label, value, y_pos):
        pdf.set_xy(content_start_x, y_pos)
        pdf.set_font(font_to_use, '', buyer_font_size)
        label_text = label + " "
        label_width = pdf.get_string_width(label_text)
        pdf.cell(label_width, buyer_line_height, label_text, 0, 0, 'L')

        pdf.set_font(font_to_use, '', buyer_font_size)
        value_width = content_width_available - label_width
        if value_width < 10: value_width = 10
        pdf.multi_cell(value_width, buyer_line_height, value, 0, 'L')
        y_after_multi_cell = pdf.get_y()

        if pdf.get_x() > content_start_x :
             y_after = max(y_pos + buyer_line_height, y_after_multi_cell)
        else:
             y_after = y_after_multi_cell
        return y_after

    current_y = draw_buyer_line("Razón Social / Nombres y Apellidos:", buyer_razon_social, current_y)
    current_y = draw_buyer_line("Identificación:", buyer_identificacion, current_y)

    buyer_placa = _safe_get(invoice_data, ['info_adicional', 'placa'], '') 
    buyer_guia = _safe_get(invoice_data, ['doc_especifico', 'guia_remision'], '') 
    y_before_row3 = current_y
    pdf.set_y(y_before_row3)
    width_fecha_part = content_width_available * 0.40
    width_placa_part = content_width_available * 0.30
    width_guia_part = content_width_available - width_fecha_part - width_placa_part

    pdf.set_x(content_start_x); pdf.set_font(font_to_use, '', buyer_font_size); label_fecha = "Fecha Emisión:"; label_fecha_width = pdf.get_string_width(label_fecha + " "); pdf.cell(label_fecha_width, buyer_line_height, label_fecha, 0, 0, 'L'); pdf.set_font(font_to_use, '', buyer_font_size); value_fecha_width = width_fecha_part - label_fecha_width; pdf.cell(value_fecha_width, buyer_line_height, doc_fecha_emision, 0, 0, 'L')
    x_placa = content_start_x + width_fecha_part; pdf.set_xy(x_placa, y_before_row3); pdf.set_font(font_to_use, '', buyer_font_size); label_placa = "Placa / Matrícula:"; label_placa_width = pdf.get_string_width(label_placa + " "); pdf.cell(label_placa_width, buyer_line_height, label_placa, 0, 0, 'L'); pdf.set_font(font_to_use, '', buyer_font_size); value_placa_width = width_placa_part - label_placa_width; pdf.cell(value_placa_width, buyer_line_height, buyer_placa, 0, 0, 'L')
    x_guia = content_start_x + width_fecha_part + width_placa_part; pdf.set_xy(x_guia, y_before_row3); pdf.set_font(font_to_use, '', buyer_font_size); label_guia = "Guía Remisión:"; label_guia_width = pdf.get_string_width(label_guia + " "); pdf.cell(label_guia_width, buyer_line_height, label_guia, 0, 0, 'L'); pdf.set_font(font_to_use, '', buyer_font_size); value_guia_width = width_guia_part - label_guia_width; pdf.cell(value_guia_width, buyer_line_height, buyer_guia, 0, 0, 'L')
    current_y = y_before_row3 + buyer_line_height; pdf.set_y(current_y)

    content_end_y = current_y
    rect_height = (content_end_y - buyer_section_start_y)
    pdf.rect(MARGIN_LEFT, buyer_section_start_y, page_width_available, rect_height)
    pdf.set_y(buyer_section_start_y + rect_height + 5)
    return pdf.get_y()

def _define_table_columns_factura(page_width: float, pdf: InvoicePDF, invoice_data: Dict[str, Any]) -> Tuple[List[float], List[str], List[str]]:
    TABLE_FONT_SIZE = 7
    padding_col = 2

    pdf.set_font(pdf._font_name, '', TABLE_FONT_SIZE)
    max_w_unit_header = pdf.get_string_width("Unitario"); max_w_subsidio_header = pdf.get_string_width("Subsidio")
    max_w_psinsub_header = pdf.get_string_width("sin Sub."); max_w_dcto_header = pdf.get_string_width("Descuento")
    max_w_total_header = pdf.get_string_width("Total")
    max_w_unit_data = 0; max_w_subsidio_data = 0; max_w_psinsub_data = 0; max_w_dcto_data = 0; max_w_total_data = 0
    detalles_list_calc = _safe_get(invoice_data, ['detalles'], [])
    for item in detalles_list_calc:
        if not isinstance(item, dict): continue
        detalles_adicionales = item.get('detalles_adicionales', {});
        try: valor_subsidio_item = float(detalles_adicionales.get('valorSubsidio', '0.0'))
        except: valor_subsidio_item = 0.0
        try: precio_sin_subsidio_item = float(detalles_adicionales.get('precioSinSubsidio', item.get('precio_unitario', 0.0)))
        except: precio_sin_subsidio_item = float(item.get('precio_unitario', 0.0))
        str_unit = _format_currency_pdf(item.get('precio_unitario')); str_subsidio = _format_currency_pdf(valor_subsidio_item)
        str_psinsub = _format_currency_pdf(precio_sin_subsidio_item); str_dcto = _format_currency_pdf(item.get('descuento'))
        str_total = _format_currency_pdf(item.get('precio_total_sin_impuesto'))
        max_w_unit_data = max(max_w_unit_data, pdf.get_string_width(str_unit)); max_w_subsidio_data = max(max_w_subsidio_data, pdf.get_string_width(str_subsidio))
        max_w_psinsub_data = max(max_w_psinsub_data, pdf.get_string_width(str_psinsub)); max_w_dcto_data = max(max_w_dcto_data, pdf.get_string_width(str_dcto))
        max_w_total_data = max(max_w_total_data, pdf.get_string_width(str_total))
    required_w_unit = max(max_w_unit_header, max_w_unit_data); required_w_subsidio = max(max_w_subsidio_header, max_w_subsidio_data)
    required_w_psinsub = max(max_w_psinsub_header, max_w_psinsub_data); required_w_dcto = max(max_w_dcto_header, max_w_dcto_data)
    required_w_total = max(max_w_total_header, max_w_total_data)
    min_common_width_calc = max(required_w_unit, required_w_subsidio, required_w_psinsub, required_w_dcto, required_w_total) + padding_col

    w_cod_pri = page_width * 0.0707; w_cod_aux = page_width * 0.0707; w_cant = page_width * 0.0707
    common_width = min_common_width_calc if min_common_width_calc > 0 else page_width * 0.06
    w_unit_orig = common_width; w_unit_part1 = w_unit_orig / 2; w_unit_part2 = w_unit_orig / 2
    w_subsidio = common_width; w_p_sin_sub = common_width; w_dcto = common_width; w_total = common_width
    fixed_width_sum = w_cod_pri + w_cod_aux + w_cant + w_unit_orig + w_subsidio + w_p_sin_sub + w_dcto + w_total
    remaining_width = page_width - fixed_width_sum
    w_desc = remaining_width * 0.60 if remaining_width > 0 else page_width * 0.20
    w_det_adic = remaining_width * 0.40 if remaining_width > 0 else page_width * 0.13

    column_widths = [w_cod_pri, w_cod_aux, w_cant, w_desc, w_det_adic, w_unit_part1, w_unit_part2, w_subsidio, w_p_sin_sub, w_dcto, w_total]
    header_texts = ["Cod.\nPrincipal", "Cod.\nAuxiliar", "Cantidad", "Descripción", "Detalle\nAdicional", "Precio\nUnitario", "", "Subsidio", "Precio\nsin Sub.", "Descuento", "Precio\nTotal"]
    body_alignments = ['C', 'C', 'C', 'L', 'L', 'R', 'R', 'R', 'R', 'R', 'R']
    return column_widths, header_texts, body_alignments

def _calculate_row_height_factura(pdf: InvoicePDF, texts: List[str], widths: List[float], line_height: float, padding_after: float, font_to_use: str, is_summary: bool = False, is_header: bool = False, is_detail: bool = False) -> float:
    TABLE_FONT_SIZE = 7
    if is_summary:
        return SUMMARY_TABLE_LINE_HEIGHT + padding_after

    max_lines = 1
    current_x_sim = MARGIN_LEFT
    start_y_sim = pdf.get_y()
    current_font_family = pdf.font_family
    current_font_style = pdf.font_style
    current_font_size = pdf.font_size_pt
    pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
    num_cols = len(widths)

    for i in range(num_cols):
        current_text_for_multicell = texts[i] if i < len(texts) else ''
        current_width_for_multicell = widths[i] if widths[i] is not None else 0

        is_factura_header_fusion = is_header and len(widths) == 11 and i == 5
        is_factura_header_skip = is_header and len(widths) == 11 and i == 6
        is_factura_detail_precio_unitario_skip = is_detail and len(widths) == 11 and i == 6

        effective_width_for_call: float
        text_to_render_for_call: str

        if is_factura_header_fusion:
            effective_width_for_call = widths[i] + widths[i+1]
            text_to_render_for_call = texts[i] 
            align_for_call = 'C'
            
            pdf.set_xy(current_x_sim, start_y_sim)
            try:
                lines = pdf.multi_cell(effective_width_for_call, line_height, str(text_to_render_for_call), border=0, align=align_for_call, split_only=True, max_line_height=line_height)
                max_lines = max(max_lines, len(lines))
            except (ValueError, TypeError):
                max_lines = max(max_lines, 1)
            current_x_sim += effective_width_for_call 
            continue 
        elif is_factura_header_skip or is_factura_detail_precio_unitario_skip: 
            continue 
        else:
            effective_width_for_call = current_width_for_multicell
            text_to_render_for_call = current_text_for_multicell
            align_for_call = 'L' 
            
            pdf.set_xy(current_x_sim, start_y_sim)
            try:
                lines = pdf.multi_cell(effective_width_for_call, line_height, str(text_to_render_for_call) if text_to_render_for_call is not None else '', border=0, align=align_for_call, split_only=True, max_line_height=line_height)
                max_lines = max(max_lines, len(lines))
            except (ValueError, TypeError):
                max_lines = max(max_lines, 1)
            current_x_sim += effective_width_for_call 

    pdf.set_font(current_font_family, current_font_style, current_font_size)
    pdf.set_y(start_y_sim)

    if is_header: final_padding = 0.5
    elif is_detail: final_padding = padding_after * 2
    else: final_padding = padding_after
    return (max_lines * line_height) + final_padding

def _draw_table_row_factura(pdf: InvoicePDF, texts: List[str], widths: List[float], line_height: float, row_height: float, start_y: float, font_to_use: str, body_alignments: List[str], is_header: bool = False, is_summary_row: bool = False):
    TABLE_FONT_SIZE = 7
    is_detail_row = not is_header and not is_summary_row
    
    if is_detail_row: 
        logger.info(f"_draw_table_row_factura (DETALLE): texts={texts}, row_height={row_height}, start_y={start_y}")

    row_bottom_y = start_y + row_height
    num_cols = len(widths)
    table_right_edge = pdf.w - MARGIN_RIGHT

    if is_summary_row: 
        if len(widths) == 11: 
            label = texts[0]; value = texts[1]
            label_width_merged = sum(widths[7:10]); value_width = widths[10]
            label_x = MARGIN_LEFT + sum(widths[0:7]); value_x = label_x + label_width_merged
            label_padding_left = 1; value_padding_left = 1
            pdf.set_font(font_to_use, '', SUMMARY_TABLE_FONT_SIZE)
            pdf.set_xy(label_x + label_padding_left, start_y)
            pdf.cell(label_width_merged - label_padding_left, row_height, label, border=0, align='L', ln=0)
            pdf.set_xy(value_x + value_padding_left, start_y)
            pdf.cell(value_width - value_padding_left, row_height, value, border=0, align='R')
    else: 
        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        current_x = MARGIN_LEFT
        for i in range(num_cols):
            if widths[i] is None: continue
            width = widths[i]; text = texts[i] if i < len(texts) else ''

            is_factura_header_fusion = is_header and len(widths) == 11 and i == 5
            is_factura_detail_precio_unitario_cell = is_detail_row and len(widths) == 11 and i == 5
            is_factura_header_skip = is_header and len(widths) == 11 and i == 6
            is_factura_detail_precio_unitario_skip = is_detail_row and len(widths) == 11 and i == 6

            if is_factura_header_fusion:
                merged_width = widths[i] + widths[i+1]
                pdf.set_xy(current_x, start_y)
                pdf.multi_cell(merged_width, line_height, str(text), border=0, align='C', ln=3, fill=False, max_line_height=line_height)
                current_x += merged_width; pdf.set_y(start_y); continue
            elif is_factura_detail_precio_unitario_cell:
                merged_width = widths[i] + widths[i+1]
                text_to_draw = texts[i]
                cell_align = body_alignments[i] if i < len(body_alignments) else 'L'
                pdf.set_xy(current_x, start_y)
                pdf.multi_cell(merged_width, line_height, str(text_to_draw), border=0, align=cell_align, ln=3, fill=False, max_line_height=line_height)
                current_x += merged_width; pdf.set_y(start_y); continue
            elif is_factura_header_skip or is_factura_detail_precio_unitario_skip:
                continue

            cell_align = 'C' if is_header else (body_alignments[i] if i < len(body_alignments) else 'L')
            pdf.set_xy(current_x, start_y)
            pdf.multi_cell(width, line_height, str(text), border=0, align=cell_align, ln=3, fill=False, max_line_height=line_height)
            current_x += width; pdf.set_y(start_y) 

    if is_summary_row and len(widths) == 11:
        start_x_summary_area = MARGIN_LEFT + sum(widths[0:7])
        pdf.line(start_x_summary_area, row_bottom_y, table_right_edge, row_bottom_y)
    elif not is_summary_row:
        pdf.line(MARGIN_LEFT, row_bottom_y, table_right_edge, row_bottom_y)

    if is_summary_row and len(widths) == 11:
        start_x_summary_labels = MARGIN_LEFT + sum(widths[0:7])
        start_x_summary_value = MARGIN_LEFT + sum(widths[0:10])
        end_x_summary_value = table_right_edge
        pdf.line(start_x_summary_labels, start_y, start_x_summary_labels, row_bottom_y)
        pdf.line(start_x_summary_value, start_y, start_x_summary_value, row_bottom_y)
        pdf.line(end_x_summary_value, start_y, end_x_summary_value, row_bottom_y)
    elif not is_summary_row:
        current_x_border = MARGIN_LEFT
        pdf.line(current_x_border, start_y, current_x_border, row_bottom_y)
        for i in range(num_cols):
            if widths[i] is None: continue
            current_x_border += widths[i]
            draw_this_vertical_line = True
            if len(widths) == 11 and i == 5: draw_this_vertical_line = False 
            if i == num_cols - 1 or draw_this_vertical_line:
                 pdf.line(current_x_border, start_y, current_x_border, row_bottom_y)

    if not is_summary_row:
        pdf.set_y(row_bottom_y)

def _prepare_detail_row_data_factura(item: Dict[str, Any]) -> List[str]:
    detalles_adicionales = item.get('detalles_adicionales', {});
    detalle_adicional_texto = detalles_adicionales.get('detalle1', detalles_adicionales.get('Detalle1', ''));
    if not detalle_adicional_texto and len(detalles_adicionales) == 1: detalle_adicional_texto = list(detalles_adicionales.values())[0]
    try: valor_subsidio_item = float(detalles_adicionales.get('valorSubsidio', '0.0'))
    except: valor_subsidio_item = 0.0
    try: precio_sin_subsidio_item = float(detalles_adicionales.get('precioSinSubsidio', item.get('precio_unitario', 0.0)))
    except: precio_sin_subsidio_item = float(item.get('precio_unitario', 0.0))
    return [
        _safe_get(item, ['codigo_principal']), _safe_get(item, ['codigo_auxiliar']),
        _format_integer_pdf(item.get('cantidad'), default=0), _safe_get(item, ['descripcion']),
        detalle_adicional_texto, _format_currency_pdf(item.get('precio_unitario')), "", 
        _format_currency_pdf(valor_subsidio_item), _format_currency_pdf(precio_sin_subsidio_item),
        _format_currency_pdf(item.get('descuento', 0)), _format_currency_pdf(item.get('precio_total_sin_impuesto', 0))
    ]

def _draw_info_adicional_factura(
    pdf: InvoicePDF, 
    invoice_data: Dict[str, Any], 
    font_to_use: str, start_y: float, 
    column_widths: List[float] # Se usa para determinar el ancho de la sección de info adicional
) -> float:
    TABLE_FONT_SIZE = 7
    ROW_V_PADDING_AFTER = 1.0
    info_adicional_data = _safe_get(invoice_data, ['info_adicional'], {})
    info_fields_to_draw = {k: v for k, v in info_adicional_data.items() if v and str(v).strip()}
    current_info_y = start_y
    page_total_content_width = pdf.w - MARGIN_LEFT - MARGIN_RIGHT
    spacing_between_sections = 5 # mm
    min_section_width = 20 # mm

    info_section_width = 0
    asesor_section_width = 0
    asesor_section_start_x = 0
    has_asesor_info = False # Forzar a que no haya información del asesor

    # Si no hay info del asesor, la info adicional toma un ancho predeterminado
    # (basado en la estructura de la tabla de detalles si column_widths está disponible y es relevante)
    if len(column_widths) == 11: # Asumiendo que column_widths es para la tabla de detalles principal
        # Info adicional podría tomar el ancho de las primeras N columnas de la tabla de detalles
        info_section_width = sum(column_widths[0:6]) # Ejemplo: Cod, Cant, Desc, DetAdic, P.Unit
    else: 
        info_section_width = page_total_content_width * 0.7 # Un ancho por defecto
    asesor_section_width = 0 # No hay sección de asesor


    if info_section_width <=0: # Asegurar que la sección de info tenga algo de ancho si es la única
        info_section_width = page_total_content_width
        has_asesor_info = False # No se puede dibujar asesor si info toma todo el espacio
        asesor_section_width = 0

    # --- Dibujar Sección de Información Adicional ---
    info_header_height = SUMMARY_TABLE_LINE_HEIGHT + ROW_V_PADDING_AFTER
    pdf.set_font(font_to_use, '', SUMMARY_TABLE_FONT_SIZE)
    pdf.set_xy(MARGIN_LEFT, current_info_y)
    pdf.cell(info_section_width, info_header_height, "Información Adicional", border=1, align='C') # Borde para el título
    
    y_after_info_header = current_info_y + info_header_height
    y_for_info_content = y_after_info_header

    def draw_info_field_row(y_pos, key, value, width):
        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        label_text = f"{key.replace('_', ' ').capitalize()}: "; label_width = pdf.get_string_width(label_text) + 1

        value_width_calc = width - label_width - 2
        if value_width_calc < 5: value_width_calc = 5 

        pdf.set_xy(MARGIN_LEFT + 1 + label_width, y_pos + 0.5) 
        lines_value = pdf.multi_cell(value_width_calc, LINE_HEIGHT, str(value), split_only=True, max_line_height=LINE_HEIGHT)
        cell_height_value = max(LINE_HEIGHT, len(lines_value) * LINE_HEIGHT) + 1

        pdf.set_xy(MARGIN_LEFT + 1, y_pos + 0.5) 
        lines_label = pdf.multi_cell(label_width, LINE_HEIGHT, label_text, split_only=True, max_line_height=LINE_HEIGHT)
        cell_height_label = max(LINE_HEIGHT, len(lines_label) * LINE_HEIGHT) + 1
        
        cell_height = max(cell_height_value, cell_height_label)

        pdf.set_xy(MARGIN_LEFT + 1, y_pos + (cell_height - (len(lines_label) * LINE_HEIGHT))/2 ); pdf.multi_cell(label_width, LINE_HEIGHT, label_text, 0, 'L')
        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        value_width_draw = width - label_width - 2; value_x_draw = MARGIN_LEFT + label_width + 1
        pdf.set_xy(value_x_draw, y_pos + (cell_height - (len(lines_value) * LINE_HEIGHT))/2); pdf.multi_cell(value_width_draw, LINE_HEIGHT, str(value), 0, 'L')

        pdf.line(MARGIN_LEFT, y_pos, MARGIN_LEFT, y_pos + cell_height) 
        pdf.line(MARGIN_LEFT + width, y_pos, MARGIN_LEFT + width, y_pos + cell_height) 
        return y_pos + cell_height

    if info_fields_to_draw:
        for key, value in info_fields_to_draw.items():
             y_for_info_content = draw_info_field_row(y_for_info_content, key, value, info_section_width)
        pdf.line(MARGIN_LEFT, y_for_info_content, MARGIN_LEFT + info_section_width, y_for_info_content) 
    else: # Si no hay campos, solo dibujar la línea inferior del área de contenido vacía
         pdf.line(MARGIN_LEFT, y_for_info_content, MARGIN_LEFT + info_section_width, y_for_info_content)

    y_after_info_adicional_content = y_for_info_content
    
    # --- Sección del Asesor ---
    # Lógica del asesor eliminada
    final_y_position = y_after_info_adicional_content
    return final_y_position


def _draw_payment_section_factura(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str, start_y: float, column_widths: List[float]) -> float:
    TABLE_FONT_SIZE = 7; ROW_V_PADDING_AFTER = 1.0
    payment_section_start_y = start_y + LINE_HEIGHT 
    payments = _safe_get(invoice_data, ['factura_info', 'pagos'], [])
    payment_desc_combined = ""; payment_val_combined = ""

    if payments:
        desc_list = []; val_list = []
        for pago in payments:
            code = _safe_get(pago, ['forma_pago'])
            description = PAYMENT_METHOD_MAP.get(code, f"Código {code}")
            value = _format_currency_pdf(_safe_get(pago, ['total'], 0.0))
            desc_list.append(f"{code} - {description}"); val_list.append(value)
        payment_desc_combined = "\n".join(desc_list); payment_val_combined = "\n".join(val_list)
    else: payment_desc_combined = "N/A"; payment_val_combined = "N/A"

    label_height = SUMMARY_TABLE_LINE_HEIGHT + ROW_V_PADDING_AFTER
    if len(column_widths) == 11: 
        total_payment_section_width = sum(column_widths[0:6])
    else: 
        total_payment_section_width = (pdf.w - MARGIN_LEFT - MARGIN_RIGHT) * 0.7
    
    width_ad = total_payment_section_width * 0.70
    width_e = total_payment_section_width * 0.30

    pdf.set_font(font_to_use, '', TABLE_FONT_SIZE); temp_y_pay = pdf.get_y(); temp_x_pay = pdf.get_x()
    pdf.set_xy(MARGIN_LEFT + 1, temp_y_pay)
    try: lines_desc = pdf.multi_cell(width_ad - 2, TABLE_LINE_HEIGHT, payment_desc_combined, split_only=True, max_line_height=TABLE_LINE_HEIGHT); num_lines_desc = max(1, len(lines_desc))
    except: num_lines_desc = 1
    value_height_desc = (num_lines_desc * TABLE_LINE_HEIGHT) + ROW_V_PADDING_AFTER
    pdf.set_xy(MARGIN_LEFT + width_ad + 1, temp_y_pay)
    try: lines_val = pdf.multi_cell(width_e - 2, TABLE_LINE_HEIGHT, payment_val_combined, split_only=True, max_line_height=TABLE_LINE_HEIGHT); num_lines_val = max(1, len(lines_val))
    except: num_lines_val = 1
    value_height_val = (num_lines_val * TABLE_LINE_HEIGHT) + ROW_V_PADDING_AFTER
    pdf.set_xy(temp_x_pay, temp_y_pay); value_row_height = max(value_height_desc, value_height_val)
    total_payment_section_height = label_height + value_row_height

    if payment_section_start_y + total_payment_section_height > pdf.h - MARGIN_BOTTOM:
        pdf.add_page(); payment_section_start_y = pdf.get_y()

    label_row_y = payment_section_start_y
    pdf.set_font(font_to_use, '', SUMMARY_TABLE_FONT_SIZE)
    pdf.set_xy(MARGIN_LEFT, label_row_y); pdf.cell(width_ad, label_height, "Forma de Pago", border=1, align='L')
    pdf.set_xy(MARGIN_LEFT + width_ad, label_row_y); pdf.cell(width_e, label_height, "Valor", border=1, align='L')

    value_row_y = label_row_y + label_height
    pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
    pdf.rect(MARGIN_LEFT, value_row_y, width_ad, value_row_height)
    pdf.set_xy(MARGIN_LEFT + 1, value_row_y + (value_row_height - (num_lines_desc * TABLE_LINE_HEIGHT)) / 2)
    pdf.multi_cell(width_ad - 2, TABLE_LINE_HEIGHT, payment_desc_combined, border=0, align='L', max_line_height=TABLE_LINE_HEIGHT)
    pdf.rect(MARGIN_LEFT + width_ad, value_row_y, width_e, value_row_height)
    pdf.set_xy(MARGIN_LEFT + width_ad + 1, value_row_y + (value_row_height - (num_lines_val * TABLE_LINE_HEIGHT)) / 2)
    pdf.multi_cell(width_e - 2, TABLE_LINE_HEIGHT, payment_val_combined, border=0, align='R', max_line_height=TABLE_LINE_HEIGHT)
    return value_row_y + value_row_height

def _draw_summary_section_factura(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str, start_y: float, column_widths: List[float], header_texts: List[str], body_alignments: List[str]) -> float:
    ROW_V_PADDING_AFTER = 1.0
    totals = _calculate_totals(invoice_data) 
    summary_lines_data = [
        ("SUBTOTAL IVA 15%", totals["subtotal_iva_15"]), ("SUBTOTAL 12%", totals["subtotal_iva_12"]),
        ("SUBTOTAL IVA DIFERENCIADO", totals["subtotal_iva_diferenciado"]), ("SUBTOTAL IVA 5%", totals["subtotal_iva_5"]),
        ("SUBTOTAL IVA 0%", totals["subtotal_iva_0"]), ("SUBTOTAL NO OBJETO DE IVA", totals["subtotal_no_objeto"]),
        ("SUBTOTAL EXENTO DE IVA", totals["subtotal_exento"]), ("SUBTOTAL SIN IMPUESTOS", totals["total_sin_impuestos"]),
        ("TOTAL DESCUENTO", totals["total_descuento"]), ("ICE", totals["total_ice"]),
        ("IVA", totals["iva_15"] + totals["iva_12"] + totals["iva_5"] + totals["iva_diferenciado"]),
        ("TOTAL DEVOLUCION IVA", totals["total_devolucion_iva"]), ("IRBPNR", totals["total_irbpnr"]),
        ("PROPINA", totals["propina"]), ("VALOR TOTAL", totals["importe_total"]),
        ("VALOR TOTAL SIN SUBSIDIO", totals["valor_total_sin_subsidio"]),
        ("AHORRO POR SUBSIDIO:", totals["total_subsidio_calculado"])
    ]

    summary_start_y_for_loop = start_y
    max_y_for_sections = pdf.h - MARGIN_BOTTOM - 5

    for label, value in summary_lines_data:
        is_always_shown = label.upper() in ["SUBTOTAL SIN IMPUESTOS", "VALOR TOTAL", "SUBTOTAL IVA 15%"]
        show_row = (value != 0 or is_always_shown or label == "PROPINA" or "AHORRO POR SUBSIDIO" in label)

        if show_row:
            current_row_start_y = summary_start_y_for_loop
            current_row_height = SUMMARY_TABLE_LINE_HEIGHT + ROW_V_PADDING_AFTER

            if current_row_start_y + current_row_height > max_y_for_sections:
                pdf.add_page()
                header_start_y_new = pdf.get_y()
                header_height_new = _calculate_row_height_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, is_header=True)
                pdf.line(MARGIN_LEFT, header_start_y_new, pdf.w - MARGIN_RIGHT, header_start_y_new)
                _draw_table_row_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height_new, header_start_y_new, font_to_use, [], is_header=True)
                summary_start_y_for_loop = pdf.get_y(); current_row_start_y = summary_start_y_for_loop

            summary_texts = [label, _format_summary_value(value)]
            _draw_table_row_factura(pdf, summary_texts, column_widths, SUMMARY_TABLE_LINE_HEIGHT, current_row_height, current_row_start_y, font_to_use, body_alignments, is_summary_row=True)
            summary_start_y_for_loop += current_row_height

            if label == "VALOR TOTAL": 
                blank_row_start_y = summary_start_y_for_loop
                blank_row_height = SUMMARY_TABLE_LINE_HEIGHT + ROW_V_PADDING_AFTER
                if blank_row_start_y + blank_row_height > max_y_for_sections:
                     pdf.add_page()
                     header_start_y_new = pdf.get_y()
                     header_height_new = _calculate_row_height_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, is_header=True)
                     pdf.line(MARGIN_LEFT, header_start_y_new, pdf.w - MARGIN_RIGHT, header_start_y_new)
                     _draw_table_row_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height_new, header_start_y_new, font_to_use, [], is_header=True)
                     blank_row_start_y = pdf.get_y(); summary_start_y_for_loop = blank_row_start_y
                if len(column_widths) == 11: 
                    row_bottom_y_blank = blank_row_start_y + blank_row_height
                    start_x_summary_area_blank = MARGIN_LEFT + sum(column_widths[0:7])
                    pdf.line(start_x_summary_area_blank, row_bottom_y_blank, pdf.w - MARGIN_RIGHT, row_bottom_y_blank) 
                summary_start_y_for_loop += blank_row_height
    return summary_start_y_for_loop


def generate_invoice_pdf(invoice_data: Dict[str, Any], output_folder: str) -> str: 
    """
    Genera el PDF específicamente para una Factura.
    """
    numero_autorizacion = _safe_get(invoice_data, ['numero_autorizacion'], '')
    fecha_autorizacion_dt = _safe_get(invoice_data, ['fecha_autorizacion_dt'])
    timestamp = fecha_autorizacion_dt.strftime('%Y%m%d%H%M%S') if isinstance(fecha_autorizacion_dt, datetime) else datetime.now().strftime('%Y%m%d%H%M%S%f')
    
    identificador_comprador = _safe_get(invoice_data, ['comprador', 'identificacion'], '0'*13)
    nombre_archivo_base = f"FAC_{identificador_comprador}_{timestamp}"
    
    pdf_filename_base = numero_autorizacion if numero_autorizacion else f"ERROR_SIN_AUT_{nombre_archivo_base}"
    pdf_filename = f"{pdf_filename_base}.pdf"
    pdf_path = os.path.join(output_folder, pdf_filename)
    
    font_to_use = FONT_FALLBACK 
    pdf = None

    # Lógica del asesor eliminada

    try:
        pdf = InvoicePDF('P', 'mm', 'A4')
        try:
            font_to_use = FONT_FAMILY_NAME 
            pdf.set_doc_font(font_to_use)
        except Exception as font_error:
            logger.warning(f"Al cargar fuente para Factura ({pdf_filename}): {font_error}")
            font_to_use = FONT_FALLBACK 
            pdf.set_doc_font(font_to_use)
        
        pdf.set_auto_page_break(auto=True, margin=MARGIN_BOTTOM)
        pdf.set_margins(MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT)
        pdf.add_page()
        pdf.alias_nb_pages()
        page_width = pdf.w - MARGIN_LEFT - MARGIN_RIGHT
        if page_width <= 0: raise ValueError("Ancho de página inválido para Factura.")
        pdf.set_text_color(*COLOR_BLACK)

        current_y = _draw_header_factura(pdf, invoice_data, font_to_use); pdf.set_y(current_y)
        current_y = _draw_buyer_info_factura(pdf, invoice_data, font_to_use); pdf.set_y(current_y)

        column_widths, header_texts, body_alignments = _define_table_columns_factura(page_width, pdf, invoice_data)
        
        header_start_y = pdf.get_y()
        header_height = _calculate_row_height_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, is_header=True)
        pdf.line(MARGIN_LEFT, header_start_y, pdf.w - MARGIN_RIGHT, header_start_y) 
        _draw_table_row_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height, header_start_y, font_to_use, body_alignments, is_header=True)

        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        detalles_list = _safe_get(invoice_data, ['detalles'], [])
        
        logger.debug(f"Factura - Iniciando bucle de detalles. Total detalles en XML: {len(detalles_list)}")
        for item in detalles_list:
            if not isinstance(item, dict):
                logger.warning(f"Factura - Item en detalles_list no es un diccionario: {item}")
                continue
            
            logger.debug(f"Factura - Procesando item de detalle XML: {item}")
            data_row_texts = _prepare_detail_row_data_factura(item)
            logger.info(f"Factura - Fila de detalle preparada para dibujar (data_row_texts): {data_row_texts}")
            
            current_row_start_y = pdf.get_y()
            natural_row_height = _calculate_row_height_factura(pdf, data_row_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, is_detail=True)
            current_row_height = max(natural_row_height, header_height) 
            logger.info(f"Factura - Altura calculada para fila de detalle: natural={natural_row_height}, final={current_row_height}")
            
            estimated_space_needed = 60 
            if current_row_start_y + current_row_height + estimated_space_needed > pdf.h - MARGIN_BOTTOM:
                pdf.add_page()
                header_start_y_new = pdf.get_y()
                header_height_new = _calculate_row_height_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, is_header=True)
                pdf.line(MARGIN_LEFT, header_start_y_new, pdf.w - MARGIN_RIGHT, header_start_y_new)
                _draw_table_row_factura(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height_new, header_start_y_new, font_to_use, body_alignments, is_header=True)
                pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
                current_row_start_y = pdf.get_y(); header_height = header_height_new 
            _draw_table_row_factura(pdf, data_row_texts, column_widths, TABLE_LINE_HEIGHT, current_row_height, current_row_start_y, font_to_use, body_alignments, is_header=False)
            logger.debug(f"Factura - Fila de detalle dibujada. Y después de dibujar: {pdf.get_y()}")

        details_end_y_final = pdf.get_y()
        blank_row_height_sep = _calculate_row_height_factura(pdf, [], [], SUMMARY_TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, is_summary=True)
        bottom_block_start_y = details_end_y_final

        current_info_adic_start_y = bottom_block_start_y + blank_row_height_sep + 1
        
        # Llamada a _draw_info_adicional_factura sin parámetros de asesor
        y_after_info = _draw_info_adicional_factura(pdf, invoice_data, font_to_use, current_info_adic_start_y, column_widths)
        
        y_after_payment = _draw_payment_section_factura(pdf, invoice_data, font_to_use, y_after_info, column_widths)
        y_after_summary = _draw_summary_section_factura(pdf, invoice_data, font_to_use, bottom_block_start_y, column_widths, header_texts, body_alignments)
        final_y_pos = max(y_after_payment, y_after_summary)
        pdf.set_y(final_y_pos)
        pdf.ln(8) 
        
        pdf.output(pdf_path) 
        logger.info(f"PDF de Factura generado: {pdf_filename}")
        return pdf_path

    except FPDFException as e:
        logger.error(f"Error FPDF generando Factura '{pdf_filename}': {e}")
        raise Exception(f"Fallo en PDF Factura ({pdf_filename}): {e}") from e
    except Exception as e:
        logger.exception(f"Error inesperado generando Factura '{pdf_filename}': {e}")
        raise Exception(f"Fallo en PDF Factura ({pdf_filename}): {e}") from e
