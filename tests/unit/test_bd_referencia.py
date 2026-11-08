"""Comparar la base con una huella de referencia (DEV31 F4c, C1.6)."""

from datetime import UTC, datetime

from semaforo.bd.reglas import RULES_ALGORITHM
from semaforo.bd.verificacion import (
    HASH_ALGORITHM,
    Fingerprint,
    FingerprintFile,
    Measured,
    compare_with_reference,
    read_fingerprints,
)

VERSION = "sql-0123456789abcdef"
CONTENT = "c" * 64
RULES = "d" * 64
ROOTS = [Fingerprint(artefacto_id="datos:casos/c/case.json", sha256="1" * 64)]
ROWS = {"caso.casos": 1, "simulacion.corridas": 4}


def _reference(**changes: object) -> FingerprintFile:
    values: dict[str, object] = {
        "generated_at": datetime(2026, 11, 7, tzinfo=UTC),
        "carga_id": "carga-1",
        "schema_version_db": VERSION,
        "content_sha256": CONTENT,
        "algoritmo_huella": HASH_ALGORITHM,
        "reglas_sha256": RULES,
        "algoritmo_reglas": RULES_ALGORITHM,
        "rows": ROWS,
        "roots": ROOTS,
    }
    return FingerprintFile.model_validate({**values, **changes})


def _measured(
    *,
    content_sha256: str = CONTENT,
    rules_sha256: str = RULES,
    rows: dict[str, int] | None = None,
    roots: list[Fingerprint] | None = None,
) -> Measured:
    return Measured(
        VERSION,
        content_sha256,
        rules_sha256,
        dict(ROWS) if rows is None else rows,
        list(ROOTS) if roots is None else roots,
    )


def test_the_same_base_coincides_with_its_reference() -> None:
    check = compare_with_reference(_reference(), _measured(), "git abc")
    assert (check.outcome, check.differences, check.reason) == ("coincide", [], None)


def test_a_reference_of_another_schema_version_is_not_a_difference() -> None:
    check = compare_with_reference(_reference(schema_version_db="sql-otra"), _measured(), "git abc")
    assert check.outcome == "no_concluyente"
    assert check.differences == []
    assert "otra versión del esquema" in str(check.reason)


def test_a_reference_with_another_hash_algorithm_is_not_comparable() -> None:
    check = compare_with_reference(_reference(algoritmo_huella="contenido-9"), _measured(), "x")
    assert check.outcome == "no_concluyente"
    assert "algoritmo distinto" in str(check.reason)


def test_each_kind_of_change_is_reported_by_name() -> None:
    changed = _measured(
        content_sha256="e" * 64,
        rules_sha256="f" * 64,
        rows={"caso.casos": 1, "simulacion.corridas": 5, "simulacion.eventos": 2},
        roots=[Fingerprint(artefacto_id="datos:casos/c/case.json", sha256="2" * 64)],
    )
    check = compare_with_reference(_reference(), changed, "git abc")
    assert check.outcome == "difiere"
    items = {d.item for d in check.differences}
    assert items == {
        "huella de contenido",
        "filas de simulacion.corridas",
        "filas de simulacion.eventos",
        "archivo raíz datos:casos/c/case.json",
        "reglas instaladas",
    }


def test_a_root_added_or_removed_is_a_difference() -> None:
    extra = [*ROOTS, Fingerprint(artefacto_id="datos:otro.json", sha256="3" * 64)]
    assert compare_with_reference(_reference(), _measured(roots=extra), "x").outcome == "difiere"
    assert compare_with_reference(_reference(), _measured(roots=[]), "x").outcome == "difiere"


def test_a_reference_with_another_rules_algorithm_is_not_comparable() -> None:
    old = _reference(algoritmo_reglas="reglas-1", reglas_sha256="9" * 64)
    check = compare_with_reference(old, _measured(), "x")
    assert check.outcome == "no_concluyente"
    assert "algoritmo distinto" in str(check.reason)


def test_a_reference_without_rules_says_nothing_about_the_rules() -> None:
    old = _reference(reglas_sha256=None, algoritmo_reglas=None)
    assert compare_with_reference(old, _measured(rules_sha256="9" * 64), "x").outcome == "coincide"


def test_a_file_of_the_first_format_is_read_with_the_original_algorithm() -> None:
    text = (
        '{"schema_version":"1.0.0","generated_at":"2026-11-06T23:14:14Z","carga_id":"c",'
        f'"schema_version_db":"{VERSION}","content_sha256":"{CONTENT}","rows":{{}},"roots":[]}}'
    )
    reference = read_fingerprints(text)
    assert (reference.algoritmo_huella, reference.reglas_sha256) == (None, None)
    check = compare_with_reference(reference, _measured(rows={}, roots=[]), "x")
    assert check.outcome == "coincide"
