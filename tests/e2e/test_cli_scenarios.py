"""Prueba de punta a punta de ``python -m semaforo scenarios`` (DEV11 F4).

Ejecuta el comando como lo haría el analista, en un proceso aparte: genera un conjunto, lo revisa
con ``runs verify``, lo altera y vuelve a revisar, y comprueba los códigos de salida.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import cast

from scenario_tools import spec_data, write_inputs


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


def generate(
    cwd: Path, case: Path, spec: Path, seed: str = "7"
) -> tuple[int, dict[str, object], str]:
    return cli(
        cwd,
        "scenarios",
        "generate",
        "--case",
        str(case),
        "--spec",
        str(spec),
        "--seed",
        seed,
        "--workspace",
        "datos",
    )


def test_a_set_is_generated_and_checked_by_runs_verify(tmp_path: Path) -> None:
    case, spec = write_inputs(tmp_path / "entradas")
    code, data, message = generate(tmp_path, case, spec)
    assert code == 0
    assert data["status"] == "published"
    assert data["scenarios"] == 10
    assert (tmp_path / "datos" / str(data["manifest"])).is_file()
    assert "Conjunto de escenarios publicado" in message
    code, report, _ = cli(tmp_path, "runs", "verify", "--workspace", "datos")
    assert code == 0
    assert report["status"] == "intact"
    items = cast(list[dict[str, str]], report["items"])
    scenarios = [item for item in items if item["family"] == "scenarios"]
    assert [item["status"] for item in scenarios] == ["intact"]
    assert scenarios[0]["path"] == data["folder"]


def test_the_same_inputs_and_seed_give_the_same_content_hash(tmp_path: Path) -> None:
    case, spec = write_inputs(tmp_path / "entradas")
    _, first, _ = generate(tmp_path, case, spec)
    _, again, _ = cli(
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
        "otro",
    )
    assert first["content_id"] == again["content_id"]
    _, other_seed, _ = generate(tmp_path, case, spec, seed="8")
    assert other_seed["content_id"] != first["content_id"]


def test_a_changed_scenario_makes_runs_verify_exit_5(tmp_path: Path) -> None:
    case, spec = write_inputs(tmp_path / "entradas")
    _, data, _ = generate(tmp_path, case, spec)
    victim = tmp_path / "datos" / str(data["folder"]) / "escenarios" / "FAM_PUNTA-V01-S01.json"
    victim.chmod(stat.S_IWRITE | stat.S_IREAD)
    victim.write_bytes(victim.read_bytes() + b" ")
    code, report, message = cli(tmp_path, "runs", "verify", "--workspace", "datos")
    assert code == 5
    assert report["status"] == "altered"
    assert f"ALTERADA {data['folder']}: HASH_MISMATCH" in message


def test_an_invalid_range_exits_2_with_every_problem_and_publishes_nothing(
    tmp_path: Path,
) -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 600, "max": 400}
    case, spec = write_inputs(tmp_path / "entradas", data)
    code, out, message = generate(tmp_path, case, spec)
    assert code == 2
    assert out["code"] == "INPUT_SCHEMA"
    assert "- SPEC-C03 families[0].demand[0].flow_vph" in message
    assert not (tmp_path / "datos").exists()


def test_a_bad_seed_is_a_syntax_error_for_argparse(tmp_path: Path) -> None:
    case, spec = write_inputs(tmp_path / "entradas")
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        [
            sys.executable,
            "-m",
            "semaforo",
            "scenarios",
            "generate",
            "--case",
            str(case),
            "--spec",
            str(spec),
            "--seed",
            "-3",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2
    assert "--seed" in result.stderr
