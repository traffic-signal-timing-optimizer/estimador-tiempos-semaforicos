"""Ensayo de daño de DEV31 F4: se rompe el código nuevo a propósito y alguna prueba debe fallar.

Cada mutación cambia un fragmento, corre las pruebas que deben notarlo y devuelve el archivo a su
estado original (se comprueba con su huella). Solo toca `src/`; usa solo bases temporales.
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST = ROOT / ".venv" / "Scripts" / "pytest.exe"
BD = ROOT / "src" / "semaforo" / "bd"
CONCILIATION = ("tests/integration/test_bd_conciliacion_sumo.py",)
CHOICE = ("tests/unit/test_bd_metricas.py",)


@dataclass(frozen=True)
class Mutation:
    name: str
    file: Path
    old: str
    new: str
    tests: tuple[str, ...]


M = Mutation
MUTATIONS = [
    M(
        "la conciliación no revisa los archivos",
        BD / "conciliacion.py",
        "        elif path.stat().st_size != size:",
        "        elif False:",
        CONCILIATION,
    ),
    M(
        "la conciliación no compara la huella",
        BD / "conciliacion.py",
        "        elif sha256_file(path) != digest:",
        "        elif False:",
        CONCILIATION,
    ),
    M(
        "la conciliación no cuenta los vehículos",
        BD / "conciliacion.py",
        '        found.compare(run_id, "vehículos", vehicles.get(run_id, 0), expected[0])',
        "        pass",
        CONCILIATION,
    ),
    M(
        "la conciliación no cuenta los de la cohorte",
        BD / "conciliacion.py",
        '        found.compare(run_id, "vehículos de la cohorte", cohort.get(run_id, 0), expected[1])',
        "        pass",
        CONCILIATION,
    ),
    M(
        "la conciliación no cuenta los eventos",
        BD / "conciliacion.py",
        'found.compare(run_id, "eventos del registro de SUMO", events.get(run_id, 0), expected[2])',
        "pass",
        CONCILIATION,
    ),
    M(
        "la conciliación no recalcula la demora",
        BD / "conciliacion.py",
        '        found.compare(run_id, f"demora y métricas: {name}", stored[name], value)',
        "        pass",
        CONCILIATION,
    ),
    M(
        "la conciliación acepta cualquier diferencia",
        BD / "conciliacion.py",
        '    elif found.items:\n        status = "different"',
        '    elif False:\n        status = "different"',
        CONCILIATION,
    ),
    M(
        "la conciliación no mira la cola segundo a segundo",
        BD / "conciliacion.py",
        '        found.compare(run_id, "filas de cola segundo a segundo", queue.get(run_id, 0), expected)',
        "        pass",
        CONCILIATION,
    ),
    M(
        "se mide con un protocolo cuya zona es más amplia",
        BD / "metricas.py",
        "    candidates = [p for p in protocols.values() if zone_edges(p) == edges]",
        "    candidates = [p for p in protocols.values() if zone_edges(p) >= edges]",
        CHOICE,
    ),
    M(
        "se elige un protocolo cualquiera cuando hay varios",
        BD / "metricas.py",
        "    if len(candidates) == 1:\n        return candidates[0], None",
        "    if candidates:\n        return candidates[0], None",
        CHOICE,
    ),
    M(
        "la corrida de una búsqueda no usa el protocolo de su búsqueda",
        BD / "metricas.py",
        "        protocol = context.protocols.get(search.protocol_id)",
        "        protocol = next(iter(context.protocols.values()), None)",
        CONCILIATION,
    ),
    M(
        "se vuelven a publicar las métricas que ya existen",
        BD / "metricas.py",
        "    if published.exists():\n        return _already(published, run_id)",
        "    if False:\n        return _already(published, run_id)",
        CONCILIATION,
    ),
    M(
        "se miden corridas que no terminaron bien",
        BD / "metricas.py",
        '    if manifest.status != "succeeded":',
        "    if False:",
        CHOICE,
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
    only = sys.argv[1:]
    chosen = [m for m in MUTATIONS if not only or any(o in m.name for o in only)]
    survivors: list[str] = []
    for mutation in chosen:
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
    print(f"\n{len(chosen) - len(survivors)} de {len(chosen)} detectadas")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
