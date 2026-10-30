# Acta 2026-10-29: DEV02 · F1 (modelo tipado del caso y lectura del archivo)

- **Tipo:** registro de fase del plan de DEV02 (HU01)
- **Autorización:** el Product Owner autorizó F1 («Continúa con F1»).
- **Siguiente fase:** F2 (reglas de consistencia CASE-C01 a C13 y pruebas QA01 y QA02), a la espera de su autorización.

## Qué se hizo

**1. Reorganización previa**, en un commit aparte (`8b4f03c`) y sin cambiar comportamiento: las 528 pruebas existentes siguen pasando.

| Cambio | Motivo |
|---|---|
| `FrozenModel` pasa de `caso/base_model.py` a `dominio/base_model.py` | Lo importaban siete módulos desde `caso`, y `dominio` no puede depender de `caso` (ADR01) |
| `EXIT_CODES` y `exit_code_for` pasan de `app/reception.py` a `app/exit_codes.py` | Son de toda la CLI; `doctor` importaba el servicio de recepción solo para obtenerlos |

**2. Modelo del caso**, `src/semaforo/dominio/case.py`. Reproduce el contrato `case` v1.0 (`schemas/case.schema.json`, sin cambios) con tipos exactos, sin conversiones y con los límites del contrato: `tick_s > 0`; rangos y mínimos de grupo ≥ 0; mínimos y máximos de slot > 0; listas principales con al menos un elemento; estados de señal solo con las letras de SUMO; huella SHA-256 de 64 caracteres. Reglas puras: no lee archivos ni lanza procesos.

| Regla | Qué comprueba |
|---|---|
| CASE-S01 | Contrato completo, sin campos desconocidos a ninguna profundidad, tipos exactos (un `"1"` no es un número; un `true` no es un entero), sin NaN ni infinito |
| CASE-S02 | Identificadores sin vacío, sin espacios al inicio o al final, sin caracteres de control ni invisibles. Se aplica a todos los campos que son identificadores, incluidos `tls_id`, `approach_id`, carriles y aristas, y no solo a los de la lista del acta de F0 |
| CASE-S03 | `case_version` con formato `MAYOR.MENOR.PARCHE`, sin ceros a la izquierda |

Cada problema se informa con su regla, su campo (por ejemplo `slots[2].max_s`) y su motivo en español. Todos los problemas salen juntos, hasta 100; si hay más, el último dice cuántos faltan. `parse_case` lanza `CaseInvalidError` con código `INPUT_SCHEMA` (código de salida 2), que lleva la lista completa de problemas para el `CaseReport` de F3.

**3. Lector del archivo**, `src/semaforo/caso/case_validation.py` (`read_case`):

| Regla o límite | Qué hace |
|---|---|
| CASE-S04 | Archivo de 1 MiB como máximo. Lee a lo sumo un byte más que el límite, así que un archivo enorme no se carga |
| Codificación | UTF-8, con o sin marca de orden de bytes (BOM): PowerShell 5.1 la escribe |
| Claves repetidas, `NaN`, `Infinity` | Se rechazan: JSON las admitiría y harían ambiguo el caso |
| Anidación excesiva | Un JSON de 200 000 niveles da un error claro, no una caída |
| Enlaces y uniones | No se siguen: PATH_NOT_ALLOWED (código 5) |
| Archivo ausente, carpeta o ilegible | INPUT_SCHEMA (código 2) |

**Dos detalles que decidí y no estaban en el acta de F0:** aceptar el BOM, y rechazar los caracteres invisibles (categoría Unicode «formato») además de los de control.

## Pruebas

| Archivo | Pruebas | Qué cubre |
|---|---|---|
| `tests/unit/test_case.py` | 193 | caso de ejemplo aceptado e ida y vuelta; cada uno de los 14 campos obligatorios ausentes; campos desconocidos a cuatro profundidades; tipos exactos; NaN e infinito; límites numéricos; listas vacías; valores fuera de lista; estados de señal; hash; 12 campos identificadores por 9 valores malos; identificadores válidos con espacios y acentos; propiedad con `hypothesis` (un identificador aceptado siempre está limpio); versiones válidas e inválidas; todos los problemas juntos; código y primer problema del error; tope exacto de 100; el caso no se puede modificar |
| `tests/unit/test_case_file.py` | 22 | archivo de ejemplo; BOM; el archivo no cambia ni deja restos; ausente; carpeta; unión de Windows; enlace simbólico (se salta en este equipo); tamaño exacto del máximo y un byte más; archivo de 50 MiB; no UTF-8; JSON vacío, cortado o con coma sobrante; clave repetida; `NaN`, `Infinity` y `-Infinity`; anidación excesiva; JSON que no es objeto |

**Mutaciones:** 30 errores introducidos a propósito en `case.py` y `case_validation.py` (validar menos, invertir límites, cambiar la regla de un código, cambiar el código de salida, quitar el BOM, leer sin límite, no detectar claves repetidas, entre otros). Las pruebas detectaron los 30. La primera ronda dejó pasar uno: la condición `not value.strip()` era redundante con `value != value.strip()`, así que se simplificó el código en vez de agregar una prueba sin efecto.

## Verificación

- `scripts/check.ps1` pasa: ruff, formato, pyright estricto, 742 pruebas pasan y 2 se saltan de forma declarada (enlaces simbólicos sin privilegios), contratos de referencia (43 comprobaciones), ningún código ignorado por git y ruff alineado.
- ADR01 se cumple (`tests/unit/test_arquitectura.py`): `dominio` no importa ningún otro módulo; `caso` solo importa `dominio`.
- `schemas/case.schema.json` y `tools/contracts/` no se tocaron. La prueba de que el modelo sigue el contrato es de F3.
- Sin cambios en el paquete de documentación del investigador (`documentacion/`).

## Pendiente

- **F2:** reglas de consistencia CASE-C01 a C13, con las pruebas QA01 y QA02 del catálogo.
- **F3:** `CaseReport`, `case_sha256`, reglas de red CASE-N01 y N02 y prueba del contrato.
- **Aviso al Product Owner:** el repositorio privado del escenario SUMO sigue sin crearse y no hace falta todavía. Se necesitará antes de DEV03.
