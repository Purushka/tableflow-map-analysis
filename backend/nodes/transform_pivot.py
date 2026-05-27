import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformPivotNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_pivot",
            label="Pivot Table",
            category="transform",
            icon="Table2",
            color="#10b981",
            description="Create a pivot table from data",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="index", label="Row Index Column", type="column_select", required=True,
                            description="Column to use as row labels"),
                ConfigField(name="pivot_column", label="Pivot Column", type="column_select", required=True,
                            description="Column whose unique values become new columns"),
                ConfigField(name="value_column", label="Value Column", type="column_select", required=True,
                            description="Column to aggregate"),
                ConfigField(name="agg_func", label="Aggregation", type="select",
                            default="sum", options=["sum", "mean", "count", "min", "max", "first"]),
                ConfigField(name="fill_value", label="Fill Value", type="text",
                            default="0", description="Value for missing cells"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        index = config.get("index", "")
        pivot_col = config.get("pivot_column", "")
        value_col = config.get("value_column", "")
        agg_func = config.get("agg_func", "sum")
        fill_value = config.get("fill_value", "0")

        try:
            fill_val = float(fill_value)
        except (ValueError, TypeError):
            fill_val = fill_value

        result = pd.pivot_table(
            df,
            index=index,
            columns=pivot_col,
            values=value_col,
            aggfunc=agg_func,
            fill_value=fill_val,
        ).reset_index()

        # Flatten multi-level column names
        if hasattr(result.columns, 'levels'):
            result.columns = [str(c) if not isinstance(c, tuple) else '_'.join(str(x) for x in c) for c in result.columns]

        if on_progress:
            await on_progress(f"Pivot table: {result.shape[0]} rows × {result.shape[1]} columns")
        return {"output": result}
