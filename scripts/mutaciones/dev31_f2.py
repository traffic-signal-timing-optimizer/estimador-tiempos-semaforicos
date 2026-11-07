"""Ensayo de daño de DEV31 F2: se rompe el código a propósito y se comprueba que alguna prueba falla.

Cada mutación cambia un fragmento, corre las pruebas que deben notarlo y devuelve el archivo a su
estado original (se comprueba con su huella). Solo toca `src/`; no escribe en `datos/`.
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST = ROOT / ".venv" / "Scripts" / "pytest.exe"
SRC = ROOT / "src" / "semaforo"
UNIT = "tests/unit"
NEW_SUMO = "tests/integration/test_run_metrics_sumo.py"


@dataclass(frozen=True)
class Mutation:
    name: str
    file: Path
    old: str
    new: str
    tests: tuple[str, ...]


M = Mutation
FCD_TESTS = (f"{UNIT}/test_fcd_compression.py",)
ENV_TESTS = (f"{UNIT}/test_environment.py",)
SERIES_TESTS = (f"{UNIT}/test_zone_metrics.py",)
PUBLISHED = (f"{UNIT}/test_published_metrics.py",)
REPLICA = (f"{UNIT}/test_replica.py",)
SUMO_NEW = (NEW_SUMO, "-k", "a_new_run_has_a_compressed_fcd")

MUTATIONS = [
    M("gzip con fecha", SRC / "simulacion/runner.py", "mtime=0)", "mtime=1)", FCD_TESTS),
    M(
        "no borra la FCD original",
        SRC / "simulacion/runner.py",
        "    source.unlink()\n",
        "    pass\n",
        FCD_TESTS,
    ),
    M(
        "deja la comprimida si no puede borrar",
        SRC / "simulacion/runner.py",
        "        target.unlink(missing_ok=True)  # no se deja la FCD dos veces\n",
        "        pass\n",
        FCD_TESTS,
    ),
    M(
        "la corrida no anota el equipo",
        SRC / "simulacion/runner.py",
        "            **capture_environment(),\n",
        "",
        SUMO_NEW,
    ),
    M(
        "la serie marca todo como en ventana",
        SRC / "evaluacion/metrics.py",
        "self.in_window.append(index is not None)",
        "self.in_window.append(True)",
        SERIES_TESTS,
    ),
    M(
        "la serie suma uno",
        SRC / "evaluacion/metrics.py",
        "self.series[name].append(count)",
        "self.series[name].append(count + 1)",
        SERIES_TESTS,
    ),
    M(
        "la réplica compara el gz byte a byte",
        SRC / "simulacion/replica.py",
        'name.endswith((".xml", ".xml.gz"))',
        'name.endswith(".xml")',
        REPLICA,
    ),
    M(
        "la réplica no limita el gz descomprimido",
        SRC / "simulacion/replica.py",
        "if self._left < 0:",
        "if False:",
        REPLICA,
    ),
    M(
        "las métricas leídas no se cotejan con el manifiesto",
        SRC / "evaluacion/published_metrics.py",
        "metrics.run_id == manifest.run_id == folder.name\n        and ",
        "True\n        and ",
        PUBLISHED,
    ),
    M(
        "las series se escriben una línea por número",
        SRC / "evaluacion/published_metrics.py",
        "if not any(isinstance(item, dict | list) for item in elements):",
        "if False:",
        PUBLISHED,
    ),
    M(
        "se pisan las métricas ya publicadas",
        SRC / "evaluacion/published_metrics.py",
        "    except FileExistsError as error:",
        "    except ZeroDivisionError as error:",
        PUBLISHED,
    ),
    M(
        "code_modified al revés",
        SRC / "simulacion/environment.py",
        '"true" if changes else "false"',
        '"false" if changes else "true"',
        ENV_TESTS,
    ),
    M(
        "los textos no se recortan",
        SRC / "simulacion/environment.py",
        "[:MAX_TEXT_CHARS]",
        "",
        ENV_TESTS,
    ),
    M(
        "una ubicación inválida se toma por local",
        SRC / "simulacion/environment.py",
        "    else:\n        return {}\n",
        '    else:\n        return {"location": "local"}\n',
        ENV_TESTS,
    ),
    M(
        "memoria total = memoria disponible",
        SRC / "simulacion/resources.py",
        '_physical_memory("ullTotalPhys", "MemTotal")',
        '_physical_memory("ullAvailPhys", "MemAvailable")',
        ENV_TESTS,
    ),
    M(
        "la revisión del espacio no mira las métricas",
        SRC / "app/integrity.py",
        '        ("metrics", workspace / METRICS, lambda f: _check(read_run_metrics, f), True),\n',
        "",
        PUBLISHED,
    ),
    M(
        "evaluate_run solo lee fcd.xml",
        SRC / "evaluacion/run_metrics.py",
        "fcd = fcd_file(outputs)",
        "fcd = outputs / FCD",
        SUMO_NEW,
    ),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests(tests: tuple[str, ...]) -> int:
    completed = subprocess.run(
        [str(PYTEST), "-q", "-x", "-p", "no:cacheprovider", *tests],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return completed.returncode


def main() -> int:
    survivors: list[str] = []
    for mutation in MUTATIONS:
        original = mutation.file.read_bytes()
        before = hashlib.sha256(original).hexdigest()
        text = original.decode("utf-8")
        if text.count(mutation.old) != 1:
            print(f"NO APLICA ({text.count(mutation.old)} coincidencias): {mutation.name}")
            survivors.append(mutation.name)
            continue
        try:
            mutation.file.write_bytes(text.replace(mutation.old, mutation.new).encode("utf-8"))
            code = run_tests(mutation.tests)
        finally:
            mutation.file.write_bytes(original)
        if digest(mutation.file) != before:
            print(f"ERROR: {mutation.file} no volvió a su estado original")
            return 2
        verdict = "detectada" if code != 0 else "SOBREVIVE"
        print(f"{verdict}: {mutation.name}", flush=True)
        if code == 0:
            survivors.append(mutation.name)
    print(f"\n{len(MUTATIONS) - len(survivors)} de {len(MUTATIONS)} detectadas")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
