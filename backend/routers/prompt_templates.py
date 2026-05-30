"""
Prompt template management API.

Allows reading, editing, and resetting the AI prompt templates used by
the map analysis pipeline, without touching code.

The current pipeline uses these templates:
  EXTRACT_SYSTEM / EXTRACT_USER       — grounded extractor (single pass)
  GEO_CRITIC_SYSTEM / *_USER          — strict geographic-claim verifier
  OCR_CRITIC_SYSTEM / *_USER          — medium text-fidelity verifier
  VISUAL_CRITIC_SYSTEM / *_USER       — lenient visual-classification verifier
  CORRECTION_USER                     — fed back to the extractor's session
                                        when a critic flags something
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
    "GEO_CRITIC_SYSTEM": {
        "level": "Critic",
        "role": "system",
        "label": "Geo Critic System — Strict Anti-Hallucination",
        "description": "System rules for the geographic-claim verifier (country/province/city/bbox).",
        "placeholders": [],
    },
    "GEO_CRITIC_USER": {
        "level": "Critic",
        "role": "user",
        "label": "Geo Critic User — Geographic Claims Audit",
        "description": "User prompt for the geographic-claim verifier.",
        "placeholders": ["{filename}", "{claims_json}"],
    },
    "OCR_CRITIC_SYSTEM": {
        "level": "Critic",
        "role": "system",
        "label": "OCR Critic System — Text Fidelity",
        "description": "System rules for the OCR/text-fidelity verifier (title/date/publisher/scale/etc).",
        "placeholders": [],
    },
    "OCR_CRITIC_USER": {
        "level": "Critic",
        "role": "user",
        "label": "OCR Critic User — Text Claims Audit",
        "description": "User prompt for the OCR/text-fidelity verifier.",
        "placeholders": ["{filename}", "{claims_json}"],
    },
    "VISUAL_CRITIC_SYSTEM": {
        "level": "Critic",
        "role": "system",
        "label": "Visual Critic System — Lenient Classification",
        "description": "System rules for the visual-classification verifier (map_type/medium/condition/etc).",
        "placeholders": [],
    },
    "VISUAL_CRITIC_USER": {
        "level": "Critic",
        "role": "user",
        "label": "Visual Critic User — Visual Claims Audit",
        "description": "User prompt for the visual-classification verifier.",
        "placeholders": ["{filename}", "{claims_json}"],
    },
    "CORRECTION_USER": {
        "level": "Correction",
        "role": "user",
        "label": "Correction User — Critic Feedback",
        "description": "Fed back into the extractor's session when the critic flags fields.",
        "placeholders": ["{verdicts_summary}"],
    },
    "RESCUE_SYSTEM": {
        "level": "Rescue",
        "role": "system",
        "label": "Rescue System — Salvage Demoted Fields",
        "description": "Text-only agent that converts a critic's observation into a typed field value.",
        "placeholders": [],
    },
    "RESCUE_USER": {
        "level": "Rescue",
        "role": "user",
        "label": "Rescue User — Field-Specific Recovery",
        "description": "Per-field rescue prompt sent without an image attachment.",
        "placeholders": ["{field_name}", "{field_type}", "{field_format}",
                         "{what_you_see}", "{old_value}", "{issue}"],
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
        GEO_CRITIC_SYSTEM, GEO_CRITIC_USER,
        OCR_CRITIC_SYSTEM, OCR_CRITIC_USER,
        VISUAL_CRITIC_SYSTEM, VISUAL_CRITIC_USER,
        CORRECTION_USER,
        RESCUE_SYSTEM, RESCUE_USER,
    )
    return {
        "EXTRACT_SYSTEM": EXTRACT_SYSTEM,
        "EXTRACT_USER": EXTRACT_USER,
        "GEO_CRITIC_SYSTEM": GEO_CRITIC_SYSTEM,
        "GEO_CRITIC_USER": GEO_CRITIC_USER,
        "OCR_CRITIC_SYSTEM": OCR_CRITIC_SYSTEM,
        "OCR_CRITIC_USER": OCR_CRITIC_USER,
        "VISUAL_CRITIC_SYSTEM": VISUAL_CRITIC_SYSTEM,
        "VISUAL_CRITIC_USER": VISUAL_CRITIC_USER,
        "CORRECTION_USER": CORRECTION_USER,
        "RESCUE_SYSTEM": RESCUE_SYSTEM,
        "RESCUE_USER": RESCUE_USER,
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
