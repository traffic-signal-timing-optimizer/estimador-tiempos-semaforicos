"""Piezas para armar HTML: escape, etiquetas y estructura accesible (DEV09 F2, D3, D9 y D10)."""

import ast
from pathlib import Path

import pytest

from html_checks import assert_safe_page, inspect
from semaforo.app.html_page import (
    Html,
    Tone,
    bullet_list,
    code,
    definition_list,
    element,
    escape,
    heading,
    join,
    page,
    paragraph,
    status,
    table,
    text,
)

SOURCE = Path(__file__).resolve().parents[2] / "src" / "semaforo"
ATTACKS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "'><svg onload=alert(1)>",
    "&lt;b&gt; &amp; &#60;",
    "javascript:alert(1)",
    "</td></tr></table><h1>otro</h1>",
]


# --- escape -----------------------------------------------------------------------------------


def test_the_html_special_characters_are_escaped() -> None:
    assert escape('<a href="x">&\'</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&#x27;&lt;/a&gt;"


def test_plain_text_and_accents_are_not_changed() -> None:
    assert escape("Válido con avisos: 50 % (ñandú)") == "Válido con avisos: 50 % (ñandú)"


def test_tab_and_line_breaks_are_kept() -> None:
    assert escape("a\tb\nc\r\nd") == "a\tb\nc\r\nd"


@pytest.mark.parametrize(
    "char", ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\x0e", "\x1b", "\x1f", "\x7f"]
)
def test_control_characters_are_replaced(char: str) -> None:
    assert escape(f"a{char}b") == "a\N{REPLACEMENT CHARACTER}b"


@pytest.mark.parametrize(
    "char",
    [
        "\N{LEFT-TO-RIGHT EMBEDDING}",
        "\N{RIGHT-TO-LEFT EMBEDDING}",
        "\N{POP DIRECTIONAL FORMATTING}",
        "\N{LEFT-TO-RIGHT OVERRIDE}",
        "\N{RIGHT-TO-LEFT OVERRIDE}",
        "\N{LEFT-TO-RIGHT ISOLATE}",
        "\N{RIGHT-TO-LEFT ISOLATE}",
        "\N{FIRST STRONG ISOLATE}",
        "\N{POP DIRECTIONAL ISOLATE}",
    ],
)
def test_text_direction_controls_are_replaced(char: str) -> None:
    assert escape(f"a{char}b") == "a\N{REPLACEMENT CHARACTER}b"


def test_text_around_the_direction_controls_is_kept() -> None:
    assert escape("\N{RIGHT-TO-LEFT MARK}x") == "\N{RIGHT-TO-LEFT MARK}x"
    assert escape("x\N{ARABIC LETTER ALEF}") == "x\N{ARABIC LETTER ALEF}"


def test_text_returns_an_html_fragment_that_join_does_not_escape_twice() -> None:
    fragment = text("<b>")
    assert isinstance(fragment, Html)
    assert fragment == "&lt;b&gt;"
    assert join([fragment, "<i>"]) == "&lt;b&gt;&lt;i&gt;"


def test_join_leaves_an_html_fragment_as_it_is() -> None:
    assert join([Html("<b>x</b>"), "<i>"]) == "<b>x</b>&lt;i&gt;"


# --- etiquetas y atributos permitidos ---------------------------------------------------------


def test_an_element_escapes_its_children_and_keeps_nested_fragments() -> None:
    inner = element("span", ["<x>"])
    assert element("p", ["a&b ", inner]) == "<p>a&amp;b <span>&lt;x&gt;</span></p>"


@pytest.mark.parametrize("tag", ["script", "img", "iframe", "style", "html", "body", "form", "a b"])
def test_a_tag_that_is_not_allowed_is_refused(tag: str) -> None:
    with pytest.raises(ValueError, match="etiqueta no permitida"):
        element(tag)


@pytest.mark.parametrize(
    "attribute", ["onclick", "onerror", "style", "src", "srcset", "formaction", "data-x", "xmlns"]
)
def test_an_attribute_that_is_not_allowed_is_refused(attribute: str) -> None:
    with pytest.raises(ValueError, match="atributo no permitido"):
        element("p", [], {attribute: "x"})


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("class", 'x" onmouseover="y'),
        ("class", "Mayuscula"),
        ("class", ""),
        ("class", "a  b"),
        ("id", "1abc"),
        ("id", "a b"),
        ("id", 'a"'),
        ("href", "https://example.com"),
        ("href", "javascript:alert(1)"),
        ("href", "#"),
        ("href", "#Mayus"),
        ("href", "otra.html#x"),
        ("href", "reglas"),
        ("charset", "latin-1"),
        ("name", "Viewport"),
        ("name", "<x>"),
        ("scope", "colgroup"),
        ("colspan", "0"),
        ("colspan", "100"),
        ("aria-hidden", "false"),
    ],
)
def test_an_attribute_value_that_breaks_its_format_is_refused(attribute: str, value: str) -> None:
    with pytest.raises(ValueError, match="valor no permitido"):
        element("a", [], {attribute: value})


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("class", "estado ok"),
        ("id", "reglas-1"),
        ("href", "#reglas-1"),
        ("scope", "row"),
        ("colspan", "3"),
        ("aria-hidden", "true"),
    ],
)
def test_an_attribute_value_in_its_format_is_accepted(attribute: str, value: str) -> None:
    assert element("a", [], {attribute: value}) == f'<a {attribute}="{value}"></a>'


def test_a_free_text_attribute_is_escaped() -> None:
    assert element("div", [], {"aria-label": '"><script>'}) == (
        '<div aria-label="&quot;&gt;&lt;script&gt;"></div>'
    )


def test_a_void_tag_has_no_closing_tag() -> None:
    assert element("br") == "<br>"
    assert element("meta", [], {"name": "viewport", "content": "a>b"}) == (
        '<meta name="viewport" content="a&gt;b">'
    )


def test_the_content_security_policy_is_the_only_http_equiv_allowed() -> None:
    element("meta", [], {"http-equiv": "Content-Security-Policy", "content": "x"})
    with pytest.raises(ValueError, match="valor no permitido"):
        element("meta", [], {"http-equiv": "refresh", "content": "0;url=https://x"})


# --- piezas -----------------------------------------------------------------------------------


def test_headings_are_h1_to_h3_with_an_optional_anchor() -> None:
    assert heading(1, "Hola") == "<h1>Hola</h1>"
    assert heading(2, "A & B", "seccion-1") == '<h2 id="seccion-1">A &amp; B</h2>'
    assert heading(3, "x") == "<h3>x</h3>"
    with pytest.raises(ValueError, match="etiqueta no permitida"):
        heading(4, "x")
    with pytest.raises(ValueError, match="etiqueta no permitida"):
        heading(0, "x")


def test_paragraph_code_and_lists() -> None:
    assert paragraph(["a", code("<x>")], "nota") == '<p class="nota">a<code>&lt;x&gt;</code></p>'
    assert paragraph(["a"]) == "<p>a</p>"
    assert bullet_list(["<a>", Html("<b>b</b>")]) == "<ul><li>&lt;a&gt;</li><li><b>b</b></li></ul>"


def test_a_definition_list_pairs_names_and_values() -> None:
    result = definition_list([("Origen", "<x>"), ("Estado", Html("<b>ok</b>"))])
    assert result == (
        '<dl class="datos"><dt>Origen</dt><dd>&lt;x&gt;</dd><dt>Estado</dt><dd><b>ok</b></dd></dl>'
    )


@pytest.mark.parametrize(
    ("tone", "symbol"),
    [
        ("ok", "\N{HEAVY CHECK MARK}"),
        ("warn", "\N{WARNING SIGN}"),
        ("bad", "\N{HEAVY MULTIPLICATION X}"),
        ("none", "\N{EN DASH}"),
    ],
)
def test_a_status_carries_a_symbol_and_a_text_besides_its_color(tone: Tone, symbol: str) -> None:
    result = status(tone, "<Cumple>")
    assert result == (
        f'<span class="estado {tone}"><span aria-hidden="true">{symbol}</span> '
        "&lt;Cumple&gt;</span>"
    )


def test_a_table_has_a_caption_column_headers_and_alignment() -> None:
    result = table("Mi tabla", ["A", "B"], [["x", "1"], ["y", "2"]], numeric=frozenset({1}))
    assert result == (
        '<div class="tabla"><table><caption>Mi tabla</caption><thead><tr>'
        '<th scope="col">A</th><th scope="col">B</th></tr></thead><tbody>'
        '<tr><td>x</td><td class="num">1</td></tr><tr><td>y</td><td class="num">2</td></tr>'
        "</tbody></table></div>"
    )


def test_a_table_can_use_its_first_column_as_row_headers() -> None:
    result = table("T", ["A", "B"], [["x", "1"]], row_headers=True)
    assert '<tr><th scope="row">x</th><td>1</td></tr>' in result


def test_a_table_with_no_rows_still_has_its_headers() -> None:
    result = table("Vacía", ["A"], [])
    assert '<th scope="col">A</th>' in result
    assert "<tbody></tbody>" in result


def test_a_row_with_the_wrong_number_of_cells_is_refused() -> None:
    with pytest.raises(ValueError, match="tantas celdas como cabeceras"):
        table("T", ["A", "B"], [["solo"]])


@pytest.mark.parametrize("attack", ATTACKS)
def test_hostile_text_in_any_part_of_a_table_stays_text(attack: str) -> None:
    result = table(attack, [attack], [[attack]], row_headers=True)
    page_text = page("t", [heading(1, "x"), result])
    seen = assert_safe_page(page_text)
    assert attack.replace("\n", "") in seen.visible_text
    assert seen.tags["table"] == 1
    assert seen.tags["h1"] == 1


# --- la página --------------------------------------------------------------------------------


def test_the_page_has_what_a_report_needs() -> None:
    result = page("Informe", [heading(1, "Informe"), paragraph(["hola"])])
    seen = assert_safe_page(result)
    assert seen.values("html", "lang") == ["es"]
    assert "Informe" in seen.visible_text


def test_the_page_title_is_escaped() -> None:
    result = page("</title><script>alert(1)</script>", [heading(1, "x")])
    seen = assert_safe_page(result)
    assert "&lt;/title&gt;&lt;script&gt;" in result
    assert "<script>" not in result
    assert seen.tags["title"] == 1


def test_the_page_policy_forbids_scripts_and_external_resources() -> None:
    result = page("t", [heading(1, "x")])
    assert "default-src 'none'" in result
    assert "script-src" not in result
    assert "http://" not in result
    assert "https://" not in result


def test_the_page_language_must_be_two_lowercase_letters() -> None:
    assert 'lang="en"' in page("t", [heading(1, "x")], lang="en")
    for bad in ('es"', "ES", "esp", "", "e s"):
        with pytest.raises(ValueError, match="idioma no permitido"):
            page("t", [], lang=bad)


def test_the_page_viewport_and_charset_are_declared() -> None:
    result = page("t", [heading(1, "x")])
    assert '<meta charset="utf-8">' in result
    assert 'name="viewport"' in result


def test_the_inspector_rejects_what_it_should() -> None:
    bad = page("t", [Html("<h1>a</h1><script>x</script>")])
    with pytest.raises(AssertionError):
        assert_safe_page(bad)
    unbalanced = page("t", [Html("<h1>a</h1><p>sin cerrar")])
    assert inspect(unbalanced).problems
    event = page("t", [Html('<h1 onclick="x">a</h1>')])
    with pytest.raises(AssertionError, match="evento"):
        assert_safe_page(event)
    outside = page("t", [Html('<h1>a</h1><a href="https://x.com">x</a>')])
    with pytest.raises(AssertionError, match="sale de la página"):
        assert_safe_page(outside)
    orphan = page("t", [Html('<h1>a</h1><a href="#nada">x</a>')])
    with pytest.raises(AssertionError, match="ancla sin destino"):
        assert_safe_page(orphan)
    untitled = page("t", [Html("<h1>a</h1><table><tr><td>x</td></tr></table>")])
    with pytest.raises(AssertionError, match="título"):
        assert_safe_page(untitled)


# --- solo este módulo crea fragmentos seguros -------------------------------------------------


def test_only_the_html_module_creates_html_fragments() -> None:
    offenders: list[str] = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path.name == "html_page.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "Html":
                    offenders.append(f"{path.relative_to(SOURCE).as_posix()}:{node.lineno}")
    assert offenders == []
