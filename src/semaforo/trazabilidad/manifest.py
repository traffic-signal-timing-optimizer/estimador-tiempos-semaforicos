"""DTO del contrato run_manifest v1.0 (``schemas/run_manifest.schema.json``).

Reproduce campo a campo el modelo de referencia de la documentación (``tools/contracts``), de modo
que su esquema JSON es idéntico al publicado. Añade comprobaciones que no cambian el esquema:
``run_id`` sirve como nombre de carpeta, ``created_at`` lleva zona horaria, las rutas de los
artefactos son relativas a la carpeta de la ejecución y ningún artefacto se repite.
"""

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from semaforo.trazabilidad.paths import check_relative_path

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
Kind = Literal["simulation", "search", "training", "query", "evaluation", "export"]
Status = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TerminalStatus = Literal["succeeded", "failed", "cancelled"]
_CONFIG = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


def check_run_id(value: str) -> str:
    """Devuelve ``value`` si sirve como nombre de carpeta; ValueError si no."""
    if not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(f"run_id no válido como nombre de carpeta: {value!r}")
    return value


# Las clases del contrato se documentan con comentarios y no con docstrings: pydantic convierte
# las docstrings en «description» y el esquema dejaría de ser idéntico al publicado.


# Un archivo de la ejecución, con su ruta relativa a la carpeta de la ejecución.
class Artifact(BaseModel):
    model_config = _CONFIG

    artifact_id: str
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("path")
    @classmethod
    def _relative(cls, value: str) -> str:
        return check_relative_path(value)


# Error de una ejecución: código estable, campo afectado y mensaje sin trazas del sistema.
class Error(BaseModel):
    model_config = _CONFIG

    code: str
    field: str | None
    message: str
    artifact_id: str | None = None


# Manifiesto de una ejecución: qué se ejecutó, con qué entradas y qué produjo.
class RunManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        title="Contrato run_manifest v1.0",
        json_schema_extra={"$schema": SCHEMA_DIALECT},
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    kind: Kind
    status: Status
    created_at: datetime
    case_id: str
    case_version: str
    scenario_id: str | None
    seed: int | None = Field(default=None, ge=0)
    protocol_id: str | None
    command: list[str]
    environment: dict[str, str]
    inputs: list[Artifact]
    outputs: list[Artifact]
    exit_code: int | None
    error: Error | None
    retry_of: str | None

    @field_validator("run_id")
    @classmethod
    def _folder_name(cls, value: str) -> str:
        return check_run_id(value)

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at debe llevar zona horaria")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        # Reglas del modelo de referencia.
        if self.status == "succeeded" and (self.exit_code != 0 or not self.outputs):
            raise ValueError("success requires outputs and exit zero")
        if self.status == "failed" and self.error is None:
            raise ValueError("failure requires error")
        # Reglas añadidas: no cambian el esquema.
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("una ejecución succeeded no puede llevar error")
        artifacts = [*self.inputs, *self.outputs]
        if len({a.artifact_id for a in artifacts}) != len(artifacts):
            raise ValueError("hay artifact_id repetidos")
        if len({a.path for a in artifacts}) != len(artifacts):
            raise ValueError("hay rutas de artefacto repetidas")
        return self
