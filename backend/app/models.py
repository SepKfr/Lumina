import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.settings import settings


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    moderation_status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False)
    type_label: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    stance_label: Mapped[str] = mapped_column(String(20), default="neutral", nullable=False)
    canonical_claim: Mapped[str] = mapped_column(Text, nullable=False)
    counterclaim: Mapped[str] = mapped_column(Text, nullable=False)
    guardrail_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saves: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reports: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (PrimaryKeyConstraint("src", "dst"),)

    src: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("insights.id"), nullable=False)
    dst: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("insights.id"), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Cluster(Base):
    __tablename__ = "clusters"

    cluster_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    centroid: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    insight_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("insights.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
