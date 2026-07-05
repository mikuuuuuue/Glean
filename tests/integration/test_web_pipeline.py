"""T018: 网页剪藏集成测试 - httpx 路径端到端验证。

验证: HTML 抓取 → Markdown 生成 → 图片下载(可选) → fetch_backend 字段 → 索引写入。

测试策略:
  - httpx_mock 拦截网络请求,注入可控 HTML
  - 验证 MD 文件内容、result 结构、fetch_backend 字段
  - T021 实现后 fetch_backend 字段测试变绿
"""

from pathlib import Path

import pytest


class TestClipWebpageHttpx:
    """httpx 后端集成测试"""

    @pytest.mark.asyncio
    async def test_basic_clip_produces_md(self, tmp_path, tmp_config, httpx_mock):
        """httpx 抓取 → MD 生成 → 文件落盘"""
        from clipper.web import clip_webpage

        html = """
        <html>
        <head><title>测试文章标题</title></head>
        <body>
        <article>
        <h1>测试文章标题</h1>
        <p>这是一段测试正文内容,用于验证 HTML→MD 转换。</p>
        </article>
        </body>
        </html>
        """
        httpx_mock.add_response(
            url="https://example.com/article",
            text=html,
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
        )

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = await clip_webpage(
            "https://example.com/article",
            output_dir,
            download_images=False,
        )

        # 基本成功
        assert result["success"] is True
        assert result["title"] == "测试文章标题"
        assert result["md_file"] is not None

        # MD 文件已落盘
        md_path = Path(result["md_file"])
        assert md_path.exists()
        md_content = md_path.read_text(encoding="utf-8")
        assert "测试文章标题" in md_content
        assert "测试正文内容" in md_content

    @pytest.mark.asyncio
    async def test_result_contains_fetch_backend(self, tmp_path, tmp_config, httpx_mock):
        """FR-012: 结果包含 fetch_backend 字段,值为 'httpx'"""
        from clipper.web import clip_webpage

        html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        httpx_mock.add_response(
            url="https://example.com/test",
            text=html,
            status_code=200,
        )

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = await clip_webpage(
            "https://example.com/test",
            output_dir,
            download_images=False,
        )

        # FR-012: fetch_backend 字段标识抓取后端
        assert result.get("fetch_backend") == "httpx"

    @pytest.mark.asyncio
    async def test_clip_failure_produces_placeholder_md(self, tmp_path, tmp_config, httpx_mock):
        """FR-013: httpx 抓取失败时生成失败占位 md"""
        from clipper.web import clip_webpage

        httpx_mock.add_response(
            url="https://example.com/404",
            status_code=404,
        )

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = await clip_webpage(
            "https://example.com/404",
            output_dir,
            download_images=False,
        )

        # 失败时也应生成占位 md
        assert result["success"] is False
        assert result["md_file"] is not None
        assert Path(result["md_file"]).exists()
        md_content = Path(result["md_file"]).read_text(encoding="utf-8")
        assert "失败" in md_content or "error" in md_content.lower()

    @pytest.mark.asyncio
    async def test_clip_result_can_be_indexed(self, tmp_path, tmp_config, httpx_mock):
        """剪藏结果可写入索引,索引条目含 fetch_backend"""
        from clipper.indexer import Indexer
        from clipper.web import clip_webpage

        html = (
            "<html><head><title>Indexable Article</title></head><body><p>Content</p></body></html>"
        )
        httpx_mock.add_response(
            url="https://example.com/indexable",
            text=html,
            status_code=200,
        )

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = await clip_webpage(
            "https://example.com/indexable",
            output_dir,
            download_images=False,
        )

        # 写入索引
        base_dir = tmp_path / "clipped_pages"
        base_dir.mkdir()
        idx = Indexer(str(base_dir))
        idx.add_entry(
            url="https://example.com/indexable",
            title=result["title"],
            category="科技与AI",
            folder=output_dir.name,
            files=[result["md_file"]] if result["md_file"] else [],
            fetch_backend=result.get("fetch_backend", "httpx"),
        )

        # 验证索引
        entry = idx.find_by_url("https://example.com/indexable")
        assert entry is not None
        assert entry["fetch_backend"] == "httpx"
        assert entry["title"] == "Indexable Article"

    @pytest.mark.asyncio
    async def test_image_download_disabled(self, tmp_path, tmp_config, httpx_mock):
        """download_images=False 时不下载图片"""
        from clipper.web import clip_webpage

        html = """
        <html><head><title>Img Test</title></head>
        <body><p>Text</p>
        <img src="https://example.com/image.png"></body></html>
        """
        httpx_mock.add_response(
            url="https://example.com/imgpage",
            text=html,
            status_code=200,
        )

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = await clip_webpage(
            "https://example.com/imgpage",
            output_dir,
            download_images=False,
        )

        assert result["success"] is True
        assert result["images_downloaded"] == 0
        # images 目录不应被创建
        assert not (output_dir / "images").exists()
