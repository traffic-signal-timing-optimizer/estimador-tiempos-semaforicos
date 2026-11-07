"""Ensayo de daño a propósito del verificador del esquema (DEV31 F1). Solo lectura del proyecto.

Aplica un error a una copia del esquema y comprueba que scripts/bd_esquema.py lo detecta.
"""

import importlib.util
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(tempfile.gettempdir())  # el esquema dañado no se guarda en el repositorio
sys.stdout.reconfigure(encoding="utf-8")
spec = importlib.util.spec_from_file_location("bd_esquema", ROOT / "scripts" / "bd_esquema.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
ORIGINAL = (ROOT / "docs" / "bd" / "esquema.toml").read_text(encoding="utf-8")
CATALOG = mod.catalog_names()

MUTATIONS = [
    (
        "tipo distinto en una clave foránea",
        '{ nombre = "plan_id", tipo = "huella", descripcion = "Duraciones del plan vigente."',
        '{ nombre = "plan_id", tipo = "text", descripcion = "Duraciones del plan vigente."',
    ),
    (
        "clave foránea a una columna que no es clave",
        '{ columnas = ["run_id_a"], referencia = "simulacion.corridas", referidas = ["run_id"] }',
        '{ columnas = ["run_id_a"], referencia = "simulacion.corridas", referidas = ["estado"] }',
    ),
    (
        "clave primaria que puede quedar vacía",
        '{ nombre = "caso_version", tipo = "text", descripcion = "Versión del caso.", origen = "case.json: case_version" }',
        '{ nombre = "caso_version", tipo = "text", nulo = true, descripcion = "Versión del caso.", origen = "case.json: case_version" }',
    ),
    (
        "tipo desconocido",
        'tipo = "double precision", unidad = "s", descripcion = "Paso de tiempo de los planes."',
        'tipo = "float", unidad = "s", descripcion = "Paso de tiempo de los planes."',
    ),
    (
        "relación obligatoria sobre columna que puede quedar vacía",
        'referidas = ["protocolo_id"], opcional = true },\n  { columnas = ["plan_id"], referencia = "simulacion.planes", referidas = ["plan_id"], opcional = true },\n  { columnas = ["entorno_id"]',
        'referidas = ["protocolo_id"] },\n  { columnas = ["plan_id"], referencia = "simulacion.planes", referidas = ["plan_id"], opcional = true },\n  { columnas = ["entorno_id"]',
    ),
    (
        "tabla aprobada que no está en el catálogo del acta",
        'esquema = "control"\nnombre = "hitos"\n',
        'esquema = "control"\nnombre = "hitos_extra"\n',
    ),
    ("tabla sin clave primaria", 'clave_primaria = ["hito_id"]\n', ""),
    (
        "cegado por un padre que no está cegado",
        'cegado = "padre:aprendizaje.consultas(request_id)"',
        'cegado = "padre:caso.casos(caso_id)"',
    ),
    (
        "raíz de cegado obligatoria sobre columna que puede quedar vacía",
        'cegado = "raiz_opcional:escenario_id"',
        'cegado = "raiz:escenario_id"',
    ),
    (
        "clave foránea a una tabla inexistente",
        '{ columnas = ["particion_id"], referencia = "experimento.particiones", referidas = ["particion_id"] },\n  { columnas = ["caso_id", "caso_version"], referencia = "caso.casos"',
        '{ columnas = ["particion_id"], referencia = "experimento.particion", referidas = ["particion_id"] },\n  { columnas = ["caso_id", "caso_version"], referencia = "caso.casos"',
    ),
    (
        "columna repetida",
        '{ nombre = "inicio", tipo = "timestamptz", descripcion = "Momento en que empieza la carga.", origen = "cargador" },',
        '{ nombre = "inicio", tipo = "timestamptz", descripcion = "Momento en que empieza la carga.", origen = "cargador" },\n  { nombre = "inicio", tipo = "timestamptz", descripcion = "Copia.", origen = "cargador" },',
    ),
    ("nombre de columna inválido", '{ nombre = "tick_s",', '{ nombre = "Tick_s",'),
    (
        "uno a uno que no usa la clave primaria",
        '{ columnas = ["artefacto_metricas_id"], referencia = "control.artefactos", referidas = ["artefacto_id"], opcional = true },',
        '{ columnas = ["artefacto_metricas_id"], referencia = "control.artefactos", referidas = ["artefacto_id"], opcional = true, uno_a_uno = true },',
    ),
    (
        "columna sin origen",
        '{ nombre = "detalle", tipo = "text", descripcion = "Explicación del problema.", origen = "cargador" },',
        '{ nombre = "detalle", tipo = "text", descripcion = "Explicación del problema." },',
    ),
]


def detected(text: str) -> tuple[bool, str]:
    path = SCRATCH / "esquema_danado.toml"
    path.write_text(text, encoding="utf-8")
    try:
        design = mod.load(path)
    except (mod.SchemaError, tomllib.TOMLDecodeError) as error:
        return True, f"ilegible: {error}"
    errors = mod.verify(design, CATALOG)
    return bool(errors), (errors[0] if errors else "sin errores")


base_ok, base_msg = detected(ORIGINAL)
print(f"esquema original: {'FALLA' if base_ok else 'correcto'} ({base_msg})")
caught = 0
for name, old, new in MUTATIONS:
    count = ORIGINAL.count(old)
    if count == 0:
        print(f"[NO APLICA] {name}: el texto a cambiar no está")
        continue
    hit, msg = detected(ORIGINAL.replace(old, new, 1))
    caught += hit
    print(f"[{'detectado' if hit else 'SOBREVIVE'}] {name} -> {msg[:150]}")
print(f"\n{caught} de {len(MUTATIONS)} daños detectados")
