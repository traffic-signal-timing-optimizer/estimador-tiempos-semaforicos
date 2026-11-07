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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from semaforo.bd.carga import crudo
from semaforo.bd.carga.corridas import SearchRun
from semaforo.bd.carga.fuentes import Sources, children, discover
from semaforo.bd.carga.modelo import CargaError
from semaforo.bd.carga.referencias import read_trace, trace_runs
from semaforo.caso.case_validation import read_case
from semaforo.datos.scenario_set import read_scenario_set
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError
from semaforo.dominio.protocol import Protocol, parse_protocol
from semaforo.dominio.scenario import Scenario
from semaforo.evaluacion.published_metrics import (
    METRICS,
    RUNS,
    publish_run_metrics,
    read_run_metrics,
)
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.simulacion.demand_inputs import read_scenario
from semaforo.simulacion.prepare import InputsManifest
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
    # Lo que no se pudo leer (fuente → motivo): una corrida que lo necesite queda «no verificada».
    problems: Mapping[str, str] = field(default_factory=dict[str, str])


def _cases(
    workspace: Path, sources: Sources, problems: dict[str, str]
) -> dict[tuple[str, str], Case]:
    found: dict[tuple[str, str], Case] = {}
    for source in sources.of("case"):
        try:
            case = read_case(workspace / source.main)
        except DomainError as error:
            problems[source.key] = error.message
            continue
        found[(case.case_id, case.case_version)] = case
    return found


def _protocols(workspace: Path, sources: Sources, problems: dict[str, str]) -> dict[str, Protocol]:
    found: dict[str, Protocol] = {}
    for source in sources.of("protocol"):
        try:
            protocol = parse_protocol(json.loads((workspace / source.main).read_bytes()))
        except (DomainError, ValueError, OSError) as error:
            problems[source.key] = getattr(error, "message", type(error).__name__)
            continue
        found[protocol.protocol_id] = protocol
    return found


def _scenarios(
    workspace: Path,
    sources: Sources,
    cases: Mapping[tuple[str, str], Case],
    problems: dict[str, str],
) -> dict[tuple[str, str, str], Scenario]:
    """Los escenarios escritos a mano y los de los conjuntos generados."""
    found: dict[tuple[str, str, str], Scenario] = {}
    for source in sources.of("scenario"):
        path = workspace / source.main
        try:
            raw = crudo.mapping(crudo.loads(path.read_bytes(), path.name), path.name)
            case = cases.get((str(raw.get("case_id")), str(raw.get("case_version"))))
            if case is None:
                continue  # sin su caso no se puede leer; la unidad de carga lo informa
            scenario = read_scenario(path, case)
        except (CargaError, DomainError, OSError) as error:
            problems[source.key] = getattr(error, "message", type(error).__name__)
            continue
        found[(scenario.case_id, scenario.case_version, scenario.scenario_id)] = scenario
    for source in sources.of("scenario_set"):
        try:
            generated = read_scenario_set(workspace / source.folder)
        except DomainError as error:
            problems[source.key] = error.message
            continue
        for scenario in generated.scenarios:
            found[(scenario.case_id, scenario.case_version, scenario.scenario_id)] = scenario
    return found


def load_context(workspace: Path, sources: Sources | None = None) -> ProtocolContext:
    """Lee los casos, protocolos, escenarios (a mano y generados) y trazas de ``workspace``.

    Lo que no se puede leer no detiene la lectura: queda en ``problems`` con su motivo, y solo
    afecta a las corridas que lo necesiten.
    """
    catalog = discover(workspace) if sources is None else sources
    problems: dict[str, str] = {}
    cases = _cases(workspace, catalog, problems)
    protocols = _protocols(workspace, catalog, problems)
    scenarios = _scenarios(workspace, catalog, cases, problems)
    searches: dict[str, SearchRun] = {}
    for source in catalog.of("search"):
        try:
            searches.update(trace_runs(read_trace(workspace, source.folder)))
        except DomainError as error:
            problems[source.key] = error.message
    return ProtocolContext(workspace, cases, protocols, scenarios, searches, problems)


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


def _why(error: Exception) -> str:
    """Por qué falló una lectura, sin rutas de la máquina ni texto del archivo."""
    return type(error).__name__


def _cannot_measure(manifest: RunManifest, inputs_path: Path) -> str | None:
    if manifest.status != "succeeded":
        return "la corrida no terminó bien: no tiene métricas"
    if not inputs_path.is_file() or manifest.scenario_id is None:
        return "no tiene carpeta de entradas de DEV06"
    return None


def _already(folder: Path, run_id: str) -> MetricsOutcome:
    """Una carpeta de métricas que ya existe solo cuenta como publicada si se puede leer."""
    try:
        read_run_metrics(folder)
    except DomainError as error:
        return _outcome(
            run_id,
            "failed",
            None,
            f"la carpeta de métricas ya existe pero no es válida: {error.message}",
        )
    return _outcome(run_id, "already", None, None)


def _read_run(workspace: Path, run_id: str) -> tuple[RunManifest, InputsManifest] | MetricsOutcome:
    """Los manifiestos de la corrida, o el resultado que la deja sin medir (cada error, aislado)."""
    folder = workspace / RUNS / run_id
    try:
        manifest = RunManifest.model_validate_json((folder / MANIFEST).read_bytes())
    except (OSError, ValueError) as error:
        return _outcome(
            run_id, "failed", None, f"el manifiesto de la corrida no se puede leer: {_why(error)}"
        )
    inputs_path = folder / INPUTS_MANIFEST
    skipped = _cannot_measure(manifest, inputs_path)
    if skipped is not None or manifest.scenario_id is None:
        return _outcome(run_id, "skipped", None, skipped)
    published = workspace / METRICS / manifest.case_id / run_id
    if published.exists():
        return _already(published, run_id)
    try:
        inputs = InputsManifest.model_validate_json(inputs_path.read_bytes())
    except (OSError, ValueError) as error:
        return _outcome(
            run_id, "failed", None, f"las entradas de la corrida no se pueden leer: {_why(error)}"
        )
    return manifest, inputs


def _measure(context: ProtocolContext, run_id: str, preferred: str | None) -> MetricsOutcome:
    workspace = context.workspace
    folder = workspace / RUNS / run_id
    read = _read_run(workspace, run_id)
    if isinstance(read, MetricsOutcome):
        return read
    manifest, inputs = read
    case = context.cases.get((manifest.case_id, manifest.case_version))
    scenario = context.scenarios.get(
        (manifest.case_id, manifest.case_version, str(manifest.scenario_id))
    )
    if case is None or scenario is None:
        return _outcome(run_id, "skipped", None, "falta el caso o el escenario")
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
        _measure(context, folder.name, protocol_id) for folder in children(workspace / RUNS)
    ]
    counts = {
        status: sum(1 for o in outcomes if o.status == status)
        for status in ("published", "already", "skipped", "failed")
    }
    return MetricsReport(counts=counts, runs=outcomes)
