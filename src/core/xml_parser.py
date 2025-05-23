# d:\Datos\Desktop\Asistente Contable\src\core\xml_parser.py
import xml.etree.ElementTree as ET
import os
from typing import Dict, Any, List, Optional
import logging

# Namespace handling (puede variar si tus XML usan namespaces explícitos)
# Si tus elementos tienen prefijos como 'ns0:', necesitarás definir el namespace
# ns = {'ns0': 'http://url.del.namespace.aqui'}
# y usar find('.//ns0:elemento', ns)
# Por ahora, asumimos que no hay namespaces explícitos o se manejan implícitamente
ns = {} # Vacío si no hay namespaces explícitos

from datetime import datetime, timezone # <--- Importar datetime y timezone aquí
logger = logging.getLogger(__name__) # Obtener logger para este módulo

# Mapeo de códigos de tipo de identificación a nombres legibles
TIPO_IDENTIFICACION_MAP = {
    "04": "RUC",
    "05": "CEDULA",
    "06": "PASAPORTE",
    "07": "VENTA A CONSUMIDOR FINAL",
    "08": "IDENTIFICACION DEL EXTERIOR",
    "09": "PLACA"
}
# Mapeo de códigos de documento a nombres legibles
COD_DOC_MAP = {
    "01": "Factura",
    "03": "Liquidación de Compra de Bienes y Prestación de Servicios",
    "04": "Nota de Crédito",
    "05": "Nota de Débito",
    "06": "Guía de Remisión",
    "07": "Comprobante de Retención"
}
# Importar el mapa necesario desde pdf_base
from .pdf_base import IMPUESTO_RETENCION_MAP


# Lista de todos los posibles campos CSV que se pueden extraer.
# MainWindow dependerá de esta lista.
ALL_CSV_FIELDS: List[str] = [
    "CodDoc", "Fecha", "RUC Emisor", "Razón Social Emisor",
    "Nro.Secuencial", "TipoId.", "Id.Comprador", "Razón Social Comprador",
    # Campos específicos de NC
    "Fecha D.M.", "CodDocMod", "Num.Doc.Modificado", "N.A.Doc.Modificado", "Valor Mod.",
    # Campos específicos de Retención
    "Id.Sujeto Retenido", "Razón Social Sujeto Retenido", "Periodo Fiscal",
    "CodDocSust", "Fecha D.S.", "Num.Doc.Sustento", "Autorización Doc Sust.", "Tipo Impuesto Ret.", "Codigo Ret.", "Base Imponible Ret.", "Porcentaje Ret.", "Valor Retenido", # Nuevos para detalles de retención
    "Base IVA 0%", "Base IVA 5%", "Base IVA 8%", "Base IVA 12%", "Base IVA 13%", "Base IVA 14%", "Base IVA 15%",
    "No Objeto IVA", "Exento IVA",
    "Desc. Adicional", "Devol. IVA", "Monto IVA",
    "Base ICE", "Monto ICE", "Base IRBPNR", "Monto IRBPNR",
    "Propina", "Ret. IVA Pres.", "Ret. Renta Pres.", "Total Ret. ISD", # Añadido Total Ret. ISD
    "Monto Total", "Guia de Remisión", "Primeros 3 Articulos", "Nro de Autorización",
    "original_xml_path" # Clave interna para la ruta del archivo XML original
]


def _safe_float_conversion(
    value_str: Any, # Aceptar Any, no solo str
    default_value: float,
    xml_file_path_for_error: str,
    field_description: str,
    errors_list: List[str]
) -> float:
    """Intenta convertir un valor a float de forma segura, registrando errores."""
    if value_str is None or value_str == '':
        return default_value
    try:
        # Intentar reemplazar coma por punto si es necesario
        if isinstance(value_str, str):
             value_str = value_str.replace(',', '.')
        return float(value_str)
    except (ValueError, TypeError):
        user_friendly_error = (
            f"Archivo: '{os.path.basename(xml_file_path_for_error)}', Campo: '{field_description}', "
            f"Valor: '{value_str}'. No es un número válido. Se usó '{default_value:.2f}'." # Formatear default
        )
        # Evitar duplicados exactos en la lista de errores
        if user_friendly_error not in errors_list:
            errors_list.append(user_friendly_error)
        logger.warning(f"Error de conversión (usando default): {user_friendly_error}")
        return default_value


def _find_text_or_default(element: Optional[ET.Element], xpath: str, default: str = '') -> str:
    """Helper function to find text in an element or return a default value."""
    if element is None:
        return default
    # Usar findtext con namespaces si están definidos, o sin ellos si ns es {}
    found = element.findtext(xpath, default=default, namespaces=ns)
    
    # Asegurar que text_to_return sea una cadena antes de strip() y replace()
    # Si found es None y default es None, text_to_return será None.
    # Si found tiene texto, se usa. Si found es None pero default tiene texto, se usa default.
    text_value = found if found is not None else default
    
    text_to_return = text_value.strip() if isinstance(text_value, str) else (default if isinstance(default, str) else "")
    # Reemplazar caracteres problemáticos para Helvetica (Latin-1)
    text_to_return = text_to_return.replace('\u2013', '-') # EN DASH to HYPHEN-MINUS
    return text_to_return

def _parse_fecha(fecha_str: str, xml_file_path_for_error: str, field_name: str) -> Optional[datetime]:
    if not fecha_str:
        return None
    
    possible_formats = [
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S"
    ]
    
    # Normalizar 'Z' a '+00:00' para %z
    if fecha_str.endswith('Z'):
        fecha_str = fecha_str[:-1] + '+00:00'
        
    # Manejar formatos con milisegundos si aparecen
    if '.' in fecha_str and ('%f' not in possible_formats):
         possible_formats.insert(0, "%Y-%m-%dT%H:%M:%S.%f%z")
         possible_formats.insert(0, "%Y-%m-%dT%H:%M:%S.%f")


    for fmt in possible_formats:
        try:
            dt_obj = datetime.strptime(fecha_str, fmt)
            return dt_obj
        except ValueError:
            continue
            
    logger.warning(f"Archivo: {os.path.basename(xml_file_path_for_error)}, Campo: '{field_name}', "
                   f"Valor: '{fecha_str}'. No se pudo parsear la fecha con los formatos conocidos.")
    return None


def _parse_info_tributaria(info_trib_element: ET.Element) -> Dict[str, Any]:
    """Parses the infoTributaria section."""
    if info_trib_element is None:
        return {}
    return {
        'ambiente': _find_text_or_default(info_trib_element, './/{}ambiente'.format(ns.get('', '') or '')),
        'tipo_emision': _find_text_or_default(info_trib_element, './/{}tipoEmision'.format(ns.get('', '') or '')),
        'razon_social': _find_text_or_default(info_trib_element, './/{}razonSocial'.format(ns.get('', '') or '')),
        'nombre_comercial': _find_text_or_default(info_trib_element, './/{}nombreComercial'.format(ns.get('', '') or ''), default=_find_text_or_default(info_trib_element, './/{}razonSocial'.format(ns.get('', '') or ''))), # Default a razonSocial
        'ruc': _find_text_or_default(info_trib_element, './/{}ruc'.format(ns.get('', '') or '')),
        'clave_acceso': _find_text_or_default(info_trib_element, './/{}claveAcceso'.format(ns.get('', '') or '')),
        'cod_doc': _find_text_or_default(info_trib_element, './/{}codDoc'.format(ns.get('', '') or '')),
        'estab': _find_text_or_default(info_trib_element, './/{}estab'.format(ns.get('', '') or '')),
        'pto_emi': _find_text_or_default(info_trib_element, './/{}ptoEmi'.format(ns.get('', '') or '')),
        'secuencial': _find_text_or_default(info_trib_element, './/{}secuencial'.format(ns.get('', '') or '')),
        'dir_matriz': _find_text_or_default(info_trib_element, './/{}dirMatriz'.format(ns.get('', '') or '')),
        'agente_retencion_num_res': _find_text_or_default(info_trib_element, './/{}agenteRetencion'.format(ns.get('', '') or '')), # Para el número de resolución del agente de retención
    }

def _parse_comprador(doc_info_element: ET.Element) -> Dict[str, Any]:
    """Parses common buyer information from infoFactura, infoNotaDebito, etc."""
    if doc_info_element is None:
        return {}
    return {
        'tipo_identificacion': _find_text_or_default(doc_info_element, './/{}tipoIdentificacionComprador'.format(ns.get('', '') or '')),
        'razon_social': _find_text_or_default(doc_info_element, './/{}razonSocialComprador'.format(ns.get('', '') or '')),
        'identificacion': _find_text_or_default(doc_info_element, './/{}identificacionComprador'.format(ns.get('', '') or '')),
        'direccion': _find_text_or_default(doc_info_element, './/{}direccionComprador'.format(ns.get('', '') or '')), # Puede no estar en ND
        # Campos específicos de factura que podrían estar aquí o en infoAdicional
        'guia_remision': _find_text_or_default(doc_info_element, './/{}guiaRemision'.format(ns.get('', '') or '')),
        'placa': '', # Generalmente en infoAdicional, buscar allí si es necesario
    }

def _parse_totales_y_impuestos(doc_info_element: ET.Element, tag_impuestos_container: str, tag_impuesto_item: str) -> Dict[str, Any]:
    """Parses totals and the list of taxes (handles totalConImpuestos/impuestos)."""
    totales = {}
    if doc_info_element is None:
        return {'impuestos_resumen': []} # Devuelve lista vacía si no hay info

    totales['total_sin_impuestos'] = _find_text_or_default(doc_info_element, './/{}totalSinImpuestos'.format(ns.get('', '') or ''), default='0.0')
    totales['total_descuento'] = _find_text_or_default(doc_info_element, './/{}totalDescuento'.format(ns.get('', '') or ''), default='0.0') # Puede no estar en ND
    totales['propina'] = _find_text_or_default(doc_info_element, './/{}propina'.format(ns.get('', '') or ''), default='0.0') # Puede no estar en ND
    totales['importe_total'] = _find_text_or_default(doc_info_element, './/{}valorTotal'.format(ns.get('', '') or ''), default=_find_text_or_default(doc_info_element, './/{}importeTotal'.format(ns.get('', '') or ''), default='0.0')) # Usa valorTotal o importeTotal

    # --- Procesamiento de la lista de impuestos ---
    impuestos_resumen_list = []
    impuestos_container = doc_info_element.find('.//{}'.format(tag_impuestos_container))
    if impuestos_container is not None:
        # Usar tag_impuesto_item para encontrar los elementos individuales
        for imp_element in impuestos_container.findall('{}'.format(tag_impuesto_item)):
            impuesto_dict = {
                'codigo': _find_text_or_default(imp_element, '{}codigo'.format(ns.get('', '') or ''), default=''),
                'codigo_porcentaje': _find_text_or_default(imp_element, '{}codigoPorcentaje'.format(ns.get('', '') or ''), default=''),
                'base_imponible': _find_text_or_default(imp_element, '{}baseImponible'.format(ns.get('', '') or ''), default='0.0'),
                'tarifa': _find_text_or_default(imp_element, '{}tarifa'.format(ns.get('', '') or ''), default='0.0'),
                'valor': _find_text_or_default(imp_element, '{}valor'.format(ns.get('', '') or ''), default='0.0'),
                'valor_devolucion_iva': _find_text_or_default(imp_element, '{}valorDevolucionIva'.format(ns.get('', '') or ''), default='0.0') # Para Notas de Crédito
            }
            impuestos_resumen_list.append(impuesto_dict)

    totales['impuestos_resumen'] = impuestos_resumen_list
    return totales

def _parse_info_factura(info_factura_element: ET.Element) -> Dict[str, Any]:
    """Parses the infoFactura section."""
    if info_factura_element is None:
        return {}

    factura_info = {
        'fecha_emision': _find_text_or_default(info_factura_element, './/{}fechaEmision'.format(ns.get('', '') or '')),
        'dir_establecimiento': _find_text_or_default(info_factura_element, './/{}dirEstablecimiento'.format(ns.get('', '') or '')),
        'contribuyente_especial': _find_text_or_default(info_factura_element, './/{}contribuyenteEspecial'.format(ns.get('', '') or '')),
        'obligado_contabilidad': _find_text_or_default(info_factura_element, './/{}obligadoContabilidad'.format(ns.get('', '') or '')),
        'moneda': _find_text_or_default(info_factura_element, './/{}moneda'.format(ns.get('', '') or '')),
        # tipo_emision_doc no parece estándar, tipoEmision está en infoTributaria
        # 'tipo_emision_doc': _find_text_or_default(info_factura_element, './/{}tipoEmision'.format(ns.get('', '') or '')),
    }

    # Parse Pagos
    pagos_list = []
    pagos_element = info_factura_element.find('.//{}pagos'.format(ns.get('', '') or ''))
    if pagos_element is not None:
        for pago_element in pagos_element.findall('{}pago'.format(ns.get('', '') or '')):
            pago_data = {
                'forma_pago': _find_text_or_default(pago_element, '{}formaPago'.format(ns.get('', '') or '')),
                'total': _find_text_or_default(pago_element, '{}total'.format(ns.get('', '') or '')),
                'plazo': _find_text_or_default(pago_element, '{}plazo'.format(ns.get('', '') or ''), default=''),
                'unidad_tiempo': _find_text_or_default(pago_element, '{}unidadTiempo'.format(ns.get('', '') or ''), default='')
            }
            pagos_list.append(pago_data)
    factura_info['pagos'] = pagos_list

    return factura_info

def _parse_info_nota_debito(info_nd_element: ET.Element) -> Dict[str, Any]:
    """Parses the infoNotaDebito section."""
    if info_nd_element is None:
        return {}

    nd_info = {
        'fecha_emision': _find_text_or_default(info_nd_element, './/{}fechaEmision'.format(ns.get('', '') or '')),
        'dir_establecimiento': _find_text_or_default(info_nd_element, './/{}dirEstablecimiento'.format(ns.get('', '') or '')), # Puede no existir
        'cod_doc_modificado': _find_text_or_default(info_nd_element, './/{}codDocModificado'.format(ns.get('', '') or '')),
        'num_doc_modificado': _find_text_or_default(info_nd_element, './/{}numDocModificado'.format(ns.get('', '') or '')),
        'fecha_emision_doc_sustento': _find_text_or_default(info_nd_element, './/{}fechaEmisionDocSustento'.format(ns.get('', '') or '')),
        'obligado_contabilidad': _find_text_or_default(info_nd_element, './/{}obligadoContabilidad'.format(ns.get('', '') or '')), # No estándar en ND, pero lo buscamos
        # No hay sección 'pagos' en Nota de Débito
    }
    return nd_info

def _parse_info_nota_credito(info_nc_element: ET.Element) -> Dict[str, Any]:
    """Parses the infoNotaCredito section."""
    if info_nc_element is None:
        return {}

    nc_info = {
        'fecha_emision': _find_text_or_default(info_nc_element, './/{}fechaEmision'.format(ns.get('', '') or '')),
        'dir_establecimiento': _find_text_or_default(info_nc_element, './/{}dirEstablecimiento'.format(ns.get('', '') or '')), # Puede no existir
        'tipo_identificacion_comprador': _find_text_or_default(info_nc_element, './/{}tipoIdentificacionComprador'.format(ns.get('', '') or '')), # NC tiene info del comprador aquí
        'razon_social_comprador': _find_text_or_default(info_nc_element, './/{}razonSocialComprador'.format(ns.get('', '') or '')),
        'identificacion_comprador': _find_text_or_default(info_nc_element, './/{}identificacionComprador'.format(ns.get('', '') or '')),
        'obligado_contabilidad': _find_text_or_default(info_nc_element, './/{}obligadoContabilidad'.format(ns.get('', '') or '')),
        'cod_doc_modificado': _find_text_or_default(info_nc_element, './/{}codDocModificado'.format(ns.get('', '') or '')),
        'num_doc_modificado': _find_text_or_default(info_nc_element, './/{}numDocModificado'.format(ns.get('', '') or '')),
        'fecha_emision_doc_sustento': _find_text_or_default(info_nc_element, './/{}fechaEmisionDocSustento'.format(ns.get('', '') or '')),
        'moneda': _find_text_or_default(info_nc_element, './/{}moneda'.format(ns.get('', '') or '')),
        'motivo': _find_text_or_default(info_nc_element, './/{}motivo'.format(ns.get('', '') or '')), # Motivo de la NC
        'valorModificacion': _find_text_or_default(info_nc_element, './/{}valorModificacion'.format(ns.get('', '') or ''), default='0.0'), # Campo clave para el total de NC
        'contribuyente_especial': _find_text_or_default(info_nc_element, './/{}contribuyenteEspecial'.format(ns.get('', '') or '')), # Añadido para NC
    }
    return nc_info

def _parse_info_retencion(info_ret_element: ET.Element) -> Dict[str, Any]:
    """Parses the infoCompRetencion section."""
    if info_ret_element is None:
        return {}

    ret_info = {
        'fecha_emision': _find_text_or_default(info_ret_element, './/{}fechaEmision'.format(ns.get('', '') or '')),
        'dir_establecimiento': _find_text_or_default(info_ret_element, './/{}dirEstablecimiento'.format(ns.get('', '') or '')), # Puede no existir
        'obligado_contabilidad': _find_text_or_default(info_ret_element, './/{}obligadoContabilidad'.format(ns.get('', '') or '')),
        'tipo_identificacion_sujeto_retenido': _find_text_or_default(info_ret_element, './/{}tipoIdentificacionSujetoRetenido'.format(ns.get('', '') or '')),
        'razon_social_sujeto_retenido': _find_text_or_default(info_ret_element, './/{}razonSocialSujetoRetenido'.format(ns.get('', '') or '')),
        'identificacion_sujeto_retenido': _find_text_or_default(info_ret_element, './/{}identificacionSujetoRetenido'.format(ns.get('', '') or '')),
        'periodo_fiscal': _find_text_or_default(info_ret_element, './/{}periodoFiscal'.format(ns.get('', '') or '')),
    }
    return ret_info

def _parse_detalles(detalles_container: ET.Element) -> List[Dict[str, Any]]:
    """Parses the detalles section (for Factura and Nota de Crédito)."""
    logger.debug(f"_parse_detalles: Recibido detalles_container: {detalles_container is not None}")
    items = []
    if detalles_container is None:
        logger.debug("_parse_detalles: detalles_container es None, devolviendo lista vacía.")
        return items
    # Usar findall directo sobre el contenedor para los hijos 'detalle'
    for det_element in detalles_container.findall('{}detalle'.format(ns.get('', '') or '')):
        # Para detalles de Factura, Nota de Crédito
        ns_map = {'': ns.get('', '')} if ns.get('', '') else {}
        item = {
            'codigo_principal': _find_text_or_default(det_element, './/{}codigoPrincipal'.format(ns.get('', '') or ''), default=None), # Intentar primero codigoPrincipal
            'codigo_auxiliar': _find_text_or_default(det_element, './/{}codigoAuxiliar'.format(ns.get('', '') or '')),
            'descripcion': _find_text_or_default(det_element, './/{}descripcion'.format(ns.get('', '') or '')),
            'cantidad': _find_text_or_default(det_element, './/{}cantidad'.format(ns.get('', '') or ''), default='0'),
            'precio_unitario': _find_text_or_default(det_element, './/{}precioUnitario'.format(ns.get('', '') or ''), default='0.0'),
            'descuento': _find_text_or_default(det_element, './/{}descuento'.format(ns.get('', '') or ''), default='0.0'),
            'precio_total_sin_impuesto': _find_text_or_default(det_element, './/{}precioTotalSinImpuesto'.format(ns.get('', '') or ''), default='0.0'),
            'detalles_adicionales': {},
            'impuestos_detalle': []
        }
        logger.debug(f"_parse_detalles: Encontrado elemento detalle, datos iniciales: {item}")
        # Si codigoPrincipal no se encontró o está vacío, intentar con codigoInterno
        if not item['codigo_principal']:
            item['codigo_principal'] = _find_text_or_default(det_element, './/{}codigoInterno'.format(ns.get('', '') or ''))

        # Detalles Adicionales del item
        det_adicionales_element = det_element.find('.//{}detallesAdicionales'.format(ns.get('', '') or ''))
        if det_adicionales_element is not None:
            for adic_element in det_adicionales_element.findall('.//{}detAdicional'.format(ns.get('', '') or '')):
                nombre = adic_element.get('nombre', '').replace(' ', '_').lower() # Normalizar nombre
                valor = adic_element.get('valor', adic_element.text.strip() if adic_element.text else '') # SRI a veces usa atributo 'valor'
                if nombre and valor:
                    # Manejar nombres duplicados si es necesario (ej. concatenar)
                    if nombre in item['detalles_adicionales']:
                        item['detalles_adicionales'][nombre] = f"{item['detalles_adicionales'][nombre]}; {valor}"
                    else:
                        item['detalles_adicionales'][nombre] = valor
            logger.debug(f"_parse_detalles: Detalles adicionales para item: {item['detalles_adicionales']}")

        # Parsear impuestos del detalle (si es necesario para la tabla, aunque usualmente no se muestran directamente)
        impuestos_detalle_element = det_element.find('.//{}impuestos'.format(ns.get('', '') or ''))
        if impuestos_detalle_element is not None:
            for imp_det_element in impuestos_detalle_element.findall('.//{}impuesto'.format(ns.get('', '') or '')):
                impuesto_item_detalle = {
                    'codigo': _find_text_or_default(imp_det_element, './/{}codigo'.format(ns.get('', '') or '')),
                    'codigoPorcentaje': _find_text_or_default(imp_det_element, './/{}codigoPorcentaje'.format(ns.get('', '') or '')),
                    # ... otros campos del impuesto del detalle si son necesarios
                }
                item['impuestos_detalle'].append(impuesto_item_detalle)
        items.append(item) # Asegurar que el item se añade a la lista
    logger.debug(f"_parse_detalles: Total items parseados: {len(items)}")
    return items

def _parse_motivos(motivos_container: ET.Element) -> List[Dict[str, Any]]:
    """Parses the motivos section (for Nota de Débito)."""
    items = []
    if motivos_container is None:
        return items
    for mot_element in motivos_container.findall('.//{}motivo'.format(ns.get('', '') or '')):
        item = {
            # Adaptar nombres para que coincidan con 'detalles' si es posible para pdf_generator
            'descripcion': _find_text_or_default(mot_element, './/{}razon'.format(ns.get('', '') or '')),
            'precio_total_sin_impuesto': _find_text_or_default(mot_element, './/{}valor'.format(ns.get('', '') or ''), default='0.0'),
            # Añadir campos vacíos para compatibilidad con estructura de detalles si es necesario
            'codigo_principal': '',
            'codigo_auxiliar': '',
            'cantidad': '1', # Asumir cantidad 1 para motivos
            'precio_unitario': _find_text_or_default(mot_element, './/{}valor'.format(ns.get('', '') or ''), default='0.0'), # Asumir valor como precio unitario
            'descuento': '0.0',
            'detalles_adicionales': {},
            'impuestos_detalle': [] # Los impuestos del motivo no están aquí, están en infoNotaDebito/impuestos
        }
        items.append(item)
    return items

def _parse_impuestos_retencion(comprobante_retencion_root: ET.Element) -> List[Dict[str, Any]]:
    """
    Parses the retentions from a comprobanteRetencion XML, handling v1.0.0 and v2.0.0.
    For v2.0.0: docsSustento -&gt; docSustento -&gt; retenciones -&gt; retencion
    For v1.0.0: impuestos -&gt; impuesto
    """
    items = []
    if comprobante_retencion_root is None:
        return items

    ns_map = {'ns': ns.get('', '') or ''} # Helper para namespaces si es necesario, aunque findall con {} funciona
    version_cr = comprobante_retencion_root.get('version', '1.0.0') # Default a 1.0.0 si no hay atributo

    if version_cr == '2.0.0':
        docs_sustento_container = comprobante_retencion_root.find('.//{}docsSustento'.format(ns_map['ns']))
        if docs_sustento_container is not None:
            for doc_sustento_element in docs_sustento_container.findall('.//{}docSustento'.format(ns_map['ns'])):
                cod_doc_sustento_padre = _find_text_or_default(doc_sustento_element, './/{}codDocSustento'.format(ns_map['ns']))
                num_doc_sustento_padre = _find_text_or_default(doc_sustento_element, './/{}numDocSustento'.format(ns_map['ns']))
                fecha_emision_doc_sustento_padre = _find_text_or_default(doc_sustento_element, './/{}fechaEmisionDocSustento'.format(ns_map['ns']))
                num_aut_doc_sustento_padre = _find_text_or_default(doc_sustento_element, './/{}numAutDocSustento'.format(ns_map['ns'])) # Nuevo

                retenciones_container = doc_sustento_element.find('.//{}retenciones'.format(ns_map['ns']))
                if retenciones_container is not None:
                    for ret_element in retenciones_container.findall('.//{}retencion'.format(ns_map['ns'])):
                        item = {
                            'codigo': _find_text_or_default(ret_element, './/{}codigo'.format(ns_map['ns'])),
                            'codigo_retencion': _find_text_or_default(ret_element, './/{}codigoRetencion'.format(ns_map['ns'])),
                            'base_imponible': _find_text_or_default(ret_element, './/{}baseImponible'.format(ns_map['ns']), default='0.0'),
                            'porcentaje_retener': _find_text_or_default(ret_element, './/{}porcentajeRetener'.format(ns_map['ns']), default='0.0'),
                            'valor_retenido': _find_text_or_default(ret_element, './/{}valorRetenido'.format(ns_map['ns']), default='0.0'),
                            'cod_doc_sustento': cod_doc_sustento_padre,
                            'num_doc_sustento': num_doc_sustento_padre,
                            'num_aut_doc_sustento': num_aut_doc_sustento_padre, # Nuevo
                            'fecha_emision_doc_sustento': fecha_emision_doc_sustento_padre,
                            'descripcion': f"Ret. Cód.{_find_text_or_default(ret_element, './/{}codigoRetencion'.format(ns_map['ns']))} ({_find_text_or_default(ret_element, './/{}porcentajeRetener'.format(ns_map['ns']), default='0.0')}%) Doc: {num_doc_sustento_padre}",
                            'precio_total_sin_impuesto': _find_text_or_default(ret_element, './/{}valorRetenido'.format(ns_map['ns']), default='0.0'),
                            'cantidad': '1',
                            'precio_unitario': _find_text_or_default(ret_element, './/{}valorRetenido'.format(ns_map['ns']), default='0.0'),
                        }
                        items.append(item)
    elif version_cr == '1.0.0':
        impuestos_container = comprobante_retencion_root.find('.//{}impuestos'.format(ns_map['ns']))
        if impuestos_container is not None:
            for imp_element in impuestos_container.findall('.//{}impuesto'.format(ns_map['ns'])): # En v1.0.0, cada &lt;impuesto&gt; es una retención
                item = {
                    'codigo': _find_text_or_default(imp_element, './/{}codigo'.format(ns_map['ns'])),
                    'codigo_retencion': _find_text_or_default(imp_element, './/{}codigoRetencion'.format(ns_map['ns'])),
                    'base_imponible': _find_text_or_default(imp_element, './/{}baseImponible'.format(ns_map['ns']), default='0.0'),
                    'porcentaje_retener': _find_text_or_default(imp_element, './/{}porcentajeRetener'.format(ns_map['ns']), default='0.0'),
                    'valor_retenido': _find_text_or_default(imp_element, './/{}valorRetenido'.format(ns_map['ns']), default='0.0'),
                    'cod_doc_sustento': _find_text_or_default(imp_element, './/{}codDocSustento'.format(ns_map['ns'])),
                    'num_doc_sustento': _find_text_or_default(imp_element, './/{}numDocSustento'.format(ns_map['ns'])),
                    'num_aut_doc_sustento': _find_text_or_default(imp_element, './/{}numAutDocSustento'.format(ns_map['ns'])), # Nuevo (aunque menos común en v1)
                    'fecha_emision_doc_sustento': _find_text_or_default(imp_element, './/{}fechaEmisionDocSustento'.format(ns_map['ns'])),
                    'descripcion': f"Ret. Cód.{_find_text_or_default(imp_element, './/{}codigoRetencion'.format(ns_map['ns']))} ({_find_text_or_default(imp_element, './/{}porcentajeRetener'.format(ns_map['ns']), default='0.0')}%) Doc: {_find_text_or_default(imp_element, './/{}numDocSustento'.format(ns_map['ns']))}",
                    'precio_total_sin_impuesto': _find_text_or_default(imp_element, './/{}valorRetenido'.format(ns_map['ns']), default='0.0'),
                    'cantidad': '1',
                    'precio_unitario': _find_text_or_default(imp_element, './/{}valorRetenido'.format(ns_map['ns']), default='0.0'),
                }
                items.append(item)
    else:
        logger.warning(f"Versión de comprobanteRetencion no manejada en xml_parser: {version_cr}")

    return items

def _parse_info_adicional(info_adic_element: ET.Element) -> Dict[str, Any]:
    """Parses the infoAdicional section."""
    adicional = {}
    if info_adic_element is None:
        return adicional
    for campo_element in info_adic_element.findall('.//{}campoAdicional'.format(ns.get('', '') or '')):
        nombre = campo_element.get('nombre', '').replace(' ', '_').lower() # Normalizar nombre
        valor = campo_element.text.strip() if campo_element.text else ''
        valor_raw = campo_element.text.strip() if campo_element.text else ''
        # Aplicar el reemplazo del EN DASH también aquí
        valor = valor_raw.replace('\u2013', '-')

        if nombre and valor:
            # Manejar nombres duplicados si es necesario (ej. concatenar)
            if nombre in adicional:
                adicional[nombre] = f"{adicional[nombre]}; {valor}"
            else:
                adicional[nombre] = valor
    return adicional

def parse_xml(xml_path: str) -> Optional[Dict[str, Any]]:
    """
    Parses an XML authorization file from the SRI (Factura, Nota de Débito, etc.).

    Args:
        xml_path: The path to the XML file.

    Returns:
        A dictionary containing the parsed data, or None if parsing fails.
    """
    if not os.path.exists(xml_path): # Mantener este print para feedback inmediato si el archivo no existe
        logger.error(f"Archivo XML no encontrado en {xml_path}")
        return None

    try:
        # Parsear el archivo de autorización principal
        auth_tree = ET.parse(xml_path)
        auth_root = auth_tree.getroot()

        parsed_data = {
            'estado': _find_text_or_default(auth_root, './/{}estado'.format(ns.get('', '') or '')),
            'numero_autorizacion': _find_text_or_default(auth_root, './/{}numeroAutorizacion'.format(ns.get('', '') or '')),
            'fecha_autorizacion': _find_text_or_default(auth_root, './/{}fechaAutorizacion'.format(ns.get('', '') or '')),
            'fecha_autorizacion_dt': None, # Inicializar como None
            'ambiente': _find_text_or_default(auth_root, './/{}ambiente'.format(ns.get('', '') or '')),
            'mensajes': [], # TODO: Parsear mensajes si existen
            # Inicializar secciones principales
            'info_tributaria': {},
            'comprador': {},
            'doc_especifico': {}, # Contendrá infoFactura o infoNotaDebito, etc.
            'totales': {},
            'detalles': [], # Usaremos 'detalles' como clave genérica para items/motivos
            'impuestos_retencion': [], # Específico para retenciones
            'info_adicional': {},
            'tipo_documento': 'Desconocido', # Se determinará por codDoc
            'doc_modificado': {} # Para Notas de Crédito/Débito
        }

        # Intentar parsear fecha_autorizacion a datetime
        fecha_auth_str = parsed_data.get('fecha_autorizacion')
        parsed_data['fecha_autorizacion_dt'] = _parse_fecha(fecha_auth_str, xml_path, "fechaAutorizacion (principal)")


        # Encontrar el comprobante dentro del CDATA
        comprobante_cdata = auth_root.findtext('.//{}comprobante'.format(ns.get('', '') or ''))
        if not comprobante_cdata:
            logger.error(f"No se encontró la sección <comprobante> o está vacía en {xml_path}")
            return None

        # Limpiar posible BOM (Byte Order Mark) al inicio del CDATA
        comprobante_cdata = comprobante_cdata.lstrip('\ufeff')

        # Parsear el XML del comprobante
        comprobante_root = ET.fromstring(comprobante_cdata)

        # 1. Parsear InfoTributaria
        info_trib_element = comprobante_root.find('.//{}infoTributaria'.format(ns.get('', '') or ''))
        parsed_data['info_tributaria'] = _parse_info_tributaria(info_trib_element)

        # Determinar tipo de documento
        cod_doc = parsed_data['info_tributaria'].get('cod_doc')
        doc_info_element = None
        comprador_id_raw = "N/A" # ID sin procesar para la lógica de entidad
        detalles_motivos_element = None
        tag_impuestos_container = ''
        tag_impuesto_item = ''

        if cod_doc == '01': # Factura
            parsed_data['tipo_documento'] = 'Factura'
            doc_info_element = comprobante_root.find('.//{}infoFactura'.format(ns.get('', '') or ''))
            parsed_data['doc_especifico'] = _parse_info_factura(doc_info_element)
            logger.debug("Parseando detalles para Factura...")
            detalles_motivos_element = comprobante_root.find('.//{}detalles'.format(ns.get('', '') or ''))
            parsed_data['detalles'] = _parse_detalles(detalles_motivos_element)
            tag_impuestos_container = 'totalConImpuestos'
            tag_impuesto_item = 'totalImpuesto'
            if doc_info_element is not None:
                comprador_id_raw = _find_text_or_default(doc_info_element, './/{}identificacionComprador'.format(ns.get('', '') or ''))
        elif cod_doc == '05': # Nota de Débito
            parsed_data['tipo_documento'] = 'Nota de Débito'
            doc_info_element = comprobante_root.find('.//{}infoNotaDebito'.format(ns.get('', '') or ''))
            parsed_data['doc_especifico'] = _parse_info_nota_debito(doc_info_element)
            logger.debug("Parseando motivos para Nota de Débito...")
            detalles_motivos_element = comprobante_root.find('.//{}motivos'.format(ns.get('', '') or ''))
            parsed_data['detalles'] = _parse_motivos(detalles_motivos_element) # Usa parser de motivos
            tag_impuestos_container = 'impuestos' # Diferente tag en ND
            tag_impuesto_item = 'impuesto'      # Diferente tag en ND
            # Extraer info del documento modificado
            parsed_data['doc_modificado'] = {
                'cod_doc': parsed_data['doc_especifico'].get('cod_doc_modificado', ''),
                'num_doc': parsed_data['doc_especifico'].get('num_doc_modificado', ''),
                'fecha_emision': parsed_data['doc_especifico'].get('fecha_emision_doc_sustento', '')
            }
            if doc_info_element is not None:
                comprador_id_raw = _find_text_or_default(doc_info_element, './/{}identificacionComprador'.format(ns.get('', '') or ''))
        elif cod_doc == '04': # Nota de Crédito
            parsed_data['tipo_documento'] = 'Nota de Crédito'
            doc_info_element = comprobante_root.find('.//{}infoNotaCredito'.format(ns.get('', '') or '')) # Asumiendo 'infoNotaCredito'
            parsed_data['doc_especifico'] = _parse_info_nota_credito(doc_info_element)
            logger.debug("Parseando detalles para Nota de Crédito...")
            detalles_motivos_element = comprobante_root.find('.//{}detalles'.format(ns.get('', '') or '')) # Asumiendo 'detalles' como en factura
            parsed_data['detalles'] = _parse_detalles(detalles_motivos_element) # Reutiliza el parser de detalles de factura
            tag_impuestos_container = 'totalConImpuestos' # Asumiendo como en factura
            tag_impuesto_item = 'totalImpuesto'       # Asumiendo como en factura
            parsed_data['doc_modificado'] = { # Información del documento que modifica
                'cod_doc': parsed_data['doc_especifico'].get('cod_doc_modificado', ''),
                'num_doc': parsed_data['doc_especifico'].get('num_doc_modificado', ''),
                'fecha_emision': parsed_data['doc_especifico'].get('fecha_emision_doc_sustento', '')
            }
            if doc_info_element is not None: # NC tiene identificacionComprador dentro de infoNotaCredito
                comprador_id_raw = _find_text_or_default(doc_info_element, './/{}identificacionComprador'.format(ns.get('', '') or ''))
        elif cod_doc == '07': # Comprobante de Retención
            parsed_data['tipo_documento'] = 'Comprobante de Retención'
            doc_info_element = comprobante_root.find('.//{}infoCompRetencion'.format(ns.get('', '') or ''))
            parsed_data['doc_especifico'] = _parse_info_retencion(doc_info_element)
            logger.debug("Parseando impuestos para Comprobante de Retención...")
            # Pasar el comprobante_root a _parse_impuestos_retencion para que pueda determinar la versión
            parsed_data['impuestos_retencion'] = _parse_impuestos_retencion(comprobante_root) # Guardar en su propia clave
            parsed_data['detalles'] = parsed_data['impuestos_retencion'] # También en 'detalles' para consistencia si se usa genéricamente
            if doc_info_element is not None:
                comprador_id_raw = _find_text_or_default(doc_info_element, './/{}identificacionSujetoRetenido'.format(ns.get('', '') or ''))
            # No hay 'totalConImpuestos' o 'impuestos' a nivel de totales como en Factura/ND
        elif cod_doc: # Si hay cod_doc pero no es uno de los conocidos
            logger.warning(f"Tipo de documento '{cod_doc}' no soportado completamente en {xml_path}.")
            # Intentar parsear genéricamente si es posible o devolver error/parcial
            # Por ahora, dejamos doc_info_element as None

        if doc_info_element is None and cod_doc not in ['01', '04', '05', '07']: # Si no es Factura, NC, ND o Ret y no se encontró info específica
             logger.error(f"No se encontró la sección de información específica para el documento {cod_doc} en {xml_path}.")
             # Podrías intentar buscar elementos comunes si existen
        elif doc_info_element is not None:
             # 2. Parsear Comprador (desde el elemento de info específico o campos directos en NC)
             # Para retenciones, el "comprador" es el "sujetoRetenido" (usar función específica)
             if cod_doc == '07':
                 parsed_data['comprador'] = _parse_comprador_retencion(doc_info_element)
             else:
                 parsed_data['comprador'] = _parse_comprador(doc_info_element)

             # 3. Parsear Totales e Impuestos (desde el elemento de info específico) - No aplica directamente a Retención de la misma forma
             parsed_data['totales'] = _parse_totales_y_impuestos(doc_info_element, tag_impuestos_container, tag_impuesto_item)
             
        # 4. Parsear InfoAdicional
        info_adic_element = comprobante_root.find('.//{}infoAdicional'.format(ns.get('', '') or ''))
        parsed_data['info_adicional'] = _parse_info_adicional(info_adic_element)

        # Si numeroAutorizacion no está en el XML principal, intentar obtenerlo de claveAcceso
        if not parsed_data['numero_autorizacion'] and parsed_data['info_tributaria'].get('clave_acceso'):
            parsed_data['numero_autorizacion'] = parsed_data['info_tributaria']['clave_acceso']
            logger.debug(f"Usando claveAcceso como número de autorización para {os.path.basename(xml_path)}.")



        # --- Consolidar datos para la salida ---
        # Mover algunos datos a niveles superiores para facilitar acceso en pdf_generator
        # Emisor (combinando infoTributaria y doc_especifico)
        parsed_data['emisor'] = {
            **parsed_data['info_tributaria'], # Copia todo de infoTributaria
            'dir_establecimiento': parsed_data['doc_especifico'].get('dir_establecimiento', parsed_data['info_tributaria'].get('dir_matriz')), # Usa dirEstablecimiento si existe, sino dirMatriz
            'contribuyente_especial': parsed_data['doc_especifico'].get('contribuyente_especial', ''),
            'obligado_contabilidad': parsed_data['doc_especifico'].get('obligado_contabilidad', ''),
            'agente_retencion_num_res': parsed_data['info_tributaria'].get('agente_retencion_num_res', ''), # Aseguramos que se copie a emisor
        } # Eliminado 'logo_path': None

        # Factura Info (para mantener compatibilidad con código PDF existente)
        # Copiar datos relevantes a una clave 'factura_info' aunque sea ND
        # Esto simplifica el código del PDF que espera 'factura_info'
        parsed_data['factura_info'] = {
            'numero_factura': f"{parsed_data['info_tributaria'].get('estab', '')}-{parsed_data['info_tributaria'].get('pto_emi', '')}-{parsed_data['info_tributaria'].get('secuencial', '')}",
            'fecha_emision': parsed_data['doc_especifico'].get('fecha_emision', ''),
            'clave_acceso': parsed_data['info_tributaria'].get('clave_acceso', ''),
            'tipo_emision_doc': parsed_data['info_tributaria'].get('tipo_emision', ''), # Usar el de infoTributaria
            'pagos': parsed_data['doc_especifico'].get('pagos', []) # Estará vacío para ND
        }

        # Añadir el ID "raw" del comprador para la lógica de selección de entidad
        parsed_data['id_comprador_raw'] = comprador_id_raw
        
        # Consolidar el ID de display para la GUI
        if parsed_data['comprador'] and parsed_data['comprador'].get('identificacion'):
            parsed_data['id_comprador_display'] = parsed_data['comprador']['identificacion']
        # No necesitamos un else aquí, ya que id_comprador_display se inicializaría a "N/A"
        # si 'comprador' o 'identificacion' no existen, debido a _parse_comprador.
        # Si comprador_id_raw es "N/A", id_comprador_display también lo será.

        logger.debug(f"Parseo de {os.path.basename(xml_path)} ({parsed_data['tipo_documento']}) completado. Detalles encontrados: {len(parsed_data.get('detalles', []))}")
        return parsed_data

    except ET.ParseError as e: # Mantener este print para feedback inmediato si el XML está mal formado
        logger.error(f"Error de parseo XML en {os.path.basename(xml_path)}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Error inesperado durante el parseo de {xml_path}")
        # logger.exception ya incluye el traceback
        return None

def _parse_comprador_retencion(info_ret_element: ET.Element) -> Dict[str, Any]:
    """Parses subject information for Retenciones (similar to buyer)."""
    if info_ret_element is None:
        return {}
    return {
        'tipo_identificacion': _find_text_or_default(info_ret_element, './/{}tipoIdentificacionSujetoRetenido'.format(ns.get('', '') or '')),
        'razon_social': _find_text_or_default(info_ret_element, './/{}razonSocialSujetoRetenido'.format(ns.get('', '') or '')),
        'identificacion': _find_text_or_default(info_ret_element, './/{}identificacionSujetoRetenido'.format(ns.get('', '') or '')),
        'direccion': '', # Dirección del sujeto retenido no es un campo estándar aquí
        'guia_remision': '', # No aplica
        'placa': '', # No aplica
    }

# --- Funciones de ayuda para extraer datos específicos para la tabla de la GUI ---
# Estas funciones se usan en el WorkerThread de main_window.py para poblar la tabla.

def extract_header_data(parsed_xml_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extrae datos del encabezado para la GUI desde el XML ya parseado."""
    if not parsed_xml_data:
        return None
    return {
        "id_comprador": parsed_xml_data.get('id_comprador_display', "N/A"),
        "id_comprador_raw": parsed_xml_data.get('id_comprador_raw', "N/A"),
        "razon_social_comprador": parsed_xml_data.get('comprador', {}).get('razon_social', "N/A"),
        "cod_doc": parsed_xml_data.get('info_tributaria', {}).get('cod_doc', "N/A")
    }

def get_unique_identifier(parsed_xml_data: Dict[str, Any]) -> Optional[str]:
    """Obtiene el número de autorización o clave de acceso del XML ya parseado."""
    if not parsed_xml_data:
        return None
    num_auth = parsed_xml_data.get('numero_autorizacion')
    if num_auth and num_auth.strip(): # Asegurar que no sea cadena vacía
        return num_auth
    
    clave_acceso = parsed_xml_data.get('info_tributaria', {}).get('clave_acceso')
    if clave_acceso and clave_acceso.strip():
        return clave_acceso
        
    logger.warning(f"No se pudo obtener un identificador único (Nro. Autorización/Clave Acceso) desde parsed_data.")
    return None


def extract_data_from_xml(parsed_xml_data: Dict[str, Any], xml_file_path: str, cod_doc_filter: str, entity_id_filter: str, conversion_errors_list: List[str]) -> Optional[Dict[str, Any]]:
    """
    Extrae los datos necesarios para una fila de la tabla de la GUI,
    a partir del diccionario de datos ya parseado del XML.
    """
    if not parsed_xml_data:
        return None # No se puede extraer datos si no hay datos parseados

    # No necesitamos filtrar aquí, el WorkerThread ya filtra los archivos antes de llamar a esta función.
    # Esta función asume que los datos de entrada son para la entidad y tipo de documento correctos.

    row_data: Dict[str, Any] = {}

    # Inicializar el diccionario con todas las claves esperadas y valores por defecto
    for field_name in ALL_CSV_FIELDS:
        # Usar cadena vacía como default para la mayoría, 0.0 para campos numéricos esperados
        if any(num_field in field_name for num_field in ["Base", "Monto", "Total", "Descuento", "Propina", "Ret.", "Devol.", "Valor", "Porcentaje"]):
             row_data[field_name] = 0.0 # Usar float 0.0 para cálculos posteriores si es necesario
        else:
             row_data[field_name] = ""

    # Rellenar con datos parseados
    info_trib = parsed_xml_data.get('info_tributaria', {})
    doc_especifico = parsed_xml_data.get('doc_especifico', {})
    comprador = parsed_xml_data.get('comprador', {})
    totales = parsed_xml_data.get('totales', {})
    impuestos_resumen = totales.get('impuestos_resumen', [])
    detalles_list = parsed_xml_data.get('detalles', []) # Puede ser items o motivos
    impuestos_retencion_list = parsed_xml_data.get('impuestos_retencion', []) # Específico para retenciones

    row_data["CodDoc"] = info_trib.get('cod_doc', 'N/A')
    row_data["Fecha"] = doc_especifico.get('fecha_emision', 'N/A')
    row_data["RUC Emisor"] = info_trib.get('ruc', 'N/A')
    row_data["Razón Social Emisor"] = info_trib.get('razon_social', 'N/A')
    row_data["Nro.Secuencial"] = f"{info_trib.get('estab', '')}-{info_trib.get('pto_emi', '')}-{info_trib.get('secuencial', '')}"
    tipo_id_comprador_code = comprador.get('tipo_identificacion', 'N/A')

    # Para Retenciones, el "comprador" es el sujeto retenido.
    if row_data["CodDoc"] == '07':
        row_data["Id.Sujeto Retenido"] = comprador.get('identificacion', 'N/A')
        row_data["Razón Social Sujeto Retenido"] = comprador.get('razon_social', 'N/A')
    
    if row_data["CodDoc"] == '01': # Si es Factura
        row_data["TipoId."] = tipo_id_comprador_code # Usar el código directamente
    else: # Para otros tipos de documentos
        row_data["TipoId."] = TIPO_IDENTIFICACION_MAP.get(tipo_id_comprador_code, tipo_id_comprador_code) # Usar el mapa
    row_data["Id.Comprador"] = comprador.get('identificacion', 'N/A')
    row_data["Razón Social Comprador"] = comprador.get('razon_social', 'N/A')

    # Formas de Pago (principalmente para Factura)
    pagos_list = doc_especifico.get('pagos', [])
    if pagos_list:
        formas_pago_str = ", ".join([pago.get('forma_pago', '') for pago in pagos_list if pago.get('forma_pago')])
        row_data["Formas de Pago"] = formas_pago_str

    # Campos específicos de NC
    if row_data["CodDoc"] == '04':
        doc_modificado = parsed_xml_data.get('doc_modificado', {})
        row_data["Fecha D.M."] = doc_modificado.get('fecha_emision', '')
        row_data["CodDocMod"] = doc_modificado.get('cod_doc', '')
        row_data["Num.Doc.Modificado"] = doc_modificado.get('num_doc', '')
        row_data["Valor Mod."] = _safe_float_conversion(doc_especifico.get('valorModificacion'), 0.0, xml_file_path, "NC Valor Modificacion", conversion_errors_list)

    # Descuento (principalmente Factura, NC)
    row_data["Descuento"] = _safe_float_conversion(totales.get('total_descuento'), 0.0, xml_file_path, "Total Descuento", conversion_errors_list)

    # Total Sin Impuestos (Factura, ND, NC, LiqCompra)
    row_data["Total Sin Impuestos"] = _safe_float_conversion(totales.get('total_sin_impuestos'), 0.0, xml_file_path, "Total Sin Impuestos", conversion_errors_list)

    # Bases y Montos de Impuestos (IVA, ICE, IRBPNR)
    total_monto_iva = 0.0
    for imp in impuestos_resumen:
        codigo = imp.get('codigo')
        codigo_porcentaje = imp.get('codigo_porcentaje')
        base_imponible = _safe_float_conversion(imp.get('base_imponible'), 0.0, xml_file_path, f"Impuesto Resumen ({codigo}/{codigo_porcentaje}) Base Imponible", conversion_errors_list)
        valor_impuesto = _safe_float_conversion(imp.get('valor'), 0.0, xml_file_path, f"Impuesto Resumen ({codigo}/{codigo_porcentaje}) Valor", conversion_errors_list)
        valor_devolucion = _safe_float_conversion(imp.get('valor_devolucion_iva'), 0.0, xml_file_path, f"Impuesto Resumen ({codigo}/{codigo_porcentaje}) Valor Devolucion IVA", conversion_errors_list)

        if codigo == '2': # IVA
            total_monto_iva += valor_impuesto # Sumar todos los valores de IVA
            if codigo_porcentaje == '0': row_data["Base IVA 0%"] += base_imponible
            elif codigo_porcentaje == '2': row_data["Base IVA 12%"] += base_imponible
            elif codigo_porcentaje in ['3', '4']: row_data["Base IVA 15%"] += base_imponible # SRI usa 3 o 4 para 15%
            elif codigo_porcentaje == '5': row_data["Base IVA 5%"] += base_imponible
            elif codigo_porcentaje == '6':
                # Asegurar que el valor actual sea numérico antes de sumar
                current_val_no_obj = row_data.get("No Objeto IVA", 0.0)
                if isinstance(current_val_no_obj, str):
                    current_val_no_obj = _safe_float_conversion(current_val_no_obj, 0.0, xml_file_path, "Acumulado No Objeto IVA", conversion_errors_list)
                row_data["No Objeto IVA"] = current_val_no_obj + base_imponible
            elif codigo_porcentaje == '7':
                # Asegurar que el valor actual sea numérico antes de sumar
                current_val_exento = row_data.get("Exento IVA", 0.0)
                if isinstance(current_val_exento, str):
                    current_val_exento = _safe_float_conversion(current_val_exento, 0.0, xml_file_path, "Acumulado Exento IVA", conversion_errors_list)
                row_data["Exento IVA"] = current_val_exento + base_imponible
            elif codigo_porcentaje == '8': row_data["Base IVA 8%"] += base_imponible
            elif codigo_porcentaje == '10': row_data["Base IVA 13%"] += base_imponible # Aunque 13% es raro, lo incluimos si aparece

            row_data["Devol. IVA"] += valor_devolucion # Sumar devoluciones de IVA

        elif codigo == '3': # ICE
            row_data["Base ICE"] += base_imponible # Aunque no siempre se reporta base para ICE a este nivel
            row_data["Monto ICE"] += valor_impuesto

        elif codigo == '5': # IRBPNR
            row_data["Base IRBPNR"] += base_imponible # Aunque no siempre se reporta base para IRBPNR a este nivel
            row_data["Monto IRBPNR"] += valor_impuesto

    row_data["Monto IVA"] = total_monto_iva # Asignar la suma total del valor IVA

    # Monto Total (Factura, ND, NC, Ret, LiqCompra)
    # Para NC, el total es valorModificacion, no importeTotal
    if parsed_xml_data.get('info_tributaria', {}).get('cod_doc') == '04': # Nota de Crédito
        row_data["Monto Total"] = row_data["Valor Mod."]# Ya se calculó y guardó en "Valor Mod."
    # Para Retención, el total es la suma de los valores retenidos
    elif parsed_xml_data.get('info_tributaria', {}).get('cod_doc') == '07': # Comprobante de Retención
        total_retenido = sum(
            _safe_float_conversion(ret.get('valor_retenido'), 0.0, xml_file_path, f"Retencion Item Valor Retenido ({ret.get('codigo')})", conversion_errors_list)
            for ret in impuestos_retencion_list # Usar la lista específica de retenciones
        )
        row_data["Monto Total"] = total_retenido
    else: # Factura, ND, LiqCompra, etc. usan importeTotal
        row_data["Monto Total"] = _safe_float_conversion(totales.get('importe_total'), 0.0, xml_file_path, "Importe Total", conversion_errors_list)


    # Propina (principalmente Factura)
    row_data["Propina"] = _safe_float_conversion(totales.get('propina'), 0.0, xml_file_path, "Propina", conversion_errors_list)

    # Retenciones (para Comprobante de Retención)
    total_ret_iva = 0.0
    total_ret_renta = 0.0
    total_ret_isd = 0.0
    if row_data["CodDoc"] == '07':
        row_data["Periodo Fiscal"] = doc_especifico.get('periodo_fiscal', '')
        for ret in impuestos_retencion_list: # Usar la lista específica de retenciones
            codigo_impuesto_ret = ret.get('codigo')
            valor_retenido_item = _safe_float_conversion(ret.get('valor_retenido'), 0.0, xml_file_path, f"Retencion Item Valor Retenido ({codigo_impuesto_ret})", conversion_errors_list)
            if codigo_impuesto_ret == '1': # Renta
                total_ret_renta += valor_retenido_item
            elif codigo_impuesto_ret == '2': # IVA
                total_ret_iva += valor_retenido_item
            elif codigo_impuesto_ret == '6': # ISD
                total_ret_isd += valor_retenido_item
        row_data["Ret. IVA Pres."] = total_ret_iva
        row_data["Ret. Renta Pres."] = total_ret_renta
        row_data["Total Ret. ISD"] = total_ret_isd
        
        # Si solo hay una línea de retención (o un docSustento), podemos poblar los campos detallados.
        # Esto es una simplificación. Para múltiples líneas, necesitaríamos múltiples filas en la GUI o una representación diferente.
        if len(impuestos_retencion_list) == 1: # O podrías iterar y concatenar si son del mismo docSustento
            first_ret_detail = impuestos_retencion_list[0]
            row_data["CodDocSust"] = first_ret_detail.get('cod_doc_sustento', '')
            row_data["Fecha D.S."] = first_ret_detail.get('fecha_emision_doc_sustento', '')
            row_data["Num.Doc.Sustento"] = first_ret_detail.get('num_doc_sustento', '')
            row_data["Autorización Doc Sust."] = first_ret_detail.get('num_aut_doc_sustento', '')
            row_data["Tipo Impuesto Ret."] = IMPUESTO_RETENCION_MAP.get(first_ret_detail.get('codigo', ''), first_ret_detail.get('codigo', ''))
            row_data["Codigo Ret."] = first_ret_detail.get('codigo_retencion', '')
            row_data["Base Imponible Ret."] = _safe_float_conversion(first_ret_detail.get('base_imponible'), 0.0, xml_file_path, "Ret. Base Imponible Detalle", conversion_errors_list)
            row_data["Porcentaje Ret."] = _safe_float_conversion(first_ret_detail.get('porcentaje_retener'), 0.0, xml_file_path, "Ret. Porcentaje Detalle", conversion_errors_list)
            row_data["Valor Retenido"] = _safe_float_conversion(first_ret_detail.get('valor_retenido'), 0.0, xml_file_path, "Ret. Valor Retenido Detalle", conversion_errors_list)

    row_data["N.A.Doc.Modificado"] = "" # No es un campo estándar, inicializar como vacío.

    # Guia de Remisión (principalmente Factura)
    row_data["Guia de Remisión"] = doc_especifico.get('guia_remision', '') # Viene de infoFactura

    # Primeros 3 Articulos / Motivos
    descripciones_articulos = []
    if detalles_list: # Si hay detalles (items o motivos)
        for item in detalles_list[:3]: # Tomar solo los primeros 3
            if isinstance(item, dict):
                # Para items (Factura, NC, LiqCompra)
                if item.get('descripcion'):
                    descripciones_articulos.append(item['descripcion'])
                # Para motivos (ND) - El parser de motivos ya mapea 'razon' a 'descripcion'
                elif item.get('descripcion'):
                     descripciones_articulos.append(item['descripcion'])

    row_data["Primeros 3 Articulos"] = " | ".join(descripciones_articulos)

    # Ruta XML original (ya está en parsed_xml_data)
    row_data["original_xml_path"] = xml_file_path # Asegurar que se guarda

    return row_data

# --- Bloque if __name__ == '__main__' para pruebas ---
if __name__ == '__main__':
    # Configuración básica de logging para la prueba
    if not logging.getLogger().hasHandlers():
        log_format = '%(asctime)s - %(levelname)s - %(name)s - [%(filename)s:%(lineno)d] - %(message)s'
        logging.basicConfig(level=logging.DEBUG, format=log_format)

    # Cambia la ruta al archivo XML que quieras probar
    test_xml_path_ret = r'D:\Datos\Desktop\Asistente Contable\retencion.xml' # COLOCA AQUÍ EL NOMBRE DE TU ARCHIVO DE RETENCIÓN
    test_xml_path_nd = r'd:\Datos\Desktop\Asistente Contable\2404202505106003130000120010060001062241438928214.xml' # Nota de Débito
    test_xml_path_nc = r'D:\Datos\Desktop\Asistente Contable\Nota de credito.xml' # Ejemplo de ruta para Nota de Crédito
    test_xml_path_fac = r'd:\Datos\Desktop\Asistente Contable\factura_ejemplo.xml' # Ejemplo de ruta para Factura

    test_files = [
        test_xml_path_fac,
        test_xml_path_nd,
        test_xml_path_nc,
        test_xml_path_ret,
    ]

    for test_file_path in test_files:
        if os.path.exists(test_file_path):
            logger.info(f"\n--- Parseando y Extrayendo datos para tabla: {os.path.basename(test_file_path)} ---")
            parsed_result = parse_xml(test_file_path)

            if parsed_result:
                # Simular la llamada desde WorkerThread
                # Necesitamos un cod_doc_filter y entity_id_filter para la prueba
                simulated_cod_doc = parsed_result.get('info_tributaria', {}).get('cod_doc')
                simulated_entity_id_raw = parsed_result.get('id_comprador_raw')
                simulated_conversion_errors_list = [] # Lista vacía para acumular errores

                if simulated_cod_doc and simulated_entity_id_raw:
                    row_data = extract_data_from_xml(
                        parsed_result,
                        test_file_path,
                        simulated_cod_doc, # Usar el cod_doc real del archivo
                        simulated_entity_id_raw, # Usar el entity_id_raw real del archivo
                        simulated_conversion_errors_list # Pasar la lista
                    )

                    if row_data:
                        print("\n--- Datos Extraídos para Tabla ---")
                        import json
                        # Imprimir solo los campos que deberían ir a la tabla
                        table_data_to_print = {k: row_data.get(k, 'N/A') for k in ALL_CSV_FIELDS}
                        print(json.dumps(table_data_to_print, indent=4, ensure_ascii=False))

                        if simulated_conversion_errors_list:
                            print("\n--- Errores de Conversión ---")
                            for err in simulated_conversion_errors_list:
                                print(f"- {err}")

                    else:
                        logger.warning(f"La extracción de datos para la tabla de {os.path.basename(test_file_path)} falló o devolvió None.")
                else:
                    logger.warning(f"No se pudo determinar cod_doc ({simulated_cod_doc}) o entity_id_raw ({simulated_entity_id_raw}) para {os.path.basename(test_file_path)}. No se llamó a extract_data_from_xml.")

            else:
                logger.warning(f"El parseo de {os.path.basename(test_file_path)} falló o no devolvió datos.")
        else:
            logger.warning(f"Archivo de prueba no encontrado: {test_file_path}")
