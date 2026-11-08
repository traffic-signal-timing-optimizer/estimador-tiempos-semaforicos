"""Ensayo de daño de DEV31 F3: se rompe el código a propósito y se comprueba que alguna prueba falla.

Cada mutación cambia un fragmento (del código o del SQL de la base), corre las pruebas que deben
notarlo y devuelve el archivo a su estado original (se comprueba con su huella). Solo toca `src/`;
no escribe en `datos/` y usa solo bases temporales.
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST = ROOT / ".venv" / "Scripts" / "pytest.exe"
SRC = ROOT / "src" / "semaforo"
SQL = SRC / "bd" / "sql"
RULES = ("tests/integration/test_bd_reglas.py",)
LOAD = ("tests/integration/test_bd_carga_sumo.py",)
READING = ("tests/unit/test_bd_lectura.py",)
SECURITY = ("tests/security/test_bd_seguridad.py",)


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
        "se puede borrar evidencia",
        SQL / "02_reglas.sql",
        "BEGIN\n    IF TG_OP = 'UPDATE' AND TG_TABLE_SCHEMA = 'control' THEN",
        "BEGIN\n    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;\n"
        "    IF TG_OP = 'UPDATE' AND TG_TABLE_SCHEMA = 'control' THEN",
        RULES,
    ),
    M(
        "una carga se cierra dos veces",
        SQL / "02_reglas.sql",
        "IF OLD.estado = 'running' AND NEW.estado <> 'running'",
        "IF NEW.estado <> 'running'",
        RULES,
    ),
    M(
        "la apertura no destapa la prueba",
        SQL / "02_reglas.sql",
        "WHERE a.asignacion = 'test' AND NOT control.prueba_abierta(a.particion_id);",
        "WHERE a.asignacion = 'test';",
        RULES,
    ),
    M(
        "cualquier hito abre la prueba",
        SQL / "02_reglas.sql",
        "WHERE tipo = 'test_opened' AND particion_id = p_particion",
        "WHERE particion_id = p_particion",
        RULES,
    ),
    M(
        "se abre la prueba sin modelo congelado",
        SQL / "02_reglas.sql",
        "        IF NOT EXISTS (\n                SELECT 1 FROM control.hitos AS h\n",
        "        IF FALSE AND NOT EXISTS (\n                SELECT 1 FROM control.hitos AS h\n",
        RULES,
    ),
    M(
        "un preliminar pasa a prueba",
        SQL / "02_reglas.sql",
        "WHERE escenario_id = NEW.escenario_id AND preliminar",
        "WHERE escenario_id = NEW.escenario_id AND false",
        RULES,
    ),
    M(
        "una familia se reparte",
        SQL / "02_reglas.sql",
        "AND (otra.particion_id <> NEW.particion_id OR otra.asignacion <> NEW.asignacion)",
        "AND false",
        RULES,
    ),
    M(
        "una corrida final en entrenamiento",
        SQL / "02_reglas.sql",
        "IF NEW.etapa = 'final' AND NOT EXISTS (",
        "IF false AND NOT EXISTS (",
        RULES,
    ),
    M(
        "la vista del panel no filtra los escenarios cegados",
        SQL / "02_reglas.sql",
        "    WHERE control.escenario_visible(e.escenario_id);\nCOMMENT ON VIEW vistas.zona_escenario",
        "    ;\nCOMMENT ON VIEW vistas.zona_escenario",
        RULES,
    ),
    M(
        "los eventos de la prueba se ven",
        SQL / "03_seguridad.sql",
        "CREATE POLICY lectura_cegada ON simulacion.eventos FOR SELECT TO semaforo_lectura USING (EXISTS (SELECT 1 FROM simulacion.corridas AS padre WHERE padre.run_id = eventos.run_id));",
        "CREATE POLICY lectura_cegada ON simulacion.eventos FOR SELECT TO semaforo_lectura USING (true);",
        RULES,
    ),
    M(
        "el cargador puede modificar corridas",
        SQL / "03_seguridad.sql",
        "GRANT UPDATE ON control.cargas, control.conflictos TO semaforo_carga;",
        "GRANT UPDATE ON ALL TABLES IN SCHEMA control, simulacion TO semaforo_carga;",
        RULES,
    ),
    M(
        "los conflictos se ignoran",
        SRC / "bd/carga/insercion.py",
        "    if conflicts:\n        return WriteResult(new={}, same={}, conflicts=conflicts)",
        "    if False:\n        return WriteResult(new={}, same={}, conflicts=conflicts)",
        LOAD,
    ),
    M(
        "se agrega aunque la clave ya esté",
        SRC / "bd/carga/insercion.py",
        '"WHERE NOT EXISTS (SELECT 1 FROM {table} AS t WHERE {match})"',
        '"WHERE true"',
        LOAD,
    ),
    M(
        "el atajo no compara la huella",
        SRC / "bd/carga/motor.py",
        "if row is None or row[0] != digest:",
        "if row is None:",
        LOAD,
    ),
    M(
        "el -1 de SUMO se guarda como dato",
        SRC / "bd/carga/corridas.py",
        "return None if number == SUMO_MISSING else number",
        "return number",
        READING,
    ),
    M(
        "los errores del registro no se cargan",
        SRC / "bd/carga/corridas.py",
        'if line.startswith("Error:"):\n        return "error", None',
        'if False:\n        return "error", None',
        READING,
    ),
    M(
        "la etapa de la búsqueda no se usa",
        SRC / "bd/carga/corridas.py",
        "stage, protocol = search.stage, search.protocol_id",
        'stage, protocol = "diagnostic", search.protocol_id',
        LOAD,
    ),
    M(
        "las semillas de finalistas como búsqueda",
        SRC / "bd/carga/referencias.py",
        '{**row, "etapa": stage}',
        '{**row, "etapa": "search"}',
        LOAD,
    ),
    M(
        "un escenario a mano entra sin autorización",
        SRC / "bd/carga/motor.py",
        '            if not run.options.preliminary:\n                raise Pending(\n                    "un escenario',
        '            if False:\n                raise Pending(\n                    "un escenario',
        LOAD,
    ),
    M(
        "la huella incluye la carga",
        SRC / "bd/verificacion.py",
        'EXCLUDED_COLUMNS = frozenset({"carga_id"})',
        "EXCLUDED_COLUMNS = frozenset[str]()",
        LOAD,
    ),
    M(
        "verificar no ve archivos cambiados",
        SRC / "bd/verificacion.py",
        "        if found != root.sha256:",
        "        if False:",
        LOAD,
    ),
    M(
        "se restaura un respaldo alterado",
        SRC / "bd/respaldo.py",
        "        if sha256_file(path) != expected:",
        "        if False:",
        LOAD,
    ),
    M(
        "se puede borrar cualquier base",
        SRC / "bd/temporales.py",
        '    if not prefixed or not name.replace("_", "").isalnum() or name != name.lower():',
        "    if False:",
        SECURITY,
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
