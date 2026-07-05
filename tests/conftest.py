"""共享 pytest fixtures。

提供:
- tmp_config: 临时配置文件 + 注入,用于隔离测试
- tmp_index: 临时索引目录与 Indexer 实例
- mock_httpx: httpx_mock fixture 的便捷封装(通过 pytest-httpx 自动提供)
"""

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """创建临时 config.yaml 并 monkeypatch 配置路径。

    返回临时配置文件路径。各模块通过 clipper.config.get_config() 读取。
    """
    cfg = {
        "storage": {"base_dir": str(tmp_path / "clipped_pages"), "index_file": "_index.json"},
        "categories": [
            "科技与AI",
            "财经与商业",
            "游戏与文化",
            "阅读与思考",
            "工具与技巧",
            "视频与影音",
            "其他收藏",
        ],
        "category_keywords": {"科技与AI": ["ai", "代码", "编程"], "其他收藏": []},
        "features": {"download_images": True, "video_subtitle": True, "ai_summary": False},
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
            "enabled": True,
            "engine": "off",
            "timeout": 30,
            "user_agent": "",
            "full_page": True,
            "store_screenshot": True,
        },
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    # 重置配置单例缓存,强制下次 get_config() 重新加载
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture
def tmp_index(tmp_path: Path) -> Path:
    """创建临时索引目录,返回 base_dir 路径。"""
    base_dir = tmp_path / "clipped_pages"
    base_dir.mkdir(parents=True, exist_ok=True)
    index_file = base_dir / "_index.json"
    index_file.write_text(
        json.dumps({"pages": [], "total": 0, "last_updated": ""}, ensure_ascii=False),
        encoding="utf-8",
    )
    return base_dir
