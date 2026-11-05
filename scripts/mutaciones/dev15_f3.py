r"""Mutaciones de DEV15 F3: traducción de los verdes de Webster a un plan de tramos (baselines.py).

Rompe a propósito, de a una vez, cada regla y corre las pruebas de baselines. Restaura el archivo
siempre. No corre si las pruebas fallan sin mutación. Uso: python scripts\mutaciones\dev15_f3.py [nombres]
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
B = "src/semaforo/referencias/baselines.py"
TESTS = ["tests/unit/test_baselines.py"]

MUTATIONS = [
    (
        B,
        "    if required is None:" + chr(10) + "        return lower",
        "    if False:" + chr(10) + "        return lower",
        "carril sin flujo exige verde",
    ),
    (
        B,
        "                lane_id: ratio * usable / path.y",
        "                lane_id: ratio * usable",
        "verde sin dividir por Y",
    ),
    (
        B,
        "    lower = {k: Fraction(case.slots[k].min_s) for k in own}",
        "    lower = {k: Fraction(0) for k in own}",
        "tramos sin su mínimo",
    ),
    (B, "    if not own:", "    if False:", "carril crítico sin tramo variable"),
    (B, "        and span[0] <= _span(lanes, other)[0]", "        and True", "interno sin inicio"),
    (B, "        and _span(lanes, other)[1] <= span[1]", "        and True", "interno sin fin"),
    (
        B,
        "            if missing > 0:",
        "            if False:",
        "lo que pide un carril interno se ignora",
    ),
    (
        B,
        "                lower[mine[0]] += missing",
        "                lower[mine[-1]] += missing",
        "lo interno al último tramo",
    ),
    (B, "    if extra < 0:", "    if False:", "verde crítico corto aceptado"),
    (
        B,
        "    target = min(own, key=lambda k: (served[k], -k))",
        "    target = max(own, key=lambda k: (served[k], -k))",
        "sobrante al tramo más compartido",
    ),
    (
        B,
        "    target = min(own, key=lambda k: (served[k], -k))",
        "    target = min(own, key=lambda k: (served[k], k))",
        "empate al primer tramo",
    ),
    (B, "    lower[target] += extra", "    pass", "sobrante perdido"),
    (B, "        if got < need:", "        if False:", "carril sin atender aceptado"),
    (
        B,
        "            value = math.floor(value / tick + Fraction(1, 2)) * tick",
        "            value = math.floor(value / tick) * tick",
        "redondeo hacia abajo",
    ),
    (
        B,
        "            value = math.floor(value / tick + Fraction(1, 2)) * tick",
        "            pass",
        "sin redondeo",
    ),
    (B, "        durations.update(split)", "        pass", "verdes críticos no se aplican"),
    (
        B,
        "            if violated:" + chr(10) + "                problems.append(",
        "            if False:" + chr(10) + "                problems.append(",
        "plan que incumple aceptado",
    ),
    (
        B,
        "            violated = check_plan(prepared, durations).violated",
        "            violated = ()",
        "sin revisar reglas del caso",
    ),
    (
        B,
        "        cycle_s=None if durations is None else math.fsum(durations.values()),",
        "        cycle_s=None,",
        "ciclo del plan no informado",
    ),
]


def tests_fail() -> bool:
    result = subprocess.run(
        [PY, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *TESTS],
        cwd=ROOT,
        capture_output=True,
        timeout=600,
        check=False,
    )
    return result.returncode != 0


def main() -> int:
    if tests_fail():
        print("las pruebas fallan sin mutación: el ensayo no vale")
        return 2
    wanted = set(sys.argv[1:])
    chosen = [m for m in MUTATIONS if not wanted or m[3] in wanted]
    survivors: list[str] = []
    skipped: list[str] = []
    for name, old, new, what in chosen:
        path = ROOT / name
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            skipped.append(what)
            continue
        changed = text.replace(old, new)
        if "bisect_right" in new:
            changed = changed.replace(
                "from bisect import bisect_left", "from bisect import bisect_left, bisect_right"
            )
        try:
            path.write_bytes(changed.encode("utf-8"))
            if not tests_fail():
                survivors.append(what)
        finally:
            path.write_bytes(original)
    applied = len(chosen) - len(skipped)
    print(f"aplicadas {applied}, detectadas {applied - len(survivors)}")
    print("sobreviven:", survivors)
    print("no aplican:", skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
