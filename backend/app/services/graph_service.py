from collections import defaultdict, deque
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Cluster, Edge, Insight
from app.settings import settings


def _get_clusters_map(db: Session, cluster_ids: set[str]) -> dict:
    if not cluster_ids:
        return {}
    rows = db.query(Cluster).filter(Cluster.cluster_id.in_(list(cluster_ids))).all()
    return {r.cluster_id: {"title": r.title, "summary": r.summary} for r in rows}


def _get_nodes_map(db: Session, node_ids: set[UUID]) -> dict:
    if not node_ids:
        return {}
    rows = db.query(Insight).filter(Insight.id.in_(list(node_ids))).all()
    return {
        r.id: {
            "id": r.id,
            "text": r.text,
            "cluster_id": r.cluster_id,
            "stance_label": r.stance_label,
            "type_label": r.type_label,
            "canonical_claim": r.canonical_claim,
        }
        for r in rows
    }


def get_graph(db: Session, node_id: UUID | None, depth: int = 2, budget: int = 80) -> dict:
    if node_id is None:
        rows = db.query(Insight).order_by(Insight.created_at.desc()).limit(budget).all()
        ids = {r.id for r in rows}
        edges = db.query(Edge).filter(Edge.src.in_(ids), Edge.dst.in_(ids)).all() if ids else []
        nodes = [
            {
                "id": r.id,
                "text": r.text,
                "cluster_id": r.cluster_id,
                "stance_label": r.stance_label,
                "type_label": r.type_label,
                "canonical_claim": r.canonical_claim,
            }
            for r in rows
        ]
        edge_list = [{"src": e.src, "dst": e.dst, "weight": e.weight} for e in edges]
        cluster_ids = {n["cluster_id"] for n in nodes}
        clusters = _get_clusters_map(db, cluster_ids)
        return {"nodes": nodes, "edges": edge_list, "clusters": clusters}

    per_node_budget = max(1, budget // max(depth, 1))
    visited = {node_id}
    queue = deque([(node_id, 0)])
    collected_edges = {}
    adjacency_counts = defaultdict(int)

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue

        # Outgoing edges: current -> dst
        outgoing = (
            db.query(Edge)
            .filter(Edge.src == current)
            .order_by(Edge.weight.desc())
            .limit(per_node_budget)
            .all()
        )
        for e in outgoing:
            src, dst = e.src, e.dst
            if adjacency_counts[src] >= settings.max_edges_per_node:
                continue
            key = (src, dst)
            collected_edges[key] = {"src": src, "dst": dst, "weight": e.weight}
            adjacency_counts[src] += 1
            if dst not in visited:
                visited.add(dst)
                queue.append((dst, dist + 1))

        # Incoming edges: src -> current (so we include nodes that link to this one)
        incoming = (
            db.query(Edge)
            .filter(Edge.dst == current)
            .order_by(Edge.weight.desc())
            .limit(per_node_budget)
            .all()
        )
        for e in incoming:
            src, dst = e.src, e.dst
            if adjacency_counts[src] >= settings.max_edges_per_node:
                continue
            key = (src, dst)
            collected_edges[key] = {"src": src, "dst": dst, "weight": e.weight}
            adjacency_counts[src] += 1
            if src not in visited:
                visited.add(src)
                queue.append((src, dist + 1))

    nodes_map = _get_nodes_map(db, visited)
    nodes_list = list(nodes_map.values())
    edge_list = list(collected_edges.values())
    cluster_ids = {n["cluster_id"] for n in nodes_list}
    clusters = _get_clusters_map(db, cluster_ids)
    return {"nodes": nodes_list, "edges": edge_list, "clusters": clusters}
