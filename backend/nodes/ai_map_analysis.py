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


def _read_image_physical_info(image_path: str) -> dict:
    """Read DPI + pixel dims from the image file and compute physical cm.

    Returns: {pixel_w, pixel_h, dpi_x, dpi_y, image_w_cm, image_h_cm}.
    Any field is 0 if not determinable.
    """
    from PIL import Image
    out = {
        "pixel_w": 0, "pixel_h": 0,
        "dpi_x": 0.0, "dpi_y": 0.0,
        "image_w_cm": 0.0, "image_h_cm": 0.0,
    }
    try:
        with Image.open(image_path) as im:
            out["pixel_w"], out["pixel_h"] = im.size
            dpi = im.info.get("dpi")
            if dpi and isinstance(dpi, (tuple, list)) and len(dpi) >= 2:
                try:
                    dx, dy = float(dpi[0]), float(dpi[1])
                    if dx > 0 and dy > 0:
                        out["dpi_x"] = round(dx, 1)
                        out["dpi_y"] = round(dy, 1)
                        # 1 inch = 2.54 cm
                        out["image_w_cm"] = round(out["pixel_w"] / dx * 2.54, 2)
                        out["image_h_cm"] = round(out["pixel_h"] / dy * 2.54, 2)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return out


# Heuristic to classify the source of a scale_ratio claim.
# This is applied to the evidence_text the extractor provides.
def _classify_scale_source(evidence_text: str, evidence_kind: str) -> str:
    """Return one of: printed_ratio, computed_from_text, computed_from_bar, unknown."""
    if not evidence_text:
        return "unknown"
    if evidence_kind == "direct_quote":
        # OCR'd directly from a printed ratio like "1:25000"
        if re.search(r"\d[\d,]{2,}\s*$", evidence_text) or "1:" in evidence_text:
            return "printed_ratio"
        return "direct_quote_other"
    if evidence_kind != "computed":
        return "unknown"
    et = evidence_text.lower()
    # Bar-derived: "scale bar", "graphical scale", contains "→" with units
    if "bar" in et or "graphical" in et or "mile" in et or "km" in et or "inch" in et:
        return "computed_from_bar"
    return "computed_from_text"


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


# Transient errors we retry: network blips, 5xx, rate limits, upstream timeouts.
# We DON'T retry on auth errors, content-policy refusals, geo-blocks etc.
_TRANSIENT_MARKERS = (
    "connection error", "connection reset", "connection aborted",
    "timeout", "timed out", "deadline exceeded",
    "503", "502", "504", "529",  # 529 = Anthropic overload
    "rate limit", "rate-limit", "ratelimit",
    "temporarily unavailable", "service unavailable",
    "upstream", "bad gateway",
)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


async def _with_retry(coro_factory, *, max_attempts: int = 4,
                      base_delay: float = 2.0, context=None, row_info=None,
                      label: str = ""):
    """Call coro_factory() up to max_attempts times on transient failures.

    base_delay grows exponentially (2, 4, 8 sec ...). Non-transient exceptions
    re-raise immediately.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_factory()
        except GeminiRecitationError:
            raise  # handled separately by the recitation wrapper
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_transient(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            if context and row_info:
                await context.emit("ai_debug", {
                    **row_info,
                    "phase": "transient_retry",
                    "attempt": attempt,
                    "next_delay_sec": delay,
                    "label": label,
                    "error": str(exc)[:300],
                })
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc


async def _call_with_recitation_retry(
    model, system, user_text, image_b64, image_mime,
    max_tokens, api_key, context=None, row_info=None,
) -> LLMResponse:
    """Call vision LLM with transient-error retry + Gemini recitation fallback."""
    async def _attempt(sys_p):
        return await _with_retry(
            lambda: call_vision_llm(
                model, sys_p, user_text,
                image_b64, image_mime, max_tokens, api_key,
            ),
            context=context, row_info=row_info, label=f"call_vision[{model}]",
        )

    try:
        return await _attempt(system)
    except GeminiRecitationError:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": "Gemini RECITATION block — retrying with catalogue framing...",
            })
        return await _attempt(_CATALOGUE_PREFIX + "\n\n" + system)


async def _call_conversation_with_recitation_retry(
    model, system, messages, max_tokens, api_key, context=None, row_info=None,
) -> LLMResponse:
    """Call vision conversation with transient-error retry + Gemini recitation fallback."""
    async def _attempt(sys_p):
        return await _with_retry(
            lambda: call_vision_conversation(
                model, sys_p, messages, max_tokens, api_key,
            ),
            context=context, row_info=row_info,
            label=f"call_vision_conv[{model}]",
        )

    try:
        return await _attempt(system)
    except GeminiRecitationError:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": "Gemini RECITATION block — retrying with catalogue framing...",
            })
        return await _attempt(_CATALOGUE_PREFIX + "\n\n" + system)


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

BBOX TIGHTNESS RULE — DO NOT USE THE FULL-IMAGE BBOX
[0, 0, 100, 100] (covering the entire image) is FORBIDDEN for any
direct_quote or computed field. A title block, scale bar, coordinate
strip, legend, etc. occupies a small fraction of the image — your
evidence_bbox must reflect that. A typical text bbox is 5-40% wide,
2-15% tall. A typical strip bbox is 80-100% wide but only 3-10% tall
(or vice-versa). If you cannot locate the value within a small region,
the value is probably not visible — OMIT the field instead.

The only fields where a wide bbox is acceptable are visual_observation
fields whose evidence really IS the whole image:
  map_type, medium, condition, description, has_insets
and even there, prefer the smallest region that demonstrates the trait.

RULES
- NEVER include a field whose value you cannot ground. If you cannot
  OCR / see / compute it, OMIT it.
- evidence_bbox must cover the region where the evidence is actually
  visible (not where the metadata belongs conceptually).
- For "computed" fields, point the bbox at the SOURCE region (e.g. for
  scale_ratio computed from a scale bar, point at the scale bar).

ANTI-HALLUCINATION HARD RULES — most-leaked fields
- country / province / city / district: ONLY list a place name that
  you can SEE PRINTED on the map (in the title, legend, or as a label
  on the body). Do NOT infer the country from world knowledge of which
  countries border the depicted region. Example: an Arctic map showing
  "GREENLAND" and "SPITSBERGEN" labels lets you write country=
  "Greenland, Norway"; it does NOT let you write "USA, Canada, Russia"
  just because those countries also border the Arctic. If the scan
  appears to be a partial / cropped view, only describe the visible
  portion.
- bbox_west / bbox_east / bbox_south / bbox_north: ONLY emit a value
  for an edge if you can SEE a printed coordinate tick / label at that
  edge in the visible image. Do NOT emit -180 / 180 unless those exact
  values are printed and visible. Do NOT emit 90°N for a polar map
  unless the scan shows the pole label. For partial-scan maps where
  one or more edges are missing, EMIT ONLY THE EDGES WHERE LABELS ARE
  VISIBLE and OMIT the others (leave them out entirely).
- publisher: ONLY a name printed somewhere on the visible map (title
  block, margin, or copyright line). Do NOT supply a publisher from
  knowledge of which institution typically produces this kind of map.
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
# Specialist critic prompts — three domains, three calibrations
#
# Each specialist sees only the claims in its domain, with a strictness
# tuned for that domain's failure modes:
#   geo    — STRICT (training-knowledge leak is the main risk)
#   ocr    — MEDIUM (catch character-level errors, tolerate paraphrase)
#   visual — LENIENT (classification, paraphrase is fine)
# ═════════════════════════════════════════════════════════════════════════════

# Shared JSON return shape & rules used by all three critics.
# Braces in the JSON example are doubled because each *_USER template is
# fed through .format(filename=..., claims_json=...) downstream; only
# the {filename} / {claims_json} placeholders should expand.
_CRITIC_RETURN_SHAPE = """\
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
      "issue": "one sentence — what specifically is wrong",
      "what_you_see": "what IS visible at/near the bbox"
    }}
  }}
}}

For "type_specific" entries, prefix the key with "type_specific." \
(e.g. "type_specific.contour_interval"). When ok=true, "issue" and \
"what_you_see" MUST be empty. When ok=false, both are required. \
Audit ONLY fields present in the input claims. Do NOT invent fields."""


# ── GEO critic — strict, anti-hallucination ────────────────────────────────

GEO_CRITIC_SYSTEM = """\
You are a geographic-claim fact-checker for map metadata. You audit
ONLY fields that name administrative regions or coordinate bounds:
  country, province, city, district,
  coordinates_text, bbox_west, bbox_east, bbox_south, bbox_north.

Be STRICT. These fields are the most-leaked category — a model that
"knows" what region a map depicts will list bordering countries and
plausible coordinate ranges that aren't actually printed on the scan.
Your job: catch every such leak.

Verdict policy
- ok = true   ONLY if the value has direct visible evidence on the map:
              * Each named place (country/province/city/district) must
                have a corresponding label PRINTED on the map (in the
                title, legend, or as a place label).
              * Each bbox_* edge must correspond to a coordinate tick
                or label PRINTED at the visible edge.
              * Saying "country=USA" requires a visible "USA" / "United
                States" label or visible US territory with a name label
                you can point to.
- ok = false  if the value is plausible from world knowledge of which
              countries border the depicted region but you cannot point
              to a printed label on the scan.
- ok = false  for partial / cropped scans where bbox edges have been
              extrapolated to the full original map area.

Synonym/abbreviation tolerance: "SA" → "South Australia", "U.S.A." →
"USA" are still ok=true if any form is visible.

You may NOT add fields. You may NOT correct values. You only flag.
Return STRICT JSON only."""

GEO_CRITIC_USER = """\
Audit the GEOGRAPHIC claims for this map.

Filename: {filename}

═══ GEOGRAPHIC CLAIMS ═══
{claims_json}

For each field, look at the evidence_bbox region AND the broader image:
- ok=true  ONLY if every named place has a visible label, OR every
           bbox edge corresponds to a visible printed coordinate tick.
- ok=false if any named place lacks a visible label, OR any bbox edge
           extrapolates beyond what the scan actually shows.

""" + _CRITIC_RETURN_SHAPE


# ── OCR critic — medium strictness ─────────────────────────────────────────

OCR_CRITIC_SYSTEM = """\
You are an OCR-fidelity fact-checker for map metadata. You audit ONLY
fields that quote or interpret PRINTED TEXT on the map:
  title, date_text, date_year, publisher, scale_text, scale_ratio,
  projection, edition, legend_content, notes, place_names.

Verdict policy
- ok = true   if the value matches the visible printed text closely.
              You should ACCEPT:
              * paraphrasing / summarization of long notes
              * minor punctuation differences
              * scale_ratio numerically within 2% of the printed value
              * place_names that lists ANY 3-5 visible names
              * date_year computed correctly from a visible date_text
- ok = false  if there's a CHARACTER-LEVEL OCR error you can verify
              against the bbox (e.g. value says "S.G.F" but image shows
              "N.G.F"), OR a publisher / projection / edition that is
              NOT printed anywhere on the visible map (training-knowledge
              leak — common for famous map series).

A loose bbox alone is not grounds to flag. If the value is visible
SOMEWHERE on the map and basically matches, accept it.

You may NOT add fields. You may NOT correct values. You only flag.
Return STRICT JSON only."""

OCR_CRITIC_USER = """\
Audit the OCR/text claims for this map.

Filename: {filename}

═══ OCR/TEXT CLAIMS ═══
{claims_json}

For each field, compare the value to the printed text visible in the
image (search the whole map, not just the bbox — bboxes may be loose):
- ok=true  if the printed text supports the value (paraphrase OK).
- ok=false ONLY for character-level mismatches you can verify, or for
           publisher/projection/edition values that aren't printed
           anywhere visible.

""" + _CRITIC_RETURN_SHAPE


# ── Visual critic — lenient ────────────────────────────────────────────────

VISUAL_CRITIC_SYSTEM = """\
You are a visual-classification fact-checker for map metadata. You
audit ONLY fields about overall visual character:
  map_type, medium, condition, coverage, subject, language,
  has_insets, description.

These are interpretive classifications — paraphrase, synonym, and
slight abstraction are EXPECTED. Be LENIENT.

Verdict policy
- ok = true  whenever the value is a reasonable visual classification
             of the map, even if you would have phrased it differently.
             ACCEPT:
             * synonyms ("monochrome" vs "black and white")
             * different but compatible map_type assignments
             * description paraphrases
             * has_insets descriptions that name visible inset boxes
- ok = false ONLY if the classification is clearly wrong:
             * a topographic map labelled map_type="celestial"
             * description mentioning features absent from the image
             * has_insets="yes: X" where X is on the main map, not an inset
             * language claim contradicting visible text

When in doubt, ok=true.

You may NOT add fields. You may NOT correct values. You only flag.
Return STRICT JSON only."""

VISUAL_CRITIC_USER = """\
Audit the visual-classification claims for this map.

Filename: {filename}

═══ VISUAL CLAIMS ═══
{claims_json}

Be lenient — these are interpretive. Only flag clearly-wrong
classifications.

""" + _CRITIC_RETURN_SHAPE


# Field → domain mapping. type_specific.* fields all go to "visual"
# (free-form bag, easiest to audit lightly).
_FIELD_DOMAINS: dict[str, str] = {
    # Geo (strict)
    "country":          "geo",
    "province":         "geo",
    "city":             "geo",
    "district":         "geo",
    "coordinates_text": "geo",
    "bbox_west":        "geo",
    "bbox_east":        "geo",
    "bbox_south":       "geo",
    "bbox_north":       "geo",
    # OCR (medium)
    "title":            "ocr",
    "date_text":        "ocr",
    "date_year":        "ocr",
    "publisher":        "ocr",
    "scale_text":       "ocr",
    "scale_ratio":      "ocr",
    "projection":       "ocr",
    "edition":          "ocr",
    "legend_content":   "ocr",
    "notes":            "ocr",
    "place_names":      "ocr",
    # Visual (lenient)
    "map_type":         "visual",
    "subject":          "visual",
    "coverage":         "visual",
    "medium":           "visual",
    "language":         "visual",
    "condition":        "visual",
    "has_insets":       "visual",
    "description":      "visual",
}


def _domain_of(field_key: str) -> str:
    """Pick the right specialist domain for a field key."""
    if field_key.startswith("type_specific."):
        return "visual"
    return _FIELD_DOMAINS.get(field_key, "visual")


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
- IMPORTANT: If a flagged field's VALUE is actually correct (you can
  still see it on the map), KEEP THE VALUE — just provide a tighter
  evidence_bbox. The critic mostly flags wide bboxes; that is a
  bbox problem, not a value problem.
- For each previously-flagged field, either provide a TIGHTER
  evidence_bbox + same/corrected value + evidence_text + evidence_kind,
  OR omit it (only if the value really isn't on the map).
- A tight bbox is 5-40% wide for text, narrow strips along edges for
  coordinates, etc. [0,0,100,100] is NOT acceptable as a correction.
- Do NOT introduce new field names that were not in your previous output.
- Do NOT defend an outside-knowledge claim — if the value is not visible
  in the image, omit the field.
- The same grounding rule applies: every value you keep needs an
  evidence_bbox you can point to."""


# ═════════════════════════════════════════════════════════════════════════════
# Rescue prompt — salvages demoted fields from the critic's own observations
#
# Insight: when the critic rejects a value, its `what_you_see` field already
# describes what IS actually visible in that bbox region — often containing
# the correct OCR'd text or computed value. We don't need to re-call a vision
# model; we just ask a small TEXT-ONLY model to convert the critic's free-form
# observation into a typed field value. Marginal cost per call.
# ═════════════════════════════════════════════════════════════════════════════

RESCUE_SYSTEM = """\
You are a metadata recovery agent. A previous extraction was demoted
because the fact-checker disagreed with the value but provided their
own observation of what IS visible in the region. Your job: convert
the fact-checker's observation into the correct value for the
specified field — IF the observation actually contains enough
information to do so confidently.

You receive ONLY text. Do NOT speculate beyond what the observation
states. If the observation does not clearly contain a value for the
requested field, return value=null and confident=false.

Return STRICT JSON only — no commentary."""

RESCUE_USER = """\
Field to recover: {field_name}
Field type:       {field_type}
Expected format:  {field_format}

The fact-checker's observation about that region of the map:
\"\"\"{what_you_see}\"\"\"

The extractor's previously-rejected guess (for context — do NOT
default to it): {old_value}
Why it was rejected: {issue}

Return STRICT JSON:

{{
  "value": <a value of the expected type, or null if the observation
           does not clearly contain one>,
  "confident": <true if you are highly confident the value is correct
                from the observation alone; false if you have to guess>,
  "reasoning": "<one short sentence>"
}}

Rules:
- If the observation only describes the region in general terms
  without stating the specific value, return value=null.
- For numeric fields (date_year, scale_ratio, bbox_west, etc.),
  value must be a JSON number, not a string.
- For coordinate fields (bbox_*), convert from degree/minute/second
  text to decimal degrees (west/south are negative).
- Never invent information that is not in the observation."""


# Per-field hints for the rescue prompt — what shape the value should
# take. Defaults to "string" if not listed.
_RESCUE_FIELD_HINTS: dict[str, tuple[str, str]] = {
    "title":            ("string", "exact title text"),
    "date_text":        ("string", "date as printed"),
    "date_year":        ("integer", "4-digit year"),
    "publisher":        ("string", "publisher name only"),
    "scale_text":       ("string", "scale as printed"),
    "scale_ratio":      ("integer", "denominator only (e.g. 63360 for 1:63,360)"),
    "projection":       ("string", "projection name"),
    "edition":          ("string", "edition text"),
    "coordinates_text": ("string", "lat/long range as text"),
    "bbox_west":        ("number",  "decimal degrees, NEGATIVE for west hemisphere"),
    "bbox_east":        ("number",  "decimal degrees, NEGATIVE for west hemisphere"),
    "bbox_south":       ("number",  "decimal degrees, NEGATIVE for south hemisphere"),
    "bbox_north":       ("number",  "decimal degrees, NEGATIVE for south hemisphere"),
    "place_names":      ("string", "comma-separated, up to 15"),
    "legend_content":   ("string", "main legend entries"),
    "notes":            ("string", "printed notes"),
    "country":          ("string", "country name(s) comma-separated"),
    "province":         ("string", "state/province"),
    "city":             ("string", "city name"),
    "district":         ("string", "district/county"),
    "language":         ("string", "language name(s)"),
}


def _rescue_field_hint(field_key: str) -> tuple[str, str]:
    # type_specific.* fields fall through to string
    base = field_key[len("type_specific."):] if field_key.startswith("type_specific.") else field_key
    return _RESCUE_FIELD_HINTS.get(base, ("string", "free-form value"))


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


# Templates for each specialist — kept as keys so prompt_templates router
# can expose them for runtime editing.
_DOMAIN_TEMPLATE_KEYS = {
    "geo":    ("GEO_CRITIC_SYSTEM",    "GEO_CRITIC_USER"),
    "ocr":    ("OCR_CRITIC_SYSTEM",    "OCR_CRITIC_USER"),
    "visual": ("VISUAL_CRITIC_SYSTEM", "VISUAL_CRITIC_USER"),
}

_DOMAIN_LABEL = {"geo": "Geo", "ocr": "OCR", "visual": "Visual"}


def _partition_claims_by_domain(claims: dict) -> dict[str, dict]:
    """Split a flat claims dict into {domain: {field: claim}} buckets."""
    buckets: dict[str, dict] = {"geo": {}, "ocr": {}, "visual": {}}
    for k, v in claims.items():
        dom = _domain_of(k)
        buckets[dom][k] = v
    return buckets


async def _run_one_specialist(
    domain: str,
    image_b64: str,
    media_type: str,
    filename: str,
    domain_claims: dict,
    critic_model: str,
    critic_api_key: str,
    max_tokens: int,
    context=None,
    row_info=None,
) -> tuple[dict, LLMUsage]:
    """Run a single specialist critic on its slice of claims."""
    if not domain_claims:
        return {}, LLMUsage()

    sys_key, usr_key = _DOMAIN_TEMPLATE_KEYS[domain]
    sys_p = _get_tmpl(sys_key)
    claims_json = json.dumps(domain_claims, indent=2, ensure_ascii=False, default=str)
    user_text = _get_tmpl(usr_key).format(
        filename=filename, claims_json=claims_json,
    )
    user_msg = _make_vision_message(user_text, image_b64, media_type)

    if context and row_info:
        await context.emit("ai_debug", {
            **row_info,
            "phase": "critic_start",
            "domain": domain,
            "critic_model": critic_model,
            "claim_count": len(domain_claims),
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
                "error": f"Critic[{domain}] call failed: {exc}"[:500],
            })
        return {}, LLMUsage()

    parsed = extract_json(resp.text) or {}
    verdicts = _parse_verdicts(parsed)

    # Keep only verdicts for fields we actually sent — defends against
    # hallucinated field names in critic output
    verdicts = {k: v for k, v in verdicts.items() if k in domain_claims}

    if context and row_info:
        flagged = [f for f, v in verdicts.items() if not v.get("ok")]
        await context.emit("ai_debug", {
            **row_info,
            "phase": "critic_review",
            "domain": domain,
            "verdicts": verdicts,
            "flagged_count": len(flagged),
            "flagged_fields": flagged,
            "tokens": {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        })

    return verdicts, resp.usage


async def _run_specialist_critics(
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
    """Run geo / ocr / visual critics in parallel on their slices.

    Returns (merged_verdicts, claims_sent, total_usage).
    """
    claims = _build_claims_for_critic(fields, type_specific)
    if not claims:
        return {}, {}, LLMUsage()

    buckets = _partition_claims_by_domain(claims)

    # Run the three specialists concurrently — each gets its own slice
    results = await asyncio.gather(
        _run_one_specialist(
            "geo", image_b64, media_type, filename, buckets["geo"],
            critic_model, critic_api_key, max_tokens, context, row_info,
        ),
        _run_one_specialist(
            "ocr", image_b64, media_type, filename, buckets["ocr"],
            critic_model, critic_api_key, max_tokens, context, row_info,
        ),
        _run_one_specialist(
            "visual", image_b64, media_type, filename, buckets["visual"],
            critic_model, critic_api_key, max_tokens, context, row_info,
        ),
        return_exceptions=False,
    )

    merged_verdicts: dict = {}
    total = LLMUsage()
    for verdicts, usage in results:
        merged_verdicts.update(verdicts)
        total.input_tokens += usage.input_tokens
        total.output_tokens += usage.output_tokens

    return merged_verdicts, claims, total


# Back-compat shim — the old single-critic name still callable.
async def _run_critic(*args, **kwargs):
    return await _run_specialist_critics(*args, **kwargs)


# ═════════════════════════════════════════════════════════════════════════════
# Rescue pass — recover demoted fields from the critic's own observation
# ═════════════════════════════════════════════════════════════════════════════

async def _run_one_rescue(
    field_key: str,
    old_value,
    issue: str,
    what_you_see: str,
    rescue_model: str,
    rescue_api_key: str,
    max_tokens: int,
    context=None,
    row_info=None,
) -> tuple[dict | None, LLMUsage]:
    """Send a single text-only rescue request for one demoted field.

    Returns (rescue_result_dict_or_None, usage).
    """
    if not what_you_see or not what_you_see.strip():
        return None, LLMUsage()

    ftype, fformat = _rescue_field_hint(field_key)
    sys_p = _get_tmpl("RESCUE_SYSTEM")
    user_text = _get_tmpl("RESCUE_USER").format(
        field_name=field_key,
        field_type=ftype,
        field_format=fformat,
        what_you_see=what_you_see.strip(),
        old_value=json.dumps(old_value, ensure_ascii=False, default=str),
        issue=(issue or "").strip(),
    )

    # Use the text-only call path — no image attached. Reuses
    # providers' call_vision_conversation but with a text-only message.
    msgs = [_make_text_message(user_text)]
    try:
        resp = await _call_conversation_with_recitation_retry(
            rescue_model, sys_p, msgs, max_tokens, rescue_api_key,
            context, row_info,
        )
    except Exception as exc:
        if context and row_info:
            await context.emit("ai_debug", {
                **row_info,
                "phase": "error",
                "error": f"Rescue[{field_key}] call failed: {exc}"[:500],
            })
        return None, LLMUsage()

    parsed = extract_json(resp.text) or {}
    if not isinstance(parsed, dict):
        return None, resp.usage

    val = parsed.get("value")
    confident = bool(parsed.get("confident", False))
    reasoning = str(parsed.get("reasoning", "") or "")[:300]

    return {
        "value": val,
        "confident": confident,
        "reasoning": reasoning,
    }, resp.usage


async def _run_rescue_pass(
    last_verdicts: dict,
    last_claims: dict,
    demoted_keys: set[str],
    rescue_model: str,
    rescue_api_key: str,
    max_tokens: int,
    context=None,
    row_info=None,
) -> tuple[dict, LLMUsage]:
    """Try to salvage each demoted field from its critic's own observation.

    Returns ({field_key: rescued_value_dict}, total_usage). Caller
    decides whether to write the value back to the dataframe.

    No image is sent — this is a pure-text extraction of the critic's
    `what_you_see` notes into a typed value. Marginal cost.
    """
    rescues: dict[str, dict] = {}
    total = LLMUsage()
    if not demoted_keys or not rescue_model or not rescue_api_key:
        return rescues, total

    targets = []
    for k in demoted_keys:
        v = last_verdicts.get(k, {})
        if v.get("ok"):
            continue
        wys = v.get("what_you_see", "")
        if not wys or not wys.strip():
            continue
        claim = last_claims.get(k, {})
        targets.append((k, claim.get("value"), v.get("issue", ""), wys))

    if not targets:
        return rescues, total

    if context and row_info:
        await context.emit("ai_debug", {
            **row_info,
            "phase": "rescue_start",
            "rescue_model": rescue_model,
            "field_count": len(targets),
            "fields": [k for k, *_ in targets],
        })

    results = await asyncio.gather(*(
        _run_one_rescue(
            k, old, issue, wys,
            rescue_model, rescue_api_key, max_tokens,
            context, row_info,
        )
        for k, old, issue, wys in targets
    ), return_exceptions=False)

    successes = []
    for (k, old, issue, wys), (rescue_result, usage) in zip(targets, results):
        total.input_tokens += usage.input_tokens
        total.output_tokens += usage.output_tokens
        if not rescue_result:
            continue
        if not rescue_result.get("confident"):
            continue
        if rescue_result.get("value") in (None, "", "null"):
            continue
        rescues[k] = rescue_result
        successes.append(k)

    if context and row_info:
        await context.emit("ai_debug", {
            **row_info,
            "phase": "rescue_result",
            "rescued_count": len(successes),
            "rescued_fields": successes,
            "tokens": {
                "input_tokens": total.input_tokens,
                "output_tokens": total.output_tokens,
            },
        })

    return rescues, total


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
                    name="enable_rescue",
                    label="Rescue demoted fields",
                    type="boolean",
                    default=True,
                    description="After the critic finalises its verdicts, attempt "
                                "to recover demoted fields by parsing the critic's "
                                "own observation (what_you_see) into a typed value. "
                                "Text-only call, ~$0.00005 per rescued field.",
                ),
                ConfigField(
                    name="rescue_model",
                    label="Rescue Model",
                    type="select",
                    default="",
                    options=[],
                    description="Small text-mode model that converts critic notes "
                                "into structured values. Defaults to the critic model.",
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

        # Rescue model recovers demoted fields from the critic's own
        # observation. Defaults to the critic model since the call is
        # text-only and small. Set to "" to disable rescue.
        rescue_model = (
            config.get("rescue_model")
            or critic_model
            or ""
        ).strip() if config.get("enable_rescue", True) else ""
        rescue_api_key = ""
        if rescue_model and context:
            try:
                rescue_provider_id = get_provider_id_for_model(rescue_model)
                rescue_api_key = context.get_api_key(rescue_provider_id)
            except ValueError:
                rescue_model = ""
            if rescue_model and not rescue_api_key:
                # Don't hard-fail — rescue is a quality boost, not core.
                rescue_model = ""

        # Output columns
        original_columns = set(df.columns.tolist())

        # Physical dimensions (filename-derived; ground truth depends on the
        # operator naming the file correctly — may NOT match what was scanned)
        if "map_width_cm" not in df.columns:
            df["map_width_cm"] = 0.0
        if "map_height_cm" not in df.columns:
            df["map_height_cm"] = 0.0

        # Image-file physical info read from the image itself.
        # These are ground-truth for the scan (independent of the filename).
        for col, default in [
            ("map_pixel_w", 0), ("map_pixel_h", 0),
            ("map_dpi_x", 0.0), ("map_dpi_y", 0.0),
            ("map_image_w_cm", 0.0), ("map_image_h_cm", 0.0),
            ("map_scale_source", ""),
        ]:
            if col not in df.columns:
                df[col] = default

        for idx_dim, row_dim in df.iterrows():
            path = str(row_dim.get(image_column, "")).strip()
            fn = os.path.basename(path)
            # Filename-claimed dimensions (preserved for backward compat)
            w_cm, h_cm = _extract_dimensions_cm(fn)
            if w_cm > 0:
                df.at[idx_dim, "map_width_cm"] = w_cm
                df.at[idx_dim, "map_height_cm"] = h_cm
            # Image-derived physical info
            if path and os.path.isfile(path):
                info = _read_image_physical_info(path)
                df.at[idx_dim, "map_pixel_w"] = info["pixel_w"]
                df.at[idx_dim, "map_pixel_h"] = info["pixel_h"]
                df.at[idx_dim, "map_dpi_x"] = info["dpi_x"]
                df.at[idx_dim, "map_dpi_y"] = info["dpi_y"]
                df.at[idx_dim, "map_image_w_cm"] = info["image_w_cm"]
                df.at[idx_dim, "map_image_h_cm"] = info["image_h_cm"]

        for _, out_col in MAP_FIELDS:
            if out_col not in df.columns:
                df[out_col] = ""
        if "map_regions_preview" not in df.columns:
            df["map_regions_preview"] = ""
        # Audit columns — fields that critic touched but were KEPT (uncertain)
        # vs fields critic finally rejected (demoted to empty). Surface these
        # so a human reviewer can scan only the rows that warrant attention.
        if "map_review_fields_uncertain" not in df.columns:
            df["map_review_fields_uncertain"] = ""
        if "map_review_fields_demoted" not in df.columns:
            df["map_review_fields_demoted"] = ""
        if "map_review_fields_rescued" not in df.columns:
            df["map_review_fields_rescued"] = ""
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
                    # Per-field provenance for the audit columns: which fields
                    # were flagged at any point during the loop. Even if a
                    # field ultimately survives (extractor fixed it), the fact
                    # that it had to be challenged is signal for human review.
                    ever_flagged: set[str] = set()

                    if critic_model and critic_api_key and (fields or type_specific):
                        for round_idx in range(max(1, max_correction_rounds + 1)):
                            # Always run critic once even when rounds == 0
                            if round_idx > max_correction_rounds:
                                break

                            verdicts, claims, c_usage = await _run_specialist_critics(
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
                            ever_flagged.update(flagged)
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
                    demoted: set[str] = set()
                    if last_verdicts:
                        for k, v in list(last_verdicts.items()):
                            if v.get("ok"):
                                continue
                            if k.startswith("type_specific."):
                                ts_key = k[len("type_specific."):]
                                if ts_key in type_specific:
                                    prev_val = (last_claims.get(k) or {}).get("value")
                                    cur_val = type_specific[ts_key].get("value")
                                    if prev_val == cur_val:
                                        type_specific.pop(ts_key, None)
                                        demoted.add(k)
                            else:
                                if k in fields:
                                    prev_val = (last_claims.get(k) or {}).get("value")
                                    cur_val = fields[k].get("value")
                                    if prev_val == cur_val:
                                        fields.pop(k, None)
                                        demoted.add(k)
                    # ─── Rescue pass — recover demoted fields from the
                    #     critic's `what_you_see` notes. Text-only call,
                    #     marginal cost.
                    rescued_keys: set[str] = set()
                    if rescue_model and rescue_api_key and demoted:
                        rescues, r_usage = await _run_rescue_pass(
                            last_verdicts, last_claims, demoted,
                            rescue_model, rescue_api_key,
                            max_tokens, context, _row,
                        )
                        _token_total["input"]  += r_usage.input_tokens
                        _token_total["output"] += r_usage.output_tokens
                        for k, r in rescues.items():
                            val = r["value"]
                            # Synthesize a minimal grounded entry so the
                            # downstream writer treats it like any other
                            # field. evidence_kind = "computed" because
                            # the value was derived from the critic's
                            # observation, not OCR'd directly.
                            synth_entry = {
                                "value": val,
                                "evidence_bbox": (last_claims.get(k) or {}).get(
                                    "evidence_bbox", [0, 0, 100, 100],
                                ),
                                "evidence_text": (
                                    f"rescued from critic observation: "
                                    f"{r.get('reasoning','')}"
                                )[:400],
                                "evidence_kind": "computed",
                            }
                            if k.startswith("type_specific."):
                                ts_key = k[len("type_specific."):]
                                type_specific[ts_key] = synth_entry
                            else:
                                fields[k] = synth_entry
                            rescued_keys.add(k)
                        # Demoted ↑ rescued — they're no longer "lost"
                        demoted = demoted - rescued_keys

                    # Fields that were flagged at some point but survived
                    # — those are "uncertain" and worth manual review.
                    uncertain: set[str] = ever_flagged - demoted - rescued_keys - {
                        k for k in ever_flagged
                        if (k.startswith("type_specific.")
                            and k[len("type_specific."):] not in type_specific)
                        or (not k.startswith("type_specific.") and k not in fields)
                    }
                    df.at[idx, "map_review_fields_uncertain"] = (
                        ", ".join(sorted(uncertain)) if uncertain else ""
                    )
                    df.at[idx, "map_review_fields_demoted"] = (
                        ", ".join(sorted(demoted)) if demoted else ""
                    )
                    if "map_review_fields_rescued" in df.columns:
                        df.at[idx, "map_review_fields_rescued"] = (
                            ", ".join(sorted(rescued_keys)) if rescued_keys else ""
                        )

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

                    # Tag where the scale_ratio came from so a human reviewer
                    # knows which values warrant manual verification (numbers
                    # derived from a graphical scale bar are inherently
                    # less precise than printed ratios).
                    scale_entry = fields.get("scale_ratio")
                    if scale_entry:
                        df.at[idx, "map_scale_source"] = _classify_scale_source(
                            scale_entry.get("evidence_text", ""),
                            scale_entry.get("evidence_kind", ""),
                        )
                    else:
                        df.at[idx, "map_scale_source"] = ""

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
