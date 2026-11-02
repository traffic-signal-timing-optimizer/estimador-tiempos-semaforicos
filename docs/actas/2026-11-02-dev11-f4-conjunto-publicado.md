# Acta 2026-11-02: DEV11 · F4 (conjunto publicado, comando y revisión)

- **Tipo:** fase F4 de DEV11 (HU06). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D9, D10, D11 y D12 de F0. Esta fase incluye el comando `scenarios generate` (pregunta 4 del plan, resuelta como se propuso).
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/datos/scenario_set.py` | Publica el conjunto (`publish_scenario_set`) con su manifiesto y lo lee verificado (`read_scenario_set`) |
| `src/semaforo/app/scenario_commands.py` | Caso de uso `generate_scenario_set` y su resumen `ScenarioSetResult` |
| `src/semaforo/app/issue_lines.py` | Una línea por problema de un error de validación, para la salida de error |
| `src/semaforo/cli/main.py` | Grupo `scenarios` con `generate --case --spec --seed [--workspace] [--debug]` |
| `src/semaforo/app/integrity.py` | `runs verify` revisa también la familia «escenarios» |
| `src/semaforo/dominio/scenario_spec.py` | La composición de cada fila queda con sus clases en orden alfabético (ver hallazgo 2) |
| `README.md` | Sección «Escenarios controlados: `scenarios generate`» con la tabla de códigos de salida |
| Pruebas | `test_scenario_set.py`, `test_scenario_commands.py`, `test_scenario_cli.py`, `test_scenario_sets_in_workspace.py`, `tests/e2e/test_cli_scenarios.py`: 130 nuevas en total |

## Cómo queda un conjunto publicado

`<espacio de trabajo>\derivados\escenarios\<caso>\<fecha>_<huella8>\`:

- `spec.json`: la especificación en su forma canónica (la huella de su texto va en el manifiesto);
- `escenarios\<escenario>.json`: cada escenario (contrato `scenario` v1.0) con `demand_artifact` apuntando a su archivo de llegadas;
- `demanda\<escenario>.csv`: sus llegadas;
- `manifiesto.json`: caso (versión y huella), especificación, semilla, origen, fecha, huella de contenido, resumen por familia (rangos, perturbaciones, semillas, escenarios), y por escenario su familia, perturbación, repetición, `demand_seed`, flujos usados y vehículos; más la lista de archivos con su huella.

La huella de contenido cubre todos los archivos menos el manifiesto: generar dos veces lo mismo da la misma huella aunque la carpeta lleve otra fecha. Los archivos quedan de solo lectura y nunca se sobrescribe una carpeta.

## La lectura verificada

`read_scenario_set` comprueba que la carpeta tiene exactamente los archivos del manifiesto con su huella, que la huella de contenido corresponde, que la especificación es la del manifiesto, que cada escenario cumple su contrato y coincide con su entrada (grupo, semilla, caso, origen, flujos), que enlaza su archivo de llegadas, que ese archivo es válido para el escenario y tiene los vehículos anotados, y que las familias del manifiesto son las de la especificación con todos sus escenarios. Si el cambio deja las huellas coherentes pero incumple una de esas relaciones, también lo detecta (12 de las pruebas son de ese tipo).

## El comando

```powershell
.venv\Scripts\python.exe -m semaforo scenarios generate --case RUTA\case.json --spec RUTA\spec.json --seed 7 [--workspace datos]
```

| Código | Cuándo |
|---|---|
| 0 | Conjunto publicado |
| 2 | Semilla o argumentos mal escritos; caso o especificación inexistentes o inválidos (no se publica nada) |
| 5 | Enlace en una ruta, o el conjunto ya existe |
| 1 | Error interno |

La salida estándar lleva solo el JSON (sin rutas de la máquina); la persona ve en la salida de error la ruta completa, los totales y, si hay errores de validación, **todos los problemas**, uno por línea con su regla, campo y motivo.

## Verificación

- **Pruebas:** 130 nuevas. Suite completa: **2634 pasan, 1 se salta** (una prueba que solo corre fuera de Windows). Formato, lint, tipos, contratos y reglas de capas sin observaciones.
- **QA13 completo:** generar dos veces da la misma huella de contenido y los mismos archivos byte a byte; un rango inválido o fuera del dominio se rechaza sin publicar nada; la familia se conserva (grupo, rangos, composición, frontera); la evidencia son los hashes del manifiesto y el resumen del comando.
- **Mutaciones:** 49 cambios a propósito (nombres, límites, huellas, banderas invertidas, comprobaciones de la lectura, resumen del comando, líneas de problemas, conexión del comando, agrupación por caso en `runs verify`). **46 se detectaron en la primera pasada y 3 no**: el origen del manifiesto, y los vehículos totales frente a los de la cohorte (en el manifiesto y en el resumen del comando). Las tres se cerraron con pruebas (un conjunto `field_derived` y uno con calentamiento) y los 49 quedan detectados.
- **Revisión del espacio de trabajo:** un conjunto alterado hace salir 5 a `runs verify`; los escenarios escritos a mano de `datos/escenarios/` no se mezclan con los publicados.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | `datos/escenarios/caso-001/` tiene archivos escritos a mano; publicar ahí habría marcado «desconocidos» en `runs verify` | Los conjuntos van a `derivados/escenarios/` (decisión de F0, confirmada con una prueba que mezcla ambos) |
| 2 | El orden de las clases dentro de la composición (`{"car":…,"bus":…}` o al revés) cambiaba los bytes de los escenarios y por tanto la huella, aunque la demanda fuera la misma | El modelo de la especificación ordena las clases alfabéticamente; dos especificaciones iguales en contenido dan la misma huella (prueba nueva en F1 y F2) |
| 3 | Los errores de aforos (`CountImportError`) también llevan una lista `issues`, pero con otra forma | `issue_lines` solo imprime problemas de caso, escenario y especificación; una prueba lo fija |
| 4 | El caso con un identificador como `../fuera` es válido para el caso, pero no sirve de nombre de carpeta | Se rechaza con PATH_NOT_ALLOWED antes de generar nada, con ocho identificadores inseguros probados |
| 5 | La sección nueva del README salió con un carácter de control (salto de página) en una ruta, por las barras invertidas de la herramienta | Se corrigió y se comprobó que el archivo no tiene caracteres de control |
| 6 | Una prueba mía usaba `\xff\xfe` y la herramienta lo escribió como letras, y otra dejó un salto de línea dentro de una cadena | Se corrigieron con `bytes([0xFF, 0xFE])` y con una edición directa; revisión final de caracteres invisibles en los archivos de DEV11 |
| 7 | La especificación se guarda canónica (`spec.json`), no como copia fiel del archivo original | F0 decía «copia fiel»; se corrige aquí: así dos archivos con distintos espacios dan el mismo conjunto |
| 8 | Ninguna dependencia nueva; `schemas/` sin cambios (siguen nueve contratos) | — |

## Límites

- La lectura verificada no vuelve a comparar los escenarios con el archivo del caso (el manifiesto guarda su huella); cada consumidor valida con el caso al usarlo (`read_scenario` de DEV06).
- Las llegadas no tienen rutas ni tipos de SUMO: se agregan al preparar las entradas (DEV06).

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
