Escrito para: el Product Owner (qué se decidió y por qué) y el equipo técnico (valores para F1 a F5).

# DEV14 F0: decisiones con los límites reales del equipo

- **Fecha:** 2026-11-02
- **Plan:** `docs/actas/2026-11-02-plan-dev14.md`
- **Delegación:** el Product Owner pidió que todas las decisiones las tome el equipo técnico, teniendo en cuenta los recursos del computador, los tokens de Claude y cualquier otro límite.
- **Estado:** decidido. Este acta reemplaza las propuestas D1 a D6 del plan donde difieren.

## Lo que se midió antes de decidir

| Recurso | Medida | Lectura |
|---|---|---|
| Procesador | AMD Ryzen 9 4900HS, 8 núcleos, 16 hilos | Permite correr varias simulaciones a la vez |
| Memoria | 15,4 GB en total y 2,7 GB libres (Chrome y VS Code abiertos) | Una corrida de SUMO usa poca memoria (pico medido de 34 MB); no es el límite |
| Disco D: | 428 GB libres de 488 GB; `datos/` ocupa 417 MB | Holgado para un piloto |
| Una corrida del caso-001 | 12 s y 43 MB de FCD sin filtro (27 MB con la zona); 5,6 MB comprimida | El límite real es el tiempo y el disco a gran escala, no la memoria |
| Procesos de SUMO | 0 en marcha | Nada que liberar |

## El hallazgo que cambia el tamaño del trabajo

La documentación separa dos tareas:

- **DEV14** construye el buscador y prueba que funciona (QA16 y QA18).
- **DEV24** («construir corpus principal») genera todas las etiquetas, con el protocolo congelado y DEC06, DEC07 y DEC08 cerradas.

Por eso **DEV14 no necesita las 28 horas de cálculo** que estimó el plan: esas son de DEV24. A DEV14 le basta con pruebas sobre un espacio pequeño y con un **piloto** del caso-001 que mida el costo real.

## Decisiones

**F0-1. Tamaño: un piloto, no el conjunto completo.**
- Un escenario real (`ESC-SINT-001`), con 20 candidatos más el plan vigente, 3 semillas por candidato y 3 finalistas reevaluados con 13 semillas.
- Son unas 102 corridas: unos 20 minutos en serie, o unos 6 minutos con 4 a la vez.
- Ocupan unos 2,8 GB de disco.
- Motivo: cumple QA16 y QA18 con evidencia real y mide el costo para DEV24, sin ocupar el computador por un día.

**F0-2. Corridas en paralelo: 4 a la vez, con prioridad baja.**
- Es la mitad de los núcleos, para que el Product Owner pueda seguir usando el computador.
- Antes de cada tanda se mide la memoria libre. Si baja de 1,5 GB, la tanda se pausa.
- La búsqueda guarda su avance después de cada candidato. Si el computador se suspende o se corta, continúa donde quedó, sin repetir corridas.

**F0-3. Tokens de Claude: el cálculo corre solo, sin conversación.**
- Las corridas largas se lanzan en segundo plano y solo se lee un resumen corto al final. Una simulación no gasta tokens; leer sus archivos sí, y eso se evita.
- Se reusan `evaluate_run` (DEV19), el validador y el corrector de DEV13 y el ejecutor de DEV07. No se reescribe nada de eso.
- Las mutaciones se concentran en las reglas que deciden la etiqueta, unas 60, en vez de las 129 de DEV19. Así cuestan la mitad sin perder lo importante.

**F0-4. Parámetros: se leen del protocolo, que ya tiene los campos.**
El contrato `protocol` v1.0 ya trae `search_budget`, `sampling_attempt_limit`, `finalist_count`, `seeds` y `tie_epsilon_s`. No hace falta cambiar ninguno de los nueve contratos. Valores del borrador del piloto:

| Campo | Valor | Motivo |
|---|---|---|
| `status` / `purpose` | `draft` / `synthetic_fixture` | Las etiquetas del piloto no son las principales |
| `search_budget` (B) | 20 | Piloto. DEV24 lo fija con el costo medido aquí |
| `sampling_attempt_limit` | 2000 | La grilla completa no cabe: 4 tramos variables con pasos de 1 s dan unos 4,5 millones de planes |
| `finalist_count` | 3 | |
| `seeds.search` | 1001, 1002, 1003 | Distintas de las 100 a 112 de DEV19 |
| `seeds.finalists` | 2001 a 2013 | 13 semillas, por la sensibilidad a la semilla medida en DEV19 |
| `seeds.final` | 3001 a 3013 | Reservadas. DEV14 no las usa |
| `tie_epsilon_s` | 2,0 s | Unos 2 % de la demora de las corridas limpias (104 s). El contrato lo pide en segundos, no en porcentaje |

Estos valores son de desarrollo. Fijarlos para el experimento es DEC07, en DEV24.

**F0-5. Búsqueda: muestra uniforme reproducible.**
- Cada candidato pasa por el validador de DEV13: ciclo de 120 a 240 s y verdes dentro de sus límites.
- Los planes repetidos se descartan y se cuenta el número de intentos.
- El plan vigente entra como candidato auxiliar y **no consume B**. Queda registrado así.
- Webster no entra: es de DEV15 y necesita DEC08.

**F0-6. DEC06 (provisional, solo para el desarrollo sintético).**
- Se mantiene la regla del protocolo, `complete_cohort_or_no_label`: un candidato con la cohorte incompleta en alguna semilla no puede ganar.
- **Teletransportes y choques:** un candidato con teletransportes o choques en alguna semilla **no puede ganar**. Se guarda con su motivo. Al teletransportar, SUMO saca del atasco a vehículos que seguían esperando y esconde parte de la demora: una media «buena» podría ser falsa.
- Si ningún candidato puede ganar, la etiqueta es `no_reference`, con el motivo y el conteo de cada causa. Ese escenario no se borra.
- La regla queda escrita en la traza de la búsqueda. Congelarla para el experimento principal le corresponde al investigador (DEC06) antes de DEV24.
- Riesgo aceptado: con la demanda sintética actual, 7 de 13 semillas tienen teletransportes, así que el piloto puede terminar en `no_reference`. Si pasa, es un hallazgo útil: dice que la demanda sintética satura el cruce. La demanda no se toca, porque la confirmó el Product Owner.

**F0-7. DEC04 (zona): se mantiene la zona actual y se registra la diferencia.**
- Dato del Product Owner: Javier Prado mide 800 m (este→oeste) y 750 m (oeste→este), y Frutales 1,3 km.
- En la red de SUMO, la zona mide 471 m en el acceso de Javier Prado desde el este y 1,13 km en el acceso de Frutales desde el sur. Los demás accesos de Javier Prado miden de 30 a 197 m.
- No se puede medir más allá de donde llega la red. Los vehículos que no alcanzan a entrar porque la cola llega al borde de la red sí cuentan en la demora (como espera para entrar, `departDelay`). Así, la medida principal no pierde esa espera; solo la cola, que se usa para desempatar, se queda corta.
- La corrección de fondo es extender la red de SUMO hasta esas medidas. Es un cambio del escenario de SUMO que hace el Product Owner con el especialista (ver «SUMO en cambio» en la memoria del proyecto). Cuando llegue la red nueva, la zona se recalcula sola, porque sale de las rutas.

**F0-8. Disco a gran escala (para DEV24, no ahora).**
- Para DEV24, guardar toda la FCD costaría unos 240 GB. Comprimida, unos 30 GB, porque se reduce unas 8 veces.
- La decisión de comprimirla (con un cambio de ADR11) se toma en DEV24.
- En el piloto se guarda todo sin comprimir, unos 2,8 GB, para que `runs verify` revise todas las corridas.

**F0-9. Lugar de los resultados.** La traza de la búsqueda y las etiquetas del piloto se guardan en `datos/derivados/referencias/<caso>/<fecha>_<huella>/`, de solo lectura y sin sobrescribir. `datos/etiquetas/` queda para el corpus principal de DEV24.

**F0-10. Ritmo y modelo.** Las fases F1 a F5 se hacen seguidas, con un informe final, como en DEV19. Solo se para por las causas que fijó el Product Owner. Todas las fases usan Opus.

## Fases ajustadas

| Fase | Contenido | Costo previsto |
|---|---|---|
| F1 | Muestra de candidatos, factibilidad, duplicados, intentos y traza. Sin SUMO (QA16, parte 1) | Bajo en tiempo y tokens |
| F2 | Evaluación con `evaluate_run`, elegibilidad (cohorte, teletransportes, choques), desempate, finalistas, reanudación y 4 corridas en paralelo (QA16 y QA18) | El más alto en tokens |
| F3 | Etiquetas `label` v1.0 y publicación con manifiesto y cobertura | Medio |
| F4 | Piloto del caso-001, mutaciones dirigidas, seguridad e inspección contra la documentación | Unos 6 a 20 minutos de cálculo |
| F5 | Cierre, acta, `CONTEXTO.md` y commits como crisroco, sin coautor y sin push | Bajo |
