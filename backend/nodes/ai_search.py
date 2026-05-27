"""AI Search node — RAG-enhanced enrichment with hybrid search and confidence scoring."""
import json
import asyncio

import pandas as pd
import numpy as np

from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField
from ..providers.registry import call_llm, get_provider_id_for_model
from ..search.bm25 import bm25_search
from ..search.vector import vector_search
from ..search.web import web_search
from ..search.hybrid import reciprocal_rank_fusion
from ..engine.context import build_data_preview
from .llm_utils import extract_json, clean_cell

_DEFAULT_SYSTEM_PROMPT = (
    "You are a research assistant. Based on the search results provided, "
    "answer the question accurately. Return JSON only:\n"
    '{"answer": "your answer here", "confidence": 85}\n'
    "confidence is 0-100 indicating how confident you are in the answer. "
    "If the search results don't contain relevant information, set confidence to 0."
)


class AISearchNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="ai_search",
            label="AI Search",
            category="ai",
            icon="SearchCheck",
            color="#8b5cf6",
            description="RAG-enhanced enrichment — search + AI with confidence scoring",
            inputs=[
                PortDefinition(name="input", label="Data"),
                PortDefinition(name="knowledge", label="Knowledge Base"),
            ],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="model", label="Model", type="select",
                    default="", options=[],
                    description="Select an AI model (configure API key in Settings first)",
                ),
                ConfigField(
                    name="query_template", label="Query Template", type="prompt_template",
                    required=True,
                    placeholder="What is the capital city of {Country}?",
                    description="Search query template. Use {COLUMN} placeholders.",
                ),
                ConfigField(
                    name="use_knowledge_base", label="Search Knowledge Base", type="boolean",
                    default=True,
                    description="Search the connected knowledge base DataFrame",
                ),
                ConfigField(
                    name="knowledge_columns", label="Knowledge Columns", type="text",
                    default="",
                    placeholder="col1, col2",
                    description="Columns to search in the knowledge base (comma-separated, empty = all)",
                ),
                ConfigField(
                    name="use_web_search", label="Enable Web Search", type="boolean",
                    default=False,
                ),
                ConfigField(
                    name="web_search_provider", label="Web Search Provider", type="select",
                    default="tavily",
                    options=["tavily", "google", "bing", "serpapi"],
                ),
                ConfigField(
                    name="web_search_api_key", label="Web Search API Key", type="text",
                    default="",
                    placeholder="Enter web search API key",
                ),
                ConfigField(
                    name="top_k", label="Top-K Results", type="number",
                    default=5,
                    description="Number of search results to send to the LLM",
                ),
                ConfigField(
                    name="system_prompt", label="System Prompt", type="prompt_template",
                    default=_DEFAULT_SYSTEM_PROMPT,
                ),
                ConfigField(
                    name="max_tokens", label="Max Tokens", type="number",
                    default=500,
                ),
                ConfigField(
                    name="output_column", label="Answer Column", type="text",
                    default="ai_answer",
                ),
                ConfigField(
                    name="confidence_column", label="Confidence Column", type="text",
                    default="ai_confidence",
                ),
                ConfigField(
                    name="confidence_threshold", label="Confidence Threshold", type="number",
                    default=70,
                    description="Minimum confidence (0-100) to fill the answer column",
                ),
                ConfigField(
                    name="concurrency", label="Concurrency", type="number", default=0,
                    description="Parallel LLM requests (0=auto, matches row count)",
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
        use_kb = config.get("use_knowledge_base", True)
        kb_columns_raw = config.get("knowledge_columns", "")
        use_web = config.get("use_web_search", False)
        web_provider = config.get("web_search_provider", "tavily")
        web_api_key = config.get("web_search_api_key", "")
        top_k = int(config.get("top_k", 5))
        system_prompt = config.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        max_tokens = int(config.get("max_tokens", 500))
        output_col = config.get("output_column", "ai_answer")
        confidence_col = config.get("confidence_column", "ai_confidence")
        threshold = float(config.get("confidence_threshold", 70))
        raw_conc = int(config.get("concurrency", 0))
        concurrency = raw_conc if raw_conc > 0 else min(10, len(df))

        # Get LLM API key from context
        api_key = ""
        if context:
            provider_id = get_provider_id_for_model(model)
            api_key = context.get_api_key(provider_id)
        if not api_key:
            raise ValueError(f"No API key configured for model '{model}'. Set it in Settings.")

        # Knowledge base DataFrame (optional second input)
        kb_df = inputs.get("knowledge")
        if kb_df is None or (isinstance(kb_df, pd.DataFrame) and kb_df.empty):
            use_kb = False

        # Parse knowledge columns
        kb_columns: list[str] = []
        if use_kb and kb_df is not None:
            if kb_columns_raw.strip():
                kb_columns = [c.strip() for c in kb_columns_raw.split(",") if c.strip()]
            else:
                kb_columns = list(kb_df.columns)

        # Initialize output columns
        original_columns = set(df.columns.tolist())
        if output_col not in df.columns:
            df[output_col] = ""
        if confidence_col not in df.columns:
            df[confidence_col] = np.nan
        new_columns = [c for c in df.columns if c not in original_columns]

        # Pre-compute knowledge base embeddings (once, reused by all rows)
        cached_embeddings = None
        cached_corpus = None
        if use_kb and kb_df is not None:
            try:
                _, cached_embeddings, cached_corpus = vector_search(
                    "warmup", kb_df, kb_columns, top_k=1,
                    doc_embeddings=None, corpus_texts=None,
                )
            except Exception:
                pass  # Vector search unavailable, will fall back to BM25 only

        total = len(df)
        completed = 0
        sem = asyncio.Semaphore(concurrency)

        async def process_row(i, idx, row):
            nonlocal completed

            # 1. Build query from template
            query = query_template
            for col in df.columns:
                val = str(row[col]) if pd.notna(row[col]) else ""
                query = query.replace(f"{{{col}}}", val)

            # 2. Search all enabled sources
            all_result_lists = []

            if use_kb and kb_df is not None:
                # BM25 keyword search (fast, sync)
                bm25_results = bm25_search(query, kb_df, kb_columns, top_k=top_k)
                all_result_lists.append(bm25_results)

                # Vector semantic search (using pre-computed cache)
                if cached_embeddings is not None:
                    vec_results, _, _ = vector_search(
                        query, kb_df, kb_columns, top_k=top_k,
                        doc_embeddings=cached_embeddings,
                        corpus_texts=cached_corpus,
                    )
                    all_result_lists.append(vec_results)

            if use_web and web_api_key:
                try:
                    web_results = await web_search(query, web_provider, web_api_key, top_k=top_k)
                    all_result_lists.append(web_results)
                except Exception:
                    pass  # Web search failure shouldn't break the pipeline

            # 3. RRF fusion
            if all_result_lists:
                fused = reciprocal_rank_fusion(*all_result_lists, top_k=top_k)
            else:
                fused = []

            # 4. Build LLM context from search results
            if fused:
                context_parts = []
                for r in fused:
                    src = r.metadata.get("url", r.source)
                    context_parts.append(f"[{r.rank}] ({src}) {r.text}")
                search_context = "\n\n".join(context_parts)
            else:
                search_context = "(No search results found)"

            user_prompt = f"Question: {query}\n\nSearch Results:\n{search_context}\n\nAnswer in JSON format."

            # 5. Call LLM (gated by semaphore)
            async with sem:
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
                    answer = parsed.get("answer", "")
                    confidence = float(parsed.get("confidence", 0))

                    # 6. Apply confidence threshold
                    df.at[idx, confidence_col] = confidence
                    if confidence >= threshold:
                        df.at[idx, output_col] = clean_cell(answer)
                    else:
                        df.at[idx, output_col] = ""
                except Exception as exc:
                    if context:
                        await context.emit("ai_debug", {
                            "row": i + 1, "total": total, "phase": "error",
                            "error": str(exc)[:500],
                        })
                    df.at[idx, output_col] = ""
                    df.at[idx, confidence_col] = 0.0

            completed += 1

            if on_progress and (completed % 5 == 0 or completed == total):
                await on_progress(f"{completed}/{total} rows searched")
            if context and (completed % 10 == 0 or completed == total):
                preview = build_data_preview(df, new_columns=new_columns, processed_rows=completed)
                preview["node_id"] = "__live__"
                preview["node_label"] = "AI Search"
                await context.emit("node_data_preview", preview)

        tasks = [process_row(i, idx, row) for i, (idx, row) in enumerate(df.iterrows())]
        await asyncio.gather(*tasks)

        return {"output": df}
