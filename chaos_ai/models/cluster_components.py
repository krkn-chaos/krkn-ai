from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

class Container(BaseModel):
    name: str

class Pod(BaseModel):
    name: str
    labels: Dict[str, str] = {}
    containers: List[Container] = []

class Namespace(BaseModel):
    name: str
    pods: List[Pod] = []

class ClusterComponents(BaseModel):
    namespaces: List[Namespace] = []
