"""Small JSON-file stores kept in the data directory."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional


def ensure_private_dir(path: os.PathLike | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


class JsonFile:
    """JSON file with atomic writes (0600 temp file + os.replace)."""

    def __init__(self, path: os.PathLike | str, default: Any) -> None:
        self.path = Path(path)
        self.default = default

    def read(self) -> Any:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return copy.deepcopy(self.default)

    def write(self, data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


class HistoryStore:
    """Recent messages, kept separately per business connection and chat."""

    def __init__(self, path: os.PathLike | str, limit: int) -> None:
        self.file = JsonFile(path, {})
        self.limit = limit
        data = self.file.read()
        self.data: Dict[str, List[Dict[str, Any]]] = data if isinstance(data, dict) else {}

    @staticmethod
    def key(connection_id: str, chat_id: int) -> str:
        return f"{connection_id}:{chat_id}"

    def get(self, connection_id: str, chat_id: int) -> List[Dict[str, Any]]:
        return list(self.data.get(self.key(connection_id, chat_id), []))

    def add(
        self,
        connection_id: str,
        chat_id: int,
        *,
        role: str,
        name: str,
        text: str,
        lang: Optional[str],
        ts: float,
    ) -> None:
        items = self.data.setdefault(self.key(connection_id, chat_id), [])
        items.append({"role": role, "name": name, "text": text, "lang": lang, "ts": ts})
        if len(items) > self.limit:
            del items[: len(items) - self.limit]
        self.file.write(self.data)

    def last_language(self, connection_id: str, chat_id: int) -> Optional[str]:
        for item in reversed(self.data.get(self.key(connection_id, chat_id), [])):
            if item.get("role") == "other" and item.get("lang"):
                return item["lang"]
        return None

    def chat_count(self) -> int:
        return len(self.data)


class SeenMessages:
    """Remembers processed message keys so duplicates are caught even after a restart."""

    def __init__(self, path: os.PathLike | str, capacity: int = 5000) -> None:
        self.file = JsonFile(path, [])
        self.capacity = capacity
        data = self.file.read()
        self.keys: "OrderedDict[str, None]" = OrderedDict(
            (str(k), None) for k in (data if isinstance(data, list) else [])
        )

    def first_time(self, key: str) -> bool:
        if key in self.keys:
            return False
        self.keys[key] = None
        while len(self.keys) > self.capacity:
            self.keys.popitem(last=False)
        self.file.write(list(self.keys))
        return True


class RuntimeState:
    """Pause flag and usage-limit deadline, persisted across restarts."""

    def __init__(self, path: os.PathLike | str) -> None:
        self.file = JsonFile(path, {})
        data = self.file.read()
        self._data: Dict[str, Any] = data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self.file.write(self._data)

    @property
    def paused(self) -> bool:
        return bool(self._data.get("paused", False))

    @paused.setter
    def paused(self, value: bool) -> None:
        self._data["paused"] = bool(value)
        self._save()

    @property
    def limit_until(self) -> Optional[float]:
        value = self._data.get("limit_until")
        return float(value) if isinstance(value, (int, float)) else None

    @limit_until.setter
    def limit_until(self, value: Optional[float]) -> None:
        self._data["limit_until"] = value
        self._save()
