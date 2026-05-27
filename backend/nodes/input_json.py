import json
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField

# File storage path
import os
STORAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "uploads"))


class InputJSONNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="input_json",
            label="JSON Reader",
            category="input",
            icon="Braces",
            color="#3b82f6",
            description="Load data from a JSON file",
            inputs=[],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="file_id", label="File", type="file", required=True),
                ConfigField(name="json_path", label="JSON Path", type="text",
                            description="Dot-path to array, e.g. data.items (leave empty for root)",
                            placeholder="data.items"),
                ConfigField(name="orient", label="Format", type="select",
                            default="records", options=["records", "columns", "auto"],
                            description="JSON structure: records=[{...},...], columns={col:[...],...}"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        file_id = config.get("file_id", "")
        json_path = config.get("json_path", "").strip()
        orient = config.get("orient", "auto")

        file_path = os.path.join(STORAGE_DIR, file_id)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Navigate to nested path
        if json_path:
            for key in json_path.split("."):
                if isinstance(data, dict):
                    data = data[key]
                elif isinstance(data, list) and key.isdigit():
                    data = data[int(key)]

        # Convert to DataFrame
        if orient == "auto":
            if isinstance(data, list):
                df = pd.DataFrame(data)
            elif isinstance(data, dict):
                # Try columns format first, fall back to wrapping
                try:
                    df = pd.DataFrame(data)
                except ValueError:
                    df = pd.DataFrame([data])
            else:
                df = pd.DataFrame([{"value": data}])
        elif orient == "records":
            df = pd.DataFrame(data)
        elif orient == "columns":
            df = pd.DataFrame(data)
        else:
            df = pd.DataFrame(data)

        if on_progress:
            await on_progress(f"Loaded {len(df)} rows from JSON")
        return {"output": df}
