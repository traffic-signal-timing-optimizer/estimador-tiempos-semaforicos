"""Seguridad de los escenarios controlados y las particiones (DEV11 y DEV12).

Toda entrada es no confiable (especificaciones, políticas, carpetas, manifiestos): se prueba que los
archivos hostiles no tumban el programa ni lo dejan consumir memoria sin límite, que los nombres con
rutas no sacan nada de la carpeta de trabajo, que los enlaces no se siguen y que un manifiesto
alterado se detecta.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scenario_tools import families_spec, publish_set, spec_data, write_inputs
from semaforo.app.scenario_commands import ScenarioSetResult, generate_scenario_set
from semaforo.app.split_commands import create_split_set, validate_split_set
from semaforo.caso.errors import CasoError
from semaforo.caso.json_input import MAX_JSON_BYTES
from semaforo.datos.scenario_set import MANIFEST_FILE, read_scenario_set
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario_spec import MAX_SCENARIOS, SpecInvalidError
from workspace_tools import writable

SEED = 7


def tree(folder: Path) -> set[str]:
    """Todos los archivos y carpetas bajo ``folder``, relativos."""
    return (
        {p.relative_to(folder).as_posix() for p in folder.rglob("*")} if folder.exists() else set()
    )


def generate(tmp_path: Path, spec_text: str | bytes, name: str = "spec.json") -> ScenarioSetResult:
    case, _ = write_inputs(tmp_path / "entradas")
    spec = tmp_path / "entradas" / name
    if isinstance(spec_text, bytes):
        spec.write_bytes(spec_text)
    else:
        spec.write_text(spec_text, encoding="utf-8")
    return generate_scenario_set(tmp_path / "datos", case, spec, SEED)


def outside_untouched(tmp_path: Path) -> bool:
    """Lo único que existe fuera de las entradas es la carpeta de trabajo, y nada fuera de ella."""
    return {p.name for p in tmp_path.iterdir()} <= {"entradas", "datos"}


# --- especificaciones hostiles ----------------------------------------------------------------


def test_a_spec_nested_a_hundred_thousand_levels_is_rejected_without_crashing(
    tmp_path: Path,
) -> None:
    with pytest.raises(CasoError) as raised:
        generate(tmp_path, "[" * 100_000 + "]" * 100_000)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert not (tmp_path / "datos").exists()


def test_a_spec_over_the_size_limit_is_rejected_before_parsing(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        generate(tmp_path, b" " * (MAX_JSON_BYTES + 1))
    assert "supera el límite" in raised.value.message
    assert not (tmp_path / "datos").exists()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "null",
        "[]",
        '"texto"',
        "{",
        '{"a": 1, "a": 2}',
        '{"schema_version": NaN}',
        '{"schema_version": Infinity}',
        '{"schema_version": -Infinity}',
    ],
)
def test_malformed_specs_are_rejected_with_a_domain_error(tmp_path: Path, text: str) -> None:
    with pytest.raises(DomainError) as raised:
        generate(tmp_path, text)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert not (tmp_path / "datos").exists()


def test_a_spec_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        generate(tmp_path, bytes([0xFF, 0xFE, 0x00]))
    assert "UTF-8" in raised.value.message


@pytest.mark.parametrize(
    "family_id", ["../fuera", "..", "a/b", "a" + chr(92) + "b", "CON:", "a\x00b", "ñ", "a b"]
)
def test_a_family_name_with_a_path_is_rejected_and_nothing_is_written(
    tmp_path: Path, family_id: str
) -> None:
    data = spec_data()
    data["families"][0]["family_id"] = family_id
    with pytest.raises(SpecInvalidError) as raised:
        generate(tmp_path, json.dumps(data))
    assert raised.value.issues[0].rule_id == "SPEC-S02"
    assert not (tmp_path / "datos").exists()
    assert outside_untouched(tmp_path)


@pytest.mark.parametrize("case_id", ["../fuera", "a/b", "a" + chr(92) + "b", ".oculto"])
def test_a_case_name_with_a_path_cannot_become_a_folder(tmp_path: Path, case_id: str) -> None:
    case, spec = write_inputs(tmp_path / "entradas")
    case_data = json.loads(case.read_text(encoding="utf-8"))
    case_data["case_id"] = case_id
    case.write_text(json.dumps(case_data), encoding="utf-8")
    data = spec_data()
    data["case_id"] = case_id
    spec.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        generate_scenario_set(tmp_path / "datos", case, spec, SEED)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (tmp_path / "datos").exists()
    assert outside_untouched(tmp_path)


@pytest.mark.parametrize(
    "counts",
    [
        {"variants": 10**9, "seeds": 1},
        {"variants": 1, "seeds": 10**9},
        {"variants": 10**6, "seeds": 10**6},
        {"variants": 10**30, "seeds": 10**30},
    ],
)
def test_huge_counts_are_rejected_before_generating_anything(
    tmp_path: Path, counts: dict[str, int]
) -> None:
    data = spec_data()
    data["families"][0].update(counts)
    started = time.perf_counter()
    with pytest.raises(SpecInvalidError) as raised:
        generate(tmp_path, json.dumps(data))
    assert time.perf_counter() - started < 5
    assert any(issue.rule_id == "SPEC-C05" for issue in raised.value.issues)
    assert not (tmp_path / "datos").exists()


def test_a_spec_with_three_thousand_families_is_rejected_quickly(tmp_path: Path) -> None:
    template = spec_data()["families"][0]
    data = spec_data()
    data["families"] = [
        {**template, "family_id": f"F{n}", "variants": 1, "seeds": 1} for n in range(3_000)
    ]
    started = time.perf_counter()
    with pytest.raises(SpecInvalidError) as raised:
        generate(tmp_path, json.dumps(data))
    assert time.perf_counter() - started < 20
    assert len(raised.value.issues) <= 101
    assert any("el máximo es" in issue.message for issue in raised.value.issues)
    assert MAX_SCENARIOS == 2000


@pytest.mark.parametrize("flow", [-1, 1e308, float("inf")])
def test_extreme_flows_are_rejected_not_generated(tmp_path: Path, flow: float) -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 0, "max": flow}
    text = json.dumps(data).replace("Infinity", "1e999")
    with pytest.raises(DomainError):
        generate(tmp_path, text)
    assert not (tmp_path / "datos").exists()


def test_a_subnormal_flow_is_a_valid_tiny_flow_and_does_not_crash(tmp_path: Path) -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 0, "max": 1e-320}
    result = generate(tmp_path, json.dumps(data))
    assert result.scenarios == 10


def test_a_spec_with_a_hundred_thousand_classes_is_capped(tmp_path: Path) -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["composition"] = {f"c{n}": 0.00001 for n in range(100_000)}
    started = time.perf_counter()
    with pytest.raises(SpecInvalidError) as raised:
        generate(tmp_path, json.dumps(data))
    assert time.perf_counter() - started < 20
    assert len(raised.value.issues) <= 101


def test_a_spec_that_is_a_directory_or_a_link_is_not_read(tmp_path: Path) -> None:
    case, real = write_inputs(tmp_path / "entradas")
    with pytest.raises(CasoError):
        generate_scenario_set(tmp_path / "datos", case, tmp_path / "entradas", SEED)
    link = tmp_path / "entradas" / "enlace.json"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(CasoError) as raised:
        generate_scenario_set(tmp_path / "datos", case, link, SEED)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


def test_everything_written_stays_inside_the_set_folder(tmp_path: Path) -> None:
    case, spec = write_inputs(tmp_path / "entradas")
    before = tree(tmp_path)
    result = generate_scenario_set(tmp_path / "datos", case, spec, SEED)
    created = tree(tmp_path) - before
    assert all(name == "datos" or name.startswith("datos/derivados") for name in created)
    folder = tmp_path / "datos" / result.folder
    inside = {p.relative_to(tmp_path).as_posix() for p in folder.rglob("*")}
    assert inside <= created


# --- políticas y carpetas hostiles ------------------------------------------------------------


def prepared(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "datos"
    return workspace, publish_set(workspace, 5).folder


@pytest.mark.parametrize(
    "text",
    [
        "",
        "{",
        "[]",
        "null",
        '{"proportions": {"train": NaN, "validation": 0.2, "test": 0.2}}',
        pytest.param("[" * 100_000 + "]" * 100_000, id="anidado"),
    ],
)
def test_hostile_policy_files_are_rejected_and_nothing_is_published(
    tmp_path: Path, text: str
) -> None:
    workspace, folder = prepared(tmp_path)
    policy = tmp_path / "politica.json"
    policy.write_text(text, encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        create_split_set(workspace, folder, SEED, policy)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert not (workspace / "derivados" / "particiones").exists()


@pytest.mark.parametrize("policy_id", ["../fuera", "a/b", "..", "a b", "ñ", ""])
def test_a_policy_name_with_a_path_is_rejected(tmp_path: Path, policy_id: str) -> None:
    workspace, folder = prepared(tmp_path)
    policy = tmp_path / "politica.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "policy_id": policy_id,
                "proportions": {"train": 0.6, "validation": 0.2, "test": 0.2},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(DomainError) as raised:
        create_split_set(workspace, folder, SEED, policy)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert not (workspace / "derivados" / "particiones").exists()


@pytest.mark.parametrize("which", ["file", "empty_folder", "workspace"])
def test_a_folder_argument_that_is_not_a_set_is_rejected(tmp_path: Path, which: str) -> None:
    workspace, _ = prepared(tmp_path)
    target = {
        "file": tmp_path / "datos" / "nota.txt",
        "empty_folder": tmp_path / "vacia",
        "workspace": workspace,
    }[which]
    if which == "file":
        target.write_text("x", encoding="utf-8")
    elif which == "empty_folder":
        target.mkdir()
    with pytest.raises(DomainError) as raised:
        create_split_set(workspace, target, SEED)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_a_set_folder_that_is_a_link_is_not_followed(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    link = tmp_path / "enlace"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(DomainError) as raised:
        create_split_set(workspace, link, SEED)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


def editable(folder: Path, tmp_path: Path) -> Path:
    target = tmp_path / "copia"
    shutil.copytree(folder, target)
    for path in [target, *target.rglob("*")]:
        writable(path)
    return target


@pytest.mark.parametrize(
    "name", ["../fuera.txt", "/absoluta.txt", "C:/windows.txt", "a/../../b", "", "a//b"]
)
def test_a_manifest_naming_a_path_outside_the_folder_is_rejected(tmp_path: Path, name: str) -> None:
    _, folder = prepared(tmp_path)
    copy = editable(folder, tmp_path)
    manifest = json.loads((copy / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest["files"][name] = "0" * 64
    (copy / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        read_scenario_set(copy)
    assert raised.value.code in (ErrorCode.PATH_NOT_ALLOWED, ErrorCode.HASH_MISMATCH)
    assert not (tmp_path / "fuera.txt").exists()


def test_a_forged_hash_of_content_is_detected(tmp_path: Path) -> None:
    _, folder = prepared(tmp_path)
    copy = editable(folder, tmp_path)
    manifest = json.loads((copy / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest["content_id"] = "f" * 64
    (copy / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        read_scenario_set(copy)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_split_made_of_an_altered_set_is_never_created(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    victim = folder / "escenarios" / "FAM_01-V01-S01.json"
    writable(victim).write_bytes(victim.read_bytes() + b" ")
    with pytest.raises(DomainError) as raised:
        create_split_set(workspace, folder, SEED)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert not (workspace / "derivados" / "particiones").exists()


def test_validate_never_trusts_a_split_of_another_set(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    result = create_split_set(workspace, folder, SEED)
    other = publish_set(workspace, 5, seed=SEED + 1).folder
    with pytest.raises(DomainError):
        validate_split_set(workspace / str(result.folder), other)


def test_the_split_tool_never_touches_the_set_it_reads(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    before = {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }
    result = create_split_set(workspace, folder, SEED)
    validate_split_set(workspace / str(result.folder), folder)
    after = {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }
    assert before == after


# --- desde la línea de comandos ---------------------------------------------------------------


def cli(cwd: Path, *arguments: str) -> tuple[int, str, str]:
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        [sys.executable, "-m", "semaforo", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
        cwd=cwd,
        timeout=180,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def test_a_hostile_spec_through_the_command_line_exits_2_with_only_json_on_stdout(
    tmp_path: Path,
) -> None:
    data = spec_data()
    data["families"][0]["family_id"] = "../fuera"
    case, spec = write_inputs(tmp_path / "entradas", data)
    code, out, err = cli(
        tmp_path,
        "scenarios",
        "generate",
        "--case",
        str(case),
        "--spec",
        str(spec),
        "--seed",
        "7",
        "--workspace",
        "datos",
    )
    assert code == 2
    assert json.loads(out)["code"] == "INPUT_SCHEMA"
    assert "- SPEC-S02 families[0].family_id" in err
    assert not (tmp_path / "datos").exists()


def test_an_internal_failure_never_leaks_a_traceback_without_debug(tmp_path: Path) -> None:
    case, spec = write_inputs(tmp_path / "entradas", families_spec(5))
    code, out, err = cli(
        tmp_path,
        "scenarios",
        "generate",
        "--case",
        str(case),
        "--spec",
        str(spec),
        "--seed",
        "7",
        "--workspace",
        str(tmp_path / "datos" / "nada" / ("x" * 300)),
    )
    assert "Traceback" not in err
    assert "Traceback" not in out
    assert code in (0, 1, 2, 5)
