"""Piezas para armar páginas HTML estáticas sin que un dato pueda inyectar HTML (DEV09 F2).

Decisiones D3, D9 y D10 de ``2026-11-01-dev09-f0-decisiones.md``:

- **Todo texto se escapa.** Cada función recibe texto común (``str``) y lo escapa; solo un
  fragmento ``Html`` se inserta tal cual, y solo este módulo crea ``Html`` (una prueba lo
  comprueba). El texto fijo de las páginas vive en constantes.
- **Solo etiquetas y atributos conocidos**, con valores que cumplen un formato. No hay ``script``,
  atributos de eventos, imágenes ni recursos externos; los únicos enlaces apuntan a anclas de la
  misma página.
- **Caracteres de control y de dirección de texto** (que pueden esconder o invertir lo que se lee)
  se reemplazan por ``U+FFFD``.
- **Política de contenido** en la propia página: sin scripts, sin recursos externos.
- **Accesibilidad:** idioma, título, encabezados, tablas con título y cabeceras de columna y fila.
  Cada estado lleva un símbolo y un texto además del color.
"""

import html
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, Literal

__all__ = [
    "Html",
    "Tone",
    "bullet_list",
    "code",
    "definition_list",
    "element",
    "escape",
    "heading",
    "join",
    "page",
    "paragraph",
    "status",
    "table",
    "text",
]

Tone = Literal["ok", "warn", "bad", "none"]
_SYMBOLS: Final[dict[Tone, str]] = {
    "ok": "\N{HEAVY CHECK MARK}",
    "warn": "\N{WARNING SIGN}",
    "bad": "\N{HEAVY MULTIPLICATION X}",
    "none": "\N{EN DASH}",
}
_CONTROL: Final = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
    "\N{LEFT-TO-RIGHT EMBEDDING}-\N{RIGHT-TO-LEFT OVERRIDE}"
    "\N{LEFT-TO-RIGHT ISOLATE}-\N{POP DIRECTIONAL ISOLATE}]"
)
_REPLACEMENT: Final = "\N{REPLACEMENT CHARACTER}"

_VOID_TAGS: Final = frozenset({"meta", "br"})
_TAGS: Final = frozenset(
    {
        "a",
        "br",
        "caption",
        "code",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "header",
        "li",
        "main",
        "meta",
        "nav",
        "p",
        "section",
        "span",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_CLASS: Final = re.compile(r"[a-z][a-z0-9_-]*( [a-z][a-z0-9_-]*)*")
_SLUG: Final = re.compile(r"[a-z][a-z0-9-]*")
# None: texto libre, que se escapa; una expresión: formato obligatorio.
_ATTRIBUTES: Final[dict[str, re.Pattern[str] | None]] = {
    "class": _CLASS,
    "id": _SLUG,
    "href": re.compile(r"#[a-z][a-z0-9-]*"),
    "scope": re.compile(r"col|row"),
    "colspan": re.compile(r"[1-9][0-9]?"),
    "aria-hidden": re.compile(r"true"),
    "aria-label": None,
    "aria-labelledby": _SLUG,
    "charset": re.compile(r"utf-8"),
    "name": re.compile(r"[a-z]+"),
    "content": None,
    "http-equiv": re.compile(r"Content-Security-Policy"),
}

_POLICY: Final = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
)
_STYLE: Final = """
:root{color-scheme:light dark;--fg:#1a1a1a;--bg:#fff;--mute:#555;--line:#c4c4c4;--head:#efefef;
--ok:#0a6b2d;--warn:#855400;--bad:#a4161a}
@media (prefers-color-scheme:dark){:root{--fg:#ececec;--bg:#161616;--mute:#a9a9a9;--line:#484848;
--head:#262626;--ok:#62d68d;--warn:#f0b64a;--bad:#ff8c8f}}
body{font:16px/1.5 system-ui,"Segoe UI",Arial,sans-serif;color:var(--fg);background:var(--bg);
margin:0}
header,main,footer{max-width:72rem;margin:0 auto;padding:.75rem 1rem}
h1{font-size:1.6rem;margin:.5rem 0}
h2{font-size:1.25rem;margin:2rem 0 .5rem;border-bottom:1px solid var(--line)}
table{border-collapse:collapse;width:100%;margin:.5rem 0}
caption{text-align:left;font-weight:600;padding:.25rem 0}
th,td{border:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top}
th{background:var(--head)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.tabla{overflow-x:auto}
.estado{font-weight:600;white-space:nowrap}
.estado.ok{color:var(--ok)}.estado.warn{color:var(--warn)}.estado.bad{color:var(--bad)}
.estado.none{color:var(--mute)}
code{font-family:Consolas,monospace;word-break:break-all}
dl.datos{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem}
dt{font-weight:600}
dd{margin:0}
.nota{color:var(--mute)}
.alerta{border:2px solid var(--bad);padding:.25rem 1rem;margin:1rem 0}
"""


class Html(str):
    """Un fragmento de HTML ya seguro. Solo este módulo lo crea."""

    __slots__ = ()


def escape(value: str) -> str:
    """``value`` listo para ir como texto o como valor de un atributo."""
    return html.escape(_CONTROL.sub(_REPLACEMENT, value), quote=True)


def text(value: str) -> Html:
    """Un texto común como fragmento HTML."""
    return Html(escape(value))


def join(parts: Iterable[Html | str]) -> Html:
    """Une partes: el texto común se escapa y los fragmentos ``Html`` se dejan como están."""
    return Html("".join(part if isinstance(part, Html) else escape(part) for part in parts))


def _attributes(values: Mapping[str, str]) -> str:
    rendered: list[str] = []
    for name, value in values.items():
        if name not in _ATTRIBUTES:
            raise ValueError(f"atributo no permitido: {name}")
        pattern = _ATTRIBUTES[name]
        if pattern is not None and pattern.fullmatch(value) is None:
            raise ValueError(f"valor no permitido para {name}: {value!r}")
        rendered.append(f' {name}="{escape(value)}"')
    return "".join(rendered)


def element(
    tag: str, children: Iterable[Html | str] = (), attributes: Mapping[str, str] | None = None
) -> Html:
    """Una etiqueta con sus hijos. El texto común de los hijos se escapa.

    Raises:
        ValueError: si la etiqueta o un atributo no están permitidos, o un valor no cumple su
            formato. Es un error de quien arma la página, no de los datos.
    """
    if tag not in _TAGS:
        raise ValueError(f"etiqueta no permitida: {tag}")
    opening = f"<{tag}{_attributes(attributes or {})}>"
    if tag in _VOID_TAGS:
        return Html(opening)
    return Html(f"{opening}{join(children)}</{tag}>")


def heading(level: int, value: str, slug: str | None = None) -> Html:
    """Un encabezado ``h1``, ``h2`` o ``h3``, con ancla opcional."""
    attributes = {} if slug is None else {"id": slug}
    return element(f"h{level}", [value], attributes)


def paragraph(children: Iterable[Html | str], css: str | None = None) -> Html:
    return element("p", children, None if css is None else {"class": css})


def code(value: str) -> Html:
    return element("code", [value])


def bullet_list(items: Sequence[Html | str]) -> Html:
    return element("ul", [element("li", [item]) for item in items])


def definition_list(pairs: Sequence[tuple[str, Html | str]]) -> Html:
    """Pares nombre-valor, para los datos de identidad de un informe."""
    parts: list[Html] = []
    for name, value in pairs:
        parts.append(element("dt", [name]))
        parts.append(element("dd", [value]))
    return element("dl", parts, {"class": "datos"})


def status(tone: Tone, label: str) -> Html:
    """Un estado con símbolo y texto: el color nunca es el único indicador."""
    symbol = element("span", [_SYMBOLS[tone]], {"aria-hidden": "true"})
    return element("span", [symbol, " ", label], {"class": f"estado {tone}"})


def table(
    caption: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[Html | str]],
    *,
    numeric: frozenset[int] = frozenset(),
    row_headers: bool = False,
) -> Html:
    """Una tabla con título, cabeceras de columna y, si se pide, de fila.

    ``numeric`` son las columnas que se alinean a la derecha. Una fila con otra cantidad de
    celdas que las cabeceras es un error de quien arma la página.
    """
    head = element(
        "thead",
        [element("tr", [element("th", [name], {"scope": "col"}) for name in headers])],
    )
    body: list[Html] = []
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("una fila no tiene tantas celdas como cabeceras")
        cells: list[Html] = []
        for index, cell in enumerate(row):
            if row_headers and index == 0:
                cells.append(element("th", [cell], {"scope": "row"}))
            else:
                css = {"class": "num"} if index in numeric else None
                cells.append(element("td", [cell], css))
        body.append(element("tr", cells))
    wrapper = element(
        "table",
        [element("caption", [caption]), head, element("tbody", body)],
    )
    return element("div", [wrapper], {"class": "tabla"})


def page(title: str, body: Iterable[Html], *, lang: str = "es") -> str:
    """La página completa. ``title`` se escapa; el resto del encabezado es fijo."""
    if re.fullmatch(r"[a-z]{2}", lang) is None:
        raise ValueError(f"idioma no permitido: {lang!r}")
    return (
        "<!doctype html>\n"
        f'<html lang="{lang}">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{_POLICY}">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>{_STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{join(body)}\n"
        "</body>\n</html>\n"
    )
