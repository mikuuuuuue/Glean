"""T019: 网页剪藏去重单元测试 - FR-010。

验证去重判定三条路径:
  1. "duplicate": URL 与 content_hash 均相同 → 完全重复,跳过
  2. "updated": URL 相同但 content_hash 不同 → 内容已更新,提示覆盖
  3. "new": URL 无匹配 → 非重复,正常剪藏

测试 Indexer.check_dedup() 在网页剪藏场景下的行为。
"""


class TestWebDedupDuplicate:
    """完全重复:URL + content_hash 均相同"""

    def test_duplicate_same_url_same_hash(self, tmp_index):
        """URL 与 content_hash 均相同 → duplicate"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com/article",
            title="Original Title",
            category="科技与AI",
            folder="20260704_article",
            files=["article.md"],
            fetch_backend="httpx",
            content_hash="abc123",
        )

        result = idx.check_dedup("https://example.com/article", "abc123")
        assert result["status"] == "duplicate"
        assert len(result["existing"]) == 1

    def test_duplicate_multiple_versions_same_hash(self, tmp_index):
        """多条同 URL 记录,其中一条 hash 匹配 → duplicate"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com/article",
            title="V1",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
            content_hash="hash_v1",
        )
        idx.add_entry(
            url="https://example.com/article",
            title="V2",
            category="科技与AI",
            folder="f2",
            files=[],
            fetch_backend="firecrawl",
            content_hash="hash_v2",
        )

        result = idx.check_dedup("https://example.com/article", "hash_v1")
        assert result["status"] == "duplicate"
        assert len(result["existing"]) == 2


class TestWebDedupUpdated:
    """内容已更新:URL 相同但 content_hash 不同"""

    def test_updated_same_url_different_hash(self, tmp_index):
        """URL 相同但 content_hash 不同 → updated"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com/article",
            title="Old Title",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
            content_hash="old_hash",
        )

        result = idx.check_dedup("https://example.com/article", "new_hash")
        assert result["status"] == "updated"
        assert len(result["existing"]) == 1

    def test_updated_no_content_hash(self, tmp_index):
        """URL 相同但未提供 content_hash → updated (保守判定)"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com/article",
            title="Existing",
            category="科技与AI",
            folder="f1",
            files=[],
            fetch_backend="httpx",
            content_hash="existing_hash",
        )

        result = idx.check_dedup("https://example.com/article", content_hash=None)
        assert result["status"] == "updated"


class TestWebDedupNew:
    """非重复:URL 无匹配"""

    def test_new_url_not_in_index(self, tmp_index):
        """URL 不在索引中 → new"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        result = idx.check_dedup("https://example.com/new", "any_hash")
        assert result["status"] == "new"
        assert result["existing"] == []

    def test_new_url_empty_index(self, tmp_index):
        """空索引中查重 → new"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        result = idx.check_dedup("https://example.com/anything", None)
        assert result["status"] == "new"


class TestWebDedupFindAll:
    """find_by_url_all 返回全部匹配(FR-010)"""

    def test_find_all_returns_multiple_versions(self, tmp_index):
        """同一 URL 有多条记录时全部返回"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        for i in range(3):
            idx.add_entry(
                url="https://example.com/versions",
                title=f"Version {i}",
                category="科技与AI",
                folder=f"f{i}",
                files=[],
                fetch_backend="httpx",
                content_hash=f"hash_{i}",
            )

        all_matches = idx.find_by_url_all("https://example.com/versions")
        assert len(all_matches) == 3

    def test_find_all_no_match_returns_empty(self, tmp_index):
        """无匹配时返回空列表"""
        from clipper.indexer import Indexer

        idx = Indexer(str(tmp_index))
        idx.add_entry(
            url="https://example.com/a",
            title="A",
            category="科技与AI",
            folder="fa",
            files=[],
            fetch_backend="httpx",
        )

        result = idx.find_by_url_all("https://example.com/b")
        assert result == []
