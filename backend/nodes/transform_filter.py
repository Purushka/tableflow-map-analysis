import re
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformFilterNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_filter",
            label="Filter",
            category="transform",
            icon="Filter",
            color="#10b981",
            description="Filter rows into matched/unmatched outputs",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[
                PortDefinition(name="matched", label="Matched"),
                PortDefinition(name="unmatched", label="Unmatched"),
            ],
            config_fields=[
                ConfigField(name="column", label="Column", type="column_select", required=True),
                ConfigField(
                    name="operator",
                    label="Operator",
                    type="select",
                    required=True,
                    options=["equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty", "regex", "greater_than", "less_than"],
                ),
                ConfigField(name="value", label="Value", type="text", default=""),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        col = config.get("column", "")
        op = config.get("operator", "equals")
        val = config.get("value", "")

        if col not in df.columns:
            return {"matched": df, "unmatched": pd.DataFrame(columns=df.columns)}

        series = df[col].astype(str).fillna("")

        if op == "equals":
            mask = series == val
        elif op == "not_equals":
            mask = series != val
        elif op == "contains":
            mask = series.str.contains(val, case=False, na=False)
        elif op == "not_contains":
            mask = ~series.str.contains(val, case=False, na=False)
        elif op == "is_empty":
            mask = (series == "") | df[col].isna()
        elif op == "is_not_empty":
            mask = (series != "") & df[col].notna()
        elif op == "regex":
            mask = series.str.match(val, na=False)
        elif op == "greater_than":
            mask = pd.to_numeric(df[col], errors="coerce") > float(val)
        elif op == "less_than":
            mask = pd.to_numeric(df[col], errors="coerce") < float(val)
        else:
            mask = pd.Series([True] * len(df))

        matched = df[mask].reset_index(drop=True)
        unmatched = df[~mask].reset_index(drop=True)

        if on_progress:
            await on_progress(f"Matched: {len(matched)}, Unmatched: {len(unmatched)}")
        return {"matched": matched, "unmatched": unmatched}
