import os
import uuid
import json
import hashlib
import pandas as pd
from fastapi import APIRouter, UploadFile, File, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.database import get_db
from ..models.schemas import FileModel

router = APIRouter(prefix="/api/files", tags=["files"])
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "file.csv")[1].lower()
    stored_name = f"{file_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, stored_name)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # Read preview
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(filepath, nrows=5)
        else:
            df = pd.read_csv(filepath, encoding="utf-8-sig", nrows=5)
        columns = list(df.columns)
        total_rows = len(pd.read_csv(filepath, encoding="utf-8-sig")) if ext == ".csv" else len(pd.read_excel(filepath))
    except Exception:
        columns = []
        total_rows = 0

    file_model = FileModel(
        id=stored_name,
        filename=file.filename or "unknown",
        filepath=filepath,
        rows=str(total_rows),
        columns_json=json.dumps(columns),
    )
    db.add(file_model)
    await db.commit()

    return {
        "file_id": stored_name,
        "filename": file.filename,
        "rows": total_rows,
        "columns": columns,
    }


@router.get("/{file_id}/preview")
async def preview_file(file_id: str, limit: int = 50):
    filepath = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(filepath):
        return {"error": "File not found"}

    ext = os.path.splitext(file_id)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(filepath, nrows=limit)
        else:
            df = pd.read_csv(filepath, encoding="utf-8-sig", nrows=limit)
        return {
            "columns": list(df.columns),
            "rows": df.fillna("").to_dict(orient="records"),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/{file_id}/download")
async def download_file(file_id: str):
    filepath = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(filepath):
        # Try outputs dir
        filepath = os.path.join(UPLOAD_DIR, "..", "outputs", file_id)
    if not os.path.exists(filepath):
        return {"error": "File not found"}
    return FileResponse(filepath, filename=file_id)


@router.get("/{file_id}/columns")
async def get_columns(file_id: str):
    filepath = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(filepath):
        return {"columns": []}
    ext = os.path.splitext(file_id)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(filepath, nrows=0)
        else:
            df = pd.read_csv(filepath, encoding="utf-8-sig", nrows=0)
        return {"columns": list(df.columns)}
    except Exception:
        return {"columns": []}


THUMB_DIR = os.path.join(UPLOAD_DIR, ".thumbnails")
os.makedirs(THUMB_DIR, exist_ok=True)

# Map previews directory (crops, region previews)
MAP_PREVIEW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage", "map_previews")
)


@router.get("/thumbnail")
async def get_thumbnail(path: str = Query(..., description="Relative path under storage/uploads/")):
    """Serve a resized thumbnail (200x150 max) of an image in storage/uploads/."""
    # Security: normalize and verify path stays within UPLOAD_DIR
    resolved = os.path.normpath(os.path.join(UPLOAD_DIR, path))
    if not resolved.startswith(os.path.normpath(UPLOAD_DIR)):
        return {"error": "Invalid path"}
    if not os.path.isfile(resolved):
        return {"error": "File not found"}

    # Check cache
    path_hash = hashlib.md5(resolved.encode()).hexdigest()
    cached = os.path.join(THUMB_DIR, f"{path_hash}.jpg")
    if os.path.exists(cached):
        return FileResponse(cached, media_type="image/jpeg")

    # Generate thumbnail with Pillow
    try:
        from PIL import Image
        img = Image.open(resolved)
        img.thumbnail((200, 150), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(cached, "JPEG", quality=80)
        return FileResponse(cached, media_type="image/jpeg")
    except Exception as e:
        return {"error": f"Cannot generate thumbnail: {e}"}


@router.get("/map-preview")
async def get_map_preview(path: str = Query(..., description="Absolute or relative path to a map preview/crop image")):
    """Serve a map crop or region preview image from storage/map_previews/."""
    # If absolute path, verify it's within MAP_PREVIEW_DIR
    if os.path.isabs(path):
        resolved = os.path.normpath(path)
    else:
        resolved = os.path.normpath(os.path.join(MAP_PREVIEW_DIR, path))

    if not resolved.startswith(os.path.normpath(MAP_PREVIEW_DIR)):
        return {"error": "Invalid path — must be within map_previews/"}
    if not os.path.isfile(resolved):
        return {"error": "File not found"}

    ext = os.path.splitext(resolved)[1].lower()
    media = "image/png" if ext == ".png" else "image/jpeg"
    return FileResponse(resolved, media_type=media)


@router.get("/map-source-thumb")
async def get_map_source_thumbnail(
    path: str = Query(..., description="Absolute path to the source map image"),
    size: int = Query(600, description="Max dimension for thumbnail"),
):
    """Serve a resized thumbnail of a source map image (for the analysis panel)."""
    resolved = os.path.normpath(path)
    if not os.path.isfile(resolved):
        return {"error": "File not found"}

    # Cache by path hash + size
    path_hash = hashlib.md5(f"{resolved}:{size}".encode()).hexdigest()
    cached = os.path.join(THUMB_DIR, f"map_{path_hash}.jpg")
    if os.path.exists(cached):
        return FileResponse(cached, media_type="image/jpeg")

    try:
        from PIL import Image
        img = Image.open(resolved)
        img.thumbnail((size, size), Image.LANCZOS)
        if img.mode in ("RGBA", "P", "LA", "I", "I;16"):
            img = img.convert("RGB")
        img.save(cached, "JPEG", quality=85)
        return FileResponse(cached, media_type="image/jpeg")
    except Exception as e:
        return {"error": f"Cannot generate thumbnail: {e}"}


# ── Map debug: prompt files and log archives ──────────────────────────────

MAP_DEBUG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "storage", "map_debug")
)


@router.get("/map-debug/prompt")
async def get_debug_prompt(
    path: str = Query(..., description="Absolute path to a prompt text file"),
):
    """Serve a full AI prompt text file from map_debug/."""
    if os.path.isabs(path):
        resolved = os.path.normpath(path)
    else:
        resolved = os.path.normpath(os.path.join(MAP_DEBUG_DIR, path))

    if not resolved.startswith(os.path.normpath(MAP_DEBUG_DIR)):
        return {"error": "Invalid path — must be within map_debug/"}
    if not os.path.isfile(resolved):
        return {"error": "File not found"}

    return FileResponse(resolved, media_type="text/plain; charset=utf-8")


@router.get("/map-debug/archives")
async def list_debug_archives():
    """List available debug log archives."""
    os.makedirs(MAP_DEBUG_DIR, exist_ok=True)
    archives = sorted(
        [f for f in os.listdir(MAP_DEBUG_DIR)
         if f.startswith("debug_archive_") and f.endswith(".json")],
        reverse=True,
    )
    result = []
    for fname in archives[:20]:  # last 20
        fpath = os.path.join(MAP_DEBUG_DIR, fname)
        size = os.path.getsize(fpath)
        result.append({"filename": fname, "path": fpath, "size": size})
    return {"archives": result}


@router.get("/map-debug/archive")
async def get_debug_archive(
    path: str = Query(..., description="Path to debug archive JSON"),
):
    """Download a debug log archive JSON file."""
    if os.path.isabs(path):
        resolved = os.path.normpath(path)
    else:
        resolved = os.path.normpath(os.path.join(MAP_DEBUG_DIR, path))

    if not resolved.startswith(os.path.normpath(MAP_DEBUG_DIR)):
        return {"error": "Invalid path — must be within map_debug/"}
    if not os.path.isfile(resolved):
        return {"error": "File not found"}

    return FileResponse(
        resolved,
        media_type="application/json",
        filename=os.path.basename(resolved),
    )
