"""DTO del contrato protocol v1.0 (``schemas/protocol.schema.json``; DEV19 F2, decisión D5).

Reproduce campo a campo el modelo de referencia de la documentación (``tools/contracts``), de modo
que su esquema JSON es idéntico al publicado: el contrato no cambia y siguen siendo nueve. Lo que
la evaluación de DEV19 usa de él: la población (``cohort_policy``), la censura
(``censoring_policy``), la zona (``zone_lane_ids``), los umbrales de cola y de detención, el
muestreo de la cola y la tolerancia numérica. El resto (búsqueda, semillas, intervalos) lo usan
DEV14 y DEV20.

Congelar el protocolo (``status = "frozen"``) es una decisión del investigador (DEC06) y de DEV24;
un protocolo ``draft`` sirve para el desarrollo sintético.

Añade, sin cambiar el esquema, que los carriles de la zona no se repitan.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from semaforo.dominio.case import issues_of
from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "Artifact",
    "CalibrationCriterion",
    "Protocol",
    "ProtocolInvalidError",
    "Seeds",
    "parse_protocol",
]

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_CONFIG = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


# Las clases del contrato se documentan con comentarios y no con docstrings: pydantic convierte
# las docstrings en «description» y el esquema dejaría de ser idéntico al publicado.


# Un artefacto referido por el protocolo (por ejemplo, los pesos por grupo).
class Artifact(BaseModel):
    model_config = _CONFIG

    artifact_id: str
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


# Semillas de la búsqueda, de los finalistas y de la evaluación final: no se repiten entre sí.
class Seeds(BaseModel):
    model_config = _CONFIG

    search: list[int] = Field(min_length=1)
    finalists: list[int] = Field(min_length=1)
    final: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _disjoint(self) -> Self:
        seeds = [*self.search, *self.finalists, *self.final]
        if len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
            raise ValueError("las semillas no pueden repetirse ni ser negativas")
        return self


# Un criterio de calibración de SUMO (DEV23).
class CalibrationCriterion(BaseModel):
    model_config = _CONFIG

    variable: Literal["volume", "queue", "travel_time"]
    metric: str
    unit: str
    scope: str
    maximum_error: float = Field(ge=0)
    pilot_evidence: str


# Protocolo de medición, búsqueda y evaluación de un experimento.
class Protocol(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        title="Contrato protocol v1.0",
        json_schema_extra={"$schema": SCHEMA_DIALECT},
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    protocol_id: str
    status: Literal["draft", "frozen"]
    purpose: Literal["synthetic_fixture", "main_experiment"]
    metric_definition: str
    cohort_policy: str
    censoring_policy: Literal["complete_cohort_or_no_label", "approved_alternative"]
    alternate_censoring_rule: str | None
    search_budget: int = Field(gt=0)
    sampling_attempt_limit: int = Field(gt=0)
    finalist_count: int = Field(gt=0)
    seeds: Seeds
    tie_epsilon_s: float = Field(ge=0)
    queue_speed_threshold_mps: float = Field(ge=0)
    confidence_level: float = Field(gt=0, lt=1)
    bootstrap_repetitions: int = Field(gt=0)
    acceptance_margin_s: float | None = Field(default=None, ge=0)
    count_error_tolerance: float | None = Field(default=None, ge=0)
    simulation_fit_tolerance: float | None = Field(default=None, ge=0)
    approval_reference: str | None
    zone_lane_ids: list[str] = Field(min_length=1)
    queue_sampling_s: float = Field(gt=0)
    stop_speed_threshold_mps: float = Field(ge=0)
    calibration_criteria: list[CalibrationCriterion]
    group_aggregation: Literal["equal_group_weight", "declared_field_weights"]
    group_weight_artifact: Artifact | None
    refit_policy: Literal["train_only", "train_plus_validation_after_selection"]
    numeric_abs_tolerance: float = Field(ge=0)

    @model_validator(mode="after")
    def _gate(self) -> Self:
        # Reglas del modelo de referencia.
        if self.censoring_policy == "approved_alternative" and not self.alternate_censoring_rule:
            raise ValueError("una censura alternativa exige su regla")
        main = self.status == "frozen" and self.purpose == "main_experiment"
        pending = (self.acceptance_margin_s, self.count_error_tolerance)
        if main and (
            not self.approval_reference
            or any(value is None for value in (*pending, self.simulation_fit_tolerance))
        ):
            raise ValueError("un protocolo principal no se congela con criterios sin resolver")
        if main:
            variables = {criterion.variable for criterion in self.calibration_criteria}
            if "volume" not in variables or not variables & {"queue", "travel_time"}:
                raise ValueError("la calibración exige volumen y un criterio de desempeño")
        if (
            self.group_aggregation == "declared_field_weights"
            and self.group_weight_artifact is None
        ):
            raise ValueError("los pesos declarados exigen su artefacto")
        # Regla añadida: no cambia el esquema.
        if len(set(self.zone_lane_ids)) != len(self.zone_lane_ids):
            raise ValueError("los carriles de la zona no pueden repetirse")
        return self


class ProtocolInvalidError(DomainError):
    """El protocolo no cumple el contrato. Código INPUT_SCHEMA; lleva todos los problemas."""

    def __init__(self, error: ValidationError) -> None:
        issues = issues_of(error)
        first = issues[0]
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        where = "" if first.field is None else f" en {first.field}"
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"el protocolo no es válido{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


def parse_protocol(data: object) -> Protocol:
    """Valida ``data`` (el JSON ya leído) contra el contrato y devuelve el protocolo.

    Raises:
        ProtocolInvalidError: si no cumple el contrato, con todos los problemas.
    """
    try:
        return Protocol.model_validate(data)
    except ValidationError as error:
        raise ProtocolInvalidError(error) from None
