"""Ensayo de sensibilidad de QA01 a QA10 (DEV10, decisión D6).

Para cada QA, se rompe a propósito, de a una vez, una de las reglas que protege y se corren las
pruebas clave del catálogo (``tests/qa_catalog.py``). Si alguna falla, el cambio se **detectó**; si
todas pasan, **sobrevivió**: la prueba no protege esa regla.

ADVERTENCIA: modifica archivos de ``src/`` y los restaura al terminar (también ante Ctrl+C). No lo
use mientras edita el código ni en paralelo con otro ensayo. Se niega a correr si algún archivo
que va a modificar tiene cambios sin guardar en git.

Uso:  .venv\\Scripts\\python.exe scripts\\sensibilidad.py [--out ruta.json] [--only QA03,QA07]
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from qa_catalog import CATALOG, resolve  # noqa: E402

SRC = ROOT / "src" / "semaforo"
TIMEOUT_S = 600


@dataclass(frozen=True)
class Mutation:
    qa_id: str
    file: str
    old: str
    new: str
    what: str


M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    # QA01: identificadores únicos y referencias que existen
    M(
        "QA01",
        "dominio/case_rules.py",
        "if value not in first:",
        "if True:",
        "un ID repetido ya no se detecta",
    ),
    M(
        "QA01",
        "dominio/case_rules.py",
        "elif slot_id not in by_id:",
        "elif False:",
        "un tramo inexistente ya no se detecta",
    ),
    M(
        "QA01",
        "dominio/case_rules.py",
        "if slot_id in seen:",
        "if False:",
        "un tramo repetido en un grupo ya no se detecta",
    ),
    # QA02: tick, límites y ventanas
    M(
        "QA02",
        "dominio/case_rules.py",
        "return abs(ratio - round(ratio)) <= TICK_EPSILON * max(1.0, abs(ratio))",
        "return True",
        "todo valor se toma por múltiplo del tick",
    ),
    M(
        "QA02",
        "dominio/case_rules.py",
        "return abs(ratio - round(ratio)) <= TICK_EPSILON * max(1.0, abs(ratio))",
        "return abs(ratio - round(ratio)) <= 0.5",
        "el tick se verifica con un margen enorme",
    ),
    # QA03: flujo en veh/h y proporciones
    M(
        "QA03",
        "datos/normalizer.py",
        "flow = SECONDS_PER_HOUR * total / duration_s",
        "flow = SECONDS_PER_HOUR * total",
        "el flujo no se divide entre la duración",
    ),
    M(
        "QA03",
        "datos/normalizer.py",
        "SECONDS_PER_HOUR = 3600",
        "SECONDS_PER_HOUR = 3000",
        "se usa una hora de 3000 s",
    ),
    M(
        "QA03",
        "datos/normalizer.py",
        "(None if total == 0 else count / total)",
        "(None if total == 0 else count / (total + 1))",
        "las proporciones no suman 1",
    ),
    # QA04: defectos del archivo de aforos
    M("QA04", "datos/importer.py", "if key in keys:", "if False:", "un duplicado se acepta"),
    M(
        "QA04",
        "datos/importer.py",
        "if INTEGER.fullmatch(text) is None:",
        "if False:",
        "un conteo negativo o con decimales se acepta",
    ),
    M(
        "QA04",
        "datos/importer.py",
        "if moment.tzinfo is None:",
        "if False:",
        "una fecha sin zona horaria se acepta",
    ),
    M(
        "QA04",
        "datos/importer.py",
        "if start is not None and end is not None and end <= start:",
        "if False:",
        "un periodo invertido se acepta",
    ),
    # QA05: cero y faltante
    M(
        "QA05",
        "datos/normalizer.py",
        "(None if total == 0 else count / total)",
        "(0.0 if total == 0 else count / total)",
        "la composición de un cero se vuelve 0.0",
    ),
    M(
        "QA05",
        "datos/normalizer.py",
        "    if missing:\n",
        "    if False:\n",
        "un periodo con faltantes se toma por completo",
    ),
    # QA06: error absoluto, relativo y cobertura
    M(
        "QA06",
        "datos/quality.py",
        "if control == 0:",
        "if False:",
        "un control en cero da un error relativo",
    ),
    M(
        "QA06",
        "datos/quality.py",
        "abs(difference) / control",
        "abs(difference) / (control + 1)",
        "el error relativo se calcula mal",
    ),
    M(
        "QA06",
        "datos/quality.py",
        "difference = observed - control",
        "difference = control - observed",
        "el signo del error se invierte",
    ),
    M(
        "QA06",
        "datos/coverage.py",
        "    coverage = covered_s / window_s\n    return Coverage(",
        "    coverage = 1.0\n    return Coverage(",
        "la cobertura siempre es 1",
    ),
    # QA07: éxito solo si el proceso y las salidas son válidos
    M(
        "QA07",
        "simulacion/runner.py",
        'case "sumo_error":',
        'case "nunca":',
        "un error de SUMO se toma por éxito",
    ),
    M(
        "QA07",
        "simulacion/runner.py",
        "if len(trips) != inserted:",
        "if False:",
        "viajes que no coinciden con los insertados se aceptan",
    ),
    # QA08: fallos sin métricas
    M(
        "QA08",
        "simulacion/runner.py",
        "if inserted > loaded:",
        "if False:",
        "más insertados que cargados se acepta",
    ),
    M(
        "QA08",
        "simulacion/runner.py",
        "if unfinished != running:",
        "if False:",
        "viajes sin terminar incoherentes se aceptan",
    ),
    M(
        "QA08",
        "simulacion/runner.py",
        'case "timeout":',
        'case "nunca":',
        "el tiempo agotado deja de ser un fallo",
    ),
    # QA09: réplica
    M(
        "QA09",
        "simulacion/replica.py",
        "if a.seed != b.seed:",
        "if False:",
        "otra semilla se toma por réplica",
    ),
    M(
        "QA09",
        "simulacion/replica.py",
        'SKIPPED_ELEMENTS: dict[str, frozenset[str]] = {"statistics.xml"',
        "SKIPPED_ELEMENTS: dict[str, frozenset[str]] = {} and {'statistics.xml'",
        "los tiempos de reloj cuentan como resultado",
    ),
    M(
        "QA09",
        "simulacion/replica.py",
        "if tag_a != tag_b or set(attrs_a) != set(attrs_b):",
        "if False:",
        "una estructura distinta se toma por igual",
    ),
    # QA10: seguridad
    M(
        "QA10",
        "simulacion/tripinfo.py",
        'events=("start", "end"), forbid_dtd=True',
        'events=("start", "end"), forbid_dtd=False',
        "el tripinfo admite DTD",
    ),
    M(
        "QA10",
        "caso/xml_input.py",
        "root = fromstring(data, forbid_dtd=True)",
        "root = fromstring(data, forbid_dtd=False)",
        "la red admite DTD",
    ),
    M(
        "QA10",
        "trazabilidad/paths.py",
        'if any(part in ("", ".", "..") for part in value.split("/")):',
        "if False:",
        "una ruta con .. se acepta",
    ),
    M(
        "QA10",
        "datos/importer.py",
        "if path.is_symlink() or path.is_junction():",
        "if False:",
        "el importador sigue enlaces",
    ),
    M(
        "QA10",
        "simulacion/process.py",
        "stdin=subprocess.DEVNULL,",
        "stdin=subprocess.DEVNULL, shell=True,",
        "SUMO se lanza por un shell",
    ),
    M(
        "QA10",
        "trazabilidad/retry.py",
        "run_id = check_run_id(spec.retry_of)",
        "run_id = spec.retry_of",
        "un identificador de reintento con .. se acepta",
    ),
)


def tests_of(qa_id: str) -> list[str]:
    qa = next(item for item in CATALOG if item.qa_id == qa_id)
    return [node for entry in qa.key_tests for node in resolve(entry)]


def clean(paths: list[Path]) -> bool:
    status = subprocess.run(  # noqa: S603
        ["git", "status", "--porcelain", "--", *map(str, paths)],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    )
    return not status.stdout.strip()


def detected(nodes: list[str]) -> bool:
    """True si alguna prueba clave falla (o se cuelga) con el cambio puesto."""
    try:
        run = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *nodes],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return True
    return run.returncode != 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--out", type=Path, default=None, help="archivo JSON con el resultado")
    parser.add_argument("--only", default=None, help="QA a ensayar, separados por coma")
    arguments = parser.parse_args()
    chosen = set(arguments.only.split(",")) if arguments.only else {qa.qa_id for qa in CATALOG}
    files = sorted({SRC / mutation.file for mutation in MUTATIONS if mutation.qa_id in chosen})
    if not clean(files):
        print("Hay cambios sin guardar en los archivos a modificar; guárdelos antes.")
        return 2
    originals = {path: path.read_bytes() for path in files}
    results: list[dict[str, object]] = []
    try:
        for mutation in MUTATIONS:
            if mutation.qa_id not in chosen:
                continue
            path = SRC / mutation.file
            text = originals[path].decode("utf-8")
            if text.count(mutation.old) != 1:
                count = text.count(mutation.old)
                print(f"SALTADA {mutation.qa_id}: «{mutation.old[:50]}» aparece {count} veces")
                results.append({**mutation.__dict__, "result": "skipped"})
                continue
            path.write_bytes(text.replace(mutation.old, mutation.new).encode("utf-8"))
            try:
                found = detected(tests_of(mutation.qa_id))
            finally:
                path.write_bytes(originals[path])
            verdict = "detected" if found else "survived"
            print(
                f"{mutation.qa_id} {verdict.upper():9} {mutation.file}: {mutation.what}", flush=True
            )
            results.append({**mutation.__dict__, "result": verdict})
    finally:
        for path, data in originals.items():
            path.write_bytes(data)
    survivors = [item for item in results if item["result"] == "survived"]
    skipped = [item for item in results if item["result"] == "skipped"]
    print(
        f"cambios ensayados: {len(results) - len(skipped)}; detectados: "
        f"{sum(1 for item in results if item['result'] == 'detected')}; "
        f"sobrevivieron: {len(survivors)}; saltados: {len(skipped)}"
    )
    if arguments.out is not None:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date_utc": datetime.now(UTC).isoformat(), "results": results}
        arguments.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 1 if survivors or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
