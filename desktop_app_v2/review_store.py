"""Review queue + decision persistence (resume-friendly)."""
import json
from pathlib import Path
from pipeline import LIST_FIELDS


class ReviewStore:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.state_path = self.output_dir / "review_state.json"
        self.queue: list[dict] = []
        self.decisions: dict[str, dict] = {}

    def build_queue(self, results: list[dict]):
        self.queue = []
        for r in results:
            if not r.get("ok"):
                continue
            meta = r.get("metadata", {})
            for field in LIST_FIELDS:
                for it in meta.get(field, []) or []:
                    if not isinstance(it, dict):
                        continue
                    if it.get("category", "").upper() != "INFERRED":
                        continue
                    self.queue.append({
                        "key": f"{r['filename']}|{field}|{it['value']}",
                        "filename": r["filename"],
                        "file_path": r["file_path"],
                        "field": field,
                        "ai_value": it["value"],
                        "ai_evidence": it.get("evidence", ""),
                    })
        self.load_decisions()

    @property
    def pending(self) -> int:
        return sum(1 for q in self.queue if q["key"] not in self.decisions)

    @property
    def decided(self) -> int:
        return sum(1 for q in self.queue if q["key"] in self.decisions)

    def set_decision(self, key: str, decision: dict):
        self.decisions[key] = decision
        self.save()

    def get_decision(self, key: str) -> dict | None:
        return self.decisions.get(key)

    def load_decisions(self):
        if not self.state_path.exists():
            self.decisions = {}
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.decisions = data.get("decisions", {})
        except Exception:
            self.decisions = {}

    def load_saved(self) -> bool:
        """Load queue + decisions directly from review_state.json (for resume),
        independent of the per-map cache. Returns True if a saved queue exists."""
        if not self.state_path.exists():
            return False
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.queue = data.get("queue", []) or []
            self.decisions = data.get("decisions", {}) or {}
            return len(self.queue) > 0
        except Exception:
            return False

    def save(self):
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps({"queue": self.queue, "decisions": self.decisions},
                           indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def peek(output_dir: str):
        """Return (has, pending, decided, total) for the resume card."""
        p = Path(output_dir) / "review_state.json"
        if not p.exists():
            return (False, 0, 0, 0)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            q = data.get("queue", [])
            d = data.get("decisions", {})
            total = len(q)
            decided = sum(1 for x in q if x["key"] in d)
            return (total > 0, total - decided, decided, total)
        except Exception:
            return (False, 0, 0, 0)
