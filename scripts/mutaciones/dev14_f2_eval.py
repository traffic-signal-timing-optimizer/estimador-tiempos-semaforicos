"""Mutaciones de DEV14 F2: evaluación con SUMO, bitácora y reanudación (evaluation.py, fs.py)."""

E = "src/semaforo/referencias/evaluation.py"
F = "src/semaforo/trazabilidad/fs.py"
TESTS = [
    "tests/unit/test_search_journal.py",
    "tests/unit/test_fs.py",
    "tests/integration/test_search_sumo.py",
]
MUTATIONS = [
    (
        E,
        "        return free is None or free >= min_free_bytes",
        "        return free is None or free > min_free_bytes",
        "mínimo de memoria exclusivo",
    ),
    (
        E,
        "        return free is None or free >= min_free_bytes",
        "        return free is not None and free >= min_free_bytes",
        "memoria desconocida bloquea",
    ),
    (E, '        "seeds_search": list(protocol.seeds.search),', "", "identidad sin semillas"),
    (
        E,
        '        "sumo_options": dict(sorted(setup.sumo_options.items())),',
        "",
        "identidad sin opciones de SUMO",
    ),
    (E, "    require_supported(protocol)", "    pass", "censura sin revisar"),
    (
        E,
        "    if candidates.scenario_id != setup.scenario.scenario_id:",
        "    if False:",
        "escenario ajeno",
    ),
    (
        E,
        "    if candidates.budget != protocol.search_budget:",
        "    if False:",
        "presupuesto ajeno",
    ),
    (
        E,
        "    if candidates.attempt_limit != protocol.sampling_attempt_limit:",
        "    if False:",
        "intentos ajenos",
    ),
    (
        E,
        "    if candidates.seed != protocol.seeds.search[0]:",
        "    if False:",
        "semilla de muestra ajena",
    ),
    (
        E,
        "    for number, line in enumerate(raw.split(_NEWLINE)[:-1], start=1):",
        "    for number, line in enumerate([l for l in raw.split(_NEWLINE) if l], start=1):",
        "línea cortada leída",
    ),
    (
        E,
        "    if path.is_symlink() or not path.is_file():",
        "    if path.is_symlink():",
        "carpeta como bitácora",
    ),
    (E, "    if path.stat().st_size > MAX_JOURNAL_BYTES:", "    if False:", "bitácora sin tope"),
    (
        E,
        '    if not records or records[0].type != "header":',
        "    if not records:",
        "sin identidad al inicio",
    ),
    (
        E,
        "    if records[0].identity != json.loads(_canonical(dict(identity))):",
        "    if False:",
        "bitácora ajena aceptada",
    ),
    (E, "    if complete < len(raw):", "    if False:", "línea cortada no se quita"),
    (
        E,
        '    if relative.anchor or ".." in relative.parts or not relative.parts:',
        "    if relative.anchor or not relative.parts:",
        "ruta con .. aceptada",
    ),
    (
        E,
        '    if relative.anchor or ".." in relative.parts or not relative.parts:',
        '    if ".." in relative.parts or not relative.parts:',
        "ruta absoluta aceptada",
    ),
    (E, "        read_program(folder)", "        pass", "programa sin verificar"),
    (E, "        if key in state.inputs:", "        if False:", "entradas dobles aceptadas"),
    (E, "        if outcome.seed != key[2]:", "        if False:", "resultado de otra semilla"),
    (E, "        if key in state.outcomes:", "        if False:", "resultado doble aceptado"),
    (
        E,
        "    if candidate.candidate_id in state.programs:",
        "    if False:",
        "programa publicado de nuevo",
    ),
    (E, "    if known is not None:", "    if False:", "entradas preparadas de nuevo"),
    (E, '    if manifest.status != "succeeded":', "    if False:", "corrida fallida evaluada"),
    (
        E,
        "        while can_start is not None and not cancel.is_set() and not can_start():",
        "        while False:",
        "sin esperar permiso",
    ),
    (
        E,
        "        if cancel.is_set():\n            return  # una corrida cancelada",
        "        if False:\n            return  # una corrida cancelada",
        "cancelada anotada",
    ),
    (
        E,
        "        if (stage, candidate.candidate_id, seed) not in state.outcomes",
        "        if True",
        "repite lo anotado",
    ),
    (
        E,
        "            seeds=protocol.seeds.finalists,",
        "            seeds=protocol.seeds.final,",
        "finalistas con semillas finales",
    ),
    (
        F,
        "            if attempt == RENAME_ATTEMPTS or target.exists():",
        "            if attempt == RENAME_ATTEMPTS:",
        "reintenta sobre un destino existente",
    ),
    (
        F,
        "            if attempt == RENAME_ATTEMPTS or target.exists():",
        "            if target.exists():",
        "reintenta sin fin",
    ),
    (F, "            pause(RENAME_PAUSE_S)", "            pass", "reintento sin pausa"),
]
