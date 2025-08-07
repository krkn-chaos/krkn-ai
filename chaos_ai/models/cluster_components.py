from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

class Namespace(BaseModel):
    name: str
    pods: List[str] = []

class Container(BaseModel):
    name: str

class Pod(BaseModel):
    name: str
    namespace: str
    labels: Dict[str, str] = {}
    containers: List[Container] = []

class ClusterComponents(BaseModel):
    namespaces: List[Namespace] = []
