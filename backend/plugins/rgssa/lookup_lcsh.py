import pandas as pd
from backend.nodes.base import BaseNode, NodeDefinition, PortDefinition, ConfigField


def _safe_str(val) -> str:
    """Safely convert any value to string, handling arrays/lists/nan."""
    if val is None:
        return ""
    try:
        if isinstance(val, (list, tuple)):
            return ", ".join(str(v) for v in val if v)
        if hasattr(val, '__iter__') and not isinstance(val, str):
            return ", ".join(str(v) for v in val if v)
        if pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    s = str(val).strip()
    # Handle string-encoded Python lists: "['Paris', 'London']" → "Paris, London"
    if s.startswith('[') and s.endswith(']'):
        import ast
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return ", ".join(str(v) for v in parsed if v)
        except (ValueError, SyntaxError):
            pass
    return s


class LookupLCSHNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="lookup_lcsh",
            label="LCSH Generator",
            category="lookup",
            icon="Library",
            color="#f59e0b",
            description="Generate LCSH headings from geographic and theme data",
            plugin="rgssa",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="country_col", label="Country Column", type="column_select", required=True),
                ConfigField(name="state_col", label="State Column", type="column_select"),
                ConfigField(name="city_col", label="City Column", type="column_select"),
                ConfigField(name="theme_col", label="Theme Column", type="column_select"),
                ConfigField(name="output_column", label="Output Column", type="text",
                            default="subject_lcsh"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()

        country_col = config.get("country_col", "")
        state_col = config.get("state_col", "")
        city_col = config.get("city_col", "")
        theme_col = config.get("theme_col", "")
        out_col = config.get("output_column", "subject_lcsh")

        from .data.tiered_rag import LCSH_TEMPLATES, THEME_TO_LCSH_SUBDIVISION

        df[out_col] = ""
        total = len(df)
        for i, (idx, row) in enumerate(df.iterrows()):
            country = _safe_str(row.get(country_col)) if country_col else ""
            state = _safe_str(row.get(state_col)) if state_col else ""
            city = _safe_str(row.get(city_col)) if city_col else ""
            theme = _safe_str(row.get(theme_col)) if theme_col else ""

            locality = city or state or country or ""
            headings = []

            if locality:
                template_key = (country, state) if state else (country, None)
                template = LCSH_TEMPLATES.get(template_key, "{locality}")
                if "{locality}" in template:
                    area_term = template.format(locality=locality)
                else:
                    area_term = template
                headings.append(f"{area_term} -- Maps")

                theme_lower = theme.lower()
                for kw, subdiv in THEME_TO_LCSH_SUBDIVISION.items():
                    if kw in theme_lower:
                        headings.append(f"{area_term} -- {subdiv}")
                        break

            if state and city:
                headings.append(f"{state} -- Maps")
            if country and country != (city or ""):
                headings.append(f"{country} -- Maps")

            # Deduplicate while preserving order
            seen = set()
            unique_headings = []
            for h in headings:
                if h not in seen:
                    seen.add(h)
                    unique_headings.append(h)
            df.at[idx, out_col] = "; ".join(unique_headings)

            if on_progress and (i % 100 == 0 or i == total - 1):
                await on_progress(f"{i + 1}/{total} rows processed")

        if on_progress:
            hit = sum(1 for v in df[out_col] if v)
            await on_progress(f"Generated LCSH for {hit}/{len(df)} rows")
        return {"output": df}
