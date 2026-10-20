# Vigila cambios en la carpeta de demos de SUMO comparando hashes SHA256
# contra una línea base guardada.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File vigilar_sumo.ps1 -Init     # crea/actualiza la línea base
#   powershell -ExecutionPolicy Bypass -File vigilar_sumo.ps1           # compara y muestra cambios

param(
    [switch]$Init,
    [string]$Carpeta = "D:\SUMO_demos\2026-10-14-16-22-34",
    [string]$Baseline = "$PSScriptRoot\vigilar_sumo_baseline.json"
)

if (-not (Test-Path $Carpeta)) {
    Write-Error "No existe la carpeta: $Carpeta"
    exit 1
}

# Hash actual de cada archivo (ruta relativa -> hash)
$actual = @{}
Get-ChildItem -Path $Carpeta -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($Carpeta.Length).TrimStart('\')
    try {
        $actual[$rel] = (Get-FileHash -Path $_.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
    } catch {
        # Archivo en uso por otro proceso (p. ej. SUMO escribiendo): no se puede hashear ahora
        $actual[$rel] = "BLOQUEADO"
    }
}

if ($Init) {
    $salida = [ordered]@{
        carpeta     = $Carpeta
        generado    = (Get-Date).ToString("s")
        archivos    = $actual
    }
    $salida | ConvertTo-Json -Depth 4 | Set-Content -Path $Baseline -Encoding utf8
    Write-Output "Línea base creada con $($actual.Count) archivos en: $Baseline"
    exit 0
}

if (-not (Test-Path $Baseline)) {
    Write-Error "No existe línea base. Ejecuta primero con -Init."
    exit 1
}

$base = (Get-Content -Path $Baseline -Raw -Encoding utf8 | ConvertFrom-Json).archivos
$base_h = @{}
$base.PSObject.Properties | ForEach-Object { $base_h[$_.Name] = $_.Value }

$nuevos      = @($actual.Keys | Where-Object { -not $base_h.ContainsKey($_) })
$eliminados  = @($base_h.Keys | Where-Object { -not $actual.ContainsKey($_) })
$modificados = @($actual.Keys | Where-Object {
    $base_h.ContainsKey($_) -and $actual[$_] -ne "BLOQUEADO" -and $base_h[$_] -ne "BLOQUEADO" -and $base_h[$_] -ne $actual[$_]
})
$no_verificados = @($actual.Keys | Where-Object { $actual[$_] -eq "BLOQUEADO" -or ($base_h.ContainsKey($_) -and $base_h[$_] -eq "BLOQUEADO") })
foreach ($f in $no_verificados) { Write-Output "NO VERIFICADO (en uso) $f" }

if ($nuevos.Count -eq 0 -and $eliminados.Count -eq 0 -and $modificados.Count -eq 0) {
    Write-Output "Sin cambios en $Carpeta"
    exit 0
}

foreach ($f in $nuevos)      { Write-Output "NUEVO       $f" }
foreach ($f in $modificados) { Write-Output "MODIFICADO  $f" }
foreach ($f in $eliminados)  { Write-Output "ELIMINADO   $f" }
Write-Output ""
Write-Output "Resumen: $($nuevos.Count) nuevos, $($modificados.Count) modificados, $($eliminados.Count) eliminados."
Write-Output "Si los cambios son correctos, actualiza la línea base con -Init."
exit 2
