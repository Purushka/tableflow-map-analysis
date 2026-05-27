import os
import uuid
import zipfile
import pandas as pd
from .base import BaseNode, NodeDefinition, PortDefinition, ConfigField

STORAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage", "uploads"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

# Windows MAX_PATH is 260. Reserve space for extract_dir prefix + safety margin.
_MAX_FILENAME_LEN = 150


def _safe_filename(basename: str) -> str:
    """Truncate filename if it would exceed Windows MAX_PATH limit."""
    if len(basename) <= _MAX_FILENAME_LEN:
        return basename
    name, ext = os.path.splitext(basename)
    max_name = _MAX_FILENAME_LEN - len(ext)
    return name[:max_name] + ext


class InputImagesNode(BaseNode):
    @classmethod
    def definition(cls) -> NodeDefinition:
        return NodeDefinition(
            type="input_images",
            label="Image Loader",
            category="input",
            icon="Image",
            color="#3b82f6",
            description="Load images from a ZIP file or a local folder",
            inputs=[],
            outputs=[PortDefinition(name="output", label="Data")],
            config_fields=[
                ConfigField(
                    name="folder_path",
                    label="Folder Path (or leave empty to use ZIP)",
                    type="text",
                    required=False,
                    placeholder=r"D:\maps\scanned_images",
                    description="Absolute path to a folder containing images. "
                                "If set, ZIP file is ignored. "
                                "Scans for JPG, JPEG, PNG, TIFF, TIF, etc.",
                ),
                ConfigField(
                    name="file_id",
                    label="File (ZIP)",
                    type="file",
                    required=False,
                    accept=".zip",
                ),
                ConfigField(
                    name="scan_subfolders",
                    label="Scan Subfolders",
                    type="number",
                    default=0,
                    description="Set to 1 to also scan subfolders recursively",
                ),
                ConfigField(
                    name="max_images",
                    label="Max Images (0=all)",
                    type="number",
                    default=0,
                    description="Limit number of images to load. 0 = load all",
                ),
            ],
        )

    async def execute(self, inputs, config, on_progress=None, context=None):
        # Auto-detect: folder_path takes priority over ZIP
        folder_path = config.get("folder_path", "").strip()
        has_folder = bool(folder_path)
        has_zip = bool(config.get("file_id", ""))

        if has_folder:
            rows = self._load_from_folder(config)
            source_mode = "folder"
        elif has_zip:
            rows = self._load_from_zip(config)
            source_mode = "zip"
        else:
            raise ValueError(
                "No image source configured.\n"
                "Either enter a Folder Path or upload a ZIP file."
            )

        # Add image dimensions via Pillow
        try:
            from PIL import Image
            for row in rows:
                try:
                    with Image.open(row["file_path"]) as img:
                        row["width"] = img.width
                        row["height"] = img.height
                except Exception:
                    row["width"] = None
                    row["height"] = None
        except ImportError:
            for row in rows:
                row["width"] = None
                row["height"] = None

        df = pd.DataFrame(rows)

        max_images = int(config.get("max_images", 0))
        if max_images > 0:
            df = df.head(max_images)

        source_label = "folder" if source_mode == "folder" else "ZIP"
        if on_progress:
            await on_progress(f"Loaded {len(df)} images from {source_label}")
        return {"output": df}

    # ── ZIP mode ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_from_zip(config) -> list[dict]:
        file_id = config.get("file_id", "")
        if not file_id:
            raise ValueError("No ZIP file uploaded. Please upload a ZIP file in the node config.")
        filepath = os.path.join(STORAGE_DIR, file_id)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {file_id} (looked in {STORAGE_DIR})")

        if not zipfile.is_zipfile(filepath):
            raise ValueError("Uploaded file is not a valid ZIP archive")

        extract_dir = os.path.join(STORAGE_DIR, f"images_{uuid.uuid4().hex[:12]}")
        os.makedirs(extract_dir, exist_ok=True)

        rows = []
        with zipfile.ZipFile(filepath, "r") as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    continue
                ext = os.path.splitext(entry.filename)[1].lower()
                if ext not in IMAGE_EXTENSIONS:
                    continue
                original_name = os.path.basename(entry.filename)
                if not original_name:
                    continue
                basename = _safe_filename(original_name)
                target_path = os.path.join(extract_dir, basename)
                if os.path.exists(target_path):
                    name, extension = os.path.splitext(basename)
                    target_path = os.path.join(
                        extract_dir, f"{name}_{uuid.uuid4().hex[:6]}{extension}"
                    )
                    basename = os.path.basename(target_path)
                with zf.open(entry) as src, open(target_path, "wb") as dst:
                    dst.write(src.read())
                rows.append({
                    "filename": original_name,
                    "disk_filename": basename,
                    "file_path": os.path.abspath(target_path),
                    "extension": ext,
                    "size_bytes": os.path.getsize(target_path),
                })
        return rows

    # ── Folder mode ───────────────────────────────────────────────────────

    @staticmethod
    def _load_from_folder(config) -> list[dict]:
        folder_path = config.get("folder_path", "").strip().strip('"').strip("'")
        if not folder_path:
            raise ValueError(
                "No folder path specified. Enter the path to a folder containing images."
            )
        # Normalize: handle forward slashes, resolve .. etc.
        folder_path = os.path.normpath(folder_path)
        if not os.path.isdir(folder_path):
            raise FileNotFoundError(
                f"Folder not found: {folder_path}\n"
                f"Please check the path exists and is accessible."
            )

        raw_sub = config.get("scan_subfolders", 0)
        scan_subfolders = (int(raw_sub) != 0) if raw_sub else False

        rows = []
        if scan_subfolders:
            entries = []
            for root, _dirs, files in os.walk(folder_path):
                for fname in files:
                    entries.append(os.path.join(root, fname))
            entries.sort()
        else:
            entries = sorted(
                os.path.join(folder_path, f)
                for f in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, f))
            )

        for full_path in entries:
            fname = os.path.basename(full_path)
            ext = os.path.splitext(fname)[1].lower()
            if ext not in IMAGE_EXTENSIONS:
                continue
            abs_path = os.path.abspath(full_path)
            rows.append({
                "filename": fname,
                "disk_filename": fname,
                "file_path": abs_path,
                "extension": ext,
                "size_bytes": os.path.getsize(abs_path),
            })

        if not rows:
            raise ValueError(
                f"No image files found in: {folder_path}\n"
                f"Supported formats: {', '.join(sorted(IMAGE_EXTENSIONS))}"
            )

        return rows
