# Acta 2026-10-30: DEV03 · F3 (verificación contra el original, QA23 y QA24)

- **Tipo:** fase F3 del plan de DEV03 (HU01, HU04; P0, tamaño L). Dependencias: DEV00 y DEV02, cerradas.
- **Autorización:** el Product Owner pidió ejecutar F3 tras F2 (acta `2026-10-30-dev03-f2-programa-derivado.md`).
- **Alcance de la fase:** probar, sobre el escenario real revisado (R1), que el mapa de F1 y el programa derivado de F2 reproducen lo que el Product Owner aprobó en QA23 y QA24, que SUMO se comporta igual con ambos programas y que los archivos originales no cambian. No agrega código a la herramienta.

## Qué se hizo

1. **Se formalizó el caso de la intersección de referencia como archivo**, `datos/casos/caso-001/case.json`, con un identificador neutro. Hasta ahora existía solo en memoria. Sus datos salen de dos fuentes ya aprobadas:
   - Los 23 movimientos, de la planilla QA23 que revisó el Product Owner.
   - Los 9 tramos (duración y estado de las 26 señales), del programa activo de la red. Los límites son los de F0.
   - La red se copia dentro de la carpeta del caso, porque CASE-N01 exige que esté ahí; la copia es idéntica a la original (misma huella).
2. **Se validó el caso con las reglas de DEV02.**
3. **Se comparó** el mapa y el programa derivado con las planillas aprobadas, y se publicó el programa derivado en `datos/derivados/programas/caso-001/20261031T041338Z_63437585/`.
4. **Se corrió SUMO dos veces** sobre copias temporales, con la misma semilla y 1800 s: una con el programa original y otra con el derivado.
5. **Se comprobaron las huellas** de los originales antes y después.

Los scripts de esta verificación quedaron fuera del repositorio, porque apuntan a los datos locales (`datos/` no se versiona).

## Resultados

| Comprobación | Resultado |
|---|---|
| Validación del caso (CASE-S01 a S04, C01 a C13, N01 y N02) | 19 de 19 reglas pasan; estado `valid`, red `verified`, código de salida 0; ciclo factible 120 a 240 s, 4 slots variables, 24 s fijos |
| Huellas de los 3 archivos de identidad del escenario R1 contra el manifiesto aprobado | Iguales, antes y después |
| Copia de trabajo de la red y copia dentro del caso | Iguales a la original |
| Mapa de F1 contra QA23 (23 movimientos) | Enlace, punto de espera, carril de entrada y calle de salida coinciden en los 23; 0 diferencias |
| Señales del semáforo con dueño | Las 26, cada una con uno solo (23 de paso y 3 puntos de espera) |
| Programa derivado contra el programa de la red | 9 fases con la misma duración y el mismo estado; ciclo de 206 s |
| Programa derivado contra QA24 (9 fases y ciclo) | Duración, «Verde para» y «Amarillo para» coinciden con lo aprobado en las 9 fases; el ciclo coincide |
| Carpeta publicada | 3 archivos; el manifiesto apunta al caso validado y a la red original; las huellas del manifiesto coinciden con los archivos |
| SUMO con el programa original contra el derivado (misma semilla, 1800 s) | Los 1140 viajes y las estadísticas son idénticos |
| Control negativo (primer verde de 82 a 70 s) | Los resultados cambian, así que la comparación detecta diferencias |

En la comparación de SUMO se ignoran dos cosas que siempre difieren entre corridas: el comentario inicial con la fecha y las opciones, y la línea `performance`, que mide los segundos que tardó el computador.

## Hallazgos

- **Las reglas de DEV02 funcionan con datos reales.** CASE-C08, C11, N01 y N02 no se habían probado con el caso real; el cierre de DEV02 lo dejó como pendiente. Con `caso-001` pasan.
- **El caso lleva valores provisionales**, anotados en `restrictions_evidence`: los límites de tiempo son una propuesta del equipo pendiente del especialista de tránsito, y el dominio de flujo de cada movimiento (0 a 3600 veh/h) se fijó solo para cumplir el contrato hasta tener aforos (DEV04).
- **El origen del caso se declaró `field` con estado `unverified`**: representa una intersección real, pero no está calibrada.
- **QA23 y QA24 ya estaban revisadas** por el Product Owner el 2026-10-29 (todo «Correcto», salvo `QA24-PEATONES` en «Discrepancia», aceptada como limitación). F3 demuestra que el mapa y el programa derivado reproducen esos valores; no se generaron planillas nuevas.

## Límites de esta verificación

- La comparación en SUMO cubre 1800 s con una sola semilla. Es suficiente para probar que el programa es el mismo; no es una evaluación de tráfico.
- Los pasos peatonales siguen sin modelarse.
- La carpeta del programa derivado, el caso y los scripts son locales y no se suben a GitHub.

## Pendiente

- **F4:** cierre de DEV03, con su acta, la tabla de cumplimiento de HU01 y HU04, las desviaciones y lo pendiente.
- Decisión del Product Owner: si desea volver a firmar QA23 y QA24 con el programa derivado. No es necesario para cumplir el criterio, porque coinciden con lo que ya aprobó.
