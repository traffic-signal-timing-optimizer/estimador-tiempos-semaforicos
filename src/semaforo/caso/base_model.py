"""Base común de los modelos de datos de caso."""

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Modelo estricto: sin campos desconocidos, sin conversión de tipos y sin NaN.

    No permite reasignar campos (``frozen``). Las listas y los diccionarios que contiene siguen
    siendo mutables, así que no deben modificarse una vez creado el modelo.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
