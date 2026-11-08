Escrito para: quien genere o mantenga el panel de resultados (persona o agente), sin conocer el proyecto.

# Panel de resultados

Una página que se abre con doble clic y muestra los datos de entrada y los resultados del proyecto, para revisarlos con el asesor o con el jurado. Es una **foto de la base de datos**: no se conecta a nada y no cambia sola.

## Generarlo

Desde la carpeta raíz del proyecto:

```powershell
.venv\Scripts\python.exe -m semaforo bd panel
```

Publica una carpeta **nueva** de solo lectura en `datos\reportes\panel\<fecha>\`. Para verlo, abra `index.html` con doble clic. Para compartirlo, copie esa carpeta completa: funciona sola, sin internet. Los enlaces a los archivos de origen solo funcionan si la carpeta sigue dentro de `datos\`; las rutas y las huellas se ven igual.

**Códigos de salida:** 0 publicado (lea los avisos, si hay); 2 a la base le faltan las vistas del panel; 3 no hay conexión con la base o falta el rol `semaforo_panel`.

Conviene correr antes `bd evidencia`, para que la página Evidencia muestre la comprobación de esta misma base. Si la última evidencia es de otra versión, el panel lo avisa en la consola y en la página.

## De dónde sale cada cosa

| Lo que muestra | De dónde sale |
|---|---|
| Caso, planes, escenarios, demanda, protocolos | Vistas aprobadas de la base (`vistas.*`), leídas con `semaforo_panel` |
| Corridas, accesos, movimientos, cola | Las mismas vistas. La cola se resume en la base a un promedio cada 60 s; el dato segundo a segundo sigue en `vistas.cola_por_segundo` |
| Comparación con el plan actual | Se calcula en `src/semaforo/app/panel_resumen.py`, sin inferencia estadística |
| Avance del proyecto y nombres de los accesos | [`docs/panel/avance.toml`](avance.toml), a mano |
| Resultado de la última evidencia | `datos/reportes/bd/<fecha>/manifiesto.json`: solo estado y huellas |

## Reglas que no se deben romper

- **Solo `semaforo_panel`:** el rol no tiene permiso sobre ninguna tabla. Lo que una vista no devuelve, el panel no lo puede publicar. Por eso el cegado de la prueba final no depende del código del panel.
- **Una vista nueva lleva su filtro de cegado escrito.** Se agrega en `src/semaforo/bd/sql/02_reglas.sql`, en `docs/bd/esquema.toml` y en `PANEL_VIEWS` de `src/semaforo/bd/ddl.py`. Es un cambio de esquema: base candidata y aprobación de las tres huellas (`bd reconstruir`).
- **Nada externo:** la página no pide nada a la red. La política de contenido de `index.html` lo impide.
- **Todo dato pasa por `esc()`** antes de ser HTML (`src/semaforo/app/panel_web/app.js`).
- **Nada específico de un cruce en el código.** Los nombres de las calles y el avance viven en `avance.toml`.

## Al cerrar una fase

1. Actualice `docs/panel/avance.toml`: estado, fecha y acta. Si una fase queda «hecho» sin acta, una prueba falla.
2. Corra `bd evidencia` y `bd panel`.

## Qué mostrará cuando haya modelo

Las páginas **Entrenamiento**, **Consultas** y **Evaluación final** ya leen sus vistas (`metricas_modelos`, `etiquetas_entrenamiento`, `consultas_resumen`, `indicadores_finales`). Hoy dicen que no hay datos. Cuando DEV16 en adelante carguen filas, aparecen solas al generar de nuevo. La Evaluación final se queda reservada hasta que exista el hito de apertura de la prueba.

## Probarlo

```powershell
.venv\Scripts\pytest.exe tests\unit\test_panel_resumen.py tests\unit\test_panel_web.py tests\integration\test_bd_panel.py -q
.venv\Scripts\python.exe -B scripts\mutaciones\dev31_f5.py
```

`test_panel_web.py` ejecuta las páginas con Node y les inyecta un texto hostil en cada campo; sin Node en el equipo, esas pruebas se saltan. El cegado se prueba en `test_bd_reglas.py` (`test_catalog_sweep_...`), con una prueba cerrada en la base.

## Antecedente

El diseño visual, la navegación y las etiquetas de estado parten del prototipo del PO en `documentacion/frontend/`, que no se tocó y no está en git.
