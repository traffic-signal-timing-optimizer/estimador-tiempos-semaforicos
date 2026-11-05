"""Evaluación de los candidatos con SUMO y elección de la referencia (DEV14 F2, HU08).

``run_search`` toma los candidatos de ``search.generate_candidates`` y, para cada uno:

1. compila y publica su programa de semáforo (DEV03, ``publish_program``);
2. prepara una carpeta de entradas por semilla (DEV06, ``publish_inputs``), la corre (DEV07,
   ``run_inputs``) y la mide (DEV19, ``evaluate_run``) con las semillas de búsqueda del protocolo;
3. elige a los finalistas, los reevalúa con las semillas de finalistas y elige la referencia
   (``selection``). Las semillas finales del protocolo no se usan: son de la evaluación final.

Reglas de ejecución (acta de DEV14 F0, decisiones F0-2 y F0-3):

- **Bitácora:** cada programa publicado y cada resultado por semilla se agregan, una línea JSON por
  registro, a ``journal_path`` en cuanto terminan. Si la búsqueda se corta, otra llamada con la
  misma bitácora sigue donde quedó: no repite lo que ya está anotado. La primera línea dice qué
  búsqueda es: caso, escenario, protocolo, semillas, candidatos y, desde la versión 2.0.0, la
  huella del contenido de cada insumo (caso, red, escenario con su demanda, rutas, tipos de
  vehículo, protocolo completo y versión de SUMO). Una bitácora de otra búsqueda, o de una versión
  anterior, se rechaza. Al seguir, cada carpeta de entradas y cada corrida anotadas se comprueban
  contra esos insumos (A01). Una última línea cortada (el proceso murió al escribirla) se ignora.
- **En paralelo:** ``workers`` corridas a la vez. Antes de lanzar cada una se consulta
  ``can_start`` (por ejemplo, si queda memoria libre) y se espera mientras diga que no.
- **Cancelar:** con ``cancel`` activado no se lanzan corridas nuevas y las que estaban en marcha se
  cancelan; nada de eso se anota, así que se repetirá al seguir. El resultado queda
  ``interrupted``, sin selección.
- **Fallos:** una corrida que no termina bien o que no se puede medir es un resultado (la semilla
  queda descartada) y se anota. Un error al preparar (rutas, programa) detiene la búsqueda: no es
  culpa del candidato.
"""

import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from semaforo.caso.network_map import NetworkMap
from semaforo.dominio.case import Case, canonical_sha256
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.protocol import Protocol
from semaforo.dominio.scenario import Scenario
from semaforo.evaluacion.cohort import require_supported
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.search import SEARCH_VERSION, Candidate, CandidateSet
from semaforo.referencias.selection import (
    SELECTION_RULE,
    CandidateScore,
    SeedOutcome,
    SeedProblem,
    Selection,
    Stage,
    choose_finalists,
    failed_seed,
    score_candidate,
    seed_outcome,
    select,
)
from semaforo.simulacion.compiler import (
    PROGRAM_FILE,
    compile_program,
    publish_program,
    read_program,
)
from semaforo.simulacion.demand_inputs import RouteTable, VehicleTypes
from semaforo.simulacion.prepare import (
    INPUTS_SCHEMA_VERSION,
    PreparationRequest,
    canonical_json_sha256,
    publish_inputs,
)
from semaforo.simulacion.run_inputs import run_inputs, verify_inputs
from semaforo.simulacion.runner import RunLimits, find_sumo, sumo_version
from semaforo.trazabilidad.fs import read_at_most
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import MANIFEST

__all__ = [
    "JOURNAL_VERSION",
    "MAX_JOURNAL_BYTES",
    "SearchOutcome",
    "SearchSetup",
    "free_memory_gate",
    "identity_digest",
    "input_fingerprints",
    "run_search",
    "search_identity",
]

JOURNAL_VERSION = "2.0.0"
MAX_JOURNAL_BYTES = 64 * 1024 * 1024
MAX_RUN_MANIFEST_BYTES = 16 * 1024 * 1024
RUN_INPUTS_ARTIFACT = "inputs/manifiesto.json"
_WAIT_S = 5.0
_NEWLINE = bytes([10])


@dataclass(frozen=True)
class SearchSetup:
    """Lo fijo de una búsqueda: el caso, el escenario, el protocolo y dónde se publica todo."""

    case: Case
    case_dir: Path
    network_map: NetworkMap
    scenario: Scenario
    routes: RouteTable
    vehicle_types: VehicleTypes
    protocol: Protocol
    programs_root: Path
    inputs_root: Path
    runs_root: Path
    sumo_options: Mapping[str, float | bool]
    sumo: Path | None = None
    limits: RunLimits | None = None


@dataclass(frozen=True)
class SearchOutcome:
    """El resultado de una búsqueda: cada candidato en cada etapa y la referencia elegida."""

    identity: Mapping[str, object]
    candidates: CandidateSet
    search_scores: tuple[CandidateScore, ...]
    finalist_scores: tuple[CandidateScore, ...]
    selection: Selection | None
    simulation_count: int
    interrupted: bool

    def to_json(self) -> dict[str, object]:
        return {
            "identity": dict(self.identity),
            "interrupted": self.interrupted,
            "simulation_count": self.simulation_count,
            "candidates": self.candidates.trace(),
            "search_scores": [score.to_json() for score in self.search_scores],
            "finalist_scores": [score.to_json() for score in self.finalist_scores],
            "selection": None if self.selection is None else self.selection.to_json(),
        }


def free_memory_gate(
    min_free_bytes: int, read_free: Callable[[], int | None]
) -> Callable[[], bool]:
    """``can_start`` que deja lanzar una corrida si quedan ``min_free_bytes`` libres.

    Si la memoria libre no se puede medir (``read_free`` da None) no se bloquea.
    """

    def can_start() -> bool:
        free = read_free()
        return free is None or free >= min_free_bytes

    return can_start


def _canonical(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _input_hashes(setup: SearchSetup) -> dict[str, str | None]:
    """Las huellas que el manifiesto de entradas de cada corrida también guarda."""
    network = setup.case.network
    return {
        "case_sha256": canonical_sha256(setup.case),
        "network_sha256": None if network is None else network.sha256,
        "scenario_sha256": canonical_json_sha256(setup.scenario.model_dump(mode="json")),
        "routes_sha256": canonical_json_sha256(setup.routes.model_dump(mode="json")),
        "vehicle_types_sha256": canonical_json_sha256(setup.vehicle_types.model_dump(mode="json")),
    }


def input_fingerprints(setup: SearchSetup, sumo_version: str) -> dict[str, object]:
    """Huella del contenido de cada insumo que puede cambiar el resultado de una búsqueda.

    Las del caso, la red, el escenario (con su demanda, su semilla de llegadas y sus horizontes),
    las rutas y los tipos de vehículo se calculan igual que en los manifiestos de entradas de las
    corridas; así una búsqueda ya hecha se puede reexpresar a partir de ellos. El protocolo va
    completo (zona, umbrales, cohorte), junto con la versión de SUMO y la de las entradas.
    """
    return {
        **_input_hashes(setup),
        "protocol_sha256": canonical_json_sha256(setup.protocol.model_dump(mode="json")),
        "inputs_schema_version": INPUTS_SCHEMA_VERSION,
        "sumo_version": sumo_version,
    }


def search_identity(
    setup: SearchSetup, candidates: CandidateSet, sumo_version: str
) -> dict[str, object]:
    """Qué búsqueda es: lo que debe coincidir para seguir una bitácora."""
    protocol = setup.protocol
    return {
        "journal_version": JOURNAL_VERSION,
        "search_version": SEARCH_VERSION,
        "selection_rule": SELECTION_RULE,
        "case_id": setup.case.case_id,
        "case_version": setup.case.case_version,
        "scenario_id": setup.scenario.scenario_id,
        "rules_version": candidates.rules_version,
        "protocol_id": protocol.protocol_id,
        "protocol_status": protocol.status,
        "search_budget": protocol.search_budget,
        "sampling_attempt_limit": protocol.sampling_attempt_limit,
        "finalist_count": protocol.finalist_count,
        "tie_epsilon_s": protocol.tie_epsilon_s,
        "seeds_search": list(protocol.seeds.search),
        "seeds_finalists": list(protocol.seeds.finalists),
        "sumo_options": dict(sorted(setup.sumo_options.items())),
        "inputs": input_fingerprints(setup, sumo_version),
        "candidates_sha256": hashlib.sha256(
            _canonical(candidates.trace()).encode("utf-8")
        ).hexdigest(),
    }


def identity_digest(identity: Mapping[str, object]) -> str:
    """Los 16 primeros caracteres de la huella de una identidad; de ahí salen los identificadores
    de la búsqueda y de su etiqueta.
    """
    return hashlib.sha256(_canonical(dict(identity)).encode("utf-8")).hexdigest()[:16]


def _check_consistent(setup: SearchSetup, candidates: CandidateSet) -> None:
    """Los candidatos son de este escenario y se generaron con lo que dice el protocolo."""
    protocol = setup.protocol
    require_supported(protocol)
    problems: list[str] = []
    if candidates.scenario_id != setup.scenario.scenario_id:
        problems.append("el escenario de los candidatos no es el de la búsqueda")
    if candidates.budget != protocol.search_budget:
        problems.append("el presupuesto de los candidatos no es el del protocolo")
    if candidates.attempt_limit != protocol.sampling_attempt_limit:
        problems.append("el límite de intentos de los candidatos no es el del protocolo")
    if candidates.seed != protocol.seeds.search[0]:
        problems.append("la semilla de la muestra no es la primera de búsqueda del protocolo")
    if problems:
        raise ReferenciasError(ErrorCode.INPUT_SCHEMA, "; ".join(problems), "candidates")


class _Record(BaseModel):
    """Una línea de la bitácora (se valida al leerla)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["header", "program", "inputs", "seed"]
    identity: dict[str, Any] | None = None
    candidate_id: str | None = None
    program_dir: str | None = None
    stage: Literal["search", "finalists"] | None = None
    seed: int | None = None
    inputs_dir: str | None = None
    outcome: dict[str, Any] | None = None


class _Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    seed: int
    run_id: str | None
    run_status: str
    mean_delay_s: float | None
    mean_queue_veh: float | None
    mean_stops: float | None
    teleports: int
    collisions: int
    problems: list[
        Literal[
            "run_failed",
            "evaluation_failed",
            "cohort_incomplete",
            "teleports",
            "collisions",
            "zone_incomplete",
        ]
    ]
    message: str | None


def _bad_journal(message: str) -> ReferenciasError:
    return ReferenciasError(ErrorCode.INPUT_SCHEMA, f"bitácora inválida: {message}", "journal")


@dataclass
class _State:
    """Lo anotado en la bitácora: programas, y carpetas de entradas y resultados por (etapa,
    candidato, semilla).
    """

    programs: dict[str, Path]
    inputs: dict[tuple[Stage, str, int], Path]
    outcomes: dict[tuple[Stage, str, int], SeedOutcome]


def _parse_lines(raw: bytes) -> list[_Record]:
    """Los registros de las líneas completas. Lo que sigue al último salto de línea (una línea
    que el proceso no alcanzó a terminar) no cuenta.
    """
    records: list[_Record] = []
    for number, line in enumerate(raw.split(_NEWLINE)[:-1], start=1):
        try:
            records.append(_Record.model_validate_json(line))
        except ValidationError as error:
            raise _bad_journal(f"la línea {number} no es un registro válido") from error
    return records


def _outcome_of(record: _Record) -> SeedOutcome:
    try:
        data = _Outcome.model_validate(record.outcome)
    except ValidationError as error:
        raise _bad_journal("un resultado no tiene la forma esperada") from error
    problems: tuple[SeedProblem, ...] = tuple(data.problems)
    return SeedOutcome(
        seed=data.seed,
        run_id=data.run_id,
        run_status=data.run_status,
        mean_delay_s=data.mean_delay_s,
        mean_queue_veh=data.mean_queue_veh,
        mean_stops=data.mean_stops,
        teleports=data.teleports,
        collisions=data.collisions,
        problems=problems,
        message=data.message,
    )


def _load(path: Path, identity: Mapping[str, object], setup: SearchSetup) -> _State:
    """Lee la bitácora (o la empieza) y comprueba que es de esta búsqueda."""
    state = _State({}, {}, {})
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _append(path, {"type": "header", "identity": dict(identity)})
        return state
    if path.is_symlink() or not path.is_file():
        raise _bad_journal("no es un archivo normal")
    if path.stat().st_size > MAX_JOURNAL_BYTES:
        raise _bad_journal(f"supera {MAX_JOURNAL_BYTES} bytes")
    raw = path.read_bytes()
    records = _parse_lines(raw)
    if not records or records[0].type != "header":
        raise _bad_journal("no empieza con la identidad de la búsqueda")
    header = records[0].identity or {}
    if header.get("journal_version") != JOURNAL_VERSION:
        raise _bad_journal(
            f"es de una versión anterior ({header.get('journal_version')}) y no se puede "
            "reanudar: no guarda la huella de sus insumos"
        )
    if header != json.loads(_canonical(dict(identity))):
        raise _bad_journal(
            "es de otra búsqueda (cambió el caso, la demanda, las rutas, los tipos de vehículo, "
            "el protocolo, SUMO o los candidatos)"
        )
    for record in records[1:]:
        _apply(record, state, setup)
    _check_links(state, setup)
    complete = raw.rfind(_NEWLINE) + 1
    if complete < len(raw):
        # Se quita la línea cortada para que el próximo registro empiece en una línea nueva.
        with path.open("r+b") as handle:
            handle.truncate(complete)
    return state


def _check_inputs_folder(
    folder: Path, setup: SearchSetup, seed: int, hashes: Mapping[str, str | None]
) -> tuple[str, str]:
    """Comprueba una carpeta de entradas anotada contra los insumos de esta búsqueda y devuelve la
    huella de su manifiesto (a la que se ata cada corrida) y la de su programa.
    """
    try:
        manifest = verify_inputs(folder)
    except DomainError as error:
        raise _bad_journal(
            f"la carpeta de entradas {folder.name} no se puede verificar: {error.message}"
        ) from error
    found: dict[str, object] = {
        "case_sha256": manifest.case_sha256,
        "network_sha256": manifest.network.sha256,
        "scenario_sha256": manifest.scenario_sha256,
        "routes_sha256": manifest.routes_sha256,
        "vehicle_types_sha256": manifest.vehicle_types_sha256,
        "scenario_id": manifest.scenario_id,
        "sumo_seed": manifest.seeds.sumo_seed,
        "sumo_options": manifest.sumo_options,
        "inputs_schema_version": manifest.schema_version,
    }
    wanted: dict[str, object] = {
        **hashes,
        "scenario_id": setup.scenario.scenario_id,
        "sumo_seed": seed,
        "sumo_options": dict(setup.sumo_options),
        "inputs_schema_version": INPUTS_SCHEMA_VERSION,
    }
    different = sorted(name for name, value in wanted.items() if found[name] != value)
    if different:
        raise _bad_journal(
            f"la carpeta de entradas {folder.name} no corresponde a esta búsqueda "
            f"({', '.join(different)})"
        )
    return sha256_file(folder / "manifiesto.json"), manifest.program.sha256


def _check_run_link(setup: SearchSetup, run_id: str, inputs_sha256: str) -> None:
    """La corrida anotada existe y salió de la carpeta de entradas anotada.

    El manifiesto de la corrida guarda la huella del manifiesto de sus entradas, que a su vez dice
    el escenario, el caso, el programa y la semilla: con esa huella basta para atarlas.
    """
    path = _inside(setup.runs_root, run_id, "una corrida") / MANIFEST
    try:
        with path.open("rb") as stream:
            data = read_at_most(stream, MAX_RUN_MANIFEST_BYTES + 1)
    except OSError as error:
        raise _bad_journal(f"la corrida {run_id} no se puede leer") from error
    if len(data) > MAX_RUN_MANIFEST_BYTES:
        raise _bad_journal(f"el manifiesto de la corrida {run_id} es demasiado grande")
    try:
        manifest = RunManifest.model_validate_json(data)
    except ValidationError as error:
        raise _bad_journal(f"el manifiesto de la corrida {run_id} no es válido") from error
    artifacts = {artifact.artifact_id: artifact.sha256 for artifact in manifest.inputs}
    if artifacts.get(RUN_INPUTS_ARTIFACT) != inputs_sha256:
        raise _bad_journal(f"la corrida {run_id} no salió de las entradas anotadas")


def _check_links(state: _State, setup: SearchSetup) -> None:
    """Cada carpeta de entradas y cada corrida anotadas son de los insumos de esta búsqueda."""
    hashes = _input_hashes(setup)
    inputs_sha: dict[tuple[Stage, str, int], str] = {}
    for key, folder in state.inputs.items():
        inputs_sha[key], program_sha = _check_inputs_folder(folder, setup, key[2], hashes)
        program = state.programs.get(key[1])
        if program is not None:
            recorded = read_program(program).files.get(PROGRAM_FILE)
            if recorded != program_sha:
                raise _bad_journal(f"las entradas {folder.name} no usan el programa anotado")
    for key, outcome in state.outcomes.items():
        if outcome.run_id is None:
            continue
        if key not in inputs_sha:
            raise _bad_journal("un resultado no tiene su carpeta de entradas anotada")
        _check_run_link(setup, outcome.run_id, inputs_sha[key])


def _inside(root: Path, text: str, what: str) -> Path:
    """``root / text`` si ``text`` es una ruta relativa que no sale de ``root``."""
    relative = Path(text)
    # ``anchor`` cubre la unidad y la raíz: en Windows «/x» no es absoluta pero sí sale de ``root``.
    if relative.anchor or ".." in relative.parts or not relative.parts:
        raise _bad_journal(f"{what} está fuera de su carpeta")
    return root / relative


def _key(record: _Record) -> tuple[Stage, str, int] | None:
    """Etapa, candidato y semilla de un registro, si los tiene todos."""
    if record.stage is None or not record.candidate_id or record.seed is None:
        return None
    return record.stage, record.candidate_id, record.seed


def _apply(record: _Record, state: _State, setup: SearchSetup) -> None:
    if record.type == "program" and record.candidate_id and record.program_dir:
        folder = _inside(setup.programs_root, record.program_dir, "un programa")
        read_program(folder)
        state.programs[record.candidate_id] = folder
        return
    key = _key(record)
    if record.type == "inputs" and key is not None and record.inputs_dir:
        if key in state.inputs:
            raise _bad_journal("una carpeta de entradas está anotada dos veces")
        state.inputs[key] = _inside(setup.inputs_root, record.inputs_dir, "una carpeta de entradas")
        return
    if record.type == "seed" and key is not None:
        outcome = _outcome_of(record)
        if outcome.seed != key[2]:
            raise _bad_journal("un resultado no es de la semilla anotada")
        if key in state.outcomes:
            raise _bad_journal("un resultado está anotado dos veces")
        state.outcomes[key] = outcome
        return
    raise _bad_journal(f"registro {record.type!r} incompleto o fuera de lugar")


_journal_lock = threading.Lock()


def _append(path: Path, data: Mapping[str, object]) -> None:
    line = _canonical(dict(data)).encode("utf-8") + _NEWLINE
    with _journal_lock, path.open("ab") as handle:
        handle.write(line)
        handle.flush()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _program_for(setup: SearchSetup, candidate: Candidate, state: _State, journal: Path) -> Path:
    if candidate.candidate_id in state.programs:
        return state.programs[candidate.candidate_id]
    program = compile_program(setup.case, setup.network_map, candidate.durations_s)
    folder = publish_program(setup.programs_root, setup.case, program)
    _append(
        journal,
        {
            "type": "program",
            "candidate_id": candidate.candidate_id,
            "program_dir": _relative(folder, setup.programs_root),
        },
    )
    state.programs[candidate.candidate_id] = folder
    return folder


def _inputs_for(setup: SearchSetup, job: "_Job", state: _State, journal: Path) -> Path:
    """La carpeta de entradas del trabajo: la anotada si ya existe; si no, una nueva, anotada en
    cuanto se publica (al seguir una búsqueda cortada no se vuelve a preparar).
    """
    key = (job.stage, job.candidate.candidate_id, job.seed)
    with _journal_lock:
        known = state.inputs.get(key)
    if known is not None:
        return known
    request = PreparationRequest(
        case=setup.case,
        case_dir=setup.case_dir,
        scenario=setup.scenario,
        routes=setup.routes,
        vehicle_types=setup.vehicle_types,
        program_dir=job.program_dir,
        sumo_seed=job.seed,
        sumo_options=setup.sumo_options,
    )
    inputs = publish_inputs(setup.inputs_root, request)
    _append(
        journal,
        {
            "type": "inputs",
            "stage": job.stage,
            "candidate_id": job.candidate.candidate_id,
            "seed": job.seed,
            "inputs_dir": _relative(inputs, setup.inputs_root),
        },
    )
    with _journal_lock:
        state.inputs[key] = inputs
    return inputs


def _evaluate_seed(
    setup: SearchSetup, inputs: Path, seed: int, cancel: threading.Event | None
) -> SeedOutcome:
    result = run_inputs(
        inputs, setup.runs_root, sumo=setup.sumo, limits=setup.limits, cancel=cancel
    )
    manifest = result.manifest
    if manifest.status != "succeeded":
        message = f"la corrida terminó con estado {manifest.status}"
        return failed_seed(seed, manifest.run_id, manifest.status, "run_failed", message)
    try:
        metrics = evaluate_run(inputs, setup.runs_root, manifest.run_id, setup.case, setup.protocol)
    except DomainError as error:
        return failed_seed(
            seed, manifest.run_id, manifest.status, "evaluation_failed", error.message
        )
    return seed_outcome(seed, metrics)


@dataclass(frozen=True)
class _Execution:
    """Cómo se corre: bitácora, corridas a la vez, permiso para lanzar y cancelación."""

    journal: Path
    workers: int
    can_start: Callable[[], bool] | None
    cancel: threading.Event
    wait_s: float


@dataclass(frozen=True)
class _Job:
    stage: Stage
    candidate: Candidate
    program_dir: Path
    seed: int


def _run_jobs(
    setup: SearchSetup, jobs: Sequence[_Job], state: _State, execution: _Execution
) -> None:
    cancel = execution.cancel
    can_start = execution.can_start

    def work(job: _Job) -> None:
        while can_start is not None and not cancel.is_set() and not can_start():
            cancel.wait(execution.wait_s)
        if cancel.is_set():
            return
        inputs = _inputs_for(setup, job, state, execution.journal)
        outcome = _evaluate_seed(setup, inputs, job.seed, cancel)
        if cancel.is_set():
            return  # una corrida cancelada no es un resultado: se repetirá al seguir
        _append(
            execution.journal,
            {
                "type": "seed",
                "stage": job.stage,
                "candidate_id": job.candidate.candidate_id,
                "seed": job.seed,
                "inputs_dir": _relative(inputs, setup.inputs_root),
                "outcome": outcome.to_json(),
            },
        )
        with _journal_lock:
            state.outcomes[(job.stage, job.candidate.candidate_id, job.seed)] = outcome

    with ThreadPoolExecutor(max_workers=execution.workers) as pool:
        futures = [pool.submit(work, job) for job in jobs]
        try:
            for future in futures:
                future.result()
        except BaseException:
            cancel.set()
            raise


def _vector(candidate: Candidate) -> tuple[int, ...]:
    return tuple(candidate.ticks.values())


def _scores(
    stage: Stage, candidates: Sequence[Candidate], seeds: Sequence[int], state: _State
) -> tuple[CandidateScore, ...]:
    return tuple(
        score_candidate(
            candidate.candidate_id,
            _vector(candidate),
            stage,
            seeds,
            (
                state.outcomes[(stage, candidate.candidate_id, seed)]
                for seed in seeds
                if (stage, candidate.candidate_id, seed) in state.outcomes
            ),
        )
        for candidate in candidates
    )


def _positive(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA, f"{field} debe ser un entero mayor que cero", field
        )
    return value


def _stage(  # noqa: PLR0913  (cada argumento es una pieza distinta de la etapa)
    setup: SearchSetup,
    stage: Stage,
    *,
    candidates: Sequence[Candidate],
    seeds: Sequence[int],
    state: _State,
    execution: _Execution,
) -> tuple[CandidateScore, ...]:
    jobs = [
        _Job(stage, candidate, _program_for(setup, candidate, state, execution.journal), seed)
        for candidate in candidates
        for seed in seeds
        if (stage, candidate.candidate_id, seed) not in state.outcomes
    ]
    _run_jobs(setup, jobs, state, execution)
    return _scores(stage, candidates, seeds, state)


def run_search(  # noqa: PLR0913  (los opcionales son de solo palabra clave)
    setup: SearchSetup,
    candidates: CandidateSet,
    journal_path: Path,
    *,
    workers: int = 4,
    can_start: Callable[[], bool] | None = None,
    cancel: threading.Event | None = None,
    wait_s: float = _WAIT_S,
) -> SearchOutcome:
    """Evalúa los candidatos, elige finalistas, los reevalúa y elige la referencia.

    Raises:
        ReferenciasError: si los candidatos no son de este escenario o no se generaron con el
            protocolo, si la bitácora es de otra búsqueda o está dañada, o si ``workers`` no es un
            entero positivo.
        DomainError: lo que lanzan la compilación del programa o la preparación de las entradas
            (no es culpa de un candidato, así que detiene la búsqueda).
    """
    workers = _positive(workers, "workers")
    _check_consistent(setup, candidates)
    binary = setup.sumo if setup.sumo is not None else find_sumo()
    identity = search_identity(setup, candidates, sumo_version(binary))
    state = _load(journal_path, identity, setup)
    stop = threading.Event() if cancel is None else cancel
    protocol = setup.protocol
    execution = _Execution(journal_path, workers, can_start, stop, wait_s)
    pool = list(candidates.candidates)
    search_scores = _stage(
        setup,
        "search",
        candidates=pool,
        seeds=protocol.seeds.search,
        state=state,
        execution=execution,
    )
    finalist_scores: tuple[CandidateScore, ...] = ()
    selection: Selection | None = None
    if not stop.is_set():
        chosen = choose_finalists(search_scores, protocol.finalist_count, protocol.tie_epsilon_s)
        by_id = {candidate.candidate_id: candidate for candidate in pool}
        finalists = [by_id[score.candidate_id] for score in chosen]
        finalist_scores = _stage(
            setup,
            "finalists",
            candidates=finalists,
            seeds=protocol.seeds.finalists,
            state=state,
            execution=execution,
        )
    if not stop.is_set():
        selection = select(
            search_scores, finalist_scores, protocol.finalist_count, protocol.tie_epsilon_s
        )
    return SearchOutcome(
        identity=identity,
        candidates=candidates,
        search_scores=search_scores,
        finalist_scores=finalist_scores,
        selection=selection,
        simulation_count=len(state.outcomes),
        interrupted=stop.is_set(),
    )
