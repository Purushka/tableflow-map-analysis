import json
import httpx
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField


class InputAPINode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="input_api",
            label="HTTP API Input",
            category="input",
            icon="Globe",
            color="#3b82f6",
            description="Fetch data from an HTTP API endpoint",
            inputs=[],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(name="url", label="URL", type="text", required=True,
                            placeholder="https://api.example.com/data"),
                ConfigField(name="method", label="Method", type="select",
                            default="GET", options=["GET", "POST"]),
                ConfigField(name="headers", label="Headers (JSON)", type="json",
                            description='e.g. {"Authorization": "Bearer ..."}',
                            placeholder='{}'),
                ConfigField(name="body", label="Request Body (JSON)", type="json",
                            description="POST body (ignored for GET)",
                            placeholder='{}'),
                ConfigField(name="json_path", label="JSON Path", type="text",
                            description="Dot-path to array in response, e.g. data.results",
                            placeholder="data.results"),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        body = config.get("body", {})
        json_path = config.get("json_path", "").strip()

        if isinstance(headers, str):
            headers = json.loads(headers) if headers else {}
        if isinstance(body, str):
            body = json.loads(body) if body else {}

        async with httpx.AsyncClient(timeout=60) as client:
            if method == "POST":
                resp = await client.post(url, headers=headers, json=body)
            else:
                resp = await client.get(url, headers=headers)

        resp.raise_for_status()
        data = resp.json()

        # Navigate to nested path
        if json_path:
            for key in json_path.split("."):
                if isinstance(data, dict):
                    data = data[key]
                elif isinstance(data, list) and key.isdigit():
                    data = data[int(key)]

        # Convert to DataFrame
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            try:
                df = pd.DataFrame(data)
            except ValueError:
                df = pd.DataFrame([data])
        else:
            df = pd.DataFrame([{"value": data}])

        if on_progress:
            await on_progress(f"Fetched {len(df)} rows from API")
        return {"output": df}
