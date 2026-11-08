"""Ensayo de daño de DEV31 F4c, etapa C3: se rompen a propósito las reglas y los controles nuevos.

Cada mutación cambia un fragmento, corre las pruebas que deben notarlo y devuelve el archivo a su
estado original (se comprueba con su huella). Toca `src/` (código y SQL de la base); usa solo bases
temporales. Los daños sobre el SQL funcionan porque cada prueba crea su base desde esos archivos.
Uso: python scripts/mutaciones/dev31_c3.py [parte del nombre de un daño ...]
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST = ROOT / ".venv" / "Scripts" / "pytest.exe"
BD = ROOT / "src" / "semaforo" / "bd"
SQL = BD / "sql"
APP = ROOT / "src" / "semaforo" / "app"
REGLAS = ("tests/integration/test_bd_reglas.py",)
EVIDENCIA = ("tests/integration/test_bd_evidencia.py",)


@dataclass(frozen=True)
class Mutation:
    name: str
    file: Path
    old: str
    new: str
    tests: tuple[str, ...]


M = Mutation
MUTATIONS = [
    # --- hitos y selección (B03) ---
    M(
        "la apertura no exige que la partición sea la del experimento",
        SQL / "02_reglas.sql",
        "IF v_particion IS DISTINCT FROM NEW.particion_id THEN",
        "IF false THEN",
        REGLAS,
    ),
    M(
        "el congelamiento acepta una selección de otra partición",
        SQL / "02_reglas.sql",
        "WHERE seleccion_id = v_seleccion AND particion_id = v_particion",
        "WHERE seleccion_id = v_seleccion",
        REGLAS,
    ),
    M(
        "el congelamiento acepta una selección posterior",
        SQL / "02_reglas.sql",
        ") OR v_fecha_seleccion > NEW.registrado_en",
        ") OR false",
        REGLAS,
    ),
    # --- cola (B09) ---
    M(
        "la cola acepta pasos repetidos",
        SQL / "02_reglas.sql",
        "v_pasos[s.i] <= v_pasos[s.i - 1]",
        "v_pasos[s.i] < v_pasos[s.i - 1]",
        REGLAS,
    ),
    M(
        "la cola acepta banderas de ventana de otra longitud",
        SQL / "02_reglas.sql",
        "OR cardinality(v_pasos) <> cardinality(v_ventana)",
        "OR false",
        REGLAS,
    ),
    M(
        "los pasos de la cola aceptan infinitos y NaN",
        SQL / "01_tablas.sql",
        " AND 'Infinity'::double precision > ALL(pasos_cola_s)",
        "",
        REGLAS,
    ),
    M(
        "los pasos de la cola aceptan negativos",
        SQL / "01_tablas.sql",
        "AND 0 <= ALL(pasos_cola_s) AND 'Infinity'",
        "AND 'Infinity'",
        REGLAS,
    ),
    # --- cegado de archivos, planes, réplicas y diferencias (B02, N1) ---
    M(
        "un archivo de cualquier alcance se ve",
        SQL / "02_reglas.sql",
        "archivo.alcance = 'global'",
        "archivo.alcance IS NOT NULL",
        REGLAS,
    ),
    M(
        "todos los planes se ven",
        SQL / "03_seguridad.sql",
        "CREATE POLICY lectura_cegada ON simulacion.planes FOR SELECT TO semaforo_lectura USING (",
        "CREATE POLICY lectura_cegada ON simulacion.planes FOR SELECT TO semaforo_lectura USING (true OR ",
        REGLAS,
    ),
    M(
        "una réplica se ve con una sola corrida visible",
        SQL / "03_seguridad.sql",
        " AND EXISTS (SELECT 1 FROM simulacion.corridas AS b WHERE b.run_id = replicas.run_id_b)",
        "",
        REGLAS,
    ),
    M(
        "una diferencia se ve con una sola comparación visible",
        SQL / "03_seguridad.sql",
        " AND EXISTS (SELECT 1 FROM evaluacion.comparaciones AS b WHERE b.comparacion_id = diferencias.comparacion_b_id)",
        "",
        REGLAS,
    ),
    # --- barrido (C3.2) ---
    M(
        "el barrido da por permitido todo",
        BD / "barrido.py",
        'allowed = role == LECTURA or (schema == "vistas" and name in PANEL_VIEWS)',
        "allowed = True",
        REGLAS,
    ),
    M(
        "el barrido no busca las marcas",
        BD / "barrido.py",
        "found = _leak_rows(connection, schema, name, patterns) if patterns else 0",
        "found = 0",
        REGLAS,
    ),
    M(
        "el barrido cuenta como filtración las columnas justificadas",
        BD / "barrido.py",
        'removed = JUSTIFIED.get(f"{schema}.{name}", [])',
        "removed = []",
        REGLAS,
    ),
    M(
        "el barrido no junta las corridas de los escenarios cegados",
        BD / "barrido.py",
        "marks.update(str(row[0]) for row in admin.execute(query.encode(), (hidden,)))",
        "_ = (str(row[0]) for row in admin.execute(query.encode(), (hidden,)))",
        REGLAS,
    ),
    M(
        "el barrido no avisa de un acceso negado de más",
        BD / "barrido.py",
        "unexpected_denials.append(full)",
        "_ = full",
        REGLAS,
    ),
    M(
        "el barrido no avisa de un acceso permitido de más",
        BD / "barrido.py",
        "unexpected_reads.append(full)",
        "_ = full",
        REGLAS,
    ),
    # --- evidencia (C3.5) ---
    M(
        "la evidencia sale siempre en orden",
        APP / "bd_evidencia.py",
        "code = INTEGRITY_EXIT if INTEGRITY_EXIT in codes else INCONCLUSIVE_EXIT if codes - {0} else 0",
        "code = 0",
        EVIDENCIA,
    ),
    M(
        "la cobertura incompleta no se informa",
        APP / "bd_evidencia.py",
        "complete = not (coverage.missing or coverage.excluded_pending or coverage.surplus)",
        "complete = True",
        EVIDENCIA,
    ),
    M(
        "la red abierta no se informa",
        APP / "bd_evidencia.py",
        'code = {"aislada": 0, "abierta": INTEGRITY_EXIT}.get(network.verdict, INCONCLUSIVE_EXIT)',
        "code = 0",
        EVIDENCIA,
    ),
    M(
        "el manifiesto no guarda la huella de los archivos",
        APP / "bd_evidencia.py",
        "{file: sha256_bytes(data) for file, data in sorted(contents.items())}",
        '{file: sha256_bytes(b"") for file, data in sorted(contents.items())}',
        EVIDENCIA,
    ),
    M(
        "la evidencia no dice si el repositorio tiene cambios sin confirmar",
        APP / "bd_evidencia.py",
        'repository_clean=None if status_output is None else status_output == ""',
        "repository_clean=True",
        EVIDENCIA,
    ),
    M(
        "se elige el respaldo más viejo",
        BD / "respaldo.py",
        "return found[-1] if found else None",
        "return found[0] if found else None",
        EVIDENCIA,
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
