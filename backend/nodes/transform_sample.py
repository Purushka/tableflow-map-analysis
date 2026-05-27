import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformSampleNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_sample",
            label="Sample",
            category="transform",
            icon="Shuffle",
            color="#10b981",
            description="Random sample of rows",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Sampled")],
            config_fields=[
                ConfigField(name="mode", label="Mode", type="select",
                            default="count", options=["count", "percent"]),
                ConfigField(name="count", label="Sample Size", type="number",
                            default=100, description="Number of rows (count mode)"),
                ConfigField(name="percent", label="Percentage", type="number",
                            default=10, description="Percentage of rows (percent mode)"),
                ConfigField(name="seed", label="Random Seed", type="number",
                            description="For reproducible sampling (optional)"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        mode = config.get("mode", "count")
        seed = config.get("seed")
        seed = int(seed) if seed else None

        if mode == "percent":
            pct = float(config.get("percent", 10))
            frac = min(pct / 100.0, 1.0)
            result = df.sample(frac=frac, random_state=seed).reset_index(drop=True)
        else:
            n = min(int(config.get("count", 100)), len(df))
            result = df.sample(n=n, random_state=seed).reset_index(drop=True) if n > 0 else df.head(0)

        if on_progress:
            await on_progress(f"Sampled {len(result)} of {len(df)} rows")
        return {"output": result}
