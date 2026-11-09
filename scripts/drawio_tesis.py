"""Versiones editables en draw.io de las figuras del punto 3 de la tesis.

Genera un ``.drawio`` por cada figura de ``documentacion/tesis-punto-3/figuras``:

- Los diagramas de ``graficos_tesis.py`` se convierten desde su modelo: cada caja es una forma con
  su texto y cada flecha queda unida a sus dos cajas, así que al mover una caja la flecha la sigue.
- Las demás (secuencia de fases, hojas, canvas y matriz) se convierten desde su SVG: cada
  rectángulo, texto, línea y círculo pasa a su forma de draw.io. Sus líneas no quedan unidas a
  cajas porque el SVG no registra esa relación.
- Las dos capturas del panel no son vectoriales: se incrustan como imagen.

Uso, desde la carpeta raíz del proyecto:

    .venv\\Scripts\\python.exe scripts\\drawio_tesis.py
"""

import base64
import html
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from defusedxml import ElementTree as SafeET

sys.path.insert(0, str(Path(__file__).resolve().parent))

import graficos_tesis as gt

ROOT = Path(__file__).resolve().parents[1]
FIGURAS = ROOT / "documentacion" / "tesis-punto-3" / "figuras"
FONT = "Segoe UI"
Point = tuple[float, float]
Box = tuple[float, float, float, float]


def style(**values: object) -> str:
    """Estilo de draw.io: pares clave=valor separados por punto y coma; omite los None."""
    return "".join(f"{key}={value};" for key, value in values.items() if value is not None)


def color(value: str | None) -> str:
    return "none" if value in (None, "", "none") else value


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def text_html(value: str) -> str:
    return html.escape(value, quote=False)


def vertex(cell_id: str, value: str, st: str, box: Box) -> str:
    x, y, w, h = box
    return (
        f'<mxCell id="{esc(cell_id)}" value="{esc(value)}" style="{esc(st)}" vertex="1" parent="1">'
        f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry"/>'
        "</mxCell>"
    )


def connected(  # noqa: PLR0913, PLR0917  (una arista lleva origen, destino, texto, estilo y recorrido)
    cell_id: str, source: str, target: str, value: str, st: str, via: Sequence[Point] = ()
) -> str:
    inner = "".join(f'<mxPoint x="{x:.1f}" y="{y:.1f}"/>' for x, y in via)
    array = f'<Array as="points">{inner}</Array>' if via else ""
    return (
        f'<mxCell id="{esc(cell_id)}" value="{esc(value)}" style="{esc(st)}" edge="1" parent="1" '
        f'source="{esc(source)}" target="{esc(target)}">'
        f'<mxGeometry relative="1" as="geometry">{array}</mxGeometry></mxCell>'
    )


def free_line(cell_id: str, points: Sequence[Point], st: str) -> str:
    (sx, sy), *middle, (tx, ty) = points
    inner = "".join(f'<mxPoint x="{x:.1f}" y="{y:.1f}"/>' for x, y in middle)
    array = f'<Array as="points">{inner}</Array>' if middle else ""
    return (
        f'<mxCell id="{esc(cell_id)}" value="" style="{esc(st)}" edge="1" parent="1">'
        f'<mxGeometry relative="1" as="geometry">'
        f'<mxPoint x="{sx:.1f}" y="{sy:.1f}" as="sourcePoint"/>'
        f'<mxPoint x="{tx:.1f}" y="{ty:.1f}" as="targetPoint"/>{array}</mxGeometry></mxCell>'
    )


def document(name: str, width: float, height: float, cells: Sequence[str]) -> str:
    return (
        f'<mxfile host="app.diagrams.net" agent="scripts/drawio_tesis.py">'
        f'<diagram id="{esc(name)}" name="{esc(name)}">'
        f'<mxGraphModel dx="0" dy="0" grid="1" gridSize="9" guides="1" tooltips="1" connect="1" '
        f'arrows="1" fold="1" page="0" pageScale="1" '
        f'pageWidth="{width:.0f}" pageHeight="{height:.0f}" '
        f'math="0" shadow="0"><root>'
        + "".join(cells)
        + "</root></mxGraphModel></diagram></mxfile>\n"
    )


# ------------------------------------------------------- diagramas con modelo (cajas y flechas)


def exit_point(where: str, fraction: float) -> Point:
    return {
        "right": (1.0, fraction),
        "left": (0.0, fraction),
        "down": (fraction, 1.0),
        "up": (fraction, 0.0),
    }[where]


def anchors(spec: gt.Spec, boxes: dict[str, Box]) -> dict[tuple[int, str], tuple[str, float]]:
    """Reparte los puntos de cada lado de una caja como en el SVG, para que no se crucen."""
    uses: dict[tuple[str, str], list[tuple[float, int, str]]] = defaultdict(list)
    for index, edge in enumerate(spec.edges):
        a, b = boxes[edge.source], boxes[edge.target]
        out = edge.out or gt.side(a, b)
        back = edge.into or gt.OPPOSITE[out]
        uses[(edge.source, out)].append((b[0] + b[1], index, "s"))
        uses[(edge.target, back)].append((a[0] + a[1], index, "t"))
    placed: dict[tuple[int, str], tuple[str, float]] = {}
    for (_, where), entries in uses.items():
        entries.sort()
        for position, (_, index, role) in enumerate(entries):
            placed[(index, role)] = (where, (position + 1) / (len(entries) + 1))
    return placed


def node_cell(node: gt.N, box: Box) -> str:
    if node.kind == "grupo":
        return vertex(
            f"n-{node.id}", "", style(rounded=0, fillColor="none", strokeColor="none"), box
        )
    fill, stroke, title_color, body_color, dash = gt.KIND[node.kind]
    head, body, _ = gt.layout(node)
    lines = [
        f'<span style="font-size:{gt.TITLE}px;color:{title_color}"><b>{text_html(line)}</b></span>'
        for line in head
    ]
    if node.tag:
        tag = text_html(node.tag)
        lines.append(f'<span style="font-size:{gt.TAG}px;color:{body_color}"><i>[{tag}]</i></span>')
    lines += [
        f'<span style="font-size:{gt.BODY}px;color:{body_color}">{text_html(line)}</span>'
        for line in body
    ]
    st = style(
        html=1,
        whiteSpace="nowrap",
        rounded=1,
        absoluteArcSize=1,
        arcSize=14,
        align="center",
        verticalAlign="middle",
        spacing=0,
        fillColor=fill,
        strokeColor=stroke,
        dashed=1 if dash else None,
        dashPattern=dash or None,
        fontFamily=FONT,
        fontSize=gt.BODY,
    )
    return vertex(f"n-{node.id}", "<br>".join(lines), st, box)


def spec_cells(spec: gt.Spec) -> list[str]:
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    boxes: dict[str, Box] = {}
    for node in spec.nodes:
        x, y, w, h = gt.box_of(node)
        boxes[node.id] = (x * gt.CELL, y * gt.CELL, w * gt.CELL, h * gt.CELL)
    for index, group in enumerate(spec.groups):
        st = style(
            rounded=1,
            absoluteArcSize=1,
            arcSize=20,
            html=0,
            whiteSpace="nowrap",
            fillColor="#fbfcfd",
            strokeColor=group.stroke,
            dashed=1 if group.dash else None,
            dashPattern="8 5" if group.dash else None,
            align="left",
            verticalAlign="top",
            spacingLeft=12,
            spacingTop=5,
            fontStyle=1,
            fontColor=group.stroke,
            fontSize=14,
            fontFamily=FONT,
        )
        box = (group.x * gt.CELL, group.y * gt.CELL, group.w * gt.CELL, group.h * gt.CELL)
        cells.append(vertex(f"g{index}", group.label, st, box))
    placed = anchors(
        spec,
        {
            n.id: (
                boxes[n.id][0] / gt.CELL,
                boxes[n.id][1] / gt.CELL,
                boxes[n.id][2] / gt.CELL,
                boxes[n.id][3] / gt.CELL,
            )
            for n in spec.nodes
        },
    )
    routes = gt.edge_routes(spec)
    for index, edge in enumerate(spec.edges):
        s_where, s_frac = placed[(index, "s")]
        t_where, t_frac = placed[(index, "t")]
        ex, ey = exit_point(s_where, s_frac)
        nx, ny = exit_point(t_where, t_frac)
        st = style(
            edgeStyle="orthogonalEdgeStyle",
            rounded=0,
            orthogonalLoop=1,
            jettySize="auto",
            html=1,
            endArrow="classic",
            endFill=1,
            strokeColor=gt.MUTED,
            strokeWidth=1.3,
            labelBackgroundColor="#ffffff",
            fontSize=gt.SMALL,
            fontColor=gt.MUTED,
            fontFamily=FONT,
            exitX=ex,
            exitY=ey,
            entryX=nx,
            entryY=ny,
            exitPerimeter=0,
            entryPerimeter=0,
            dashed=1 if edge.dashed else None,
            dashPattern="6 4" if edge.dashed else None,
        )
        cells.append(
            connected(
                f"e{index}",
                f"n-{edge.source}",
                f"n-{edge.target}",
                text_html(edge.label),
                st,
                routes[index][1:-1],
            )
        )
    for node in spec.nodes:
        cells.append(node_cell(node, boxes[node.id]))
    return cells


# ---------------------------------------------------------------- figuras desde su SVG


def rotate(point: Point, theta: float, pivot: Point) -> Point:
    dx, dy = point[0] - pivot[0], point[1] - pivot[1]
    return (
        pivot[0] + dx * math.cos(theta) - dy * math.sin(theta),
        pivot[1] + dx * math.sin(theta) + dy * math.cos(theta),
    )


def text_cell(cell_id: str, element: ET.Element) -> str:
    size = float(element.get("font-size", "12"))
    family_attr = element.get("font-family", "Arial")
    mono = "Consolas" in family_attr or "monospace" in family_attr
    content = element.text or ""
    width = len(content) * size * (0.6 if mono else 0.56) + 6
    height = size * 1.5
    x, y = float(element.get("x", "0")), float(element.get("y", "0"))
    anchor = element.get("text-anchor", "start")
    center_y = y - 0.35 * size
    bold = element.get("font-weight") in ("700", "bold")
    italic = element.get("font-style") == "italic"
    family = family_attr.split(",")[0].strip().strip("'\"")
    st = "text;" + style(
        html=0,
        whiteSpace="nowrap",
        strokeColor="none",
        fillColor="none",
        spacing=0,
        verticalAlign="middle",
        fontFamily=family,
        fontSize=f"{size:g}",
        fontColor=color(element.get("fill")),
        fontStyle=(1 if bold else 0) + (2 if italic else 0),
    )
    match = re.fullmatch(
        r"rotate\((-?[\d.]+) (-?[\d.]+) (-?[\d.]+)\)", element.get("transform") or ""
    )
    if match:
        # El texto empieza en su borde izquierdo y gira alrededor del pivote del SVG.
        angle, px, py = (float(g) for g in match.groups())
        theta = math.radians(angle)
        left_x, left_y = rotate((x, center_y), theta, (px, py))
        cx = left_x + (width / 2) * math.cos(theta)
        cy = left_y + (width / 2) * math.sin(theta)
        st += style(rotation=f"{angle:g}")
        align = "left"
    elif anchor == "middle":
        cx, cy, align = x, center_y, "center"
    elif anchor == "end":
        cx, cy, align = x - width / 2, center_y, "right"
    else:
        cx, cy, align = x + width / 2, center_y, "left"
    st += style(align=align)
    return vertex(cell_id, content, st, (cx - width / 2, cy - height / 2, width, height))


def svg_cells(svg: str) -> tuple[list[str], float, float]:
    root = SafeET.fromstring(svg)
    width = float(root.get("width", "0"))
    height = float(root.get("height", "0"))
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for number, element in enumerate(root):
        kind = element.tag.split("}")[-1]
        cell_id = f"s{number}"
        dashed = element.get("stroke-dasharray")
        if kind == "defs":
            continue
        if kind == "rect":
            x, y = float(element.get("x", "0")), float(element.get("y", "0"))
            w, h = float(element.get("width", "0")), float(element.get("height", "0"))
            if (x, y, w, h) == (0.0, 0.0, width, height) and element.get("fill") == "#ffffff":
                continue  # fondo blanco del dibujo
            rx = float(element.get("rx", "0"))
            st = style(
                rounded=1 if rx else 0,
                absoluteArcSize=1 if rx else None,
                arcSize=2 * rx if rx else None,
                fillColor=color(element.get("fill")),
                strokeColor=color(element.get("stroke")),
                dashed=1 if dashed else None,
                dashPattern=dashed,
            )
            cells.append(vertex(cell_id, "", st, (x, y, w, h)))
        elif kind == "circle":
            cx, cy, r = (float(element.get(key, "0")) for key in ("cx", "cy", "r"))
            st = "ellipse;" + style(fillColor=color(element.get("fill")), strokeColor="none")
            cells.append(vertex(cell_id, "", st, (cx - r, cy - r, 2 * r, 2 * r)))
        elif kind == "polyline":
            points = [
                (float(a), float(b))
                for a, b in (pair.split(",") for pair in (element.get("points") or "").split())
            ]
            arrow = element.get("marker-end") is not None
            st = style(
                edgeStyle="none",
                html=0,
                strokeColor=color(element.get("stroke")),
                strokeWidth=1.3,
                endArrow="classic" if arrow else "none",
                endFill=1 if arrow else None,
                dashed=1 if dashed else None,
                dashPattern=dashed,
            )
            cells.append(free_line(cell_id, points, st))
        elif kind == "text":
            cells.append(text_cell(cell_id, element))
        else:
            raise SystemExit(f"elemento SVG sin conversión: {kind}")
    return cells, width, height


# ---------------------------------------------------------------- capturas del panel (imagen)


def png_cells(path: Path) -> tuple[list[str], float, float]:
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    encoded = base64.b64encode(data).decode("ascii")
    st = style(
        shape="image",
        verticalLabelPosition="bottom",
        verticalAlign="top",
        aspect="fixed",
        imageAspect=0,
        image=f"data:image/png,{encoded}",
    )
    cells = [
        '<mxCell id="0"/>',
        '<mxCell id="1" parent="0"/>',
        vertex("captura", "", st, (0, 0, width, height)),
    ]
    return cells, float(width), float(height)


# ---------------------------------------------------------------- principal


def write(name: str, cells: Sequence[str], width: float, height: float) -> None:
    target = FIGURAS / f"{name}.drawio"
    target.write_text(document(name, width, height, cells), encoding="utf-8", newline="\n")
    print(f"{target.name}: {len(cells) - 2} celdas", flush=True)


def main() -> int:
    spec_names: set[str] = set()
    for build in gt.SPECS.values():
        spec = build()
        spec_names.add(spec.name)
        write(spec.name, spec_cells(spec), spec.width * gt.CELL, spec.height * gt.CELL)
    for svg in sorted(FIGURAS.glob("*.svg")):
        if svg.stem in spec_names:
            continue
        cells, width, height = svg_cells(svg.read_text(encoding="utf-8"))
        write(svg.stem, cells, width, height)
    for png in sorted(FIGURAS.glob("*.png")):
        if (FIGURAS / f"{png.stem}.svg").exists():
            continue  # versión vectorial ya convertida
        cells, width, height = png_cells(png)
        write(png.stem, cells, width, height)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
