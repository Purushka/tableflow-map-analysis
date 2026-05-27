import re
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


# ─── Core normalize functions ─────────────────────────────────────────

def _normalize_trim(val):
    if pd.isna(val):
        return ""
    return re.sub(r'\s+', ' ', str(val)).strip()


def _normalize_lowercase(val):
    return str(val).lower().strip() if pd.notna(val) else ""


def _normalize_uppercase(val):
    return str(val).upper().strip() if pd.notna(val) else ""


def _normalize_title_case(val):
    return str(val).strip().title() if pd.notna(val) else ""


def _normalize_strip_html(val):
    s = str(val) if pd.notna(val) else ""
    return re.sub(r'<[^>]+>', '', s).strip()


def _normalize_number(val):
    """Extract first numeric value from string."""
    s = str(val) if pd.notna(val) else ""
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    return float(m.group(0)) if m else ""


def _normalize_date(val):
    """Parse date string — handles bracketed, circa, ranges, decades, centuries."""
    d = str(val).strip() if pd.notna(val) else ""
    if not d:
        return ""

    # 1. Strip surrounding brackets first: [1705?] → 1705?, [n.d.] → n.d.
    inner = d
    if inner.startswith('[') and inner.endswith(']'):
        inner = inner[1:-1].strip()

    # 2. Strip internal brackets: 166[3] → 1663
    inner = re.sub(r'[\[\]]', '', inner)

    # 3. "n.d." or "N.D." → no date (now catches [n.d.] too)
    if re.match(r'^[Nn]\.?\s*[Dd]\.?\s*$', inner):
        return ""

    # 4. [between YYYY and YYYY?] → first year
    between_m = re.match(r'between\s+(\d{4})\s+and\s+(\d{4})', inner, re.IGNORECASE)
    if between_m:
        return between_m.group(1)

    # 5. Decade range: 188-?-189-? → 1880s (first decade)
    decade_range = re.match(r'^(\d{3})-\??\s*[-–]\s*\d{3}-', inner)
    if decade_range:
        return f"{int(decade_range.group(1)) * 10}s"

    # 6. circa: c.1800, ca. 1800
    circa = re.match(r'^c[a]?\.?\s*(\d{4})', inner)
    if circa:
        return circa.group(1)

    # 7. Range: 1800-1850 or 1800–50
    range_m = re.match(r'^(\d{4})\s*[-–]\s*(\d{2,4})', inner)
    if range_m:
        return range_m.group(1)

    # 8. Exact 4-digit year (with optional ?)
    q_m = re.match(r'^(\d{4})\s*\??$', inner)
    if q_m:
        return q_m.group(1)

    # 9. Decade: 192-? → 1920s, 183- → 1830s (3 known digits)
    decade_m = re.match(r'^(\d{3})-?\??\s*$', inner)
    if decade_m:
        return f"{int(decade_m.group(1)) * 10}s"

    # 10. Century: 19-- or 19--? → "20th century"; 19-? → "20th century"
    century_m = re.match(r'^(\d{2})-{1,2}\??\s*$', inner)
    if century_m:
        n = int(century_m.group(1)) + 1
        suffix = ("st" if n % 10 == 1 and n % 100 != 11 else
                  "nd" if n % 10 == 2 and n % 100 != 12 else
                  "rd" if n % 10 == 3 and n % 100 != 13 else "th")
        return f"{n}{suffix} century"

    # 11. Fallback: extract first 4-digit year from any position
    exact2 = re.search(r'(\d{4})', inner)
    if exact2:
        return exact2.group(1)

    return d


def _normalize_regex_extract(val, pattern=""):
    s = str(val) if pd.notna(val) else ""
    if not pattern:
        return s
    m = re.search(pattern, s)
    return m.group(1) if m and m.groups() else (m.group(0) if m else "")


def _normalize_find_replace(val, find="", replace=""):
    s = str(val) if pd.notna(val) else ""
    return s.replace(find, replace)


def _normalize_fix_encoding(val):
    """Remove U+FFFD replacement characters and fix common mojibake."""
    s = str(val) if pd.notna(val) else ""
    # Remove replacement character (the diamond &#xFFFD;)
    s = s.replace('\ufffd', '')
    # Collapse double-spaces left behind
    s = re.sub(r'  +', ' ', s)
    return s.strip()


# ─── Function registry ────────────────────────────────────────────────

FUNCTIONS = {
    "trim": _normalize_trim,
    "lowercase": _normalize_lowercase,
    "uppercase": _normalize_uppercase,
    "title_case": _normalize_title_case,
    "strip_html": _normalize_strip_html,
    "number": _normalize_number,
    "date": _normalize_date,
    "regex_extract": _normalize_regex_extract,
    "find_replace": _normalize_find_replace,
    "fix_encoding": _normalize_fix_encoding,
}


def register_function(name: str, fn):
    """Register an additional normalize function (e.g. from a plugin)."""
    FUNCTIONS[name] = fn


def get_function_names() -> list[str]:
    """Return all registered function names."""
    return sorted(FUNCTIONS.keys())


# ─── Node ──────────────────────────────────────────────────────────────

class TransformNormalizeNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="transform_normalize",
            label="Normalize",
            category="transform",
            icon="Wand2",
            color="#10b981",
            description="Field-level cleaning and normalization",
            inputs=[PortDefinition(name="input", label="Data")],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="operations",
                    label="Operations",
                    type="json",
                    required=True,
                    description="Array of {column, output_column, function, params}",
                    placeholder='[{"column":"Date","output_column":"year","function":"date"}]',
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        df = inputs["input"].copy()
        operations = config.get("operations", [])
        if isinstance(operations, str):
            import json
            operations = json.loads(operations)

        for op in operations:
            col = op.get("column", "")
            out_col = op.get("output_column", "")
            func_name = op.get("function", "trim")
            params = op.get("params", {})

            func = FUNCTIONS.get(func_name)
            if not func:
                continue

            # "*" means apply to all string/object columns
            if col == "*":
                target_cols = [c for c in df.columns if df[c].dtype == object]
            elif col in df.columns:
                target_cols = [col]
            else:
                continue

            for tc in target_cols:
                dest = out_col if (out_col and col != "*") else tc
                if func_name == "regex_extract":
                    df[dest] = df[tc].apply(lambda v: func(v, params.get("pattern", "")))
                elif func_name == "find_replace":
                    df[dest] = df[tc].apply(lambda v: func(v, params.get("find", ""), params.get("replace", "")))
                else:
                    df[dest] = df[tc].apply(func)

        if on_progress:
            await on_progress(f"Applied {len(operations)} normalize operations")
        return {"output": df}
