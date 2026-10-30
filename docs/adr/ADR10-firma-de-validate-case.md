# ADR10: Firma de la validación del caso: `validate_case(ruta)`

- **Estado:** Aceptada (2026-10-30), por decisión del Product Owner (opción A)
- **Tipo:** P (decisión de este equipo; aparta la firma de la documentación)
- **Fecha de registro:** 2026-10-30
- **Fecha de aceptación:** 2026-10-30
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, tabla de paquetes, fila `caso`: «validate_case(case, network) → CaseReport»
- **Relacionado con:** `docs/actas/2026-10-30-dev02-f3-reporte-y-red.md` (decisiones de F3) y `docs/actas/2026-10-30-dev02-cierre.md` (desviaciones)

## Decisión

`validate_case` recibe la **ruta del archivo del caso** y devuelve siempre un `CaseReport`:

```python
validate_case(path: Path) -> CaseReport
```

La red declarada por el caso se busca en la carpeta de ese archivo. No se pasa como argumento aparte.

Por esto, la firma de la documentación, `validate_case(case, network)`, queda sustituida por esta.

## Motivo

1. **El reporte existe también con un archivo inválido.** Si el JSON está roto, o si el archivo supera el tamaño máximo, no hay un `Case` que pasar. Con la firma de la documentación habría que escribir una segunda función para leer el archivo, y las dos podrían dar resultados distintos. Con esta firma hay un solo camino de validación.
2. **La seguridad de la ruta de la red queda en un solo lugar.** La red se declara como ruta relativa dentro del caso. CASE-N01 comprueba que esa ruta no sea absoluta, no suba de carpeta y no pase por enlaces. Esa comprobación necesita saber dónde está el caso, así que la función que la hace también debe tenerlo. Si la red llegara desde fuera, quien llama tendría que repetirla.
3. **Nadie la usa todavía.** Ningún módulo ni CLI llama a `validate_case` hoy, así que el costo de esta decisión es bajo.

## Alternativas descartadas

- **Firma de la documentación, `validate_case(case, network)`.** Obliga a dos puntos de entrada y mueve la comprobación de seguridad a quien llama. Se revisó y se descartó en F4 del DEV02, con el Product Owner.
- **Aceptar ambas firmas.** Duplica el mismo flujo sin ganar nada funcional.

## Impacto

- Afecta a `caso/case_validation.py` (`validate_case`) y, cuando exista, a la CLI `case validate` del diseño técnico, que debe recibir la ruta del caso y no un caso ya leído.
- La documentación no se modifica: su fila de `caso` sigue describiendo la firma original. Este ADR es la referencia de la diferencia.
- Si DEV03 o un consumidor externo necesitan leer la red desde otra carpeta, esta decisión se revisa con un ADR nuevo.

## Prueba de aceptación

- `tests/unit/test_case_report.py`: un archivo ausente, una carpeta, un JSON roto, un archivo por encima del tamaño máximo y un enlace producen reporte, con su motivo y su código de salida.
- `tests/unit/test_case_network.py`: una red con ruta absoluta, con `..`, con unidad o pasando por un enlace produce código de salida 5, y una red en una subcarpeta del caso se verifica.
