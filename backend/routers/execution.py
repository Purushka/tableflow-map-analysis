import json
import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.database import get_db
from ..models.schemas import PipelineModel
from ..engine.executor import execute_pipeline
from ..engine.context import PipelineContext

router = APIRouter(prefix="/api/pipelines", tags=["execution"])

# Store contexts for result retrieval
_contexts: dict[str, PipelineContext] = {}


@router.post("/{pipeline_id}/run")
async def run_pipeline(pipeline_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PipelineModel).where(PipelineModel.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        return {"error": "Pipeline not found"}

    # Read API keys from request body (keys never stored server-side)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    api_keys = body.get("api_keys", {})

    pipeline_data = pipeline.to_dict()
    context = PipelineContext(api_keys=api_keys)
    _contexts[pipeline_id] = context

    async def event_stream():
        queue = asyncio.Queue()

        async def on_event(event_type, data):
            await queue.put({"event": event_type, "data": data})

        context.set_event_handler(on_event)

        # Run pipeline in background
        task = asyncio.create_task(execute_pipeline(pipeline_data, context))

        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat', 'data': {}})}\n\n"

            # Drain remaining events
            while not queue.empty():
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"

            if task.exception():
                yield f"data: {json.dumps({'event': 'error', 'data': {'message': str(task.exception())}})}\n\n"

        except asyncio.CancelledError:
            task.cancel()
            raise

        yield f"data: {json.dumps({'event': 'done', 'data': {}})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{pipeline_id}/results/{node_id}")
async def get_node_results(pipeline_id: str, node_id: str):
    context = _contexts.get(pipeline_id)
    if not context:
        return {"error": "No execution context found. Run the pipeline first."}

    result = context.get_node_result(node_id)
    if not result:
        return {"error": "No results for this node"}

    for port_name, data in result.items():
        return data
    return {"error": "No output data"}


@router.get("/{pipeline_id}/outputs")
async def list_outputs(pipeline_id: str):
    import os
    output_dir = os.path.join(os.path.dirname(__file__), "..", "storage", "outputs")
    if not os.path.exists(output_dir):
        return []
    files = os.listdir(output_dir)
    return [
        {"filename": f, "url": f"/api/files/{f}/download"}
        for f in files
    ]
