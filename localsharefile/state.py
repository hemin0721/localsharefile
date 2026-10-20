"""访问状态记录：历史目录、常用目录排序（持久化到 state.json）。

key 形如 "共享名/子目录相对路径"（根目录则仅为共享名）。
"""
import json
import threading
import time
from pathlib import Path

from . import config

MAX_RECENT = 50
MAX_TOP = 12


class ShareState:
    """线程安全的访问统计器；每次 record() 后立即落盘（数据量小，代价可忽略）。"""

    def __init__(self, path: Path = None):
        self.path = path or config.config_dir() / "state.json"
        self.lock = threading.Lock()
        self.visits: dict = {}      # key -> {"count": int, "last": epoch}
        self.recent: list = []      # 最近访问的 key，新的在前
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.visits = {k: v for k, v in (data.get("visits") or {}).items()
                               if isinstance(v, dict) and "count" in v}
                self.recent = [k for k in (data.get("recent") or []) if isinstance(k, str)]
        except (OSError, ValueError):
            pass   # 首次运行或文件损坏：从空状态开始

    def _save(self):
        """调用方必须已持有 self.lock。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"visits": self.visits, "recent": self.recent[:MAX_RECENT]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)      # 原子替换，避免断电写坏

    def record(self, key: str):
        with self.lock:
            item = self.visits.setdefault(key, {"count": 0, "last": 0})
            item["count"] += 1
            item["last"] = int(time.time())
            if key in self.recent:
                self.recent.remove(key)
            self.recent.insert(0, key)
            self.recent = self.recent[:MAX_RECENT]
            self._save()

    def count(self, key: str) -> int:
        with self.lock:
            return self.visits.get(key, {}).get("count", 0)

    def top(self, limit: int = MAX_TOP) -> list:
        """常用目录：按访问次数降序，返回 [(key, count)]。"""
        with self.lock:
            items = sorted(self.visits.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
            return [(k, v["count"]) for k, v in items[:limit]]

    def recent_keys(self, limit: int = 10) -> list:
        with self.lock:
            return list(self.recent[:limit])

    def last_time(self, key: str) -> int:
        with self.lock:
            return self.visits.get(key, {}).get("last", 0)

    def drop_share(self, share: str):
        """共享目录被删除时，清理其全部统计与历史记录。"""
        prefix = share + "/"
        with self.lock:
            self.visits = {k: v for k, v in self.visits.items()
                           if k != share and not k.startswith(prefix)}
            self.recent = [k for k in self.recent
                           if k != share and not k.startswith(prefix)]
            self._save()
