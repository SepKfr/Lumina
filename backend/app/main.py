from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.models import Insight
from app.schemas import ChatRequest, ChatResponse, GraphResponse, InsightCreate, SubmissionResult
from app.services.chat_service import generate_chat_reply
from app.services.graph_service import get_graph
from app.services.insight_service import create_insight_pipeline
from app.settings import settings

app = FastAPI(title=settings.app_name)

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/insights", response_model=SubmissionResult)
def create_insight(payload: InsightCreate, db: Session = Depends(get_db)) -> SubmissionResult:
    try:
        insight, guardrail, supporters, challengers, cluster = create_insight_pipeline(db, payload.text, payload.user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    decision = guardrail.get("decision", "reject")
    if decision == "reject":
        raise HTTPException(status_code=400, detail={"decision": "reject", "guardrail": guardrail})
    if decision == "revise":
        raise HTTPException(status_code=422, detail={"decision": "revise", "guardrail": guardrail})

    db.commit()
    db.refresh(insight)

    node = {
        "id": insight.id,
        "text": insight.text,
        "cluster_id": insight.cluster_id,
        "stance_label": insight.stance_label,
        "type_label": insight.type_label,
        "created_at": insight.created_at,
    }

    minimal_graph = get_graph(db, insight.id, depth=1, budget=32)

    return SubmissionResult(
        node=node,
        cluster={
            "cluster_id": cluster.cluster_id,
            "title": cluster.title,
            "summary": cluster.summary,
        },
        supporters=[{k: s[k] for k in ("id", "text", "cluster_id", "stance_label", "type_label", "created_at")} for s in supporters],
        challengers=[{k: c[k] for k in ("id", "text", "cluster_id", "stance_label", "type_label", "created_at")} for c in challengers],
        subgraph=minimal_graph,
        moderation_status=insight.moderation_status,
        guardrail=guardrail,
    )


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
