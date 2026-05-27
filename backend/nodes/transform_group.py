import json
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformGroupNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_group",
            label="Group By",
            category="transform",
            icon="Layers",
            color="#10b981",
            description="Group by columns and aggregate",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="group_by", label="Group By Columns", type="column_select", required=True,
                            description="Comma-separated column names"),
                ConfigField(
                    name="aggregations",
                    label="Aggregations",
                    type="json",
                    required=True,
                    description='Array of {column, function: count|first|mode|sum|min|max, output_column}',
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        group_cols = config.get("group_by", "")
        if isinstance(group_cols, str):
            group_cols = [c.strip() for c in group_cols.split(",") if c.strip()]

        aggs = config.get("aggregations", [])
        if isinstance(aggs, str):
            aggs = json.loads(aggs)

        agg_dict = {}
        rename_map = {}
        for agg in aggs:
            col = agg["column"]
            func = agg.get("function", "count")
            out_col = agg.get("output_column", f"{col}_{func}")
            if func == "mode":
                agg_dict[col] = lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else None
            else:
                agg_dict[col] = func
            rename_map[col] = out_col

        grouped = df.groupby(group_cols, dropna=False).agg(agg_dict).reset_index()
        grouped.rename(columns=rename_map, inplace=True)

        if on_progress:
            await on_progress(f"Grouped into {len(grouped)} groups")
        return {"output": grouped}
