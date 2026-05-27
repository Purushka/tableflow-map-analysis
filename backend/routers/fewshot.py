"""
Few-shot annotation API for map analysis.

Users annotate low-res map thumbnails by drawing bounding boxes
and labelling regions. These annotations are injected as few-shot
examples into L1 and/or L2b prompts, helping the AI produce more
accurate text region detection and coordinate/sample planning.

Each example is tagged with one or more phases: "L1", "L2b".
"""

import os
import io
import json
import uuid
import base64
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/fewshot", tags=["fewshot"])

_STORAGE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage", "fewshot")
)
_INDEX_FILE = os.path.join(_STORAGE_DIR, "index.json")
_THUMB_DIM = 3840   # match analysis thumbnail size

# Region types per phase
L1_TYPES = {"text_region"}
L2B_TYPES = {"coordinate_strip", "map_sample"}


# ── Storage I/O ────────────────────────────────────────────────────────────

def _load_index() -> list[dict]:
    if os.path.isfile(_INDEX_FILE):
        try:
            with open(_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_index(data: list[dict]):
    os.makedirs(_STORAGE_DIR, exist_ok=True)
    with open(_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_thumb_b64(thumb_file: str) -> str | None:
    """Read a thumbnail as base64, or None if missing."""
    path = os.path.join(_STORAGE_DIR, thumb_file)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _make_image_message(img_b64: str, text: str) -> dict:
    """Build a provider-neutral user message with image + text."""
    return {
        "role": "user",
        "content": [
            {"type": "image", "data": img_b64, "media_type": "image/jpeg"},
            {"type": "text", "text": text},
        ],
    }


# ── Runtime: build few-shot messages per phase ────────────────────────────

def get_fewshot_messages(phase: str) -> list[dict]:
    """
    Build few-shot conversation turns for a given phase ("L1" or "L2b").
    Returns a list of {role, content} dicts ready to prepend
    to the conversation history.

    Each example becomes:
      user:      [thumbnail image] + reference instruction
      assistant: [correct JSON output matching that phase's format]
    """
    examples = _load_index()
    if not examples:
        return []

    messages = []
    for ex in examples:
        # Check phase match
        ex_phases = ex.get("phases", ["L2b"])  # backward compat
        if phase not in ex_phases:
            continue

        img_b64 = _read_thumb_b64(ex["thumb_file"])
        if not img_b64:
            continue

        regions = ex.get("regions", [])
        description = ex.get("description", "Reference example map")

        if phase == "L1":
            expected_output = _build_l1_output(regions, description)
        else:  # L2b
            expected_output = _build_l2b_output(regions, description)

        messages.append(_make_image_message(img_b64, (
            "Here is a REFERENCE EXAMPLE. "
            "Study the correct annotations below, "
            "then apply the same approach to the next map.\n"
            f"Map description: {description}"
        )))
        messages.append({
            "role": "assistant",
            "content": expected_output,
        })

    return messages


def _build_l1_output(regions: list[dict], description: str) -> str:
    """Build L1-format JSON from annotated regions."""
    text_regions = []
    for r in regions:
        if r.get("type") == "text_region":
            text_regions.append({
                "label": r["label"],
                "bbox": r["bbox"],
                "hint": r.get("hint", ""),
            })

    return json.dumps({
        "overview": {
            "rough_title": "",
            "map_type": "",
            "medium": "",
            "condition": "good",
            "has_insets": "no",
            "brief": description,
        },
        "text_regions": text_regions,
    }, ensure_ascii=False)


def _build_l2b_output(regions: list[dict], description: str) -> str:
    """Build L2b-format JSON from annotated regions."""
    map_regions = []
    for r in regions:
        if r.get("type") in ("coordinate_strip", "map_sample"):
            map_regions.append({
                "label": r["label"],
                "type": r["type"],
                "bbox": r["bbox"],
                "hint": r.get("hint", ""),
            })

    return json.dumps({
        "understanding": description,
        "visual_update": {
            "subject": "",
            "coverage": "",
            "language": "",
        },
        "map_regions": map_regions,
    }, ensure_ascii=False)


# ── API endpoints ──────────────────────────────────────────────────────────

@router.get("/")
async def list_examples():
    """List all few-shot examples."""
    examples = _load_index()
    for ex in examples:
        ex["thumb_url"] = f"/api/fewshot/{ex['id']}/thumb"
        # Backward compat: add phases if missing
        if "phases" not in ex:
            ex["phases"] = ["L2b"]
    return {"examples": examples}


@router.get("/{example_id}/thumb")
async def get_thumbnail(example_id: str):
    """Serve the thumbnail image for an example."""
    examples = _load_index()
    for ex in examples:
        if ex["id"] == example_id:
            path = os.path.join(_STORAGE_DIR, ex["thumb_file"])
            if os.path.isfile(path):
                return FileResponse(path, media_type="image/jpeg")
    return {"error": "Not found"}


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    """
    Upload a map image. Returns a temporary ID and thumbnail URL.
    The image is resized to thumbnail dimensions for annotation.
    """
    from PIL import Image

    content = await file.read()
    img = Image.open(io.BytesIO(content))

    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > _THUMB_DIM:
        ratio = _THUMB_DIM / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    os.makedirs(_STORAGE_DIR, exist_ok=True)
    temp_id = uuid.uuid4().hex[:8]
    thumb_file = f"{temp_id}_thumb.jpg"
    thumb_path = os.path.join(_STORAGE_DIR, thumb_file)
    img.save(thumb_path, "JPEG", quality=70)

    return {
        "temp_id": temp_id,
        "thumb_file": thumb_file,
        "thumb_url": f"/api/fewshot/{temp_id}/thumb-temp",
        "width": img.size[0],
        "height": img.size[1],
    }


@router.get("/{temp_id}/thumb-temp")
async def get_temp_thumbnail(temp_id: str):
    """Serve a temporary thumbnail (before saving as example)."""
    path = os.path.join(_STORAGE_DIR, f"{temp_id}_thumb.jpg")
    if os.path.isfile(path):
        return FileResponse(path, media_type="image/jpeg")
    return {"error": "Not found"}


class RegionAnnotation(BaseModel):
    label: str
    type: str  # "text_region", "coordinate_strip", or "map_sample"
    bbox: list[float]  # [x%, y%, w%, h%]
    hint: str = ""


class SaveExample(BaseModel):
    temp_id: str
    thumb_file: str
    description: str = ""
    phases: list[str] = ["L2b"]  # "L1" and/or "L2b"
    regions: list[RegionAnnotation]


@router.post("/save")
async def save_example(body: SaveExample):
    """Save annotations as a few-shot example."""
    examples = _load_index()
    example = {
        "id": body.temp_id,
        "thumb_file": body.thumb_file,
        "description": body.description,
        "phases": body.phases,
        "regions": [r.dict() for r in body.regions],
    }
    examples.append(example)
    _save_index(examples)
    return {"ok": True, "id": body.temp_id}


class UpdateExample(BaseModel):
    description: Optional[str] = None
    phases: Optional[list[str]] = None
    regions: Optional[list[RegionAnnotation]] = None


@router.put("/{example_id}")
async def update_example(example_id: str, body: UpdateExample):
    """Update an existing example's annotations."""
    examples = _load_index()
    for ex in examples:
        if ex["id"] == example_id:
            if body.description is not None:
                ex["description"] = body.description
            if body.phases is not None:
                ex["phases"] = body.phases
            if body.regions is not None:
                ex["regions"] = [r.dict() for r in body.regions]
            _save_index(examples)
            return {"ok": True, "id": example_id}
    return {"error": "Not found"}


@router.delete("/{example_id}")
async def delete_example(example_id: str):
    """Delete a few-shot example."""
    examples = _load_index()
    new_examples = []
    deleted = False
    for ex in examples:
        if ex["id"] == example_id:
            path = os.path.join(_STORAGE_DIR, ex["thumb_file"])
            if os.path.isfile(path):
                os.remove(path)
            deleted = True
        else:
            new_examples.append(ex)
    if deleted:
        _save_index(new_examples)
        return {"ok": True}
    return {"error": "Not found"}
