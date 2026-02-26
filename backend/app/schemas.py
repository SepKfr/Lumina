from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InsightCreate(BaseModel):
    text: str = Field(min_length=5, max_length=320)
    user_id: UUID | None = None
    metadata_json: dict | None = None


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
    user_emotion: str | None = None  # optional: from voice (e.g. angry, calm); agent can match or soften tone


class ChatResponse(BaseModel):
    mode: str
    response: str
    conversation_state: list[dict]
    guardrail: dict
    suggested_tone: str | None = None  # optional: for TTS (e.g. match_user_intensity, calm, assertive)


class ClusterInfo(BaseModel):
    title: str
    summary: str


class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    clusters: dict[str, ClusterInfo] = Field(default_factory=dict)


class IdeaNode(BaseModel):
    id: UUID
    text: str
    topic_id: UUID | None
    subtopic_id: UUID | None
    stance_label: str
    stance_confidence: float | None = None
    created_at: datetime
    metadata_json: dict = Field(default_factory=dict)


class IdeaSubmissionResult(BaseModel):
    node: IdeaNode
    topic: dict
    subtopic: dict


class TopicOut(BaseModel):
    id: UUID
    level: int
    name: str
    n_points: int
    parent_topic_id: UUID | None
    stance_centroids_json: dict = Field(default_factory=dict)


class TopicsResponse(BaseModel):
    topics: list[TopicOut]


class NeighborsResponse(BaseModel):
    id: UUID
    neighbors: list[dict]


class MapResponse(BaseModel):
    topics: list[dict]
    topic_edges: list[dict]
    ideas: list[dict]
    edges: list[dict]


class RelationBucketsResponse(BaseModel):
    id: UUID
    supportive: list[dict]
    opposing: list[dict]
    neutral: list[dict] = Field(default_factory=list)


class TranscribeResponse(BaseModel):
    text: str
    emotion: str | None = None


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    voice_profile: str = Field(default="support", pattern="^(support|debate)$")
