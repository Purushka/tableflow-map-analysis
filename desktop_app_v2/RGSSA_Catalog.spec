# PyInstaller spec — RGSSA Catalog Tool (one-file, windowed)
# Build with:  pyinstaller --noconfirm RGSSA_Catalog.spec
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# dashscope ships data files (version, configs) + dynamic submodules
for pkg in ("dashscope",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# extra safety nets
hiddenimports += collect_submodules("openpyxl")
hiddenimports += ["PIL._tkinter_finder"]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # trim weight: NONE of these are used by this app. They get dragged in
    # only because they happen to live in the global site-packages and appear
    # in some transitive import graph. Excluding them takes the build from
    # ~349 MB down to <100 MB.
    excludes=[
        # heavy ML / data stacks (not used at all)
        "torch", "torchvision", "torchaudio",
        "cv2", "opencv-python",
        "numpy", "scipy", "pandas", "pyarrow",
        "sklearn", "scikit-learn",
        "transformers", "tokenizers", "huggingface_hub", "hf_xet", "safetensors",
        "matplotlib", "sympy", "numba", "llvmlite",
        "tensorflow", "jax", "jaxlib", "onnx", "onnxruntime",
        # GUI/test cruft
        "tkinter", "test", "tests", "unittest",
        # unused Qt modules (keep Core/Gui/Widgets only)
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner",
        "PySide6.QtHelp", "PySide6.QtUiTools",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="RGSSA Catalog Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # windowed (no console popup)
    disable_windowed_traceback=False,
    icon=None,              # set to "icon.ico" if you add one
)
