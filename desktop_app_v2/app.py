"""RGSSA Map Catalog Tool — PySide6 desktop app.

All processing local. Only a resized JPEG (~2MB) is sent to Qwen via the
DashScope SDK (local-file path). Original 400MB TIFs never leave the machine.

Worker thread -> Qt signals -> UI updates (thread-safe, no flaky bridge).
"""
import os, sys, json, time, tempfile, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from PySide6.QtCore import Qt, QObject, Signal, QThread, QTimer, QSize
from PySide6.QtGui import QPixmap, QFont, QImage, QImageReader
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit, QScrollArea,
    QFrame, QProgressBar, QStackedWidget, QSpinBox, QMessageBox, QSizePolicy,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QComboBox,
)

from pipeline import (QwenExtractor, scan_files, count_flagged, LIST_FIELDS,
                      compress_to_temp, REGIONS, DEFAULT_REGION)
from review_store import ReviewStore
from xlsx_writer import write_catalog

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "RgssaCatalog"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_WS = ""   # no hardcoded workspace — user enters their own

# ── Theme (Fluent-ish dark) ───────────────────────────────────────────
QSS = """
* {
    font-family: 'Segoe UI Variable', 'Segoe UI';
    color: #E6EDF5;
    outline: none;
}
QMainWindow, QWidget#root { background: #0F141C; }
QWidget { background: transparent; }
QFrame#card { background: #161D29; border: 1px solid #283344; border-radius: 10px; }
QLabel { background: transparent; }
QLabel#h1 { font-size: 24px; font-weight: 600; }
QLabel#h2 { font-size: 16px; font-weight: 600; }
QLabel#dim { color: #8B98AB; font-size: 13px; }
QLabel#tiny { color: #8B98AB; font-size: 11px; }

/* Inputs — all dark, no white anywhere */
QLineEdit, QSpinBox, QTextEdit, QPlainTextEdit, QAbstractSpinBox {
    background: #0B0F16;
    border: 1px solid #283344;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 14px;
    color: #E6EDF5;
    selection-background-color: #3B82F6;
    selection-color: white;
}
QLineEdit:focus, QSpinBox:focus, QTextEdit:focus, QAbstractSpinBox:focus {
    border: 1px solid #3B82F6;
    background: #0F141C;
}
QSpinBox::up-button, QSpinBox::down-button {
    background: #1F2937; border: none; width: 16px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #283344; }
QSpinBox::up-arrow { image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid #8B98AB; }
QSpinBox::down-arrow { image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #8B98AB; }
QComboBox {
    background: #0B0F16;
    border: 1px solid #283344;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 14px;
    color: #E6EDF5;
}
QComboBox:focus, QComboBox:hover { border: 1px solid #3B82F6; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow {
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid #8B98AB;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: #0F141C;
    border: 1px solid #283344;
    color: #E6EDF5;
    selection-background-color: #3B82F6;
    selection-color: white;
    outline: none;
}

QPushButton {
    border: none; border-radius: 6px; padding: 10px 16px; font-size: 13px;
    font-weight: 600; color: white;
}
QPushButton#primary { background: #3B82F6; }
QPushButton#primary:hover { background: #4C8DF7; }
QPushButton#primary:pressed { background: #2F6FE0; }
QPushButton#secondary { background: #232C3A; color: #E6EDF5; border: 1px solid #2E3A4D; }
QPushButton#secondary:hover { background: #2C374A; }
QPushButton#secondary:pressed { background: #1F2937; }
QPushButton#success { background: #22C55E; }
QPushButton#success:hover { background: #34D06E; }
QPushButton#danger { background: #EF4444; }
QPushButton#danger:hover { background: #F25C5C; }
QPushButton#warn { background: #EAB308; color: #1E293B; }
QPushButton#warn:hover { background: #F5C220; }
QPushButton:disabled { background: #1A222E; color: #4A5568; }

QTextEdit#log {
    background: #080B11; border: 1px solid #283344; border-radius: 6px;
    font-family: 'Cascadia Mono', Consolas; font-size: 11px; color: #8B98AB;
    padding: 8px;
}
QProgressBar {
    background: #0B0F16; border: 1px solid #283344; border-radius: 6px;
    min-height: 22px; max-height: 22px; text-align: center; color: #E6EDF5;
    font-size: 12px;
}
QProgressBar::chunk { background: #3B82F6; border-radius: 5px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#stat { background: #0B0F16; border-radius: 8px; }

/* Scrollbars — dark, thin */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2E3A4D; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3B4960; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: #2E3A4D; border-radius: 5px; min-width: 30px; }

QGraphicsView { border: none; }
QMessageBox { background: #161D29; }
QMessageBox QLabel { color: #E6EDF5; }

QLabel#pathbox {
    background: #0B0F16; border: 1px solid #283344; border-radius: 6px;
    padding: 9px 11px; color: #8B98AB; font-family: Consolas; font-size: 12px;
}
QLabel#pathbox[hasPath="true"] { color: #E6EDF5; border-color: #2E5A8C; }
QLabel#filenamebox {
    background: #0B0F16; border-radius: 6px; padding: 7px 9px;
    font-family: Consolas; font-size: 12px; color: #E6EDF5;
}
"""


# ── Worker: runs processing on a thread, emits signals ────────────────
class Worker(QObject):
    progress = Signal(int, int, int, int, float, list)  # done,total,flagged,errors,elapsed,inflight
    log = Signal(str, str)        # message, level
    finished = Signal(list)       # results
    failed_all = Signal(str)      # first error
    eta = Signal(float)           # estimated seconds remaining (dynamic)

    def __init__(self, files, in_dir, out_dir, api_key, ws, concurrency,
                 region=DEFAULT_REGION):
        super().__init__()
        self.files = files
        self.in_dir = Path(in_dir)
        self.out_dir = Path(out_dir)
        self.cache_dir = self.out_dir / "per_map_cache"
        self.api_key = api_key
        self.ws = ws
        self.region = region
        self.concurrency = max(1, min(10, concurrency))
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def cancel(self):
        self._cancel.set()

    def run(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="rgssa_"))
        extractor = QwenExtractor(self.api_key, self.ws, self.region)
        total = len(self.files)
        results = [None] * total
        done = [0]; errors = [0]; flagged = [0]
        inflight = set()
        t0 = time.time()

        completed_times = []  # actual per-map seconds, for dynamic ETA

        def report():
            with self._lock:
                self.progress.emit(done[0], total, flagged[0], errors[0],
                                   time.time() - t0, sorted(inflight))
                # Dynamic ETA from real throughput once a few maps complete.
                if completed_times and done[0] > 0:
                    mean = sum(completed_times) / len(completed_times)
                    remaining = total - done[0]
                    # remaining wall ≈ remaining/concurrency * mean (lanes in parallel)
                    eta = remaining / max(1, self.concurrency) * mean
                    self.eta.emit(eta)

        def process(idx, path):
            fn = path.name
            cache = self.cache_dir / (path.stem + ".json")
            if cache.exists():
                try:
                    r = json.loads(cache.read_text(encoding="utf-8"))
                    r["filename"] = fn; r["file_path"] = str(path)
                    self.log.emit(f"⏭ {fn} (cached)", "warn")
                    return idx, r
                except Exception:
                    pass
            if self._cancel.is_set():
                return idx, None
            with self._lock:
                inflight.add(fn)
            report()
            self.log.emit(f"→ {fn} starting…", "info")
            r = extractor.extract(
                path, tmp_dir, max_retries=6,
                on_retry=lambda f, a, w, e: self.log.emit(
                    f"⟳ {f}: retry {a} in {w:.0f}s — {str(e)[:90]}", "warn"),
                log=lambda m, lvl: self.log.emit(m, lvl if lvl in ("ok", "err", "warn") else "info"))
            with self._lock:
                inflight.discard(fn)
            try:
                cache.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return idx, r

        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            futs = {ex.submit(process, i, p): i for i, p in enumerate(self.files)}
            for fut in as_completed(futs):
                if self._cancel.is_set():
                    break
                idx, r = fut.result()
                if r is None:
                    continue
                results[idx] = r
                if r.get("ok"):
                    self.log.emit(f"✓ {r['filename']} ({r['elapsed_sec']:.0f}s)", "ok")
                    flagged[0] += count_flagged(r)
                    if r.get("elapsed_sec", 0) > 1:
                        completed_times.append(r["elapsed_sec"])
                else:
                    errors[0] += 1
                    self.log.emit(f"✗ {r['filename']}: {str(r.get('error',''))[:120]}", "err")
                done[0] += 1
                report()

        shutil.rmtree(tmp_dir, ignore_errors=True)
        final = [r for r in results if r is not None]
        ok = sum(1 for r in final if r.get("ok"))
        # Surface a failure list (copyable) if any failed
        failures = [r for r in final if not r.get("ok")]
        if failures:
            self.log.emit(f"━━━ {len(failures)} FAILED ━━━", "err")
            for r in failures:
                self.log.emit(f"  ✗ {r['filename']}  →  {str(r.get('error',''))[:200]}", "err")
        if ok == 0 and errors[0] > 0:
            first = next((r.get("error") for r in failures), "unknown")
            self.failed_all.emit(str(first))
        else:
            # Partial success is fine — proceed to review with the good ones.
            self.finished.emit(final)


def card() -> QFrame:
    f = QFrame(); f.setObjectName("card")
    return f


def tighten(layout, m=16, s=8):
    """Apply consistent margins/spacing so dark card bg shows, no white gaps."""
    layout.setContentsMargins(m, m, m, m)
    layout.setSpacing(s)
    return layout


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RGSSA Map Catalog Tool")
        self.resize(1180, 840)
        self.setStyleSheet(QSS)

        self.config = self._load_config()
        self.input_folder = self.config.get("last_input")
        self.output_folder = self.config.get("last_output")
        self.file_count = 0
        self.results = []
        self.store = None
        self.review_idx = 0
        self.final_xlsx = None
        self.worker = None
        self.worker_thread = None

        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(24, 24, 24, 24); outer.setSpacing(14)

        # Header
        outer.addWidget(self._mk_label("📚 RGSSA Map Catalog Tool", "h1"))
        outer.addWidget(self._mk_label(
            "All processing happens on your computer. Only resized thumbnails (~2 MB) go to the Qwen API.", "dim"))

        # Steps
        self.steps = []
        steps_row = QHBoxLayout(); steps_row.setSpacing(8)
        for i, name in enumerate(["1  Setup", "2  Process", "3  Review", "4  Done"]):
            s = QLabel(name); s.setObjectName("card")
            s.setAlignment(Qt.AlignCenter)
            s.setStyleSheet("padding:10px; border-radius:6px; background:#161D29; border:1px solid #283344; color:#8B98AB;")
            self.steps.append(s); steps_row.addWidget(s)
        outer.addLayout(steps_row)

        # Stacked views
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_setup())       # 0
        self.stack.addWidget(self._build_processing())  # 1
        self.stack.addWidget(self._build_review())       # 2
        self.stack.addWidget(self._build_done())         # 3

        self._refresh_from_config()
        self._set_step(1)
        self._update_start()

    # ── Config ────────────────────────────────────────────
    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
        except Exception:
            return {}

    def _save_config(self):
        try:
            CONFIG_DIR.mkdir(exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── Helpers ───────────────────────────────────────────
    def _mk_label(self, text, obj=None):
        lbl = QLabel(text)
        if obj:
            lbl.setObjectName(obj)
        lbl.setWordWrap(True)
        return lbl

    def _btn(self, text, obj, cb):
        b = QPushButton(text); b.setObjectName(obj); b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(cb)
        return b

    def _set_step(self, n):
        for i, s in enumerate(self.steps):
            if i + 1 < n:
                s.setStyleSheet("padding:10px;border-radius:6px;background:#22C55E;border:1px solid #22C55E;color:white;")
            elif i + 1 == n:
                s.setStyleSheet("padding:10px;border-radius:6px;background:#3B82F6;border:1px solid #3B82F6;color:white;")
            else:
                s.setStyleSheet("padding:10px;border-radius:6px;background:#161D29;border:1px solid #283344;color:#8B98AB;")

    # ── SETUP VIEW ─────────────────────────────────────────
    def _build_setup(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12); v.setContentsMargins(0, 0, 0, 0)

        # Resume card
        self.resume_card = card()
        rc = tighten(QHBoxLayout(self.resume_card))
        self.resume_label = QLabel("⚠ items pending review"); self.resume_label.setObjectName("h2")
        rc.addWidget(QLabel("⚠")); rc.addWidget(self.resume_label, 1)
        rc.addWidget(self._btn("Continue review", "warn", self._resume_review))
        self.resume_card.setVisible(False)
        v.addWidget(self.resume_card)

        # API key
        c1 = card(); l1 = tighten(QVBoxLayout(c1))
        l1.addWidget(self._mk_label("🔑 API key (one-time)", "h2"))
        l1.addWidget(self._mk_label("DashScope API key + workspace ID. Stored locally.", "dim"))
        l1.addWidget(self._mk_label("DashScope API key", "tiny"))
        self.api_key_edit = QLineEdit(); self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        l1.addWidget(self.api_key_edit)
        l1.addWidget(self._mk_label("Workspace ID", "tiny"))
        self.ws_edit = QLineEdit(DEFAULT_WS)
        self.ws_edit.setPlaceholderText("ws-...")
        l1.addWidget(self.ws_edit)
        l1.addWidget(self._mk_label("Region / endpoint  (choose the node closest to you)", "tiny"))
        self.region_combo = QComboBox()
        self._region_keys = list(REGIONS.keys())
        for k in self._region_keys:
            self.region_combo.addItem(REGIONS[k]["label"], k)
        self.region_combo.setCurrentIndex(self._region_keys.index(DEFAULT_REGION))
        l1.addWidget(self.region_combo)
        save_row = QHBoxLayout(); save_row.addWidget(self._btn("Save", "primary", self._save_api)); save_row.addStretch()
        l1.addLayout(save_row)
        v.addWidget(c1)

        # Folders
        c2 = card(); l2 = tighten(QVBoxLayout(c2))
        l2.addWidget(self._mk_label("📁 Folders", "h2"))
        l2.addWidget(self._mk_label("Input folder (maps)", "tiny"))
        self.input_lbl = QLabel("Not selected"); self.input_lbl.setObjectName("pathbox")
        self.input_lbl.setWordWrap(True)
        l2.addWidget(self.input_lbl)
        r1 = QHBoxLayout(); r1.addWidget(self._btn("Browse input…", "secondary", self._pick_input)); r1.addStretch()
        l2.addLayout(r1)
        l2.addWidget(self._mk_label("Output folder (catalog files)", "tiny"))
        self.output_lbl = QLabel("Defaults to input/_catalog_output"); self.output_lbl.setObjectName("pathbox")
        self.output_lbl.setWordWrap(True)
        l2.addWidget(self.output_lbl)
        r2 = QHBoxLayout()
        r2.addWidget(self._btn("Browse output…", "secondary", self._pick_output))
        r2.addWidget(self._btn("Use default", "secondary", self._default_output))
        r2.addStretch()
        l2.addLayout(r2)
        # Advanced
        adv = QHBoxLayout()
        adv.addWidget(self._mk_label("Test mode (first N, 0=all):", "tiny"))
        self.test_limit = QSpinBox(); self.test_limit.setRange(0, 99999); self.test_limit.setValue(0)
        self.test_limit.setFixedWidth(90); self.test_limit.valueChanged.connect(self._update_start)
        adv.addWidget(self.test_limit)
        adv.addSpacing(20)
        adv.addWidget(self._mk_label("Concurrency (max 10):", "tiny"))
        self.concurrency = QSpinBox(); self.concurrency.setRange(1, 10)
        self.concurrency.setValue(self.config.get("concurrency", 7)); self.concurrency.setFixedWidth(70)
        self.concurrency.valueChanged.connect(self._update_start)
        adv.addWidget(self.concurrency); adv.addStretch()
        l2.addSpacing(8); l2.addLayout(adv)
        v.addWidget(c2)

        # Start
        c3 = card(); l3 = tighten(QVBoxLayout(c3))
        sr = QHBoxLayout()
        self.start_btn = self._btn("▶  Start processing", "primary", self._start)
        self.start_btn.setEnabled(False); sr.addWidget(self.start_btn); sr.addStretch()
        l3.addLayout(sr)
        self.start_hint = self._mk_label("Save API key and pick an input folder.", "tiny")
        l3.addWidget(self.start_hint)
        v.addWidget(c3)
        v.addStretch()

        scroll.setWidget(w)
        return scroll

    def _refresh_from_config(self):
        if self.config.get("api_key"):
            self.api_key_edit.setText(self.config["api_key"])
        self.ws_edit.setText(self.config.get("workspace_id", DEFAULT_WS))
        saved_region = self.config.get("region", DEFAULT_REGION)
        if saved_region in self._region_keys:
            self.region_combo.setCurrentIndex(self._region_keys.index(saved_region))
        if self.input_folder and Path(self.input_folder).is_dir():
            self.file_count = len(scan_files(self.input_folder))
            self.input_lbl.setText(f"{self.input_folder}   ·   {self.file_count} files")
            self.input_lbl.setProperty("hasPath", True)
        self.input_lbl.style().polish(self.input_lbl)
        if self.output_folder:
            self.output_lbl.setText(self.output_folder)
            self._check_resume()

    def _save_api(self):
        key = self.api_key_edit.text().strip(); ws = self.ws_edit.text().strip()
        if not key or not ws:
            QMessageBox.warning(self, "Missing", "Enter both API key and Workspace ID."); return
        region = self.region_combo.currentData()
        self.config["api_key"] = key; self.config["workspace_id"] = ws
        self.config["region"] = region
        self._save_config(); self._update_start()
        QMessageBox.information(self, "Saved",
            f"API key saved.\nRegion: {REGIONS[region]['label']}")

    def _pick_input(self):
        d = QFileDialog.getExistingDirectory(self, "Select map folder")
        if not d: return
        self.input_folder = d; self.file_count = len(scan_files(d))
        self.input_lbl.setText(f"{d}   ·   {self.file_count} files")
        self.input_lbl.setProperty("hasPath", True)
        self.input_lbl.style().polish(self.input_lbl)
        self.config["last_input"] = d; self._save_config()
        if not self.output_folder:
            self._default_output()
        self._update_start()

    def _pick_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if not d: return
        self.output_folder = d; self.output_lbl.setText(d)
        self.config["last_output"] = d; self._save_config()
        self._check_resume(); self._update_start()

    def _default_output(self):
        if not self.input_folder:
            QMessageBox.warning(self, "No input", "Pick input folder first."); return
        self.output_folder = str(Path(self.input_folder) / "_catalog_output")
        self.output_lbl.setText(self.output_folder + "  (default)")
        self.config["last_output"] = self.output_folder; self._save_config()
        self._check_resume(); self._update_start()

    def _check_resume(self):
        if not self.output_folder:
            self.resume_card.setVisible(False); return
        has, pending, decided, total = ReviewStore.peek(self.output_folder)
        if has and pending > 0:
            self.resume_card.setVisible(True)
            self.resume_label.setText(f"⚠ {pending} items pending review  ·  {decided}/{total} decided")
        else:
            self.resume_card.setVisible(False)

    def _update_start(self):
        if not self.config.get("api_key"):
            self.start_btn.setEnabled(False); self.start_hint.setText("Save API key first."); return
        if not self.input_folder:
            self.start_btn.setEnabled(False); self.start_hint.setText("Pick input folder."); return
        if not self.output_folder:
            self.start_btn.setEnabled(False); self.start_hint.setText("Pick or use default output."); return
        if self.file_count == 0:
            self.start_btn.setEnabled(False); self.start_hint.setText("No map files in input folder."); return
        self.start_btn.setEnabled(True)
        limit = self.test_limit.value(); conc = self.concurrency.value()
        n = min(limit, self.file_count) if limit > 0 else self.file_count
        self.start_hint.setText(
            f"Ready: {n} maps × Qwen 3.7-plus ({conc} parallel). "
            f"Estimated time: {self._estimate_time(n, conc)}")

    @staticmethod
    def _estimate_time(n: int, conc: int) -> str:
        """Initial estimate from measured data (refined live by dynamic ETA).

        Real measurements (qwen3.7-plus thinking, 9 RGSSA maps): per-map times
        55–226 s, mean ≈ 105 s. The API handles up to ~10 concurrent requests
        in parallel reliably, so within that range speedup is ~linear. Wall
        time ≈ ceil(n/conc) lanes, each running mean per map, + ~10% tail for
        the slowest map in the last batch."""
        PER_MAP = 105.0
        lanes = max(1, min(conc, 10))
        secs = (n / lanes) * PER_MAP * 1.1
        if secs < 90:
            return f"~{round(secs)} sec"
        mins = secs / 60
        if mins < 60:
            return f"~{round(mins)} min"
        return f"~{mins/60:.1f} hr"

    # ── PROCESSING VIEW ────────────────────────────────────
    def _build_processing(self):
        w = QWidget(); v = QVBoxLayout(w)
        c = card(); cl = tighten(QVBoxLayout(c))
        cl.addWidget(self._mk_label("⚙  Processing maps…", "h2"))
        pr = QHBoxLayout()
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.progress.setTextVisible(False)  # no built-in %, we show our own
        pr.addWidget(self.progress)
        self.pct_lbl = QLabel("0%"); self.pct_lbl.setFixedWidth(50)
        self.pct_lbl.setStyleSheet("font-size:14px;font-weight:600;")
        self.pct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pr.addWidget(self.pct_lbl)
        cl.addLayout(pr)
        meta = QHBoxLayout()
        self.proc_text = self._mk_label("Starting…", "tiny"); meta.addWidget(self.proc_text)
        meta.addStretch()
        self.proc_time = self._mk_label("", "tiny"); meta.addWidget(self.proc_time)
        cl.addLayout(meta)
        # stats
        stats = QHBoxLayout(); self.stat_vals = {}
        for key, label, color in [("done", "DONE", "#22C55E"), ("total", "TOTAL", "#E6EDF5"),
                                   ("flagged", "TO REVIEW", "#EAB308"), ("errors", "ERRORS", "#EF4444")]:
            f = QFrame(); f.setObjectName("stat"); fl = QVBoxLayout(f)
            fl.addWidget(self._mk_label(label, "tiny"))
            val = QLabel("0"); val.setStyleSheet(f"font-size:20px;font-weight:600;color:{color};")
            fl.addWidget(val); self.stat_vals[key] = val; stats.addWidget(f)
        cl.addSpacing(10); cl.addLayout(stats)
        # log header + copy button
        log_head = QHBoxLayout()
        log_head.addWidget(self._mk_label("Detailed log (for debugging / sharing)", "tiny"))
        log_head.addStretch()
        log_head.addWidget(self._btn("📋 Copy log", "secondary", self._copy_log))
        log_head.addWidget(self._btn("Save log…", "secondary", self._save_log))
        cl.addLayout(log_head)
        self.log_box = QTextEdit(); self.log_box.setObjectName("log"); self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(220)
        cl.addWidget(self.log_box, 1)
        # cancel
        cr = QHBoxLayout()
        self.cancel_btn = self._btn("Cancel", "danger", self._cancel_or_back); cr.addWidget(self.cancel_btn); cr.addStretch()
        cl.addLayout(cr)
        v.addWidget(c)
        return w

    def _copy_log(self):
        QApplication.clipboard().setText(self.log_box.toPlainText())
        self.proc_text.setText("Log copied to clipboard ✓")

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save log", "rgssa_log.txt", "Text (*.txt)")
        if path:
            try:
                Path(path).write_text(self.log_box.toPlainText(), encoding="utf-8")
                self.proc_text.setText(f"Log saved: {path}")
            except Exception as e:
                QMessageBox.warning(self, "Save failed", str(e))

    def _log(self, msg, level):
        colors = {"ok": "#22C55E", "err": "#EF4444", "warn": "#EAB308", "info": "#8B98AB"}
        self.log_box.append(f'<span style="color:{colors.get(level, "#8B98AB")}">{msg}</span>')
        sb = self.log_box.verticalScrollBar(); sb.setValue(sb.maximum())

    def _start(self):
        self.stack.setCurrentIndex(1); self._set_step(2)
        self.log_box.clear(); self.progress.setValue(0); self.pct_lbl.setText("0%")
        for k in self.stat_vals: self.stat_vals[k].setText("0")
        limit = self.test_limit.value(); conc = self.concurrency.value()
        self.config["concurrency"] = conc; self._save_config()
        Path(self.output_folder).mkdir(parents=True, exist_ok=True)
        files = scan_files(self.input_folder, limit)
        self.stat_vals["total"].setText(str(len(files)))
        region = self.config.get("region", DEFAULT_REGION)
        self._log(f"Output: {self.output_folder}  ·  {conc} parallel  ·  "
                  f"region={REGIONS[region]['label']}", "info")

        self.worker = Worker(files, self.input_folder, self.output_folder,
                             self.config["api_key"], self.config.get("workspace_id", DEFAULT_WS),
                             conc, region)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._log)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed_all.connect(self._on_failed_all)
        self.worker.eta.connect(self._on_eta)
        self.worker_thread.started.connect(self.worker.run)
        self.cancel_btn.setText("Cancel")
        # Show the initial estimate until real ETA data arrives
        n = len(files); conc = self.concurrency.value()
        self.proc_time.setText(f"Est. {self._estimate_time(n, conc)} remaining")
        self.worker_thread.start()

    def _on_progress(self, done, total, flagged, errors, elapsed, inflight):
        pct = round(100 * done / total) if total else 0
        self.progress.setValue(pct); self.pct_lbl.setText(f"{pct}%")
        if inflight:
            self.proc_text.setText(f"{done} / {total} done  ·  {len(inflight)} in progress")
        else:
            self.proc_text.setText(f"{done} / {total} done")
        self.stat_vals["done"].setText(str(done))
        self.stat_vals["flagged"].setText(str(flagged))
        self.stat_vals["errors"].setText(str(errors))

    def _on_eta(self, secs):
        """Dynamic remaining-time estimate from real throughput."""
        if secs < 90:
            txt = f"~{round(secs)} sec remaining"
        elif secs < 3600:
            txt = f"~{round(secs/60)} min remaining"
        else:
            txt = f"~{secs/3600:.1f} hr remaining"
        self.proc_time.setText(txt)

    def _cleanup_thread(self):
        if self.worker_thread:
            self.worker_thread.quit(); self.worker_thread.wait(2000)
            self.worker_thread = None

    def _on_finished(self, results):
        self._cleanup_thread()
        self.results = results
        ok = sum(1 for r in results if r.get("ok"))
        err = len(results) - ok
        self._log(f"━━━ Done: {ok} ok, {err} errors ━━━", "ok")
        self.store = ReviewStore(self.output_folder)
        self.store.build_queue(results)
        if self.store.pending > 0:
            self._enter_review()
        else:
            self._write_xlsx()
            self._goto_done("✓ Done — nothing flagged",
                            f"{ok} maps, {err} errors. Catalog: {self.final_xlsx}")

    def _on_failed_all(self, first_err):
        self._cleanup_thread()
        self._log(f"━━━ All maps failed. ━━━", "err")
        self._log(f"First error: {first_err}", "err")
        self.proc_text.setText("All failed — fix and retry")
        self.cancel_btn.setText("← Back to setup")
        QMessageBox.critical(self, "Processing failed",
            f"All maps failed.\n\nFirst error:\n{first_err}\n\n"
            "Fix the issue (API key / network) and Start again. "
            "Successful maps are cached.")

    def _cancel_or_back(self):
        if self.worker and not self.worker._cancel.is_set() and self.worker_thread and self.worker_thread.isRunning():
            self.worker.cancel()
            self._log("⚠ Cancelling, finishing in-flight maps…", "warn")
        else:
            self.stack.setCurrentIndex(0); self._set_step(1); self._check_resume(); self._update_start()

    # ── REVIEW VIEW ────────────────────────────────────────
    def _build_review(self):
        w = QWidget(); v = QVBoxLayout(w)
        c = card(); cl = tighten(QVBoxLayout(c))
        top = QHBoxLayout()
        top.addWidget(self._mk_label("🔍  Review flagged items", "h2")); top.addStretch()
        self.review_prog = self._mk_label("Item 1 of N", "tiny"); top.addWidget(self.review_prog)
        cl.addLayout(top)
        cl.addWidget(self._mk_label(
            "The AI couldn't find direct evidence for these. Confirm, Remove, or edit. "
            "Decisions save automatically — resume any time.", "dim"))

        body = QHBoxLayout()
        # Image (QGraphicsView for proper zoom/pan)
        img_card = card(); icl = tighten(QVBoxLayout(img_card))
        icl.addWidget(self._mk_label("MAP PREVIEW", "tiny"))
        self.review_fn = QLabel("—"); self.review_fn.setObjectName("filenamebox")
        self.review_fn.setWordWrap(True)
        icl.addWidget(self.review_fn)
        self.gview = ZoomView()
        self.gview.setMinimumHeight(340)
        icl.addWidget(self.gview, 1)
        ic_btns = QHBoxLayout()
        ic_btns.addWidget(self._btn("🔍 +", "secondary", lambda: self.gview.zoom_by(1.25)))
        ic_btns.addWidget(self._btn("🔍 −", "secondary", lambda: self.gview.zoom_by(0.8)))
        ic_btns.addWidget(self._btn("Fit", "secondary", self.gview.reset_zoom))
        ic_btns.addWidget(self._btn("Open in OS", "secondary", self._open_source))
        ic_btns.addStretch()
        icl.addLayout(ic_btns)
        icl.addWidget(self._mk_label("Full-resolution scan · scroll to zoom · drag to pan", "tiny"))
        body.addWidget(img_card, 5)

        # Decision panel
        dec_card = card(); dcl = tighten(QVBoxLayout(dec_card))
        dcl.addWidget(self._mk_label("AI FLAGGED THIS", "tiny"))
        info = QGridLayout()
        info.addWidget(self._mk_label("Field", "dim"), 0, 0)
        self.rev_field = QLabel("—"); self.rev_field.setStyleSheet("font-weight:600;")
        info.addWidget(self.rev_field, 0, 1)
        info.addWidget(self._mk_label("AI value", "dim"), 1, 0)
        self.rev_value = QLabel("—"); self.rev_value.setStyleSheet("font-weight:600;"); self.rev_value.setWordWrap(True)
        info.addWidget(self.rev_value, 1, 1)
        dcl.addLayout(info)
        ev = card(); ev.setStyleSheet("background:#0F141C;border-left:3px solid #EAB308;border-radius:4px;")
        evl = QVBoxLayout(ev); evl.addWidget(self._mk_label("AI REASONING", "tiny"))
        self.rev_evidence = QLabel("—"); self.rev_evidence.setWordWrap(True); self.rev_evidence.setStyleSheet("font-size:12px;")
        evl.addWidget(self.rev_evidence)
        dcl.addWidget(ev)
        dcl.addWidget(self._mk_label("YOUR DECISION", "tiny"))
        drow = QHBoxLayout()
        drow.addWidget(self._btn("✓ Confirm", "success", lambda: self._decide("confirm")))
        drow.addWidget(self._btn("✗ Remove", "danger", lambda: self._decide("remove")))
        dcl.addLayout(drow)
        dcl.addWidget(self._mk_label("Edit value (optional)", "tiny"))
        self.edit_value = QLineEdit(); self.edit_value.returnPressed.connect(self._save_edit)
        dcl.addWidget(self.edit_value)
        dcl.addWidget(self._mk_label("Notes (optional)", "tiny"))
        self.edit_note = QTextEdit(); self.edit_note.setMaximumHeight(56)
        dcl.addWidget(self.edit_note)
        dcl.addWidget(self._btn("Save edit & next", "primary", self._save_edit))
        nav = QHBoxLayout()
        nav.addWidget(self._btn("← Prev", "secondary", self._prev))
        nav.addWidget(self._btn("Skip", "secondary", self._next))
        nav.addWidget(self._btn("Next →", "secondary", self._next))
        dcl.addLayout(nav)
        dcl.addStretch()
        body.addWidget(dec_card, 4)
        cl.addLayout(body, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(self._btn("⏸ Pause (saved)", "secondary", self._pause_review))
        bottom.addWidget(self._btn("✓ Export final catalog", "success", self._export))
        bottom.addStretch()
        cl.addLayout(bottom)
        v.addWidget(c)
        return w

    def _enter_review(self):
        self.stack.setCurrentIndex(2); self._set_step(3)
        self.review_idx = next((i for i, q in enumerate(self.store.queue)
                                if self.store.get_decision(q["key"]) is None), 0)
        self._show_item()

    def _resume_review(self):
        if not self.output_folder: return
        # Load cached results (used for xlsx export) if available.
        results = []
        cache_dir = Path(self.output_folder) / "per_map_cache"
        if cache_dir.exists():
            for f in sorted(cache_dir.glob("*.json")):
                try: results.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception: pass
        self.results = results
        self.store = ReviewStore(self.output_folder)
        # Prefer the saved queue from review_state.json (survives cache loss).
        if self.store.load_saved():
            # If we also have fresh cache, rebuild to pick up any new items,
            # but keep decisions. Only rebuild when cache covers the queue.
            if results:
                saved_decisions = dict(self.store.decisions)
                self.store.build_queue(results)
                # build_queue reloads decisions from disk; merge to be safe
                self.store.decisions.update(saved_decisions)
        else:
            self.store.build_queue(results)
        if not self.store.queue:
            QMessageBox.information(self, "Nothing to review",
                "No saved review items found. Process a folder first.")
            self.stack.setCurrentIndex(0); self._set_step(1)
            return
        self._enter_review()

    def _show_item(self):
        if not self.store or not self.store.queue:
            self.rev_field.setText("(no items)"); return
        it = self.store.queue[self.review_idx]
        self.rev_field.setText(it["field"])
        self.rev_value.setText(it["ai_value"])
        self.rev_evidence.setText(it["ai_evidence"] or "—")
        self.review_fn.setText(it["filename"])
        self.edit_value.clear(); self.edit_note.clear()
        dec = self.store.get_decision(it["key"])
        if dec:
            if dec.get("value"): self.edit_value.setText(dec["value"])
            if dec.get("note"): self.edit_note.setText(dec["note"])
        total = len(self.store.queue)
        self.review_prog.setText(f"Item {self.review_idx+1} of {total} · {self.store.decided}/{total} decided")
        self.gview.load_image(it["file_path"], hd=True)  # full-resolution by default

    def _decide(self, action):
        if not self.store or not self.store.queue: return
        it = self.store.queue[self.review_idx]
        self.store.set_decision(it["key"], {"action": action, "note": self.edit_note.toPlainText().strip()})
        self._next()

    def _save_edit(self):
        if not self.store or not self.store.queue: return
        it = self.store.queue[self.review_idx]
        nv = self.edit_value.text().strip()
        action = "edit" if nv else "confirm"
        self.store.set_decision(it["key"], {"action": action, "value": nv or it["ai_value"],
                                            "note": self.edit_note.toPlainText().strip()})
        self._next()

    def _next(self):
        if self.store and self.review_idx < len(self.store.queue) - 1:
            self.review_idx += 1
        self._show_item()

    def _prev(self):
        if self.review_idx > 0:
            self.review_idx -= 1
        self._show_item()

    def _open_source(self):
        if self.store and self.store.queue:
            os.startfile(self.store.queue[self.review_idx]["file_path"])

    def _pause_review(self):
        self.stack.setCurrentIndex(0); self._set_step(1); self._check_resume()

    def _export(self):
        self._write_xlsx()
        pending = self.store.pending if self.store else 0
        self._goto_done("✓ Final catalog exported",
                        f"{len(self.results)} maps. {pending} items still pending.\n{self.final_xlsx}")

    def _write_xlsx(self):
        self.final_xlsx = str(Path(self.output_folder) / "rgssa_catalog.xlsx")
        try:
            write_catalog(self.results, self.store, self.final_xlsx)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    # ── DONE VIEW ──────────────────────────────────────────
    def _build_done(self):
        w = QWidget(); v = QVBoxLayout(w)
        c = card(); cl = tighten(QVBoxLayout(c))
        self.done_icon = QLabel("✓"); self.done_icon.setAlignment(Qt.AlignCenter)
        self.done_icon.setStyleSheet("font-size:48px;")
        cl.addWidget(self.done_icon)
        self.done_msg = QLabel("Catalog exported"); self.done_msg.setAlignment(Qt.AlignCenter)
        self.done_msg.setStyleSheet("font-size:16px;")
        cl.addWidget(self.done_msg)
        self.done_sum = QLabel(""); self.done_sum.setAlignment(Qt.AlignCenter); self.done_sum.setWordWrap(True)
        self.done_sum.setObjectName("dim")
        cl.addWidget(self.done_sum)
        br = QHBoxLayout(); br.addStretch()
        br.addWidget(self._btn("📥 Open xlsx", "primary", self._open_xlsx))
        br.addWidget(self._btn("Process another folder", "secondary", self._restart))
        br.addStretch()
        cl.addSpacing(12); cl.addLayout(br)
        v.addWidget(c); v.addStretch()
        return w

    def _goto_done(self, msg, summary):
        self.stack.setCurrentIndex(3); self._set_step(4)
        self.done_msg.setText(msg); self.done_sum.setText(summary)

    def _open_xlsx(self):
        if self.final_xlsx and Path(self.final_xlsx).exists():
            os.startfile(self.final_xlsx)

    def _restart(self):
        self.stack.setCurrentIndex(0); self._set_step(1); self._check_resume()


# ── Async image loader (keeps UI responsive) ──────────────────────────
class _ImgLoader(QThread):
    loaded = Signal(QImage, str)  # image, path

    def __init__(self, path, hd):
        super().__init__()
        self.path = path; self.hd = hd

    def run(self):
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            # Cap to 5000px long side — full detail for reading handwriting,
            # but avoids decoding a 100-megapixel TIF straight into RAM.
            cap = 5000 if self.hd else 2000
            sz = reader.size()
            if sz.isValid() and max(sz.width(), sz.height()) > cap:
                if sz.width() >= sz.height():
                    reader.setScaledSize(QSize(cap, int(cap * sz.height() / sz.width())))
                else:
                    reader.setScaledSize(QSize(int(cap * sz.width() / sz.height()), cap))
            img = reader.read()
            self.loaded.emit(img, self.path)
        except Exception:
            self.loaded.emit(QImage(), self.path)


# ── Zoomable graphics view ────────────────────────────────────────────
class ZoomView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setStyleSheet("background:#0B0F16;border-radius:6px;")
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._item = None
        self._path = None
        self._loader = None
        # Loading placeholder
        self._placeholder = self.scene().addText("")

    def load_image(self, path, hd=False):
        self._path = path
        # Show a quick "loading" hint, then load off-thread
        self.scene().clear()
        ph = self.scene().addText("Loading preview…")
        ph.setDefaultTextColor(Qt.gray)
        self._item = None
        # Cancel any in-flight load
        if self._loader and self._loader.isRunning():
            self._loader.requestInterruption()
        self._loader = _ImgLoader(path, hd)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.start()

    def _on_loaded(self, img, path):
        if path != self._path or img.isNull():
            return
        pix = QPixmap.fromImage(img)
        self.scene().clear()
        self._item = self.scene().addPixmap(pix)
        self.scene().setSceneRect(pix.rect())
        self.reset_zoom()

    def reset_zoom(self):
        self.resetTransform()
        if self._item:
            self.fitInView(self._item, Qt.KeepAspectRatio)

    def zoom_by(self, factor):
        if self._item:
            self.scale(factor, factor)

    def wheelEvent(self, e):
        self.zoom_by(1.18 if e.angleDelta().y() > 0 else 0.85)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI Variable", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
