"""Shared utilities for parsing LLM responses in AI nodes."""
import json
import re


def extract_json(text: str) -> dict:
    """Robustly extract a JSON object from LLM output.

    Handles:
    - ```json code fences (with or without newlines)
    - Truncated JSON (missing closing braces/quotes)
    - null values → empty strings
    """
    if not text or not text.strip():
        raise ValueError("Empty LLM response")

    cleaned = text.strip()

    # Strip thinking model tags: <think>...</think>
    cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL).strip()

    # Strip code fences: ```json ... ``` or ``` ... ```
    # Handle both newline-separated and same-line variants
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```\s*$', '', cleaned)
    cleaned = cleaned.strip()

    # Remove trailing commas before } or ] (common LLM formatting issue)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

    # Try parsing as-is first (strict=False to allow control chars in strings)
    try:
        parsed = json.loads(cleaned, strict=False)
        return _nulls_to_empty(parsed)
    except json.JSONDecodeError:
        pass

    # Try to find the first { and extract from there
    brace_start = cleaned.find('{')
    if brace_start < 0:
        raise ValueError(f"No JSON object found in: {cleaned[:200]}")

    json_str = cleaned[brace_start:]

    # Try parsing the substring
    try:
        parsed = json.loads(json_str, strict=False)
        return _nulls_to_empty(parsed)
    except json.JSONDecodeError:
        pass

    # Attempt to repair truncated JSON
    repaired = _repair_truncated_json(json_str)
    try:
        parsed = json.loads(repaired, strict=False)
        return _nulls_to_empty(parsed)
    except json.JSONDecodeError as e:
        raise ValueError(f"Cannot parse JSON even after repair: {e}. Raw: {cleaned[:300]}")


def _repair_truncated_json(s: str) -> str:
    """Try to close truncated JSON by balancing braces and quotes."""
    # Fix invalid escape sequences (e.g. \S \P \C → \\S \\P \\C)
    # Valid JSON escapes: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
    s = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)

    # If we're inside an unclosed string, close it
    in_string = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string

    if in_string:
        s += '"'  # close the dangling string

    # Remove only genuinely incomplete trailing patterns.
    # We iterate because closing a string may expose a new trailing comma.
    for _ in range(3):
        prev = s
        # Strip trailing whitespace / comma / colon
        s = re.sub(r'[,:\s]+$', '', s)
        # Remove a trailing key that has no value: , "someKey"
        # But NOT a complete key-value pair like , "key": "val"
        s = re.sub(r',\s*"[^"]*"\s*$', '', s)
        # Remove a first key with no value: { "someKey"
        s = re.sub(r'{\s*"[^"]*"\s*$', '{', s)
        if s == prev:
            break

    # Count open/close braces and brackets
    open_braces = s.count('{') - s.count('}')
    open_brackets = s.count('[') - s.count(']')

    s += ']' * max(0, open_brackets)
    s += '}' * max(0, open_braces)

    return s


def _nulls_to_empty(obj):
    """Recursively replace null/None values with empty strings."""
    if obj is None:
        return ""
    if isinstance(obj, dict):
        return {k: _nulls_to_empty(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nulls_to_empty(v) for v in obj]
    return obj


def clean_cell(val) -> str:
    """Sanitise an AI-produced value before storing it in a DataFrame cell.

    - Converts to string
    - Strips newlines / tabs / carriage returns (prevents CSV / TSV corruption)
    - Collapses runs of spaces left behind
    """
    if not val:
        return ""
    s = str(val)
    s = s.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    s = re.sub(r'  +', ' ', s)
    return s.strip()
