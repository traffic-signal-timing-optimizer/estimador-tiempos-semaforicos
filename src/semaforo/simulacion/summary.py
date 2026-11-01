"""Resumen de una corrida de SUMO: estado final de los vehículos, incidencias y demanda atendida.

Se guarda como ``outputs/summary.json`` solo en corridas exitosas: una corrida fallida no publica
métricas (QA08). Los hallazgos no invalidan la corrida; avisan de que sus resultados mezclan el
efecto del semáforo con otros (por ejemplo, demanda que nunca entró a la red).
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from semaforo.dominio.base_model import FrozenModel

FindingCode = Literal[
    "LOADED_BELOW_DECLARED",
    "DEMAND_NOT_INSERTED",
    "VEHICLES_STILL_RUNNING",
    "TELEPORTS",
    "COLLISIONS",
    "SUMO_WARNINGS",
]
UNMET_DEMAND: frozenset[str] = frozenset(
    {"LOADED_BELOW_DECLARED", "DEMAND_NOT_INSERTED", "VEHICLES_STILL_RUNNING"}
)
Mode = Literal["smoke", "base"]
# Por qué terminó una corrida (DEV07 F2, D7). ``not_started``: falló antes de lanzar SUMO.
Termination = Literal[
    "completed",
    "sumo_error",
    "timeout",
    "cancelled",
    "output_budget",
    "memory_budget",
    "not_started",
]


class SimulationFinding(FrozenModel):
    """Una observación sobre la corrida."""

    code: FindingCode
    message: str


class SimulationSummary(FrozenModel):
    """Resumen leído de ``statistics.xml`` y ``tripinfo.xml``.

    ``declared_vehicles`` viene de la auditoría (F4). ``demand_unmet`` es verdadero si la
    simulación terminó sin cargar toda la demanda declarada, con vehículos esperando para entrar o
    con vehículos todavía en la red.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    mode: Mode
    end_limit_s: float | None
    sumo_version: str | None
    simulated_end_s: float | None
    vehicles_loaded: int = Field(ge=0)
    vehicles_inserted: int = Field(ge=0)
    vehicles_running: int = Field(ge=0)
    vehicles_waiting: int = Field(ge=0)
    trips_finished: int = Field(ge=0)
    trips_unfinished: int = Field(ge=0)
    teleports_total: int = Field(ge=0)
    teleports_jam: int = Field(ge=0)
    teleports_yield: int = Field(ge=0)
    teleports_wrong_lane: int = Field(ge=0)
    collisions: int = Field(ge=0)
    sumo_warnings: int = Field(ge=0)
    mean_depart_delay_s: float | None
    declared_vehicles: float | None
    demand_unmet: bool
    findings: list[SimulationFinding]


class RunTiming(FrozenModel):
    """Tiempos de una corrida (``outputs/tiempos.json``; DEV07 F2, decisión D7).

    Va en un archivo propio y no en el manifiesto porque el contrato ``run_manifest`` viene de la
    documentación. Las horas y la duración no entran en comparaciones científicas (QA09).
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    started_at: datetime
    finished_at: datetime
    duration_s: float = Field(ge=0)
    wall_timeout_s: float = Field(gt=0)
    end_s: float = Field(gt=0)
    termination: Termination
    peak_memory_bytes: int | None = Field(ge=0)
    output_bytes: int = Field(ge=0)
