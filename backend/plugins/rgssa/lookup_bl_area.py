import re
import pandas as pd
from backend.nodes.base import BaseNode, NodeDefinition, PortDefinition, ConfigField


def _safe_str(val) -> str:
    """Safely convert any value to string, handling arrays/lists/nan."""
    if val is None:
        return ""
    try:
        if isinstance(val, (list, tuple)):
            return " ".join(str(v) for v in val)
        if hasattr(val, '__iter__') and not isinstance(val, str):
            # numpy array or pandas Series
            return " ".join(str(v) for v in val)
        if pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    return str(val).strip()


class LookupBLAreaNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="lookup_bl_area",
            label="B-L Area Match",
            category="lookup",
            icon="MapPin",
            color="#f59e0b",
            description="Match Boggs-Lewis area code from geographic fields",
            plugin="rgssa",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="geo_columns", label="Geo Columns (comma-separated)", type="text",
                            required=True, default="geo_city,geo_feature,geo_state,geo_country",
                            description="Columns to search, most specific first"),
                ConfigField(name="output_column", label="Output Column", type="text",
                            required=True, default="bl_area_matched"),
                ConfigField(name="min_match_length", label="Min Match Length", type="number",
                            default=5, description="Minimum place name length for contains match"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        geo_cols_str = config.get("geo_columns", "")
        geo_cols = [c.strip() for c in geo_cols_str.split(",") if c.strip()]
        out_col = config.get("output_column", "bl_area_matched")
        min_len = int(config.get("min_match_length", 5))

        from .data.tiered_rag import PLACE_TO_BL_AREA

        df[out_col] = ""
        total = len(df)
        for i, (idx, row) in enumerate(df.iterrows()):
            code = ""
            for col in geo_cols:
                if col not in df.columns:
                    continue
                val = _safe_str(row.get(col, ""))
                if not val:
                    continue
                val_lower = val.lower()

                # Exact match
                if val_lower in PLACE_TO_BL_AREA:
                    code = PLACE_TO_BL_AREA[val_lower]
                    break

                # Split by comma and try each part
                candidates = []
                parts = [p.strip() for p in re.split(r'[,;/&]', val_lower)]
                for part in parts:
                    if part in PLACE_TO_BL_AREA:
                        candidates.append((len(part), PLACE_TO_BL_AREA[part]))
                if candidates:
                    candidates.sort(reverse=True)
                    code = candidates[0][1]
                    break

                # Contains match (only long names)
                for place, c in PLACE_TO_BL_AREA.items():
                    if len(place) >= min_len and place in val_lower:
                        candidates.append((len(place), c))
                if candidates:
                    candidates.sort(reverse=True)
                    code = candidates[0][1]
                    break

            df.at[idx, out_col] = code

            if on_progress and (i % 100 == 0 or i == total - 1):
                await on_progress(f"{i + 1}/{total} rows matched")

        if on_progress:
            hit = sum(1 for v in df[out_col] if v)
            await on_progress(f"Matched {hit}/{len(df)} B-L area codes")
        return {"output": df}
