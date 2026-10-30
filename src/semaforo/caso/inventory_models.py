"""Inventario de una red SUMO: conteos, semáforos con sus programas y hallazgos (ADR09, F3).

Describe lo que la red declara, sin interpretarlo como calibración. No lleva rutas ni fechas: la
misma red produce siempre el mismo inventario.
"""

from typing import Literal

from pydantic import Field

from semaforo.dominio.base_model import FrozenModel

FindingCode = Literal[
    "PHASE_DURATION_BELOW_MIN",
    "PHASE_DURATION_ABOVE_MAX",
    "STATE_LENGTH_MISMATCH",
    "MULTIPLE_PROGRAMS",
    "TLS_WITHOUT_PROGRAM",
]


class NetworkCounts(FrozenModel):
    """Elementos de la red. Los totales incluyen los internos que SUMO crea dentro de cada cruce."""

    junctions: int = Field(ge=0)
    junction_types: dict[str, int]
    edges_total: int = Field(ge=0)
    edges_internal: int = Field(ge=0)
    lanes_total: int = Field(ge=0)
    lanes_internal: int = Field(ge=0)
    connections_total: int = Field(ge=0)
    connections_from_internal: int = Field(ge=0)


class Phase(FrozenModel):
    """Una fase de un programa. ``index`` cuenta desde 0, en el orden del archivo."""

    index: int = Field(ge=0)
    duration_s: float
    min_dur_s: float | None
    max_dur_s: float | None
    state: str
    name: str | None


class TlsProgram(FrozenModel):
    """Un programa semafórico (``tlLogic``) tal como está en la red."""

    program_id: str
    type: str
    offset_s: float
    params: dict[str, str]
    phases: list[Phase]


class TlsInventory(FrozenModel):
    """Un semáforo: sus enlaces controlados y sus programas.

    ``link_count`` es el mayor ``linkIndex`` más uno. ``active_program_id`` es el programa que SUMO
    1.27.1 ejecuta al arrancar cuando la red trae varios: el último del archivo (comprobado en
    ``tests/integration/test_inventory_sumo.py``). Un cambio de programa durante la simulación
    (TraCI o un archivo adicional) no se refleja aquí.
    """

    id: str
    link_count: int = Field(ge=0)
    connection_count: int = Field(ge=0)
    active_program_id: str | None
    programs: list[TlsProgram]


class InventoryFinding(FrozenModel):
    """Una observación sobre la red. No afirma que sea un error: lo revisa el Product Owner."""

    code: FindingCode
    tls_id: str
    program_id: str | None
    phase_index: int | None
    message: str


class NetworkInventory(FrozenModel):
    """Inventario completo de una red."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    net_version: str | None
    counts: NetworkCounts
    traffic_lights: list[TlsInventory]
    findings: list[InventoryFinding]
