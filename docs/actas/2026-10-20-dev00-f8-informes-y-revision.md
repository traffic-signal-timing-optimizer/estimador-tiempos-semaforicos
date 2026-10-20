# Acta 2026-10-20: DEV00 · F8 (informes, planillas de revisión y comparación)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F8 («Ejecuta F8»).
- **Código y pruebas:** commit `cd58da2`.
- **Siguiente fase:** F9 (recepción R0 provisional de punta a punta en `datos/` e informe en `docs/recepcion/`), completada: ver `docs/actas/2026-10-20-dev00-f9-recepcion-de-r0.md`.

## Qué se implementó

| Módulo | Responsabilidad |
|---|---|
| `caso/movements.py` | tabla de movimientos semafóricos por carril y clase (cambio de alcance aprobado en F4); primer paso del mapa de red de DEV03 |
| `caso/permissions.py` | permisos `allow`/`disallow` de SUMO, compartidos con la auditoría |
| `app/reception_report.py` | informe público, detalle privado de hallazgos y planillas QA23 y QA24 |
| `app/comparison.py` | comparación entre dos recepciones |
| `app/reception_models.py` | modelos del registro y de la comparación |
| `cli/main.py` | comandos `case publish-report` y `case compare` |

## Qué produce ahora cada recepción

Además de los artefactos de F7, la carpeta `datos/derivados/recepcion/<reception_id>/` contiene:

| Archivo | Para qué | ¿Se publica? |
|---|---|---|
| `movements.json` | movimientos por carril y clase | no |
| `revision_qa23.csv` | planilla de revisión de movimientos (QA23) | no |
| `revision_qa24.csv` | planilla de revisión del programa semafórico (QA24) | no |
| `hallazgos.md` | detalle de los hallazgos de la red, la demanda y la corrida | no, hasta que el Product Owner lo autorice (ADR09) |
| `informe_publico.md` | informe con lo que permite ADR09 | sí, con `case publish-report` |

## Planillas de revisión

Se abren con doble clic en Excel. Van separadas por punto y coma, que es el separador de listas de la configuración regional es-PE de este equipo, y en UTF-8 con BOM para que se vean las tildes. Desde la revisión de F9 (`dcf4b77`), los identificadores de SUMO van como fórmula de texto, porque Excel mostraba las aristas de ID numérico en notación científica.

- **QA23** tiene una fila por movimiento: semáforo, enlace (`linkIndex`), arista y carril de entrada y salida, giro y clases de la demanda que pueden usarlo.
- **QA24** tiene una fila por fase de cada programa: duración, `minDur`, `maxDur` y movimientos en verde y en amarillo. Añade el ciclo y el desfase, y filas para revisar peatones (DEC03), la frontera con semáforos vecinos (DEC04) y los detectores del programa actuado.
- **Cómo se usan:** en cada fila se escribe `Correcto` o `Discrepancia` en la columna «Resultado» y, si hay diferencia, una nota breve. Al final se completan «Revisado por» y «Fecha». Es la lista firmada que piden QA23 y QA24.
- **Cuándo:** una primera pasada con R0 después de F9, y la firma final con R1 en F10.

## Informe público y su publicación

`informe_publico.md` lleva lo que permite ADR09:

- la recepción, la copia (`snapshot_id`), la configuración de entrada, la versión de SUMO, la fecha y el estado propuesto;
- los archivos de la simulación con su rol y su hash;
- la huella de cada artefacto privado;
- la corrida base con la huella de su manifiesto (ampliación aprobada tras F5).

No lleva ningún hallazgo de la red, de la demanda ni de los resultados.

```powershell
python -m semaforo case publish-report --reception-id <id> [--workspace datos] [--destination docs/recepcion]
```

El comando verifica que la carpeta de la recepción coincida exactamente con su registro (huellas) y que el informe no contenga rutas de un equipo (unidades de Windows, rutas UNC y carpetas de usuario). Solo entonces copia el informe a `docs/recepcion/<reception_id>.md`, sin sobrescribir nunca. Es la prueba de aceptación de F8 en ADR09.

## Comparación entre recepciones

```powershell
python -m semaforo case compare --before <id> --after <id> [--workspace datos]
```

Lista los cambios entre dos recepciones verificadas:

- archivos de la copia añadidos, quitados o cambiados;
- conteos de la red y fases de cada programa;
- vehículos declarados, rutas, demanda y tipos;
- resultados de la corrida base.

Sirve para revisar R1 frente a R0. Dos recepciones de la misma simulación no muestran cambios.

## Evidencia de la puerta de salida (R0 en un espacio de trabajo temporal)

Según ADR09, el detalle no se publica aquí.

| Comprobación | Resultado |
|---|---|
| `case receive` | código 0; se generan las planillas, `hallazgos.md` y el informe |
| `case publish-report` | código 0; el informe publicado no tiene rutas del equipo |
| Planilla QA23 | una fila por cada enlace del semáforo |
| Planilla QA24 | todas las fases del programa activo, con ciclo y desfase |
| `case compare` de una recepción consigo misma | sin cambios |

**Hallazgo para QA23:** hay movimientos semafóricos que no puede usar ninguna clase de la demanda (autos ni buses), porque su carril de destino solo admite peatones, repartos o bicicletas. `hallazgos.md` los cuenta y los lista. Se confirmó contra la red que el cálculo es correcto; revisar si corresponden al cruce real es parte de QA23.

## Verificación

- Pruebas: 439 pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios). F8 añade 31.
- **Desviación del procedimiento:** las pruebas del informe, la publicación y la comparación se escribieron sin ejecutarse antes en rojo. Se compensó con 26 mutaciones de los cinco módulos, todas detectadas: separador y BOM de las planillas, verde y amarillo de las fases, firma, detección de rutas del equipo, huellas en el informe, verificación antes de publicar, no sobrescritura y comparación.
- `ruff`, formato y `pyright` estricto sin errores; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- Las planillas suponen el separador de listas de este equipo (punto y coma). En un Excel con otra configuración regional se abren con «Datos → Desde texto/CSV».
- Los movimientos se identifican por orden (`M01`, `M02`…). Si R1 cambia los enlaces del semáforo, los números pueden no coincidir con los de R0; la comparación compara fases y conteos, no movimientos uno a uno.
- La detección de rutas de un equipo cubre las formas habituales de Windows y POSIX. No reconoce rutas que alguien escriba de forma deliberadamente distinta.
