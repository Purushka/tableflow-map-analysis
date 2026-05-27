# TableFlow — Map Analysis

A no-code data pipeline system built with FastAPI + React. The headline feature is a multi-stage vision pipeline that turns map images into structured, geo-tagged tabular data (country / province / city / district + ~25 metadata fields).

## What it does

TableFlow is a visual pipeline editor (think n8n / Node-RED, but for tables) where each node reads, transforms, or enriches a dataset. Nodes can be plain ETL (filter, join, pivot, deduplicate) or LLM-powered (classify, enrich, vision, search, map-analysis).

The **Map Analysis** node is the centerpiece. Given a folder of map images, it runs each image through a four-stage vision conversation and emits one structured row per map:

```
L1  thumbnail scan          → overview + text regions
L2a parallel OCR            → text content per region
L2b planning                → decide which map regions to crop and inspect
L3  parallel region explore → border + sample reads with positional context
Synthesis                   → 25-column structured JSON (country / province / city / district / …)
```

L1 → L2b → Synthesis share a single conversation per map, so each step sees the model's earlier reasoning. L2a OCR and L3 region exploration are fanned out in parallel for throughput.

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
