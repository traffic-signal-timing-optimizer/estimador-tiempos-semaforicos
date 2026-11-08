"""Las cuentas del panel (DEV31 F5): lo que se puede restar y lo que no se debe decir."""

from typing import Any

import pytest

from semaforo.app.panel_resumen import comparisons, group_stats, run_series

OBSERVED = "plan-actual"
OTHER = "plan-otro"
SCENARIO = "ESC"
CASE = {"caso_id": "C", "caso_version": "1"}
SEARCH = {"busqueda_id": "B", "escenario_id": SCENARIO, "protocolo_id": "P", **CASE}


def _run(  # noqa: PLR0913  (cada dato de la corrida se nombra)
    run_id: str,
    plan: str,
    seed: int,
    *,
    delay: float | None = 100.0,
    teleports: int = 0,
    collisions: int = 0,
    stage: str = "search",
    protocol: str | None = "P",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "plan_id": plan,
        "semilla_sumo": seed,
        "demora_media_s": delay,
        "cota_inf_demora_s": None,
        "cola_media_veh": 5.0,
        "teletransportes_total": teleports,
        "choques": collisions,
        "etapa": stage,
        "protocolo_metricas_id": protocol,
        "estado": "succeeded",
        "estado_demora": "complete" if delay is not None else "censored",
        "escenario_id": SCENARIO,
    }


def _candidate(
    name: str, plan: str, *, eligible: bool = True, finalist: bool = False
) -> dict[str, Any]:
    return {
        "busqueda_id": "B",
        "candidato_id": name,
        "plan_id": plan,
        "ciclo_s": 100.0,
        "origen": "current_plan" if plan == OBSERVED else "sampled",
        "elegible_busqueda": eligible,
        "posicion_busqueda": 1,
        "finalista": finalist,
        "problemas_busqueda": {},
        "elegible_finalistas": False,
        "posicion_finalistas": None,
        "problemas_finalistas": {},
    }


def _seed(  # noqa: PLR0913  (cada dato de la semilla se nombra)
    candidate: str,
    seed: int,
    run_id: str,
    *,
    delay: float | None = 100.0,
    problems: tuple[str, ...] = (),
    stage: str = "search",
) -> dict[str, Any]:
    return {
        "busqueda_id": "B",
        "candidato_id": candidate,
        "etapa": stage,
        "semilla": seed,
        "run_id": run_id,
        "demora_media_s": delay,
        "problemas": list(problems),
        "teletransportes": 0,
        "choques": 0,
    }


PLANS = [{"plan_id": OBSERVED, "es_plan_observado": True, **CASE}, {"plan_id": OTHER, **CASE}]


def _compare(
    runs: list[dict[str, Any]], seeds: list[dict[str, Any]], *candidates: dict[str, Any]
) -> dict[str, Any]:
    (found,) = comparisons([SEARCH], list(candidates), seeds, runs, PLANS)
    return found


def test_a_paired_difference_is_the_same_seed_in_both_plans() -> None:
    runs = [
        _run("a1", OBSERVED, 1, delay=100.0),
        _run("a2", OBSERVED, 2, delay=200.0),
        _run("b1", OTHER, 1, delay=90.0),
        _run("b2", OTHER, 2, delay=150.0),
    ]
    seeds = [_seed("A", 1, "a1"), _seed("A", 2, "a2"), _seed("B", 1, "b1"), _seed("B", 2, "b2")]
    result = _compare(runs, seeds, _candidate("A", OBSERVED), _candidate("B", OTHER))
    (plan,) = result["emparejada"]
    assert plan["pares_validos"] == 2
    assert plan["diferencia_valida"]["media"] == pytest.approx(-30.0)  # (-10 + -50) / 2
    assert plan["diferencia_valida_pct"] == pytest.approx(-20.0)  # -30 sobre 150
    assert result["semillas_busqueda"] == [1, 2]


def test_a_seed_with_an_incident_is_measured_but_is_not_a_valid_pair() -> None:
    runs = [
        _run("a1", OBSERVED, 1, delay=100.0),
        _run("a2", OBSERVED, 2, delay=300.0, teleports=9),
        _run("b1", OTHER, 1, delay=90.0),
        _run("b2", OTHER, 2, delay=50.0),
    ]
    seeds = [
        _seed("A", 1, "a1"),
        _seed("A", 2, "a2", delay=None, problems=("teleports",)),
        _seed("B", 1, "b1"),
        _seed("B", 2, "b2"),
    ]
    result = _compare(
        runs, seeds, _candidate("A", OBSERVED, eligible=False), _candidate("B", OTHER)
    )
    (plan,) = result["emparejada"]
    assert (plan["pares_validos"], plan["pares_medidos"]) == (1, 2)
    assert plan["diferencia_valida"]["media"] == pytest.approx(-10.0)  # no se apoya en el atasco
    assert plan["diferencia_medida"]["media"] == pytest.approx(-130.0)
    assert result["plan_observado_elegible"] is False


def test_without_a_valid_pair_there_is_no_difference_never_a_zero() -> None:
    runs = [_run("a1", OBSERVED, 1), _run("b1", OTHER, 1, delay=None)]
    seeds = [_seed("A", 1, "a1"), _seed("B", 1, "b1", delay=None, problems=("cohort_incomplete",))]
    (plan,) = _compare(runs, seeds, _candidate("A", OBSERVED), _candidate("B", OTHER))["emparejada"]
    assert plan["pares_validos"] == 0
    assert plan["diferencia_valida"]["media"] is None
    assert plan["diferencia_valida_pct"] is None


def test_finalists_on_other_seeds_are_declared_not_paired() -> None:
    runs = [
        _run("d1", OBSERVED, 100, stage="diagnostic", protocol="DEV19"),
        _run("f1", OTHER, 2001, delay=70.0, stage="finalists"),
    ]
    seeds = [_seed("B", 2001, "f1", stage="finalists", delay=70.0)]
    result = _compare(runs, seeds, _candidate("A", OBSERVED), _candidate("B", OTHER, finalist=True))
    assert result["semillas_finalistas"] == [2001]
    assert result["finalistas_con_mismas_semillas"] is False
    assert result["plan_observado_diagnostico"]["corridas"] == 1
    (finalist,) = result["finalistas"]
    assert finalist["grupo"]["demora"]["media"] == pytest.approx(70.0)


def test_finalists_on_the_same_seeds_are_declared_paired() -> None:
    runs = [
        _run("d1", OBSERVED, 2001, stage="diagnostic"),
        _run("f1", OTHER, 2001, stage="finalists"),
    ]
    seeds = [_seed("B", 2001, "f1", stage="finalists")]
    result = _compare(runs, seeds, _candidate("A", OBSERVED), _candidate("B", OTHER, finalist=True))
    assert result["finalistas_con_mismas_semillas"] is True


def test_a_replica_or_another_measuring_zone_of_a_seed_does_not_count_twice() -> None:
    group = group_stats(
        [
            _run("a", OBSERVED, 100, delay=100.0, protocol="zona-corta"),
            _run("b", OBSERVED, 100, delay=100.0, protocol="zona-larga"),
            _run("c", OBSERVED, 101, delay=200.0, teleports=3),
        ]
    )
    assert group["corridas"] == 2
    assert group["demora"]["media"] == pytest.approx(150.0)
    assert group["con_incidentes"] == 1
    assert group["demora_sin_incidentes"]["media"] == pytest.approx(100.0)
    assert group["demora_con_incidentes"]["media"] == pytest.approx(200.0)


def test_a_missing_delay_stays_out_of_the_mean_and_is_counted() -> None:
    group = group_stats([_run("a", OBSERVED, 1, delay=None), _run("b", OBSERVED, 2, delay=80.0)])
    assert group["sin_demora"] == 1
    assert group["demora"]["n"] == 1
    assert group["demora"]["media"] == pytest.approx(80.0)


def test_a_series_is_one_stage_and_one_measuring_protocol() -> None:
    series = run_series(
        [
            _run("a", OBSERVED, 1, stage="diagnostic", protocol="zona-corta"),
            _run("b", OBSERVED, 1, stage="diagnostic", protocol="zona-larga"),
            _run("c", OTHER, 2, stage="search", protocol="P", teleports=1),
            _run("d", OTHER, 3, stage="finalists", protocol="P", collisions=1),
        ]
    )
    assert [(s["etapa"], s["protocolo"]) for s in series] == [
        ("search", "P"),
        ("finalists", "P"),
        ("diagnostic", "zona-corta"),
        ("diagnostic", "zona-larga"),
    ]
    assert series[0]["con_teletransportes"] == 1
    assert series[1]["con_choques"] == 1


def test_without_an_observed_plan_there_is_nothing_to_compare_against() -> None:
    plans = [{"plan_id": OTHER, **CASE}]
    assert comparisons([SEARCH], [_candidate("B", OTHER)], [], [], plans) == []


def test_the_current_plan_on_the_finalist_seeds_is_not_mixed_with_the_diagnostics() -> None:
    runs = [
        _run("dx", OBSERVED, 100, stage="diagnostic", protocol="DEV19"),
        _run("fa", OBSERVED, 2001, stage="diagnostic", protocol="P", delay=100.0),
        _run("fb", OBSERVED, 2002, stage="diagnostic", protocol="P", teleports=5, delay=None),
        _run("ff", OTHER, 2001, stage="finalists", protocol="P", delay=70.0),
    ]
    seeds = [_seed("B", 2001, "ff", stage="finalists", delay=70.0)]
    result = _compare(runs, seeds, _candidate("A", OBSERVED), _candidate("B", OTHER, finalist=True))
    assert result["plan_observado_diagnostico"]["corridas"] == 1  # solo la de DEV19
    # Solo cuentan las semillas de finalistas de esta búsqueda (2001); la 2002 no es de ellas.
    with_finalists = result["plan_observado_finalistas"]
    assert with_finalists["corridas"] == 1
    assert with_finalists["con_incidentes"] == 0
    assert result["finalistas_con_mismas_semillas"] is True
    (finalist,) = result["finalistas"]
    pairs = finalist["pares_con_plan_actual"]
    assert pairs["pares_validos"] == 1
    assert pairs["diferencia_valida"]["media"] == pytest.approx(-30.0)  # 70 frente a 100


def test_a_pair_with_a_teleport_on_either_side_is_not_counted() -> None:
    runs = [
        _run("fa", OBSERVED, 2001, stage="diagnostic", protocol="P", delay=100.0),
        _run("ff", OTHER, 2001, stage="finalists", protocol="P", delay=70.0, teleports=1),
    ]
    seeds = [_seed("B", 2001, "ff", stage="finalists", delay=70.0)]
    result = _compare(runs, seeds, _candidate("A", OBSERVED), _candidate("B", OTHER, finalist=True))
    pairs = result["finalistas"][0]["pares_con_plan_actual"]
    assert pairs["pares_validos"] == 0
    assert pairs["diferencia_valida"]["media"] is None
