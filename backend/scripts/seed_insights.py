import random
import time

import requests

API_BASE = "http://localhost:8000"
TARGET = 250

TOPICS = [
    ("Remote work increases productivity", "Remote work hurts team cohesion"),
    ("AI tutors improve learning speed", "AI tutors weaken deep thinking"),
    ("City bike lanes reduce congestion", "Bike lanes worsen traffic bottlenecks"),
    ("Nuclear energy is essential for climate goals", "Nuclear energy is too risky to scale"),
    ("Social media builds community", "Social media fragments attention and trust"),
    ("Universal basic income boosts creativity", "Universal basic income reduces work motivation"),
    ("Public transit should be free", "Free transit degrades service quality"),
    ("Open source accelerates innovation", "Open source can dilute accountability"),
    ("School uniforms improve focus", "School uniforms suppress self-expression"),
    ("Cryptocurrency enables financial freedom", "Cryptocurrency increases systemic instability"),
]

PREFIXES = [
    "In my experience,",
    "I think",
    "It seems that",
    "My hypothesis is that",
    "I've learned that",
]

SUFFIXES = [
    "because incentives align better.",
    "when teams define clear norms.",
    "if institutions adapt fast enough.",
    "in most dense urban contexts.",
    "once people trust the process.",
]


def build_sentence(base: str) -> str:
    return f"{random.choice(PREFIXES)} {base.lower()} {random.choice(SUFFIXES)}"


def generate_pool() -> list[str]:
    out = []
    for pro, con in TOPICS:
        for _ in range(12):
            out.append(build_sentence(pro))
            out.append(build_sentence(con))
    random.shuffle(out)
    return out[:TARGET]


def main() -> None:
    texts = generate_pool()
    inserted = 0
    for text in texts:
        payload = {"text": text}
        try:
            resp = requests.post(f"{API_BASE}/v1/insights", json=payload, timeout=120)
            if resp.status_code in (200, 201):
                inserted += 1
            time.sleep(0.05)
        except requests.RequestException:
            continue

    print(f"Seed complete. Inserted {inserted} / {len(texts)} insights.")


if __name__ == "__main__":
    main()
