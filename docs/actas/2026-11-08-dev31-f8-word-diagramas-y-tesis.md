Escrito para: el Product Owner (revisión de F8 de DEV31) y quien ponga al día los documentos Word y la tesis.

# DEV31 F8: Word, diagramas y tesis v2.6 borrador

- **Fecha:** 2026-11-08
- **Tarea:** DEV31 (HU15), fase F8 de la sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`.
- **Orden del PO:** «Ejecuta F8». El PO había autorizado antes pandoc y Graphviz.
- **Modelo:** Sonnet 5.5, como pide el plan.
- **Estado:** hecha. **El PO dio conformidad a F7 y F8 el 2026-11-08.** Pendiente: la tesis debe completar HU15 (sección 6); los demás pendientes de la sección 5 quedan como están.
- `documentacion/` no está en git, así que los entregables de esta fase no entran al commit. Lo que consta en git es esta acta.

## 1. Qué se entrega (en `documentacion/`)

| Entregable | Estado |
|---|---|
| `documentos/01_Diseno_tecnico.docx`, `02_Requisitos_y_plan.docx` y `03_Pruebas_y_operacion.docx` | Regenerados desde los Markdown 1.1: 24, 22 y 16 páginas (antes 17, 21 y 15). Pie de página «v1.1» |
| `diagramas/D02_Unidades`, `D03_Componentes`, `D06_Datos` y `D07_Seguridad` (`.png` y `.svg`) | Regenerados desde sus fuentes `.dot`, que ya incluían la base |
| `documentos/261-2097-11-RV-PI1-TPq v.2.6 borrador (verificada).docx` | Copia de la tesis con los cambios de HU15. **La v2.5 no se tocó** (misma huella `d0cde358…` antes y después) |
| `documentos/cambios-tesis-v2.5-a-v2.6.md` | Cada cambio: sección, texto antes, texto después y motivo |
| `INVENTARIO_SHA256.json` | Huellas nuevas de las 16 imágenes y Word y los archivos de F7 |

El validador de contratos pasó 43 de 43, con 15 historias.

## 2. Cómo se hizo

- **Herramientas temporales,** como decidió el PO: pandoc 3.13 (de la página oficial de versiones de GitHub) y Graphviz 12.2.1 (de GitLab; su huella coincide con la publicada). Se usaron desde `D:\tmp\f8-herramientas\`, fuera del proyecto, y esa carpeta se borró al terminar.
- **Word:** pandoc usa cada Word de la versión 1.0 como plantilla de estilos. Como la plantilla no daba bordes a las tablas, se les dio el aspecto de la versión 1.0 (borde gris, encabezado azul claro, letra de 9 puntos).
- **Imágenes:** la fuente DejaVu Sans, que usan los `.dot`, no está en Windows. Se dibujó con Arial en una copia, sin tocar los `.dot`. Las imágenes miden lo mismo en estilo, pero la tipografía cambió respecto de la versión 1.0.
- **Tesis:** los cambios se aplicaron sobre el XML del Word, con el texto de origen buscado exactamente una vez. No tiene control de cambios.

## 3. Revisión

Se abrieron los cinco Word con Microsoft Word, se exportaron a PDF y se revisaron visualmente **páginas representativas**: portada, una tabla, un diagrama y los casos QA32 a QA37 (documentos 01 a 03), y las páginas de los cambios de la tesis (HU15, backlog, Figura 8, Tabla 14). **No se revisó cada página.** Se vieron los cuatro diagramas nuevos.

## 4. Hallazgos

1. **La primera versión de la tesis v2.6 salió corrupta y Word no la abría.** El error era mío: una expresión que buscaba el texto de los párrafos también atrapaba otras etiquetas del XML. Lo vi al validar el XML. Se corrigió y la versión nueva abre bien.
2. **Hay un conflicto que la tesis no resuelve solo:** el capítulo 4 dice «tres de los siete módulos». Con la fila nueva de la Tabla 14 son ocho módulos. Es historia del Sprint 1 y no se tocó. Consta en el registro de cambios.
3. **Las figuras de la tesis no cambiaron.** Las Figuras 7, 8, 9 y 10 son imágenes. La nota de la Figura 8 avisa que la base se incorporará a la figura; hay que redibujarla.
4. **Los diagramas D01, D04 y D05 no se regeneraron,** porque no cambiaron. Sus imágenes siguen siendo las de la versión 1.0.
5. **No se afirma en la tesis que PostgreSQL acepte solo conexiones locales,** porque esa configuración (D4) está pendiente.

## 5. Pendientes

- **Limpieza de Word (mía, y requiere al PO).** Mi primer intento de abrir la tesis defectuosa dejó dos instancias de Word sin ventana (procesos `WINWORD` iniciados a las 19:06 y 19:07 del 2026-11-08). Una mantiene bloqueado el archivo roto `261-2097-11-RV-PI1-TPq v.2.6 borrador.docx`, y el permiso automático impidió que yo cerrara los procesos. **Hay que cerrarlos** (Administrador de tareas, procesos de Word sin ventana; el Word con ventana, «TB1-261…_E2.docx», es del PO y no se toca), borrar ese archivo roto y renombrar «(verificada)» a `261-2097-11-RV-PI1-TPq v.2.6 borrador.docx`. Mientras tanto, **el archivo bueno es el que dice «(verificada)»; no usar el otro.**
- **Revisión del PO** de los Word, los diagramas y los cambios de la tesis.
- **Decisión del PO y del asesor:** si HU15 entra en las tablas de historias de la tesis. El borrador la incluye; sin esa decisión, se quitan los cambios 2, 3, 4, 13 y 14 (la fila de la Tabla 14, el cambio 15, es de la base y se queda).
- **Redibujar las Figuras 7, 8 y 9 de la tesis.**
- **Para el final de DEV31:** prueba inestable de reconstrucción y D4. **D12:** conservar las bases anteriores hasta que el asesor vea el panel. **Con DEV16:** ensayo a escala.
- **Cierre de DEV31:** con F8 terminan las fases del plan. Cerrar DEV31 requiere la conformidad del PO sobre F7 y F8.

## 6. Conformidad del PO y completitud de HU15 en la tesis

- **Conformidad:** el PO dio conformidad a F7 y F8 el 2026-11-08. Pidió que HU15 entre en la tesis y que el cambio de Figura 8 (redibujar figuras) quede pendiente.
- **Lo que el borrador contiene de HU15:** la historia y sus criterios (3.2.5), la fila 15 del backlog (Tabla 11), la fila «Base de consulta» de la Tabla 14 y los párrafos de arquitectura y almacenamiento.
- **Lo que le falta para estar completa** (HU14 aparece 29 veces en la tesis; HU15, 3):
  1. El mapa de historias (Figura 7) y la tabla de entregas ENT1–ENT4 no incluyen HU15.
  2. No hay descomposición de HU15 en tareas técnicas (como T23–T25 para HU14) ni su asignación a sprints.
  3. El tablero y el roadmap (Tablas 12 y 13) no mencionan HU15.
  4. La tabla de trazabilidad de historias no la lista con sus objetivos, indicadores y pruebas.
  5. Los casos de prueba de la tesis (CP) no mencionan QA32 a QA37.
  6. Dependencias: la Tabla 11 dice «HU14; HU13», pero la matriz dice «DEV08;DEV19». Hay que elegir una.
- **Pendiente de redacción:** esos seis puntos. No se corrigieron en esta fase porque requieren decidir el reparto de sprints y las dependencias.
