# Acta 2026-11-02: DEV19 · F4 (comparación, MAE y métricas de una corrida)

- **Tipo:** fase F4 de DEV19 (HU12; HU13; QA25, QA26 y QA27 de integración). Seguida de F3, por pedido del Product Owner.
- **Decisiones que aplica:** D12, D13, D14 y D15 de `2026-11-02-dev19-f0-decisiones.md`.
- **Modelo:** Opus.
- **Datos:** sintéticos (red de demostración con SUMO real; cifras calculadas a mano).

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `evaluacion/cohort.py` (ampliado) | `compare_cohorts`: compara la demora de dos corridas con la **misma cohorte**, en total y por acceso, con la censura de cada lado a la vista |
| `evaluacion/plan_error.py` | `plan_mae`: MAE del ciclo y del verde de cada grupo (I5), con planes reconstruidos por DEV13 y con sus denominadores |
| `evaluacion/run_metrics.py` | `evaluate_run`: las métricas de una corrida publicada. Junta la conciliación, la demora con censura, la cola y las detenciones. Es lo que usarán DEV14 y DEV20 |

**Cambio frente a D17 de F0:** la comparación quedó en `cohort.py` y el MAE en un archivo propio (`plan_error.py`), en lugar de los dos en `metrics.py`. Así cada archivo hace una sola cosa. `compare.py` sigue reservado para DEV20, como dice la matriz.

## Cómo se compara (QA26)

| A | B | Resultado |
|---|---|---|
| Completa | Completa | Diferencia de medias (A − B); «igual» si cabe en la tolerancia del protocolo |
| Completa | Censurada | A es menor **solo si** su media es menor que la cota inferior de B; si no, «indeterminado» |
| Censurada | Censurada | «Indeterminado»: no hay medias completas |
| Otra cohorte | — | «No comparable»: los vehículos pedidos difieren (otro identificador, movimiento o clase) |

**La media de los que terminaron no se usa nunca.** Ejemplo de QA26: el plan A deja terminar a 2 vehículos rápidos (5 s) y deja a 2 sin entrar durante 400 s; el plan B atiende a los 4 (20 s cada uno). La media de los que terminaron diría que A es mejor (5 < 20). Pero la cota inferior de A es (5 + 5 + 400 + 400) / 4 = **202.5 s**, así que B es menor con certeza. Si los que no entraron hubieran esperado solo 15 s, la cota de A sería 10 s y la respuesta sería «indeterminado», no «A».

## MAE (I5)

- **Qué mide:** el error absoluto medio del ciclo y del verde de cada grupo, en segundos, entre el plan estimado y el de referencia de cada escenario.
- **Cómo se reconstruyen los planes:** con DEV13, así que el ciclo cuenta cada tramo una vez.
- **Faltantes:** un par sin plan estimado (rechazado o fallido) o sin referencia (`no_reference`) se cuenta aparte. No se descarta en silencio.
- **Denominador:** el MAE se calcula sobre los evaluados. Se cumple que pares = evaluados + sin predicción + sin referencia.
- **Planes inválidos:** si un plan no es un plan del caso (le falta o le sobra un tramo, o tiene un NaN o un negativo), el cálculo se rechaza con su motivo.
- **Comparación con la mediana:** se calcula un MAE por estimador con los mismos pares. Ese uso es de DEV16 y DEV25.

## `evaluate_run`

1. **Entradas:** comprueba la carpeta de entradas.
2. **Caso:** comprueba que es el de esas entradas, por su huella; si no, `HASH_MISMATCH`.
3. **Protocolo:** exige una población y una censura que se sepan medir.
4. **Corrida:** la concilia. Debe ser exitosa, no estar alterada y estar hecha con esas mismas entradas.
5. **Cálculo:** la demora con censura y, si la corrida tiene FCD, la cola y las detenciones. Una carpeta 1.0.0, sin FCD, da la cola y las detenciones vacías y dice por qué.
6. **Zona:** si el protocolo pide un carril que la corrida no registró, `INPUT_SCHEMA`.

El resultado lleva el origen del caso (sintético o de campo), el protocolo y su estado (`draft` o `frozen`), la definición de demora usada, y cada cifra con su unidad y su denominador. No escribe nada: publicarlo como evaluación es de DEV20.

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | **60**: 13 de comparación (QA26 y reglas), 13 de MAE, 10 de integración con SUMO real y 24 de seguridad |
| Con SUMO real | Corrida completa: 150 pedidos, cohorte completa, cola con cobertura 100 % (900 ticks) y detenciones. Saturada: todos los pedidos en la tabla, censurada, cota inferior y espera registrada por SUMO. Carpeta 1.0.0: sin zona, con el motivo. Carpeta 1.0.0 saturada: la espera de los que no entraron es fin de la simulación menos su salida programada. Rechazos: caso ajeno, corrida de otras entradas, corrida fallida y zona no registrada |
| Seguridad | Bomba de entidades rechazada en menos de 5 s; entidad externa sin resolver; identificadores y políticas de 1 MB con mensajes de menos de 400 caracteres; números no finitos rechazados; 20 000 niveles de anidación sin caerse; 200 000 pasos leídos sin guardarlos; identificadores de corrida hostiles sin salir de la carpeta |
| Suite completa | **4745 pasan, 1 se salta**. Formato, lint, tipos estrictos y reglas de capas sin observaciones |
| Mutaciones | **25**. 22 detectadas a la primera. 2 huecos reales cerrados: la igualdad justo en el borde de la tolerancia, y el fin de la simulación en una carpeta vieja saturada **con drenaje** (sin drenaje, el fin de la cohorte y el de la simulación coinciden y no se distinguen). 1 equivalente: con la misma cohorte, los dos lados tienen los mismos pedidos; se simplificó la condición |

## Hallazgo de seguridad

Los mensajes de «población no admitida» y «censura no admitida» repetían enteros los textos del protocolo. Con un texto de 1 MB, el mensaje medía 1 MB. Ahora se acortan con `shown` (40 caracteres), como en DEV13. Lo mismo se aplicó a los identificadores de vehículo, de movimiento y de carril en los demás mensajes de DEV19.

## Límites

- Comparar dos **planes** distintos con la misma demanda necesita armar dos corridas con programas distintos: eso es de DEV20. Aquí se comprobó que dos corridas censuradas iguales dan «indeterminado».
- Los costos (I7) y los intervalos de confianza (QA28) quedan en DEV20 (D14).
