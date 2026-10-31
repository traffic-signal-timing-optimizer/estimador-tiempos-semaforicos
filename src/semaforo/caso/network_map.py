"""Mapa de la red para DEV03: qué enlace del semáforo controla cada movimiento del caso.

Para cada movimiento declarado busca en la red las conexiones de sus enlaces y comprueba que
salgan de los carriles declarados y lleguen a las calles declaradas. Cada enlace del semáforo debe
pertenecer a un movimiento: como enlace de paso o como punto de espera de un giro, que SUMO numera
aparte. El mapa solo lee la red; nunca la modifica.

Política (acta ``2026-10-30-dev03-f0-tiempos-y-limites``): un solo semáforo por caso. Si la red
tiene otro número, no se adivina a qué enlace corresponde cada tramo: se rechaza.
"""

from dataclasses import dataclass
from pathlib import Path

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.inventory import read_network_inventory
from semaforo.caso.movements import Movement as Connection
from semaforo.caso.movements import read_movements
from semaforo.dominio.case import Case, CaseIssue, Movement

__all__ = ["MAX_TRAFFIC_LIGHTS", "MappedMovement", "NetworkMap", "build_network_map"]

MAX_TRAFFIC_LIGHTS = 1
OWNERSHIP_RULE = "MAP-01"
CONNECTION_RULE = "MAP-02"
FIELD = "network"


@dataclass(frozen=True)
class MappedMovement:
    """Enlaces de la red que controlan un movimiento y los carriles y calles que la red usa."""

    movement_id: str
    link_indices: tuple[int, ...]
    waiting_link_indices: tuple[int, ...]
    lanes: tuple[str, ...]
    edges: tuple[str, ...]


@dataclass(frozen=True)
class NetworkMap:
    """Mapa del semáforo de la red frente a los movimientos del caso.

    ``issues`` son las diferencias entre el caso y la red. Un mapa sin problemas es el único que
    sirve de base para generar el programa derivado.
    """

    tls_id: str
    link_count: int
    movements: tuple[MappedMovement, ...]
    issues: tuple[CaseIssue, ...]

    @property
    def is_complete(self) -> bool:
        return not self.issues


def build_network_map(path: Path, case: Case) -> NetworkMap:
    """Mapa de ``path`` frente a los movimientos de ``case``.

    Raises:
        CasoError: INPUT_SCHEMA si la red no tiene exactamente un semáforo, o si no se puede leer.
    """
    signals = read_network_inventory(path).traffic_lights
    if len(signals) != MAX_TRAFFIC_LIGHTS:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            f"la red tiene {len(signals)} semáforos y esta versión solo admite "
            f"{MAX_TRAFFIC_LIGHTS}; no se asigna un tramo a un semáforo por suposición",
            FIELD,
        )
    signal = signals[0]
    connections = read_movements(path, case.vehicle_classes)
    issues: list[CaseIssue] = []
    owner: dict[int, str] = {}
    mapped: list[MappedMovement] = []
    for index, movement in enumerate(case.movements):
        rows = [
            row
            for row in connections
            if row.tls_id == signal.id and row.link_index in movement.link_indices
        ]
        issues.extend(_movement_issues(f"movements[{index}]", movement, rows, signal.id))
        waiting = sorted(
            {row.waiting_link_index for row in rows if row.waiting_link_index is not None}
        )
        issues.extend(_claim_links(f"movements[{index}]", movement, waiting, owner))
        mapped.append(_mapped(movement, rows, waiting))
    for link in range(signal.link_count):
        if link not in owner:
            issues.append(
                CaseIssue(
                    OWNERSHIP_RULE,
                    None,
                    f"el enlace {link} del semáforo no pertenece a ningún movimiento",
                )
            )
    return NetworkMap(
        tls_id=signal.id,
        link_count=signal.link_count,
        movements=tuple(mapped),
        issues=tuple(issues),
    )


def _movement_issues(
    base: str, movement: Movement, rows: list[Connection], tls_id: str
) -> list[CaseIssue]:
    """Diferencias entre un movimiento y las conexiones de la red que dice controlar."""
    issues: list[CaseIssue] = []
    if movement.tls_id != tls_id:
        issues.append(
            CaseIssue(
                OWNERSHIP_RULE,
                f"{base}.tls_id",
                f"el movimiento usa el semáforo {movement.tls_id!r}, pero la red tiene {tls_id!r}",
            )
        )
    for position, link in enumerate(movement.link_indices):
        if not any(row.link_index == link for row in rows):
            issues.append(
                CaseIssue(
                    CONNECTION_RULE,
                    f"{base}.link_indices[{position}]",
                    f"el enlace {link} no tiene ninguna conexión en la red",
                )
            )
    for row in rows:
        lane = _lane_of(row)
        if lane not in movement.incoming_lanes:
            issues.append(
                CaseIssue(
                    CONNECTION_RULE,
                    f"{base}.incoming_lanes",
                    f"el enlace {row.link_index} sale del carril {lane!r}, que el movimiento "
                    "no declara",
                )
            )
        if row.to_edge not in movement.outgoing_edges:
            issues.append(
                CaseIssue(
                    CONNECTION_RULE,
                    f"{base}.outgoing_edges",
                    f"el enlace {row.link_index} llega a la calle {row.to_edge!r}, que el "
                    "movimiento no declara",
                )
            )
    used_lanes = {_lane_of(row) for row in rows}
    for position, lane in enumerate(movement.incoming_lanes):
        if lane not in used_lanes:
            issues.append(
                CaseIssue(
                    CONNECTION_RULE,
                    f"{base}.incoming_lanes[{position}]",
                    f"ninguna conexión del movimiento sale del carril {lane!r}",
                )
            )
    return issues


def _claim_links(
    base: str, movement: Movement, waiting: list[int], owner: dict[int, str]
) -> list[CaseIssue]:
    """Registra qué movimiento controla cada enlace; un enlace solo puede tener un dueño."""
    issues: list[CaseIssue] = []
    for link in (*movement.link_indices, *waiting):
        if link in owner:
            issues.append(
                CaseIssue(
                    OWNERSHIP_RULE,
                    base,
                    f"el enlace {link} ya pertenece al movimiento {owner[link]!r}",
                )
            )
        else:
            owner[link] = movement.id
    return issues


def _mapped(movement: Movement, rows: list[Connection], waiting: list[int]) -> MappedMovement:
    return MappedMovement(
        movement_id=movement.id,
        link_indices=tuple(movement.link_indices),
        waiting_link_indices=tuple(waiting),
        lanes=tuple(sorted({_lane_of(row) for row in rows})),
        edges=tuple(sorted({row.to_edge for row in rows})),
    )


def _lane_of(row: Connection) -> str:
    """Identificador del carril de entrada de una conexión, como lo escribe SUMO (``calle_0``)."""
    return f"{row.from_edge}_{row.from_lane}"
