import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from .models.database import init_db
from .engine.registry import init_registry
from .providers.registry import init_providers
from .routers import files, nodes, pipelines, execution, nl_parse, providers, prompt_templates, map_knowledge, fewshot


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    init_providers()
    init_registry()
    yield


app = FastAPI(title="TableFlow", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files.router)
app.include_router(nodes.router)
app.include_router(pipelines.router)
app.include_router(execution.router)
app.include_router(nl_parse.router)
app.include_router(providers.router)
app.include_router(prompt_templates.router)
app.include_router(map_knowledge.router)
app.include_router(fewshot.router)

# Serve output files
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "storage", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/settings")
async def get_settings():
    """Return provider info only. API keys are managed client-side."""
    from .providers.registry import get_all_providers
    return {"providers": get_all_providers()}
