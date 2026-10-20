# Vigilar cambios en la carpeta de demos de SUMO

La carpeta vigilada es la de la simulación de SUMO, que está fuera del repositorio. Su ruta es propia de cada equipo y no se versiona: se indica con `-Carpeta` o con la variable de entorno `SUMO_WATCH_DIR`.

## Qué hay aquí

- `vigilar_sumo.ps1`: calcula el SHA256 de cada archivo de la carpeta y lo compara con una línea base.
- `vigilar_sumo_baseline.json`: línea base. Es estado local de cada equipo y git la ignora; se crea con `-Init`.

## Acceso de Claude a la carpeta

Para que Claude pueda leer la carpeta en todas las sesiones, se añade a `permissions.additionalDirectories` en el `settings.json` de Claude Code del equipo (`.claude\settings.json` dentro del perfil de usuario).

## Uso

Los comandos se ejecutan en PowerShell desde la raíz del repositorio. Los ejemplos escriben `<carpeta>` donde va la ruta de la simulación; si se define `SUMO_WATCH_DIR` se puede omitir `-Carpeta`.

### 1. Crear la línea base (la primera vez, o después de aceptar cambios)

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\sumo\vigilar_sumo.ps1 -Carpeta <carpeta> -Init
```

### 2. Revisar cambios

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\sumo\vigilar_sumo.ps1 -Carpeta <carpeta>
```

Salidas posibles:

- `Sin cambios en ...`: no hay diferencias (código de salida 0).
- `NUEVO`, `MODIFICADO`, `ELIMINADO`: hubo cambios (código de salida 2).
- `NO VERIFICADO (en uso)`: el archivo estaba bloqueado en la línea base o lo está ahora. Cierre lo que lo use y ejecute `-Init` de nuevo si la comparación anterior no mostró cambios.

### 3. Aceptar los cambios

Si los cambios son esperados, vuelva a ejecutar el paso 1.

## Si un archivo sigue «en uso»

1. Cierre `sumo-gui`, `netedit` y cualquier script de Python o Java que use TraCI.
2. En el Administrador de tareas, pestaña Detalles, busque `sumo.exe`, `sumo-gui.exe`, `netedit.exe`, `python.exe` y `java.exe`.
3. Si no aparece nada, abra el Monitor de recursos (`resmon`), pestaña CPU, y busque el nombre del archivo en «Identificadores asociados». Allí se ve qué proceso lo retiene.
4. Revise también el antivirus y los editores (VS Code) que tengan el archivo abierto.

## Notas

- El script no vigila en tiempo real; solo detecta cambios cuando se ejecuta.
- Los `.gz` (red y polígonos) se hashean igual que los `.xml`: si la red cambia, el hash cambia.
- Cada cambio que el usuario avise de la simulación (rutas, comportamiento o tiempos semafóricos) exige actualizar la línea base y, si cambian fases o geometría, abrir una nueva versión del caso.
