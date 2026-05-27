import re
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class TransformFormulaNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_formula",
            label="Formula",
            category="transform",
            icon="Calculator",
            color="#10b981",
            description="Computed column via expression or template",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="output_column", label="Output Column", type="text", required=True),
                ConfigField(
                    name="formula_type",
                    label="Type",
                    type="select",
                    default="template",
                    options=["expression", "template"],
                ),
                ConfigField(
                    name="formula",
                    label="Formula",
                    type="prompt_template",
                    required=True,
                    description='Expression: count_filled([Col1],[Col2])/10*100\nTemplate: "{Author} — {Title}"',
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        out_col = config.get("output_column", "result")
        formula_type = config.get("formula_type", "template")
        formula = config.get("formula", "")

        if formula_type == "template":
            def apply_template(row):
                result = formula
                for col in df.columns:
                    val = str(row[col]) if pd.notna(row[col]) else ""
                    result = result.replace(f"{{{col}}}", val)
                return result
            df[out_col] = df.apply(apply_template, axis=1)
        else:
            # Expression mode: support count_filled([Col1],[Col2]...)
            def apply_expression(row):
                expr = formula
                # Replace count_filled
                def count_filled_fn(match):
                    cols = match.group(1).split(",")
                    count = 0
                    for c in cols:
                        c = c.strip().strip("[]")
                        if c in row.index and pd.notna(row[c]) and str(row[c]).strip():
                            count += 1
                    return str(count)
                expr = re.sub(r'count_filled\(([^)]+)\)', count_filled_fn, expr)
                # Replace [Col] references
                for col in df.columns:
                    val = row[col] if pd.notna(row[col]) else 0
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        val = 0
                    expr = expr.replace(f"[{col}]", str(val))
                try:
                    return eval(expr)
                except Exception:
                    return None
            df[out_col] = df.apply(apply_expression, axis=1)

        if on_progress:
            await on_progress(f"Computed column '{out_col}'")
        return {"output": df}
