"""Prueba de punta a punta de ``python -m semaforo splits`` (DEV12 F3).

Recorre el camino completo como lo haría el analista, en procesos aparte: genera un conjunto de
escenarios, reparte sus familias, valida la partición, la revisa con ``runs verify``, la altera y
vuelve a revisar, y comprueba los códigos de salida.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import cast

from scenario_tools import families_spec, write_inputs


def cli(cwd: Path, *arguments: str) -> tuple[int, dict[str, object], str]:
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
    return result.returncode, json.loads(result.stdout), result.stderr


def generate_set(tmp_path: Path, families: int = 5) -> Path:
    case, spec = write_inputs(tmp_path / "entradas", families_spec(families))
    code, data, _ = cli(
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
    assert code == 0
    return tmp_path / "datos" / str(data["folder"])


def test_the_whole_path_from_scenarios_to_a_checked_split(tmp_path: Path) -> None:
    folder = generate_set(tmp_path)
    code, created, message = cli(
        tmp_path,
        "splits",
        "create",
        "--scenarios",
        str(folder),
        "--seed",
        "7",
        "--workspace",
        "datos",
    )
    assert code == 0
    assert created["status"] == "published"
    assert created["groups"] == {"train": 3, "validation": 1, "test": 1}
    assert "Partición publicada" in message
    assert "DEC07 pendiente" in message
    split_folder = tmp_path / "datos" / str(created["folder"])
    code, checked, message = cli(
        tmp_path, "splits", "validate", "--split", str(split_folder), "--scenarios", str(folder)
    )
    assert code == 0
    assert checked["status"] == "valid"
    assert "es válida" in message
    code, report, _ = cli(tmp_path, "runs", "verify", "--workspace", "datos")
    assert code == 0
    items = cast(list[dict[str, str]], report["items"])
    families = {item["family"]: item["status"] for item in items}
    assert families == {"scenarios": "intact", "splits": "intact"}


def test_a_second_split_of_the_same_set_exits_5(tmp_path: Path) -> None:
    folder = generate_set(tmp_path)
    arguments = ["splits", "create", "--scenarios", str(folder), "--workspace", "datos"]
    assert cli(tmp_path, *arguments, "--seed", "7")[0] == 0
    code, data, message = cli(tmp_path, *arguments, "--seed", "8")
    assert code == 5
    assert data["code"] == "RUN_EXISTS"
    assert "la prueba se reserva una sola vez" in message


def test_a_changed_split_makes_runs_verify_exit_5(tmp_path: Path) -> None:
    folder = generate_set(tmp_path)
    _, created, _ = cli(
        tmp_path,
        "splits",
        "create",
        "--scenarios",
        str(folder),
        "--seed",
        "7",
        "--workspace",
        "datos",
    )
    victim = tmp_path / "datos" / str(created["folder"]) / "split.json"
    victim.chmod(stat.S_IWRITE | stat.S_IREAD)
    victim.write_bytes(victim.read_bytes() + b" ")
    code, report, message = cli(tmp_path, "runs", "verify", "--workspace", "datos")
    assert code == 5
    assert report["status"] == "altered"
    assert f"ALTERADA {created['folder']}: HASH_MISMATCH" in message


def test_two_families_exit_2_with_the_reason_and_publish_nothing(tmp_path: Path) -> None:
    folder = generate_set(tmp_path, families=2)
    code, data, message = cli(
        tmp_path,
        "splits",
        "create",
        "--scenarios",
        str(folder),
        "--seed",
        "7",
        "--workspace",
        "datos",
    )
    assert code == 2
    assert data["code"] == "INPUT_SCHEMA"
    assert "- SPLIT-C04 scenarios: hacen falta al menos 3 grupos" in message
    assert not (tmp_path / "datos" / "derivados" / "particiones").exists()
