"""Estado de la red de PostgreSQL: dónde escucha y qué conexiones admite (DEV31 F4c, C1.9; B07).

``bd verificar --red`` informa, **en solo lectura**:

- ``listen_addresses``: en qué direcciones escucha el servicio;
- las reglas de acceso de ``pg_hba.conf``: cuáles admiten conexiones desde fuera de la laptop.

Las reglas solo las puede leer el administrador del servicio (``pg_hba_file_rules``). Si el usuario
con que se verifica no puede, el resultado es **no verificado: lo consulta el administrador**; no se
inventa. Se pueden analizar también desde el texto de un ``pg_hba.conf`` que se indique.
"""

import ipaddress
from dataclasses import dataclass
from typing import Literal

import psycopg

from semaforo.bd.conexion import Connection
from semaforo.dominio.base_model import FrozenModel

__all__ = ["HbaRule", "NetworkReport", "analyze_rules", "network_report", "parse_hba"]

LOCAL_NAMES = frozenset({"localhost"})
ANY_SERVER_ADDRESS = frozenset({"all", "samehost", "samenet"})
MIN_HOST_FIELDS = 4


@dataclass(frozen=True)
class HbaRule:
    """Una línea de ``pg_hba.conf``: tipo, base, usuario, dirección y método."""

    kind: str
    database: str
    user: str
    address: str | None
    method: str

    def text(self) -> str:
        parts = [self.kind, self.database, self.user]
        if self.address is not None:
            parts.append(self.address)
        parts.append(self.method)
        return " ".join(parts)


class NetworkReport(FrozenModel):
    """Estado de la red del servicio (sin rutas ni datos de la máquina)."""

    listen_addresses: str | None
    listens_everywhere: bool | None
    rules_source: Literal["servidor", "archivo", "no_verificado"]
    rules_checked: int
    remote_rules: list[str]
    verdict: Literal["aislada", "abierta", "no_verificada"]
    warnings: list[str]


def _is_ip_mask(token: str) -> bool:
    try:
        ipaddress.ip_address(token)
    except ValueError:
        return False
    return True


def parse_hba(text: str) -> list[HbaRule]:
    """Las reglas de un ``pg_hba.conf`` (sin comentarios ni líneas vacías ni ``include``)."""
    rules: list[HbaRule] = []
    for raw in text.splitlines():
        tokens = raw.split("#", 1)[0].split()
        if not tokens or tokens[0] in ("include", "include_dir", "include_if_exists"):
            continue
        kind = tokens[0]
        if kind == "local":
            if len(tokens) >= MIN_HOST_FIELDS:
                rules.append(HbaRule(kind, tokens[1], tokens[2], None, tokens[3]))
            continue
        if len(tokens) < MIN_HOST_FIELDS + 1:
            continue
        address, rest = tokens[3], tokens[4:]
        if "/" not in address and rest and _is_ip_mask(rest[0]):
            address = f"{address} {rest[0]}"  # dirección y máscara en columnas separadas
            rest = rest[1:]
        if rest:
            rules.append(HbaRule(kind, tokens[1], tokens[2], address, rest[0]))
    return rules


def _admits_remote(rule: HbaRule) -> bool:
    """Si la regla deja entrar a equipos distintos de la propia laptop."""
    if rule.kind == "local" or rule.address is None or rule.method == "reject":
        return False
    first = rule.address.split()[0]
    if first in ANY_SERVER_ADDRESS:
        return True
    if first.lower() in LOCAL_NAMES:
        return False
    try:
        network = ipaddress.ip_network(first, strict=False)
    except ValueError:
        return True  # un nombre de equipo distinto de localhost
    return not network.is_loopback


def analyze_rules(rules: list[HbaRule]) -> list[str]:
    """Las reglas que admiten conexiones desde fuera de la laptop, como texto."""
    return [rule.text() for rule in rules if _admits_remote(rule)]


def _listen_addresses(connection: Connection) -> str | None:
    try:
        with connection.transaction():
            row = connection.execute("SHOW listen_addresses").fetchone()
    except psycopg.Error:
        return None
    return None if row is None else str(row[0])


def _server_rules(connection: Connection) -> list[HbaRule] | None:
    """Las reglas que cargó el servidor, o ``None`` si el usuario no puede leerlas."""
    try:
        with connection.transaction():
            rows = connection.execute(
                "SELECT type, array_to_string(database, ','), array_to_string(user_name, ','), "
                "address, netmask, auth_method FROM pg_hba_file_rules "
                "WHERE error IS NULL ORDER BY line_number"
            ).fetchall()
    except psycopg.Error:
        return None
    rules: list[HbaRule] = []
    for kind, database, user, address, mask, method in rows:
        joined = None if address is None else (f"{address} {mask}" if mask else str(address))
        rules.append(HbaRule(str(kind), str(database), str(user), joined, str(method)))
    return rules


def network_report(connection: Connection, hba_text: str | None = None) -> NetworkReport:
    """El estado de la red. ``hba_text`` es el texto de un ``pg_hba.conf`` por analizar."""
    listen = _listen_addresses(connection)
    everywhere = (
        None
        if listen is None
        else any(p.strip() in ("*", "0.0.0.0", "::") for p in listen.split(","))  # noqa: S104
    )
    source: Literal["servidor", "archivo", "no_verificado"]
    if hba_text is not None:
        rules, source = parse_hba(hba_text), "archivo"
    else:
        found = _server_rules(connection)
        rules, source = ([], "no_verificado") if found is None else (found, "servidor")
    remote = analyze_rules(rules)
    warnings: list[str] = []
    if source == "no_verificado":
        warnings.append(
            "No se pudieron leer las reglas de acceso (pg_hba.conf): las consulta el "
            "administrador del servicio, o se indica el archivo con --hba."
        )
        verdict: Literal["aislada", "abierta", "no_verificada"] = "no_verificada"
    elif remote:
        warnings.append(f"Hay {len(remote)} reglas que admiten equipos fuera de la laptop.")
        verdict = "abierta"
    else:
        verdict = "aislada"
        if everywhere:
            warnings.append(
                "El servicio escucha en todas las direcciones, pero las reglas solo admiten "
                "conexiones desde la propia laptop."
            )
    return NetworkReport(
        listen_addresses=listen,
        listens_everywhere=everywhere,
        rules_source=source,
        rules_checked=len(rules),
        remote_rules=remote,
        verdict=verdict,
        warnings=warnings,
    )
