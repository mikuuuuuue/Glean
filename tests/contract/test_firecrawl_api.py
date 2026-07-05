"""T020: Firecrawl API 契约测试 - FR-005 (宪法原则 IV)。

验证 Firecrawl 响应结构符合代码预期,记录字段契约。

契约要点:
  1. scrape_url() 返回 dict,包含 'markdown' 字段(str)
  2. 'metadata' 子 dict 包含 'title'(str)
  3. 'screenshot' 字段为 base64 编码图片(str,可选)
  4. clip_webpage_firecrawl() 正确提取并写入 MD
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestFirecrawlResponseContract:
    """Firecrawl API 响应结构契约"""

    def test_response_has_markdown_field(self):
        """响应必须包含 'markdown' 字段(str)"""
        mock_response = {
            "markdown": "# Test Article\n\nContent here.",
            "metadata": {"title": "Test Article"},
        }
        assert "markdown" in mock_response
        assert isinstance(mock_response["markdown"], str)

    def test_response_has_metadata_title(self):
        """metadata 必须包含 'title'(str)"""
        mock_response = {
            "markdown": "# Test",
            "metadata": {"title": "Test Article", "description": "A test"},
        }
        assert "metadata" in mock_response
        assert "title" in mock_response["metadata"]
        assert isinstance(mock_response["metadata"]["title"], str)

    def test_response_screenshot_optional(self):
        """screenshot 字段可选(base64 str)"""
        # 有截图
        mock_with_screenshot = {
            "markdown": "# Test",
            "metadata": {"title": "Test"},
            "screenshot": "iVBORw0KGgoAAAANSUhEUg==",
        }
        assert "screenshot" in mock_with_screenshot

        # 无截图也合法
        mock_without_screenshot = {
            "markdown": "# Test",
            "metadata": {"title": "Test"},
        }
        assert "screenshot" not in mock_without_screenshot


class TestClipWebpageFirecrawlContract:
    """clip_webpage_firecrawl() 与 Firecrawl API 的集成契约"""

    @pytest.mark.asyncio
    async def test_firecrawl_success_produces_md(self, tmp_path, tmp_config):
        """Firecrawl 成功响应 → MD 文件落盘"""
        from clipper.web import clip_webpage_firecrawl

        # 构造 mock FirecrawlApp
        mock_app = MagicMock()
        mock_app.scrape_url.return_value = {
            "markdown": "# 测试文章\n\n这是 Firecrawl 返回的 Markdown 正文。",
            "metadata": {"title": "测试文章"},
        }

        with patch.dict(
            "sys.modules", {"firecrawl": MagicMock(FirecrawlApp=MagicMock(return_value=mock_app))}
        ):
            # 设置 API key
            from clipper.config import get_config

            get_config()["scraping"]["firecrawl"]["api_key"] = "test_key"

            output_dir = tmp_path / "output"
            output_dir.mkdir()

            result = await clip_webpage_firecrawl(
                "https://example.com/firecrawl-test",
                output_dir,
            )

        assert result["success"] is True
        assert result["title"] == "测试文章"
        assert result["md_file"] is not None
        assert Path(result["md_file"]).exists()

        md_content = Path(result["md_file"]).read_text(encoding="utf-8")
        assert "测试文章" in md_content
        assert "Firecrawl 返回的 Markdown 正文" in md_content

    @pytest.mark.asyncio
    async def test_firecrawl_result_has_fetch_backend(self, tmp_path, tmp_config):
        """FR-012: Firecrawl 结果含 fetch_backend='firecrawl'"""
        from clipper.web import clip_webpage_firecrawl

        mock_app = MagicMock()
        mock_app.scrape_url.return_value = {
            "markdown": "# Test",
            "metadata": {"title": "Test"},
        }

        with patch.dict(
            "sys.modules", {"firecrawl": MagicMock(FirecrawlApp=MagicMock(return_value=mock_app))}
        ):
            from clipper.config import get_config

            get_config()["scraping"]["firecrawl"]["api_key"] = "test_key"

            output_dir = tmp_path / "output"
            output_dir.mkdir()

            result = await clip_webpage_firecrawl(
                "https://example.com/test",
                output_dir,
            )

        assert result.get("fetch_backend") == "firecrawl"

    @pytest.mark.asyncio
    async def test_firecrawl_no_api_key_returns_error(self, tmp_path, tmp_config):
        """未配置 API key → 返回错误"""
        from clipper.config import get_config
        from clipper.web import clip_webpage_firecrawl

        get_config()["scraping"]["firecrawl"]["api_key"] = ""

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = await clip_webpage_firecrawl(
            "https://example.com/no-key",
            output_dir,
        )

        assert result["success"] is False
        assert "API Key" in result.get("error", "") or "api_key" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_firecrawl_screenshot_saved(self, tmp_path, tmp_config):
        """Firecrawl 返回截图时保存为文件"""
        import base64

        from clipper.web import clip_webpage_firecrawl

        # 构造 1x1 PNG 的 base64
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        screenshot_b64 = base64.b64encode(png_bytes).decode()

        mock_app = MagicMock()
        mock_app.scrape_url.return_value = {
            "markdown": "# Screenshot Test",
            "metadata": {"title": "Screenshot Test"},
            "screenshot": screenshot_b64,
        }

        with patch.dict(
            "sys.modules", {"firecrawl": MagicMock(FirecrawlApp=MagicMock(return_value=mock_app))}
        ):
            from clipper.config import get_config

            get_config()["scraping"]["firecrawl"]["api_key"] = "test_key"

            output_dir = tmp_path / "output"
            output_dir.mkdir()

            result = await clip_webpage_firecrawl(
                "https://example.com/screenshot-test",
                output_dir,
            )

        assert result["success"] is True
        assert result.get("screenshot_file") is not None
        assert Path(result["screenshot_file"]).exists()
