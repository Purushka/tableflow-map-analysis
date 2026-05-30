# TableFlow — Map Analysis

A no-code data pipeline system built with FastAPI + React. The headline feature is a multi-stage vision pipeline that turns map images into structured, geo-tagged tabular data (country / province / city / district + ~25 metadata fields).

## What it does

TableFlow is a visual pipeline editor (think n8n / Node-RED, but for tables) where each node reads, transforms, or enriches a dataset. Nodes can be plain ETL (filter, join, pivot, deduplicate) or LLM-powered (classify, enrich, vision, search, map-analysis).

The **Map Analysis** node is the centerpiece. Given a folder of map images, it runs each image through a grounded extractor + critic loop and emits one structured row per map:

```
Extract  full image → grounded fields ({value, evidence_bbox, evidence_text, evidence_kind})
   ↓
Critic   reviews each field against its evidence_bbox in the same image
   ↓
Correct  if critic flags anything, the feedback is appended to the extractor's
         conversation and the extractor re-grounds the flagged fields
   ↓
(loop up to max_correction_rounds; fields the critic still rejects are dropped)
```

Every non-empty field the extractor outputs must be bound to a specific
rectangular region of the image (`evidence_bbox`) and accompanied by the
source text or visual marker that supports it. If the extractor cannot point
to where a value is visible, it must omit the field entirely — so the
dataframe never gets values pulled from the model's training memory of
"famous maps that usually show X".

The critic is a second vision model that looks at each `evidence_bbox`
and judges whether the claim is actually supported. Flagged fields are
fed back into the **same extractor conversation** as a follow-up user
message, so the extractor has its prior reasoning plus the critic's
feedback when it re-extracts. After the final round, any field the critic
still flags is demoted to empty — better a missing column than a
hallucinated one.

## Stack

| Layer    | Tech                                                              |
|----------|-------------------------------------------------------------------|
| Backend  | FastAPI · SQLAlchemy (aiosqlite) · pandas · Pillow                |
| Frontend | React 19 · TypeScript · Vite · @xyflow/react · TanStack Query/Table · Zustand · Tailwind |
| LLMs     | Anthropic Claude · OpenAI · Google Gemini (pluggable provider layer) |
| Retrieval| sentence-transformers · BM25                                      |

The provider layer (`backend/providers/`) abstracts vision + conversation calls across all three vendors behind a single neutral message format, so any node can swap models without code changes.

## Repo layout

```
backend/
  main.py              FastAPI app + lifespan init
  nodes/               pipeline node implementations (input/transform/output/ai_*)
  providers/           LLM provider abstraction (anthropic / openai / google)
  routers/             HTTP routes: files, nodes, pipelines, execution, providers, …
  engine/              pipeline registry and execution engine
  models/              SQLAlchemy schema
  search/              embedding + BM25 retrieval
  lookups/             reference data lookups
  plugins/             extension points
  storage/             runtime data (gitignored; only map_knowledge.json is tracked)
frontend/
  src/                 React app (App.tsx, components, nodes, store, api, …)
examples/
  rgssa_pipeline.json  sample pipeline definition
```

## Running locally

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then set ANTHROPIC_API_KEY (and OPENAI_API_KEY / GOOGLE_API_KEY if used)
cd ..
uvicorn backend.main:app --reload
```

API is now at `http://localhost:8000`. Health check: `GET /api/health`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dev server at `http://localhost:5173`. CORS is already wired for that origin in `backend/main.py`.

## Map Analysis output schema

The synthesis step emits one row per map with these columns (subset):

- `map_country`, `map_province`, `map_city`, `map_district` — administrative hierarchy from broadest to narrowest
- map type, projection, scale, year, language, source
- legend entries, color scheme, notable features
- text extracted from titles, captions, legends, annotations

Full schema is in `backend/nodes/ai_map_analysis.py` (`MAP_FIELDS`).

## Notes

- API keys are managed client-side by default — `/api/settings` only returns provider metadata, not secrets.
- `backend/storage/` is gitignored. The directory will be created at runtime; uploads, generated outputs, and the SQLite DB live there.
- The `examples/rgssa_pipeline.json` file is a complete pipeline you can import to see how nodes are wired together.

## License

No license has been set yet. All rights reserved by the author.
