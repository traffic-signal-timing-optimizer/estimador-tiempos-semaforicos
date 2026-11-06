"""Unidades de las búsquedas con su etiqueta y de los comparadores (DEV31 F3).

- ``datos/derivados/referencias/<caso>/<carpeta>``: ``label.json``, ``traza.json`` y
  ``cobertura.json`` dan ``simulacion.busquedas``, ``candidatos``, ``candidato_semillas`` y
  ``etiquetas``, y los planes de los candidatos. La traza es también la que dice de qué etapa y de
  qué protocolo es cada corrida (``trace_index``).
- ``datos/derivados/comparadores/<caso>/<carpeta>``: ``comparadores.json`` y ``parametros.json``
  dan ``simulacion.comparadores``, el plan vigente (``caso.planes_observados``) y el plan de
  Webster si aplica.

La traza y la cobertura no tienen un modelo de lectura en el proyecto: se leen con
``semaforo.bd.carga.crudo`` y se comprueban contra la etiqueta y su manifiesto.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from semaforo.bd.carga import crudo
from semaforo.bd.carga.corridas import SearchRun
from semaforo.bd.carga.modelo import (
    DATA_ROOT,
    CargaError,
    FileRecord,
    Row,
    Unit,
    read_file,
    verified_record,
)
from semaforo.bd.carga.planes import add_plan
from semaforo.dominio.case import Case
from semaforo.dominio.errors import ErrorCode
from semaforo.referencias.comparators import COMPARATORS_FILE, PARAMETERS_FILE, read_comparators
from semaforo.referencias.comparators import MANIFEST_FILE as COMPARATORS_MANIFEST
from semaforo.referencias.label import (
    COVERAGE_FILE,
    LABEL_FILE,
    TRACE_FILE,
    StoredLabel,
    read_label,
)
from semaforo.referencias.label import MANIFEST_FILE as LABEL_MANIFEST

__all__ = ["Trace", "comparators_unit", "read_trace", "search_unit", "trace_runs"]


@dataclass(frozen=True)
class Trace:
    """La etiqueta verificada, su traza y su cobertura, con los registros de sus archivos."""

    folder: str
    stored: StoredLabel
    trace: dict[str, object]
    coverage: dict[str, object]
    files: tuple[FileRecord, ...]

    @property
    def trace_record(self) -> FileRecord:
        return next(f for f in self.files if f.relative.endswith(f"/{TRACE_FILE}"))


def read_trace(workspace: Path, folder: str) -> Trace:
    """La carpeta de una etiqueta, verificada (``read_label``) y con su traza leída."""
    stored = read_label(workspace / folder)
    manifest, _ = read_file(workspace, DATA_ROOT, f"{folder}/{LABEL_MANIFEST}", "manifest")
    files = stored.manifest.files
    label = verified_record(
        workspace,
        DATA_ROOT,
        f"{folder}/{LABEL_FILE}",
        "label",
        files[LABEL_FILE],
        manifest.artifact_id,
    )
    trace, trace_bytes = read_file(
        workspace,
        DATA_ROOT,
        f"{folder}/{TRACE_FILE}",
        "trace",
        expected=files[TRACE_FILE],
        manifest=manifest.artifact_id,
    )
    coverage, coverage_bytes = read_file(
        workspace,
        DATA_ROOT,
        f"{folder}/{COVERAGE_FILE}",
        "coverage",
        expected=files[COVERAGE_FILE],
        manifest=manifest.artifact_id,
    )
    return Trace(
        folder=folder,
        stored=stored,
        trace=crudo.mapping(crudo.loads(trace_bytes, TRACE_FILE), TRACE_FILE),
        coverage=crudo.mapping(crudo.loads(coverage_bytes, COVERAGE_FILE), COVERAGE_FILE),
        files=(manifest, label, trace, coverage),
    )


# --- la traza --------------------------------------------------------------------------------


def _section(trace: Trace, name: str) -> dict[str, object]:
    return crudo.mapping(trace.trace.get(name), f"{TRACE_FILE}: {name}")


def _candidates(trace: Trace) -> list[dict[str, object]]:
    section = _section(trace, "candidates")
    where = f"{TRACE_FILE}: candidates.candidates"
    return [crudo.mapping(item, where) for item in crudo.items(section.get("candidates"), where)]


def _durations(candidate: Mapping[str, object], where: str) -> dict[str, float]:
    raw = crudo.mapping(candidate.get("durations_s"), where)
    return {slot: crudo.number(value, where) for slot, value in raw.items()}


def _scores(trace: Trace, name: str) -> dict[str, dict[str, object]]:
    where = f"{TRACE_FILE}: {name}"
    scores = [crudo.mapping(item, where) for item in crudo.items(trace.trace.get(name), where)]
    return {crudo.text(score.get("candidate_id"), where): score for score in scores}


def _seeds(score: Mapping[str, object], where: str) -> list[dict[str, object]]:
    return [crudo.mapping(item, where) for item in crudo.items(score.get("seeds"), where)]


def trace_runs(trace: Trace) -> dict[str, SearchRun]:
    """Cada corrida de la búsqueda con su etapa, protocolo, semilla y plan."""
    identity = _section(trace, "identity")
    protocol = crudo.text(identity.get("protocol_id"), f"{TRACE_FILE}: identity.protocol_id")
    durations = {
        crudo.text(c.get("candidate_id"), TRACE_FILE): _durations(c, TRACE_FILE)
        for c in _candidates(trace)
    }
    search_id = trace.stored.label.search_run_id
    runs: dict[str, SearchRun] = {}
    for name in ("search_scores", "finalist_scores"):
        for candidate, score in _scores(trace, name).items():
            where = f"{TRACE_FILE}: {name}.{candidate}"
            stage = crudo.text(score.get("stage"), where)
            if candidate not in durations:
                raise CargaError(ErrorCode.INPUT_SCHEMA, "candidato sin plan en la traza", where)
            for seed in _seeds(score, where):
                run_id = crudo.optional_text(seed.get("run_id"), where)
                if run_id is None:
                    continue
                if run_id in runs:
                    raise CargaError(ErrorCode.INPUT_SCHEMA, "corrida usada dos veces", run_id)
                runs[run_id] = SearchRun(
                    search_id=search_id,
                    stage=stage,
                    protocol_id=protocol,
                    seed=crudo.integer(seed.get("seed"), where),
                    durations_s=durations[candidate],
                )
    return runs


def _search_row(trace: Trace) -> Row:
    stored = trace.stored
    section = _section(trace, "candidates")
    identity = _section(trace, "identity")
    selection = _section(trace, "selection")
    where = TRACE_FILE
    current = crudo.mapping(section.get("current_plan"), f"{where}: current_plan")
    webster = section.get("webster")
    return {
        "busqueda_id": stored.label.search_run_id,
        "escenario_id": crudo.text(identity.get("scenario_id"), where),
        "caso_id": crudo.text(identity.get("case_id"), where),
        "caso_version": crudo.text(identity.get("case_version"), where),
        "protocolo_id": crudo.text(identity.get("protocol_id"), where),
        "estado_protocolo": crudo.text(identity.get("protocol_status"), where),
        "metodo": crudo.text(section.get("method"), where),
        "version_busqueda": crudo.text(section.get("search_version"), where),
        "version_reglas": crudo.text(section.get("rules_version"), where),
        "version_identidad": stored.manifest.identity_version,
        "version_bitacora": crudo.optional_text(identity.get("journal_version"), where),
        "semilla": crudo.integer(section.get("seed"), where),
        "presupuesto": crudo.integer(section.get("budget"), where),
        "cuenta_presupuesto": crudo.text(section.get("budget_counts"), where),
        "presupuesto_usado": crudo.integer(section.get("budget_used"), where),
        "limite_intentos": crudo.integer(section.get("attempt_limit"), where),
        "intentos": crudo.integer(section.get("attempts"), where),
        "duplicados": crudo.integer(section.get("duplicates"), where),
        "inviables": crudo.integer(section.get("infeasible"), where),
        "inviables_por_regla": crudo.mapping(section.get("infeasible_by_rule"), where),
        "cuadricula_factible": crudo.optional_integer(section.get("grid_feasible"), where),
        "limite_cuadricula": crudo.integer(section.get("grid_scan_limit"), where),
        "tamano_espacio": crudo.optional_integer(section.get("space_size"), where),
        "agotado": crudo.boolean(section.get("exhausted"), where),
        "estado_plan_vigente": crudo.text(current.get("status"), where),
        "estado_webster": None
        if webster is None
        else crudo.text(crudo.mapping(webster, where).get("status"), where),
        "finalistas": crudo.integer(identity.get("finalist_count"), where),
        "epsilon_empate_s": crudo.number(identity.get("tie_epsilon_s"), where),
        "semillas_busqueda": crudo.items(identity.get("seeds_search"), where),
        "semillas_finalistas": crudo.items(identity.get("seeds_finalists"), where),
        "opciones_sumo": crudo.mapping(identity.get("sumo_options"), where),
        "huella_candidatos": crudo.text(identity.get("candidates_sha256"), where),
        "regla_seleccion": crudo.text(selection.get("rule"), where),
        "estado_seleccion": crudo.text(selection.get("status"), where),
        "motivo_sin_referencia": crudo.optional_text(selection.get("reason"), where),
        "cobertura": trace.coverage,
        "simulaciones": crudo.integer(trace.trace.get("simulation_count"), where),
        "interrumpida": crudo.boolean(trace.trace.get("interrupted"), where),
    }


def _score_columns(score: Mapping[str, object] | None, suffix: str, where: str) -> Row:
    """Las columnas de un candidato en una etapa (``busqueda`` o ``finalistas``)."""
    if score is None:
        names = (
            f"elegible_{suffix}",
            f"puntaje_{suffix}_s",
            f"cola_media_{suffix}_veh",
            f"detenciones_media_{suffix}",
            f"problemas_{suffix}",
            f"semillas_faltantes_{suffix}",
        )
        return {name: None for name in names}
    return {
        f"elegible_{suffix}": crudo.boolean(score.get("eligible"), where),
        f"puntaje_{suffix}_s": crudo.optional_number(score.get("score_s"), where),
        f"cola_media_{suffix}_veh": crudo.optional_number(score.get("mean_queue_veh"), where),
        f"detenciones_media_{suffix}": crudo.optional_number(score.get("mean_stops"), where),
        f"problemas_{suffix}": score.get("problems"),
        f"semillas_faltantes_{suffix}": score.get("missing_seeds"),
    }


def _ranking(selection: Mapping[str, object], name: str) -> dict[str, int]:
    where = f"{TRACE_FILE}: selection.{name}"
    names = [crudo.text(item, where) for item in crudo.items(selection.get(name), where)]
    return {candidate: position for position, candidate in enumerate(names, start=1)}


def _seed_row(search_id: str, candidate: str, seed: Mapping[str, object], where: str) -> Row:
    return {
        "busqueda_id": search_id,
        "candidato_id": candidate,
        "semilla": crudo.integer(seed.get("seed"), where),
        "run_id": crudo.optional_text(seed.get("run_id"), where),
        "estado_corrida": crudo.optional_text(seed.get("run_status"), where),
        "demora_media_s": crudo.optional_number(seed.get("mean_delay_s"), where),
        "cola_media_veh": crudo.optional_number(seed.get("mean_queue_veh"), where),
        "detenciones_media": crudo.optional_number(seed.get("mean_stops"), where),
        "teletransportes": crudo.integer(seed.get("teleports"), where),
        "choques": crudo.integer(seed.get("collisions"), where),
        "problemas": seed.get("problems"),
        "mensaje": crudo.optional_text(seed.get("message"), where),
        "clase_incidente": crudo.optional_text(seed.get("incident_class"), where),
    }


def search_unit(trace: Trace, cases: Mapping[tuple[str, str], Case]) -> Unit:
    """La unidad de una búsqueda con su etiqueta."""
    stored = trace.stored
    label, manifest = stored.label, stored.manifest
    case = cases.get((manifest.case_id, manifest.case_version))
    if case is None:
        raise CargaError(ErrorCode.INPUT_SCHEMA, f"falta el caso {manifest.case_id}", trace.folder)
    unit = Unit(key=f"busqueda:{label.search_run_id}", kind="search")
    for record in trace.files:
        unit.add_file(record)
    source = trace.trace_record
    label_record = next(f for f in trace.files if f.kind == "label")
    search = _search_row(trace)
    if (search["escenario_id"], search["protocolo_id"]) != (label.scenario_id, label.protocol_id):
        raise CargaError(ErrorCode.INPUT_SCHEMA, "la traza no es de su etiqueta", trace.folder)
    unit.add("simulacion.busquedas", search, source)
    selection = _section(trace, "selection")
    search_ranking = _ranking(selection, "search_ranking")
    finalist_ranking = _ranking(selection, "finalist_ranking")
    finalists = set(_ranking(selection, "finalists"))
    winner = crudo.optional_text(selection.get("winner"), TRACE_FILE)
    search_scores = _scores(trace, "search_scores")
    finalist_scores = _scores(trace, "finalist_scores")
    for order, candidate in enumerate(_candidates(trace)):
        identifier = crudo.text(candidate.get("candidate_id"), TRACE_FILE)
        where = f"{TRACE_FILE}: {identifier}"
        plan = add_plan(unit, case, _durations(candidate, where), source)
        unit.add(
            "simulacion.candidatos",
            {
                "busqueda_id": label.search_run_id,
                "candidato_id": identifier,
                "plan_id": plan,
                "origen": crudo.text(candidate.get("origin"), where),
                "consume_presupuesto": crudo.boolean(candidate.get("consumes_budget"), where),
                "orden": order,
                **_score_columns(search_scores.get(identifier), "busqueda", where),
                "posicion_busqueda": search_ranking.get(identifier),
                "finalista": identifier in finalists,
                **_score_columns(finalist_scores.get(identifier), "finalistas", where),
                "posicion_finalistas": finalist_ranking.get(identifier),
                "ganador": identifier == winner,
            },
            source,
        )
    for name in ("search_scores", "finalist_scores"):
        for candidate, score in _scores(trace, name).items():
            where = f"{TRACE_FILE}: {name}.{candidate}"
            stage = crudo.text(score.get("stage"), where)
            for seed in _seeds(score, where):
                row = _seed_row(label.search_run_id, candidate, seed, where)
                unit.add("simulacion.candidato_semillas", {**row, "etapa": stage}, source)
                if row["run_id"] is not None:
                    unit.need(
                        "simulacion.corridas",
                        {"run_id": row["run_id"]},
                        f"falta la corrida {row['run_id']}",
                    )
    plan_id = None
    greens = None
    if label.plan is not None:
        plan_id = add_plan(
            unit, case, label.plan.slot_durations_s, label_record, cycle_s=label.plan.cycle_s
        )
        greens = dict(label.plan.greens_s)
    unit.add(
        "simulacion.etiquetas",
        {
            "etiqueta_id": label.label_id,
            "escenario_id": label.scenario_id,
            "caso_id": manifest.case_id,
            "caso_version": label.case_version,
            "busqueda_id": label.search_run_id,
            "protocolo_id": label.protocol_id,
            "estado": label.status,
            "plan_id": plan_id,
            "verdes_s": greens,
            "candidatos_cantidad": label.candidate_count,
            "simulaciones_cantidad": label.simulation_count,
            "estado_evidencia": label.evidence_status,
            "motivo": label.reason,
            "red_sha256": manifest.network_sha256,
            "creada_en": manifest.created_at,
        },
        label_record,
    )
    unit.need(
        "experimento.escenarios",
        {"escenario_id": label.scenario_id},
        f"falta el escenario {label.scenario_id}",
    )
    unit.need(
        "experimento.protocolos",
        {"protocolo_id": label.protocol_id},
        f"falta el protocolo {label.protocol_id}",
    )
    return unit


# --- comparadores ----------------------------------------------------------------------------


def comparators_unit(workspace: Path, folder: str, cases: Mapping[tuple[str, str], Case]) -> Unit:
    """La unidad de una publicación de comparadores."""
    stored = read_comparators(workspace / folder)
    content, parameters = stored.comparators, stored.parameters
    case = cases.get((content.case_id, content.case_version))
    if case is None:
        raise CargaError(ErrorCode.INPUT_SCHEMA, f"falta el caso {content.case_id}", folder)
    case_folder, publication = folder.rsplit("/", 2)[-2:]
    unit = Unit(key=f"comparadores:{case_folder}:{publication}", kind="comparators")
    manifest, _ = read_file(workspace, DATA_ROOT, f"{folder}/{COMPARATORS_MANIFEST}", "manifest")
    unit.add_file(manifest)
    files = stored.manifest.files
    comparators = unit.add_file(
        verified_record(
            workspace,
            DATA_ROOT,
            f"{folder}/{COMPARATORS_FILE}",
            "comparators",
            files[COMPARATORS_FILE],
            manifest.artifact_id,
        )
    )
    unit.add_file(
        verified_record(
            workspace,
            DATA_ROOT,
            f"{folder}/{PARAMETERS_FILE}",
            "parameters",
            files[PARAMETERS_FILE],
            manifest.artifact_id,
        )
    )
    current = content.current_plan
    current_plan = add_plan(
        unit, case, current.plan.durations_s, comparators, cycle_s=current.plan.cycle_s
    )
    observed = f"{content.case_id}:{current.program_folder}"
    unit.add(
        "caso.planes_observados",
        {
            "plan_observado_id": observed,
            "caso_id": content.case_id,
            "caso_version": content.case_version,
            "plan_id": current_plan,
            "fuente": current.source,
            "variacion_horaria": current.hourly_variation,
            "confirmado_por": current.confirmed_by,
            "carpeta_programa": current.program_folder,
            "reglas_incumplidas": list(current.violated),
        },
        comparators,
    )
    webster = content.webster
    webster_plan = None
    if webster.plan is not None:
        webster_plan = add_plan(
            unit, case, webster.plan.durations_s, comparators, cycle_s=webster.plan.cycle_s
        )
    path = webster.critical_path
    unit.add(
        "simulacion.comparadores",
        {
            "comparador_id": f"{case_folder}:{publication}",
            "escenario_id": content.scenario_id,
            "caso_id": content.case_id,
            "caso_version": content.case_version,
            "origen_caso": content.case_origin,
            "origen_demanda": content.demand_origin,
            "origen_evidencia": content.evidence_origin,
            "plan_observado_id": observed,
            "webster_estado": webster.status,
            "webster_adaptacion": webster.adaptation,
            "conjunto_parametros": webster.parameter_set,
            "provisional": webster.provisional,
            "webster_ciclo_s": webster.webster_cycle_s,
            "webster_plan_id": webster_plan,
            "webster_reglas_incumplidas": list(webster.violated),
            "webster_problemas": [p.model_dump(mode="json") for p in webster.problems],
            "y_critico": None if path is None else path.y,
            "tiempo_perdido_s": None if path is None else path.lost_time_s,
            "ciclo_recorrido_s": None if path is None else path.cycle_s,
            "carriles_criticos": None if path is None else list(path.lane_ids),
            "tramos_perdidos": None if path is None else list(path.lost_slot_ids),
            "saturacion_vph_carril": parameters.saturation_flow_veh_h_lane,
            "equivalencias_vehiculo": dict(parameters.vehicle_equivalence),
            "estado_parametros": parameters.status,
            "parametros": parameters.model_dump(mode="json"),
        },
        comparators,
    )
    unit.need(
        "experimento.escenarios",
        {"escenario_id": content.scenario_id},
        f"falta el escenario {content.scenario_id}",
    )
    return unit
