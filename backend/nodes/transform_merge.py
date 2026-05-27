import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformMergeNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_merge",
            label="Merge",
            category="transform",
            icon="Merge",
            color="#10b981",
            description="Join two tables on matching columns",
            inputs=[
                PortDefinition(name="left", label="Left"),
                PortDefinition(name="right", label="Right"),
            ],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="left_key", label="Left Key", type="column_select", required=True),
                ConfigField(name="right_key", label="Right Key", type="column_select", required=True),
                ConfigField(
                    name="how",
                    label="Join Type",
                    type="select",
                    default="left",
                    options=["left", "right", "inner", "outer"],
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        left = inputs.get("left")
        right = inputs.get("right")
        if left is None or right is None:
            raise ValueError("Merge requires both left and right inputs")

        left_key = config.get("left_key", "")
        right_key = config.get("right_key", "")
        how = config.get("how", "left")

        df = pd.merge(left, right, left_on=left_key, right_on=right_key, how=how, suffixes=("", "_right"))

        if on_progress:
            await on_progress(f"Merged: {len(df)} rows ({how} join)")
        return {"output": df}
