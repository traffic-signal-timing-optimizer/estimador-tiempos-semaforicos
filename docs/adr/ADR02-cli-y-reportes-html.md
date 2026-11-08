# ADR02: CLI y reportes HTML estáticos

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
- **Tipo:** P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

> **Alcance posterior aprobado por el PO el 2026-11-05 e implementado en DEV31 F5:** HU15/DEV31 añade un panel HTML estático generado desde PostgreSQL local. El panel sigue abriéndose sin servidor web ni API HTTP; PostgreSQL es el servicio de datos local. Ver las precisiones de DEC09 al final.

## Decisión

La CLI es la interfaz ejecutable inicial. Las cinco vistas (Caso, Datos, Construcción, Consulta y Resultados) son reportes HTML estáticos. No se monta un servidor.

## Motivo

Los comandos implementan las operaciones y los reportes permiten inspección sin infraestructura adicional.

## Alternativas descartadas

- Formulario gráfico interactivo: exigiría una decisión de alcance y pruebas adicionales; queda para después.
- Servidor web: fuera del alcance de la versión 1 (sin API HTTP).

## Impacto

Afecta a `cli/` y a los reportes de DEV09 y DEV21. Las vistas solo muestran artefactos; la lógica vive en los módulos.

## Prueba de aceptación

QA30 (vistas con errores y texto HTML inyectado: estados claros, texto escapado, sin ejecución de contenido) y revisión manual de DEV09.

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`.

1. **Panel.** `bd panel` publica un HTML estático generado desde la base, con el rol `semaforo_panel`, que solo lee las 25 vistas aprobadas. Se abre sin servidor ni internet. Pruebas: QA30, QA34 y QA37.
2. **Las cinco vistas.** Caso y Datos existen como informes (`report case`, `report data`, DEV09) y también en el panel. Construcción corresponde a Simulaciones, Búsqueda y Entrenamiento del panel. Consulta y Resultados corresponden a Consultas, Comparación y Evaluación final: existen, pero sus datos llegan con DEV18, DEV20 y DEV26. DEV21 decidirá si completa esas vistas en el panel o aparte.
3. **Panel con servidor.** Sigue fuera de alcance. Si se pide, requiere otro ADR y pruebas de seguridad. El cambio queda acotado: el panel solo lee vistas (`vistas.*`), así que otro generador usaría las mismas consultas y el mismo rol.
