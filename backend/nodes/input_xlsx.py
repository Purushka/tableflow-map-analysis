import os
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField

STORAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage", "uploads"))


class InputXLSXNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="input_xlsx",
            label="Excel Input",
            category="input",
            icon="FileSpreadsheet",
            color="#3b82f6",
            description="Load data from an Excel file",
            inputs=[],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="file_id", label="File", type="file", required=True),
                ConfigField(name="sheet_name", label="Sheet", type="text", default="0", placeholder="Sheet name or index"),
                ConfigField(name="header_row", label="Header Row", type="number", default=0),
                ConfigField(name="max_rows", label="Max Rows (0=all)", type="number", default=0,
                            description="Limit rows to load. 0 = load all"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        file_id = config.get("file_id", "")
        sheet = config.get("sheet_name", "0")
        header_row = int(config.get("header_row", 0))

        filepath = os.path.join(STORAGE_DIR, file_id)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {file_id}")

        try:
            sheet = int(sheet)
        except ValueError:
            pass

        df = pd.read_excel(filepath, sheet_name=sheet, header=header_row)
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
