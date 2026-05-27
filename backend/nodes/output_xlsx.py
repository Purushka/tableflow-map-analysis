import os
import json
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "storage", "outputs")


class OutputXLSXNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="output_xlsx",
            label="Excel Output",
            category="output",
            icon="FileDown",
            color="#ef4444",
            description="Export data to Excel (.xlsx)",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[],
            config_fields=[
                ConfigField(name="filename", label="Filename", type="text",
                            required=True, default="output.xlsx"),
                ConfigField(name="sheet_name", label="Sheet Name", type="text", default="Sheet1"),
                ConfigField(name="columns", label="Columns (rename/order)", type="json",
                            description='[{"source":"col_name","label":"Display Name"}] or empty for all'),
                ConfigField(name="freeze_top_row", label="Freeze Top Row", type="boolean", default=True),
                ConfigField(name="auto_filter", label="Auto Filter", type="boolean", default=True),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        filename = config.get("filename", "output.xlsx")
        sheet = config.get("sheet_name", "Sheet1")
        columns_cfg = config.get("columns", None)
        freeze = config.get("freeze_top_row", True)
        auto_filter = config.get("auto_filter", True)

        if columns_cfg:
            if isinstance(columns_cfg, str):
                columns_cfg = json.loads(columns_cfg)
            if columns_cfg:
                source_cols = [c["source"] for c in columns_cfg if c["source"] in df.columns]
                rename_map = {c["source"]: c.get("label", c["source"]) for c in columns_cfg if c["source"] in df.columns}
                df = df[source_cols].rename(columns=rename_map)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filepath = os.path.join(OUTPUT_DIR, filename)

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet, index=False)
            ws = writer.sheets[sheet]
            if freeze:
                ws.freeze_panes = "A2"
            if auto_filter and len(df) > 0:
                ws.auto_filter.ref = ws.dimensions

        if on_progress:
            await on_progress(f"Exported {len(df)} rows to {filename}")
        return {}
