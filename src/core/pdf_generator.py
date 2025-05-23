# d:\Datos\Desktop\Asistente Contable\src\core\pdf_generator.py
import os
import sys
from datetime import datetime, timezone 
from typing import Dict, Any, List, Tuple, Optional, TYPE_CHECKING
from fpdf import FPDFException
import logging 
import tempfile 

# Importaciones desde pdf_base.py
from .pdf_base import (
    InvoicePDF, _safe_get, _format_currency_pdf, _format_summary_value, _format_integer_pdf,
    MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM,
    BASE_FONT_SIZE, BASE_LINE_HEIGHT, BODY_FONT_SIZE, TABLE_LINE_HEIGHT,
    LINE_HEIGHT, SMALL_FONT_SIZE, ACCESS_KEY_FONT_SIZE,
    SUMMARY_TABLE_FONT_SIZE, SUMMARY_TABLE_LINE_HEIGHT, TABLE_FONT_SIZE, 
    ROW_V_PADDING_AFTER, 
    COLOR_BLACK, BORDER_THICKNESS_MM, FONT_FAMILY_NAME, FONT_FALLBACK, FONTS_DIR, _calculate_totals,
    PAYMENT_METHOD_MAP, 
    COD_DOC_SUSTENTO_MAP, IMPUESTO_RETENCION_MAP, 
    BARCODE_SUPPORT,
    _parse_fecha_pdf, _draw_c_two_col_row # Importar funciones movidas
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING: 
    from .xml_parser import parse_xml
    from .pdf_invoice_generator import generate_invoice_pdf
    from fpdf import FPDF


if BARCODE_SUPPORT:
    import barcode
    from barcode.writer import ImageWriter
    import io

# --- Funciones de Dibujo Específicas para Otros Documentos ---

def _draw_header_other_docs(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str, doc_type: str) -> float:
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
    pdf.set_xy(col_izq_start_x, col_izq_current_y)
    pdf.set_font(font_to_use, 'B', 25); pdf.set_text_color(255,0,0); pdf.cell(col_width, logo_height, "NO TIENE LOGO", 0, 0, 'C'); pdf.set_text_color(*COLOR_BLACK)

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
        b_agente_ret_num_res = _safe_get(invoice_data, ['emisor', 'agente_retencion_num_res'])
        
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

        if doc_type == "Comprobante de Retención" and b_agente_ret_num_res:
            agente_ret_label = "Agente de Retención Resolución No.:"
            agente_ret_text = f"{agente_ret_label} {str(b_agente_ret_num_res)}"
            pdf.set_x(b_text_start_x)
            pdf.multi_cell(b_single_col_width, block_line_height, agente_ret_text, 0, 'L'); pdf.ln(block_row_spacing)
            b_current_y_inner = pdf.get_y()

        b_content_end_y = b_current_y_inner - block_row_spacing
    except Exception as e_b:
        logger.exception(f"Error dibujando bloque B (Emisor): {e_b}")
        b_content_end_y = pdf.get_y()

    try:
        pdf.set_text_color(*COLOR_BLACK)
        c_ruc = _safe_get(invoice_data, ['emisor', 'ruc'])
        c_num_doc = _safe_get(invoice_data, ['factura_info', 'numero_factura']) 
        c_num_autorizacion = _safe_get(invoice_data, ['numero_autorizacion'])
        c_fecha_autorizacion_fmt = _parse_fecha_pdf(_safe_get(invoice_data, ['fecha_autorizacion']))

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
        pdf.multi_cell(c_available_internal_width, block_line_height, doc_type.upper(), 0, 'L')
        c_current_y_inner = pdf.get_y() + block_row_spacing
        pdf.set_y(c_current_y_inner)

        pdf.set_font(font_to_use, '', block_font_size)
        pdf.set_x(c_text_start_x)
        pdf.multi_cell(c_available_internal_width, block_line_height, f"No. {c_num_doc}", 0, 'L')
        c_current_y_inner = pdf.get_y() + block_row_spacing
        pdf.set_y(c_current_y_inner)

        pdf.set_x(c_text_start_x)
        pdf.multi_cell(c_available_internal_width, block_line_height, "NÚMERO DE AUTORIZACIÓN", 0, 'L')
        c_current_y_inner = pdf.get_y() + block_row_spacing
        pdf.set_y(c_current_y_inner)

        pdf.set_font(font_to_use, '', SMALL_FONT_SIZE)
        pdf.set_x(c_text_start_x)
        pdf.multi_cell(c_available_internal_width, block_line_height, c_num_autorizacion, 0, 'L')
        c_current_y_inner = pdf.get_y() + block_row_spacing
        pdf.set_y(c_current_y_inner)

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
                logger.warning(f"  ADVERTENCIA al generar barcode: {bc_err}"); barcode_buffer = None

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

def _draw_buyer_info_other_docs(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str, doc_type: str) -> float:
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

    if doc_type == "Comprobante de Retención":
        current_y = draw_buyer_line("Fecha Emisión:", doc_fecha_emision, current_y)
    elif doc_type in ["Nota de Débito", "Nota de Crédito"]:
        current_y = draw_buyer_line("Fecha Emisión:", doc_fecha_emision, current_y)
        
        line_separator_padding_nd_nc = 1.5
        current_y += line_separator_padding_nd_nc / 2 
        pdf.line(MARGIN_LEFT, current_y, MARGIN_LEFT + page_width_available, current_y)
        current_y += line_separator_padding_nd_nc 
        pdf.set_y(current_y)

        doc_mod_data = _safe_get(invoice_data, ['doc_modificado'], {})
        cod_doc_mod = doc_mod_data.get('cod_doc', ''); num_doc_mod = doc_mod_data.get('num_doc', ''); fecha_doc_mod = doc_mod_data.get('fecha_emision', '')
        doc_mod_nombre = COD_DOC_SUSTENTO_MAP.get(cod_doc_mod, f"Doc. ({cod_doc_mod})")

        texto_doc_modificado = f"{doc_mod_nombre}: {num_doc_mod}"
        current_y = draw_buyer_line("Comprobante que se modifica:", texto_doc_modificado, current_y)
        current_y = draw_buyer_line("Fecha Emisión (Comp. que modifica):", fecha_doc_mod, current_y)

        razon_modificacion_valor = ""
        if doc_type == "Nota de Crédito":
            motivo = _safe_get(invoice_data, ['doc_especifico', 'motivo'], '')
            if motivo: razon_modificacion_valor = motivo
        elif doc_type == "Nota de Débito":
            detalles_nd = _safe_get(invoice_data, ['detalles'], []) 
            if detalles_nd and isinstance(detalles_nd, list) and len(detalles_nd) > 0:
                primer_motivo = detalles_nd[0]
                if isinstance(primer_motivo, dict):
                    razon_modificacion_valor = primer_motivo.get('descripcion', '') 
        
        if razon_modificacion_valor:
            current_y = draw_buyer_line("Razón de Modificación:", razon_modificacion_valor, current_y)
    elif doc_type == "Liquidación de Compra de Bienes y Prestación de Servicios":
         current_y = draw_buyer_line("Fecha Emisión:", doc_fecha_emision, current_y)

    content_end_y = current_y
    rect_height = (content_end_y - buyer_section_start_y)
    pdf.rect(MARGIN_LEFT, buyer_section_start_y, page_width_available, rect_height)
    pdf.set_y(buyer_section_start_y + rect_height + 5)
    return pdf.get_y()

def _define_table_columns_other_docs(page_width: float, doc_type: str, pdf: InvoicePDF, invoice_data: Dict[str, Any]) -> Tuple[List[float], List[str], List[str]]:
    TABLE_FONT_SIZE = 7
    padding_col = 2

    if doc_type == "Nota de Débito":
        razon_width = page_width * 0.7
        valor_total_width = page_width * 0.3
        valor_subcol_width = valor_total_width / 2
        column_widths = [razon_width, valor_subcol_width, valor_subcol_width]
        header_texts = ["Razón de la Modificación", "VALOR DE LA MODIFICACIÓN", None]
        body_alignments = ['L', 'R', 'R']
    elif doc_type == "Comprobante de Retención":
        pdf.set_font(pdf._font_name, '', TABLE_FONT_SIZE)
        text_padding_horizontal = 2.5; safety_factor = 1.05
        header_text_fecha_sust = "Fecha Emision"; header_text_ej_fiscal = "Ejercicio Fiscal"; header_text_val_ret = "Valor Retenido"
        header_text_impuesto_calc = "Impuesto"; header_text_cod_ret_calc = "Código"
        header_text_base_imp = "Base Imponible\npara la Retención"; header_text_porc_ret = "Porcentaje\nRetención"

        min_w_fecha_sust_text = (pdf.get_string_width(header_text_fecha_sust) * safety_factor) + text_padding_horizontal
        min_w_ej_fiscal_text = (pdf.get_string_width(header_text_ej_fiscal) * safety_factor) + text_padding_horizontal
        min_w_val_ret_text = (pdf.get_string_width(header_text_val_ret) * safety_factor) + text_padding_horizontal
        min_w_impuesto_header_text = (pdf.get_string_width(header_text_impuesto_calc) * safety_factor) + text_padding_horizontal
        min_w_cod_ret_header_text = (pdf.get_string_width(header_text_cod_ret_calc) * safety_factor) + text_padding_horizontal

        w_fecha_sust = min_w_fecha_sust_text; w_ej_fiscal = min_w_ej_fiscal_text; w_val_ret = min_w_val_ret_text
        fixed_widths_sum = w_fecha_sust + w_ej_fiscal + w_val_ret
        remaining_width_for_others = page_width - fixed_widths_sum

        p_comp = 0.10; p_num = 0.14; p_base_imp = 0.14; p_impuesto_orig = 0.10; p_cod_ret_orig = 0.06; p_porc_ret = 0.08
        sum_all_6_props = p_comp + p_num + p_base_imp + p_impuesto_orig + p_cod_ret_orig + p_porc_ret

        w_comp_sust = remaining_width_for_others * (p_comp / sum_all_6_props)
        w_num_sust = remaining_width_for_others * (p_num / sum_all_6_props)
        w_base_imp = remaining_width_for_others * (p_base_imp / sum_all_6_props)
        w_porc_ret = remaining_width_for_others * (p_porc_ret / sum_all_6_props)
        total_width_for_imp_cod = remaining_width_for_others * ((p_impuesto_orig + p_cod_ret_orig) / sum_all_6_props)

        if min_w_impuesto_header_text + min_w_cod_ret_header_text <= total_width_for_imp_cod:
            slack_imp_cod = total_width_for_imp_cod - (min_w_impuesto_header_text + min_w_cod_ret_header_text)
            w_impuesto = min_w_impuesto_header_text + slack_imp_cod / 2
            w_cod_ret = min_w_cod_ret_header_text + slack_imp_cod / 2
        else:
            total_min_for_imp_cod = min_w_impuesto_header_text + min_w_cod_ret_header_text
            if total_min_for_imp_cod > 0:
                w_impuesto = total_width_for_imp_cod * (min_w_impuesto_header_text / total_min_for_imp_cod)
                w_cod_ret = total_width_for_imp_cod - w_impuesto
            else:
                w_impuesto = total_width_for_imp_cod / 2; w_cod_ret = total_width_for_imp_cod / 2

        column_widths = [w_comp_sust, w_num_sust, w_fecha_sust, w_ej_fiscal, w_base_imp, w_impuesto, w_cod_ret, w_porc_ret, w_val_ret]
        header_texts = ["Comprobante", "Número", header_text_fecha_sust, header_text_ej_fiscal, header_text_base_imp, header_text_impuesto_calc, header_text_cod_ret_calc, header_text_porc_ret, header_text_val_ret]
        body_alignments = ['C', 'C', 'C', 'C', 'C', 'C', 'C', 'C', 'C']
    elif doc_type == "Nota de Crédito":
        pdf.set_font(pdf._font_name, '', TABLE_FONT_SIZE)
        page_w = page_width
        w_cod_pri  = page_w * 0.10
        w_cod_aux  = page_w * 0.10
        w_cant     = page_w * 0.08
        w_desc     = page_w * 0.27
        w_det_adic = page_w * 0.15
        w_dcto     = page_w * 0.10
        w_unit     = page_w * 0.10
        current_sum = w_cod_pri + w_cod_aux + w_cant + w_desc + w_det_adic + w_dcto + w_unit
        w_total = page_w - current_sum

        column_widths = [w_cod_pri, w_cod_aux, w_cant, w_desc, w_det_adic, w_dcto, w_unit, w_total]
        header_texts = ["Cod.\nPrincipal", "Cod.\nAuxiliar", "Cantidad", "Descripción", "Detalle\nAdicional", "Descuento", "Precio\nUnitario", "Precio\nTotal"]
        body_alignments = ['C', 'C', 'C', 'L', 'L', 'R', 'R', 'R']
    elif doc_type == "Liquidación de Compra de Bienes y Prestación de Servicios":
        column_widths = [page_width * 0.15, page_width * 0.45, page_width * 0.15, page_width * 0.1, page_width * 0.15]
        header_texts = ["Código", "Descripción", "Cantidad", "P. Unit.", "P. Total"]
        body_alignments = ['C', 'L', 'C', 'R', 'R']
    else: 
        column_widths = [page_width]
        header_texts = ["Información del Documento"]
        body_alignments = ['L']
    return column_widths, header_texts, body_alignments

def _calculate_row_height_other_docs(pdf: InvoicePDF, texts: List[str], widths: List[float], line_height: float, padding_after: float, font_to_use: str, doc_type: str, is_summary: bool = False, is_header: bool = False, is_detail: bool = False) -> float:
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
        text = texts[i] if i < len(texts) else ''
        width = widths[i] if widths[i] is not None else 0

        is_nd_header_fusion = is_header and doc_type == "Nota de Débito" and len(widths) == 3 and i == 1
        is_nd_header_skip = is_header and doc_type == "Nota de Débito" and len(widths) == 3 and i == 2

        if is_nd_header_fusion: 
            merged_width = widths[i] + widths[i+1]
            pdf.set_xy(current_x_sim, start_y_sim)
            try:
                lines = pdf.multi_cell(merged_width, line_height, str(text), border=0, align='C', split_only=True, max_line_height=line_height)
                max_lines = max(max_lines, len(lines))
            except (ValueError, TypeError): max_lines = max(max_lines, 1)
            current_x_sim += merged_width
            continue
        elif is_nd_header_skip: 
            continue

        pdf.set_xy(current_x_sim, start_y_sim)
        try:
            lines = pdf.multi_cell(width, line_height, str(text) if text is not None else '', border=0, align='L', split_only=True, max_line_height=line_height)
            max_lines = max(max_lines, len(lines))
        except (ValueError, TypeError): max_lines = max(max_lines, 1)
        current_x_sim += width

    pdf.set_font(current_font_family, current_font_style, current_font_size)
    pdf.set_y(start_y_sim)

    if is_header: final_padding = 0.5
    elif is_detail: final_padding = padding_after * 2
    else: final_padding = padding_after
    return (max_lines * line_height) + final_padding

def _draw_table_row_other_docs(pdf: InvoicePDF, texts: List[str], widths: List[float], line_height: float, row_height: float, start_y: float, font_to_use: str, doc_type: str, body_alignments: List[str], is_header: bool = False, is_summary_row: bool = False):
    TABLE_FONT_SIZE = 7
    is_detail_row = not is_header and not is_summary_row
    
    if is_detail_row: 
        logger.info(f"_draw_table_row_other_docs (DETALLE): texts={texts}, row_height={row_height}, start_y={start_y}")

    row_bottom_y = start_y + row_height
    num_cols = len(widths)
    table_right_edge = pdf.w - MARGIN_RIGHT

    if not is_summary_row: 
        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        current_x = MARGIN_LEFT
        for i in range(num_cols):
            if widths[i] is None: continue
            width = widths[i]; text = texts[i] if i < len(texts) else ''

            is_nd_header_fusion = is_header and doc_type == "Nota de Débito" and len(widths) == 3 and i == 1
            is_nd_detail_fusion = is_detail_row and doc_type == "Nota de Débito" and len(widths) == 3 and i == 1
            is_nd_header_skip = is_header and doc_type == "Nota de Débito" and len(widths) == 3 and i == 2
            is_nd_detail_skip = is_detail_row and doc_type == "Nota de Débito" and len(widths) == 3 and i == 2

            if is_nd_header_fusion:
                merged_width = widths[i] + widths[i+1]
                pdf.set_xy(current_x, start_y)
                pdf.multi_cell(merged_width, line_height, str(text), border=0, align='C', ln=3, fill=False, max_line_height=line_height)
                current_x += merged_width; pdf.set_y(start_y); continue
            elif is_nd_detail_fusion:
                merged_width = widths[i] + widths[i+1]
                detail_text = texts[1] if len(texts) > 1 else '' 
                pdf.set_xy(current_x, start_y)
                cell_align = body_alignments[1] if 1 < len(body_alignments) else 'R'
                pdf.multi_cell(merged_width, line_height, str(detail_text), border=0, align=cell_align, ln=3, fill=False, max_line_height=line_height)
                current_x += merged_width; pdf.set_y(start_y); continue
            elif is_nd_header_skip or is_nd_detail_skip:
                continue

            cell_align = 'C' if is_header else (body_alignments[i] if i < len(body_alignments) else 'L')
            if doc_type == "Comprobante de Retención" and is_header and i in [2, 3, 8]: cell_align = 'L'
            pdf.set_xy(current_x, start_y)
            pdf.multi_cell(width, line_height, str(text), border=0, align=cell_align, ln=3, fill=False, max_line_height=line_height)
            current_x += width; pdf.set_y(start_y)

    if not is_summary_row:
        pdf.line(MARGIN_LEFT, row_bottom_y, table_right_edge, row_bottom_y)

    if not is_summary_row:
        current_x_border = MARGIN_LEFT
        pdf.line(current_x_border, start_y, current_x_border, row_bottom_y)
        for i in range(num_cols):
            if widths[i] is None: continue
            current_x_border += widths[i]
            draw_this_vertical_line = True
            if doc_type == "Nota de Débito" and len(widths) == 3 and i == 1 and (is_header or is_detail_row): draw_this_vertical_line = False
            if i == num_cols - 1 or draw_this_vertical_line:
                 pdf.line(current_x_border, start_y, current_x_border, row_bottom_y)

    if not is_summary_row:
        pdf.set_y(row_bottom_y)

def _prepare_detail_row_data_other_docs(item: Dict[str, Any], doc_type: str, periodo_fiscal_doc: str = "") -> List[str]:
    if doc_type == "Nota de Débito":
        valor_original = _format_currency_pdf(item.get('precio_total_sin_impuesto'))
        return [_safe_get(item, ['descripcion']), valor_original, ""]
    elif doc_type == "Comprobante de Retención":
        cod_doc_sustento = _safe_get(item, ['cod_doc_sustento'])
        tipo_comp_sust = COD_DOC_SUSTENTO_MAP.get(str(cod_doc_sustento), str(cod_doc_sustento))
        codigo_impuesto = _safe_get(item, ['codigo'])
        tipo_impuesto = IMPUESTO_RETENCION_MAP.get(str(codigo_impuesto), str(codigo_impuesto))
        return [
            tipo_comp_sust, _safe_get(item, ['num_doc_sustento']),
            _safe_get(item, ['fecha_emision_doc_sustento']), periodo_fiscal_doc,
            _format_currency_pdf(item.get('base_imponible')), tipo_impuesto, 
            _safe_get(item, ['codigo_retencion']), _format_currency_pdf(item.get('porcentaje_retener')), 
            _format_currency_pdf(item.get('valor_retenido'))
        ]
    elif doc_type == "Nota de Crédito":
        detalles_adicionales = item.get('detalles_adicionales', {})
        detalle_adicional_texto = detalles_adicionales.get('detalle1', detalles_adicionales.get('Detalle1', ''))
        if not detalle_adicional_texto and len(detalles_adicionales) == 1:
            detalle_adicional_texto = list(detalles_adicionales.values())[0]
        codigo_principal_valor = item.get('codigo_principal', '')
        return [
            codigo_principal_valor, item.get('codigo_auxiliar', ''),
            _format_integer_pdf(item.get('cantidad', 0)), item.get('descripcion', ''),
            detalle_adicional_texto, _format_currency_pdf(item.get('descuento', 0)), 
            _format_currency_pdf(item.get('precio_unitario', 0)),
            _format_currency_pdf(item.get('precio_total_sin_impuesto', 0))
        ]
    elif doc_type == "Liquidación de Compra de Bienes y Prestación de Servicios":
        return [
            _safe_get(item, ['codigo_principal']), _safe_get(item, ['descripcion']),
            _format_integer_pdf(item.get('cantidad'), default=0),
            _format_currency_pdf(item.get('precio_unitario')),
            _format_currency_pdf(item.get('precio_total_sin_impuesto', 0))
        ]
    else:
        return [str(item.get(f"col{i+1}", "")) for i in range(len(item))] 
    
def _draw_info_adicional_other_docs(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str, start_y: float, column_widths: List[float], doc_type: str) -> float:
    TABLE_FONT_SIZE = 7; ROW_V_PADDING_AFTER = 1.0
    info_adicional_data = _safe_get(invoice_data, ['info_adicional'], {})
    info_fields_to_draw = {k: v for k, v in info_adicional_data.items() if v and str(v).strip()}
    current_info_y = start_y    
    page_total_content_width = pdf.w - MARGIN_LEFT - MARGIN_RIGHT
    info_section_width = 0
    # Lógica del asesor eliminada, info_adicional toma el ancho según la lógica original.
    if doc_type == "Comprobante de Retención":
        info_section_width = page_total_content_width * 0.65 
    elif doc_type == "Nota de Débito" and len(column_widths) == 3: # Relies on main table's column_widths
        info_section_width = column_widths[0] * 0.98 
    elif doc_type == "Nota de Crédito": # Relies on main table's column_widths
        if len(column_widths) == 8: base_width_nc = sum(column_widths[0:5])
        else: base_width_nc = page_total_content_width * 0.7 
        info_section_width = base_width_nc * 0.97
    else:
        info_section_width = page_total_content_width * 0.7 # Default width for info adicional

    if info_section_width <=0: # Ensure info section has some width
        info_section_width = page_total_content_width

    info_header_height = SUMMARY_TABLE_LINE_HEIGHT + ROW_V_PADDING_AFTER
    pdf.set_font(font_to_use, '', SUMMARY_TABLE_FONT_SIZE)
    pdf.set_xy(MARGIN_LEFT, current_info_y)
    pdf.cell(info_section_width, info_header_height, "Información Adicional", border=0, align='C')
    pdf.line(MARGIN_LEFT, current_info_y, MARGIN_LEFT + info_section_width, current_info_y)
    pdf.line(MARGIN_LEFT, current_info_y + info_header_height, MARGIN_LEFT + info_section_width, current_info_y + info_header_height)
    pdf.line(MARGIN_LEFT, current_info_y, MARGIN_LEFT, current_info_y + info_header_height) # Borde izquierdo
    pdf.line(MARGIN_LEFT + info_section_width, current_info_y, MARGIN_LEFT + info_section_width, current_info_y + info_header_height) # Borde derecho
    current_info_y += info_header_height

    def draw_info_field_row(y_pos, key, value, width):
        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        label_text = f"{key.replace('_', ' ').capitalize()}: "; label_width = pdf.get_string_width(label_text) + 1
        pdf.set_xy(MARGIN_LEFT + 1, y_pos + 0.5); pdf.cell(label_width, LINE_HEIGHT, label_text, 0, 0, 'L')
        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        value_width = width - label_width - 2; value_x = MARGIN_LEFT + label_width + 1
        pdf.set_xy(value_x, y_pos + 0.5)
        try:
            lines = pdf.multi_cell(value_width, LINE_HEIGHT, str(value), split_only=True, max_line_height=LINE_HEIGHT)
            cell_height = max(LINE_HEIGHT, len(lines) * LINE_HEIGHT) + 1
        except: cell_height = LINE_HEIGHT + 1
        pdf.set_xy(value_x, y_pos + 0.5); pdf.multi_cell(value_width, LINE_HEIGHT, str(value), 0, 'L')
        pdf.line(MARGIN_LEFT, y_pos, MARGIN_LEFT, y_pos + cell_height)
        pdf.line(MARGIN_LEFT + width, y_pos, MARGIN_LEFT + width, y_pos + cell_height)
        return y_pos + cell_height

    if info_fields_to_draw:
        for key, value in info_fields_to_draw.items():
             current_info_y = draw_info_field_row(current_info_y, key, value, info_section_width)
        pdf.line(MARGIN_LEFT, current_info_y, MARGIN_LEFT + info_section_width, current_info_y) 
    else: # Si no hay campos, solo dibujar la línea inferior del área de contenido vacía
         pdf.line(MARGIN_LEFT, current_info_y, MARGIN_LEFT + info_section_width, current_info_y)
    
    # Lógica de la sección del asesor eliminada

    return current_info_y

def _draw_summary_section_other_docs(pdf: InvoicePDF, invoice_data: Dict[str, Any], font_to_use: str, start_y: float, column_widths: List[float], doc_type: str, header_texts: List[str], body_alignments: List[str]) -> float:
    ROW_V_PADDING_AFTER = 1.0
    totals = _calculate_totals(invoice_data) 
    
    summary_lines_data_initial = [
        ("SUBTOTAL IVA 15%", totals["subtotal_iva_15"]), 
        ("SUBTOTAL 12%", totals["subtotal_iva_12"]),
        ("SUBTOTAL IVA DIFERENCIADO", totals["subtotal_iva_diferenciado"]), 
        ("SUBTOTAL IVA 5%", totals["subtotal_iva_5"]),
        ("SUBTOTAL IVA 0%", totals["subtotal_iva_0"]), 
        ("SUBTOTAL NO OBJETO DE IVA", totals["subtotal_no_objeto"]),
        ("SUBTOTAL EXENTO DE IVA", totals["subtotal_exento"]), 
        ("SUBTOTAL SIN IMPUESTOS", totals["total_sin_impuestos"]),
        ("TOTAL DESCUENTO", totals["total_descuento"]), 
        ("ICE", totals["total_ice"]),
        ("IVA", totals["iva_15"] + totals["iva_12"] + totals["iva_5"] + totals["iva_diferenciado"]),
        ("TOTAL DEVOLUCION IVA", totals["total_devolucion_iva"]), 
        ("IRBPNR", totals["total_irbpnr"]),
        ("VALOR TOTAL", totals["importe_total"]), 
    ]

    summary_lines_data = list(summary_lines_data_initial)

    if doc_type == "Nota de Crédito":
        valor_modificacion_nc_str = _safe_get(invoice_data, ['doc_especifico', 'valorModificacion'], '0.00')
        try:
            valor_modificacion_nc_float = float(valor_modificacion_nc_str)
        except ValueError:
            valor_modificacion_nc_float = 0.00
            logger.warning(f"No se pudo convertir valorModificacion '{valor_modificacion_nc_str}' a float para Nota de Crédito. Usando 0.00.")

        found_valor_total = False
        for i, (label, value) in enumerate(summary_lines_data):
            if label.upper() == "VALOR TOTAL":
                summary_lines_data[i] = ("VALOR TOTAL", valor_modificacion_nc_float)
                found_valor_total = True
                break
        if not found_valor_total: 
            summary_lines_data.append(("VALOR TOTAL", valor_modificacion_nc_float))

    summary_start_y_for_loop = start_y
    max_y_for_sections = pdf.h - MARGIN_BOTTOM - 5 

    summary_start_x = 0
    label_width_summary = 0
    value_width_summary = 0
    summary_area_end_x = 0
    
    if doc_type == "Nota de Débito" and len(column_widths) == 3:
        summary_start_x = MARGIN_LEFT + column_widths[0]
        total_summary_width = column_widths[1] + column_widths[2]
    elif doc_type == "Nota de Crédito" and len(column_widths) == 8:
        summary_start_x = MARGIN_LEFT + sum(column_widths[0:5])
        total_summary_width = sum(column_widths[5:8]) 
    elif doc_type == "Liquidación de Compra de Bienes y Prestación de Servicios" and len(column_widths) == 5:
        summary_start_x = MARGIN_LEFT + sum(column_widths[0:2]) 
        total_summary_width = sum(column_widths[2:5]) 
    else: 
        return summary_start_y_for_loop 

    if doc_type == "Nota de Crédito" and len(column_widths) == 8:
        label_width_summary = column_widths[5] + column_widths[6]
        value_width_summary = column_widths[7]
    elif not (label_width_summary > 0 and value_width_summary > 0): 
        label_width_summary = total_summary_width * 0.70
        value_width_summary = total_summary_width * 0.30
    
    summary_area_end_x = summary_start_x + total_summary_width

    for label, value in summary_lines_data: 
        show_row = False
        label_upper = label.upper()

        if doc_type == "Nota de Débito":
            nd_always_show = ["SUBTOTAL SIN IMPUESTOS", "VALOR TOTAL"]
            nd_show_if_nonzero = ["SUBTOTAL IVA 15%", "SUBTOTAL 12%", "SUBTOTAL IVA DIFERENCIADO", "SUBTOTAL IVA 5%", "SUBTOTAL IVA 0%", "SUBTOTAL NO OBJETO DE IVA", "SUBTOTAL EXENTO DE IVA", "ICE", "IRBPNR", "IVA"]
            if "SUBSIDIO" in label_upper or "PROPINA" in label_upper or "TOTAL DESCUENTO" in label_upper or "DEVOLUCION IVA" in label_upper:
                continue
            show_row = (label_upper in nd_always_show or (value != 0 and label_upper in nd_show_if_nonzero))
        elif doc_type == "Nota de Crédito":
            nc_always_show = ["SUBTOTAL SIN IMPUESTOS", "VALOR TOTAL"]
            nc_show_if_nonzero = ["SUBTOTAL IVA 15%", "SUBTOTAL 12%", "SUBTOTAL IVA DIFERENCIADO", "SUBTOTAL IVA 5%", "SUBTOTAL IVA 0%", "SUBTOTAL NO OBJETO DE IVA", "SUBTOTAL EXENTO DE IVA", "IVA", "TOTAL DEVOLUCION IVA"]
            if "SUBSIDIO" in label_upper or "PROPINA" in label_upper or "TOTAL DESCUENTO" in label_upper or "ICE" in label_upper or "IRBPNR" in label_upper:
                continue
            show_row = (label_upper in nc_always_show or (value != 0 and label_upper in nc_show_if_nonzero))
        elif doc_type == "Liquidación de Compra de Bienes y Prestación de Servicios":
            liq_always_show = ["SUBTOTAL SIN IMPUESTOS", "VALOR TOTAL", "SUBTOTAL IVA 15%"] 
            if "SUBSIDIO" in label_upper or "PROPINA" in label_upper or "DEVOLUCION IVA" in label_upper or "IRBPNR" in label_upper:
                continue
            show_row = (value != 0 or label_upper in liq_always_show)

        if show_row:
            current_row_start_y = summary_start_y_for_loop
            current_row_height = SUMMARY_TABLE_LINE_HEIGHT + ROW_V_PADDING_AFTER

            if current_row_start_y + current_row_height > max_y_for_sections:
                pdf.add_page()
                header_start_y_new = pdf.get_y()
                header_height_new = _calculate_row_height_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, doc_type, is_header=True)
                pdf.line(MARGIN_LEFT, header_start_y_new, pdf.w - MARGIN_RIGHT, header_start_y_new)
                _draw_table_row_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height_new, header_start_y_new, font_to_use, doc_type, [], is_header=True)
                summary_start_y_for_loop = pdf.get_y()
                current_row_start_y = summary_start_y_for_loop

            pdf.set_font(font_to_use, '', SUMMARY_TABLE_FONT_SIZE)
            pdf.set_fill_color(255, 255, 255) 
            pdf.set_line_width(BORDER_THICKNESS_MM)
            pdf.set_draw_color(180, 180, 180) 
            
            row_bottom_y = current_row_start_y + current_row_height
            middle_line_x = summary_start_x + label_width_summary
            y_centered_summary = current_row_start_y + (current_row_height - SUMMARY_TABLE_LINE_HEIGHT) / 2 

            pdf.set_xy(summary_start_x + 1, y_centered_summary) 
            pdf.cell(label_width_summary - 2, SUMMARY_TABLE_LINE_HEIGHT, label, border=0, align='L', ln=0) 
            
            pdf.set_xy(middle_line_x + 1, y_centered_summary) 
            pdf.cell(value_width_summary - 2, SUMMARY_TABLE_LINE_HEIGHT, _format_summary_value(value), border=0, align='R', ln=0) 

            pdf.line(summary_start_x, row_bottom_y, summary_area_end_x, row_bottom_y) 
            pdf.line(summary_start_x, current_row_start_y, summary_start_x, row_bottom_y) 
            pdf.line(middle_line_x, current_row_start_y, middle_line_x, row_bottom_y) 
            pdf.line(summary_area_end_x, current_row_start_y, summary_area_end_x, row_bottom_y) 
            
            summary_start_y_for_loop += current_row_height
            
    return summary_start_y_for_loop


def _generate_specific_pdf_content(pdf: InvoicePDF, document_data: Dict[str, Any], font_to_use: str, doc_type: str):
    """
    Dibuja el contenido específico del PDF para documentos que NO son Facturas.
    """
    prefix_map = {
        'Nota de Crédito': "NC", 'Nota de Débito': "ND", 'Comprobante de Retención': "RET",
        'Liquidación de Compra de Bienes y Prestación de Servicios': "LQC", 'Guía de Remisión': "GR" 
    }
    prefix = prefix_map.get(doc_type, "DOC")
    
    try:
        page_width = pdf.w - MARGIN_LEFT - MARGIN_RIGHT
        if page_width <= 0: raise ValueError(f"Ancho de página inválido para {doc_type}.")
        pdf.set_text_color(*COLOR_BLACK)

        current_y = _draw_header_other_docs(pdf, document_data, font_to_use, doc_type); pdf.set_y(current_y)
        current_y = _draw_buyer_info_other_docs(pdf, document_data, font_to_use, doc_type); pdf.set_y(current_y)

        column_widths, header_texts, body_alignments = _define_table_columns_other_docs(page_width, doc_type, pdf, document_data) 
        
        header_start_y = pdf.get_y()
        header_height = _calculate_row_height_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, doc_type, is_header=True)
        pdf.line(MARGIN_LEFT, header_start_y, pdf.w - MARGIN_RIGHT, header_start_y) 
        _draw_table_row_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height, header_start_y, font_to_use, doc_type, body_alignments, is_header=True)

        pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
        detalles_list = _safe_get(document_data, ['detalles'], []) 
        periodo_fiscal_formateado_ret = ""

        if doc_type == "Comprobante de Retención":
            periodo_fiscal_raw = _safe_get(document_data, ['doc_especifico', 'periodo_fiscal'], '')
            if periodo_fiscal_raw:
                if len(periodo_fiscal_raw) == 6 and periodo_fiscal_raw.isdigit(): periodo_fiscal_formateado_ret = f"{periodo_fiscal_raw[4:6]}/{periodo_fiscal_raw[0:4]}"
                else: periodo_fiscal_formateado_ret = periodo_fiscal_raw
        
        logger.debug(f"OtroDoc - Iniciando bucle de detalles. Total items en detalles_list: {len(detalles_list)}")
        for item in detalles_list:
            if not isinstance(item, dict):
                logger.warning(f"OtroDoc - Item en detalles_list no es un diccionario: {item}")
                continue
            
            logger.debug(f"OtroDoc - Procesando item de detalle XML: {item}")
            data_row_texts = _prepare_detail_row_data_other_docs(item, doc_type, periodo_fiscal_formateado_ret)
            logger.info(f"OtroDoc - Fila de detalle preparada para dibujar (data_row_texts): {data_row_texts}")
            
            current_row_start_y = pdf.get_y()
            natural_row_height = _calculate_row_height_other_docs(pdf, data_row_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, doc_type, is_detail=True)
            current_row_height = max(natural_row_height, header_height) 
            logger.info(f"OtroDoc - Altura calculada para fila de detalle: natural={natural_row_height}, final={current_row_height}")
            
            estimated_space_needed = 40 if doc_type == "Comprobante de Retención" else 60 
            if current_row_start_y + current_row_height + estimated_space_needed > pdf.h - MARGIN_BOTTOM:
                pdf.add_page()
                header_start_y_new = pdf.get_y()
                header_height_new = _calculate_row_height_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, doc_type, is_header=True)
                pdf.line(MARGIN_LEFT, header_start_y_new, pdf.w - MARGIN_RIGHT, header_start_y_new)
                _draw_table_row_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height_new, header_start_y_new, font_to_use, doc_type, body_alignments, is_header=True)
                pdf.set_font(font_to_use, '', TABLE_FONT_SIZE)
                current_row_start_y = pdf.get_y(); header_height = header_height_new 
            _draw_table_row_other_docs(pdf, data_row_texts, column_widths, TABLE_LINE_HEIGHT, current_row_height, current_row_start_y, font_to_use, doc_type, body_alignments, is_header=False)
            logger.debug(f"OtroDoc - Fila de detalle dibujada. Y después de dibujar: {pdf.get_y()}")

        details_end_y_final = pdf.get_y()
        blank_row_height_sep = _calculate_row_height_other_docs(pdf, [], [], SUMMARY_TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, doc_type, is_summary=True)
        bottom_block_start_y = details_end_y_final

        estimated_bottom_block_height = 60 if doc_type != "Comprobante de Retención" else 40
        if bottom_block_start_y + estimated_bottom_block_height > pdf.h - MARGIN_BOTTOM:
            pdf.add_page()
            header_start_y_new_page = pdf.get_y()
            header_height_new_page = _calculate_row_height_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, ROW_V_PADDING_AFTER, font_to_use, doc_type, is_header=True)
            pdf.line(MARGIN_LEFT, header_start_y_new_page, pdf.w - MARGIN_RIGHT, header_start_y_new_page)
            _draw_table_row_other_docs(pdf, header_texts, column_widths, TABLE_LINE_HEIGHT, header_height_new_page, header_start_y_new_page, font_to_use, doc_type, body_alignments, is_header=True)
            bottom_block_start_y = pdf.get_y()

        current_info_adic_start_y = bottom_block_start_y + blank_row_height_sep + 1
        
        if doc_type == "Comprobante de Retención":
            y_after_info_ret = _draw_info_adicional_other_docs(pdf, document_data, font_to_use, current_info_adic_start_y, column_widths, doc_type)
            pdf.set_y(y_after_info_ret)
        elif doc_type in ["Nota de Crédito", "Nota de Débito", "Liquidación de Compra de Bienes y Prestación de Servicios"]:
            y_after_info_non_ret = _draw_info_adicional_other_docs(pdf, document_data, font_to_use, current_info_adic_start_y, column_widths, doc_type)
            y_after_summary_non_ret = _draw_summary_section_other_docs(pdf, document_data, font_to_use, bottom_block_start_y, column_widths, doc_type, header_texts, body_alignments)
            final_y_pos = max(y_after_info_non_ret, y_after_summary_non_ret)
            pdf.set_y(final_y_pos)
        elif doc_type == 'Guía de Remisión':
            pdf.set_y(bottom_block_start_y + blank_row_height_sep + 1)
        else: 
            numero_autorizacion_log = _safe_get(document_data, ['numero_autorizacion'], 'N/A')
            error_msg = f"Tipo de documento '{doc_type}' no soportado para generación de PDF (Num Aut: {numero_autorizacion_log})."
            logger.error(error_msg)
            raise ValueError(error_msg)

        numero_autorizacion_log = _safe_get(document_data, ['numero_autorizacion'], 'N/A')
        logger.info(f"Contenido PDF de {doc_type} dibujado (Num Aut: {numero_autorizacion_log})")

    except FPDFException as e:
        numero_autorizacion_log = _safe_get(document_data, ['numero_autorizacion'], 'N/A')
        logger.error(f"Error FPDF dibujando contenido de {doc_type} (Num Aut: {numero_autorizacion_log}): {e}")
        raise Exception(f"Fallo en PDF {doc_type} (Num Aut: {numero_autorizacion_log}): {e}") from e
    except ValueError as e: 
        numero_autorizacion_log = _safe_get(document_data, ['numero_autorizacion'], 'N/A')
        logger.error(f"Error de Valor dibujando contenido de {doc_type} (Num Aut: {numero_autorizacion_log}): {e}")
        raise Exception(f"Fallo en PDF {doc_type} (Num Aut: {numero_autorizacion_log}): {e}") from e
    except Exception as e:
        numero_autorizacion_log = _safe_get(document_data, ['numero_autorizacion'], 'N/A')
        logger.exception(f"Error inesperado dibujando contenido de {doc_type} (Num Aut: {numero_autorizacion_log}): {e}")
        raise Exception(f"Fallo en PDF {doc_type} (Num Aut: {numero_autorizacion_log}): {e}") from e

try:
    from .xml_parser import parse_xml
    from .pdf_invoice_generator import generate_invoice_pdf
except ImportError as e:
    logger.error(f"Error al importar módulos del core: {e}. Asegúrese que xml_parser.py y pdf_invoice_generator.py existan y estén en el mismo directorio.")
    def parse_xml(*args, **kwargs): 
        raise NotImplementedError("xml_parser no pudo ser importado.")
    def generate_invoice_pdf(*args, **kwargs):
        raise NotImplementedError("pdf_invoice_generator no pudo ser importado.")      


def generate_pdf_from_xml(xml_file_path: str, 
                          output_dir: str, 
                          # logo_path para el emisor eliminado
                          ) -> Optional[str]:
    """
    Parsea un archivo XML, determina el tipo de documento y llama al generador de PDF apropiado.
    """
    logger.debug(f"Iniciando generación de PDF desde XML: {xml_file_path} en directorio: {output_dir}")
    try:
        parsed_data = parse_xml(xml_file_path) 
    except Exception as e:
        logger.error(f"Error al parsear XML {os.path.basename(xml_file_path)}: {e}")
        return None

    if not parsed_data:
        logger.error(f"No se pudieron parsear los datos del XML: {xml_file_path}")
        return None

    doc_type = parsed_data.get('tipo_documento')
    logger.info(f"Tipo de documento detectado: '{doc_type}' para el archivo {os.path.basename(xml_file_path)}")

    # Lógica para añadir logo_path del emisor a parsed_data eliminada.
    # Lógica para añadir asesor_info a parsed_data eliminada.

    pdf = InvoicePDF('P', 'mm', 'A4')
    
    try:
        font_to_use = FONT_FAMILY_NAME 
        pdf.set_doc_font(font_to_use)
    except Exception as font_error:
        logger.warning(f"Al cargar fuente para PDF: {font_error}. Usando fuente de respaldo.")
        font_to_use = FONT_FALLBACK
        pdf.set_doc_font(font_to_use)

    pdf.set_auto_page_break(auto=True, margin=MARGIN_BOTTOM)
    pdf.set_margins(MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT)
    pdf.add_page()
    pdf.alias_nb_pages()

    if doc_type == 'Factura':
        logger.debug(f"Llamando a generate_invoice_pdf para {os.path.basename(xml_file_path)}")
        # generate_invoice_pdf ya no espera asesor_info en parsed_data para la marca de agua
        return generate_invoice_pdf(parsed_data, output_dir) 
    elif doc_type in ['Nota de Crédito', 'Nota de Débito', 'Comprobante de Retención', 'Liquidación de Compra de Bienes y Prestación de Servicios', 'Guía de Remisión']:
        logger.debug(f"Llamando a _generate_specific_pdf_content para {doc_type}: {os.path.basename(xml_file_path)}")
        _generate_specific_pdf_content(pdf, parsed_data, font_to_use, doc_type)
        
        numero_autorizacion = _safe_get(parsed_data, ['numero_autorizacion'], '')
        prefix_map = {
            'Nota de Crédito': "NC", 'Nota de Débito': "ND", 'Comprobante de Retención': "RET",
            'Liquidación de Compra de Bienes y Prestación de Servicios': "LQC", 'Guía de Remisión': "GR"
        }
        prefix = prefix_map.get(doc_type, "DOC")
        fecha_autorizacion_dt = _safe_get(parsed_data, ['fecha_autorizacion_dt'])
        timestamp = fecha_autorizacion_dt.strftime('%Y%m%d%H%M%S') if isinstance(fecha_autorizacion_dt, datetime) else datetime.now().strftime('%Y%m%d%H%M%S%f')
        identificador = _safe_get(parsed_data, ['emisor', 'ruc']) or _safe_get(parsed_data, ['comprador', 'identificacion']) or '0000000000000'
        
        pdf_filename_base = f"{prefix}_{identificador}_{timestamp}"
        if numero_autorizacion:
            pdf_filename_base = numero_autorizacion
        else:
            pdf_filename_base = f"ERROR_SIN_AUT_{pdf_filename_base}"

        pdf_filename = f"{pdf_filename_base}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
        
        try:
            pdf.output(pdf_path)
            logger.info(f"PDF de {doc_type} generado: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"Error al guardar el PDF de {doc_type} en {pdf_path}: {e}")
            return None
    else:
        logger.warning(f"Tipo de documento '{doc_type}' no soportado para generación de PDF: {os.path.basename(xml_file_path)}")
        return None

def create_temp_folder() -> str:
    """
    Crea una carpeta temporal única para almacenar los PDFs generados durante una ejecución.
    """
    system_temp_dir = tempfile.gettempdir()
    base_temp_dir = os.path.join(system_temp_dir, "AsistenteContablePDFs")
    
    os.makedirs(base_temp_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temp_dir_path = tempfile.mkdtemp(prefix=f"pdfs_{timestamp}_", dir=base_temp_dir)
    logger.info(f"Carpeta temporal para PDFs creada en: {temp_dir_path}")
    return temp_dir_path
