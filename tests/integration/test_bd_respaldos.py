"""Fichas de respaldo y prueba de un respaldo específico (DEV31 F4c, C1.8; B10).

Cada prueba es un criterio de aceptación de B10: el respaldo se restaura en una base temporal y su
huella se **recalcula** sobre las tablas restauradas; un número guardado no basta.
"""

import json
import shutil
from pathlib import Path

import pytest

from semaforo.bd.carga.insercion import Catalog
from semaforo.bd.conexion import ADMIN, BdError, connect
from semaforo.bd.esquema import installed_version
from semaforo.bd.prueba_respaldo import backup_test_exit_code, probar_respaldo
from semaforo.bd.respaldo import backup, ficha_de_archivo, ficha_path, read_ficha
from semaforo.bd.verificacion import content_hash

pytestmark = pytest.mark.bd

RECORDED = "carga-de-referencia"


def _content_hash(database: str) -> str:
    with connect(ADMIN, database=database) as connection:
        return content_hash(connection, Catalog.load(connection))[0]


def _record_completed_load(database: str, version: str | None = None) -> str:
    """Una carga completa que guardó la huella de contenido de la base tal como está.

    ``version`` es la versión del esquema que dice la carga (por defecto, la instalada).
    """
    with connect(ADMIN, database=database) as connection:
        digest = content_hash(connection, Catalog.load(connection))[0]
        connection.execute(
            "INSERT INTO control.cargas (carga_id, inicio, fin, estado, comando, version_paquete, "
            "version_postgres, version_esquema, huella_contenido) VALUES (%s, now(), now(), "
            "'completed', '{}'::jsonb, 'prueba', 'prueba', %s, %s)",
            (RECORDED, version or installed_version(connection), digest),
        )
        connection.commit()
    return digest


def _add_file_row(database: str) -> None:
    """Una fila nueva (un archivo registrado) después de la carga que guardó la huella."""
    with connect(ADMIN, database=database, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO control.artefactos (artefacto_id, raiz, ruta_relativa, tipo, "
            "tamano_bytes, sha256, manifiesto_id, estado, alcance, registrado_en, carga_id) VALUES "
            "('datos:otro.json', 'datos', 'otro.json', 'other', 1, %s, NULL, 'intact', "
            "'desconocido', now(), %s)",
            ("a" * 64, RECORDED),
        )


def _temporary_databases() -> int:
    with connect(ADMIN, database="postgres", autocommit=True) as connection:
        row = connection.execute(
            "SELECT count(*) FROM pg_database WHERE datname LIKE 'semaforo\\_pruebas\\_%'"
        ).fetchone()
    return 0 if row is None else int(row[0])


def _dump(tmp_path: Path, base: str) -> Path:
    saved = backup(tmp_path / "respaldos", database=base)
    return tmp_path / "respaldos" / saved.file


def _without_card(dump: Path) -> Path:
    """Un respaldo como los antiguos: sin ficha."""
    ficha_path(dump).unlink()
    return dump


# --- fichas ----------------------------------------------------------------------------------


def test_a_new_backup_goes_in_its_schema_folder_with_a_card_taken_from_the_same_snapshot(
    base: str, tmp_path: Path
) -> None:
    digest = _content_hash(base)
    saved = backup(tmp_path / "respaldos", database=base)
    dump = tmp_path / "respaldos" / saved.file
    assert Path(saved.file).parent.name == saved.version_esquema
    assert saved.version_esquema is not None and saved.version_esquema.startswith("sql-")
    assert dump.with_name(f"{dump.name}.sha256").is_file()
    ficha = read_ficha(dump)
    assert ficha is not None
    assert (ficha.sha256.estado, ficha.sha256.valor) == ("verificado", saved.sha256)
    assert (ficha.huella_contenido.estado, ficha.huella_contenido.valor) == ("verificado", digest)
    assert (ficha.version_esquema.estado, ficha.version_esquema.valor) == (
        "verificado",
        saved.version_esquema,
    )
    assert ficha.tablas.estado == "verificado"
    assert isinstance(ficha.tablas.valor, list)
    assert {"control.cargas", "simulacion.cola_por_acceso"} <= set(ficha.tablas.valor)
    assert ficha.carga_id.estado == "desconocido"  # esta base no tiene ninguna carga


def test_the_card_of_an_old_backup_says_only_what_can_be_read_without_restoring(
    base: str, tmp_path: Path
) -> None:
    dump = _without_card(_dump(tmp_path, base))
    ficha = ficha_de_archivo(dump)
    assert (ficha.sha256.estado, ficha.version_esquema.estado) == ("verificado", "declarado")
    assert ficha.version_esquema.valor == installed_version_of(base)
    assert ficha.tablas.estado == "verificado"
    assert (ficha.huella_contenido.estado, ficha.huella_contenido.valor) == ("no_comprobado", None)
    assert (ficha.carga_id.estado, ficha.commit_codigo.estado) == ("no_comprobado",) * 2
    assert read_ficha(dump) == ficha


def installed_version_of(database: str) -> str | None:
    with connect(ADMIN, database=database) as connection:
        return installed_version(connection)


def test_an_old_backup_whose_file_does_not_match_its_fingerprint_is_not_verified(
    base: str, tmp_path: Path
) -> None:
    dump = _without_card(_dump(tmp_path, base))
    dump.with_name(f"{dump.name}.sha256").write_text(f"{'0' * 64}  {dump.name}\n", encoding="utf-8")
    ficha = ficha_de_archivo(dump)
    assert ficha.sha256.estado == "desconocido"
    assert "NO coincide" in ficha.sha256.fuente
    dump.with_name(f"{dump.name}.sha256").unlink()
    ficha_path(dump).unlink()
    assert ficha_de_archivo(dump).sha256.estado == "desconocido"


def test_a_card_that_already_exists_is_not_rewritten_by_one_that_knows_less(
    base: str, tmp_path: Path
) -> None:
    dump = _dump(tmp_path, base)
    before = ficha_path(dump).read_bytes()
    with pytest.raises(BdError, match="ya tiene ficha"):
        ficha_de_archivo(dump)
    assert ficha_path(dump).read_bytes() == before


# --- probar un respaldo ----------------------------------------------------------------------


def test_a_new_backup_is_intact_restores_and_its_recalculated_fingerprint_coincides(
    base: str, tmp_path: Path
) -> None:
    dump = _dump(tmp_path, base)
    card_before = ficha_path(dump).read_bytes()
    before = _temporary_databases()
    evidence = probar_respaldo(dump)
    assert (evidence.sha256.estado, evidence.restauracion.estado) == ("coincide", "exitosa")
    assert evidence.contenido.estado == "coincide"
    assert evidence.contenido.huella_calculada == evidence.contenido.huella_esperada
    assert "ficha del respaldo" in str(evidence.contenido.procedencia)
    assert backup_test_exit_code(evidence) == 0
    assert _temporary_databases() == before  # la base temporal se borró
    assert ficha_path(dump).read_bytes() == card_before  # la ficha original no se reescribe
    (written,) = list(dump.parent.glob(f"{dump.name}.verificacion-*.json"))
    assert json.loads(written.read_text(encoding="utf-8"))["contenido"]["estado"] == "coincide"


def test_a_file_whose_fingerprint_differs_stops_before_restoring(base: str, tmp_path: Path) -> None:
    dump = _dump(tmp_path, base)
    dump.with_name(f"{dump.name}.sha256").write_text(f"{'0' * 64}  {dump.name}\n", encoding="utf-8")
    evidence = probar_respaldo(dump)
    assert evidence.sha256.estado == "difiere"
    assert evidence.restauracion.estado == "no_intentada"
    assert evidence.contenido.estado == "no_comprobado"
    assert backup_test_exit_code(evidence) == 5
    dump.with_name(f"{dump.name}.sha256").unlink()
    missing = probar_respaldo(dump)
    assert (missing.sha256.estado, missing.restauracion.estado) == ("no_comprobado", "no_intentada")
    assert backup_test_exit_code(missing) == 6


def test_a_restoration_that_works_can_still_differ_if_a_row_is_not_the_one_in_the_reference(
    base: str, tmp_path: Path
) -> None:
    dump = _dump(tmp_path, base)
    card = json.loads(ficha_path(dump).read_text(encoding="utf-8"))
    card["huella_contenido"]["valor"] = "b" * 64  # la referencia original ya no es la de las tablas
    ficha_path(dump).write_text(json.dumps(card), encoding="utf-8")
    evidence = probar_respaldo(dump)
    assert evidence.restauracion.estado == "exitosa"
    assert evidence.contenido.estado == "difiere"
    assert "huella de contenido" in str(evidence.contenido.detalle)
    assert backup_test_exit_code(evidence) == 5


def test_a_card_made_with_another_hash_algorithm_is_not_compared(base: str, tmp_path: Path) -> None:
    dump = _dump(tmp_path, base)
    card = json.loads(ficha_path(dump).read_text(encoding="utf-8"))
    card["algoritmo_huella"] = "contenido-9"
    ficha_path(dump).write_text(json.dumps(card), encoding="utf-8")
    evidence = probar_respaldo(dump)
    assert evidence.contenido.estado == "no_comprobado"
    assert "algoritmo distinto" in str(evidence.contenido.detalle)
    assert backup_test_exit_code(evidence) == 6


def test_an_old_backup_uses_the_fingerprint_its_own_last_load_left(
    base: str, tmp_path: Path
) -> None:
    digest = _record_completed_load(base)
    dump = _without_card(_dump(tmp_path, base))
    evidence = probar_respaldo(dump)
    assert evidence.contenido.estado == "coincide"
    assert evidence.contenido.huella_esperada == digest
    assert f"carga {RECORDED}" in str(evidence.contenido.procedencia)
    assert backup_test_exit_code(evidence) == 0


def test_an_old_backup_without_a_valid_reference_restores_but_its_content_is_not_checked(
    base: str, tmp_path: Path
) -> None:
    dump = _without_card(_dump(tmp_path, base))  # la base no tiene ninguna carga
    evidence = probar_respaldo(dump)
    assert evidence.restauracion.estado == "exitosa"
    assert evidence.contenido.estado == "no_comprobado"
    assert "sin referencia válida" in str(evidence.contenido.detalle)
    assert backup_test_exit_code(evidence) == 6


def test_an_old_backup_with_rows_added_after_its_last_load_differs(
    base: str, tmp_path: Path
) -> None:
    _record_completed_load(base)
    _add_file_row(base)
    evidence = probar_respaldo(_without_card(_dump(tmp_path, base)))
    assert evidence.restauracion.estado == "exitosa"
    assert evidence.contenido.estado == "difiere"
    assert backup_test_exit_code(evidence) == 5


def test_each_old_backup_is_tested_by_its_own_path_and_none_is_moved(
    base: str, tmp_path: Path
) -> None:
    first = _without_card(_dump(tmp_path, base))
    second = tmp_path / "otra-carpeta" / "20200101T000000Z.dump"
    second.parent.mkdir()
    shutil.copy(first, second)
    shutil.copy(first.with_name(f"{first.name}.sha256"), second.with_name(f"{second.name}.sha256"))
    results = {path.name: probar_respaldo(path) for path in (first, second)}
    assert {r.archivo for r in results.values()} == {first.name, second.name}
    assert first.is_file() and second.is_file()


def test_b10_a_card_that_names_another_schema_version_makes_the_content_differ(
    base: str, tmp_path: Path
) -> None:
    dump = _dump(tmp_path, base)
    card = json.loads(ficha_path(dump).read_text(encoding="utf-8"))
    card["version_esquema"]["valor"] = "sql-de-otra-version"
    ficha_path(dump).write_text(json.dumps(card), encoding="utf-8")
    evidence = probar_respaldo(dump)
    assert evidence.restauracion.estado == "exitosa"
    assert evidence.contenido.estado == "difiere"
    assert evidence.contenido.version_esperada == "sql-de-otra-version"
    assert "versión del esquema" in str(evidence.contenido.detalle)
    assert "huella de contenido" not in str(evidence.contenido.detalle)  # las filas son las mismas
    assert backup_test_exit_code(evidence) == 5


def test_b10_an_old_backup_whose_last_load_names_another_schema_version_differs(
    base: str, tmp_path: Path
) -> None:
    _record_completed_load(base, version="sql-de-otra-version")
    evidence = probar_respaldo(_without_card(_dump(tmp_path, base)))
    assert evidence.restauracion.estado == "exitosa"
    assert evidence.contenido.estado == "difiere"
    assert "versión del esquema" in str(evidence.contenido.detalle)
    assert backup_test_exit_code(evidence) == 5
