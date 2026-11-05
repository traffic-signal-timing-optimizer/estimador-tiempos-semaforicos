"""Verifica la evidencia de una búsqueda publicada, sin escribir nada (auditoría A01 y A06).

Comprueba una etiqueta de ``datos/derivados/referencias`` contra la bitácora con que se hizo y las
carpetas de entradas y corridas, y dice qué identificador tendría hoy esa búsqueda. Con
``--recalcular`` vuelve a medir cada corrida con el protocolo dado (unos 2 s por corrida).

Uso, desde la carpeta raíz del proyecto, con el piloto de DEV14 como ejemplo:

    .venv\\Scripts\\python.exe scripts\\verificar_busqueda.py ^
        --etiqueta datos\\derivados\\referencias\\caso-001\\20261103T163554Z_decb039e ^
        --bitacora datos\\evidencia\\piloto-dev14-v1\\bitacora.jsonl ^
        --caso datos\\casos\\caso-001\\case.json ^
        --protocolo datos\\derivados\\protocolos\\caso-001\\borrador-dev14-piloto.json ^
        --escenario datos\\escenarios\\caso-001\\ESC-SINT-001.json ^
        --recalcular

Sale con 0 si todo cuadra y con 1 si hay problemas. No usa SUMO ni modifica ningún archivo.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semaforo.caso.case_validation import read_case  # noqa: E402
from semaforo.caso.json_input import read_json  # noqa: E402
from semaforo.dominio.protocol import parse_protocol  # noqa: E402
from semaforo.referencias.evidence import verify_search_evidence  # noqa: E402
from semaforo.simulacion.demand_inputs import read_scenario  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", maxsplit=1)[0])
    parser.add_argument("--etiqueta", type=Path, required=True, help="carpeta de la etiqueta")
    parser.add_argument("--bitacora", type=Path, required=True, help="bitácora de la búsqueda")
    parser.add_argument("--caso", type=Path, required=True, help="case.json del caso")
    parser.add_argument("--protocolo", type=Path, required=True, help="protocolo de la búsqueda")
    parser.add_argument("--escenario", type=Path, required=True, help="escenario de la búsqueda")
    parser.add_argument("--datos", type=Path, default=ROOT / "datos", help="carpeta de trabajo")
    parser.add_argument("--recalcular", action="store_true", help="volver a medir cada corrida")
    parser.add_argument("--json", action="store_true", help="escribir el informe como JSON")
    arguments = parser.parse_args()

    case = read_case(arguments.caso)
    report = verify_search_evidence(
        arguments.etiqueta,
        journal=arguments.bitacora,
        inputs_root=arguments.datos / "derivados" / "entradas",
        runs_root=arguments.datos / "ejecuciones",
        case=case,
        protocol=parse_protocol(read_json(arguments.protocolo, "protocolo")),
        scenario=read_scenario(arguments.escenario, case),
        recompute=arguments.recalcular,
    )
    if arguments.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
    else:
        print(f"Etiqueta {report.label_id} (identidad {report.identity_version})")
        print(
            f"  corridas: {report.runs}; carpetas de entradas verificadas: {report.input_folders}"
        )
        print(
            f"  versión de SUMO: {report.sumo_version}; métricas recalculadas: {report.recomputed}"
        )
        print(f"  identificador con la identidad 2.0.0: {report.expected_search_run_id}")
        for problem in report.problems:
            print(f"  PROBLEMA: {problem}")
        print("TODO CUADRA" if report.ok else "HAY PROBLEMAS")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
