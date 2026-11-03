"""Elegibilidad, orden y elección de la referencia (DEV14 F2, HU08, QA16 y QA18).

Diseño técnico, «Búsqueda propuesta reproducible»: puntuar con la métrica principal y la política
de viajes incompletos del protocolo; ordenar por puntuación y desempatar dentro de epsilon usando
cola, detenciones y por último el vector lexicográfico; reevaluar a los finalistas con semillas
reservadas de desarrollo. Reglas de este módulo (acta de DEV14 F0, decisión F0-6):

- **Una semilla** de un candidato queda descartada si la corrida no terminó bien, si la cohorte no
  quedó completa (``complete_cohort_or_no_label``), si hubo teletransportes o choques (SUMO esconde
  parte de la demora de los vehículos que saca) o si la cola o las detenciones de la zona no se
  pudieron medir completas.
- **Un candidato es elegible** solo si todas sus semillas de la etapa están y ninguna quedó
  descartada. Su puntuación es la media, con igual peso por semilla, de la demora media de la
  cohorte (s/veh); la cola (veh) y las detenciones (por vehículo), también medias por semilla,
  sirven para desempatar.
- **Orden:** entre los elegibles que quedan, los que están a ``epsilon`` o menos de la mejor
  puntuación empatan; de ellos va primero el de menos cola, después el de menos detenciones y por
  último el vector de ticks menor. Se repite con los que quedan.
- **Finalistas:** los ``finalist_count`` primeros del orden de la búsqueda. Se reevalúan con las
  semillas de finalistas, y la referencia es el primero del orden **solo con esas semillas**: las
  de la búsqueda no se mezclan.
- **Sin referencia** (``no_reference``) si no hay candidatos, si ninguno es elegible en la
  búsqueda o si ningún finalista es elegible al reevaluarlo. Siempre con el motivo.

Es puro: no lee archivos ni lanza procesos (ADR01).
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from semaforo.dominio.errors import ErrorCode
from semaforo.evaluacion.run_metrics import RunMetrics
from semaforo.referencias.errors import ReferenciasError

__all__ = [
    "SELECTION_RULE",
    "CandidateScore",
    "NoReferenceReason",
    "SeedOutcome",
    "SeedProblem",
    "Selection",
    "Stage",
    "choose_finalists",
    "failed_seed",
    "rank",
    "score_candidate",
    "seed_outcome",
    "select",
]

Stage = Literal["search", "finalists"]
SeedProblem = Literal[
    "run_failed",
    "evaluation_failed",
    "cohort_incomplete",
    "teleports",
    "collisions",
    "zone_incomplete",
]
NoReferenceReason = Literal["no_candidates", "no_eligible_candidate", "no_eligible_finalist"]
# Versión y texto de la regla de selección: van en la traza y en la etiqueta.
SELECTION_RULE = (
    "selection-1.0.0: elegible = todas las semillas de la etapa con corrida exitosa, cohorte "
    "completa, sin teletransportes ni choques y zona completa; puntuación = media por semilla de "
    "la demora media de la cohorte (timeLoss + departDelay, s/veh); empate dentro de epsilon: "
    "menos cola media, menos detenciones por vehículo, vector de ticks menor; referencia = primer "
    "finalista elegible con las semillas de finalistas"
)


@dataclass(frozen=True)
class SeedOutcome:
    """Lo que dio un candidato con una semilla: sus cifras o por qué no cuenta.

    ``mean_delay_s``, ``mean_queue_veh`` y ``mean_stops`` solo se llenan si la semilla no tiene
    problemas; ``problems`` dice todos los motivos por los que no cuenta.
    """

    seed: int
    run_id: str | None
    run_status: str
    mean_delay_s: float | None
    mean_queue_veh: float | None
    mean_stops: float | None
    teleports: int
    collisions: int
    problems: tuple[SeedProblem, ...]
    message: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "run_id": self.run_id,
            "run_status": self.run_status,
            "mean_delay_s": self.mean_delay_s,
            "mean_queue_veh": self.mean_queue_veh,
            "mean_stops": self.mean_stops,
            "teleports": self.teleports,
            "collisions": self.collisions,
            "problems": list(self.problems),
            "message": self.message,
        }


def seed_outcome(seed: int, metrics: RunMetrics) -> SeedOutcome:
    """Cifras de una corrida exitosa ya evaluada, con los motivos por los que no cuenta."""
    if metrics.sumo_seed != seed:
        raise ReferenciasError(
            ErrorCode.OUTPUT_INVALID,
            f"la corrida {metrics.run_id} es de la semilla {metrics.sumo_seed}, no de {seed}",
            "seed",
        )
    problems: list[SeedProblem] = []
    total = metrics.cohort.total
    if total.status != "complete" or total.mean_delay_s is None:
        problems.append("cohort_incomplete")
    if metrics.teleports_total > 0:
        problems.append("teleports")
    if metrics.collisions > 0:
        problems.append("collisions")
    zone = metrics.zone
    queue = None if zone is None else zone.queue
    stops = None if zone is None else zone.stops
    if (
        queue is None
        or stops is None
        or queue.status != "complete"
        or queue.mean_vehicles is None
        or stops.mean_stops is None
    ):
        problems.append("zone_incomplete")
    clean = not problems
    return SeedOutcome(
        seed=seed,
        run_id=metrics.run_id,
        run_status="succeeded",
        mean_delay_s=total.mean_delay_s if clean else None,
        mean_queue_veh=None if not clean or queue is None else queue.mean_vehicles,
        mean_stops=None if not clean or stops is None else stops.mean_stops,
        teleports=metrics.teleports_total,
        collisions=metrics.collisions,
        problems=tuple(problems),
    )


def failed_seed(
    seed: int, run_id: str | None, run_status: str, problem: SeedProblem, message: str
) -> SeedOutcome:
    """Una semilla cuya corrida falló o no se pudo evaluar."""
    return SeedOutcome(
        seed=seed,
        run_id=run_id,
        run_status=run_status,
        mean_delay_s=None,
        mean_queue_veh=None,
        mean_stops=None,
        teleports=0,
        collisions=0,
        problems=(problem,),
        message=message[:300],
    )


@dataclass(frozen=True)
class CandidateScore:
    """Un candidato en una etapa: sus semillas, si es elegible y sus cifras medias."""

    candidate_id: str
    vector: tuple[int, ...]
    stage: Stage
    outcomes: tuple[SeedOutcome, ...]
    missing_seeds: tuple[int, ...]
    eligible: bool
    score_s: float | None
    mean_queue_veh: float | None
    mean_stops: float | None

    @property
    def problems(self) -> dict[str, int]:
        """Cuántas semillas tienen cada problema (``missing_seed`` para las que faltan)."""
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            for problem in outcome.problems:
                counts[problem] = counts.get(problem, 0) + 1
        if self.missing_seeds:
            counts["missing_seed"] = len(self.missing_seeds)
        return counts

    def to_json(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "stage": self.stage,
            "eligible": self.eligible,
            "score_s": self.score_s,
            "mean_queue_veh": self.mean_queue_veh,
            "mean_stops": self.mean_stops,
            "missing_seeds": list(self.missing_seeds),
            "problems": self.problems,
            "seeds": [outcome.to_json() for outcome in self.outcomes],
        }


def _mean(values: Iterable[float | None]) -> float:
    numbers = [value for value in values if value is not None]
    return math.fsum(numbers) / len(numbers)


def score_candidate(
    candidate_id: str,
    vector: Sequence[int],
    stage: Stage,
    seeds: Sequence[int],
    outcomes: Iterable[SeedOutcome],
) -> CandidateScore:
    """Elegibilidad y cifras de un candidato con las semillas ``seeds`` de su etapa.

    Raises:
        ReferenciasError: OUTPUT_INVALID si llega una semilla repetida o que no es de la etapa.
    """
    by_seed: dict[int, SeedOutcome] = {}
    for outcome in outcomes:
        if outcome.seed not in seeds or outcome.seed in by_seed:
            raise ReferenciasError(
                ErrorCode.OUTPUT_INVALID,
                f"la semilla {outcome.seed} del candidato {candidate_id} está repetida o no es "
                f"de la etapa {stage}",
                "seed",
            )
        by_seed[outcome.seed] = outcome
    ordered = tuple(by_seed[seed] for seed in seeds if seed in by_seed)
    missing = tuple(seed for seed in seeds if seed not in by_seed)
    eligible = bool(seeds) and not missing and all(not o.problems for o in ordered)
    return CandidateScore(
        candidate_id=candidate_id,
        vector=tuple(vector),
        stage=stage,
        outcomes=ordered,
        missing_seeds=missing,
        eligible=eligible,
        score_s=_mean(o.mean_delay_s for o in ordered) if eligible else None,
        mean_queue_veh=_mean(o.mean_queue_veh for o in ordered) if eligible else None,
        mean_stops=_mean(o.mean_stops for o in ordered) if eligible else None,
    )


def _epsilon(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value >= 0:
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA, "epsilon debe ser un número no negativo", "tie_epsilon_s"
        )
    if math.isinf(value):
        raise ReferenciasError(ErrorCode.INPUT_SCHEMA, "epsilon debe ser finito", "tie_epsilon_s")
    return float(value)


def _figures(score: CandidateScore) -> tuple[float, float, float]:
    """Puntuación, cola y detenciones de un elegible (siempre están: lo garantiza la etapa)."""
    if score.score_s is None or score.mean_queue_veh is None or score.mean_stops is None:
        raise ReferenciasError(
            ErrorCode.OUTPUT_INVALID, f"el candidato {score.candidate_id} no tiene cifras", "score"
        )
    return score.score_s, score.mean_queue_veh, score.mean_stops


def rank(scores: Iterable[CandidateScore], epsilon_s: float) -> tuple[CandidateScore, ...]:
    """Los elegibles en orden: mejor puntuación, con empates dentro de epsilon desempatados.

    Raises:
        ReferenciasError: si epsilon no es un número finito no negativo o si un candidato aparece
            dos veces.
    """
    epsilon = _epsilon(epsilon_s)
    remaining = [score for score in scores if score.eligible]
    ids = [score.candidate_id for score in remaining]
    if len(set(ids)) != len(ids):
        raise ReferenciasError(ErrorCode.OUTPUT_INVALID, "un candidato aparece dos veces", "scores")
    ordered: list[CandidateScore] = []
    while remaining:
        best = min(_figures(score)[0] for score in remaining)
        tied = [score for score in remaining if _figures(score)[0] <= best + epsilon]
        chosen = min(tied, key=lambda s: (_figures(s)[1], _figures(s)[2], s.vector))
        ordered.append(chosen)
        remaining.remove(chosen)
    return tuple(ordered)


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA,
            "finalist_count debe ser un entero mayor que cero",
            "finalist_count",
        )
    return value


def choose_finalists(
    scores: Iterable[CandidateScore], finalist_count: int, epsilon_s: float
) -> tuple[CandidateScore, ...]:
    """Los ``finalist_count`` primeros del orden de la búsqueda."""
    return rank(scores, epsilon_s)[: _count(finalist_count)]


@dataclass(frozen=True)
class Selection:
    """La referencia elegida o por qué no hay, con el orden de cada etapa."""

    status: Literal["reference", "no_reference"]
    winner: CandidateScore | None
    reason: NoReferenceReason | None
    search_ranking: tuple[CandidateScore, ...]
    finalists: tuple[str, ...]
    finalist_ranking: tuple[CandidateScore, ...]
    ineligible_search: Mapping[str, int]
    ineligible_finalists: Mapping[str, int]

    def to_json(self) -> dict[str, object]:
        return {
            "rule": SELECTION_RULE,
            "status": self.status,
            "winner": None if self.winner is None else self.winner.candidate_id,
            "reason": self.reason,
            "search_ranking": [score.candidate_id for score in self.search_ranking],
            "finalists": list(self.finalists),
            "finalist_ranking": [score.candidate_id for score in self.finalist_ranking],
            "ineligible_search": dict(self.ineligible_search),
            "ineligible_finalists": dict(self.ineligible_finalists),
        }


def _ineligible(scores: Iterable[CandidateScore]) -> dict[str, int]:
    """Cuántos candidatos tienen cada problema (un candidato cuenta una vez por problema). Un
    elegible no tiene ninguno, así que solo cuentan los no elegibles.
    """
    counts: dict[str, int] = {}
    for score in scores:
        for problem in score.problems:
            counts[problem] = counts.get(problem, 0) + 1
    return dict(sorted(counts.items()))


def select(
    search_scores: Sequence[CandidateScore],
    finalist_scores: Sequence[CandidateScore],
    finalist_count: int,
    epsilon_s: float,
) -> Selection:
    """Elige la referencia: los finalistas salen de la búsqueda y gana el mejor reevaluado.

    Raises:
        ReferenciasError: OUTPUT_INVALID si los reevaluados no son exactamente los finalistas, o
            si alguna cifra llega de la etapa equivocada.
    """
    if any(score.stage != "search" for score in search_scores) or any(
        score.stage != "finalists" for score in finalist_scores
    ):
        raise ReferenciasError(ErrorCode.OUTPUT_INVALID, "cifras de otra etapa", "stage")
    search_ranking = rank(search_scores, epsilon_s)
    finalists = choose_finalists(search_scores, finalist_count, epsilon_s)
    finalist_ids = tuple(score.candidate_id for score in finalists)
    if sorted(score.candidate_id for score in finalist_scores) != sorted(finalist_ids):
        raise ReferenciasError(
            ErrorCode.OUTPUT_INVALID,
            "los candidatos reevaluados no son los finalistas de la búsqueda",
            "finalists",
        )
    by_id = {score.candidate_id: score.vector for score in finalists}
    if any(by_id[score.candidate_id] != score.vector for score in finalist_scores):
        raise ReferenciasError(
            ErrorCode.OUTPUT_INVALID, "un finalista cambió de plan al reevaluarlo", "finalists"
        )
    finalist_ranking = rank(finalist_scores, epsilon_s)
    reason: NoReferenceReason | None = None
    if not search_scores:
        reason = "no_candidates"
    elif not search_ranking:
        reason = "no_eligible_candidate"
    elif not finalist_ranking:
        reason = "no_eligible_finalist"
    return Selection(
        status="no_reference" if reason else "reference",
        winner=finalist_ranking[0] if finalist_ranking else None,
        reason=reason,
        search_ranking=search_ranking,
        finalists=finalist_ids,
        finalist_ranking=finalist_ranking,
        ineligible_search=_ineligible(search_scores),
        ineligible_finalists=_ineligible(finalist_scores),
    )
