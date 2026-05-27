import uuid
import json
from datetime import datetime
from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.database import get_db
from ..models.schemas import PipelineModel

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("")
async def list_pipelines(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PipelineModel).order_by(PipelineModel.updated_at.desc()))
    pipelines = result.scalars().all()
    return [p.to_dict() for p in pipelines]


@router.post("")
async def create_pipeline(data: dict = Body(...), db: AsyncSession = Depends(get_db)):
    pipeline = PipelineModel(
        id=str(uuid.uuid4()),
        name=data.get("name", "Untitled Pipeline"),
        description=data.get("description", ""),
        nodes_json=json.dumps(data.get("nodes", [])),
        edges_json=json.dumps(data.get("edges", [])),
    )
    db.add(pipeline)
    await db.commit()
    return pipeline.to_dict()


@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PipelineModel).where(PipelineModel.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        return {"error": "Pipeline not found"}
    return pipeline.to_dict()


@router.put("/{pipeline_id}")
async def update_pipeline(pipeline_id: str, data: dict = Body(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PipelineModel).where(PipelineModel.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        pipeline = PipelineModel(id=pipeline_id)
        db.add(pipeline)

    if "name" in data:
        pipeline.name = data["name"]
    if "description" in data:
        pipeline.description = data["description"]
    if "nodes" in data:
        pipeline.nodes_json = json.dumps(data["nodes"])
    if "edges" in data:
        pipeline.edges_json = json.dumps(data["edges"])
    pipeline.updated_at = datetime.utcnow()

    await db.commit()
    return pipeline.to_dict()


@router.delete("/{pipeline_id}")
async def delete_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PipelineModel).where(PipelineModel.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if pipeline:
        await db.delete(pipeline)
        await db.commit()
    return {"ok": True}
