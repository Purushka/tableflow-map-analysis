import json
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformSplitNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_split",
            label="Split (Router)",
            category="transform",
            icon="GitBranch",
            color="#10b981",
            description="Multi-way router: split rows by rules into up to 5 routes",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[
                PortDefinition(name="route_1", label="Route 1"),
                PortDefinition(name="route_2", label="Route 2"),
                PortDefinition(name="route_3", label="Route 3"),
                PortDefinition(name="route_4", label="Route 4"),
                PortDefinition(name="default", label="Default"),
            ],
            config_fields=[
                ConfigField(
                    name="rules",
                    label="Rules (first match wins)",
                    type="json",
                    required=True,
                    description="Array of {output, label, conditions: [{column, op, value}]}",
                    placeholder='[{"output":"route_1","label":"Tier A","conditions":[{"column":"score","op":">=","value":"80"}]}]',
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        rules = config.get("rules", [])
        if isinstance(rules, str):
            rules = json.loads(rules)

        output_names = ["route_1", "route_2", "route_3", "route_4", "default"]
        buckets = {name: [] for name in output_names}
        assigned = set()

        for idx, row in df.iterrows():
            matched = False
            for rule in rules:
                out = rule.get("output", "default")
                conditions = rule.get("conditions", [])
                all_match = True
                for cond in conditions:
                    col = cond.get("column", "")
                    op = cond.get("op", "equals")
                    val = cond.get("value", "")
                    if col not in df.columns:
                        all_match = False
                        break
                    cell = str(row[col]) if pd.notna(row[col]) else ""
                    if not _check_condition(cell, op, val):
                        all_match = False
                        break
                if all_match:
                    buckets[out].append(idx)
                    assigned.add(idx)
                    matched = True
                    break
            if not matched:
                buckets["default"].append(idx)

        result = {}
        for name in output_names:
            if buckets[name]:
                result[name] = df.loc[buckets[name]].reset_index(drop=True)
            else:
                result[name] = pd.DataFrame(columns=df.columns)

        if on_progress:
            counts = ", ".join(f"{k}: {len(v)}" for k, v in result.items() if len(v) > 0)
            await on_progress(f"Split: {counts}")
        return result


def _check_condition(cell_value: str, op: str, value: str) -> bool:
    if op == "equals":
        return cell_value.lower() == value.lower()
    elif op == "not_equals":
        return cell_value.lower() != value.lower()
    elif op == "contains":
        return value.lower() in cell_value.lower()
    elif op == "is_empty":
        return cell_value.strip() == ""
    elif op == "is_not_empty":
        return cell_value.strip() != ""
    elif op in (">=", "greater_equal"):
        try:
            return float(cell_value) >= float(value)
        except ValueError:
            return False
    elif op in (">", "greater_than"):
        try:
            return float(cell_value) > float(value)
        except ValueError:
            return False
    elif op in ("<=", "less_equal"):
        try:
            return float(cell_value) <= float(value)
        except ValueError:
            return False
    elif op in ("<", "less_than"):
        try:
            return float(cell_value) < float(value)
        except ValueError:
            return False
    elif op == "regex":
        import re
        return bool(re.search(value, cell_value))
    return False
