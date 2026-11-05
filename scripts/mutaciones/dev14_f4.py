"""Mutaciones de DEV14 F4: etiqueta publicada (label.py) y su revisión en el espacio de trabajo.

Rompe a propósito, de a una vez, cada regla y corre las pruebas sin SUMO de la etiqueta. Restaura el
archivo siempre. Se niega a correr si los archivos tienen cambios sin commit o si las pruebas fallan
sin mutación.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
L = "src/semaforo/referencias/label.py"
INTEGRITY = "src/semaforo/app/integrity.py"
TESTS = ["tests/unit/test_label.py", "tests/security/test_dev14.py"]

MUTATIONS = [
    (
        L,
        '        if self.status == "reference" and self.plan is None:',
        "        if False:",
        "referencia sin plan",
    ),
    (
        L,
        "(self.plan is not None or self.reason is None)",
        "(self.plan is not None)",
        "sin referencia sin motivo",
    ),
    (
        L,
        "(self.plan is not None or self.reason is None)",
        "(self.reason is None)",
        "sin referencia con plan",
    ),
    (L, "    cycle_s: float = Field(gt=0)", "    cycle_s: float = Field(ge=0)", "ciclo cero"),
    (L, "    candidate_count: int = Field(ge=0)", "    candidate_count: int", "conteo negativo"),
    (
        L,
        "    if outcome.interrupted or outcome.selection is None:",
        "    if outcome.selection is None:",
        "interrumpida publicada",
    ),
    (
        L,
        "    if outcome.interrupted or outcome.selection is None:",
        "    if outcome.interrupted:",
        "sin selección publicada",
    ),
    (
        L,
        "    if dict(outcome.identity) != search_identity(setup, outcome.candidates):",
        "    if False:",
        "identidad sin revisar",
    ),
    (
        L,
        "        if candidate.candidate_id == winner.candidate_id:",
        "        if True:",
        "el primer candidato gana",
    ),
    (
        L,
        '    raise ReferenciasError(\n        ErrorCode.OUTPUT_INVALID, "el ganador',
        '    return {}\n    raise ReferenciasError(\n        ErrorCode.OUTPUT_INVALID, "el ganador',
        "ganador ajeno sin error",
    ),
    (
        L,
        '    return "evaluated" if purpose == "main_experiment" else "fixture_only"',
        '    return "fixture_only"',
        "nunca evaluated",
    ),
    (
        L,
        '    return "evaluated" if purpose == "main_experiment" else "fixture_only"',
        '    return "evaluated"',
        "piloto como evaluated",
    ),
    (
        L,
        '        label_id=f"label-{digest}",',
        '        label_id=f"label-{digest[:8]}",',
        "id de etiqueta corto",
    ),
    (
        L,
        '        search_run_id=f"search-{digest}",',
        '        search_run_id=f"label-{digest}",',
        "id de búsqueda mal nombrado",
    ),
    (
        L,
        "        candidate_count=len(outcome.candidates.candidates),",
        "        candidate_count=len(outcome.search_scores),",
        "conteo de candidatos",
    ),
    (
        L,
        "        simulation_count=outcome.simulation_count,\n        evidence_status",
        "        simulation_count=0,\n        evidence_status",
        "simulaciones en cero",
    ),
    (L, "        reason=selection.reason,", "        reason=None,", "sin motivo"),
    (L, "greens_s=timing.greens_s)", "greens_s={})", "sin verdes"),
    (
        L,
        "plan = Plan(slot_durations_s=durations,",
        "plan = Plan(slot_durations_s=dict(list(durations.items())[1:]),",
        "falta un slot",
    ),
    (
        L,
        '        "eligible": sum(1 for score in scores if score.eligible),',
        '        "eligible": len(scores),',
        "todos elegibles en la cobertura",
    ),
    (
        L,
        '        "ineligible": dict(ineligible),',
        '        "ineligible": {},',
        "causas no contadas",
    ),
    (
        L,
        '        "search": _stage_coverage(outcome.search_scores, selection.ineligible_search),',
        '        "search": _stage_coverage(outcome.search_scores, selection.ineligible_finalists),',
        "causas cruzadas",
    ),
    (
        L,
        '        "simulations": outcome.simulation_count,',
        '        "simulations": len(outcome.search_scores),',
        "simulaciones mal contadas",
    ),
    (
        L,
        '        "budget_used": candidates.budget_used,',
        '        "budget_used": candidates.budget,',
        "presupuesto usado = declarado",
    ),
    (L, "    if SAFE_FOLDER.fullmatch(case_id) is None:", "    if False:", "caso con ruta"),
    (
        L,
        "    moment = (utc_now() if now is None else now).astimezone(UTC)",
        "    moment = utc_now() if now is None else now",
        "hora local en el nombre",
    ),
    (
        L,
        "        network_sha256=None if setup.case.network is None else setup.case.network.sha256,",
        "        network_sha256=None,",
        "sin huella de la red",
    ),
    (
        L,
        '            ErrorCode.RUN_EXISTS, "ya existe',
        '            ErrorCode.INPUT_SCHEMA, "ya existe',
        "código de duplicado",
    ),
    (L, "lambda m: m.files)", "lambda m: {})", "manifiesto sin archivos"),
    (
        L,
        "    if set(manifest.files) != {LABEL_FILE, TRACE_FILE, COVERAGE_FILE}:",
        "    if False:",
        "manifiesto incompleto aceptado",
    ),
    (L, "    if len(data) > MAX_LABEL_BYTES:", "    if False:", "etiqueta sin límite"),
    (L, "        label.label_id == manifest.label_id\n", "        True\n", "label_id sin cotejar"),
    (
        L,
        "        and label.scenario_id == manifest.scenario_id",
        "        and True",
        "escenario sin cotejar",
    ),
    (
        L,
        "        and label.case_version == manifest.case_version",
        "        and True",
        "versión sin cotejar",
    ),
    (L, "        and label.status == manifest.status", "        and True", "estado sin cotejar"),
    (
        L,
        "        and label.search_run_id == manifest.search_run_id",
        "        and True",
        "búsqueda sin cotejar",
    ),
    (
        L,
        "        and label.protocol_id == manifest.protocol_id",
        "        and True",
        "protocolo sin cotejar",
    ),
    (
        L,
        "        and label.evidence_status == manifest.evidence_status",
        "        and True",
        "evidencia sin cotejar",
    ),
    (
        INTEGRITY,
        '        ("labels", workspace / LABELS, lambda f: _check(read_label, f), True),\n',
        "",
        "runs verify sin etiquetas",
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
    for name in {m[0] for m in MUTATIONS}:
        if subprocess.run(["git", "diff", "--quiet", "--", name], cwd=ROOT, check=False).returncode:
            print(f"{name} tiene cambios sin commit: no se muta")
            return 2
    if tests_fail():
        print("las pruebas fallan sin mutación: el ensayo no vale")
        return 2
    survivors: list[str] = []
    skipped: list[str] = []
    wanted = set(sys.argv[1:])
    chosen = [m for m in MUTATIONS if not wanted or m[3] in wanted]
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
