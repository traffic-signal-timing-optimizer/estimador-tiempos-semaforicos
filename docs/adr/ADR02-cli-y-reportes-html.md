# ADR02: CLI y reportes HTML estáticos

- **Estado:** Propuesta
- **Tipo:** P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

> **Alcance posterior aprobado por el PO el 2026-11-05:** HU15/DEV31 añade un panel HTML estático generado desde PostgreSQL local. El panel sigue abriéndose sin servidor web ni API HTTP; PostgreSQL es el servicio de datos local. Su implementación corresponde a DEV31 F5, aún pendiente. La aceptación formal de ADR02 sigue pendiente de DEC09 en F7.

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
