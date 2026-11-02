# Acta 2026-11-02: DEV12 · F3 (partición publicada, comandos y revisión)

- **Tipo:** fase F3 de DEV12 (HU07). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D8, D10 y D11 de F0. Esta fase incluye los comandos `splits create` y `splits validate` (pregunta 4 del plan, resuelta como se propuso).
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/aprendizaje/split_store.py` | Publica la partición de un conjunto de escenarios (`publish_split`), la lee verificada (`read_split`) y la compara con su conjunto (`validate_split`) |
| `src/semaforo/app/split_commands.py` | Casos de uso `create_split_set` y `validate_split_set` y su resumen `SplitResult` |
| `src/semaforo/cli/main.py` | Grupo `splits` con `create --scenarios --seed [--policy]` y `validate --split --scenarios` |
| `src/semaforo/app/integrity.py` | `runs verify` revisa también la familia «particiones» |
| `src/semaforo/dominio/split.py` | `split_self_issues`: las reglas que se pueden comprobar sin los escenarios (SPLIT-C02, C04, C05) |
| `src/semaforo/aprendizaje/splits.py` | `create_split` comprueba la semilla (0 a 2^63 − 1) y lo dice como regla SPLIT-S01 |
| `README.md` | Sección «Particiones sin fuga de la prueba: `splits create` y `splits validate`» |
| Pruebas | `test_split_store.py`, `test_split_commands.py`, `test_split_cli.py`, `test_splits_in_workspace.py`, `tests/e2e/test_cli_splits.py`: 102 nuevas en total |

## Cómo queda una partición publicada

`<espacio de trabajo>\derivados\particiones\<caso>\<huella16>\`, con `<huella16>` el comienzo de la huella de contenido del conjunto de escenarios:

- `split.json`: la partición, con el contrato `split` v1.0 y `frozen` siempre verdadero;
- `manifiesto.json`: caso y versión, huella de contenido del conjunto, política y proporciones (y si son provisionales), semilla, fecha, grupos y cantidad de escenarios por partición, y la huella de `split.json`.

Los archivos quedan de solo lectura y nunca se sobrescribe. Como la carpeta se nombra con la huella del conjunto, **un conjunto tiene una sola partición**: un segundo intento (con otra semilla u otra política) se rechaza con «la prueba se reserva una sola vez; para otra partición hace falta un conjunto nuevo». Es la regla de ADR07: un cambio aprendido de los resultados de la prueba implica un experimento nuevo.

## Los comandos

```powershell
.venv\Scripts\python.exe -m semaforo splits create --scenarios CARPETA_DEL_CONJUNTO --seed 7 [--policy politica.json] [--workspace datos]
.venv\Scripts\python.exe -m semaforo splits validate --split CARPETA_DE_LA_PARTICION --scenarios CARPETA_DEL_CONJUNTO
```

| Código | Cuándo |
|---|---|
| 0 | Partición publicada o válida |
| 2 | Argumentos mal escritos; conjunto, política o partición inválidos (se listan todos los problemas, uno por línea, con su regla `SPLIT-…`); menos de tres familias |
| 5 | Enlace en una ruta; conjunto o partición alterados; el conjunto ya tiene su partición |
| 1 | Error interno |

Sin `--policy` se usan las proporciones provisionales 0.6 / 0.2 / 0.2 y el mensaje para la persona dice «proporciones provisionales: DEC07 pendiente». La salida estándar lleva solo el JSON (sin rutas de la máquina).

## La lectura verificada

`read_split` comprueba que la carpeta tiene exactamente `split.json` y `manifiesto.json`, que las huellas coinciden, que la partición cumple el contrato, que está congelada, que cada grupo está en una sola partición y que las tres partes tienen grupos, y que el manifiesto coincide con la partición (identificador, semilla, grupos y cantidades). `validate_split` agrega que es la partición de ese conjunto (huella de contenido, caso y versión) y todas las reglas con sus escenarios (cobertura, grupo de cada escenario, fuente de campo compartida).

## Verificación

- **Pruebas:** 102 nuevas. Suite completa: **2929 pasan, 1 se salta** (una prueba que solo corre fuera de Windows). Formato, lint, tipos, contratos y reglas de capas sin observaciones.
- **QA14 de punta a punta:** una prueba recorre generar el conjunto, partirlo, validar, `runs verify` y alterar un byte (sale 5).
- **Mutaciones:** 44 cambios a propósito (nombres, límites, huellas, banderas invertidas, coherencia del manifiesto, vínculo con el conjunto, resumen, mensajes, conexión del comando y agrupación por caso en `runs verify`). **43 se detectaron en la primera pasada y 1 no**: que el comando use la fecha que se le da y no la del equipo. Se cerró con una prueba y las 44 quedan detectadas.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Una semilla negativa llegaba a `Split` y salía como un error de validación sin formato | `create_split` la comprueba y la informa como SPLIT-S01 con su campo y motivo |
| 2 | Agregar el grupo `splits` dejaba la función que arma los argumentos y el despachador de la CLI por encima de los límites de complejidad de Ruff | Se separó el armado de `scenarios` y `splits` en una función y el despachador usa una tabla de grupos; el comportamiento de los demás comandos no cambia (las pruebas existentes lo confirman) |
| 3 | La primera corrida del ensayo de mutaciones falló por un problema de comillas al lanzarla, sin tocar el código | Se repitió completa; el árbol de trabajo no cambió |
| 4 | Ninguna dependencia nueva; `schemas/` sin cambios (siguen nueve contratos); el archivo de política no es un contrato publicado | — |

## Límites

- `validate` compara la partición con el conjunto que se le indica; que ese conjunto sea el que se usó para entrenar lo comprobará el entrenamiento (DEV16) con la huella del conjunto que guarda el manifiesto.
- Una partición solo se puede crear desde un conjunto leído y verificado; no hay forma de partir escenarios sueltos por la línea de comandos.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
