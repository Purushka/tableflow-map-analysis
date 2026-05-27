"""Natural language -> structured config parser using any LLM provider."""
import json
from fastapi import APIRouter
from pydantic import BaseModel
from ..providers.registry import call_llm

router = APIRouter(prefix="/api/nl", tags=["nl"])


class NLParseRequest(BaseModel):
    text: str
    node_type: str
    field_name: str
    columns: list[str] = []
    api_key: str = ""
    model: str = ""


# Schema definitions per (node_type, field_name)
FIELD_SCHEMAS: dict[tuple[str, str], dict] = {
    ("transform_normalize", "operations"): {
        "desc": "Array of cleaning operations",
        "schema": '[{"column":"<from columns>","output_column":"string","function":"trim|lowercase|uppercase|date|title_case|strip_html|number|regex_extract|find_replace","params":{"pattern":"(for regex_extract)","find":"(for find_replace)","replace":"(for find_replace)"}}]',
        "example": '[{"column":"Date Published","output_column":"date_year","function":"date"},{"column":"TITLE","output_column":"title_clean","function":"trim"}]',
    },
    ("transform_group", "aggregations"): {
        "desc": "Array of aggregation operations",
        "schema": '[{"column":"<from columns>","function":"count|first|mode|sum|min|max","output_column":"string"}]',
        "example": '[{"column":"Country","function":"count","output_column":"country_count"}]',
    },
    ("transform_split", "rules"): {
        "desc": "Array of routing rules with conditions (first match wins)",
        "schema": '[{"output":"route_1|route_2|route_3|route_4","label":"string","conditions":[{"column":"<from columns>","op":"equals|not_equals|contains|is_empty|is_not_empty|>=|>|<=|<|regex","value":"string"}]}]',
        "example": '[{"output":"route_1","label":"High Score","conditions":[{"column":"score","op":">=","value":"80"}]}]',
    },
    ("ai_enrich", "json_field_mapping"): {
        "desc": "Object mapping AI JSON response field names to output column names",
        "schema": '{"ai_field_name":"output_column_name",...}',
        "example": '{"continent":"geo_continent","country":"geo_country","city":"geo_city"}',
    },
    ("output_xlsx", "columns"): {
        "desc": "Array of column selections with optional display labels",
        "schema": '[{"source":"<from columns>","label":"display name"}]',
        "example": '[{"source":"TITLE","label":"Map Title"},{"source":"Author","label":"Creator"}]',
    },
}

# Fields that return a template string instead of JSON
TEMPLATE_FIELDS = {
    ("transform_formula", "formula"),
    ("ai_classify", "prompt_template"),
    ("ai_enrich", "system_prompt"),
    ("ai_enrich", "user_prompt_template"),
}


@router.post("/parse")
async def parse_nl(req: NLParseRequest):
    api_key = req.api_key
    model = req.model

    if not api_key or not model:
        return {"error": "No API key or model provided. Configure in Settings."}

    key = (req.node_type, req.field_name)
    cols_str = ", ".join(req.columns) if req.columns else "(no columns available)"

    try:
        if key in TEMPLATE_FIELDS:
            system = (
                f"You convert natural language descriptions into prompt templates.\n"
                f"Available columns that can be referenced: {cols_str}\n"
                f"Column references use curly braces: {{ColumnName}}\n"
                f"Return ONLY the template string. No JSON wrapping, no explanation, no markdown."
            )
            result_text = await call_llm(model, system, req.text, 500, api_key)
            return {"result": result_text}

        schema_info = FIELD_SCHEMAS.get(key)
        if not schema_info:
            return {"error": f"Unknown field: {req.node_type}.{req.field_name}"}

        system = (
            f"You convert natural language descriptions into structured JSON config.\n"
            f"Field purpose: {schema_info['desc']}\n"
            f"Expected JSON schema: {schema_info['schema']}\n"
            f"Example output: {schema_info['example']}\n"
            f"Available columns: {cols_str}\n"
            f"Return ONLY valid JSON. No explanation, no markdown code blocks."
        )
        raw = await call_llm(model, system, req.text, 1000, api_key)

        # Strip markdown code blocks if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        try:
            parsed = json.loads(raw)
            return {"result": parsed}
        except json.JSONDecodeError:
            return {"result": raw, "error": "Failed to parse JSON, returning raw text"}

    except Exception as e:
        return {"error": str(e)}
