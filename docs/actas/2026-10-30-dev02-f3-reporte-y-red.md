# Acta 2026-10-30: DEV02 · F3 (reporte del caso y red declarada)

- **Tipo:** registro de fase del plan de DEV02 (HU01).
- **Autorización:** el Product Owner autorizó F3 («ejecuta F3»).
- **Siguiente fase:** F4 (cierre de DEV02), a la espera de su autorización.

## Qué se hizo

- `dominio/case.py`: `canonical_sha256(case)`, la huella SHA-256 del JSON canónico del caso (claves ordenadas, sin espacios, UTF-8).
- `caso/case_report_models.py`: modelo `CaseReport` con `status`, `exit_code`, `network`, `limits`, `case_sha256` y `rules` en orden fijo. Incluye la tabla de códigos de salida del reporte.
- `caso/case_network.py`: CASE-N01 y CASE-N02, solo si el caso declara su red.
- `caso/case_validation.py`: `validate_case(path)` devuelve siempre un `CaseReport`. `read_case` mantiene su comportamiento de F2.

### Reglas de red (F3)

| Regla | Qué comprueba | Código si falla |
|---|---|---|
| CASE-N01 | La red existe, está dentro de la carpeta del caso (sin rutas absolutas, sin `..`, sin enlaces en ningún componente) y su SHA-256 coincide con el declarado | 5 si la ruta no es segura o la huella no coincide; 3 si no existe |
| CASE-N02 | Con el inventario de DEV00: los semáforos, los índices de enlace, los carriles de entrada y las aristas de salida de cada movimiento existen en la red; cada estado tiene tantas señales como enlaces tiene su semáforo | 2 (caso inválido) |

### Reporte

- `status`: `valid`, `valid_with_warnings` o `invalid`.
- `exit_code`: 0 si no hay fallos; si los hay, 5 o 3 cuando la red falla en integridad, y 2 en los demás casos.
- `network`: `not_declared`, `verified` o `failed`, y `not_checked` cuando no se pudo leer la estructura (ver decisiones).
- `limits`: ciclo declarado y factible, tiempo fijo, número de slots variables y, por grupo, el verde declarado y el alcanzable (`cycle_window` y `group_window` de F2). Es `null` si no se pudo leer la estructura.
- `case_sha256`: huella del contenido revisado. Es `null` si no se pudo leer la estructura.
- `rules`: CASE-S01 a S04, C01 a C13 y N01 y N02, en ese orden. Cada regla lleva su estado (`passed`, `warning`, `failed` o `not_applicable`) y la lista de sus problemas, cada uno con campo y motivo.
- `error`: el motivo cuando el archivo del caso no se puede leer (ausente, no es un archivo, enlace o unión).

## Decisiones (no estaban en el acta de F0)

| Tema | Decisión | Cómo relajarla |
|---|---|---|
| Estado `not_checked` | Si no se pudo leer la estructura, no se sabe si el caso declara red. El acta de F0 listaba tres valores; este es el cuarto | agregar la rama en `_network_check` |
| Problemas por regla | Cada regla lleva una lista de problemas (campo y motivo). El ejemplo del acta de F0 mostraba un solo campo; ese ejemplo era ilustrativo | — |
| Huella | Se calcula siempre que la estructura se lee, aunque la consistencia falle, porque identifica el contenido que se revisó | `case_sha256` en `validate_case` |
| Huella y números | La huella se calcula sobre el modelo validado, así que `1` y `1.0` dan la misma huella (el contrato tipa `tick_s` como número) | — |
| Prioridad de códigos | Integridad de la red (5) prevalece sobre red faltante (3), y esta sobre caso inválido (2). Un fallo de N02 cuenta como caso inválido | `_verdict` |
| Códigos de salida en `caso` | `caso` no puede importar `app` (ADR01), así que el reporte repite la tabla de tres códigos. Una prueba comprueba que coincida con `app/exit_codes.py` | mover la tabla a `dominio` |
| Ruta de la red | Se rechazan rutas absolutas, unidades, rutas UNC, `..` y enlaces en cualquier componente, aunque la ruta resuelva dentro de la carpeta | `_inside_case_folder` |
| Número de enlaces | Se compara con el máximo índice de enlace más uno (`link_count` de DEV00). Un hueco en la numeración de SUMO no se detecta (ver limitaciones) | — |
| Prueba de contrato | Sin dependencia nueva: compara el esquema que genera el modelo con `schemas/case.schema.json`, ignorando solo `description`, el título y `$schema`. Usar `jsonschema` sería una dependencia nueva y requiere OK del PO | — |
| Orden de evaluación | Las reglas de red corren siempre que la estructura sea válida, aunque falle la consistencia, para que el reporte muestre todos los problemas | — |
| Lectura de la red | La red se lee dos veces: el inventario de DEV00 y la lista de carriles y aristas. No se midió el costo con una red real | — |

## Pruebas

- 48 pruebas nuevas: 46 pasan y 2 se saltan porque este equipo no permite crear enlaces simbólicos sin privilegios. La prueba de unión (junction) sí corre en Windows.
- Archivos: `tests/unit/test_case_network.py`, `tests/unit/test_case_report.py` y `tests/unit/test_case_contract.py`.
- Suite completa: 891 pasan y 4 se saltan (antes, 843 y 2).
- **Mutaciones:** 37 errores introducidos a propósito en los cuatro módulos de F3 (rutas, enlaces, huella, prioridad de códigos, estados, límites, orden del canónico). La primera ronda dejó sobrevivir dos:
  - el número de enlaces con `connection_count` en lugar de `link_count`: se agregó una prueba con un hueco en los índices;
  - el código 5 para un archivo de caso que no se puede leer: se agregó una prueba que lo provoca con `monkeypatch`, porque aquí no se puede crear el enlace.
  Después de las pruebas nuevas, las 37 quedan detectadas.
- Una mutación de N02 resultó equivalente (retirar su código de error no cambiaba el resultado): se quitó la rama del código en lugar de dejarla sin prueba.
- Huella de regresión: la del caso de ejemplo y la de una descripción con acentos quedan fijadas. Son valores de regresión de esta implementación, no una referencia externa.

## Verificación

- `ruff check .`, `ruff format --check .`, `pyright` (0 errores), `pytest` (891 pasan y 4 se saltan) y `tools/contracts/validar_paquete.py` (código 0).
- Ningún archivo de código está ignorado por git. `ruff` alineado con `pre-commit` en 0.17.1.
- `tests/unit/test_arquitectura.py` y `test_estructura.py` pasan: `caso` no importa `app` ni `cli`, y solo `simulacion` importa SUMO.
- `schemas/case.schema.json` y `tools/contracts/` no cambiaron.
- Los pasos de `scripts/check.ps1` se corrieron uno por uno; el script completo no se ejecutó como tal.

## Limitaciones

- Las reglas de red se probaron con redes pequeñas generadas en las pruebas, con los identificadores del caso de ejemplo. Todavía no existe un caso ni una red de Los Frutales (se crean en DEV03).
- Un hueco en la numeración de enlaces de SUMO no se detecta (ver decisiones).
- No se midió el tiempo de validar la red real de Frutales (511 KB descomprimidos según DEV00).
- Las pruebas de enlaces simbólicos no corren en este equipo; la de unión sí.

## Pendiente

- **F4:** cierre de DEV02 (acta de cierre frente a `02_Requisitos_y_plan.md` y al diseño técnico, abiertos y siguiente tarea).
- **Aviso al Product Owner:** el repositorio privado del escenario SUMO no hace falta todavía. Se necesitará antes de DEV03.
- Commits locales de DEV01 y DEV02 sin subir a GitHub; la decisión de subirlos es del PO.
