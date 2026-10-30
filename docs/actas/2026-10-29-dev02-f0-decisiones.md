# Acta 2026-10-29: DEV02 · F0 (decisiones)

- **Tipo:** registro de fase del plan de DEV02 (HU01; P0, tamaño M). Dependencia: DEV01, cerrada el 2026-10-29.
- **Autorización:** el Product Owner autorizó F0 y respondió las cinco decisiones del plan. En la 1, 2 y 3 delegó la definición en el equipo («con tu perfil de desarrollador senior…», «crea las reglas que mejor se adapten», «define el formato»); en la 4 y la 5 aceptó la propuesta.
- **Código:** F0 no cambia código.

## Lo que pide la documentación

- `02_Requisitos_y_plan.md`, DEV02: «Tipar contrato, validar IDs, límites, tick, referencias de slots y grupos; rechazar incompletos». Archivos propuestos: `dominio/case.py` y `schemas/case.schema.json`. Resultado: «Caso versionado y reporte de restricciones». Verificación: QA01 y QA02.
- HU01, criterios de aceptación: «ID y versión obligatorios; incompletos bloqueados; límites y referencias a red verificados; origen sintético/real visible».
- `01_Diseno_tecnico.md`: el paquete `caso` expone `validate_case(case, network) → CaseReport`; las reglas de dominio no importan la CLI ni lanzan procesos; los slots son intervalos sin cambio de estado, con un estado por TLS; los límites y fijos deben ser compatibles con el tick; el ciclo factible es la intersección de los límites del caso y las sumas posibles; las necesidades peatonales se representan con ventanas verificadas.
- Código de referencia (`tools/contracts/modelos_contrato.py`): trae un `Case` con reglas básicas. No es la aplicación: «las reglas cruzadas del caso … requieren pruebas propias del producto».

## Decisión 1: organización del proyecto

**Dónde va DEV02.** Se respetan los dos documentos, cada uno en su capa (ADR01):

| Capa | Archivo | Contenido |
|---|---|---|
| `dominio` | `dominio/case.py` | modelo tipado del contrato v1.0 y reglas puras (sin archivos ni procesos) |
| `caso` | `caso/case_validation.py` | `validate_case`: lee el archivo con límites, aplica las reglas, verifica la red si está declarada y arma el `CaseReport` |
| `caso` | `caso/case_report_models.py` | modelo del reporte |

**Reorganización previa (al inicio de F1, en un commit aparte y sin cambiar comportamiento):**

1. `FrozenModel` pasa de `caso/base_model.py` a `dominio/base_model.py`. Hoy lo importan siete módulos desde `caso`, y `dominio` no puede importar `caso` (ADR01).
2. `EXIT_CODES` y `exit_code_for` pasan de `app/reception.py` a `app/exit_codes.py`. Son de toda la CLI; hoy `doctor` importa el servicio de recepción solo para obtenerlos.

**Revisión del proyecto.** Ya cumple: estructura `src/` con paquetes por responsabilidad, dependencias bloqueadas (`uv.lock`), tipos estrictos, pruebas por capa, reglas de arquitectura comprobadas por pruebas, actas y ADR, hooks y `scripts/check.ps1`. Recomendaciones para que decida el Product Owner (no se ejecutan sin su OK):

| Recomendación | Motivo |
|---|---|
| **Crear un repositorio privado para el escenario SUMO** (red, rutas, configuraciones y propuestas; nunca videos ni datos personales) | El paquete de la candidata y la carpeta de SUMO no tienen historial. El diseño técnico dice que los originales no van al repositorio de código, que además es público |
| Integración continua mínima en GitHub (ruff, pyright y pruebas sin SUMO) | El repositorio público no tiene ninguna. Es parte de DEV29; se puede adelantar una versión mínima |
| Licencia | El repositorio público no tiene licencia: por defecto, todos los derechos reservados. Es decisión del investigador y la universidad |
| Decidir DEC09 | ADR01 a ADR08 siguen como propuestas, aunque ADR01 ya se cumple y se prueba |

`tests/security/` está vacía porque las pruebas de seguridad existentes están en `tests/unit/`. Se ordenan en DEV28.

## Decisión 2: reglas del caso

Cada regla tiene un código estable, para que el reporte y las pruebas la nombren igual. Fuente: «ref» = código de referencia; «DT» = diseño técnico; «HU01»; «equipo» = buena práctica propuesta por el equipo.

**Estructura (F1)**

| Código | Regla | Fuente |
|---|---|---|
| CASE-S01 | Contrato v1.0 completo: campos obligatorios, sin campos desconocidos, tipos exactos sin conversión, sin NaN ni infinito | ref, HU01 |
| CASE-S02 | Identificadores (caso, versión, clases, movimientos, slots, grupos, política de frontera) no vacíos, sin espacios al inicio o al final y sin caracteres de control | HU01, equipo |
| CASE-S03 | `case_version` con formato `MAYOR.MENOR.PARCHE` (por ejemplo `1.0.0`) | DT («nueva versión del caso»), equipo |
| CASE-S04 | Archivo JSON en UTF-8 de 1 MiB como máximo | DT (fronteras de confianza) |

**Consistencia (F2)**

| Código | Regla | Fuente |
|---|---|---|
| CASE-C01 | Identificadores únicos en clases, movimientos, slots y grupos | ref |
| CASE-C02 | Rangos con mínimo ≤ máximo (ciclo y dominio de flujo) | ref |
| CASE-C03 | Slot: mínimo ≤ máximo; un slot fijo tiene mínimo = máximo | ref |
| CASE-C04 | Al menos un slot variable | ref |
| CASE-C05 | Límites de slots, del ciclo y de los grupos son múltiplos de `tick_s` | ref (solo slots), DT («todos los límites y fijos») |
| CASE-C06 | Cada slot tiene exactamente un estado por cada TLS del caso, y el estado de un TLS tiene el mismo largo en todos los slots | ref (TLS repetido), DT |
| CASE-C07 | Dos slots consecutivos, incluido el último con el primero, no tienen los mismos estados. Es un **aviso**, no un error: el caso es válido, pero esos slots deberían unirse | DT (un slot es un intervalo sin cambio de estado) |
| CASE-C08 | Cada movimiento usa un TLS presente en los slots; sus índices de enlace son ≥ 0, no se repiten y caben en el largo del estado | ref (≥ 0), DT |
| CASE-C09 | Grupos: sus slots existen y no se repiten; mínimo ≤ máximo; la ventana del grupo se puede alcanzar con sus slots (suma de mínimos ≤ máximo del grupo y suma de máximos ≥ mínimo del grupo) | ref, DT |
| CASE-C10 | Ciclo factible no vacío: intersección del rango del ciclo con [suma de mínimos, suma de máximos] | ref, DT |
| CASE-C11 | Cada slot de un grupo de verde muestra verde (`g` o `G`) en al menos un enlace | DT |
| CASE-C12 | Un grupo peatonal exige evidencia en `restrictions_evidence` | DT (ventanas verificadas) |
| CASE-C13 | Origen y estado coherentes: un caso de campo (`field`) declara su red y no puede ser `synthetic_fixture`; un caso sintético no puede ser `calibrated` ni `validated` | HU01, equipo |

**Red (F3), solo si el caso declara su red**

| Código | Regla | Fuente |
|---|---|---|
| CASE-N01 | El archivo de red existe, su ruta es relativa a la carpeta del caso sin salir de ella ni pasar por enlaces, y su SHA-256 coincide | HU01, ADR09 |
| CASE-N02 | Los TLS, índices de enlace, carriles de entrada y aristas de salida de los movimientos existen en la red, y el largo de cada estado coincide con los enlaces de su TLS. Usa el inventario de red de DEV00 | HU01 |

Si el caso no declara red (el caso de ejemplo es sintético y no la tiene), CASE-N01 y CASE-N02 quedan «no aplica» y el reporte lo dice.

## Decisión 3: formato del reporte (`CaseReport`, JSON)

```json
{
  "schema_version": "1.0.0",
  "case_id": "SYNTHETIC_DEMO",
  "case_version": "1.0.0",
  "origin": "synthetic",
  "representation_status": "synthetic_fixture",
  "case_sha256": "…",
  "status": "valid",
  "exit_code": 0,
  "network": "not_declared",
  "limits": {
    "tick_s": 1.0,
    "cycle_declared_s": {"min": 40.0, "max": 100.0},
    "cycle_feasible_s": {"min": 40.0, "max": 100.0},
    "fixed_time_s": 8.0,
    "variable_slots": 2,
    "green_groups": [{"id": "NS", "declared_s": {"min": 10.0, "max": 50.0}, "reachable_s": {"min": 10.0, "max": 50.0}}]
  },
  "rules": [
    {"rule_id": "CASE-C05", "status": "passed", "field": null, "message": "…"}
  ]
}
```

Los valores del ejemplo son ilustrativos.

- `status`: `valid`, `valid_with_warnings` o `invalid`. `network`: `not_declared`, `verified` o `failed`.
- `case_sha256`: SHA-256 del contenido validado, en JSON canónico (claves ordenadas, sin espacios). Identifica la versión exacta: dos archivos con el mismo contenido dan el mismo valor aunque cambien espacios o el orden de las claves.
- `rules`: una entrada por regla, en orden fijo, con estado `passed`, `warning`, `failed` o `not_applicable`. Si falla, `field` indica el campo (por ejemplo `slots[2].max_s`) y `message` el motivo, como pide QA01.
- `limits` solo se calcula si la estructura es válida; si no, es `null`.
- **Códigos de salida**, los del diseño técnico: 0 válido o con avisos; 2 caso inválido (`INPUT_SCHEMA`); 3 archivo de red faltante (`DEPENDENCY_MISSING`); 5 red con otro hash o ruta no permitida (`HASH_MISMATCH`, `PATH_NOT_ALLOWED`).
- El reporte siempre se produce, incluso con el caso inválido: nunca se muestra una traza.

## Decisión 4: contrato

`schemas/case.schema.json` v1.0 no cambia. Las reglas nuevas se implementan como validaciones del producto, no como cambios del esquema. Si hiciera falta un campo nuevo, se pide antes al Product Owner. Una prueba de F3 comprueba que el modelo sigue el contrato.

## Decisión 5: fuera de alcance

- El comando `case validate` de la CLI.
- El verificador que exige una solución factible de referencia antes de entrenar.
- El registro que impide dos contenidos distintos con el mismo `case_id` y `case_version`. Es parte de la trazabilidad (DEV08).

## Fases siguientes

| Fase | Qué se hace |
|---|---|
| F1 | Reorganización previa; modelo tipado y lectura del archivo (CASE-S01 a S04) |
| F2 | Reglas de consistencia CASE-C01 a C13; pruebas QA01 y QA02 |
| F3 | `CaseReport`, `case_sha256`, reglas de red CASE-N01 y N02 y prueba del contrato |
| F4 | Cierre de DEV02 |

Cada fase necesita el OK del Product Owner.

## Verificación

- Sin cambios en el código ni en el paquete de documentación del investigador (`documentacion/`).
- El caso de ejemplo (`tests/fixtures/case.json`) cumple todas las reglas propuestas: se revisó a mano su contenido (2 movimientos, 6 slots, 2 grupos, un TLS).
