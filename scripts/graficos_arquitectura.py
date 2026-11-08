"""Qué dibuja cada gráfico de arquitectura (DEV31 F7). Lo usa ``scripts/graficos.py``.

Las posiciones están en celdas de 9 px. Lo que se cotejó con el código, y dónde, lo dicen
``docs/arquitectura/arquitectura-tecnica.md`` y ``arquitectura-de-solucion.md``. Las dependencias
entre paquetes (AT1) no se escriben: se miden en el código.
"""

import ast
import importlib.util
import itertools
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Box:
    identifier: str
    lines: tuple[str, ...]
    x: int  # en celdas
    y: int
    w: int
    h: int
    kind: str = "hecho"


@dataclass(frozen=True)
class Group:
    label: str
    x: int
    y: int
    w: int
    h: int
    stroke: str = "#7b8794"


@dataclass(frozen=True)
class Link:
    source: str
    target: str
    label: str = ""
    dashed: bool = False


@dataclass(frozen=True)
class Architecture:
    name: str
    title: str
    subtitle: str
    width: int  # en celdas
    height: int
    boxes: tuple[Box, ...]
    links: tuple[Link, ...]
    groups: tuple[Group, ...] = ()


@dataclass(frozen=True)
class Matrix:
    """Quién importa a quién: una fila por paquete, en orden de capas."""

    name: str
    title: str
    subtitle: str
    packages: tuple[tuple[str, str], ...]  # nombre y para qué sirve
    links: dict[str, frozenset[str]]
    forbidden: dict[str, frozenset[str]]


def package_links(source: Path) -> dict[str, set[str]]:
    """Qué paquete de ``semaforo`` importa a cuál, según el código."""
    packages = {p.name for p in source.iterdir() if p.is_dir() and p.name != "__pycache__"}
    links: dict[str, set[str]] = {name: set() for name in packages}
    for name in packages:
        for file in (source / name).rglob("*.py"):
            for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                for module in modules:
                    parts = module.split(".")
                    if parts[0] == "semaforo" and len(parts) > 1 and parts[1] in packages:
                        links[name].add(parts[1])
            links[name].discard(name)
    return links


def forbidden_imports(tests: Path) -> dict[str, frozenset[str]]:
    """Las dependencias prohibidas, de la prueba que las vigila (ADR01): no se copian aquí."""
    spec = importlib.util.spec_from_file_location("reglas", tests / "unit" / "test_arquitectura.py")
    if spec is None or spec.loader is None:
        raise SystemExit("No se pudo leer tests/unit/test_arquitectura.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    forbidden: dict[str, frozenset[str]] = module.FORBIDDEN
    return forbidden


def package_matrix(source: Path, tests: Path) -> Matrix:
    packages = (
        ("cli", "comandos: python -m semaforo"),
        ("app", "servicios de aplicación y panel"),
        ("bd", "base de consulta: carga y verificación"),
        ("referencias", "búsqueda y comparadores"),
        ("aprendizaje", "particiones; modelo desde DEV16"),
        ("estimacion", "consulta al modelo: vacío hasta DEV18"),
        ("evaluacion", "cohorte y métricas"),
        ("datos", "aforos y escenarios"),
        ("simulacion", "SUMO; único que lanza procesos"),
        ("caso", "recepción y validación del caso"),
        ("trazabilidad", "huellas y publicación"),
        ("dominio", "reglas puras: no importa nada"),
    )
    links = package_links(source)
    unknown = set(links) - {name for name, _ in packages}
    if unknown:
        raise SystemExit(f"Paquetes sin lugar en el gráfico AT1: {sorted(unknown)}")
    count = sum(len(targets) for targets in links.values())
    return Matrix(
        "AT1_paquetes",
        "Paquetes del programa y sus dependencias reales",
        f"Monolito modular (ADR01): {len(packages)} paquetes y {count} dependencias medidas en el "
        "código.",
        packages,
        {name: frozenset(targets) for name, targets in links.items()},
        forbidden_imports(tests),
    )


def _load_flow() -> Architecture:
    boxes = (
        Box(
            "datos",
            ("datos/", "archivos con manifiesto y huella", "= el original"),
            6,
            12,
            30,
            9,
            "dato",
        ),
        Box("decidir", ("bd decidir", "excluye una corrida, con ruta y huella"), 6, 30, 30, 9),
        Box("verificar1", ("1. Verificar", "huellas y contrato de cada carpeta"), 48, 12, 34, 9),
        Box("transaccion", ("2. Insertar", "una transacción: todo o nada"), 48, 30, 34, 9),
        Box(
            "conflictos",
            ("control.conflictos", "misma clave con otra huella:", "se rechaza y se registra"),
            48,
            48,
            34,
            10,
            "riesgo",
        ),
        Box(
            "base",
            ("PostgreSQL: base semaforo", "copia de consulta, se puede regenerar", "solo agregar"),
            96,
            30,
            40,
            9,
            "dato",
        ),
        Box(
            "conciliar",
            ("bd conciliar", "cobertura, conteos y demora", "contra los archivos (QA33)"),
            150,
            12,
            32,
            10,
        ),
        Box("verif", ("bd verificar", "contenido, reglas y referencia"), 150, 28, 32, 8),
        Box(
            "huellas", ("docs/bd/huellas.json", "en git: fecha externa"), 192, 28, 28, 8, "externo"
        ),
        Box("regenerar", ("bd regenerar", "base temporal: misma huella (QA36)"), 150, 42, 32, 8),
        Box("respaldo", ("bd respaldar", "pg_dump con ficha y huella"), 150, 56, 32, 8),
        Box("panel", ("bd panel", "rol de solo vistas; HTML estático"), 96, 56, 40, 8),
        Box(
            "evidencia",
            ("bd evidencia", "verificación, red, conciliación,", "barrido y respaldo"),
            192,
            56,
            28,
            9,
        ),
    )
    links = (
        Link("datos", "verificar1"),
        Link("decidir", "transaccion"),
        Link("verificar1", "transaccion"),
        Link("transaccion", "conflictos", "si difiere"),
        Link("transaccion", "base"),
        Link("base", "conciliar"),
        Link("base", "verif"),
        Link("verif", "huellas", "compara"),
        Link("base", "regenerar"),
        Link("base", "respaldo"),
        Link("base", "panel"),
        Link("base", "evidencia"),
    )
    return Architecture(
        "AT2_carga_y_verificacion",
        "Cómo entran los datos a la base y cómo se comprueba",
        "Ningún cálculo lee la base: los procesos trabajan con archivos y la base se alimenta de ellos.",
        228,
        72,
        boxes,
        links,
    )


def _rebuild() -> Architecture:
    step = 22
    prepare = [
        ("P0", "la vigente coincide", "con git"),
        ("P1", "candidata con", "el mismo esquema"),
        ("P2", "cargar lo", "publicado"),
        ("P3", "conciliación:", "coincide"),
        ("P4", "regeneración:", "misma huella"),
        ("P5", "respaldo restaurado:", "misma huella"),
        ("P7", "versión, contenido", "y reglas"),
    ]
    boxes: list[Box] = [
        Box(code, (code, a, b), 6 + i * step, 16, step - 4, 9)
        for i, (code, a, b) in enumerate(prepare)
    ]
    boxes += [
        Box(
            "borrar",
            ("Si falla cualquier puerta", "se borra la candidata; la vigente no se tocó"),
            44,
            31,
            56,
            7,
            "riesgo",
        ),
        Box("aprueba", ("El PO aprueba", "las tres huellas (D11)"), 138, 30, 26, 8, "persona"),
        Box("P6", ("P6", "seguridad y cegado", "en bases desechables"), 6, 50, 24, 9),
        Box("P7b", ("P7", "se repite: la candidata", "tiene lo aprobado"), 44, 50, 26, 9),
        Box("P8", ("P8", "cambio de nombre", "(sin conexiones)"), 84, 50, 24, 9),
        Box("P9", ("P9", "verifica las tres", "huellas en la nueva"), 122, 50, 24, 9),
        Box(
            "nueva",
            ("Base nueva vigente", "la anterior se conserva", "con otro nombre"),
            160,
            50,
            28,
            9,
            "dato",
        ),
        Box("revertir", ("Reversión", "cada base vuelve a su nombre"), 96, 66, 38, 7, "riesgo"),
    ]
    links = [Link(a[0], b[0]) for a, b in itertools.pairwise(prepare)]
    links += [
        Link("P3", "borrar", dashed=True),
        Link("P7", "aprueba"),
        Link("aprueba", "P7b"),
        Link("P6", "P7b"),
        Link("P7b", "P8"),
        Link("P8", "P9"),
        Link("P9", "nueva"),
        Link("P8", "revertir", dashed=True),
        Link("P9", "revertir", dashed=True),
    ]
    return Architecture(
        "AT3_reconstruccion",
        "Reconstruir la base sin arriesgar la vigente (bd reconstruir)",
        "Arriba, «preparar»: la vigente no se toca. Abajo, «cambiar»: solo con la aprobación del PO.",
        198,
        80,
        tuple(boxes),
        tuple(links),
        (
            Group("preparar", 3, 11, 164, 30, "#1f7a99"),
            Group("cambiar", 3, 45, 190, 31, "#a66a00"),
        ),
    )


def _security() -> Architecture:
    boxes = (
        Box("po", ("Product Owner", "cuenta local de Windows"), 6, 13, 28, 7, "persona"),
        Box(
            "cred",
            ("pgpass.conf y pg_service.conf", "fuera del repositorio"),
            6,
            27,
            28,
            8,
            "externo",
        ),
        Box(
            "postgres",
            ("postgres", "administrador del servicio;", "el proyecto no lo usa"),
            50,
            11,
            34,
            9,
        ),
        Box("admin", ("semaforo_admin", "dueño: esquema e hitos"), 50, 24, 34, 8),
        Box("carga", ("semaforo_carga", "solo agrega filas; ve todo"), 50, 36, 34, 8),
        Box("lectura", ("semaforo_lectura", "consulta; no ve la prueba cerrada"), 50, 48, 34, 8),
        Box("panelrol", ("semaforo_panel", "solo 25 vistas aprobadas"), 50, 60, 34, 8),
        Box("tablas", ("57 tablas", "solo agregar (disparadores)"), 104, 24, 34, 8, "dato"),
        Box(
            "rls",
            ("Seguridad por filas", "oculta la prueba hasta su apertura"),
            104,
            42,
            34,
            8,
            "dato",
        ),
        Box(
            "vistas",
            ("Vistas con filtro explícito", "control.escenario_visible"),
            104,
            60,
            34,
            8,
            "dato",
        ),
        Box(
            "hitos",
            ("Hitos en orden", "protocolo → partición → modelo", "→ apertura de la prueba"),
            156,
            18,
            36,
            10,
        ),
        Box(
            "huella",
            ("Huellas en git", "contenido y reglas: cualquier", "cambio deja rastro"),
            156,
            36,
            36,
            10,
            "externo",
        ),
        Box(
            "panel",
            ("Panel HTML", "texto escapado; sin red", "(política de contenido)"),
            156,
            58,
            36,
            10,
        ),
        Box(
            "red",
            (
                "Red: pendiente D4",
                "listen_addresses = * (riesgo aceptado, D15)",
                "pg_hba.conf: solo 127.0.0.1 y ::1",
            ),
            6,
            74,
            60,
            10,
            "riesgo",
        ),
    )
    links = (
        Link("po", "cred"),
        Link("cred", "admin"),
        Link("cred", "carga"),
        Link("cred", "lectura"),
        Link("cred", "panelrol"),
        Link("admin", "tablas"),
        Link("carga", "tablas", "INSERT"),
        Link("lectura", "rls"),
        Link("panelrol", "vistas"),
        Link("rls", "tablas"),
        Link("vistas", "tablas"),
        Link("admin", "hitos", "bd hito"),
        Link("tablas", "huella"),
        Link("vistas", "panel", "bd panel"),
    )
    return Architecture(
        "AT4_seguridad",
        "Quién puede hacer qué en la base y cómo se protege la prueba final",
        "Límite honesto: el administrador de la laptop puede saltarse los permisos; lo que protege la "
        "tesis es que cualquier cambio deja rastro en las huellas de git.",
        198,
        88,
        boxes,
        links,
    )


def _overview() -> Architecture:
    groups = (
        Group("Personas", 3, 10, 174, 11, "#8a3f96"),
        Group("Aplicaciones", 3, 23, 174, 15, "#1f7a99"),
        Group("Datos", 3, 40, 174, 15, "#2f7d4f"),
        Group("Infraestructura", 3, 57, 174, 15, "#a66a00"),
    )
    boxes = (
        Box("analista", ("Analista / Product Owner", "opera y valida"), 22, 13, 34, 7, "persona"),
        Box("asesor", ("Asesor y jurado", "revisan la evidencia"), 120, 13, 34, 7, "persona"),
        Box("cli", ("Programa semaforo", "línea de comandos"), 8, 27, 34, 9),
        Box("informes", ("Informes HTML", "caso y datos (DEV09)"), 50, 27, 32, 9),
        Box("panel", ("Panel de resultados", "HTML estático, sin servidor"), 92, 27, 36, 9),
        Box("modelo", ("Estimador", "DEV16 a DEV18: pendiente"), 138, 27, 34, 9, "pendiente"),
        Box("archivos", ("Archivos con huella", "datos/: el original"), 50, 44, 32, 9, "dato"),
        Box("base", ("Base semaforo", "copia de consulta"), 92, 44, 36, 9, "dato"),
        Box("git", ("Huellas y actas en git", "fecha externa"), 138, 44, 34, 9, "externo"),
        Box("sumo", ("SUMO 1.27.1", "proceso hijo por corrida"), 8, 61, 34, 9),
        Box("python", ("Python 3.12", "entorno .venv y uv.lock"), 50, 61, 32, 9),
        Box("pg", ("PostgreSQL 17.9", "servicio local; datos en D:"), 92, 61, 36, 9),
        Box("github", ("GitHub", "código y huellas; sin datos"), 138, 61, 34, 9, "externo"),
    )
    links = (
        Link("analista", "cli"),
        Link("analista", "informes"),
        Link("asesor", "panel"),
        Link("cli", "archivos", "publica"),
        Link("cli", "sumo", "ejecuta", dashed=True),
        Link("archivos", "base", "bd cargar"),
        Link("base", "panel", "bd panel"),
        Link("base", "pg"),
        Link("base", "git", "huellas"),
        Link("git", "github", "push a pedido"),
    )
    return Architecture(
        "AS1_vista_general",
        "Arquitectura de solución: vista general",
        "Un solo programa local. Los archivos con huella son el original y la base es su copia de consulta.",
        180,
        76,
        boxes,
        links,
        groups,
    )


def _data_flow() -> Architecture:
    boxes = (
        Box("caso", ("Caso y red", "23 movimientos, 9 tramos"), 6, 14, 28, 8, "dato"),
        Box("aforos", ("Aforos de campo", "código listo; datos: DEV22"), 6, 28, 28, 8, "pendiente"),
        Box("escen", ("Escenarios", "demanda por movimiento y clase"), 42, 14, 32, 8, "dato"),
        Box("part", ("Partición", "código listo; se publica en DEV16"), 42, 28, 32, 8, "pendiente"),
        Box("prot", ("Protocolo", "cómo se mide; se congela"), 42, 42, 32, 8, "dato"),
        Box("corr", ("Corridas de SUMO", "143 cargadas"), 84, 14, 28, 8, "dato"),
        Box("metr", ("Métricas por corrida", "demora, cola, detenciones"), 122, 14, 30, 8, "dato"),
        Box("busq", ("Búsqueda y etiquetas", "piloto: no_reference"), 122, 28, 30, 8, "dato"),
        Box("comp", ("Comparadores", "plan actual y Webster"), 84, 42, 28, 8, "dato"),
        Box("modelo", ("Modelos", "mediana y XGBoost: DEV16-17"), 162, 28, 30, 8, "pendiente"),
        Box("consulta", ("Consultas", "sin SUMO: DEV18"), 162, 42, 30, 8, "pendiente"),
        Box("final", ("Evaluación final", "DEV20 y DEV26"), 122, 42, 30, 8, "pendiente"),
        Box("pub", ("Todo lo publicado", "datos/, con manifiesto y huella"), 6, 62, 34, 8, "dato"),
        Box("base", ("Base semaforo", "57 tablas y 26 vistas: copia verificada"), 58, 62, 46, 8),
        Box("panel", ("Panel", "solo vistas aprobadas"), 122, 62, 30, 8),
    )
    links = (
        Link("caso", "escen"),
        Link("aforos", "escen", dashed=True),
        Link("escen", "corr"),
        Link("escen", "part", dashed=True),
        Link("prot", "corr"),
        Link("corr", "metr"),
        Link("corr", "comp"),
        Link("metr", "busq"),
        Link("busq", "modelo", dashed=True),
        Link("part", "modelo", "solo desarrollo", dashed=True),
        Link("modelo", "consulta", dashed=True),
        Link("consulta", "final", dashed=True),
        Link("comp", "final", dashed=True),
        Link("pub", "base", "bd cargar"),
        Link("base", "panel", "bd panel"),
    )
    return Architecture(
        "AS2_datos",
        "Arquitectura de datos: de la red al resultado",
        "Línea continua y caja sólida: existe hoy. Punteada: está planificada. Todo lo publicado pasa a la "
        "base con «bd cargar».",
        198,
        76,
        boxes,
        links,
    )


def _applications() -> Architecture:
    groups = (
        Group("Interfaz: python -m semaforo", 3, 10, 196, 11, "#1f7a99"),
        Group("Capacidades", 3, 23, 196, 28, "#2f7d4f"),
        Group("Apoyo común", 3, 53, 196, 12, "#55606e"),
    )
    boxes = (
        Box("doctor", ("doctor", "entorno"), 6, 13, 18, 6),
        Box("case", ("case", "recepción"), 27, 13, 18, 6),
        Box("scen", ("scenarios y splits", "demanda y prueba"), 48, 13, 26, 6),
        Box("simulate", ("simulate y runs", "corridas"), 77, 13, 26, 6),
        Box("report", ("report", "informes HTML"), 106, 13, 22, 6),
        Box("bd", ("bd", "14 comandos"), 131, 13, 20, 6),
        Box("futuro", ("model, plan, evaluate", "pendientes"), 154, 13, 40, 6, "pendiente"),
        Box("recep", ("Recepción y caso", "DEV00 a DEV03"), 6, 27, 28, 8),
        Box("datos", ("Aforos y escenarios", "DEV04, 05, 11 y 12"), 38, 27, 28, 8),
        Box("sim", ("Simulación", "DEV06 a DEV08"), 70, 27, 28, 8),
        Box("ref", ("Búsqueda y comparadores", "DEV14 y 15; por guiones"), 102, 27, 30, 8),
        Box("eval", ("Métricas", "DEV19"), 136, 27, 20, 8),
        Box("base", ("Base y panel", "DEV31"), 160, 27, 30, 8),
        Box("fact", ("Factibilidad", "DEV13; misma regla en todo"), 100, 40, 34, 8),
        Box("train", ("Entrenar y seleccionar", "DEV16 y DEV17"), 38, 40, 30, 8, "pendiente"),
        Box("est", ("Consulta", "DEV18"), 74, 40, 20, 8, "pendiente"),
        Box("final", ("Evaluación final", "DEV20 y DEV26"), 140, 40, 26, 8, "pendiente"),
        Box("traz", ("Trazabilidad", "huellas y publicación atómica"), 30, 56, 40, 7),
        Box("dom", ("Dominio", "reglas puras y contratos"), 96, 56, 40, 7),
    )
    links = (
        Link("case", "recep"),
        Link("scen", "datos"),
        Link("simulate", "sim"),
        Link("bd", "base"),
        Link("recep", "traz"),
        Link("base", "traz"),
        Link("sim", "traz"),
        Link("ref", "fact"),
        Link("fact", "dom"),
        Link("train", "est", dashed=True),
        Link("est", "fact", dashed=True),
    )
    return Architecture(
        "AS3_aplicaciones",
        "Arquitectura de aplicaciones: qué hace el programa",
        "Cada capacidad es un paquete del mismo programa, no un servicio aparte. Punteado: planificado.",
        204,
        69,
        boxes,
        links,
        groups,
    )


def _infrastructure() -> Architecture:
    groups = (
        Group(
            "Laptop del investigador: Windows 11, 16 hilos, 16 GB de RAM", 3, 10, 150, 56, "#a66a00"
        ),
        Group("Disco D:", 8, 44, 140, 18, "#2f7d4f"),
    )
    boxes = (
        Box("python", ("Python 3.12 en .venv", "versiones exactas en uv.lock"), 8, 16, 34, 9),
        Box("sumo", ("SUMO 1.27.1", "un proceso por corrida, sin shell"), 56, 16, 36, 9),
        Box("pg", ("PostgreSQL 17.9", "servicio local, puerto 5432"), 106, 16, 36, 9),
        Box("edge", ("Navegador", "abre el panel, sin internet"), 56, 31, 36, 8),
        Box(
            "cred",
            ("%APPDATA%\\postgresql", "contraseñas: fuera del repositorio"),
            8,
            31,
            38,
            8,
            "externo",
        ),
        Box("datos", ("Proyecto y datos/", "archivos con huella: 3 GB"), 12, 50, 34, 9, "dato"),
        Box("pgdata", ("D:\\pgdata\\semaforo", "espacio de tablas: 149 MB"), 62, 50, 36, 9, "dato"),
        Box("resp", ("D:\\respaldos\\semaforo", "pg_dump, ficha y huella"), 106, 50, 38, 9, "dato"),
        Box(
            "publico",
            ("GitHub público", "código, actas y huellas", "sin datos ni contraseñas"),
            164,
            16,
            36,
            10,
            "externo",
        ),
        Box("privado", ("GitHub privado", "escenario de SUMO"), 164, 32, 36, 8, "externo"),
        Box(
            "nube",
            (
                "Otra máquina o nube",
                "sin requisito hoy; la base ya",
                "registra dónde corrió cada corrida",
            ),
            164,
            48,
            36,
            11,
            "pendiente",
        ),
    )
    links = (
        Link("python", "sumo", "ejecuta"),
        Link("python", "pg", "psycopg"),
        Link("python", "cred"),
        Link("python", "datos", "lee y publica"),
        Link("pg", "pgdata"),
        Link("pg", "resp", "pg_dump"),
        Link("datos", "edge", "panel"),
        Link("datos", "publico", "git, a pedido", dashed=True),
        Link("datos", "privado", dashed=True),
        Link("datos", "nube", dashed=True),
    )
    return Architecture(
        "AS4_infraestructura",
        "Arquitectura de infraestructura",
        "Todo corre en una laptop. Pendiente D4: hoy PostgreSQL escucha en toda la red, riesgo aceptado (D15) "
        "para el uso declarado en red cerrada.",
        206,
        70,
        boxes,
        links,
        groups,
    )


def architecture_diagrams() -> list[Architecture]:
    return [
        _load_flow(),
        _rebuild(),
        _security(),
        _overview(),
        _data_flow(),
        _applications(),
        _infrastructure(),
    ]
