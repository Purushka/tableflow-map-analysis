import json
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


# Builtin dictionaries will be loaded from lookups/
BUILTIN_DICTS = {}


def register_builtin(name: str, data: dict):
    BUILTIN_DICTS[name] = data


class LookupDictionaryNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="lookup_dictionary",
            label="Dictionary Lookup",
            category="lookup",
            icon="BookOpen",
            color="#f59e0b",
            description="Match values against a dictionary",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="source_column", label="Source Column", type="column_select", required=True),
                ConfigField(name="output_column", label="Output Column", type="text", required=True),
                ConfigField(name="match_mode", label="Match Mode", type="select",
                            default="exact", options=["exact", "contains", "fuzzy"]),
                ConfigField(name="case_sensitive", label="Case Sensitive", type="boolean", default=False),
                ConfigField(name="dictionary_source", label="Dictionary Source", type="select",
                            default="builtin", options=["builtin", "upload"]),
                ConfigField(name="builtin_name", label="Builtin Dictionary", type="select",
                            options=list(BUILTIN_DICTS.keys()),
                            description="Select a builtin dictionary"),
                ConfigField(name="no_match_value", label="No Match Value", type="text", default=""),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        src_col = config.get("source_column", "")
        out_col = config.get("output_column", "")
        mode = config.get("match_mode", "exact")
        case_sens = config.get("case_sensitive", False)
        source = config.get("dictionary_source", "builtin")
        builtin_name = config.get("builtin_name", "")
        no_match = config.get("no_match_value", "")

        if source == "builtin" and builtin_name in BUILTIN_DICTS:
            dictionary = BUILTIN_DICTS[builtin_name]
        else:
            dictionary = {}

        if not case_sens:
            dictionary = {k.lower(): v for k, v in dictionary.items()}

        df[out_col] = ""
        for idx, row in df.iterrows():
            val = str(row.get(src_col, "")) if pd.notna(row.get(src_col)) else ""
            lookup_val = val if case_sens else val.lower()

            matched = None
            if mode == "exact":
                matched = dictionary.get(lookup_val)
            elif mode == "contains":
                for key, value in dictionary.items():
                    if key in lookup_val:
                        matched = value
                        break
            elif mode == "fuzzy":
                from difflib import SequenceMatcher
                best_score = 0
                for key, value in dictionary.items():
                    score = SequenceMatcher(None, lookup_val, key).ratio()
                    if score > best_score and score > 0.7:
                        best_score = score
                        matched = value

            df.at[idx, out_col] = matched if matched else no_match

        if on_progress:
            hit = sum(1 for v in df[out_col] if v and v != no_match)
            await on_progress(f"Matched {hit}/{len(df)} rows")
        return {"output": df}
