import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformDeduplicateNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_deduplicate",
            label="Deduplicate",
            category="transform",
            icon="Copy",
            color="#10b981",
            description="Remove duplicate rows based on columns",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[
                PortDefinition(name="unique", label="Unique"),
                PortDefinition(name="duplicates", label="Duplicates"),
            ],
            config_fields=[
                ConfigField(name="columns", label="Key Columns (comma-separated)", type="text",
                            required=True, description="Leave empty to use all columns",
                            placeholder="col1,col2"),
                ConfigField(name="keep", label="Keep", type="select",
                            default="first", options=["first", "last", "none"],
                            description="Which duplicate to keep"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        cols_str = config.get("columns", "").strip()
        keep = config.get("keep", "first")

        subset = [c.strip() for c in cols_str.split(",") if c.strip()] if cols_str else None

        # keep="none" in pandas means drop ALL duplicates
        keep_param = keep if keep != "none" else False

        mask = df.duplicated(subset=subset, keep=keep_param)
        unique_df = df[~mask].reset_index(drop=True)
        dup_df = df[mask].reset_index(drop=True)

        if on_progress:
            await on_progress(f"Found {len(dup_df)} duplicates, kept {len(unique_df)} unique rows")
        return {"unique": unique_df, "duplicates": dup_df}
