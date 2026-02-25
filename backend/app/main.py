import os
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.models import Insight
from app.schemas import (
    ChatRequest,
    ChatResponse,
    GraphResponse,
    IdeaSubmissionResult,
    InsightCreate,
    MapResponse,
    NeighborsResponse,
    RelationBucketsResponse,
    SubmissionResult,
    TopicsResponse,
)
from app.services.chat_service import generate_chat_reply
from app.services.graph_service import get_graph
from app.services.topic_layer import (
    build_map,
    get_neighbors,
    ingest_idea,
    list_topics,
    retrieve_nearby,
    retrieve_opposing,
    retrieve_relation_buckets,
    retrieve_supportive,
    run_periodic_recluster,
)
from app.settings import settings

root_path = os.getenv("APP_ROOT_PATH", "")
app = FastAPI(title=settings.app_name, root_path=root_path)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    # Enforce duplicate protection at the database level as well.
    with engine.begin() as conn:
        conn.execute(
            sql_text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS insights_text_norm_uidx
                ON insights ((lower(regexp_replace(regexp_replace(text, '[.!?]+$', '', 'g'), '\\s+', ' ', 'g'))))
                """
            )
        )
        conn.execute(sql_text("ALTER TABLE insights ADD COLUMN IF NOT EXISTS topic_id UUID"))
        conn.execute(sql_text("ALTER TABLE insights ADD COLUMN IF NOT EXISTS subtopic_id UUID"))
        conn.execute(sql_text("ALTER TABLE insights ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb"))
        conn.execute(sql_text("ALTER TABLE insights ADD COLUMN IF NOT EXISTS stance_confidence DOUBLE PRECISION"))
        conn.execute(sql_text("ALTER TABLE edges ADD COLUMN IF NOT EXISTS edge_type VARCHAR(40) DEFAULT 'idea_similarity'"))
        conn.execute(
            sql_text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'insights_topic_id_fkey'
                    ) THEN
                        ALTER TABLE insights
                        ADD CONSTRAINT insights_topic_id_fkey
                        FOREIGN KEY (topic_id) REFERENCES topics(id);
                    END IF;
                END $$;
                """
            )
        )
        conn.execute(
            sql_text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'insights_subtopic_id_fkey'
                    ) THEN
                        ALTER TABLE insights
                        ADD CONSTRAINT insights_subtopic_id_fkey
                        FOREIGN KEY (subtopic_id) REFERENCES topics(id);
                    END IF;
                END $$;
                """
            )
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/insights", response_model=SubmissionResult)
def create_insight(payload: InsightCreate, db: Session = Depends(get_db)) -> SubmissionResult:
    """Use topic_layer (ingest_idea) for fast ingestion: embed + one topic LLM, no stance LLM. Same response shape as before."""
    try:
        idea, topic, subtopic = ingest_idea(
            db,
            payload.text,
            payload.user_id,
            metadata_json=payload.metadata_json,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    db.commit()
    db.refresh(idea)

    node = {
        "id": idea.id,
        "text": idea.text,
        "cluster_id": idea.cluster_id,
        "stance_label": idea.stance_label,
        "type_label": idea.type_label,
        "created_at": idea.created_at,
    }

    cluster_out = {
        "cluster_id": idea.cluster_id,
        "title": subtopic.name or topic.name,
        "summary": subtopic.name or topic.name,
    }

    support_rows = retrieve_supportive(db, idea.id, top_k=2)
    oppose_rows = retrieve_opposing(db, idea.id, top_k=2)

    def to_node_like(row: dict) -> dict:
        return {
            "id": row["id"],
            "text": row.get("text", ""),
            "cluster_id": str(row.get("subtopic_id") or row.get("topic_id") or ""),
            "stance_label": row.get("stance_label", "neutral"),
            "type_label": "other",
            "created_at": row.get("created_at"),
        }

    supporters = [to_node_like(r) for r in support_rows]
    challengers = [to_node_like(r) for r in oppose_rows]
    for n in supporters + challengers:
        if n.get("created_at") is None:
            n["created_at"] = idea.created_at

    minimal_graph = get_graph(db, idea.id, depth=1, budget=32)

    return SubmissionResult(
        node=node,
        cluster=cluster_out,
        supporters=supporters,
        challengers=challengers,
        subgraph=minimal_graph,
        moderation_status=idea.moderation_status,
        guardrail={"decision": "accept", "path": "topic_layer"},
    )


@app.post("/ideas", response_model=IdeaSubmissionResult)
def create_idea(payload: InsightCreate, db: Session = Depends(get_db)) -> IdeaSubmissionResult:
    try:
        idea, topic, subtopic = ingest_idea(
            db,
            payload.text,
            payload.user_id,
            metadata_json=payload.metadata_json,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    db.commit()
    db.refresh(idea)
    return IdeaSubmissionResult(
        node={
            "id": idea.id,
            "text": idea.text,
            "topic_id": idea.topic_id,
            "subtopic_id": idea.subtopic_id,
            "stance_label": idea.stance_label,
            "stance_confidence": getattr(idea, "stance_confidence", None),
            "created_at": idea.created_at,
            "metadata_json": idea.metadata_json or {},
        },
        topic={
            "id": topic.id,
            "level": topic.level,
            "name": topic.name,
            "n_points": topic.n_points,
            "parent_topic_id": topic.parent_topic_id,
            "stance_centroids_json": topic.stance_centroids_json or {},
        },
        subtopic={
            "id": subtopic.id,
            "level": subtopic.level,
            "name": subtopic.name,
            "n_points": subtopic.n_points,
            "parent_topic_id": subtopic.parent_topic_id,
            "stance_centroids_json": subtopic.stance_centroids_json or {},
        },
    )


@app.get("/neighbors", response_model=NeighborsResponse)
def neighbors(
    id: str = Query(..., description="Idea UUID"),
    top_k: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> NeighborsResponse:
    try:
        parsed = UUID(id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid idea UUID") from exc
    rows = get_neighbors(db, parsed, top_k=top_k)
    return NeighborsResponse(id=parsed, neighbors=rows)


@app.get("/supportive", response_model=NeighborsResponse)
def supportive(
    id: str = Query(..., description="Idea UUID"),
    top_k: int = Query(default=2, ge=1, le=100),
    db: Session = Depends(get_db),
) -> NeighborsResponse:
    try:
        parsed = UUID(id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid idea UUID") from exc
    rows = retrieve_supportive(db, parsed, top_k=top_k)
    return NeighborsResponse(id=parsed, neighbors=rows)


@app.get("/opposing", response_model=NeighborsResponse)
def opposing(
    id: str = Query(..., description="Idea UUID"),
    top_k: int = Query(default=2, ge=1, le=100),
    alpha: float = Query(default=settings.opposing_alpha, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> NeighborsResponse:
    try:
        parsed = UUID(id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid idea UUID") from exc
    rows = retrieve_opposing(db, parsed, top_k=top_k, alpha=alpha)
    return NeighborsResponse(id=parsed, neighbors=rows)


@app.get("/nearby", response_model=NeighborsResponse)
def nearby(
    id: str = Query(..., description="Idea UUID"),
    top_k: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> NeighborsResponse:
    try:
        parsed = UUID(id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid idea UUID") from exc
    rows = retrieve_nearby(db, parsed, top_k=top_k)
    return NeighborsResponse(id=parsed, neighbors=rows)


@app.get("/relations", response_model=RelationBucketsResponse)
def relations(
    id: str = Query(..., description="Idea UUID"),
    top_k: int = Query(default=2, ge=1, le=10),
    candidate_pool: int = Query(default=24, ge=4, le=120),
    db: Session = Depends(get_db),
) -> RelationBucketsResponse:
    try:
        parsed = UUID(id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid idea UUID") from exc
    data = retrieve_relation_buckets(db, parsed, top_k=top_k, candidate_pool=candidate_pool)
    db.commit()
    return RelationBucketsResponse(id=parsed, **data)


@app.get("/topics", response_model=TopicsResponse)
def topics(db: Session = Depends(get_db)) -> TopicsResponse:
    return TopicsResponse(topics=list_topics(db))


@app.get("/map", response_model=MapResponse)
def map_payload(
    max_idea_edges: int = Query(default=2500, ge=100, le=10000),
    db: Session = Depends(get_db),
) -> MapResponse:
    return MapResponse(**build_map(db, max_idea_edges=max_idea_edges))


@app.post("/jobs/recluster")
def recluster_topics(db: Session = Depends(get_db)) -> dict:
    result = run_periodic_recluster(db)
    db.commit()
    return result


@app.get("/v1/graph", response_model=GraphResponse)
def graph(
    node_id: str | None = Query(default=None),
    depth: int = Query(default=2, ge=1, le=3),
    budget: int = Query(default=80, ge=10, le=500),
    db: Session = Depends(get_db),
) -> GraphResponse:
    parsed_node_id = None
    if node_id:
        try:
            parsed_node_id = UUID(node_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid node_id UUID") from exc
    try:
        graph_data = get_graph(db, parsed_node_id, depth=depth, budget=budget)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GraphResponse(
        nodes=graph_data["nodes"],
        edges=graph_data["edges"],
        clusters=graph_data.get("clusters", {}),
    )


@app.post("/v1/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    if payload.mode not in {"support", "debate"}:
        raise HTTPException(status_code=400, detail="mode must be support or debate")

    seed = db.query(Insight).filter(Insight.id == payload.seed_insight_id).one_or_none()
    if not seed:
        raise HTTPException(status_code=404, detail="seed insight not found")

    try:
        reply, guardrail = generate_chat_reply(
            payload.mode,
            seed,
            payload.user_message,
            payload.conversation_state,
            user_belief=payload.user_belief,
            counterparty_belief=payload.counterparty_belief,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state = payload.conversation_state or []
    state = state + [{"role": "user", "content": payload.user_message}, {"role": "agent", "content": reply}]
    return ChatResponse(mode=payload.mode, response=reply, conversation_state=state, guardrail=guardrail)
