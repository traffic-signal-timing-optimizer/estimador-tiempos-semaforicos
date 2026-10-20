"""Carpeta de ejecución: escritura temporal, publicación atómica y lectura verificada.

Sigue el diseño técnico («Integración y transacciones»): la ejecución se crea como carpeta
temporal, se escriben sus artefactos, se calculan los hashes, se escribe el manifiesto final y se
publica con un renombrado. Disposición publicada::

    <root>/<run_id>/manifest.json
    <root>/<run_id>/inputs/...    copia de las entradas
    <root>/<run_id>/outputs/...   lo que produjo la ejecución

Mientras se escribe vive en ``<root>/.tmp-<run_id>-…`` con un manifiesto provisional en estado
``running``, y el lock ``<root>/.lock-<run_id>`` impide dos escrituras al mismo destino. Una caída
deja esa carpeta temporal (incompleta): nunca queda publicada una ejecución a medias, y una
ejecución publicada nunca se sobrescribe.
"""

import os
import secrets
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from pydantic import ValidationError

from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad.fs import make_read_only
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.manifest import (
    Artifact,
    Error,
    Kind,
    RunManifest,
    Status,
    TerminalStatus,
    check_run_id,
)
from semaforo.trazabilidad.paths import check_relative_path

MANIFEST = "manifest.json"
INPUTS = "inputs"
OUTPUTS = "outputs"
TEMP_PREFIX = ".tmp-"
LOCK_PREFIX = ".lock-"
MAX_MANIFEST_BYTES = 1024 * 1024
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


class TrazabilidadError(DomainError):
    """Error de la carpeta de ejecución."""


def utc_now() -> datetime:
    """Fecha y hora actual en UTC."""
    return datetime.now(UTC)


def new_run_id(kind: str, now: datetime) -> str:
    """Identificador ordenable por fecha y único: ``<AAAAMMDDTHHMMSSZ>_<kind>_<8 hex>``."""
    return f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}_{kind}_{secrets.token_hex(4)}"


@dataclass(frozen=True)
class RunSpec:
    """Qué es la ejecución: los campos del manifiesto que no dependen de su resultado."""

    kind: Kind
    case_id: str
    case_version: str
    scenario_id: str | None = None
    seed: int | None = None
    protocol_id: str | None = None
    retry_of: str | None = None


@dataclass(frozen=True)
class _Result:
    """Lo que produjo la ejecución. Vacío en el manifiesto provisional (``running``)."""

    command: list[str] = field(default_factory=list[str])
    environment: dict[str, str] = field(default_factory=dict[str, str])
    exit_code: int | None = None
    error: Error | None = None
    outputs: list[Artifact] = field(default_factory=list[Artifact])


def _relative(text: str) -> str:
    try:
        return check_relative_path(text)
    except ValueError as error:
        raise TrazabilidadError(ErrorCode.PATH_NOT_ALLOWED, str(error), "path") from error


def _checked_run_id(run_id: str) -> str:
    try:
        return check_run_id(run_id)
    except ValueError as error:
        raise TrazabilidadError(ErrorCode.PATH_NOT_ALLOWED, str(error), "run_id") from error


def _scan(folder: Path) -> list[str]:
    """Archivos de ``folder`` por ruta relativa con ``/``, ordenados. Rechaza enlaces y uniones."""
    files: list[str] = []
    pending = [folder]
    while pending:
        with os.scandir(pending.pop()) as iterator:
            for entry in iterator:
                relative = Path(entry.path).relative_to(folder).as_posix()
                if entry.is_symlink() or entry.is_junction():
                    raise TrazabilidadError(
                        ErrorCode.PATH_NOT_ALLOWED, "no se admiten enlaces ni uniones", relative
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files.append(relative)
                else:
                    raise TrazabilidadError(
                        ErrorCode.PATH_NOT_ALLOWED, "tipo de archivo no admitido", relative
                    )
    return sorted(files)


class RunWriter:
    """Escribe una ejecución en una carpeta temporal y la publica de una sola vez.

    Se usa como gestor de contexto. Si el bloque termina sin ``publish`` (por ejemplo, por una
    excepción), la carpeta temporal queda como ejecución incompleta y el lock se libera.
    """

    def __init__(
        self,
        root: Path,
        spec: RunSpec,
        *,
        run_id: str | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        created_at = clock()
        chosen = new_run_id(spec.kind, created_at) if run_id is None else run_id
        self.run_id = _checked_run_id(chosen)
        self._root = root
        self._spec = spec
        self._created_at = created_at
        self._inputs: dict[str, Artifact] = {}
        self._published = False
        provisional = self._manifest("running", _Result())
        root.mkdir(parents=True, exist_ok=True)
        if (root / self.run_id).exists():
            raise TrazabilidadError(
                ErrorCode.RUN_EXISTS, "la ejecución ya existe y no se sobrescribe", "run_id"
            )
        self._lock = root / f"{LOCK_PREFIX}{self.run_id}"
        try:
            os.close(os.open(self._lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError as error:
            raise TrazabilidadError(
                ErrorCode.RUN_EXISTS, "otra escritura de esta ejecución está en curso", "run_id"
            ) from error
        try:
            self.path = Path(tempfile.mkdtemp(prefix=f"{TEMP_PREFIX}{self.run_id}-", dir=root))
            (self.path / INPUTS).mkdir()
            (self.path / OUTPUTS).mkdir()
            self._write_manifest(provisional)
        except BaseException:
            self._release()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._release()

    def add_input(self, source: Path, relative: str) -> Artifact:
        """Copia ``source`` a ``inputs/<relative>`` y la registra con su hash."""
        self._check_open()
        path = f"{INPUTS}/{_relative(relative)}"
        destination = self.path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, destination)
            digest = sha256_file(destination)
            unchanged = sha256_file(source) == digest
        except OSError as error:
            raise TrazabilidadError(
                ErrorCode.INPUT_SCHEMA,
                f"no se pudo copiar la entrada ({type(error).__name__})",
                path,
            ) from error
        if not unchanged:
            raise TrazabilidadError(
                ErrorCode.HASH_MISMATCH, "la entrada cambió durante la copia", path
            )
        artifact = Artifact(artifact_id=path, path=path, sha256=digest)
        self._inputs[path] = artifact
        return artifact

    def output_path(self, relative: str) -> Path:
        """Ruta donde escribir la salida ``outputs/<relative>``; crea sus carpetas."""
        self._check_open()
        path = self.path / OUTPUTS / _relative(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def publish(
        self,
        *,
        status: TerminalStatus,
        command: list[str],
        environment: dict[str, str],
        exit_code: int | None,
        error: Error | None = None,
    ) -> RunManifest:
        """Calcula los hashes, escribe el manifiesto final y publica la carpeta.

        Todo lo que hay en ``outputs/`` se registra como salida. Raises:
            TrazabilidadError: OUTPUT_INVALID si el manifiesto no cumple el contrato (por ejemplo,
                ``succeeded`` sin salidas) o hay archivos sin registrar; HASH_MISMATCH si una
                entrada cambió; PATH_NOT_ALLOWED si hay enlaces; RUN_EXISTS si el destino existe.
        """
        self._check_open()
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"solo se publica un estado final, no {status!r}")
        outputs = self._verified_outputs()
        try:
            result = _Result(command, environment, exit_code, error, outputs)
            manifest = self._manifest(status, result)
        except ValidationError as invalid:
            reasons = "; ".join(str(item["msg"]) for item in invalid.errors())
            raise TrazabilidadError(
                ErrorCode.OUTPUT_INVALID,
                f"el manifiesto no cumple el contrato: {reasons}",
                "status",
            ) from invalid
        final = self._root / self.run_id
        if final.exists():
            raise TrazabilidadError(ErrorCode.RUN_EXISTS, "la ejecución ya existe", "run_id")
        self._write_manifest(manifest)
        make_read_only(self.path)
        try:
            self.path.replace(final)
        except OSError as failure:
            raise TrazabilidadError(
                ErrorCode.RUN_EXISTS, "no se pudo publicar: el destino ya existe", "run_id"
            ) from failure
        self._published = True
        self._release()
        return manifest

    def _verified_outputs(self) -> list[Artifact]:
        files = _scan(self.path)
        inputs = {path for path in files if path.startswith(f"{INPUTS}/")}
        if inputs != set(self._inputs):
            raise TrazabilidadError(
                ErrorCode.OUTPUT_INVALID, "hay entradas que no se registraron con add_input", INPUTS
            )
        stray = [
            p for p in files if p != MANIFEST and not p.startswith((f"{INPUTS}/", f"{OUTPUTS}/"))
        ]
        if stray:
            raise TrazabilidadError(
                ErrorCode.OUTPUT_INVALID, "hay archivos fuera de inputs/ y outputs/", stray[0]
            )
        for path, artifact in self._inputs.items():
            if sha256_file(self.path / path) != artifact.sha256:
                raise TrazabilidadError(
                    ErrorCode.HASH_MISMATCH, "una entrada cambió antes de publicar", path
                )
        return [
            Artifact(artifact_id=path, path=path, sha256=sha256_file(self.path / path))
            for path in files
            if path.startswith(f"{OUTPUTS}/")
        ]

    def _manifest(self, status: Status, result: _Result) -> RunManifest:
        spec = self._spec
        return RunManifest(
            run_id=self.run_id,
            kind=spec.kind,
            status=status,
            created_at=self._created_at,
            case_id=spec.case_id,
            case_version=spec.case_version,
            scenario_id=spec.scenario_id,
            seed=spec.seed,
            protocol_id=spec.protocol_id,
            command=result.command,
            environment=result.environment,
            inputs=sorted(self._inputs.values(), key=lambda artifact: artifact.path),
            outputs=result.outputs,
            exit_code=result.exit_code,
            error=result.error,
            retry_of=spec.retry_of,
        )

    def _write_manifest(self, manifest: RunManifest) -> None:
        (self.path / MANIFEST).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def _check_open(self) -> None:
        if self._published:
            raise ValueError("la ejecución ya se publicó")

    def _release(self) -> None:
        lock = getattr(self, "_lock", None)
        if lock is not None:
            lock.unlink(missing_ok=True)


def read_run(root: Path, run_id: str) -> RunManifest:
    """Lee una ejecución publicada y comprueba que coincide exactamente con su manifiesto.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si ``run_id`` no es un nombre de carpeta seguro o hay
            enlaces; INPUT_SCHEMA si no existe o su manifiesto no es válido; HASH_MISMATCH si un
            artefacto falta, sobra, cambió o el manifiesto es de otra ejecución.
    """
    folder = root / _checked_run_id(run_id)
    if folder.is_symlink() or folder.is_junction():
        raise TrazabilidadError(ErrorCode.PATH_NOT_ALLOWED, "la ejecución es un enlace", "run_id")
    manifest_path = folder / MANIFEST
    if not manifest_path.is_file():
        raise TrazabilidadError(ErrorCode.INPUT_SCHEMA, "la ejecución no existe", "run_id")
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise TrazabilidadError(
                ErrorCode.INPUT_SCHEMA, "el manifiesto es demasiado grande", MANIFEST
            )
        manifest = RunManifest.model_validate_json(manifest_path.read_bytes())
    except (OSError, ValidationError) as error:
        raise TrazabilidadError(
            ErrorCode.INPUT_SCHEMA,
            f"manifiesto ilegible o no válido ({type(error).__name__})",
            MANIFEST,
        ) from error
    if manifest.run_id != run_id:
        raise TrazabilidadError(
            ErrorCode.HASH_MISMATCH, "el manifiesto es de otra ejecución", "run_id"
        )
    artifacts = [*manifest.inputs, *manifest.outputs]
    if set(_scan(folder)) != {artifact.path for artifact in artifacts} | {MANIFEST}:
        raise TrazabilidadError(
            ErrorCode.HASH_MISMATCH,
            "la carpeta no tiene exactamente los archivos del manifiesto",
            run_id,
        )
    for artifact in artifacts:
        if sha256_file(folder / artifact.path) != artifact.sha256:
            raise TrazabilidadError(
                ErrorCode.HASH_MISMATCH, "un artefacto fue modificado", artifact.path
            )
    return manifest
