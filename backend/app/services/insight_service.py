import re

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import Cluster, Edge, Insight
from app.services.clustering import assign_cluster
from app.services.guardrails import run_submission_guardrail
from app.services.llm_client import embed_text
from app.services.pre_embedding import classify_embedding_context
from app.services.stance import extract_stance
from app.services.utils import insight_text_key, is_opposing_stance, normalize_insight_text
from app.settings import settings


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in values) + "]"


def retrieve_neighbors(db: Session, embedding: list[float], limit: int = 20, exclude_id: str | None = None) -> list[dict]:
    sql = """
        SELECT id, text, cluster_id, stance_label, type_label, created_at,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM insights
    """
    params = {"embedding": _vector_literal(embedding), "limit": limit}
    if exclude_id:
        sql += " WHERE id::text != :exclude_id"
        params["exclude_id"] = exclude_id
    sql += " ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit"
    rows = db.execute(sql_text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def upsert_edges(db: Session, new_insight_id, new_cluster_id: str, neighbors: list[dict]) -> None:
    for n in neighbors:
        # Keep graph semantics aligned with cluster semantics.
        if n.get("cluster_id") != new_cluster_id:
            continue
        sim = float(n["similarity"])
        if sim < settings.edge_similarity_threshold:
            continue
        src = new_insight_id
        dst = n["id"]
        db.merge(Edge(src=src, dst=dst, weight=sim))
        db.merge(Edge(src=dst, dst=src, weight=sim))


def split_supporters_challengers(
    stance_label: str,
    cluster_id: str,
    seed_text: str,
    neighbors: list[dict],
) -> tuple[list[dict], list[dict]]:
    supporters_same_cluster, challengers_same_cluster = [], []

    for n in neighbors:
        n_stance = n.get("stance_label", "neutral")
        same_cluster = n.get("cluster_id") == cluster_id

        if not same_cluster:
            continue

        if n_stance == stance_label:
            supporters_same_cluster.append(n)
        elif is_opposing_stance(stance_label, n_stance):
            challengers_same_cluster.append(n)

    supporters_same_cluster.sort(key=lambda x: x["similarity"], reverse=True)
    challengers_same_cluster.sort(key=lambda x: x["similarity"], reverse=True)

    def key_for(node: dict) -> str:
        text_value = (node.get("text") or "").strip().lower()
        text_value = re.sub(r"\s+", " ", text_value)
        return text_value

    def dedupe(nodes: list[dict], blocked: set[str] | None = None) -> list[dict]:
        seen = set(blocked or set())
        out = []
        for node in nodes:
            key = key_for(node)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(node)
        return out

    seed_key = re.sub(r"\s+", " ", (seed_text or "").strip().lower())
    blocked_seed = {seed_key} if seed_key else set()

    supporters = dedupe(supporters_same_cluster, blocked=blocked_seed)
    supporter_keys = {key_for(s) for s in supporters}
    challengers = dedupe(challengers_same_cluster, blocked=supporter_keys | blocked_seed)

    return supporters[:6], challengers[:6]


def create_insight_pipeline(db: Session, text_input: str, user_id=None) -> tuple[Insight, dict, list[dict], list[dict], object]:
    insight_text = normalize_insight_text(text_input)
    if len(insight_text) < 8 or len(insight_text) > 320:
        raise ValueError("Insight must be between 8 and 320 characters.")

    normalized_key = insight_text_key(insight_text)
    dup_sql = """
        SELECT id
        FROM insights
        WHERE lower(regexp_replace(regexp_replace(text, '[.!?]+$', '', 'g'), '\s+', ' ', 'g')) = :key
        ORDER BY created_at ASC
        LIMIT 1
    """
    existing_id = db.execute(sql_text(dup_sql), {"key": normalized_key}).scalar_one_or_none()
    if existing_id:
        existing = db.query(Insight).filter(Insight.id == existing_id).one()
        neighbors = retrieve_neighbors(db, existing.embedding, limit=40, exclude_id=str(existing.id))
        supporters, challengers = split_supporters_challengers(
            existing.stance_label,
            existing.cluster_id,
            existing.text,
            neighbors,
        )
        cluster = db.query(Cluster).filter(Cluster.cluster_id == existing.cluster_id).one()
        return existing, {"decision": "accept", "duplicate": True}, supporters, challengers, cluster

    guardrail = run_submission_guardrail(insight_text)
    decision = guardrail.get("decision")
    if decision in {"reject", "revise"}:
        return None, guardrail, [], [], None

    embedding_context = classify_embedding_context(insight_text, guardrail.get("type_label", "other"))
    embedding_input = (
        f"topic_label: {embedding_context.get('topic_label', 'general')}\n"
        f"stance_hint: {embedding_context.get('stance_hint', 'neutral')}\n"
        f"type_label: {guardrail.get('type_label', 'other')}\n"
        f"canonical_claim: {embedding_context.get('canonical_claim', insight_text)}\n"
        f"insight: {insight_text}"
    )
    embedding = embed_text(embedding_input)
    cluster = assign_cluster(db, embedding)

    stance = extract_stance(insight_text, cluster.summary)
    guardrail_enriched = dict(guardrail)
    guardrail_enriched["embedding_context"] = embedding_context
    stance_label = stance.get("stance_label", "neutral")
    stance_hint = embedding_context.get("stance_hint")
    if stance_label not in {"pro", "con"} and stance_hint in {"pro", "con"}:
        # Use pre-embedding stance hint when extractor returns neutral/unclear.
        stance_label = stance_hint

    insight = Insight(
        user_id=user_id,
        text=insight_text,
        moderation_status="approved",
        type_label=guardrail.get("type_label", "other"),
        embedding=embedding,
        cluster_id=cluster.cluster_id,
        stance_label=stance_label,
        canonical_claim=stance.get("canonical_claim", insight_text),
        counterclaim=stance.get("counterclaim", ""),
        guardrail_json=guardrail_enriched,
    )
    db.add(insight)
    try:
        db.flush()
    except IntegrityError:
        # Another request inserted an equivalent normalized insight concurrently.
        db.rollback()
        existing_id = db.execute(sql_text(dup_sql), {"key": normalized_key}).scalar_one_or_none()
        if not existing_id:
            raise
        existing = db.query(Insight).filter(Insight.id == existing_id).one()
        neighbors = retrieve_neighbors(db, existing.embedding, limit=40, exclude_id=str(existing.id))
        supporters, challengers = split_supporters_challengers(
            existing.stance_label,
            existing.cluster_id,
            existing.text,
            neighbors,
        )
        cluster = db.query(Cluster).filter(Cluster.cluster_id == existing.cluster_id).one()
        return existing, {"decision": "accept", "duplicate": True}, supporters, challengers, cluster

    neighbors = retrieve_neighbors(db, embedding, limit=30, exclude_id=str(insight.id))
    upsert_edges(db, insight.id, insight.cluster_id, neighbors)
    supporters, challengers = split_supporters_challengers(
        insight.stance_label,
        insight.cluster_id,
        insight.text,
        neighbors,
    )

    return insight, guardrail, supporters, challengers, cluster
