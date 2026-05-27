"""RGSSA-specific normalize functions: scale, call_number, description_isbd."""
import re
import pandas as pd


def _normalize_scale(val):
    s = str(val).strip() if pd.notna(val) else ""
    if not s:
        return ""
    m = re.search(r'1\s*:\s*([\d,\s]+)', s)
    if m:
        ratio = m.group(1).replace(',', '').replace(' ', '')
        try:
            return f"1:{int(ratio):,}"
        except ValueError:
            pass
    return s


def _normalize_call_number(val):
    cn = str(val).strip() if pd.notna(val) else ""
    parts = cn.split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return cn


def _normalize_description_isbd(val):
    d = str(val).strip() if pd.notna(val) else ""
    if not d:
        return ""
    count_m = re.match(r'^(\d+)\s+maps?', d)
    cnt = count_m.group(1) if count_m else "1"
    color = "col." if any(w in d.lower() for w in ["col", "colour", "color"]) else "b&w"
    dim_m = re.search(r'(\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*cm)', d, re.IGNORECASE)
    dim = dim_m.group(1) if dim_m else ""
    parts = [f"{cnt} map{'s' if int(cnt) > 1 else ''}", color]
    if dim:
        parts.append(dim)
    return " ; ".join(parts)


FUNCTIONS = {
    "scale": _normalize_scale,
    "call_number": _normalize_call_number,
    "description_isbd": _normalize_description_isbd,
}
