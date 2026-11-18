"""Validated same-grid ablation output; areas are sampled approximations."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

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
