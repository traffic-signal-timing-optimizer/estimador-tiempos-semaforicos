"""Ensayo de daño de DEV31 F5: se rompe a propósito el panel de resultados.

Cada mutación cambia un fragmento, corre las pruebas que deben notarlo y devuelve el archivo a su
estado original (se comprueba con su huella). Toca `src/` (código, SQL de las vistas y la página);
usa solo bases temporales. Las pruebas de la página necesitan Node.
Uso: python scripts/mutaciones/dev31_f5.py [parte del nombre de un daño ...]
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST = ROOT / ".venv" / "Scripts" / "pytest.exe"
BD = ROOT / "src" / "semaforo" / "bd"
SQL = BD / "sql" / "02_reglas.sql"
APP = ROOT / "src" / "semaforo" / "app"
WEB = APP / "panel_web"
BARRIDO = ("tests/integration/test_bd_reglas.py", "-k", "sweep")
PANEL = ("tests/integration/test_bd_panel.py",)
RESUMEN = ("tests/unit/test_panel_resumen.py",)
PAGINA = ("tests/unit/test_panel_web.py",)


@dataclass(frozen=True)
class Mutation:
    name: str
    file: Path
    old: str
    new: str
    tests: tuple[str, ...]


M = Mutation
MUTATIONS = [
    # --- cegado de cada vista nueva ---
    M(
        "la demanda de la prueba se ve",
        SQL,
        "FROM experimento.demanda AS d\n    WHERE control.escenario_visible(d.escenario_id);",
        "FROM experimento.demanda AS d;",
        BARRIDO,
    ),
    M(
        "los datos del escenario de prueba se ven",
        SQL,
        "JOIN control.artefactos AS a ON a.artefacto_id = e.artefacto_id\n    WHERE control.escenario_visible(e.escenario_id);",
        "JOIN control.artefactos AS a ON a.artefacto_id = e.artefacto_id;",
        BARRIDO,
    ),
    M(
        "los planes de la prueba se ven por sus corridas",
        SQL,
        "WHERE c.plan_id = p.plan_id AND control.escenario_visible(c.escenario_id)",
        "WHERE c.plan_id = p.plan_id",
        BARRIDO,
    ),
    M(
        "los planes de la prueba se ven por sus candidatos",
        SQL,
        "WHERE n.plan_id = p.plan_id AND control.escenario_visible(b.escenario_id)",
        "WHERE n.plan_id = p.plan_id",
        BARRIDO,
    ),
    M(
        "la procedencia de las corridas de prueba se ve",
        SQL,
        "x.artefacto_id = r.artefacto_metricas_id\n    WHERE control.escenario_visible(c.escenario_id);",
        "x.artefacto_id = r.artefacto_metricas_id;",
        BARRIDO,
    ),
    M(
        "los accesos de las corridas de prueba se ven",
        SQL,
        "FROM simulacion.resultados_acceso AS r\n    JOIN simulacion.corridas AS c ON c.run_id = r.run_id\n    WHERE control.escenario_visible(c.escenario_id);",
        "FROM simulacion.resultados_acceso AS r\n    JOIN simulacion.corridas AS c ON c.run_id = r.run_id;",
        BARRIDO,
    ),
    M(
        "los movimientos de las corridas de prueba se ven",
        SQL,
        "FROM simulacion.resultados_movimiento AS r\n    JOIN simulacion.corridas AS c ON c.run_id = r.run_id\n    WHERE control.escenario_visible(c.escenario_id);",
        "FROM simulacion.resultados_movimiento AS r\n    JOIN simulacion.corridas AS c ON c.run_id = r.run_id;",
        BARRIDO,
    ),
    M(
        "los candidatos de la prueba se ven",
        SQL,
        "JOIN simulacion.planes AS p ON p.plan_id = n.plan_id\n    WHERE control.escenario_visible(b.escenario_id);",
        "JOIN simulacion.planes AS p ON p.plan_id = n.plan_id;",
        BARRIDO,
    ),
    M(
        "las semillas de los candidatos de la prueba se ven",
        SQL,
        "JOIN simulacion.busquedas AS b ON b.busqueda_id = s.busqueda_id\n    WHERE control.escenario_visible(b.escenario_id);",
        "JOIN simulacion.busquedas AS b ON b.busqueda_id = s.busqueda_id;",
        BARRIDO,
    ),
    M(
        "los comparadores de la prueba se ven",
        SQL,
        "FROM simulacion.comparadores AS k\n    WHERE control.escenario_visible(k.escenario_id);",
        "FROM simulacion.comparadores AS k;",
        BARRIDO,
    ),
    M(
        "la exclusión de un archivo de la prueba se ve",
        SQL,
        "AND (a.alcance = 'desconocido' OR control.archivo_visible(a.artefacto_id));",
        ";",
        BARRIDO,
    ),
    M(
        "las semillas finales salen como semillas de búsqueda",
        SQL,
        "WHERE s.protocolo_id = p.protocolo_id AND s.etapa = 'search') AS semillas_busqueda",
        "WHERE s.protocolo_id = p.protocolo_id) AS semillas_busqueda",
        BARRIDO,
    ),
    # --- lectura y publicación ---
    M(
        "el panel lee con un usuario con más permisos",
        BD / "panel_datos.py",
        "with connect(PANEL, database=database) as connection:",
        'with connect("semaforo_admin", database=database) as connection:',
        PANEL,
    ),
    M(
        "el panel no avisa si le faltan las vistas",
        BD / "panel_datos.py",
        "except (psycopg.errors.UndefinedTable, psycopg.errors.InsufficientPrivilege) as error:",
        "except psycopg.errors.DivisionByZero as error:",
        PANEL,
    ),
    M(
        "una evidencia de otra base pasa por la de esta",
        APP / "bd_panel.py",
        '"de_esta_base": same,',
        '"de_esta_base": True,',
        PANEL,
    ),
    M(
        "el manifiesto del panel no guarda las huellas",
        APP / "bd_panel.py",
        "files={file: sha256_bytes(raw) for file, raw in sorted(contents.items())},",
        'files={file: sha256_bytes(b"") for file, raw in sorted(contents.items())},',
        PANEL,
    ),
    M(
        "el panel filtra rutas de la máquina",
        APP / "bd_panel.py",
        'return {"datos": relative(workspace), "repositorio": relative(repository)}',
        'return {"datos": str(workspace), "repositorio": relative(repository)}',
        PANEL,
    ),
    M(
        "un acta inexistente no se avisa",
        APP / "bd_panel.py",
        "if acta and not (repository / str(acta)).is_file():",
        "if False:",
        PANEL,
    ),
    # --- las cuentas ---
    M(
        "un par con incidentes cuenta como válido",
        APP / "panel_resumen.py",
        '"valida": _valid(mine) and _valid(theirs),',
        '"valida": True,',
        RESUMEN,
    ),
    M(
        "una réplica cuenta dos veces",
        APP / "panel_resumen.py",
        'chosen.setdefault((run.get("plan_id"), run.get("semilla_sumo")), run)',
        'chosen.setdefault((run.get("plan_id"), run.get("run_id")), run)',
        RESUMEN,
    ),
    M(
        "los finalistas se declaran emparejados siempre",
        APP / "panel_resumen.py",
        "and all(seed in observed_seeds for seed in finalist_seeds),",
        "and True,",
        RESUMEN,
    ),
    M(
        "la diferencia se resta al revés",
        APP / "panel_resumen.py",
        "measured - reference if measured is not None",
        "reference - measured if measured is not None",
        RESUMEN,
    ),
    M(
        "las series mezclan protocolos",
        APP / "panel_resumen.py",
        'groups.setdefault((str(run.get("etapa") or ""), str(protocol)), []).append(run)',
        'groups.setdefault((str(run.get("etapa") or ""), ""), []).append(run)',
        RESUMEN,
    ),
    # --- la página ---
    M("la página no escapa el texto", WEB / "app.js", "'<': '&lt;'", "'<': '<'", PAGINA),
    M("la página no escapa las comillas", WEB / "app.js", "'\"': '&quot;'", "'\"': '\"'", PAGINA),
    M(
        "la evaluación se abre sin indicadores",
        WEB / "app.js",
        "if (!indicators.length) {",
        "if (false) {",
        PAGINA,
    ),
    M(
        "no se avisa que la comparación no es emparejada",
        WEB / "app.js",
        "(comparison.finalistas_con_mismas_semillas ? '' : notice(",
        "(true ? '' : notice(",
        PAGINA,
    ),
    M(
        "no se avisa de la demanda sintética",
        WEB / "app.js",
        "return hasSynthetic(data)\n      ? notice(",
        "return false\n      ? notice(",
        PAGINA,
    ),
    M(
        "la página permite recursos externos",
        WEB / "index.html",
        "default-src 'none'",
        "default-src *",
        PAGINA,
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
