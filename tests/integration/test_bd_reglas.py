"""Reglas que aplica la propia base: cegado, hitos, solo agregar y permisos (DEV31 F3).

Cada prueba usa una base temporal nueva con el esquema (``base``). Las filas se escriben como
``semaforo_admin`` (el dueño, que no está sujeto al cegado pero sí a los disparadores).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from bd_tools import insert, rows_of, scalar
from prepared_inputs import request_for
from search_tools import protocol
from semaforo.bd.carga.caso import case_unit, protocol_unit
from semaforo.bd.carga.corridas import entorno_row
from semaforo.bd.carga.modelo import Row, Unit
from semaforo.bd.carga.motor import artifact_rows
from semaforo.bd.conexion import ADMIN, CARGA, LECTURA, connect
from workspace_tools import build_workspace

pytestmark = pytest.mark.bd

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
    names = ("protocolo_id", "particion_id", "modelo_id", "experimento_id")
    values: dict[str, object] = {name: None for name in names}
    values.update(objects)
    return {
        "control.hitos": [
            _row(
                hito_id=hito_id,
                tipo=kind,
                registrado_en=MOMENT,
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
        "evaluacion.experimentos": [
            _row(
                experimento_id="X1",
                **ids,
                protocolo_id=world.protocol_id,
                particion_id="P1",
                modelo_id="M1",
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
