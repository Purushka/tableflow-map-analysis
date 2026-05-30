# Map Analysis — Design Notes & Experiment Log

Date span: 2026-05-31 session  
Repo: https://github.com/Purushka/tableflow-map-analysis  
Data set used for iteration: 9 HD TIF maps from `C:\Users\14002\OneDrive\桌面\u盘：f\HD maps`  
End user / acceptance reviewer: Ingrid Ahmer (RGSSA Library)

This file records every architectural choice, parameter, prompt design
decision, and run outcome for the `backend/nodes/ai_map_analysis.py`
pipeline. Read this before iterating further so you don't re-litigate
choices that were already tested.

> **Maintenance contract**: any change to the pipeline — prompt, model,
> parameter, column, architecture step — must be appended here as part
> of the same change. Add a Run-N row to §6 for each new full-pipeline
> evaluation, an entry to §5 for prompt edits, etc. Treat this as a
> running experiment log, not a frozen design doc.

---

## 1. Architecture history

### Phase 0 — Original "multilevel" pipeline (deleted)
- L1 thumbnail scan → overview + text region detection
- L2a parallel OCR of text crops
- L2b planning → coordinate-strip / map-body regions
- L3 parallel high-res region exploration
- Synthesis → 28-field structured JSON
- Optional post-processing batch refinement across maps
- Optional single critic pass on the synthesized output (legacy)

Problems Ingrid flagged on this phase's output (March 2026 review):
- Hallucinated country lists / bbox edges for partial-scan maps
- Author/cartographer initials pulled from training memory ("R.A." Luebbers)
- Inset maps mis-identified (Falkland/Canal Zone in 740 S America)
- OCR character errors ("S.G.F" vs "N.G.F", "13" vs "12")
- Filename-derived `map_width_cm` / `map_height_cm` independent of
  actual scan dimensions

Deleted in commit 30ea110. Prompts removed: L1_*, L2A_*, L2B_*,
L3_SYSTEM_COORDINATE/SAMPLE, SYNTH_*, POST_PROCESS_*,
DIRECT_SUPPLEMENT_*.

### Phase 1 — Direct grounded extraction + single critic loop (current)
- Single high-res image → extractor produces `{fields, type_specific}`
- Every value must come with `evidence_bbox`, `evidence_text`, `evidence_kind`
- One critic agent verifies each value against its bbox
- Flagged fields trigger correction round — feedback re-injected
  into extractor's conversation_history
- Loop ≤ `max_correction_rounds`; remaining flagged → demoted to empty

Implemented in commit 30ea110. Iterated on prompts across run 3 & 4.

### Phase 2 — Specialist critic ensemble (designed, partially implemented)
- 3 specialists run in parallel, each handling its own field slice:
  - `geo_critic` — strict (anti-hallucination on country/province/bbox)
  - `ocr_critic` — medium (character-level errors, paraphrase OK)
  - `visual_critic` — lenient (paraphrase/synonyms expected)
- Prompts already in code; orchestration wiring pending
- Add 2 audit columns: `map_review_fields_uncertain`,
  `map_review_fields_demoted`

Rationale: single critic + single calibration cannot simultaneously
catch hallucinations on country/bbox AND tolerate paraphrase on
description. Splitting calibrations per domain resolves the
precision/recall deadlock observed between run 3 (over-strict, 185
fields) and run 4 (lenient, 267 fields but Arctic country regression).

---

## 2. Models

### Extractor
| Model | Provider | Notes |
|---|---|---|
| `qwen/qwen3-vl-235b-a22b-instruct` | OpenRouter | **Current default**. Good grounding when prompted strictly. Tends toward lazy `[0,0,100,100]` bboxes without explicit anti-laziness rule. |
| `qwen/qwen3-vl-235b-a22b-thinking` | OpenRouter | Untested as extractor — reasoning trace may help grounding decisions. |
| `claude-sonnet-4-5` direct | Anthropic | Untested — strong but $$$. |
| `gpt-4o` | OpenAI / OpenRouter | Untested. |

### Critic
| Model | Provider | Verdict |
|---|---|---|
| `gemini-2.5-pro` | Google native | **Geo-blocked** in this environment (`400 User location is not supported`). Also 504 timeouts on large images. Unusable here. |
| `anthropic/claude-sonnet-4-5` | OpenRouter | **Current default**. Excellent at catching hallucinations (e.g. "Brasilia did not exist in 1937"). Was too strict in run 3, calibrated in run 4. |
| `openai/gpt-4o` | OpenRouter | Registered but untested as critic. Likely good fallback. |
| `qwen/qwen3-vl-235b-a22b-thinking` | OpenRouter | Untested — could serve as same-family self-critic when budget is tight. |

### Models registered in `openrouter_provider.py` (commit current)
Vision: qwen3-vl-235b-instruct, qwen3-vl-235b-thinking, qwen2.5-vl-72b-instruct, qwen2.5-vl-32b-instruct, qwen3-vl-8b-instruct, anthropic/claude-sonnet-4-5, openai/gpt-4o, google/gemini-2.5-pro-preview, google/gemini-2.5-flash-preview

Text-only: deepseek-r1, deepseek-chat-v3, qwen3-235b

---

## 3. Key parameters & constants

All in `backend/nodes/ai_map_analysis.py`.

### Image processing
```python
_FULL_IMAGE_DIM = 3840          # max side sent to vision API
_THUMB_QUALITY  = 95            # JPEG q for full-image send
_CROP_QUALITY   = 100           # JPEG q for crops (lossless)
_MAX_IMAGE_BYTES = 18 * 1024 * 1024   # API upload ceiling
_PREVIEW_DIM    = 1500          # evidence-preview visualization size
```

Vision APIs internally downscale to ~1.5 MP, so 3840 is overkill but
preserves edge legibility for unusual aspect ratios.

### Pipeline behavior
| Config field | Default | Tested range | Notes |
|---|---|---|---|
| `model` | "" | qwen3-vl-235b-instruct | Required. |
| `critic_model` | "" | claude-sonnet-4-5 (OR), gemini-2.5-pro (native, blocked) | Blank = skip critic entirely. |
| `max_correction_rounds` | 2 | 0, 2 | 0 = critic flags read-only without correction; 2 = good default observed. |
| `max_tokens` | 16000 | 16000 | Per-response cap. 8000 may be enough for most. |
| `concurrency` | 0 (auto) | 1, 2 | 2 maps in flight = fine for OpenRouter rate limits, observed. |
| `dublin_core_export` | false | false | DC columns appended at end if true. |
| `image_column` | required | "file_path" | Pandas column with image path. |

### Transient-error retry (added run 3 → run 4)
- Status codes retried: 500, 502, 503, 504
- Connection errors / timeouts also retried
- Exponential backoff: 2s → 6s → 18s, 3 attempts
- Implemented in `_with_retry()` wrapping `call_vision_*`

### Evidence schema
Every grounded value:
```python
{
  "value": <typed>,
  "evidence_bbox": [x%, y%, w%, h%],   # 0..100, top-left origin
  "evidence_text": "<≤500 chars>",
  "evidence_kind": "direct_quote" | "visual_observation" | "computed"
}
```

`evidence_kind` distinguishes:
- `direct_quote` — OCR'd printed text; evidence_text = the exact OCR
- `visual_observation` — visual classification (map_type, medium); evidence_text = what was seen
- `computed` — derived from visible data (scale_ratio from scale bar); evidence_text = source values

Fields without a bbox are **dropped silently** in `_parse_grounded`.

---

## 4. B-group structural columns (added run 3)

Driven by Ingrid's email feedback that filename-derived dimensions are
unreliable and DPI should be reported.

| Column | Source | Notes |
|---|---|---|
| `map_width_cm`, `map_height_cm` | filename regex `<n>cm[xX×]<n>cm` | Legacy. Often wrong for partial scans (e.g. 171 Arctic claims 91×91 but scan is 91×46). |
| `map_pixel_w`, `map_pixel_h` | `PIL.Image.size` | Always correct. |
| `map_dpi_x`, `map_dpi_y` | `PIL.Image.info["dpi"]` | All test maps were 200 dpi. |
| `map_image_w_cm`, `map_image_h_cm` | `pixel / dpi * 2.54` | Real scan dimensions. 171 Arctic correctly comes out as 90.97×45.87. |
| `map_scale_source` | extractor's evidence_kind on scale_ratio | "computed_from_bar" / "computed_from_text" / "" (printed) |

Implementation: `_extract_b_group_metadata()` runs before the LLM
pipeline, populates 8 columns from image file alone.

---

## 5. Prompt design decisions

### EXTRACT_USER (extractor)
- Schema: `{fields: {key: {value, evidence_bbox, evidence_text, evidence_kind}}, type_specific: {...}}`
- 28 allowed top-level field names listed with field-specific rules
- Hard rule: omit field if can't ground
- Anti-laziness rule (added run 3 → run 4): `[0,0,100,100]` FORBIDDEN
  for direct_quote/computed; allowed only for visual_observation
- Anti-hallucination hard rules (added run 4 → run 5):
  - country/province/city/district: only list if a printed label is visible
  - bbox_*: only emit edges that have a printed coordinate tick visible
  - publisher: only if printed somewhere visible
- Numeric types enforced via `_coerce_value`

### Critic prompts evolution
- **Run 3 (initial CRITIC_USER)**: "ok=false if value is more specific
  than the region shows or from training knowledge". Result: **too
  strict**. Map 6 Younghusband cut from 26 → 8 fields. Map 9 Port
  Moresby cut to 15. Total run-3 = 185 filled cells.
- **Run 4 calibration**: added "Bias toward ok=true; over-flagging
  discards correct metadata" + explicit tolerance list (paraphrase,
  synonyms, ≤2% numeric drift). Result: **swing back too far**. Map 2
  Arctic regressed to listing "USA, Canada, Russia" for country. Total
  run-4 = 267 cells (+44%) but with the regressions noted.
- **Run 5 (planned)**: specialist critics with per-domain calibration.

### CORRECTION_USER
- Sent back to extractor's conversation as a follow-up user message
- Lists flagged fields with critic's `issue` + `what_you_see`
- Hard rule: if value is correct, just tighten bbox; don't drop it
- Hard rule: new bbox must be tight (no `[0,0,100,100]`)
- Asks for same schema; omitted fields = "give up on this field"

### CORRECTION loop merge semantics (`_apply_corrections`)
- Flagged fields: replace with new value, OR drop if extractor omitted
- Accepted fields: keep unless extractor re-sent (then replace)
- New field names not in previous output: ignored (no expansion)

---

## 6. Run history

### Run 1 — `tmp_run/run_grounded.py` first attempt
- **Result**: aborted with crashes
- **Root cause**: Windows gbk stdout codec couldn't encode `↳` arrow
  inside the script's `on_event` print → exception bubbled up through
  `context.emit` → `_archiving_emit` → into the node's per-map
  try/except → entire map's fields cleared on each crash
- **Fix**: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
  and wrap `on_event` in try/except inside the run script
- **Lesson**: user-supplied event handlers must NEVER bubble exceptions
  back into the node. Consider hardening `context.emit` in
  `backend/engine/context.py` to swallow handler exceptions.

### Run 2 — 1558s, Gemini critic
- Extractor: qwen3-vl-235b-instruct; critic: gemini-2.5-pro
- Successes: 9 maps completed, evidence preview images generated
- Failures:
  - Gemini 504 timeouts on maps 7 (Yorkes) and 8 (Gawler) — critic skipped
  - One map hit Gemini RECITATION block (caught by fallback handler)

### Run 3 — 1480s, Claude critic, strict
- Switched critic to anthropic/claude-sonnet-4-5 (via OpenRouter) to
  avoid Gemini geo-block
- Connection errors on maps 3 (S America) and 4 (Australia) — those
  rows were empty; added retry → run 4
- Critic over-strict: 8 maps lost 30-60% of their fields to demotion
- Total 185 filled metadata cells across 9 maps

### Run 4 — 905s, calibrated critic
- Added `_with_retry` for transient OpenRouter errors → maps 3 & 4
  recovered
- Recalibrated CRITIC_USER: "bias to ok=true" + tolerance list
- Total 267 filled metadata cells (+44% vs run 3)
- But regression: Arctic country list back to "USA, Canada, Russia,
  Norway, Greenland" (Ingrid's #1 complaint)
- Also: Port Moresby bbox_north precision regressed from -9.425 (run 3
  critic-corrected) back to -9.4167 (extractor's original)

### Run 5 — 927s, specialist critic ensemble
- Implemented `_run_specialist_critics` that partitions claims by
  `_FIELD_DOMAINS` and fans out 3 calls in parallel:
  - `geo_critic` (strict) on country/province/city/district/bbox_*/coordinates_text
  - `ocr_critic` (medium) on title/date/publisher/scale/projection/notes/...
  - `visual_critic` (lenient) on map_type/medium/condition/coverage/...
- Added `_partition_claims_by_domain` + `_domain_of` helpers.
- Added 3 pairs of templates (GEO_CRITIC_SYSTEM/USER, OCR_*, VISUAL_*)
  exposed through `prompt_templates` router so each can be edited.
- Added `map_review_fields_uncertain` and `map_review_fields_demoted`
  columns surfacing critic-touched fields per row.
- Added JSON parse robustness in `llm_utils.extract_json` to handle
  "Extra data after JSON" via `JSONDecoder.raw_decode` (Claude
  sometimes appends a second blob).
- First attempt crashed on every map with
  `KeyError: '\\n  "verdicts"'` — the JSON example braces in
  `_CRITIC_RETURN_SHAPE` weren't doubled for `.format()`. Fixed by
  escaping braces in shared shape.
- Headline result: **total filled cells 232** vs Run 4 (267), a 13%
  recall drop. BUT:
  - Map 171 Arctic country dropped USA/Canada (geo_critic caught the
    "Arctic = USA+Canada+Russia" leak) → "Greenland, Norway, Russia"
    only, plus `map_review_fields_uncertain = "country"` flag for
    Ingrid to manually verify.
  - Map 921 Port Moresby: `map_review_fields_uncertain = "coordinates_text, has_insets"` exposed exactly what Ingrid had complained about.
  - Map 831.113 Port Adelaide: `map_review_fields_demoted = "notes, place_names"` — transparency about lost data.
  - Map 8 Gawler regressed to 8 cells (-21) — root cause was a
    Claude-returned response with extra trailing tokens that the old
    extract_json couldn't parse. The robustness fix applies on the next run.
- Cost: ~$2.50 observed (3× Qwen extractor + 3 critic calls per
  correction round × 9 maps). Token totals: 50-300k input, 5-15k output
  per map depending on correction rounds.

Specialist critics are net positive for the precision/transparency
goal Ingrid signaled (she'd rather see "AI is uncertain about this"
than silently-correct-looking hallucinations). But to match Run 4
recall, two follow-ups are needed:
  - JSON-parse robustness on Claude's occasional double-blob outputs (✓ shipped)
  - geo_critic calibration is currently a bit too strict on
    Younghusband / Port Adelaide where it dropped country/province on
    purely visual evidence (visible labels exist but in small print)

### Run 6 — 666s, Gemini 2.5 Flash Lite critic (cheap-critic test)
- Same Qwen3-VL-235B extractor as Run 5
- Critic swapped from `anthropic/claude-sonnet-4.5` to
  `google/gemini-2.5-flash-lite` via OpenRouter
- Required `_run_one_specialist` to be wired in already; just changed
  `CRITIC_MODEL` env var
- First attempt used `google/gemini-2.5-flash-preview` — that ID is
  stale on OpenRouter (returns 400 "not a valid model ID"). Pulled
  `/v1/models` from OpenRouter to find the real ID:
  `google/gemini-2.5-flash-lite` ($0.10/$0.40 per M token, ~14× cheaper
  than Claude Sonnet).
- Registered the live model IDs in `openrouter_provider.py`
  (`gemini-2.5-flash-lite`, `gemini-2.0-flash-001`, `claude-3-haiku`,
  `qwen3-vl-32b-instruct`, etc.) — kept old stale ones out.
- Result: 242 filled cells (+25 vs Run 5), only 1 uncertain row, 0
  demoted, ~666s wall-clock (-30% vs Run 5).
- Cost: $0.091 total for 9 maps (~$0.01/map). 15% of Run 4's $0.61.
  Projected 1225 maps ≈ $12.
- Flash Lite is more lenient than Claude. Caught the Arctic
  "USA, Canada" leak (kept only "Greenland, Norway, Russia") but
  let through some character-level OCR drifts (e.g. Yorkes "1 inch =
  10 Mls." instead of "30 Mls."). Acceptable tradeoff for the price.

### Run 7 — 562s, Qwen3-VL-32B + Flash Lite (all-cheap)
- Extractor swapped from 235B → `qwen/qwen3-vl-32b-instruct`
  ($0.10/$0.42 per M token vs 235B's $0.20/$0.88)
- Same Gemini 2.5 Flash Lite critic
- Result: 245 filled cells (more than Run 5 and 6), 4 uncertain
  rows, 3 demoted rows, ~562s wall-clock (fastest of all runs).
- Cost: $0.065 total for 9 maps (~$0.007/map). **11% of Run 4** cost.
  Projected 1225 maps ≈ $9.
- Wins:
  - Arctic country: "Greenland, Norway, Russia, Canada" — USA dropped
    (Ingrid's key concern handled). Canada is technically reasonable
    since Ellesmere Island coast IS visible. Better than Run 4
    baseline ("USA, Canada, Russia, Norway, Greenland").
  - 740 S America: 13 countries all listed (all printed on the map);
    bbox correct (-85/-30/-55/12); publisher correct.
- Losses (vs Run 5 with the bigger Qwen extractor):
  - Port Moresby bbox: all 4 edges demoted because Qwen-32B couldn't
    accurately read the small coordinate ticks. The audit column
    correctly flags this — a downstream consumer sees an empty bbox
    rather than a hallucinated one, which is the desired failure mode.
  - Yorkes scale text: "Scale — 1\" = 10 Mls." (Run 4: "30 Mls.").
    32B extractor OCR'd the digit wrong. Critic let it through.

### 4-run cost & quality comparison

| Run | Extractor | Critic | Fields | Uncert. rows | Demoted rows | Tokens | Cost | vs Run 4 |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 4 | Qwen3-VL-235B | Claude Sonnet 4.5 (1 critic) | 258 | 0 | 0 | 368k | $0.61 | 100% |
| 5 | Qwen3-VL-235B | Claude (3 specialists) | 217 | 5 | 2 | 416k | $0.88 | 145% |
| 6 | Qwen3-VL-235B | Gemini 2.5 Flash Lite (3 specialists) | 242 | 1 | 0 | 463k | $0.09 | 15% |
| 7 | **Qwen3-VL-32B** | Gemini 2.5 Flash Lite (3 specialists) | 245 | 4 | 3 | 457k | $0.07 | **11%** |

Counts use "non-empty `map_*` cell, excluding `map_review_*` and
`map_regions_preview`". Costs use the per-M pricing in `compare_runs.py`.

**Production recommendation (current state):**
1. Default config = **Run 7 setup** (Qwen3-VL-32B + Gemini 2.5 Flash Lite + specialist critics + audit columns).
   - $9 for the full 1225-map RGSSA collection.
   - Audit columns surface ~7 rows/9 that need human spot-check.
2. For maps where the Run 7 audit flags `bbox_*` or `coordinates_text`
   as demoted, optionally re-run those rows with the Qwen3-VL-235B
   extractor (Run 5/6 config). Costs maybe $1-2 more for the long tail.
3. Skip Claude critic in production. Run 5 showed it's 14× more
   expensive and the quality delta vs Flash Lite for catching Ingrid's
   actual flagged failure modes is marginal — both catch the
   training-knowledge leaks; Claude is stricter on minor OCR drift,
   but those are already in the audit log anyway.

---

## 7. Ingrid's per-map issues — status by run

Legend: ✓ fixed | ≈ partial | ✗ regression | ? not addressed | — N/A

| Map | Issue | Run 3 | Run 4 | Run 5 (planned) |
|---|---|---|---|---|
| 000 HEAVENS | No errors detected | — | — | — |
| 171 Arctic | width/height from filename | ✓ (B-group adds map_image_w_cm = 45.87) | ✓ | ✓ |
| 171 Arctic | bbox -180/180/60/90 spans full original map | ✓ (empty) | ✗ (-180/180/60/90 back) | ✓ (geo_critic) |
| 171 Arctic | country lists USA/Canada (in missing half) | ✓ ("International") | ✗ (back) | ✓ (geo_critic) |
| 171 Arctic | "8/31" transcribed as "SAN" | ? | ? | OCR-dependent |
| 740 S America | Falkland/Canal Zone/Juan Fernandez listed as insets | ? | ✓ (only Galapagos + thematic insets) | ✓ |
| 740 S America | Brasilia listed (didn't exist 1937) | ? | ✓ (critic flagged) | ✓ |
| 804 Australia | scale_ratio 6,000,000 unverifiable | ≈ (empty) | ✓ (empty) | ✓ |
| 804 Australia | scan dpi reporting requested | ✓ (200 dpi) | ✓ | ✓ |
| 831.113 Port Adelaide | "13" handwritten as "12" | ? | ? | OCR-dependent |
| 831.12 Younghusband | "R.A." Luebbers initials inserted | ≈ (empty publisher) | ✓ ("Luebbers" only) | ✓ |
| 831.12 Younghusband | "Continued Below/Above" mis-interp as series | ? | ✓ (clean notes) | ✓ |
| 831.18 Yorkes | scale_ratio unverifiable | ≈ | ≈ | tagged |
| 831.18 Yorkes | Boggs Lewis number misread | ? | ? | OCR-dependent |
| 834.2 Gawler | Boggs Lewis decimal missing | ? | ? | OCR-dependent |
| 921 Port Moresby | "S.G.F" should be "N.G.F" | ✓ (empty) | ≈ ("Lambert" no prefix) | ≈ |
| 921 Port Moresby | notes incorrectly paraphrased ("brown contours converge…") | ✓ (correct version) | ≈ (truncated) | ? |

Architectural fixes (apply to all maps):
- ✓ B-group columns added: pixel_w/h, dpi_x/y, image_w_cm/h_cm, scale_source
- ? Scan resolution reporting: 200 dpi column added (Ingrid asked for it)
- ? Per-field confidence annotation: planned for run 5

---

## 8. Cost analysis

Token cost per map (run 4 measurements):
- Extractor: ~25k input + ~3.5k output per map (single grounded pass)
- Critic + correction rounds: ~5-50k input + ~1.5-10k output (varies)
- Total per map: ~30-75k input + ~5-13k output

OpenRouter pricing (as of 2026):
- `qwen/qwen3-vl-235b-a22b-instruct`: ~$0.30/M in, $0.30/M out
- `anthropic/claude-sonnet-4-5`: ~$3/M in, $15/M out

Per-map cost estimate:
- Cheap case (no correction rounds): ~$0.08
- Typical case (1 correction round): ~$0.15
- Worst case (2 correction rounds, hard map): ~$0.30

Run 4 (9 maps, mixed): ~$1.50 total observed.

Projection to Ingrid's full collection (1225 maps):
- Best case: $98
- Typical: $184
- Worst: $367

Aligns with Ingrid's email estimate of "less than $100 and may be as
low as $28" (her estimate was for the cheaper old multilevel pipeline
without critic loop). Adding the critic increases cost ~3x but is the
key to the quality Ingrid praised in her review.

---

## 9. Operational notes

### Storage
- `backend/storage/map_previews/` — evidence preview PNGs (gitignored)
- `backend/storage/map_debug/` — prompt logs + debug_archive_*.json (gitignored)
- `backend/storage/prompt_templates.json` — user-customized template overrides (gitignored — at runtime overrides the in-code defaults via `_get_tmpl`)

### Test data
`C:\Users\14002\OneDrive\桌面\u盘：f\HD maps\` — 9 TIF maps, 21-137 MB each, all 200 dpi:
```
000 a 1957 A Map of the HEAVENS  National Geographic 71.5cm X 106.6cm Side 1.tif  (8404×5616)
171 a 1912 Arctic region 91cmX91cm.tif                                              (7163×3612)  ← partial scan
740 fa 1937  S America 95cm X 68cm.tif                                              (5376×7473)
804 ac 1954 Australia 38cmX33cm.tif                                                 (2964×2582)
831.113 1858 Port Adelaide Harbour Development 43cmX57cm.tif                        (4156×4491)
831.12 eac 1982 Younghusband Peninsula Archeological Sites 42cmX30cm.tif            (3300×2321)
831.18 ac 1868 Yorkes Peninsula signed Goyder 28.5cm X 32.6cm.tif                   (2832×2560)
834.2 atc 1858 Gawler Ranges 51cmX37cm.tif                                          (4220×2906)
921.411 a 1943 Port Moresby 90cmX64cm.tif                                           (7133×6448)
```

PIL handles the fullwidth-colon path ("u盘：f") fine on Windows.

### Run script
`tmp_run/run_grounded.py` (gitignored). Bypasses UI/pipeline engine,
drives `AIMapAnalysisNode.execute()` directly. Reads API keys from env
vars. Outputs xlsx + csv + event_log.json. Hardened against
encoding-induced print crashes (`sys.stdout.reconfigure(encoding=
"utf-8")` + try/except around event handler body).

### Comparison script
`tmp_run/compare_to_ingrid.py` (gitignored). Maps each of Ingrid's
per-map issues to a status: `n/a` / `fixed_by_structure` / `improved` /
`tagged` / `ocr_dependent` / `manual_check`. Writes
`tmp_run/ingrid_comparison.md`.

### How to add a new model
1. Append `ModelInfo(...)` to the relevant provider in
   `backend/providers/`
2. If it's OpenAI-compatible: just register; existing
   `call_vision_conversation` will work
3. If it's a novel API: implement provider class extending `LLMProvider`

### How to add an extracted field
1. Append `(json_key, df_column)` tuple to `MAP_FIELDS` at top of
   `ai_map_analysis.py`
2. If numeric: add `json_key` to `_NUMERIC_FIELDS`
3. Add `(json_key, "geo" | "ocr" | "visual")` to `_FIELD_DOMAINS` for
   critic routing
4. Update `EXTRACT_USER` prompt's allowed field list
5. Add to `_SUMMARY_KEYS` dict in `process_map` if it should appear in
   debug `synthesis_result` summary

### How to switch critic model
Just pass a different `critic_model` config value. The node:
- Looks up provider via `get_provider_id_for_model`
- Resolves api_key from `context.get_api_key(provider_id)`
- Falls back to disabled if model id unknown
- Blank = skip critic loop entirely

---

## 10. Future directions evaluated but NOT taken

### Tool-use forced grounding (rejected: too much infra)
- Idea: pre-run PaddleOCR/Surya layout detection, give extractor a
  fixed candidate set of (bbox, text) pairs to pick from
- Pro: hallucination structurally impossible
- Con: requires another model + Python install pain; adds 5-15s/map
- Decision: defer unless quality plateaus

### Self-consistency multi-model (rejected: 3x cost, same biases)
- Idea: run Qwen + GPT-4o + Claude in parallel, take consensus per field
- Con: all 3 vision models likely share the "Arctic = USA/Canada/Russia"
  prior; consensus doesn't catch shared hallucinations
- Decision: not now

### Selective re-OCR on low-confidence fields (deferred)
- Idea: if extractor's confidence on title/scale_text is low, auto-crop
  the bbox and ask a separate "just OCR this" prompt
- Pro: targets exactly the OCR-dependent issues Ingrid flagged
- Decision: defer until specialist critic results show this is needed

### Confidence-tiered output with cell coloring (planned)
- xlsx with red/yellow conditional formatting on flagged cells
- Requires openpyxl conditional formatting; existing xlsx writer doesn't
  do colors
- Decision: add when specialist critic emits per-field confidence

### Cross-map post-processing (deleted, may revive)
- The old multilevel pipeline had a batch QA pass that compared maps
  to each other (consistent country names, deduped publishers)
- Deleted with the multilevel code
- Could revive as a post-process node after grounded extraction
- Useful for catching e.g. "Port Adelaide" vs "Port Adelaid" typos
  across batch

---

## 11. Open questions for next iteration

1. Should `evidence_kind = "from_external_knowledge"` be a permitted
   value (and trigger auto-demote)? Current schema doesn't allow it;
   the model must omit the field. This may push hallucinations into
   the gaps elsewhere.

2. Should specialist critics see **crops** of just their relevant
   regions (saves tokens, sharper focus) instead of the full image?
   Geo critic only needs the title block + place labels; OCR critic
   needs the title + scale + notes; visual critic needs the whole.
   Estimate: ~30% token reduction at cost of more crops.

3. Should the correction loop go MORE than 2 rounds when a critic
   keeps flagging the same field with different specific issues? Right
   now max_rounds=2 caps it; sometimes a 3rd round would yield convergence.

4. Should we cache `_full_image_b64` per file path across reruns?
   Currently re-encoded every run. Negligible CPU but wastes a few
   seconds × number of maps.

5. The `notes` field tends to be where models smuggle interpretation
   ("brown contours converge" vs "brown (convergence) figures"). Should
   `notes` get a stricter "verbatim quote" mode?

---

## 12. Quick reference: file inventory

| Path | Purpose | Tracked |
|---|---|---|
| `backend/nodes/ai_map_analysis.py` | Main node, all prompts, orchestration | ✓ |
| `backend/routers/prompt_templates.py` | HTTP API for prompt editing | ✓ |
| `backend/routers/map_knowledge.py` | Knowledge-base injection (phases: extract, critic) | ✓ |
| `backend/routers/fewshot.py` | Few-shot annotated examples (legacy phases L1/L2b) | ✓ |
| `backend/providers/openrouter_provider.py` | Vision models registered | ✓ |
| `backend/providers/google_provider.py` | Gemini support + RECITATION fallback | ✓ |
| `frontend/src/templates/ai_map_analysis.ts` | Default UI pipeline template | ✓ |
| `frontend/src/components/AIDebugPanel.tsx` | SSE event phase styling | ✓ |
| `frontend/src/components/MapAnalysisPanel.tsx` | Phase timeline (grounded/legacy auto-detect) | ✓ |
| `frontend/src/hooks/useSSE.ts` | Phase event handler / store sync | ✓ |
| `docs/MAP_ANALYSIS_DESIGN_NOTES.md` | This file | ✓ |
| `tmp_run/run_grounded.py` | Standalone test runner | gitignored |
| `tmp_run/compare_to_ingrid.py` | Per-map issue diff | gitignored |
| `tmp_run/grounded_run_output.xlsx` | Latest run output | gitignored |
| `tmp_run/grounded_run3_strict_critic.xlsx` | Run 3 archive | gitignored |
| `tmp_run/event_log_run3.json` | Run 3 event archive | gitignored |
| `backend/storage/map_previews/` | Evidence preview PNGs | gitignored |
| `backend/storage/map_debug/` | Prompt logs, debug archives | gitignored |
