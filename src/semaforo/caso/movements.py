"""Movimientos semafóricos por carril y clase de vehículo (tabla para QA23).

Un movimiento es una conexión controlada por un semáforo, entre un carril de entrada y uno de
salida. Es el primer paso del mapa de red de DEV03, que además asociará los movimientos del caso.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field

from semaforo.caso.base_model import FrozenModel
from semaforo.caso.permissions import permits
from semaforo.caso.xml_input import integer, parse_root, required

MAX_NET_BYTES = 64 * 1024 * 1024
# Códigos de giro de SUMO (atributo dir de <connection>).
DIRECTIONS = {
    "s": "recto",
    "l": "izquierda",
    "r": "derecha",
    "t": "vuelta en U",
    "L": "izquierda suave",
    "R": "derecha suave",
}


class Movement(FrozenModel):
    """Una conexión controlada por un semáforo.

    ``id`` numera los movimientos (``M01``…) por semáforo y ``linkIndex``. ``classes`` son las
    clases, de las pedidas, que admiten el carril de entrada, el de salida y la propia conexión.
    """

    id: str
    tls_id: str
    link_index: int = Field(ge=0)
    from_edge: str
    from_lane: int = Field(ge=0)
    to_edge: str
    to_lane: int = Field(ge=0)
    direction: str
    classes: list[str]


class MovementTable(FrozenModel):
    """Tabla de movimientos de una red (``movements.json`` de una recepción)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    classes: list[str]
    movements: list[Movement]


def read_movements(
    path: Path, classes: Sequence[str], max_bytes: int = MAX_NET_BYTES
) -> list[Movement]:
    """Movimientos semafóricos de la red de ``path``, en orden de semáforo y ``linkIndex``.

    Raises:
        CasoError: INPUT_SCHEMA si la red no se puede leer o le faltan atributos.
    """
    root = parse_root(path, max_bytes, frozenset({"net"}), "red")
    lanes: dict[str, tuple[str | None, str | None]] = {
        required(lane, "id"): (lane.get("allow"), lane.get("disallow"))
        for edge in root.findall("edge")
        for lane in edge.findall("lane")
    }
    rows: list[tuple[str, int, str, int, str, int, str, list[str]]] = []
    for connection in root.findall("connection"):
        tls_id, origin = connection.get("tl"), required(connection, "from")
        if tls_id is None or origin.startswith(":"):
            continue
        target = required(connection, "to")
        from_lane, to_lane = integer(connection, "fromLane"), integer(connection, "toLane")
        source_lane = lanes.get(f"{origin}_{from_lane}", (None, None))
        target_lane = lanes.get(f"{target}_{to_lane}", (None, None))
        allowed = [
            vclass
            for vclass in classes
            if permits(*source_lane, vclass)
            and permits(*target_lane, vclass)
            and permits(connection.get("allow"), connection.get("disallow"), vclass)
        ]
        code = connection.get("dir", "")
        rows.append(
            (
                tls_id,
                integer(connection, "linkIndex"),
                origin,
                from_lane,
                target,
                to_lane,
                DIRECTIONS.get(code, code),
                allowed,
            )
        )
    order = {tls: position for position, tls in enumerate(dict.fromkeys(row[0] for row in rows))}
    rows.sort(key=lambda row: (order[row[0]], row[1], row[2], row[3], row[4], row[5]))
    return [
        Movement(
            id=f"M{number:02d}",
            tls_id=tls_id,
            link_index=link_index,
            from_edge=origin,
            from_lane=from_lane,
            to_edge=target,
            to_lane=to_lane,
            direction=direction,
            classes=allowed,
        )
        for number, (
            tls_id,
            link_index,
            origin,
            from_lane,
            target,
            to_lane,
            direction,
            allowed,
        ) in enumerate(rows, start=1)
    ]
