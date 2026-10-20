"""Pruebas de la recepción: copia inmutable de las entradas de una simulación SUMO (ADR09)."""

import contextlib
import dataclasses
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Generator, Iterator, Mapping
from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.reception import ReceptionSettings, SnapshotResult, snapshot_source
from semaforo.caso.reception_models import MissingDependency
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.ids import content_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sumo"
DEMO = FIXTURES / "demo"
INVALID = FIXTURES / "invalid"
FAST = ReceptionSettings(retry_attempts=2, retry_delay_s=0.0)
ENTRY = "entry.sumocfg"
CONFIG = """<configuration>
    <input>
        <net-file value="net.xml"/>
        <route-files value="routes.xml"/>
    </input>
    <output>
        <tripinfo-output value="tripinfo.xml"/>
    </output>
    <gui_only>
        <gui-settings-file value="view.xml"/>
    </gui_only>
</configuration>
"""
BASE_FILES: dict[str, str] = {
    ENTRY: CONFIG,
    "net.xml": "<net/>",
    "routes.xml": "<routes/>",
    "view.xml": "<viewsettings/>",
    "tripinfo.xml": "<tripinfos/>",
    "run.bat": "sumo-gui -c entry.sumocfg",
    "legacy.sumocfg": "<configuration/>",
    "notes.txt": "notas",
}
IDENTITY = ["entry.sumocfg", "net.xml", "routes.xml"]


@pytest.fixture
def snapshots(tmp_path: Path) -> Iterator[Path]:
    """Carpeta de copias; al terminar se borra aunque sus archivos sean de solo lectura."""
    root = tmp_path / "snapshots"
    yield root
    remove_tree(root)


def make_source(base: Path, files: Mapping[str, str] | None = None, name: str = "source") -> Path:
    source = base / name
    for relative, content in (BASE_FILES if files is None else files).items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return source


def roles(result: SnapshotResult) -> dict[str, str]:
    return {record.path: record.role for record in result.manifest.files}


def copied_files(result: SnapshotResult) -> list[str]:
    return sorted(
        p.relative_to(result.path).as_posix() for p in result.path.rglob("*") if p.is_file()
    )


def lock_files(
    monkeypatch: pytest.MonkeyPatch, names: set[str], times: int | None
) -> dict[str, int]:
    """Hace que ``sha256_file`` falle con PermissionError ``times`` veces (siempre si es None)."""
    calls: dict[str, int] = {}

    def fake(path: Path) -> str:
        if path.name in names:
            calls[path.name] = calls.get(path.name, 0) + 1
            if times is None or calls[path.name] <= times:
                raise PermissionError("bloqueado por otro proceso")
        return sha256_file(path)

    monkeypatch.setattr("semaforo.caso.reception.sha256_file", fake)
    return calls


def make_junction(link: Path, target: Path) -> None:
    """Crea una unión de Windows (``mklink /J``), que no necesita privilegios."""
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],  # noqa: S607
        check=True,
        capture_output=True,
    )


class FakeEntry:
    """Entrada de carpeta simulada: un enlace simbólico o un tipo especial (tubería...)."""

    def __init__(self, path: Path, *, symlink: bool = False) -> None:
        self.path = str(path)
        self._symlink = symlink

    def is_symlink(self) -> bool:
        return self._symlink

    def is_junction(self) -> bool:
        return False

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return False

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return False


def test_classifies_every_file_by_role(tmp_path: Path, snapshots: Path) -> None:
    result = snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    assert roles(result) == {
        "entry.sumocfg": "entry_config",
        "legacy.sumocfg": "unreferenced",
        "net.xml": "input",
        "notes.txt": "unreferenced",
        "routes.xml": "input",
        "run.bat": "script",
        "tripinfo.xml": "output",
        "view.xml": "view",
    }
    assert result.manifest.identity_files == IDENTITY


def test_copies_only_the_identity_files_with_identical_content(
    tmp_path: Path, snapshots: Path
) -> None:
    source = make_source(tmp_path)
    result = snapshot_source(source, ENTRY, snapshots, FAST)
    assert copied_files(result) == IDENTITY
    for relative in IDENTITY:
        assert sha256_file(result.path / relative) == sha256_file(source / relative)
    assert result.path == snapshots / result.manifest.snapshot_id
    assert result.reused is False


def test_records_every_observed_file_with_hash_and_size(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    result = snapshot_source(source, ENTRY, snapshots, FAST)
    for record in result.manifest.files:
        assert record.sha256 == sha256_file(source / record.path)
        assert record.size_bytes == (source / record.path).stat().st_size
        assert record.in_snapshot is (record.path in IDENTITY)


def test_snapshot_id_follows_adr09(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    result = snapshot_source(source, ENTRY, snapshots, FAST)
    expected = content_id([(relative, sha256_file(source / relative)) for relative in IDENTITY])
    assert result.manifest.snapshot_id == expected


def test_second_reception_reuses_the_snapshot(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    second = snapshot_source(source, ENTRY, snapshots, FAST)
    assert second.reused is True
    assert second.path == first.path
    assert second.manifest == first.manifest


def test_the_copy_is_read_only(tmp_path: Path, snapshots: Path) -> None:
    result = snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    for relative in IDENTITY:
        assert not (result.path / relative).stat().st_mode & stat.S_IWRITE


def test_the_source_is_not_modified(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    before = {p: (sha256_file(p), p.stat().st_mtime_ns) for p in source.rglob("*") if p.is_file()}
    snapshot_source(source, ENTRY, snapshots, FAST)
    after = {p: (sha256_file(p), p.stat().st_mtime_ns) for p in source.rglob("*") if p.is_file()}
    assert after == before


def test_non_identity_files_do_not_change_the_id(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    for name in ("tripinfo.xml", "view.xml", "run.bat", "notes.txt", "legacy.sumocfg"):
        (source / name).write_text("otro contenido", encoding="utf-8")
    second = snapshot_source(source, ENTRY, snapshots, FAST)
    assert second.manifest.snapshot_id == first.manifest.snapshot_id
    assert second.reused is True
    changed = {r.path: r.sha256 for r in second.manifest.files if r.path == "tripinfo.xml"}
    assert (
        changed["tripinfo.xml"] != {r.path: r.sha256 for r in first.manifest.files}["tripinfo.xml"]
    )


def test_changing_an_input_changes_the_id(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    (source / "routes.xml").write_text("<routes changed='1'/>", encoding="utf-8")
    second = snapshot_source(source, ENTRY, snapshots, FAST)
    assert second.manifest.snapshot_id != first.manifest.snapshot_id
    assert second.reused is False
    assert second.path != first.path


def test_changing_the_config_changes_the_id(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    config = CONFIG.replace("<input>", '<time><begin value="5"/></time><input>')
    (source / ENTRY).write_text(config, encoding="utf-8")
    assert (
        snapshot_source(source, ENTRY, snapshots, FAST).manifest.snapshot_id
        != first.manifest.snapshot_id
    )


def test_the_manifest_is_deterministic(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots / "a", FAST)
    second = snapshot_source(source, ENTRY, snapshots / "b", FAST)
    assert first.manifest.model_dump_json() == second.manifest.model_dump_json()


def test_nested_entry_config_keeps_the_layout(tmp_path: Path, snapshots: Path) -> None:
    files = {
        "sub/entry.sumocfg": CONFIG.replace('value="routes.xml"', 'value="../data/routes.xml"'),
        "sub/net.xml": "<net/>",
        "data/routes.xml": "<routes/>",
        "sub/view.xml": "<viewsettings/>",
    }
    source = make_source(tmp_path, files)
    result = snapshot_source(source, "sub/entry.sumocfg", snapshots, FAST)
    assert result.manifest.identity_files == ["data/routes.xml", "sub/entry.sumocfg", "sub/net.xml"]
    assert copied_files(result) == result.manifest.identity_files
    assert (
        snapshot_source(source, "sub\\entry.sumocfg", snapshots, FAST).manifest == result.manifest
    )


def test_a_load_state_file_is_part_of_the_identity(tmp_path: Path, snapshots: Path) -> None:
    files = {
        **BASE_FILES,
        ENTRY: CONFIG.replace("</input>", '<load-state value="state.xml"/></input>'),
        "state.xml": "<snapshot/>",
    }
    source = make_source(tmp_path, files)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    assert roles(first)["state.xml"] == "input"
    assert first.manifest.identity_files == [*IDENTITY, "state.xml"]
    (source / "state.xml").write_text("<snapshot changed='1'/>", encoding="utf-8")
    second = snapshot_source(source, ENTRY, snapshots, FAST)
    assert second.manifest.snapshot_id != first.manifest.snapshot_id


def test_missing_dependency_is_reported_not_invented(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    (source / "routes.xml").unlink()
    result = snapshot_source(source, ENTRY, snapshots, FAST)
    assert result.manifest.missing_dependencies == [
        MissingDependency(
            path="routes.xml", section="input", option="route-files", reason="not_found"
        )
    ]
    assert result.manifest.identity_files == ["entry.sumocfg", "net.xml"]


def test_missing_view_is_reported_with_its_section(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    (source / "view.xml").unlink()
    result = snapshot_source(source, ENTRY, snapshots, FAST)
    assert [(d.path, d.section, d.reason) for d in result.manifest.missing_dependencies] == [
        ("view.xml", "gui_only", "not_found")
    ]


def test_a_reference_outside_the_source_is_not_followed(tmp_path: Path, snapshots: Path) -> None:
    (tmp_path / "outside.xml").write_text("<secreto/>", encoding="utf-8")
    files = dict(BASE_FILES)
    files[ENTRY] = CONFIG.replace('value="routes.xml"', 'value="../outside.xml"')
    source = make_source(tmp_path, files)
    result = snapshot_source(source, ENTRY, snapshots, FAST)
    assert [(d.path, d.reason) for d in result.manifest.missing_dependencies] == [
        ("../outside.xml", "outside_source")
    ]
    assert copied_files(result) == ["entry.sumocfg", "net.xml"]


def test_an_absolute_input_is_reported_as_missing_and_as_a_finding(
    tmp_path: Path, snapshots: Path
) -> None:
    files = dict(BASE_FILES)
    files[ENTRY] = CONFIG.replace('value="net.xml"', 'value="C:\\mapas\\net.xml"')
    result = snapshot_source(make_source(tmp_path, files), ENTRY, snapshots, FAST)
    assert [(d.path, d.reason) for d in result.manifest.missing_dependencies] == [
        ("C:\\mapas\\net.xml", "absolute_path")
    ]
    assert [(f.code, f.section, f.option) for f in result.manifest.findings] == [
        ("ABSOLUTE_PATH", "input", "net-file")
    ]


def test_an_absolute_output_is_reported_as_a_finding(tmp_path: Path, snapshots: Path) -> None:
    files = dict(BASE_FILES)
    files[ENTRY] = CONFIG.replace('value="tripinfo.xml"', 'value="Q:\\salida\\tripinfo.xml"')
    result = snapshot_source(make_source(tmp_path, files), ENTRY, snapshots, FAST)
    assert [(f.code, f.section, f.option, f.path) for f in result.manifest.findings] == [
        ("ABSOLUTE_PATH", "output", "tripinfo-output", "Q:\\salida\\tripinfo.xml")
    ]
    assert result.manifest.identity_files == IDENTITY


def test_reference_casing_follows_the_platform(tmp_path: Path, snapshots: Path) -> None:
    files = dict(BASE_FILES)
    files[ENTRY] = CONFIG.replace('value="net.xml"', 'value="NET.XML"')
    result = snapshot_source(make_source(tmp_path, files), ENTRY, snapshots, FAST)
    if os.name == "nt":
        assert "net.xml" in result.manifest.identity_files
        assert result.manifest.missing_dependencies == []
    else:
        assert [d.path for d in result.manifest.missing_dependencies] == ["NET.XML"]


def test_receives_the_synthetic_demo_fixture(snapshots: Path) -> None:
    result = snapshot_source(DEMO, "demo.sumocfg", snapshots, FAST)
    assert result.manifest.identity_files == ["demo.net.xml", "demo.rou.xml", "demo.sumocfg"]
    assert {roles(result)[name] for name in ("demo.nod.xml", "demo.tll.xml")} == {"unreferenced"}
    assert result.manifest.missing_dependencies == []
    assert result.manifest.findings == []


def test_the_absolute_output_variant_of_the_fixture_is_flagged(snapshots: Path) -> None:
    result = snapshot_source(INVALID / "absolute_output", "demo.sumocfg", snapshots, FAST)
    assert [(f.code, f.section, f.option) for f in result.manifest.findings] == [
        ("ABSOLUTE_PATH", "output", "tripinfo-output")
    ]


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        ("", ErrorCode.INPUT_SCHEMA),
        ("absent.sumocfg", ErrorCode.INPUT_SCHEMA),
        ("notes.txt", ErrorCode.INPUT_SCHEMA),
        ("../entry.sumocfg", ErrorCode.PATH_NOT_ALLOWED),
        ("C:\\entry.sumocfg", ErrorCode.PATH_NOT_ALLOWED),
        ("/entry.sumocfg", ErrorCode.PATH_NOT_ALLOWED),
    ],
)
def test_rejects_an_invalid_entry_config(
    tmp_path: Path, snapshots: Path, entry: str, code: ErrorCode
) -> None:
    with pytest.raises(CasoError) as raised:
        snapshot_source(make_source(tmp_path), entry, snapshots, FAST)
    assert raised.value.code is code


def test_the_source_must_be_an_existing_folder(tmp_path: Path, snapshots: Path) -> None:
    for candidate in (tmp_path / "absent", make_source(tmp_path) / "notes.txt"):
        with pytest.raises(CasoError) as raised:
            snapshot_source(candidate, ENTRY, snapshots, FAST)
        assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_the_snapshots_folder_cannot_be_inside_the_source(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    with pytest.raises(CasoError) as raised:
        snapshot_source(source, ENTRY, source / "snapshots", FAST)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (source / "snapshots").exists()


WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="las uniones (junctions) solo existen en Windows"
)


@WINDOWS_ONLY
def test_a_junction_in_the_source_is_rejected(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = source / "linked"
    make_junction(link, target)
    try:
        with pytest.raises(CasoError) as raised:
            snapshot_source(source, ENTRY, snapshots, FAST)
        assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
        assert raised.value.field == "linked"
    finally:
        link.rmdir()


@WINDOWS_ONLY
def test_a_source_that_is_a_junction_is_rejected(tmp_path: Path, snapshots: Path) -> None:
    real = make_source(tmp_path, name="real")
    link = tmp_path / "linked-source"
    make_junction(link, real)
    try:
        with pytest.raises(CasoError) as raised:
            snapshot_source(link, ENTRY, snapshots, FAST)
        assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
        assert raised.value.field == "source"
    finally:
        link.rmdir()


def test_a_symlink_in_the_source_is_rejected(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    try:
        os.symlink(source / "net.xml", source / "link.xml")
    except (OSError, NotImplementedError):
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    with pytest.raises(CasoError) as raised:
        snapshot_source(source, ENTRY, snapshots, FAST)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.parametrize(
    ("symlink", "reason"),
    [(False, "tipo de archivo no admitido"), (True, "enlaces simbólicos")],
    ids=["special-file", "symlink"],
)
def test_links_and_special_file_types_are_rejected_before_reading_them(
    tmp_path: Path, snapshots: Path, monkeypatch: pytest.MonkeyPatch, *, symlink: bool, reason: str
) -> None:
    """Simula la entrada: crear enlaces o tuberías reales exige privilegios o POSIX."""
    source = make_source(tmp_path)

    @contextlib.contextmanager
    def fake_scandir(path: Path) -> Generator[Iterator[FakeEntry]]:
        yield iter([FakeEntry(Path(path) / "odd", symlink=symlink)])

    monkeypatch.setattr("semaforo.caso.reception.os.scandir", fake_scandir)
    with pytest.raises(CasoError) as raised:
        snapshot_source(source, ENTRY, snapshots, FAST)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert raised.value.field == "odd"
    assert reason in raised.value.message


@pytest.mark.parametrize("relative", ["occupied", "occupied/child"])
def test_the_snapshots_path_must_be_usable_as_a_folder(tmp_path: Path, relative: str) -> None:
    (tmp_path / "occupied").write_text("no soy una carpeta", encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        snapshot_source(make_source(tmp_path), ENTRY, tmp_path / relative, FAST)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "snapshots_root"


@pytest.mark.parametrize(
    "changes",
    [{"max_entries": 3}, {"max_observed_bytes": 10}, {"max_config_bytes": 10}],
    ids=["entries", "observed-bytes", "config-bytes"],
)
def test_limits_are_enforced(tmp_path: Path, snapshots: Path, changes: dict[str, int]) -> None:
    with pytest.raises(CasoError) as raised:
        snapshot_source(
            make_source(tmp_path), ENTRY, snapshots, dataclasses.replace(FAST, **changes)
        )
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


@pytest.mark.parametrize(
    "changes",
    [{"retry_attempts": 0}, {"retry_delay_s": -1.0}, {"max_entries": 0}, {"max_observed_bytes": 0}],
)
def test_invalid_settings_are_rejected(changes: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="debe"):
        dataclasses.replace(FAST, **changes)


def test_a_locked_non_identity_file_is_recorded_not_skipped(
    tmp_path: Path, snapshots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = lock_files(monkeypatch, {"tripinfo.xml"}, times=None)
    result = snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    assert calls["tripinfo.xml"] == FAST.retry_attempts
    locked = next(r for r in result.manifest.files if r.path == "tripinfo.xml")
    assert locked.sha256 is None
    assert locked.in_snapshot is False
    assert locked.unreadable_reason is not None
    assert "PermissionError" in locked.unreadable_reason
    assert copied_files(result) == IDENTITY


def test_a_transient_lock_is_retried(
    tmp_path: Path, snapshots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = lock_files(monkeypatch, {"tripinfo.xml", "net.xml"}, times=1)
    result = snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    assert calls["tripinfo.xml"] >= 2
    assert calls["net.xml"] >= 2
    assert all(r.sha256 is not None for r in result.manifest.files)


def test_a_locked_identity_file_stops_the_reception(
    tmp_path: Path, snapshots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = lock_files(monkeypatch, {"net.xml"}, times=None)
    with pytest.raises(CasoError) as raised:
        snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    assert calls["net.xml"] == FAST.retry_attempts
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "net.xml"
    assert not snapshots.exists() or list(snapshots.iterdir()) == []


def test_a_source_changed_during_the_copy_is_detected(
    tmp_path: Path, snapshots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def copy_then_modify(origin: Path, destination: Path) -> None:
        shutil.copyfile(origin, destination)
        if origin.name == "net.xml":
            origin.write_text("<net changed='1'/>", encoding="utf-8")

    monkeypatch.setattr("semaforo.caso.reception._copy_file", copy_then_modify)
    with pytest.raises(CasoError) as raised:
        snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert list(snapshots.iterdir()) == []


def test_a_corrupt_copy_is_detected(
    tmp_path: Path, snapshots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def corrupt_copy(origin: Path, destination: Path) -> None:
        destination.write_bytes(b"corrupto")

    monkeypatch.setattr("semaforo.caso.reception._copy_file", corrupt_copy)
    with pytest.raises(CasoError) as raised:
        snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert list(snapshots.iterdir()) == []


def test_a_tampered_existing_snapshot_is_detected(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    victim = first.path / "net.xml"
    os.chmod(victim, stat.S_IWRITE)
    victim.write_text("<net manipulada='1'/>", encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        snapshot_source(source, ENTRY, snapshots, FAST)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_an_extra_file_in_an_existing_snapshot_is_detected(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    (first.path / "extra.xml").write_text("<extra/>", encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        snapshot_source(source, ENTRY, snapshots, FAST)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_file_with_the_name_of_a_snapshot_is_detected(tmp_path: Path, snapshots: Path) -> None:
    source = make_source(tmp_path)
    first = snapshot_source(source, ENTRY, snapshots, FAST)
    remove_tree(first.path)
    first.path.write_text("no soy una carpeta", encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        snapshot_source(source, ENTRY, snapshots, FAST)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_no_temporary_folders_are_left_behind(tmp_path: Path, snapshots: Path) -> None:
    result = snapshot_source(make_source(tmp_path), ENTRY, snapshots, FAST)
    assert [p.name for p in snapshots.iterdir()] == [result.manifest.snapshot_id]
