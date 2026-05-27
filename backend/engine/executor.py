"""Pipeline execution engine with topological sort."""
import os
import pandas as pd
from collections import defaultdict, deque
from .registry import get_node_class
from .context import PipelineContext, build_data_preview

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "storage", "outputs")


def topological_sort(nodes: list, edges: list) -> list[str]:
    """Kahn's algorithm for topological sorting."""
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    node_ids = {n["id"] for n in nodes}

    for n in nodes:
        in_degree[n["id"]] = in_degree.get(n["id"], 0)

    for e in edges:
        src = e["source"]
        tgt = e["target"]
        if src in node_ids and tgt in node_ids:
            graph[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue = deque([nid for nid in node_ids if in_degree.get(nid, 0) == 0])
    order = []

    while queue:
        nid = queue.popleft()
        order.append(nid)
        for neighbor in graph[nid]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(node_ids):
        raise ValueError("Pipeline contains a cycle")

    return order


def get_downstream(node_id: str, edges: list) -> list[str]:
    """Get all downstream node IDs."""
    visited = set()
    queue = deque([node_id])
    while queue:
        nid = queue.popleft()
        for e in edges:
            if e["source"] == nid and e["target"] not in visited:
                visited.add(e["target"])
                queue.append(e["target"])
    return list(visited)


async def _auto_export_partial(context: PipelineContext, last_output_node: str | None,
                               node_map: dict) -> str | None:
    """Auto-export partial results when pipeline fails. Returns filename or None."""
    if not last_output_node:
        return None

    result = context.get_output(last_output_node, "output")
    if result is None:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    node_label = node_map.get(last_output_node, {}).get("data", {}).get("label", last_output_node)
    filename = f"partial_{node_label.replace(' ', '_')}.xlsx"
    filepath = os.path.join(OUTPUT_DIR, filename)

    try:
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            result.to_excel(writer, sheet_name="Partial", index=False)
            ws = writer.sheets["Partial"]
            ws.freeze_panes = "A2"
            if len(result) > 0:
                ws.auto_filter.ref = ws.dimensions
        return filename
    except Exception:
        return None


async def execute_pipeline(pipeline: dict, context: PipelineContext):
    """Execute a full pipeline in topological order."""
    nodes = pipeline.get("nodes", [])
    edges = pipeline.get("edges", [])

    order = topological_sort(nodes, edges)
    node_map = {n["id"]: n for n in nodes}

    await context.emit("pipeline_start", {"total_nodes": len(order)})

    skipped_nodes: set[str] = set()
    last_output_node: str | None = None
    has_error = False
    output_files: list[dict] = []  # [{filename, node_label}]

    for node_id in order:
        # Skip nodes that were already marked as skipped due to upstream failure
        if node_id in skipped_nodes:
            continue

        node_def = node_map[node_id]
        node_type = node_def["type"]
        config = node_def.get("data", {}).get("config", {})

        await context.set_status(node_id, "running")

        try:
            NodeClass = get_node_class(node_type)
            node_instance = NodeClass()
            defn = NodeClass.definition()

            # Capture input columns for diff tracking
            inputs = {}
            input_columns: set[str] = set()
            for port in defn.inputs:
                df = context.resolve_input(node_id, port.name, edges)
                if df is not None:
                    inputs[port.name] = df
                    input_columns.update(df.columns.tolist())

            # Progress callback bound to this node
            async def on_progress(msg, _nid=node_id):
                await context.set_status(_nid, "running", message=msg)

            outputs = await node_instance.execute(inputs, config, on_progress, context)

            if outputs:
                context.store_outputs(node_id, outputs)
                last_output_node = node_id

                # Emit data preview with new columns highlighted
                for port_name, df in outputs.items():
                    if isinstance(df, pd.DataFrame) and len(df) > 0:
                        new_cols = [c for c in df.columns if c not in input_columns]
                        node_label = node_def.get("data", {}).get("label", node_type)
                        preview = build_data_preview(df, new_columns=new_cols)
                        preview["node_id"] = node_id
                        preview["node_label"] = node_label
                        await context.emit("node_data_preview", preview)
                        break  # only first output port

            # Track output files from output nodes
            if node_type.startswith("output_"):
                filename = config.get("filename", "")
                if filename:
                    node_label = node_def.get("data", {}).get("label", node_type)
                    output_files.append({"filename": filename, "node_label": node_label})

            # Report row count
            total_rows = sum(len(df) for df in outputs.values()) if outputs else 0
            if total_rows == 0 and inputs:
                input_rows = sum(len(df) for df in inputs.values())
                await context.set_status(node_id, "success", message=f"Exported {input_rows} rows")
            else:
                await context.set_status(node_id, "success", message=f"{total_rows} rows")

        except Exception as e:
            has_error = True
            await context.set_status(node_id, "error", error=str(e))
            # Skip downstream nodes
            downstream = get_downstream(node_id, edges)
            for downstream_id in downstream:
                skipped_nodes.add(downstream_id)
                await context.set_status(downstream_id, "skipped", error=f"Upstream node {node_id} failed")

    # Auto-export partial results on failure
    partial_file = None
    if has_error and last_output_node:
        partial_file = await _auto_export_partial(context, last_output_node, node_map)

    await context.emit("pipeline_complete", {
        "has_error": has_error,
        "partial_file": partial_file,
        "output_files": output_files,
    })
