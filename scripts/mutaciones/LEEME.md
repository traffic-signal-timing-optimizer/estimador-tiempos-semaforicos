Escrito para: el equipo técnico y quien audite el desarrollo (cómo repetir los ensayos de daño a propósito de DEV14 y DEV15).

# Ensayos de daño a propósito (mutaciones)

Cada guion **rompe a propósito**, de a una vez, una regla del código, corre las pruebas que deberían protegerla y restaura el archivo. Si las pruebas fallan, el daño se **detectó**; si pasan, **sobrevivió**: esa prueba no protege la regla.

## Antes de correr

- **Modifican archivos de `src/` y los restauran al terminar.** No los corra mientras edita el código ni en paralelo con otro ensayo ni con la puerta de calidad.
- Las pruebas deben pasar sin daño. Los guiones propios lo comprueban; `mutar.py` no, así que corra antes las pruebas del tema.
- Algunos usan SUMO real (marca `sumo`): necesitan SUMO instalado y unos minutos.
- Si un guion dice que un texto «aparece 0 veces» (omitida), el código cambió desde que se escribió: actualice el guion, no lo ignore.

## Cómo correrlos (desde la carpeta raíz del proyecto)

Los guiones de solo datos (`MUTATIONS` y `TESTS`) se corren con el ejecutor común:

```
.venv\Scripts\python.exe scripts\mutaciones\mutar.py scripts\mutaciones\dev14_f1.py
```

Los demás traen su propio ejecutor:

```
.venv\Scripts\python.exe scripts\mutaciones\dev15_f3.py
.venv\Scripts\python.exe scripts\mutaciones\dev14_a01.py [nombre de un daño]
```

## Qué rompe cada guion

| Guion | Archivo que daña | Pruebas que corre | Acta |
|---|---|---|---|
| `dev14_f1.py` (ejecutor `mutar.py`) | `referencias/search.py` | `test_search_candidates.py` | DEV14 F1 |
| `dev14_f2_sel.py` (`mutar.py`) | `referencias/selection.py` | `test_search_selection.py` | DEV14 F2 |
| `dev14_f2_eval.py`, `dev14_f2_eval_b.py` (`mutar.py`) | `referencias/evaluation.py`, `trazabilidad/fs.py` | búsqueda con SUMO | DEV14 F2 |
| `dev14_f4.py` | `referencias/label.py`, `app/integrity.py` | `test_label.py`, `test_dev14.py` | DEV14 F4 |
| `dev14_a01.py` | `evaluation.py`, `label.py`, `evidence.py` | bitácora, etiqueta, evidencia, con SUMO | enmienda A01 |
| `a03.py` (`mutar.py`) | `dominio/scenario.py`, `run_metrics.py`, `comparators.py`, `evidence.py` | origen de la evidencia | enmienda A03 |
| `dev15_f1.py`, `dev15_f2.py`, `dev15_f3.py` | `referencias/baselines.py` | `test_baselines.py` | DEV15 F1 a F3 |
| `dev15_f4.py` | `comparators.py`, `search.py` | `test_comparators.py`, `test_search_candidates.py` | DEV15 F4 |
| `dev15_f5.py` (`mutar.py`) | `comparators.py`, `baselines.py` | `test_comparators.py`, `security/test_dev15.py` | DEV15 F5 |

Los resultados de cada ensayo están en el acta de la fase. **Esta carpeta no guarda resultados**: cada corrida imprime cuántos daños se aplicaron, cuáles se detectaron y cuáles sobrevivieron.

## Lo que falta

Los ensayos de DEV01 a DEV13 y DEV19 se hicieron con guiones que siguen fuera del repositorio (en carpetas temporales de las sesiones). Si se necesitan, se archivan aquí con el mismo formato.
