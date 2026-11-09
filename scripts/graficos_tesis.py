"""Figuras del punto 3 de la tesis (diseño de la solución), para la respuesta a los comentarios del asesor.

Genera, en una carpeta, las figuras nuevas del capítulo (esquemas conceptuales, secuencia de fases,
prototipos, mapa de historias y los cuatro niveles del modelo C4). Todo lo que sea un dato del
proyecto sale de los archivos y del código, no de números escritos aquí: el plan vigente se mide con
el verificador de ``semaforo.dominio``, la demanda de ejemplo sale de ESC-SINT-001 y las
dependencias entre paquetes, del código. Las figuras se dibujan en un lienzo estrecho y con letra
grande para que se lean a 15,5 cm de ancho, que es lo que mide el texto de la tesis.

Uso, desde la carpeta raíz del proyecto:

    .venv\\Scripts\\python.exe scripts\\graficos_tesis.py [--salida CARPETA] [figura ...]

Sin nombres de figura, genera todas. Escribe ``<nombre>.svg`` y ``<nombre>.png``.
"""

import argparse
import itertools
import json
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graficos import CELL, EDGE_BROWSER, Router, Scene, _corners
from graficos_arquitectura import package_links

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "documentacion" / "tesis-punto-3" / "figuras"
SANS = "Segoe UI, Arial, sans-serif"
INK = "#1f2933"
MUTED = "#52606d"
TITLE, BODY, TAG, SMALL = 16, 14, 12, 13
CHAR = 0.53  # ancho medio de un carácter, en veces el tamaño de la letra
STUB = 2
MAX_SCALE = 1.7
WAIT_S = 90

# relleno, borde, color del título, color del texto, línea del borde
KIND = {
    "persona": ("#2f4f66", "#2f4f66", "#ffffff", "#dce6ee", ""),
    "sistema": ("#dfe9f1", "#2f4f66", INK, "#3b4a57", ""),
    "contenedor": ("#edf3f8", "#396076", INK, "#3b4a57", ""),
    "componente": ("#f7f9fb", "#52606d", INK, "#3b4a57", ""),
    "externo": ("#e6e6e6", "#7b8794", INK, "#4a4a4a", ""),
    "dato": ("#f1f1f1", "#7b8794", INK, "#3b4a57", ""),
    "pendiente": ("#ffffff", "#7b8794", INK, "#52606d", "6 4"),
    "fuera": ("#ffffff", "#a8a29e", "#7a746f", "#7a746f", "6 4"),
    "regla": ("#fff7e0", "#a68a2b", INK, "#4a4330", ""),
    "grupo": ("none", "none", INK, INK, ""),
}


@dataclass
class N:
    """Una caja: título, texto, y su lugar en celdas de 9 px."""

    id: str
    title: str
    x: int
    y: int
    w: int
    body: str = ""
    tag: str = ""
    h: int = 0
    kind: str = "contenedor"


@dataclass(frozen=True)
class E:
    source: str
    target: str
    label: str = ""
    dashed: bool = False
    out: str = ""
    into: str = ""


@dataclass(frozen=True)
class G:
    label: str
    x: int
    y: int
    w: int
    h: int
    stroke: str = "#7b8794"
    dash: bool = True


@dataclass
class Spec:
    name: str
    width: int  # celdas
    height: int
    nodes: list[N]
    edges: list[E] = field(default_factory=list[E])
    groups: list[G] = field(default_factory=list[G])


def wrap(text: str, width_px: float, size: float) -> list[str]:
    per_line = max(8, int(width_px / (size * CHAR)))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words, current = paragraph.split(), ""
        for word in words:
            trial = f"{current} {word}".strip()
            if len(trial) <= per_line:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def layout(node: N) -> tuple[list[str], list[str], int]:
    if node.kind == "grupo":
        return [], [], node.h
    inner = node.w * CELL - 20
    head = wrap(node.title, inner, TITLE)
    body = wrap(node.body, inner, BODY) if node.body else []
    tag_h = 18 if node.tag else 0
    need = 14 + 21 * len(head) + tag_h + 18 * len(body) + 10
    cells = -(-need // CELL)
    return head, body, max(node.h, cells)


def draw_node(scene: Scene, node: N) -> None:
    if node.kind == "grupo":
        return
    fill, stroke, title_color, body_color, dash = KIND[node.kind]
    head, body, cells = layout(node)
    x, y, w, h = node.x * CELL, node.y * CELL, node.w * CELL, cells * CELL
    scene.rect(x, y, w, h, fill=fill, stroke=stroke, radius=7, dash=dash)
    total = 21 * len(head) + (18 if node.tag else 0) + 18 * len(body)
    top = y + (h - total) / 2 + 16
    for line in head:
        scene.text(x + w / 2, top, line, size=TITLE, bold=True, color=title_color, anchor="middle")
        top += 21
    if node.tag:
        scene.parts.append(
            f'<text x="{x + w / 2}" y="{top - 2}" font-family="{SANS}" font-size="{TAG}" '
            f'font-style="italic" fill="{body_color}" text-anchor="middle">[{node.tag}]</text>'
        )
        top += 18
    for line in body:
        scene.text(x + w / 2, top, line, size=BODY, color=body_color, anchor="middle")
        top += 18


def box_of(node: N) -> tuple[int, int, int, int]:
    _, _, cells = layout(node)
    return node.x, node.y, node.w, cells


def side(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> str:
    ax, ay, _aw, ah = a
    bx, by, _bw, bh = b
    if by >= ay + ah:
        return "down"
    if ay >= by + bh:
        return "up"
    return "right" if bx >= ax else "left"


OPPOSITE = {"down": "up", "up": "down", "right": "left", "left": "right"}
STEP = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}


def anchor(box: tuple[int, int, int, int], where: str, index: int, count: int) -> tuple[int, int]:
    x, y, w, h = box
    if where in {"down", "up"}:
        return (x + (w * (index + 1)) // (count + 1), y + h if where == "down" else y)
    return (x + w if where == "right" else x, y + (h * (index + 1)) // (count + 1))


def edge_routes(spec: Spec) -> list[list[tuple[int, int]]]:
    """Recorrido (en píxeles) de cada flecha, en el orden de spec.edges; lo comparten el SVG y el .drawio."""
    boxes = {n.id: box_of(n) for n in spec.nodes}
    router = Router(spec.width + 2, spec.height + 2)
    for node in spec.nodes:
        if node.kind == "grupo":
            continue
        x, y, w, h = boxes[node.id]
        router.block(x * CELL, y * CELL, w * CELL, h * CELL)
    uses: dict[tuple[str, str], list[tuple[int, int, str]]] = defaultdict(list)
    for index, edge in enumerate(spec.edges):
        a, b = boxes[edge.source], boxes[edge.target]
        out = edge.out or side(a, b)
        back = edge.into or OPPOSITE[out]
        uses[(edge.source, out)].append((b[0] + b[1], index, "s"))
        uses[(edge.target, back)].append((a[0] + a[1], index, "t"))
    anchors: dict[tuple[int, str], tuple[tuple[int, int], str]] = {}
    for (name, where), entries in uses.items():
        entries.sort()
        for position, (_, index, role) in enumerate(entries):
            anchors[(index, role)] = (anchor(boxes[name], where, position, len(entries)), where)
    routes: list[list[tuple[int, int]]] = []
    for index, edge in enumerate(spec.edges):
        (start, out), (end, back) = anchors[(index, "s")], anchors[(index, "t")]
        ox, oy = STEP[out]
        ix, iy = STEP[back]
        begin = (start[0] + ox * STUB, start[1] + oy * STUB)
        finish = (end[0] + ix * STUB, end[1] + iy * STUB)
        free = [(start[0] + ox * i, start[1] + oy * i) for i in range(STUB + 1)]
        free += [(end[0] + ix * i, end[1] + iy * i) for i in range(STUB + 1)]
        cells = router.route(begin, finish, free)
        if not cells:
            raise SystemExit(f"sin camino en {spec.name}: {edge.source} → {edge.target}")
        points = [(x * CELL, y * CELL) for x, y in _corners([start, *cells, end])]
        routes.append(points)
    return routes


def render(spec: Spec) -> tuple[str, int, int]:
    width, height = spec.width * CELL, spec.height * CELL
    scene = Scene(width, height)
    for group in spec.groups:
        scene.rect(
            group.x * CELL,
            group.y * CELL,
            group.w * CELL,
            group.h * CELL,
            fill="#fbfcfd",
            stroke=group.stroke,
            radius=10,
            dash="8 5" if group.dash else "",
        )
        scene.text(
            group.x * CELL + 12,
            group.y * CELL + 22,
            group.label,
            size=SMALL + 1,
            bold=True,
            color=group.stroke,
        )
    labels: list[tuple[int, int, str]] = []
    for edge, points in zip(spec.edges, edge_routes(spec), strict=True):
        scene.line(points, color="#52606d", dash=edge.dashed)
        if edge.label:
            best = max(
                itertools.pairwise(points),
                key=lambda p: abs(p[0][0] - p[1][0]) + abs(p[0][1] - p[1][1]),
            )
            labels.append(
                ((best[0][0] + best[1][0]) // 2, (best[0][1] + best[1][1]) // 2, edge.label)
            )
    for node in spec.nodes:
        draw_node(scene, node)
    for x, y, text in labels:
        lines = wrap(text, 190, SMALL)
        half = max(len(line) for line in lines) * SMALL * CHAR / 2 + 6
        scene.rect(x - half, y - 11, 2 * half, 16 * len(lines) + 4, fill="#ffffff")
        for i, line in enumerate(lines):
            scene.text(x, y + 2 + 16 * i, line, size=SMALL, color=MUTED, anchor="middle")
    return scene.svg(), width, height


# ---------------------------------------------------------------------------------------------
# Esquemas con cajas y flechas


def conceptual() -> Spec:
    nodes = [
        N(
            "obs",
            "Observaciones y condiciones del caso",
            3,
            6,
            40,
            "Aforos, geometría, fases y límites de los tiempos",
            kind="dato",
        ),
        N(
            "busq",
            "Búsqueda en SUMO",
            3,
            20,
            40,
            "Configuraciones factibles evaluadas por simulación",
            kind="contenedor",
        ),
        N(
            "ref",
            "Referencias (etiquetas)",
            3,
            33,
            40,
            "Mejor configuración factible de cada escenario",
            kind="dato",
        ),
        N(
            "entr",
            "Entrenamiento y selección",
            3,
            46,
            40,
            "Modelo supervisado y predictor sencillo, con datos de desarrollo",
            kind="contenedor",
        ),
        N(
            "dem",
            "Demanda del periodo",
            57,
            6,
            40,
            "Volumen por movimiento y composición vehicular",
            kind="dato",
        ),
        N(
            "est",
            "Estimador seleccionado",
            57,
            20,
            40,
            "Propone ciclo y verdes, en segundos",
            kind="sistema",
        ),
        N(
            "comp",
            "Comprobación de factibilidad",
            57,
            33,
            40,
            "Reglas del caso: límites, secuencia y ciclo",
            kind="regla",
        ),
        N("plan", "Plan admisible o rechazo", 57, 46, 40, "Con motivo registrado", kind="sistema"),
        N(
            "esc",
            "Escenarios reservados",
            3,
            72,
            40,
            "Prueba final, cerrada hasta su apertura",
            kind="dato",
        ),
        N(
            "alt",
            "Alternativas comparadas",
            57,
            72,
            40,
            "Modelo, plan vigente, Webster, búsqueda y predictor sencillo",
            kind="contenedor",
        ),
        N(
            "sim",
            "Simulación en SUMO",
            30,
            87,
            40,
            "Mismas condiciones para todas",
            kind="contenedor",
        ),
        N(
            "ind",
            "Indicadores",
            30,
            100,
            40,
            "Demora, colas, detenciones, factibilidad y costo",
            kind="sistema",
        ),
    ]
    edges = [
        E("obs", "busq"),
        E("busq", "ref"),
        E("ref", "entr"),
        E("entr", "est", "modelo", out="right", into="left"),
        E("dem", "est"),
        E("est", "comp"),
        E("comp", "plan"),
        E("plan", "alt", "planes admitidos"),
        E("esc", "sim"),
        E("alt", "sim"),
        E("sim", "ind"),
    ]
    groups = [
        G("Construcción del modelo", 1, 2, 44, 60, "#52606d"),
        G("Consulta (sin ejecutar SUMO)", 55, 2, 44, 60, "#2f4f66"),
        G("Evaluación fuera de línea", 1, 66, 98, 46, "#52606d"),
    ]
    return Spec("conceptual", 100, 114, nodes, edges, groups)


def caracterizacion() -> Spec:
    nodes = [
        N("v", "1. Video de la intersección", 3, 4, 40, "Periodos de estudio", kind="externo"),
        N(
            "c",
            "2. Conteos por movimiento y clase",
            3,
            17,
            40,
            "Extracción con una herramienta elegida por su desempeño en el caso",
            kind="contenedor",
        ),
        N(
            "m",
            "3. Muestra manual de control",
            3,
            31,
            40,
            "Contraste del error de conteo",
            kind="contenedor",
        ),
        N(
            "q",
            "4. Control de calidad",
            3,
            44,
            40,
            "Cobertura, faltantes, exclusiones justificadas",
            kind="regla",
        ),
        N(
            "a",
            "5. Aforos verificados",
            3,
            58,
            40,
            "Demanda en vehículos por hora, con su origen",
            kind="dato",
        ),
        N(
            "g",
            "A. Geometría y plan vigente",
            57,
            4,
            40,
            "Carriles, conexiones, movimientos y fases observadas",
            kind="externo",
        ),
        N(
            "f",
            "B. Ficha del caso",
            57,
            17,
            40,
            "Límites de los tiempos, secuencia fija y restricciones",
            kind="contenedor",
        ),
        N(
            "s",
            "C. Representación en SUMO",
            57,
            31,
            40,
            "Red, demanda y plan fijo, con versión",
            kind="contenedor",
        ),
        N(
            "k",
            "D. Calibración y validación",
            57,
            44,
            40,
            "Registros independientes; contraste en demanda y colas o recorridos",
            kind="regla",
        ),
        N(
            "r",
            "E. Representación comprobada",
            57,
            58,
            40,
            "Fijada antes de generar etiquetas",
            kind="dato",
        ),
        N(
            "o",
            "Escenarios y configuraciones de referencia",
            30,
            74,
            40,
            "Entrada de la búsqueda y del entrenamiento",
            kind="sistema",
        ),
    ]
    edges = [
        E("v", "c"),
        E("c", "m"),
        E("m", "q"),
        E("q", "a"),
        E("g", "f"),
        E("f", "s"),
        E("s", "k"),
        E("k", "r"),
        E("a", "s", "demanda", out="right", into="left"),
        E("a", "o"),
        E("r", "o"),
    ]
    groups = [
        G("Preparación de datos de campo", 1, 1, 44, 69, "#52606d"),
        G("Representación de la intersección", 55, 1, 44, 69, "#52606d"),
    ]
    return Spec("caracterizacion", 100, 88, nodes, edges, groups)


def busqueda() -> Spec:
    nodes = [
        N("e", "Escenario de desarrollo", 3, 3, 46, "Demanda, composición y semilla", kind="dato"),
        N(
            "g",
            "Generar candidatos",
            3,
            15,
            46,
            "Grilla de ticks o muestreo dentro de los límites del caso, sin repetidos",
            kind="contenedor",
        ),
        N(
            "f",
            "Filtrar por factibilidad",
            3,
            29,
            46,
            "Reglas del caso: límites, secuencia, ciclo",
            kind="regla",
        ),
        N(
            "s",
            "Simular cada candidato",
            3,
            42,
            46,
            "SUMO, con las semillas de búsqueda y el presupuesto fijado",
            kind="contenedor",
        ),
        N(
            "p",
            "Puntuar",
            3,
            56,
            46,
            "Demora media; desempate por cola, detenciones y orden fijo",
            kind="contenedor",
        ),
        N(
            "r",
            "Reevaluar finalistas",
            3,
            69,
            46,
            "Semillas reservadas, para no elegir una suerte favorable",
            kind="contenedor",
        ),
        N(
            "l",
            "Etiqueta",
            3,
            82,
            46,
            "Mejor configuración factible encontrada; o «sin referencia» con motivo",
            kind="sistema",
        ),
        N(
            "reg",
            "Registro de la búsqueda",
            58,
            29,
            38,
            "Espacio, presupuesto, regla de parada, semillas y todos los candidatos, también los descartados",
            kind="dato",
        ),
        N(
            "cls",
            "Clasificación de cada ejecución",
            58,
            52,
            38,
            "Limpia, con incidente aislado o con colapso (teletransportes o choques). El protocolo fija cuántas se toleran",
            kind="regla",
        ),
    ]
    edges = [
        E("e", "g"),
        E("g", "f"),
        E("f", "s"),
        E("s", "p"),
        E("p", "r"),
        E("r", "l"),
        E("f", "reg", dashed=True, out="right", into="left"),
        E("s", "cls", dashed=True, out="right", into="left"),
    ]
    return Spec("busqueda", 100, 96, nodes, edges)


def particiones() -> Spec:
    nodes = [
        N(
            "e",
            "Escenarios generados",
            30,
            3,
            40,
            "Con su origen: sintético o de campo",
            kind="dato",
        ),
        N(
            "a",
            "Agrupar por día o patrón de demanda",
            30,
            15,
            40,
            "Las repeticiones con otras semillas quedan en el mismo grupo",
            kind="regla",
        ),
        N(
            "t",
            "Entrenamiento",
            3,
            31,
            28,
            "Ajusta el modelo y sus transformaciones",
            kind="contenedor",
        ),
        N("v", "Selección", 36, 31, 28, "Elige modelo e hiperparámetros", kind="contenedor"),
        N("f", "Prueba final", 69, 31, 28, "Reservada: cerrada hasta su apertura", kind="sistema"),
        N("h1", "Protocolo congelado", 3, 54, 19, "", h=9, kind="componente"),
        N("h2", "Partición congelada", 28, 54, 19, "", h=9, kind="componente"),
        N("h3", "Modelo congelado", 53, 54, 19, "", h=9, kind="componente"),
        N("h4", "Apertura de la prueba", 78, 54, 19, "", h=9, kind="sistema"),
        N(
            "b",
            "La base de datos aplica la regla",
            3,
            68,
            94,
            "Sin el hito de apertura, ninguna consulta del panel ni de desarrollo devuelve datos de prueba, y el orden de los hitos lo valida la propia base. Las semillas de búsqueda, de finalistas y finales son conjuntos disjuntos.",
            kind="regla",
        ),
    ]
    edges = [
        E("e", "a"),
        E("a", "t"),
        E("a", "v"),
        E("a", "f"),
        E("h1", "h2"),
        E("h2", "h3"),
        E("h3", "h4"),
    ]
    groups = [G("Hitos del procedimiento, en orden", 1, 49, 98, 17, "#52606d")]
    return Spec("particiones", 100, 85, nodes, edges, groups)


# ---------------------------------------------------------------------------------------------
# Modelo C4


def c4_n1() -> Spec:
    nodes = [
        N(
            "analista",
            "Analista del experimento",
            3,
            4,
            30,
            "Prepara datos, entrena, consulta y evalúa",
            tag="Persona",
            kind="persona",
        ),
        N(
            "asesor",
            "Asesor y jurado",
            67,
            4,
            30,
            "Revisan los resultados y su evidencia",
            tag="Persona",
            kind="persona",
        ),
        N(
            "sistema",
            "Estimador de tiempos semafóricos",
            25,
            32,
            50,
            "Propone ciclo y verdes de una intersección, comprueba su factibilidad y los compara con las referencias",
            tag="Sistema de software: aplicación local",
            kind="sistema",
        ),
        N(
            "sumo",
            "SUMO",
            3,
            62,
            30,
            "Microsimulación de tránsito",
            tag="Sistema externo",
            kind="externo",
        ),
        N(
            "extr",
            "Herramienta de extracción de aforos",
            36,
            62,
            30,
            "Obtiene conteos de los videos",
            tag="Sistema externo",
            kind="externo",
        ),
        N(
            "git",
            "Control de versiones (GitHub)",
            69,
            62,
            28,
            "Guarda el código y las huellas de lo publicado",
            tag="Sistema externo",
            kind="externo",
        ),
        N(
            "video",
            "Videos de campo",
            36,
            82,
            30,
            "Material de la intersección; permanece fuera del repositorio",
            tag="Fuente de datos",
            kind="externo",
        ),
        N(
            "muni",
            "Plataformas municipales y semáforos físicos",
            3,
            82,
            30,
            "Sin conexión ni actuación",
            tag="Fuera de alcance",
            kind="fuera",
        ),
    ]
    edges = [
        E("analista", "sistema", "Usa"),
        E("asesor", "sistema", "Revisa el panel"),
        E("sistema", "sumo", "Ejecuta y lee sus salidas"),
        E("extr", "sistema", "Aforos derivados"),
        E("sistema", "git", "Publica, a pedido"),
        E("video", "extr"),
    ]
    return Spec("c4_n1", 100, 100, nodes, edges)


def c4_n2() -> Spec:
    nodes = [
        N("analista", "Analista del experimento", 3, 3, 30, "", tag="Persona", kind="persona"),
        N("asesor", "Asesor y jurado", 68, 3, 29, "", tag="Persona", kind="persona"),
        N(
            "prog",
            "Programa semaforo",
            3,
            22,
            30,
            "Comandos para preparar, simular, cargar, verificar y generar el panel",
            tag="Contenedor: Python 3.12, línea de comandos",
            kind="contenedor",
        ),
        N(
            "panel",
            "Panel de resultados",
            68,
            22,
            29,
            "Diez páginas con el estado y la evidencia; texto escapado, sin red",
            tag="Contenedor: HTML estático",
            kind="contenedor",
        ),
        N(
            "arch",
            "Archivos con huella",
            38,
            50,
            26,
            "El original: manifiesto y SHA-256 por carpeta; nunca se sobrescriben",
            tag="Almacén: CSV, JSON y XML",
            kind="dato",
        ),
        N(
            "bd",
            "Base de consulta",
            68,
            50,
            29,
            "Copia verificada: solo agregar; prueba final cegada; se regenera desde los archivos",
            tag="Base de datos: PostgreSQL 17.9",
            kind="dato",
        ),
        N(
            "sumo",
            "SUMO",
            3,
            84,
            30,
            "Un proceso por corrida, sin shell",
            tag="Sistema externo",
            kind="externo",
        ),
        N(
            "git",
            "Control de versiones",
            38,
            84,
            26,
            "Código y huellas",
            tag="Sistema externo",
            kind="externo",
        ),
        N(
            "bk",
            "Respaldos",
            68,
            84,
            29,
            "Copia de la base con su ficha",
            tag="Almacén: pg_dump",
            kind="dato",
        ),
    ]
    edges = [
        E("analista", "prog", "Comandos"),
        E("asesor", "panel", "Abre"),
        E("prog", "panel", "Genera", out="right", into="left"),
        E("prog", "arch", "Publica y lee"),
        E("prog", "bd", "Carga verificada"),
        E("prog", "sumo", "Ejecuta"),
        E("prog", "git", "Huellas", True),
        E("bd", "bk", "Respalda"),
    ]
    groups = [G("Estimador de tiempos semafóricos (una laptop)", 1, 17, 98, 64, "#2f4f66", False)]
    return Spec("c4_n2", 100, 100, nodes, edges, groups)


def c4_n3() -> Spec:
    nodes = [
        N(
            "cli",
            "cli",
            3,
            4,
            30,
            "Traduce comandos y códigos de salida",
            tag="Componente",
            kind="componente",
        ),
        N(
            "app",
            "app",
            38,
            4,
            30,
            "Servicios que combinan componentes; informes y panel",
            tag="Componente",
            kind="componente",
        ),
        N("cap", "", 3, 22, 94, h=36, kind="grupo"),
        N(
            "caso",
            "caso",
            6,
            27,
            28,
            "Recepción y validación del caso",
            tag="Componente",
            kind="componente",
        ),
        N(
            "datos",
            "datos",
            37,
            27,
            28,
            "Aforos, calidad y escenarios",
            tag="Componente",
            kind="componente",
        ),
        N(
            "ref",
            "referencias",
            68,
            27,
            28,
            "Búsqueda y comparadores",
            tag="Componente",
            kind="componente",
        ),
        N(
            "apr",
            "aprendizaje",
            6,
            42,
            28,
            "Particiones y, luego, entrenamiento",
            tag="Componente",
            kind="componente",
        ),
        N(
            "eva",
            "evaluacion",
            37,
            42,
            28,
            "Cohorte y métricas",
            tag="Componente",
            kind="componente",
        ),
        N(
            "est",
            "estimacion",
            68,
            42,
            28,
            "Consulta al modelo (por construir)",
            tag="Componente",
            kind="pendiente",
        ),
        N("sop", "", 3, 62, 94, h=22, kind="grupo"),
        N(
            "sim",
            "simulacion",
            5,
            67,
            21,
            "Prepara y ejecuta SUMO",
            tag="Componente",
            kind="componente",
        ),
        N(
            "dom",
            "dominio",
            28,
            67,
            21,
            "Reglas puras y contratos",
            tag="Componente",
            kind="sistema",
        ),
        N(
            "bd",
            "bd",
            51,
            67,
            21,
            "Esquema, carga verificada y panel",
            tag="Componente",
            kind="componente",
        ),
        N(
            "tra",
            "trazabilidad",
            74,
            67,
            21,
            "Huellas y publicación atómica",
            tag="Componente",
            kind="componente",
        ),
        N("xs", "SUMO", 3, 91, 26, "", tag="Sistema externo", kind="externo"),
        N("xp", "PostgreSQL", 40, 91, 26, "", tag="Base de datos", kind="externo"),
        N("xa", "Archivos con huella", 71, 91, 26, "", tag="Almacén", kind="externo"),
    ]
    edges = [
        E("cli", "app", out="right", into="left"),
        E("app", "cap", "usa"),
        E("cap", "sop", "usan"),
        E("sim", "xs", "Ejecuta"),
        E("bd", "xp", "SQL"),
        E("tra", "xa", "Publica"),
    ]
    groups = [
        G("Programa semaforo", 1, 1, 98, 85, "#2f4f66", False),
        G("Capacidades", 3, 22, 94, 36, "#52606d"),
        G("Apoyo común", 3, 62, 94, 22, "#52606d"),
    ]
    return Spec("c4_n3", 100, 104, nodes, edges, groups)


def c4_n4_factibilidad() -> Spec:
    nodes = [
        N(
            "case",
            "dominio/case.py",
            3,
            3,
            21,
            "Case: movimientos, tramos, grupos de verde, ciclo y tick",
            kind="componente",
        ),
        N(
            "timing",
            "dominio/timing.py",
            27,
            3,
            21,
            "reconstruct → Timing: ciclo, verdes y ventanas",
            kind="componente",
        ),
        N(
            "plan",
            "dominio/case_plan.py",
            51,
            3,
            21,
            "plan_issues: límites, ciclo y verde por grupo",
            kind="componente",
        ),
        N(
            "order",
            "dominio/adjust_order.py",
            75,
            3,
            22,
            "AdjustOrder: orden de ajuste; es dato del caso",
            kind="componente",
        ),
        N(
            "prep",
            "prepare(case, orden) → PreparedCase",
            3,
            26,
            94,
            "slots y variables, orden de ajuste, versión de las reglas (huella SHA-256)",
            tag="dominio/feasibility.py",
            kind="sistema",
        ),
        N(
            "chk",
            "check_plan(prepared, duraciones) → PlanCheck",
            3,
            44,
            41,
            "Reglas satisfechas, violadas u omitidas; feasible; timing",
            tag="Función",
            kind="sistema",
        ),
        N(
            "cor",
            "correct(prepared, duraciones, caso) → Correction",
            56,
            44,
            41,
            "Estado: accepted, corrected, rejected o invalid_input; original, final y cambios",
            tag="Función",
            kind="sistema",
        ),
        N(
            "cov",
            "summarize(correcciones) → Coverage",
            27,
            66,
            46,
            "Factibilidad antes y después, y cobertura, con sus denominadores",
            tag="Función",
            kind="sistema",
        ),
    ]
    edges = [
        E("case", "prep"),
        E("timing", "prep"),
        E("plan", "prep"),
        E("order", "prep"),
        E("prep", "chk"),
        E("prep", "cor"),
        E("cor", "cov"),
        E("chk", "cor", "reglas", out="right", into="left"),
    ]
    return Spec("c4_n4_factibilidad", 100, 84, nodes, edges)


def c4_n4_carga() -> Spec:
    nodes = [
        N(
            "cmd",
            "app/bd_commands.py",
            3,
            3,
            44,
            "bd cargar, verificar, conciliar y regenerar; traduce el resultado a un código de salida",
            kind="componente",
        ),
        N(
            "op",
            "LoadOptions",
            52,
            3,
            45,
            "preliminary, loose_runs, without_metrics, kinds, repository, content",
            tag="Clase",
            kind="componente",
        ),
        N(
            "motor",
            "load_workspace(carpeta, opciones) → LoadReport",
            3,
            19,
            94,
            "carga_id, estado, conteos, filas por tabla y un UnitOutcome por unidad (clave, tipo, estado, filas)",
            tag="bd/carga/motor.py",
            kind="sistema",
        ),
        N(
            "fu",
            "fuentes.py",
            3,
            37,
            28,
            "Descubre las unidades publicadas y sus archivos",
            kind="componente",
        ),
        N(
            "tr",
            "trazabilidad/verify",
            36,
            37,
            28,
            "Verifica huellas y manifiesto de cada carpeta",
            kind="componente",
        ),
        N(
            "ld",
            "caso, corridas, planes, referencias, hitos, modelo, decisiones, crudo",
            68,
            37,
            29,
            "Un cargador por tipo de archivo",
            kind="componente",
        ),
        N(
            "ins",
            "insercion.py",
            3,
            58,
            45,
            "Una transacción por unidad: todo o nada; claves naturales sin duplicar",
            kind="componente",
        ),
        N(
            "cf",
            "control.conflictos",
            52,
            58,
            45,
            "La misma clave con otra huella se rechaza y se registra",
            tag="Tabla",
            kind="regla",
        ),
        N(
            "ver",
            "verificacion.py y conciliacion.py",
            3,
            76,
            94,
            "content_hash, comparación con la referencia de git, cobertura, conteos y demora recalculada",
            tag="Lectura en una sola foto, con candado compartido",
            kind="sistema",
        ),
    ]
    edges = [
        E("cmd", "motor"),
        E("op", "motor"),
        E("motor", "fu"),
        E("motor", "tr"),
        E("motor", "ld"),
        E("fu", "ins"),
        E("ld", "cf", "si difiere"),
        E("ins", "ver", "lo cargado"),
    ]
    return Spec("c4_n4_carga", 100, 96, nodes, edges)


def despliegue() -> Spec:
    nodes = [
        N(
            "py",
            "Python 3.12",
            4,
            8,
            24,
            "Entorno .venv; versiones exactas en uv.lock",
            tag="Entorno de ejecución",
            kind="contenedor",
        ),
        N(
            "sumo",
            "SUMO 1.27.1",
            38,
            8,
            24,
            "Un proceso por corrida",
            tag="Programa",
            kind="contenedor",
        ),
        N("pg", "PostgreSQL 17.9", 72, 8, 24, "Servicio local", tag="Servicio", kind="contenedor"),
        N(
            "datos",
            "datos/",
            4,
            30,
            24,
            "Archivos con huella; unos 3 GB",
            tag="Carpeta del proyecto",
            kind="dato",
        ),
        N(
            "pgd",
            "D:\\pgdata\\semaforo",
            38,
            30,
            24,
            "Espacio de tablas: 149 MB",
            tag="Carpeta",
            kind="dato",
        ),
        N(
            "rsp",
            "D:\\respaldos\\semaforo",
            72,
            30,
            24,
            "pg_dump con su ficha y huella",
            tag="Carpeta",
            kind="dato",
        ),
        N(
            "repo",
            "Repositorio git local",
            4,
            50,
            24,
            "Código, actas y huellas de lo publicado",
            tag="Carpeta del proyecto",
            kind="dato",
        ),
        N(
            "nav",
            "Navegador",
            38,
            50,
            24,
            "Abre el panel; sin internet",
            tag="Programa",
            kind="contenedor",
        ),
        N(
            "gh",
            "GitHub público",
            4,
            72,
            24,
            "Sin datos ni contraseñas",
            tag="Servicio externo",
            kind="externo",
        ),
        N(
            "gp",
            "GitHub privado",
            38,
            72,
            24,
            "Escenario de SUMO",
            tag="Servicio externo",
            kind="externo",
        ),
        N(
            "nube",
            "Otra máquina o nube",
            72,
            72,
            24,
            "Sin requisito hoy; cada corrida registra dónde se ejecutó",
            tag="Posible, sin construir",
            kind="pendiente",
        ),
    ]
    edges = [
        E("py", "sumo", "Ejecuta"),
        E("py", "pg", "psycopg"),
        E("py", "datos", "Lee y publica"),
        E("pg", "pgd"),
        E("pg", "rsp", "pg_dump"),
        E("datos", "repo", "huellas"),
        E("datos", "nav", "Panel", out="right", into="left"),
        E("repo", "gh", "push, a pedido", True),
        E("repo", "gp", "", True),
    ]
    groups = [
        G(
            "Laptop del investigador: Windows 11, 16 hilos y 16 GB de RAM",
            1,
            2,
            98,
            66,
            "#2f4f66",
            False,
        )
    ]
    return Spec("despliegue", 100, 92, nodes, edges, groups)


# ---------------------------------------------------------------------------------------------
# Figuras dibujadas a medida


def text_block(
    scene: Scene, x: float, y: float, text: str, width: float, size: int, **style: object
) -> float:
    lines = wrap(text, width, size)
    for i, line in enumerate(lines):
        scene.text(x, y + i * (size + 5), line, size=size, **style)  # type: ignore[arg-type]
    return y + len(lines) * (size + 5)


def secuencia_fases() -> tuple[str, int, int]:
    from semaforo.caso.case_validation import read_case  # noqa: PLC0415
    from semaforo.dominio.feasibility import check_plan, prepare  # noqa: PLC0415

    case = read_case(ROOT / "datos" / "casos" / "caso-001" / "case.json")
    plan = {"t1": 82, "t2": 5, "t3": 45, "t4": 5, "t5": 45, "t6": 5, "t7": 10, "t8": 5, "t9": 4}
    check = check_plan(prepare(case), plan)
    if not check.feasible or check.timing is None:
        raise SystemExit("el plan vigente de ejemplo ya no es factible: revisar la figura")
    timing = check.timing
    fixed = {s.id for s in case.slots if s.kind == "fixed"}
    names = {
        "jp_este_oeste": "Javier Prado, este → oeste",
        "jp_oeste_este_recto": "Javier Prado, oeste → este (recto)",
        "jp_oeste_este_flecha": "Javier Prado, oeste → este (flecha)",
        "frutales_sur": "Los Frutales, sur → norte",
        "frutales_norte": "Los Frutales, norte → sur",
    }
    width, left, right = 900, 250, 870
    unit = (right - left) / timing.cycle_s
    height = 470
    scene = Scene(width, height)
    scene.text(
        left,
        30,
        f"Ciclo = {timing.cycle_s:.0f} s: la suma de los nueve tramos, cada uno contado una sola vez",
        size=15,
        bold=True,
    )
    scene.text(left, 58, "Tramos de la secuencia fija", size=SMALL, color=MUTED)
    y0 = 70
    for slot in timing.slots:
        x = left + slot.start_s * unit
        w = (slot.end_s - slot.start_s) * unit
        is_fixed = slot.slot_id in fixed
        scene.rect(x, y0, w, 36, fill="#d5d9de" if is_fixed else "#c7dbe9", stroke="#52606d")
        scene.text(
            x + w / 2,
            y0 + 24,
            slot.slot_id if w < 34 else f"{slot.slot_id}",
            size=12 if w < 34 else 14,
            bold=True,
            anchor="middle",
        )
        if not is_fixed:
            scene.text(
                x + w / 2,
                y0 + 56,
                f"{slot.end_s - slot.start_s:.0f} s",
                size=13,
                anchor="middle",
                color=INK,
            )
    scene.text(8, y0 + 24, "Variables (azul)", size=SMALL, color="#2f4f66", bold=True)
    scene.text(8, y0 + 44, "Fijos (gris): ámbar y todo rojo", size=12, color=MUTED)
    scene.text(left, y0 + 92, "Verde de cada grupo", size=SMALL, color=MUTED)
    y = y0 + 106
    for group in timing.groups:
        scene.text(8, y + 20, names[group.group_id], size=13, color=INK)
        for window in group.windows:
            x = left + window.start_s * unit
            w = window.duration_s * unit
            scene.rect(x, y, w, 26, fill="#9cc0d8", stroke="#2f4f66")
            scene.text(
                x + w / 2,
                y + 19,
                f"{'+'.join(window.slot_ids)} = {group.total_s:.0f} s",
                size=13,
                bold=True,
                anchor="middle",
            )
        y += 40
    scene.line([(left, y + 8), (right, y + 8)], color="#52606d", arrow=True)
    scene.text(left, y + 28, "0 s", size=12, color=MUTED)
    scene.text(right, y + 28, f"{timing.cycle_s:.0f} s", size=12, color=MUTED, anchor="end")
    text_block(
        scene,
        8,
        y + 56,
        "En t1 hay dos grupos con verde al mismo tiempo; en t5, también. Por eso el ciclo no es la suma de los verdes de los grupos: se reconstruye sobre la secuencia completa y cada tramo se cuenta una vez.",
        width - 16,
        14,
        color=INK,
    )
    return scene.svg(), width, y + 130


def hoja_de_datos() -> tuple[str, int, int]:
    e = json.loads(
        (ROOT / "datos" / "escenarios" / "caso-001" / "ESC-SINT-001.json").read_text("utf-8")
    )
    demand = e["request"]["demand"][:5]
    width = 900
    scene = Scene(width, 520)
    col = [90, 150, 130, 130, 130, 110]

    def sheet(
        y: int, title: str, headers: list[str], rows: list[list[str]], widths: list[int], note: str
    ) -> int:
        scene.text(10, y + 18, title, size=15, bold=True)
        top = y + 30
        x = 10
        scene.rect(10, top, 26, 26, fill="#e6e6e6", stroke="#9aa5b1")
        for i, w in enumerate(widths):
            scene.rect(x + 26, top, w, 26, fill="#e6e6e6", stroke="#9aa5b1")
            scene.text(x + 26 + w / 2, top + 18, chr(65 + i), size=13, color=MUTED, anchor="middle")
            x += w
        total = sum(widths)
        for r_index, row in enumerate([headers, *rows]):
            ty = top + 26 + r_index * 28
            scene.rect(10, ty, 26, 28, fill="#e6e6e6", stroke="#9aa5b1")
            scene.text(23, ty + 19, str(r_index + 1), size=12, color=MUTED, anchor="middle")
            x = 10 + 26
            for _c_index, (cell, w) in enumerate(zip(row, widths, strict=True)):
                head = r_index == 0
                scene.rect(x, ty, w, 28, fill="#dfe9f1" if head else "#ffffff", stroke="#c3cad2")
                scene.text(x + 8, ty + 19, cell, size=13, bold=head, color=INK)
                x += w
        scene.text(10, top + 26 + (len(rows) + 1) * 28 + 22, note, size=12, color=MUTED)
        return top + 26 + (len(rows) + 1) * 28 + 34 + (total * 0)

    rows = [
        [
            d["movement_id"],
            str(d["flow_vph"]),
            *[f"{d['composition'][c]:.2f}" for c in ("passenger", "motorcycle", "truck", "bus")],
        ]
        for d in demand
    ]
    rows.append(["…", "…", "…", "…", "…", "…"])
    y = sheet(
        0,
        "Hoja «Demanda»: entrada del estimador (escenario sintético ESC-SINT-001)",
        ["movimiento", "flujo (veh/h)", "autos", "motos", "camiones", "buses"],
        rows,
        col,
        "Una fila por movimiento (23 en el caso). Las proporciones por clase suman 1; con flujo 0 la composición queda vacía.",
    )
    out_w = [180, 70, 70, 70, 70, 90, 120]
    y = sheet(
        y + 8,
        "Hoja «Propuesta»: salida de la consulta",
        ["origen", "t1 (s)", "t3 (s)", "t5 (s)", "t7 (s)", "ciclo (s)", "estado"],
        [
            ["Plan vigente (referencia)", "82", "45", "45", "10", "206", "factible"],
            ["Estimador (por entrenar)", "—", "—", "—", "—", "—", "—"],
        ],
        out_w,
        "Los tramos fijos (ámbar y todo rojo) salen del caso. El plan vigente se comprobó con el verificador del proyecto.",
    )
    return scene.svg(), width, y + 4


def mapa_historias() -> tuple[str, int, int]:
    cols = [
        ("Caso y datos", "HU01–HU03"),
        ("Representación", "HU04–HU05"),
        ("Modelo", "HU06–HU09"),
        ("Consulta", "HU10–HU11"),
        ("Evaluación", "HU12–HU13"),
        ("Evidencia y panel", "HU14–HU15"),
    ]
    rows = [
        (
            "ENT1",
            [
                "Datos sintéticos verificados",
                "Ejecución sintética",
                "Particiones y búsqueda\nEntrenamiento preliminar",
                "Tiempos y restricciones",
                "Pruebas sintéticas independientes",
                "Manifiestos y base de consulta",
            ],
        ),
        (
            "ENT2",
            [
                "Caso y aforos verificados",
                "Calibración y validación independiente",
                "—",
                "—",
                "—",
                "Aforos y calibración en la base",
            ],
        ),
        (
            "ENT3",
            [
                "Esquema de datos fijado",
                "Representación fijada",
                "Escenarios y particiones\nBúsqueda y entrenamiento",
                "Estimación y restricciones",
                "—",
                "Etiquetas y modelo en la base",
            ],
        ),
        (
            "ENT4",
            [
                "—",
                "Ejecuciones de prueba",
                "Modelo seleccionado",
                "Planes de prueba",
                "Comparación e indicadores",
                "Evaluación final y panel",
            ],
        ),
    ]
    width = 900
    first, cw = 60, 128
    scene = Scene(width, 640)
    x0 = 8
    scene.rect(x0, 8, first, 78, fill="#f3f3f3", stroke="#52606d")
    scene.text(x0 + first / 2, 52, "Entrega", size=14, bold=True, anchor="middle")
    for i, (name, hu) in enumerate(cols):
        x = x0 + first + 6 + i * (cw + 2)
        scene.rect(x, 8, cw, 78, fill="#dfe9f1" if i < 5 else "#fff7e0", stroke="#52606d")
        scene.text(x + cw / 2, 40, name, size=14, bold=True, anchor="middle")
        scene.text(x + cw / 2, 64, hu, size=13, anchor="middle", color=MUTED)
    y = 94
    for label, cells in rows:
        scene.rect(x0, y, first, 108, fill="#f3f3f3", stroke="#52606d")
        scene.text(x0 + first / 2, y + 60, label, size=14, bold=True, anchor="middle")
        for i, cell in enumerate(cells):
            x = x0 + first + 6 + i * (cw + 2)
            scene.rect(
                x, y, cw, 108, fill="#fafafa" if cell != "—" else "#f1f1f1", stroke="#9aa5b1"
            )
            lines = [ln for part in cell.split("\n") for ln in wrap(part, cw - 12, 13)]
            top = y + 54 - (len(lines) * 17) / 2 + 12
            for line in lines:
                scene.text(
                    x + cw / 2,
                    top,
                    line,
                    size=13,
                    anchor="middle",
                    color=INK if cell != "—" else MUTED,
                )
                top += 17
        y += 112
    text_block(
        scene,
        8,
        y + 22,
        "HU14 y HU15 conservan los registros y la evidencia de todas las entregas. Las funciones incorporadas se reutilizan en las etapas posteriores.",
        width - 16,
        14,
        color=INK,
    )
    return scene.svg(), width, y + 76


def product_canvas() -> tuple[str, int, int]:
    width = 900
    pairs = [
        (
            "Visión",
            "Un prototipo local que propone el ciclo y los verdes de una intersección de Lima a partir de su demanda, comprueba que sean admisibles y permite contrastarlos con el plan vigente, Webster, una búsqueda de referencia y un predictor sencillo.",
        ),
        None,
        (
            "Usuarios",
            "Analista del experimento (perfil único), con el equipo de investigación como Product Owner y Scrum Master. Asesor y jurado revisan la evidencia.",
        ),
        (
            "Problema y necesidad",
            "Evaluar tiempos ante cambios de demanda exige simular muchas configuraciones; el costo y la falta de repetibilidad lo hacen difícil de contrastar.",
        ),
        None,
        (
            "Solución: funciones clave",
            "Comprobar datos · simular en SUMO · buscar referencias · entrenar y seleccionar · consultar tiempos · comprobar factibilidad · evaluar · consultar la evidencia en una base y un panel.",
        ),
        (
            "Valor para la investigación",
            "Estimar tiempos sin simular en cada consulta; comparar bajo condiciones equivalentes; conservar los resultados desfavorables; trazar cada cifra hasta su archivo y su huella.",
        ),
        None,
        (
            "Entradas y productos",
            "Entradas: aforos por movimiento y clase, caso y restricciones. Productos: conjunto etiquetado, paquete del estimador, planes comprobados, registros y panel.",
        ),
        (
            "Alcance y restricciones",
            "Una intersección, fases fijas y ejecución local, evaluada por microsimulación. Fuera de alcance: control en vía, plataformas municipales, pronóstico de demanda, aprendizaje por refuerzo y modelos de lenguaje.",
        ),
        None,
        (
            "Métricas de éxito",
            "Indicadores I1 a I8: calidad de datos, correspondencia de la simulación, etiquetas, factibilidad y cobertura, error de tiempos, desempeño vehicular, costo de cálculo y reproducibilidad.",
        ),
        (
            "Riesgos y supuestos",
            "Cobertura de los datos de campo; límites de tiempos por validar con un especialista; saturación de la demanda; el resultado puede ser desfavorable y se informa igual.",
        ),
        None,
        (
            "Recursos",
            "Dos personas, una laptop (16 GB de RAM), SUMO, Python y PostgreSQL como software libre. Sin infraestructura en la nube.",
        ),
    ]
    rows: list[list[tuple[str, str]]] = [[]]
    for item in pairs:
        if item is None:
            rows.append([])
        else:
            rows[-1].append(item)
    scene = Scene(width, 1200)
    y = 8
    for row in rows:
        w = 884 if len(row) == 1 else 436
        heights = [60 + 19 * len(wrap(body, w - 28, 14)) for _, body in row]
        height = max(heights)
        for i, (title, body) in enumerate(row):
            x = 8 + i * 448
            scene.rect(
                x,
                y,
                w,
                height,
                fill="#dfe9f1" if title == "Visión" else "#f7f9fb",
                stroke="#52606d",
                radius=6,
            )
            scene.text(x + 14, y + 26, title, size=16, bold=True, color="#2f4f66")
            text_block(scene, x + 14, y + 52, body, w - 28, 14, color=INK)
        y += height + 8
    return scene.svg(), width, y


def matriz_dependencias() -> tuple[str, int, int]:
    from importlib.util import module_from_spec, spec_from_file_location  # noqa: PLC0415

    links = package_links(ROOT / "src" / "semaforo")
    spec = spec_from_file_location("reglas", ROOT / "tests" / "unit" / "test_arquitectura.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    forbidden = module.FORBIDDEN
    names = [
        "cli",
        "app",
        "bd",
        "referencias",
        "aprendizaje",
        "estimacion",
        "evaluacion",
        "datos",
        "simulacion",
        "caso",
        "trazabilidad",
        "dominio",
    ]
    assert set(names) == set(links)
    cell, label, head = 44, 150, 120
    width = label + cell * len(names) + 20
    scene = Scene(width, head + cell * len(names) + 70)
    for i, name in enumerate(names):
        x = label + i * cell + cell / 2
        scene.parts.append(
            f'<text x="{x}" y="{head - 8}" font-family="Consolas, monospace" font-size="14" font-weight="700" '
            f'fill="{INK}" transform="rotate(-55 {x} {head - 8})">{name}</text>'
        )
    for r, name in enumerate(names):
        y = head + r * cell
        scene.text(8, y + 28, name, size=14, bold=True, font="Consolas, monospace")
        for c, other in enumerate(names):
            x = label + c * cell
            bad = other in forbidden.get(name, frozenset())
            fill = "#e8eaed" if other == name else "#f7d9d4" if bad else "#ffffff"
            scene.rect(x, y, cell, cell, fill=fill, stroke="#c3cad2")
            if other in links.get(name, set()):
                scene.parts.append(
                    f'<circle cx="{x + cell / 2}" cy="{y + cell / 2}" r="10" fill="#2f4f66"/>'
                )
    total = sum(len(v) for v in links.values())
    y = head + cell * len(names) + 26
    scene.text(
        8,
        y,
        f"Círculo: el componente de la fila importa al de la columna ({total} dependencias, medidas en el código).",
        size=13,
        color=MUTED,
    )
    scene.text(
        8,
        y + 20,
        "Rosa: dependencia prohibida por la decisión de arquitectura ADR01.",
        size=13,
        color=MUTED,
    )
    return scene.svg(), width, y + 36


def capturas_panel(target_dir: Path, browser: Path) -> list[str]:
    latest = sorted((ROOT / "datos" / "reportes" / "panel").iterdir())[-1] / "index.html"
    produced = []
    for name, route, alto in (
        ("proto_app_inicio", "inicio", 1250),
        ("proto_app_comparacion", "comparacion", 1152),
    ):
        target = target_dir / f"{name}.png"
        target.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(  # noqa: S603  (programa local con lista fija de argumentos)
                [
                    str(browser),
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--hide-scrollbars",
                    f"--user-data-dir={Path(folder) / 'perfil'}",
                    "--virtual-time-budget=6000",
                    f"--window-size=760,{alto}",
                    f"--screenshot={target}",
                    f"{latest.as_uri()}#{route}",
                ],
                capture_output=True,
                check=False,
                timeout=WAIT_S * 3,
            )
            for _ in range(WAIT_S):
                if target.exists() and target.stat().st_size > 0:
                    break
                time.sleep(1)
            time.sleep(1)
        produced.append(name)
    return produced


SPECS = {
    s.__name__: s
    for s in (
        conceptual,
        caracterizacion,
        busqueda,
        particiones,
        c4_n1,
        c4_n2,
        c4_n3,
        c4_n4_factibilidad,
        c4_n4_carga,
        despliegue,
    )
}
CUSTOM = {
    f.__name__: f
    for f in (secuencia_fases, hoja_de_datos, mapa_historias, product_canvas, matriz_dependencias)
}


def png(browser: Path, svg: str, target: Path, width: int, height: int) -> None:
    target.unlink(missing_ok=True)
    scale = min(MAX_SCALE, 16000 / max(width, height))
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "figura.html"
        page.write_text(
            f'<!doctype html><meta charset="utf-8"><body style="margin:0">{svg}</body>',
            encoding="utf-8",
        )
        subprocess.run(  # noqa: S603  (programa local con lista fija de argumentos)
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
            timeout=WAIT_S * 3,
        )
        for _ in range(WAIT_S):
            if target.exists() and target.stat().st_size > 0:
                break
            time.sleep(1)
        time.sleep(1)
    if not target.exists():
        raise SystemExit(f"Edge no produjo {target.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("figuras", nargs="*")
    parser.add_argument("--salida", type=Path, default=OUTPUT)
    parser.add_argument("--navegador", type=Path, default=EDGE_BROWSER)
    args = parser.parse_args()
    folder: Path = args.salida
    folder.mkdir(parents=True, exist_ok=True)
    wanted = set(args.figuras)
    for name, build in SPECS.items():
        if wanted and name not in wanted:
            continue
        spec = build()
        svg, width, height = render(spec)
        (folder / f"{spec.name}.svg").write_text(svg, encoding="utf-8", newline="\n")
        png(args.navegador, svg, folder / f"{spec.name}.png", width, height)
        print(spec.name, width, height, flush=True)
    for name, build in CUSTOM.items():
        if wanted and name not in wanted:
            continue
        svg, width, height = build()
        (folder / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
        png(args.navegador, svg, folder / f"{name}.png", width, height)
        print(name, width, height, flush=True)
    if not wanted or "capturas_panel" in wanted:
        print(capturas_panel(folder, args.navegador), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
