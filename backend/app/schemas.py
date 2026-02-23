from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InsightCreate(BaseModel):
    text: str = Field(min_length=5, max_length=320)
    user_id: UUID | None = None


class InsightNode(BaseModel):
    id: UUID
    text: str
    cluster_id: str
    stance_label: str
    type_label: str
    created_at: datetime


class EdgeOut(BaseModel):
    src: UUID
    dst: UUID
    weight: float


class ClusterOut(BaseModel):
    cluster_id: str
    title: str
    summary: str


class SubmissionResult(BaseModel):
    node: InsightNode
    cluster: ClusterOut
    supporters: list[InsightNode]
    challengers: list[InsightNode]
    subgraph: dict
    moderation_status: str
    guardrail: dict


class ChatRequest(BaseModel):
    mode: str
    seed_insight_id: UUID
    user_message: str
    conversation_state: list[dict] | None = None
    user_belief: str | None = None  # if absent, backend falls back to selected seed insight text
    counterparty_belief: str | None = None  # optional: real supporter/challenger text; if missing, agent infers (synthetic)


class ChatResponse(BaseModel):
    mode: str
    response: str
    conversation_state: list[dict]
    guardrail: dict


class ClusterInfo(BaseModel):
    title: str
    summary: str


class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    clusters: dict[str, ClusterInfo] = Field(default_factory=dict)
