"""Métricas que faltan: calcularlas con el código oficial y publicarlas (DEV31 F4; decisión B10).

Las 133 corridas anteriores a DEV31 F2 no tienen ``metricas.json``. ``publish_missing`` se las
calcula con ``evaluate_run`` (DEV19) y las publica con ``publish_run_metrics`` en carpetas
**nuevas** de ``datos/derivados/metricas`` (solo lectura, con manifiesto); no cambia nada de lo
que ya existe. Así la base copia métricas publicadas y nunca calcula las suyas.

Qué protocolo mide cada corrida:

1. la que usó una búsqueda publicada se mide con el protocolo de esa búsqueda (sale de su traza);
2. una corrida suelta se mide con el protocolo cuya zona coincide **exactamente** con la que
   registró la corrida (``measurement_edges`` de su carpeta de entradas). Si hay varios con esa
   misma zona, hay que decir cuál con ``protocol_id``; si no, la corrida se deja sin medir y se
   dice por qué.

``ProtocolContext`` junta lo que hace falta para medir (casos, protocolos, escenarios y trazas); la
conciliación (``semaforo.bd.conciliacion``) lo reutiliza para recalcular con lo mismo.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from semaforo.bd.carga import crudo
from semaforo.bd.carga.corridas import SearchRun
from semaforo.bd.carga.modelo import CargaError
from semaforo.bd.carga.referencias import read_trace, trace_runs
from semaforo.caso.case_validation import read_case
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError
from semaforo.dominio.protocol import Protocol, parse_protocol
from semaforo.dominio.scenario import Scenario
from semaforo.evaluacion.published_metrics import METRICS, RUNS, publish_run_metrics
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.simulacion.demand_inputs import read_scenario
from semaforo.simulacion.prepare import InputsManifest
from semaforo.trazabilidad.fs import INCOMPLETE_DIR, TEMP_PREFIX, is_plain_folder
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import MANIFEST

__all__ = [
    "MetricsOutcome",
    "MetricsReport",
    "ProtocolContext",
    "choose_protocol",
    "load_context",
    "publish_missing",
    "zone_edges",
]

CASES = "casos"
PROTOCOLS = "derivados/protocolos"
SCENARIOS = "escenarios"
LABELS = "derivados/referencias"
INPUTS_MANIFEST = "inputs/manifiesto.json"

Status = Literal["published", "already", "skipped", "failed"]


class MetricsOutcome(FrozenModel):
    """Qué pasó con una corrida."""

    run_id: str
    status: Status
    protocol_id: str | None
    detail: str | None


class MetricsReport(FrozenModel):
    """Informe de ``bd metricas`` (sin rutas de la máquina)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    counts: dict[str, int]
    runs: list[MetricsOutcome]


def _children(folder: Path) -> list[Path]:
    if not is_plain_folder(folder):
        return []
    return [
        child
        for child in sorted(folder.iterdir())
        if is_plain_folder(child)
        and not child.name.startswith((".", TEMP_PREFIX))
        and child.name != INCOMPLETE_DIR
    ]


def zone_edges(protocol: Protocol) -> frozenset[str]:
    """Las calles (sin el índice del carril) de la zona del protocolo."""
    return frozenset(lane.rsplit("_", 1)[0] for lane in protocol.zone_lane_ids)


@dataclass(frozen=True)
class ProtocolContext:
    """Lo que hace falta para medir una corrida de ``datos/``."""

    workspace: Path
    cases: Mapping[tuple[str, str], Case]
    protocols: Mapping[str, Protocol]
    scenarios: Mapping[tuple[str, str, str], Scenario]
    searches: Mapping[str, SearchRun]


def load_context(workspace: Path) -> ProtocolContext:
    """Lee los casos, protocolos, escenarios escritos a mano y trazas de ``workspace``."""
    cases: dict[tuple[str, str], Case] = {}
    for folder in _children(workspace / CASES):
        path = folder / "case.json"
        if path.is_file():
            case = read_case(path)
            cases[(case.case_id, case.case_version)] = case
    protocols: dict[str, Protocol] = {}
    for group in _children(workspace / PROTOCOLS):
        for path in sorted(group.glob("*.json")):
            protocol = parse_protocol(json.loads(path.read_bytes()))
            protocols[protocol.protocol_id] = protocol
    scenarios: dict[tuple[str, str, str], Scenario] = {}
    for group in _children(workspace / SCENARIOS):
        for path in sorted(group.glob("*.json")):
            try:
                raw = crudo.mapping(crudo.loads(path.read_bytes(), path.name), path.name)
            except CargaError:
                continue  # las rutas y los tipos de vehículo de la carpeta no son escenarios
            if "scenario_id" not in raw:
                continue
            case = cases.get((str(raw.get("case_id")), str(raw.get("case_version"))))
            if case is not None:
                scenario = read_scenario(path, case)
                scenarios[(scenario.case_id, scenario.case_version, scenario.scenario_id)] = (
                    scenario
                )
    searches: dict[str, SearchRun] = {}
    for group in _children(workspace / LABELS):
        for folder in _children(group):
            relative = folder.relative_to(workspace).as_posix()
            searches.update(trace_runs(read_trace(workspace, relative)))
    return ProtocolContext(workspace, cases, protocols, scenarios, searches)


def choose_protocol(
    edges: frozenset[str],
    protocols: Mapping[str, Protocol],
    preferred: str | None = None,
) -> tuple[Protocol | None, str | None]:
    """El protocolo que mide una corrida suelta con la zona ``edges``, o el motivo de no haberlo.

    Es el único protocolo cuya zona coincide exactamente con ``edges``; si hay varios, el que se
    pidió con ``preferred`` (que tiene que ser uno de ellos).
    """
    candidates = [p for p in protocols.values() if zone_edges(p) == edges]
    if preferred is not None:
        chosen = [p for p in candidates if p.protocol_id == preferred]
        if chosen:
            return chosen[0], None
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, "ningún protocolo tiene exactamente la zona que registró la corrida"
    names = ", ".join(sorted(p.protocol_id for p in candidates))
    return None, f"varios protocolos tienen esa zona ({names}): indique cuál con --protocolo"


def _outcome(
    run_id: str, status: Status, protocol: str | None, detail: str | None
) -> MetricsOutcome:
    return MetricsOutcome(run_id=run_id, status=status, protocol_id=protocol, detail=detail)


def _cannot_measure(manifest: RunManifest, inputs_path: Path) -> str | None:
    if manifest.status != "succeeded":
        return "la corrida no terminó bien: no tiene métricas"
    if not inputs_path.is_file() or manifest.scenario_id is None:
        return "no tiene carpeta de entradas de DEV06"
    return None


def _measure(context: ProtocolContext, run_id: str, preferred: str | None) -> MetricsOutcome:
    workspace = context.workspace
    folder = workspace / RUNS / run_id
    manifest = RunManifest.model_validate_json((folder / MANIFEST).read_bytes())
    inputs_path = folder / INPUTS_MANIFEST
    skipped = _cannot_measure(manifest, inputs_path)
    if skipped is not None or manifest.scenario_id is None:
        return _outcome(run_id, "skipped", None, skipped)
    if (workspace / METRICS / manifest.case_id / run_id).exists():
        return _outcome(run_id, "already", None, None)
    case = context.cases.get((manifest.case_id, manifest.case_version))
    scenario = context.scenarios.get(
        (manifest.case_id, manifest.case_version, manifest.scenario_id)
    )
    if case is None or scenario is None:
        return _outcome(run_id, "skipped", None, "falta el caso o el escenario escrito a mano")
    inputs = InputsManifest.model_validate_json(inputs_path.read_bytes())
    search = context.searches.get(run_id)
    if search is not None:
        protocol = context.protocols.get(search.protocol_id)
        reason = None if protocol else f"falta el protocolo {search.protocol_id} de su búsqueda"
    else:
        protocol, reason = choose_protocol(
            frozenset(inputs.measurement_edges), context.protocols, preferred
        )
    if protocol is None:
        return _outcome(run_id, "skipped", None, reason)
    try:
        metrics = evaluate_run(
            folder / "inputs", workspace / RUNS, run_id, case, protocol, scenario=scenario
        )
        publish_run_metrics(workspace, metrics)
    except DomainError as error:
        return _outcome(
            run_id, "failed", protocol.protocol_id, f"{error.code.value}: {error.message}"
        )
    return _outcome(run_id, "published", protocol.protocol_id, None)


def publish_missing(workspace: Path, *, protocol_id: str | None = None) -> MetricsReport:
    """Calcula y publica las métricas de cada corrida de ``workspace`` que todavía no las tiene.

    Una corrida que no se puede medir no detiene a las demás: queda en el informe con su motivo.
    """
    context = load_context(workspace)
    outcomes = [
        _measure(context, folder.name, protocol_id) for folder in _children(workspace / RUNS)
    ]
    counts = {
        status: sum(1 for o in outcomes if o.status == status)
        for status in ("published", "already", "skipped", "failed")
    }
    return MetricsReport(counts=counts, runs=outcomes)
