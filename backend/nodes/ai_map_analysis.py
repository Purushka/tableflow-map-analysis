"""AI Map Analysis node — 3-level progressive extraction of cartographic metadata.

Level 1 (Scan):     Thumbnail (~500px) → visual impression + locate TEXT regions.
Level 2 (Read):     High-res OCR of text regions → feed text back to thumbnail →
                    AI now understands the map → marks border + map body regions.
Level 3 (Explore):  High-res crops of borders + map body → coordinates, place
                    names, terrain features.
Synthesis:          Combine all levels into 21 AI fields + 2 regex fields.
"""

import json
import asyncio
import base64
import os
import re
import math
import io
import uuid
from datetime import datetime
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField
from ..providers.registry import call_vision_llm, call_vision_conversation, get_provider_id_for_model
from ..providers.base import LLMResponse, LLMUsage
from ..engine.context import build_data_preview
from .llm_utils import extract_json, clean_cell
from .ai_vision import _relative_image_path
from ..providers.google_provider import GeminiRecitationError
from ..routers.prompt_templates import get_effective_template as _get_tmpl
from ..routers.map_knowledge import get_knowledge_for_phase as _get_kb
from ..routers.fewshot import get_fewshot_messages as _get_fewshot

# Directory for region-preview images
_PREVIEW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage", "map_previews")
)

# Directory for debug prompt logs and archives
_DEBUG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage", "map_debug")
)

# ── Fixed output schema ──────────────────────────────────────────────────────

MAP_FIELDS: list[tuple[str, str]] = [
    # ── Text / OCR fields ──
    ("title",            "map_title"),
    ("date_text",        "map_date"),
    ("date_year",        "map_date_year"),
    ("publisher",        "map_publisher"),
    ("scale_text",       "map_scale"),
    ("scale_ratio",      "map_scale_ratio"),
    ("projection",       "map_projection"),
    ("edition",          "map_edition"),
    ("coordinates_text", "map_coordinates"),
    ("bbox_west",        "map_bbox_west"),
    ("bbox_east",        "map_bbox_east"),
    ("bbox_south",       "map_bbox_south"),
    ("bbox_north",       "map_bbox_north"),
    ("place_names",      "map_place_names"),
    ("legend_content",   "map_legend_content"),
    ("notes",            "map_notes"),
    # ── Visual / classification fields ──
    ("map_type",         "map_type"),
    ("subject",          "map_subject"),
    ("coverage",         "map_coverage"),
    ("country",          "map_country"),
    ("province",         "map_province"),
    ("city",             "map_city"),
    ("district",         "map_district"),
    ("medium",           "map_medium"),
    ("language",         "map_language"),
    ("condition",        "map_condition"),
    ("has_insets",       "map_has_insets"),
    ("description",      "map_description"),
]

# ── Canonical type-specific column order (grouped by category) ──────────────
# Columns not listed here will be appended alphabetically at the end.
_TS_COLUMN_ORDER: list[str] = [
    # ── Grid / Coordinate ──
    "ts_grid_system",
    "ts_grid_zone",
    "ts_grid_interval",
    "ts_grid_easting_range",
    "ts_grid_northing_range",
    "ts_magnetic_declination",
    "ts_coordinate_system",
    "ts_datum",
    # ── Terrain / Elevation ──
    "ts_contour_interval",
    "ts_elevation_range",
    "ts_elevation_unit",
    "ts_highest_point",
    "ts_relief",
    # ── Hydrographic / Nautical ──
    "ts_depth_range",
    "ts_depth_unit",
    "ts_tidal_datum",
    "ts_navigation_aids",
    "ts_chart_number",
    # ── Geological ──
    "ts_rock_types",
    "ts_geological_period",
    "ts_stratigraphic_units",
    "ts_mineral_deposits",
    # ── Survey / Cadastral ──
    "ts_lot_numbers",
    "ts_parish",
    "ts_hundred",
    "ts_land_parcels",
    "ts_surveyor",
    "ts_survey_date",
    "ts_survey_reference",
    # ── Plan / Engineering ──
    "ts_plan_number",
    "ts_drawing_number",
    "ts_engineer",
    "ts_approval_date",
    # ── Thematic / Classification ──
    "ts_theme",
    "ts_data_source",
    "ts_classification_method",
    # ── Celestial ──
    "ts_star_magnitude_range",
    "ts_epoch",
]


def _reorder_ts_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder ts_ columns by canonical grouping; non-ts_ columns stay in place."""
    all_cols = list(df.columns)
    ts_cols = [c for c in all_cols if c.startswith("ts_")]
    if not ts_cols:
        return df
    non_ts = [c for c in all_cols if not c.startswith("ts_")]
    # Sort ts_ columns: canonical order first, then alphabetical remainder
    order_map = {c: i for i, c in enumerate(_TS_COLUMN_ORDER)}
    max_idx = len(_TS_COLUMN_ORDER)
    ts_sorted = sorted(ts_cols, key=lambda c: (order_map.get(c, max_idx), c))
    return df[non_ts + ts_sorted]


# ── Dublin Core export ─────────────────────────────────────────────────────
# Map fields → DCMI Metadata Terms (https://www.dublincore.org/specifications/dublin-core/dcmi-terms/)
# Output column order (added at end of DataFrame, after ts_ columns)
_DC_COLUMN_ORDER: list[str] = [
    "dc:identifier",
    "dc:title",
    "dc:creator",
    "dc:publisher",
    "dc:date",
    "dcterms:created",
    "dcterms:hasVersion",
    "dc:type",
    "dc:format",
    "dcterms:medium",
    "dcterms:extent",
    "dc:language",
    "dc:subject",
    "dc:coverage",
    "dcterms:spatial",
    "dc:description",
    "dcterms:conformsTo",
]

# ISO 639-1 mapping for common languages (best-effort)
_LANG_ISO = {
    "english": "en", "french": "fr", "german": "de", "spanish": "es",
    "italian": "it", "portuguese": "pt", "russian": "ru", "chinese": "zh",
    "japanese": "ja", "arabic": "ar", "dutch": "nl", "latin": "la",
}


def _to_iso_lang(s: str) -> str:
    """Best-effort conversion of a language string to ISO 639-1 code."""
    if not s:
        return ""
    parts = [p.strip() for p in str(s).split(",") if p.strip()]
    out = []
    for p in parts:
        key = p.lower()
        if len(key) == 2:
            out.append(key)
        else:
            out.append(_LANG_ISO.get(key, p))
    return ", ".join(out)


def _dcmi_box(west, east, south, north) -> str:
    """Encode bbox values into DCMI Box format. Returns '' if any value missing."""
    def _num(v):
        try:
            if v == "" or v is None or (isinstance(v, str) and v.strip().upper() == "N/A"):
                return None
            return float(v)
        except (ValueError, TypeError):
            return None
    w, e, s, n = _num(west), _num(east), _num(south), _num(north)
    if None in (w, e, s, n):
        return ""
    return (
        f"name=Bounding Box; northlimit={n}; southlimit={s}; "
        f"westlimit={w}; eastlimit={e}; projection=WGS84"
    )


def _join_nonempty(values, sep: str = "; ") -> str:
    """Join values, skipping empty/N/A entries."""
    out = []
    seen = set()
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if not s or s.upper() == "N/A":
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return sep.join(out)


def _add_dublin_core_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add Dublin Core / DCTERMS columns derived from existing extracted fields.
    Original columns are preserved unchanged. DC columns are appended at the end."""
    if df.empty:
        return df

    def _get(row, col, default=""):
        if col not in df.columns:
            return default
        v = row.get(col, default)
        if v is None:
            return default
        if isinstance(v, float) and pd.isna(v):
            return default
        return v

    rows_dc: list[dict] = []
    for _, row in df.iterrows():
        title = _get(row, "map_title")
        date_text = _get(row, "map_date")
        date_year = _get(row, "map_date_year")
        publisher = _get(row, "map_publisher")
        edition = _get(row, "map_edition")
        scale_text = _get(row, "map_scale")
        scale_ratio = _get(row, "map_scale_ratio")
        projection = _get(row, "map_projection")
        map_type = _get(row, "map_type")
        subject = _get(row, "map_subject")
        coverage = _get(row, "map_coverage")
        country = _get(row, "map_country")
        province = _get(row, "map_province")
        city = _get(row, "map_city")
        district = _get(row, "map_district")
        place_names = _get(row, "map_place_names")
        medium = _get(row, "map_medium")
        language = _get(row, "map_language")
        condition = _get(row, "map_condition")
        description = _get(row, "map_description")
        notes = _get(row, "map_notes")
        legend = _get(row, "map_legend_content")
        coords_text = _get(row, "map_coordinates")
        width_cm = _get(row, "map_width_cm", 0)
        height_cm = _get(row, "map_height_cm", 0)
        bbox_w = _get(row, "map_bbox_west")
        bbox_e = _get(row, "map_bbox_east")
        bbox_s = _get(row, "map_bbox_south")
        bbox_n = _get(row, "map_bbox_north")
        filename = _get(row, "filename")

        # dcterms:extent — physical dimensions
        try:
            w_v = float(width_cm) if width_cm not in ("", None) else 0
            h_v = float(height_cm) if height_cm not in ("", None) else 0
        except (ValueError, TypeError):
            w_v = h_v = 0
        extent = f"{w_v:g} cm × {h_v:g} cm" if w_v > 0 and h_v > 0 else ""

        # dcterms:spatial — DCMI Box + textual coverage
        spatial_parts = []
        box = _dcmi_box(bbox_w, bbox_e, bbox_s, bbox_n)
        if box:
            spatial_parts.append(box)
        if coords_text and str(coords_text).strip().upper() != "N/A":
            spatial_parts.append(str(coords_text).strip())
        spatial = " | ".join(spatial_parts)

        # dc:coverage — admin hierarchy + place names
        coverage_value = _join_nonempty(
            [coverage, country, province, city, district, place_names]
        )

        # dc:description — main description + notes + legend + scale/projection metadata
        desc_parts = []
        if description and str(description).strip().upper() != "N/A":
            desc_parts.append(str(description).strip())
        scale_meta = []
        if scale_text and str(scale_text).strip().upper() != "N/A":
            scale_meta.append(f"Scale: {scale_text}")
        if scale_ratio and str(scale_ratio).strip() not in ("", "N/A"):
            try:
                sr = int(float(scale_ratio))
                scale_meta.append(f"Scale ratio: 1:{sr}")
            except (ValueError, TypeError):
                pass
        if projection and str(projection).strip().upper() != "N/A":
            scale_meta.append(f"Projection: {projection}")
        if scale_meta:
            desc_parts.append(" — ".join(scale_meta))
        if notes and str(notes).strip().upper() != "N/A":
            desc_parts.append(f"Notes: {notes}")
        if legend and str(legend).strip().upper() != "N/A":
            desc_parts.append(f"Legend: {legend}")
        if condition and str(condition).strip().upper() != "N/A":
            desc_parts.append(f"Condition: {condition}")
        dc_description = " ; ".join(desc_parts)

        # dc:type — map maps to DCMI Type "Image" + cartographic refinement
        if map_type and str(map_type).strip().upper() != "N/A":
            dc_type = f"Image; cartographic ({map_type})"
        else:
            dc_type = "Image; cartographic"

        # dc:format — physical medium + format
        format_parts = []
        if medium and str(medium).strip().upper() != "N/A":
            format_parts.append(str(medium).strip())
        if extent:
            format_parts.append(extent)
        dc_format = "; ".join(format_parts)

        # dc:subject — keywords + map_type
        subject_value = _join_nonempty([subject, map_type], sep=", ")

        # dc:date — prefer printed date_text, fall back to year
        try:
            year_int = int(float(date_year)) if date_year not in ("", None) else None
        except (ValueError, TypeError):
            year_int = None
        if date_text and str(date_text).strip() not in ("", "N/A"):
            dc_date = str(date_text).strip()
        elif year_int:
            dc_date = str(year_int)
        else:
            dc_date = ""

        rec = {
            "dc:identifier": str(filename) if filename else "",
            "dc:title": str(title) if title and str(title).strip().upper() != "N/A" else "",
            "dc:creator": "",  # not currently extracted
            "dc:publisher": str(publisher) if publisher and str(publisher).strip().upper() != "N/A" else "",
            "dc:date": dc_date,
            "dcterms:created": str(year_int) if year_int else "",
            "dcterms:hasVersion": str(edition) if edition and str(edition).strip().upper() != "N/A" else "",
            "dc:type": dc_type,
            "dc:format": dc_format,
            "dcterms:medium": str(medium) if medium and str(medium).strip().upper() != "N/A" else "",
            "dcterms:extent": extent,
            "dc:language": _to_iso_lang(str(language) if language else ""),
            "dc:subject": subject_value,
            "dc:coverage": coverage_value,
            "dcterms:spatial": spatial,
            "dc:description": dc_description,
            "dcterms:conformsTo": "DCMI Metadata Terms",
        }
        rows_dc.append(rec)

    # Append DC columns to the original DataFrame
    dc_df = pd.DataFrame(rows_dc, index=df.index, columns=_DC_COLUMN_ORDER)
    out = pd.concat([df, dc_df], axis=1)
    return out


# Regex for extracting physical dimensions from filename (e.g. "71.5cm X 106.6cm")
_DIM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*cm\s*[xX×]\s*(\d+(?:\.\d+)?)\s*cm",
    re.IGNORECASE,
)


def _extract_dimensions_cm(filename: str) -> tuple[float, float]:
    """Extract (width_cm, height_cm) from filename. Returns (0, 0) if not found."""
    m = _DIM_RE.search(filename)
    if m:
        return float(m.group(1)), float(m.group(2))
    return 0.0, 0.0

# ── Institutional cataloguing prefix (appended to system prompts on retry) ──
_CATALOGUE_PREFIX = """\
IMPORTANT: This analysis is performed by an institutional archive (library / \
geographic society) for cataloguing items in their own collection. The goal \
is to extract structured metadata (titles, dates, publishers, coordinates) \
for a catalogue database — NOT to reproduce or redistribute content. \
Output ONLY structured JSON metadata fields, never full reproductions."""


def _make_vision_message(text: str, image_b64: str, media_type: str) -> dict:
    """Build a provider-neutral user message with image + text."""
    return {
        "role": "user",
        "content": [
            {"type": "image", "data": image_b64, "media_type": media_type},
            {"type": "text", "text": text},
        ],
    }


def _make_assistant_message(text: str) -> dict:
    """Build a provider-neutral assistant message."""
    return {"role": "assistant", "content": text}


def _bbox_to_position_desc(bbox: list[float]) -> str:
    """Convert [x%, y%, w%, h%] to a human-readable position description."""
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    if cy < 33:
        v = "top"
    elif cy > 67:
        v = "bottom"
    else:
        v = "center"
    if cx < 33:
        h_pos = "left"
    elif cx > 67:
        h_pos = "right"
    else:
        h_pos = "center"
    if v == "center" and h_pos == "center":
        return "center of the map"
    if v == "center":
        return f"{h_pos} side of the map"
    if h_pos == "center":
        return f"{v} of the map"
    return f"{v}-{h_pos} area of the map"


def _sanitize_bbox(bbox: list, label: str = "") -> list[float]:
    """Validate and clamp a bbox [x%, y%, w%, h%] from AI output.

    Only does basic safety clamping — does NOT try to second-guess AI
    positioning, as small drifts are normal and aggressive correction
    can make things worse.
    """
    if not bbox or len(bbox) != 4:
        return [0.0, 0.0, 100.0, 100.0]

    x, y, w, h = [float(v) for v in bbox]

    # Clamp dimensions to reasonable range
    w = max(1.0, min(100.0, w))
    h = max(1.0, min(100.0, h))

    # Clamp origin so box stays within image
    x = max(0.0, min(100.0 - w, x))
    y = max(0.0, min(100.0 - h, y))

    return [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]


def _sanitize_regions(regions: list[dict], phase: str = "") -> list[dict]:
    """Sanitize bbox in all regions, return new list with fixed bboxes."""
    result = []
    for r in regions:
        r2 = dict(r)
        raw_bbox = r2.get("bbox", [0, 0, 100, 100])
        r2["bbox"] = _sanitize_bbox(raw_bbox, r2.get("label", ""))
        r2["_raw_bbox"] = raw_bbox  # keep original for debugging
        result.append(r2)
    return result


async def _call_with_recitation_retry(
    model, system, user_text, image_b64, image_mime,
    max_tokens, api_key, context=None, row_info=None,
) -> LLMResponse:
    """Call vision LLM; on Gemini recitation block, retry with catalogue prefix.
    Returns LLMResponse with text and usage statistics."""
    try:
        return await call_vision_llm(
            model, system, user_text,
            image_b64, image_mime, max_tokens, api_key,
        )
    except GeminiRecitationError:
        # Retry with institutional cataloguing framing
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": "Gemini RECITATION block — retrying with "
                         "catalogue framing...",
            })
        retry_system = _CATALOGUE_PREFIX + "\n\n" + system
        return await call_vision_llm(
            model, retry_system, user_text,
            image_b64, image_mime, max_tokens, api_key,
        )


async def _call_conversation_with_recitation_retry(
    model, system, messages, max_tokens, api_key, context=None, row_info=None,
) -> LLMResponse:
    """Call vision conversation; on Gemini recitation block, retry with catalogue prefix.
    Returns LLMResponse with text and usage statistics."""
    try:
        return await call_vision_conversation(
            model, system, messages, max_tokens, api_key,
        )
    except GeminiRecitationError:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": "Gemini RECITATION block — retrying with "
                         "catalogue framing...",
            })
        retry_system = _CATALOGUE_PREFIX + "\n\n" + system
        return await call_vision_conversation(
            model, retry_system, messages, max_tokens, api_key,
        )


# Fields the critic should never touch (metadata, structural, regex-derived)
_CRITIC_SKIP_FIELDS = {
    "confidence", "_evidence", "type_specific",
    "needs_crop", "high", "low",
}

# Numeric fields — when demoted, write "" not ""
_NUMERIC_FIELD_KEYS = {
    "date_year", "scale_ratio",
    "bbox_west", "bbox_east", "bbox_south", "bbox_north",
}


def _build_claims_for_critic(merged: dict) -> dict:
    """Extract auditable claims from merged extraction (skip structural fields)."""
    claims = {}
    for k, v in merged.items():
        if k in _CRITIC_SKIP_FIELDS:
            continue
        # Skip empty / N/A — nothing to audit
        if v is None:
            continue
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped or stripped.upper() == "N/A":
                continue
        claims[k] = v
    # Include type_specific entries flattened for audit
    ts = merged.get("type_specific") or {}
    if isinstance(ts, dict):
        for tk, tv in ts.items():
            if tv is None:
                continue
            if isinstance(tv, str):
                s = tv.strip()
                if not s or s.upper() == "N/A":
                    continue
            claims[f"type_specific.{tk}"] = tv
    return claims


async def _run_critic(
    image_b64: str,
    media_type: str,
    filename: str,
    merged: dict,
    critic_model: str,
    critic_api_key: str,
    max_tokens: int,
    context=None,
    row_info=None,
) -> tuple[dict, dict, LLMUsage]:
    """Run the critic agent. Returns (revised_merged, audit_dict, usage).

    Policy:
    - 'from_external_knowledge' → field demoted to '' (or '' for numerics)
    - 'inferred_questionable' → kept, but flagged in audit dict
    - other levels → kept unchanged

    Critic may only DEMOTE values, never ADD or CHANGE them.
    """
    claims = _build_claims_for_critic(merged)
    if not claims:
        return merged, {}, LLMUsage()

    claims_json_str = json.dumps(claims, indent=2, ensure_ascii=False)
    user_text = CRITIC_USER.format(
        filename=filename, claims_json=claims_json_str
    )

    user_msg = _make_vision_message(user_text, image_b64, media_type)

    if context and row_info:
        await context.emit("ai_debug", {
            **row_info,
            "phase": "critic_start",
            "critic_model": critic_model,
            "claim_count": len(claims),
        })

    try:
        resp = await call_vision_conversation(
            critic_model, CRITIC_SYSTEM, [user_msg],
            max_tokens, critic_api_key,
        )
    except Exception as exc:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": f"Critic call failed: {exc}"[:500],
            })
        return merged, {}, LLMUsage()

    parsed = extract_json(resp.text) or {}
    audit = parsed.get("audit", {}) if isinstance(parsed, dict) else {}
    if not isinstance(audit, dict):
        audit = {}

    revised = dict(merged)
    revised_ts = dict(merged.get("type_specific") or {})
    corrections: list[dict] = []
    warnings: list[dict] = []

    for field, info in audit.items():
        if not isinstance(info, dict):
            continue
        evidence = (info.get("evidence") or "").strip().lower()
        note = (info.get("note") or "").strip()

        is_ts = field.startswith("type_specific.")
        ts_key = field[len("type_specific."):] if is_ts else None

        if evidence == "from_external_knowledge":
            # Demote to empty
            if is_ts:
                if ts_key in revised_ts:
                    old = revised_ts[ts_key]
                    revised_ts[ts_key] = ""
                    corrections.append({
                        "field": field, "old": old, "note": note,
                    })
            else:
                if field in revised and field not in _CRITIC_SKIP_FIELDS:
                    old = revised[field]
                    revised[field] = ""
                    corrections.append({
                        "field": field, "old": old, "note": note,
                    })
        elif evidence == "inferred_questionable":
            warnings.append({"field": field, "note": note})

    if revised_ts != (merged.get("type_specific") or {}):
        revised["type_specific"] = revised_ts

    if context and row_info:
        await context.emit("ai_debug", {
            **row_info,
            "phase": "critic_review",
            "audit": audit,
            "corrections": corrections,
            "warnings": warnings,
            "tokens": {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        })
        for corr in corrections:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "critic_correction",
                "field": corr["field"],
                "old_value": str(corr["old"])[:200],
                "note": corr["note"],
            })

    return revised, audit, resp.usage


# Thumbnail: high-res for better text/border recognition
_THUMBNAIL_DIM = 3840

# Preview image for region visualization
_PREVIEW_DIM = 1500

# Colors for different region types (RGB)
_REGION_COLORS = {
    "text":             (255, 0, 0),      # red
    "border":           (0, 100, 255),    # blue (legacy)
    "coordinate_strip": (0, 100, 255),    # blue
    "map_sample":       (0, 200, 0),      # green
}


# ═════════════════════════════════════════════════════════════════════════════
# Level 1: Thumbnail scan — visual impression + find TEXT regions
# ═════════════════════════════════════════════════════════════════════════════

L1_SYSTEM = """\
You are a cartographic analysis specialist. You will receive a VERY \
LOW-RESOLUTION thumbnail of a map (roughly 500 pixels). Your tasks:
1. Get an overall impression of the map (type, colors, medium, condition).
2. Locate ALL areas that contain READABLE TEXT — titles, labels, legends, \
notes, scale text, publisher info, annotations. These will be cropped at \
HIGH RESOLUTION for precise OCR in the next step.

Return JSON only. No markdown, no explanation."""

L1_USER = """\
Analyze this map thumbnail.
Filename: {filename}

Return a JSON object with two sections:

{{
  "overview": {{
    "rough_title": "title if you can read it even partially",
    "map_type": "topographic, geological, nautical, cadastral, thematic, sketch, plan, celestial, other",
    "medium": "lithograph, engraving, manuscript, printed, photocopy, other — plus color: full color, monochrome, sepia, hand colored",
    "condition": "comma-separated from: tears, foxing, stains, folds, discoloration, good",
    "has_insets": "no / yes: brief description",
    "brief": "one-sentence description of what this map appears to show"
  }},
  "text_regions": [
    {{
      "label": "descriptive_name",
      "bbox": [left_x_percent, top_y_percent, width_percent, height_percent],
      "hint": "what text you expect here"
    }}
  ]
}}

RULES for text_regions:
- bbox = [x%, y%, w%, h%] where x,y is the TOP-LEFT corner of the box, \
expressed as PERCENTAGES (0-100) of image width/height. \
Example: [10, 5, 30, 8] means a box starting at 10% from left edge, 5% \
from top edge, 30% wide, 8% tall. The origin (0,0) is the TOP-LEFT \
corner of the image.
- Include EVERY area with visible text: title block, subtitle, publisher line, \
legend/key text, scale text, margin notes, handwritten annotations, inset \
titles, edition text, copyright lines, etc.
- The MOST IMPORTANT region is the largest/main title — always include it.
- CRITICAL for titles: Make the bbox GENEROUSLY LARGE to capture the ENTIRE \
title including any subtitle or secondary line below/above it. It is much \
better to include extra whitespace than to cut off part of the title text. \
Add at LEAST 5% extra padding on ALL sides beyond the visible title text. \
If there is a subtitle line (e.g. "Showing Railways and Telegraph Lines" \
below the main title), include BOTH lines in a SINGLE bbox with padding. \
Common mistake: placing the title bbox on just the FIRST LINE of a \
multi-line title block. Always look BELOW the main title line for \
subtitles, attribution, or secondary text — wrap ALL lines in ONE bbox.
- Keep bbox TIGHT around other text (non-title), not the whole map.
- Do NOT include map body areas or borders yet — only text blocks.
- Typical labels: "main_title", "subtitle", "legend_text", "scale_text", \
"publisher_info", "notes", "margin_text_top", "margin_text_bottom", \
"inset_title", "edition_info", "copyright"."""


# ═════════════════════════════════════════════════════════════════════════════
# Level 2a: High-res text OCR
# ═════════════════════════════════════════════════════════════════════════════

L2A_SYSTEM = """\
You are a precision OCR specialist for cartographic documents. \
You will receive a HIGH-RESOLUTION crop from a map, along with context \
about the map itself. Use this context to help you interpret ambiguous \
characters, abbreviations, and symbols. Return JSON only."""

L2A_USER = """\
This is a high-resolution crop of the "{label}" area from a map.
Hint: {hint}

═══ MAP CONTEXT (from thumbnail overview) ═══
{context}

Read ALL text visible in this crop. Be precise — copy text exactly as printed, \
including punctuation, line breaks, and any symbols or numbers.
Use the context above to help interpret abbreviations, faded text, or \
ambiguous characters (e.g. knowing the map covers South Australia helps \
distinguish "S.A." from other abbreviations).
Return:
{{
  "text": "all text content, preserving line breaks with \\n"
}}"""


# ═════════════════════════════════════════════════════════════════════════════
# Level 2b: Back to thumbnail WITH text knowledge → smart region planning
# ═════════════════════════════════════════════════════════════════════════════

L2B_SYSTEM = """\
You are a cartographic analysis specialist. You previously scanned this map \
at low resolution and identified text regions. Those text regions have now \
been read at high resolution. Using this new understanding of what the map \
is about, plan which areas of the MAP BODY and COORDINATE EDGES to \
examine next at high resolution.

Return JSON only. No markdown, no explanation."""

L2B_USER = """\
You are looking at the same map thumbnail again.
Filename: {filename}

Here is what we already know from the text regions we read:

═══ OVERVIEW (from first scan) ═══
{overview_json}

═══ TEXT OCR RESULTS (read at high resolution) ═══
{ocr_json}

Now that you understand what this map is about, identify which areas of \
the MAP BODY and COORDINATE EDGES should be examined at high resolution.

Return:
{{
  "understanding": "1-2 sentences summarizing what you now know about this map",
  "visual_update": {{
    "subject": "refined subject keywords, comma-separated (e.g. mining, transport, pastoral)",
    "coverage": "refined geographic coverage description",
    "language": "language name(s), comma-separated (e.g. English, Spanish)"
  }},
  "map_regions": [
    {{
      "label": "region_name",
      "type": "coordinate_strip / map_sample",
      "bbox": [left_x_percent, top_y_percent, width_percent, height_percent],
      "hint": "what to look for here"
    }}
  ]
}}

REGION TYPES (choose the right one):
- "coordinate_strip": narrow strips along map edges where PRINTED \
COORDINATE LABELS are visible — latitude/longitude numbers in \
degrees/minutes/seconds, grid reference numbers, or scale indicators. \
IMPORTANT: Only select edges that have ACTUAL COORDINATE DATA \
(numbers like 138°E, 30°S, etc.) printed along them. \
DO NOT select the photographic edge where the map paper meets the \
background — that is NOT a coordinate strip. \
⚠️ EDGE DISAMBIGUATION: Many map images (especially photographs of \
physical maps) have MULTIPLE PARALLEL LINES near each edge: \
  (1) The PHOTO EDGE — where the image file ends (outermost). \
  (2) The PAPER EDGE — where the physical map sheet ends. \
  (3) The MAP'S PRINTED BORDER — a ruled/drawn line with coordinate \
      tick marks and labels printed along it (innermost of the three). \
Your coordinate_strip bbox must target line (3) — the PRINTED BORDER \
with actual coordinate numbers. Do NOT place the bbox on (1) or (2). \
If you see a white/grey margin between the map content and the image \
edge, the printed coordinate labels are INSIDE that margin, closer \
to the map content. Place your bbox on the printed labels, not on \
the outer paper/photo edge. \
Use separate regions for each edge with descriptive names: \
  - "longitude_labels_top" or "longitude_labels_bottom" for top/bottom \
edges that show LONGITUDE values (e.g. 138°E, 139°E, 140°E). \
  - "latitude_labels_left" or "latitude_labels_right" for left/right \
edges that show LATITUDE values (e.g. 30°S, 31°S, 32°S). \
  - "scale_bar" for a region containing the scale indicator/bar. \
Keep coordinate strips as NARROW STRIPS covering just the labels \
(height or width ~5-10%). \
CRITICAL: Make coordinate_strip bbox WIDER/TALLER than you think — \
extend at least 2-3% beyond the visible labels to avoid cutting them \
off. Use the TEXT OCR RESULTS above to confirm where coordinate \
labels actually appear — if OCR found numbers at certain edges, \
place your coordinate_strip bbox exactly there, not where you \
vaguely remember from the thumbnail.
- "map_sample": sections of the MAP BODY itself — to identify place \
names, terrain features, settlements, rivers, roads. Pick 2-4 areas \
that seem most interesting or information-rich based on what you now \
know about the map's subject and coverage.

RULES for bbox:
- bbox = [x%, y%, w%, h%] where x,y is the TOP-LEFT corner of the box, \
expressed as PERCENTAGES (0-100) of image width/height. \
Example: [10, 5, 30, 8] means a box starting at 10% from left edge, 5% \
from top edge, 30% wide, 8% tall. The origin (0,0) is the TOP-LEFT \
corner of the image.
- "coordinate_strip" regions: narrow strips along the edges WHERE \
COORDINATE LABELS ARE VISIBLE. If an edge has no printed coordinate \
labels, DO NOT create a coordinate_strip region for it — skip it. \
Each strip bbox must cover the ACTUAL printed coordinate numbers — \
cross-check with the OCR results to verify positioning.
- "map_sample" regions: medium rectangles (~15-25% of map dimensions) \
in different parts of the map body.
- If the map has NO visible coordinates on ANY edge, do NOT \
create any coordinate_strip regions. Only create map_sample regions.
- Focus map_sample regions on areas with dense features or text.
- Make sure bbox values are INSIDE the actual map content area, not \
on the photographic background or empty white margins."""


# ═════════════════════════════════════════════════════════════════════════════
# Level 3: High-res map body / coordinate strip analysis
# ═════════════════════════════════════════════════════════════════════════════

L3_SYSTEM_COORDINATE = """\
You are a cartographic coordinate and scale extraction specialist. \
You will receive a HIGH-RESOLUTION crop of a map edge strip showing \
coordinate labels or scale indicators, along with context about the map. \
Use the context to determine hemisphere (N/S, E/W) and expected \
coordinate ranges. Return JSON only."""

L3_USER_COORDINATE = """\
This is a high-resolution crop of the "{label}" strip from a map.
Location: {position}
Expected content: {expected_type}
Hint: {hint}

═══ MAP CONTEXT ═══
{context}

═══ OTHER REGIONS BEING EXAMINED ═══
{other_regions}

Answer these questions precisely based on what you see in this strip:

1. CONFIRM TYPE: Based on its position ({position}) and name "{label}", \
this strip is expected to contain {expected_type}. \
Confirm: is this what you see? If the strip appears blank or shows \
something different, describe what is actually visible.

2. RANGE: Read ALL coordinate labels visible, from one end to the other. \
List every single value you can see. What is the minimum value? \
What is the maximum value? Include hemisphere (N/S/E/W) or grid units.

3. PRECISION: Where exactly are the labels positioned on this strip? \
At tick marks along a ruled line? Printed above/below or left/right \
of the line? What is the spacing between labels?

4. SCALE: Is there any scale bar, distance indicator, or representative \
fraction visible in this strip? If so, read it precisely.

BE CONCISE: List only the actual coordinate/scale values. Do not describe \
what you see in detail — just fill in the fields below precisely.

Return:
{{
  "coordinates": "all coordinate values WITH hemisphere labels in order \
(e.g. '138°E 138°30'E 139°E' or '30°S 31°S 32°S')",
  "coord_type": "latitude / longitude / grid / scale / mixed",
  "range_min": "smallest coordinate value with unit (e.g. '138°E' or '30°S')",
  "range_max": "largest coordinate value with unit (e.g. '141°E' or '38°S')",
  "grid_refs": "grid reference numbers if any",
  "scale_info": "scale bar reading or representative fraction if visible \
(e.g. '1 inch = 4 miles' or '1:250,000')",
  "other": "any other markings or labels"
}}"""

L3_SYSTEM_SAMPLE = """\
You are a cartographic content analyst. \
You will receive a HIGH-RESOLUTION crop from the body of a map, along with \
context about the map. Use the context to help interpret place names and \
features. Return JSON only."""

L3_USER_SAMPLE = """\
This is a high-resolution crop from the body of a map.
Region: {label} — located in the {position}
Hint: {hint}

═══ MAP CONTEXT ═══
{context}

═══ OTHER REGIONS BEING EXAMINED ═══
{other_regions}

Describe what is visible in this map section:
- Place names (towns, cities, stations, homesteads, geographic features)
- Terrain features (mountains, rivers, creeks, lakes, coastline)
- Infrastructure (roads, railways, tracks, telegraph lines)
- Land use indicators (pastoral runs, mining claims, reserves, parks)
- Contour lines, spot heights, or depth markings with values
- Any printed text or labels

BE CONCISE: Keep your response compact. List at most 20 place names \
(pick the most significant). Describe features in 1-2 sentences max.

Return:
{{
  "place_names": ["list", "of", "significant", "place", "names"],
  "features": "brief description of terrain and infrastructure",
  "labels": "any other text or numeric labels visible",
  "detail_level": "high / medium / low"
}}"""


# ═════════════════════════════════════════════════════════════════════════════
# Synthesis: combine everything into 21 structured fields
# ═════════════════════════════════════════════════════════════════════════════

SYNTH_SYSTEM = """\
You are a cartographic metadata specialist. Combine all the multi-level \
analysis data into final structured catalogue metadata. \
Output STANDARDIZED, machine-friendly values. Return JSON only."""

SYNTH_USER = """\
Combine ALL data below into final structured metadata for this map.

═══ OVERVIEW (from thumbnail scan) ═══
{overview_json}

═══ TEXT OCR READINGS (from high-res text crops) ═══
{text_json}

═══ LEVEL 2 UNDERSTANDING (after reading text) ═══
{understanding_json}

═══ COORDINATE STRIP READINGS (from high-res longitude/latitude/scale strips) ═══
{coordinate_json}

═══ MAP BODY SAMPLES (from high-res map sections) ═══
{sample_json}

Return a JSON object with EXACTLY these fields (use "N/A" for not applicable, \
"" for not found/unreadable — NEVER use 0 for missing numbers):
{{
  "title": "exact map title from OCR",
  "date_text": "date as printed (e.g. 'December 1957')",
  "date_year": 1957,
  "publisher": "publisher/cartographer name ONLY — no roles or descriptions",
  "scale_text": "scale as printed (e.g. '1:63,360' or '1 inch to 1 mile')",
  "scale_ratio": 63360,
  "projection": "map projection if stated",
  "edition": "edition if stated",
  "coordinates_text": "lat/long range as text (e.g. '138°E-141°E, 30°S-38°S')",
  "bbox_west": -141.0,
  "bbox_east": -138.0,
  "bbox_south": -38.0,
  "bbox_north": -30.0,
  "place_names": "major place names, comma-separated, up to 15, deduplicated",
  "legend_content": "main legend entries if read",
  "notes": "printed notes or handwritten annotations",
  "map_type": "standard values only: topographic, geological, nautical, cadastral, thematic, sketch, plan, celestial, other",
  "subject": "keywords, comma-separated (e.g. mining, transport, pastoral)",
  "coverage": "geographic area description",
  "country": "country name(s) this map covers, comma-separated if multiple (e.g. 'Australia')",
  "province": "state/province/territory, comma-separated if multiple (e.g. 'South Australia')",
  "city": "major city or cities if the map is city-level or shows urban areas prominently",
  "district": "district/county/shire/local area if at that detail level",
  "medium": "format and color combined (e.g. 'printed, full color' or 'manuscript, hand colored')",
  "language": "language names, comma-separated (e.g. 'English' or 'English, Spanish')",
  "condition": "standard terms, comma-separated from: tears, foxing, stains, folds, discoloration, good",
  "has_insets": "no / yes: brief description",
  "description": "2-3 sentence catalogue description for researchers"
}}

RULES:
- BE CONCISE: Keep all string values as short as possible. Use comma-separated \
lists, not sentences. "place_names" should list at most 15 significant names. \
"description" should be 2-3 sentences max. Do not pad with unnecessary detail.
- Use ONLY information from the readings. Do NOT infer or guess.
- If a field is NOT APPLICABLE to this map type, write "N/A". \
If a field SHOULD exist but you CANNOT READ it, write "" (empty string). \
NEVER use 0 for missing numbers — 0 implies an actual zero value.
- "date_year": extract the 4-digit year from date_text. If ambiguous, use "".
- "publisher": just the name/organization — NOT "projected and drawn by X", \
just "X". If multiple, comma-separate names only.
- "scale_ratio": the DENOMINATOR only (e.g. 63360 for 1:63,360). If only \
text like "3in to a mile", convert: 3in/mile = 1:21,120. If unclear, use "". \
If the map has no scale (e.g. sketch), use "N/A".
- "bbox_*": decimal degrees. West and South are NEGATIVE for W/S hemispheres. \
Use the coordinate strip readings' "range_min", "range_max", and "coord_type" \
fields to determine the bounding box. For example, if the left strip has \
range_min="30°S" range_max="10°N" (latitude), and the top strip has \
range_min="80°W" range_max="35°W" (longitude), then: \
bbox_south=-30.0, bbox_north=10.0, bbox_west=-80.0, bbox_east=-35.0. \
If no coordinates found, use "".
- "map_type": MUST use ONLY the standard values listed above. If multiple \
apply, comma-separate (e.g. "thematic, nautical"). Use lowercase.
- "condition": MUST use ONLY standard terms listed above, comma-separated.
- "country"/"province"/"city"/"district": geographic admin hierarchy. \
Fill from broadest to narrowest based on what the map actually covers. \
A country-level map has country filled but province/city/district may be "". \
A city plan has all four filled. Use modern English names. Comma-separate if multiple.
- "place_names": combine from ALL map body samples, deduplicate.
- "description": write a useful catalogue summary to help a researcher \
decide if this map is relevant to their work.
- CELESTIAL / NON-GEOGRAPHIC MAPS: For maps that do NOT depict the Earth's \
surface (celestial charts, star maps, etc.), bbox_*, scale_ratio, scale_text, \
and coordinates_text MUST be "N/A". Do NOT fill bbox with celestial coordinates."""


# ═════════════════════════════════════════════════════════════════════════════
# Post-processing: cross-map review & refinement
# ═════════════════════════════════════════════════════════════════════════════

POST_PROCESS_SYSTEM = """\
You are a cartographic catalogue quality-assurance specialist. You will \
review the machine-extracted metadata for a batch of maps and REFINE each \
entry using cross-map context, domain knowledge, and the original vision \
outputs. Fix errors, fill gaps where you can confidently infer the answer, \
and improve consistency. Return JSON only."""

POST_PROCESS_USER = """\
Below is the metadata extracted from {count} maps in a single batch. Each \
entry includes the ORIGINAL VISION OUTPUTS (what the AI saw) and the \
CURRENT SYNTHESIS (what was filled in the table).

Your job:
1. Cross-reference entries — if multiple maps cover the same area, they \
should have consistent country/province/city values.
2. Fix obvious errors — e.g. coordinates with wrong hemisphere signs, \
inconsistent scale ratios, garbled place names.
3. Fill gaps — if map A's OCR found a publisher name that also appears \
on map B (same publisher, same series), fill it in for map B if missing.
4. Standardize — ensure country/province names use modern English names, \
date formats are consistent, map_type values use only the standard set.
5. Improve descriptions — make catalogue descriptions more useful.

═══ CROSS-MAP CONTEXT (summary of all maps) ═══
{cross_map_summary}

═══ MAP DATA TO REFINE ═══
{map_data_json}

Return a JSON array with one object per map, in the same order:
[
  {{
    "filename": "original filename",
    "refined": {{
      // same fields as synthesis, only include fields you are CHANGING
      // do NOT include unchanged fields
    }}
  }},
  ...
]

RULES:
- Only include fields you are actually changing/improving.
- If a field is correct, do NOT include it in "refined".
- Never invent data that has no basis in the vision outputs.
- If you cannot improve anything for a map, return {{"filename": "...", "refined": {{}}}}.
- Preserve ALL original data that is correct.
- The "refined" object uses the SAME field names as synthesis \
(title, date_text, date_year, publisher, country, province, city, etc.).
- You may also refine or add "type_specific" fields — a dict of \
map-type-specific metadata (e.g. contour_interval, depth_range, \
grid_system). Include the FULL type_specific dict if refining any part of it.
- For grid-coordinate-only maps: if you can determine the projection \
(e.g. MGA Zone 54, UTM Zone 55S) and estimate approximate lat/lon, \
refine bbox_west/east/south/north with your best estimate."""


# ═════════════════════════════════════════════════════════════════════════════
# Direct mode: single high-res pass + optional supplement crops
# ═════════════════════════════════════════════════════════════════════════════

DIRECT_SYSTEM = """\
You are a cartographic metadata extraction specialist. You will receive a \
HIGH-RESOLUTION image of a map. Extract ALL available structured metadata \
in a single pass.

Return JSON only. No markdown, no explanation."""

DIRECT_USER = """\
Analyze this map image and extract all structured metadata.
Filename: {filename}

Return a JSON object with EXACTLY these fields (use "N/A" for not applicable, \
"" for not found/unreadable — NEVER use 0 for missing numbers):
{{
  "title": "exact map title as printed on the map",
  "date_text": "date as printed (e.g. 'December 1957')",
  "date_year": 1957,
  "publisher": "publisher/cartographer name ONLY — no roles or descriptions",
  "scale_text": "scale as printed (e.g. '1:63,360' or '1 inch to 1 mile')",
  "scale_ratio": 63360,
  "projection": "map projection if stated",
  "edition": "edition if stated",
  "coordinates_text": "lat/long range as text (e.g. '138°E-141°E, 30°S-38°S')",
  "bbox_west": -141.0,
  "bbox_east": -138.0,
  "bbox_south": -38.0,
  "bbox_north": -30.0,
  "place_names": "major place names, comma-separated, up to 15",
  "legend_content": "main legend entries if readable",
  "notes": "printed notes or handwritten annotations",
  "map_type": "topographic, geological, nautical, cadastral, thematic, sketch, plan, celestial, other",
  "subject": "keywords, comma-separated (e.g. mining, transport, pastoral)",
  "coverage": "geographic area description",
  "country": "country name(s), comma-separated",
  "province": "state/province/territory, comma-separated",
  "city": "major city if city-level map",
  "district": "district/county/shire if at that detail level",
  "medium": "format and color (e.g. 'printed, full color')",
  "language": "language names, comma-separated",
  "condition": "standard terms: tears, foxing, stains, folds, discoloration, good",
  "has_insets": "no / yes: brief description",
  "description": "2-3 sentence catalogue description for researchers",
  "type_specific": {{
    // Additional fields specific to this map type. Include ONLY fields
    // that are APPLICABLE and VISIBLE on this map. Examples by map_type:
    // topographic: "contour_interval", "elevation_range", "highest_point", "datum"
    // nautical: "depth_range", "depth_unit", "tidal_datum", "navigation_aids", "chart_number"
    // geological: "rock_types", "geological_period", "stratigraphic_units", "mineral_deposits"
    // cadastral: "lot_numbers", "parish", "hundred", "land_parcels", "survey_reference"
    // thematic: "theme", "data_source", "classification_method"
    // sketch: "surveyor", "survey_date", "field_book_reference"
    // plan: "plan_number", "drawing_number", "engineer", "approval_date"
    // celestial: "star_magnitude_range", "coordinate_system", "epoch"
    // military/grid maps: "grid_system", "grid_zone", "magnetic_declination", "grid_interval"
    // any map: "contour_interval", "elevation_range", "depth_range", "grid_reference"
    // Use descriptive string values. Omit fields that are not applicable.
  }},
  "confidence": {{
    "high": ["list of field names you are confident about"],
    "low": ["list of field names you are uncertain about or could not read clearly"],
    "needs_crop": [
      {{
        "field": "field_name",
        "reason": "why this needs a closer look",
        "bbox": [left_x_percent, top_y_percent, width_percent, height_percent]
      }}
    ]
  }},
  "_evidence": {{
    "directly_visible": ["field names you OCR'd or visually counted from the image"],
    "inferred_from_visible": ["field names you DERIVED by calculation from visible data (e.g. scale_ratio computed from a printed scale bar; bbox computed from printed coordinate strip values)"],
    "from_external_knowledge": ["field names where the value came from your training data, NOT from visible content — this list MUST be empty"]
  }}
}}

RULES:
- Read ALL text visible: titles, legends, scale bars, coordinate labels, \
publisher info, margin notes, annotations.
- For coordinates: read the PRINTED degree/minute values along the map \
borders. Look for tick marks with numbers like 138°E, 30°S, etc.
- For maps using LOCAL GRID COORDINATES (e.g. Easting/Northing, Zone numbers), \
extract the grid system name and range into type_specific fields (grid_system, \
grid_zone, grid_easting_range, grid_northing_range). Leave bbox_* empty unless \
the map ALSO prints decimal degree marks visible on this scan.
- bbox_*: decimal degrees, derived ONLY from coordinate text PRINTED on this \
scan. West and South are NEGATIVE for W/S hemispheres. Do NOT estimate bbox \
from your knowledge of where a place is on Earth — if no coordinate text is \
visible, write "" for all four bbox fields.
- title: copy the EXACT text. Include subtitles on separate lines.
- "confidence.needs_crop": if you can SEE that a field exists but cannot \
READ it clearly (e.g. small text, blurry coordinates), provide a bbox \
for that area so we can crop and re-examine at higher resolution. \
bbox = [x%, y%, w%, h%] where x,y is TOP-LEFT corner as percentage of \
image dimensions.
- If you can read everything clearly, leave "needs_crop" as empty [].
- publisher: just the name, not "projected and drawn by X".
- scale_ratio: DENOMINATOR only (63360 for 1:63,360). Convert if needed.
- map_type: MUST use only the standard values listed above.
- type_specific: include ONLY fields relevant to this specific map type. \
Do NOT include fields that are not applicable — simply omit them.
- For fields that are NOT APPLICABLE to this map type (e.g. scale_ratio \
on a sketch with no scale), write "N/A" (the string).
- For fields that SHOULD exist but you CANNOT READ or FIND the value, \
write "" (empty string) for text, or "" for numbers. Do NOT write 0 — \
a zero implies an actual value of zero.
- Summary: "N/A" = not applicable; "" = not found; an actual value = found.
- CELESTIAL / NON-GEOGRAPHIC MAPS: For maps that do NOT depict the Earth's \
surface (celestial charts, star maps, constellation maps, etc.), the following \
fields MUST be "N/A": bbox_west, bbox_east, bbox_south, bbox_north, \
scale_ratio, scale_text, coordinates_text. Do NOT fill bbox with celestial \
coordinates (RA/Dec) — bbox is strictly for geographic (Earth) coordinates. \
Use type_specific for celestial coordinate info instead (e.g. coordinate_system, \
epoch, declination_range, right_ascension_range).
- NO EXTERNAL KNOWLEDGE: Never include information that is not visibly present \
on this scan. Do NOT add author full names, titles, or initials that you know \
from external sources but cannot see printed. Do NOT extrapolate place names, \
regions, or coordinate ranges from your knowledge of "what this map usually \
shows" — describe ONLY what you can see in this specific image. If the scan \
appears to be a partial/cropped view of a larger map, describe ONLY the \
visible portion.
- "_evidence": for EVERY non-empty field in your output (excluding "confidence" \
and "_evidence" itself), classify it into exactly ONE of:
  * "directly_visible" — you OCR'd the value or visually counted/observed it
  * "inferred_from_visible" — you derived it by calculation/conversion from \
visible data (e.g. converting "3in to a mile" to scale_ratio 21120; computing \
bbox_west from a printed coordinate strip reading "138°E")
  * "from_external_knowledge" — the value came from your training knowledge \
rather than the image. THIS LIST MUST BE EMPTY. If you cannot place a field \
in one of the first two buckets, set the field's value to "" instead of \
listing it here."""

DIRECT_SUPPLEMENT_SYSTEM = """\
You are a cartographic detail reader. You previously analyzed this map at \
full resolution but could not read certain details clearly. You now receive \
a HIGH-RESOLUTION CROP of a specific area. Extract the requested information. \
Return JSON only."""

DIRECT_SUPPLEMENT_USER = """\
This is a high-resolution crop from the map "{filename}".
Area: {label}
We need to read: {field} — {reason}

═══ WHAT WE ALREADY KNOW ═══
{context}

Read the content in this crop carefully and return:
{{
  "field": "{field}",
  "value": "the extracted value",
  "raw_text": "exact text you can see in this crop",
  "confident": true
}}

If you still cannot read it clearly, set "confident" to false and \
"value" to your best guess with a ? suffix."""


# ═════════════════════════════════════════════════════════════════════════════
# Critic / Verifier — independent agent that audits extraction for hallucination
# ═════════════════════════════════════════════════════════════════════════════

CRITIC_SYSTEM = """\
You are an independent cartographic fact-checker. You audit metadata that \
another AI extracted from a scanned map. Your ONLY job is to detect claims \
that came from the auditing AI's pretraining knowledge rather than from \
visible content on the scan.

You have ONE allowed action: classify each field's evidence level. You may \
NOT add new claims. You may NOT correct values. You may only flag fields \
that lack visual evidence.

Be especially vigilant for:
- Place names, regions, or coordinate ranges that aren't visible on this scan \
but might be "common knowledge" about the map subject
- Author/cartographer initials, full names, or titles not actually printed
- Bbox coordinates that span a wider area than the scan actually shows \
(e.g. a half-map scan with bbox claiming the full original area)
- Inferences that go beyond the visible content
- Information that would only be true of a famous published version of this \
map, but isn't actually in this scan

Return STRICT JSON only — no commentary."""

CRITIC_USER = """\
Audit the following extracted metadata against the attached map image.

Filename: {filename}

═══ EXTRACTED CLAIMS ═══
{claims_json}

═══ AUDIT INSTRUCTIONS ═══
For each non-empty field listed above (excluding "confidence" and "_evidence"), \
classify the evidence supporting its value:
- "directly_visible": text/feature is clearly OCR-able or visually present in the scan
- "inferred_correct": derived by sound calculation from visible data (e.g. \
scale conversion, bbox from printed coordinate strip)
- "inferred_questionable": derivation is weak, depends on assumptions, or \
extrapolates beyond visible content
- "from_external_knowledge": value cannot be located on the scan and was \
likely sourced from training knowledge of similar maps
- "cannot_verify": evidence is too small/unclear in this image to confirm

Return STRICT JSON:
{{
  "audit": {{
    "field_name_1": {{"evidence": "directly_visible", "note": ""}},
    "field_name_2": {{"evidence": "from_external_knowledge", "note": "USA and Alaska are not visible on this scan; appears to be sourced from knowledge of the full map"}},
    ...
  }}
}}

Notes (the "note" field) are REQUIRED for evidence levels \
"inferred_questionable" and "from_external_knowledge". Empty string is fine \
for the other levels.

Audit ONLY fields present in the input claims. Do not invent fields."""


# ═════════════════════════════════════════════════════════════════════════════
# Image helpers — all output as JPEG
#   Crops:     JPG quality=100 (no compression) — max detail within API limit
# ═════════════════════════════════════════════════════════════════════════════

_THUMB_QUALITY = 95     # high quality for readable text
_CROP_QUALITY = 100     # no compression — preserve every detail
_MAX_IMAGE_BYTES = 18 * 1024 * 1024  # API upload limit


def _fix_mode(img):
    """Convert exotic PIL modes to RGB for JPEG compatibility."""
    if img.mode in ("I", "I;16", "F"):
        return img.convert("RGB")
    if img.mode in ("LA", "RGBA", "PA", "P"):
        return img.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _pil_to_b64_jpg(img, quality: int = _CROP_QUALITY) -> tuple[str, str]:
    """Convert PIL Image to (base64_str, 'image/jpeg') at given quality."""
    img = _fix_mode(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def _make_thumbnail(img, dim: int = _THUMBNAIL_DIM):
    """Resize to small thumbnail, return PIL Image (not yet encoded)."""
    from PIL import Image
    w, h = img.size
    if max(w, h) <= dim:
        return img.copy()
    ratio = dim / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def _thumbnail_b64(img) -> tuple[str, str]:
    """Make thumbnail + encode as compressed JPG. Returns (b64, mime)."""
    thumb = _make_thumbnail(img)
    return _pil_to_b64_jpg(thumb, quality=_THUMB_QUALITY)


def _crop_region(img, bbox: list[float]):
    """Crop using percentage bbox [x%, y%, w%, h%] at original resolution."""
    w, h = img.size
    x_pct, y_pct, w_pct, h_pct = bbox
    pad = 2.0
    x1 = max(0, (x_pct - pad) / 100.0 * w)
    y1 = max(0, (y_pct - pad) / 100.0 * h)
    x2 = min(w, (x_pct + w_pct + pad) / 100.0 * w)
    y2 = min(h, (y_pct + h_pct + pad) / 100.0 * h)
    if x2 - x1 < 50:
        x2 = min(w, x1 + 50)
    if y2 - y1 < 50:
        y2 = min(h, y1 + 50)
    return img.crop((int(x1), int(y1), int(x2), int(y2)))


def _save_crop_to_disk(img, bbox: list[float], stem: str, label: str) -> str:
    """Save a crop to disk for frontend visualization. Returns saved path."""
    os.makedirs(_PREVIEW_DIR, exist_ok=True)
    crop = _crop_region(img, bbox)
    crop = _fix_mode(crop)
    # Save a medium-res version for display (max 800px)
    max_dim = max(crop.size)
    if max_dim > 800:
        ratio = 800 / max_dim
        crop = crop.resize(
            (int(crop.size[0] * ratio), int(crop.size[1] * ratio)),
            crop.__class__.LANCZOS if hasattr(crop.__class__, 'LANCZOS') else 1,
        )
    safe_label = re.sub(r'[^\w\-]', '_', label)[:60]
    fname = f"{stem}_{safe_label}.jpg"
    fpath = os.path.join(_PREVIEW_DIR, fname)
    crop.save(fpath, "JPEG", quality=85)
    return fpath


def _save_prompt_to_disk(
    stem: str, phase: str, label: str,
    system_prompt: str, user_prompt: str,
) -> str:
    """Save full AI prompts to disk for debugging. Returns saved path."""
    os.makedirs(_DEBUG_DIR, exist_ok=True)
    safe_label = re.sub(r'[^\w\-]', '_', label)[:60]
    fname = f"{stem}_{phase}_{safe_label}.txt"
    fpath = os.path.join(_DEBUG_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write("═══ SYSTEM PROMPT ═══\n")
        f.write(system_prompt)
        f.write("\n\n═══ USER PROMPT ═══\n")
        f.write(user_prompt)
    return fpath


def _archive_debug_logs(
    debug_log: list[dict],
    run_timestamp: str,
) -> str:
    """Archive all debug log entries to a timestamped JSON file."""
    os.makedirs(_DEBUG_DIR, exist_ok=True)
    fname = f"debug_archive_{run_timestamp}.json"
    fpath = os.path.join(_DEBUG_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(debug_log, f, indent=2, ensure_ascii=False, default=str)
    return fpath


def _crop_b64(img, bbox: list[float]) -> tuple[str, str, int, int]:
    """Crop at original resolution → JPG q=100 → fit within API limit.

    If JPG q=100 still exceeds 18 MB, reduce RESOLUTION (not quality).
    Returns (b64, mime, crop_w, crop_h).
    """
    from PIL import Image
    crop = _crop_region(img, bbox)
    crop = _fix_mode(crop)
    crop_w, crop_h = crop.size

    b64, mt = _pil_to_b64_jpg(crop, quality=_CROP_QUALITY)
    raw = len(base64.b64decode(b64))

    if raw <= _MAX_IMAGE_BYTES:
        return b64, mt, crop_w, crop_h

    # Over limit: shrink resolution, keep quality=100
    ratio = math.sqrt(_MAX_IMAGE_BYTES / raw) * 0.92
    crop = crop.resize(
        (int(crop_w * ratio), int(crop_h * ratio)), Image.LANCZOS
    )
    b64, mt = _pil_to_b64_jpg(crop, quality=_CROP_QUALITY)

    # Safety loop
    while len(base64.b64decode(b64)) > _MAX_IMAGE_BYTES and max(crop.size) > 512:
        cw, ch = crop.size
        crop = crop.resize((int(cw * 0.75), int(ch * 0.75)), Image.LANCZOS)
        b64, mt = _pil_to_b64_jpg(crop, quality=_CROP_QUALITY)

    return b64, mt, crop.size[0], crop.size[1]


def _draw_regions_preview(img_full, all_regions: list[dict],
                          save_path: str) -> str:
    """Draw color-coded bounding boxes + labels on a medium-res preview.

    - text regions   → RED
    - border regions → BLUE
    - map_sample     → GREEN

    `all_regions` is a combined list; each dict must have "type" and "label".
    Returns the absolute path of the saved PNG.
    """
    from PIL import Image, ImageDraw, ImageFont

    w, h = img_full.size
    if max(w, h) > _PREVIEW_DIM:
        ratio = _PREVIEW_DIM / max(w, h)
        preview = img_full.resize(
            (int(w * ratio), int(h * ratio)), Image.LANCZOS
        )
    else:
        preview = img_full.copy()

    if preview.mode != "RGB":
        preview = preview.convert("RGB")

    draw = ImageDraw.Draw(preview)
    pw, ph = preview.size

    font = None
    font_size = max(12, int(ph * 0.018))
    for fn in ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
               "LiberationSans-Regular.ttf"]:
        try:
            font = ImageFont.truetype(fn, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

    line_width = max(2, int(pw * 0.003))

    for region in all_regions:
        label = region.get("label", "?")
        rtype = region.get("type", "text")
        bbox = region.get("bbox", [0, 0, 100, 100])
        color = _REGION_COLORS.get(rtype, (255, 0, 0))

        x_pct, y_pct, w_pct, h_pct = bbox
        x1 = max(0, x_pct / 100.0 * pw)
        y1 = max(0, y_pct / 100.0 * ph)
        x2 = min(pw, (x_pct + w_pct) / 100.0 * pw)
        y2 = min(ph, (y_pct + h_pct) / 100.0 * ph)

        for offset in range(line_width):
            draw.rectangle(
                [x1 + offset, y1 + offset, x2 - offset, y2 - offset],
                outline=color,
            )

        tag = f" {label} [{rtype}] "
        try:
            bb = font.getbbox(tag) if font else None
            tw = bb[2] - bb[0] if bb else len(tag) * 7
            th = bb[3] - bb[1] if bb else 14
        except Exception:
            tw, th = len(tag) * 7, 14

        lx = x1
        ly = max(0, y1 - th - 2) if y1 > th + 4 else y1
        draw.rectangle([lx, ly, lx + tw + 4, ly + th + 4], fill=color)
        if font:
            draw.text((lx + 2, ly + 1), tag, fill=(255, 255, 255), font=font)
        else:
            draw.text((lx + 2, ly + 1), tag, fill=(255, 255, 255))

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    preview.save(save_path, format="PNG")
    return os.path.abspath(save_path)


# ═════════════════════════════════════════════════════════════════════════════
# Node
# ═════════════════════════════════════════════════════════════════════════════

class AIMapAnalysisNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="ai_map_analysis",
            label="AI Map Analysis",
            category="ai",
            icon="MapPin",
            color="#059669",
            description="3-level map analysis: scan → read text → explore "
                        "map body → structured metadata",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="mode",
                    label="Analysis Mode",
                    type="select",
                    default="direct",
                    options=[
                        {"value": "direct", "label": "Direct (high-res single pass + supplement)"},
                        {"value": "multilevel", "label": "Multi-level (L1→L2→L3→Synthesis)"},
                    ],
                    description="Direct: send full high-res image, extract everything at once. "
                                "Multi-level: progressive thumbnail→crop pipeline.",
                ),
                ConfigField(
                    name="model",
                    label="Model",
                    type="select",
                    default="",
                    options=[],
                    description="Vision-capable model (GPT-4o, Claude, Gemini)",
                ),
                ConfigField(
                    name="critic_model",
                    label="Critic Model (anti-hallucination)",
                    type="select",
                    default="",
                    options=[],
                    description="Optional second vision model that audits the "
                                "main extraction for hallucinated content. "
                                "Leave blank to disable. Adds ~30-50% to per-map cost.",
                ),
                ConfigField(
                    name="dublin_core_export",
                    label="Dublin Core columns",
                    type="boolean",
                    default=False,
                    description="Add Dublin Core / DCTERMS standard columns "
                                "(dc:title, dcterms:spatial, etc.) alongside "
                                "the original columns for library/archive interchange.",
                ),
                ConfigField(
                    name="image_column",
                    label="Image Column",
                    type="column_select",
                    required=True,
                    description="Column containing image file paths",
                ),
                ConfigField(
                    name="max_tokens",
                    label="Max Tokens",
                    type="number",
                    default=16000,
                    description="Maximum tokens per API response (high default to avoid truncation)",
                ),
                ConfigField(
                    name="concurrency",
                    label="Concurrency",
                    type="number",
                    default=0,
                    description="Parallel images (0 = auto). Each image makes "
                                "multiple API calls internally.",
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        if df.empty:
            return {"output": df}

        model = config.get("model", "")
        if not model:
            raise ValueError("No model selected.")

        image_column = config.get("image_column", "")
        if not image_column or image_column not in df.columns:
            raise ValueError(f"Image column '{image_column}' not found")

        max_tokens = int(config.get("max_tokens", 16000))
        raw_conc = int(config.get("concurrency", 0))
        concurrency = raw_conc if raw_conc > 0 else min(4, len(df))

        api_key = ""
        if context:
            provider_id = get_provider_id_for_model(model)
            api_key = context.get_api_key(provider_id)
        if not api_key:
            raise ValueError(f"No API key for '{model}'. Set it in Settings.")

        critic_model = (config.get("critic_model") or "").strip()
        critic_api_key = ""
        if critic_model and context:
            try:
                critic_provider_id = get_provider_id_for_model(critic_model)
                critic_api_key = context.get_api_key(critic_provider_id)
            except ValueError:
                critic_model = ""  # unknown model id — disable
            if critic_model and not critic_api_key:
                raise ValueError(
                    f"No API key for critic '{critic_model}'. Set it in Settings."
                )

        # Output columns
        original_columns = set(df.columns.tolist())
        # Physical dimensions from filename (regex, no AI needed)
        if "map_width_cm" not in df.columns:
            df["map_width_cm"] = 0.0
        if "map_height_cm" not in df.columns:
            df["map_height_cm"] = 0.0
        for idx_dim, row_dim in df.iterrows():
            fn = os.path.basename(str(row_dim.get(image_column, "")))
            w_cm, h_cm = _extract_dimensions_cm(fn)
            if w_cm > 0:
                df.at[idx_dim, "map_width_cm"] = w_cm
                df.at[idx_dim, "map_height_cm"] = h_cm
        for _, out_col in MAP_FIELDS:
            if out_col not in df.columns:
                df[out_col] = ""
        if "map_regions_preview" not in df.columns:
            df["map_regions_preview"] = ""
        new_columns = [c for c in df.columns if c not in original_columns]

        total = len(df)
        completed = 0
        skipped = 0
        analyzed = 0
        sem = asyncio.Semaphore(concurrency)

        def _has_image(val) -> bool:
            if pd.isna(val):
                return False
            s = str(val).strip()
            return bool(s) and s.lower() != "nan"

        rows_with_images = sum(1 for v in df[image_column] if _has_image(v))
        mode = config.get("mode", "direct")

        if on_progress:
            mode_label = "Direct" if mode == "direct" else "Multi-level"
            await on_progress(
                f"Map Analysis ({mode_label}): {rows_with_images} images"
            )

        # Store intermediate data per map for post-processing
        _map_raw_data: dict[int, dict] = {}   # idx → raw vision data

        # Accumulate all debug events for archival
        _debug_archive: list[dict] = []
        _run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Wrap context to intercept ai_debug events for archival
        _orig_emit = context.emit if context else None

        async def _archiving_emit(event_type: str, data: dict):
            """Emit event AND accumulate ai_debug for archival."""
            if event_type == "ai_debug":
                _debug_archive.append({
                    "ts": datetime.now().isoformat(),
                    **data,
                })
            if _orig_emit:
                await _orig_emit(event_type, data)

        # Monkey-patch context.emit to capture debug events
        if context:
            context.emit = _archiving_emit  # type: ignore

        def _save_prompt(
            stem: str, phase: str, label: str,
            sys_p: str, usr_p: str,
        ) -> str:
            """Save full prompt to disk and return path."""
            return _save_prompt_to_disk(stem, phase, label, sys_p, usr_p)

        # ── Process one map ───────────────────────────────────────────────

        async def process_map(i, idx, row):
            nonlocal completed, skipped, analyzed

            if not _has_image(row[image_column]):
                skipped += 1
                completed += 1
                return

            image_path = str(row[image_column]).strip()
            filename = os.path.basename(image_path)

            # Per-map token accumulator
            _token_total = {"input": 0, "output": 0}

            async with sem:
                try:
                    from PIL import Image
                    img_full = Image.open(image_path)
                    img_full = _fix_mode(img_full)
                    full_w, full_h = img_full.size

                    # ═══ LEVEL 1: Thumbnail scan ══════════════════════
                    # Compressed JPG — small & fast
                    if on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"L1 scanning ({full_w}x{full_h})..."
                        )
                    thumb_b64, thumb_mime = _thumbnail_b64(img_full)

                    if context:
                        thumb_sz = _make_thumbnail(img_full).size
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total,
                            "phase": "L1_scan",
                            "filename": filename,
                            "full_size": f"{full_w}x{full_h}",
                            "thumb_size": f"{thumb_sz[0]}x{thumb_sz[1]}",
                            "format": "JPG q=60",
                            "source_image": image_path,
                        })

                    _row = {"row": i + 1, "total": total,
                           "filename": filename}

                    # ── Conversation history for sequential chain ──
                    stem = os.path.splitext(filename)[0]
                    _l1_sys = _get_tmpl("L1_SYSTEM")
                    _l1_kb = _get_kb("L1")
                    if _l1_kb:
                        _l1_sys = _l1_sys + "\n\n" + _l1_kb
                    _l1_usr = _get_tmpl("L1_USER")
                    l1_prompt = _l1_usr.replace("{filename}", filename)

                    # Save L1 prompt to disk
                    l1_prompt_path = _save_prompt(
                        stem, "L1", "scan", _l1_sys, l1_prompt
                    )

                    # Inject L1 few-shot examples before L1 query
                    l1_fewshot = _get_fewshot("L1")
                    l1_user_msg = _make_vision_message(
                        l1_prompt, thumb_b64, thumb_mime)
                    l1_messages = l1_fewshot + [l1_user_msg] \
                        if l1_fewshot else [l1_user_msg]

                    l1_resp = await _call_conversation_with_recitation_retry(
                        model, _l1_sys,
                        l1_messages,
                        max_tokens, api_key,
                        context, _row,
                    )
                    l1_text = l1_resp.text
                    _token_total["input"] += l1_resp.usage.input_tokens
                    _token_total["output"] += l1_resp.usage.output_tokens
                    # Store clean conversation history (without few-shot)
                    conversation_history = [
                        l1_user_msg,
                        _make_assistant_message(l1_text),
                    ]
                    l1 = extract_json(l1_text)
                    overview = l1.get("overview", {})
                    text_regions_raw = l1.get("text_regions", [])
                    text_regions = _sanitize_regions(
                        text_regions_raw, "L1"
                    )

                    if context:
                        # Log any bbox corrections
                        corrections = [
                            f"{r['label']}: {r.get('_raw_bbox')} → {r['bbox']}"
                            for r in text_regions
                            if r.get("_raw_bbox") != r["bbox"]
                        ]
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total,
                            "phase": "L1_result",
                            "filename": filename,
                            "text_regions": len(text_regions),
                            "labels": [r.get("label", "?")
                                       for r in text_regions],
                            "prompt_path": l1_prompt_path,
                            "llm_output": l1_text[:2000],
                            **({"bbox_corrections": corrections}
                               if corrections else {}),
                        })

                    # Build context string from L1 overview for L2a/L3
                    _ctx_parts = [f"Filename: {filename}"]
                    if overview.get("rough_title"):
                        _ctx_parts.append(
                            f"Title (approx): {overview['rough_title']}")
                    if overview.get("map_type"):
                        _ctx_parts.append(
                            f"Type: {overview['map_type']}")
                    if overview.get("medium"):
                        _ctx_parts.append(
                            f"Medium: {overview['medium']}")
                    if overview.get("brief"):
                        _ctx_parts.append(
                            f"Description: {overview['brief']}")
                    map_context = "\n".join(_ctx_parts)

                    # ═══ LEVEL 2a: High-res OCR of text regions ═══════
                    if on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"L2a reading {len(text_regions)} text regions..."
                        )
                    ocr_results = {}

                    async def ocr_text_region(region: dict):
                        label = region.get("label", "unknown")
                        bbox = region.get("bbox", [0, 0, 100, 100])
                        hint = region.get("hint", "read all text")

                        try:
                            # Full-res crop → JPG q=100 (no compression)
                            crop_b64, crop_mime, cw, ch = _crop_b64(
                                img_full, bbox
                            )
                            # Save crop to disk for visualization
                            stem = os.path.splitext(filename)[0]
                            crop_disk_path = _save_crop_to_disk(
                                img_full, bbox, stem, label
                            )

                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "L2a_ocr",
                                    "filename": filename,
                                    "region": label,
                                    "crop_size": f"{cw}x{ch}",
                                    "format": "JPG q=100",
                                    "crop_path": crop_disk_path,
                                    "bbox": bbox,
                                })

                            _l2a_sys = _get_tmpl("L2A_SYSTEM")
                            _l2a_kb = _get_kb("L2a")
                            if _l2a_kb:
                                _l2a_sys = _l2a_sys + "\n\n" + _l2a_kb
                            _l2a_usr_tmpl = _get_tmpl("L2A_USER")
                            l2a_usr = (
                                _l2a_usr_tmpl
                                .replace("{label}", label)
                                .replace("{hint}", hint)
                                .replace("{context}", map_context)
                            )
                            l2a_prompt_path = _save_prompt(
                                stem, "L2a", label,
                                _l2a_sys, l2a_usr
                            )

                            resp = await _call_with_recitation_retry(
                                model, _l2a_sys,
                                l2a_usr,
                                crop_b64, crop_mime,
                                max_tokens, api_key,
                                context, _row,
                            )
                            _token_total["input"] += resp.usage.input_tokens
                            _token_total["output"] += resp.usage.output_tokens
                            parsed = extract_json(resp.text)
                            text_val = parsed.get("text", "")

                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "L2a_result",
                                    "filename": filename,
                                    "region": label,
                                    "text_preview": str(text_val)[:300],
                                    "crop_path": crop_disk_path,
                                    "bbox": bbox,
                                    "llm_output": str(text_val)[:500],
                                    "prompt_path": l2a_prompt_path,
                                })
                            ocr_results[label] = text_val

                        except Exception as exc:
                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "error",
                                    "filename": filename,
                                    "error": f"L2a {label}: {exc}"[:500],
                                })

                    if text_regions:
                        await asyncio.gather(
                            *(ocr_text_region(r) for r in text_regions)
                        )

                    # ═══ LEVEL 2b: Back to thumbnail — smart planning ═
                    if on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"L2b planning map exploration (read {len(ocr_results)} text regions)..."
                        )
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total,
                            "phase": "L2b_planning",
                            "filename": filename,
                            "ocr_regions_read": len(ocr_results),
                        })

                    _l2b_sys = _get_tmpl("L2B_SYSTEM")
                    _l2b_kb = _get_kb("L2b")
                    if _l2b_kb:
                        _l2b_sys = _l2b_sys + "\n\n" + _l2b_kb
                    _l2b_usr_tmpl = _get_tmpl("L2B_USER")
                    l2b_prompt = (
                        _l2b_usr_tmpl
                        .replace("{filename}", filename)
                        .replace("{overview_json}",
                                 json.dumps(overview, indent=2,
                                            ensure_ascii=False))
                        .replace("{ocr_json}",
                                 json.dumps(ocr_results, indent=2,
                                            ensure_ascii=False))
                    )
                    # Save L2b prompt
                    l2b_prompt_path = _save_prompt(
                        stem, "L2b", "planning",
                        _l2b_sys, l2b_prompt
                    )

                    # Inject few-shot examples before L2b query
                    fewshot_msgs = _get_fewshot("L2b")
                    if fewshot_msgs:
                        l2b_messages = (
                            conversation_history
                            + fewshot_msgs
                            + [_make_vision_message(
                                l2b_prompt, thumb_b64, thumb_mime)]
                        )
                    else:
                        l2b_messages = conversation_history + [
                            _make_vision_message(
                                l2b_prompt, thumb_b64, thumb_mime)
                        ]

                    l2b_resp = await _call_conversation_with_recitation_retry(
                        model, _l2b_sys,
                        l2b_messages,
                        max_tokens, api_key,
                        context, _row,
                    )
                    l2b_text = l2b_resp.text
                    _token_total["input"] += l2b_resp.usage.input_tokens
                    _token_total["output"] += l2b_resp.usage.output_tokens
                    # Add L2b exchange to main conversation history
                    conversation_history.append(
                        _make_vision_message(l2b_prompt, thumb_b64, thumb_mime)
                    )
                    conversation_history.append(
                        _make_assistant_message(l2b_text)
                    )
                    l2b = extract_json(l2b_text)
                    understanding = l2b.get("understanding", "")
                    visual_update = l2b.get("visual_update", {})
                    map_regions_raw = l2b.get("map_regions", [])
                    map_regions = _sanitize_regions(
                        map_regions_raw, "L2b"
                    )

                    if context:
                        region_counts = {}
                        for r in map_regions:
                            rt = r.get("type", "?")
                            region_counts[rt] = region_counts.get(rt, 0) + 1
                        corrections = [
                            f"{r['label']}: {r.get('_raw_bbox')} → {r['bbox']}"
                            for r in map_regions
                            if r.get("_raw_bbox") != r["bbox"]
                        ]
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total,
                            "phase": "L2b_result",
                            "filename": filename,
                            "understanding": understanding[:300],
                            "map_regions": region_counts,
                            "labels": [r.get("label", "?")
                                       for r in map_regions],
                            "prompt_path": l2b_prompt_path,
                            "llm_output": l2b_text[:2000],
                            **({"bbox_corrections": corrections}
                               if corrections else {}),
                        })

                    # ─── Region preview: combine L1 text + L2b map ────
                    all_viz_regions = []
                    for r in text_regions:
                        all_viz_regions.append({**r, "type": "text"})
                    for r in map_regions:
                        all_viz_regions.append(r)

                    if all_viz_regions:
                        try:
                            stem = os.path.splitext(filename)[0]
                            pname = f"{stem}_regions_{uuid.uuid4().hex[:6]}.png"
                            psave = os.path.join(_PREVIEW_DIR, pname)
                            ppath = _draw_regions_preview(
                                img_full, all_viz_regions, psave
                            )
                            df.at[idx, "map_regions_preview"] = ppath
                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "region_preview",
                                    "filename": filename,
                                    "preview_path": ppath,
                                    "num_regions": len(all_viz_regions),
                                    "regions": [
                                        {
                                            "label": r.get("label", "?"),
                                            "type": r.get("type", "text"),
                                            "bbox": r.get("bbox", [0, 0, 100, 100]),
                                        }
                                        for r in all_viz_regions
                                    ],
                                    "source_image": image_path,
                                })
                        except Exception as exc:
                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "region_preview_error",
                                    "error": str(exc)[:300],
                                })

                    # ═══ LEVEL 3: High-res map body + coordinate strips ═
                    # Enrich context with L2 understanding for L3 crops
                    _l3_ctx = [map_context]
                    if understanding:
                        _l3_ctx.append(f"Understanding: {understanding}")
                    if visual_update.get("coverage"):
                        _l3_ctx.append(
                            f"Coverage: {visual_update['coverage']}")
                    if visual_update.get("subject"):
                        _l3_ctx.append(
                            f"Subject: {visual_update['subject']}")
                    # Include any place names already identified from OCR
                    for _ocr_text in ocr_results.values():
                        if isinstance(_ocr_text, str) and _ocr_text.strip():
                            _l3_ctx.append(
                                f"Text already read: {_ocr_text[:200]}")
                            break  # one sample is enough for context
                    l3_context = "\n".join(_l3_ctx)

                    if on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"L3 exploring {len(map_regions)} map regions..."
                        )
                    coordinate_results = {}
                    sample_results = {}

                    async def analyze_map_region(region: dict):
                        label = region.get("label", "unknown")
                        rtype = region.get("type", "map_sample")
                        bbox = region.get("bbox", [0, 0, 100, 100])
                        hint = region.get("hint", "describe content")

                        # Position and sibling region context
                        position = _bbox_to_position_desc(bbox)
                        other = []
                        for r2 in map_regions:
                            if r2.get("label") != label:
                                r2_pos = _bbox_to_position_desc(
                                    r2.get("bbox", [0, 0, 100, 100])
                                )
                                other.append(
                                    f"- {r2.get('label')}: {r2_pos} "
                                    f"({r2.get('type', 'map_sample')})"
                                )
                        other_regions_text = (
                            "\n".join(other) if other else "(none)"
                        )

                        try:
                            # Full-res crop → JPG q=100 (no compression)
                            crop_b64, crop_mime, cw, ch = _crop_b64(
                                img_full, bbox
                            )
                            # Save crop to disk for visualization
                            stem = os.path.splitext(filename)[0]
                            l3_crop_path = _save_crop_to_disk(
                                img_full, bbox, stem, label
                            )

                            if rtype in ("border", "coordinate_strip"):
                                # Determine expected coordinate type
                                # from label and position
                                _lbl = label.lower()
                                if "scale" in _lbl:
                                    expected_type = (
                                        "a scale bar, representative "
                                        "fraction, or distance indicator"
                                    )
                                elif any(k in _lbl for k in (
                                    "longitude", "easting", "lon",
                                )) or "top" in position or "bottom" in position:
                                    expected_type = (
                                        "LONGITUDE values "
                                        "(e.g. 138°E, 139°E) "
                                        "running left to right"
                                    )
                                elif any(k in _lbl for k in (
                                    "latitude", "northing", "lat",
                                )) or "left" in position or "right" in position:
                                    expected_type = (
                                        "LATITUDE values "
                                        "(e.g. 30°S, 31°S) "
                                        "running top to bottom"
                                    )
                                else:
                                    expected_type = (
                                        "coordinate labels or "
                                        "scale information"
                                    )

                                _l3c_sys = _get_tmpl("L3_SYSTEM_COORDINATE")
                                _l3c_kb = _get_kb("L3_coord")
                                if _l3c_kb:
                                    _l3c_sys = _l3c_sys + "\n\n" + _l3c_kb
                                sys_p, usr_p = (
                                    _l3c_sys,
                                    _get_tmpl("L3_USER_COORDINATE")
                                    .replace("{label}", label)
                                    .replace("{hint}", hint)
                                    .replace("{position}", position)
                                    .replace("{expected_type}",
                                             expected_type)
                                    .replace("{other_regions}",
                                             other_regions_text)
                                    .replace("{context}", l3_context),
                                )
                            else:
                                _l3s_sys = _get_tmpl("L3_SYSTEM_SAMPLE")
                                _l3s_kb = _get_kb("L3_sample")
                                if _l3s_kb:
                                    _l3s_sys = _l3s_sys + "\n\n" + _l3s_kb
                                sys_p, usr_p = (
                                    _l3s_sys,
                                    _get_tmpl("L3_USER_SAMPLE")
                                    .replace("{label}", label)
                                    .replace("{hint}", hint)
                                    .replace("{position}", position)
                                    .replace("{other_regions}",
                                             other_regions_text)
                                    .replace("{context}", l3_context),
                                )

                            # Save L3 prompt to disk
                            l3_prompt_path = _save_prompt(
                                stem, "L3", label, sys_p, usr_p
                            )

                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "L3_crop",
                                    "filename": filename,
                                    "region": label,
                                    "type": rtype,
                                    "crop_size": f"{cw}x{ch}",
                                    "format": "JPG q=100",
                                    "crop_path": l3_crop_path,
                                    "bbox": bbox,
                                    "position": position,
                                    "prompt_preview": usr_p[:500],
                                    "prompt_path": l3_prompt_path,
                                })

                            l3_resp = await _call_with_recitation_retry(
                                model, sys_p, usr_p,
                                crop_b64, crop_mime,
                                max_tokens, api_key,
                                context, _row,
                            )
                            _token_total["input"] += l3_resp.usage.input_tokens
                            _token_total["output"] += l3_resp.usage.output_tokens
                            parsed = extract_json(l3_resp.text)

                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "L3_result",
                                    "filename": filename,
                                    "region": label,
                                    "type": rtype,
                                    "preview": json.dumps(
                                        parsed, ensure_ascii=False
                                    )[:300],
                                    "crop_path": l3_crop_path,
                                    "bbox": bbox,
                                    "position": position,
                                    "llm_output": json.dumps(
                                        parsed, ensure_ascii=False
                                    )[:1000],
                                    "prompt_preview": usr_p[:500],
                                    "prompt_path": l3_prompt_path,
                                })

                            if rtype in ("border", "coordinate_strip"):
                                coordinate_results[label] = parsed
                            else:
                                sample_results[label] = parsed

                        except Exception as exc:
                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total,
                                    "phase": "error",
                                    "filename": filename,
                                    "error": f"L3 {label}: {exc}"[:500],
                                })

                    if map_regions:
                        await asyncio.gather(
                            *(analyze_map_region(r) for r in map_regions)
                        )

                    # ═══ SYNTHESIS ═════════════════════════════════════
                    if on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"synthesizing (text:{len(ocr_results)} "
                            f"coord:{len(coordinate_results)} "
                            f"sample:{len(sample_results)})..."
                        )

                    # Start with data we already have (fallback if
                    # synthesis fails)
                    merged = {**overview, **visual_update}

                    try:
                        _synth_sys = _get_tmpl("SYNTH_SYSTEM")
                        _synth_kb = _get_kb("Synthesis")
                        if _synth_kb:
                            _synth_sys = _synth_sys + "\n\n" + _synth_kb
                        _synth_usr_tmpl = _get_tmpl("SYNTH_USER")
                        synth_prompt = (
                            _synth_usr_tmpl
                            .replace("{overview_json}",
                                     json.dumps(overview, indent=2,
                                                ensure_ascii=False))
                            .replace("{text_json}",
                                     json.dumps(ocr_results, indent=2,
                                                ensure_ascii=False)
                                     if ocr_results else "(no text read)")
                            .replace("{understanding_json}",
                                     json.dumps({
                                         "understanding": understanding,
                                         **visual_update,
                                     }, indent=2, ensure_ascii=False))
                            .replace("{coordinate_json}",
                                     json.dumps(coordinate_results, indent=2,
                                                ensure_ascii=False)
                                     if coordinate_results else "(no coordinate strips)")
                            .replace("{sample_json}",
                                     json.dumps(sample_results, indent=2,
                                                ensure_ascii=False)
                                     if sample_results else "(no samples)")
                        )

                        # Save synthesis prompt
                        synth_prompt_path = _save_prompt(
                            stem, "Synth", "synthesis",
                            _synth_sys, synth_prompt
                        )

                        if context:
                            await context.emit("ai_debug", {
                                "row": i + 1, "total": total,
                                "phase": "synthesis",
                                "filename": filename,
                                "text_ocr": len(ocr_results),
                                "coordinate_strips": len(coordinate_results),
                                "samples": len(sample_results),
                                "prompt_path": synth_prompt_path,
                            })

                        conversation_history.append(
                            _make_vision_message(
                                synth_prompt, thumb_b64, thumb_mime
                            )
                        )
                        synth_resp = await _call_conversation_with_recitation_retry(
                            model, _synth_sys,
                            conversation_history,
                            max_tokens, api_key,
                            context, _row,
                        )
                        synth_text = synth_resp.text
                        _token_total["input"] += synth_resp.usage.input_tokens
                        _token_total["output"] += synth_resp.usage.output_tokens
                        final = extract_json(synth_text)
                        merged = {**merged, **final}

                    except Exception as exc:
                        # Synthesis failed — we still keep partial data
                        # from overview + visual_update
                        if context:
                            await context.emit("ai_debug", {
                                "row": i + 1, "total": total,
                                "phase": "error",
                                "filename": filename,
                                "error": f"Synthesis: {exc}"[:500],
                            })

                    if context:
                        filled = sum(
                            1 for v in merged.values()
                            if v and str(v).strip()
                        )
                        # Build synthesis_result summary for frontend card
                        synthesis_result = {}
                        _SUMMARY_KEYS = {
                            "country": "country",
                            "province": "province_or_state",
                            "city": "city",
                            "district": "district_or_county",
                            "title": "map_title",
                            "date_text": "estimated_date",
                            "place_names": "place_names",
                            "coverage": "geographic_coverage",
                            "subject": "notable_features",
                            "map_type": "map_type",
                            "language": "language",
                        }
                        for src_key, dst_key in _SUMMARY_KEYS.items():
                            val = merged.get(src_key, "")
                            if val and str(val).strip():
                                if isinstance(val, (list, tuple)):
                                    sv = ", ".join(str(v) for v in val)
                                else:
                                    sv = str(val)
                                synthesis_result[dst_key] = sv

                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total,
                            "phase": "done",
                            "filename": filename,
                            "fields_filled": filled,
                            "synthesis_result": synthesis_result,
                            "token_usage": {
                                "input_tokens": _token_total["input"],
                                "output_tokens": _token_total["output"],
                                "total_tokens": _token_total["input"] + _token_total["output"],
                            },
                        })

                    # Numeric fields — store as numbers, not strings
                    _NUMERIC_FIELDS = {
                        "date_year", "scale_ratio",
                        "bbox_west", "bbox_east", "bbox_south", "bbox_north",
                    }

                    # Write to DataFrame
                    for json_key, out_col in MAP_FIELDS:
                        val = merged.get(json_key, "")
                        # "N/A" from AI means not applicable — keep as-is
                        if isinstance(val, str) and val.strip().upper() == "N/A":
                            df.at[idx, out_col] = "N/A"
                            continue
                        if json_key in _NUMERIC_FIELDS:
                            if val == "" or val is None:
                                df.at[idx, out_col] = ""
                                continue
                            try:
                                val = float(val)
                                if json_key in ("date_year", "scale_ratio"):
                                    val = int(val)
                            except (ValueError, TypeError):
                                df.at[idx, out_col] = ""
                                continue
                        elif isinstance(val, (list, tuple)):
                            val = ", ".join(str(v) for v in val if v)
                        elif isinstance(val, bool):
                            val = "yes" if val else "no"
                        else:
                            val = clean_cell(val)
                        df.at[idx, out_col] = val

                    # Expand type_specific dict into
                    # ts_<key> columns
                    type_specific = merged.get(
                        "type_specific", {})
                    if isinstance(type_specific, dict):
                        for ts_key, ts_val in \
                                type_specific.items():
                            col = f"ts_{ts_key}"
                            if isinstance(ts_val, (list, tuple)):
                                ts_val = ", ".join(
                                    str(v) for v in ts_val if v)
                            elif isinstance(ts_val, bool):
                                ts_val = "yes" if ts_val \
                                    else "no"
                            else:
                                ts_val = clean_cell(ts_val)
                            df.at[idx, col] = ts_val

                    # Save raw data for post-processing
                    _map_raw_data[idx] = {
                        "filename": filename,
                        "overview": overview,
                        "ocr_results": ocr_results,
                        "understanding": understanding,
                        "visual_update": visual_update,
                        "coordinate_results": coordinate_results,
                        "sample_results": sample_results,
                        "merged": merged,
                    }

                    img_full.close()

                except Exception as exc:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total,
                            "phase": "error",
                            "filename": filename,
                            "error": str(exc)[:500],
                        })
                    for _, out_col in MAP_FIELDS:
                        df.at[idx, out_col] = ""

            analyzed += 1
            completed += 1

            if on_progress:
                await on_progress(
                    f"Map Analysis: {analyzed}/{rows_with_images} complete"
                )
            if context and (analyzed % 3 == 0 or completed == total):
                preview = build_data_preview(df, new_columns)
                if preview:
                    await context.emit("data_preview", preview)

        # ── Process one map — DIRECT mode ─────────────────────────────────

        async def process_map_direct(i, idx, row):
            nonlocal completed, skipped, analyzed

            if not _has_image(row[image_column]):
                skipped += 1
                completed += 1
                return

            image_path = str(row[image_column]).strip()
            filename = os.path.basename(image_path)

            # Per-map token accumulator
            _token_total = {"input": 0, "output": 0}

            async with sem:
                try:
                    from PIL import Image
                    img_full = Image.open(image_path)
                    img_full = _fix_mode(img_full)
                    full_w, full_h = img_full.size

                    stem = os.path.splitext(filename)[0]
                    _row = {"row": i + 1, "total": total,
                            "filename": filename}

                    # ═══ PHASE 1: Full high-res pass ══════════════════
                    if on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"direct analysis ({full_w}x{full_h})..."
                        )

                    thumb_b64, thumb_mime = _thumbnail_b64(img_full)

                    if context:
                        thumb_sz = _make_thumbnail(img_full).size
                        await context.emit("ai_debug", {
                            **_row,
                            "phase": "direct_main",
                            "full_size": f"{full_w}x{full_h}",
                            "thumb_size": f"{thumb_sz[0]}x{thumb_sz[1]}",
                            "source_image": image_path,
                        })

                    # Build system prompt with knowledge
                    _dir_sys = _get_tmpl("DIRECT_SYSTEM")
                    _dir_kb = _get_kb("L1")  # general map knowledge
                    _dir_kb2 = _get_kb("L2b")  # border knowledge
                    _dir_kb3 = _get_kb("L3_coord")  # coordinate knowledge
                    _dir_kb4 = _get_kb("Synthesis")  # quality knowledge
                    for kb in [_dir_kb, _dir_kb2, _dir_kb3, _dir_kb4]:
                        if kb:
                            _dir_sys = _dir_sys + "\n\n" + kb

                    _dir_usr = _get_tmpl("DIRECT_USER")
                    dir_prompt = _dir_usr.replace("{filename}", filename)

                    # Save prompt to disk
                    dir_prompt_path = _save_prompt(
                        stem, "Direct", "main", _dir_sys, dir_prompt
                    )

                    # Inject few-shot examples
                    dir_fewshot = _get_fewshot("L1")
                    dir_user_msg = _make_vision_message(
                        dir_prompt, thumb_b64, thumb_mime)
                    dir_messages = dir_fewshot + [dir_user_msg] \
                        if dir_fewshot else [dir_user_msg]

                    dir_resp = \
                        await _call_conversation_with_recitation_retry(
                            model, _dir_sys,
                            dir_messages,
                            max_tokens, api_key,
                            context, _row,
                        )
                    dir_text = dir_resp.text
                    _token_total["input"] += dir_resp.usage.input_tokens
                    _token_total["output"] += dir_resp.usage.output_tokens
                    main_result = extract_json(dir_text)

                    if context:
                        confidence = main_result.get("confidence", {})
                        needs_crop = confidence.get("needs_crop", [])
                        await context.emit("ai_debug", {
                            **_row,
                            "phase": "direct_result",
                            "fields_high": len(
                                confidence.get("high", [])),
                            "fields_low": len(
                                confidence.get("low", [])),
                            "needs_crop": len(needs_crop),
                            "prompt_path": dir_prompt_path,
                            "llm_output": dir_text[:2000],
                        })

                    # ═══ PHASE 2: Supplement crops ════════════════════
                    needs_crop = main_result.get(
                        "confidence", {}).get("needs_crop", [])

                    if needs_crop and on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"supplementing {len(needs_crop)} areas..."
                        )

                    # Build context summary for supplement calls
                    _ctx_parts = [f"Filename: {filename}"]
                    for k in ("title", "date_text", "coverage",
                              "country", "map_type"):
                        v = main_result.get(k, "")
                        if v and str(v).strip():
                            _ctx_parts.append(f"{k}: {v}")
                    supp_context = "\n".join(_ctx_parts)

                    # Draw preview and do supplement crops
                    preview_regions = []

                    async def do_supplement(crop_req):
                        field = crop_req.get("field", "unknown")
                        reason = crop_req.get("reason", "")
                        bbox = _sanitize_bbox(
                            crop_req.get("bbox", [0, 0, 100, 100]),
                            field)

                        preview_regions.append({
                            "label": field,
                            "type": "coordinate_strip"
                                if "coord" in field or "bbox" in field
                                or "scale" in field
                                else "map_sample",
                            "bbox": bbox,
                        })

                        try:
                            crop_b64, crop_mime, cw, ch = \
                                _crop_b64(img_full, bbox)

                            # Save crop to disk
                            crop_path = _save_crop_to_disk(
                                img_full, bbox, stem,
                                f"Supp_{field}")

                            _supp_sys = _get_tmpl(
                                "DIRECT_SUPPLEMENT_SYSTEM")
                            _supp_usr = _get_tmpl(
                                "DIRECT_SUPPLEMENT_USER")
                            supp_prompt = (
                                _supp_usr
                                .replace("{filename}", filename)
                                .replace("{label}", field)
                                .replace("{field}", field)
                                .replace("{reason}", reason)
                                .replace("{context}", supp_context)
                            )

                            supp_prompt_path = _save_prompt(
                                stem, "Supp", field,
                                _supp_sys, supp_prompt
                            )

                            # Emit crop event before LLM call
                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "supplement_crop",
                                    "field": field,
                                    "reason": reason,
                                    "bbox": bbox,
                                    "crop_path": crop_path,
                                    "crop_size": f"{cw}x{ch}",
                                    "prompt_preview":
                                        supp_prompt[:500],
                                })

                            supp_resp = \
                                await _call_with_recitation_retry(
                                    model, _supp_sys, supp_prompt,
                                    crop_b64, crop_mime,
                                    max_tokens, api_key,
                                    context, _row,
                                )
                            _token_total["input"] += supp_resp.usage.input_tokens
                            _token_total["output"] += supp_resp.usage.output_tokens
                            supp_parsed = extract_json(supp_resp.text)

                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "supplement_result",
                                    "field": field,
                                    "reason": reason,
                                    "bbox": bbox,
                                    "value": str(
                                        supp_parsed.get("value", "")
                                    )[:200],
                                    "confident": supp_parsed.get(
                                        "confident", False),
                                    "crop_path": crop_path,
                                    "prompt_path": supp_prompt_path,
                                    "prompt_preview":
                                        supp_prompt[:500],
                                    "llm_output":
                                        supp_resp.text[:1000],
                                })

                            # Merge supplement result into main
                            val = supp_parsed.get("value", "")
                            if val and supp_parsed.get(
                                    "confident", False):
                                main_result[field] = val

                        except Exception as exc:
                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "error",
                                    "error":
                                        f"Supplement {field}: "
                                        f"{exc}"[:500],
                                })

                    if needs_crop:
                        await asyncio.gather(
                            *(do_supplement(cr) for cr in needs_crop)
                        )

                    # Draw preview image with supplement regions
                    if preview_regions:
                        try:
                            preview_img = _draw_regions_preview(
                                img_full, preview_regions)
                            preview_path = os.path.join(
                                _PREVIEW_DIR,
                                f"{stem}_direct_preview.jpg")
                            os.makedirs(_PREVIEW_DIR, exist_ok=True)
                            preview_img.save(
                                preview_path, "JPEG", quality=85)
                            df.at[idx, "map_regions_preview"] = \
                                preview_path

                            if context:
                                await context.emit(
                                    "map_analysis_update", {
                                        **_row,
                                        "phase": "region_preview",
                                        "preview_path": preview_path,
                                        "regions": preview_regions,
                                    })
                        except Exception:
                            pass

                    # Remove confidence/_evidence metadata before writing
                    merged = {k: v for k, v in main_result.items()
                              if k not in ("confidence", "_evidence")}

                    # ── Critic pass: audit for hallucinated fields ──
                    critic_audit: dict = {}
                    if critic_model and critic_api_key:
                        try:
                            merged, critic_audit, critic_usage = \
                                await _run_critic(
                                    thumb_b64, thumb_mime,
                                    filename, merged,
                                    critic_model, critic_api_key,
                                    max_tokens, context, _row,
                                )
                            _token_total["input"] += \
                                critic_usage.input_tokens
                            _token_total["output"] += \
                                critic_usage.output_tokens
                        except Exception as exc:
                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "error",
                                    "error":
                                        f"Critic pass failed: "
                                        f"{exc}"[:500],
                                })

                    if context:
                        filled = sum(
                            1 for v in merged.values()
                            if v and str(v).strip()
                        )
                        synthesis_result = {}
                        _SUMMARY_KEYS = {
                            "country": "country",
                            "province": "province_or_state",
                            "city": "city",
                            "district": "district_or_county",
                            "title": "map_title",
                            "date_text": "estimated_date",
                            "place_names": "place_names",
                            "coverage": "geographic_coverage",
                            "subject": "notable_features",
                            "map_type": "map_type",
                            "language": "language",
                        }
                        for src_key, dst_key in _SUMMARY_KEYS.items():
                            val = merged.get(src_key, "")
                            if val and str(val).strip():
                                if isinstance(val, (list, tuple)):
                                    sv = ", ".join(
                                        str(v) for v in val)
                                else:
                                    sv = str(val)
                                synthesis_result[dst_key] = sv

                        await context.emit("ai_debug", {
                            **_row,
                            "phase": "done",
                            "fields_filled": filled,
                            "synthesis_result": synthesis_result,
                            "token_usage": {
                                "input_tokens": _token_total["input"],
                                "output_tokens": _token_total["output"],
                                "total_tokens": _token_total["input"] + _token_total["output"],
                            },
                        })

                    # Write to DataFrame
                    _NUMERIC_FIELDS = {
                        "date_year", "scale_ratio",
                        "bbox_west", "bbox_east",
                        "bbox_south", "bbox_north",
                    }
                    for json_key, out_col in MAP_FIELDS:
                        val = merged.get(json_key, "")
                        if isinstance(val, str) and \
                                val.strip().upper() == "N/A":
                            df.at[idx, out_col] = "N/A"
                            continue
                        if json_key in _NUMERIC_FIELDS:
                            if val == "" or val is None:
                                df.at[idx, out_col] = ""
                                continue
                            try:
                                val = float(val)
                                if json_key in (
                                        "date_year", "scale_ratio"):
                                    val = int(val)
                            except (ValueError, TypeError):
                                df.at[idx, out_col] = ""
                                continue
                        elif isinstance(val, (list, tuple)):
                            val = ", ".join(
                                str(v) for v in val if v)
                        elif isinstance(val, bool):
                            val = "yes" if val else "no"
                        else:
                            val = clean_cell(val)
                        df.at[idx, out_col] = val

                    # Expand type_specific dict into
                    # ts_<key> columns
                    type_specific = merged.get(
                        "type_specific", {})
                    if isinstance(type_specific, dict):
                        for ts_key, ts_val in \
                                type_specific.items():
                            col = f"ts_{ts_key}"
                            if isinstance(ts_val, (list, tuple)):
                                ts_val = ", ".join(
                                    str(v) for v in ts_val if v)
                            elif isinstance(ts_val, bool):
                                ts_val = "yes" if ts_val \
                                    else "no"
                            else:
                                ts_val = clean_cell(ts_val)
                            df.at[idx, col] = ts_val

                    # Save raw data for post-processing
                    _map_raw_data[idx] = {
                        "filename": filename,
                        "overview": {},
                        "ocr_results": {},
                        "understanding": merged.get(
                            "description", ""),
                        "visual_update": {},
                        "coordinate_results": {},
                        "sample_results": {},
                        "merged": merged,
                    }

                    img_full.close()

                except Exception as exc:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total,
                            "phase": "error",
                            "filename": filename,
                            "error": str(exc)[:500],
                        })
                    for _, out_col in MAP_FIELDS:
                        df.at[idx, out_col] = ""

            analyzed += 1
            completed += 1

            if on_progress:
                await on_progress(
                    f"Map Analysis: {analyzed}/{rows_with_images} "
                    f"complete"
                )
            if context and (analyzed % 3 == 0 or completed == total):
                preview = build_data_preview(df, new_columns)
                if preview:
                    await context.emit("data_preview", preview)

        # ── Run all ───────────────────────────────────────────────────────
        _process_fn = process_map_direct if mode == "direct" \
            else process_map
        tasks = [
            _process_fn(i, idx, row)
            for i, (idx, row) in enumerate(df.iterrows())
        ]
        await asyncio.gather(*tasks)

        # ── Post-processing: cross-map review & refinement ────────────
        if len(_map_raw_data) >= 1:
            try:
                if on_progress:
                    await on_progress(
                        f"Post-processing: reviewing {len(_map_raw_data)} "
                        f"maps with cross-map context..."
                    )
                if context:
                    await context.emit("ai_debug", {
                        "row": 0, "total": total,
                        "phase": "post_process_start",
                        "map_count": len(_map_raw_data),
                    })

                # Build cross-map summary (brief, for context)
                cross_map_lines = []
                for idx_pp, raw_pp in _map_raw_data.items():
                    m = raw_pp["merged"]
                    line = (
                        f"- {raw_pp['filename']}: "
                        f"title={m.get('title', '?')}, "
                        f"country={m.get('country', '?')}, "
                        f"coverage={m.get('coverage', '?')}, "
                        f"type={m.get('map_type', '?')}"
                    )
                    cross_map_lines.append(line)
                cross_map_summary = "\n".join(cross_map_lines)

                # Process in batches of up to 5 maps per API call
                _BATCH_SIZE = 5
                raw_items = list(_map_raw_data.items())
                for batch_start in range(0, len(raw_items), _BATCH_SIZE):
                    batch = raw_items[batch_start:batch_start + _BATCH_SIZE]

                    # Build per-map data for this batch
                    map_data_list = []
                    for idx_b, raw_b in batch:
                        entry_data = {
                            "filename": raw_b["filename"],
                            "vision_outputs": {
                                "overview": raw_b["overview"],
                                "ocr_texts": raw_b["ocr_results"],
                                "understanding": raw_b["understanding"],
                                "coordinate_readings": raw_b["coordinate_results"],
                                "map_samples": raw_b["sample_results"],
                            },
                            "current_synthesis": raw_b["merged"],
                        }
                        map_data_list.append(entry_data)

                    _pp_sys = _get_tmpl("POST_PROCESS_SYSTEM")
                    _pp_usr_tmpl = _get_tmpl("POST_PROCESS_USER")
                    pp_prompt = (
                        _pp_usr_tmpl
                        .replace("{count}", str(len(batch)))
                        .replace("{cross_map_summary}", cross_map_summary)
                        .replace("{map_data_json}",
                                 json.dumps(map_data_list, indent=2,
                                            ensure_ascii=False))
                    )

                    if on_progress:
                        await on_progress(
                            f"Post-processing batch "
                            f"{batch_start // _BATCH_SIZE + 1}/"
                            f"{(len(raw_items) + _BATCH_SIZE - 1) // _BATCH_SIZE}"
                            f" ({len(batch)} maps)..."
                        )

                    try:
                        pp_resp = await _call_conversation_with_recitation_retry(
                            model, _pp_sys,
                            [{"role": "user",
                              "content": pp_prompt}],
                            max_tokens, api_key,
                            context,
                            {"row": 0, "total": total,
                             "filename": "post-process"},
                        )
                        pp_text = pp_resp.text
                        pp_result = extract_json(pp_text)

                        # pp_result should be a list of
                        # {"filename": ..., "refined": {...}}
                        if isinstance(pp_result, list):
                            # Build filename → idx mapping for this batch
                            fn_to_idx = {
                                raw_b["filename"]: idx_b
                                for idx_b, raw_b in batch
                            }

                            for pp_entry in pp_result:
                                fn = pp_entry.get("filename", "")
                                refined = pp_entry.get("refined", {})
                                if not refined or fn not in fn_to_idx:
                                    continue

                                target_idx = fn_to_idx[fn]
                                # Update merged data with refinements
                                existing_merged = _map_raw_data[
                                    target_idx]["merged"]
                                existing_merged.update(refined)

                                # Re-write to DataFrame
                                _NUMERIC_FIELDS = {
                                    "date_year", "scale_ratio",
                                    "bbox_west", "bbox_east",
                                    "bbox_south", "bbox_north",
                                }
                                for json_key, out_col in MAP_FIELDS:
                                    if json_key not in refined:
                                        continue
                                    val = existing_merged.get(
                                        json_key, "")
                                    if isinstance(val, str) and \
                                            val.strip().upper() \
                                            == "N/A":
                                        df.at[target_idx, out_col] \
                                            = "N/A"
                                        continue
                                    if json_key in _NUMERIC_FIELDS:
                                        if val == "" or val is None:
                                            df.at[target_idx,
                                                  out_col] = ""
                                            continue
                                        try:
                                            val = float(val)
                                            if json_key in (
                                                "date_year",
                                                "scale_ratio",
                                            ):
                                                val = int(val)
                                        except (ValueError,
                                                TypeError):
                                            df.at[target_idx,
                                                  out_col] = ""
                                            continue
                                    elif isinstance(
                                            val, (list, tuple)):
                                        val = ", ".join(
                                            str(v) for v in val
                                            if v)
                                    elif isinstance(val, bool):
                                        val = "yes" if val \
                                            else "no"
                                    else:
                                        val = clean_cell(val)
                                    df.at[target_idx, out_col] = \
                                        val

                                # Handle refined type_specific
                                ts_refined = refined.get(
                                    "type_specific", {})
                                if isinstance(ts_refined, dict):
                                    for ts_k, ts_v in \
                                            ts_refined.items():
                                        col = f"ts_{ts_k}"
                                        if isinstance(
                                                ts_v,
                                                (list, tuple)):
                                            ts_v = ", ".join(
                                                str(v) for v
                                                in ts_v if v)
                                        elif isinstance(
                                                ts_v, bool):
                                            ts_v = "yes" \
                                                if ts_v \
                                                else "no"
                                        else:
                                            ts_v = clean_cell(
                                                ts_v)
                                        df.at[target_idx, col] = \
                                            ts_v

                                if context:
                                    await context.emit("ai_debug", {
                                        "row": 0, "total": total,
                                        "phase": "post_process_refined",
                                        "filename": fn,
                                        "fields_refined": list(
                                            refined.keys()),
                                    })

                    except Exception as pp_exc:
                        if context:
                            await context.emit("ai_debug", {
                                "row": 0, "total": total,
                                "phase": "error",
                                "filename": "post-process",
                                "error": (
                                    f"Post-process batch: {pp_exc}"
                                )[:500],
                            })

                # Emit final data preview after post-processing
                if context:
                    preview = build_data_preview(df, new_columns)
                    if preview:
                        await context.emit("data_preview", preview)
                    await context.emit("ai_debug", {
                        "row": 0, "total": total,
                        "phase": "post_process_done",
                        "map_count": len(_map_raw_data),
                    })

            except Exception as pp_outer_exc:
                # Post-processing failure should NOT block results
                if context:
                    await context.emit("ai_debug", {
                        "row": 0, "total": total,
                        "phase": "error",
                        "filename": "post-process",
                        "error": f"Post-processing failed: {pp_outer_exc}"[:500],
                    })

        # ═══ Archive debug logs ═══════════════════════════════════
        # Restore original emit before archival
        if context and _orig_emit:
            context.emit = _orig_emit  # type: ignore

        if _debug_archive:
            try:
                archive_path = _archive_debug_logs(
                    _debug_archive, _run_timestamp
                )
                if context:
                    await context.emit("ai_debug", {
                        "row": 0, "total": total,
                        "phase": "debug_archive",
                        "archive_path": archive_path,
                        "entry_count": len(_debug_archive),
                    })
            except Exception:
                pass  # Don't fail the run for archival errors

        if on_progress:
            await on_progress(
                f"Map Analysis complete: {analyzed} maps, {skipped} skipped"
            )

        # Reorder ts_ columns by canonical grouping
        df = _reorder_ts_columns(df)

        # Optionally append Dublin Core columns
        if bool(config.get("dublin_core_export", False)):
            df = _add_dublin_core_columns(df)

        return {"output": df}
