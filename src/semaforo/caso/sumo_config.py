"""Lectura de las referencias a archivos que declara un .sumocfg.

El .sumocfg es un archivo externo y por tanto no confiable: se lee con ``defusedxml``, sin
DTD ni entidades, y con un límite de tamaño.
"""

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import parse

from semaforo.caso.errors import CasoError, ErrorCode

INPUT = "input"
GUI_ONLY = "gui_only"
OUTPUT = "output"
_ROOT_TAGS = frozenset({"configuration", "sumoConfiguration"})
_FILE_OPTION_SUFFIXES = ("-file", "-files")
_OUTPUT_OPTION_SUFFIX = "-output"


@dataclass(frozen=True)
class FileReference:
    """Un valor de archivo declarado en el .sumocfg, tal como está escrito."""

    section: str
    option: str
    path: str


@dataclass(frozen=True)
class ConfigReferences:
    """Archivos declarados por un .sumocfg.

    ``files`` contiene los archivos de ``<input>`` y ``<gui_only>`` y las salidas declaradas en
    ``<output>``. ``absolute_paths`` contiene cualquier valor, de cualquier sección, que parezca
    una ruta absoluta: SUMO la usaría tal cual, fuera de la carpeta de la corrida.
    """

    files: tuple[FileReference, ...]
    absolute_paths: tuple[FileReference, ...]


def is_absolute_like(text: str) -> bool:
    """Indica si ``text`` parece una ruta absoluta, con sintaxis de Windows o de POSIX.

    Incluye letras de unidad (``C:\\x``, ``C:/x``), rutas UNC y rutas relativas a una unidad
    (``C:x``), que también escapan de la carpeta de la corrida.
    """
    path = PureWindowsPath(text)
    return bool(path.drive or path.root)


def read_config_references(path: Path, max_bytes: int) -> ConfigReferences:
    """Lee los archivos que declara un .sumocfg.

    Una opción cuenta como archivo de entrada o de vista si su nombre termina en ``-file`` o
    ``-files`` (``net-file``, ``route-files``...), y como salida si termina en ``-output``.
    Los valores separados por comas se tratan como archivos distintos. Las opciones que no son
    archivos (``delay``, ``seed``, ``tripinfo-output.write-unfinished``...) se ignoran.

    Args:
        path: ruta del .sumocfg.
        max_bytes: tamaño máximo aceptado, en bytes.

    Raises:
        CasoError: INPUT_SCHEMA si el archivo no se puede leer, supera el límite, no es XML
            válido, contiene DTD o entidades, o su raíz no es una configuración de SUMO.
    """
    try:
        size = path.stat().st_size
    except OSError as error:
        raise _invalid(f"no se puede leer el .sumocfg ({type(error).__name__})", path) from error
    if size > max_bytes:
        raise _invalid(f"el .sumocfg pesa {size} bytes y el límite es {max_bytes}", path)
    try:
        root = parse(path, forbid_dtd=True).getroot()
    except (DefusedXmlException, ParseError, OSError) as error:
        raise _invalid(
            f"el .sumocfg no es un XML válido o seguro ({type(error).__name__})", path
        ) from error
    if root is None or root.tag not in _ROOT_TAGS:
        raise _invalid("la raíz del .sumocfg no es una configuración de SUMO", path)
    files: list[FileReference] = []
    absolute: list[FileReference] = []
    for section in root:
        for option in section:
            value = option.get("value")
            if value is None:
                continue
            references = [
                FileReference(section.tag, option.tag, item)
                for item in (part.strip() for part in value.split(","))
                if item
            ]
            absolute.extend(ref for ref in references if is_absolute_like(ref.path))
            if _declares_files(section.tag, option.tag):
                files.extend(references)
    return ConfigReferences(files=tuple(files), absolute_paths=tuple(absolute))


def _declares_files(section: str, option: str) -> bool:
    if section in (INPUT, GUI_ONLY):
        return option.endswith(_FILE_OPTION_SUFFIXES)
    return section == OUTPUT and option.endswith(_OUTPUT_OPTION_SUFFIX)


def _invalid(message: str, path: Path) -> CasoError:
    return CasoError(ErrorCode.INPUT_SCHEMA, message, path.name)
