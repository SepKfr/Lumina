import math
import uuid
from datetime import datetime

import numpy as np
from sqlalchemy import func, text as sql_text
from sqlalchemy.orm import Session

from app.models import Edge, IdeaRelation, Insight, Topic
from app.services.llm_client import chat_json
from app.services.llm_client import embed_text
from app.services.utils import insight_text_key, normalize_insight_text
from app.settings import settings

STANCE_LABELS = ("pro", "neutral", "con")


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in values) + "]"


def _running_mean(old: list[float], old_n: int, new_vec: list[float]) -> list[float]:
    ov = np.array(old, dtype=np.float32)
    nv = np.array(new_vec, dtype=np.float32)
    updated = (ov * old_n + nv) / max(old_n + 1, 1)
    return updated.tolist()


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _normalize_stance_label(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"con", "contra", "against", "opposed"}:
        return "con"
    if raw in {"pro", "support", "supportive", "in favor"}:
        return "pro"
    return "neutral"


def _nearest_topic(
    db: Session, embedding: list[float], level: int, parent_topic_id: uuid.UUID | None = None
) -> tuple[Topic | None, float]:
    sql = """
        SELECT id, 1 - (centroid_embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM topics
        WHERE level = :level
    """
    params = {"embedding": _vector_literal(embedding), "level": level}
    if parent_topic_id is None:
        sql += " AND parent_topic_id IS NULL "
    else:
        sql += " AND parent_topic_id = :parent_topic_id "
        params["parent_topic_id"] = parent_topic_id
    sql += " ORDER BY centroid_embedding <=> CAST(:embedding AS vector) ASC LIMIT 1"
    row = db.execute(sql_text(sql), params).mappings().first()
    if not row:
        return None, 0.0
    topic = db.query(Topic).filter(Topic.id == row["id"]).one()
    return topic, float(row["similarity"])


def _nearest_topics(
    db: Session, embedding: list[float], level: int, parent_topic_id: uuid.UUID | None = None, limit: int = 6
) -> list[dict]:
    sql = """
        SELECT id, name, 1 - (centroid_embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM topics
        WHERE level = :level
    """
    params = {"embedding": _vector_literal(embedding), "level": level, "limit": limit}
    if parent_topic_id is None:
        sql += " AND parent_topic_id IS NULL "
    else:
        sql += " AND parent_topic_id = :parent_topic_id "
        params["parent_topic_id"] = parent_topic_id
    sql += " ORDER BY centroid_embedding <=> CAST(:embedding AS vector) ASC LIMIT :limit"
    rows = db.execute(sql_text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _llm_select_parent_topic(text_value: str, topic_label: str, candidates: list[dict]) -> str:
    if not candidates:
        return "NEW"
    system_prompt = (
        "You are a strict topic router. Choose one existing topic name if it is clearly the same underlying issue. "
        "Otherwise return NEW. Output JSON only with keys: selected_topic_name, confidence."
    )
    lines = [f"- {c['name']} (sim={float(c['similarity']):.3f})" for c in candidates]
    user_prompt = (
        f"Idea: {text_value}\n"
        f"Suggested topic_label: {topic_label}\n"
        "Candidate existing topics:\n"
        + "\n".join(lines)
        + "\n\nReturn selected_topic_name as exact candidate name or NEW."
    )
    result = chat_json(system_prompt, user_prompt)
    selected = str(result.get("selected_topic_name", "NEW")).strip()
    confidence = float(result.get("confidence", 0.0) or 0.0)
    if confidence < 0.45:
        return "NEW"
    names = {c["name"] for c in candidates}
    if selected in names:
        return selected
    return "NEW"


def _topic_by_name(db: Session, level: int, topic_name: str, parent_topic_id: uuid.UUID | None = None) -> Topic | None:
    query = db.query(Topic).filter(Topic.level == level, func.lower(Topic.name) == topic_name.lower())
    if parent_topic_id is None:
        query = query.filter(Topic.parent_topic_id.is_(None))
    else:
        query = query.filter(Topic.parent_topic_id == parent_topic_id)
    return query.first()


def _classify_topic_hierarchy(
    text_value: str, topic_label: str = "", canonical_claim: str = ""
) -> dict:
    from pathlib import Path
    here = Path(__file__).resolve()
    for root in [here.parents[2], here.parents[3]]:
        prompt_path = root / "clustering" / "topic_extraction.txt"
        if prompt_path.exists():
            break
    else:
        prompt_path = Path("clustering/topic_extraction.txt")
    system_prompt = prompt_path.read_text()
    user_prompt = f"""
        Idea: {text_value}

        Instructions:
        - Reuse stable level2/level3 names.
        - Do NOT include sentiment in topic names.
        - Same topic even if stance differs.
        - Choose level1 from allowed list.

        Return JSON only.
        """
    if topic_label or canonical_claim:
        user_prompt += f"\nSuggested topic_label: {topic_label}\nCanonical claim: {canonical_claim}\n"
    result = chat_json(system_prompt, user_prompt)
    level1 = str(result.get("level1", topic_label) or topic_label).strip() or "general"
    level2 = str(result.get("level2", topic_label) or topic_label).strip() or level1
    level3 = str(result.get("level3", canonical_claim) or canonical_claim).strip() or level2
    return {"level1": level1[:80], "level2": level2[:80], "level3": level3[:120]}


def _create_topic(
    db: Session, level: int, name: str, embedding: list[float], parent_topic_id: uuid.UUID | None
) -> Topic:
    topic = Topic(
        level=level,
        name=name[:200],
        centroid_embedding=embedding,
        n_points=1,
        parent_topic_id=parent_topic_id,
        stance_centroids_json={},
    )
    db.add(topic)
    db.flush()
    return topic


def _upsert_topic_level(
    db: Session,
    embedding: list[float],
    level: int,
    name: str,
    parent_topic_id: uuid.UUID | None,
    threshold: float,
) -> Topic:
    by_name = _topic_by_name(db, level=level, topic_name=name, parent_topic_id=parent_topic_id)
    if by_name is not None:
        _update_topic_centroid(by_name, embedding)
        return by_name

    nearest, similarity = _nearest_topic(db, embedding, level=level, parent_topic_id=parent_topic_id)
    if nearest is not None and similarity >= threshold:
        _update_topic_centroid(nearest, embedding)
        return nearest
    return _create_topic(db, level=level, name=name, embedding=embedding, parent_topic_id=parent_topic_id)


def _get_stance_bucket(topic: Topic, stance_label: str) -> dict:
    stance_map = dict(topic.stance_centroids_json or {})
    if stance_label in stance_map:
        return dict(stance_map[stance_label] or {})
    if stance_label == "con" and "contra" in stance_map:
        return dict(stance_map["contra"] or {})
    return {}


def _get_stance_centroid(topic: Topic, stance_label: str) -> list[float] | None:
    bucket = _get_stance_bucket(topic, stance_label)
    centroid = bucket.get("centroid")
    if isinstance(centroid, list) and centroid:
        return centroid
    return None


def _update_topic_centroid(topic: Topic, embedding: list[float]) -> None:
    topic.centroid_embedding = _running_mean(topic.centroid_embedding, topic.n_points, embedding)
    topic.n_points += 1
    topic.updated_at = datetime.utcnow()


def _update_stance_centroid(topic: Topic, embedding: list[float], stance_label: str) -> None:
    stance_map = dict(topic.stance_centroids_json or {})
    stance_bucket = _get_stance_bucket(topic, stance_label)
    old_n = int(stance_bucket.get("n_points", 0))
    old_centroid = stance_bucket.get("centroid")
    if old_n <= 0 or not isinstance(old_centroid, list):
        stance_bucket = {"n_points": 1, "centroid": embedding}
    else:
        stance_bucket = {
            "n_points": old_n + 1,
            "centroid": _running_mean(old_centroid, old_n, embedding),
        }
    stance_map[stance_label] = stance_bucket
    if stance_label == "con" and "contra" in stance_map:
        del stance_map["contra"]
    topic.stance_centroids_json = stance_map
    topic.updated_at = datetime.utcnow()


def _assign_stance(
    embedding: list[float],
    topic: Topic,
    parent_topic: Topic | None,
    llm_stance_hint: str | None,
) -> tuple[str, float]:
    pro_centroid = _get_stance_centroid(topic, "pro") or (
        _get_stance_centroid(parent_topic, "pro") if parent_topic else None
    )
    con_centroid = _get_stance_centroid(topic, "con") or (
        _get_stance_centroid(parent_topic, "con") if parent_topic else None
    )
    if pro_centroid is not None and con_centroid is not None:
        p = _cosine(embedding, pro_centroid)
        c = _cosine(embedding, con_centroid)
        stance_score = p - c
        if abs(stance_score) < settings.stance_confidence_margin:
            return "neutral", stance_score
        return ("pro", stance_score) if stance_score > 0 else ("con", stance_score)
    # Bootstrap stance from lightweight LLM hint when centroids are sparse (cold start).
    return _normalize_stance_label(llm_stance_hint), 0.0


def _nearest_ideas_in_subtree(
    db: Session,
    embedding: list[float],
    root_topic_id: uuid.UUID,
    exclude_id: uuid.UUID,
    limit: int,
) -> list[dict]:
    return _nearest_ideas_in_topics(
        db=db,
        embedding=embedding,
        topic_ids=[root_topic_id],
        exclude_id=exclude_id,
        limit=limit,
    )


def _nearest_ideas_in_topics(
    db: Session,
    embedding: list[float],
    topic_ids: list[uuid.UUID],
    exclude_id: uuid.UUID,
    limit: int,
) -> list[dict]:
    if not topic_ids:
        return []
    sql = """
        SELECT id, text, topic_id, subtopic_id, stance_label, embedding, metadata_json, created_at,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM insights
        WHERE topic_id = ANY(:topic_ids) AND id != :exclude_id
        ORDER BY embedding <=> CAST(:embedding AS vector) ASC
        LIMIT :limit
    """
    rows = db.execute(
        sql_text(sql),
        {
            "embedding": _vector_literal(embedding),
            "topic_ids": topic_ids,
            "exclude_id": exclude_id,
            "limit": limit,
        },
    ).mappings()
    return [dict(r) for r in rows]


def _nearest_ideas_same_subtree(
    db: Session,
    embedding: list[float],
    subtopic_id: uuid.UUID,
    exclude_id: uuid.UUID,
    limit: int,
    stance_label: str | None = None,
) -> list[dict]:
    """Ideas in same topic subtree (same level1/2/3), optionally same stance. Returns rows with embedding."""
    sql = """
        SELECT id, text, topic_id, subtopic_id, stance_label, embedding, metadata_json, created_at,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM insights
        WHERE subtopic_id = :subtopic_id AND id != :exclude_id
    """
    params: dict = {
        "embedding": _vector_literal(embedding),
        "subtopic_id": subtopic_id,
        "exclude_id": exclude_id,
        "limit": limit,
    }
    if stance_label is not None:
        sql += " AND stance_label = :stance_label "
        params["stance_label"] = stance_label
    sql += " ORDER BY embedding <=> CAST(:embedding AS vector) ASC LIMIT :limit"
    rows = db.execute(sql_text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _nearest_ideas_same_level2(
    db: Session,
    embedding: list[float],
    level2_topic_id: uuid.UUID,
    exclude_id: uuid.UUID,
    limit: int,
    stance_label: str | None = None,
) -> list[dict]:
    """Ideas in same level2 topic (siblings of our subtopic). Returns rows with embedding."""
    sql = """
        SELECT i.id, i.text, i.topic_id, i.subtopic_id, i.stance_label, i.embedding, i.metadata_json, i.created_at,
               1 - (i.embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM insights i
        JOIN topics t ON t.id = i.subtopic_id AND t.parent_topic_id = :level2_id
        WHERE i.id != :exclude_id
    """
    params: dict = {
        "embedding": _vector_literal(embedding),
        "level2_id": level2_topic_id,
        "exclude_id": exclude_id,
        "limit": limit,
    }
    if stance_label is not None:
        sql += " AND i.stance_label = :stance_label "
        params["stance_label"] = stance_label
    sql += " ORDER BY i.embedding <=> CAST(:embedding AS vector) ASC LIMIT :limit"
    rows = db.execute(sql_text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _nearest_ideas_same_level1(
    db: Session,
    embedding: list[float],
    topic_id: uuid.UUID,
    exclude_id: uuid.UUID,
    limit: int,
    stance_label: str | None = None,
) -> list[dict]:
    """Ideas in same level1 topic. Returns rows with embedding."""
    sql = """
        SELECT id, text, topic_id, subtopic_id, stance_label, embedding, metadata_json, created_at,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM insights
        WHERE topic_id = :topic_id AND id != :exclude_id
    """
    params: dict = {
        "embedding": _vector_literal(embedding),
        "topic_id": topic_id,
        "exclude_id": exclude_id,
        "limit": limit,
    }
    if stance_label is not None:
        sql += " AND stance_label = :stance_label "
        params["stance_label"] = stance_label
    sql += " ORDER BY embedding <=> CAST(:embedding AS vector) ASC LIMIT :limit"
    rows = db.execute(sql_text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _merge_candidates_by_similarity(
    scopes: list[list[dict]], exclude_ids: set[uuid.UUID], top_k: int
) -> list[dict]:
    """Merge scope results in order, dedupe by id, sort by similarity, return top_k."""
    merged: list[dict] = []
    seen: set[uuid.UUID] = set(exclude_ids)
    for scope_rows in scopes:
        for row in scope_rows:
            rid = row["id"]
            if rid in seen:
                continue
            seen.add(rid)
            merged.append(row)
    merged.sort(key=lambda r: float(r.get("similarity", 0.0)), reverse=True)
    return merged[:top_k]


def _merge_candidates_hierarchical(
    scopes: list[list[dict]], exclude_ids: set[uuid.UUID], top_k: int
) -> list[dict]:
    """Leaves-first: use level3 (first scope) only; only if not enough, add level2 then level1. Within combined set sort by similarity."""
    merged: list[dict] = []
    seen: set[uuid.UUID] = set(exclude_ids)
    for scope_rows in scopes:
        for row in scope_rows:
            rid = row["id"]
            if rid in seen:
                continue
            seen.add(rid)
            merged.append(row)
        merged.sort(key=lambda r: float(r.get("similarity", 0.0)), reverse=True)
        if len(merged) >= top_k:
            return merged[:top_k]
    return merged[:top_k]


def _nearest_ideas_with_filters(
    db: Session,
    embedding: list[float],
    exclude_id: uuid.UUID,
    limit: int,
    topic_ids: list[uuid.UUID] | None = None,
    mid_topic_id: str | None = None,
    subtopic_id: uuid.UUID | None = None,
) -> list[dict]:
    sql = """
        SELECT id, text, topic_id, subtopic_id, stance_label, embedding, metadata_json, created_at,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM insights
        WHERE id != :exclude_id
    """
    params: dict = {
        "embedding": _vector_literal(embedding),
        "exclude_id": exclude_id,
        "limit": limit,
    }
    if topic_ids:
        sql += " AND topic_id = ANY(:topic_ids) "
        params["topic_ids"] = topic_ids
    if mid_topic_id:
        sql += " AND metadata_json->>'mid_topic_id' = :mid_topic_id "
        params["mid_topic_id"] = mid_topic_id
    if subtopic_id:
        sql += " AND subtopic_id = :subtopic_id "
        params["subtopic_id"] = subtopic_id
    sql += " ORDER BY embedding <=> CAST(:embedding AS vector) ASC LIMIT :limit"
    rows = db.execute(sql_text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _related_topic_ids(db: Session, seed_topic_id: uuid.UUID, seed_embedding: list[float]) -> list[uuid.UUID]:
    sql = """
        SELECT id, 1 - (centroid_embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM topics
        WHERE level = 1
        ORDER BY centroid_embedding <=> CAST(:embedding AS vector) ASC
        LIMIT 8
    """
    rows = db.execute(sql_text(sql), {"embedding": _vector_literal(seed_embedding)}).mappings().all()
    out: list[uuid.UUID] = []
    for row in rows:
        tid = row["id"]
        sim = float(row["similarity"])
        if tid == seed_topic_id or sim >= settings.fallback_similarity_floor:
            out.append(tid)
    if seed_topic_id not in out:
        out.insert(0, seed_topic_id)
    return out


def _dedupe_and_trim(rows: list[dict], top_k: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        key = insight_text_key(row.get("text", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned = dict(row)
        cleaned.pop("embedding", None)
        out.append(cleaned)
        if len(out) >= top_k:
            break
    return out


def _upsert_similarity_edges(db: Session, src_id: uuid.UUID, neighbors: list[dict]) -> None:
    """Create edges to all same-topic neighbors. No similarity threshold — connect by level (L3 → L2 → L1) only. Weight = similarity (min 0.01)."""
    for row in neighbors:
        sim = max(float(row.get("similarity", 0.5)), 0.01)
        dst_id = row["id"]
        db.merge(Edge(src=src_id, dst=dst_id, weight=sim, edge_type="idea_similarity"))
        db.merge(Edge(src=dst_id, dst=src_id, weight=sim, edge_type="idea_similarity"))


def _classify_pair_relation(
    seed_text: str, candidate_text: str, topic_1: str = "", topic_2: str = "", topic_3: str = ""
) -> tuple[str, float]:
    system_prompt = (
        "You classify relation between two short ideas. "
        "Return JSON only with keys relation_label and confidence. "
        "relation_label must be one of: support, oppose, neutral."
    )
    user_prompt = (
        f"Seed idea:\n{seed_text}\n\n"
        f"Candidate idea:\n{candidate_text}\n\n"
    )
    if topic_1 or topic_2 or topic_3:
        user_prompt += f"Topic context: {topic_1} / {topic_2} / {topic_3}\n\n"
    user_prompt += "Classify whether candidate supports, opposes, or is neutral to the seed idea."
    result = chat_json(system_prompt, user_prompt)
    label = str(result.get("relation_label", "neutral")).strip().lower()
    if label not in {"support", "oppose", "neutral"}:
        label = "neutral"
    confidence = float(result.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    return label, confidence


def _get_cached_relation(db: Session, src_id: uuid.UUID, dst_id: uuid.UUID) -> IdeaRelation | None:
    return db.query(IdeaRelation).filter(IdeaRelation.src_id == src_id, IdeaRelation.dst_id == dst_id).one_or_none()


def _get_or_create_relation(
    db: Session,
    seed: Insight,
    candidate_id: uuid.UUID,
    candidate_text: str,
    topic_path: list[str] | None = None,
) -> tuple[str, float]:
    cached = _get_cached_relation(db, seed.id, candidate_id)
    if cached is not None:
        return cached.relation_label, float(cached.confidence)
    t1, t2, t3 = "", "", ""
    if topic_path and len(topic_path) >= 3:
        t1, t2, t3 = topic_path[0], topic_path[1], topic_path[2]
    elif topic_path:
        t1 = topic_path[0] if len(topic_path) > 0 else ""
        t2 = topic_path[1] if len(topic_path) > 1 else ""
    label, confidence = _classify_pair_relation(seed.text, candidate_text, t1, t2, t3)
    db.merge(
        IdeaRelation(
            src_id=seed.id,
            dst_id=candidate_id,
            relation_label=label,
            confidence=confidence,
            updated_at=datetime.utcnow(),
        )
    )
    db.flush()
    return label, confidence


def _upsert_relation_edges(
    db: Session,
    src_id: uuid.UUID,
    dst_id: uuid.UUID,
    relation_label: str,
    confidence: float,
    similarity: float,
    allow_write: bool = True,
) -> None:
    if not allow_write:
        return
    if relation_label not in {"support", "oppose"}:
        return
    edge_type = "support" if relation_label == "support" else "oppose"
    # Blend confidence with cosine so edge thickness still reflects semantic closeness.
    weight = max(0.0, min(1.0, 0.55 * float(confidence) + 0.45 * float(similarity)))
    db.merge(Edge(src=src_id, dst=dst_id, weight=weight, edge_type=edge_type))
    db.merge(Edge(src=dst_id, dst=src_id, weight=weight, edge_type=edge_type))


def _in_relation_scope(seed: Insight, candidate_row: dict) -> bool:
    return candidate_row.get("topic_id") == seed.topic_id


def retrieve_relation_buckets(db: Session, idea_id: uuid.UUID, top_k: int = 2, candidate_pool: int = 24) -> dict:
    seed = _get_idea_or_none(db, idea_id)
    if not seed or not seed.topic_id:
        return {"supportive": [], "opposing": [], "neutral": []}
    candidates = _nearest_ideas_with_filters(
        db=db,
        embedding=seed.embedding,
        exclude_id=seed.id,
        topic_ids=[seed.topic_id],
        limit=max(top_k * 6, candidate_pool),
    )

    support_rows: list[dict] = []
    oppose_rows: list[dict] = []
    neutral_rows: list[dict] = []
    for row in candidates:
        in_scope = _in_relation_scope(seed, row)
        if not in_scope:
            continue
        topic_path = (seed.metadata_json or {}).get("topic_path")
        label, confidence = _get_or_create_relation(db, seed, row["id"], row.get("text", ""), topic_path=topic_path)
        _upsert_relation_edges(
            db=db,
            src_id=seed.id,
            dst_id=row["id"],
            relation_label=label,
            confidence=confidence,
            similarity=float(row.get("similarity", 0.0)),
            allow_write=in_scope,
        )
        enriched = {**row, "relation_label": label, "relation_confidence": confidence}
        if label == "support":
            support_rows.append(enriched)
        elif label == "oppose":
            oppose_rows.append(enriched)
        else:
            neutral_rows.append(enriched)

    support_rows.sort(key=lambda r: (float(r["relation_confidence"]), float(r.get("similarity", 0.0))), reverse=True)
    oppose_rows.sort(key=lambda r: (float(r["relation_confidence"]), float(r.get("similarity", 0.0))), reverse=True)
    neutral_rows.sort(key=lambda r: float(r.get("similarity", 0.0)), reverse=True)

    return {
        "supportive": _dedupe_and_trim(support_rows, top_k),
        "opposing": _dedupe_and_trim(oppose_rows, top_k),
        "neutral": _dedupe_and_trim(neutral_rows, top_k),
    }


def ingest_idea(
    db: Session, text_input: str, user_id: uuid.UUID | None = None, metadata_json: dict | None = None
) -> tuple[Insight, Topic, Topic]:
    text_value = normalize_insight_text(text_input)
    if len(text_value) < 5 or len(text_value) > 320:
        raise ValueError("Idea text must be between 5 and 320 characters.")

    normalized_key = insight_text_key(text_value)
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
        if metadata_json:
            merged_meta = dict(existing.metadata_json or {})
            merged_meta.update(metadata_json)
            existing.metadata_json = merged_meta
            db.add(existing)
            db.flush()
        parent = db.query(Topic).filter(Topic.id == existing.topic_id).one_or_none()
        subtopic = db.query(Topic).filter(Topic.id == existing.subtopic_id).one_or_none()
        if parent is None and subtopic is not None and subtopic.parent_topic_id is not None:
            parent = db.query(Topic).filter(Topic.id == subtopic.parent_topic_id).one_or_none()
        if parent is None or subtopic is None:
            # Legacy row without hierarchy; continue through regular routing path.
            existing_id = None
        else:
            return existing, parent, subtopic

    # Raw text only embedding; no topic_label/canonical_claim prefixing.
    embedding = embed_text(text_value)
    hierarchy = _classify_topic_hierarchy(text_value, topic_label="", canonical_claim="")

    level1 = _upsert_topic_level(
        db=db,
        embedding=embedding,
        level=1,
        name=hierarchy["level1"],
        parent_topic_id=None,
        threshold=settings.topic_similarity_threshold,
    )
    level2 = _upsert_topic_level(
        db=db,
        embedding=embedding,
        level=2,
        name=hierarchy["level2"],
        parent_topic_id=level1.id,
        threshold=settings.subtopic_similarity_threshold,
    )
    level3 = _upsert_topic_level(
        db=db,
        embedding=embedding,
        level=3,
        name=hierarchy["level3"],
        parent_topic_id=level2.id,
        threshold=settings.subtopic_similarity_threshold,
    )

    # Stance: centroid-based score; fallback to metadata stance_hint when centroids missing.
    llm_hint = (metadata_json or {}).get("stance_hint") if metadata_json else None
    stance_label, stance_score = _assign_stance(embedding, level3, level2, llm_hint)
    stance_confidence = abs(stance_score)
    _update_stance_centroid(level3, embedding, stance_label)

    idea = Insight(
        user_id=user_id,
        text=text_value,
        moderation_status="approved",
        type_label="other",
        embedding=embedding,
        cluster_id=str(level3.id),
        topic_id=level1.id,
        subtopic_id=level3.id,
        stance_label=stance_label,
        stance_confidence=stance_confidence,
        canonical_claim=text_value,
        counterclaim="",
        guardrail_json={"decision": "accept", "path": "topic_layer"},
        metadata_json={
            "stance_score": stance_score,
            "mid_topic_id": str(level2.id),
            "topic_path": [level1.name, level2.name, level3.name],
            "level1": hierarchy["level1"],
            "level2": hierarchy["level2"],
            "level3": hierarchy["level3"],
            "retrieval_mode": "topic_cosine_only",
            **(metadata_json or {}),
        },
    )
    db.add(idea)
    db.flush()

    # Hierarchical edge fallback:
    # level3 -> level2 (metadata mid_topic_id) -> level1 -> related level1 topics.
    needed = max(6, settings.topic_neighbor_top_k)
    merged: list[dict] = []
    seen_ids: set[uuid.UUID] = set()

    scopes = [
        _nearest_ideas_with_filters(
            db=db,
            embedding=embedding,
            exclude_id=idea.id,
            limit=needed,
            subtopic_id=level3.id,
        ),
        _nearest_ideas_with_filters(
            db=db,
            embedding=embedding,
            exclude_id=idea.id,
            limit=needed,
            topic_ids=[level1.id],
            mid_topic_id=str(level2.id),
        ),
        _nearest_ideas_with_filters(
            db=db,
            embedding=embedding,
            exclude_id=idea.id,
            limit=needed,
            topic_ids=[level1.id],
        ),
    ]

    for scope_rows in scopes:
        for row in scope_rows:
            rid = row["id"]
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            merged.append(row)
        if len(merged) >= needed:
            break

    merged.sort(key=lambda r: float(r.get("similarity", 0.0)), reverse=True)
    neighbors = merged[: settings.topic_neighbor_top_k]
    _upsert_similarity_edges(db, idea.id, neighbors)
    return idea, level1, level3


def _get_idea_or_none(db: Session, idea_id: uuid.UUID) -> Insight | None:
    return db.query(Insight).filter(Insight.id == idea_id).one_or_none()


def retrieve_nearby(db: Session, idea_id: uuid.UUID, top_k: int = 10) -> list[dict]:
    seed = _get_idea_or_none(db, idea_id)
    if not seed or not seed.topic_id:
        return []
    topic_ids = _related_topic_ids(db, seed.topic_id, seed.embedding)
    rows = _nearest_ideas_in_topics(
        db=db,
        embedding=seed.embedding,
        topic_ids=topic_ids,
        exclude_id=seed.id,
        limit=max(top_k, settings.retrieval_candidate_pool),
    )
    rows.sort(key=lambda r: float(r.get("similarity", 0.0)), reverse=True)
    return _dedupe_and_trim(rows, top_k)


def retrieve_supportive(db: Session, idea_id: uuid.UUID, top_k: int = 10) -> list[dict]:
    seed = _get_idea_or_none(db, idea_id)
    if not seed or not seed.topic_id:
        return []
    # Bounded per-level limit so we try leaves (L3) first with a small pool; fallback pulls only what we need.
    per_scope_limit = max(top_k * 4, 24)
    exclude = {seed.id}
    # Hierarchical: level3 (leaves) first; only if not enough, add level2 then level1.
    scopes: list[list[dict]] = []
    if seed.subtopic_id:
        scopes.append(
            _nearest_ideas_same_subtree(
                db=db,
                embedding=seed.embedding,
                subtopic_id=seed.subtopic_id,
                exclude_id=seed.id,
                limit=per_scope_limit,
                stance_label=seed.stance_label,
            )
        )
    subtopic = db.query(Topic).filter(Topic.id == seed.subtopic_id).one_or_none() if seed.subtopic_id else None
    if subtopic and subtopic.parent_topic_id:
        scopes.append(
            _nearest_ideas_same_level2(
                db=db,
                embedding=seed.embedding,
                level2_topic_id=subtopic.parent_topic_id,
                exclude_id=seed.id,
                limit=per_scope_limit,
                stance_label=seed.stance_label,
            )
        )
    scopes.append(
        _nearest_ideas_same_level1(
            db=db,
            embedding=seed.embedding,
            topic_id=seed.topic_id,
            exclude_id=seed.id,
            limit=per_scope_limit,
            stance_label=seed.stance_label,
        )
    )
    rows = _merge_candidates_hierarchical(scopes, exclude, top_k)
    return _dedupe_and_trim(rows, top_k)


def retrieve_opposing(db: Session, idea_id: uuid.UUID, top_k: int = 10, alpha: float | None = None) -> list[dict]:
    seed = _get_idea_or_none(db, idea_id)
    if not seed or not seed.topic_id:
        return []
    a = (alpha if alpha is not None else settings.opposing_alpha)
    opposite_stance = "con" if seed.stance_label == "pro" else "pro"
    per_scope_limit = max(top_k * 4, 24)
    exclude = {seed.id}
    # Hierarchical: level3 (leaves) first; only if not enough, add level2 then level1.
    scopes: list[list[dict]] = []
    if seed.subtopic_id:
        scopes.append(
            _nearest_ideas_same_subtree(
                db=db,
                embedding=seed.embedding,
                subtopic_id=seed.subtopic_id,
                exclude_id=seed.id,
                limit=per_scope_limit,
                stance_label=opposite_stance,
            )
        )
    subtopic = db.query(Topic).filter(Topic.id == seed.subtopic_id).one_or_none() if seed.subtopic_id else None
    if subtopic and subtopic.parent_topic_id:
        scopes.append(
            _nearest_ideas_same_level2(
                db=db,
                embedding=seed.embedding,
                level2_topic_id=subtopic.parent_topic_id,
                exclude_id=seed.id,
                limit=per_scope_limit,
                stance_label=opposite_stance,
            )
        )
    scopes.append(
        _nearest_ideas_same_level1(
            db=db,
            embedding=seed.embedding,
            topic_id=seed.topic_id,
            exclude_id=seed.id,
            limit=per_scope_limit,
            stance_label=opposite_stance,
        )
    )
    rows = _merge_candidates_hierarchical(scopes, exclude, top_k)
    # Score = α*cos(seed, candidate) + (1-α)*cos(candidate, opposite_centroid) when centroid exists.
    parent = db.query(Topic).filter(Topic.id == subtopic.parent_topic_id).one_or_none() if (subtopic and subtopic.parent_topic_id) else None
    opposite_centroid = None
    if subtopic:
        opposite_centroid = _get_stance_centroid(subtopic, opposite_stance) or (
            _get_stance_centroid(parent, opposite_stance) if parent else None
        )
    if opposite_centroid is not None:
        for r in rows:
            sim = float(r.get("similarity", 0.0))
            cand_emb = r.get("embedding")
            if isinstance(cand_emb, list) and cand_emb:
                toward_opposite = _cosine(cand_emb, opposite_centroid)
                r["similarity"] = a * sim + (1.0 - a) * toward_opposite
        rows.sort(key=lambda r: float(r.get("similarity", 0.0)), reverse=True)
    else:
        rows.sort(key=lambda r: float(r.get("similarity", 0.0)))
    return _dedupe_and_trim(rows, top_k)


def get_neighbors(db: Session, idea_id: uuid.UUID, top_k: int = 10) -> list[dict]:
    # Backward-compatible alias.
    return retrieve_nearby(db, idea_id, top_k=top_k)


def list_topics(db: Session) -> list[dict]:
    rows = db.query(Topic).order_by(Topic.level.asc(), Topic.n_points.desc()).all()
    out = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "level": row.level,
                "name": row.name,
                "n_points": row.n_points,
                "parent_topic_id": row.parent_topic_id,
                "stance_centroids_json": row.stance_centroids_json,
            }
        )
    return out


def build_map(db: Session, max_idea_edges: int = 2500) -> dict:
    topics = db.query(Topic).all()
    ideas = (
        db.query(Insight)
        .filter(Insight.topic_id.is_not(None), Insight.subtopic_id.is_not(None))
        .order_by(Insight.created_at.desc())
        .limit(1000)
        .all()
    )
    edges = db.query(Edge).order_by(Edge.weight.desc()).limit(max_idea_edges).all()
    return {
        "topics": [
            {
                "id": t.id,
                "level": t.level,
                "name": t.name,
                "n_points": t.n_points,
                "parent_topic_id": t.parent_topic_id,
                "centroid_embedding": t.centroid_embedding,
                "stance_centroids_json": t.stance_centroids_json,
            }
            for t in topics
        ],
        "topic_edges": [
            {"src_id": t.parent_topic_id, "dst_id": t.id, "weight": 1.0, "edge_type": "topic_hierarchy"}
            for t in topics
            if t.parent_topic_id is not None
        ],
        "ideas": [
            {
                "id": i.id,
                "text": i.text,
                "topic_id": i.topic_id,
                "subtopic_id": i.subtopic_id,
                "stance_label": i.stance_label,
            }
            for i in ideas
        ],
        "edges": [{"src_id": e.src, "dst_id": e.dst, "weight": e.weight, "edge_type": e.edge_type} for e in edges],
    }


def _assignment_entropy(labels: list[uuid.UUID | None]) -> float:
    counts: dict[uuid.UUID | None, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    entropy = 0.0
    for c in counts.values():
        p = c / total
        entropy -= p * math.log(p + 1e-12)
    return entropy


def _kmeans(embeddings: np.ndarray, k: int, n_iter: int = 20) -> np.ndarray:
    if embeddings.shape[0] <= k:
        return np.arange(embeddings.shape[0])
    rng = np.random.default_rng(seed=42)
    centroids = embeddings[rng.choice(embeddings.shape[0], size=k, replace=False)]
    labels = np.zeros(embeddings.shape[0], dtype=np.int32)
    for _ in range(n_iter):
        dists = ((embeddings[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        new_labels = np.argmin(dists, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for idx in range(k):
            members = embeddings[labels == idx]
            if len(members) > 0:
                centroids[idx] = members.mean(axis=0)
    return labels


def run_periodic_recluster(db: Session) -> dict:
    parents = db.query(Topic).filter(Topic.level == 1).all()
    refreshed = 0
    for parent in parents:
        ideas = db.query(Insight).filter(Insight.topic_id == parent.id).all()
        if len(ideas) < settings.recluster_min_points:
            continue
        entropy = _assignment_entropy([i.subtopic_id for i in ideas])
        if entropy < settings.recluster_entropy_threshold:
            continue

        vectors = np.array([i.embedding for i in ideas], dtype=np.float32)
        k = int(max(2, min(8, round(math.sqrt(len(ideas) / 6)))))
        labels = _kmeans(vectors, k=k)

        old_children = db.query(Topic).filter(Topic.level == 2, Topic.parent_topic_id == parent.id).all()
        for child in old_children:
            child.n_points = 0
            child.updated_at = datetime.utcnow()

        new_children: list[Topic] = []
        for idx in range(k):
            members = vectors[labels == idx]
            centroid = members.mean(axis=0).tolist() if len(members) else vectors[0].tolist()
            child = _create_topic(
                db=db,
                level=2,
                name=f"{parent.name} / cluster {idx + 1}",
                embedding=centroid,
                parent_topic_id=parent.id,
            )
            child.n_points = int(len(members))
            child.stance_centroids_json = {}
            new_children.append(child)

        for row_idx, idea in enumerate(ideas):
            child = new_children[int(labels[row_idx])]
            idea.subtopic_id = child.id
            idea.cluster_id = str(child.id)
            db.add(idea)
            _update_topic_centroid(child, idea.embedding)
            idea_stance = _normalize_stance_label(idea.stance_label)
            if idea_stance in {"pro", "con"}:
                _update_stance_centroid(child, idea.embedding, idea_stance)
        refreshed += 1

    db.flush()
    return {"topics_refreshed": refreshed}
