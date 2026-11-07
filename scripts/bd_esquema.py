"""Verifica el esquema de la base y genera su diccionario y su SQL (DEV31 F1 y F3).

Lee ``docs/bd/esquema.toml`` (la fuente única del diseño) con ``semaforo.bd.diseno``, comprueba
que sea coherente y escribe:

- ``docs/bd/diccionario.md``, con todas las columnas de todas las tablas, sus relaciones y sus
  diagramas;
- ``src/semaforo/bd/sql/01_tablas.sql`` y ``03_seguridad.sql``, el SQL que crea la base
  (``semaforo.bd.ddl``). ``02_reglas.sql`` se escribe a mano y no lo toca.

No se conecta a ninguna base de datos. Además de lo que comprueba ``semaforo.bd.diseno``, exige
que las tablas aprobadas coincidan con el catálogo del acta de DEV31 F0.

Uso:  .venv\\Scripts\\python.exe scripts\\bd_esquema.py [--comprobar] [--html RUTA]

- sin opciones: verifica y reescribe el diccionario y el SQL generado;
- ``--comprobar``: verifica y falla si el diccionario o el SQL no están al día; no escribe nada;
- ``--html RUTA``: además escribe una versión HTML para verla en el navegador.
"""

import argparse
import html
import io
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from semaforo.bd.ddl import security_sql, tables_sql
from semaforo.bd.diseno import Column, Design, ForeignKey, SchemaError, Table, load, verify

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "docs" / "bd" / "esquema.toml"
DICTIONARY_FILE = ROOT / "docs" / "bd" / "diccionario.md"
SQL_FOLDER = ROOT / "src" / "semaforo" / "bd" / "sql"
TABLES_FILE = SQL_FOLDER / "01_tablas.sql"
SECURITY_FILE = SQL_FOLDER / "03_seguridad.sql"
ACTA_F0 = ROOT / "docs" / "actas" / "2026-11-05-dev31-f0-planificacion-y-diseno.md"


# Nombres de tabla del acta F0 que cambiaron después, con su aprobación del PO. El acta no se
# reescribe: el cambio queda aquí y en su propia acta. cola_segundo pasó a cola_por_acceso (un
# arreglo por acceso en vez de una fila por segundo; DEV31 F4, aprobado el 2026-11-07).
RENAMED_SINCE_F0 = {"cola_segundo": "cola_por_acceso"}


def catalog_names(path: Path = ACTA_F0) -> set[str]:
    """Nombres de tabla del catálogo (sección 5.4) del acta de DEV31 F0, con sus cambios."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("### 5.4"))
    end = next(i for i, line in enumerate(lines) if line.startswith("### 5.5"))
    names: set[str] = set()
    for line in lines[start:end]:
        if line.startswith("| `"):
            names.update(re.findall(r"`([a-z_]+)`", line.split("|")[1]))
    return {RENAMED_SINCE_F0.get(name, name) for name in names}


# ---------------------------------------------------------------------------------------------
# Documento (un modelo pequeño que se escribe en Markdown o en HTML)

Block = tuple[str, object]


def _blinding_text(cegado: str) -> str:
    kind, _, arg = cegado.partition(":")
    texts = {
        "no": "No. El usuario de lectura ve todas las filas.",
        "raiz": f"Sí. Se ocultan las filas cuyo escenario (`{arg}`) es de una prueba no abierta.",
        "raiz_opcional": f"Sí, si la fila tiene escenario (`{arg}`) de una prueba no abierta.",
        "padre": f"Sí. Hereda la visibilidad de `{arg}`.",
        "apertura_particion": (
            f"Sí. Las filas de prueba se ocultan hasta abrir la prueba de su partición (`{arg}`)."
        ),
        "apertura_experimento": f"Sí. Se oculta hasta abrir la prueba del experimento (`{arg}`).",
    }
    return texts.get(kind, cegado)


def _key_text(table: Table, column: Column) -> str:
    marks: list[str] = []
    if column.nombre in table.clave_primaria:
        marks.append("PK")
    for key in table.claves_foraneas:
        if column.nombre in key.columnas:
            mark = "FK" + (" opc." if key.opcional else "")
            marks.append(f"{mark} → `{key.referencia}`")
    if any(column.nombre in group for group in table.unicas):
        marks.append("única")
    return "; ".join(marks)


def _mermaid_keys(table: Table, column: Column) -> str:
    marks = []
    if column.nombre in table.clave_primaria:
        marks.append("PK")
    if any(column.nombre in k.columnas for k in table.claves_foraneas if not k.comun):
        marks.append("FK")
    if any(column.nombre in group for group in table.unicas):
        marks.append("UK")
    return ", ".join(marks)


def _relation(parent: str, child: str, key: ForeignKey) -> str:
    if key.uno_a_uno:
        card = "||--||"
    elif key.opcional:
        card = "|o--o{"
    else:
        card = "||--o{"
    return f'  {parent} {card} {child} : "{", ".join(key.columnas)}"'


def _schema_diagram(design: Design, schema: str) -> str:
    tables = [t for t in design.tablas if t.esquema == schema]
    lines = ["erDiagram"]
    for table in tables:
        lines.append(f"  {table.nombre} {{")
        for column in table.columnas:
            marks = _mermaid_keys(table, column)
            lines.append(f"    {column.tipo.replace(' ', '_')} {column.nombre} {marks}".rstrip())
        lines.append("  }")
    # Las tablas de otros esquemas aparecen solas, como cajas sin columnas, por sus relaciones.
    lines.extend(
        _relation(key.referencia.split(".")[1], table.nombre, key)
        for table in tables
        for key in table.claves_foraneas
        if not key.comun
    )
    return "\n".join(lines)


def _overview_diagram(design: Design) -> str:
    lines = ["erDiagram"]
    for table in design.tablas:
        lines.append(f"  {table.nombre} {{")
        for name in table.clave_primaria:
            column = table.column(name)
            kind = column.tipo.replace(" ", "_") if column else "text"
            lines.append(f"    {kind} {name} PK")
        lines.append("  }")
    for table in design.tablas:
        for key in table.claves_foraneas:
            if not key.comun:
                lines.append(_relation(key.referencia.split(".")[1], table.nombre, key))
    return "\n".join(lines)


def _table_blocks(table: Table) -> list[Block]:
    title = f"`{table.full}`" + (
        " (PROPUESTA: requiere aprobación del PO)" if table.propuesta else ""
    )
    facts = [
        ("Qué guarda", table.descripcion),
        ("Grano", table.grano),
        ("Origen", table.origen),
        ("Estado de la fuente", table.fuente),
        ("Filas estimadas en DEV16", table.filas_dev16),
        ("Cegado de la prueba", _blinding_text(table.cegado)),
        ("Solo agregar", table.excepcion or "Sí: no se modifican ni se borran filas."),
    ]
    rows = [
        [
            str(i),
            f"`{c.nombre}`",
            c.tipo,
            "sí" if c.nulo else "no",
            c.unidad or "",
            _key_text(table, c),
            c.descripcion + (" (columna común)" if c.comun else ""),
            c.origen,
            f"`{c.regla}`" if c.regla else "",
        ]
        for i, c in enumerate(table.columnas, start=1)
    ]
    blocks: list[Block] = [
        ("h4", title),
        ("facts", facts),
        (
            "table",
            (
                [
                    "#",
                    "Columna",
                    "Tipo",
                    "Vacío",
                    "Unidad",
                    "Clave",
                    "Descripción",
                    "Origen",
                    "Regla",
                ],
                rows,
            ),
        ),
    ]
    extra = [f"Clave primaria: `{', '.join(table.clave_primaria)}`."]
    extra += [f"Clave única: `{', '.join(u)}`." for u in table.unicas]
    extra += [f"Índice: `{', '.join(i)}`." for i in table.indices]
    extra += [
        f"Regla «{r.nombre}»: {r.descripcion}" + (f" `CHECK ({r.sql})`" if r.sql else "")
        for r in table.reglas
    ]
    extra += [
        f"Relación `{', '.join(k.columnas)}` → `{k.referencia}`: {k.nota}"
        for k in table.claves_foraneas
        if k.nota
    ]
    blocks.append(("list", extra))
    return blocks


def _summary_rows(design: Design) -> list[list[str]]:
    rows: list[list[str]] = []
    for schema, description in design.esquemas:
        tables = [t for t in design.tablas if t.esquema == schema]
        approved = [t for t in tables if not t.propuesta]
        rows.append(
            [
                f"`{schema}`",
                description,
                str(len(approved)),
                str(len(tables) - len(approved)),
                str(sum(len(t.columnas) for t in tables)),
            ]
        )
    return rows


def _relations_rows(design: Design) -> list[list[str]]:
    rows: list[list[str]] = []
    for table in design.tablas:
        for key in table.claves_foraneas:
            if key.comun:
                continue
            if key.uno_a_uno:
                card = "1 a 1"
            elif key.opcional:
                card = "0..1 a N (opcional)"
            else:
                card = "1 a N"
            rows.append(
                [
                    f"`{table.full}`",
                    f"`{', '.join(key.columnas)}`",
                    f"`{key.referencia}`",
                    f"`{', '.join(key.referidas)}`",
                    card,
                ]
            )
    return rows


def build(design: Design) -> list[Block]:
    approved = [t for t in design.tablas if not t.propuesta]
    proposals = [t for t in design.tablas if t.propuesta]
    columns = sum(len(t.columnas) for t in design.tablas)
    relations = sum(1 for t in design.tablas for k in t.claves_foraneas if not k.comun)
    blocks: list[Block] = [
        (
            "p",
            "Escrito para: el Product Owner (revisión del diseño), el asesor y el jurado "
            "(qué datos respaldan la tesis) y el equipo técnico (F2 a F8 de DEV31).",
        ),
        ("h1", "Diccionario de datos de la base «semaforo»"),
        (
            "p",
            f"Versión {design.version} del {design.fecha}. Motor: {design.motor}. "
            f"Estado: {design.estado}.",
        ),
        (
            "p",
            "**Archivo generado** por `scripts/bd_esquema.py` desde `docs/bd/esquema.toml`. "
            "No se edita a mano: se cambia el esquema y se vuelve a generar.",
        ),
        (
            "p",
            f"**{len(approved)} tablas aprobadas en F0** y **{len(proposals)} propuestas** "
            f"de F1, con **{columns} columnas** en total y **{relations} relaciones** entre "
            "tablas. Cada tabla lleva además `carga_id` y `artefacto_id`, que la unen con la "
            "carga que la escribió y con su archivo original.",
        ),
        ("h2", "Resumen por esquema"),
        (
            "table",
            (
                ["Esquema", "Qué guarda", "Tablas aprobadas", "Propuestas", "Columnas"],
                _summary_rows(design),
            ),
        ),
        ("h2", "Cómo leer este diccionario"),
        (
            "list",
            [
                "**Vacío**: «sí» quiere decir que la columna puede quedar vacía. "
                "Vacío nunca es cero.",
                "**Clave**: PK es la clave primaria; FK, una relación con otra tabla («opc.» si "
                "puede quedar vacía).",
                "**Origen**: el archivo y el campo de donde sale el dato. «Pendiente» marca tablas "
                "cuyo archivo de origen todavía no existe.",
                "**Valores codificados** (estados, orígenes, etapas): se guardan como vienen en "
                "los archivos, en inglés; la descripción los traduce.",
                "**Cegado**: cómo se oculta la prueba final al usuario de lectura hasta su "
                "apertura.",
            ],
        ),
        ("h2", "Tipos de datos"),
        (
            "table",
            (
                ["Tipo", "Qué es"],
                [
                    ["text", "Texto."],
                    ["integer", "Número entero."],
                    ["bigint", "Número entero grande."],
                    ["double precision", "Número con decimales."],
                    ["boolean", "Verdadero o falso."],
                    ["timestamptz", "Fecha y hora con zona horaria."],
                    ["date", "Fecha."],
                    [
                        "jsonb",
                        "Lista u objeto con estructura propia, por ejemplo una lista de carriles.",
                    ],
                    *(
                        [n, f"{d} Se define sobre {b} con `CHECK ({r})`."]
                        for n, (b, r, d) in design.tipos.items()
                    ),
                ],
            ),
        ),
        ("h2", "Usuarios y permisos"),
        ("table", (["Usuario", "Para qué", "Permisos"], [list(r) for r in design.roles])),
        ("h2", "Cegado de la prueba final"),
        (
            "p",
            "La zona (desarrollo o prueba) no se guarda en cada fila: se deduce de la "
            "partición congelada. Un escenario asignado a «test» está cegado mientras su "
            "partición no tenga el hito de apertura. La seguridad por filas de PostgreSQL "
            "oculta al usuario de lectura las filas de esos escenarios y todo lo que cuelga de "
            "ellas. Al registrar la apertura, aparecen sin cambiar ningún dato.",
        ),
        ("h2", "Funciones, disparadores y vistas"),
        ("table", (["Nombre", "Clase", "Qué hace"], [list(f) for f in design.funciones])),
        (
            "table",
            (
                ["Vista", "Qué muestra", "Lee de"],
                [[f"`{n}`", d, ", ".join(f"`{s}`" for s in src)] for n, d, src in design.vistas],
            ),
        ),
        ("h2", "Diagrama general"),
        (
            "p",
            "Todas las tablas con su clave primaria y sus relaciones. Las columnas comunes "
            "`carga_id` y `artefacto_id` no se dibujan para no tapar el resto.",
        ),
        ("mermaid", _overview_diagram(design)),
    ]
    for schema, description in design.esquemas:
        blocks += [
            ("h2", f"Esquema `{schema}`"),
            ("p", description),
            ("h3", "Diagrama con todas las columnas"),
            ("mermaid", _schema_diagram(design, schema)),
            ("h3", "Tablas"),
        ]
        for table in design.tablas:
            if table.esquema == schema:
                blocks += _table_blocks(table)
    blocks += [
        ("h2", "Todas las relaciones"),
        (
            "p",
            "Además de estas, cada tabla se relaciona con `control.cargas` por `carga_id` y "
            "con `control.artefactos` por `artefacto_id`.",
        ),
        (
            "table",
            (
                ["Tabla", "Columnas", "Referencia", "Columnas referidas", "Cardinalidad"],
                _relations_rows(design),
            ),
        ),
    ]
    return blocks


def _md_text(text: str) -> str:
    """Escapa «<» y «>» fuera del código, para que «<run_id>» no se lea como etiqueta HTML."""
    parts = text.split("`")
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("<", "&lt;").replace(">", "&gt;")
    return "`".join(parts)


def _md_cell(text: str) -> str:
    return _md_text(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(blocks: Sequence[Block]) -> str:
    out: list[str] = []
    for kind, payload in blocks:
        if kind in ("h1", "h2", "h3", "h4"):
            out.append("#" * int(kind[1]) + " " + _md_text(cast(str, payload)))
        elif kind == "p":
            out.append(_md_text(cast(str, payload)))
        elif kind == "list":
            out.append("\n".join(f"- {_md_text(item)}" for item in cast(list[str], payload)))
        elif kind == "facts":
            facts = cast(list[tuple[str, str]], payload)
            out.append("\n".join(f"- **{label}:** {_md_text(value)}" for label, value in facts))
        elif kind == "table":
            headers, rows = cast(tuple[list[str], list[list[str]]], payload)
            lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
            lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in rows]
            out.append("\n".join(lines))
        elif kind == "mermaid":
            out.append("```mermaid\n" + cast(str, payload) + "\n```")
    return "\n\n".join(out) + "\n"


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)


HTML_HEAD = """<meta name="claude:viewport-fit-sides" content="cover">
<title>Diccionario de datos semaforo</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono&display=swap">
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<style>
:root { --bg:#f6f5f2; --fg:#1d2328; --muted:#5b6670; --line:#d9d6cf; --card:#ffffff;
  --accent:#1f5f8b; --soft:#e4eef6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#16191c;
  --fg:#e8e6e1; --muted:#9aa4ad; --line:#2f363d; --card:#1e2327; --accent:#7fb6dc;
  --soft:#1d2f3d; color-scheme: dark; } }
:root[data-theme="dark"] { --bg:#16191c; --fg:#e8e6e1; --muted:#9aa4ad; --line:#2f363d;
  --card:#1e2327; --accent:#7fb6dc; --soft:#1d2f3d; color-scheme: dark; }
body { margin:0; background:var(--bg); color:var(--fg); line-height:1.5;
  font-family:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;
  padding-left:max(16px, env(safe-area-inset-left, 0px));
  padding-right:max(16px, env(safe-area-inset-right, 0px)); padding-block:24px 48px; }
main { max-width:1200px; margin:0 auto; }
h1 { font-size:1.7rem; text-wrap:balance; } h2 { margin-top:40px; padding-top:16px;
  border-top:1px solid var(--line); } h4 { margin:28px 0 6px; font-size:1.05rem; }
p, li { max-width:80ch; } code { font-family:"IBM Plex Mono",Consolas,monospace;
  font-size:.86em; }
.scroll { overflow-x:auto; background:var(--card); border:1px solid var(--line);
  border-radius:6px; margin:10px 0; }
table { border-collapse:collapse; font-size:.86rem; width:100%; }
th, td { text-align:left; vertical-align:top; padding:6px 8px;
  border-bottom:1px solid var(--line); }
th { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.04em; }
.diagram { overflow-x:auto; background:var(--card); border:1px solid var(--line);
  border-radius:6px; padding:12px; } .diagram .mermaid { min-width:max-content; }
a { color:var(--accent); }
</style>
<main>
"""

HTML_TAIL = """</main>
<script>
(function () {
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  try { mermaid.initialize({ startOnLoad: true, theme: dark ? "dark" : "default",
    securityLevel: "strict", maxTextSize: 400000, er: { useMaxWidth: false, fontSize: 12 } }); }
  catch (e) { document.querySelectorAll("pre.mermaid").forEach(function (p) {
    p.textContent = "No se pudo dibujar el diagrama: " + e.message; }); }
})();
</script>
"""


def to_html(blocks: Sequence[Block]) -> str:
    out: list[str] = [HTML_HEAD]
    for kind, payload in blocks:
        if kind in ("h1", "h2", "h3", "h4"):
            out.append(f"<{kind}>{_inline(cast(str, payload))}</{kind}>")
        elif kind == "p":
            out.append(f"<p>{_inline(cast(str, payload))}</p>")
        elif kind == "list":
            items = "".join(f"<li>{_inline(i)}</li>" for i in cast(list[str], payload))
            out.append(f"<ul>{items}</ul>")
        elif kind == "facts":
            facts = cast(list[tuple[str, str]], payload)
            items = "".join(
                f"<li><strong>{_inline(a)}:</strong> {_inline(b)}</li>" for a, b in facts
            )
            out.append(f"<ul>{items}</ul>")
        elif kind == "table":
            headers, rows = cast(tuple[list[str], list[list[str]]], payload)
            head = "".join(f"<th>{_inline(h)}</th>" for h in headers)
            body = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rows
            )
            out.append(
                f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>"
            )
        elif kind == "mermaid":
            code = html.escape(cast(str, payload), quote=False)
            out.append(f'<div class="diagram"><pre class="mermaid">\n{code}\n</pre></div>')
    out.append(HTML_TAIL)
    return "\n".join(out)


def outputs(design: Design) -> dict[Path, str]:
    """Cada archivo que genera el esquema, con su contenido."""
    return {
        DICTIONARY_FILE: to_markdown(build(design)),
        TABLES_FILE: tables_sql(design),
        SECURITY_FILE: security_sql(design),
    }


def _current(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", maxsplit=1)[0])
    parser.add_argument(
        "--comprobar", action="store_true", help="no escribe; falla si no está al día"
    )
    parser.add_argument("--html", type=Path, help="escribe también una versión HTML en esta ruta")
    args = parser.parse_args()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        design = load(SCHEMA_FILE)
    except (SchemaError, tomllib.TOMLDecodeError) as error:
        print(f"Esquema ilegible: {error}")
        return 1
    errors = verify(design, catalog_names())
    if errors:
        print(f"El esquema tiene {len(errors)} problemas:")
        for error in errors:
            print(f"  - {error}")
        return 1
    approved = sum(1 for t in design.tablas if not t.propuesta)
    columns = sum(len(t.columnas) for t in design.tablas)
    relations = sum(1 for t in design.tablas for k in t.claves_foraneas if not k.comun)
    print(
        f"Esquema correcto: {approved} tablas aprobadas (coinciden con el acta de F0), "
        f"{len(design.tablas) - approved} propuestas, {columns} columnas, {relations} relaciones."
    )
    files = outputs(design)
    if args.comprobar:
        stale = [path for path, text in files.items() if _current(path) != text]
        if stale:
            names = ", ".join(path.relative_to(ROOT).as_posix() for path in stale)
            print(f"No está al día: {names}. Ejecute el script sin --comprobar.")
            return 1
        print("El diccionario y el SQL generado están al día.")
        return 0
    for path, text in files.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"Escrito: {path.relative_to(ROOT).as_posix()}")
    if args.html:
        args.html.write_text(to_html(build(design)), encoding="utf-8")
        print(f"Escrito: {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
