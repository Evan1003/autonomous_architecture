"""Data models for ArchFlow architectures (web / mobile app oriented)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

NODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$")

NodeType = Literal[
    "page",  # web page / app screen
    "component",  # reusable UI component
    "state",  # client-side state store (redux, pinia, provider...)
    "api",  # HTTP / RPC endpoint
    "service",  # business logic / backend module
    "data",  # data model / table / collection
    "external",  # third-party service (payment, OAuth, push...)
    "job",  # background job / scheduler / queue worker
    "infra",  # deployment, config, CI
]

Layer = Literal["frontend", "backend", "data", "external", "infra"]

DEFAULT_LAYER: dict[str, str] = {
    "page": "frontend",
    "component": "frontend",
    "state": "frontend",
    "api": "backend",
    "service": "backend",
    "job": "backend",
    "data": "data",
    "external": "external",
    "infra": "infra",
}

EdgeKind = Literal["calls", "navigates", "reads", "writes", "uses", "triggers"]


class Decision(BaseModel):
    question: str
    answer: str
    source: str = Field(default="discussion", description="e.g. 'Q3' (questionnaire) or 'discussion'")


class TestCase(BaseModel):
    __test__ = False  # not a pytest class

    id: str = Field(description="Unique test id, e.g. 'T-auth.login-1'")
    description: str = Field(description="What is verified, in Given/When/Then or plain words")
    kind: Literal["unit", "integration", "e2e"] = "unit"


class Node(BaseModel):
    id: str = Field(description="Stable id, lowercase, e.g. 'fe.login' or 'api.auth.login'")
    title: str
    type: NodeType
    layer: Layer | None = Field(default=None, description="Defaults from type if omitted")
    description: str = ""
    acceptance: list[str] = Field(
        default_factory=list,
        description="User-visible acceptance criteria; become CHECKLIST.md items",
    )
    decisions: list[Decision] = Field(default_factory=list)
    tests: list[TestCase] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not NODE_ID_RE.match(v):
            raise ValueError(
                f"invalid node id '{v}': use lowercase letters, digits, '.', '_' or '-'"
            )
        return v

    @model_validator(mode="after")
    def _fill_layer(self) -> "Node":
        if self.layer is None:
            self.layer = DEFAULT_LAYER[self.type]  # type: ignore[assignment]
        return self


class Edge(BaseModel):
    source: str = Field(description="Node id that depends on / calls / navigates from")
    target: str = Field(description="Node id that is used / called / navigated to")
    kind: EdgeKind = "uses"
    label: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.source, self.target, self.kind)


class Architecture(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "Architecture":
        ids = [n.id for n in self.nodes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate node ids: {sorted(dupes)}")
        idset = set(ids)
        for e in self.edges:
            missing = [x for x in (e.source, e.target) if x not in idset]
            if missing:
                raise ValueError(f"edge {e.source}->{e.target} references unknown node(s): {missing}")
        seen = set()
        for e in self.edges:
            if e.key() in seen:
                raise ValueError(f"duplicate edge {e.source}->{e.target} ({e.kind})")
            seen.add(e.key())
        test_ids = [t.id for n in self.nodes for t in n.tests]
        tdupes = {t for t in test_ids if test_ids.count(t) > 1}
        if tdupes:
            raise ValueError(f"duplicate test ids: {sorted(tdupes)}")
        return self

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)


class QuestionOption(BaseModel):
    key: str = Field(description="Short key such as 'A', 'B'")
    label: str
    detail: str = Field(default="", description="Pros/cons or explanation")


class Question(BaseModel):
    id: str = Field(description="e.g. 'Q1'")
    question: str
    type: Literal["single", "multi", "text"] = "single"
    options: list[QuestionOption] = Field(default_factory=list)
    why: str = Field(default="", description="Why the AI needs this answer")
    node_ids: list[str] = Field(default_factory=list, description="Related architecture nodes")
    recommended: str | None = Field(default=None, description="Option key the AI recommends")
    allow_other: bool = True

    @model_validator(mode="after")
    def _check(self) -> "Question":
        if self.type in ("single", "multi") and not self.options:
            raise ValueError(f"{self.id}: '{self.type}' question needs options")
        keys = [o.key for o in self.options]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{self.id}: duplicate option keys")
        if self.recommended and self.recommended not in keys:
            raise ValueError(f"{self.id}: recommended '{self.recommended}' is not an option key")
        return self


class EdgeRef(BaseModel):
    source: str
    target: str
    kind: EdgeKind | None = Field(default=None, description="If omitted, all edges source->target match")


class ArchPatch(BaseModel):
    """Partial change to an architecture."""

    upsert_nodes: list[Node] = Field(default_factory=list, description="Add or fully replace nodes by id")
    remove_nodes: list[str] = Field(default_factory=list, description="Node ids to delete (their edges go too)")
    add_edges: list[Edge] = Field(default_factory=list)
    remove_edges: list[EdgeRef] = Field(default_factory=list)
