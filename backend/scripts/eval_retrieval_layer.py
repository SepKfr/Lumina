import json
import uuid

import requests

API_BASE = "http://localhost:8000"


def submit_idea(text: str, run_tag: str) -> dict:
    resp = requests.post(
        f"{API_BASE}/ideas",
        json={"text": text, "metadata_json": {"eval_run_tag": run_tag}},
        timeout=120,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to submit idea: {text} :: {resp.status_code} {resp.text}")
    return resp.json()


def fetch_neighbors(path: str, idea_id: str, run_tag: str, top_k: int = 5, alpha: float | None = None) -> list[dict]:
    params = {"id": idea_id, "top_k": top_k}
    if alpha is not None:
        params["alpha"] = alpha
    resp = requests.get(f"{API_BASE}/{path}", params=params, timeout=60)
    resp.raise_for_status()
    rows = resp.json().get("neighbors", [])
    return [r for r in rows if (r.get("metadata_json") or {}).get("eval_run_tag") == run_tag]


def main() -> None:
    run_tag = uuid.uuid4().hex[:8]
    seed_ideas = [
        "I love winters because snow days make me happy.",
        "Winters are great for cozy reading and calm evenings.",
        "I dislike winters because the cold feels exhausting.",
        "Snowstorms in winter make commuting stressful and unsafe.",
    ]
    probe_text = "I love winters."

    for text in seed_ideas:
        submit_idea(text, run_tag)
    probe = submit_idea(probe_text, run_tag)
    probe_id = probe["node"]["id"]
    probe_stance = probe["node"]["stance_label"]

    supportive = fetch_neighbors("supportive", probe_id, run_tag, top_k=8)
    opposing = fetch_neighbors("opposing", probe_id, run_tag, top_k=8, alpha=0.65)
    nearby = fetch_neighbors("nearby", probe_id, run_tag, top_k=8)

    supportive_texts = [row["text"] for row in supportive]
    opposing_texts = [row["text"] for row in opposing]
    nearby_texts = [row["text"] for row in nearby]

    supportive_winter_positive = [
        t for t in supportive_texts if "winter" in t.lower() and ("love" in t.lower() or "great" in t.lower())
    ]
    opposing_winter_negative = [
        t
        for t in opposing_texts
        if "winter" in t.lower() and ("dislike" in t.lower() or "stressful" in t.lower() or "unsafe" in t.lower())
    ]

    print("Run tag:", run_tag)
    print("Probe:", probe_text)
    print("Assigned stance:", probe_stance)
    print("Supportive:", json.dumps(supportive_texts, indent=2))
    print("Opposing:", json.dumps(opposing_texts, indent=2))
    print("Nearby:", json.dumps(nearby_texts, indent=2))

    if probe_stance != "pro":
        raise SystemExit("FAIL: expected probe stance to be pro")
    if not supportive_winter_positive:
        raise SystemExit("FAIL: supportive results did not include winter-positive neighbors")
    if not opposing_winter_negative:
        raise SystemExit("FAIL: opposing results did not include winter-negative neighbors")
    if len(nearby_texts) == 0:
        raise SystemExit("FAIL: nearby returned no neighbors")

    print("PASS: retrieval layer returns supportive/opposing/nearby as expected.")


if __name__ == "__main__":
    main()
