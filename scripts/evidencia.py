"""Genera el registro de ejecución de pruebas de QA01 a QA10 (DEV10, decisiones D3 a D5).

Corre toda la suite con ``pytest``, lee el resultado y escribe:

- ``docs/evidencia/<fecha>_<commit>/``: ``informe.md`` y ``registro.json``, **sin rutas de la
  máquina** (se versiona: el repositorio es público);
- ``datos/reportes/evidencia/<fecha>_<commit>/``: el registro completo de pytest (``pytest.log`` y
  ``junit.xml``; no se versiona).

Con ``--sensibilidad`` corre antes el ensayo de ``scripts/sensibilidad.py`` (varios minutos) y lo
incluye. Se niega a correr con cambios sin guardar, salvo ``--allow-dirty``, para que el commit que
queda registrado sea el que se probó. Devuelve 1 si hay fallos críticos.

Uso:  .venv\\Scripts\\python.exe scripts\\evidencia.py [--sensibilidad] [--allow-dirty]
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from evidence_lib import (  # noqa: E402
    classify,
    command_text,
    environment_facts,
    fixtures_digest,
    git_state,
    parse_junit,
    render_markdown,
    scrub,
)
from semaforo.simulacion.resources import available_memory_bytes  # noqa: E402
from semaforo.simulacion.runner import find_sumo, sumo_version  # noqa: E402


def sumo_text() -> str | None:
    try:
        return sumo_version(find_sumo())
    except Exception:
        return None


def run_sensitivity(out: Path) -> dict[str, int] | None:
    run = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "sensibilidad.py"), "--out", str(out)],
        cwd=ROOT,
        check=False,
    )
    if not out.is_file():
        print(f"El ensayo de sensibilidad no produjo resultado (código {run.returncode}).")
        return None
    results = json.loads(out.read_text(encoding="utf-8"))["results"]
    return {
        "ensayados": sum(1 for item in results if item["result"] != "skipped"),
        "detectados": sum(1 for item in results if item["result"] == "detected"),
        "sobrevivieron": sum(1 for item in results if item["result"] == "survived"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--sensibilidad", action="store_true", help="incluye el ensayo")
    parser.add_argument("--allow-dirty", action="store_true", help="permite cambios sin guardar")
    arguments = parser.parse_args()

    commit, dirty = git_state()
    if dirty and not arguments.allow_dirty:
        print("Hay cambios sin guardar: guarde (commit) antes de generar la evidencia.")
        return 2
    now = datetime.now(UTC)
    stamp = f"{now:%Y%m%dT%H%M%SZ}_{commit[:8]}"
    public = ROOT / "docs" / "evidencia" / stamp
    private = ROOT / "datos" / "reportes" / "evidencia" / stamp
    private.mkdir(parents=True)

    sensitivity = run_sensitivity(private / "sensibilidad.json") if arguments.sensibilidad else None

    junit = private / "junit.xml"
    with (private / "pytest.log").open("w", encoding="utf-8") as log:
        run = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={junit}",
                "-rs",
                "tests",
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if not junit.is_file():
        print(
            f"pytest no produjo resultado (código {run.returncode}); vea {private / 'pytest.log'}"
        )
        return 2

    report = classify(
        parse_junit(junit),
        generated_at=now.isoformat(timespec="seconds"),
        command=command_text(),
        commit=commit,
        dirty=dirty,
        environment=environment_facts(sumo_text(), available_memory_bytes()),
        fixtures=fixtures_digest(),
        sensitivity=sensitivity,
    )
    public.mkdir(parents=True)
    (public / "registro.json").write_text(
        scrub(report.model_dump_json(indent=2)) + "\n", encoding="utf-8", newline="\n"
    )
    (public / "informe.md").write_text(
        scrub(render_markdown(report)), encoding="utf-8", newline="\n"
    )
    print(f"Resultado de la puerta: {report.gate.result}")
    print(f"Resumen versionable: {public.relative_to(ROOT)}")
    print(f"Registro completo (no versionado): {private.relative_to(ROOT)}")
    return 1 if report.gate.critical_failures else 0


if __name__ == "__main__":
    sys.exit(main())
