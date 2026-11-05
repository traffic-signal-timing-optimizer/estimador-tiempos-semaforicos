r"""Mutaciones de DEV15 F2: parámetros, plan vigente, estructura, recorrido crítico y ciclo (baselines.py).

Rompe a propósito, de a una vez, cada regla y corre las pruebas de baselines. Restaura el archivo
siempre. No corre si las pruebas fallan sin mutación. Uso: python scripts\mutaciones\dev15_f2.py [nombres]
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
    (
        B,
        "LOST_TIME_FACTOR = Fraction(3, 2)",
        "LOST_TIME_FACTOR = Fraction(1)",
        "factor de pérdida 1",
    ),
    (B, "LOST_TIME_EXTRA_S = Fraction(5)", "LOST_TIME_EXTRA_S = Fraction(0)", "sin los 5 s"),
    (
        B,
        "    return (LOST_TIME_FACTOR * lost_time_s + LOST_TIME_EXTRA_S) / (1 - y)",
        "    return (LOST_TIME_FACTOR * lost_time_s + LOST_TIME_EXTRA_S) / (1 + y)",
        "fórmula con 1 + Y",
    ),
    (
        B,
        "        if not any(other.y >= path.y and other.lost >= path.lost for other in kept):",
        "        if not any(other.y >= path.y for other in kept):",
        "pareto solo por Y",
    ),
    (
        B,
        "        if not any(other.y >= path.y and other.lost >= path.lost for other in kept):",
        "        if True:",
        "sin pareto",
    ),
    (
        B,
        "        if current is None or (-ratio, lane.lane_id) < (-current[0], current[1]):",
        "        if current is None:",
        "primer carril por tramo",
    ),
    (B, '        if slot.kind == "fixed":', "        if True:", "tramo variable se puede perder"),
    (
        B,
        "                    rest.lost + Fraction(slot.min_s),",
        "                    rest.lost,",
        "fijo perdido no suma",
    ),
    (
        B,
        "        suffix[position] = _pareto(options)",
        "        suffix[position] = _pareto(options)[:1]",
        "solo el de mayor Y",
    ),
    (B, "    if not paths:", "    if False:", "sin recorrido sin motivo"),
    (B, "    if highest == 0:", "    if False:", "Y cero sin motivo"),
    (
        B,
        "    if highest >= Fraction(parameters.applicability.y_must_be_below):",
        "    if highest > Fraction(parameters.applicability.y_must_be_below):",
        "Y igual al límite aceptado",
    ),
    (
        B,
        "    if highest >= Fraction(parameters.applicability.y_must_be_below):",
        "    if highest >= 1:",
        "límite de Y fijo",
    ),
    (
        B,
        "        key=lambda path: (-webster_cycle(path.y, path.lost), -path.y, path.lanes, path.lost_slots),",
        "        key=lambda path: (-path.y, path.lanes, path.lost_slots),",
        "elige por Y y no por ciclo",
    ),
    (
        B,
        "        if not low <= cycle <= high:",
        "        if not low <= cycle:",
        "sin tope de ciclo",
    ),
    (
        B,
        "        if not low <= cycle <= high:",
        "        if not cycle <= high:",
        "sin mínimo de ciclo",
    ),
    (
        B,
        "            usable = cycle - path.lost",
        "            usable = cycle",
        "verde sin restar L",
    ),
    (
        B,
        "                lane_id: float(ratio * usable / path.y)",
        "                lane_id: float(ratio * usable)",
        "verde sin dividir por Y",
    ),
    (B, "    if isinstance(chosen, Problem):", "    if False:", "problema del ciclo ignorado"),
    (
        B,
        "    y_must_be_below: Annotated[float, Field(gt=0, le=1)]",
        "    y_must_be_below: Annotated[float, Field(gt=0)]",
        "límite de Y sobre 1",
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
