"""索引管理模块 - 维护 _index.json"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class Indexer:
    """维护剪藏索引文件"""

    def __init__(self, base_dir: str, index_filename: str = "_index.json"):
        self.base_dir = Path(base_dir)
        self.index_file = self.base_dir / index_filename
        self._ensure_index()

    def _ensure_index(self):
        """确保索引文件存在"""
        if not self.index_file.exists():
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self._write({"pages": [], "total": 0, "last_updated": ""})

    def _read(self) -> dict:
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"pages": [], "total": 0, "last_updated": ""}

    def _write(self, data: dict):
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self, pages: list):
        """整体写回 pages 列表（用于批量修改后持久化）"""
        index = self._read()
        index["pages"] = pages
        index["total"] = len(pages)
        index["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write(index)

    def update_entry(self, predicate, patch):
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
        folder_name: str,
        files: list,
        warnings: Optional[list] = None,
        errors: Optional[list] = None,
        status: str = "ok",
        item_type: str = "web",
        source: Optional[str] = None,
        content_hash: Optional[str] = None,
    ):
        """添加一条剪藏记录

        status: ok / partial / failed
        item_type: web / video / image / doc
        source: 原始链接或文件名（缺省时回退到 url）
        content_hash: 文件类剪藏的内容哈希，用于查重
        """
        index = self._read()

        entry = {
            "url": url,
            "type": item_type,
            "title": title,
            "category": category,
            "folder": folder_name,
            "files": files,
            "source": source or url,
            "status": status,
            "content_hash": content_hash,
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

    def search(self, keyword: str) -> list:
        """按标题关键词搜索"""
        index = self._read()
        keyword_lower = keyword.lower()
        return [
            entry
            for entry in index["pages"]
            if keyword_lower in entry.get("title", "").lower()
            or keyword_lower in entry.get("category", "").lower()
        ]

    def get_all(self) -> list:
        """获取全部剪藏记录"""
        return self._read().get("pages", [])

    def get_by_category(self, category: str) -> list:
        """按分类获取"""
        return [
            entry
            for entry in self._read().get("pages", [])
            if entry.get("category") == category
        ]

    def get_stats(self) -> dict:
        """获取统计信息"""
        index = self._read()
        pages = index.get("pages", [])
        stats = {"total": len(pages), "by_category": {}, "last_updated": index.get("last_updated", "")}

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

    def find_by_url(self, url: str) -> Optional[dict]:
        """按原始 URL 查重，命中返回最早一条记录，否则 None"""
        for entry in self._read().get("pages", []):
            if entry.get("url") == url:
                return entry
        return None

    def find_by_hash(self, content_hash: str) -> Optional[dict]:
        """按文件内容哈希查重（用于图片/文档类剪藏）"""
        for entry in self._read().get("pages", []):
            if entry.get("content_hash") == content_hash:
                return entry
        return None