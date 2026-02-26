#!/usr/bin/env python3
"""
Reingest ideas: clear topic-layer data (edges, idea_relations, insights, topics)
then re-submit each line from seed_insights.jsonl to POST /ideas.

Run with API server up: uv run uvicorn app.main:app --port 8000
Then: cd backend && uv run python scripts/reingest_ideas.py
"""
import json
import os
import sys
import time
from pathlib import Path

# Run from backend or project root
if Path("app").exists():
    sys.path.insert(0, os.getcwd())
elif Path("backend/app").exists():
    sys.path.insert(0, str(Path("backend").resolve()))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text as sql_text

from app.db import engine

# Seed file: project root / seed_insights.jsonl (override with SEED_PATH env)
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
SEED_PATH = Path(os.getenv("SEED_PATH", str(PROJECT_ROOT / "seed_insights.jsonl")))
API_BASE = os.getenv("API_BASE", "http://localhost:8000")


def clear_topic_layer_tables():
    """Delete edges, idea_relations, reports, insights, topics (in FK order)."""
    with engine.begin() as conn:
        conn.execute(sql_text("DELETE FROM edges"))
        conn.execute(sql_text("DELETE FROM idea_relations"))
        conn.execute(sql_text("DELETE FROM reports"))
        conn.execute(sql_text("DELETE FROM insights"))
        conn.execute(sql_text("DELETE FROM topics"))
    print("Cleared edges, idea_relations, reports, insights, topics.")


def load_seed_lines(path: Path):
    """Yield dicts from JSONL."""
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def post_idea(payload: dict) -> bool:
    """POST one idea to /ideas. Returns True on success."""
    try:
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/ideas",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"  POST failed: {e}")
        return False


def main():
    print("Reingest: clearing topic-layer tables...")
    clear_topic_layer_tables()

    print(f"Loading seed from {SEED_PATH}...")
    lines = list(load_seed_lines(SEED_PATH))
    print(f"Submitting {len(lines)} ideas to POST /ideas...")

    ok = 0
    for i, row in enumerate(lines):
        text = row.get("text", "").strip()
        if not text:
            continue
        payload = {"text": text}
        if row.get("metadata"):
            payload["metadata_json"] = row["metadata"]
        if row.get("user_id") is not None:
            payload["user_id"] = str(row["user_id"])
        if post_idea(payload):
            ok += 1
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(lines)} ...")
        time.sleep(0.08)

    print(f"Done. Ingested {ok}/{len(lines)} ideas.")


if __name__ == "__main__":
    main()
