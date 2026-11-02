"""Vista del caso: origen, estado de la validación y restricciones (DEV09 F2, decisión D6)."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from html_checks import assert_safe_page
from quality_tools import DEMO_CASE_TEXT, write_case
from semaforo.app.report_case_view import render_case
from semaforo.app.report_inputs import CaseInputs, load_case_inputs
from semaforo.caso.case_report_models import (
    Interval,
    NetworkStatus,
    ReportStatus,
    RuleStatus,
)

NOW = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)
ATTACKS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "'><svg onload=alert(1)>",
    "&lt;b&gt; &amp; &#60;",
    "</li></ul><h1>otro</h1>",
]


def demo(mutate: Callable[[dict[str, object]], None] | None = None) -> str:
    data = json.loads(DEMO_CASE_TEXT)
    if mutate is not None:
        mutate(data)
    return json.dumps(data)


def inputs_of(tmp_path: Path, text: str | None = None) -> CaseInputs:
    return load_case_inputs(write_case(tmp_path, DEMO_CASE_TEXT if text is None else text))


def rendered(tmp_path: Path, text: str | None = None) -> str:
    return render_case(inputs_of(tmp_path, text), NOW)


def incoherent(data: dict[str, object]) -> None:
    groups = data["green_groups"]
    assert isinstance(groups, list)
    groups[0]["slot_ids"] = ["NO_EXISTE"]


# --- un caso válido ---------------------------------------------------------------------------


def test_a_valid_case_shows_its_identity_origin_and_status(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    seen = assert_safe_page(render_case(inputs, NOW))
    text = seen.visible_text
    assert "Informe del caso: SYNTHETIC_DEMO (versión 1.0.0)" in text
    assert "Sintético: datos de prueba, no son observaciones de Lima" in text
    assert "Caso de prueba sintético" in text
    assert "Válido" in text
    assert inputs.report.case_sha256 is not None
    assert inputs.report.case_sha256 in text
    assert "No declarada" in text  # la red


def test_every_rule_appears_with_its_result(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    seen = assert_safe_page(render_case(inputs, NOW))
    for rule in inputs.report.rules:
        assert rule.rule_id in seen.visible_text
        assert rule.title in seen.visible_text
    assert "17 cumplen, 0 con aviso, 0 no cumplen, 2 no aplican." in seen.visible_text
    assert seen.visible_text.count("Cumple") == 17
    assert seen.visible_text.count("No aplica") == 2


def test_the_limits_show_the_cycle_the_fixed_time_and_each_group(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    seen = assert_safe_page(render_case(inputs, NOW))
    text = seen.visible_text
    assert "Ciclo declarado40 a 100 s" in text
    assert "Ciclo que se puede alcanzar40 a 100 s" in text
    assert "Tiempo fijo8 s" in text
    assert "Tramos de duración variable2" in text
    assert inputs.case is not None
    for group in inputs.case.green_groups:
        assert group.id in text
    assert text.count("Vehicular") == 2


def test_the_movements_show_their_flow_range_in_vehicles_per_hour(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    seen = assert_safe_page(render_case(inputs, NOW))
    assert inputs.case is not None
    assert "2 movimientos del caso" in seen.visible_text
    assert "Flujo permitido (veh/h)" in seen.visible_text
    for movement in inputs.case.movements:
        assert movement.id in seen.visible_text
        assert movement.approach_id in seen.visible_text
        assert f"{movement.flow_domain_vph.min:g} a {movement.flow_domain_vph.max:g}" in (
            seen.visible_text
        )


def test_each_movement_row_has_its_link_indices_and_flow(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    assert inputs.case is not None
    seen = assert_safe_page(render_case(inputs, NOW))
    rows = seen.table("2 movimientos del caso").rows
    for movement, row in zip(inputs.case.movements, rows, strict=True):
        assert row == [
            movement.id,
            movement.approach_id,
            movement.tls_id,
            ", ".join(str(index) for index in movement.link_indices),
            f"{movement.flow_domain_vph.min:g} a {movement.flow_domain_vph.max:g}",
        ]


def test_the_case_fingerprint_is_shown_as_code(tmp_path: Path) -> None:
    seen = assert_safe_page(rendered(tmp_path))
    assert seen.tags["code"] == 1


def test_the_variable_slots_come_from_the_limits_not_from_the_groups(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    assert inputs.report.limits is not None
    limits = inputs.report.limits.model_copy(update={"variable_slots": 5})
    shown = CaseInputs(report=inputs.report.model_copy(update={"limits": limits}), case=inputs.case)
    text = assert_safe_page(render_case(shown, NOW)).visible_text
    assert "Tramos de duración variable5" in text


def test_the_classes_the_boundary_and_the_evidence_are_shown(tmp_path: Path) -> None:
    seen = assert_safe_page(rendered(tmp_path))
    assert "Clases de vehículoscar, bus" in seen.visible_text
    assert "Política de fronteraDEMO_EMPTY_START_FIXED_ROUTES" in seen.visible_text
    assert "FICTICIO: solo prueba contractual" in seen.visible_text


def test_a_case_without_restriction_evidence_says_so(tmp_path: Path) -> None:
    seen = assert_safe_page(rendered(tmp_path, demo(lambda d: d.update(restrictions_evidence=[]))))
    assert "No hay evidencia de las restricciones registrada." in seen.visible_text
    assert "FICTICIO" not in seen.visible_text


def test_the_words_of_the_project_are_explained(tmp_path: Path) -> None:
    text = assert_safe_page(rendered(tmp_path)).visible_text
    for term in ("Tick", "Slot (tramo)", "Ciclo", "Grupo de verde", "Enlace"):
        assert term in text
    assert "Qué significan estas palabras" in text


def test_the_footer_shows_the_time_in_utc_and_does_not_promise_road_safety(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    lima = datetime(2026, 11, 1, 9, 0, tzinfo=timezone(timedelta(hours=-5)))
    text = assert_safe_page(render_case(inputs, lima)).visible_text
    assert "Generado el 2026-11-01 14:00 UTC" in text
    assert "no certifica seguridad para la operación vial" in text


def test_the_same_inputs_give_the_same_page(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    assert render_case(inputs, NOW) == render_case(inputs, NOW)


# --- un caso con avisos, inválido o ilegible --------------------------------------------------


def test_a_case_with_a_warning_shows_which_rule_and_why(tmp_path: Path) -> None:
    def same_states(data: dict[str, object]) -> None:
        slots = data["slots"]
        assert isinstance(slots, list)
        slots[1]["states"] = slots[0]["states"]

    inputs = inputs_of(tmp_path, demo(same_states))
    assert inputs.report.status == "valid_with_warnings"
    seen = assert_safe_page(render_case(inputs, NOW))
    assert "Válido con avisos" in seen.visible_text
    assert "1 con aviso" in seen.visible_text
    warned = [rule for rule in inputs.report.rules if rule.status == "warning"]
    assert [rule.rule_id for rule in warned] == ["CASE-C07"]
    assert warned[0].issues[0].message in seen.visible_text
    assert "alerta" not in seen.values("div", "class")


def test_an_incoherent_case_shows_an_alert_and_the_failed_rule(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path, demo(incoherent))
    assert inputs.case is None
    seen = assert_safe_page(render_case(inputs, NOW))
    failed = [rule for rule in inputs.report.rules if rule.status == "failed"]
    assert failed
    assert "alerta" in seen.values("div", "class")
    assert "Este caso no se puede usar" in seen.visible_text
    assert f"no cumple {len(failed)} regla(s): {', '.join(r.rule_id for r in failed)}." in (
        seen.visible_text
    )
    assert "Inválido" in seen.visible_text
    assert "No cumple" in seen.visible_text
    assert failed[0].issues[0].message in seen.visible_text


def test_an_incoherent_case_does_not_show_its_content_but_says_why(tmp_path: Path) -> None:
    text = assert_safe_page(rendered(tmp_path, demo(incoherent))).visible_text
    assert "no se muestran porque el caso no es válido" in text
    assert "movimientos del caso" not in text
    assert "Evidencia de las restricciones" not in text


def test_an_incoherent_case_still_shows_its_limits_without_the_group_type(tmp_path: Path) -> None:
    text = assert_safe_page(rendered(tmp_path, demo(incoherent))).visible_text
    assert "Verde de cada grupo" in text
    assert "Vehicular" not in text


def test_a_case_without_structure_is_shown_without_identity(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path, "{}")
    seen = assert_safe_page(render_case(inputs, NOW))
    assert "Informe del caso: caso sin identificar" in seen.visible_text
    assert "Huella del casoNo informado" in seen.visible_text
    assert "Origen" in seen.visible_text
    assert "Límites del plan" not in seen.visible_text
    assert "alerta" in seen.values("div", "class")


def test_a_file_that_is_not_json_is_shown_as_an_invalid_case(tmp_path: Path) -> None:
    seen = assert_safe_page(rendered(tmp_path, "esto no es json"))
    assert "Inválido" in seen.visible_text
    assert "caso sin identificar" in seen.visible_text


# --- estados que un caso de prueba no produce -------------------------------------------------


def with_report(tmp_path: Path, **changes: object) -> CaseInputs:
    inputs = inputs_of(tmp_path)
    return CaseInputs(report=inputs.report.model_copy(update=changes), case=inputs.case)


@pytest.mark.parametrize(
    ("status", "symbol", "label"),
    [
        ("valid", "✔", "Válido"),
        ("valid_with_warnings", "⚠", "Válido con avisos"),
        ("invalid", "✖", "Inválido"),
    ],
)
def test_each_validation_state_has_its_symbol_and_text(
    tmp_path: Path, status: ReportStatus, symbol: str, label: str
) -> None:
    seen = assert_safe_page(render_case(with_report(tmp_path, status=status), NOW))
    assert f"Estado de la validación{symbol} {label}" in seen.visible_text


@pytest.mark.parametrize(
    ("network", "symbol", "label"),
    [
        ("not_declared", "\N{EN DASH}", "No declarada"),
        ("not_checked", "⚠", "No verificada"),
        ("verified", "✔", "Verificada"),
        ("failed", "✖", "Con fallos"),
    ],
)
def test_each_network_state_has_its_symbol_and_text(
    tmp_path: Path, network: NetworkStatus, symbol: str, label: str
) -> None:
    seen = assert_safe_page(render_case(with_report(tmp_path, network=network), NOW))
    assert f"Red del caso{symbol} {label}" in seen.visible_text


@pytest.mark.parametrize(
    ("result", "symbol", "label"),
    [
        ("passed", "✔", "Cumple"),
        ("warning", "⚠", "Aviso"),
        ("failed", "✖", "No cumple"),
        ("not_applicable", "\N{EN DASH}", "No aplica"),
    ],
)
def test_each_rule_result_has_its_symbol_and_text(
    tmp_path: Path, result: RuleStatus, symbol: str, label: str
) -> None:
    inputs = inputs_of(tmp_path)
    rules = [rule.model_copy(update={"status": result}) for rule in inputs.report.rules]
    shown = CaseInputs(report=inputs.report.model_copy(update={"rules": rules}), case=inputs.case)
    seen = assert_safe_page(render_case(shown, NOW))
    for row in seen.table("Resultado de cada regla del caso").rows:
        assert row[2] == f"{symbol} {label}"


def test_a_real_case_shows_its_origin_in_words(tmp_path: Path) -> None:
    inputs = with_report(tmp_path, origin="field", representation_status="unverified")
    text = assert_safe_page(render_case(inputs, NOW)).visible_text
    assert "Real: datos de campo" in text
    assert "Sin verificar" in text
    assert "Sintético" not in text


@pytest.mark.parametrize("representation", ["calibrated", "validated"])
def test_the_other_representation_states_have_their_text(
    tmp_path: Path, representation: str
) -> None:
    inputs = with_report(tmp_path, representation_status=representation)
    text = assert_safe_page(render_case(inputs, NOW)).visible_text
    assert {"calibrated": "Calibrado", "validated": "Validado"}[representation] in text


def test_an_unknown_origin_or_version_is_shown_as_not_informed(tmp_path: Path) -> None:
    inputs = with_report(tmp_path, origin=None, representation_status=None, case_version=None)
    text = assert_safe_page(render_case(inputs, NOW)).visible_text
    assert "OrigenNo informado" in text
    assert "RepresentaciónNo informado" in text
    assert "VersiónNo informado" in text
    assert "(versión No informado)" in text


def test_a_group_that_cannot_be_reached_says_so(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    assert inputs.report.limits is not None
    group = inputs.report.limits.green_groups[0].model_copy(update={"reachable_s": None})
    limits = inputs.report.limits.model_copy(
        update={
            "green_groups": [group, *inputs.report.limits.green_groups[1:]],
            "cycle_feasible_s": None,
        }
    )
    shown = CaseInputs(report=inputs.report.model_copy(update={"limits": limits}), case=inputs.case)
    text = assert_safe_page(render_case(shown, NOW)).visible_text
    assert text.count("No se puede alcanzar con los tramos del caso") == 2


def test_numbers_are_shown_without_trailing_zeros_and_with_their_unit(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    assert inputs.report.limits is not None
    limits = inputs.report.limits.model_copy(
        update={
            "tick_s": 0.5,
            "cycle_declared_s": Interval(min=40.25, max=100),
            "fixed_time_s": 12.0,
        }
    )
    shown = CaseInputs(report=inputs.report.model_copy(update={"limits": limits}), case=inputs.case)
    text = assert_safe_page(render_case(shown, NOW)).visible_text
    assert "Paso del reloj (tick)0.5 s" in text
    assert "Ciclo declarado40.25 a 100 s" in text
    assert "Tiempo fijo12 s" in text


def test_a_report_without_limits_has_no_limits_section(tmp_path: Path) -> None:
    text = assert_safe_page(render_case(with_report(tmp_path, limits=None), NOW)).visible_text
    assert "Límites del plan" not in text


# --- texto hostil (QA30) ----------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_hostile_text_in_the_restrictions_stays_text(tmp_path: Path, attack: str) -> None:
    text = demo(lambda d: d.update(restrictions_evidence=["FICTICIO: prueba", attack]))
    seen = assert_safe_page(rendered(tmp_path, text))
    assert attack in seen.visible_text
    assert seen.tags["img"] == 0
    assert seen.tags["svg"] == 0


@pytest.mark.parametrize("attack", ATTACKS)
def test_hostile_text_in_the_identifiers_of_a_valid_case_stays_text(
    tmp_path: Path, attack: str
) -> None:
    """Los identificadores del caso admiten cualquier carácter visible, también ``<`` y ``"``."""

    def hostile(data: dict[str, object]) -> None:
        data["case_id"] = attack
        data["boundary_policy_id"] = attack
        data["vehicle_classes"] = [attack, "bus"]
        movements = data["movements"]
        assert isinstance(movements, list)
        movements[0]["approach_id"] = attack

    inputs = inputs_of(tmp_path, demo(hostile))
    assert inputs.case is not None
    seen = assert_safe_page(render_case(inputs, NOW))
    assert seen.visible_text.count(attack) >= 4
    for tag in ("script", "img", "svg"):
        assert seen.tags[tag] == 0


@pytest.mark.parametrize("attack", ATTACKS)
def test_hostile_text_in_a_slot_name_stays_text_in_the_rule_problems(
    tmp_path: Path, attack: str
) -> None:
    def hostile(data: dict[str, object]) -> None:
        slots = data["slots"]
        assert isinstance(slots, list)
        slots[0]["id"] = attack

    seen = assert_safe_page(rendered(tmp_path, demo(hostile)))
    assert seen.tags["script"] == 0
    assert seen.tags["img"] == 0


def test_hostile_text_in_the_report_itself_stays_text(tmp_path: Path) -> None:
    attack = ATTACKS[0]
    inputs = inputs_of(tmp_path)
    rules = list(inputs.report.rules)
    rules[0] = rules[0].model_copy(update={"rule_id": attack, "title": attack})
    shown = CaseInputs(
        report=inputs.report.model_copy(
            update={
                "rules": rules,
                "case_id": attack,
                "case_version": attack,
                "case_sha256": attack,
            }
        ),
        case=inputs.case,
    )
    seen = assert_safe_page(render_case(shown, NOW))
    assert attack in seen.visible_text
    assert seen.tags["script"] == 0
