"""Recepción de una simulación SUMO: copia inmutable de sus entradas y manifiesto con hashes.

Implementa ADR09. De la carpeta de origen se copian solo las entradas, es decir, el .sumocfg y los
archivos de su sección ``<input>``: son los que definen el ``snapshot_id``. Todo lo demás (vistas,
salidas, scripts y archivos sin referenciar) se registra en el manifiesto con su hash y su rol,
pero no se copia ni cambia la identidad.

La carpeta de origen nunca se modifica: solo se lee.
"""

import os
import posixpath
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.reception_models import (
    IDENTITY_ROLES,
    FileRecord,
    Finding,
    MissingDependency,
    Role,
    SnapshotManifest,
)
from semaforo.caso.sumo_config import (
    GUI_ONLY,
    INPUT,
    OUTPUT,
    ConfigReferences,
    is_absolute_like,
    read_config_references,
)
from semaforo.trazabilidad.fs import make_read_only, remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.ids import content_id

# Límites provisionales, pendientes del piloto. Referencia medida en la simulación de Frutales:
# 21 archivos, 1,29 MB en total y un .sumocfg de 593 bytes.
MAX_ENTRIES = 500
MAX_OBSERVED_BYTES = 512 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
RETRY_ATTEMPTS = 3
RETRY_DELAY_S = 0.5

SCRIPT_SUFFIXES = frozenset({".bat", ".cmd", ".ps1", ".sh"})
TEMP_PREFIX = ".tmp-"
ABSOLUTE_PATH_MESSAGE = "ruta absoluta: SUMO la usaría tal cual, fuera de la carpeta de la corrida"

Reason = Literal["not_found", "not_a_file", "outside_source", "absolute_path"]
_SECTION_ROLES: tuple[tuple[str, Role], ...] = (
    (INPUT, "input"),
    (GUI_ONLY, "view"),
    (OUTPUT, "output"),
)


@dataclass(frozen=True)
class ReceptionSettings:
    """Límites y reintentos de la recepción. Valores provisionales, pendientes del piloto.

    ``max_entries`` cuenta archivos y carpetas; ``max_observed_bytes`` y ``max_config_bytes`` están
    en bytes; ``retry_delay_s`` en segundos. Los reintentos cubren archivos que otro proceso (por
    ejemplo SUMO-GUI) tiene bloqueados un instante.
    """

    max_entries: int = MAX_ENTRIES
    max_observed_bytes: int = MAX_OBSERVED_BYTES
    max_config_bytes: int = MAX_CONFIG_BYTES
    retry_attempts: int = RETRY_ATTEMPTS
    retry_delay_s: float = RETRY_DELAY_S

    def __post_init__(self) -> None:
        if min(self.max_entries, self.max_observed_bytes, self.max_config_bytes) < 1:
            raise ValueError("los límites de entradas y de bytes deben ser positivos")
        if self.retry_attempts < 1:
            raise ValueError("retry_attempts debe ser al menos 1")
        if self.retry_delay_s < 0:
            raise ValueError("retry_delay_s debe ser mayor o igual que 0")


@dataclass(frozen=True)
class SnapshotResult:
    """Resultado de una recepción: el manifiesto, la carpeta de la copia y si ya existía."""

    manifest: SnapshotManifest
    path: Path
    reused: bool


@dataclass(frozen=True)
class _Analysis:
    """Lo observado en la carpeta de origen, antes de copiar nada."""

    entry: str
    sizes: dict[str, int]
    roles: dict[str, Role]
    missing: list[MissingDependency]
    findings: list[Finding]
    identity_hashes: dict[str, str]
    observed: dict[str, tuple[str | None, str | None]]


def snapshot_source(
    source: Path,
    entry_config: str,
    snapshots_root: Path,
    settings: ReceptionSettings | None = None,
) -> SnapshotResult:
    """Copia de forma inmutable las entradas de una simulación SUMO y describe lo observado.

    Si ya existe una copia con el mismo ``snapshot_id`` (mismo contenido de entrada), se reutiliza
    tras comprobar que no fue modificada. La copia se publica con renombrado atómico: ante un
    fallo no queda una carpeta a medias.

    Args:
        source: carpeta de la simulación. Solo se lee.
        entry_config: ruta del .sumocfg de entrada, relativa a ``source``.
        snapshots_root: carpeta donde se guardan las copias; no puede estar dentro de ``source``.
        settings: límites y reintentos; si es None se usan los valores provisionales.

    Raises:
        CasoError: INPUT_SCHEMA si el origen o el .sumocfg no son válidos, la carpeta de copias
            no se puede usar, un archivo de entrada no se puede leer o se superan los límites;
            PATH_NOT_ALLOWED si hay enlaces o uniones, rutas fuera de la carpeta permitida o la
            carpeta de copias está dentro del origen; HASH_MISMATCH si el origen cambia durante
            la copia o la copia no coincide.
    """
    settings = settings or ReceptionSettings()
    origin = _checked_source(source)
    root = _checked_root(snapshots_root, origin)
    analysis = _analyse(origin, entry_config, settings)
    manifest = _build_manifest(analysis)
    final = root / manifest.snapshot_id
    reused = final.exists()
    if reused:
        _verify_existing(final, analysis.identity_hashes, settings)
    else:
        _publish(origin, final, analysis.identity_hashes, settings)
    return SnapshotResult(manifest=manifest, path=final, reused=reused)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _checked_source(source: Path) -> Path:
    if _is_link(source):
        raise CasoError(ErrorCode.PATH_NOT_ALLOWED, "la carpeta de origen es un enlace", "source")
    if not source.is_dir():
        raise CasoError(
            ErrorCode.INPUT_SCHEMA, "la carpeta de origen no existe o no es una carpeta", "source"
        )
    return source.resolve()


def _checked_root(snapshots_root: Path, origin: Path) -> Path:
    resolved = snapshots_root.resolve()
    if resolved == origin or origin in resolved.parents:
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED,
            "la carpeta de copias no puede estar dentro de la carpeta de origen",
            "snapshots_root",
        )
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            f"no se puede usar la carpeta de copias ({type(error).__name__})",
            "snapshots_root",
        ) from error
    return resolved


def _scan(folder: Path, settings: ReceptionSettings) -> dict[str, int]:
    """Tamaño en bytes de cada archivo de ``folder``, por ruta relativa con ``/``.

    Rechaza enlaces simbólicos, uniones y tipos de archivo especiales, y aplica los límites antes
    de leer ningún contenido. No sigue enlaces.
    """
    sizes: dict[str, int] = {}
    entries = 0
    pending = [folder]
    while pending:
        with os.scandir(pending.pop()) as iterator:
            for entry in iterator:
                entries += 1
                if entries > settings.max_entries:
                    raise CasoError(
                        ErrorCode.INPUT_SCHEMA,
                        f"la carpeta tiene más de {settings.max_entries} entradas",
                        "source",
                    )
                relative = Path(entry.path).relative_to(folder).as_posix()
                if entry.is_symlink() or entry.is_junction():
                    raise CasoError(
                        ErrorCode.PATH_NOT_ALLOWED,
                        "no se admiten enlaces simbólicos ni uniones",
                        relative,
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    sizes[relative] = entry.stat(follow_symlinks=False).st_size
                else:
                    raise CasoError(
                        ErrorCode.PATH_NOT_ALLOWED, "tipo de archivo no admitido", relative
                    )
    if sum(sizes.values()) > settings.max_observed_bytes:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            f"la carpeta pesa más de {settings.max_observed_bytes} bytes",
            "source",
        )
    return sizes


def _lookup(sizes: Mapping[str, int], relative: str) -> str | None:
    """Ruta real de un archivo: coincidencia exacta o, en Windows, sin distinguir mayúsculas."""
    if relative in sizes:
        return relative
    if os.name == "nt":
        matches = [path for path in sizes if path.casefold() == relative.casefold()]
        if len(matches) == 1:
            return matches[0]
    return None


def _checked_entry(entry_config: str, sizes: Mapping[str, int]) -> str:
    text = entry_config.strip().replace("\\", "/")
    if not text:
        raise CasoError(ErrorCode.INPUT_SCHEMA, "falta el .sumocfg de entrada", "entry_config")
    if is_absolute_like(text) or ".." in text.split("/"):
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el .sumocfg debe estar dentro de la carpeta de origen",
            "entry_config",
        )
    found = _lookup(sizes, posixpath.normpath(text))
    if found is None:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA, f"no existe {text!r} en la carpeta de origen", "entry_config"
        )
    return found


def _resolve(
    origin: Path, sizes: Mapping[str, int], config_dir: str, reference: str
) -> tuple[str | None, Reason | None]:
    """Ruta relativa al origen de un archivo declarado, o el motivo por el que no se resuelve."""
    if is_absolute_like(reference):
        return None, "absolute_path"
    relative = posixpath.normpath(posixpath.join(config_dir, reference.replace("\\", "/")))
    if relative == ".." or relative.startswith("../"):
        return None, "outside_source"
    found = _lookup(sizes, relative)
    if found is not None:
        return found, None
    return None, ("not_a_file" if (origin / relative).is_dir() else "not_found")


def _classify(
    origin: Path, sizes: Mapping[str, int], entry: str, references: ConfigReferences
) -> tuple[dict[str, Role], list[MissingDependency]]:
    """Rol de cada archivo y dependencias que el .sumocfg declara y no se encuentran.

    Precedencia: entrada, vista, salida, script, sin referenciar. Una salida declarada que aún no
    existe no es una dependencia: la producirá una corrida.
    """
    roles: dict[str, Role] = {entry: "entry_config"}
    missing: list[MissingDependency] = []
    config_dir = posixpath.dirname(entry)
    for section, role in _SECTION_ROLES:
        for reference in (ref for ref in references.files if ref.section == section):
            resolved, reason = _resolve(origin, sizes, config_dir, reference.path)
            if resolved is not None:
                roles.setdefault(resolved, role)
            elif reason is not None and section != OUTPUT:
                dependency = MissingDependency.model_validate(
                    {
                        "path": reference.path,
                        "section": section,
                        "option": reference.option,
                        "reason": reason,
                    }
                )
                if dependency not in missing:
                    missing.append(dependency)
    for path in sizes:
        is_script = PurePosixPath(path).suffix.lower() in SCRIPT_SUFFIXES
        roles.setdefault(path, "script" if is_script else "unreferenced")
    return roles, missing


def _hash_with_retries(path: Path, settings: ReceptionSettings) -> str:
    """SHA-256 de un archivo, reintentando si otro proceso lo tiene bloqueado.

    Hace ``retry_attempts`` intentos en total. El último no se protege: si falla, el error llega
    a quien llama.
    """
    for _ in range(settings.retry_attempts - 1):
        try:
            return sha256_file(path)
        except OSError:
            time.sleep(settings.retry_delay_s)
    return sha256_file(path)


def _hash_identity_file(origin: Path, relative: str, settings: ReceptionSettings) -> str:
    try:
        return _hash_with_retries(origin / relative, settings)
    except OSError as error:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            f"no se pudo leer un archivo de entrada ({type(error).__name__})",
            relative,
        ) from error


def _observe(
    origin: Path, relative: str, settings: ReceptionSettings
) -> tuple[str | None, str | None]:
    """(hash, None) si se pudo leer; (None, motivo) si no: nunca se omite en silencio."""
    try:
        return _hash_with_retries(origin / relative, settings), None
    except OSError as error:
        return (
            None,
            f"{type(error).__name__}: no se pudo leer tras {settings.retry_attempts} intentos",
        )


def _analyse(origin: Path, entry_config: str, settings: ReceptionSettings) -> _Analysis:
    sizes = _scan(origin, settings)
    entry = _checked_entry(entry_config, sizes)
    references = read_config_references(origin / entry, settings.max_config_bytes)
    roles, missing = _classify(origin, sizes, entry, references)
    identity = sorted(path for path, role in roles.items() if role in IDENTITY_ROLES)
    identity_hashes = {path: _hash_identity_file(origin, path, settings) for path in identity}
    observed = {
        path: _observe(origin, path, settings) for path in sizes if path not in identity_hashes
    }
    findings = [
        Finding(
            code="ABSOLUTE_PATH",
            section=ref.section,
            option=ref.option,
            path=ref.path,
            message=ABSOLUTE_PATH_MESSAGE,
        )
        for ref in references.absolute_paths
    ]
    return _Analysis(entry, sizes, roles, missing, findings, identity_hashes, observed)


def _build_manifest(analysis: _Analysis) -> SnapshotManifest:
    records: list[FileRecord] = []
    for path in sorted(analysis.sizes):
        in_snapshot = path in analysis.identity_hashes
        digest, reason = (
            (analysis.identity_hashes[path], None) if in_snapshot else analysis.observed[path]
        )
        records.append(
            FileRecord(
                path=path,
                role=analysis.roles[path],
                size_bytes=analysis.sizes[path],
                sha256=digest,
                in_snapshot=in_snapshot,
                unreadable_reason=reason,
            )
        )
    return SnapshotManifest(
        snapshot_id=content_id(analysis.identity_hashes.items()),
        entry_config=analysis.entry,
        identity_files=sorted(analysis.identity_hashes),
        files=records,
        missing_dependencies=analysis.missing,
        findings=analysis.findings,
    )


def _copy_file(origin: Path, destination: Path) -> None:
    """Copia el contenido sin atributos, para que la copia no herede el solo lectura del origen."""
    shutil.copyfile(origin, destination)


def _publish(
    origin: Path, final: Path, identity_hashes: Mapping[str, str], settings: ReceptionSettings
) -> None:
    """Copia las entradas a una carpeta temporal, las verifica y la publica con un renombrado.

    Cada archivo se comprueba dos veces: la copia debe coincidir con el hash del origen y el
    origen no debe haber cambiado mientras se copiaba.
    """
    temp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=final.parent))
    try:
        for relative, expected in sorted(identity_hashes.items()):
            destination = temp / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_file(origin / relative, destination)
            if sha256_file(destination) != expected:
                raise CasoError(
                    ErrorCode.HASH_MISMATCH, "la copia no coincide con el origen", relative
                )
            if _hash_with_retries(origin / relative, settings) != expected:
                raise CasoError(
                    ErrorCode.HASH_MISMATCH, "el origen cambió durante la copia", relative
                )
        make_read_only(temp)
        temp.replace(final)
    except BaseException:
        remove_tree(temp)
        raise


def _verify_existing(
    final: Path, identity_hashes: Mapping[str, str], settings: ReceptionSettings
) -> None:
    """Comprueba que una copia ya existente tiene exactamente los archivos y hashes esperados."""
    try:
        if sorted(_scan(final, settings)) != sorted(identity_hashes):
            raise CasoError(
                ErrorCode.HASH_MISMATCH,
                "la copia existente no tiene los archivos esperados",
                final.name,
            )
        for relative, expected in identity_hashes.items():
            if sha256_file(final / relative) != expected:
                raise CasoError(
                    ErrorCode.HASH_MISMATCH, "la copia existente fue modificada", relative
                )
    except OSError as error:
        raise CasoError(
            ErrorCode.HASH_MISMATCH,
            f"la copia existente no se puede leer ({type(error).__name__})",
            final.name,
        ) from error
