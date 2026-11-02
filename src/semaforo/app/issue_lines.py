"""Líneas legibles con todos los problemas de un error de validación.

Los errores de caso, escenario y especificación llevan todos sus problemas en ``issues``; el
mensaje solo nombra el primero. La CLI imprime el resto con esto. Otros errores con una lista
``issues`` de otra forma (los de importación de aforos) no se tocan.
"""

from semaforo.dominio.case import CaseIssue
from semaforo.dominio.errors import DomainError

__all__ = ["issue_lines"]


def issue_lines(error: DomainError) -> list[str]:
    """Una línea por problema (``- REGLA campo: motivo``); vacío si el error no lleva problemas."""
    return [
        f"- {issue.rule_id}{'' if issue.field is None else f' {issue.field}'}: {issue.message}"
        for issue in getattr(error, "issues", ())
        if isinstance(issue, CaseIssue)
    ]
