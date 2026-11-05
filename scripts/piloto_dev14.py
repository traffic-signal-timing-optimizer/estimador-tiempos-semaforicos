"""Repite el piloto de DEV14 en una carpeta nueva (auditoría A06).

Hace lo que hizo el piloto original: buscar planes con SUMO para un escenario, elegir finalistas y
publicar la etiqueta. Todo lo que escribe va a ``--salida``; de ``--datos`` solo lee el caso, el
escenario, el protocolo base y el programa vigente. **No escribe en ``datos/``.**

Dos tamaños:

- ``--pequeno``: 2 candidatos y el vigente, 1 semilla de búsqueda, 1 finalista con 2 semillas.
  Unas 5 corridas, de 1 a 2 minutos. Sirve para comprobar que el procedimiento funciona.
- completo (sin ``--pequeno``): las condiciones del piloto original (decisiones F0-1, F0-2, F0-4,
  F0-8 y F0-9 de DEV14): 20 candidatos más el vigente, semillas de búsqueda 1001 a 1003, 3
  finalistas con las semillas 2001 a 2013. 102 corridas, unos 7 minutos y 2,5 GB.

Cómo distinguir el original de una réplica: la réplica escribe ``replica.json`` en su carpeta con
el tamaño, los parámetros, el commit del código, las versiones de Python y de SUMO y los
identificadores de la búsqueda. El original (``datos/derivados/referencias/caso-001/
20261103T163554Z_decb039e``) se hizo con la identidad 1.0.0; con la actual, la réplica completa
debe llamarse ``search-67fe2aeaddf3b9c6`` (``--esperado`` lo comprueba).

Uso, desde la carpeta raíz del proyecto:

    .venv\\Scripts\\python.exe scripts\\piloto_dev14.py --salida D:\\replica-pequena --pequeno

La salida dice cómo comprobar la réplica con ``scripts\\verificar_busqueda.py``. Se puede relanzar
con la misma ``--salida`` para continuar una réplica interrumpida (sigue su bitácora).

Se niega a escribir dentro de ``--datos``, y a usar una ``--salida`` con otro contenido.
"""

import argparse
import ctypes
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semaforo.app.doctor_probe import memory_bytes  # noqa: E402
from semaforo.caso.case_validation import read_case  # noqa: E402
from semaforo.caso.network_map import build_network_map  # noqa: E402
from semaforo.dominio.adjust_order import parse_adjust_order  # noqa: E402
from semaforo.dominio.feasibility import prepare  # noqa: E402
from semaforo.dominio.protocol import Protocol, parse_protocol  # noqa: E402
from semaforo.referencias.evaluation import (  # noqa: E402
    SearchSetup,
    free_memory_gate,
    identity_digest,
    run_search,
)
from semaforo.referencias.label import publish_label, read_label  # noqa: E402
from semaforo.referencias.search import generate_candidates  # noqa: E402
from semaforo.simulacion.demand_inputs import (  # noqa: E402
    read_routes,
    read_scenario,
    read_vehicle_types,
)
from semaforo.simulacion.runner import find_sumo, sumo_version  # noqa: E402

BELOW_NORMAL = 0x00004000  # lo heredan los procesos de SUMO
CASE = "caso-001"
SCENARIO = "ESC-SINT-001"
PILOT_PROGRAM = "20261031T041338Z_63437585"
BASE_PROTOCOL = "borrador-dev19-aproximacion.json"
SUMO_OPTIONS = {"lateral-resolution": 0.8, "collision.check-junctions": True}
ORIGINAL_SEARCH_ID = "search-67fe2aeaddf3b9c6"
MIB = 1024 * 1024


def protocol_of(small: bool, base: dict[str, Any]) -> Protocol:
    """El protocolo del piloto sobre el borrador de DEV19 (mismo texto que el original)."""
    data = dict(base)
    data["metric_definition"] = base["metric_definition"].replace(
        "(DEV19)", "(DEV14 F4, piloto; misma métrica que DEV19)", 1
    )
    if small:
        data.update(
            protocol_id="CASO001_DEV14_PILOTO_PEQUENO",
            search_budget=2,
            sampling_attempt_limit=2000,
            finalist_count=1,
            tie_epsilon_s=2.0,
            seeds={"search": [1001], "finalists": [2001, 2002], "final": [3001]},
        )
    else:
        data.update(
            protocol_id="CASO001_DEV14_PILOTO",
            search_budget=20,
            sampling_attempt_limit=2000,
            finalist_count=3,
            tie_epsilon_s=2.0,
            seeds={
                "search": [1001, 1002, 1003],
                "finalists": list(range(2001, 2014)),
                "final": list(range(3001, 3014)),
            },
        )
    return parse_protocol(data)


def git_commit() -> dict[str, object]:
    """Commit del código y si había cambios sin guardar; vacío si no se puede saber."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "changes_not_committed": None}
    return {"commit": head, "changes_not_committed": bool(status.strip())}


def prepare_output(output: Path, data_root: Path) -> None:
    """Crea la carpeta de salida o reconoce una réplica anterior; si no, se niega."""
    resolved = output.resolve()
    if resolved == data_root or data_root in resolved.parents or resolved in data_root.parents:
        raise SystemExit("--salida no puede estar dentro de --datos ni contenerlo")
    if output.exists():
        if not (output / "replica.json").exists() and any(output.iterdir()):
            raise SystemExit(f"{output} existe y no es una réplica anterior: use otra --salida")
        return
    output.mkdir(parents=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", maxsplit=1)[0])
    parser.add_argument("--salida", type=Path, required=True, help="carpeta nueva de la réplica")
    parser.add_argument("--datos", type=Path, default=ROOT / "datos", help="carpeta de insumos")
    parser.add_argument("--pequeno", action="store_true", help="la réplica de unas 5 corridas")
    parser.add_argument("--procesos", type=int, default=0, help="corridas a la vez (0: 2 o 4)")
    parser.add_argument(
        "--memoria-minima-mb", type=int, default=1500, help="no lanza corridas con menos libre"
    )
    parser.add_argument("--esperado", help="identificador de búsqueda que debe dar la réplica")
    arguments = parser.parse_args()

    if sys.platform == "win32":
        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), BELOW_NORMAL)

    data_root = arguments.datos.resolve()
    output: Path = arguments.salida
    prepare_output(output, data_root)
    workspace = output / "datos"
    case_dir = data_root / "casos" / CASE
    scenarios = data_root / "escenarios" / CASE
    program = data_root / "derivados" / "programas" / CASE / PILOT_PROGRAM
    base = json.loads(
        (data_root / "derivados" / "protocolos" / CASE / BASE_PROTOCOL).read_text("utf-8")
    )

    case = read_case(case_dir / "case.json")
    order = parse_adjust_order(
        json.loads((case_dir / "orden_de_ajuste.json").read_text(encoding="utf-8"))
    )
    protocol = protocol_of(arguments.pequeno, base)
    scenario = read_scenario(scenarios / f"{SCENARIO}.json", case)
    binary = find_sumo()
    setup = SearchSetup(
        case=case,
        case_dir=case_dir,
        network_map=build_network_map(case_dir / "osm.net.xml.gz", case),
        scenario=scenario,
        routes=read_routes(scenarios / "rutas.json"),
        vehicle_types=read_vehicle_types(scenarios / "tipos.json"),
        protocol=protocol,
        programs_root=workspace / "derivados" / "programas",
        inputs_root=workspace / "derivados" / "entradas",
        runs_root=workspace / "ejecuciones",
        sumo_options=SUMO_OPTIONS,
        sumo=binary,
    )
    current = {
        slot["id"]: slot["duration_s"]
        for slot in json.loads((program / "tramos.json").read_text(encoding="utf-8"))["slots"]
    }
    candidates = generate_candidates(
        prepare(case, order),
        scenario_id=scenario.scenario_id,
        budget=protocol.search_budget,
        attempt_limit=protocol.sampling_attempt_limit,
        seed=protocol.seeds.search[0],
        current_plan=current,
    )

    gate = free_memory_gate(arguments.memoria_minima_mb * MIB, lambda: memory_bytes()[1])
    workers = arguments.procesos or (2 if arguments.pequeno else 4)
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    outcome = run_search(
        setup, candidates, output / "bitacora.jsonl", workers=workers, can_start=gate
    )
    elapsed = time.perf_counter() - started

    label_folder = None
    if outcome.selection is not None:
        label_folder = publish_label(workspace, setup, outcome)
    search_id = f"search-{identity_digest(outcome.identity)}"
    label = None if label_folder is None else read_label(label_folder).label
    summary: dict[str, object] = {
        "kind": "replica",
        "size": "pequeno" if arguments.pequeno else "completo",
        "started_at": started_at.isoformat(timespec="seconds"),
        "elapsed_s": round(elapsed, 1),
        "command": " ".join(sys.argv),
        "code": git_commit(),
        "python": platform.python_version(),
        "system": f"{platform.system()} {platform.release()}",
        "sumo": sumo_version(binary),
        "case_id": case.case_id,
        "scenario_id": scenario.scenario_id,
        "protocol_id": protocol.protocol_id,
        "search_budget": protocol.search_budget,
        "seeds": protocol.seeds.model_dump(mode="json"),
        "workers": workers,
        "simulation_count": outcome.simulation_count,
        "interrupted": outcome.interrupted,
        "search_run_id": search_id,
        "label_id": None if label is None else label.label_id,
        "label_status": None if label is None else label.status,
        "label_folder": None if label_folder is None else str(label_folder.relative_to(output)),
        "original_search_id": ORIGINAL_SEARCH_ID,
        "same_id_as_original": search_id == ORIGINAL_SEARCH_ID,
    }
    (output / "replica.json").write_bytes(
        (json.dumps(summary, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    (output / "protocolo.json").write_bytes(
        (protocol.model_dump_json(indent=2) + "\n").encode("utf-8")
    )
    print(
        f"{outcome.simulation_count} corridas en {elapsed:.0f} s; búsqueda {search_id}; "
        f"etiqueta {'no publicada' if label is None else label.status}"
    )
    if label_folder is not None:
        print(
            "Para comprobar la réplica:\n"
            "  .venv\\Scripts\\python.exe scripts\\verificar_busqueda.py "
            f"--etiqueta {label_folder} --bitacora {output / 'bitacora.jsonl'} "
            f"--caso {case_dir / 'case.json'} --protocolo {output / 'protocolo.json'} "
            f"--escenario {scenarios / (SCENARIO + '.json')} --datos {workspace} --recalcular"
        )
    if arguments.esperado is not None and search_id != arguments.esperado:
        print(f"NO COINCIDE: se esperaba {arguments.esperado}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
