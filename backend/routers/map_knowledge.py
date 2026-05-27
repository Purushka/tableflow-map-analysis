"""
Map analysis knowledge base — simple RAG-like system.

Stores domain knowledge chunks tagged by analysis phase.
At runtime, relevant chunks are retrieved and injected into
AI prompts as reference material.

Knowledge entries are stored in storage/map_knowledge.json.
Default entries are provided as seeds — users can add, edit,
and delete entries via the API (and the frontend editor).
"""

import os
import json
import uuid
from fastapi import APIRouter, Body
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/map-knowledge", tags=["map-knowledge"])

# Storage path
_STORAGE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage")
)
_KB_FILE = os.path.join(_STORAGE_DIR, "map_knowledge.json")

# ── Analysis phases that can use knowledge ─────────────────────────────────
PHASES = {
    "L1":        "L1 — Thumbnail Scan (identify text regions, map type)",
    "L2a":       "L2a — High-Res OCR (read text from crops)",
    "L2b":       "L2b — Region Planning (identify coordinate strips, map samples)",
    "L3_coord":  "L3 — Coordinate Extraction (read lat/lon/scale from strips)",
    "L3_sample": "L3 — Map Body Analysis (place names, features, terrain)",
    "Synthesis":  "Synthesis — Combine all data into structured metadata",
}

# ── Default knowledge entries (empty — users add their own) ────────────────

DEFAULT_ENTRIES: list[dict] = []


# ── Storage I/O ────────────────────────────────────────────────────────────

def _load_entries() -> list[dict]:
    """Load knowledge entries from disk. Returns empty list if file missing."""
    if os.path.isfile(_KB_FILE):
        try:
            with open(_KB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def _save_entries(entries: list[dict]):
    """Save knowledge entries to disk."""
    os.makedirs(_STORAGE_DIR, exist_ok=True)
    with open(_KB_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ── Runtime retrieval (called by ai_map_analysis) ─────────────────────────

def get_knowledge_for_phase(phase: str) -> str:
    """
    Retrieve all knowledge chunks relevant to a given phase.
    Returns formatted text ready to inject into a prompt.
    Called by ai_map_analysis at runtime.

    Phase names: L1, L2a, L2b, L3_coord, L3_sample, Synthesis
    """
    entries = _load_entries()
    relevant = [e for e in entries if phase in e.get("phases", [])]

    if not relevant:
        return ""

    parts = ["═══ REFERENCE KNOWLEDGE BASE ═══", ""]
    for entry in relevant:
        parts.append(f"### {entry.get('title', 'Untitled')}")
        parts.append(entry.get("content", ""))
        parts.append("")

    return "\n".join(parts)


# ── API endpoints ──────────────────────────────────────────────────────────


@router.get("/phases")
async def list_phases():
    """List all available analysis phases."""
    return {"phases": PHASES}


@router.get("/")
async def list_entries():
    """List all knowledge base entries."""
    entries = _load_entries()
    return {"entries": entries, "phases": PHASES}


class EntryCreate(BaseModel):
    title: str
    phases: list[str]
    category: str = ""
    content: str


class EntryUpdate(BaseModel):
    title: Optional[str] = None
    phases: Optional[list[str]] = None
    category: Optional[str] = None
    content: Optional[str] = None


@router.post("/")
async def create_entry(body: EntryCreate):
    """Create a new knowledge entry."""
    entries = _load_entries()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "title": body.title,
        "phases": body.phases,
        "category": body.category,
        "content": body.content,
    }
    entries.append(entry)
    _save_entries(entries)
    return {"ok": True, "entry": entry}


@router.put("/{entry_id}")
async def update_entry(entry_id: str, body: EntryUpdate):
    """Update an existing knowledge entry."""
    entries = _load_entries()
    for entry in entries:
        if entry["id"] == entry_id:
            if body.title is not None:
                entry["title"] = body.title
            if body.phases is not None:
                entry["phases"] = body.phases
            if body.category is not None:
                entry["category"] = body.category
            if body.content is not None:
                entry["content"] = body.content
            _save_entries(entries)
            return {"ok": True, "entry": entry}
    return {"error": f"Entry not found: {entry_id}"}


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str):
    """Delete a knowledge entry."""
    entries = _load_entries()
    new_entries = [e for e in entries if e["id"] != entry_id]
    if len(new_entries) == len(entries):
        return {"error": f"Entry not found: {entry_id}"}
    _save_entries(new_entries)
    return {"ok": True}


@router.post("/reset")
async def reset_to_defaults():
    """Reset knowledge base to default entries."""
    _save_entries(list(DEFAULT_ENTRIES))
    return {"ok": True, "message": "Knowledge base reset to defaults"}
