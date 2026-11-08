# Acta de cambio de alcance: base de evidencia y panel (HU15, DEV31)

- **Fecha de esta acta:** 2026-11-08. **Fecha de la decisión del PO:** 2026-11-05.
- **Por qué existe:** `documentacion/FUENTES_Y_PRECEDENCIA.md` pide registrar un cambio de alcance con su impacto. El análisis ya estaba en `docs/actas/2026-11-05-plan-base-de-datos.md`; el PO pidió escribir la documentación al final, cuando todo estuviera definido. Esta acta es ese registro formal.

## 1. Qué cambió

| | Versión 1.0 | Versión 1.1 |
|---|---|---|
| Base de datos | Excluida | PostgreSQL local, copia de consulta de los archivos |
| Panel | Cinco vistas como informes HTML | Además, un panel HTML estático generado desde la base |
| Historias | HU01 a HU14 | Más HU15 (requisito RF15) |
| Tareas | DEV00 a DEV30 | Más DEV31, hecha antes de DEV16 |
| Pruebas | QA01 a QA31 | Más QA32 a QA37 |
| Decisiones | ADR01 a ADR11 | Más ADR12; ADR01 a ADR08 aceptadas (DEC09) |

**Lo pidió el PO** para respaldar la tesis ante el asesor y el jurado: tener en un solo lugar todas las entradas y salidas de las pruebas, y un panel simple para verlas.

## 2. Qué no cambió

- **Los objetivos de la tesis** (OE1 a OE4) ni sus indicadores (I1 a I8).
- **El estimador, las métricas y la evaluación.** Ningún cálculo lee la base: siguen trabajando con los mismos archivos.
- **Los nueve contratos JSON.** La base copia lo que ellos describen; no agrega contratos.
- **Lo que queda fuera de alcance:** control en vía, conexión municipal, API, aprendizaje por refuerzo, agentes LLM y optimizar varias intersecciones a la vez.
- **El original sigue siendo el archivo con huella.** Si la base y un archivo difieren, manda el archivo.

## 3. Impacto

| Área | Impacto | Dónde consta |
|---|---|---|
| Arquitectura | Paquete `bd`; PostgreSQL como servicio externo | ADR01, ADR12, `docs/arquitectura/` |
| Seguridad | Amenazas nuevas y un secreto local (la contraseña de la base). Queda un riesgo aceptado: D4/D15 | ADR12, `docs/arquitectura/arquitectura-tecnica.md`, sección 6 |
| Pruebas | La puerta completa necesita PostgreSQL | Documento 03 |
| Operación | Respaldo y reconstrucción de la base | Documento 03, manual de instalación |
| Plazo | DEV16 quedó en pausa desde el 2026-11-05 | `docs/actas/2026-11-05-plan-base-de-datos.md`, sección 12 |
| Tesis | Unos 12 pasajes, en una copia v2.6 borrador. La v2.5 no se toca | DEV31 F8 |

## 4. Decisiones del PO en que se apoya

Secciones 12 y 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`: DEV31 antes de DEV16; PostgreSQL desde el inicio; archivos como respaldo físico y base como consolidado; se guarda la cola por acceso; se comprime el FCD; la tesis v2.5 queda intacta; el asesor se entera en la próxima reunión del PO.

**Pendiente del PO con el asesor:** comunicar este cambio y decidir si HU15 entra también en las tablas de historias de la tesis.
