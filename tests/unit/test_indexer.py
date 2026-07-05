"""T015: 验证 clipper.indexer 索引管理。

测试范围:
- 索引增删查
- 损坏备份恢复(FR-013a)
- fetch_backend 字段写入(FR-012)
- "内容已更新"判定(FR-010)
"""

import json
from pathlib import Path


class TestIndexerBasic:
    """索引增删查基础功能"""

    def test_add_entry(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        entry = idx.add_entry(
            url="https://example.com",
            title="Example",
            category="科技与AI",
            folder="20260704_Example",
            files=["/path/to/article.md"],
            fetch_backend="httpx",
        )
        assert entry["url"] == "https://example.com"
        assert entry["title"] == "Example"
        assert entry["fetch_backend"] == "httpx"

    def test_find_by_url(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com",
            title="Example",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
        )
        found = idx.find_by_url("https://example.com")
        assert found is not None
        assert found["title"] == "Example"

    def test_find_by_url_not_found(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        assert idx.find_by_url("https://nonexistent.com") is None

    def test_delete_entry(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com",
            title="Example",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
        )
        assert idx.delete_entry("https://example.com") is True
        assert idx.find_by_url("https://example.com") is None

    def test_search(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com",
            title="Python Tutorial",
            category="工具与技巧",
            folder="f1",
            files=[],
            fetch_backend="httpx",
        )
        results = idx.search("python")
        assert len(results) == 1
        assert results[0]["title"] == "Python Tutorial"

    def test_get_stats(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://a.com",
            title="A",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
        )
        idx.add_entry(
            url="https://b.com",
            title="B",
            category="科技与AI",
            folder="f2",
            files=[],
            fetch_backend="httpx",
        )
        stats = idx.get_stats()
        assert stats["total"] == 2
        assert stats["by_category"]["科技与AI"] == 2


class TestIndexerFetchBackend:
    """FR-012: fetch_backend 字段"""

    def test_add_entry_with_fetch_backend(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com",
            title="Example",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="firecrawl",
        )
        found = idx.find_by_url("https://example.com")
        assert found["fetch_backend"] == "firecrawl"

    def test_add_entry_default_fetch_backend(self, tmp_index: Path):
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        # 不传 fetch_backend 时应默认为空字符串或 None
        idx.add_entry(
            url="https://example.com",
            title="Example",
            category="科技与AI",
            folder="f1",
            files=[],
        )
        found = idx.find_by_url("https://example.com")
        assert found.get("fetch_backend", "") == ""


class TestIndexerCorruptionRecovery:
    """FR-013a: 索引损坏备份恢复"""

    def test_corrupted_index_backed_up_and_rebuilt(self, tmp_index: Path):
        from clipper.indexer import Indexer

        # 写入损坏的 JSON
        index_file = tmp_index / "_index.json"
        index_file.write_text("corrupted content {{{", encoding="utf-8")

        # 创建 Indexer 应触发恢复
        idx = Indexer(str(tmp_index))  # noqa: F841

        # 损坏文件应被备份(带 .corrupted. 时间戳)
        backups = list(tmp_index.glob("_index.json.corrupted.*"))
        assert len(backups) == 1

        # 索引应被重建为空
        data = json.loads(index_file.read_text(encoding="utf-8"))
        assert data["pages"] == []
        assert data["total"] == 0

    def test_corruption_recovery_allows_operation(self, tmp_index: Path):
        from clipper.indexer import Indexer

        index_file = tmp_index / "_index.json"
        index_file.write_text("not json", encoding="utf-8")

        idx = Indexer(str(tmp_index))
        # 恢复后应能正常添加记录
        idx.add_entry(
            url="https://example.com",
            title="Test",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
        )
        found = idx.find_by_url("https://example.com")
        assert found is not None


class TestIndexerDedupDetection:
    """FR-010: 去重"内容已更新"判定"""

    def test_find_by_url_returns_all_matches(self, tmp_index: Path):
        """FR-010: find_by_url 应返回全部匹配记录(非仅最早一条)"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com",
            title="V1",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
            content_hash="hash_v1",
        )
        idx.add_entry(
            url="https://example.com",
            title="V2",
            category="科技与AI",
            folder="f2",
            files=[],
            fetch_backend="httpx",
            content_hash="hash_v2",
        )
        # 应返回 2 条记录
        all_matches = idx.find_by_url_all("https://example.com")
        assert len(all_matches) == 2

    def test_dedup_check_duplicate(self, tmp_index: Path):
        """URL 与 content_hash 均相同 → duplicate"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com",
            title="V1",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
            content_hash="abc123",
        )
        result = idx.check_dedup("https://example.com", "abc123")
        assert result["status"] == "duplicate"

    def test_dedup_check_updated(self, tmp_index: Path):
        """URL 相同但 content_hash 不同 → updated"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com",
            title="V1",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
            content_hash="old_hash",
        )
        result = idx.check_dedup("https://example.com", "new_hash")
        assert result["status"] == "updated"

    def test_dedup_check_new(self, tmp_index: Path):
        """URL 无匹配 → new(非重复)"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        result = idx.check_dedup("https://example.com", "any_hash")
        assert result["status"] == "new"
