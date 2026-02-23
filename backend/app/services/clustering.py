import uuid
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.models import Cluster
from app.settings import settings


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _cluster_stub_text(cluster_id: str) -> tuple[str, str]:
    title = f"Cluster {cluster_id[:6]}"
    summary = "Semantically related insights grouped by embedding proximity."
    return title, summary


def assign_cluster(db: Session, embedding: list[float]) -> Cluster:
    clusters = db.query(Cluster).all()
    if not clusters:
        cluster_id = f"cluster-{uuid.uuid4().hex[:8]}"
        title, summary = _cluster_stub_text(cluster_id)
        cluster = Cluster(cluster_id=cluster_id, title=title, summary=summary, centroid=embedding)
        db.add(cluster)
        db.flush()
        return cluster

    best = max(clusters, key=lambda c: cosine_similarity(c.centroid, embedding))
    best_similarity = cosine_similarity(best.centroid, embedding)

    if best_similarity >= settings.cluster_similarity_threshold:
        alpha = settings.cluster_ema_alpha
        updated = ((1 - alpha) * np.array(best.centroid)) + (alpha * np.array(embedding))
        best.centroid = updated.tolist()
        best.updated_at = datetime.utcnow()
        db.add(best)
        db.flush()
        return best

    cluster_id = f"cluster-{uuid.uuid4().hex[:8]}"
    title, summary = _cluster_stub_text(cluster_id)
    cluster = Cluster(cluster_id=cluster_id, title=title, summary=summary, centroid=embedding)
    db.add(cluster)
    db.flush()
    return cluster
