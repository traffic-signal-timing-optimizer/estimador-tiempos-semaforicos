"""Mutaciones de DEV15 F5: sensibilidad a la saturación y su tope.

Uso: ``python scripts\\mutaciones\\mutar.py scripts\\mutaciones\\dev15_f5.py``.
"""

C = "src/semaforo/referencias/comparators.py"
B = "src/semaforo/referencias/baselines.py"
LOOP = "    for saturation in sorted(set(parameters.saturation_flow_sensitivity_veh_h_lane)):"
ROW = "            SensitivityRow(saturation, webster_plan(structure, prepared, scenario.request, varied))"
TESTS = ["tests/unit/test_comparators.py", "tests/security/test_dev15.py"]
MUTATIONS = [
    (
        C,
        LOOP,
        "    for saturation in parameters.saturation_flow_sensitivity_veh_h_lane:",
        "repetidas y sin ordenar",
    ),
    (
        C,
        LOOP,
        "    for saturation in set(parameters.saturation_flow_sensitivity_veh_h_lane):",
        "sin ordenar",
    ),
    (
        C,
        LOOP,
        "    for saturation in sorted(parameters.saturation_flow_sensitivity_veh_h_lane):",
        "repetidas",
    ),
    (
        C,
        LOOP,
        "    for saturation in sorted(set(parameters.saturation_flow_sensitivity_veh_h_lane))[1:]:",
        "falta la primera",
    ),
    (
        C,
        '        varied = parameters.model_copy(update={"saturation_flow_veh_h_lane": saturation})',
        "        varied = parameters",
        "saturación sin cambiar",
    ),
    (
        C,
        ROW,
        "            SensitivityRow(saturation, webster_plan(structure, prepared, scenario.request, parameters))",
        "Webster con la saturación base",
    ),
    (
        C,
        ROW,
        "            SensitivityRow(parameters.saturation_flow_veh_h_lane, webster_plan(structure, prepared, scenario.request, varied))",
        "fila con la saturación equivocada",
    ),
    (
        C,
        '    if (parameters.case_id, parameters.case_version) != (case.case_id, case.case_version):\n        raise ReferenciasError(\n            ErrorCode.INPUT_SCHEMA,\n            "los parámetros de Webster son de otro caso o de otra versión del caso",\n            "parameters",',
        '    if False:\n        raise ReferenciasError(\n            ErrorCode.INPUT_SCHEMA,\n            "los parámetros de Webster son de otro caso o de otra versión del caso",\n            "parameters",',
        "parámetros de otro caso aceptados",
    ),
    (
        C,
        '    if (scenario.case_id, scenario.case_version) != (case.case_id, case.case_version):\n        raise ReferenciasError(\n            ErrorCode.INPUT_SCHEMA, "el escenario es de otro caso o de otra versión", "scenario"\n        )\n    if (parameters.case_id',
        '    if False:\n        raise ReferenciasError(\n            ErrorCode.INPUT_SCHEMA, "el escenario es de otro caso o de otra versión", "scenario"\n        )\n    if (parameters.case_id',
        "escenario de otro caso aceptado",
    ),
    (B, "MAX_SENSITIVITY = 20\n", "MAX_SENSITIVITY = 21\n", "tope de sensibilidad corrido"),
    (
        B,
        "    saturation_flow_sensitivity_veh_h_lane: list[Positive] = Field(max_length=MAX_SENSITIVITY)\n",
        "    saturation_flow_sensitivity_veh_h_lane: list[Positive]\n",
        "sensibilidad sin tope",
    ),
]
