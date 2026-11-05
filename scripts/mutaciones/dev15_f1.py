r"""Mutaciones de DEV15 F1: parámetros, plan vigente, estructura y camino crítico (baselines.py).

Rompe a propósito, de a una vez, cada regla y corre las pruebas de baselines. Restaura el archivo
siempre. No corre si las pruebas fallan sin mutación. Uso: python scripts\mutaciones\dev15_f1.py [nombres]
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
B = "src/semaforo/referencias/baselines.py"
TESTS = ["tests/unit/test_baselines.py"]

MUTATIONS = [
    (B, 'GREEN = frozenset("Ggs")', 'GREEN = frozenset("Gs")', "g no cuenta como verde"),
    (
        B,
        "        if len(bounds) != BOUNDS or bounds[0] > bounds[1]:",
        "        if bounds[0] > bounds[1]:",
        "un solo límite de ciclo",
    ),
    (
        B,
        "        if len(bounds) != BOUNDS or bounds[0] > bounds[1]:",
        "        if len(bounds) != BOUNDS:",
        "límites al revés",
    ),
    (
        B,
        '        if self.status == "approved" and self.approval.especialista is None:',
        "        if False:",
        "aprobado sin especialista",
    ),
    (B, '        return self.status != "approved"', "        return True", "siempre provisional"),
    (
        B,
        "    if (parameters.case_id, parameters.case_version) != (case.case_id, case.case_version):",
        "    if False:",
        "parámetros de otro caso al leer",
    ),
    (
        B,
        "    if (manifest.case_id, manifest.case_version) != (case.case_id, case.case_version):",
        "    if False:",
        "programa de otro caso",
    ),
    (
        B,
        "    if [row.id for row in rows] != [slot.id for slot in case.slots]:",
        "    if False:",
        "tramos de otro caso",
    ),
    (
        B,
        "    if abs(cycle - parameters.current_plan.cycle_s) > CYCLE_TOLERANCE_S:",
        "    if False:",
        "ciclo registrado sin revisar",
    ),
    (
        B,
        "        violated=check_plan(prepared, durations).violated,",
        "        violated=(),",
        "plan vigente siempre factible",
    ),
    (
        B,
        "        if all(signal == PROTECTED for signal in signals):",
        "        if any(signal == PROTECTED for signal in signals):",
        "G parcial cuenta como G",
    ),
    (
        B,
        "    if list(indices) == list(range(first, last + 1)):",
        "    if True:",
        "partido como seguido",
    ),
    (
        B,
        '    return ("wrapping" if ends == 1 else "split"), None',
        '    return "split", None',
        "cruce del fin como partido",
    ),
    (
        B,
        '            if index not in protected and any(letters[index] == "g" for _, letters in served)',
        '            if any(letters[index] == "g" for _, letters in served)',
        "permisivo donde ya hay G",
    ),
    (
        B,
        '            problems.append(Problem("missing_flow", movement.id, "el escenario no trae su flujo"))',
        "            pass",
        "flujo faltante sin motivo",
    ),
    (B, "        if row.flow_vph == 0:", "        if False:", "flujo cero exige composición"),
    (
        B,
        "            if share == 0:",
        "            if False:",
        "clase sin participación exige equivalencia",
    ),
    (
        B,
        "            factor += Fraction(share) * Fraction(equivalence)",
        "            factor += Fraction(share)",
        "sin equivalencias",
    ),
    (
        B,
        "            (flows.get(movement_id, Fraction(0)) / lane_count[movement_id])",
        "            (flows.get(movement_id, Fraction(0)))",
        "flujo no se reparte entre carriles",
    ),
    (
        B,
        "        ratios[lane.lane_id] = Fraction(flow) / saturation",
        "        ratios[lane.lane_id] = Fraction(flow) / (saturation * 2)",
        "saturación mal usada",
    ),
    (B, "        if flow > 0:\n", "        if True:\n", "carril sin flujo exige verde"),
    (B, "        if lane.permissive:", "        if False:", "permisivo como sin verde"),
    (
        B,
        "    return first[0] > second[0] or (first[0] == second[0] and sorted(first[1]) < sorted(second[1]))",
        "    return first[0] >= second[0]",
        "empate sin regla",
    ),
    (
        B,
        "sorted(first[1]) < sorted(second[1]))",
        "sorted(first[1]) > sorted(second[1]))",
        "empate al revés",
    ),
    (
        B,
        "        before = bisect_left(ends, span[0], 0, position)",
        "        before = bisect_right(ends, span[0], 0, position)",
        "tramo compartido como libre",
    ),
    (
        B,
        "        best.append(take if _better(take, best[position]) else best[position])",
        "        best.append(take)",
        "siempre agrega el carril",
    ),
    (
        B,
        "    if (request.case_id, request.case_version) != pair:",
        "    if False:",
        "solicitud de otro caso",
    ),
    (
        B,
        "    if (parameters.case_id, parameters.case_version) != pair:",
        "    if False:",
        "parámetros de otro caso al calcular",
    ),
    (B, "    if not problems:", "    if True:", "camino crítico aunque no aplique"),
    (
        B,
        '        status="not_applicable" if problems else "applicable",',
        '        status="applicable",',
        "siempre aplicable",
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
