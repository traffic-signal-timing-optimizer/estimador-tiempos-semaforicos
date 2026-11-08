"""La página del panel (DEV31 F5): nada externo, y ningún dato se convierte en HTML.

Las páginas son funciones puras de ``app.js``, así que se ejecutan con Node sin navegador. Cada
texto de los datos se envenena con una etiqueta; si una sola página lo escribe sin escapar, se
detecta. Sin Node en el equipo esas pruebas se saltan; las de los archivos, no.
"""

import json
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any, cast

import pytest

from semaforo.app.panel_resumen import comparisons, run_series

ROUTES = [
    "inicio",
    "caso",
    "escenarios",
    "simulaciones",
    "comparacion",
    "busqueda",
    "entrenamiento",
    "consultas",
    "evaluacion",
    "evidencia",
]
HOSTILE = "<img src=x onerror=alert(1)>"
# Mapas cuyas claves son datos (un tramo, un acceso, una corrida), no nombres de campos.
DATA_KEYS = frozenset(
    {"cola", "accesos", "duraciones_s", "problemas_busqueda", "problemas_finalistas", "ineligible"}
)
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="hace falta Node para ejecutar las páginas")
WEB = resources.files("semaforo.app").joinpath("panel_web")
RUNNER = """
const panel = require(process.argv[2]);
const data = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const state = JSON.parse(process.argv[4]);
const out = {};
for (const [route] of panel.ROUTES) out[route] = panel.render(route, data, state);
process.stdout.write(JSON.stringify(out));
"""


def _text(name: str) -> str:
    return WEB.joinpath(name).read_text(encoding="utf-8")


def _render(
    tmp_path: Path, data: dict[str, Any], state: dict[str, Any] | None = None
) -> dict[str, str]:
    app = tmp_path / "app.js"
    app.write_text(_text("app.js"), encoding="utf-8")
    source = tmp_path / "datos.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    runner = tmp_path / "correr.js"
    runner.write_text(RUNNER, encoding="utf-8")
    done = subprocess.run(  # noqa: S603  (Node del equipo con un guion de esta prueba)
        [str(NODE), str(runner), str(app), str(source), json.dumps(state or {})],
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    pages: dict[str, str] = json.loads(done.stdout)
    return pages


def _world() -> dict[str, Any]:
    """Una foto pequeña y completa: un caso, dos planes, una búsqueda, un modelo y su evaluación."""
    case = {"caso_id": "C", "caso_version": "1"}
    observed = {
        "plan_id": "plan-actual",
        "ciclo_s": 100.0,
        "duraciones_s": {"t1": 90.0, "t2": 10.0},
        "es_plan_observado": True,
        "fuente_observada": "fuente",
        "variacion_horaria": "ninguna",
        "confirmado_por": "PO",
        **case,
    }
    other = {
        "plan_id": "plan-otro",
        "ciclo_s": 120.0,
        "duraciones_s": {"t1": 110.0, "t2": 10.0},
        **case,
    }
    runs = [
        {
            "run_id": run,
            "plan_id": plan,
            "semilla_sumo": seed,
            "etapa": stage,
            "escenario_id": "ESC",
            "estado": "succeeded",
            "estado_demora": "complete",
            "estado_cola": "complete",
            "estado_detenciones": "complete",
            "demora_media_s": delay,
            "cola_media_veh": 5.0,
            "cola_maxima_veh": 9,
            "detenciones_media": 1.0,
            "teletransportes_total": 0,
            "choques": 0,
            "ciclo_s": 100.0,
            "origen_demanda": "synthetic",
            "protocolo_metricas_id": "P",
            "manifiesto": "ejecuciones/x/manifest.json",
            "manifiesto_sha256": "a" * 64,
            "metricas": "derivados/metricas/x/metricas.json",
            "metricas_sha256": "b" * 64,
            "version_sumo": "1.27.1",
            "commit_codigo": "c" * 40,
        }
        for run, plan, seed, stage, delay in (
            ("run-a", "plan-actual", 1, "search", 100.0),
            ("run-b", "plan-otro", 1, "search", 80.0),
            ("run-d", "plan-actual", 100, "diagnostic", 110.0),
            ("run-f", "plan-otro", 2001, "finalists", 70.0),
        )
    ]
    candidates = [
        {
            "busqueda_id": "B",
            "candidato_id": name,
            "plan_id": plan,
            "ciclo_s": 100.0,
            "origen": origin,
            "elegible_busqueda": True,
            "posicion_busqueda": 1,
            "puntaje_busqueda_s": 90.0,
            "cola_media_busqueda_veh": 4.0,
            "problemas_busqueda": {"teleports": 1},
            "finalista": finalist,
            "elegible_finalistas": False,
            "problemas_finalistas": {"collisions": 2},
        }
        for name, plan, origin, finalist in (
            ("A", "plan-actual", "current_plan", False),
            ("O", "plan-otro", "sampled", True),
        )
    ]
    seeds: list[dict[str, Any]] = [
        {
            "busqueda_id": "B",
            "candidato_id": name,
            "etapa": stage,
            "semilla": seed,
            "run_id": run,
            "demora_media_s": delay,
            "problemas": [],
            "teletransportes": 0,
            "choques": 0,
        }
        for name, stage, seed, run, delay in (
            ("A", "search", 1, "run-a", 100.0),
            ("O", "search", 1, "run-b", 80.0),
            ("O", "finalists", 2001, "run-f", 70.0),
        )
    ]
    search = {
        "busqueda_id": "B",
        "escenario_id": "ESC",
        "candidatos": 2,
        "presupuesto": 1,
        "elegibles_busqueda": 2,
        "finalistas": 1,
        "elegibles_finalistas": 0,
        "simulaciones": 3,
        "estado_seleccion": "no_reference",
        "motivo_sin_referencia": "no_eligible_finalist",
        "plan_ganador_id": "plan-otro",
        "motivos_descarte": {"search": {"ineligible": {"teleports": 1}}},
        **case,
    }
    plans = [observed, other]
    return {
        "generado_en": "2026-11-08T00:00:00+00:00",
        "commit": "c" * 40,
        "enlaces": {"datos": "../../..", "repositorio": "../../../.."},
        "base": {
            "version_esquema": "sql-1",
            "ultima_carga_id": "L",
            "ultima_carga_estado": "completed",
            "huella_contenido": "d" * 64,
            "conflictos_pendientes": 0,
            "archivos_alcance_desconocido": 1,
        },
        "evidencia": {
            "carpeta": "reportes/bd/x",
            "fecha": "2026-11-08",
            "estado": "ok",
            "codigo": 0,
            "de_esta_base": True,
            "secciones": [{"nombre": "verificar", "estado": "ok"}],
        },
        "avance": {
            "proyecto": {
                "corto": "corto",
                "titulo": "título",
                "objetivo": "objetivo",
                "alcance": "alcance",
            },
            "fases": [
                {
                    "id": "DEV01",
                    "titulo": "hecha",
                    "estado": "hecho",
                    "sirve_para": "algo",
                    "fecha": "2026",
                },
                {"id": "DEV02", "titulo": "falta", "estado": "pendiente", "sirve_para": "algo"},
            ],
            "accesos": {"ACC": "Avenida, de norte a sur"},
        },
        "casos": [
            {
                **case,
                "descripcion": "cruce",
                "origen": "field",
                "estado_representacion": "unverified",
                "ciclo_min_s": 60.0,
                "ciclo_max_s": 200.0,
                "clases": ["auto"],
                "archivo": "casos/C/case.json",
                "archivo_sha256": "e" * 64,
                "red_ruta": "red.xml",
                "red_sha256": "f" * 64,
                "evidencia_restricciones": ["un límite"],
            }
        ],
        "movimientos": [
            {
                **case,
                "movimiento_id": "M1",
                "acceso": "ACC",
                "carriles_entrada": ["ACC_0"],
                "flujo_min_vph": 0.0,
                "flujo_max_vph": 10.0,
            }
        ],
        "tramos": [
            {
                **case,
                "tramo_id": "t1",
                "tipo": "variable",
                "minimo_s": 5.0,
                "maximo_s": 120.0,
                "grupos": [{"grupo_id": "g", "minimo_s": 5.0, "maximo_s": 9.0}],
            },
            {
                **case,
                "tramo_id": "t2",
                "tipo": "fixed",
                "minimo_s": 10.0,
                "maximo_s": 10.0,
                "grupos": [],
            },
        ],
        "planes": plans,
        "escenarios": [
            {
                **case,
                "escenario_id": "ESC",
                "preliminar": True,
                "origen": "synthetic",
                "medicion_s": 900.0,
                "calentamiento_s": 300.0,
                "vaciado_max_s": 900.0,
                "fuentes": ["F"],
                "politica_frontera": "frontera",
                "semilla_demanda": 7,
                "archivo": "escenarios/ESC.json",
                "archivo_sha256": "e" * 64,
            }
        ],
        "zonas": [{"escenario_id": "ESC", "zona": "desarrollo", "particion_id": None}],
        "demanda": [
            {
                "escenario_id": "ESC",
                "movimiento_id": "M1",
                "clase_id": "auto",
                "flujo_vph": 100.0,
                "proporcion": 1.0,
            }
        ],
        "protocolos": [
            {
                "protocolo_id": "P",
                "estado": "draft",
                "definicion_metrica": "definición",
                "umbral_cola_mps": 0.1,
                "muestreo_cola_s": 1.0,
                "carriles_zona": ["ACC_0"],
                "presupuesto_busqueda": 1,
                "semillas_busqueda": [1],
                "semillas_finalistas": [2001],
            }
        ],
        "corridas": runs,
        "series": run_series(runs),
        "accesos": [
            {
                "run_id": run,
                "acceso": "ACC",
                "con_cohorte": cohort,
                "demora_media_s": 50.0 if cohort else None,
                "cola_media_veh": 1.0,
            }
            for run, cohort in (("run-a", True), ("run-b", False))
        ],
        "resultados_movimiento": [
            {
                "run_id": "run-a",
                "movimiento_id": "M1",
                "solicitados": 1,
                "terminados": 1,
                "demora_media_s": 50.0,
                "estado_demora": "complete",
            }
        ],
        "cola": {
            "run-a": {
                "desde_s": [0.0, 60.0],
                "en_ventana": [False, True],
                "accesos": {"ACC": [1.0, 2.0]},
            }
        },
        "cola_intervalo_s": 60,
        "busquedas": [search],
        "candidatos": candidates,
        "candidato_semillas": seeds,
        "comparadores": [
            {
                "escenario_id": "ESC",
                "webster_estado": "not_applicable",
                "webster_problemas": [{"message": "motivo"}],
            }
        ],
        "comparaciones": comparisons([search], candidates, seeds, runs, plans),
        "exclusiones": [
            {
                "archivo": "ejecuciones/z/manifest.json",
                "detalle": "motivo",
                "decision": "accepted_risk",
                "decidido_por": "PO",
                "decidido_en": "2026-11-07",
                "archivo_sha256": "a" * 64,
            }
        ],
        "hitos": [
            {
                "tipo": "test_opened",
                "registrado_en": "2026-12-01",
                "experimento_id": "X",
                "responsable": "PO",
                "acta": "docs/actas/x.md",
            }
        ],
        "etiquetas": [
            {
                "etiqueta_id": "E",
                "escenario_id": "ESC",
                "particion_id": "P1",
                "asignacion": "train",
                "plan_id": "plan-otro",
            }
        ],
        "metricas_modelos": [
            {
                "entrenamiento_id": "T",
                "algoritmo": "xgboost",
                "metrica": "mae",
                "alcance": "global",
                "unidad": "s",
                "valor_entrenamiento": 1.0,
                "valor_validacion": 2.0,
            }
        ],
        "consultas": [
            {
                "request_id": "Q",
                "modelo_id": "M",
                "escenario_id": "ESC",
                "estado": "ok",
                "plan_id": "plan-otro",
                "reglas_incumplidas": 1,
                "codigos": ["R1"],
            }
        ],
        "indicadores": [
            {
                "indicador": "I4",
                "metrica": "demora",
                "alternativa_a": "modelo",
                "alternativa_b": "plan",
                "alcance": "global",
                "valor": -1.0,
                "unidad": "s",
                "ic_inferior": -2.0,
                "ic_superior": 0.5,
                "ic_nivel": 0.95,
                "denominador": 13,
                "faltantes": 0,
            }
        ],
    }


def _poison(value: object, keyed: bool = False) -> object:
    """Cada texto de los datos lleva una etiqueta delante, también los que son nombres de claves."""
    if isinstance(value, str):
        return HOSTILE + value
    if isinstance(value, list):
        return [_poison(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        return {
            (HOSTILE + key if keyed else key): _poison(item, key in DATA_KEYS)
            for key, item in cast("dict[str, object]", value).items()
        }
    return value


# --- los archivos ----------------------------------------------------------------------------


def test_the_page_forbids_everything_that_is_not_its_own_files() -> None:
    page = _text("index.html")
    assert "default-src 'none'" in page
    assert "connect-src" not in page  # sin permiso propio: lo cubre default-src 'none'
    assert re.findall(r'(?:src|href)="([^"#]+)"', page) == ["estilos.css", "datos.js", "app.js"]


@pytest.mark.parametrize("name", ["index.html", "estilos.css", "app.js"])
def test_nothing_is_fetched_from_outside_or_run_as_code(name: str) -> None:
    text = _text(name)
    assert "http://" not in text
    assert "https://" not in text
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "eval(",
        "new Function",
        "@import",
        "url(",
    ):
        assert forbidden not in text, forbidden


def test_the_page_has_no_inline_code_or_styles_the_policy_would_block() -> None:
    page = _text("index.html")
    assert "style=" not in page
    assert " onclick" not in page
    assert "<style" not in page
    assert "style=" not in _text("app.js")


def test_color_is_never_the_only_signal_in_the_page_words() -> None:
    text = _text("app.js")
    assert "con teletransportes o choques" in text  # la forma del punto también lo dice
    assert "Sin cohorte" in text


# --- las páginas -----------------------------------------------------------------------------


@needs_node
def test_every_page_draws_with_a_complete_photo(tmp_path: Path) -> None:
    pages = _render(tmp_path, _world(), {"run": "run-a"})
    assert sorted(pages) == sorted(ROUTES)
    assert "undefined" not in "".join(pages.values())
    assert "NaN" not in "".join(pages.values())
    assert "Avenida, de norte a sur" in pages["caso"]
    assert "Preliminar" in pages["escenarios"]
    assert "No es una comparación emparejada" in pages["comparacion"]
    assert "xgboost" in pages["entrenamiento"]
    assert "R1" in pages["consultas"]
    assert "I4" in pages["evaluacion"]
    assert "Reservada" not in pages["evaluacion"]
    assert "ventana de medición" in pages["simulaciones"]  # el detalle de la corrida


@needs_node
def test_every_page_draws_with_an_empty_photo_and_says_what_is_missing(tmp_path: Path) -> None:
    pages = _render(tmp_path, {})
    assert sorted(pages) == sorted(ROUTES)
    assert "undefined" not in "".join(pages.values())
    assert "Reservada: sin resultados visibles" in pages["evaluacion"]
    assert "Todavía no hay modelos entrenados" in pages["entrenamiento"]
    assert "Todavía no hay consultas" in pages["consultas"]
    assert "Sin búsquedas" in pages["busqueda"]
    assert "Sin caso" in pages["caso"]


@needs_node
def test_the_final_evaluation_stays_reserved_while_there_are_no_indicators(tmp_path: Path) -> None:
    world = _world()
    world["indicadores"] = []
    page = _render(tmp_path, world)["evaluacion"]
    assert "Reservada: sin resultados visibles" in page
    assert "<table" in page  # los hitos sí son públicos


@needs_node
def test_without_synthetic_runs_the_warning_is_not_shown(tmp_path: Path) -> None:
    world = _world()
    assert "Demanda sintética" in _render(tmp_path, world)["inicio"]
    for run in world["corridas"]:
        run["origen_demanda"] = "field"
    assert "Demanda sintética" not in _render(tmp_path, world)["inicio"]


@needs_node
@pytest.mark.parametrize(
    "state", [{}, {"run": HOSTILE + "run-a"}, {"serie": "x", "planAcceso": "y"}]
)
def test_a_hostile_text_in_any_field_is_shown_as_text_in_every_page(
    tmp_path: Path, state: dict[str, Any]
) -> None:
    pages = _render(tmp_path, cast("dict[str, Any]", _poison(_world())), state)
    for route, page in pages.items():
        assert "<img" not in page, route
        assert "onerror=alert(1)>" not in page, route
    assert "&lt;img" in "".join(pages.values())
    assert "&lt;img" in pages["caso"]
    assert "&lt;img" in pages["comparacion"]
    assert "&lt;img" in pages["evidencia"]


@needs_node
def test_a_quote_cannot_escape_from_an_attribute(tmp_path: Path) -> None:
    world = _world()
    world["corridas"][0]["run_id"] = 'x" data-malo="1'
    world["series"][0]["id"] = '"><b>serie'
    page = _render(tmp_path, world)["simulaciones"]
    assert 'data-malo="1"' not in page
    assert "><b>serie" not in page
