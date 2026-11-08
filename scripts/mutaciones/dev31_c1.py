"""Ensayo de daño de DEV31 F4c, etapa C1: se rompen los controles nuevos a propósito.

Cada mutación cambia un fragmento, corre las pruebas que deben notarlo y devuelve el archivo a su
estado original (se comprueba con su huella). Solo toca `src/`; usa solo bases temporales.
Uso: python scripts/mutaciones/dev31_c1.py [parte del nombre de un daño ...]
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST = ROOT / ".venv" / "Scripts" / "pytest.exe"
BD = ROOT / "src" / "semaforo" / "bd"
APP = ROOT / "src" / "semaforo" / "app"
CONTROLES = ("tests/integration/test_bd_controles.py",)
COBERTURA = ("tests/integration/test_bd_cobertura.py",)
RESPALDOS = ("tests/integration/test_bd_respaldos.py",)
RECONSTRUCCION = ("tests/integration/test_bd_reconstruccion.py",)
FUENTES_SUMO = ("tests/integration/test_bd_fuentes_sumo.py",)
ACCESO = ("tests/unit/test_bd_acceso.py",)


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
        "la lectura no pide el candado compartido",
        BD / "instantanea.py",
        "if not try_shared(connection):",
        "if False:",
        CONTROLES,
    ),
    M(
        "la lectura ignora las cargas en curso",
        BD / "instantanea.py",
        "if inicio.en_curso:",
        "if False:",
        CONTROLES,
    ),
    M(
        "la lectura no nota que la última carga cambió",
        BD / "instantanea.py",
        "if final != inicio:",
        "if False:",
        CONTROLES,
    ),
    M(
        "el candado compartido es exclusivo",
        BD / "candado.py",
        '"SELECT pg_try_advisory_lock_shared(%s)"',
        '"SELECT pg_try_advisory_lock(%s)"',
        CONTROLES,
    ),
    M(
        "la huella de reglas no mira las reglas",
        BD / "reglas.py",
        "digest.update(line.encode())",
        'digest.update(b"")',
        CONTROLES,
    ),
    M(
        "la referencia no compara las reglas instaladas",
        BD / "verificacion.py",
        "if reference.reglas_sha256 is not None and reference.reglas_sha256 != measured.rules_sha256:",
        "if False:",
        CONTROLES,
    ),
    M(
        "la referencia acepta otro algoritmo de huella",
        BD / "verificacion.py",
        "if algorithm != HASH_ALGORITHM:",
        "if False:",
        CONTROLES,
    ),
    M(
        "lo faltante no vuelve incompleta la conciliación",
        BD / "conciliacion.py",
        "elif coverage.missing or coverage.excluded_pending:",
        "elif False:",
        COBERTURA,
    ),
    M(
        "una decisión cubre cualquier versión del archivo",
        BD / "conciliacion.py",
        'if digest is not None and (f"{DATA_ROOT}:{mains[0]}", digest) in decided:',
        "if digest is not None:",
        COBERTURA,
    ),
    M(
        "lo que sobra en la base no se cuenta",
        BD / "conciliacion.py",
        'surplus = sorted(in_database - sources.keys("run"))',
        "surplus: list[str] = []",
        FUENTES_SUMO,
    ),
    M(
        "una corrida sin verificar queda como igual",
        BD / "conciliacion.py",
        "elif found.unverified:",
        "elif False:",
        FUENTES_SUMO,
    ),
    M(
        "una carpeta de métricas inválida cuenta como publicada",
        BD / "metricas.py",
        "        read_run_metrics(folder)",
        "        pass",
        FUENTES_SUMO,
    ),
    M(
        "las unidades abiertas no cambian el código de salida",
        APP / "bd_commands.py",
        "return INTEGRITY_EXIT if open_items else 0",
        "return 0",
        COBERTURA,
    ),
    M(
        "el acta puede tener cambios sin confirmar",
        APP / "bd_commands.py",
        'if git_output(repository, "status", "--porcelain", "--", acta):',
        "if False:",
        COBERTURA,
    ),
    M(
        "una decisión se puede repetir sobre la misma versión",
        APP / "bd_commands.py",
        "if all(row[0] is not None for row in rows):",
        "if False:",
        COBERTURA,
    ),
    M(
        "la ficha nueva pisa la ficha del respaldo",
        BD / "respaldo.py",
        "if ficha_path(dump).exists():",
        "if False:",
        RESPALDOS,
    ),
    M(
        "la prueba del respaldo no compara la huella",
        BD / "prueba_respaldo.py",
        "if calculated != expected:",
        "if False:",
        RESPALDOS,
    ),
    M(
        "la prueba del respaldo sale 0 aunque algo no se comprobó",
        BD / "prueba_respaldo.py",
        'return 0 if results == ("coincide", "exitosa", "coincide") else 6',
        "return 0",
        RESPALDOS,
    ),
    M(
        "el cambio de base no pide las pruebas declaradas",
        APP / "bd_reconstruir.py",
        "if not tests_approved:",
        "if False:",
        RECONSTRUCCION,
    ),
    M(
        "el cambio de base no compara la versión del esquema aprobada",
        APP / "bd_reconstruir.py",
        "    if measured.database_schema != approved.version_esquema:",
        "    if False:",
        RECONSTRUCCION,
    ),
    M(
        "el cambio de base no compara la huella de contenido aprobada",
        APP / "bd_reconstruir.py",
        "    if measured.content_sha256 != approved.content_sha256:",
        "    if False:",
        RECONSTRUCCION,
    ),
    M(
        "el cambio de base no compara la huella de reglas aprobada",
        APP / "bd_reconstruir.py",
        "    if measured.rules_sha256 != approved.rules_sha256:",
        "    if False:",
        RECONSTRUCCION,
    ),
    M(
        "la comprobación final del cambio de base no se hace",
        APP / "bd_reconstruir.py",
        "        mismatch = _mismatch(after, approved)",
        "        mismatch = None",
        RECONSTRUCCION,
    ),
    M(
        "el cambio de base sigue con conexiones abiertas",
        APP / "bd_reconstruir.py",
        "if _connections(admin, [current, name]):",
        "if False:",
        RECONSTRUCCION,
    ),
    M(
        "la puerta P2 deja pasar unidades abiertas",
        APP / "bd_reconstruir.py",
        "if any(open_items.values()):",
        "if False:",
        RECONSTRUCCION,
    ),
    M(
        "una red que no es de la laptop se toma por local",
        BD / "acceso.py",
        "return not network.is_loopback",
        "return False",
        ACCESO,
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
