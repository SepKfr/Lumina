# Lumina (MVP)

A **crowdsourced, AI-organized 3D map** of one-sentence human insights. People submit short beliefs or opinions; the system embeds them, groups them by topic, infers stance (pro/con), and builds a semantic graph. You explore the map, see “supporters” and “challengers” for any idea, and chat with **support** or **debate** agents—participants who agree or disagree—rather than a generic assistant.

---

## What This Project Is About

- **One-sentence insights**  
  Users contribute a single sentence: an opinion, claim, hypothesis, or personal learning (e.g. “Remote work increases productivity when teams define clear norms.”).

- **Semantic organization**  
  Each insight is embedded (OpenAI), assigned to a **cluster** by similarity to cluster centroids (online clustering with EMA updates), and gets a **stance** (pro / con / neutral) and optional **canonical claim** and **counterclaim** from an LLM.

- **Graph of ideas**  
  Similar insights in the same cluster are connected by **edges** (weight = cosine similarity). The result is a graph of nodes (insights) and edges (semantic similarity) that the frontend renders as a 3D force-directed map.

- **Supporters & challengers**  
  For any selected insight, the backend returns nearby **supporters** (same cluster, same stance) and **challengers** (same cluster, opposite stance), so users see who “agrees” and who “disagrees” in the neighborhood.

- **Conversational agents**  
  Users can open a **support** chat (aligned participant) or **debate** chat (opposing participant). Both use LLM roleplay with the selected insight and optional counterparty belief; chat messages are guarded by an LLM classifier (allow/block + safe rewrite).

- **Guardrails**  
  Submission and chat use **LLM-based reasoning** (structured JSON), not keyword bans. Submissions get accept / revise / reject with optional suggested revision; chat gets allow / block with a natural safe rewrite when blocked.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite)                                                     │
│  • 3D force graph (react-force-graph-3d) — nodes = insights, edges = sim    │
│  • InsightForm (submit), SidePanel (supporters/challengers, chat triggers)   │
│  • ChatPanel (support / debate conversation)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        │ HTTP (VITE_API_BASE_URL → backend)
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                                           │
│  • POST /v1/insights  — full pipeline: guardrail → embed → cluster → stance  │
│  • GET  /v1/graph     — neighborhood or recent sample                        │
│  • POST /v1/chat      — support or debate reply with guardrail               │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
          ┌─────────────────────────────┼─────────────────────────────┐
          │                             │                             │
          ▼                             ▼                             ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  PostgreSQL      │         │  OpenAI API      │         │  Prompt files     │
│  + pgvector      │         │  (embeddings +   │         │  guardrails/      │
│  insights,       │         │   chat completions│         │  chat/            │
│  edges,         │         │   JSON + embed)  │         │  clustering/      │
│  clusters        │         │                  │         │  (read by backend)│
└──────────────────┘         └──────────────────┘         └──────────────────┘
```

- **Data store:** Postgres with the `vector` extension (pgvector). Tables: `insights` (text, embedding, cluster_id, stance_label, type_label, canonical_claim, counterclaim, guardrail_json), `edges` (src, dst, weight), `clusters` (cluster_id, title, summary, centroid), `reports`.
- **Embeddings:** One vector per insight (e.g. 1536-d); enriched input includes topic_label, stance_hint, type_label, canonical_claim, and insight text (see `pre_embedding` + `insight_service`).
- **Clustering:** Online centroid-based: assign to best-matching cluster if similarity ≥ threshold; else create new cluster. Centroids updated with EMA when a new insight joins.
- **Graph:** Edges created only between insights in the **same cluster** and above an edge similarity threshold; stored in `edges` and used for neighborhood expansion and supporter/challenger derivation.

---

## How It’s Implemented

### Backend (FastAPI + SQLAlchemy + pgvector)

| Layer | Role |
|-------|------|
| **API** (`app/main.py`) | `POST /v1/insights`, `GET /v1/graph`, `POST /v1/chat`; CORS; health; DB unique index on normalized insight text. |
| **Models** (`app/models.py`) | `Insight`, `Edge`, `Cluster`, `Report`; pgvector `Vector(embedding_dim)` on `Insight` and `Cluster`. |
| **Insight pipeline** (`app/services/insight_service.py`) | Normalize text → duplicate check (normalized key) → submission guardrail (LLM) → embed (enriched context from `pre_embedding`) → `assign_cluster` → stance extraction (LLM) → persist insight → kNN neighbors → `upsert_edges` (same cluster, above threshold) → split supporters/challengers by stance. |
| **Clustering** (`app/services/clustering.py`) | Load all clusters; assign to best centroid by cosine similarity; if above threshold, update centroid with EMA and return; else create new cluster with stub title/summary. |
| **Graph** (`app/services/graph_service.py`) | No `node_id`: recent N insights + edges among them. With `node_id`: BFS expansion by depth and per-node edge budget, symmetric (in/out edges), cap edges per node; return nodes, edges, cluster info. |
| **Chat** (`app/services/chat_service.py`) | Chat guardrail (LLM) on user message; load support or debate prompt; substitute `user_belief`, `seed_belief`, `user_message`; build conversation history; call `chat_json`; return reply + guardrail. |
| **Guardrails** (`app/services/guardrails.py`) | `run_submission_guardrail`: LLM → `decision`, `categories`, `type_label`, `suggested_revision`. `run_chat_guardrail`: LLM → `decision`, `reason`, `safe_rewrite`. |
| **Stance** (`app/services/stance.py`) | LLM with cluster summary + insight → `canonical_claim`, `stance_label`, `counterclaim`. |
| **Pre-embedding** (`app/services/pre_embedding.py`) | LLM with type_label + insight → `topic_label`, `stance_hint`, `canonical_claim`; used to build enriched embedding input. |
| **LLM client** (`app/services/llm_client.py`) | `chat_json` (OpenAI-compatible chat, `response_format: json_object`), `embed_text` (embeddings API); settings from env. |

Config is via `app/settings.py` (Pydantic BaseSettings): `DATABASE_URL`, `OPENAI_*`, `EMBEDDING_DIM`, `CLUSTER_SIMILARITY_THRESHOLD`, `EDGE_SIMILARITY_THRESHOLD`, `CLUSTER_EMA_ALPHA`, `MAX_EDGES_PER_NODE`, `CORS_ORIGINS`.

### Frontend (React + Vite)

| Part | Role |
|------|------|
| **App** (`src/App.jsx`) | Global state: graph (nodes/edges), selected node, your submitted node, supporters, challengers, clusters, chat mode/conversation. Loads initial graph; on node click fetches neighborhood graph and derives supporters/challengers; on submit focuses map on new node and its cluster. Zoom tier (near/mid/far) drives depth/budget refetch. |
| **Map3D** (`src/components/Map3D.jsx`) | `react-force-graph-3d`; node color by cluster; labels as canvas sprites; “You are here” for your insight; click node → `onNodeClick`, click background → zoom toward point. |
| **SidePanel** (`src/components/SidePanel.jsx`) | Shows selected insight text, supporter/challenger previews, “Up for a chat?” (support) and “Up for a debate?” (debate); optional “Go to my insight” when viewing another node after submitting. |
| **ChatPanel** (`src/components/ChatPanel.jsx`) | Support or debate mode; sends `POST /v1/chat` with `mode`, `seed_insight_id`, `user_message`, `conversation_state`, optional `user_belief`/`counterparty_belief`; appends turn to conversation. |
| **InsightForm** (`src/components/InsightForm.jsx`) | Submit one-sentence insight to `POST /v1/insights`; surfaces revise/reject errors from guardrail. |
| **api.js** | `fetchGraph(params)`, `submitInsight(text)`, `sendChat(...)`; base URL from `VITE_API_BASE_URL`. |

### Prompt and config files (outside backend app)

- **guardrails/**  
  `submission_guardrail_prompt.txt` (accept/revise/reject, categories, type_label, suggested_revision); `chat_message_guardrail_prompt.txt` (allow/block, reason, safe_rewrite).
- **chat/**  
  `stance_extraction_prompt.txt` (canonical_claim, stance_label, counterclaim); `support_agent_prompt.txt`, `debate_agent_prompt.txt` (identity + user_belief/seed_belief/user_message, response as JSON `{"response":"..."}`).
- **clustering/**  
  `embedding_enrichment_prompt.txt` (topic_label, stance_hint, canonical_claim).

Moderation is entirely LLM reasoning; there is no keyword-block layer in this MVP.

---

## Folder structure

| Path | Purpose |
|------|---------|
| `backend/` | FastAPI app, DB models, services (insight, graph, chat, clustering, guardrails, stance, pre_embedding, llm_client, utils), `sql/init.sql` (pgvector), scripts (e.g. seed). |
| `frontend/` | React + Vite app, 3D map, forms, side panel, chat panel, API client. |
| `guardrails/` | LLM prompt specs for submission and chat message classification. |
| `chat/` | Prompts for stance extraction and support/debate agents. |
| `clustering/` | Prompt for embedding-enrichment classification. |
| `docker-compose.infra.yml` | Postgres + pgvector only (for local backend/frontend). |
| `docker-compose.yml` | Full stack: db + backend + frontend. |

---

## Running the project

### Option A: Infra in Docker, app locally (recommended)

1. Start Postgres + pgvector:

   ```bash
   docker-compose -f docker-compose.infra.yml up -d
   ```

2. Backend (from repo root):

   ```bash
   cd backend
   uv venv && source .venv/bin/activate
   uv pip install -r requirements.txt
   cp .env.example .env   # set OPENAI_API_KEY
   uv run uvicorn app.main:app --reload --port 8000
   ```

3. Frontend:

   ```bash
   cd frontend
   npm install && cp .env.example .env
   npm run dev
   ```

4. Check: `curl http://localhost:8000/health` → `{"status":"ok"}`. Open `http://localhost:5173/lumina` (default base path is `/lumina/` for the Lumina project). To run the app at the dev server root instead, set `VITE_BASE_PATH=/` in `frontend/.env`.

### Option B: Full Docker stack

```bash
docker-compose build && docker-compose up -d
```

Backend at 8000, frontend at 5173; set `OPENAI_API_KEY` in the environment for the backend service.

### Seed data (200–300 insights)

With backend running and DB + models ready:

```bash
python backend/scripts/seed_insights.py
```

Uses pro/con sentence variants and prefixes/suffixes to POST to `http://localhost:8000/v1/insights`.

### Deploying as **Lumina** at alignmentatlas.online/lumina

This project is configured so that **alignmentatlas.online/lumina** serves the Lumina app.

- **Frontend base path:** Vite uses `base: '/lumina/'` by default (`frontend/vite.config.js`). All assets and the app root are under `/lumina/`, so when the site is served at **alignmentatlas.online**, the path **/lumina** (or **/lumina/**) loads this app.
- **What you need on the host:** Your reverse proxy (e.g. nginx, Cloudflare, or your hosting platform) for **alignmentatlas.online** should:
  - Serve the **built** frontend static files (e.g. `frontend/dist/`) for requests to `/lumina` and `/lumina/*`.
  - Either proxy API requests to your backend (e.g. `/lumina/api` → backend) or keep the API on the same origin and set `VITE_API_BASE_URL` to that API base when building.
- **Build for production:** From `frontend/`, run `npm run build`. The output in `dist/` is meant to be served with base path `/lumina/`. Upload or deploy the contents of `dist/` so that the document root for `/lumina` is that folder (or map `/lumina` to that folder).
- **Backend CORS:** If the API is on a different host/port than the site, set `CORS_ORIGINS` in the backend to include `https://alignmentatlas.online` (and `http://localhost:5173` if you still need local dev).
- **Local dev:** With default config, open **http://localhost:5173/lumina**. To develop at the root (**http://localhost:5173/**), add `VITE_BASE_PATH=/` to `frontend/.env`.

---

## Key API contracts

- **POST /v1/insights**  
  Body: `{ "text": "one sentence", optional "user_id" }`.  
  Pipeline: normalize → duplicate check → guardrail → embed → cluster → stance → save → edges → supporters/challengers.  
  Returns: `node`, `cluster`, `supporters`, `challengers`, `subgraph`, `moderation_status`, `guardrail`.  
  On reject: 400 with guardrail; on revise: 422 with guardrail (e.g. `suggested_revision`).

- **GET /v1/graph**  
  Query: `node_id` (optional), `depth` (1–3), `budget` (10–500).  
  No `node_id`: recent `budget` insights and edges among them.  
  With `node_id`: BFS neighborhood within `depth` and `budget`, with cluster metadata.  
  Returns: `nodes`, `edges`, `clusters`.

- **POST /v1/chat**  
  Body: `mode` ("support" | "debate"), `seed_insight_id`, `user_message`, `conversation_state` (array of `{role, content}`), optional `user_belief`, `counterparty_belief`.  
  Returns: `mode`, `response`, `conversation_state` (updated with new turn), `guardrail`.

---

## Notes

- Cluster titles/summaries are minimal stubs in this baseline; they can be upgraded with an LLM summarization step.
- Duplicate detection uses a normalized key (lowercased, punctuation trimmed, whitespace collapsed) and a unique index on the DB; duplicates return the existing insight and its supporters/challengers without re-running the pipeline.
