import json
import base64
import asyncio
import os
import pandas as pd
import httpx
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField
from ..providers.registry import call_vision_llm, get_provider_id_for_model
from ..engine.context import build_data_preview
from .llm_utils import extract_json, clean_cell

def _relative_image_path(abs_path: str) -> str | None:
    """Convert absolute image path to relative path under storage/uploads/."""
    uploads_marker = os.path.join("storage", "uploads")
    norm = os.path.normpath(abs_path)
    idx = norm.find(uploads_marker)
    if idx < 0:
        return None
    return norm[idx + len(uploads_marker) + 1:].replace("\\", "/")


MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp",
    ".tiff": "image/tiff", ".tif": "image/tiff",
}


def _detect_media_type(path_or_url: str) -> str:
    ext = os.path.splitext(path_or_url.split("?")[0])[1].lower()
    return MIME_MAP.get(ext, "image/jpeg")


# MIME types natively supported by vision APIs (OpenAI, Anthropic, Google)
_API_SUPPORTED_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Vision API upload limits: OpenAI 20 MB, Anthropic 20 MB, Gemini 20 MB.
# Use 18 MB as safe ceiling (leaves room for base64 overhead in payload).
_MAX_IMAGE_BYTES = 18 * 1024 * 1024


def _fix_mode(img):
    """Convert exotic PIL modes to RGB for JPEG compatibility."""
    if img.mode in ("I", "I;16", "F"):
        return img.convert("RGB")
    if img.mode in ("LA", "RGBA", "PA", "P"):
        return img.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _to_jpg(img, quality: int = 95) -> bytes:
    """Save PIL Image to JPEG bytes."""
    import io
    img = _fix_mode(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _resize_if_needed(raw_bytes: bytes, media_type: str, max_dim: int) -> tuple[bytes, str]:
    """Convert unsupported formats (TIFF, BMP, etc.) to JPEG, resize if
    needed, and ensure the result fits within API upload limits.

    Strategy:
    - Unsupported formats → always convert to JPEG q=95.
    - Supported formats over size limit → resize (keep original format).
    - max_dim > 0 → also enforce a hard pixel-dimension cap.
    - max_dim == 0 → only constrain by byte-size limit.
    """
    needs_convert = media_type not in _API_SUPPORTED_MIMES
    over_size = len(raw_bytes) > _MAX_IMAGE_BYTES

    from PIL import Image
    import io, math

    if not needs_convert and not over_size:
        if max_dim <= 0:
            return raw_bytes, media_type
        # Still might need dimension resize for supported formats
        img = Image.open(io.BytesIO(raw_bytes))
        if max(img.size) <= max_dim:
            return raw_bytes, media_type
    else:
        img = Image.open(io.BytesIO(raw_bytes))

    w, h = img.size

    # Apply hard dimension cap if specified
    if max_dim > 0 and max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    # Fix exotic modes
    img = _fix_mode(img)

    # Convert to JPEG (much smaller than PNG for photographic content)
    jpg_bytes = _to_jpg(img, quality=95)

    # If within limit, done
    if len(jpg_bytes) <= _MAX_IMAGE_BYTES:
        return jpg_bytes, "image/jpeg"

    # Over limit: reduce resolution, keep quality
    cur_w, cur_h = img.size
    ratio = math.sqrt(_MAX_IMAGE_BYTES / len(jpg_bytes)) * 0.92
    img = img.resize(
        (int(cur_w * ratio), int(cur_h * ratio)), Image.LANCZOS
    )
    jpg_bytes = _to_jpg(img, quality=95)

    # Safety loop
    while len(jpg_bytes) > _MAX_IMAGE_BYTES and max(img.size) > 512:
        cur_w, cur_h = img.size
        img = img.resize(
            (int(cur_w * 0.75), int(cur_h * 0.75)), Image.LANCZOS
        )
        jpg_bytes = _to_jpg(img, quality=95)

    return jpg_bytes, "image/jpeg"


async def _load_image_b64(path_or_url: str, max_dimension: int = 0) -> tuple[str, str]:
    """Load image from local path or URL, optionally resize, return (base64_data, media_type)."""
    path_or_url = path_or_url.strip()
    if path_or_url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(path_or_url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            media_type = content_type if content_type.startswith("image/") else _detect_media_type(path_or_url)
            raw_bytes = resp.content
    else:
        if not os.path.exists(path_or_url):
            raise FileNotFoundError(f"Image not found: {path_or_url}")
        media_type = _detect_media_type(path_or_url)
        with open(path_or_url, "rb") as f:
            raw_bytes = f.read()

    # Always call _resize_if_needed: it also converts unsupported formats
    # (TIFF, BMP) to JPEG, even when no resize is needed.
    raw_bytes, media_type = _resize_if_needed(raw_bytes, media_type, max_dimension)

    return base64.b64encode(raw_bytes).decode(), media_type


class AIVisionNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="ai_vision",
            label="AI Vision",
            category="ai",
            icon="Eye",
            color="#8b5cf6",
            description="Analyze images using vision-capable AI models and extract structured data",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="model",
                    label="Model",
                    type="select",
                    default="",
                    options=[],
                    description="Select a vision-capable model (GPT-4o, Claude, Gemini)",
                ),
                ConfigField(
                    name="image_column",
                    label="Image Column",
                    type="column_select",
                    required=True,
                    description="Column containing image file paths or URLs",
                ),
                ConfigField(
                    name="system_prompt",
                    label="System Prompt",
                    type="prompt_template",
                    default="You are an image analysis assistant. Return JSON only, no markdown.",
                ),
                ConfigField(
                    name="user_prompt_template",
                    label="User Prompt Template",
                    type="prompt_template",
                    required=True,
                    placeholder="Describe this image. Filename: {filename}",
                ),
                ConfigField(
                    name="json_field_mapping",
                    label="JSON Field Mapping",
                    type="json",
                    required=True,
                    description='{"ai_field": "output_column"} mapping',
                    placeholder='{"description":"image_description","tags":"image_tags"}',
                ),
                ConfigField(name="max_tokens", label="Max Tokens", type="number", default=6000),
                ConfigField(name="max_image_dimension", label="Max Image Dimension", type="number", default=0,
                            description="Resize longest side to this value (0=no resize, auto-fit API limit). "
                                        "Images are auto-converted to JPEG and fit within 18 MB API limit regardless."),
                ConfigField(name="concurrency", label="Concurrency", type="number", default=0,
                            description="Parallel requests (0=auto)"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        if df.empty:
            return {"output": df}

        model = config.get("model", "")
        if not model:
            raise ValueError("No model selected. Choose a vision-capable model in the node config.")

        image_column = config.get("image_column", "")
        if not image_column or image_column not in df.columns:
            raise ValueError(f"Image column '{image_column}' not found in data")

        system_prompt = config.get("system_prompt", "")
        template = config.get("user_prompt_template", "")
        mapping = config.get("json_field_mapping", {})
        max_tokens = int(config.get("max_tokens", 500))
        max_image_dim = int(config.get("max_image_dimension", 1536))
        raw_conc = int(config.get("concurrency", 0))
        concurrency = raw_conc if raw_conc > 0 else min(20, len(df))

        if isinstance(mapping, str):
            mapping = json.loads(mapping)

        original_columns = set(df.columns.tolist())

        for ai_field, out_col in mapping.items():
            if out_col not in df.columns:
                df[out_col] = ""

        new_columns = [c for c in df.columns if c not in original_columns]

        api_key = ""
        if context:
            provider_id = get_provider_id_for_model(model)
            api_key = context.get_api_key(provider_id)
        if not api_key:
            raise ValueError(f"No API key configured for model '{model}'. Set it in Settings.")

        total = len(df)
        completed = 0
        skipped = 0
        analyzed = 0
        sem = asyncio.Semaphore(concurrency)

        # Pre-count rows that actually have images
        def _has_image(val) -> bool:
            if pd.isna(val):
                return False
            s = str(val).strip()
            return bool(s) and s.lower() != "nan"

        rows_with_images = sum(1 for v in df[image_column] if _has_image(v))
        rows_without = total - rows_with_images

        if on_progress:
            await on_progress(
                f"Found {rows_with_images} images out of {total} rows"
                + (f" ({rows_without} rows have no image, will be skipped)" if rows_without else "")
            )

        async def process_row(i, idx, row):
            nonlocal completed, skipped, analyzed

            # Check if this row has a valid image path
            raw_val = row[image_column]
            if not _has_image(raw_val):
                skipped += 1
                completed += 1
                return

            image_path = str(raw_val).strip()

            # Build user prompt from template
            prompt = template
            for col in df.columns:
                val = str(row[col]) if pd.notna(row[col]) else ""
                prompt = prompt.replace(f"{{{col}}}", val)

            async with sem:
                try:
                    image_b64, media_type = await _load_image_b64(image_path, max_image_dim)

                    rel_path = _relative_image_path(image_path)
                    img_filename = os.path.basename(image_path)

                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "prompt",
                            "system_prompt": system_prompt[:500],
                            "user_prompt": prompt[:1000],
                            "image": f"[{media_type}, {len(image_b64)} chars b64]",
                            "image_path": rel_path,
                            "filename": img_filename,
                        })

                    text = await call_vision_llm(
                        model, system_prompt, prompt,
                        image_b64, media_type,
                        max_tokens, api_key,
                    )

                    parsed = extract_json(text)

                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "response",
                            "raw_response": text[:2000],
                            "image_path": rel_path,
                            "filename": img_filename,
                            "result": {k: str(v)[:200] for k, v in parsed.items()} if parsed else None,
                        })

                    for ai_field, out_col in mapping.items():
                        val = parsed.get(ai_field, "")
                        if isinstance(val, (list, tuple)):
                            val = ", ".join(str(v) for v in val if v)
                        val = clean_cell(val)
                        df.at[idx, out_col] = val
                except Exception as exc:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "error",
                            "error": str(exc)[:500],
                        })
                    for out_col in mapping.values():
                        df.at[idx, out_col] = ""

            analyzed += 1
            completed += 1

            if on_progress and (analyzed % 3 == 0 or completed == total):
                await on_progress(f"{analyzed}/{rows_with_images} images analyzed, {skipped} skipped")
            if context and (analyzed % 5 == 0 or completed == total):
                preview = build_data_preview(df, new_columns=new_columns, processed_rows=completed)
                preview["node_id"] = "__live__"
                preview["node_label"] = "AI Vision"
                await context.emit("node_data_preview", preview)

        tasks = [process_row(i, idx, row) for i, (idx, row) in enumerate(df.iterrows())]
        await asyncio.gather(*tasks)

        if on_progress:
            await on_progress(f"Done: {analyzed} analyzed, {skipped} skipped (no image)")

        return {"output": df}
