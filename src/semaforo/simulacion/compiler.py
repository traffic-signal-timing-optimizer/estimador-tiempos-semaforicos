"""Compilador del programa derivado: duraciones de los slots a un programa de semáforo de SUMO.

Toma un caso, el mapa de su red (``caso.network_map``) y una duración por slot, y produce un
archivo adicional de SUMO con un programa nuevo. No modifica la red: SUMO suma el programa a la
red y lo activa desde el segundo 0 (comprobado con SUMO 1.27.1). Un programa con el mismo
``programID`` que uno de la red hace que SUMO se detenga, así que el derivado lleva el suyo.

Disposición publicada (acta ``2026-10-30-dev03-f0-tiempos-y-limites``)::

    <root>/<case_id>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/
        programa.tll.xml     programa de semáforo para SUMO (archivo adicional)
        tramos.json          duraciones y límites usados
        manifiesto.json      huellas SHA-256 del programa, del caso y de la red

Una carpeta publicada nunca se sobrescribe.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from semaforo.caso.network_map import NetworkMap
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case, CaseIssue, canonical_sha256
from semaforo.dominio.case_plan import plan_issues
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import utc_now

__all__ = [
    "DERIVED_PROGRAM_ID",
    "CompilationError",
    "DerivedPhase",
    "DerivedProgram",
    "ProgramManifest",
    "compile_program",
    "publish_program",
]

DERIVED_PROGRAM_ID = "derived"
PROGRAM_FILE = "programa.tll.xml"
SLOTS_FILE = "tramos.json"
MANIFEST_FILE = "manifiesto.json"
SAFE_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHORT_HASH_CHARS = 8
XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'


class CompilationError(DomainError):
    """No se pudo compilar o publicar el programa. Lleva los problemas encontrados."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        field: str | None = None,
        issues: tuple[CaseIssue, ...] = (),
    ) -> None:
        super().__init__(code, message, field)
        self.issues = issues


@dataclass(frozen=True)
class DerivedPhase:
    """Una fase del programa: el slot de origen, su duración y el estado de cada señal."""

    slot_id: str
    duration_s: float
    state: str


@dataclass(frozen=True)
class DerivedProgram:
    """Programa derivado: sus fases, el archivo XML que lo contiene y la huella de ese archivo."""

    program_id: str
    tls_id: str
    phases: tuple[DerivedPhase, ...]
    xml: bytes
    sha256: str

    @property
    def cycle_s(self) -> float:
        return sum(phase.duration_s for phase in self.phases)


class ProgramManifest(FrozenModel):
    """Manifiesto de un programa derivado publicado."""

    schema_version: str = "1.0.0"
    created_at: str
    case_id: str
    case_version: str
    case_sha256: str
    network_sha256: str | None
    program_id: str
    tls_id: str
    files: dict[str, str]


def compile_program(
    case: Case,
    network_map: NetworkMap,
    durations: Mapping[str, float],
    program_id: str = DERIVED_PROGRAM_ID,
) -> DerivedProgram:
    """Programa de semáforo de SUMO con las ``durations`` (segundos por ID de slot).

    Raises:
        CompilationError: INPUT_SCHEMA si el mapa de la red tiene diferencias con el caso, si un
            slot no tiene exactamente el estado del semáforo de la red, o si las duraciones no
            cumplen los límites del caso.
    """
    if not network_map.is_complete:
        raise CompilationError(
            ErrorCode.INPUT_SCHEMA,
            f"el mapa de la red tiene {len(network_map.issues)} diferencias con el caso; "
            "no se compila un programa a partir de un mapa incompleto",
            "network",
            network_map.issues,
        )
    state_issues = _state_issues(case, network_map)
    if state_issues:
        raise _invalid(state_issues)
    issues = plan_issues(case, durations)
    if issues:
        raise _invalid(issues)
    phases = tuple(
        DerivedPhase(slot.id, durations[slot.id], slot.states[0].state) for slot in case.slots
    )
    xml = _xml(network_map.tls_id, program_id, phases)
    return DerivedProgram(program_id, network_map.tls_id, phases, xml, sha256_bytes(xml))


def publish_program(
    root: Path,
    case: Case,
    program: DerivedProgram,
    now: datetime | None = None,
) -> Path:
    """Publica ``program`` en ``root/<case_id>/<fecha>_<huella>/`` y devuelve esa carpeta.

    Raises:
        CompilationError: PATH_NOT_ALLOWED si el ID del caso no sirve como nombre de carpeta;
            RUN_EXISTS si la carpeta de destino ya existe.
    """
    if SAFE_FOLDER_NAME.fullmatch(case.case_id) is None:
        raise CompilationError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el ID del caso solo puede llevar letras, números, punto, guion y guion bajo para "
            "usarse como nombre de carpeta",
            "case_id",
        )
    moment = (utc_now() if now is None else now).astimezone(UTC)
    final = root / case.case_id / f"{moment:%Y%m%dT%H%M%SZ}_{program.sha256[:SHORT_HASH_CHARS]}"
    slots = _slots_json(case, program)
    manifest = ProgramManifest(
        created_at=moment.isoformat(),
        case_id=case.case_id,
        case_version=case.case_version,
        case_sha256=canonical_sha256(case),
        network_sha256=None if case.network is None else case.network.sha256,
        program_id=program.program_id,
        tls_id=program.tls_id,
        files={PROGRAM_FILE: program.sha256, SLOTS_FILE: sha256_bytes(slots)},
    )
    manifest_bytes = (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
    try:
        publish_files(
            final, {PROGRAM_FILE: program.xml, SLOTS_FILE: slots, MANIFEST_FILE: manifest_bytes}
        )
    except FileExistsError as error:
        raise CompilationError(
            ErrorCode.RUN_EXISTS, "ya existe una carpeta con ese programa", "root"
        ) from error
    return final


def _invalid(issues: list[CaseIssue]) -> CompilationError:
    first = issues[0]
    extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
    where = "" if first.field is None else f" en {first.field}"
    return CompilationError(
        ErrorCode.INPUT_SCHEMA,
        f"no se puede compilar: {first.rule_id}{where}: {first.message}{extra}",
        first.field,
        tuple(issues),
    )


def _state_issues(case: Case, network_map: NetworkMap) -> list[CaseIssue]:
    """Cada slot debe traer exactamente un estado, del semáforo de la red y de su largo."""
    issues: list[CaseIssue] = []
    for index, slot in enumerate(case.slots):
        field = f"slots[{index}].states"
        if len(slot.states) != 1:
            issues.append(
                CaseIssue(
                    "COMPILE-01",
                    field,
                    f"el slot trae {len(slot.states)} estados y esta versión solo admite uno "
                    "por slot (un semáforo)",
                )
            )
            continue
        state = slot.states[0]
        if state.tls_id != network_map.tls_id:
            issues.append(
                CaseIssue(
                    "COMPILE-01",
                    f"{field}[0].tls_id",
                    f"el estado es del semáforo {state.tls_id!r}, pero la red tiene "
                    f"{network_map.tls_id!r}",
                )
            )
        elif len(state.state) != network_map.link_count:
            issues.append(
                CaseIssue(
                    "COMPILE-01",
                    f"{field}[0].state",
                    f"el estado tiene {len(state.state)} señales y el semáforo "
                    f"{network_map.link_count} enlaces",
                )
            )
    return issues


def _seconds(value: float) -> str:
    """Duración como la escribe SUMO en sus archivos: ``82`` y no ``82.0``."""
    return str(int(value)) if value == int(value) else repr(value)


def _xml(tls_id: str, program_id: str, phases: tuple[DerivedPhase, ...]) -> bytes:
    root = Element("additional")
    logic = SubElement(root, "tlLogic", id=tls_id, type="static", programID=program_id, offset="0")
    for phase in phases:
        SubElement(logic, "phase", duration=_seconds(phase.duration_s), state=phase.state)
    indent(root, space="    ")
    return (XML_HEADER + tostring(root, encoding="unicode") + "\n").encode("utf-8")


def _slots_json(case: Case, program: DerivedProgram) -> bytes:
    by_slot = {phase.slot_id: phase.duration_s for phase in program.phases}
    data = {
        "schema_version": "1.0.0",
        "cycle_s": program.cycle_s,
        "slots": [
            {
                "id": slot.id,
                "kind": slot.kind,
                "min_s": slot.min_s,
                "max_s": slot.max_s,
                "duration_s": by_slot[slot.id],
            }
            for slot in case.slots
        ],
        "green_groups": [
            {
                "id": group.id,
                "min_s": group.min_s,
                "max_s": group.max_s,
                "total_s": sum(by_slot[slot_id] for slot_id in dict.fromkeys(group.slot_ids)),
            }
            for group in case.green_groups
        ],
    }
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
