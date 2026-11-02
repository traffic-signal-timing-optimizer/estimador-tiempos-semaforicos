"""Lectura en flujo de ``tripinfo.xml`` (DEV07 F0, decisión D18).

El ``tripinfo`` es la salida más grande de una corrida (unos 470 bytes por vehículo). Leerlo entero
como árbol ocupa unos 2,5 KB por viaje: con 200 000 vehículos, unos 500 MB, y se leía dos veces
(resumen y conciliación). Aquí se lee de a un viaje y solo se guardan sus horas y sus tiempos
(``Trip``): la memoria crece con los vehículos, no con el árbol.

Mismas protecciones que ``parse_root``: tope de bytes (también para ``.gz``, contado sobre lo
descomprimido), sin DTD ni entidades (``defusedxml``) y raíz esperada. Los errores solo llevan el
nombre del archivo.
"""

from dataclasses import dataclass
from pathlib import Path

from defusedxml.ElementTree import iterparse

from semaforo.caso.xml_input import invalid, optional_number, required, stream_parse
from semaforo.trazabilidad.fs import Readable

__all__ = ["ROOT", "TAG", "Trip", "read_trips"]

ROOT = "tripinfos"
TAG = "tripinfo"


@dataclass(frozen=True)
class Trip:
    """Un viaje de SUMO, en segundos (DEV19 F1 agrega lo que mide la evaluación).

    - ``depart``: hora real de entrada; ``-1`` si nunca entró (``write-undeparted``, ADR11).
    - ``arrival``: hora de llegada; ``-1`` si no terminó.
    - ``time_loss`` y ``depart_delay``: tiempo perdido en ruta y espera para entrar. En un viaje
      sin terminar o sin entrar son lo acumulado hasta el fin de la simulación.
    - ``waiting_time`` y ``waiting_count``: tiempo y episodios a muy baja velocidad en todo el
      viaje. No son la demora (protocolo); se conservan solo como dato auxiliar.

    Un atributo ausente queda en None: el lector no inventa ceros.
    """

    depart: float | None
    arrival: float | None
    time_loss: float | None = None
    depart_delay: float | None = None
    waiting_time: float | None = None
    waiting_count: float | None = None

    @property
    def started(self) -> bool:
        """Entró a la red: ``depart`` no es negativo (sin ``depart``, sí, como en DEV07)."""
        return self.depart is None or self.depart >= 0


def _trips(source: Readable, what: str) -> dict[str, Trip]:
    trips: dict[str, Trip] = {}
    depth = 0
    root = None
    for event, element in iterparse(source, events=("start", "end"), forbid_dtd=True):
        if event == "start":
            depth += 1
            if root is None:
                root = element
                if element.tag != ROOT:
                    raise invalid(f"{what}: la raíz <{element.tag}> no es la esperada", what)
            continue
        depth -= 1
        if depth != 1 or root is None:
            continue
        if element.tag == TAG:
            trip_id = required(element, "id")
            if trip_id in trips:
                raise invalid(f"{what}: hay dos viajes del vehículo «{trip_id}»", what)
            trips[trip_id] = Trip(
                depart=optional_number(element, "depart"),
                arrival=optional_number(element, "arrival"),
                time_loss=optional_number(element, "timeLoss"),
                depart_delay=optional_number(element, "departDelay"),
                waiting_time=optional_number(element, "waitingTime"),
                waiting_count=optional_number(element, "waitingCount"),
            )
        root.clear()
    return trips


def read_trips(path: Path, max_bytes: int) -> dict[str, Trip]:
    """Viajes de ``path`` por identificador, en el orden del archivo.

    Raises:
        CasoError: INPUT_SCHEMA si no se puede leer, supera ``max_bytes`` (descomprimido), no es
            XML válido o seguro, su raíz no es ``<tripinfos>``, a un viaje le falta ``id``, un
            número no es válido o un vehículo aparece dos veces.
    """
    return stream_parse(path, max_bytes, _trips)
