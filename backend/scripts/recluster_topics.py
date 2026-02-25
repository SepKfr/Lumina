import requests

API_BASE = "http://localhost:8000"


def main() -> None:
    response = requests.post(f"{API_BASE}/jobs/recluster", timeout=300)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
