# d:\Datos\Desktop\Asistente Contable\src\utils\exporter.py
import pandas as pd
import logging
import os # Importar os para os.path.normpath
from typing import List, Dict, Any, Union, Tuple
from decimal import Decimal, InvalidOperation

# Importar xlsxwriter para usar sus funcionalidades avanzadas como write_url
try:
    import xlsxwriter
    XLSXWRITER_AVAILABLE = True
except ImportError:
    XLSXWRITER_AVAILABLE = False
    logging.warning("La biblioteca 'xlsxwriter' no está instalada. La exportación a Excel será básica (sin hipervínculos, etc.).")

logger = logging.getLogger(__name__)

# Mapeo de Data Key (interno) a Display Name
# Esto debería ser consistente con xml_parser.ALL_CSV_FIELDS y las convenciones de la GUI
DATA_KEY_TO_DISPLAY_NAME_MAP = {
    "CodDoc": "CodDoc", "Fecha": "Fecha", "RUC Emisor": "RUC Emisor",
    "Razón Social Emisor": "Razón Social Emisor", "Nro.Secuencial": "Nro.Secuencial",
    "TipoId.": "TipoId.", "Id.Comprador": "Id.Comprador",
    "Razón Social Comprador": "Razón Social Comprador", "Formas de Pago": "Formas de Pago",
    "Descuento": "Descuento", "Total Sin Impuestos": "Total Sin Impuestos",
    "Base IVA 0%": "Base IVA 0%", "Base IVA 5%": "Base IVA 5%", "Base IVA 8%": "Base IVA 8%",
    "Base IVA 12%": "Base IVA 12%", "Base IVA 13%": "Base IVA 13%", "Base IVA 14%": "Base IVA 14%",
    "Base IVA 15%": "Base IVA 15%", "No Objeto IVA": "No Objeto IVA", "Exento IVA": "Exento IVA",
    "Desc. Adicional": "Desc. Adicional", "Devol. IVA": "Devol. IVA", "Monto IVA": "Monto IVA",
    "Base ICE": "Base ICE", "Monto ICE": "Monto ICE", "Base IRBPNR": "Base IRBPNR", "Monto IRBPNR": "Monto IRBPNR",
    "Propina": "Propina",
    "Ret. IVA Pres.": "Ret. IVA Pres.", "Ret. Renta Pres.": "Ret. Renta Pres.",
    "Total Ret. ISD": "Total Ret. ISD", # Añadido Total Ret. ISD
    "Monto Total": "Monto Total", "Guia de Remisión": "Guia de Remisión",
    "Primeros 3 Articulos": "Primeros 3 Articulos", "Nro de Autorización": "Nro de Autorización",

    # Campos específicos de Nota de Crédito (si data_key es igual a display_name)
    "Fecha D.M.": "Fecha D.M.", "CodDocMod": "CodDocMod", "Num.Doc.Modificado": "Num.Doc.Modificado",
    "N.A.Doc.Modificado": "N.A.Doc.Modificado", "Valor Mod.": "Valor Mod.",

    # Campos específicos de Retención (si data_key es igual a display_name)
    # Nota: Algunas de estas claves pueden no existir si el parser no las extrae directamente
    # o si se consolidan en otros campos. Asegurarse de la consistencia con xml_parser.py
    "TipoIdSujRet.": "TipoIdSujRet.", # Asumiendo que esta es la clave interna si existe
    "IdSujRetenido": "IdSujRetenido", # Asumiendo que esta es la clave interna si existe
    "P.Fiscal": "P.Fiscal", # Asumiendo que esta es la clave interna si existe
    "CodDocSust": "CodDocSust", "Fecha D.S.": "Fecha D.S.", "Num.Doc.Sustento": "Num.Doc.Sustento",
    "Autorización Doc Sust.": "Autorización Doc Sust.",
    "Tipo": "Tipo", # Podría ser un nombre genérico para Tipo Impuesto Ret.
    "codigo": "codigo", # Código de impuesto en detalle de retención
    "codigoRetencion": "codigoRetencion", # Código de retención en detalle
    "baseImponible": "baseImponible", # Base imponible en detalle de retención
    "porcentajeRetener": "porcentajeRetener", # Porcentaje en detalle de retención
    "valorRetenido": "valorRetenido", # Valor retenido en detalle
    "F.P.Dividendo": "F.P.Dividendo", "ImpRenta": "ImpRenta", "Año Utilidad": "Año Utilidad",
    "Num.Caj.Banano": "Num.Caj.Banano", "Prec.Caj.Banano": "Prec.Caj.Banano",
}

# Mapeo inverso: Display Name a Data Key
# Este mapa se usa para encontrar la clave interna en los datos originales
# a partir del nombre de columna que se muestra en la GUI/Excel.
DISPLAY_NAME_TO_DATA_KEY_MAP = {v: k for k, v in DATA_KEY_TO_DISPLAY_NAME_MAP.items()}
# "No." es especial, no tiene un data_key directo en los datos originales.
# No lo añadimos al mapa inverso si no se usa para buscar datos originales.
# DISPLAY_NAME_TO_DATA_KEY_MAP["No."] = "No." # No necesario aquí

def _has_significant_value(value: Any) -> bool:
    """
    Verifica si un valor es significativo (no nulo, no vacío, no cero numérico).
    """
    if value is None:
        return False
    s_value = str(value).strip()
    if not s_value:  # Cadena vacía
        return False
    try:
        # Comprueba si es numéricamente cero
        # Usar Decimal para mayor precisión si los datos originales son Decimal
        num_val = Decimal(s_value)
        if num_val.is_zero():
            return False
    except InvalidOperation: # Si no se puede convertir a Decimal (ej. texto no numérico)
        # No es un número, pero es una cadena no vacía, por lo tanto, es significativo
        pass
    return True

class ExcelExportStatus:
    SUCCESS = "SUCCESS"
    ERROR_PERMISSION = "ERROR_PERMISSION"
    ERROR_IMPORT_XLSXWRITER = "ERROR_IMPORT_XLSXWRITER"
    ERROR_GENERIC = "ERROR_GENERIC"
    NO_DATA_OR_COLUMNS = "NO_DATA_OR_COLUMNS"
    INVALID_PATH = "INVALID_PATH"

# Definir el tipo para los datos de cada hoja, incluyendo la lista de diccionarios
# que ahora puede contener el formato especial de hipervínculo.
SheetExportData = Dict[str, Union[List[Dict[str, Any]], List[str], str, str, List[str]]]

def export_to_excel(data_by_sheet: Dict[str, SheetExportData],
                    file_path: str) -> str: # Cambiado el tipo de retorno a str (ExcelExportStatus)
    """
    Exporta múltiples conjuntos de datos a diferentes hojas de un archivo Excel.
    Solo se exportan las columnas que contienen al menos un valor significativo.
    Se añade una fila de totales en la parte superior de cada hoja.
    Las columnas se ordenan según la lista proporcionada por la GUI.
    Se añaden autofiltros y se ajusta el ancho de las columnas.
    Soporta la escritura de hipervínculos si xlsxwriter está disponible.

    Args:
        data_by_sheet (Dict[str, SheetExportData]): Diccionario donde la clave es el nombre de la hoja.
            El valor es otro diccionario con:
            - "data": Lista de diccionarios (filas) para esa hoja.
                      Los valores pueden ser tipos estándar o una tupla
                      ("HYPERLINK", (url, text)) para hipervínculos.
            - "sum_display_names": Lista de nombres de visualización de columnas a sumar.
            - "doc_key_prefix": Prefijo para la columna "No." (ej. "FC", "NC").
            - "doc_key_original": La clave original del documento (ej. "FC", "NC_R", "RET_R").
            - "final_ordered_display_names": La lista final y ordenada de nombres de columnas a exportar.
        file_path (str): La ruta completa (incluyendo nombre de archivo .xlsx)
                         donde se guardará el archivo Excel.

    Returns:
        str: Un valor de ExcelExportStatus indicando el resultado.
    """
    if not XLSXWRITER_AVAILABLE:
         # Si xlsxwriter no está disponible, no podemos hacer hipervínculos ni formato avanzado.
         # Podríamos intentar una exportación básica con pandas a un .xlsx,
         # pero para mantener la consistencia y evitar código duplicado,
         # simplemente reportamos el error de dependencia.
         logger.critical("xlsxwriter no está disponible. No se puede exportar a Excel con formato avanzado.")
         return ExcelExportStatus.ERROR_IMPORT_XLSXWRITER

    if not data_by_sheet:
        logger.warning("No hay datos por hoja (data_by_sheet) para exportar a Excel.")
        return ExcelExportStatus.NO_DATA_OR_COLUMNS
    if not file_path.lower().endswith('.xlsx'):
        logger.error(f"Ruta de archivo inválida para Excel: '{file_path}'. Debe terminar con .xlsx")
        return ExcelExportStatus.INVALID_PATH

    try:
        # Usar xlsxwriter directamente para tener control total sobre la escritura
        workbook = xlsxwriter.Workbook(file_path)

        # Formato para hipervínculos (opcional, xlsxwriter lo hace por defecto azul/subrayado)
        # hyperlink_format = workbook.add_format({'color': 'blue', 'underline': 1})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1})
        default_data_format = workbook.add_format({'border': 1}) # Para celdas sin fondo especial
        number_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1}) # Para números en celdas sin fondo especial

        # Formato para el fondo de las filas alternas (celeste claro)
        alternating_row_bg_format = workbook.add_format({
            'bg_color': '#E6F7FF',  # Celeste claro
            'border': 1
        })

        # Formato para números en filas alternas
        alternating_row_number_format = workbook.add_format({
            'bg_color': '#E6F7FF',
            'num_format': '#,##0.00',
            'border': 1
        })

        # Formato para hipervínculos en filas alternas
        link_on_alternating_row_format = workbook.add_format({
            'bg_color': '#E6F7FF', 'font_color': 'blue', 'underline': 1, 'border': 1
        })
        # Formato para hipervínculos en filas normales (sin fondo especial)
        link_on_normal_row_format = workbook.add_format({
            'font_color': 'blue', 'underline': 1, 'border': 1
        })
        sum_row_format = workbook.add_format({'bold': True, 'bg_color': '#E2EFDA', 'border': 1}) # Formato para fila de totales

        for sheet_name, sheet_content in data_by_sheet.items():
            # Limitar nombre de hoja a 31 caracteres
            worksheet = workbook.add_worksheet(sheet_name[:31])

            # Los datos ya vienen preparados de MainWindow, incluyendo el formato de hipervínculo
            data_rows_prepared = sheet_content["data"]
            sum_display_names_for_sheet = sheet_content["sum_display_names"]
            # Obtener la lista final y ordenada de nombres de columnas a exportar
            final_ordered_display_names = sheet_content.get("final_ordered_display_names", [])

            if not data_rows_prepared or not final_ordered_display_names:
                logger.info(f"Hoja '{sheet_name}' está vacía en los datos preparados o no tiene columnas definidas. Omitiendo creación de hoja en Excel.")
                continue # No crear hoja si no hay datos o columnas

            # 1. Preparar fila de sumas (ahora calculada aquí usando los datos preparados)
            sum_row_values: Dict[str, Any] = {} # Usar Any para permitir ""
            if final_ordered_display_names:
                sum_row_values[final_ordered_display_names[0]] = "Total" # Primera columna de la fila de suma es "Total"

            # Crear un DataFrame temporal solo para calcular sumas si es necesario
            # Esto es menos eficiente que sumar directamente, pero aprovecha pandas para to_numeric
            temp_df_for_sums = pd.DataFrame(data_rows_prepared)

            for display_name in final_ordered_display_names:
                if display_name == final_ordered_display_names[0] and final_ordered_display_names[0] in sum_row_values :
                    pass # Ya se puso "Total"
                elif display_name in sum_display_names_for_sheet:
                    try:
                        # Extraer valores, manejar hipervínculos si existen
                        col_values = temp_df_for_sums[display_name].apply(lambda x: x[1][1] if isinstance(x, tuple) and x[0] == "HYPERLINK" else x)
                        # Convertir a numérico para suma, tratando errores
                        col_sum = pd.to_numeric(col_values, errors='coerce').sum()
                        sum_row_values[display_name] = f"{col_sum:.2f}"
                    except Exception as e_sum:
                        logger.warning(f"Error al sumar columna '{display_name}' en hoja '{sheet_name}': {e_sum}")
                        sum_row_values[display_name] = "" # Dejar en blanco si hay error de suma
                elif display_name not in sum_row_values: # Si no es la primera columna y no es sumable
                     sum_row_values[display_name] = ""

            # 2. Escribir fila de totales (Fila 0)
            for col_idx, display_name in enumerate(final_ordered_display_names):
                 cell_value = sum_row_values.get(display_name, "")
                 worksheet.write(0, col_idx, cell_value, sum_row_format)

            # 3. Escribir cabeceras (Fila 1)
            for col_idx, header_title in enumerate(final_ordered_display_names):
                worksheet.write(1, col_idx, header_title, header_format)

            # 4. Escribir datos (Desde Fila 2 en adelante)
            # data_row_idx es el índice dentro de data_rows_prepared (0, 1, 2...)
            # excel_actual_row_num es la fila en Excel (2, 3, 4...)
            for data_row_idx, row_data in enumerate(data_rows_prepared):
                excel_actual_row_num = data_row_idx + 2 # Fila 0: sumas, Fila 1: cabeceras

                # Determinar si esta fila de datos debe tener el fondo alterno
                # La primera fila de datos (data_row_idx = 0, que es la fila 3 en Excel después de cabeceras) debe tener fondo.
                is_alternating_row = (data_row_idx % 2 == 0)

                # Seleccionar formatos base para la fila actual
                current_data_format_to_use = alternating_row_bg_format if is_alternating_row else default_data_format
                current_number_format_to_use = alternating_row_number_format if is_alternating_row else number_format
                current_link_format_to_use = link_on_alternating_row_format if is_alternating_row else link_on_normal_row_format

                for col_idx, display_name in enumerate(final_ordered_display_names):
                    cell_value = row_data.get(display_name)

                    if isinstance(cell_value, tuple) and len(cell_value) == 2 and cell_value[0] == "HYPERLINK":
                        link_url, link_text = cell_value[1]
                        worksheet.write_url(excel_actual_row_num, col_idx, os.path.normpath(link_url),
                                            cell_format=current_link_format_to_use, string=str(link_text))
                    elif isinstance(cell_value, (int, float)) and \
                         any(substring in display_name.lower() for substring in ["base", "monto", "total", "valor", "descuento", "ret.", "propina"]):
                        worksheet.write_number(excel_actual_row_num, col_idx, cell_value, current_number_format_to_use)
                    else:
                        # Escribir valores normales
                        # xlsxwriter intenta detectar tipos (número, fecha, string) automáticamente
                        worksheet.write(excel_actual_row_num, col_idx, cell_value, current_data_format_to_use)


            # 5. Aplicar autofiltro en la fila de encabezados (Fila 1)
            if final_ordered_display_names:
                worksheet.autofilter(1, 0, 1, len(final_ordered_display_names) - 1)

            # 6. Ajustar ancho de columnas
            # Recalcular ancho basado en contenido para todas las columnas, incluyendo la fila de sumas y cabeceras
            for col_idx, display_name in enumerate(final_ordered_display_names):
                max_len = 0
                # Ancho de la cabecera
                max_len = max(max_len, len(str(display_name)))
                # Ancho de la fila de totales
                sum_val_str = str(sum_row_values.get(display_name, ""))
                max_len = max(max_len, len(sum_val_str))

                # Ancho de los datos (considerando texto de hipervínculos si aplica)
                for row_data in data_rows_prepared:
                    cell_value = row_data.get(display_name)
                    if isinstance(cell_value, tuple) and cell_value[0] == "HYPERLINK":
                        val_str = str(cell_value[1][1]) # Usar el texto del hipervínculo
                    else:
                        val_str = str(cell_value)
                    max_len = max(max_len, len(val_str))

                # Añadir padding
                adjusted_width_with_padding = max_len + 2 # Reducido padding ligeramente

                # Aplicar límites de ancho
                if display_name == "Primeros 3 Articulos":
                    final_width = min(adjusted_width_with_padding, 250) # Cap at 250
                else:
                    final_width = min(adjusted_width_with_padding, 70) # Cap at 70 for other columns

                worksheet.set_column(col_idx, col_idx, final_width) # No text_wrap format applied

        workbook.close() # Cerrar el workbook para guardar el archivo

        logger.info(f"Datos exportados exitosamente a Excel: {file_path} con {len(data_by_sheet)} hoja(s).")
        return ExcelExportStatus.SUCCESS

    except PermissionError as pe:
        logger.error(f"Error de permisos durante la exportación a Excel en '{file_path}': {pe}", exc_info=True)
        return ExcelExportStatus.ERROR_PERMISSION
    except Exception as e:
        logger.error(f"Ocurrió un error durante la exportación a Excel en '{file_path}': {e}", exc_info=True)
        # Asegurarse de cerrar el workbook si se creó antes de la excepción
        if 'workbook' in locals() and workbook:
            try:
                workbook.close() # Intentar cerrar para evitar archivos corruptos
            except Exception as e_close:
                logger.error(f"Error adicional al intentar cerrar el workbook después de un error: {e_close}")
        # Si el archivo se creó parcialmente, intentar eliminarlo
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Eliminado archivo Excel parcial/corrupto: {file_path}")
            except Exception as e_remove:
                logger.error(f"Error al intentar eliminar archivo Excel parcial/corrupto '{file_path}': {e_remove}")

        return ExcelExportStatus.ERROR_GENERIC
