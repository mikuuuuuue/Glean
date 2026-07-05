"""搜索与统计单元测试(T063a)。

验证关键词检索(FR-014)返回正确结果、统计信息(FR-015)含总数与各领域分布。
"""

from pathlib import Path

import pytest

from clipper.indexer import Indexer


@pytest.fixture
def populated_indexer(tmp_path: Path) -> Indexer:
    """创建含多条记录的索引器。"""
    idx = Indexer(str(tmp_path / "clipped_pages"), "_index.json")
    entries = [
        {
            "url": "https://a.com/1",
            "title": "Python 编程入门",
            "category": "科技与AI",
            "folder": "f1",
            "files": [],
            "warnings": [],
            "errors": [],
            "status": "ok",
            "item_type": "web",
            "source": "",
            "fetch_backend": "httpx",
        },
        {
            "url": "https://a.com/2",
            "title": "股票投资指南",
            "category": "财经与商业",
            "folder": "f2",
            "files": [],
            "warnings": [],
            "errors": [],
            "status": "ok",
            "item_type": "web",
            "source": "",
            "fetch_backend": "httpx",
        },
        {
            "url": "https://a.com/3",
            "title": "AI 机器学习教程",
            "category": "科技与AI",
            "folder": "f3",
            "files": [],
            "warnings": [],
            "errors": [],
            "status": "ok",
            "item_type": "web",
            "source": "",
            "fetch_backend": "httpx",
        },
        {
            "url": "https://a.com/4",
            "title": "游戏文化杂谈",
            "category": "游戏与文化",
            "folder": "f4",
            "files": [],
            "warnings": [],
            "errors": [],
            "status": "ok",
            "item_type": "web",
            "source": "",
            "fetch_backend": "httpx",
        },
    ]
    for e in entries:
        idx.add_entry(**e)
    return idx


def test_search_by_title_keyword(populated_indexer: Indexer):
    """按标题关键词搜索(FR-014)。"""
    results = populated_indexer.search("Python")
    assert len(results) == 1
    assert results[0]["title"] == "Python 编程入门"


def test_search_by_partial_keyword(populated_indexer: Indexer):
    """部分关键词匹配。"""
    results = populated_indexer.search("投资")
    assert len(results) == 1
    assert "股票" in results[0]["title"]


def test_search_case_insensitive(populated_indexer: Indexer):
    """搜索不区分大小写。"""
    results = populated_indexer.search("ai")
    # "ai" matches both "AI 机器学习教程" and "Python 编程入门" (contains "ai" in "Python")
    assert len(results) >= 1
    assert any("AI" in r["title"] for r in results)


def test_search_by_category(populated_indexer: Indexer):
    """按分类名搜索也能命中。"""
    results = populated_indexer.search("科技")
    assert len(results) == 2


def test_search_no_match(populated_indexer: Indexer):
    """无匹配时返回空列表。"""
    results = populated_indexer.search("不存在的关键词xyz123")
    assert results == []


def test_search_empty_keyword(populated_indexer: Indexer):
    """空关键词匹配全部(或空字符串)。"""
    results = populated_indexer.search("")
    # 空字符串是所有标题的子串,应返回全部
    assert len(results) == 4


def test_get_stats_total(populated_indexer: Indexer):
    """统计信息含总数(FR-015)。"""
    stats = populated_indexer.get_stats()
    assert stats["total"] == 4


def test_get_stats_by_category(populated_indexer: Indexer):
    """统计信息含各领域分布(FR-015)。"""
    stats = populated_indexer.get_stats()
    assert stats["by_category"]["科技与AI"] == 2
    assert stats["by_category"]["财经与商业"] == 1
    assert stats["by_category"]["游戏与文化"] == 1


def test_get_stats_last_updated(populated_indexer: Indexer):
    """统计信息含最后更新时间。"""
    stats = populated_indexer.get_stats()
    assert "last_updated" in stats


def test_get_all(populated_indexer: Indexer):
    """获取全部记录。"""
    all_entries = populated_indexer.get_all()
    assert len(all_entries) == 4


def test_get_by_category(populated_indexer: Indexer):
    """按分类获取。"""
    tech = populated_indexer.get_by_category("科技与AI")
    assert len(tech) == 2
    finance = populated_indexer.get_by_category("财经与商业")
    assert len(finance) == 1


def test_search_speed(populated_indexer: Indexer):
    """检索在 2 秒内完成(SC-007)。"""
    import time

    start = time.time()
    populated_indexer.search("Python")
    elapsed = time.time() - start
    assert elapsed < 2.0
