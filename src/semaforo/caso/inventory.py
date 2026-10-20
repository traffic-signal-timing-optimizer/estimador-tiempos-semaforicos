"""Lectura del inventario de una red SUMO (``.net.xml`` o ``.net.xml.gz``).

La red es un archivo externo y por tanto no confiable: se descomprime con un límite de tamaño
(contra bombas de compresión) y se lee con ``defusedxml``, sin DTD ni entidades.
"""

import gzip
import math
import zlib
from collections import Counter
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.inventory_models import (
    InventoryFinding,
    NetworkCounts,
    NetworkInventory,
    Phase,
    TlsInventory,
    TlsProgram,
)

# Límite provisional del tamaño descomprimido, pendiente del piloto. La red de Frutales ocupa
# 511 429 bytes descomprimida; el árbol XML en memoria ocupa varias veces el tamaño del archivo.
MAX_NET_BYTES = 64 * 1024 * 1024
GZIP_MAGIC = b"\x1f\x8b"
INTERNAL = "internal"


def read_network_inventory(path: Path, max_bytes: int = MAX_NET_BYTES) -> NetworkInventory:
    """Describe la red de ``path``: conteos, semáforos con sus programas y hallazgos.

    Args:
        path: red de SUMO, comprimida o no (se distingue por el contenido, no por el nombre).
        max_bytes: tamaño máximo descomprimido aceptado.

    Raises:
        CasoError: INPUT_SCHEMA si el archivo no se puede leer, supera el límite, está truncado,
            no es XML válido o seguro, no es una red de SUMO o trae valores numéricos no válidos.
    """
    root = _parse(path, max_bytes)
    controlled = _controlled_links(root)
    programs = _programs(root)
    traffic_lights: list[TlsInventory] = []
    findings: list[InventoryFinding] = []
    for tls_id in [*programs, *(tls for tls in controlled if tls not in programs)]:
        links = controlled.get(tls_id, [])
        link_count = max(links) + 1 if links else 0
        found = programs.get(tls_id, [])
        traffic_lights.append(
            TlsInventory(
                id=tls_id,
                link_count=link_count,
                connection_count=len(links),
                active_program_id=found[-1].program_id if found else None,
                programs=found,
            )
        )
        findings.extend(_findings(tls_id, found, link_count))
    return NetworkInventory(
        net_version=root.get("version"),
        counts=_counts(root),
        traffic_lights=traffic_lights,
        findings=findings,
    )


def _invalid(message: str, field: str) -> CasoError:
    return CasoError(ErrorCode.INPUT_SCHEMA, message, field)


def _read_bounded(path: Path, max_bytes: int) -> bytes:
    """Contenido descomprimido de ``path``, sin leer nunca más de ``max_bytes`` + 1 bytes."""
    try:
        with path.open("rb") as handle:
            compressed = handle.read(len(GZIP_MAGIC)) == GZIP_MAGIC
            handle.seek(0)
            data = (gzip.GzipFile(fileobj=handle) if compressed else handle).read(max_bytes + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise _invalid(f"no se puede leer la red ({type(error).__name__})", path.name) from error
    if len(data) > max_bytes:
        raise _invalid(f"la red supera el límite de {max_bytes} bytes", path.name)
    return data


def _parse(path: Path, max_bytes: int) -> Element:
    data = _read_bounded(path, max_bytes)
    try:
        root = fromstring(data, forbid_dtd=True)
    except (DefusedXmlException, ParseError) as error:
        raise _invalid(
            f"la red no es un XML válido o seguro ({type(error).__name__})", path.name
        ) from error
    if root.tag != "net":
        raise _invalid("la raíz del archivo no es una red de SUMO", path.name)
    return root


def _required(element: Element, name: str) -> str:
    value = element.get(name)
    if value is None:
        raise _invalid(f"falta el atributo {name} en <{element.tag}>", f"{element.tag}.{name}")
    return value


def _to_number(element: Element, name: str, text: str) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise _invalid(
            f"{name} no es un número en <{element.tag}>", f"{element.tag}.{name}"
        ) from error
    if not math.isfinite(value):
        raise _invalid(f"{name} no es finito en <{element.tag}>", f"{element.tag}.{name}")
    return value


def _number(element: Element, name: str) -> float:
    return _to_number(element, name, _required(element, name))


def _optional_number(element: Element, name: str) -> float | None:
    text = element.get(name)
    return None if text is None else _to_number(element, name, text)


def _integer(element: Element, name: str) -> int:
    text = _required(element, name)
    try:
        return int(text)
    except ValueError as error:
        raise _invalid(
            f"{name} no es un entero en <{element.tag}>", f"{element.tag}.{name}"
        ) from error


def _counts(root: Element) -> NetworkCounts:
    edges = root.findall("edge")
    internal = [edge for edge in edges if edge.get("function") == INTERNAL]
    connections = root.findall("connection")
    types = Counter(junction.get("type", "unknown") for junction in root.findall("junction"))
    return NetworkCounts(
        junctions=sum(types.values()),
        junction_types=dict(sorted(types.items())),
        edges_total=len(edges),
        edges_internal=len(internal),
        lanes_total=sum(len(edge.findall("lane")) for edge in edges),
        lanes_internal=sum(len(edge.findall("lane")) for edge in internal),
        connections_total=len(connections),
        connections_from_internal=sum(c.get("from", "").startswith(":") for c in connections),
    )


def _controlled_links(root: Element) -> dict[str, list[int]]:
    """``linkIndex`` de cada conexión controlada, por semáforo y en el orden del archivo."""
    links: dict[str, list[int]] = {}
    for connection in root.findall("connection"):
        tls_id = connection.get("tl")
        if tls_id is not None:
            links.setdefault(tls_id, []).append(_integer(connection, "linkIndex"))
    return links


def _programs(root: Element) -> dict[str, list[TlsProgram]]:
    programs: dict[str, list[TlsProgram]] = {}
    for logic in root.findall("tlLogic"):
        programs.setdefault(_required(logic, "id"), []).append(_program(logic))
    return programs


def _program(logic: Element) -> TlsProgram:
    offset = _optional_number(logic, "offset")
    return TlsProgram(
        program_id=logic.get("programID", "0"),
        type=logic.get("type", "static"),
        offset_s=0.0 if offset is None else offset,
        params={_required(p, "key"): _required(p, "value") for p in logic.findall("param")},
        phases=[_phase(index, phase) for index, phase in enumerate(logic.findall("phase"))],
    )


def _phase(index: int, element: Element) -> Phase:
    return Phase(
        index=index,
        duration_s=_number(element, "duration"),
        min_dur_s=_optional_number(element, "minDur"),
        max_dur_s=_optional_number(element, "maxDur"),
        state=_required(element, "state"),
        name=element.get("name"),
    )


def _findings(tls_id: str, programs: list[TlsProgram], link_count: int) -> list[InventoryFinding]:
    findings: list[InventoryFinding] = []
    if not programs:
        findings.append(
            InventoryFinding(
                code="TLS_WITHOUT_PROGRAM",
                tls_id=tls_id,
                program_id=None,
                phase_index=None,
                message="hay conexiones controladas por este semáforo pero ningún programa",
            )
        )
    elif len(programs) > 1:
        findings.append(
            InventoryFinding(
                code="MULTIPLE_PROGRAMS",
                tls_id=tls_id,
                program_id=None,
                phase_index=None,
                message=(
                    f"hay {len(programs)} programas; SUMO 1.27.1 activa el último del archivo "
                    f"({programs[-1].program_id})"
                ),
            )
        )
    for program in programs:
        for phase in program.phases:
            findings.extend(_phase_findings(tls_id, program.program_id, phase, link_count))
    return findings


def _phase_findings(
    tls_id: str, program_id: str, phase: Phase, link_count: int
) -> list[InventoryFinding]:
    def finding(code: str, message: str) -> InventoryFinding:
        return InventoryFinding.model_validate(
            {
                "code": code,
                "tls_id": tls_id,
                "program_id": program_id,
                "phase_index": phase.index,
                "message": message,
            }
        )

    found: list[InventoryFinding] = []
    if len(phase.state) != link_count:
        found.append(
            finding(
                "STATE_LENGTH_MISMATCH",
                f"el estado tiene {len(phase.state)} señales y el semáforo {link_count} enlaces",
            )
        )
    if phase.min_dur_s is not None and phase.duration_s < phase.min_dur_s:
        found.append(
            finding(
                "PHASE_DURATION_BELOW_MIN",
                f"duration {phase.duration_s:g} es menor que minDur {phase.min_dur_s:g}",
            )
        )
    if phase.max_dur_s is not None and phase.duration_s > phase.max_dur_s:
        found.append(
            finding(
                "PHASE_DURATION_ABOVE_MAX",
                f"duration {phase.duration_s:g} es mayor que maxDur {phase.max_dur_s:g}",
            )
        )
    return found
