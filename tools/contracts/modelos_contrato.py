"""Contratos de referencia v1.0, no implementación del estimador.
Requiere pydantic>=2,<3. Reglas cruzadas adicionales en el TDD.
"""
from __future__ import annotations
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator
import math

class Base(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,strict=True)
class Artifact(Base):
    artifact_id:str
    path:str
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
class Range(Base):
    min:float=Field(ge=0)
    max:float=Field(ge=0)
    @model_validator(mode='after')
    def ordered(self):
        if self.min>self.max: raise ValueError('min > max')
        return self
class State(Base):
    tls_id:str
    state:str=Field(pattern=r'^[rRyYgGsuoO]+$')
class Slot(Base):
    id:str
    kind:Literal['variable','fixed']
    min_s:float=Field(gt=0)
    max_s:float=Field(gt=0)
    states:list[State]=Field(min_length=1)
    @model_validator(mode='after')
    def bounds(self):
        if self.min_s>self.max_s: raise ValueError('slot: min > max')
        if self.kind=='fixed' and self.min_s!=self.max_s: raise ValueError('fixed slot must have equal bounds')
        if len({x.tls_id for x in self.states})!=len(self.states): raise ValueError('duplicate TLS')
        return self
class Movement(Base):
    id:str
    approach_id:str
    incoming_lanes:list[str]=Field(min_length=1)
    outgoing_edges:list[str]=Field(min_length=1)
    tls_id:str
    link_indices:list[int]=Field(min_length=1)
    flow_domain_vph:Range
class GreenGroup(Base):
    id:str
    slot_ids:list[str]=Field(min_length=1)
    min_s:float=Field(ge=0)
    max_s:float=Field(gt=0)
    purpose:Literal['vehicle','pedestrian']
class Case(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    case_id:str
    case_version:str
    origin:Literal['synthetic','field']
    description:str
    representation_status:Literal['synthetic_fixture','unverified','calibrated','validated']
    network:Artifact|None
    tick_s:float=Field(gt=0)
    cycle_s:Range
    vehicle_classes:list[str]=Field(min_length=1)
    movements:list[Movement]=Field(min_length=1)
    slots:list[Slot]=Field(min_length=1)
    green_groups:list[GreenGroup]=Field(min_length=1)
    boundary_policy_id:str
    restrictions_evidence:list[str]
    @model_validator(mode='after')
    def consistency(self):
        for items in [self.vehicle_classes,[m.id for m in self.movements],[s.id for s in self.slots],[g.id for g in self.green_groups]]:
            if len(items)!=len(set(items)): raise ValueError('duplicate identifier')
        if not any(s.kind=='variable' for s in self.slots): raise ValueError('no variable slots')
        ids={s.id for s in self.slots}
        for s in self.slots:
            for v in [s.min_s,s.max_s]:
                if abs(v/self.tick_s-round(v/self.tick_s))>1e-8: raise ValueError('not aligned to tick')
        for g in self.green_groups:
            if not set(g.slot_ids)<=ids or len(g.slot_ids)!=len(set(g.slot_ids)): raise ValueError('invalid green group slots')
            if g.min_s>g.max_s: raise ValueError('invalid group bounds')
        if sum(s.min_s for s in self.slots)>self.cycle_s.max or sum(s.max_s for s in self.slots)<self.cycle_s.min: raise ValueError('infeasible cycle bounds')
        for m in self.movements:
            if any(i<0 for i in m.link_indices): raise ValueError('negative link index')
        return self
class DemandRow(Base):
    movement_id:str
    flow_vph:float=Field(ge=0)
    composition:dict[str,float]|None
    @model_validator(mode='after')
    def valid_composition(self):
        if self.flow_vph==0:
            if self.composition is not None: raise ValueError('zero flow requires null composition')
        elif not self.composition or any(not math.isfinite(v) or v<0 or v>1 for v in self.composition.values()) or abs(sum(self.composition.values())-1)>1e-8:
            raise ValueError('positive flow requires composition summing to 1')
        return self
class Request(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    request_id:str
    case_id:str
    case_version:str
    origin:Literal['synthetic','field']
    observation_start:datetime
    observation_end:datetime
    source_ids:list[str]=Field(min_length=1)
    demand:list[DemandRow]=Field(min_length=1)
    @model_validator(mode='after')
    def period(self):
        if self.observation_start.tzinfo is None or self.observation_end.tzinfo is None: raise ValueError('timezone required')
        if self.observation_end<=self.observation_start: raise ValueError('invalid period')
        if len({d.movement_id for d in self.demand})!=len(self.demand): raise ValueError('duplicate movement')
        return self
class Plan(Base):
    slot_durations_s:dict[str,float]
    cycle_s:float=Field(gt=0)
    greens_s:dict[str,float]
class Error(Base):
    code:str
    field:str|None
    message:str
    artifact_id:str|None=None
class Response(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    request_id:str
    case_id:str
    case_version:str
    model_id:str|None
    status:Literal['accepted','corrected','rejected','invalid_input','out_of_domain','failed']
    original_variable_durations_s:dict[str,float]|None
    plan:Plan|None
    errors:list[Error]
    duration_ms:dict[str,float]
    rules_version:str
    @model_validator(mode='after')
    def consistent(self):
        if (self.status in ['accepted','corrected'])!=(self.plan is not None): raise ValueError('plan/status mismatch')
        if self.status not in ['accepted','corrected'] and not self.errors: raise ValueError('reason required')
        if any(v<0 for v in self.duration_ms.values()): raise ValueError('negative duration')
        return self
class Scenario(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    scenario_id:str
    case_id:str
    case_version:str
    origin:Literal['synthetic','field_derived']
    group_id:str
    source_ids:list[str]
    request:Request
    boundary_policy_id:str
    warmup_s:float=Field(ge=0)
    measure_s:float=Field(gt=0)
    drain_max_s:float=Field(ge=0)
    demand_seed:int=Field(ge=0)
    demand_artifact:Artifact|None
    @model_validator(mode='after')
    def identity(self):
        if (self.case_id,self.case_version)!=(self.request.case_id,self.request.case_version): raise ValueError('case mismatch')
        return self
class Assignment(Base):
    scenario_id:str
    group_id:str
    partition:Literal['train','validation','test']
class Split(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    split_id:str
    policy:str
    seed:int=Field(ge=0)
    frozen:bool
    assignments:list[Assignment]=Field(min_length=1)
    @model_validator(mode='after')
    def disjoint(self):
        groups={};scenarios=set()
        for a in self.assignments:
            if a.scenario_id in scenarios: raise ValueError('duplicate scenario')
            scenarios.add(a.scenario_id)
            if a.group_id in groups and groups[a.group_id]!=a.partition: raise ValueError('group leakage')
            groups[a.group_id]=a.partition
        return self
class Seeds(Base):
    search:list[int]=Field(min_length=1)
    finalists:list[int]=Field(min_length=1)
    final:list[int]=Field(min_length=1)
    @model_validator(mode='after')
    def disjoint(self):
        allseeds=self.search+self.finalists+self.final
        if len(set(allseeds))!=len(allseeds) or any(s<0 for s in allseeds): raise ValueError('overlapping/invalid seeds')
        return self
class CalibrationCriterion(Base):
    variable:Literal['volume','queue','travel_time']
    metric:str
    unit:str
    scope:str
    maximum_error:float=Field(ge=0)
    pilot_evidence:str
class Protocol(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    protocol_id:str
    status:Literal['draft','frozen']
    purpose:Literal['synthetic_fixture','main_experiment']
    metric_definition:str
    cohort_policy:str
    censoring_policy:Literal['complete_cohort_or_no_label','approved_alternative']
    alternate_censoring_rule:str|None
    search_budget:int=Field(gt=0)
    sampling_attempt_limit:int=Field(gt=0)
    finalist_count:int=Field(gt=0)
    seeds:Seeds
    tie_epsilon_s:float=Field(ge=0)
    queue_speed_threshold_mps:float=Field(ge=0)
    confidence_level:float=Field(gt=0,lt=1)
    bootstrap_repetitions:int=Field(gt=0)
    acceptance_margin_s:float|None=Field(default=None,ge=0)
    count_error_tolerance:float|None=Field(default=None,ge=0)
    simulation_fit_tolerance:float|None=Field(default=None,ge=0)
    approval_reference:str|None
    zone_lane_ids:list[str]=Field(min_length=1)
    queue_sampling_s:float=Field(gt=0)
    stop_speed_threshold_mps:float=Field(ge=0)
    calibration_criteria:list[CalibrationCriterion]
    group_aggregation:Literal['equal_group_weight','declared_field_weights']
    group_weight_artifact:Artifact|None
    refit_policy:Literal['train_only','train_plus_validation_after_selection']
    numeric_abs_tolerance:float=Field(ge=0)
    @model_validator(mode='after')
    def gate(self):
        if self.censoring_policy=='approved_alternative' and not self.alternate_censoring_rule: raise ValueError('alternative rule required')
        if self.status=='frozen' and self.purpose=='main_experiment' and (not self.approval_reference or any(v is None for v in [self.acceptance_margin_s,self.count_error_tolerance,self.simulation_fit_tolerance])): raise ValueError('main protocol cannot freeze with unresolved criteria')
        if self.status=='frozen' and self.purpose=='main_experiment':
            variables={c.variable for c in self.calibration_criteria}
            if 'volume' not in variables or not variables.intersection({'queue','travel_time'}):
                raise ValueError('calibration needs volume and performance criteria')
        if self.group_aggregation=='declared_field_weights' and self.group_weight_artifact is None:
            raise ValueError('weights artifact required')
        return self
class Label(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    label_id:str
    scenario_id:str
    case_version:str
    status:Literal['reference','no_reference']
    plan:Plan|None
    search_run_id:str
    protocol_id:str
    candidate_count:int=Field(ge=0)
    simulation_count:int=Field(ge=0)
    evidence_status:Literal['fixture_only','evaluated']
    reason:str|None
    @model_validator(mode='after')
    def consistency(self):
        if (self.status=='reference')!=(self.plan is not None): raise ValueError('label status mismatch')
        if self.status=='no_reference' and not self.reason: raise ValueError('reason required')
        if self.evidence_status=='evaluated' and self.status=='reference' and (self.candidate_count<1 or self.simulation_count<1): raise ValueError('evaluated label requires evidence')
        return self
class ModelManifest(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    model_id:str
    status:Literal['draft','frozen']
    case_id:str
    case_version:str
    algorithm:Literal['median','xgboost_per_output']
    feature_order:list[str]=Field(min_length=1)
    variable_slot_order:list[str]=Field(min_length=1)
    rules_version:str
    split_id:str
    dataset_id:str
    training_run_id:str
    training_partitions:list[Literal['train','validation']]=Field(min_length=1)
    artifacts:list[Artifact]
    environment:dict[str,str]
    @model_validator(mode='after')
    def ready(self):
        if self.status=='frozen' and not self.artifacts: raise ValueError('frozen model needs artifacts')
        if len(set(self.feature_order))!=len(self.feature_order): raise ValueError('duplicate feature')
        return self
class RunManifest(Base):
    schema_version:Literal['1.0.0']='1.0.0'
    run_id:str
    kind:Literal['simulation','search','training','query','evaluation','export']
    status:Literal['queued','running','succeeded','failed','cancelled']
    created_at:datetime
    case_id:str
    case_version:str
    scenario_id:str|None
    seed:int|None=Field(default=None,ge=0)
    protocol_id:str|None
    command:list[str]
    environment:dict[str,str]
    inputs:list[Artifact]
    outputs:list[Artifact]
    exit_code:int|None
    error:Error|None
    retry_of:str|None
    @model_validator(mode='after')
    def terminal(self):
        if self.status=='succeeded' and (self.exit_code!=0 or not self.outputs): raise ValueError('success requires outputs and exit zero')
        if self.status=='failed' and self.error is None: raise ValueError('failure requires error')
        return self
MODELS={'case':Case,'request':Request,'response':Response,'scenario':Scenario,'split':Split,'protocol':Protocol,'label':Label,'model_manifest':ModelManifest,'run_manifest':RunManifest}

def validate_request_against_case(req:Request, case:Case):
    if (req.case_id,req.case_version)!=(case.case_id,case.case_version): raise ValueError('CASE_MISMATCH')
    if set(d.movement_id for d in req.demand)!=set(m.id for m in case.movements): raise ValueError('MISSING_OR_UNKNOWN_MOVEMENT')
    for d in req.demand:
        m=next(m for m in case.movements if m.id==d.movement_id)
        if not m.flow_domain_vph.min<=d.flow_vph<=m.flow_domain_vph.max: raise ValueError('OUT_OF_DOMAIN')
        if d.composition is not None and set(d.composition)!=set(case.vehicle_classes): raise ValueError('UNKNOWN_OR_MISSING_CLASS')

def validate_plan_against_case(plan:Plan,case:Case):
    ds=plan.slot_durations_s
    if set(ds)!={s.id for s in case.slots}: raise ValueError('slot mismatch')
    for s in case.slots:
        x=ds[s.id]
        if not s.min_s<=x<=s.max_s or abs(x/case.tick_s-round(x/case.tick_s))>1e-8: raise ValueError('slot bounds/tick')
    if abs(sum(ds.values())-plan.cycle_s)>1e-8 or not case.cycle_s.min<=plan.cycle_s<=case.cycle_s.max: raise ValueError('cycle mismatch')
    if set(plan.greens_s)!={g.id for g in case.green_groups}: raise ValueError('green group mismatch')
    for g in case.green_groups:
        x=sum(ds[s] for s in g.slot_ids)
        if abs(x-plan.greens_s[g.id])>1e-8 or not g.min_s<=x<=g.max_s: raise ValueError('green group mismatch/bounds')
