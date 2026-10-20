"""Permisos de clase de vehículo de SUMO (``allow`` y ``disallow``)."""


def permits(allow: str | None, disallow: str | None, vclass: str) -> bool:
    """Indica si un carril o una conexión admite ``vclass``.

    Como en SUMO: si hay ``allow``, solo esas clases (o todas con ``all``); si hay ``disallow``,
    todas menos esas; si no hay ninguno, todas.
    """
    if allow is not None:
        allowed = allow.split()
        return "all" in allowed or vclass in allowed
    if disallow is not None:
        forbidden = disallow.split()
        return "all" not in forbidden and vclass not in forbidden
    return True
