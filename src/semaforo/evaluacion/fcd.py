"""Lectura en flujo de la FCD de la zona (DEV19 F3; decisión D16 de F0; ADR11).

La FCD dice, en cada paso de la simulación, la velocidad y el carril de cada vehículo de la zona.
Puede ser grande (una fila por vehículo y por segundo), así que se lee de a un paso y se entrega
cada paso a quien mide (``on_step``): la memoria no crece con el archivo.

Protecciones: las de ``stream_parse`` (tope de bytes también para ``.gz``, sin DTD ni entidades,
errores con solo el nombre del archivo) y además: raíz ``<fcd-export>``, pasos en orden creciente,
cada vehículo con ``id``, ``lane`` y ``speed`` (número finito, no negativo) y una sola vez por paso.
Lo que no es un vehículo (personas, contenedores) se ignora.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import iterparse

from semaforo.caso.xml_input import invalid, number, required, stream_parse
from semaforo.dominio.timing import shown
from semaforo.trazabilidad.fs import Readable

__all__ = ["ROOT", "FcdRecord", "StepHandler", "read_fcd"]

ROOT = "fcd-export"
STEP = "timestep"
VEHICLE = "vehicle"
# Profundidad de cada elemento: la raíz es 1, el paso 2 y el vehículo 3.
STEP_DEPTH = 2
VEHICLE_DEPTH = 3


@dataclass(frozen=True)
class FcdRecord:
    """Un vehículo en un paso: su identificador, su carril y su velocidad (m/s)."""

    vehicle_id: str
    lane: str
    speed_mps: float


StepHandler = Callable[[float, list[FcdRecord]], None]


def _record(element: Element, what: str, seen: set[str]) -> FcdRecord:
    vehicle_id = required(element, "id")
    if vehicle_id in seen:
        raise invalid(
            f"{what}: el vehículo {shown(vehicle_id)!r} aparece dos veces en un paso", what
        )
    seen.add(vehicle_id)
    speed = number(element, "speed")
    if speed < 0:
        raise invalid(f"{what}: velocidad negativa del vehículo {shown(vehicle_id)!r}", what)
    return FcdRecord(vehicle_id, required(element, "lane"), speed)


def _steps(source: Readable, what: str, on_step: StepHandler) -> int:
    depth = 0
    root: Element | None = None
    records: list[FcdRecord] = []
    seen: set[str] = set()
    last: float | None = None
    steps = 0
    for event, element in iterparse(source, events=("start", "end"), forbid_dtd=True):
        if event == "start":
            depth += 1
            if root is None:
                root = element
                if element.tag != ROOT:
                    raise invalid(f"{what}: la raíz <{element.tag}> no es la esperada", what)
            continue
        closing, depth = depth, depth - 1
        if closing == VEHICLE_DEPTH and element.tag == VEHICLE:
            records.append(_record(element, what, seen))
        elif closing == STEP_DEPTH:
            if element.tag != STEP:
                raise invalid(f"{what}: <{element.tag}> no es un paso <{STEP}>", what)
            time = number(element, "time")
            if last is not None and time <= last:
                raise invalid(f"{what}: el paso {time:g} no va después del {last:g}", what)
            on_step(time, records)
            last, steps = time, steps + 1
            records, seen = [], set()
            if root is not None:
                root.clear()
    return steps


def read_fcd(path: Path, max_bytes: int, on_step: StepHandler) -> int:
    """Lee la FCD de ``path`` paso por paso, llama a ``on_step(tiempo, vehículos)`` en cada uno y
    devuelve cuántos pasos leyó.

    Raises:
        CasoError: INPUT_SCHEMA si no se puede leer, supera ``max_bytes`` (descomprimido), no es
            XML válido o seguro, su raíz no es ``<fcd-export>``, un paso no tiene ``time`` o no va
            en orden, o un vehículo no tiene sus datos, tiene velocidad negativa o se repite en un
            paso.
    """
    return stream_parse(path, max_bytes, lambda source, what: _steps(source, what, on_step))
