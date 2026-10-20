"""Pruebas de la validación de rutas relativas compartida por manifiestos y almacén."""

import pytest

from semaforo.trazabilidad.paths import check_relative_path, is_absolute_like


@pytest.mark.parametrize("path", ["a.xml", "inputs/a.xml", "a/b/c.net.xml.gz", "a b.xml"])
def test_accepts_relative_posix_paths(path: str) -> None:
    assert check_relative_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/a.xml",
        "C:/a.xml",
        "C:a.xml",
        "\\\\srv\\a.xml",
        "a\\b.xml",
        "../a.xml",
        "a/../b.xml",
        "./a.xml",
        "a//b.xml",
        "a/",
        "a\tb",
        "a\nb",
        "a\rb",
    ],
)
def test_rejects_paths_that_escape_or_break_the_format(path: str) -> None:
    with pytest.raises(ValueError, match="ruta"):
        check_relative_path(path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("a.xml", False), ("C:\\x", True), ("C:x", True), ("/x", True), ("\\\\s\\r\\x", True)],
)
def test_is_absolute_like(text: str, *, expected: bool) -> None:
    assert is_absolute_like(text) is expected
