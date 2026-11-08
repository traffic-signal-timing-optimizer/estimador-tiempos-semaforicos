# ADR05: XGBoost como candidato y mediana como predictor sencillo

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
- **Tipo:** V/P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

XGBoost es el candidato, con un regresor por salida de duración variable y reconstrucción del ciclo y los verdes. El predictor sencillo es la mediana de cada salida, calculada solo con datos de entrenamiento. Ambos pasan las mismas reglas de factibilidad. El candidato final se decide con datos de desarrollo, no por preferencia tecnológica.

## Motivo

Comparar un modelo frente a una referencia simple bajo condiciones idénticas.

## Alternativas descartadas

- Elegir XGBoost por preferencia tecnológica: prohibido por la documentación.

## Impacto

Afecta a `aprendizaje/` y `estimacion/`. Sustituir el predictor no toca restricciones ni evaluación, porque ambos cumplen la misma interfaz.

## Prueba de aceptación

QA19 (medianas esperadas; registro completo; no obliga a que gane XGBoost) y QA20 (paquete con orden o reglas alteradas se bloquea).

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`. Esta aceptación destraba DEV16: la decisión queda tomada, pero aún no hay código ni librería instalada.

1. **Orden.** Primero la mediana, que no necesita librerías; después XGBoost.
2. **Un modelo por caso y versión.** El número de salidas es el de tramos variables del caso (hoy t1, t3, t5 y t7), no un número fijo en el código. Así la herramienta sirve para otro cruce, con su propio modelo entrenado.
3. **Versión.** Se fija con una prueba de instalación, desde el PyPI oficial, en `uv.lock`. Corre en CPU y con semilla fija.
4. **Selección.** El orden de los criterios se fija en DEV16 F0, antes de entrenar. Nada de la prueba final entra a la selección. Ganar no es requisito: si la mediana es igual o mejor, se informa.
5. **Otro algoritmo.** Ambos cumplen la misma interfaz, así que el código admite más candidatos. Aun así, agregar uno cambia lo que la tesis compara: requiere otro ADR y el acuerdo del asesor, antes de abrir la prueba.
6. **Pruebas pendientes.** QA19, QA20 y la mitad de QA15 se cumplen en DEV16 y DEV17.
