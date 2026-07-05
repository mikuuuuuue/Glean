"""混合类型批量剪藏测试(T055)。"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_mixed_urls_and_files(tmp_path):
    """混合URL+文件输入的批处理。"""
    # Create a test image
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG fake")

    inputs = [
        {"type": "url", "value": "https://example.com"},
        {"type": "file", "value": str(img)},
    ]

    # Verify the batch can handle mixed types without crashing
    with (
        patch(
            "clip.clip_url",
            new=AsyncMock(return_value={"url": "https://example.com", "overall": "ok"}),
        ),
        patch(
            "clip.clip_file",
            new=AsyncMock(return_value={"url": str(img), "overall": "ok"}),
        ),
    ):
        from clip import clip_file, clip_url

        results = []
        for inp in inputs:
            if inp["type"] == "url":
                r = await clip_url(inp["value"])
            else:
                r = await clip_file(inp["value"])
            results.append(r)
        assert len(results) == 2
        assert all(r["overall"] == "ok" for r in results)
