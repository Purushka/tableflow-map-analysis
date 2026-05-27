import os
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "outputs")


class OutputCSVNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="output_csv",
            label="CSV Writer",
            category="output",
            icon="FileSpreadsheet",
            color="#ef4444",
            description="Export data to a CSV file",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[],
            config_fields=[
                ConfigField(name="filename", label="Filename", type="text",
                            default="output.csv", placeholder="output.csv"),
                ConfigField(name="encoding", label="Encoding", type="select",
                            default="utf-8", options=["utf-8", "utf-8-sig", "gbk", "latin-1"]),
                ConfigField(name="delimiter", label="Delimiter", type="select",
                            default=",", options=[",", ";", "\\t", "|"]),
                ConfigField(name="include_index", label="Include Index", type="boolean", default=False),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"]
        filename = config.get("filename", "output.csv")
        encoding = config.get("encoding", "utf-8")
        delimiter = config.get("delimiter", ",")
        include_index = config.get("include_index", False)

        if delimiter == "\\t":
            delimiter = "\t"

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, filename)
        df.to_csv(output_path, encoding=encoding, sep=delimiter, index=include_index)

        if on_progress:
            await on_progress(f"Exported {len(df)} rows to {filename}")
        return {}
