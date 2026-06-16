"""Core extraction pipeline — validated dashscope SDK + local-file route.

No GUI dependencies. Used by the PySide6 app and any CLI.
"""
import os, io, json, re, time, tempfile, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

Image.MAX_IMAGE_PIXELS = 250_000_000

import dashscope

MAP_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".jp2", ".bmp", ".webp")
LIST_FIELDS = ("country", "place_names", "province", "city")

# DashScope regional endpoints. Two styles:
#   ws_in_url=False  -> public endpoint, workspace passed as a call parameter
#                       (China Beijing, US Virginia)
#   ws_in_url=True   -> workspace-scoped host, workspace baked into the URL
#                       (Singapore, Germany Frankfurt)
REGIONS = {
    "beijing":   {"label": "China · Beijing  (华北2/北京 — 国内最稳)",
                  "base": "https://dashscope.aliyuncs.com/api/v1", "ws_in_url": False},
    "us":        {"label": "US · Virginia  (弗吉尼亚 — 澳洲生产推荐)",
                  "base": "https://dashscope-us.aliyuncs.com/api/v1", "ws_in_url": False},
    "singapore": {"label": "Singapore  (新加坡)",
                  "base": "https://{ws}.ap-southeast-1.maas.aliyuncs.com/api/v1", "ws_in_url": True},
    "frankfurt": {"label": "Germany · Frankfurt  (法兰克福)",
                  "base": "https://{ws}.eu-central-1.maas.aliyuncs.com/api/v1", "ws_in_url": True},
}
DEFAULT_REGION = "beijing"

ENCODE_MAX_DIM = 3840      # 4K long side; JPEG fine above 4K per DashScope
JPEG_QUALITY = 90
MAX_PIXELS = 6000 * 32 * 32  # ~6000 visual tokens

SYSTEM_PROMPT = (
    "You are a catalog assistant for a library archive of historical printed "
    "maps. The Royal Geographical Society of South Australia (RGSSA) is "
    "digitizing its collection for ingest into Trove, the National Library of "
    "Australia's discovery service. Extract structured cataloging metadata "
    "(Dublin Core fields) from each scanned map.\n\n"
    "This is descriptive bibliographic cataloging — list what is printed on the "
    "map sheet. Not geopolitical analysis; record visible labels of countries, "
    "regions, and place-names as they appear on the printed sheet.\n\n"
    "For each list field item (country, place_names, province, city), categorize "
    "the visual evidence:\n"
    "  DIRECT     — the country/place name itself is printed on the map\n"
    "  SUB_REGION — you see a sub-region label that implies the parent country "
    "(Spitzbergen -> Norway; Yamal -> Russia)\n"
    "  INFERRED   — you cannot point to any direct or sub-region visual evidence; "
    "the claim comes from period context or training knowledge\n\n"
    "Be honest. If you cannot find evidence, mark INFERRED."
)

USER_PROMPT = (
    "Catalog this historical printed map for the RGSSA library archive. Output "
    "STRICT JSON only. The output is mapped to Dublin Core metadata, so be "
    "thorough — extracting MORE is fine, omitting a present value is not.\n\n"
    "Schema:\n"
    "{\n"
    '  "title": "...", "subtitle": "...",\n'
    '  "creator": "...",            // cartographer / surveyor / "drawn by" / "compiled by" — the maker (DC:Creator)\n'
    '  "contributor": "...",        // engraver, lithographer, printer, reproducer (DC:Contributor)\n'
    '  "date_text": "...", "date_year": <int or null>,\n'
    '  "publisher": "...",          // publishing body / institution (DC:Publisher)\n'
    '  "scale_text": "...", "scale_ratio": <int or null>, "projection": "...",\n'
    '  "edition": "...", "coordinates_text": "...",\n'
    '  "bbox_west": <float or null>, "bbox_east": <float or null>, "bbox_south": <float or null>, "bbox_north": <float or null>,\n'
    '  "place_names": [{"value":"...", "category":"DIRECT|SUB_REGION|INFERRED", "evidence":"..."}],\n'
    '  "country":     [{"value":"...", "category":"DIRECT|SUB_REGION|INFERRED", "evidence":"..."}],\n'
    '  "province":    [{"value":"...", "category":"DIRECT|SUB_REGION|INFERRED", "evidence":"..."}],\n'
    '  "city":        [{"value":"...", "category":"DIRECT|SUB_REGION|INFERRED", "evidence":"..."}],\n'
    '  "district": "...", "legend_content": "...", "notes": "...",\n'
    '  "map_type": "topographic|geological|nautical|cadastral|thematic|sketch|plan|celestial|other",\n'
    '  "subject": "...",            // comma-separated keywords (DC:Subject)\n'
    '  "coverage": "...",           // geographic/temporal extent in words (DC:Coverage)\n'
    '  "medium": "...",             // material + colour + technique, e.g. "lithograph, hand-coloured" (DC:Format)\n'
    '  "language": "...", "condition": "...",\n'
    '  "identifier": "...",         // catalogue/accession number printed or stamped (e.g. "RG 831.18ac 1868") (DC:Identifier)\n'
    '  "rights": "...",             // copyright / rights statement printed on the sheet (DC:Rights)\n'
    '  "source": "...",             // if it is a figure/plate from a publication: the source work (DC:Source)\n'
    '  "relation": "...",           // related sheets/series ("Sheet 2 of 4", "Continued above") (DC:Relation)\n'
    '  "has_insets": "no | yes: <brief>", "description": "..."\n'
    "}\n\n"
    "For country: be EXHAUSTIVE. List EVERY sovereign nation whose territory "
    "appears (even small slivers / edges / via place names). Use period-correct "
    'names ("British Guiana" for 1937 Guyana; "Russian Empire" for 1912 Russia).\n\n'
    "For identifier: look for handwritten or stamped catalogue numbers, often in "
    'a corner (e.g. "RG 831.18ac 1868"). For rights: look for copyright lines '
    '("COPYRIGHT 1937 BY ..."). For creator: look for "Drawn by", "Compiled by", '
    '"Surveyed by", cartographer signatures.\n\n'
    "Be honest about category. If a country's territory appears but no direct or "
    "sub-region label is visible, mark INFERRED. For scalar fields, leave \"\" "
    "if not present — never invent."
)


def extract_json(text: str) -> dict | None:
    """Robust JSON extraction: strips ``` fences, finds first balanced object."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        nl = t.find("\n")
        if nl >= 0:
            t = t[nl + 1:]
        lf = t.rfind("```")
        if lf >= 0:
            t = t[:lf]
        t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    # First balanced object
    depth = 0; start = -1; in_str = False; esc = False
    for i, c in enumerate(t):
        if in_str:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': in_str = False
            continue
        if c == '"': in_str = True
        elif c == "{":
            if depth == 0: start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception:
                    start = -1
    return None


def normalize_list_field(v) -> list[dict]:
    """Accept str / [str] / [dict] → list of {value, category, evidence}."""
    out = []
    if v is None:
        return out
    if isinstance(v, str):
        for part in re.split(r"[,;]", v):
            part = part.strip()
            if part:
                out.append({"value": part, "category": "DIRECT", "evidence": ""})
        return out
    if isinstance(v, list):
        for it in v:
            if isinstance(it, str):
                if it.strip():
                    out.append({"value": it.strip(), "category": "DIRECT", "evidence": ""})
            elif isinstance(it, dict):
                val = str(it.get("value", "")).strip()
                if val:
                    out.append({
                        "value": val,
                        "category": str(it.get("category", "DIRECT") or "DIRECT").upper(),
                        "evidence": str(it.get("evidence", ""))[:300],
                    })
    return out


def compress_to_temp(img_path: Path, tmp_dir: Path) -> Path:
    """Downscale a large map to a temp JPEG; return its path."""
    img = Image.open(img_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > ENCODE_MAX_DIM:
        r = ENCODE_MAX_DIM / max(w, h)
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    out = tmp_dir / (img_path.stem + "__qwen.jpg")
    img.save(out, "JPEG", quality=JPEG_QUALITY)
    img.close()
    return out


class QwenExtractor:
    def __init__(self, api_key: str, workspace_id: str, region: str = DEFAULT_REGION):
        self.api_key = api_key
        self.workspace_id = workspace_id
        self.region = region if region in REGIONS else DEFAULT_REGION
        cfg = REGIONS[self.region]
        self.ws_in_url = cfg["ws_in_url"]
        self.base_url = cfg["base"].format(ws=workspace_id)
        # workspace passed as a call param only on public endpoints
        self.call_workspace = None if self.ws_in_url else workspace_id

    def extract(self, img_path: Path, tmp_dir: Path, max_retries: int = 10,
                on_retry=None, log=None) -> dict:
        """log(msg, level) — optional detailed step logger for debugging."""
        t0 = time.time()
        fn = img_path.name

        def dbg(msg, level="debug"):
            if log:
                log(f"   [{fn}] {msg}", level)

        dashscope.base_http_api_url = self.base_url

        # Step 1: compress
        try:
            src_sz = img_path.stat().st_size / 1024 / 1024
            jpg = compress_to_temp(img_path, tmp_dir)
            jpg_sz = jpg.stat().st_size / 1024
            from PIL import Image as _I
            with _I.open(jpg) as _im:
                dims = f"{_im.width}x{_im.height}"
            dbg(f"compress: {src_sz:.0f}MB -> {jpg_sz:.0f}KB JPEG ({dims})")
        except Exception as e:
            err = f"step=compress: {type(e).__name__}: {e}"
            dbg(err, "err")
            return _fail(err, img_path, t0)

        local_uri = f"file://{jpg.resolve()}"
        messages = [
            {"role": "system", "content": [{"text": SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"image": local_uri}, {"text": USER_PROMPT}]},
        ]
        dbg(f"params: model=qwen3.7-plus thinking=True max_pixels={MAX_PIXELS} "
            f"region={self.region} endpoint={self.base_url.split('//')[1].split('/')[0]}")

        # ── streaming + partial-continuation salvage loop ──────────────
        # answer_so_far survives across attempts: if a stream drops AFTER the
        # JSON answer started, we resume with partial mode (no re-thinking),
        # salvaging the expensive reasoning already done.
        answer_so_far = ""
        reasoning_first = ""   # reasoning from the first (thinking) attempt
        usage = {}
        last_err = ""
        attempt = 0
        while attempt < max_retries:
            continuing = bool(answer_so_far.strip())
            try:
                if continuing:
                    dbg(f"step=continue attempt={attempt+1}/{max_retries} "
                        f"(partial, have {len(answer_so_far)}ch)")
                    msgs = messages + [{"role": "assistant",
                                        "content": [{"text": answer_so_far}],
                                        "partial": True}]
                    think = False   # don't re-think when continuing
                else:
                    dbg(f"step=api_call attempt={attempt+1}/{max_retries} (streaming)")
                    msgs = messages
                    think = True

                call_kw = {}
                if self.call_workspace:
                    call_kw["workspace"] = self.call_workspace
                responses = dashscope.MultiModalConversation.call(
                    api_key=self.api_key, model="qwen3.7-plus", messages=msgs,
                    enable_thinking=think, vl_high_resolution_images=False,
                    max_pixels=MAX_PIXELS, stream=True, incremental_output=True,
                    **call_kw,
                )

                delta = ""
                reasoning_parts = []
                reasoning_len = 0
                finish = "?"
                stream_err = None
                last_tick = time.time()
                for resp in responses:
                    if resp.status_code != 200:
                        stream_err = f"HTTP{resp.status_code} code={resp.code}: {resp.message}"
                        break
                    try:
                        choice = resp.output.choices[0]
                        m = choice.message
                        finish = getattr(choice, "finish_reason", None) or finish
                    except Exception:
                        continue
                    try:
                        rc = m["reasoning_content"]
                    except (KeyError, TypeError):
                        rc = None
                    if rc:
                        reasoning_len += len(rc)
                        if reasoning_len <= 20000:
                            reasoning_parts.append(rc)
                    content = m.content
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and "text" in c:
                                delta += c["text"]
                    elif isinstance(content, str):
                        delta += content
                    if resp.usage:
                        usage = resp.usage
                    if on_retry is None and time.time() - last_tick > 4:
                        phase = "writing" if (continuing or delta) else "thinking"
                        dbg(f"{phase}… reasoning≈{reasoning_len}ch "
                            f"answer={len(answer_so_far)+len(delta)}ch ({time.time()-t0:.0f}s)")
                        last_tick = time.time()

                answer_so_far += delta
                if not continuing and reasoning_parts:
                    reasoning_first = "".join(reasoning_parts)

                if stream_err:
                    last_err = f"step=stream {stream_err}"
                    dbg(f"{last_err} (have {len(answer_so_far)}ch answer)", "warn")
                    if not _retryable(last_err) or attempt == max_retries - 1:
                        # Try to salvage whatever JSON we have
                        meta = extract_json(answer_so_far)
                        if meta:
                            break
                        return _fail(last_err, img_path, t0)
                    _backoff(attempt, on_retry, fn, last_err)
                    attempt += 1
                    continue

                dbg(f"step=response finish={finish} answer={len(answer_so_far)}ch "
                    f"reasoning≈{reasoning_len}ch tok_out={usage.get('output_tokens',0)}")

                # Empty answer after a full thinking pass → retry fresh.
                if not answer_so_far.strip():
                    last_err = f"step=empty_answer finish={finish}"
                    dbg(last_err, "warn")
                    if attempt == max_retries - 1:
                        return {"ok": False, "error": last_err, "filename": fn,
                                "file_path": str(img_path),
                                "reasoning": reasoning_first[:4000],
                                "elapsed_sec": time.time() - t0}
                    _backoff(attempt, on_retry, fn, last_err)
                    attempt += 1
                    continue

                # Parse; if incomplete JSON, continue via partial next loop.
                meta = extract_json(answer_so_far)
                if meta is None:
                    last_err = f"step=json_parse: incomplete JSON ({len(answer_so_far)}ch)"
                    dbg(last_err, "warn")
                    if attempt == max_retries - 1:
                        return {"ok": False, "error": last_err, "filename": fn,
                                "file_path": str(img_path),
                                "raw_answer": answer_so_far[:2000],
                                "reasoning": reasoning_first[:4000],
                                "elapsed_sec": time.time() - t0}
                    _backoff(attempt, on_retry, fn, last_err)
                    attempt += 1
                    continue

                break  # success
            except Exception as e:
                last_err = f"step=api_call {type(e).__name__}: {str(e)[:200]}"
                dbg(f"{last_err} (have {len(answer_so_far)}ch)", "err")
                if not _retryable(last_err) or attempt == max_retries - 1:
                    meta = extract_json(answer_so_far)
                    if meta:
                        break
                    return _fail(last_err, img_path, t0)
                _backoff(attempt, on_retry, fn, last_err)
                attempt += 1

        # Final parse + normalize
        meta = extract_json(answer_so_far)
        if meta is None:
            return _fail(last_err or "json_parse_fail", img_path, t0)
        for f in LIST_FIELDS:
            if f in meta:
                meta[f] = normalize_list_field(meta[f])
        dbg(f"step=done OK ({time.time()-t0:.0f}s, "
            f"{sum(len(meta.get(f,[]) or []) for f in LIST_FIELDS)} list items)", "ok")
        return {
            "ok": True, "filename": fn, "file_path": str(img_path),
            "metadata": meta, "reasoning": reasoning_first[:8000],
            "raw_answer": answer_so_far[:8000],
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0),
            "elapsed_sec": time.time() - t0,
        }


def _retryable(msg: str) -> bool:
    m = msg.lower()
    if any(s in m for s in ["401", "403", "invalid api", "permission", "invalidapikey"]):
        return False
    markers = ["timeout", "connection", "network", "temporarily", "429", "rate",
               "throttl", "502", "503", "504", "500", "overload", "reset",
               "ssl", "broken pipe", "read timed out",
               "chunked", "ended prematurely", "incomplete read", "eof",
               "remotedisconnected", "remote end closed", "protocol"]
    return any(s in m for s in markers)


def _backoff(attempt, on_retry, fn, err):
    import random
    wait = min(60, 5 * (2 ** attempt)) + random.uniform(0, 2)
    if on_retry:
        on_retry(fn, attempt + 1, wait, err)
    time.sleep(wait)


def _fail(err, img_path, t0):
    return {"ok": False, "error": err, "filename": img_path.name,
            "file_path": str(img_path), "elapsed_sec": time.time() - t0}


def count_flagged(result: dict) -> int:
    if not result.get("ok"):
        return 0
    meta = result.get("metadata", {})
    n = 0
    for f in LIST_FIELDS:
        for it in meta.get(f, []) or []:
            if isinstance(it, dict) and it.get("category", "").upper() == "INFERRED":
                n += 1
    return n


def scan_files(folder: str, limit: int = 0) -> list[Path]:
    files = sorted(
        (p for p in Path(folder).iterdir() if p.suffix.lower() in MAP_EXTS),
        key=lambda p: p.name.lower(),
    )
    return files[:limit] if limit > 0 else files
