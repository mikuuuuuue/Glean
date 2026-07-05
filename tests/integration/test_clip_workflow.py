"""端到端工作流集成测试(T064)。

验证完整管线: 抓取→分类→索引→归档。
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_web_clip_full_pipeline(tmp_path: Path, monkeypatch):
    """网页剪藏完整管线: httpx抓取→分类→索引写入→文件归档。"""
    # 准备临时配置
    import yaml

    cfg = {
        "storage": {"base_dir": str(tmp_path / "clipped"), "index_file": "_index.json"},
        "categories": ["科技与AI", "其他收藏"],
        "category_keywords": {"科技与AI": ["python", "编程"], "其他收藏": []},
        "scraping": {"backend": "local", "firecrawl": {"api_key": ""}},
        "limits": {
            "max_images": 5,
            "max_content_chars": 50000,
            "image_timeout": 10,
            "page_fetch_timeout": 20,
            "max_file_size_mb": 20,
            "max_video_duration_min": 15,
        },
        "screenshot": {
            "enabled": False,
            "engine": "off",
            "timeout": 30,
            "user_agent": "",
            "full_page": True,
            "store_screenshot": True,
        },
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")

    # 注入配置
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)

    from clipper.categorizer import Categorizer
    from clipper.indexer import Indexer

    categorizer = Categorizer(str(cfg_path))  # noqa: F841
    indexer = Indexer(str(tmp_path / "clipped"), "_index.json")

    # 模拟 httpx 抓取
    html_content = "<html><head><title>Python 编程指南</title></head><body><p>这是一篇关于Python编程的文章。</p></body></html>"

    with patch(
        "httpx.AsyncClient.get",
        new=AsyncMock(
            return_value=type(
                "MockResp",
                (),
                {
                    "text": html_content,
                    "content": html_content.encode(),
                    "status_code": 200,
                    "headers": {},
                    "raise_for_status": lambda self: None,
                    "cookies": {},
                },
            )()
        ),
    ):
        from clipper.web import clip_webpage

        output_dir = tmp_path / "clipped" / "科技与AI" / "test_article"
        output_dir.mkdir(parents=True, exist_ok=True)
        result = await clip_webpage(
            "https://example.com/python-guide",
            output_dir,
            download_images=False,
            category="科技与AI",
        )

    assert result["success"] is True
    assert result["md_file"] is not None
    assert Path(result["md_file"]).exists()

    # 验证索引写入
    indexer.add_entry(
        url="https://example.com/python-guide",
        title=result["title"],
        category="科技与AI",
        folder="test_article",
        files=[result["md_file"]],
        warnings=[],
        errors=[],
        status="ok",
        item_type="web",
        source="",
        fetch_backend=result.get("fetch_backend", "httpx"),
    )
    found = indexer.find_by_url("https://example.com/python-guide")
    assert found is not None
    assert found["title"] == "Python 编程指南"


def test_index_corruption_recovery_pipeline(tmp_path: Path):
    """索引损坏→备份→重建→继续剪藏(FR-013a)。"""
    from clipper.indexer import Indexer

    base_dir = tmp_path / "clipped"
    base_dir.mkdir(parents=True, exist_ok=True)
    index_file = base_dir / "_index.json"

    # 写入损坏的索引
    index_file.write_text("{invalid json content", encoding="utf-8")

    # 创建 Indexer 应触发恢复
    idx = Indexer(str(base_dir), "_index.json")

    # 验证: 空索引已重建
    data = json.loads(index_file.read_text(encoding="utf-8"))
    assert data["pages"] == []
    assert data["total"] == 0

    # 验证: 损坏文件已备份
    backups = list(base_dir.glob("_index.json.corrupted.*"))
    assert len(backups) == 1

    # 验证: 可继续正常写入
    idx.add_entry(
        url="https://test.com",
        title="Test",
        category="其他收藏",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="web",
        source="",
        fetch_backend="httpx",
    )
    assert len(idx.get_all()) == 1


def test_dedup_in_workflow(tmp_path: Path):
    """去重检查在工作流中的完整流程(FR-010)。"""
    from clipper.indexer import Indexer

    idx = Indexer(str(tmp_path / "clipped"), "_index.json")
    idx.add_entry(
        url="https://example.com/article",
        title="原文标题",
        category="科技与AI",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="web",
        source="",
        fetch_backend="httpx",
    )

    # 相同 URL → duplicate
    result = idx.check_dedup("https://example.com/article")
    assert result["status"] != "new"

    # 不同 URL → new
    result = idx.check_dedup("https://example.com/other")
    assert result["status"] == "new"


def test_atomic_write_pipeline(tmp_path: Path):
    """原子写入: 写入过程中不产生半成品索引(FR-013)。"""
    from clipper.indexer import Indexer

    idx = Indexer(str(tmp_path / "clipped"), "_index.json")
    idx.add_entry(
        url="https://test.com",
        title="Test",
        category="科技与AI",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="web",
        source="",
        fetch_backend="httpx",
    )

    # 索引文件应为合法 JSON
    index_path = tmp_path / "clipped" / "_index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data["total"] == 1

    # 无临时文件残留
    tmp_files = list((tmp_path / "clipped").glob("*.tmp"))
    assert len(tmp_files) == 0
