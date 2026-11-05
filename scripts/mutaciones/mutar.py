"""Ensayo de mutaciones de a una (nunca en paralelo): rompe una regla, corre las pruebas, restaura.

Uso: python mutar.py <archivo_de_mutaciones.py>
El archivo define TESTS (lista de rutas de pruebas) y MUTATIONS (lista de (archivo, viejo, nuevo, nombre)).
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def load(path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location("muts", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"no se puede leer {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load(sys.argv[1])
    survived: list[str] = []
    skipped: list[str] = []
    for relative, old, new, name in module.MUTATIONS:
        path = ROOT / relative
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            skipped.append(f"{name}: el texto aparece {text.count(old)} veces")
            continue
        path.write_bytes(text.replace(old, new).encode("utf-8"))
        try:
            run = subprocess.run(
                [str(PYTHON), "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *module.TESTS],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            verdict_code = run.returncode
        except subprocess.TimeoutExpired:
            verdict_code = 99  # se colgo: la mutacion se considera detectada por tiempo
        finally:
            path.write_bytes(original)
        verdict = "detectada" if verdict_code != 0 else "SOBREVIVIO"
        print(f"{verdict:11} {name}", flush=True)
        if verdict_code == 0:
            survived.append(name)
    print(
        f"\nTotal: {len(module.MUTATIONS)}  sobrevivieron: {len(survived)}  omitidas: {len(skipped)}"
    )
    for item in survived:
        print("  SOBREVIVIO:", item)
    for item in skipped:
        print("  OMITIDA:", item)
    return 1 if survived or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
