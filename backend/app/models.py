from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

ActivityKind = Literal['start', 'http', 'file', 'transform', 'log', 'kafka', 'java', 'end']

class Activity(BaseModel):
    id: str
    type: ActivityKind
    name: str
    position: dict[str, float] = Field(default_factory=lambda: {'x': 100, 'y': 100})
    config: dict[str, Any] = Field(default_factory=dict)

class Transition(BaseModel):
    id: str
    source: str
    target: str
    label: str = ''

class ProcessDefinition(BaseModel):
    id: str = 'main'
    name: str = 'Main Process'
    activities: list[Activity] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)

class Project(BaseModel):
    id: str
    name: str
    description: str = ''
    process: ProcessDefinition

class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)

class RunResult(BaseModel):
    run_id: str
    status: Literal['completed', 'failed']
    output: dict[str, Any]
    logs: list[dict[str, Any]]
