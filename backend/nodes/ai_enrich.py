import json
import asyncio
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField
from ..providers.registry import call_llm, get_provider_id_for_model
from ..engine.context import build_data_preview
from .llm_utils import extract_json, clean_cell


class AIEnrichNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="ai_enrich",
            label="AI Enrich",
            category="ai",
            icon="Sparkles",
            color="#8b5cf6",
            description="LLM batch enrichment — extract structured data from each row",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="model",
                    label="Model",
                    type="select",
                    default="",
                    options=[],  # Populated dynamically by frontend from /api/providers/models
                    description="Select an AI model (configure API key in Settings first)",
                ),
                ConfigField(name="system_prompt", label="System Prompt", type="prompt_template",
                            default="You are a data extraction assistant. Return JSON only, no markdown."),
                ConfigField(name="user_prompt_template", label="User Prompt Template", type="prompt_template",
                            required=True, placeholder="Title: {TITLE}\nPublisher: {Publisher}"),
                ConfigField(name="json_field_mapping", label="JSON Field Mapping", type="json",
                            required=True,
                            description='{"ai_field": "output_column"} mapping',
                            placeholder='{"continent":"geo_continent","country":"geo_country"}'),
                ConfigField(name="max_tokens", label="Max Tokens", type="number", default=300),
                ConfigField(name="concurrency", label="Concurrency", type="number", default=0,
                            description="Parallel LLM requests (0=auto, matches row count)"),
                ConfigField(name="batch_mode", label="Batch Mode", type="boolean", default=True,
                            description="Group multiple rows per LLM call to reduce cost (recommended)"),
                ConfigField(name="batch_size", label="Batch Size", type="number", default=5,
                            description="Rows per LLM call when batch mode is on"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        if df.empty:
            return {"output": df}

        model = config.get("model", "")
        if not model:
            raise ValueError("No model selected. Choose a model in the node config.")

        system_prompt = config.get("system_prompt", "")
        template = config.get("user_prompt_template", "")
        mapping = config.get("json_field_mapping", {})
        max_tokens = int(config.get("max_tokens", 300))
        raw_conc = int(config.get("concurrency", 0))
        concurrency = raw_conc if raw_conc > 0 else min(10, len(df))
        batch_mode = config.get("batch_mode", True)
        batch_size = max(1, int(config.get("batch_size", 5)))

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
        sem = asyncio.Semaphore(concurrency)

        def _build_prompt(row):
            prompt = template
            for col in df.columns:
                val = str(row[col]) if pd.notna(row[col]) else ""
                prompt = prompt.replace(f"{{{col}}}", val)
            return prompt

        def _apply_parsed(idx, parsed):
            for ai_field, out_col in mapping.items():
                val = parsed.get(ai_field, "")
                if isinstance(val, (list, tuple)):
                    val = ", ".join(str(v) for v in val if v)
                val = clean_cell(val)
                df.at[idx, out_col] = val

        async def _progress_update():
            if on_progress and (completed % max(5, batch_size) == 0 or completed == total):
                await on_progress(f"{completed}/{total} rows processed")
            if context and (completed % max(10, batch_size * 2) == 0 or completed == total):
                preview = build_data_preview(df, new_columns=new_columns, processed_rows=completed)
                preview["node_id"] = "__live__"
                preview["node_label"] = "AI Enrich"
                await context.emit("node_data_preview", preview)

        if not batch_mode or batch_size <= 1:
            # ── Single-row mode ──
            async def process_row(i, idx, row):
                nonlocal completed
                prompt = _build_prompt(row)
                async with sem:
                    try:
                        if context:
                            await context.emit("ai_debug", {
                                "row": i + 1, "total": total, "phase": "prompt",
                                "system_prompt": system_prompt[:500],
                                "user_prompt": prompt[:1000],
                            })
                        text = await call_llm(model, system_prompt, prompt, max_tokens, api_key)
                        if context:
                            await context.emit("ai_debug", {
                                "row": i + 1, "total": total, "phase": "response",
                                "raw_response": text[:2000],
                            })
                        _apply_parsed(idx, extract_json(text))
                    except Exception as exc:
                        if context:
                            await context.emit("ai_debug", {
                                "row": i + 1, "total": total, "phase": "error",
                                "error": str(exc)[:500],
                            })
                        for out_col in mapping.values():
                            df.at[idx, out_col] = ""
                completed += 1
                await _progress_update()

            tasks = [process_row(i, idx, row) for i, (idx, row) in enumerate(df.iterrows())]
            await asyncio.gather(*tasks)
        else:
            # ── Batch mode: group rows per LLM call ──
            batch_system = (
                system_prompt + "\n\n"
                "IMPORTANT: You will receive MULTIPLE items in one request. "
                "Return results for ALL items in order.\n"
                'Format: {"results": [{"index": 0, ...fields...}, {"index": 1, ...fields...}, ...]}'
            )

            # Pre-build all row data
            row_data = [(i, idx, row, _build_prompt(row)) for i, (idx, row) in enumerate(df.iterrows())]
            batches = [row_data[i:i + batch_size] for i in range(0, len(row_data), batch_size)]

            async def process_batch(batch):
                nonlocal completed
                prompt_parts = []
                for bi, (i, idx, row, prompt) in enumerate(batch):
                    prompt_parts.append(f"=== Item {bi} ===\n{prompt}")
                combined = "\n\n".join(prompt_parts)
                batch_max_tokens = max_tokens * len(batch)

                async with sem:
                    try:
                        if context:
                            await context.emit("ai_debug", {
                                "row": batch[0][0] + 1, "total": total, "phase": "prompt",
                                "system_prompt": batch_system[:500],
                                "user_prompt": f"[Batch of {len(batch)}]\n{combined[:1500]}",
                            })
                        text = await call_llm(model, batch_system, combined, batch_max_tokens, api_key)
                        parsed = extract_json(text)
                        results = parsed.get("results", [])

                        # Map results by index
                        result_map = {}
                        for r in results:
                            ri = int(r.get("index", -1))
                            if 0 <= ri < len(batch):
                                result_map[ri] = r

                        for bi, (i, idx, row, prompt) in enumerate(batch):
                            item_result = result_map.get(bi, {})
                            _apply_parsed(idx, item_result)
                            if context:
                                await context.emit("ai_debug", {
                                    "row": i + 1, "total": total, "phase": "response",
                                    "raw_response": json.dumps(item_result, ensure_ascii=False)[:500],
                                })

                    except Exception as exc:
                        if context:
                            await context.emit("ai_debug", {
                                "row": batch[0][0] + 1, "total": total, "phase": "error",
                                "error": f"Batch error: {str(exc)[:500]}",
                            })
                        for _, idx, _, _ in batch:
                            for out_col in mapping.values():
                                df.at[idx, out_col] = ""

                completed += len(batch)
                await _progress_update()

            tasks = [process_batch(b) for b in batches]
            await asyncio.gather(*tasks)

        return {"output": df}
