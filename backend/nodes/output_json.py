import os
import json
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "storage", "outputs")


class OutputJSONNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="output_json",
            label="JSON Output",
            category="output",
            icon="FileJson",
            color="#ef4444",
            description="Export data to JSON",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[],
            config_fields=[
                ConfigField(name="filename", label="Filename", type="text",
                            required=True, default="output.json"),
                ConfigField(name="orient", label="Orientation", type="select",
                            default="records", options=["records", "columns"]),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        filename = config.get("filename", "output.json")
        orient = config.get("orient", "records")

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filepath = os.path.join(OUTPUT_DIR, filename)

        data = df.to_dict(orient=orient)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        if on_progress:
            await on_progress(f"Exported {len(df)} rows to {filename}")
        return {}
