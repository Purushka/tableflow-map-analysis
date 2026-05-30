"""AI Map Analysis node — single-pass grounded extraction with critic loop.

Architecture
============

For each map image:

  1. Extractor (vision agent) sees the full image and must produce a
     JSON object where every non-empty field is GROUNDED — bound to a
     specific bounding box (evidence_bbox) on the image, with the source
     text or visual marker (evidence_text) that supports it.

  2. Critic (second vision agent) sees the same image plus the grounded
     fields, then for each field looks at the indicated bbox and judges
     whether the value is actually supported by what's visible there.

  3. If the critic flags any field, the issues are formatted as a
     follow-up user message and appended to the EXTRACTOR's conversation
     history. The extractor re-examines the flagged fields in the same
     session (so it has its prior reasoning + the critic feedback) and
     emits corrected fields. Up to `max_correction_rounds` iterations.

  4. Any field that the critic still rejects after the final round is
     demoted to empty.

There is no thumbnail / region-planning / OCR-crop pipeline anymore —
direct grounded extraction proved more reliable than the progressive
chain. The image is sent at high resolution (resized only to fit the
provider's vision API budget) so the model can read fine print directly.
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
from ..providers.registry import (
    call_vision_llm,
    call_vision_conversation,
    get_provider_id_for_model,
)
from ..providers.base import LLMResponse, LLMUsage
from ..engine.context import build_data_preview
from .llm_utils import extract_json, clean_cell
from .ai_vision import _relative_image_path
from ..providers.google_provider import GeminiRecitationError
from ..routers.prompt_templates import get_effective_template as _get_tmpl
from ..routers.map_knowledge import get_knowledge_for_phase as _get_kb
from ..routers.fewshot import get_fewshot_messages as _get_fewshot

# Directory for region-preview images (evidence bbox visualizations)
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

_FIELD_NAMES = {k for k, _ in MAP_FIELDS}

# Numeric fields — stored as numbers, not strings
_NUMERIC_FIELDS = {
    "date_year", "scale_ratio",
    "bbox_west", "bbox_east", "bbox_south", "bbox_north",
}

# ── Canonical type-specific column order (grouped by category) ──────────────
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
    order_map = {c: i for i, c in enumerate(_TS_COLUMN_ORDER)}
    max_idx = len(_TS_COLUMN_ORDER)
    ts_sorted = sorted(ts_cols, key=lambda c: (order_map.get(c, max_idx), c))
    return df[non_ts + ts_sorted]


# ── Dublin Core export ─────────────────────────────────────────────────────
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

_LANG_ISO = {
    "english": "en", "french": "fr", "german": "de", "spanish": "es",
    "italian": "it", "portuguese": "pt", "russian": "ru", "chinese": "zh",
    "japanese": "ja", "arabic": "ar", "dutch": "nl", "latin": "la",
}


def _to_iso_lang(s: str) -> str:
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

        try:
            w_v = float(width_cm) if width_cm not in ("", None) else 0
            h_v = float(height_cm) if height_cm not in ("", None) else 0
        except (ValueError, TypeError):
            w_v = h_v = 0
        extent = f"{w_v:g} cm × {h_v:g} cm" if w_v > 0 and h_v > 0 else ""

        spatial_parts = []
        box = _dcmi_box(bbox_w, bbox_e, bbox_s, bbox_n)
        if box:
            spatial_parts.append(box)
        if coords_text and str(coords_text).strip().upper() != "N/A":
            spatial_parts.append(str(coords_text).strip())
        spatial = " | ".join(spatial_parts)

        coverage_value = _join_nonempty(
            [coverage, country, province, city, district, place_names]
        )

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

        if map_type and str(map_type).strip().upper() != "N/A":
            dc_type = f"Image; cartographic ({map_type})"
        else:
            dc_type = "Image; cartographic"

        format_parts = []
        if medium and str(medium).strip().upper() != "N/A":
            format_parts.append(str(medium).strip())
        if extent:
            format_parts.append(extent)
        dc_format = "; ".join(format_parts)

        subject_value = _join_nonempty([subject, map_type], sep=", ")

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
            "dc:creator": "",
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

    dc_df = pd.DataFrame(rows_dc, index=df.index, columns=_DC_COLUMN_ORDER)
    out = pd.concat([df, dc_df], axis=1)
    return out


# Regex for extracting physical dimensions from filename (e.g. "71.5cm X 106.6cm")
_DIM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*cm\s*[xX×]\s*(\d+(?:\.\d+)?)\s*cm",
    re.IGNORECASE,
)


def _extract_dimensions_cm(filename: str) -> tuple[float, float]:
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


def _make_text_message(text: str) -> dict:
    """Build a provider-neutral user message with text only."""
    return {"role": "user", "content": text}


def _make_assistant_message(text: str) -> dict:
    """Build a provider-neutral assistant message."""
    return {"role": "assistant", "content": text}


def _sanitize_bbox(bbox, label: str = "") -> list[float]:
    """Validate and clamp a bbox [x%, y%, w%, h%] from AI output."""
    if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return [0.0, 0.0, 100.0, 100.0]
    try:
        x, y, w, h = [float(v) for v in bbox]
    except (ValueError, TypeError):
        return [0.0, 0.0, 100.0, 100.0]
    w = max(1.0, min(100.0, w))
    h = max(1.0, min(100.0, h))
    x = max(0.0, min(100.0 - w, x))
    y = max(0.0, min(100.0 - h, y))
    return [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]


async def _call_with_recitation_retry(
    model, system, user_text, image_b64, image_mime,
    max_tokens, api_key, context=None, row_info=None,
) -> LLMResponse:
    """Call vision LLM; on Gemini recitation block, retry with catalogue prefix."""
    try:
        return await call_vision_llm(
            model, system, user_text,
            image_b64, image_mime, max_tokens, api_key,
        )
    except GeminiRecitationError:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": "Gemini RECITATION block — retrying with catalogue framing...",
            })
        retry_system = _CATALOGUE_PREFIX + "\n\n" + system
        return await call_vision_llm(
            model, retry_system, user_text,
            image_b64, image_mime, max_tokens, api_key,
        )


async def _call_conversation_with_recitation_retry(
    model, system, messages, max_tokens, api_key, context=None, row_info=None,
) -> LLMResponse:
    """Call vision conversation; on Gemini recitation block, retry with catalogue prefix."""
    try:
        return await call_vision_conversation(
            model, system, messages, max_tokens, api_key,
        )
    except GeminiRecitationError:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": "Gemini RECITATION block — retrying with catalogue framing...",
            })
        retry_system = _CATALOGUE_PREFIX + "\n\n" + system
        return await call_vision_conversation(
            model, retry_system, messages, max_tokens, api_key,
        )


# ═════════════════════════════════════════════════════════════════════════════
# Grounded extractor prompts
# ═════════════════════════════════════════════════════════════════════════════

EXTRACT_SYSTEM = """\
You are a cartographic metadata extraction specialist. You will receive a \
HIGH-RESOLUTION image of a map. Extract structured metadata from what is \
ACTUALLY VISIBLE on this image.

CRITICAL GROUNDING RULE
-----------------------
For EVERY non-empty field you output, you MUST bind it to a specific \
rectangular region of the image (evidence_bbox) AND provide the source \
text or visual marker (evidence_text) that supports it. \
If you cannot point to where a value is visible on the image, DO NOT \
include the field — leave it out entirely.

Do NOT use your training knowledge to fill values. If a famous map \
"usually" shows X but X is not visible on this scan, X must NOT appear \
in your output.

Return JSON only. No markdown, no explanation."""

EXTRACT_USER = """\
Analyze this map image and extract grounded metadata.
Filename: {filename}

Return a JSON object with this EXACT shape:

{{
  "fields": {{
    "<field_name>": {{
      "value": <the value>,
      "evidence_bbox": [x_percent, y_percent, w_percent, h_percent],
      "evidence_text": "the exact text printed on the map OR a brief description of the visual marker",
      "evidence_kind": "direct_quote" | "visual_observation" | "computed"
    }},
    ...
  }},
  "type_specific": {{
    "<key>": {{
      "value": <value>,
      "evidence_bbox": [...],
      "evidence_text": "...",
      "evidence_kind": "..."
    }}
  }}
}}

ALLOWED FIELD NAMES (omit any field you cannot ground in visible content):
- title                  exact map title from the image
- date_text              date as printed (e.g. "December 1957")
- date_year              4-digit year (integer) — kind="computed" pointing at the date_text bbox
- publisher              publisher / cartographer name as printed
- scale_text             scale as printed (e.g. "1:63,360" or "1 inch to 1 mile")
- scale_ratio            integer denominator (kind="computed" from scale_text or scale bar)
- projection             printed projection name
- edition                edition number or text
- coordinates_text       printed lat/long range as text
- bbox_west / bbox_east / bbox_south / bbox_north
                         decimal degrees, computed from PRINTED coordinate values.
                         West and South are NEGATIVE for W/S hemispheres.
                         kind="computed", evidence_bbox = the coordinate strip you read.
- place_names            major place names visible on the map, comma-separated, up to 15.
                         evidence_bbox = a region where most of them are concentrated;
                         evidence_text = quote 3-5 of them.
- legend_content         main legend entries readable from the legend area
- notes                  printed notes or handwritten annotations
- map_type               one of: topographic, geological, nautical, cadastral,
                         thematic, sketch, plan, celestial, other.
                         kind="visual_observation".
- subject                keyword tags, comma-separated
- coverage               geographic area description
- country / province / city / district
                         admin hierarchy from broadest to narrowest, based on
                         what the map actually depicts. Ground each in a
                         place name or coverage label visible on the map.
- medium                 format + color (e.g. "printed, full color").
                         kind="visual_observation".
- language               language(s) visible in printed text
- condition              comma-separated from: tears, foxing, stains, folds,
                         discoloration, good. kind="visual_observation".
- has_insets             "no" OR "yes: brief description"
- description            2-3 sentence catalogue summary.
                         kind="visual_observation", bbox may be [0, 0, 100, 100].

EVIDENCE KIND DEFINITIONS
- direct_quote        you OCR'd the value from printed text on the map.
                      evidence_text = the exact (short) OCR'd text.
- visual_observation  you classified the value by looking at visual features
                      (e.g. map_type, medium, condition). evidence_text =
                      what you saw (e.g. "ruled grid with contour lines and
                      elevation labels printed every 20m").
- computed            you derived the value by calculation from visible data.
                      evidence_text = the source values
                      (e.g. "scale bar reads '1 inch = 1 mile' → 1:63360";
                       "left strip range 30°S to 38°S → bbox_south=-38").

BBOX FORMAT
bbox = [x_percent, y_percent, width_percent, height_percent], all numbers
in 0..100, origin top-left.
Example: [10, 5, 30, 8] = 10% from left, 5% from top, 30% wide, 8% tall.
Keep bboxes TIGHT around the evidence but with a 1-2% safety margin.

RULES
- NEVER include a field whose value you cannot ground. If you cannot
  OCR / see / compute it, OMIT it.
- evidence_bbox must cover the region where the evidence is actually
  visible (not where the metadata belongs conceptually).
- For "computed" fields, point the bbox at the SOURCE region (e.g. for
  scale_ratio computed from a scale bar, point at the scale bar).
- For NON-GEOGRAPHIC maps (celestial, etc.), DO NOT produce bbox_west /
  bbox_east / bbox_south / bbox_north — omit them. Use type_specific
  for celestial coordinate info (right_ascension_range, declination_range,
  epoch, etc.).
- For numeric fields (date_year, scale_ratio, bbox_*), value MUST be a
  JSON number, not a string.
- Keep string values short and machine-friendly. Use comma-separated
  lists, not sentences (except "description" which is 2-3 sentences).
- type_specific is a free-form bag for map-type-specific fields. Use
  short snake_case keys (e.g. contour_interval, depth_range, grid_system,
  lot_numbers). Same grounding rule applies — every entry needs bbox +
  evidence_text + kind."""


# ═════════════════════════════════════════════════════════════════════════════
# Grounding critic prompts
# ═════════════════════════════════════════════════════════════════════════════

CRITIC_SYSTEM = """\
You are an independent cartographic fact-checker. Another AI has extracted \
metadata from a map and bound each field to a specific bounding box of the \
image (the evidence_bbox). Your job: verify each grounded claim.

For each field, look at the indicated evidence_bbox region in the image and \
confirm whether the claimed value is actually supported by what is visible \
there.

- ok = true   the value is genuinely supported by what's in the bbox
- ok = false  the value is NOT visible in the bbox, the bbox points to a
              wrong area, the value is more specific than the region shows,
              or the value appears to come from training knowledge of
              similar maps rather than from this scan.

You may NOT add new fields. You may NOT correct values. You may only flag.

Return STRICT JSON only — no commentary."""

CRITIC_USER = """\
Audit the grounded metadata extracted from this map.

Filename: {filename}

═══ GROUNDED CLAIMS ═══
{claims_json}

═══ INSTRUCTIONS ═══
For each field in the claims, look at its evidence_bbox region in the \
attached image and judge:

- "ok": true  if the value is clearly supported by what is visible in
              the evidence_bbox. The evidence_text should match what is
              actually readable / observable there.
- "ok": false if any of:
              * the value is NOT actually visible in that region
              * the bbox points to the wrong area (wrong edge of the map,
                wrong text block, etc.)
              * the value is more specific than the region actually shows
              * the value appears to come from training knowledge of
                similar maps rather than from this scan

Return STRICT JSON:

{{
  "verdicts": {{
    "<field_name>": {{
      "ok": true,
      "issue": "",
      "what_you_see": ""
    }},
    "<other_field>": {{
      "ok": false,
      "issue": "one sentence explaining what's wrong",
      "what_you_see": "briefly describe what IS actually visible in that bbox"
    }}
  }}
}}

For "type_specific" entries, prefix the key with "type_specific." \
(e.g. "type_specific.contour_interval").

When ok=true, "issue" and "what_you_see" MUST be empty strings.
When ok=false, BOTH "issue" and "what_you_see" are required.

Audit ONLY fields present in the input claims. Do NOT invent fields."""


# ═════════════════════════════════════════════════════════════════════════════
# Correction prompt — fed back into the extractor's conversation
# ═════════════════════════════════════════════════════════════════════════════

CORRECTION_USER = """\
A fact-checker reviewed your extraction and flagged issues with some of the \
grounded claims you made.

═══ FACT-CHECKER FEEDBACK ═══
{verdicts_summary}

═══ TASK ═══
Re-examine the map image (it is still attached to your earlier message in \
this conversation). For each flagged field, you must either:

(a) Provide a CORRECTED value with a NEW evidence_bbox that you can \
actually point to on the image, OR
(b) Acknowledge that you cannot ground the value, in which case OMIT the \
field from your output.

Return the SAME JSON shape as before:

{{
  "fields": {{ ... }},
  "type_specific": {{ ... }}
}}

Rules for this corrective round:
- Include ONLY: (1) corrected versions of flagged fields, AND (2) any
  fields the fact-checker accepted (you may copy those verbatim from your
  prior response).
- For each previously-flagged field, either provide a fresh
  evidence_bbox + value + evidence_text + evidence_kind, OR omit it.
- Do NOT introduce new field names that were not in your previous output.
- Do NOT defend an outside-knowledge claim — if the value is not visible
  in the image, omit the field.
- The same grounding rule applies: every value you keep needs an
  evidence_bbox you can point to."""


# ═════════════════════════════════════════════════════════════════════════════
# Image helpers — all output as JPEG
#   Crops:     JPG quality=100 (no compression) — max detail within API limit
# ═════════════════════════════════════════════════════════════════════════════

# Send the full image to the extractor at this max dimension. Vision APIs
# typically downsample to ~1.5 MP internally anyway, so going much higher
# wastes upload bandwidth — but we want enough resolution that fine print
# (legends, scale bars, coordinate ticks) stays readable.
_FULL_IMAGE_DIM = 3840

# Preview image for region visualization
_PREVIEW_DIM = 1500

_THUMB_QUALITY = 95
_CROP_QUALITY = 100
_MAX_IMAGE_BYTES = 18 * 1024 * 1024

# Colors for evidence-bbox preview (RGB)
_KIND_COLORS = {
    "direct_quote":       (255, 0, 0),     # red — OCR'd text
    "visual_observation": (0, 200, 0),     # green — visual classification
    "computed":           (0, 100, 255),   # blue — derived value
}


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
    img = _fix_mode(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def _resize_to_dim(img, dim: int):
    """Resize so the longest side is at most `dim`. No-op if already smaller."""
    from PIL import Image
    w, h = img.size
    if max(w, h) <= dim:
        return img.copy()
    ratio = dim / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def _full_image_b64(img) -> tuple[str, str, int, int]:
    """Encode the full image at _FULL_IMAGE_DIM, fit within API byte limit.

    Returns (b64, mime, encoded_w, encoded_h).
    """
    from PIL import Image
    work = _resize_to_dim(img, _FULL_IMAGE_DIM)
    work = _fix_mode(work)

    b64, mt = _pil_to_b64_jpg(work, quality=_THUMB_QUALITY)
    raw = len(base64.b64decode(b64))

    # If still too big, shrink resolution further
    while raw > _MAX_IMAGE_BYTES and max(work.size) > 512:
        cw, ch = work.size
        work = work.resize((int(cw * 0.8), int(ch * 0.8)), Image.LANCZOS)
        b64, mt = _pil_to_b64_jpg(work, quality=_THUMB_QUALITY)
        raw = len(base64.b64decode(b64))

    return b64, mt, work.size[0], work.size[1]


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
    from PIL import Image
    os.makedirs(_PREVIEW_DIR, exist_ok=True)
    crop = _crop_region(img, bbox)
    crop = _fix_mode(crop)
    max_dim = max(crop.size)
    if max_dim > 800:
        ratio = 800 / max_dim
        crop = crop.resize(
            (int(crop.size[0] * ratio), int(crop.size[1] * ratio)),
            Image.LANCZOS,
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


def _archive_debug_logs(debug_log: list[dict], run_timestamp: str) -> str:
    """Archive all debug log entries to a timestamped JSON file."""
    os.makedirs(_DEBUG_DIR, exist_ok=True)
    fname = f"debug_archive_{run_timestamp}.json"
    fpath = os.path.join(_DEBUG_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(debug_log, f, indent=2, ensure_ascii=False, default=str)
    return fpath


def _draw_evidence_preview(img_full, fields: dict,
                           type_specific: dict,
                           save_path: str) -> str:
    """Draw color-coded evidence bboxes on a medium-res preview.

    Colored by evidence_kind:
      direct_quote        → red
      visual_observation  → green
      computed            → blue

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

    def _draw_entry(label: str, entry: dict):
        if not isinstance(entry, dict):
            return
        bbox = entry.get("evidence_bbox")
        if not bbox:
            return
        bbox = _sanitize_bbox(bbox, label)
        kind = entry.get("evidence_kind", "direct_quote")
        color = _KIND_COLORS.get(kind, (200, 200, 200))

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

        tag = f" {label} "
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

    for k, v in (fields or {}).items():
        _draw_entry(k, v)
    for k, v in (type_specific or {}).items():
        _draw_entry(f"ts.{k}", v)

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    preview.save(save_path, format="PNG")
    return os.path.abspath(save_path)


# ═════════════════════════════════════════════════════════════════════════════
# Grounded-output parsing & critic helpers
# ═════════════════════════════════════════════════════════════════════════════

def _coerce_value(field: str, value):
    """Coerce a JSON-parsed value into the type the dataframe expects."""
    if value is None:
        return ""
    if isinstance(value, str) and value.strip().upper() == "N/A":
        return "N/A"
    if field in _NUMERIC_FIELDS:
        if value == "" or value is None:
            return ""
        try:
            num = float(value)
            if field in ("date_year", "scale_ratio"):
                return int(num)
            return num
        except (ValueError, TypeError):
            return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return clean_cell(value)


def _parse_grounded(raw: dict) -> tuple[dict, dict]:
    """Parse the extractor's JSON output into (fields, type_specific).

    Each value is normalized to {value, evidence_bbox, evidence_text,
    evidence_kind}. Entries lacking a bbox or with an unknown field name
    are dropped silently (their values will end up as "" in the output).
    """
    if not isinstance(raw, dict):
        return {}, {}

    def _norm(entry):
        if not isinstance(entry, dict):
            return None
        if "value" not in entry:
            return None
        bbox = entry.get("evidence_bbox")
        if not bbox:
            return None
        clean = {
            "value": entry["value"],
            "evidence_bbox": _sanitize_bbox(bbox),
            "evidence_text": str(entry.get("evidence_text", "") or "")[:500],
            "evidence_kind": str(entry.get("evidence_kind", "direct_quote") or "direct_quote"),
        }
        return clean

    raw_fields = raw.get("fields", {}) if isinstance(raw.get("fields"), dict) else {}
    raw_ts = raw.get("type_specific", {}) if isinstance(raw.get("type_specific"), dict) else {}

    # Also accept flat layout where fields are top-level
    if not raw_fields and any(k in _FIELD_NAMES for k in raw.keys()):
        raw_fields = {k: v for k, v in raw.items() if k in _FIELD_NAMES}

    fields: dict[str, dict] = {}
    for k, v in raw_fields.items():
        if k not in _FIELD_NAMES:
            continue
        norm = _norm(v)
        if norm is None:
            continue
        fields[k] = norm

    type_specific: dict[str, dict] = {}
    for k, v in raw_ts.items():
        if not isinstance(k, str) or not k:
            continue
        # Strip ts_ prefix if model accidentally added it
        key = k[3:] if k.startswith("ts_") else k
        norm = _norm(v)
        if norm is None:
            continue
        type_specific[key] = norm

    return fields, type_specific


def _build_claims_for_critic(fields: dict, type_specific: dict) -> dict:
    """Build the JSON the critic sees — value + grounding only."""
    claims = {}
    for k, v in fields.items():
        if not isinstance(v, dict) or "value" not in v:
            continue
        val = v["value"]
        if val is None:
            continue
        if isinstance(val, str):
            s = val.strip()
            if not s or s.upper() == "N/A":
                continue
        claims[k] = {
            "value": val,
            "evidence_bbox": v.get("evidence_bbox"),
            "evidence_text": v.get("evidence_text", ""),
            "evidence_kind": v.get("evidence_kind", "direct_quote"),
        }
    for k, v in type_specific.items():
        if not isinstance(v, dict) or "value" not in v:
            continue
        val = v["value"]
        if val is None:
            continue
        if isinstance(val, str):
            s = val.strip()
            if not s or s.upper() == "N/A":
                continue
        claims[f"type_specific.{k}"] = {
            "value": val,
            "evidence_bbox": v.get("evidence_bbox"),
            "evidence_text": v.get("evidence_text", ""),
            "evidence_kind": v.get("evidence_kind", "direct_quote"),
        }
    return claims


def _parse_verdicts(raw: dict) -> dict[str, dict]:
    """Parse the critic's verdicts dict into a clean per-field mapping."""
    if not isinstance(raw, dict):
        return {}
    verdicts = raw.get("verdicts") if "verdicts" in raw else raw
    if not isinstance(verdicts, dict):
        return {}
    out = {}
    for k, v in verdicts.items():
        if not isinstance(v, dict):
            continue
        ok = bool(v.get("ok", True))
        out[k] = {
            "ok": ok,
            "issue": str(v.get("issue", "") or "")[:400],
            "what_you_see": str(v.get("what_you_see", "") or "")[:400],
        }
    return out


def _build_correction_summary(claims: dict, verdicts: dict) -> str:
    """Human-readable summary of flagged fields for the correction prompt."""
    flagged = []
    for field, verdict in verdicts.items():
        if verdict.get("ok"):
            continue
        claim = claims.get(field, {})
        flagged.append({
            "field": field,
            "your_value": claim.get("value"),
            "your_evidence_bbox": claim.get("evidence_bbox"),
            "your_evidence_text": claim.get("evidence_text"),
            "critic_says_wrong_because": verdict.get("issue"),
            "critic_sees_in_that_bbox": verdict.get("what_you_see"),
        })
    if not flagged:
        return "(no fields flagged)"
    return json.dumps(flagged, indent=2, ensure_ascii=False)


async def _run_critic(
    image_b64: str,
    media_type: str,
    filename: str,
    fields: dict,
    type_specific: dict,
    critic_model: str,
    critic_api_key: str,
    max_tokens: int,
    context=None,
    row_info=None,
) -> tuple[dict, dict, LLMUsage]:
    """Run the grounding critic. Returns (verdicts, claims_sent, usage)."""
    claims = _build_claims_for_critic(fields, type_specific)
    if not claims:
        return {}, {}, LLMUsage()

    claims_json = json.dumps(claims, indent=2, ensure_ascii=False, default=str)
    sys_p = _get_tmpl("CRITIC_SYSTEM")
    user_text = _get_tmpl("CRITIC_USER").format(
        filename=filename, claims_json=claims_json,
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
        resp = await _call_conversation_with_recitation_retry(
            critic_model, sys_p, [user_msg], max_tokens, critic_api_key,
            context, row_info,
        )
    except Exception as exc:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": f"Critic call failed: {exc}"[:500],
            })
        return {}, claims, LLMUsage()

    parsed = extract_json(resp.text) or {}
    verdicts = _parse_verdicts(parsed)

    if context and row_info:
        flagged = [f for f, v in verdicts.items() if not v.get("ok")]
        await context.emit("ai_debug", {
            **row_info,
            "phase": "critic_review",
            "verdicts": verdicts,
            "flagged_count": len(flagged),
            "flagged_fields": flagged,
            "tokens": {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        })

    return verdicts, claims, resp.usage


def _apply_corrections(prev_fields: dict, prev_ts: dict,
                       new_fields: dict, new_ts: dict,
                       verdicts: dict) -> tuple[dict, dict]:
    """Merge a correction round's output back into the field set.

    - For every flagged field, replace with the new value (or drop if the
      extractor omitted it, signalling "cannot ground").
    - For accepted fields, keep the prior value unless the extractor
      re-sent it.
    - New field names that did not exist before are ignored.
    """
    flagged_keys = {k for k, v in verdicts.items() if not v.get("ok")}
    out_fields = dict(prev_fields)
    out_ts = dict(prev_ts)

    for k in list(flagged_keys):
        if k.startswith("type_specific."):
            ts_key = k[len("type_specific."):]
            if ts_key in new_ts:
                out_ts[ts_key] = new_ts[ts_key]
            else:
                out_ts.pop(ts_key, None)  # extractor gave up
        else:
            if k in new_fields:
                out_fields[k] = new_fields[k]
            else:
                out_fields.pop(k, None)  # extractor gave up

    # Also allow the extractor to update accepted fields if it wants to
    for k, v in new_fields.items():
        if k in out_fields and k not in flagged_keys:
            out_fields[k] = v
    for k, v in new_ts.items():
        if k in out_ts and f"type_specific.{k}" not in flagged_keys:
            out_ts[k] = v

    return out_fields, out_ts


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
            description=(
                "Grounded single-pass map metadata extraction with a "
                "second-agent critic loop that catches hallucinated fields."
            ),
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="model",
                    label="Extractor Model",
                    type="select",
                    default="",
                    options=[],
                    description="Vision-capable model used to extract grounded metadata "
                                "(GPT-4o, Claude, Gemini).",
                ),
                ConfigField(
                    name="critic_model",
                    label="Critic Model (grounding verifier)",
                    type="select",
                    default="",
                    options=[],
                    description="Second vision model that audits each grounded claim "
                                "against its evidence_bbox. Leave blank to skip the "
                                "verification loop. A different model from the extractor "
                                "gives the best independent check.",
                ),
                ConfigField(
                    name="max_correction_rounds",
                    label="Max Correction Rounds",
                    type="number",
                    default=2,
                    description="Maximum extractor↔critic correction cycles. Each "
                                "round adds two API calls per map. Set to 0 to run "
                                "the critic for read-only flagging without "
                                "feeding corrections back.",
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
                    description="Column containing image file paths.",
                ),
                ConfigField(
                    name="max_tokens",
                    label="Max Tokens",
                    type="number",
                    default=16000,
                    description="Maximum tokens per API response (high default to avoid truncation).",
                ),
                ConfigField(
                    name="concurrency",
                    label="Concurrency",
                    type="number",
                    default=0,
                    description="Parallel images (0 = auto). Each image makes 1 + "
                                "(2 × correction rounds) API calls when the critic is on.",
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
        max_correction_rounds = max(0, int(config.get("max_correction_rounds", 2)))

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
                critic_model = ""
            if critic_model and not critic_api_key:
                raise ValueError(
                    f"No API key for critic '{critic_model}'. Set it in Settings."
                )

        # Output columns
        original_columns = set(df.columns.tolist())
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

        if on_progress:
            await on_progress(
                f"Map Analysis (grounded + critic): {rows_with_images} images"
            )

        # Accumulate all debug events for archival
        _debug_archive: list[dict] = []
        _run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _orig_emit = context.emit if context else None

        async def _archiving_emit(event_type: str, data: dict):
            if event_type == "ai_debug":
                _debug_archive.append({
                    "ts": datetime.now().isoformat(),
                    **data,
                })
            if _orig_emit:
                await _orig_emit(event_type, data)

        if context:
            context.emit = _archiving_emit  # type: ignore

        async def process_map(i, idx, row):
            nonlocal completed, skipped, analyzed

            if not _has_image(row[image_column]):
                skipped += 1
                completed += 1
                return

            image_path = str(row[image_column]).strip()
            filename = os.path.basename(image_path)
            stem = os.path.splitext(filename)[0]
            _row = {"row": i + 1, "total": total, "filename": filename}
            _token_total = {"input": 0, "output": 0}

            async with sem:
                try:
                    from PIL import Image
                    img_full = Image.open(image_path)
                    img_full = _fix_mode(img_full)
                    full_w, full_h = img_full.size

                    # Encode the image once — reused across extract & critic
                    img_b64, img_mime, enc_w, enc_h = _full_image_b64(img_full)

                    if context:
                        await context.emit("ai_debug", {
                            **_row,
                            "phase": "extract_start",
                            "full_size": f"{full_w}x{full_h}",
                            "encoded_size": f"{enc_w}x{enc_h}",
                            "source_image": image_path,
                        })

                    # ─── Round 0: initial grounded extraction ───────────
                    if on_progress:
                        await on_progress(
                            f"[{i+1}/{rows_with_images}] {filename}: "
                            f"grounded extraction ({full_w}x{full_h})..."
                        )

                    _ex_sys = _get_tmpl("EXTRACT_SYSTEM")
                    _ex_kb = _get_kb("extract")
                    if _ex_kb:
                        _ex_sys = _ex_sys + "\n\n" + _ex_kb
                    ex_prompt = _get_tmpl("EXTRACT_USER").replace(
                        "{filename}", filename)
                    ex_prompt_path = _save_prompt_to_disk(
                        stem, "Extract", "round0", _ex_sys, ex_prompt
                    )

                    fewshot = _get_fewshot("extract")
                    user_msg = _make_vision_message(ex_prompt, img_b64, img_mime)
                    messages = (fewshot + [user_msg]) if fewshot else [user_msg]

                    resp = await _call_conversation_with_recitation_retry(
                        model, _ex_sys, messages,
                        max_tokens, api_key, context, _row,
                    )
                    _token_total["input"] += resp.usage.input_tokens
                    _token_total["output"] += resp.usage.output_tokens

                    raw = extract_json(resp.text) or {}
                    fields, type_specific = _parse_grounded(raw)

                    # Conversation history retained across correction rounds
                    conversation_history = [
                        user_msg,
                        _make_assistant_message(resp.text),
                    ]

                    if context:
                        await context.emit("ai_debug", {
                            **_row,
                            "phase": "extract_result",
                            "round": 0,
                            "fields_count": len(fields),
                            "type_specific_count": len(type_specific),
                            "field_names": sorted(fields.keys()),
                            "prompt_path": ex_prompt_path,
                            "llm_output": resp.text[:2500],
                        })

                    # ─── Critic loop ────────────────────────────────────
                    last_verdicts: dict = {}
                    last_claims: dict = {}

                    if critic_model and critic_api_key and (fields or type_specific):
                        for round_idx in range(max(1, max_correction_rounds + 1)):
                            # Always run critic once even when rounds == 0
                            if round_idx > max_correction_rounds:
                                break

                            verdicts, claims, c_usage = await _run_critic(
                                img_b64, img_mime, filename,
                                fields, type_specific,
                                critic_model, critic_api_key,
                                max_tokens, context, _row,
                            )
                            _token_total["input"] += c_usage.input_tokens
                            _token_total["output"] += c_usage.output_tokens
                            last_verdicts = verdicts
                            last_claims = claims

                            flagged = [k for k, v in verdicts.items()
                                       if not v.get("ok")]
                            if not flagged:
                                break
                            if round_idx >= max_correction_rounds:
                                # Critic flagged, but no rounds left to correct
                                break

                            # ── Correction round: feed back to extractor ──
                            if on_progress:
                                await on_progress(
                                    f"[{i+1}/{rows_with_images}] {filename}: "
                                    f"correction round {round_idx + 1} "
                                    f"({len(flagged)} flagged)..."
                                )

                            summary = _build_correction_summary(claims, verdicts)
                            correction_text = _get_tmpl("CORRECTION_USER").format(
                                verdicts_summary=summary,
                            )
                            correction_path = _save_prompt_to_disk(
                                stem, "Correction",
                                f"round{round_idx + 1}",
                                _ex_sys, correction_text,
                            )

                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "correction_sent",
                                    "round": round_idx + 1,
                                    "flagged_fields": flagged,
                                    "prompt_path": correction_path,
                                    "summary_preview": summary[:1500],
                                })

                            correction_msg = _make_text_message(correction_text)
                            conversation_history.append(correction_msg)

                            cor_resp = await _call_conversation_with_recitation_retry(
                                model, _ex_sys, conversation_history,
                                max_tokens, api_key, context, _row,
                            )
                            _token_total["input"] += cor_resp.usage.input_tokens
                            _token_total["output"] += cor_resp.usage.output_tokens
                            conversation_history.append(
                                _make_assistant_message(cor_resp.text)
                            )

                            cor_raw = extract_json(cor_resp.text) or {}
                            new_fields, new_ts = _parse_grounded(cor_raw)
                            fields, type_specific = _apply_corrections(
                                fields, type_specific,
                                new_fields, new_ts,
                                verdicts,
                            )

                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "correction_result",
                                    "round": round_idx + 1,
                                    "fields_count": len(fields),
                                    "type_specific_count": len(type_specific),
                                    "llm_output": cor_resp.text[:2500],
                                })

                    # ─── Final pass: demote any field critic still rejects ──
                    if last_verdicts:
                        for k, v in list(last_verdicts.items()):
                            if v.get("ok"):
                                continue
                            if k.startswith("type_specific."):
                                ts_key = k[len("type_specific."):]
                                # If field is unchanged from when critic flagged it,
                                # drop it
                                if ts_key in type_specific:
                                    prev_val = (last_claims.get(k) or {}).get("value")
                                    cur_val = type_specific[ts_key].get("value")
                                    if prev_val == cur_val:
                                        type_specific.pop(ts_key, None)
                            else:
                                if k in fields:
                                    prev_val = (last_claims.get(k) or {}).get("value")
                                    cur_val = fields[k].get("value")
                                    if prev_val == cur_val:
                                        fields.pop(k, None)

                    # ─── Evidence preview image ─────────────────────────
                    if fields or type_specific:
                        try:
                            pname = f"{stem}_evidence_{uuid.uuid4().hex[:6]}.png"
                            psave = os.path.join(_PREVIEW_DIR, pname)
                            ppath = _draw_evidence_preview(
                                img_full, fields, type_specific, psave,
                            )
                            df.at[idx, "map_regions_preview"] = ppath
                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "evidence_preview",
                                    "preview_path": ppath,
                                    "num_regions": len(fields) + len(type_specific),
                                    "source_image": image_path,
                                })
                        except Exception as exc:
                            if context:
                                await context.emit("ai_debug", {
                                    **_row,
                                    "phase": "evidence_preview_error",
                                    "error": str(exc)[:300],
                                })

                    # ─── Write to dataframe ────────────────────────────
                    for json_key, out_col in MAP_FIELDS:
                        entry = fields.get(json_key)
                        if not entry:
                            df.at[idx, out_col] = ""
                            continue
                        df.at[idx, out_col] = _coerce_value(
                            json_key, entry.get("value", "")
                        )

                    for ts_key, entry in type_specific.items():
                        col = f"ts_{ts_key}"
                        if not isinstance(entry, dict):
                            continue
                        val = entry.get("value", "")
                        if isinstance(val, (list, tuple)):
                            val = ", ".join(str(v) for v in val if v)
                        elif isinstance(val, bool):
                            val = "yes" if val else "no"
                        else:
                            val = clean_cell(val)
                        df.at[idx, col] = val

                    # ─── Done event ────────────────────────────────────
                    if context:
                        filled = sum(
                            1 for k, _ in MAP_FIELDS
                            if str(df.at[idx, _]).strip()
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
                            entry = fields.get(src_key)
                            if not entry:
                                continue
                            val = entry.get("value", "")
                            if val and str(val).strip():
                                if isinstance(val, (list, tuple)):
                                    sv = ", ".join(str(v) for v in val)
                                else:
                                    sv = str(val)
                                synthesis_result[dst_key] = sv

                        flagged_still = [
                            k for k, v in last_verdicts.items()
                            if not v.get("ok")
                            and (
                                (k.startswith("type_specific.")
                                 and k[len("type_specific."):] not in type_specific)
                                or (not k.startswith("type_specific.") and k not in fields)
                            )
                        ]

                        await context.emit("ai_debug", {
                            **_row,
                            "phase": "done",
                            "fields_filled": filled,
                            "synthesis_result": synthesis_result,
                            "fields_demoted_by_critic": flagged_still,
                            "token_usage": {
                                "input_tokens": _token_total["input"],
                                "output_tokens": _token_total["output"],
                                "total_tokens": _token_total["input"] + _token_total["output"],
                            },
                        })

                    img_full.close()

                except Exception as exc:
                    if context:
                        await context.emit("ai_debug", {
                            **_row,
                            "phase": "error",
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

        tasks = [
            process_map(i, idx, row)
            for i, (idx, row) in enumerate(df.iterrows())
        ]
        await asyncio.gather(*tasks)

        # ═══ Archive debug logs ═══════════════════════════════════════
        if context and _orig_emit:
            context.emit = _orig_emit  # type: ignore

        if _debug_archive:
            try:
                archive_path = _archive_debug_logs(_debug_archive, _run_timestamp)
                if context:
                    await context.emit("ai_debug", {
                        "row": 0, "total": total,
                        "phase": "debug_archive",
                        "archive_path": archive_path,
                        "entry_count": len(_debug_archive),
                    })
            except Exception:
                pass

        if on_progress:
            await on_progress(
                f"Map Analysis complete: {analyzed} maps, {skipped} skipped"
            )

        df = _reorder_ts_columns(df)

        if bool(config.get("dublin_core_export", False)):
            df = _add_dublin_core_columns(df)

        return {"output": df}
