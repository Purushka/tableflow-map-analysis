"""Provider listing API."""
from fastapi import APIRouter
from ..providers.registry import get_all_providers, get_all_models

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def list_providers():
    """Return all AI providers with their models."""
    return get_all_providers()


@router.get("/models")
async def list_models():
    """Return flat list of all available models."""
    return get_all_models()
