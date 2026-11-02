"""Ayudas de prueba para las reglas temporales de DEV13 (validador y corrector).

Datos sintéticos. ``replica_data`` reproduce la estructura de caso-001 (9 slots, 4 variables, 5
grupos de verde que se solapan, ciclo de 120 a 240 s, tick de 1 s) con los límites de la tabla de
DEV03 F0: son propuestas del equipo pendientes de revisión con el especialista de tránsito. El
orden de ajuste ``PRIORITY`` es el que decidió el Product Owner para caso-001 (DEV13 F0, D6).
"""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from semaforo.dominio.adjust_order import AdjustOrder, parse_adjust_order
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.feasibility import PreparedCase, prepare

DEMO_CASE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "case.json").read_text(encoding="utf-8")
)
# (id, tipo, mínimo, máximo, estado de los dos enlaces del semáforo de ejemplo)
SLOT_TABLE = [
    ("t1", "variable", 30, 110, "GG"),
    ("t2", "fixed", 5, 5, "yG"),
    ("t3", "variable", 15, 60, "Gr"),
    ("t4", "fixed", 5, 5, "yr"),
    ("t5", "variable", 25, 70, "rG"),
    ("t6", "fixed", 5, 5, "yG"),
    ("t7", "variable", 5, 30, "rG"),
    ("t8", "fixed", 5, 5, "ry"),
    ("t9", "fixed", 4, 4, "rr"),
]
GROUP_TABLE = [
    ("jp_este_oeste", ["t1"], 30, 110),
    ("jp_oeste_este_recto", ["t1", "t2", "t3"], 50, 175),
    ("jp_oeste_este_flecha", ["t3"], 15, 60),
    ("frutales_sur", ["t5"], 25, 70),
    ("frutales_norte", ["t5", "t6", "t7"], 35, 105),
]
BASELINE = {
    "t1": 82.0,
    "t2": 5.0,
    "t3": 45.0,
    "t4": 5.0,
    "t5": 45.0,
    "t6": 5.0,
    "t7": 10.0,
    "t8": 5.0,
    "t9": 4.0,
}
SLOT_IDS = list(BASELINE)
VARIABLE_IDS = ["t1", "t3", "t5", "t7"]
BASELINE_VARIABLE = {slot_id: BASELINE[slot_id] for slot_id in VARIABLE_IDS}
FIXED = {slot_id: value for slot_id, value in BASELINE.items() if slot_id not in VARIABLE_IDS}
LIMITS = {row[0]: (float(row[2]), float(row[3])) for row in SLOT_TABLE}
PRIORITY = ["t7", "t5", "t3", "t1"]
CASE_ID = "REPLICA"
CASE_VERSION = "1.0.0"

Change = Callable[[dict[str, Any]], None]


def replica_data() -> dict[str, Any]:
    data = copy.deepcopy(DEMO_CASE)
    data["case_id"] = CASE_ID
    data["tick_s"] = 1
    data["cycle_s"] = {"min": 120, "max": 240}
    data["slots"] = [
        {
            "id": slot_id,
            "kind": kind,
            "min_s": low,
            "max_s": high,
            "states": [{"tls_id": "DEMO_TLS", "state": state}],
        }
        for slot_id, kind, low, high, state in SLOT_TABLE
    ]
    data["green_groups"] = [
        {"id": name, "slot_ids": members, "min_s": low, "max_s": high, "purpose": "vehicle"}
        for name, members, low, high in GROUP_TABLE
    ]
    return data


def make_case(change: Change | None = None) -> Case:
    data = replica_data()
    if change is not None:
        change(data)
    return parse_case(data)


def order_data(cut_order: list[str] | None = None, **fields: object) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "case_id": CASE_ID,
        "case_version": CASE_VERSION,
        "cut_order": PRIORITY if cut_order is None else cut_order,
        "evidence": ["criterio de prueba"],
        **fields,
    }


def priority_order(cut_order: list[str] | None = None) -> AdjustOrder:
    return parse_adjust_order(order_data(cut_order))


def prepared(change: Change | None = None, order: AdjustOrder | None = None) -> PreparedCase:
    return prepare(make_case(change), order)
