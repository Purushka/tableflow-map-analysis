from fastapi import APIRouter
from ..engine.registry import get_all_definitions
from ..nodes.lookup_dictionary import BUILTIN_DICTS
from ..nodes.transform_normalize import get_function_names

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@router.get("/types")
async def list_node_types():
    definitions = get_all_definitions()
    return [d.model_dump() for d in definitions]


@router.get("/dictionaries")
async def list_dictionaries():
    return [
        {"name": name, "count": len(data)}
        for name, data in BUILTIN_DICTS.items()
    ]


@router.get("/normalize-functions")
async def list_normalize_functions():
    return get_function_names()
