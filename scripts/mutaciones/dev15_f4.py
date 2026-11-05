"""Mutaciones de DEV15 F4: comparadores publicados y plan auxiliar de Webster en la búsqueda."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
C = "src/semaforo/referencias/comparators.py"
S = "src/semaforo/referencias/search.py"
TESTS = ["tests/unit/test_comparators.py", "tests/unit/test_search_candidates.py"]
NL = chr(10)

MUTATIONS = [
    (
        C,
        '        if self.webster.status != "applicable":',
        "        if False:",
        "Webster que no aplica entra a la búsqueda",
    ),
    (
        C,
        "    if (scenario.case_id, scenario.case_version) != (case.case_id, case.case_version):",
        "    if False:",
        "escenario de otro caso",
    ),
    (C, "    if SAFE_FOLDER.fullmatch(case.case_id) is None:", "    if False:", "caso con ruta"),
    (
        C,
        "    moment = (utc_now() if now is None else now).astimezone(UTC)",
        "    moment = utc_now() if now is None else now",
        "hora local en el nombre",
    ),
    (
        C,
        "        current_plan_feasible=not content.current_plan.violated,",
        "        current_plan_feasible=True,",
        "vigente siempre factible",
    ),
    (C, "    if len(data) > MAX_FILE_BYTES:", "    if False:", "archivo sin límite de tamaño"),
    (
        C,
        "    if set(manifest.files) != {COMPARATORS_FILE, PARAMETERS_FILE}:",
        "    if False:",
        "manifiesto incompleto aceptado",
    ),
    (
        C,
        "        content.case_id == manifest.case_id" + NL,
        "        True" + NL,
        "caso sin cotejar",
    ),
    (
        C,
        "        and content.case_version == manifest.case_version",
        "        and True",
        "versión sin cotejar",
    ),
    (
        C,
        "        and content.scenario_id == manifest.scenario_id",
        "        and True",
        "escenario sin cotejar",
    ),
    (
        C,
        "        and webster.status == manifest.webster_status",
        "        and True",
        "estado de Webster sin cotejar",
    ),
    (
        C,
        "        and webster.adaptation == manifest.adaptation",
        "        and True",
        "adaptación sin cotejar",
    ),
    (
        C,
        "        and webster.parameter_set == manifest.parameter_set == parameters.parameter_set",
        "        and True",
        "parámetros sin cotejar",
    ),
    (
        C,
        "        and webster.provisional == manifest.provisional == parameters.provisional",
        "        and True",
        "provisional sin cotejar",
    ),
    (
        C,
        "        and (not content.current_plan.violated) == manifest.current_plan_feasible",
        "        and True",
        "factibilidad del vigente sin cotejar",
    ),
    (
        C,
        '        if self.status == "not_applicable" and not self.problems:',
        "        if False:",
        "no aplica sin motivo",
    ),
    (
        C,
        '        if self.status == "applicable" and (',
        "        if False and (",
        "aplicable sin plan",
    ),
    (S, '        if self.webster != "absent":', "        if True:", "traza siempre con Webster"),
    (
        S,
        "    if plan is None:" + NL + '        return "absent", ()',
        "    if False:" + NL + '        return "absent", ()',
        "plan ausente sin tratar",
    ),
    (
        S,
        "    if vector is None:" + NL + '        return "excluded", violated',
        "    if False:" + NL + '        return "excluded", violated',
        "plan inviable aceptado",
    ),
    (
        S,
        "    if vector in seen:" + NL + '        return "duplicate", ()',
        "    if False:" + NL + '        return "duplicate", ()',
        "auxiliar repetido evaluado dos veces",
    ),
    (
        S,
        "    seen.add(vector)"
        + NL
        + "    candidates.append(space.candidate(vector, origin, False))",
        "    candidates.append(space.candidate(vector, origin, False))",
        "copia muestreada de un auxiliar",
    ),
    (
        S,
        "    candidates.append(space.candidate(vector, origin, False))",
        "    candidates.append(space.candidate(vector, origin, True))",
        "auxiliar consume el presupuesto",
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
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
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
