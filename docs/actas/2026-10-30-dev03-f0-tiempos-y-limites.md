# Acta 2026-10-30: DEV03 · F0 (tiempos del semáforo y sus límites)

- **Tipo:** decisión de la fase F0 del plan de DEV03 (HU01, HU04; P0, tamaño L). Dependencias: DEV00 y DEV02, cerradas.
- **Autorización:** el Product Owner aprobó el plan de DEV03 por fases y delegó en el equipo esta decisión: «decide tú cómo trabajar con los tiempos para DEV03, si es variable o fijo, y establece los máximos y mínimos de forma realista».
- **Contexto que fijó el Product Owner:** se trabaja con los tiempos reales ya configurados. La optimización de tiempos es el resultado que se espera del modelo, no un punto de partida.

## Decisión

El programa actual (9 fases, ciclo de 206 s) se describe como un caso con **dos tipos de tramos**:

- **Variables:** los verdes. El modelo podrá proponer otras duraciones más adelante, dentro de los límites.
- **Fijos:** los ámbares y el todo rojo. Son tiempos de seguridad y nadie los negocia a cambio de fluidez.

El **programa actual es la línea base**: un punto dentro de los límites, con el que se compararán las propuestas del modelo. El orden de las fases no cambia (secuencia fija, como pide la tesis).

| Tramo | Qué se ve en el cruce | Tipo | Actual (s) | Mínimo (s) | Máximo (s) |
|---|---|---|---|---|---|
| t1 | Javier Prado, los dos sentidos en verde | variable | 82 | 30 | 110 |
| t2 | Ámbar de Javier Prado este→oeste (oeste→este sigue en verde) | fijo | 5 | 5 | 5 |
| t3 | Javier Prado oeste→este recto y flecha a la izquierda | variable | 45 | 15 | 60 |
| t4 | Ámbar de oeste→este (el punto de espera sigue en verde) | fijo | 5 | 5 | 5 |
| t5 | Los Frutales, las dos entradas en verde | variable | 45 | 25 | 70 |
| t6 | Ámbar de Los Frutales sur (norte sigue en verde) | fijo | 5 | 5 | 5 |
| t7 | Los Frutales norte, solo | variable | 10 | 5 | 30 |
| t8 | Ámbar de Los Frutales norte | fijo | 5 | 5 | 5 |
| t9 | Todo rojo | fijo | 4 | 4 | 4 |

**Ciclo:** de 120 a 240 s (actual: 206 s). **Tick:** 1 s.

**Verde que ve cada movimiento** (grupos de verde), con sus límites:

| Movimiento | Tramos | Actual (s) | Límites (s) |
|---|---|---|---|
| Javier Prado este→oeste | t1 | 82 | 30 a 110 |
| Javier Prado oeste→este, recto | t1 + t2 + t3 | 132 | 50 a 175 |
| Javier Prado oeste→este, flecha a la izquierda | t3 | 45 | 15 a 60 |
| Los Frutales sur | t5 | 45 | 25 a 70 |
| Los Frutales norte | t5 + t6 + t7 | 60 | 35 a 105 |

Las entradas menores siguen siempre en rojo, como en el programa actual.

## Por qué estos valores

- **El programa actual queda adentro, y con margen hacia los dos lados.** Si la línea base quedara fuera de los límites, no se podría comparar con las propuestas del modelo.
- **Ciclo de 120 a 240 s.** Las guías generales suelen recomendar ciclos de hasta 120 a 150 s, pero Javier Prado opera hoy con 206 s. Ese tipo de ciclo largo es habitual en sus cruces y lo dio el Product Owner. Bajar de 120 s, con 24 s fijos y cuatro verdes, deja verdes cortos para una avenida de cuatro carriles por sentido. Pasar de 240 s haría esperar a Los Frutales más de 3 minutos en rojo.
- **Javier Prado (t1), 30 a 110 s.** Por debajo de 30 s, con el volumen de una vía principal, la cola de un ciclo no alcanza a salir. Más de 110 s le quita demasiado tiempo a Los Frutales.
- **Flecha (t3), 15 a 60 s.** 15 s permiten vaciar los vehículos que esperan dentro del cruce en los tres carriles de giro. 60 s es un tope para no castigar a Los Frutales.
- **Los Frutales (t5), 25 a 70 s.** 25 s es un mínimo prudente para una vía secundaria de varios carriles. Este mínimo **no** considera a los peatones que cruzan Javier Prado (ver riesgos).
- **Los Frutales norte solo (t7), 5 a 30 s.** Conserva la extensión del norte que existe hoy. El contrato no permite un tramo de 0 s, así que el mínimo es 5.
- **Ámbares de 5 s y todo rojo de 4 s, fijos.** Son los valores actuales y están dentro de la práctica habitual de seguridad (ámbar de 3 a 5 s). Si fueran variables, el modelo podría acortarlos para ganar fluidez a costa de seguridad.

Los valores son una **propuesta del equipo**, no medidas de campo. Siguen la regla del proyecto: los umbrales que dependen del piloto quedan marcados como tales hasta revisarlos con el especialista de tránsito.

## Comprobación

Se armó un caso de prueba con estos tramos, grupos y estados (los 26 enlaces del programa actual), sin guardarlo en el proyecto, y se evaluó con las reglas de DEV02:

- Las 13 reglas de consistencia (CASE-C01 a C13) pasan. Hay cuatro tramos variables, así que CASE-C04 se cumple sin cambiar ninguna regla.
- Ciclo factible: 120 a 240 s. Mínimo posible: 99 s; máximo posible: 294 s.
- Cada tramo y cada grupo del programa actual cae dentro de sus límites.

## Efectos a futuro

**Beneficios**
- DEV03 construye desde ya la pieza que convierte duraciones en un programa de SUMO (`simulacion/compiler.py`). La misma pieza servirá para aplicar los tiempos que proponga el modelo, sin rehacer nada.
- La prueba principal de DEV03 es objetiva: con las duraciones actuales, el programa derivado debe ser igual al original, fase por fase.
- La línea base y las propuestas del modelo se miden con las mismas reglas.
- Los tiempos de seguridad quedan fuera del alcance del modelo.

**Contras y riesgos**
- **Cambiar los límites más adelante tiene costo.** Según el diseño técnico, cambiar restricciones invalida la compatibilidad: hay que emitir una nueva versión del caso y repetir las etiquetas y el entrenamiento que dependan de ella. Por eso se eligieron límites moderadamente amplios desde el inicio.
- **Peatones.** El cruce real tiene pasos peatonales semaforizados que no están modelados (limitación aceptada en R1, DEC03). Cuando se modelen, el mínimo de Los Frutales (t5) probablemente deba subir, porque los peatones cruzan Javier Prado durante ese verde. Será una versión nueva del caso.
- **Más rango, más simulaciones.** Rangos amplios dan más espacio para mejorar, pero aumentan el tiempo de la búsqueda de referencias (DEV14). Rangos estrechos hacen lo contrario. Se eligió un punto medio.
- **No es una verificación de campo.** Los límites deben revisarse con el especialista de tránsito antes de las comparaciones del caso, como pide el diseño técnico para Webster y el plan vigente.

## Decisiones de cierre de F0 (aprobadas por el Product Owner, 2026-10-30)

**Dónde se guarda el programa derivado.** Dentro de `datos/derivados/programas/`, que ya prevé el diseño técnico (sección «Estructura de repositorio»). Cada corrida crea una carpeta nueva, con el mismo patrón que `datos/derivados/recepcion/`:

```
datos/derivados/programas/<identificador-del-caso>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/
    programa.tll.xml     programa de semáforo generado
    tramos.json          duraciones y límites usados
    manifiesto.json      huellas (SHA-256) del original y del derivado, versión de la herramienta
```

- El **identificador del caso** viene de la ficha del caso (DEV02), no del nombre del cruce. Así cada intersección nueva tiene su propia carpeta sin cambiar el código.
- La **carpeta original nunca se escribe**: antes y después de generar, se compara su huella con la del manifiesto aprobado.
- Una carpeta ya publicada no se modifica; una nueva generación crea otra carpeta.

**Nombres dentro del código.** Los nombres de módulos, funciones y variables usan términos generales (`programa_derivado`, `tramo`, `grupo_verde`). Ni el código ni las plantillas llevan nombres de calles, del cruce ni del identificador del semáforo. Esos datos viven solo en la ficha del caso y en los archivos de entrada.

**Varios semáforos.** La herramienta trabaja con un solo semáforo por caso. Si la red tiene más de uno, se detiene con un error claro que indica cuántos encontró, sin generar nada. Esto sigue el diseño técnico, que pide bloquear el caso incompatible hasta comprobar cómo se coordinan los semáforos.

**Límites de F0.** Sin cambios: verdes variables, ámbares y todo rojo fijos, ciclo de 120 a 240 s.
