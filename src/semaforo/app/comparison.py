"""Comparación entre dos recepciones (F8 de DEV00): qué cambió de una versión a otra.

Sirve para revisar la recepción oficial R1 frente a la provisional R0, después de que el Product
Owner modifique rutas, comportamiento o tiempos semafóricos. Solo compara recepciones verificadas.
"""

from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, ValidationError

from semaforo.app.reception import read_reception, reception_folder
from semaforo.app.reception_models import (
    Change,
    ChangeArea,
    ReceptionComparison,
    ReceptionRecord,
)
from semaforo.caso.audit_models import SimulationAudit
from semaforo.caso.inventory_models import NetworkInventory
from semaforo.caso.reception_models import SnapshotManifest
from semaforo.dominio.errors import DomainError, ErrorCode

RUN_FIELDS = (
    "vehicles_loaded",
    "vehicles_inserted",
    "vehicles_waiting",
    "vehicles_running",
    "trips_finished",
    "teleports_total",
    "collisions",
    "sumo_warnings",
    "mean_depart_delay_s",
    "demand_unmet",
)


def compare_receptions(workspace: Path, before: str, after: str) -> ReceptionComparison:
    """Diferencias entre la recepción ``before`` y la ``after`` del mismo espacio de trabajo.

    Raises:
        DomainError: los de ``read_reception`` para cualquiera de las dos.
    """
    old, new = read_reception(workspace, before), read_reception(workspace, after)
    changes = [
        *_snapshot_changes(
            _load(workspace, before, "snapshot_manifest.json", SnapshotManifest),
            _load(workspace, after, "snapshot_manifest.json", SnapshotManifest),
        ),
        *_inventory_changes(_optional(workspace, before, old), _optional(workspace, after, new)),
        *_audit_changes(
            _load(workspace, before, "audit.json", SimulationAudit),
            _load(workspace, after, "audit.json", SimulationAudit),
        ),
        *_run_changes(old, new),
    ]
    return ReceptionComparison(
        before=before,
        after=after,
        same_snapshot=old.snapshot_id == new.snapshot_id,
        changes=changes,
    )


def _load[Model: BaseModel](
    workspace: Path, reception_id: str, name: str, model: type[Model]
) -> Model:
    path = reception_folder(workspace, reception_id) / name
    try:
        return model.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise DomainError(
            ErrorCode.INPUT_SCHEMA, f"artefacto ilegible o no válido ({type(error).__name__})", name
        ) from error


def _optional(
    workspace: Path, reception_id: str, record: ReceptionRecord
) -> NetworkInventory | None:
    if all(artifact.path != "inventory.json" for artifact in record.artifacts):
        return None
    return _load(workspace, reception_id, "inventory.json", NetworkInventory)


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, bool):
        return "sí" if value else "no"
    return str(value)


def _diff(
    area: ChangeArea, before: Mapping[str, object], after: Mapping[str, object]
) -> Iterable[Change]:
    for key in sorted(set(before) | set(after)):
        old, new = _text(before.get(key)), _text(after.get(key))
        if old != new:
            yield Change(area=area, item=key, before=old, after=new)


def _snapshot_changes(before: SnapshotManifest, after: SnapshotManifest) -> list[Change]:
    def files(manifest: SnapshotManifest) -> dict[str, object]:
        return {
            record.path: f"{record.role} {record.sha256 or 'ilegible'}" for record in manifest.files
        }

    return list(_diff("snapshot", files(before), files(after)))


def _inventory_changes(
    before: NetworkInventory | None, after: NetworkInventory | None
) -> list[Change]:
    def facts(inventory: NetworkInventory | None) -> dict[str, object]:
        if inventory is None:
            return {}
        found: dict[str, object] = dict(inventory.counts.model_dump(exclude={"junction_types"}))
        for tls in inventory.traffic_lights:
            found[f"{tls.id} programa activo"] = tls.active_program_id
            found[f"{tls.id} enlaces"] = tls.link_count
            for program in tls.programs:
                key = f"{tls.id} programa {program.program_id}"
                found[f"{key} tipo"] = program.type
                found[f"{key} desfase"] = program.offset_s
                for phase in program.phases:
                    found[f"{key} fase {phase.index:02d}"] = (
                        f"{phase.duration_s:g} s [{_text(phase.min_dur_s) or '-'}, "
                        f"{_text(phase.max_dur_s) or '-'}] {phase.state}"
                    )
        return found

    return list(_diff("inventory", facts(before), facts(after)))


def _audit_changes(before: SimulationAudit, after: SimulationAudit) -> list[Change]:
    def facts(audit: SimulationAudit) -> dict[str, object]:
        found: dict[str, object] = {
            "vehículos declarados": audit.expected_vehicles_total,
            "final de la simulación": audit.config.end_s,
            "semilla": audit.config.seed,
        }
        for route in audit.routes:
            found[f"ruta {route.id}"] = (
                f"{route.edge_count} aristas {route.first_edge}→{route.last_edge}"
            )
        for item in audit.demand:
            found[f"demanda {item.id}"] = (
                f"{item.kind} {item.type_id} {_text(item.rate_veh_h) or '-'} veh/h "
                f"de {_text(item.begin_s) or '-'} a {_text(item.end_s) or '-'} s"
            )
        for vtype in audit.vehicle_types:
            found[f"tipo {vtype.id}"] = f"{vtype.vclass} {sorted(vtype.attributes.items())}"
        return found

    return list(_diff("audit", facts(before), facts(after)))


def _run_changes(before: ReceptionRecord, after: ReceptionRecord) -> list[Change]:
    def facts(record: ReceptionRecord) -> dict[str, object]:
        found: dict[str, object] = {"estado": record.base_run.status}
        summary = record.base_run.summary
        if summary is not None:
            found.update({name: getattr(summary, name) for name in RUN_FIELDS})
        return found

    return list(_diff("run", facts(before), facts(after)))
