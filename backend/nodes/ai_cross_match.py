"""AI Cross-Match: Three-layer hybrid matching OR BM25 + AI verification with 4-way output routing."""
from __future__ import annotations

import json
import re
import os
import asyncio
from difflib import SequenceMatcher

import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi

from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField
from ..providers.registry import call_llm, get_provider_id_for_model
from .llm_utils import extract_json
from .ai_vision import _relative_image_path
from ..search.embedding import embed

_DEFAULT_SYSTEM_PROMPT = (
    "You are a record matching expert for cartographic materials. "
    "Given image information and a list of candidate catalog records, "
    "determine how well each candidate matches the image.\n\n"
    "For each candidate, return a confidence score (0.0 to 1.0) and a brief reason.\n"
    "Return JSON only, no markdown:\n"
    '{"matches": [{"candidate_index": 0, "confidence": 0.85, "reason": "Title and date match"}, ...]}\n\n'
    "Rules:\n"
    "- 1.0 = perfect match, 0.0 = no relation\n"
    "- Consider title, date, author, publisher, geographic scope, scale, call number patterns in filename\n"
    "- If no candidate is a good match, all confidences should be below 0.5\n"
    "- Be conservative: only give high confidence when multiple fields corroborate"
)


# ── Hybrid matching helpers ──────────────────────────────────────────────────

def _extract_call_number(filename: str) -> str | None:
    """Extract Call Number prefix from an image filename.

    Filenames follow: '{call_number} {title}...{ext}'
    Examples: '000 a 1957 A Map of...jpg'  →  '000 a 1957'
              '831.119 caq 1886. Geo...jpg' →  '831.119 caq 1886.'
              '441.3a 1990 Hong Kong.jpg'   →  '441.3a 1990'
              '871.11 n.d. Darwin...jpg'    →  '871.11 n.d.'
    Pattern:  decimal_number [optional_space] letter_code  year_or_date
    """
    base = os.path.splitext(filename)[0]
    # Try standard format first: "123.4 abc 1900"
    m = re.match(r'^([\d.]+\s+[a-zA-Z]+\s+[\w.?-]+)', base)
    if m:
        return m.group(1).strip()
    # Try "n.d." format: "871.11 n.d." (letter code followed by dot-separated date)
    m = re.match(r'^([\d.]+\s+[a-zA-Z]+[.\s]+[\w.?-]+)', base)
    if m:
        return m.group(1).strip()
    # Try compact format: "441.3a 1990" (no space between number and letter code)
    m = re.match(r'^([\d.]+[a-zA-Z]+\s+[\w.?-]+)', base)
    return m.group(1).strip() if m else None


def _normalize_cn(cn: str) -> str:
    """Normalize a Call Number for comparison.

    Handles variations:
      '441.3 a 1990' and '441.3a 1990' both → '441.3 a 1990'
      '200 a 1891-93' and '200 a 1891-93.' both → '200 a 1891-93'
    """
    cn = cn.strip().lower()
    cn = cn.replace("n.d.", "nd")
    # Insert space between digit/period and letter when directly adjacent
    # e.g. "441.3a" → "441.3 a", "806.3atc" → "806.3 atc"
    cn = re.sub(r'(\d)([a-z])', r'\1 \2', cn)
    cn = re.sub(r'\.([a-z])', r'. \1', cn)
    cn = cn.rstrip(".?- ")
    cn = re.sub(r'\s+', ' ', cn).strip()
    return cn


def _build_cn_index(df: pd.DataFrame) -> dict[str, list[int]]:
    """Build {normalized_call_number: [iloc_indices]} from the left DataFrame."""
    cn_col = None
    for col in df.columns:
        col_key = col.lower().replace(" ", "").replace("_", "")
        if col_key in ("callnumber", "callno"):
            cn_col = col
            break
    if cn_col is None:
        return {}

    index: dict[str, list[int]] = {}
    for i in range(len(df)):
        val = df.iloc[i][cn_col]
        if pd.notna(val):
            norm = _normalize_cn(str(val))
            if norm:
                index.setdefault(norm, []).append(i)
    return index


def _title_from_filename(filename: str, cn_prefix: str | None) -> str:
    """Extract title portion from filename after removing the Call Number prefix."""
    base = os.path.splitext(filename)[0]
    if cn_prefix:
        idx = base.lower().find(cn_prefix.lower())
        if idx == 0:
            base = base[len(cn_prefix):].strip()
    return base


def _find_title_col(df: pd.DataFrame) -> str | None:
    """Find the title column in a DataFrame (case-insensitive)."""
    for col in df.columns:
        if col.strip().lower() in ("title", "标题"):
            return col
    return None


class AICrossMatchNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="ai_cross_match",
            label="AI Cross-Match",
            category="ai",
            icon="SearchCheck",
            color="#8b5cf6",
            description="Match records across two datasets using BM25 pre-filter + AI verification",
            inputs=[
                PortDefinition(name="left", label="Data"),
                PortDefinition(name="right", label="Images"),
            ],
            outputs=[
                PortDefinition(name="matched", label="Matched"),
                PortDefinition(name="ambiguous", label="Ambiguous"),
                PortDefinition(name="unmatched_left", label="No Image"),
                PortDefinition(name="unmatched_right", label="No Match"),
            ],
            config_fields=[
                ConfigField(
                    name="match_mode", label="Match Mode", type="select",
                    default="hybrid",
                    options=[
                        {"label": "Hybrid (Local)", "value": "hybrid"},
                        {"label": "LLM", "value": "llm"},
                    ],
                    description="hybrid = fast local matching (CN prefix + vector); llm = AI verification",
                ),
                ConfigField(
                    name="model", label="Model", type="select",
                    default="", options=[],
                    description="Select an AI model (only needed for LLM mode)",
                ),
                ConfigField(
                    name="left_match_columns", label="Data Match Columns",
                    type="text", required=True,
                    placeholder="TITLE, Author, Date Published, Call Number",
                    description="CSV columns for matching (comma-separated)",
                ),
                ConfigField(
                    name="right_match_columns", label="Image Match Columns",
                    type="text", required=True,
                    placeholder="filename, visual_description, text_visible",
                    description="Image columns for search query (comma-separated)",
                ),
                ConfigField(
                    name="system_prompt", label="System Prompt",
                    type="prompt_template", default=_DEFAULT_SYSTEM_PROMPT,
                ),
                ConfigField(
                    name="confidence_threshold", label="Confidence Threshold",
                    type="number", default=0.7,
                    description="Minimum confidence (0-1) for a match",
                ),
                ConfigField(
                    name="ambiguity_gap", label="Ambiguity Gap",
                    type="number", default=0.15,
                    description="Min gap between #1 and #2 confidence to avoid ambiguity",
                ),
                ConfigField(
                    name="top_k", label="Top-K Candidates",
                    type="number", default=5,
                    description="BM25 candidates per image (LLM mode) or fallback search (hybrid)",
                ),
                ConfigField(name="batch_size", label="Batch Size", type="number", default=5,
                            description="Images per LLM call (LLM mode only)"),
                ConfigField(name="max_tokens", label="Max Tokens", type="number", default=6000),
                ConfigField(name="concurrency", label="Concurrency", type="number", default=0,
                            description="Parallel LLM requests (0=auto)"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        left_df = inputs.get("left")
        right_df = inputs.get("right")
        if left_df is None or right_df is None:
            raise ValueError("AI Cross-Match requires both left (Data) and right (Images) inputs")

        left_df = left_df.copy()
        right_df = right_df.copy()

        empty_left = pd.DataFrame(columns=left_df.columns)
        empty_right = pd.DataFrame(columns=right_df.columns)

        if left_df.empty:
            return {"matched": pd.DataFrame(), "ambiguous": pd.DataFrame(),
                    "unmatched_left": empty_left, "unmatched_right": right_df}
        if right_df.empty:
            return {"matched": pd.DataFrame(), "ambiguous": pd.DataFrame(),
                    "unmatched_left": left_df, "unmatched_right": empty_right}

        # ── Parse config ──
        match_mode = config.get("match_mode", "hybrid")
        model = config.get("model", "")
        left_cols = [c.strip() for c in config.get("left_match_columns", "").split(",") if c.strip()]
        right_cols = [c.strip() for c in config.get("right_match_columns", "").split(",") if c.strip()]
        system_prompt = config.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        threshold = float(config.get("confidence_threshold", 0.7))
        gap = float(config.get("ambiguity_gap", 0.15))
        top_k = int(config.get("top_k", 5))
        max_tokens = int(config.get("max_tokens", 6000))
        raw_conc = int(config.get("concurrency", 0))
        concurrency = raw_conc if raw_conc > 0 else min(5, len(right_df))

        valid_left_cols = [c for c in left_cols if c in left_df.columns]
        valid_right_cols = [c for c in right_cols if c in right_df.columns]
        if not valid_left_cols:
            raise ValueError(f"None of the left match columns found in data: {left_cols}")
        if not valid_right_cols:
            raise ValueError(f"None of the right match columns found in images: {right_cols}")

        # API key only required for LLM mode
        api_key = ""
        if match_mode != "hybrid":
            if not model:
                raise ValueError("No model selected. Choose a model in the node config.")
            if context:
                provider_id = get_provider_id_for_model(model)
                api_key = context.get_api_key(provider_id)
            if not api_key:
                raise ValueError(f"No API key configured for model '{model}'. Set it in Settings.")

        # ── Phase 1: Build BM25 index from left_df ──
        corpus_texts = []
        for _, row in left_df.iterrows():
            parts = [str(row[c]) for c in valid_left_cols if pd.notna(row[c])]
            corpus_texts.append(" ".join(parts))

        tokenized_corpus = [doc.lower().split() for doc in corpus_texts]
        bm25 = BM25Okapi(tokenized_corpus)

        if on_progress:
            await on_progress(
                f"Index built: {len(left_df)} records, "
                f"{len(right_df)} images. Mode: {match_mode}"
            )

        # ── Phase 2: Match images to records ──
        total = len(right_df)
        right_matches: dict[int, list[tuple[int, float, str]]] = {}

        if match_mode == "hybrid":
            # ═══════════════════════════════════════════════════════════════
            # Three-layer hybrid matching (no LLM, all local computation)
            # Layer 1: Call Number prefix → unique match  (~89%)
            # Layer 2: Call Number prefix → disambiguation among duplicates
            # Layer 3: Full-library vector + BM25 fallback
            # ═══════════════════════════════════════════════════════════════
            cn_index = _build_cn_index(left_df)
            title_col = _find_title_col(left_df)

            if on_progress:
                cn_msg = f"Hybrid: {len(cn_index)} unique call numbers indexed"
                if not cn_index:
                    cn_msg += " (no Call Number column found — all images go to fallback)"
                await on_progress(f"{cn_msg}. Computing embeddings...")

            # Pre-compute embeddings for Layers 2 & 3
            left_embeddings = embed(corpus_texts)

            image_texts = []
            for _, rrow in right_df.iterrows():
                parts = [str(rrow[c]) for c in valid_right_cols
                         if c in right_df.columns and pd.notna(rrow[c])
                         and str(rrow[c]).strip()]
                image_texts.append(" ".join(parts) if parts else "")
            right_embeddings = embed(image_texts)

            if on_progress:
                await on_progress("Embeddings ready. Matching...")

            layer_counts = [0, 0, 0]  # L1 unique CN, L2 CN disambig, L3 fallback

            for i, (right_idx, right_row) in enumerate(right_df.iterrows()):
                filename = (str(right_row["filename"])
                            if "filename" in right_df.columns
                            and pd.notna(right_row.get("filename"))
                            else "")
                cn = _extract_call_number(filename)
                norm_cn = _normalize_cn(cn) if cn else None
                candidates = cn_index.get(norm_cn, []) if norm_cn else []

                if len(candidates) == 1:
                    # ── Layer 1: unique Call Number match ──
                    left_idx = candidates[0]
                    right_matches[right_idx] = [
                        (left_idx, 0.95, f"Call Number match: {cn}")
                    ]
                    layer_counts[0] += 1

                elif len(candidates) > 1:
                    # ── Layer 2: disambiguate among same-CN candidates ──
                    query_vec = right_embeddings[i]
                    title_fn = _title_from_filename(filename, cn)

                    # Gather vision-extracted text for stronger matching
                    text_vis = ""
                    vis_desc = ""
                    if "text_visible" in right_df.columns and pd.notna(right_row.get("text_visible")):
                        text_vis = str(right_row["text_visible"]).strip()
                    if "visual_description" in right_df.columns and pd.notna(right_row.get("visual_description")):
                        vis_desc = str(right_row["visual_description"]).strip()

                    # Tokenize vision text once for keyword overlap scoring
                    _stop = {"the","of","a","an","in","on","and","to","for",
                             "by","map","plan","chart","is","at","from","with"}
                    vis_tokens = set()
                    if text_vis:
                        vis_tokens = {w for w in re.split(r'[\s,;:.()]+', text_vis.lower())
                                      if len(w) >= 2 and w not in _stop}

                    # Extract numeric identifiers from text_visible and filename
                    # for sheet/number series matching (e.g., "SHEET 270", "634 Radstadt")
                    vis_numbers = set()
                    if text_vis:
                        vis_numbers = {m for m in re.findall(r'\b(\d{2,4})\b', text_vis)
                                       if not re.match(r'^(18|19|20)\d{2}$', m)}  # exclude years
                    fn_numbers = set()
                    if title_fn:
                        fn_numbers = {m for m in re.findall(r'\b(\d{2,4})\b', title_fn)
                                      if not re.match(r'^(18|19|20)\d{2}$', m)}
                    id_numbers = vis_numbers | fn_numbers  # all candidate identifiers

                    match_list = []
                    for left_idx in candidates:
                        # Semantic similarity (dot product = cosine for L2-normed vecs)
                        doc_vec = left_embeddings[left_idx]
                        sem = float(np.dot(query_vec, doc_vec))

                        # Title matching — combine:
                        #   (a) filename title vs catalogue TITLE (fuzzy)
                        #   (b) keyword overlap: text_visible tokens vs catalogue text
                        #   (c) numeric identifier exact match (sheet numbers, etc.)
                        title_score = 0.0
                        kw_score = 0.0
                        id_bonus = 0.0

                        if title_col and pd.notna(left_df.iloc[left_idx][title_col]):
                            left_title = str(left_df.iloc[left_idx][title_col])

                            # (a) filename title fuzzy match
                            if title_fn:
                                title_score = SequenceMatcher(
                                    None,
                                    title_fn.lower()[:300],
                                    left_title.lower()[:300],
                                ).ratio()

                            # (b) keyword overlap: what fraction of vision-text
                            #     keywords appear in the catalogue record?
                            if vis_tokens:
                                left_desc = ""
                                for dc in ("Description ", "Description", "description"):
                                    if dc in left_df.columns and pd.notna(left_df.iloc[left_idx].get(dc)):
                                        left_desc = str(left_df.iloc[left_idx][dc])
                                        break
                                cat_text = (left_title + " " + left_desc).lower()
                                cat_tokens = {w for w in re.split(r'[\s,;:.()]+', cat_text)
                                              if len(w) >= 2 and w not in _stop}
                                overlap = vis_tokens & cat_tokens
                                kw_score = len(overlap) / len(vis_tokens) if vis_tokens else 0

                            # (c) Numeric identifier match: if a sheet/map number from
                            #     the image appears in this candidate's title, proportional bonus.
                            #     More matched numbers → higher bonus (better discrimination)
                            if id_numbers:
                                cat_numbers = set(re.findall(r'\b(\d{2,4})\b', left_title))
                                matched_ids = id_numbers & cat_numbers
                                if matched_ids:
                                    id_bonus = 0.15 * len(matched_ids) / len(id_numbers)

                        # Best text-based signal
                        text_score = max(title_score, kw_score)

                        # CN match = strong signal → 0.40 base + disambig signals + id bonus
                        combined = 0.40 + (sem * 0.35 + text_score * 0.25) + id_bonus
                        id_tag = (f", id={id_bonus:.3f}"
                                  if id_bonus > 0 else "")
                        reason = f"CN+disambig (sem={sem:.2f}, txt={text_score:.2f}{id_tag})"
                        match_list.append((left_idx, combined, reason))

                    match_list.sort(key=lambda x: x[1], reverse=True)

                    # Check for duplicate catalogue records (same title, different IDs)
                    # If all candidates share the same title, pick top-1 automatically
                    if len(match_list) >= 2 and title_col:
                        cand_titles = set()
                        for li, _, _ in match_list:
                            t = str(left_df.iloc[li].get(title_col, "")).strip().lower()[:50]
                            if t:
                                cand_titles.add(t)
                        if len(cand_titles) <= 1:
                            # Duplicate records — auto-select top-1
                            best = match_list[0]
                            match_list = [(best[0], best[1],
                                           best[2] + " (dup-records auto-select)")]

                    right_matches[right_idx] = match_list
                    layer_counts[1] += 1

                else:
                    # ── Layer 3: full-library vector + BM25 fallback ──
                    query_vec = right_embeddings[i]
                    sem_scores = left_embeddings @ query_vec  # cosine similarity

                    # BM25 scores (with query term filtering to reduce pollution
                    # from overly common terms like "national", "society", "map")
                    _bm25_stop = {"national", "geographic", "society", "map",
                                  "maps", "plan", "chart", "the", "of", "a",
                                  "an", "in", "on", "and", "to", "for", "by",
                                  "is", "at", "from", "with", "this", "that",
                                  "image", "shows", "showing", "visible",
                                  "text", "printed", "appears", "contains"}
                    query_parts = [str(right_row[c]) for c in valid_right_cols
                                   if c in right_df.columns and pd.notna(right_row[c])
                                   and str(right_row[c]).strip()]
                    query = " ".join(query_parts)
                    if query.strip():
                        tok_q = [w for w in query.lower().split()
                                 if w not in _bm25_stop and len(w) >= 2]
                        if tok_q:
                            bm25_raw = bm25.get_scores(tok_q)
                            bm25_max = bm25_raw.max()
                            bm25_norm = bm25_raw / bm25_max if bm25_max > 0 else bm25_raw
                        else:
                            bm25_norm = np.zeros(len(left_df))
                    else:
                        bm25_norm = np.zeros(len(left_df))

                    # Weighted combination — semantic similarity is more reliable
                    # than BM25 for cross-domain matching, so it gets higher weight
                    combined_scores = sem_scores * 0.70 + bm25_norm * 0.30
                    top_idx = np.argsort(combined_scores)[::-1][:top_k]

                    match_list = []
                    for li in top_idx:
                        li = int(li)
                        sc = float(combined_scores[li])
                        if sc > 0:
                            reason = (f"Fallback (sem={sem_scores[li]:.2f}, "
                                      f"bm25={bm25_norm[li]:.2f})")
                            match_list.append((li, sc, reason))

                    match_list.sort(key=lambda x: x[1], reverse=True)
                    right_matches[right_idx] = match_list
                    layer_counts[2] += 1

                # Progress every 200 images
                if on_progress and (i + 1) % 200 == 0:
                    await on_progress(f"Hybrid: {i + 1}/{total} images")

            if on_progress:
                await on_progress(
                    f"Hybrid done — L1(unique CN)={layer_counts[0]}, "
                    f"L2(CN disambig)={layer_counts[1]}, "
                    f"L3(fallback)={layer_counts[2]}"
                )

        else:
            # ═══════════════════════════════════════════════════════════════
            # LLM mode: BM25 pre-filter + AI verification (original logic)
            # ═══════════════════════════════════════════════════════════════
            batch_size = max(1, int(config.get("batch_size", 5)))
            image_tasks = []
            bm25_skipped = 0

            for i, (right_idx, right_row) in enumerate(right_df.iterrows()):
                query_parts = []
                for c in valid_right_cols:
                    val = str(right_row[c]) if pd.notna(right_row[c]) else ""
                    if val.strip():
                        query_parts.append(val)
                query = " ".join(query_parts)

                if not query.strip():
                    right_matches[right_idx] = []
                    bm25_skipped += 1
                    continue

                tokenized_query = query.lower().split()
                scores = bm25.get_scores(tokenized_query)
                top_indices = scores.argsort()[-top_k:][::-1].tolist()
                top_indices = [idx for idx in top_indices if scores[idx] > 0]

                if not top_indices:
                    right_matches[right_idx] = []
                    bm25_skipped += 1
                    continue

                # Build image description
                image_desc_parts = []
                for c in valid_right_cols:
                    val = str(right_row[c]) if pd.notna(right_row[c]) else ""
                    if val.strip():
                        image_desc_parts.append(f"{c}: {val}")
                if ("filename" not in valid_right_cols
                        and "filename" in right_df.columns
                        and pd.notna(right_row.get("filename"))):
                    image_desc_parts.insert(0, f"filename: {right_row['filename']}")

                # Build candidates text
                cand_text_parts = []
                candidate_left_indices = []
                for cand_idx in top_indices:
                    left_row = left_df.iloc[cand_idx]
                    parts = [f"{c}: {str(left_row[c])}" for c in valid_left_cols
                             if pd.notna(left_row[c]) and str(left_row[c]).strip()]
                    cand_text_parts.append(
                        f"[C{len(cand_text_parts)}] " + " | ".join(parts))
                    candidate_left_indices.append(cand_idx)

                # Image path for debug visualization
                img_filename = (str(right_row.get("filename", ""))
                                if pd.notna(right_row.get("filename")) else "")
                file_path_val = (str(right_row.get("file_path", ""))
                                 if "file_path" in right_df.columns
                                 and pd.notna(right_row.get("file_path")) else "")
                rel_path = (_relative_image_path(file_path_val)
                            if file_path_val else None)

                image_tasks.append({
                    "seq": i, "right_idx": right_idx,
                    "image_desc": "\n".join(image_desc_parts),
                    "candidates_text": "\n".join(cand_text_parts),
                    "candidate_left_indices": candidate_left_indices,
                    "img_filename": img_filename, "rel_path": rel_path,
                })

            if on_progress:
                await on_progress(
                    f"BM25 pre-filter: {len(image_tasks)} need AI verification, "
                    f"{bm25_skipped} skipped"
                )

            # ── Batch AI verification ──
            completed = 0
            sem = asyncio.Semaphore(concurrency)

            batch_system = system_prompt
            if batch_size > 1:
                batch_system += (
                    "\n\nIMPORTANT: You will receive MULTIPLE images in one request. "
                    "Return results for ALL images.\n"
                    'Format: {"results": [{"image_index": 0, "matches": [...]}, '
                    '{"image_index": 1, "matches": [...]}, ...]}'
                )

            def _parse_single_matches(parsed, item):
                """Parse AI response for a single image and build match list."""
                ai_matches = parsed.get("matches", [])
                match_list = []
                for m in ai_matches:
                    cand_idx = int(m.get("candidate_index", -1))
                    conf = float(m.get("confidence", 0))
                    reason = str(m.get("reason", ""))
                    if 0 <= cand_idx < len(item["candidate_left_indices"]):
                        match_list.append((
                            item["candidate_left_indices"][cand_idx], conf, reason))
                match_list.sort(key=lambda x: x[1], reverse=True)
                return match_list

            def _top_summary(match_list):
                if not match_list:
                    return None
                return {"confidence": str(match_list[0][1]),
                        "reason": match_list[0][2][:200]}

            async def process_batch(batch):
                nonlocal completed

                if len(batch) == 1:
                    # ── Single-image mode ──
                    item = batch[0]
                    user_prompt = (
                        f"Image Information:\n{item['image_desc']}\n\n"
                        f"Candidate Records:\n{item['candidates_text']}\n\n"
                        f"Score each candidate's match confidence (0.0-1.0) "
                        f"and explain briefly."
                    )
                    async with sem:
                        try:
                            if context:
                                await context.emit("ai_debug", {
                                    "row": item["seq"] + 1, "total": total,
                                    "phase": "prompt",
                                    "system_prompt": system_prompt[:500],
                                    "user_prompt": user_prompt[:1500],
                                    "image_path": item["rel_path"],
                                    "filename": item["img_filename"],
                                })
                            text = await call_llm(
                                model, system_prompt, user_prompt,
                                max_tokens, api_key)
                            parsed = extract_json(text)
                            ml = _parse_single_matches(parsed, item)
                            right_matches[item["right_idx"]] = ml
                            if context:
                                await context.emit("ai_debug", {
                                    "row": item["seq"] + 1, "total": total,
                                    "phase": "response",
                                    "raw_response": text[:2000],
                                    "image_path": item["rel_path"],
                                    "filename": item["img_filename"],
                                    "result": _top_summary(ml),
                                })
                        except Exception as exc:
                            right_matches[item["right_idx"]] = []
                            if context:
                                await context.emit("ai_debug", {
                                    "row": item["seq"] + 1, "total": total,
                                    "phase": "error",
                                    "error": str(exc)[:500],
                                    "image_path": item["rel_path"],
                                    "filename": item["img_filename"],
                                })
                else:
                    # ── Batch mode: multiple images per LLM call ──
                    prompt_parts = []
                    for bi, item in enumerate(batch):
                        prompt_parts.append(
                            f"=== Image {bi} ===\n{item['image_desc']}\n"
                            f"Candidates:\n{item['candidates_text']}"
                        )
                    combined_prompt = (
                        "\n\n".join(prompt_parts)
                        + "\n\nScore each image's candidates (0.0-1.0)."
                    )
                    batch_max_tokens = max_tokens * len(batch)

                    # Emit prompt debug for batch
                    if context:
                        await context.emit("ai_debug", {
                            "row": batch[0]["seq"] + 1, "total": total,
                            "phase": "prompt",
                            "system_prompt": batch_system[:500],
                            "user_prompt": (
                                f"[Batch of {len(batch)}]\n"
                                f"{combined_prompt[:1500]}"
                            ),
                            "image_path": batch[0]["rel_path"],
                            "filename": batch[0]["img_filename"],
                        })

                    async with sem:
                        try:
                            text = await call_llm(
                                model, batch_system, combined_prompt,
                                batch_max_tokens, api_key)
                            parsed = extract_json(text)
                            results = parsed.get("results", [])

                            # Map batch results back
                            result_map: dict[int, list] = {}
                            for r in results:
                                bi = int(r.get("image_index", -1))
                                if 0 <= bi < len(batch):
                                    result_map[bi] = r.get("matches", [])

                            for bi, item in enumerate(batch):
                                ai_matches = result_map.get(bi, [])
                                ml = []
                                for m in ai_matches:
                                    ci = int(m.get("candidate_index", -1))
                                    conf = float(m.get("confidence", 0))
                                    reason = str(m.get("reason", ""))
                                    if 0 <= ci < len(
                                            item["candidate_left_indices"]):
                                        ml.append((
                                            item["candidate_left_indices"][ci],
                                            conf, reason))
                                ml.sort(key=lambda x: x[1], reverse=True)
                                right_matches[item["right_idx"]] = ml

                                if context:
                                    await context.emit("ai_debug", {
                                        "row": item["seq"] + 1,
                                        "total": total, "phase": "response",
                                        "raw_response": (
                                            f"[Batch {bi}] conf="
                                            f"{ml[0][1]:.2f}" if ml
                                            else "[Batch] no match"
                                        ),
                                        "image_path": item["rel_path"],
                                        "filename": item["img_filename"],
                                        "result": _top_summary(ml),
                                    })

                        except Exception as exc:
                            for item in batch:
                                right_matches[item["right_idx"]] = []
                            if context:
                                await context.emit("ai_debug", {
                                    "row": batch[0]["seq"] + 1,
                                    "total": total, "phase": "error",
                                    "error": f"Batch error: {str(exc)[:500]}",
                                    "image_path": batch[0]["rel_path"],
                                    "filename": batch[0]["img_filename"],
                                })

                completed += len(batch)
                if on_progress and (
                        completed % max(batch_size * 2, 1) == 0
                        or completed >= len(image_tasks)):
                    await on_progress(
                        f"{completed}/{len(image_tasks)} images verified")

            # Create batches and process
            batches = [image_tasks[i:i + batch_size]
                       for i in range(0, len(image_tasks), batch_size)]
            batch_tasks = [process_batch(b) for b in batches]
            await asyncio.gather(*batch_tasks)

        # ══════════════════════════════════════════════════════════════════
        # Phase 3: Route results into 4 non-overlapping outputs
        # ══════════════════════════════════════════════════════════════════

        # Step 1: Initial classification per image
        decisions: dict[int, dict] = {}

        for right_idx, match_list in right_matches.items():
            if not match_list or match_list[0][1] < threshold:
                decisions[right_idx] = {"status": "unmatched_right"}
                continue

            top_conf = match_list[0][1]
            second_conf = match_list[1][1] if len(match_list) > 1 else 0.0

            if (top_conf - second_conf) >= gap:
                decisions[right_idx] = {
                    "status": "matched",
                    "left_idx": match_list[0][0],
                    "confidence": top_conf,
                    "reason": match_list[0][2],
                }
            else:
                decisions[right_idx] = {
                    "status": "ambiguous",
                    "match_list": match_list,
                }

        # Step 2: Conflict detection
        if match_mode == "hybrid":
            # In hybrid mode, multiple images → same left row = multi-page map
            # (not a conflict — they will be merged in Step 3)
            pass
        else:
            # In LLM mode, multiple images claiming same left row → ambiguous
            left_claims: dict[int, list[int]] = {}
            for right_idx, dec in decisions.items():
                if dec["status"] == "matched":
                    left_idx = dec["left_idx"]
                    left_claims.setdefault(left_idx, []).append(right_idx)

            for left_idx, rindices in left_claims.items():
                if len(rindices) > 1:
                    for right_idx in rindices:
                        decisions[right_idx] = {
                            "status": "ambiguous",
                            "match_list": right_matches[right_idx],
                        }

        # Step 3: Build matched output & track used left indices
        matched_rows = []
        matched_left_indices = set()

        if match_mode == "hybrid":
            # Group matched images by left_idx for multi-page merge
            left_to_rights: dict[int, list[tuple[int, dict]]] = {}
            for right_idx, dec in decisions.items():
                if dec["status"] == "matched":
                    left_to_rights.setdefault(
                        dec["left_idx"], []).append((right_idx, dec))

            for left_idx, group in left_to_rights.items():
                matched_left_indices.add(left_idx)
                left_row = left_df.iloc[left_idx]
                merged = {col: left_row[col] for col in left_df.columns}

                if len(group) == 1:
                    # Single image → single left row
                    right_idx, dec = group[0]
                    rr = right_df.loc[right_idx]
                    for col in right_df.columns:
                        if col not in merged:
                            merged[col] = rr[col]
                    merged["_match_confidence"] = dec["confidence"]
                    merged["_matched_image"] = str(rr.get("filename", ""))
                    merged["_match_reason"] = dec["reason"]
                else:
                    # Multi-page merge: join file_path & filename with " || "
                    sorted_group = sorted(
                        group,
                        key=lambda x: str(
                            right_df.loc[x[0]].get("filename", "")))
                    first_rr = right_df.loc[sorted_group[0][0]]
                    for col in right_df.columns:
                        if col in ("file_path", "filename"):
                            vals = []
                            for ri, _ in sorted_group:
                                v = right_df.loc[ri].get(col)
                                if pd.notna(v):
                                    vals.append(str(v))
                            merged[col] = " || ".join(vals)
                        elif col not in merged:
                            merged[col] = first_rr[col]
                    best_dec = max(group, key=lambda x: x[1].get(
                        "confidence", 0))[1]
                    merged["_match_confidence"] = best_dec["confidence"]
                    merged["_matched_image"] = merged.get("filename", "")
                    merged["_match_reason"] = (
                        best_dec["reason"]
                        + f" ({len(group)} pages merged)")

                matched_rows.append(merged)
        else:
            # LLM mode: one-to-one matching (original logic)
            for right_idx, dec in decisions.items():
                if dec["status"] != "matched":
                    continue
                left_idx = dec["left_idx"]
                matched_left_indices.add(left_idx)
                left_row = left_df.iloc[left_idx]
                right_row = right_df.loc[right_idx]
                merged = {}
                for col in left_df.columns:
                    merged[col] = left_row[col]
                for col in right_df.columns:
                    if col not in merged:
                        merged[col] = right_row[col]
                merged["_match_confidence"] = dec["confidence"]
                merged["_matched_image"] = str(right_row.get("filename", ""))
                merged["_match_reason"] = dec["reason"]
                matched_rows.append(merged)

        # Step 4: Build ambiguous output (exclude already-matched left rows)
        # Layout: image columns only on the first row of each group;
        #         subsequent rows contain catalogue columns only.
        # Filter: only keep candidates whose confidence is close to the top.
        # IMPORTANT: After filtering out already-matched left rows, re-evaluate
        # whether the remaining candidates still constitute ambiguity. If the
        # new gap is large enough, promote the top candidate to matched.
        ambiguous_rows = []
        ambiguous_left_indices = set()
        right_col_set = set(right_df.columns)
        promoted_count = 0

        # Find Call Number column for area-code promotion
        cn_col_name = None
        for col in left_df.columns:
            ck = col.lower().replace(" ", "").replace("_", "")
            if ck in ("callnumber", "callno"):
                cn_col_name = col
                break

        for right_idx, dec in decisions.items():
            if dec["status"] != "ambiguous":
                continue
            match_list = dec.get("match_list", right_matches.get(right_idx, []))
            right_row = right_df.loc[right_idx]
            group_id = str(right_row.get("filename", f"image_{right_idx}"))

            # Filter: keep candidates within gap of the top score,
            # excluding those already matched to other images
            top_conf = match_list[0][1] if match_list else 0
            close_candidates = []
            for left_idx, conf, reason in match_list:
                if left_idx in matched_left_indices:
                    continue
                # Keep if confidence is within (gap * 2) of top, or rank <= 1
                if close_candidates and (top_conf - conf) > gap * 2:
                    break
                close_candidates.append((left_idx, conf, reason))

            if not close_candidates:
                continue

            # Re-evaluate: after filtering, does the top remaining candidate
            # now have a clear gap over the second?
            new_top = close_candidates[0][1]
            new_second = close_candidates[1][1] if len(close_candidates) > 1 else 0.0
            new_gap = new_top - new_second

            promote = False
            promote_reason_suffix = ""

            if new_top >= threshold and new_gap >= gap:
                promote = True
                promote_reason_suffix = " (promoted)"

            # Additional promotion: progressive Call Number component matching.
            # Compare area code → subject code → date, filtering at each level.
            # If only ONE candidate survives at any depth, promote it.
            # e.g. image "207 atu 1940":
            #   depth 0 (area "207"): 3 candidates → keep filtering
            #   depth 1 (subject "atu"): 1 candidate → promote!
            if not promote and len(close_candidates) >= 2 and cn_col_name:
                img_fn = str(right_row.get("filename", ""))
                img_cn = _extract_call_number(img_fn)
                if img_cn:
                    img_parts = _normalize_cn(img_cn).split()
                    # Pre-compute CN parts for all candidates
                    cand_cn_parts = []
                    for ci, (li, cf, rs) in enumerate(close_candidates):
                        cat_cn = str(left_df.iloc[li].get(cn_col_name, ""))
                        cand_cn_parts.append(
                            _normalize_cn(cat_cn).split() if cat_cn.strip() else [])

                    remaining = list(range(len(close_candidates)))
                    for depth, img_part in enumerate(img_parts):
                        new_remaining = [
                            ci for ci in remaining
                            if (depth < len(cand_cn_parts[ci])
                                and cand_cn_parts[ci][depth] == img_part)
                        ]
                        if len(new_remaining) == 1:
                            idx = new_remaining[0]
                            close_candidates = [close_candidates[idx]]
                            new_top = close_candidates[0][1]
                            if new_top >= threshold:
                                promote = True
                                cn_depth_labels = ["area", "subject", "date"]
                                dl = cn_depth_labels[depth] if depth < 3 else f"part{depth}"
                                promote_reason_suffix = f" (CN-{dl} unique)"
                            break
                        elif len(new_remaining) == 0:
                            break  # no candidates match → stop filtering
                        else:
                            remaining = new_remaining

            if promote:
                best_left_idx, best_conf, best_reason = close_candidates[0]
                matched_left_indices.add(best_left_idx)
                left_row = left_df.iloc[best_left_idx]
                merged = {col: left_row[col] for col in left_df.columns}
                for col in right_df.columns:
                    if col not in merged:
                        merged[col] = right_row[col]
                merged["_match_confidence"] = best_conf
                merged["_matched_image"] = str(right_row.get("filename", ""))
                merged["_match_reason"] = best_reason + promote_reason_suffix
                matched_rows.append(merged)
                promoted_count += 1
                continue

            for rank, (left_idx, conf, reason) in enumerate(close_candidates):
                ambiguous_left_indices.add(left_idx)
                left_row = left_df.iloc[left_idx]
                row = {}
                # Catalogue columns (always filled)
                for col in left_df.columns:
                    row[col] = left_row[col]
                # Image columns: only on the first row of the group
                for col in right_df.columns:
                    if col not in row:
                        row[col] = right_row[col] if rank == 0 else ""
                row["_match_group"] = group_id
                row["_match_rank"] = rank + 1
                row["_match_confidence"] = conf
                row["_match_reason"] = reason
                ambiguous_rows.append(row)

        # Step 5: Build unmatched outputs
        used_left_indices = matched_left_indices | ambiguous_left_indices
        unmatched_left_indices = [
            i for i in range(len(left_df)) if i not in used_left_indices]

        unmatched_right_rows = []
        for right_idx, dec in decisions.items():
            if dec["status"] == "unmatched_right":
                unmatched_right_rows.append(right_df.loc[right_idx].to_dict())

        matched_df = (pd.DataFrame(matched_rows).reset_index(drop=True)
                      if matched_rows else pd.DataFrame())
        ambiguous_df = (pd.DataFrame(ambiguous_rows).reset_index(drop=True)
                        if ambiguous_rows else pd.DataFrame())
        unmatched_left_df = (
            left_df.iloc[unmatched_left_indices].reset_index(drop=True)
            if unmatched_left_indices
            else pd.DataFrame(columns=left_df.columns))
        unmatched_right_df = (
            pd.DataFrame(unmatched_right_rows).reset_index(drop=True)
            if unmatched_right_rows else pd.DataFrame())

        # Count unique ambiguous groups
        amb_groups = (len(set(r.get("_match_group", "")
                              for r in ambiguous_rows))
                      if ambiguous_rows else 0)

        # Image coverage check: every right_df row should be accounted for
        covered_right = len(decisions)
        total_right = len(right_df)
        coverage_msg = ""
        if covered_right < total_right:
            coverage_msg = (
                f" WARNING: {total_right - covered_right} images "
                f"not in any output!"
            )

        if on_progress:
            promo_msg = (f" ({promoted_count} promoted)"
                         if promoted_count else "")
            await on_progress(
                f"Done: {len(matched_df)} matched{promo_msg}, "
                f"{amb_groups} ambiguous, "
                f"{len(unmatched_left_df)} no image, "
                f"{len(unmatched_right_df)} no match.{coverage_msg}"
            )

        return {
            "matched": matched_df,
            "ambiguous": ambiguous_df,
            "unmatched_left": unmatched_left_df,
            "unmatched_right": unmatched_right_df,
        }
