"""Validated same-grid ablation output; areas are sampled approximations."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class RefinementLayer(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    stage:Literal['S0','S1','S2']
    geometry:dict
    area_m2:float=Field(ge=0)
    reduction_from_previous:float|None=None
    actual_points:int=Field(ge=0)
    passed_points:int=Field(ge=0)
    reliable_landmarks:int=Field(ge=0)
    reliable_relations:int=Field(ge=0)
    ranked:bool=False
    seconds:float=Field(ge=0)
    constraints:list[str]

class SpatialRefinementResult(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    layers:list[RefinementLayer]
    ranked_regions:list[dict]
    hypotheses:list[dict]
    geojson:dict
    grid_fingerprint:str
    elapsed_seconds:float=Field(ge=0)
    geometry_repairs:list[dict]=Field(default_factory=list)
    warnings:list[str]


class RelationObservationEvidence(BaseModel):
    """Independent evidence, absent in historical VLM outputs. Defaults never certify."""
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    identity_confirmed:bool=False
    full_outline_visible:bool=False
    source:str|None=None

    @model_validator(mode='after')
    def provenance_required(self):
        if (self.identity_confirmed or self.full_outline_visible) and not (self.source and self.source.strip()):
            raise ValueError('Independent confirmation requires a source')
        return self


class ReliabilityLayer(RefinementLayer):
    stage:Literal['S1-R','S2-R']
    reduction_from_s0:float|None=None
    relation_counts:dict[Literal['HARD','SOFT','UNKNOWN'],int]=Field(default_factory=dict)
    region_count:int=Field(default=0,ge=0)


class ReliableRefinementResult(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    version:Literal['stage5.3']='stage5.3'
    layers:list[RefinementLayer|ReliabilityLayer]
    ranked_regions:list[dict]
    hypotheses:list[dict]
    geojson:dict
    grid_fingerprint:str
    elapsed_seconds:float=Field(ge=0)
    geometry_repairs:list[dict]=Field(default_factory=list)
    warnings:list[str]
