"""AI AutoFill node — web search + AI extraction to fill missing table cells."""
import json
import asyncio

import pandas as pd

from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField
from ..providers.registry import call_llm, get_provider_id_for_model
from ..search.web import web_search
from ..engine.context import build_data_preview
from .llm_utils import extract_json, clean_cell

_DEFAULT_SYSTEM_PROMPT = (
    "You are a data research assistant. Based on the search results provided, "
    "extract the requested fields. Return JSON only, no markdown fences.\n"
    "For each field, provide the best value you can find. "
    'If a field cannot be determined from the search results, use "" (empty string).\n'
    "Include a confidence score (0-100) for each field.\n"
    "Response format:\n"
    '{"fields": {"FieldName": "value", ...}, '
    '"confidence": {"FieldName": 85, ...}}'
)


class AIAutoFillNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="ai_autofill",
            label="AI AutoFill",
            category="ai",
            icon="WandSparkles",
            color="#8b5cf6",
            description="Auto-fill missing data by searching the web and extracting values with AI",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="model", label="Model", type="select",
                    default="", options=[],
                    description="Select an AI model (configure API key in Settings first)",
                ),
                ConfigField(
                    name="query_template", label="Search Query Template",
                    type="prompt_template", required=True,
                    placeholder="{TITLE} {Date Published} map catalogue",
                    description="Web search query. Use {COLUMN} placeholders.",
                ),
                ConfigField(
                    name="fields_to_fill", label="Fields to Fill",
                    type="json", required=True,
                    description='Array of {column, description} for each field to auto-fill',
                    placeholder='[{"column":"Author","description":"Map author or cartographer"}]',
                ),
                ConfigField(
                    name="only_fill_empty", label="Only Fill Empty Cells",
                    type="boolean", default=True,
                    description="Skip cells that already have a value",
                ),
                ConfigField(
                    name="web_search_provider", label="Web Search Provider",
                    type="select", default="tavily",
                    options=["tavily", "google", "bing", "serpapi"],
                ),
                ConfigField(
                    name="web_search_api_key", label="Web Search API Key",
                    type="text", default="",
                    placeholder="Enter web search API key",
                ),
                ConfigField(
                    name="top_k", label="Top-K Search Results",
                    type="number", default=5,
                    description="Number of web search results to feed to AI",
                ),
                ConfigField(
                    name="max_tokens", label="Max Tokens",
                    type="number", default=800,
                ),
                ConfigField(
                    name="confidence_threshold", label="Confidence Threshold",
                    type="number", default=50,
                    description="Minimum confidence (0-100) to accept a filled value",
                ),
                ConfigField(
                    name="system_prompt", label="System Prompt",
                    type="prompt_template",
                    default=_DEFAULT_SYSTEM_PROMPT,
                ),
                ConfigField(
                    name="concurrency", label="Concurrency", type="number", default=0,
                    description="Parallel requests (0=auto, matches row count)",
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        if df.empty:
            return {"output": df}

        model = config.get("model", "")
        if not model:
            raise ValueError("No model selected. Choose a model in the node config.")

        query_template = config.get("query_template", "")
        fields_raw = config.get("fields_to_fill", [])
        if isinstance(fields_raw, str):
            fields_raw = json.loads(fields_raw)

        only_fill_empty = config.get("only_fill_empty", True)
        web_provider = config.get("web_search_provider", "tavily")
        web_api_key = config.get("web_search_api_key", "")
        top_k = int(config.get("top_k", 5))
        max_tokens = int(config.get("max_tokens", 800))
        threshold = float(config.get("confidence_threshold", 50))
        system_prompt = config.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        raw_conc = int(config.get("concurrency", 0))
        concurrency = raw_conc if raw_conc > 0 else min(10, len(df))

        # Validate fields_to_fill
        fields_to_fill = []
        for f in fields_raw:
            col = f.get("column", "")
            desc = f.get("description", col)
            if col:
                fields_to_fill.append({"column": col, "description": desc})

        if not fields_to_fill:
            raise ValueError("No fields to fill configured. Add at least one field.")

        if not web_api_key:
            raise ValueError("Web search API key is required for AutoFill.")

        # Get LLM API key
        api_key = ""
        if context:
            provider_id = get_provider_id_for_model(model)
            api_key = context.get_api_key(provider_id)
        if not api_key:
            raise ValueError(f"No API key configured for model '{model}'. Set it in Settings.")

        # Ensure target columns exist
        original_columns = set(df.columns.tolist())
        for f in fields_to_fill:
            if f["column"] not in df.columns:
                df[f["column"]] = ""
        new_columns = [c for c in df.columns if c not in original_columns]

        total = len(df)
        filled_count = 0
        skipped_count = 0
        completed = 0
        sem = asyncio.Semaphore(concurrency)

        async def process_row(i, idx, row):
            nonlocal completed, filled_count, skipped_count

            # 1. Determine which fields need filling
            if only_fill_empty:
                missing = [
                    f for f in fields_to_fill
                    if pd.isna(row.get(f["column"])) or str(row.get(f["column"], "")).strip() == ""
                ]
            else:
                missing = list(fields_to_fill)

            if not missing:
                skipped_count += 1
                completed += 1
                if on_progress and (completed % 5 == 0 or completed == total):
                    await on_progress(f"{completed}/{total} | {filled_count} filled | {skipped_count} complete")
                if context and (completed % 10 == 0 or completed == total):
                    preview = build_data_preview(df, new_columns=new_columns, processed_rows=completed)
                    preview["node_id"] = "__live__"
                    preview["node_label"] = "AI AutoFill"
                    await context.emit("node_data_preview", preview)
                return

            # 2. Build search query
            query = query_template
            for col in df.columns:
                val = str(row[col]) if pd.notna(row[col]) else ""
                query = query.replace(f"{{{col}}}", val)
            query = query.strip()

            async with sem:
                # 3. Web search
                search_results = []
                try:
                    search_results = await web_search(query, web_provider, web_api_key, top_k=top_k)
                except Exception:
                    pass

                # 4. Build LLM prompt
                if search_results:
                    context_parts = []
                    for r in search_results:
                        src = r.metadata.get("url", r.source)
                        context_parts.append(f"[{r.rank}] ({src}) {r.text}")
                    search_context = "\n\n".join(context_parts)
                else:
                    search_context = "(No search results found)"

                fields_desc = "\n".join(
                    f"- {f['column']}: {f['description']}" for f in missing
                )

                # Include existing row data for context
                row_parts = []
                for col in df.columns:
                    val = str(row[col]) if pd.notna(row[col]) else ""
                    if val:
                        row_parts.append(f"{col}: {val[:200]}")
                row_context = "\n".join(row_parts[:15])  # limit to 15 fields

                user_prompt = (
                    f"Known data about this item:\n{row_context}\n\n"
                    f"Fields to extract (only these):\n{fields_desc}\n\n"
                    f"Search Results:\n{search_context}\n\n"
                    f"Extract the requested fields from the search results. Return JSON only."
                )

                # 5. Call LLM
                try:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "prompt",
                            "system_prompt": system_prompt[:500],
                            "user_prompt": user_prompt[:1000],
                        })

                    text = await call_llm(model, system_prompt, user_prompt, max_tokens, api_key)

                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "response",
                            "raw_response": text[:2000],
                        })

                    parsed = extract_json(text)
                    field_values = parsed.get("fields", parsed)
                    confidences = parsed.get("confidence", {})

                    for f in missing:
                        col = f["column"]
                        val = field_values.get(col, "")
                        conf = float(confidences.get(col, 100))
                        if val and str(val).strip() and conf >= threshold:
                            df.at[idx, col] = clean_cell(val)
                            filled_count += 1
                except Exception as exc:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "error",
                            "error": str(exc)[:500],
                        })

            completed += 1

            # 6. Progress + live preview
            if on_progress and (completed % 5 == 0 or completed == total):
                await on_progress(f"{completed}/{total} | {filled_count} filled | {skipped_count} complete")
            if context and (completed % 10 == 0 or completed == total):
                preview = build_data_preview(df, new_columns=new_columns, processed_rows=completed)
                preview["node_id"] = "__live__"
                preview["node_label"] = "AI AutoFill"
                await context.emit("node_data_preview", preview)

        tasks = [process_row(i, idx, row) for i, (idx, row) in enumerate(df.iterrows())]
        await asyncio.gather(*tasks)

        if on_progress:
            await on_progress(f"Done: {filled_count} cells filled across {total} rows")
        return {"output": df}
