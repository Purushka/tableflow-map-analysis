import os
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField

STORAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage", "uploads"))


class InputCSVNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="input_csv",
            label="CSV Input",
            category="input",
            icon="FileSpreadsheet",
            color="#3b82f6",
            description="Load data from a CSV file",
            inputs=[],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="file_id", label="File", type="file", required=True),
                ConfigField(
                    name="encoding",
                    label="Encoding",
                    type="select",
                    default="utf-8-sig",
                    options=["utf-8-sig", "utf-8", "latin-1", "gbk", "shift-jis"],
                ),
                ConfigField(
                    name="delimiter",
                    label="Delimiter",
                    type="select",
                    default=",",
                    options=[",", ";", "\t", "|"],
                ),
                ConfigField(name="max_rows", label="Max Rows (0=all)", type="number", default=0,
                            description="Limit rows to load. 0 = load all"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        file_id = config.get("file_id", "")
        encoding = config.get("encoding", "utf-8-sig")
        delimiter = config.get("delimiter", ",")

        filepath = os.path.join(STORAGE_DIR, file_id)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {file_id}")

        df = pd.read_csv(filepath, encoding=encoding, delimiter=delimiter)
        raw_count = len(df)
        df = df.dropna(how='all').reset_index(drop=True)

        max_rows = int(config.get("max_rows", 0))
        if max_rows > 0:
            df = df.head(max_rows)

        if on_progress:
            msg = f"Loaded {len(df)} rows, {len(df.columns)} columns"
            if raw_count != len(df):
                msg += f" (filtered from {raw_count})"
            await on_progress(msg)
        return {"output": df}
