"""Lectura del archivo del orden de ajuste de un caso (DEV13 F3; decisión D18 de F0).

El archivo se trata como no confiable, igual que el resto de las entradas JSON: límite de tamaño,
sin seguir enlaces, UTF-8 con o sin BOM, sin claves repetidas ni ``NaN``. Su contenido se valida
con ``semaforo.dominio.adjust_order``; que sirva para un caso concreto lo comprueba
``semaforo.dominio.feasibility.prepare``.
"""

from pathlib import Path

from semaforo.caso.json_input import read_json
from semaforo.dominio.adjust_order import AdjustOrder, parse_adjust_order

__all__ = ["ADJUST_ORDER_FILE", "MAX_ORDER_BYTES", "read_adjust_order"]

ADJUST_ORDER_FILE = "orden_de_ajuste.json"
MAX_ORDER_BYTES = 64 * 1024


def read_adjust_order(path: Path) -> AdjustOrder:
    """Lee y valida la estructura del archivo del orden de ajuste.

    Raises:
        CasoError: PATH_NOT_ALLOWED si es un enlace o una unión; INPUT_SCHEMA si no existe, no es
            un archivo, supera ``MAX_ORDER_BYTES``, no está en UTF-8 o no es JSON válido.
        AdjustOrderInvalidError: si no cumple la estructura (ORDER-S01 a S03).
    """
    return parse_adjust_order(read_json(path, "orden de ajuste", MAX_ORDER_BYTES))
