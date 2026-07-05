"""索引管理模块 - 维护 _index.json

功能:
  - 索引增删查改
  - 损坏备份恢复(FR-013a):检测 JSONDecodeError → 备份 → 重建空索引 → structlog 记录
  - fetch_backend 字段(FR-012):记录每条剪藏的抓取后端
  - 去重判定(FR-010):URL 为主要身份,content_hash 为次要身份
"""

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from clipper.logging import get_logger

_log = get_logger("clipper.indexer")

_EMPTY_INDEX = {"pages": [], "total": 0, "last_updated": ""}


class Indexer:
    """维护剪藏索引文件"""

    def __init__(self, base_dir: str, index_filename: str = "_index.json"):
        self.base_dir = Path(base_dir)
        self.index_file = self.base_dir / index_filename
        self._ensure_index()

    def _ensure_index(self) -> None:
        """确保索引文件存在且有效。损坏时备份并重建(FR-013a)。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            self._write(_EMPTY_INDEX)
            return
        # 文件存在,验证有效性(_read 会处理损坏恢复)
        self._read()

    def _read(self) -> dict[str, Any]:
        """读取索引文件。损坏时备份并重建空索引(FR-013a)。"""
        try:
            with open(self.index_file, encoding="utf-8") as f:
                return cast(dict[str, Any], json.load(f))
        except FileNotFoundError:
            return dict(_EMPTY_INDEX)
        except json.JSONDecodeError:
            return self._recover_from_corruption()

    def _recover_from_corruption(self) -> dict[str, Any]:
        """备份损坏的索引并重建空索引(FR-013a)。

        1. 重命名损坏文件为 _index.json.corrupted.{timestamp}
        2. 写入新的空索引
        3. structlog 记录恢复事件
        4. 向用户输出提示
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.index_file.parent / f"{self.index_file.name}.corrupted.{timestamp}"
        backup_used: Path | None = None
        try:
            self.index_file.rename(backup_path)
            backup_used = backup_path
        except Exception as e:
            _log.error("corruption_backup_failed", error=str(e))

        self._write(_EMPTY_INDEX)
        _log.warning(
            "index_corruption_recovered",
            backup_file=str(backup_used) if backup_used else None,
            index_file=str(self.index_file),
        )
        return dict(_EMPTY_INDEX)

    def _write(self, data: dict[str, Any]) -> None:
        """原子写入索引文件(tempfile → os.replace)。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(self.index_file))
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def save(self, pages: list[Any]) -> None:
        """整体写回 pages 列表（用于批量修改后持久化）"""
        index = self._read()
        index["pages"] = pages
        index["total"] = len(pages)
        index["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write(index)

    def update_entry(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        patch: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> int:
        """按 predicate(entry)->bool 命中条目，用 patch(entry)->entry 更新并写回。

        返回被更新的条目数。
        """
        index = self._read()
        changed = 0
        for i, entry in enumerate(index["pages"]):
            if predicate(entry):
                index["pages"][i] = patch(entry)
                changed += 1
        if changed:
            index["total"] = len(index["pages"])
            index["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write(index)
        return changed

    def add_entry(
        self,
        url: str,
        title: str,
        category: str,
        folder: str,
        files: list[Any],
        warnings: list[Any] | None = None,
        errors: list[Any] | None = None,
        status: str = "ok",
        item_type: str = "web",
        source: str | None = None,
        content_hash: str | None = None,
        fetch_backend: str = "",
    ) -> dict[str, Any]:
        """添加一条剪藏记录

        status: ok / partial / failed
        item_type: web / video / image / doc
        source: 原始链接或文件名（缺省时回退到 url）
        content_hash: 文件类剪藏的内容哈希，用于查重
        fetch_backend: 抓取后端标识（FR-012）,如 "httpx" / "firecrawl" / "bili-cli"
        """
        index = self._read()

        entry = {
            "url": url,
            "type": item_type,
            "title": title,
            "category": category,
            "folder": folder,
            "files": files,
            "source": source or url,
            "status": status,
            "content_hash": content_hash,
            "fetch_backend": fetch_backend,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "warnings": warnings or [],
            "errors": errors or [],
        }

        # 插入到最前面
        index["pages"].insert(0, entry)
        index["total"] = len(index["pages"])
        index["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._write(index)
        return entry

    def search(self, keyword: str) -> list[dict[str, Any]]:
        """按标题关键词搜索"""
        index = self._read()
        keyword_lower = keyword.lower()
        return [
            entry
            for entry in index["pages"]
            if keyword_lower in entry.get("title", "").lower()
            or keyword_lower in entry.get("category", "").lower()
        ]

    def get_all(self) -> list[dict[str, Any]]:
        """获取全部剪藏记录"""
        return list(self._read().get("pages", []))

    def get_by_category(self, category: str) -> list[dict[str, Any]]:
        """按分类获取"""
        return [
            entry for entry in self._read().get("pages", []) if entry.get("category") == category
        ]

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        index = self._read()
        pages = index.get("pages", [])
        stats: dict[str, Any] = {
            "total": len(pages),
            "by_category": {},
            "last_updated": index.get("last_updated", ""),
        }

        for entry in pages:
            cat = entry.get("category", "未分类")
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

        return stats

    def delete_entry(self, url: str) -> bool:
        """按 URL 删除记录"""
        index = self._read()
        before = len(index["pages"])
        index["pages"] = [e for e in index["pages"] if e.get("url") != url]
        index["total"] = len(index["pages"])
        index["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write(index)
        return len(index["pages"]) < before

    def find_by_url(self, url: str) -> dict[str, Any] | None:
        """按原始 URL 查重，命中返回最早一条记录，否则 None"""
        for entry in self._read().get("pages", []):
            if entry.get("url") == url:
                return cast(dict[str, Any], entry)
        return None

    def find_by_url_all(self, url: str) -> list[dict[str, Any]]:
        """按 URL 查找全部匹配记录（FR-010）。

        返回所有 URL 相同的记录列表（可能含多个版本），
        供"内容已更新"判定使用。
        """
        return [entry for entry in self._read().get("pages", []) if entry.get("url") == url]

    def check_dedup(self, url: str, content_hash: str | None = None) -> dict[str, Any]:
        """去重检查（FR-010）。

        URL 为主要身份，content_hash 为次要身份：
        - URL 与 content_hash 均相同 → "duplicate"（完全重复，跳过）
        - URL 相同但 content_hash 不同 → "updated"（内容已更新，提示覆盖）
        - URL 无匹配但 content_hash 命中已有条目 → "duplicate"（文件类剪藏内容重复）
        - URL 无匹配且无哈希命中 → "new"（非重复，正常剪藏）

        Args:
            url: 待查重的 URL
            content_hash: 内容哈希（可选，文件类剪藏用）

        Returns:
            {"status": "duplicate" | "updated" | "new", "existing": list}
        """
        matches = self.find_by_url_all(url)
        if not matches:
            # URL 无匹配时,回退到 content_hash 全局查重(文件类剪藏次要身份)
            if content_hash:
                hash_match = self.find_by_hash(content_hash)
                if hash_match:
                    return {"status": "duplicate", "existing": [hash_match]}
            return {"status": "new", "existing": []}
        if content_hash:
            for m in matches:
                if m.get("content_hash") == content_hash:
                    return {"status": "duplicate", "existing": matches}
        return {"status": "updated", "existing": matches}

    def find_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        """按文件内容哈希查重（用于图片/文档类剪藏）"""
        for entry in self._read().get("pages", []):
            if entry.get("content_hash") == content_hash:
                return cast(dict[str, Any], entry)
        return None
