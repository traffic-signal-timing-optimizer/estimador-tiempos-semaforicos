"""Reglas que aplica la propia base: cegado, hitos, solo agregar y permisos (DEV31 F3).

Cada prueba usa una base temporal nueva con el esquema (``base``). Las filas se escriben como
``semaforo_admin`` (el dueño, que no está sujeto al cegado pero sí a los disparadores).
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from bd_tools import insert, rows_of, scalar
from prepared_inputs import request_for
from search_tools import protocol
from semaforo.app.bd_panel import generate_panel
from semaforo.bd.barrido import sweep, sweep_exit_code
from semaforo.bd.carga.caso import case_unit, protocol_unit
from semaforo.bd.carga.corridas import entorno_row
from semaforo.bd.carga.modelo import CargaError, Row, Unit
from semaforo.bd.carga.motor import artifact_rows
from semaforo.bd.conexion import ADMIN, CARGA, LECTURA, PANEL, connect
from semaforo.bd.ddl import PANEL_VIEWS
from semaforo.bd.diseno import load
from semaforo.bd.panel_datos import read_panel_rows
from workspace_tools import build_workspace

pytestmark = pytest.mark.bd

SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "bd" / "esquema.toml"

MOMENT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
SOURCE = "datos:prueba/origen.json"
HASH = "a" * 64


def _merge(*units: Unit) -> dict[str, list[Row]]:
    rows: dict[str, list[Row]] = {"control.artefactos": []}
    for unit in units:
        rows["control.artefactos"] += artifact_rows(unit)
        for table, found in unit.rows.items():
            rows.setdefault(table, []).extend(found)
    rows["control.artefactos"].append(
        {
            "artefacto_id": SOURCE,
            "raiz": "datos",
            "ruta_relativa": "prueba/origen.json",
            "tipo": "other",
            "tamano_bytes": 1,
            "sha256": HASH,
            "manifiesto_id": None,
            "estado": "intact",
            "alcance": "global",
            "motivo": None,
            "registrado_en": MOMENT,
        }
    )
    return rows


def _row(**values: object) -> Row:
    return {**values, "artefacto_id": SOURCE}


@dataclass(frozen=True)
class World:
    """Un caso, un protocolo congelado, dos escenarios (desarrollo y prueba) y su partición."""

    database: str
    case_id: str
    case_version: str
    protocol_id: str
    train: str
    test: str
    entorno: str


def _scenario(world_case: tuple[str, str], scenario_id: str, family: str, base: Row) -> list[Row]:
    case_id, version = world_case
    return [
        _row(
            caso_id=case_id,
            caso_version=version,
            familia_id=family,
            origen="synthetic",
            variantes=None,
            semillas=None,
            rangos_demanda=None,
        ),
        _row(**{**base, "escenario_id": scenario_id, "familia_id": family, "preliminar": False}),
    ]


def _run(world: World, run_id: str, scenario: str, **changes: object) -> Row:
    return _row(
        **{
            "run_id": run_id,
            "estado": "succeeded",
            "creada_en": MOMENT,
            "caso_id": world.case_id,
            "caso_version": world.case_version,
            "escenario_id": scenario,
            "etapa": "diagnostic",
            "comando": ["sumo"],
            "entorno_id": world.entorno,
            "codigo_salida": 0,
            **changes,
        }
    )


@pytest.fixture
def world(tmp_path: Path, base: str) -> World:
    workspace, _ = build_workspace(tmp_path)
    request = request_for(tmp_path)
    case = request.case
    protocols = workspace / "derivados" / "protocolos" / case.case_id
    protocols.mkdir(parents=True)
    (protocols / "p.json").write_text(protocol(status="frozen").model_dump_json(), encoding="utf-8")
    case_rows, _ = case_unit(workspace, case.case_id)
    protocol_rows, rules = protocol_unit(workspace, f"derivados/protocolos/{case.case_id}/p.json")
    rows = _merge(case_rows, protocol_rows)
    template: Row = {
        "caso_id": case.case_id,
        "caso_version": case.case_version,
        "origen": "synthetic",
        "request_id": "SOL-1",
        "origen_solicitud": "synthetic",
        "inicio_observacion": MOMENT,
        "fin_observacion": MOMENT,
        "fuentes": ["F"],
        "politica_frontera": "DEMO_EMPTY_START_FIXED_ROUTES",
        "calentamiento_s": 60.0,
        "medicion_s": 300.0,
        "vaciado_max_s": 60.0,
        "semilla_demanda": 1,
        "demanda_ruta": None,
        "demanda_sha256": None,
        "huella_escenario": HASH,
    }
    identity = (case.case_id, case.case_version)
    families: list[Row] = []
    scenarios: list[Row] = []
    for scenario_id, family in (("ESC-TRAIN", "F-TRAIN"), ("ESC-TEST", "F-TEST")):
        family_row, scenario_row = _scenario(identity, scenario_id, family, template)
        families.append(family_row)
        scenarios.append(scenario_row)
    environment = entorno_row({"python": "3.12.3", "os": "Windows 11"})
    rows |= {
        "experimento.familias": families,
        "experimento.escenarios": scenarios,
        "experimento.particiones": [
            _row(particion_id="P1", politica="prueba", semilla=1, congelada=True)
        ],
        "experimento.asignaciones": [
            _row(
                particion_id="P1",
                escenario_id="ESC-TRAIN",
                familia_id="F-TRAIN",
                asignacion="train",
            ),
            _row(
                particion_id="P1", escenario_id="ESC-TEST", familia_id="F-TEST", asignacion="test"
            ),
        ],
        "control.entornos": [_row(**environment)],
    }
    insert(base, rows)
    made = World(
        database=base,
        case_id=case.case_id,
        case_version=case.case_version,
        protocol_id=rules.protocol_id,
        train="ESC-TRAIN",
        test="ESC-TEST",
        entorno=str(environment["entorno_id"]),
    )
    runs = [_run(made, "RUN-TRAIN", "ESC-TRAIN"), _run(made, "RUN-TEST", "ESC-TEST")]
    events = [
        _row(
            run_id=run,
            orden=1,
            tiempo_s=1.0,
            tipo="warning",
            subtipo=None,
            vehiculo_id=None,
            otro_vehiculo_id=None,
            carril_id=None,
            texto="Warning: algo",
        )
        for run in ("RUN-TRAIN", "RUN-TEST")
    ]
    insert(base, {"simulacion.corridas": runs, "simulacion.eventos": events})
    return made


def _sqlstate(action: Callable[[], object]) -> str | None:
    try:
        action()
    except psycopg.Error as error:
        return error.sqlstate
    return None


def _milestone(world: World, hito_id: str, kind: str, **objects: object) -> dict[str, list[Row]]:
    names = (
        "protocolo_id",
        "particion_id",
        "modelo_id",
        "experimento_id",
        "seleccion_id",
        "huella_seleccion",
    )
    values: dict[str, object] = {name: None for name in names}
    if kind == "model_frozen":
        values.update(seleccion_id="S1", huella_seleccion=HASH)
    values.update(objects)
    return {
        "control.hitos": [
            _row(
                hito_id=hito_id,
                tipo=kind,
                registrado_en=MOMENT + timedelta(minutes=int(hito_id[1]) + 1),
                huella_objeto=HASH,
                commit_codigo=None,
                responsable="prueba",
                notas=None,
                **values,
            )
        ]
    }


def _model_rows(world: World) -> dict[str, list[Row]]:
    ids = {"caso_id": world.case_id, "caso_version": world.case_version}
    return {
        "aprendizaje.conjuntos": [
            _row(
                conjunto_id="C1",
                particion_id="P1",
                **ids,
                orden_entradas=[],
                orden_salidas=[],
                etiquetas_entrenamiento=0,
                etiquetas_validacion=0,
                etiquetas_excluidas=0,
                motivos_exclusion={},
                huella_conjunto=HASH,
                creado_en=MOMENT,
            )
        ],
        "aprendizaje.entrenamientos": [
            _row(
                entrenamiento_id="E1",
                conjunto_id="C1",
                algoritmo="median",
                configuracion={},
                semilla=None,
                particiones_entrenamiento=["train"],
                politica_reajuste="train_only",
                version_libreria=None,
                entorno_id=world.entorno,
                estado="succeeded",
                inicio=MOMENT,
                fin=None,
                duracion_s=None,
            )
        ],
        "aprendizaje.modelos": [
            _row(
                modelo_id="M1",
                estado_manifiesto="frozen",
                **ids,
                algoritmo="median",
                orden_entradas=[],
                orden_tramos_variables=[],
                version_reglas="v",
                particion_id="P1",
                conjunto_id="C1",
                entrenamiento_id="E1",
                particiones_entrenamiento=["train"],
                archivos=[],
                entorno={},
                dominio=None,
                huella_paquete=None,
            )
        ],
        "aprendizaje.seleccion": [
            _row(
                seleccion_id="S1",
                particion_id="P1",
                protocolo_id=world.protocol_id,
                huella_seleccion=HASH,
                criterios=["factibilidad"],
                candidatos=["M1"],
                modelo_ganador_id="M1",
                motivo="prueba",
                decidido_en=MOMENT,
            )
        ],
        "evaluacion.experimentos": [
            _row(
                experimento_id="X1",
                **ids,
                protocolo_id=world.protocol_id,
                particion_id="P1",
                modelo_id="M1",
                seleccion_id="S1",
                alternativas=["model"],
                creado_en=MOMENT,
                huella_experimento=HASH,
            )
        ],
    }


def _visible(database: str) -> dict[str, list[str]]:
    return {
        "escenarios": [
            str(r[0])
            for r in rows_of(database, "SELECT escenario_id FROM experimento.escenarios ORDER BY 1")
        ],
        "corridas": [
            str(r[0])
            for r in rows_of(database, "SELECT run_id FROM simulacion.corridas ORDER BY 1")
        ],
        "eventos": [
            str(r[0]) for r in rows_of(database, "SELECT run_id FROM simulacion.eventos ORDER BY 1")
        ],
        "vista": [
            str(r[0])
            for r in rows_of(database, "SELECT escenario_id FROM vistas.zona_escenario ORDER BY 1")
        ],
    }


def test_the_reader_does_not_see_a_closed_test_and_the_loader_sees_everything(
    world: World,
) -> None:
    seen = _visible(world.database)
    assert seen == {
        "escenarios": ["ESC-TRAIN"],
        "corridas": ["RUN-TRAIN"],
        "eventos": ["RUN-TRAIN"],
        "vista": ["ESC-TRAIN"],
    }
    loader = rows_of(world.database, "SELECT run_id FROM simulacion.corridas ORDER BY 1", CARGA)
    assert [r[0] for r in loader] == ["RUN-TEST", "RUN-TRAIN"]
    hidden = rows_of(world.database, "SELECT escenario_id FROM control.escenarios_cegados")
    assert hidden == [("ESC-TEST",)]


def test_the_panel_reads_only_approved_views_and_sees_no_closed_test(world: World) -> None:
    database = world.database
    assert (
        _sqlstate(lambda: rows_of(database, "SELECT run_id FROM simulacion.corridas", PANEL))
        == "42501"
    )
    assert rows_of(database, "SELECT run_id FROM vistas.corridas_resumen ORDER BY 1", PANEL) == [
        ("RUN-TRAIN",)
    ]
    assert (
        _sqlstate(lambda: rows_of(database, "SELECT carga_id FROM vistas.estado_cargas", PANEL))
        == "42501"
    )


def test_catalog_sweep_hides_test_marks_and_denies_panel_tables(  # noqa: PLR0915  (un solo recorrido)
    world: World, tmp_path: Path
) -> None:
    """P6/C3.2: cada tabla y vista se inspecciona, incluidas las futuras."""
    database = world.database
    hidden_file = "datos:prueba/ARCHIVO-PRUEBA-OCULTA.json"
    hidden_plan = "e" * 64
    hidden_duration = 7777.125
    hidden_search = "BUSQUEDA-PRUEBA-OCULTA"
    tramo = str(rows_of(database, "SELECT tramo_id FROM caso.tramos LIMIT 1", ADMIN)[0][0])
    insert(
        database,
        {
            "control.artefactos": [
                {
                    "artefacto_id": hidden_file,
                    "raiz": "datos",
                    "ruta_relativa": "prueba/ARCHIVO-PRUEBA-OCULTA.json",
                    "tipo": "other",
                    "tamano_bytes": 1,
                    "sha256": HASH,
                    "manifiesto_id": None,
                    "estado": "intact",
                    "alcance": "escenarios",
                    "motivo": None,
                    "registrado_en": MOMENT,
                }
            ],
            "control.archivo_escenarios": [
                {"artefacto_id": hidden_file, "escenario_id": world.test}
            ],
            "simulacion.planes": [
                _row(
                    plan_id=hidden_plan,
                    caso_id=world.case_id,
                    caso_version=world.case_version,
                    duraciones_s={tramo: hidden_duration},
                    ciclo_s=hidden_duration,
                )
            ],
            "simulacion.plan_tramos": [
                _row(
                    plan_id=hidden_plan,
                    tramo_id=tramo,
                    duracion_s=hidden_duration,
                    caso_id=world.case_id,
                    caso_version=world.case_version,
                )
            ],
            "simulacion.corridas": [_run(world, "RUN-PLAN-TEST", world.test, plan_id=hidden_plan)],
            "simulacion.busquedas": [
                _row(
                    busqueda_id=hidden_search,
                    escenario_id=world.test,
                    caso_id=world.case_id,
                    caso_version=world.case_version,
                    protocolo_id=world.protocol_id,
                    estado_protocolo="frozen",
                    metodo="grid",
                    version_busqueda="v",
                    version_reglas="v",
                    version_identidad=None,
                    version_bitacora=None,
                    semilla=1,
                    presupuesto=1,
                    cuenta_presupuesto="diagnostic",
                    presupuesto_usado=0,
                    limite_intentos=1,
                    intentos=0,
                    duplicados=0,
                    inviables=0,
                    inviables_por_regla={},
                    cuadricula_factible=0,
                    limite_cuadricula=1,
                    tamano_espacio=1,
                    agotado=False,
                    estado_plan_vigente="absent",
                    estado_webster=None,
                    finalistas=0,
                    epsilon_empate_s=0.0,
                    semillas_busqueda=[],
                    semillas_finalistas=[],
                    opciones_sumo={},
                    huella_candidatos=HASH,
                    regla_seleccion="diagnostic",
                    estado_seleccion="no_reference",
                    motivo_sin_referencia="no_candidates",
                    cobertura={},
                    simulaciones=0,
                    interrumpida=False,
                )
            ],
        },
    )
    hidden_candidate = "CANDIDATO-PRUEBA-OCULTO"
    hidden_comparator = "COMPARADOR-PRUEBA-OCULTO"
    hidden_access = "ACCESO-PRUEBA-OCULTO"
    hidden_flow = 4242.125
    movement = str(
        rows_of(database, "SELECT movimiento_id FROM caso.movimientos LIMIT 1", ADMIN)[0][0]
    )
    klass = str(rows_of(database, "SELECT clase_id FROM caso.tipos_vehiculo LIMIT 1", ADMIN)[0][0])
    public_plan = "f" * 64
    case_ids = {"caso_id": world.case_id, "caso_version": world.case_version}
    insert(
        database,
        {
            "simulacion.planes": [
                _row(plan_id=public_plan, **case_ids, duraciones_s={tramo: 1.0}, ciclo_s=1.0)
            ],
            "caso.planes_observados": [
                _row(
                    plan_observado_id="OBSERVADO",
                    **case_ids,
                    plan_id=public_plan,
                    fuente="prueba",
                    variacion_horaria="ninguna",
                    confirmado_por="prueba",
                    carpeta_programa="prueba",
                    reglas_incumplidas=[],
                )
            ],
            "simulacion.candidatos": [
                _row(
                    busqueda_id=hidden_search,
                    candidato_id=hidden_candidate,
                    plan_id=hidden_plan,
                    origen="sampled",
                    consume_presupuesto=True,
                    orden=0,
                    finalista=False,
                    ganador=False,
                )
            ],
            "simulacion.candidato_semillas": [
                _row(
                    busqueda_id=hidden_search,
                    candidato_id=hidden_candidate,
                    etapa="search",
                    semilla=1,
                    run_id="RUN-PLAN-TEST",
                    teletransportes=0,
                    choques=0,
                    problemas=[],
                )
            ],
            "simulacion.comparadores": [
                _row(
                    comparador_id=hidden_comparator,
                    escenario_id=world.test,
                    **case_ids,
                    origen_caso="synthetic",
                    origen_demanda="synthetic",
                    origen_evidencia="synthetic",
                    plan_observado_id="OBSERVADO",
                    webster_estado="not_applicable",
                    webster_adaptacion="prueba",
                    conjunto_parametros="prueba",
                    provisional=True,
                    webster_reglas_incumplidas=[],
                    webster_problemas=[],
                    saturacion_vph_carril=1800.0,
                    equivalencias_vehiculo={},
                    estado_parametros="provisional",
                    parametros={},
                )
            ],
            "experimento.demanda": [
                _row(
                    escenario_id=world.test,
                    **case_ids,
                    movimiento_id=movement,
                    clase_id=klass,
                    flujo_vph=hidden_flow,
                    proporcion=1.0,
                )
            ],
            "simulacion.resultados_corrida": _steps_result("RUN-PLAN-TEST", [0.0])[
                "simulacion.resultados_corrida"
            ],
            "simulacion.resultados_acceso": [
                _row(run_id="RUN-PLAN-TEST", acceso=hidden_access, con_cohorte=False)
            ],
            "simulacion.resultados_movimiento": [
                _row(
                    run_id="RUN-PLAN-TEST",
                    **case_ids,
                    movimiento_id=movement,
                    solicitados=0,
                    terminados=0,
                    sin_terminar=0,
                    no_insertados=0,
                    estado_demora="empty",
                    suma_demora_s=0.0,
                )
            ],
        },
    )
    # Una exclusión ya decidida de un archivo de la prueba cerrada tampoco se muestra.
    with connect(ADMIN, database=database) as admin:
        admin.execute(
            "INSERT INTO control.conflictos (conflicto_id, tipo, detalle, detectado_en, decision, "
            "decidido_en, decidido_por, carga_id, artefacto_id) VALUES ('CONFLICTO-OCULTO', "
            "'not_loadable', 'CONFLICTO-OCULTO', now(), 'accepted_risk', now(), 'prueba', "
            "'prueba', %s)",
            (hidden_file,),
        )
        admin.commit()
    with connect(ADMIN, database=database) as admin:
        relations = [
            (str(schema), str(name), str(kind))
            for schema, name, kind in admin.execute(
                "SELECT n.nspname, c.relname, c.relkind FROM pg_class AS c "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname IN ('control', 'caso', 'experimento', 'simulacion', "
                "'referencias', 'aprendizaje', 'estimacion', 'evaluacion', 'vistas') "
                "AND c.relkind IN ('r', 'p', 'v') ORDER BY 1, 2"
            )
        ]
    # Las tablas del diseño entran solas al barrido: la lista sale del diseño, no está escrita aquí.
    designed = {f"{table.esquema}.{table.nombre}" for table in load(SCHEMA).tablas}
    swept = {f"{schema}.{name}" for schema, name, kind in relations if kind in {"r", "p"}}
    assert swept == designed
    assert len([rel for rel in relations if rel[2] == "v"]) >= len(PANEL_VIEWS)
    marks = (
        world.test,
        "RUN-TEST",
        "RUN-PLAN-TEST",
        hidden_file,
        hidden_plan,
        str(hidden_duration),
        hidden_search,
        hidden_candidate,
        hidden_comparator,
        hidden_access,
        str(hidden_flow),
    )
    allowed = {
        ("experimento.asignaciones", "escenario_id"),
        ("control.escenarios_cegados", "escenario_id"),
    }
    for role in (LECTURA, PANEL):
        with connect(role, database=database, autocommit=True) as connection:
            for schema, name, _kind in relations:
                full = f"{schema}.{name}"
                query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema, name))
                permitted = role == LECTURA or (schema == "vistas" and name in PANEL_VIEWS)
                if not permitted:
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        connection.execute(query)
                    continue
                cursor = connection.execute(query)
                columns = [column.name for column in cursor.description or []]
                for row in cursor:
                    for column, value in zip(columns, row, strict=True):
                        if (full, column) in allowed:
                            continue
                        assert not any(mark in str(value) for mark in marks), (
                            role,
                            full,
                            column,
                            value,
                        )
    # Lo que el panel lee y lo que publica tampoco lleva ninguna marca.
    panel_rows = json.dumps(read_panel_rows(database), default=str)
    workspace = tmp_path / "panel"
    workspace.mkdir()
    closed = generate_panel(workspace, tmp_path, database=database)
    published = workspace.joinpath(*closed.folder.split("/"), "datos.js").read_text(
        encoding="utf-8"
    )
    for mark in marks:
        assert mark not in panel_rows, mark
        assert mark not in published, mark
    assert "RUN-TRAIN" in panel_rows  # lo visible, sí
    assert "CONFLICTO-OCULTO" not in panel_rows
    # Las semillas de la etapa final no salen, aunque el protocolo sea público.
    final = {
        int(row[0])
        for row in rows_of(
            database,
            "SELECT semilla FROM experimento.protocolo_semillas WHERE etapa = 'final'",
            ADMIN,
        )
    }
    assert final
    for protocol_row in read_panel_rows(database)["protocolos"]:
        assert not final & set(
            protocol_row["semillas_busqueda"] + protocol_row["semillas_finalistas"]
        )
    for code, kind, objects in (
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P1"}),
        ("H3", "model_frozen", {"modelo_id": "M1"}),
        ("H4", "test_opened", {"experimento_id": "X1", "particion_id": "P1"}),
    ):
        if code == "H1":
            insert(database, _model_rows(world))
        insert(database, _milestone(world, code, kind, **objects))
    # Abierta la prueba, lo mismo que estaba oculto aparece en el panel, sin cambiar una fila.
    opened = json.dumps(read_panel_rows(database), default=str)
    for mark in (world.test, "RUN-PLAN-TEST", hidden_search, hidden_candidate, hidden_comparator):
        assert mark in opened, mark
    assert hidden_access in opened
    assert hidden_flow in [row["flujo_vph"] for row in read_panel_rows(database)["demanda"]]
    assert (hidden_file, world.test) in rows_of(
        database, "SELECT artefacto_id, escenario_id FROM control.archivo_escenarios"
    )
    assert ("RUN-PLAN-TEST",) in rows_of(
        database, "SELECT run_id FROM vistas.corridas_resumen", PANEL
    )
    assert (hidden_search,) in rows_of(database, "SELECT busqueda_id FROM simulacion.busquedas")
    assert (hidden_duration,) in rows_of(database, "SELECT duracion_s FROM simulacion.plan_tramos")


def test_the_test_opens_only_in_order_and_then_appears_without_changing_any_row(
    world: World,
) -> None:
    database = world.database
    insert(database, _model_rows(world))
    early = _sqlstate(
        lambda: insert(database, _milestone(world, "H0", "model_frozen", modelo_id="M1"))
    )
    assert early == "SM001"  # sin partición congelada
    insert(database, _milestone(world, "H1", "protocol_frozen", protocolo_id=world.protocol_id))
    insert(database, _milestone(world, "H2", "split_frozen", particion_id="P1"))
    opening = _milestone(world, "H4", "test_opened", experimento_id="X1", particion_id="P1")
    assert _sqlstate(lambda: insert(database, opening)) == "SM001"  # sin modelo congelado
    insert(database, _milestone(world, "H3", "model_frozen", modelo_id="M1"))
    assert _visible(database)["escenarios"] == ["ESC-TRAIN"]  # congelar no abre la prueba
    repeated = _milestone(world, "H3b", "split_frozen", particion_id="P1")
    assert _sqlstate(lambda: insert(database, repeated)) == "23505"  # un hito por objeto
    before = scalar(database, "SELECT count(*) FROM simulacion.corridas", role=ADMIN)
    insert(database, opening)
    assert _visible(database)["escenarios"] == ["ESC-TEST", "ESC-TRAIN"]
    assert _visible(database)["eventos"] == ["RUN-TEST", "RUN-TRAIN"]
    assert scalar(database, "SELECT count(*) FROM simulacion.corridas", role=ADMIN) == before


def test_a_mixed_file_stays_hidden_until_every_link_is_visible(world: World) -> None:
    database = world.database
    files: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    for name, scope, scenarios in (
        ("solo-desarrollo", "escenarios", [world.train]),
        ("mixto", "escenarios", [world.train, world.test]),
        ("sin-enlaces", "escenarios", []),
        ("desconocido", "desconocido", []),
    ):
        identifier = f"datos:prueba/{name}.json"
        files.append(
            {
                "artefacto_id": identifier,
                "raiz": "datos",
                "ruta_relativa": f"prueba/{name}.json",
                "tipo": "other",
                "tamano_bytes": 1,
                "sha256": HASH,
                "manifiesto_id": None,
                "estado": "intact",
                "alcance": scope,
                "motivo": None,
                "registrado_en": MOMENT,
            }
        )
        links.extend(
            {"artefacto_id": identifier, "escenario_id": scenario} for scenario in scenarios
        )
    insert(database, {"control.artefactos": files, "control.archivo_escenarios": links})
    query = (
        "SELECT ruta_relativa FROM control.artefactos "
        "WHERE ruta_relativa LIKE 'prueba/%' ORDER BY 1"
    )
    links_query = (
        "SELECT artefacto_id, escenario_id FROM control.archivo_escenarios "
        "WHERE artefacto_id LIKE 'datos:prueba/%' ORDER BY 1, 2"
    )
    assert rows_of(database, query) == [("prueba/origen.json",), ("prueba/solo-desarrollo.json",)]
    assert rows_of(database, links_query) == [("datos:prueba/solo-desarrollo.json", "ESC-TRAIN")]
    insert(database, _model_rows(world))
    for code, kind, objects in (
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P1"}),
        ("H3", "model_frozen", {"modelo_id": "M1"}),
        ("H4", "test_opened", {"experimento_id": "X1", "particion_id": "P1"}),
    ):
        insert(database, _milestone(world, code, kind, **objects))
    assert rows_of(database, query) == [
        ("prueba/mixto.json",),
        ("prueba/origen.json",),
        ("prueba/solo-desarrollo.json",),
    ]
    assert rows_of(database, links_query) == [
        ("datos:prueba/mixto.json", "ESC-TEST"),
        ("datos:prueba/mixto.json", "ESC-TRAIN"),
        ("datos:prueba/solo-desarrollo.json", "ESC-TRAIN"),
    ]


def test_a_plan_and_a_replica_need_a_visible_use_on_both_sides(world: World) -> None:
    database = world.database
    ids = {"train": "c" * 64, "test": "d" * 64}
    tramo = str(rows_of(database, "SELECT tramo_id FROM caso.tramos LIMIT 1", ADMIN)[0][0])
    plans = [
        _row(
            plan_id=identifier,
            caso_id=world.case_id,
            caso_version=world.case_version,
            duraciones_s={tramo: 10.0},
            ciclo_s=10.0,
        )
        for identifier in ids.values()
    ]
    runs = [
        _run(world, f"RUN-PLAN-{zone.upper()}", getattr(world, zone), plan_id=identifier)
        for zone, identifier in ids.items()
    ]
    tramos = [
        _row(
            plan_id=identifier,
            tramo_id=tramo,
            duracion_s=10.0,
            caso_id=world.case_id,
            caso_version=world.case_version,
        )
        for identifier in ids.values()
    ]
    replica = _row(
        replica_id="REPLICA-MIXTA",
        run_id_a=runs[0]["run_id"],
        run_id_b=runs[1]["run_id"],
        creada_en=MOMENT,
        semilla_a=None,
        semilla_b=None,
        entradas_iguales=True,
        diferencias_entrada={},
        tolerancia={},
        archivos={},
        veredicto="equivalent",
        motivos=[],
    )
    insert(
        database,
        {
            "simulacion.planes": plans,
            "simulacion.plan_tramos": tramos,
            "simulacion.corridas": runs,
            "control.replicas": [replica],
        },
    )
    assert rows_of(database, "SELECT plan_id FROM simulacion.planes ORDER BY 1") == [
        (ids["train"],)
    ]
    assert rows_of(database, "SELECT plan_id FROM simulacion.plan_tramos") == [(ids["train"],)]
    assert rows_of(database, "SELECT replica_id FROM control.replicas") == []
    assert rows_of(
        database,
        "SELECT run_id FROM vistas.corridas_resumen WHERE run_id LIKE 'RUN-PLAN-%'",
        PANEL,
    ) == [("RUN-PLAN-TRAIN",)]


def test_a_difference_needs_both_comparisons_visible(world: World) -> None:
    database = world.database
    insert(database, _model_rows(world))
    comparisons = [
        _row(
            comparacion_id=f"COMP-{zone.upper()}",
            experimento_id="X1",
            escenario_id=getattr(world, zone),
            alternativa="model",
            semilla=7,
            aplicable=True,
            motivo_no_aplicable=None,
            run_id=None,
            plan_id=None,
            request_id=None,
            etiqueta_id=None,
            comparador_id=None,
            rutas_sha256=None,
            red_sha256=None,
        )
        for zone in ("train", "test")
    ]
    difference = _row(
        diferencia_id="DIF-MIXTA",
        experimento_id="X1",
        comparacion_a_id="COMP-TRAIN",
        comparacion_b_id="COMP-TEST",
        metrica="delay",
        alcance="total",
        valor_a=1.0,
        valor_b=2.0,
        diferencia=-1.0,
        unidad="s",
        censurada=False,
        veredicto="a_lower",
        tolerancia=0.0,
    )
    insert(
        database,
        {
            "evaluacion.comparaciones": comparisons,
            "evaluacion.diferencias": [difference],
        },
    )
    assert rows_of(database, "SELECT comparacion_id FROM evaluacion.comparaciones") == [
        ("COMP-TRAIN",)
    ]
    assert rows_of(database, "SELECT diferencia_id FROM evaluacion.diferencias") == []
    for code, kind, objects in (
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P1"}),
        ("H3", "model_frozen", {"modelo_id": "M1"}),
        ("H4", "test_opened", {"experimento_id": "X1", "particion_id": "P1"}),
    ):
        insert(database, _milestone(world, code, kind, **objects))
    assert rows_of(database, "SELECT diferencia_id FROM evaluacion.diferencias") == [("DIF-MIXTA",)]


def test_a_model_freeze_fixes_the_selection_and_rejects_another_hash(world: World) -> None:
    database = world.database
    insert(database, _model_rows(world))
    for code, kind, objects in (
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P1"}),
    ):
        insert(database, _milestone(world, code, kind, **objects))
    wrong = _milestone(world, "H3", "model_frozen", modelo_id="M1", huella_seleccion="b" * 64)
    assert _sqlstate(lambda: insert(database, wrong)) == "SM001"
    insert(database, _milestone(world, "H3", "model_frozen", modelo_id="M1"))
    selection = _model_rows(world)["aprendizaje.seleccion"][0]
    duplicate = {**selection, "seleccion_id": "S2"}
    assert _sqlstate(lambda: insert(database, {"aprendizaje.seleccion": [duplicate]})) == "23505"


def test_a_selection_without_protocol_or_decided_after_freeze_is_rejected(world: World) -> None:
    database = world.database
    rows = _model_rows(world)
    rows["aprendizaje.seleccion"][0]["protocolo_id"] = None
    with pytest.raises(CargaError):
        insert(database, rows)
    rows = _model_rows(world)
    rows["aprendizaje.seleccion"][0]["decidido_en"] = MOMENT + timedelta(days=1)
    insert(database, rows)
    insert(database, _milestone(world, "H1", "protocol_frozen", protocolo_id=world.protocol_id))
    insert(database, _milestone(world, "H2", "split_frozen", particion_id="P1"))
    assert (
        _sqlstate(lambda: insert(database, _milestone(world, "H3", "model_frozen", modelo_id="M1")))
        == "SM001"
    )


def test_opening_rejects_a_selection_other_than_the_frozen_one(world: World) -> None:
    database = world.database
    rows = _model_rows(world)
    rows["aprendizaje.modelos"].append({**rows["aprendizaje.modelos"][0], "modelo_id": "M2"})
    rows["aprendizaje.seleccion"].append(
        {
            **rows["aprendizaje.seleccion"][0],
            "seleccion_id": "S2",
            "modelo_ganador_id": "M2",
            "huella_seleccion": "b" * 64,
        }
    )
    rows["evaluacion.experimentos"][0]["seleccion_id"] = "S2"
    insert(database, rows)
    for code, kind, objects in (
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P1"}),
        ("H3", "model_frozen", {"modelo_id": "M1"}),
    ):
        insert(database, _milestone(world, code, kind, **objects))
    opening = _milestone(world, "H4", "test_opened", experimento_id="X1", particion_id="P1")
    assert _sqlstate(lambda: insert(database, opening)) == "SM001"


def test_an_access_without_cohort_cannot_mix_a_delay_value(world: World) -> None:
    database = world.database
    no_cohort = _row(
        run_id="RUN-TRAIN",
        acceso="SIN-COHORTE",
        con_cohorte=False,
        estado_cola="complete",
        ticks_esperados=1,
        ticks_observados=1,
        cobertura_cola=1.0,
        vehiculo_ticks=2,
        cola_media_veh=2.0,
        cola_maxima_veh=2,
    )
    insert(database, {"simulacion.resultados_acceso": [no_cohort]})
    assert rows_of(
        database, "SELECT con_cohorte, estado_cola, suma_demora_s FROM simulacion.resultados_acceso"
    ) == [(False, "complete", None)]
    bad = {**no_cohort, "acceso": "MEZCLA", "suma_demora_s": 4.0}
    assert _sqlstate(lambda: insert(database, {"simulacion.resultados_acceso": [bad]})) == "23514"


def test_a_protocol_freeze_needs_a_protocol_published_as_frozen(
    world: World, tmp_path: Path
) -> None:
    workspace = tmp_path / "datos"
    folder = workspace / "derivados" / "protocolos" / "borrador"
    folder.mkdir(parents=True)
    draft = protocol(protocol_id="BORRADOR", status="draft")
    (folder / "b.json").write_text(draft.model_dump_json(), encoding="utf-8")
    unit, _ = protocol_unit(workspace, "derivados/protocolos/borrador/b.json")
    rows = _merge(unit)
    rows["control.artefactos"] = [
        r for r in rows["control.artefactos"] if r["artefacto_id"] != SOURCE
    ]
    insert(world.database, rows)
    frozen_draft = _milestone(world, "H9", "protocol_frozen", protocolo_id="BORRADOR")
    assert _sqlstate(lambda: insert(world.database, frozen_draft)) == "SM001"


def test_evidence_cannot_be_changed_even_by_its_owner(world: World) -> None:
    for statement in (
        "UPDATE caso.casos SET descripcion = 'otra'",
        "DELETE FROM simulacion.eventos",
        "TRUNCATE simulacion.eventos",
        "UPDATE control.artefactos SET sha256 = repeat('b', 64)",
    ):
        state = _sqlstate(lambda s=statement: scalar(world.database, s, role=ADMIN))
        assert state == "SM009", statement
    assert scalar(world.database, "SELECT count(*) FROM simulacion.eventos", role=ADMIN) == 2


def test_each_user_can_do_only_its_part(world: World) -> None:
    database = world.database
    write = "INSERT INTO caso.tipos_vehiculo VALUES ('x','1','y',9,'prueba',%s)"
    assert _sqlstate(lambda: scalar(database, write, (SOURCE,), role=LECTURA)) == "42501"
    change = "UPDATE simulacion.corridas SET estado = 'failed'"
    assert _sqlstate(lambda: scalar(database, change, role=CARGA)) == "42501"
    temporary = "CREATE TEMP TABLE t (x int)"
    assert _sqlstate(lambda: scalar(database, temporary, role=LECTURA)) == "42501"
    assert _sqlstate(lambda: scalar(database, "SELECT current_user", role=LECTURA)) is None


def test_a_load_is_closed_once_and_a_conflict_decided_once(world: World) -> None:
    database = world.database
    close = (
        "UPDATE control.cargas SET estado = 'completed', fin = now() "
        "WHERE carga_id = 'prueba' RETURNING 1"
    )
    assert scalar(database, close, role=CARGA) == 1
    assert _sqlstate(lambda: scalar(database, close, role=CARGA)) == "SM009"
    with connect(CARGA, database=database) as connection:
        connection.execute(
            "INSERT INTO control.conflictos (conflicto_id, tipo, detalle, detectado_en, carga_id, "
            "artefacto_id) VALUES ('c1', 'not_loadable', 'x', now(), 'prueba', %s)",
            (SOURCE,),
        )
    decide = (
        "UPDATE control.conflictos SET decision = 'accepted_risk', decidido_en = now(), "
        "decidido_por = 'PO' WHERE conflicto_id = 'c1' RETURNING 1"
    )
    assert scalar(database, decide, role=CARGA) == 1
    assert _sqlstate(lambda: scalar(database, decide, role=CARGA)) == "SM009"
    other = "UPDATE control.conflictos SET detalle = 'otro' WHERE conflicto_id = 'c1'"
    assert _sqlstate(lambda: scalar(database, other, role=CARGA)) == "SM009"


def test_a_preliminary_scenario_never_goes_to_the_test(world: World) -> None:
    database = world.database
    base_row = rows_of(
        database,
        "SELECT to_jsonb(e) FROM experimento.escenarios AS e WHERE escenario_id = 'ESC-TRAIN'",
        ADMIN,
    )[0][0]
    data = dict(json.loads(json.dumps(base_row)))
    data.update(escenario_id="ESC-PRE", familia_id="F-PRE", preliminar=True)
    data.pop("carga_id")
    data["artefacto_id"] = SOURCE
    family = _row(
        caso_id=world.case_id,
        caso_version=world.case_version,
        familia_id="F-PRE",
        origen="synthetic",
        variantes=None,
        semillas=None,
        rangos_demanda=None,
    )
    insert(database, {"experimento.familias": [family], "experimento.escenarios": [data]})
    split = {
        "experimento.particiones": [
            _row(particion_id="P2", politica="x", semilla=2, congelada=True)
        ],
        "experimento.asignaciones": [
            _row(particion_id="P2", escenario_id="ESC-PRE", familia_id="F-PRE", asignacion="test")
        ],
    }
    assert _sqlstate(lambda: insert(database, split)) == "SM003"


def test_a_family_goes_whole_to_one_assignment(world: World) -> None:
    database = world.database
    template = rows_of(
        database,
        "SELECT to_jsonb(e) FROM experimento.escenarios AS e WHERE escenario_id = 'ESC-TRAIN'",
        ADMIN,
    )[0][0]
    data = dict(json.loads(json.dumps(template)))
    data.update(escenario_id="ESC-TRAIN-2")
    data.pop("carga_id")
    data["artefacto_id"] = SOURCE
    insert(database, {"experimento.escenarios": [data]})
    rows = {
        "experimento.particiones": [
            _row(particion_id="P3", politica="x", semilla=3, congelada=True)
        ],
        "experimento.asignaciones": [
            _row(
                particion_id="P3",
                escenario_id="ESC-TRAIN-2",
                familia_id="F-TRAIN",
                asignacion="validation",
            )
        ],
    }
    assert _sqlstate(lambda: insert(database, rows)) == "SM002"


def test_a_final_run_needs_a_test_scenario_and_a_final_seed(world: World) -> None:
    database = world.database

    def attempt(run_id: str, stage: str, seed: int) -> str | None:
        row = _run(
            world,
            run_id,
            "ESC-TRAIN",
            etapa=stage,
            semilla_sumo=seed,
            protocolo_id=world.protocol_id,
        )
        return _sqlstate(lambda: insert(database, {"simulacion.corridas": [row]}))

    assert attempt("RUN-F1", "final", 301) == "SM004"  # final en un escenario de entrenamiento
    assert attempt("RUN-S1", "search", 301) == "SM004"  # semilla final usada en la búsqueda
    # Con una semilla de búsqueda el disparador la acepta; falla después por no tener plan.
    assert attempt("RUN-S2", "search", 101) == "23514"


def test_a_text_is_stored_as_text_never_as_sql(world: World) -> None:
    hostile = "x'); DROP TABLE caso.casos; --"
    event = _row(
        run_id="RUN-TRAIN",
        orden=2,
        tiempo_s=None,
        tipo="warning",
        subtipo=None,
        vehiculo_id=None,
        otro_vehiculo_id=None,
        carril_id=None,
        texto=hostile,
    )
    insert(world.database, {"simulacion.eventos": [event]})
    stored = scalar(world.database, "SELECT texto FROM simulacion.eventos WHERE orden = 2")
    assert stored == hostile
    assert scalar(world.database, "SELECT count(*) FROM caso.casos") == 1


# --- C3.1: escenarios de la auditoría que no tenían prueba propia ------------------------------


def _message(action: Callable[[], object]) -> str:
    """El texto del error que lanza la base (vacío si no falla)."""
    try:
        action()
    except psycopg.Error as error:
        return str(error)
    return ""


def _other_partition_rows(world: World, *, selection_partition: str) -> dict[str, list[Row]]:
    """Una segunda partición P2 con su modelo M2, su selección S2 y un experimento X2 sobre P1."""
    first = _model_rows(world)
    return {
        "experimento.particiones": [
            _row(particion_id="P2", politica="prueba", semilla=2, congelada=True)
        ],
        "aprendizaje.conjuntos": [
            {
                **first["aprendizaje.conjuntos"][0],
                "conjunto_id": "C2",
                "particion_id": "P2",
                "huella_conjunto": "c" * 64,
            }
        ],
        "aprendizaje.entrenamientos": [
            {
                **first["aprendizaje.entrenamientos"][0],
                "entrenamiento_id": "E2",
                "conjunto_id": "C2",
            }
        ],
        "aprendizaje.modelos": [
            {
                **first["aprendizaje.modelos"][0],
                "modelo_id": "M2",
                "particion_id": "P2",
                "conjunto_id": "C2",
                "entrenamiento_id": "E2",
            }
        ],
        "aprendizaje.seleccion": [
            {
                **first["aprendizaje.seleccion"][0],
                "seleccion_id": "S2",
                "particion_id": selection_partition,
                "huella_seleccion": "c" * 64,
                "candidatos": ["M2"],
                "modelo_ganador_id": "M2",
            }
        ],
        "evaluacion.experimentos": [
            {
                **first["evaluacion.experimentos"][0],
                "experimento_id": "X2",
                "modelo_id": "M2",
                "seleccion_id": "S2",
                "particion_id": "P1",
                "huella_experimento": "d" * 64,
            }
        ],
    }


def _freeze(world: World, *steps: tuple[str, str, dict[str, object]]) -> None:
    for code, kind, objects in steps:
        insert(world.database, _milestone(world, code, kind, **objects))


def test_b03_a_model_cannot_be_frozen_with_a_selection_of_another_partition(world: World) -> None:
    insert(world.database, _other_partition_rows(world, selection_partition="P1"))
    _freeze(
        world,
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P2"}),
    )
    freeze = _milestone(
        world, "H3", "model_frozen", modelo_id="M2", seleccion_id="S2", huella_seleccion="c" * 64
    )
    refusal = _message(lambda: insert(world.database, freeze))
    assert "no coincide con la selección fijada" in refusal
    assert (
        scalar(world.database, "SELECT count(*) FROM control.hitos WHERE tipo = 'model_frozen'")
        == 0
    )


def test_b03_the_test_does_not_open_with_a_model_frozen_for_another_partition(
    world: World,
) -> None:
    insert(world.database, _other_partition_rows(world, selection_partition="P2"))
    _freeze(
        world,
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P1"}),
        ("H3", "split_frozen", {"particion_id": "P2"}),
        (
            "H4",
            "model_frozen",
            {"modelo_id": "M2", "seleccion_id": "S2", "huella_seleccion": "c" * 64},
        ),
    )
    opening = _milestone(world, "H5", "test_opened", experimento_id="X2", particion_id="P1")
    refusal = _message(lambda: insert(world.database, opening))
    assert "solo se abre con su protocolo, su partición y su modelo" in refusal
    assert (
        scalar(world.database, "SELECT count(*) FROM control.hitos WHERE tipo = 'test_opened'") == 0
    )


def test_b03_the_test_does_not_open_with_a_partition_that_is_not_the_experiments(
    world: World,
) -> None:
    insert(world.database, _model_rows(world))
    insert(
        world.database,
        {
            "experimento.particiones": [
                _row(particion_id="P2", politica="prueba", semilla=2, congelada=True)
            ]
        },
    )
    _freeze(
        world,
        ("H1", "protocol_frozen", {"protocolo_id": world.protocol_id}),
        ("H2", "split_frozen", {"particion_id": "P1"}),
        ("H3", "model_frozen", {"modelo_id": "M1"}),
    )
    opening = _milestone(world, "H4", "test_opened", experimento_id="X1", particion_id="P2")
    refusal = _message(lambda: insert(world.database, opening))
    assert "no es la del experimento" in refusal


# --- B09: la cola se valida en la base, no solo en el código que la escribe --------------------


def _steps_result(run_id: str, steps: Sequence[float | None]) -> dict[str, list[Row]]:
    """Un resultado de corrida mínimo cuya serie de pasos es ``steps``."""
    return {
        "simulacion.resultados_corrida": [
            _row(
                run_id=run_id,
                modo="base",
                fin_limite_s=10.0,
                vehiculos_cargados=0,
                vehiculos_insertados=0,
                vehiculos_en_red=0,
                vehiculos_esperando=0,
                viajes_terminados=0,
                viajes_sin_terminar=0,
                teletransportes_total=0,
                teletransportes_atasco=0,
                teletransportes_cruce=0,
                teletransportes_carril=0,
                choques=0,
                avisos_sumo=0,
                demanda_insatisfecha=False,
                hallazgos=[],
                pasos_cola_s=steps,
                pasos_en_ventana=[True] * len(steps),
            )
        ]
    }


def _raw_insert(world: World, table: str, row: Row) -> None:
    """Escribe una fila directamente como dueño, sin pasar por las validaciones del cargador."""
    values: dict[str, object] = {**row, "carga_id": "prueba"}
    for column, value in values.items():
        if isinstance(value, dict | list) and column == "hallazgos":
            values[column] = Jsonb(value)
    schema, name = table.split(".")
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(schema, name),
        sql.SQL(", ").join(sql.Identifier(column) for column in values),
        sql.SQL(", ").join(sql.Placeholder() for _ in values),
    )
    with connect(ADMIN, database=world.database) as connection:
        connection.execute(statement, list(values.values()))


STEP_CASES = [
    pytest.param([-1.0, 0.0, 1.0], id="negativo"),
    pytest.param([0.0, float("nan"), 2.0], id="nan"),
    pytest.param([0.0, float("inf"), 2.0], id="infinito"),
    pytest.param([0.0, None, 2.0], id="nulo"),
]


@pytest.mark.parametrize("steps", STEP_CASES)
def test_b09_the_loader_refuses_bad_step_times_before_they_reach_the_base(
    world: World, steps: list[float | None]
) -> None:
    with pytest.raises(CargaError, match="valores inválidos"):
        insert(world.database, _steps_result("RUN-TRAIN", steps))
    assert scalar(world.database, "SELECT count(*) FROM simulacion.resultados_corrida") == 0


@pytest.mark.parametrize("steps", STEP_CASES)
def test_b09_the_base_refuses_bad_step_times_even_if_the_loader_were_skipped(
    world: World, steps: list[float | None]
) -> None:
    row = _steps_result("RUN-TRAIN", steps)["simulacion.resultados_corrida"][0]
    assert _sqlstate(lambda: _raw_insert(world, "simulacion.resultados_corrida", row)) == "23514"
    assert scalar(world.database, "SELECT count(*) FROM simulacion.resultados_corrida") == 0


def _queue_insert(world: World, values: list[object]) -> None:
    _raw_insert(
        world,
        "simulacion.cola_por_acceso",
        {
            "run_id": "RUN-TRAIN",
            "acceso": "ACCESO-PRUEBA",
            "vehiculos_en_cola": values,
            "artefacto_id": SOURCE,
        },
    )


@pytest.mark.parametrize(
    "steps", [[0.0, 2.0, 1.0], [0.0, 1.0, 1.0]], ids=["desordenados", "repetidos"]
)
def test_b09_the_queue_of_an_access_needs_strictly_ordered_steps(
    world: World, steps: list[float]
) -> None:
    insert(world.database, _steps_result("RUN-TRAIN", steps))
    # Los pasos de la corrida no están en orden estricto: ninguna cola de esa corrida entra.
    assert _sqlstate(lambda: _queue_insert(world, [0, 0, 0])) == "SM006"
    assert scalar(world.database, "SELECT count(*) FROM simulacion.cola_por_acceso") == 0


def test_b09_the_queue_of_an_access_needs_one_window_flag_per_step(world: World) -> None:
    rows = _steps_result("RUN-TRAIN", [0.0, 1.0, 2.0])
    rows["simulacion.resultados_corrida"][0]["pasos_en_ventana"] = [True, True]  # falta una
    insert(world.database, rows)
    assert _sqlstate(lambda: _queue_insert(world, [0, 0, 0])) == "SM006"
    assert scalar(world.database, "SELECT count(*) FROM simulacion.cola_por_acceso") == 0


def test_b09_the_queue_of_an_access_is_numbers_only(world: World) -> None:
    insert(world.database, _steps_result("RUN-TRAIN", [0.0, 1.0, 2.0]))
    # Un texto en lugar de un número no entra por su tipo, aunque los pasos sean válidos.
    assert _sqlstate(lambda: _queue_insert(world, ["a", "b", "c"])) in {"42804", "22P02"}
    assert scalar(world.database, "SELECT count(*) FROM simulacion.cola_por_acceso") == 0
    # Con el cargador por delante, un texto o un negativo ni siquiera llega a la base.
    for bad in (["a", "b", "c"], [0, -1, 0]):
        row: Row = {
            "run_id": "RUN-TRAIN",
            "acceso": "ACCESO-PRUEBA",
            "vehiculos_en_cola": bad,
            "artefacto_id": SOURCE,
        }
        with pytest.raises(CargaError, match="valores inválidos"):
            insert(world.database, {"simulacion.cola_por_acceso": [row]})


# --- C3.2 y C3.5: el barrido de cegado de una base real -----------------------------------------


def _admin(world: World, *statements: str) -> None:
    with connect(ADMIN, database=world.database, autocommit=True) as connection:
        for statement in statements:
            connection.execute(statement.encode())


def test_c32_the_sweep_of_a_sound_base_finds_nothing_out_of_place(world: World) -> None:
    report = sweep(world.database)
    assert (report.status, sweep_exit_code(report)) == ("ok", 0)
    assert (report.hidden_scenarios, report.marks) == (1, 2)  # ESC-TEST y su corrida RUN-TEST
    reader, panel = report.roles
    assert (reader.role, panel.role) == ("semaforo_lectura", "semaforo_panel")
    assert reader.readable == report.relations and reader.denied == 0
    assert panel.readable == len(PANEL_VIEWS)
    assert panel.denied == report.relations - len(PANEL_VIEWS)
    assert not (reader.leaks or panel.leaks or reader.unexpected_reads or panel.unexpected_reads)


def test_c32_the_sweep_finds_a_policy_that_lets_a_closed_test_through(world: World) -> None:
    _admin(world, "ALTER POLICY lectura_cegada ON simulacion.corridas USING (true)")
    report = sweep(world.database)
    assert (report.status, sweep_exit_code(report)) == ("falla", 5)
    reader = report.roles[0]
    assert [leak.relation for leak in reader.leaks if leak.relation == "simulacion.corridas"] == [
        "simulacion.corridas"
    ]


def test_c32_the_sweep_finds_a_permission_that_is_too_wide_or_too_narrow(world: World) -> None:
    # PostgreSQL niega primero por el esquema: el panel necesita USAGE además de SELECT.
    _admin(
        world,
        "GRANT USAGE ON SCHEMA control TO semaforo_panel",
        "GRANT SELECT ON control.cargas TO semaforo_panel",
    )
    report = sweep(world.database)
    assert report.status == "falla"
    assert "control.cargas" in report.roles[1].unexpected_reads
    _admin(
        world,
        "REVOKE SELECT ON control.cargas FROM semaforo_panel",
        "REVOKE USAGE ON SCHEMA control FROM semaforo_panel",
    )
    assert sweep(world.database).status == "ok"
    _admin(world, "REVOKE SELECT ON control.cargas FROM semaforo_lectura")
    narrow = sweep(world.database)
    assert narrow.status == "falla"
    assert "control.cargas" in narrow.roles[0].unexpected_denials


def test_c32_without_a_closed_test_the_sweep_only_checks_the_permissions(base: str) -> None:
    report = sweep(base)
    assert (report.status, report.hidden_scenarios, report.marks) == ("ok", 0, 0)
    assert report.note is not None and "No hay escenarios cegados" in report.note
