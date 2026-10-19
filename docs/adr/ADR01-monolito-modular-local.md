# ADR01: Monolito modular local

- **Estado:** Propuesta
- **Tipo:** V/P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

Una sola distribución Python con módulos que exponen interfaces explícitas. SUMO es un proceso externo. Los límites internos se preservan sin convertir cada módulo en un servicio.

## Motivo

Un analista, procesamiento experimental en archivos locales y un equipo pequeño. Los microservicios añadirían despliegues y comunicación sin un requisito que los justifique.

## Alternativas descartadas

- Microservicios: despliegues y comunicación sin requisito que los justifique.
- Arquitectura hexagonal formal: no es compromiso del documento; el adaptador SUMO sí encapsula la dependencia.

## Impacto

Define la dirección de dependencia: interfaz → servicios de aplicación → reglas de dominio. Las reglas de dominio no importan la CLI ni lanzan procesos.

## Prueba de aceptación

`tests/unit/test_arquitectura.py`: comprueba las reglas de dependencia entre módulos y que los detectores fallan ante imports prohibidos, incluidos los relativos.

**Aceptada por el Product Owner para su prueba de aceptación.** La adopción formal sigue pendiente de DEC09.
