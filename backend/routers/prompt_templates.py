"""
Prompt template management API.

Allows reading, editing, and resetting the AI prompt templates used by
the map analysis pipeline, without touching code.

The current pipeline uses three templates:
  EXTRACT_SYSTEM / EXTRACT_USER  — grounded extractor (single pass)
  CRITIC_SYSTEM / CRITIC_USER    — independent grounding verifier
  CORRECTION_USER                — fed back to the extractor's session
                                   when the critic flags something
"""

import os
import json
from fastapi import APIRouter, Body
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/prompt-templates", tags=["prompt-templates"])

_TEMPLATE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage")
)
_TEMPLATE_FILE = os.path.join(_TEMPLATE_DIR, "prompt_templates.json")

# ── All template keys and their meta ────────────────────────────────────────

TEMPLATE_META = {
    "EXTRACT_SYSTEM": {
        "level": "Extract",
        "role": "system",
        "label": "Extractor System — Grounded Extraction",
        "description": "System instructions for the single-pass grounded extractor.",
        "placeholders": [],
    },
    "EXTRACT_USER": {
        "level": "Extract",
        "role": "user",
        "label": "Extractor User — Grounded Fields",
        "description": "User prompt that tells the extractor what fields to ground and how.",
        "placeholders": ["{filename}"],
    },
    "CRITIC_SYSTEM": {
        "level": "Critic",
        "role": "system",
        "label": "Critic System — Grounding Verifier",
        "description": "System instructions for the independent grounding verifier.",
        "placeholders": [],
    },
    "CRITIC_USER": {
        "level": "Critic",
        "role": "user",
        "label": "Critic User — Per-Field Verdicts",
        "description": "User prompt for the critic to verify each grounded claim.",
        "placeholders": ["{filename}", "{claims_json}"],
    },
    "CORRECTION_USER": {
        "level": "Correction",
        "role": "user",
        "label": "Correction User — Critic Feedback",
        "description": "Fed back into the extractor's session when the critic flags fields.",
        "placeholders": ["{verdicts_summary}"],
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
        EXTRACT_SYSTEM, EXTRACT_USER,
        CRITIC_SYSTEM, CRITIC_USER,
        CORRECTION_USER,
    )
    return {
        "EXTRACT_SYSTEM": EXTRACT_SYSTEM,
        "EXTRACT_USER": EXTRACT_USER,
        "CRITIC_SYSTEM": CRITIC_SYSTEM,
        "CRITIC_USER": CRITIC_USER,
        "CORRECTION_USER": CORRECTION_USER,
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
