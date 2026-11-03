"""Elegibilidad, orden y elección de la referencia (DEV14 F2, HU08, QA16 y QA18 sin SUMO).

Datos sintéticos: métricas armadas a mano con las piezas de DEV19.
"""

import json
import math
from typing import Any

import pytest

from prepared_inputs import FIXTURES
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.protocol import ProtocolInvalidError, parse_protocol
from semaforo.evaluacion.cohort import CohortDelay, DelaySummary
from semaforo.evaluacion.metrics import QueueSummary, StopsSummary, ZoneMetrics
from semaforo.evaluacion.run_metrics import RunMetrics
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.selection import (
    SELECTION_RULE,
    CandidateScore,
    SeedOutcome,
    Stage,
    choose_finalists,
    failed_seed,
    rank,
    score_candidate,
    seed_outcome,
    select,
)


def metrics(  # noqa: PLR0913 - cada argumento cambia una cifra de la corrida
    seed: int = 101,
    *,
    delay: float = 100.0,
    status: str = "complete",
    teleports: int = 0,
    collisions: int = 0,
    queue: float | None = 5.0,
    queue_status: str = "complete",
    stops: float | None = 1.2,
    zone: bool = True,
) -> RunMetrics:
    total = DelaySummary.model_construct(
        status=status, mean_delay_s=delay if status == "complete" else None
    )
    cohort = CohortDelay.model_construct(total=total)
    zone_metrics = ZoneMetrics.model_construct(
        queue=QueueSummary.model_construct(status=queue_status, mean_vehicles=queue),
        stops=StopsSummary.model_construct(mean_stops=stops),
    )
    return RunMetrics.model_construct(
        run_id=f"run-{seed}",
        sumo_seed=seed,
        cohort=cohort,
        zone=zone_metrics if zone else None,
        teleports_total=teleports,
        collisions=collisions,
    )


def clean(seed: int, delay: float, queue: float = 5.0, stops: float = 1.0) -> SeedOutcome:
    return seed_outcome(seed, metrics(seed, delay=delay, queue=queue, stops=stops))


def scored(  # noqa: PLR0913 - cada argumento cambia una cifra del candidato
    name: str,
    delay: float,
    *,
    queue: float = 5.0,
    stops: float = 1.0,
    vector: tuple[int, ...] = (1, 1),
    stage: Stage = "search",
    eligible: bool = True,
) -> CandidateScore:
    seeds = [101, 102] if stage == "search" else [201, 202]
    if eligible:
        outcomes = [clean(seed, delay, queue, stops) for seed in seeds]
    else:
        outcomes = [seed_outcome(seed, metrics(seed, teleports=3)) for seed in seeds]
    return score_candidate(name, vector, stage, seeds, outcomes)


# Una semilla: qué cuenta y qué no


def test_a_clean_run_counts_with_its_figures() -> None:
    outcome = seed_outcome(101, metrics(delay=97.5, queue=12.0, stops=1.4))
    assert outcome.problems == ()
    assert (outcome.mean_delay_s, outcome.mean_queue_veh, outcome.mean_stops) == (97.5, 12.0, 1.4)
    assert outcome.run_id == "run-101"
    assert outcome.run_status == "succeeded"


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"status": "censored"}, "cohort_incomplete"),
        ({"status": "empty"}, "cohort_incomplete"),
        ({"teleports": 1}, "teleports"),
        ({"collisions": 1}, "collisions"),
        ({"zone": False}, "zone_incomplete"),
        ({"queue_status": "incomplete", "queue": None}, "zone_incomplete"),
        ({"queue": None}, "zone_incomplete"),
        ({"stops": None}, "zone_incomplete"),
    ],
)
def test_a_seed_with_a_problem_does_not_count_and_hides_its_figures(
    changes: dict[str, Any], problem: str
) -> None:
    outcome = seed_outcome(101, metrics(**changes))
    assert outcome.problems == (problem,)
    assert outcome.mean_delay_s is None
    assert outcome.mean_queue_veh is None
    assert outcome.mean_stops is None


def test_every_problem_of_a_seed_is_listed() -> None:
    outcome = seed_outcome(101, metrics(status="censored", teleports=8, collisions=1, zone=False))
    assert outcome.problems == ("cohort_incomplete", "teleports", "collisions", "zone_incomplete")
    assert (outcome.teleports, outcome.collisions) == (8, 1)


def test_a_run_of_another_seed_is_rejected() -> None:
    with pytest.raises(ReferenciasError) as caught:
        seed_outcome(102, metrics(101))
    assert caught.value.code == ErrorCode.OUTPUT_INVALID


def test_a_failed_seed_keeps_a_short_reason() -> None:
    outcome = failed_seed(101, "run-x", "failed", "run_failed", "x" * 5000)
    assert outcome.problems == ("run_failed",)
    assert outcome.message is not None
    assert len(outcome.message) == 300
    assert outcome.mean_delay_s is None


# Un candidato en una etapa


def test_an_eligible_candidate_scores_the_mean_of_its_seeds() -> None:
    score = score_candidate(
        "a", (1, 2), "search", [101, 102], [clean(102, 110.0, 6.0, 2.0), clean(101, 90.0, 4.0, 1.0)]
    )
    assert score.eligible
    assert score.score_s == 100.0
    assert score.mean_queue_veh == 5.0
    assert score.mean_stops == 1.5
    assert [o.seed for o in score.outcomes] == [101, 102]
    assert score.problems == {}


def test_the_mean_is_exact_with_many_seeds() -> None:
    seeds = list(range(13))
    score = score_candidate("a", (1,), "finalists", seeds, [clean(s, 0.1) for s in seeds])
    assert score.score_s == pytest.approx(0.1, abs=1e-15)
    assert score.score_s == math.fsum([0.1] * 13) / 13


def test_one_bad_seed_makes_the_candidate_ineligible() -> None:
    bad = seed_outcome(102, metrics(102, teleports=9))
    score = score_candidate("a", (1,), "search", [101, 102], [clean(101, 50.0), bad])
    assert not score.eligible
    assert score.score_s is None
    assert score.mean_queue_veh is None
    assert score.mean_stops is None
    assert score.problems == {"teleports": 1}


def test_a_missing_seed_makes_the_candidate_ineligible() -> None:
    score = score_candidate("a", (1,), "search", [101, 102], [clean(101, 50.0)])
    assert not score.eligible
    assert score.missing_seeds == (102,)
    assert score.problems == {"missing_seed": 1}


def test_a_stage_without_seeds_is_never_eligible() -> None:
    assert not score_candidate("a", (1,), "search", [], []).eligible


@pytest.mark.parametrize("seeds", [[101, 101], [101, 999]])
def test_a_repeated_or_foreign_seed_is_rejected(seeds: list[int]) -> None:
    with pytest.raises(ReferenciasError) as caught:
        score_candidate("a", (1,), "search", [101, 102], [clean(s, 1.0) for s in seeds])
    assert caught.value.code == ErrorCode.OUTPUT_INVALID


# Orden con empates dentro de epsilon


def ids(scores: tuple[CandidateScore, ...]) -> list[str]:
    return [score.candidate_id for score in scores]


def test_candidates_are_ordered_by_their_score() -> None:
    order = rank([scored("c", 130.0), scored("a", 100.0), scored("b", 110.0)], 2.0)
    assert ids(order) == ["a", "b", "c"]


def test_ineligible_candidates_are_left_out_of_the_order() -> None:
    order = rank([scored("a", 100.0), scored("b", 1.0, eligible=False)], 2.0)
    assert ids(order) == ["a"]


def test_within_epsilon_less_queue_goes_first() -> None:
    order = rank([scored("a", 100.0, queue=9.0), scored("b", 101.5, queue=4.0)], 2.0)
    assert ids(order) == ["b", "a"]


def test_the_epsilon_limit_is_inclusive() -> None:
    order = rank([scored("a", 100.0, queue=9.0), scored("b", 102.0, queue=4.0)], 2.0)
    assert ids(order) == ["b", "a"]
    order = rank([scored("a", 100.0, queue=9.0), scored("b", 102.5, queue=4.0)], 2.0)
    assert ids(order) == ["a", "b"]


def test_with_equal_queue_fewer_stops_go_first() -> None:
    order = rank([scored("a", 100.0, stops=2.0), scored("b", 100.5, stops=1.0)], 2.0)
    assert ids(order) == ["b", "a"]


def test_with_equal_queue_and_stops_the_smaller_vector_goes_first() -> None:
    order = rank([scored("a", 100.0, vector=(5, 2)), scored("b", 101.0, vector=(5, 1))], 2.0)
    assert ids(order) == ["b", "a"]


def test_without_epsilon_only_an_exact_tie_uses_the_queue() -> None:
    order = rank([scored("a", 100.0, queue=9.0), scored("b", 100.0001, queue=1.0)], 0.0)
    assert ids(order) == ["a", "b"]
    order = rank([scored("a", 100.0, queue=9.0), scored("b", 100.0, queue=1.0)], 0.0)
    assert ids(order) == ["b", "a"]


def test_the_tie_window_moves_with_the_best_that_remains() -> None:
    # a (100) y b (101.5) empatan; c (103) solo empata con b, cuando a ya salió.
    scores = [
        scored("a", 100.0, queue=1.0),
        scored("b", 101.5, queue=5.0),
        scored("c", 103.0, queue=2.0),
    ]
    assert ids(rank(scores, 2.0)) == ["a", "c", "b"]


def test_the_order_does_not_depend_on_the_input_order() -> None:
    scores = [scored(name, 100.0 + i * 0.7, queue=10.0 - i) for i, name in enumerate("abcdef")]
    assert ids(rank(scores, 2.0)) == ids(rank(list(reversed(scores)), 2.0))


@pytest.mark.parametrize("epsilon", [-0.1, math.nan, math.inf, True, "2"])
def test_an_invalid_epsilon_is_rejected(epsilon: Any) -> None:  # noqa: ANN401
    with pytest.raises(ReferenciasError) as caught:
        rank([scored("a", 1.0)], epsilon)
    assert caught.value.field == "tie_epsilon_s"


def test_a_candidate_twice_is_rejected() -> None:
    with pytest.raises(ReferenciasError):
        rank([scored("a", 1.0), scored("a", 2.0)], 2.0)


# Finalistas y referencia


def test_the_finalists_are_the_first_of_the_search_order() -> None:
    scores = [scored("a", 120.0), scored("b", 100.0), scored("c", 110.0)]
    assert ids(choose_finalists(scores, 2, 2.0)) == ["b", "c"]
    assert ids(choose_finalists(scores, 10, 2.0)) == ["b", "c", "a"]


@pytest.mark.parametrize("count", [0, -1, True, 2.0])
def test_an_invalid_finalist_count_is_rejected(count: Any) -> None:  # noqa: ANN401
    with pytest.raises(ReferenciasError) as caught:
        choose_finalists([scored("a", 1.0)], count, 2.0)
    assert caught.value.field == "finalist_count"


def test_the_reference_is_the_best_finalist_with_the_finalist_seeds_only() -> None:
    search = [scored("a", 100.0, vector=(1,)), scored("b", 105.0, vector=(2,)), scored("c", 140.0)]
    finalists = [
        scored("a", 120.0, vector=(1,), stage="finalists"),
        scored("b", 104.0, vector=(2,), stage="finalists"),
    ]
    result = select(search, finalists, 2, 2.0)
    assert result.status == "reference"
    assert result.reason is None
    assert result.winner is not None
    assert result.winner.candidate_id == "b"
    assert result.winner.score_s == 104.0
    assert result.finalists == ("a", "b")
    assert ids(result.finalist_ranking) == ["b", "a"]
    assert ids(result.search_ranking) == ["a", "b", "c"]


def test_without_candidates_there_is_no_reference() -> None:
    result = select([], [], 2, 2.0)
    assert (result.status, result.reason, result.winner) == ("no_reference", "no_candidates", None)


def test_without_eligible_candidates_there_is_no_reference() -> None:
    search = [scored("a", 1.0, eligible=False), scored("b", 2.0, eligible=False)]
    result = select(search, [], 2, 2.0)
    assert result.status == "no_reference"
    assert result.reason == "no_eligible_candidate"
    assert result.finalists == ()
    assert result.ineligible_search == {"teleports": 2}


def test_if_every_finalist_fails_on_reevaluation_there_is_no_reference() -> None:
    search = [scored("a", 100.0)]
    finalists = [scored("a", 100.0, stage="finalists", eligible=False)]
    result = select(search, finalists, 2, 2.0)
    assert result.status == "no_reference"
    assert result.reason == "no_eligible_finalist"
    assert result.winner is None
    assert result.ineligible_finalists == {"teleports": 1}


def test_reevaluated_candidates_must_be_exactly_the_finalists() -> None:
    search = [scored("a", 100.0), scored("b", 110.0), scored("c", 120.0)]
    with pytest.raises(ReferenciasError):
        select(search, [scored("c", 1.0, stage="finalists")], 1, 2.0)
    with pytest.raises(ReferenciasError):
        select(search, [scored("a", 1.0, stage="finalists")], 2, 2.0)


def test_a_finalist_with_another_plan_is_rejected() -> None:
    search = [scored("a", 100.0, vector=(1,))]
    with pytest.raises(ReferenciasError):
        select(search, [scored("a", 100.0, vector=(2,), stage="finalists")], 1, 2.0)


def test_figures_of_the_wrong_stage_are_rejected() -> None:
    finalist = scored("a", 100.0, stage="finalists")
    with pytest.raises(ReferenciasError) as caught:
        select([finalist], [finalist], 1, 2.0)
    assert caught.value.field == "stage"
    with pytest.raises(ReferenciasError) as caught:
        select([scored("a", 100.0)], [scored("a", 100.0)], 1, 2.0)
    assert caught.value.field == "stage"


def test_a_censored_cohort_does_not_count_even_with_a_mean() -> None:
    outcome = seed_outcome(101, metrics(status="censored"))
    data = metrics()
    censored = data.model_copy(
        update={
            "cohort": CohortDelay.model_construct(
                total=DelaySummary.model_construct(status="censored", mean_delay_s=100.0)
            )
        }
    )
    assert outcome.problems == ("cohort_incomplete",)
    assert seed_outcome(101, censored).problems == ("cohort_incomplete",)


def test_an_incomplete_queue_does_not_count_even_with_a_mean() -> None:
    outcome = seed_outcome(101, metrics(queue_status="incomplete", queue=5.0))
    assert outcome.problems == ("zone_incomplete",)


def test_the_mean_of_the_seeds_is_summed_exactly() -> None:
    values = [0.1, 0.2, 0.3]
    seeds = [101, 102, 103]
    outcomes = [clean(s, v) for s, v in zip(seeds, values, strict=True)]
    score = score_candidate("a", (1,), "search", seeds, outcomes)
    assert score.score_s == math.fsum(values) / 3


def test_a_stage_with_one_seed_scores_that_seed() -> None:
    score = score_candidate("a", (1,), "search", [101], [clean(101, 87.5, 3.0, 2.0)])
    assert (score.score_s, score.mean_queue_veh, score.mean_stops) == (87.5, 3.0, 2.0)


def test_the_queue_breaks_the_tie_before_the_stops() -> None:
    order = rank(
        [scored("a", 100.0, queue=9.0, stops=1.0), scored("b", 101.0, queue=4.0, stops=3.0)], 2.0
    )
    assert ids(order) == ["b", "a"]


def test_the_selection_is_written_with_its_rule() -> None:
    search = [scored("a", 100.0), scored("b", 1.0, eligible=False)]
    finalists = [scored("a", 99.0, stage="finalists")]
    data = select(search, finalists, 1, 2.0).to_json()
    assert json.loads(json.dumps(data)) == data
    assert data["rule"] == SELECTION_RULE
    assert data["winner"] == "a"
    assert data["ineligible_search"] == {"teleports": 1}


def test_a_score_is_written_with_every_seed() -> None:
    data = scored("a", 100.0).to_json()
    assert json.loads(json.dumps(data)) == data
    assert [seed["seed"] for seed in data["seeds"]] == [101, 102]  # type: ignore[index, union-attr]


# QA18: semillas de búsqueda, finalistas y final disjuntas


def test_qa18_a_seed_shared_between_sets_is_rejected_by_the_protocol() -> None:
    data = json.loads((FIXTURES / "protocol.json").read_text(encoding="utf-8"))
    data["seeds"]["finalists"] = [101, 202]
    with pytest.raises(ProtocolInvalidError):
        parse_protocol(data)


def test_qa18_a_finalist_scored_with_search_seeds_does_not_count() -> None:
    search_outcomes = [clean(101, 90.0), clean(102, 90.0)]
    with pytest.raises(ReferenciasError):
        score_candidate("a", (1,), "finalists", [201, 202], search_outcomes)
