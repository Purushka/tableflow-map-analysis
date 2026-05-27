import asyncio
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField
from ..providers.registry import call_llm, get_provider_id_for_model
from ..engine.context import build_data_preview
from .llm_utils import clean_cell


class AIClassifyNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="ai_classify",
            label="AI Classify",
            category="ai",
            icon="Tags",
            color="#8b5cf6",
            description="Single-label classification using AI",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="model", label="Model", type="select",
                            default="",
                            options=[],  # Populated dynamically by frontend
                            description="Select an AI model (configure API key in Settings first)"),
                ConfigField(name="prompt_template", label="Prompt Template", type="prompt_template",
                            required=True, placeholder="Classify this item: {Title}"),
                ConfigField(name="labels", label="Labels (comma-separated)", type="text",
                            required=True, placeholder="topographic,nautical,geological,political"),
                ConfigField(name="output_column", label="Output Column", type="text",
                            required=True, default="classification"),
                ConfigField(name="concurrency", label="Concurrency", type="number", default=0,
                            description="Parallel LLM requests (0=auto, matches row count)"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        if df.empty:
            return {"output": df}

        model = config.get("model", "")
        if not model:
            raise ValueError("No model selected. Choose a model in the node config.")

        template = config.get("prompt_template", "")
        labels = [l.strip() for l in config.get("labels", "").split(",") if l.strip()]
        out_col = config.get("output_column", "classification")
        raw_conc = int(config.get("concurrency", 0))
        concurrency = raw_conc if raw_conc > 0 else min(10, len(df))

        # Get API key from context
        api_key = ""
        if context:
            provider_id = get_provider_id_for_model(model)
            api_key = context.get_api_key(provider_id)
        if not api_key:
            raise ValueError(f"No API key configured for model '{model}'. Set it in Settings.")

        original_columns = set(df.columns.tolist())
        df[out_col] = ""
        new_columns = [c for c in df.columns if c not in original_columns]

        total = len(df)
        system = f"Classify into exactly one label: {', '.join(labels)}. Reply with ONLY the label."
        completed = 0
        sem = asyncio.Semaphore(concurrency)

        async def process_row(i, idx, row):
            nonlocal completed
            prompt = template
            for col in df.columns:
                val = str(row[col]) if pd.notna(row[col]) else ""
                prompt = prompt.replace(f"{{{col}}}", val)

            async with sem:
                try:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "prompt",
                            "system_prompt": system[:500],
                            "user_prompt": prompt[:1000],
                        })

                    text = await call_llm(model, system, prompt, 50, api_key)

                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "response",
                            "raw_response": text[:2000],
                        })

                    label = clean_cell(text).lower()
                    matched = next((l for l in labels if l.lower() == label), label)
                    df.at[idx, out_col] = matched
                except Exception as exc:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "error",
                            "error": str(exc)[:500],
                        })
                    df.at[idx, out_col] = ""

            completed += 1

            if on_progress and (completed % 5 == 0 or completed == total):
                await on_progress(f"{completed}/{total} classified")
            if context and (completed % 10 == 0 or completed == total):
                preview = build_data_preview(df, new_columns=new_columns, processed_rows=completed)
                preview["node_id"] = "__live__"
                preview["node_label"] = "AI Classify"
                await context.emit("node_data_preview", preview)

        tasks = [process_row(i, idx, row) for i, (idx, row) in enumerate(df.iterrows())]
        await asyncio.gather(*tasks)

        return {"output": df}
