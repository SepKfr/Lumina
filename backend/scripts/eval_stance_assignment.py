import json

import requests

API_BASE = "http://localhost:8000"

SEED_IDEAS = [
    "I love winters because snow days make me happy.",
    "Winters are great for cozy reading and calm evenings.",
    "I dislike winters because the cold feels exhausting.",
    "Snowstorms in winter make commuting stressful and unsafe.",
    "I love summers for long sunny evenings.",
]

PROBE = "I love winters"


def submit_idea(text: str) -> dict:
    resp = requests.post(f"{API_BASE}/ideas", json={"text": text}, timeout=120)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to submit idea: {text} :: {resp.status_code} {resp.text}")
    return resp.json()


def main() -> None:
    created = []
    for text in SEED_IDEAS:
        created.append(submit_idea(text))

    probe = submit_idea(PROBE)
    probe_id = probe["node"]["id"]
    neighbors_resp = requests.get(f"{API_BASE}/neighbors", params={"id": probe_id, "top_k": 5}, timeout=60)
    neighbors_resp.raise_for_status()
    neighbors = neighbors_resp.json()["neighbors"]

    top_neighbor_texts = [n["text"] for n in neighbors]
    positive_winter_hits = [
        t for t in top_neighbor_texts if "winter" in t.lower() and ("love" in t.lower() or "great" in t.lower())
    ]
    print("Probe idea:", PROBE)
    print("Assigned stance:", probe["node"]["stance_label"])
    print("Top neighbors:", json.dumps(top_neighbor_texts, indent=2))
    print("Positive winter hits in top-k:", len(positive_winter_hits))

    if probe["node"]["stance_label"] != "pro":
        raise SystemExit("FAIL: probe stance is not pro")
    if not positive_winter_hits:
        raise SystemExit("FAIL: no positive winter neighbors found")
    print("PASS: stance-aware assignment places probe near winter-positive ideas.")


if __name__ == "__main__":
    main()
