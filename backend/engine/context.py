"""Runtime context: DataFrames flowing between nodes, status tracking, API keys."""
import pandas as pd
from typing import Optional, Callable


class PipelineContext:
    def __init__(self, api_keys: dict[str, str] | None = None):
        self._outputs: dict[str, dict[str, pd.DataFrame]] = {}  # node_id -> {port_name: df}
        self._status: dict[str, dict] = {}  # node_id -> {status, message, error}
        self._on_event: Optional[Callable] = None
        self._api_keys: dict[str, str] = api_keys or {}  # provider_id -> api_key

    def get_api_key(self, provider_id: str) -> str:
        """Get API key for a provider. Returns empty string if not configured."""
        return self._api_keys.get(provider_id, "")

    def set_event_handler(self, handler: Callable):
        self._on_event = handler

    async def emit(self, event_type: str, data: dict):
        if self._on_event:
            await self._on_event(event_type, data)

    def store_outputs(self, node_id: str, outputs: dict[str, pd.DataFrame]):
        self._outputs[node_id] = outputs

    def get_output(self, node_id: str, port_name: str) -> Optional[pd.DataFrame]:
        if node_id in self._outputs and port_name in self._outputs[node_id]:
            return self._outputs[node_id][port_name]
        return None

    def resolve_input(self, node_id: str, port_name: str, edges: list) -> Optional[pd.DataFrame]:
        """Find the upstream node/port that connects to this input."""
        matching_edges = [
            e for e in edges
            if e["target"] == node_id and e.get("targetHandle", "input") == port_name
        ]
        if not matching_edges:
            return None

        dfs = []
        for edge in matching_edges:
            src_id = edge["source"]
            src_handle = edge.get("sourceHandle", "output")
            df = self.get_output(src_id, src_handle)
            if df is not None:
                dfs.append(df)

        if not dfs:
            return None
        if len(dfs) == 1:
            return dfs[0]
        return pd.concat(dfs, ignore_index=True)

    async def set_status(self, node_id: str, status: str, message: str = "", error: str = ""):
        self._status[node_id] = {"status": status, "message": message, "error": error}
        await self.emit("node_status", {
            "node_id": node_id, "status": status,
            "message": message, "error": error,
        })

    async def progress(self, message: str):
        await self.emit("progress", {"message": message})

    def get_node_result(self, node_id: str) -> Optional[dict]:
        if node_id not in self._outputs:
            return None
        result = {}
        for port_name, df in self._outputs[node_id].items():
            result[port_name] = {
                "columns": list(df.columns),
                "rows": df.head(100).fillna("").to_dict(orient="records"),
                "total": len(df),
            }
        return result


def build_data_preview(df: pd.DataFrame, new_columns: list[str] | None = None,
                       processed_rows: int | None = None) -> dict:
    """Build a compact data preview dict for SSE transmission."""
    max_preview = 100
    preview_df = df.head(max_preview).fillna("")
    rows = []
    for _, row in preview_df.iterrows():
        rows.append({col: str(val)[:200] for col, val in row.items()})
    return {
        "columns": list(df.columns),
        "new_columns": new_columns or [],
        "rows": rows,
        "total_rows": len(df),
        "processed_rows": processed_rows,
    }
