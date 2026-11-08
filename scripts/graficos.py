"""Genera los gráficos de la arquitectura y del modelo de datos (DEV31 F7).

Las tablas y las columnas salen de ``docs/bd/esquema.toml``; las columnas de las vistas, de
``docs/arquitectura/diagramas/vistas_columnas.json`` (una prueba lo compara con la base); las
dependencias entre paquetes, del código. Nada de eso se escribe a mano: si cambia, el gráfico
queda desactualizado y ``--comprobar`` lo dice.

No usa librerías ni programas de terceros para dibujar: calcula la posición de cada caja y traza
las líneas de modo que no pasen sobre las cajas. La imagen PNG la saca el navegador Edge de la
laptop, sin internet.

Uso, desde la carpeta raíz del proyecto:

    .venv\\Scripts\\python.exe scripts\\graficos.py

Opciones: ``--comprobar`` no escribe y falla si algo no está al día; ``--vistas-desde-base``
actualiza antes las columnas de las vistas, leyéndolas de la base.
"""

import argparse
import hashlib
import heapq
import html
import itertools
import json
import math
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from graficos_arquitectura import Architecture, Box, Matrix, architecture_diagrams, package_matrix

from semaforo.bd.diseno import Design, ForeignKey, Table, load
from semaforo.bd.esquema import schema_version

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "docs" / "bd" / "esquema.toml"
OUTPUT = ROOT / "docs" / "arquitectura" / "diagramas"
VIEW_COLUMNS = "vistas_columnas.json"
FINGERPRINTS = "huellas_graficos.json"
FULL_NAME = "BD00_modelo_completo"
EDGE_BROWSER = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

CELL = 9  # lado de la cuadrícula (px); filas, cajas y líneas se alinean a ella
HEADER_H = 3 * CELL
ROW_H = 2 * CELL
CHAR_W = 6.6  # ancho de un carácter de Consolas a 12 px
GAP = 7 * CELL  # espacio entre tablas: por ahí pasan las líneas
CLUSTER_PAD = 6 * CELL
CLUSTER_GAP = 16 * CELL
TITLE_H = 14 * CELL
MARGIN = 5 * CELL
STUB = 2  # celdas que una línea sale recta de su caja
FULL_COLUMN_H = 2400  # alto buscado de cada columna de tablas en el gráfico completo (px)
AREA_COLUMN_H = 1300  # lo mismo en los gráficos por área
PNG_LIMIT = 16000  # Edge no captura imágenes más grandes (px)
MAX_SCALE = 1.6
WAIT_S = 90
SANS = "Segoe UI, Arial, sans-serif"
MONO = "Consolas, monospace"
INK = "#1f2933"
MUTED = "#52606d"
PK_COLOR = "#0b3d91"
FK_COLOR = "#7b341e"

SCHEMA_COLORS = {
    "control": ("#fdecc8", "#a66a00"),
    "caso": ("#dcefe0", "#2f7d4f"),
    "experimento": ("#e3e7fb", "#4557b8"),
    "simulacion": ("#d9eef7", "#1f7a99"),
    "aprendizaje": ("#f3e1f5", "#8a3f96"),
    "evaluacion": ("#fbdfdb", "#b5463a"),
    "vistas": ("#e8eaed", "#55606e"),
}
# Filas de cajas de esquemas en el gráfico completo.
FULL_LAYOUT = (("control", "caso", "experimento"), ("simulacion", "aprendizaje", "evaluacion"))

Point = tuple[int, int]


# ---------------------------------------------------------------------------------------------
# Trazado de líneas: camino más corto en una cuadrícula, sin cruzar cajas


@dataclass
class Router:
    """Traza líneas rectas con ángulos, en orden, evitando las cajas y separándose entre sí."""

    width: int
    height: int
    blocked: set[Point] = field(default_factory=set[Point])
    used: dict[tuple[int, int, int], int] = field(default_factory=lambda: defaultdict(int))

    TURN_COST = 6
    SHARED_COST = 5
    CROSS_COST = 1

    def block(self, x: int, y: int, w: int, h: int) -> None:
        """Marca como prohibido el rectángulo (px), con una celda de margen."""
        for cx in range(x // CELL - 1, (x + w) // CELL + 2):
            for cy in range(y // CELL - 1, (y + h) // CELL + 2):
                self.blocked.add((cx, cy))

    def route(self, start: Point, end: Point, end_blocked: Iterable[Point] = ()) -> list[Point]:
        """Camino de celdas entre dos celdas libres; lista vacía si no existe."""
        steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
        forbidden = self.blocked - {start, end, *end_blocked}
        best: dict[tuple[int, int, int], int] = {}
        came: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
        counter = 0
        queue: list[tuple[int, int, int, int, int, int]] = []
        for direction in range(4):
            state = (start[0], start[1], direction)
            best[state] = 0
            came[state] = None
            heapq.heappush(queue, (0, counter, 0, *state))
            counter += 1
        while queue:
            _, _, cost, x, y, direction = heapq.heappop(queue)
            if (x, y) == end:
                return self._walk(came, (x, y, direction))
            if cost > best[(x, y, direction)]:
                continue
            for turn, (dx, dy) in enumerate(steps):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < self.width and 0 <= ny < self.height):
                    continue
                if (nx, ny) in forbidden:
                    continue
                axis = turn // 2
                price = 1 + self.SHARED_COST * self.used[(nx, ny, axis)]
                price += self.CROSS_COST * self.used[(nx, ny, 1 - axis)]
                if turn != direction:
                    price += self.TURN_COST
                total = cost + price
                state = (nx, ny, turn)
                if total < best.get(state, 1 << 60):
                    best[state] = total
                    came[state] = (x, y, direction)
                    guess = total + abs(nx - end[0]) + abs(ny - end[1])
                    heapq.heappush(queue, (guess, counter, total, *state))
                    counter += 1
        return []

    def _walk(
        self,
        came: dict[tuple[int, int, int], tuple[int, int, int] | None],
        last: tuple[int, int, int],
    ) -> list[Point]:
        path: list[Point] = []
        state: tuple[int, int, int] | None = last
        while state is not None:
            path.append((state[0], state[1]))
            state = came[state]
        path.reverse()
        for (ax, ay), (bx, by) in itertools.pairwise(path):
            axis = 0 if ay == by else 1
            self.used[(bx, by, axis)] += 1
            self.used[(ax, ay, axis)] += 1
        return path


def _corners(points: Sequence[Point]) -> list[Point]:
    """Quita los puntos intermedios de cada tramo recto."""
    result: list[Point] = []
    for point in points:
        if result and point == result[-1]:
            continue
        if len(result) >= 2:  # noqa: PLR2004  (hacen falta dos puntos para ver si sigue recto)
            (ax, ay), (bx, by) = result[-2], result[-1]
            if (ax == bx == point[0]) or (ay == by == point[1]):
                result[-1] = point
                continue
        result.append(point)
    return result


# ---------------------------------------------------------------------------------------------
# Dibujo: una escena sencilla que se escribe como SVG


@dataclass
class Scene:
    width: int
    height: int
    parts: list[str] = field(default_factory=list[str])

    def rect(  # noqa: PLR0913  (atributos de dibujo)
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = "none",
        stroke: str = "none",
        radius: int = 0,
        dash: str = "",
    ) -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" '
            f'stroke="{stroke}"{extra}/>'
        )

    def text(  # noqa: PLR0913  (atributos de dibujo)
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: int = 12,
        color: str = INK,
        bold: bool = False,
        font: str = SANS,
        anchor: str = "start",
    ) -> None:
        weight = ' font-weight="700"' if bold else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}"{weight}>{html.escape(value, quote=False)}</text>'
        )

    def line(
        self, points: Sequence[Point], *, color: str = MUTED, dash: bool = False, arrow: bool = True
    ) -> None:
        path = " ".join(f"{x},{y}" for x, y in points)
        extra = ' stroke-dasharray="6 4"' if dash else ""
        marker = f' marker-end="url(#a{color[1:]})"' if arrow else ""
        self.parts.append(
            f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.3"'
            f"{extra}{marker}/>"
        )
        if arrow and f"a{color[1:]}" not in self.markers:
            self.markers.add(f"a{color[1:]}")
            self.defs.append(
                f'<marker id="a{color[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
                'markerHeight="8" orient="auto">'
                f'<path d="M0 0L10 5L0 10z" fill="{color}"/></marker>'
            )

    def dot(self, x: int, y: int, color: str) -> None:
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="2.6" fill="{color}"/>')

    markers: set[str] = field(default_factory=set[str])
    defs: list[str] = field(default_factory=list[str])

    def svg(self) -> str:
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}">'
        )
        defs = f"<defs>{''.join(sorted(self.defs))}</defs>"
        back = f'<rect width="{self.width}" height="{self.height}" fill="#ffffff"/>'
        return head + defs + back + "\n".join(self.parts) + "</svg>\n"


# ---------------------------------------------------------------------------------------------
# Modelo de datos: colocar las tablas


@dataclass(frozen=True)
class Row:
    """Una columna de la tabla, tal como se escribe en su caja."""

    name: str
    text: str
    kind: str  # "PK", "FK", "PF" (ambas) o ""


@dataclass
class Placed:
    """Una tabla o vista colocada en el gráfico."""

    schema: str
    name: str
    rows: tuple[Row, ...]
    width: int = 0
    x: int = 0
    y: int = 0

    @property
    def height(self) -> int:
        return HEADER_H + ROW_H * len(self.rows)

    @property
    def key(self) -> str:
        return f"{self.schema}.{self.name}"

    def row_y(self, column: str) -> int:
        index = next(i for i, row in enumerate(self.rows) if row.name == column)
        return self.y + HEADER_H + ROW_H * index + ROW_H // 2


def _snap(value: float) -> int:
    return math.ceil(value / CELL) * CELL


def _table_rows(table: Table) -> tuple[Row, ...]:
    foreign: dict[str, str] = {}
    for key in table.claves_foraneas:
        for column in key.columnas:
            foreign.setdefault(column, key.referencia.split(".")[1])
    rows: list[Row] = []
    for column in table.columnas:
        primary = column.nombre in table.clave_primaria
        linked = column.nombre in foreign
        kind = "PF" if primary and linked else "PK" if primary else "FK" if linked else ""
        mark = "?" if column.nulo else ""
        target = f" → {foreign[column.nombre]}" if linked else ""
        text = f"{kind or '  '} {column.nombre} : {column.tipo}{mark}{target}"
        rows.append(Row(column.nombre, text, kind))
    return tuple(rows)


def _place_table(table: Table) -> Placed:
    return _sized(Placed(table.esquema, table.nombre, _table_rows(table)))


def _sized(placed: Placed) -> Placed:
    longest = max([len(placed.name), *(len(row.text) for row in placed.rows)])
    placed.width = _snap(longest * CHAR_W + 2 * CELL)
    return placed


def _masonry(items: list[Placed], column_h: int) -> tuple[int, int]:
    """Coloca las tablas en columnas, en su orden, desde (0, 0); devuelve ancho y alto."""
    total = sum(item.height + GAP for item in items)
    count = max(1, math.ceil(total / column_h))
    columns: list[list[Placed]] = [[] for _ in range(count)]
    heights = [0] * count
    for item in items:
        index = heights.index(min(heights))
        columns[index].append(item)
        heights[index] += item.height + GAP
    x = 0
    for column in columns:
        y = 0
        width = max((item.width for item in column), default=0)
        for item in column:
            item.x, item.y = x, y
            y += item.height + GAP
        x += width + GAP
    return x - GAP, max(heights) - GAP


@dataclass(frozen=True)
class Relation:
    source: Placed
    source_column: str
    target: Placed
    target_column: str
    optional: bool


def _relations(tables: Sequence[Table], placed: dict[str, Placed]) -> list[Relation]:
    """Las relaciones dibujadas: sin las comunes de procedencia, ni las que salen del gráfico."""
    result: list[Relation] = []
    for table in tables:
        source = placed[f"{table.esquema}.{table.nombre}"]
        for key in table.claves_foraneas:
            target = placed.get(key.referencia)
            if target is not None and not key.comun:
                result.append(_relation(source, key, target))
    return result


def _relation(source: Placed, key: ForeignKey, target: Placed) -> Relation:
    return Relation(source, key.columnas[0], target, key.referidas[0], key.opcional)


def _ports(relation: Relation) -> tuple[Point, int, Point, int]:
    """Punto y lado (+1 derecha, -1 izquierda) por donde sale y entra cada línea."""
    source, target = relation.source, relation.target
    source_center = source.x + source.width / 2
    target_center = target.x + target.width / 2
    overlap = source.x < target.x + target.width and target.x < source.x + source.width
    if overlap:  # una sobre otra: salen y entran por la derecha, por el pasillo de al lado
        out_side = in_side = 1
    elif target_center > source_center:
        out_side, in_side = 1, -1
    else:
        out_side, in_side = -1, 1
    out_x = source.x + source.width if out_side > 0 else source.x
    in_x = target.x + target.width if in_side > 0 else target.x
    return (
        (out_x, source.row_y(relation.source_column)),
        out_side,
        (in_x, target.row_y(relation.target_column)),
        in_side,
    )


def _route_relations(
    relations: Sequence[Relation], items: Sequence[Placed], width: int, height: int
) -> list[list[Point]]:
    router = Router(width // CELL + 2, height // CELL + 2)
    for item in items:
        router.block(item.x, item.y, item.width, item.height)
    order = sorted(
        range(len(relations)),
        key=lambda i: (
            abs(relations[i].source.x - relations[i].target.x)
            + abs(relations[i].source.y - relations[i].target.y)
        ),
    )
    paths: dict[int, list[Point]] = {}
    for index in order:
        (ox, oy), out_side, (ix, iy), in_side = _ports(relations[index])
        start = (ox // CELL + out_side * STUB, oy // CELL)
        end = (ix // CELL + in_side * STUB, iy // CELL)
        stubs = [(ox // CELL + out_side * step, oy // CELL) for step in range(STUB + 1)]
        stubs += [(ix // CELL + in_side * step, iy // CELL) for step in range(STUB + 1)]
        cells = router.route(start, end, stubs)
        if not cells:
            raise SystemExit(f"sin camino: {relations[index].source.key} {start} → {end}")
        points = [(ox, oy), *((x * CELL, y * CELL) for x, y in cells), (ix, iy)]
        paths[index] = _corners(points)
    return [paths[i] for i in range(len(relations))]


LEGEND = (
    "PK clave primaria · FK relación (→ tabla) · PF las dos · ? puede quedar vacía",
    "Línea: de la columna a la tabla que refiere; punteada si es opcional",
    "carga_id y artefacto_id van en casi todas las tablas: sus líneas no se dibujan",
)


@dataclass
class ErDiagram:
    """Un gráfico del modelo de datos, ya colocado y con sus líneas."""

    name: str
    title: str
    subtitle: str
    width: int
    height: int
    items: list[Placed]
    relations: list[Relation]
    paths: list[list[Point]]
    groups: list[tuple[str, int, int, int, int]]
    legend: tuple[str, ...] = LEGEND


def _arrange(
    name: str,
    title: str,
    subtitle: str,
    layout: Sequence[Sequence[tuple[str, list[Placed]]]],
    column_h: int,
) -> tuple[ErDiagram, list[Placed]]:
    """Coloca grupos de tablas por filas; devuelve el gráfico (aún sin líneas) y sus tablas."""
    groups: list[tuple[str, int, int, int, int]] = []
    placed: list[Placed] = []
    y = MARGIN + TITLE_H
    full_w = 0
    for row in layout:
        x = MARGIN
        row_h = 0
        for schema, items in row:
            width, height = _masonry(items, column_h)
            for item in items:
                item.x += x + CLUSTER_PAD
                item.y += y + CLUSTER_PAD + 3 * CELL
            box_w = width + 2 * CLUSTER_PAD
            box_h = height + 2 * CLUSTER_PAD + 3 * CELL
            groups.append((schema, x, y, box_w, box_h))
            placed.extend(items)
            x += box_w + CLUSTER_GAP
            row_h = max(row_h, box_h)
        full_w = max(full_w, x - CLUSTER_GAP)
        y += row_h + CLUSTER_GAP
    diagram = ErDiagram(
        name, title, subtitle, full_w + MARGIN, y - CLUSTER_GAP + MARGIN, placed, [], [], groups
    )
    return diagram, placed


def _with_lines(diagram: ErDiagram, tables: Sequence[Table]) -> ErDiagram:
    index = {item.key: item for item in diagram.items}
    diagram.relations = _relations(tables, index)
    diagram.paths = _route_relations(
        diagram.relations, diagram.items, diagram.width, diagram.height
    )
    return diagram


def full_diagram(design: Design) -> ErDiagram:
    by_schema: dict[str, list[Placed]] = defaultdict(list)
    for table in design.tablas:
        by_schema[table.esquema].append(_place_table(table))
    layout = [[(schema, by_schema[schema]) for schema in row] for row in FULL_LAYOUT]
    columns = sum(len(t.columnas) for t in design.tablas)
    diagram, _ = _arrange(
        FULL_NAME,
        "Modelo de datos completo de la base «semaforo»",
        f"{len(design.tablas)} tablas · {columns} columnas · esquema {schema_version()}",
        layout,
        FULL_COLUMN_H,
    )
    return _with_lines(diagram, design.tablas)


def schema_diagrams(design: Design) -> list[ErDiagram]:
    result: list[ErDiagram] = []
    for number, (schema, description) in enumerate(design.esquemas, start=1):
        tables = [t for t in design.tablas if t.esquema == schema]
        items = [_place_table(t) for t in tables]
        columns = sum(len(t.columnas) for t in tables)
        diagram, _ = _arrange(
            f"BD{number:02d}_{schema}",
            f"Esquema {schema}: {len(tables)} tablas y {columns} columnas",
            description,
            [[(schema, items)]],
            AREA_COLUMN_H,
        )
        result.append(_with_lines(diagram, tables))
    return result


def views_diagram(design: Design, columns: dict[str, list[list[str]]]) -> ErDiagram:
    items: list[Placed] = []
    for name, _, sources in design.vistas:
        schema, short = name.split(".")
        rows = tuple(Row(c, f"   {c} : {t}", "") for c, t in columns[short])
        note = "de: " + ", ".join(source.split(".")[1] for source in sources)
        placed = Placed(schema, short, (*rows, Row("(fuentes)", note, "note")))
        items.append(_sized(placed))
    total = sum(len(rows) for rows in columns.values())
    diagram, _ = _arrange(
        f"BD{len(design.esquemas) + 1:02d}_vistas",
        f"Esquema vistas: {len(items)} vistas y {total} columnas",
        "Lo que leen el panel y las consultas. Cada caja termina con las tablas de las que sale.",
        [[("vistas", items)]],
        AREA_COLUMN_H,
    )
    diagram.legend = ()
    return diagram


def draw_er(diagram: ErDiagram) -> str:
    scene = Scene(diagram.width, diagram.height)
    scene.text(MARGIN, MARGIN + 18, diagram.title, size=24, bold=True)
    scene.text(MARGIN, MARGIN + 42, diagram.subtitle, size=14, color=MUTED)
    for index, line in enumerate(diagram.legend):
        scene.text(MARGIN, MARGIN + 64 + index * 18, line, size=13, color=MUTED)
    for schema, x, y, w, h in diagram.groups:
        fill, stroke = SCHEMA_COLORS[schema]
        scene.rect(x, y, w, h, fill=fill + "55", stroke=stroke, radius=8)
        scene.text(x + 16, y + 28, schema, size=20, bold=True, color=stroke)
    for item in diagram.items:
        _draw_table(scene, item)
    for relation, path in zip(diagram.relations, diagram.paths, strict=True):
        color = SCHEMA_COLORS[relation.source.schema][1]
        scene.line(path, color=color, dash=relation.optional)
        scene.dot(path[0][0], path[0][1], color)
    return scene.svg()


def _draw_table(scene: Scene, item: Placed) -> None:
    fill, stroke = SCHEMA_COLORS[item.schema]
    scene.rect(item.x, item.y, item.width, item.height, fill="#ffffff", stroke=stroke, radius=3)
    scene.rect(item.x, item.y, item.width, HEADER_H, fill=fill, stroke=stroke, radius=3)
    scene.text(
        item.x + item.width / 2,
        item.y + 18,
        item.name,
        size=13,
        bold=True,
        anchor="middle",
        font=MONO,
    )
    for index, row in enumerate(item.rows):
        y = item.y + HEADER_H + ROW_H * index + 13
        color = {"PK": PK_COLOR, "PF": PK_COLOR, "FK": FK_COLOR, "note": MUTED}.get(row.kind, INK)
        scene.text(
            item.x + 6, y, row.text, color=color, bold=row.kind in {"PK", "PF"}, font=MONO, size=12
        )


# ---------------------------------------------------------------------------------------------
# Archivo editable de draw.io


def _attrs(**values: object) -> str:
    return " ".join(f'{k}="{html.escape(str(v), quote=True)}"' for k, v in values.items())


def _style(**values: object) -> str:
    return "".join(f"{k}={v};" for k, v in values.items())


def _vertex(identifier: str, value: str, style: str, parent: str, *box: int) -> str:
    x, y, w, h = box
    cell = _attrs(id=identifier, value=value, style=style, vertex=1, parent=parent)
    size = _attrs(x=x, y=y, width=w, height=h)
    return f'<mxCell {cell}><mxGeometry {size} as="geometry"/></mxCell>'


def _row_style(kind: str) -> str:
    color = {"PK": PK_COLOR, "PF": PK_COLOR, "FK": FK_COLOR}.get(kind, INK)
    return (
        "text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=6;"
        "spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];"
        "portConstraint=eastwest;fontFamily=Consolas;fontSize=12;html=0;"
        + _style(fontStyle=1 if kind in {"PK", "PF"} else 0, fontColor=color)
    )


def _table_cells(item: Placed) -> list[str]:
    fill, stroke = SCHEMA_COLORS[item.schema]
    style = (
        "swimlane;align=center;verticalAlign=middle;childLayout=stackLayout;horizontal=1;"
        "horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=1;"
        "marginBottom=0;fontFamily=Consolas;fontSize=13;html=0;fontStyle=1;"
        "swimlaneFillColor=#ffffff;"
        + _style(startSize=HEADER_H, fillColor=fill, strokeColor=stroke)
    )
    cells = [
        _vertex(f"t:{item.key}", item.name, style, "1", item.x, item.y, item.width, item.height)
    ]
    for index, row in enumerate(item.rows):
        cells.append(
            _vertex(
                f"c:{item.key}.{row.name}",
                row.text,
                _row_style(row.kind),
                f"t:{item.key}",
                0,
                HEADER_H + ROW_H * index,
                item.width,
                ROW_H,
            )
        )
    return cells


def _edge_cell(index: int, relation: Relation, path: Sequence[Point]) -> str:
    color = SCHEMA_COLORS[relation.source.schema][1]
    (_, out_side, _, in_side) = _ports(relation)
    style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=0;"
        + _style(
            startArrow="ERzeroToMany",
            startFill=0,
            endArrow="ERzeroToOne" if relation.optional else "ERmandOne",
            endFill=0,
            strokeColor=color,
            exitX=1 if out_side > 0 else 0,
            exitY=0.5,
            exitDx=0,
            exitDy=0,
            entryX=1 if in_side > 0 else 0,
            entryY=0.5,
            entryDx=0,
            entryDy=0,
            dashed=1 if relation.optional else 0,
        )
    )
    source = f"c:{relation.source.key}.{relation.source_column}"
    target = f"c:{relation.target.key}.{relation.target_column}"
    points = "".join(f"<mxPoint {_attrs(x=x, y=y)}/>" for x, y in path[1:-1])
    cell = _attrs(id=f"r{index}", style=style, edge=1, parent="1", source=source, target=target)
    return (
        f'<mxCell {cell}><mxGeometry relative="1" as="geometry">'
        f'<Array as="points">{points}</Array></mxGeometry></mxCell>'
    )


def drawio(diagram: ErDiagram) -> str:
    """El gráfico como archivo de draw.io: cada tabla se mueve con sus filas y sus líneas."""
    text_style = "text;html=0;strokeColor=none;fillColor=none;align=left;verticalAlign=top;"
    cells = [
        '<mxCell id="0"/>',
        '<mxCell id="1" parent="0"/>',
        _vertex(
            "titulo",
            f"{diagram.title} ({diagram.subtitle})",
            text_style + "fontSize=24;fontStyle=1;",
            "1",
            MARGIN,
            MARGIN,
            diagram.width - 2 * MARGIN,
            36,
        ),
        _vertex(
            "leyenda",
            " · ".join(diagram.legend),
            text_style + "fontSize=13;whiteSpace=wrap;",
            "1",
            MARGIN,
            MARGIN + 54,
            diagram.width - 2 * MARGIN,
            27,
        ),
    ]
    for schema, x, y, w, h in diagram.groups:
        fill, stroke = SCHEMA_COLORS[schema]
        style = (
            "rounded=1;arcSize=1;html=0;align=left;verticalAlign=top;spacingLeft=14;spacingTop=6;"
            "fontSize=20;fontStyle=1;"
            + _style(fillColor=fill, strokeColor=stroke, fontColor=stroke, opacity=35)
        )
        cells.append(_vertex(f"g:{schema}", schema, style, "1", x, y, w, h))
    for item in diagram.items:
        cells.extend(_table_cells(item))
    for index, (relation, path) in enumerate(zip(diagram.relations, diagram.paths, strict=True)):
        cells.append(_edge_cell(index, relation, path))
    model = _attrs(
        dx=0,
        dy=0,
        grid=1,
        gridSize=CELL,
        guides=1,
        tooltips=1,
        connect=1,
        arrows=1,
        fold=1,
        page=0,
        pageScale=1,
        pageWidth=diagram.width,
        pageHeight=diagram.height,
        math=0,
        shadow=0,
    )
    return (
        '<mxfile host="app.diagrams.net" agent="scripts/graficos.py">'
        '<diagram id="modelo-de-datos" name="Modelo de datos">'
        f"<mxGraphModel {model}><root>\n" + "\n".join(cells) + "\n</root></mxGraphModel>"
        "</diagram></mxfile>\n"
    )


# ---------------------------------------------------------------------------------------------
# Gráficos de arquitectura: cajas colocadas a mano y líneas trazadas solas

KINDS = {
    "hecho": ("#d9eef7", "#1f7a99", ""),
    "dato": ("#dcefe0", "#2f7d4f", ""),
    "pendiente": ("#f4f5f7", "#7b8794", "6 4"),
    "externo": ("#fdecc8", "#a66a00", ""),
    "riesgo": ("#fbdfdb", "#b5463a", ""),
    "persona": ("#f3e1f5", "#8a3f96", ""),
}


def _side(source: Box, target: Box) -> str:
    """Por qué lado sale una línea de ``source`` hacia ``target``."""
    if target.y >= source.y + source.h:
        return "down"
    if source.y >= target.y + target.h:
        return "up"
    return "right" if target.x >= source.x else "left"


OPPOSITE = {"down": "up", "up": "down", "right": "left", "left": "right"}
SIDE_STEP = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}


def _anchor(box: Box, side: str, index: int, count: int) -> Point:
    """Celda del borde de la caja: las líneas de un mismo lado se reparten a lo largo de él."""
    if side in {"down", "up"}:
        x = box.x + (box.w * (index + 1)) // (count + 1)
        return (x, box.y + box.h if side == "down" else box.y)
    y = box.y + (box.h * (index + 1)) // (count + 1)
    return (box.x + box.w if side == "right" else box.x, y)


def draw_architecture(diagram: Architecture) -> str:
    boxes = {box.identifier: box for box in diagram.boxes}
    width, height = diagram.width * CELL, diagram.height * CELL
    scene = Scene(width, height)
    scene.text(MARGIN, 40, diagram.title, size=22, bold=True)
    scene.text(MARGIN, 64, diagram.subtitle, size=13, color=MUTED)
    for group in diagram.groups:
        scene.rect(
            group.x * CELL,
            group.y * CELL,
            group.w * CELL,
            group.h * CELL,
            fill="#fafbfc",
            stroke=group.stroke,
            radius=8,
        )
        scene.text(
            group.x * CELL + 10,
            group.y * CELL + 20,
            group.label,
            size=13,
            bold=True,
            color=group.stroke,
        )
    router = Router(diagram.width + 2, diagram.height + 2)
    for box in diagram.boxes:
        router.block(box.x * CELL, box.y * CELL, box.w * CELL, box.h * CELL)
    # Reparte las líneas de cada lado de cada caja según hacia dónde van, para que no se crucen.
    uses: dict[tuple[str, str], list[tuple[int, int, str]]] = defaultdict(list)
    for index, link in enumerate(diagram.links):
        source, target = boxes[link.source], boxes[link.target]
        out = _side(source, target)
        back = OPPOSITE[out]
        uses[(link.source, out)].append((target.x + target.y, index, "s"))
        uses[(link.target, back)].append((source.x + source.y, index, "t"))
    anchors: dict[tuple[int, str], tuple[Point, str]] = {}
    for (name, side), entries in uses.items():
        entries.sort()
        for position, (_, index, role) in enumerate(entries):
            anchors[(index, role)] = (_anchor(boxes[name], side, position, len(entries)), side)
    labels: list[tuple[int, int, str]] = []
    for index, link in enumerate(diagram.links):
        (start, out), (end, back) = anchors[(index, "s")], anchors[(index, "t")]
        ox, oy = SIDE_STEP[out]
        ix, iy = SIDE_STEP[back]
        begin = (start[0] + ox * STUB, start[1] + oy * STUB)
        finish = (end[0] + ix * STUB, end[1] + iy * STUB)
        free = [(start[0] + ox * i, start[1] + oy * i) for i in range(STUB + 1)]
        free += [(end[0] + ix * i, end[1] + iy * i) for i in range(STUB + 1)]
        cells = router.route(begin, finish, free)
        if not cells:
            raise SystemExit(f"sin camino en {diagram.name}: {link.source} → {link.target}")
        path = _corners([start, *cells, end])
        points = [(x * CELL, y * CELL) for x, y in path]
        scene.line(points, color=MUTED, dash=link.dashed)
        if link.label:
            labels.append((*_label_spot(points), link.label))
    for box in diagram.boxes:
        _draw_box(scene, box)
    for x, y, text in labels:
        half = len(text) * 3.2 + 4
        scene.rect(x - half, y - 8, 2 * half, 15, fill="#ffffff")
        scene.text(x, y + 3, text, size=11, color=MUTED, anchor="middle")
    return scene.svg()


def _label_spot(points: Sequence[Point]) -> Point:
    """El centro del tramo más largo de la línea."""
    best = max(
        itertools.pairwise(points),
        key=lambda pair: abs(pair[0][0] - pair[1][0]) + abs(pair[0][1] - pair[1][1]),
    )
    return ((best[0][0] + best[1][0]) // 2, (best[0][1] + best[1][1]) // 2)


def _draw_box(scene: Scene, box: Box) -> None:
    fill, stroke, dash = KINDS[box.kind]
    x, y, w, h = box.x * CELL, box.y * CELL, box.w * CELL, box.h * CELL
    scene.rect(x, y, w, h, fill=fill, stroke=stroke, radius=6, dash=dash)
    line_h = 16
    top = y + h / 2 - line_h * (len(box.lines) - 1) / 2 + 4
    for index, text in enumerate(box.lines):
        scene.text(
            x + w / 2,
            top + index * line_h,
            text,
            size=13 if index == 0 else 11,
            bold=index == 0,
            color=INK if index == 0 else MUTED,
            anchor="middle",
        )


# ---------------------------------------------------------------------------------------------
# Matriz de dependencias entre paquetes

MATRIX_CELL = 5 * CELL
MATRIX_LABEL_W = 44 * CELL
MATRIX_HEAD_H = 15 * CELL
MATRIX_TOP = 11 * CELL


def matrix_size(matrix: Matrix) -> tuple[int, int]:
    count = len(matrix.packages)
    width = MARGIN * 2 + MATRIX_LABEL_W + count * MATRIX_CELL
    return width, MATRIX_TOP + MATRIX_HEAD_H + count * MATRIX_CELL + 7 * CELL


def draw_matrix(matrix: Matrix) -> str:
    width, height = matrix_size(matrix)
    scene = Scene(width, height)
    scene.text(MARGIN, 40, matrix.title, size=22, bold=True)
    scene.text(MARGIN, 64, matrix.subtitle, size=13, color=MUTED)
    left = MARGIN + MATRIX_LABEL_W
    top = MATRIX_TOP + MATRIX_HEAD_H
    names = [name for name, _ in matrix.packages]
    for index, name in enumerate(names):
        x = left + index * MATRIX_CELL + MATRIX_CELL // 2 + 4
        scene.parts.append(
            f'<text x="{x}" y="{top - 8}" font-family="{MONO}" font-size="13" font-weight="700" '
            f'fill="{INK}" transform="rotate(-60 {x} {top - 8})">{name}</text>'
        )
    for row, (name, role) in enumerate(matrix.packages):
        y = top + row * MATRIX_CELL
        scene.text(MARGIN, y + 20, name, size=13, bold=True, font=MONO)
        scene.text(MARGIN, y + 36, role, size=11, color=MUTED)
        for column, other in enumerate(names):
            x = left + column * MATRIX_CELL
            forbidden = other in matrix.forbidden.get(name, frozenset())
            fill = "#e8eaed" if other == name else "#fbdfdb" if forbidden else "#ffffff"
            scene.rect(x, y, MATRIX_CELL, MATRIX_CELL, fill=fill, stroke="#cbd2d9")
            if other in matrix.links.get(name, frozenset()):
                scene.parts.append(
                    f'<circle cx="{x + MATRIX_CELL // 2}" cy="{y + MATRIX_CELL // 2}" r="8" '
                    'fill="#1f7a99"/>'
                )
    notes = (
        "Círculo: el paquete de la fila importa al de la columna.",
        "Rojo: dependencia prohibida por ADR01 (tests/unit/test_arquitectura.py).",
    )
    for index, note in enumerate(notes):
        scene.text(MARGIN, height - 4 * CELL + index * 18, note, size=12, color=MUTED)
    return scene.svg()


# ---------------------------------------------------------------------------------------------
# Salida


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_png(browser: Path, svg: str, target: Path, width: int, height: int) -> None:
    """Saca la imagen con Edge, sin ventana y sin internet."""
    scale = min(MAX_SCALE, PNG_LIMIT / max(width, height))
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "grafico.html"
        page.write_text(
            f'<!doctype html><meta charset="utf-8"><body style="margin:0">{svg}</body>',
            encoding="utf-8",
        )
        subprocess.run(  # noqa: S603  (programa local, ruta fija y lista de argumentos)
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--hide-scrollbars",
                f"--user-data-dir={Path(folder) / 'perfil'}",
                f"--force-device-scale-factor={scale:.3f}",
                f"--window-size={width},{height}",
                f"--screenshot={target}",
                page.as_uri(),
            ],
            capture_output=True,
            check=False,
            timeout=WAIT_S * 4,
        )
        for _ in range(WAIT_S):
            if target.exists() and target.stat().st_size > 0:
                break
            time.sleep(1)
        time.sleep(1)
    if not target.exists():
        raise SystemExit(f"Edge no produjo {target.name}")


def view_columns(folder: Path) -> dict[str, list[list[str]]]:
    data: dict[str, list[list[str]]] = json.loads(
        (folder / VIEW_COLUMNS).read_text(encoding="utf-8")
    )
    return data


def read_view_columns() -> dict[str, list[list[str]]]:
    """Columnas de las vistas según la base, con el usuario de lectura."""
    from semaforo.bd.conexion import LECTURA, connect  # noqa: PLC0415  (solo con esta opción)

    with connect(LECTURA) as connection:
        rows = connection.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'vistas' ORDER BY table_name, ordinal_position"
        ).fetchall()
    result: dict[str, list[list[str]]] = defaultdict(list)
    for table, column, kind in rows:
        result[str(table)].append([str(column), str(kind)])
    return dict(result)


def build(folder: Path) -> tuple[dict[str, tuple[str, int, int]], str]:
    """Todos los gráficos como SVG, con su tamaño, y el archivo editable del completo."""
    design = load(SCHEMA_FILE)
    full = full_diagram(design)
    images = {full.name: (draw_er(full), full.width, full.height)}
    for diagram in [*schema_diagrams(design), views_diagram(design, view_columns(folder))]:
        images[diagram.name] = (draw_er(diagram), diagram.width, diagram.height)
    matrix = package_matrix(ROOT / "src" / "semaforo", ROOT / "tests")
    images[matrix.name] = (draw_matrix(matrix), *matrix_size(matrix))
    for spec in architecture_diagrams():
        images[spec.name] = (draw_architecture(spec), spec.width * CELL, spec.height * CELL)
    return images, drawio(full)


def check(folder: Path) -> list[str]:
    """Lo que no está al día respecto del esquema, la base documentada y el código."""
    images, editable = build(folder)
    problems: list[str] = []
    recorded = folder / FINGERPRINTS
    known = json.loads(recorded.read_text(encoding="utf-8")) if recorded.exists() else {}
    for name, (svg, _, _) in images.items():
        if known.get(name) != sha256_text(svg):
            problems.append(f"{name}: la imagen no corresponde a las fuentes actuales")
        if not (folder / f"{name}.png").exists():
            problems.append(f"{name}: falta la imagen")
    file = folder / f"{FULL_NAME}.drawio"
    if not file.exists() or file.read_text(encoding="utf-8") != editable:
        problems.append(f"{FULL_NAME}.drawio: no corresponde a las fuentes actuales")
    return problems


def generate(folder: Path, browser: Path) -> None:
    images, editable = build(folder)
    fingerprints: dict[str, str] = {}
    for name, (svg, width, height) in images.items():
        write_png(browser, svg, folder / f"{name}.png", width, height)
        fingerprints[name] = sha256_text(svg)
        print(
            name, width, height, (folder / f"{name}.png").stat().st_size // 1024, "KB", flush=True
        )
    (folder / f"{FULL_NAME}.drawio").write_text(editable, encoding="utf-8", newline="\n")
    (folder / FINGERPRINTS).write_text(
        json.dumps(fingerprints, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comprobar", action="store_true", help="no escribe; falla si no está al día"
    )
    parser.add_argument("--vistas-desde-base", action="store_true")
    parser.add_argument("--carpeta", type=Path, default=OUTPUT)
    parser.add_argument("--navegador", type=Path, default=EDGE_BROWSER)
    args = parser.parse_args()
    folder: Path = args.carpeta
    if args.comprobar:
        problems = check(folder)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print("Regenere con: python scripts/graficos.py", file=sys.stderr)
            return 1
        print("Los gráficos están al día.")
        return 0
    folder.mkdir(parents=True, exist_ok=True)
    if args.vistas_desde_base:
        (folder / VIEW_COLUMNS).write_text(
            json.dumps(read_view_columns(), indent=1, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    generate(folder, args.navegador)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
