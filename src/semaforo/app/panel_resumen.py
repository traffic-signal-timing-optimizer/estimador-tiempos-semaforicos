"""Las cuentas del panel (DEV31 F5): series de corridas y comparación con el plan observado.

Son funciones puras: reciben filas y devuelven filas, sin base ni archivos. Tres reglas que evitan
que el panel diga más de lo que los datos permiten:

- **Una comparación emparejada exige la misma semilla.** Dos planes se restan solo si corrieron con
  el mismo escenario y la misma semilla. Si el plan observado no corrió con esas semillas, se
  muestran los dos grupos lado a lado y se dice que no es una comparación emparejada.
- **Un par válido no tiene incidentes.** Una corrida con teletransportes o sin demora completa no
  entra en la diferencia válida: se muestra aparte, como par medido.
- **Una definición de cola por protocolo.** La demora no depende de la zona de medición, pero la
  cola sí: las series se separan por protocolo, y una réplica de la misma semilla no cuenta dos
  veces.

Nada de esto declara una mejora: no hay inferencia estadística, solo diferencias descriptivas.
"""

import statistics
from collections.abc import Iterable
from typing import Any

__all__ = ["comparisons", "group_stats", "run_series"]

type Row = dict[str, Any]

STAGE_ORDER = {"search": 0, "finalists": 1, "diagnostic": 2, "final": 3}
SEARCH = "search"
FINALISTS = "finalists"
DIAGNOSTIC = "diagnostic"


def _stats(values: Iterable[float | None]) -> Row:
    present = [value for value in values if value is not None]
    if not present:
        return {"n": 0, "media": None, "mediana": None, "minimo": None, "maximo": None}
    return {
        "n": len(present),
        "media": statistics.fmean(present),
        "mediana": statistics.median(present),
        "minimo": min(present),
        "maximo": max(present),
    }


def _one_per_seed(runs: list[Row]) -> list[Row]:
    """Una corrida por plan y semilla: una réplica o la misma corrida con otra zona no suma."""
    chosen: dict[tuple[object, object], Row] = {}
    for run in sorted(runs, key=lambda item: str(item["run_id"])):
        chosen.setdefault((run.get("plan_id"), run.get("semilla_sumo")), run)
    return list(chosen.values())


def group_stats(runs: list[Row]) -> Row:
    """Demora de un grupo de corridas, una por semilla, separando las que tuvieron incidentes."""
    unique = _one_per_seed(runs)
    clean = [run for run in unique if not (run.get("teletransportes_total") or run.get("choques"))]
    troubled = [run for run in unique if run.get("teletransportes_total") or run.get("choques")]
    return {
        "corridas": len(unique),
        "con_incidentes": len(troubled),
        "sin_demora": sum(1 for run in unique if run.get("demora_media_s") is None),
        "demora": _stats(run.get("demora_media_s") for run in unique),
        "demora_sin_incidentes": _stats(run.get("demora_media_s") for run in clean),
        "demora_con_incidentes": _stats(run.get("demora_media_s") for run in troubled),
        "por_semilla": [
            {
                "semilla": run.get("semilla_sumo"),
                "run_id": run.get("run_id"),
                "demora_media_s": run.get("demora_media_s"),
                "cota_inf_demora_s": run.get("cota_inf_demora_s"),
                "cola_media_veh": run.get("cola_media_veh"),
                "teletransportes": run.get("teletransportes_total"),
                "choques": run.get("choques"),
            }
            for run in sorted(unique, key=lambda item: item.get("semilla_sumo") or 0)
        ],
    }


def run_series(runs: list[Row]) -> list[Row]:
    """Las series de corridas: misma etapa y mismo protocolo de medición (no se mezclan)."""
    groups: dict[tuple[str, str], list[Row]] = {}
    for run in runs:
        protocol = run.get("protocolo_metricas_id") or run.get("protocolo_id") or ""
        groups.setdefault((str(run.get("etapa") or ""), str(protocol)), []).append(run)
    series: list[Row] = []
    for (stage, protocol), members in sorted(
        groups.items(), key=lambda item: (STAGE_ORDER.get(item[0][0], 9), item[0][1])
    ):
        seeds = sorted(
            {int(run["semilla_sumo"]) for run in members if run.get("semilla_sumo") is not None}
        )
        series.append(
            {
                "id": f"{stage}|{protocol}",
                "etapa": stage,
                "protocolo": protocol or None,
                "corridas": len(members),
                "planes": len({run.get("plan_id") for run in members}),
                "semillas": seeds,
                "exitosas": sum(1 for run in members if run.get("estado") == "succeeded"),
                "demora_completa": sum(
                    1 for run in members if run.get("estado_demora") == "complete"
                ),
                "con_teletransportes": sum(
                    1 for run in members if run.get("teletransportes_total")
                ),
                "con_choques": sum(1 for run in members if run.get("choques")),
                "demora": _stats(run.get("demora_media_s") for run in _one_per_seed(members)),
                "cola_media": _stats(run.get("cola_media_veh") for run in _one_per_seed(members)),
            }
        )
    return series


def _seed_rows(candidate: Row, rows: list[Row], stage: str) -> dict[int, Row]:
    return {
        int(row["semilla"]): row
        for row in rows
        if row["candidato_id"] == candidate["candidato_id"]
        and row["busqueda_id"] == candidate["busqueda_id"]
        and row["etapa"] == stage
    }


def _valid(row: Row | None) -> bool:
    return row is not None and row.get("demora_media_s") is not None and not row.get("problemas")


def _paired_plan(
    candidate: Row, current: dict[int, Row], rows: list[Row], runs: dict[str, Row]
) -> Row:
    own = _seed_rows(candidate, rows, SEARCH)
    seeds: list[Row] = []
    for seed in sorted(set(own) | set(current)):
        mine, theirs = own.get(seed), current.get(seed)
        my_run = runs.get(str((mine or {}).get("run_id")), {})
        their_run = runs.get(str((theirs or {}).get("run_id")), {})
        measured, reference = my_run.get("demora_media_s"), their_run.get("demora_media_s")
        seeds.append(
            {
                "semilla": seed,
                "run_id": (mine or {}).get("run_id"),
                "run_id_actual": (theirs or {}).get("run_id"),
                "demora_s": measured,
                "demora_actual_s": reference,
                "diferencia_s": (
                    measured - reference if measured is not None and reference is not None else None
                ),
                "valida": _valid(mine) and _valid(theirs),
                "problemas": (mine or {}).get("problemas") or [],
                "problemas_actual": (theirs or {}).get("problemas") or [],
                "teletransportes": (mine or {}).get("teletransportes"),
                "choques": (mine or {}).get("choques"),
            }
        )
    valid = [seed["diferencia_s"] for seed in seeds if seed["valida"]]
    measured_pairs = [seed["diferencia_s"] for seed in seeds if seed["diferencia_s"] is not None]
    reference_mean = _stats(seed["demora_actual_s"] for seed in seeds if seed["valida"])["media"]
    mean_valid = _stats(valid)["media"]
    return {
        "candidato_id": candidate["candidato_id"],
        "plan_id": candidate["plan_id"],
        "ciclo_s": candidate.get("ciclo_s"),
        "origen": candidate.get("origen"),
        "elegible": candidate.get("elegible_busqueda"),
        "posicion": candidate.get("posicion_busqueda"),
        "finalista": candidate.get("finalista"),
        "problemas": candidate.get("problemas_busqueda") or {},
        "por_semilla": seeds,
        "pares_validos": len(valid),
        "pares_medidos": len(measured_pairs),
        "diferencia_valida": _stats(valid),
        "diferencia_medida": _stats(measured_pairs),
        "diferencia_valida_pct": (
            100.0 * mean_valid / reference_mean
            if mean_valid is not None and reference_mean
            else None
        ),
    }


def _usable(run: Row | None) -> bool:
    """Una corrida cuenta para una diferencia: tiene demora y no tuvo atascos ni choques."""
    return (
        run is not None
        and run.get("demora_media_s") is not None
        and not run.get("teletransportes_total")
        and not run.get("choques")
    )


def _finalist_pairs(
    candidate: Row, rows: list[Row], runs: dict[str, Row], actual: dict[int, Row]
) -> Row:
    """El finalista frente al plan actual, semilla por semilla (solo pares en que ambos cuentan)."""
    own = _seed_rows(candidate, rows, FINALISTS)
    seeds: list[Row] = []
    for seed in sorted(own):
        mine = runs.get(str(own[seed].get("run_id")))
        theirs = actual.get(seed)
        both = _usable(mine) and _usable(theirs)
        seeds.append(
            {
                "semilla": seed,
                "demora_s": None if mine is None else mine.get("demora_media_s"),
                "demora_actual_s": None if theirs is None else theirs.get("demora_media_s"),
                "diferencia_s": (
                    mine["demora_media_s"] - theirs["demora_media_s"] if both else None  # type: ignore[index,operator]
                ),
                "valida": both,
            }
        )
    valid = [item["diferencia_s"] for item in seeds if item["valida"]]
    return {
        "candidato_id": candidate["candidato_id"],
        "plan_id": candidate["plan_id"],
        "pares_validos": len(valid),
        "diferencia_valida": _stats(valid),
        "por_semilla": seeds,
    }


def _finalist_plan(
    candidate: Row, rows: list[Row], runs: dict[str, Row], actual: dict[int, Row]
) -> Row:
    own = _seed_rows(candidate, rows, FINALISTS)
    members = [runs[str(row["run_id"])] for row in own.values() if str(row["run_id"]) in runs]
    return {
        "candidato_id": candidate["candidato_id"],
        "plan_id": candidate["plan_id"],
        "ciclo_s": candidate.get("ciclo_s"),
        "elegible": candidate.get("elegible_finalistas"),
        "posicion": candidate.get("posicion_finalistas"),
        "problemas": candidate.get("problemas_finalistas") or {},
        "grupo": group_stats(members),
        "pares_con_plan_actual": _finalist_pairs(candidate, rows, runs, actual),
    }


def _one_comparison(  # noqa: PLR0913  (cada lista de filas tiene su nombre)
    search: Row,
    candidates: list[Row],
    rows: list[Row],
    runs: list[Row],
    *,
    by_id: dict[str, Row],
    observed: str,
) -> Row:
    mine = [row for row in candidates if row["busqueda_id"] == search["busqueda_id"]]
    reference = next((row for row in mine if row["plan_id"] == observed), None)
    current = {} if reference is None else _seed_rows(reference, rows, SEARCH)
    finalists = [row for row in mine if row.get("finalista")]
    scenario = search.get("escenario_id")
    observed_runs = [
        run
        for run in runs
        if run.get("plan_id") == observed and run.get("escenario_id") == scenario
    ]
    finalist_seeds = sorted(
        {
            int(row["semilla"])
            for row in rows
            if row["etapa"] == FINALISTS and row["busqueda_id"] == search["busqueda_id"]
        }
    )
    protocol = search.get("protocolo_id")
    # El plan actual medido con las semillas de los finalistas y con su mismo protocolo.
    with_finalists = [
        run
        for run in observed_runs
        if protocol is not None
        and run.get("protocolo_metricas_id") == protocol
        and run.get("semilla_sumo") in finalist_seeds
    ]
    actual_by_seed = {int(run["semilla_sumo"]): run for run in with_finalists}
    observed_seeds = {run.get("semilla_sumo") for run in with_finalists}
    # Lo demás de diagnóstico, con otro protocolo: no se mezcla con las semillas de finalistas.
    diagnostic = [
        run
        for run in observed_runs
        if run.get("etapa") == DIAGNOSTIC and run.get("protocolo_metricas_id") != protocol
    ]
    return {
        "busqueda_id": search["busqueda_id"],
        "escenario_id": scenario,
        "plan_observado_id": observed,
        "plan_observado_es_candidato": reference is not None,
        "semillas_busqueda": sorted(current),
        "plan_observado_elegible": None
        if reference is None
        else reference.get("elegible_busqueda"),
        "plan_observado_problemas": {}
        if reference is None
        else reference.get("problemas_busqueda") or {},
        "emparejada": sorted(
            (_paired_plan(row, current, rows, by_id) for row in mine if row["plan_id"] != observed),
            key=lambda plan: (
                plan["diferencia_valida"]["media"] is None,
                plan["diferencia_valida"]["media"] or 0.0,
                str(plan["plan_id"]),
            ),
        ),
        "semillas_finalistas": finalist_seeds,
        "finalistas_con_mismas_semillas": bool(finalist_seeds)
        and all(seed in observed_seeds for seed in finalist_seeds),
        "finalistas": [_finalist_plan(row, rows, by_id, actual_by_seed) for row in finalists],
        "plan_observado_diagnostico": group_stats(diagnostic),
        "plan_observado_finalistas": group_stats(with_finalists),
    }


def comparisons(
    searches: list[Row],
    candidates: list[Row],
    seed_rows: list[Row],
    runs: list[Row],
    plans: list[Row],
) -> list[Row]:
    """La comparación con el plan observado, una por búsqueda cuyo caso tiene plan observado."""
    observed = {
        (str(plan["caso_id"]), str(plan["caso_version"])): str(plan["plan_id"])
        for plan in plans
        if plan.get("es_plan_observado")
    }
    by_id = {str(run["run_id"]): run for run in runs}
    found: list[Row] = []
    for search in searches:
        plan = observed.get((str(search.get("caso_id")), str(search.get("caso_version"))))
        if plan is not None:
            found.append(
                _one_comparison(search, candidates, seed_rows, runs, by_id=by_id, observed=plan)
            )
    return found
