"""
Prompt template management API.

Allows reading, editing, and resetting the AI prompt templates
used by the map analysis pipeline, without touching code.
"""

import os
import json
from fastapi import APIRouter, Body
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/prompt-templates", tags=["prompt-templates"])

# Path to the user-customized templates file
_TEMPLATE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage")
)
_TEMPLATE_FILE = os.path.join(_TEMPLATE_DIR, "prompt_templates.json")

# ── All template keys and their meta ────────────────────────────────────────

TEMPLATE_META = {
    "L1_SYSTEM": {
        "level": "L1",
        "role": "system",
        "label": "L1 System — Thumbnail Scan",
        "description": "System instructions for the initial thumbnail scan that identifies text regions.",
        "placeholders": [],
    },
    "L1_USER": {
        "level": "L1",
        "role": "user",
        "label": "L1 User — Thumbnail Analysis",
        "description": "User prompt for thumbnail scan. The AI identifies text regions and gets an overview.",
        "placeholders": ["{filename}"],
    },
    "L2A_SYSTEM": {
        "level": "L2a",
        "role": "system",
        "label": "L2a System — High-Res OCR",
        "description": "System instructions for precision OCR on text region crops.",
        "placeholders": [],
    },
    "L2A_USER": {
        "level": "L2a",
        "role": "user",
        "label": "L2a User — Text OCR",
        "description": "User prompt for reading text from high-res crops.",
        "placeholders": ["{label}", "{hint}", "{context}"],
    },
    "L2B_SYSTEM": {
        "level": "L2b",
        "role": "system",
        "label": "L2b System — Region Planning",
        "description": "System instructions for planning which map regions to examine next.",
        "placeholders": [],
    },
    "L2B_USER": {
        "level": "L2b",
        "role": "user",
        "label": "L2b User — Smart Planning",
        "description": "User prompt for planning coordinate strips and map samples to examine.",
        "placeholders": ["{filename}", "{overview_json}", "{ocr_json}"],
    },
    "L3_SYSTEM_COORDINATE": {
        "level": "L3",
        "role": "system",
        "label": "L3 System — Coordinate Extraction",
        "description": "System instructions for extracting coordinates from map edge strips.",
        "placeholders": [],
    },
    "L3_USER_COORDINATE": {
        "level": "L3",
        "role": "user",
        "label": "L3 User — Coordinate Strip",
        "description": "User prompt for reading longitude/latitude/scale from edge strips.",
        "placeholders": ["{label}", "{position}", "{expected_type}", "{hint}", "{context}", "{other_regions}"],
    },
    "L3_SYSTEM_SAMPLE": {
        "level": "L3",
        "role": "system",
        "label": "L3 System — Map Body Analysis",
        "description": "System instructions for analyzing map body content.",
        "placeholders": [],
    },
    "L3_USER_SAMPLE": {
        "level": "L3",
        "role": "user",
        "label": "L3 User — Map Body Sample",
        "description": "User prompt for extracting place names, terrain, infrastructure from map sections.",
        "placeholders": ["{label}", "{position}", "{hint}", "{context}", "{other_regions}"],
    },
    "SYNTH_SYSTEM": {
        "level": "Synthesis",
        "role": "system",
        "label": "Synthesis System — Metadata Merge",
        "description": "System instructions for combining all analysis data into final metadata.",
        "placeholders": [],
    },
    "SYNTH_USER": {
        "level": "Synthesis",
        "role": "user",
        "label": "Synthesis User — Final Metadata",
        "description": "User prompt for merging all levels into 21 structured catalogue fields.",
        "placeholders": ["{overview_json}", "{text_json}", "{understanding_json}", "{coordinate_json}", "{sample_json}"],
    },
    "POST_PROCESS_SYSTEM": {
        "level": "Post",
        "role": "system",
        "label": "Post-Process System — QA Review",
        "description": "System instructions for cross-map quality assurance review.",
        "placeholders": [],
    },
    "POST_PROCESS_USER": {
        "level": "Post",
        "role": "user",
        "label": "Post-Process User — Batch Refinement",
        "description": "User prompt for refining a batch of maps with cross-map context.",
        "placeholders": ["{count}", "{cross_map_summary}", "{map_data_json}"],
    },
    # ── Direct mode prompts ──
    "DIRECT_SYSTEM": {
        "level": "Direct",
        "role": "system",
        "label": "Direct System — Single-Pass Extraction",
        "description": "System instructions for the direct single-pass high-res analysis mode.",
        "placeholders": [],
    },
    "DIRECT_USER": {
        "level": "Direct",
        "role": "user",
        "label": "Direct User — Full Metadata Extraction",
        "description": "User prompt for extracting all map metadata in one pass from a high-res image.",
        "placeholders": ["{filename}"],
    },
    "DIRECT_SUPPLEMENT_SYSTEM": {
        "level": "Direct",
        "role": "system",
        "label": "Direct Supplement System — Detail Crop",
        "description": "System instructions for re-examining unclear areas at higher resolution.",
        "placeholders": [],
    },
    "DIRECT_SUPPLEMENT_USER": {
        "level": "Direct",
        "role": "user",
        "label": "Direct Supplement User — Targeted Read",
        "description": "User prompt for reading specific details from a cropped region.",
        "placeholders": ["{filename}", "{label}", "{field}", "{reason}", "{context}"],
    },
}


def _load_custom_templates() -> dict[str, str]:
    """Load user-customized templates from disk."""
    if os.path.isfile(_TEMPLATE_FILE):
        try:
            with open(_TEMPLATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_custom_templates(templates: dict[str, str]):
    """Save user-customized templates to disk."""
    os.makedirs(_TEMPLATE_DIR, exist_ok=True)
    with open(_TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)


def _get_defaults() -> dict[str, str]:
    """Import and return default prompt constants from ai_map_analysis."""
    from ..nodes.ai_map_analysis import (
        L1_SYSTEM, L1_USER,
        L2A_SYSTEM, L2A_USER,
        L2B_SYSTEM, L2B_USER,
        L3_SYSTEM_COORDINATE, L3_USER_COORDINATE,
        L3_SYSTEM_SAMPLE, L3_USER_SAMPLE,
        SYNTH_SYSTEM, SYNTH_USER,
        POST_PROCESS_SYSTEM, POST_PROCESS_USER,
        DIRECT_SYSTEM, DIRECT_USER,
        DIRECT_SUPPLEMENT_SYSTEM, DIRECT_SUPPLEMENT_USER,
    )
    return {
        "L1_SYSTEM": L1_SYSTEM,
        "L1_USER": L1_USER,
        "L2A_SYSTEM": L2A_SYSTEM,
        "L2A_USER": L2A_USER,
        "L2B_SYSTEM": L2B_SYSTEM,
        "L2B_USER": L2B_USER,
        "L3_SYSTEM_COORDINATE": L3_SYSTEM_COORDINATE,
        "L3_USER_COORDINATE": L3_USER_COORDINATE,
        "L3_SYSTEM_SAMPLE": L3_SYSTEM_SAMPLE,
        "L3_USER_SAMPLE": L3_USER_SAMPLE,
        "SYNTH_SYSTEM": SYNTH_SYSTEM,
        "SYNTH_USER": SYNTH_USER,
        "POST_PROCESS_SYSTEM": POST_PROCESS_SYSTEM,
        "POST_PROCESS_USER": POST_PROCESS_USER,
        "DIRECT_SYSTEM": DIRECT_SYSTEM,
        "DIRECT_USER": DIRECT_USER,
        "DIRECT_SUPPLEMENT_SYSTEM": DIRECT_SUPPLEMENT_SYSTEM,
        "DIRECT_SUPPLEMENT_USER": DIRECT_SUPPLEMENT_USER,
    }


def get_effective_template(key: str) -> str:
    """
    Get the effective template for a given key.
    Returns user-customized version if it exists, otherwise the default.
    Called by ai_map_analysis at runtime.
    """
    custom = _load_custom_templates()
    if key in custom:
        return custom[key]
    defaults = _get_defaults()
    return defaults.get(key, "")


# ── API endpoints ───────────────────────────────────────────────────────────


@router.get("/")
async def list_templates():
    """List all prompt templates with metadata, defaults, and custom overrides."""
    defaults = _get_defaults()
    custom = _load_custom_templates()

    result = []
    for key, meta in TEMPLATE_META.items():
        is_custom = key in custom
        result.append({
            "key": key,
            **meta,
            "default": defaults.get(key, ""),
            "custom": custom.get(key, None),
            "is_custom": is_custom,
            "effective": custom[key] if is_custom else defaults.get(key, ""),
        })
    return {"templates": result}


class TemplateUpdate(BaseModel):
    content: str


@router.put("/{key}")
async def update_template(key: str, body: TemplateUpdate):
    """Update a single prompt template."""
    if key not in TEMPLATE_META:
        return {"error": f"Unknown template key: {key}"}

    custom = _load_custom_templates()
    custom[key] = body.content
    _save_custom_templates(custom)
    return {"ok": True, "key": key, "is_custom": True}


@router.delete("/{key}")
async def reset_template(key: str):
    """Reset a single template back to its default."""
    if key not in TEMPLATE_META:
        return {"error": f"Unknown template key: {key}"}

    custom = _load_custom_templates()
    if key in custom:
        del custom[key]
        _save_custom_templates(custom)
    return {"ok": True, "key": key, "is_custom": False}


@router.post("/reset-all")
async def reset_all_templates():
    """Reset ALL templates back to defaults."""
    _save_custom_templates({})
    return {"ok": True, "message": "All templates reset to defaults"}
