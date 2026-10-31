"""Grafo de calles de una red de SUMO: calles, carriles y qué calle sigue a cuál (DEV06 F2).

Sirve para validar las rutas de la demanda sin inventarlas: una ruta solo puede usar calles que
existen, que no sean tramos internos del cruce, y cada calle debe estar conectada con la siguiente.
Solo lee la red; nunca la modifica.
"""

from dataclasses import dataclass
from pathlib import Path

from semaforo.caso.movements import MAX_NET_BYTES
from semaforo.caso.permissions import permits
from semaforo.caso.xml_input import integer, parse_root, required

__all__ = ["Lane", "NetworkGraph", "read_network_graph"]


@dataclass(frozen=True)
class Lane:
    """Un carril: su calle, su posición (0 es el de la derecha) y sus permisos de clase."""

    lane_id: str
    edge_id: str
    index: int
    allow: str | None
    disallow: str | None

    def permits(self, vclass: str) -> bool:
        return permits(self.allow, self.disallow, vclass)


@dataclass(frozen=True)
class NetworkGraph:
    """Calles normales, tramos internos, carriles y pares de calles conectadas."""

    edges: frozenset[str]
    internal_edges: frozenset[str]
    lanes: dict[str, Lane]
    connections: frozenset[tuple[str, str]]

    def lanes_of(self, edge_id: str) -> tuple[Lane, ...]:
        """Carriles de una calle, de derecha a izquierda."""
        found = [lane for lane in self.lanes.values() if lane.edge_id == edge_id]
        return tuple(sorted(found, key=lambda lane: lane.index))


def read_network_graph(path: Path, max_bytes: int = MAX_NET_BYTES) -> NetworkGraph:
    """Grafo de la red de ``path`` (``.net.xml`` o ``.net.xml.gz``).

    Raises:
        CasoError: INPUT_SCHEMA si la red no se puede leer o le faltan atributos.
    """
    root = parse_root(path, max_bytes, frozenset({"net"}), "red")
    edges: set[str] = set()
    internal: set[str] = set()
    lanes: dict[str, Lane] = {}
    for edge in root.findall("edge"):
        edge_id = required(edge, "id")
        if edge.get("function") == "internal":
            internal.add(edge_id)
            continue
        edges.add(edge_id)
        for lane in edge.findall("lane"):
            lane_id = required(lane, "id")
            lanes[lane_id] = Lane(
                lane_id, edge_id, integer(lane, "index"), lane.get("allow"), lane.get("disallow")
            )
    connections = {
        (origin, required(connection, "to"))
        for connection in root.findall("connection")
        if not (origin := required(connection, "from")).startswith(":")
    }
    return NetworkGraph(frozenset(edges), frozenset(internal), lanes, frozenset(connections))
