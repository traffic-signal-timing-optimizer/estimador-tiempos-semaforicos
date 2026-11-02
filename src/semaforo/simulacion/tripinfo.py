"""Lectura en flujo de ``tripinfo.xml`` (DEV07 F0, decisión D18).

El ``tripinfo`` es la salida más grande de una corrida (unos 470 bytes por vehículo). Leerlo entero
como árbol ocupa unos 2,5 KB por viaje: con 200 000 vehículos, unos 500 MB, y se leía dos veces
(resumen y conciliación). Aquí se lee de a un viaje y solo se guardan sus horas y sus tiempos
(``Trip``): la memoria crece con los vehículos, no con el árbol.

Mismas protecciones que ``parse_root``: tope de bytes (también para ``.gz``, contado sobre lo
descomprimido), sin DTD ni entidades (``defusedxml``) y raíz esperada. Los errores solo llevan el
nombre del archivo.
"""

import gzip
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse

from semaforo.caso.xml_input import GZIP_MAGIC, invalid, optional_number, required
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


class _TooLargeError(Exception):
    """Se leyó más del tope."""


class _Capped:
    """Envuelve un flujo y falla si se lee más de ``limit`` bytes."""

    def __init__(self, stream: Readable, limit: int) -> None:
        self._stream = stream
        self._left = limit

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._stream.read(size)
        self._left -= len(chunk)
        if self._left < 0:
            raise _TooLargeError
        return chunk


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
    name = path.name
    try:
        with path.open("rb") as handle:
            compressed = handle.read(len(GZIP_MAGIC)) == GZIP_MAGIC
            handle.seek(0)
            stream: BinaryIO | gzip.GzipFile = (
                gzip.GzipFile(fileobj=handle) if compressed else handle
            )
            trips = _trips(_Capped(stream, max_bytes), name)
    except _TooLargeError:
        raise invalid(f"el archivo supera el límite de {max_bytes} bytes", name) from None
    except (DefusedXmlException, SyntaxError) as error:
        raise invalid(
            f"{name}: no es un XML válido o seguro ({type(error).__name__})", name
        ) from error
    except (OSError, EOFError, zlib.error) as error:
        raise invalid(f"no se puede leer el archivo ({type(error).__name__})", name) from error
    return trips
