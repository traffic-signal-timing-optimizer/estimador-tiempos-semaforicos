Escrito para: el Product Owner (qué se guarda y dónde) y el equipo técnico (contrato y reglas).

# DEV14 F3: publicar la etiqueta de una búsqueda

- **Fecha:** 2026-11-03
- **Plan y decisiones:** `2026-11-02-plan-dev14.md`, `2026-11-02-dev14-f0-decisiones.md` (F0-9 reemplaza la carpeta `datos/etiquetas/` del plan por `datos/derivados/referencias/`), `2026-11-02-dev14-f2-evaluacion-y-seleccion.md`
- **Historia:** HU08
- **Datos:** sintéticos (red de demostración). Las pruebas escriben en carpetas temporales; nada se escribe en `datos/`.

## Qué se hizo, en simple

Al terminar una búsqueda, la herramienta ya guarda su resultado en una carpeta **que nadie puede modificar después**:

- `label.json`: la etiqueta en el formato oficial (contrato `label` v1.0). Dice si hay plan ganador o no, el plan (duración de cada slot, ciclo y verde de cada grupo), cuántos candidatos y simulaciones hubo, y el motivo si no hay referencia.
- `traza.json`: toda la búsqueda: cada candidato, sus semillas, sus cifras, la regla de selección y por qué cada plan ganó o no.
- `cobertura.json`: cuántos planes se revisaron, cuántos eran repetidos o inviables, y cuántos quedaron fuera en cada etapa y por qué.
- `manifiesto.json`: la identidad de la etiqueta, la huella de cada archivo anterior y la huella de la red usada.

La carpeta queda en `datos/derivados/referencias/<caso>/<AAAAMMDDTHHMMSSZ>_<huella8>/`. Nunca se sobrescribe: si ya existe una igual en el mismo instante, la publicación se rechaza.

Para leerla, `read_label` revisa que la carpeta tenga exactamente esos cuatro archivos, que ninguno haya cambiado y que la etiqueta coincida con su manifiesto. Si algo no cuadra, no se usa.

`runs verify` ahora también revisa esta carpeta (familia `labels`). Si alguien cambia un archivo, aparece como «alterada».

Una búsqueda que no terminó (por ejemplo, cancelada a medias) **no** produce etiqueta. Tampoco se publica una búsqueda hecha con otro protocolo o escenario.

## Decisiones de F3

**F3-1. Ubicación:** `datos/derivados/referencias/<caso>/<fecha>_<huella8>/`, como fijó F0-9.

**F3-2. `evidence_status` sigue el propósito del protocolo.** Si el protocolo es `synthetic_fixture` (el piloto), la etiqueta sale `fixture_only`, que `CONTRATOS.md` prohíbe en el corpus principal. Solo un protocolo `main_experiment` produce `evaluated`. Así una etiqueta de desarrollo no puede colarse en el experimento principal.

**F3-3. Identificadores sin reloj.** `search_run_id` = `search-<huella16>` y `label_id` = `label-<huella16>`, donde la huella sale de la identidad de la búsqueda (caso, escenario, protocolo, presupuesto, semillas, opciones de SUMO y la lista de candidatos). La misma búsqueda da el mismo identificador.

**F3-4. `candidate_count` cuenta todos los candidatos evaluados,** incluido el plan vigente, que es auxiliar y no consume el presupuesto B. La separación queda en `traza.json` y `cobertura.json`.

**F3-5. El plan se deriva con la misma función que usa el resto del sistema** (`dominio/timing.reconstruct`), así que el ciclo y los verdes salen de las duraciones igual que en DEV19.

**F3-6. Un `reference` lleva plan y `reason` vacío; un `no_reference` no lleva plan y sí su motivo.** Esta regla no está en el JSON publicado, pero sí en el modelo (`Label`). El JSON publicado no cambió, y una prueba compara el modelo con el esquema.

**F3-7. Cobertura por búsqueda.** `cobertura.json` describe una sola búsqueda. La cobertura del conjunto de etiquetas (todos los escenarios) es de DEV24.

**F3-8. Sin comando nuevo en la CLI.** La etiqueta se publica desde código. Quien corre el piloto (F4) la publica con `publish_label`.

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/label.py` | Contrato `Label` y `Plan`, `LabelManifest`, `publish_label`, `read_label` |
| `src/semaforo/app/integrity.py` | Familia `labels` en `verify_workspace` (lo que usa `runs verify`) |
| `tests/unit/test_label.py` | 17 pruebas sin SUMO: contrato, referencia, no_reference (dos causas), búsqueda sin terminar, otro protocolo, doble publicación, cambios de archivo, manifiesto contradictorio y revisión del espacio de trabajo |
| `tests/integration/test_search_sumo.py` | 1 prueba con SUMO real: publica y relee la etiqueta de la búsqueda completa |

## Verificación

- **Puerta completa** (`scripts/check.ps1`): ruff, formato, pyright estricto, 4920 pruebas pasan y 1 se salta (solo corre fuera de Windows); contratos 43/43; ningún archivo oculto.
- **Arquitectura:** `referencias` sigue sin importar `app` ni `cli`.
- **Memoria antes de correr SUMO:** 3,4 GB libres y ningún proceso de SUMO en marcha.
- **Mutaciones:** no se hicieron en F3. Están previstas en F4, junto con el piloto real, como dice el plan.

## Pendiente

- **F4:** el piloto real del caso-001 (20 planes, 3 semillas de búsqueda, 3 finalistas con 13 semillas, 4 corridas a la vez). Medirá si sale referencia con la regla estricta; el resultado decidirá DEC06. Después, mutaciones dirigidas y revisión final.
- **Modelo:** el acta F0-10 pide Opus para todas las fases. Esta fase se hizo con Haiku 5.5, que el Product Owner eligió después de la tabla de complejidad.
- **Sin subir al remoto:** los commits quedan locales hasta que el Product Owner lo pida.
