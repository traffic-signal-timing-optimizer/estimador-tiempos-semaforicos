r"""Mutaciones de la corrección A01: identidad v2, vínculos de la bitácora y evidencia.

Rompe a propósito, de a una vez, cada regla y corre las pruebas de la búsqueda, de la bitácora, de la
etiqueta y de la evidencia (con SUMO real). Restaura el archivo siempre. No corre si las pruebas
fallan sin mutación. Uso: python scripts\mutaciones\dev14_a01.py [nombres]
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
E = "src/semaforo/referencias/evaluation.py"
L = "src/semaforo/referencias/label.py"
V = "src/semaforo/referencias/evidence.py"
UNIT = [
    "tests/unit/test_search_journal.py",
    "tests/unit/test_label.py",
    "tests/unit/test_search_evidence.py",
]
SUMO = ["tests/integration/test_search_sumo.py"]

# (archivo, texto, reemplazo, nombre, pruebas que se corren)
MUTATIONS = [
    (
        E,
        'JOURNAL_VERSION = "2.0.0"',
        'JOURNAL_VERSION = "1.0.0"',
        "versión de la bitácora sin subir",
        UNIT,
    ),
    (
        E,
        '        "case_sha256": canonical_sha256(setup.case),',
        '        "case_sha256": "x",',
        "caso fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '        "network_sha256": None if network is None else network.sha256,',
        '        "network_sha256": None,',
        "red fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '        "scenario_sha256": canonical_json_sha256(setup.scenario.model_dump(mode="json")),',
        '        "scenario_sha256": "x",',
        "escenario fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '        "routes_sha256": canonical_json_sha256(setup.routes.model_dump(mode="json")),',
        '        "routes_sha256": "x",',
        "rutas fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '        "vehicle_types_sha256": canonical_json_sha256(setup.vehicle_types.model_dump(mode="json")),',
        '        "vehicle_types_sha256": "x",',
        "tipos fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '        "protocol_sha256": canonical_json_sha256(setup.protocol.model_dump(mode="json")),',
        '        "protocol_sha256": "x",',
        "protocolo fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '        "inputs_schema_version": INPUTS_SCHEMA_VERSION,\n        "sumo_version": sumo_version,',
        '        "inputs_schema_version": INPUTS_SCHEMA_VERSION,\n        "sumo_version": "x",',
        "SUMO fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '        "inputs": input_fingerprints(setup, sumo_version),',
        "",
        "huellas fuera de la identidad",
        UNIT,
    ),
    (
        E,
        '    if header.get("journal_version") != JOURNAL_VERSION:',
        "    if False:",
        "bitácora vieja aceptada",
        UNIT,
    ),
    (
        E,
        "    if header != json.loads(_canonical(dict(identity))):",
        "    if False:",
        "bitácora de otra búsqueda aceptada",
        UNIT,
    ),
    (E, "    _check_links(state, setup)\n", "", "vínculos sin comprobar", SUMO),
    (
        E,
        "    different = sorted(name for name, value in wanted.items() if found[name] != value)",
        "    different = []",
        "carpeta de entradas sin cotejar",
        SUMO,
    ),
    (
        E,
        '        "sumo_seed": seed,\n',
        '        "sumo_seed": found["sumo_seed"],\n',
        "semilla de las entradas sin cotejar",
        SUMO,
    ),
    (
        E,
        '        "sumo_options": dict(setup.sumo_options),\n        "inputs_schema_version"',
        '        "sumo_options": found["sumo_options"],\n        "inputs_schema_version"',
        "opciones de SUMO sin cotejar",
        SUMO,
    ),
    (
        E,
        "            if recorded != program_sha:",
        "            if False:",
        "programa anotado sin cotejar",
        SUMO,
    ),
    (
        E,
        "        if key not in inputs_sha:",
        "        if False:",
        "resultado sin su carpeta de entradas",
        SUMO,
    ),
    (
        E,
        "    if len(data) > MAX_RUN_MANIFEST_BYTES:",
        "    if False:",
        "manifiesto de corrida sin límite",
        SUMO,
    ),
    (
        L,
        '        identity_version=str(outcome.identity.get("journal_version", "")),',
        '        identity_version="1.0.0",',
        "versión de la identidad en el manifiesto",
        [*UNIT, "tests/unit/test_comparators.py"],
    ),
    (
        V,
        '    if records[0].get("identity") != identity:',
        "    if False:",
        "bitácora ajena a la etiqueta",
        SUMO,
    ),
    (
        V,
        "        if manifest.seeds.sumo_seed != key[2]:",
        "        if False:",
        "semilla de entradas sin cotejar en la evidencia",
        SUMO,
    ),
    (
        V,
        "        if key not in manifests:",
        "        if False:",
        "corrida sin entradas aceptada",
        SUMO,
    ),
    (
        V,
        '        if recompute and outcome.get("run_status") == "succeeded":',
        "        if False:",
        "recálculo omitido",
        SUMO,
    ),
    (
        V,
        "            different = _compare(outcome, seed_outcome(key[2], metrics).to_json())",
        "            different = []",
        "recálculo sin comparar",
        SUMO,
    ),
    (
        V,
        "    if len(sumo_versions) > 1:",
        "    if False:",
        "más de una versión de SUMO aceptada",
        SUMO,
    ),
    (
        V,
        "        if canonical_sha256(case) != base.case_sha256:",
        "        if False:",
        "caso distinto aceptado",
        SUMO,
    ),
    (
        V,
        "    if protocol.protocol_id != stored.label.protocol_id:",
        "    if False:",
        "protocolo de otra etiqueta aceptado",
        SUMO,
    ),
    (
        V,
        '        if fingerprints and identity.get("inputs") != fingerprints:',
        "        if False:",
        "huellas distintas aceptadas",
        SUMO,
    ),
    (V, "        if not matches:", "        if False:", "identificadores ajenos aceptados", SUMO),
    (
        E,
        "    if artifacts.get(RUN_INPUTS_ARTIFACT) != inputs_sha256:",
        "    if False:",
        "entradas de la corrida sin cotejar",
        SUMO,
    ),
    (
        V,
        '        if artifacts.get(RUN_INPUTS_ARTIFACT) != sha256_file(folder / "manifiesto.json"):',
        "        if False:",
        "entradas de la corrida sin cotejar en la evidencia",
        SUMO,
    ),
    (
        V,
        "                if getattr(manifest, name) != getattr(base, name):",
        "                if False:",
        "insumos distintos aceptados",
        SUMO,
    ),
]


def tests_fail(tests: list[str]) -> bool:
    result = subprocess.run(
        [PY, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests],
        cwd=ROOT,
        capture_output=True,
        timeout=900,
        check=False,
    )
    return result.returncode != 0


def main() -> int:
    if tests_fail(UNIT + SUMO):
        print("las pruebas fallan sin mutación: el ensayo no vale")
        return 2
    wanted = set(sys.argv[1:])
    chosen = [m for m in MUTATIONS if not wanted or m[3] in wanted]
    survivors: list[str] = []
    skipped: list[str] = []
    for name, old, new, what, tests in chosen:
        path = ROOT / name
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            skipped.append(what)
            continue
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            if not tests_fail(tests):
                survivors.append(what)
        finally:
            path.write_bytes(original)
        print(".", end="", flush=True)
    applied = len(chosen) - len(skipped)
    print(f"\naplicadas {applied}, detectadas {applied - len(survivors)}")
    print("sobreviven:", survivors)
    print("no aplican:", skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
