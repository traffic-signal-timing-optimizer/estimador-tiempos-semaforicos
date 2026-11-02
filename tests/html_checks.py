"""Comprobaciones comunes de un informe HTML (DEV09, QA30).

Lee la página como la leería un navegador (con ``html.parser``) y comprueba lo que la
documentación pide de un informe: texto escapado, nada que se ejecute, estructura accesible. Sirve
para las dos vistas y para las pruebas de seguridad.
"""

from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = frozenset({"meta", "br"})
FORBIDDEN_TAGS = frozenset(
    {
        "script",
        "iframe",
        "object",
        "embed",
        "img",
        "link",
        "form",
        "input",
        "button",
        "svg",
        "base",
        "audio",
        "video",
        "source",
        "frame",
        "frameset",
    }
)
FORBIDDEN_ATTRIBUTES = frozenset({"src", "srcset", "style", "action", "formaction", "data"})


@dataclass
class Table:
    """Una tabla leída: su título, sus cabeceras de columna y el texto de cada fila."""

    caption: str = ""
    headers: list[str] = field(default_factory=list[str])
    rows: list[list[str]] = field(default_factory=list[list[str]])


@dataclass
class Inspection:
    """Lo que un navegador vería en la página."""

    tables: list[Table] = field(default_factory=list[Table])
    tags: Counter[str] = field(default_factory=Counter[str])
    attributes: list[tuple[str, str, str | None]] = field(
        default_factory=list[tuple[str, str, str | None]]
    )
    text: list[str] = field(default_factory=list[str])
    problems: list[str] = field(default_factory=list[str])

    @property
    def visible_text(self) -> str:
        return "".join(self.text)

    def table(self, caption: str) -> Table:
        """La tabla con ese título (debe ser única)."""
        found = [table for table in self.tables if table.caption == caption]
        assert len(found) == 1, f"tablas con el título {caption!r}: {len(found)}"
        return found[0]

    def values(self, tag: str, attribute: str) -> list[str]:
        return [value or "" for t, name, value in self.attributes if (t, name) == (tag, attribute)]


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.result = Inspection()
        self.stack: list[str] = []
        self.table: Table | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.in_caption = False
        self.in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.result.tags[tag] += 1
        for name, value in attrs:
            self.result.attributes.append((tag, name, value))
        if tag not in VOID:
            self.stack.append(tag)
        self._open(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.result.problems.append(f"cierre inesperado de {tag}")
            return
        self.stack.pop()
        self._close(tag)

    def _open(self, tag: str) -> None:
        if tag == "table":
            self.table = Table()
            self.result.tables.append(self.table)
        elif tag == "caption":
            self.in_caption = True
        elif tag == "thead":
            self.in_head = True
        elif tag == "tr":
            self.row = []
        elif tag in {"th", "td"}:
            self.cell = []

    def _close(self, tag: str) -> None:
        if tag == "caption":
            self.in_caption = False
        elif tag == "thead":
            self.in_head = False
        elif tag in {"th", "td"} and self.cell is not None and self.row is not None:
            shown = "".join(self.cell).strip()
            if self.in_head and self.table is not None:
                self.table.headers.append(shown)
            else:
                self.row.append(shown)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None and not self.in_head:
                self.table.rows.append(self.row)
            self.row = None

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1] == "style":
            return
        self.result.text.append(data)
        if self.cell is not None:
            self.cell.append(data)
        elif self.in_caption and self.table is not None:
            self.table.caption += data

    def close(self) -> None:
        super().close()
        if self.stack:
            self.result.problems.append(f"etiquetas sin cerrar: {self.stack}")


def inspect(page: str) -> Inspection:
    """La página leída como un navegador; los defectos de forma quedan en ``problems``."""
    reader = _Reader()
    reader.feed(page)
    reader.close()
    return reader.result


def assert_safe_page(page: str) -> Inspection:
    """Comprueba que ``page`` cumple lo que se pide de un informe y devuelve su lectura."""
    assert page.startswith("<!doctype html>"), "falta el tipo de documento"
    seen = inspect(page)
    assert seen.problems == [], seen.problems
    assert seen.values("html", "lang") == ["es"]
    assert seen.values("meta", "charset") == ["utf-8"]
    policy = seen.values("meta", "content")
    assert any("default-src 'none'" in value for value in policy), "falta la política de contenido"
    assert seen.tags["title"] == 1
    assert seen.tags["h1"] == 1, "debe haber un solo encabezado principal"
    assert not (set(seen.tags) & FORBIDDEN_TAGS), set(seen.tags) & FORBIDDEN_TAGS
    for tag, name, _ in seen.attributes:
        assert not name.startswith("on"), f"atributo de evento en {tag}: {name}"
        assert name not in FORBIDDEN_ATTRIBUTES, f"atributo no permitido en {tag}: {name}"
    ids = [value or "" for _, name, value in seen.attributes if name == "id"]
    assert len(ids) == len(set(ids)), "identificadores repetidos"
    for tag, name, value in seen.attributes:
        if name == "href":
            target = value or ""
            assert tag == "a", f"enlace en {tag}"
            assert target.startswith("#"), f"enlace que sale de la página: {target}"
            assert target[1:] in ids, f"ancla sin destino: {target}"
    assert seen.tags["table"] == seen.tags["caption"], "toda tabla lleva título"
    assert seen.tags["th"] == len(seen.values("th", "scope")), "toda cabecera lleva su alcance"
    for tag, name, value in seen.attributes:
        assert "javascript:" not in (value or "").lower(), f"{tag}.{name} lleva javascript:"
    return seen
