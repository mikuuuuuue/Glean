"""URL 类型检测模块单元测试(T062 覆盖补充)。

验证 clipper.url_detector 的三类 URL 识别与拒绝策略(FR-001):
  - bilibili_video: BV/av/b23.tv/番剧
  - web: http(s) 且有效域名
  - unknown: 调用方 MUST 拒绝剪藏
"""

import pytest

from clipper.url_detector import (
    _is_bilibili,
    _is_valid_web_url,
    detect_url_type,
    should_reject,
)

# ── detect_url_type: bilibili_video ──────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "http://www.bilibili.com/video/BV1xx411c7mD",
        "https://bilibili.com/video/BV1xx411c7mD",
        "https://www.bilibili.com/video/av12345",
        "https://b23.tv/abc123",
        "https://www.bilibili.com/bangumi/play/ep12345",
        "https://www.bilibili.com/bangumi/play/ss100",
    ],
)
def test_detect_url_type_bilibili_video(url: str):
    """BV/av/b23.tv/番剧链接识别为 bilibili_video。"""
    assert detect_url_type(url) == "bilibili_video"


def test_detect_url_type_bilibili_case_insensitive():
    """B站链接大小写不敏感(BV 号大写,URL 路径小写均能识别)。"""
    assert detect_url_type("https://WWW.BILIBILI.COM/video/BV1xx411c7mD") == "bilibili_video"
    assert detect_url_type("HTTPS://B23.TV/AbC123") == "bilibili_video"


# ── detect_url_type: web ─────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article",
        "http://example.com",
        "https://www.zhihu.com/question/123",
        "https://blog.example.org/posts/2024",
        "http://sub.domain.co.uk/path",
    ],
)
def test_detect_url_type_web(url: str):
    """可识别网页链接识别为 web。"""
    assert detect_url_type(url) == "web"


# ── detect_url_type: unknown ────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "just-some-text",
        "",
        "://missing-protocol.com",
    ],
)
def test_detect_url_type_unknown(url: str):
    """无法识别的 URL 返回 unknown。"""
    assert detect_url_type(url) == "unknown"


def test_detect_url_type_no_protocol_is_unknown():
    """无协议(无 http/https)的 URL 识别为 unknown。"""
    assert detect_url_type("www.example.com/article") == "unknown"
    assert detect_url_type("example.com") == "unknown"


def test_detect_url_type_no_domain_is_unknown():
    """有协议但无有效域名的 URL 识别为 unknown。"""
    assert detect_url_type("https://localhost") == "unknown"
    assert detect_url_type("https:///path-only") == "unknown"


def test_detect_url_type_bilibili_priority_over_web():
    """B站链接优先于 web 识别(优先级 bilibili > web > unknown)。"""
    # 这是 B站链接,即便也满足 web 模式,也应返回 bilibili_video
    url = "https://www.bilibili.com/video/BV1xx411c7mD"
    assert detect_url_type(url) == "bilibili_video"


# ── should_reject ───────────────────────────────────────────


def test_should_reject_unknown_returns_true():
    """unknown URL 应被拒绝(should_reject 返回 True)。"""
    assert should_reject("not a url") is True
    assert should_reject("ftp://example.com/file") is True
    assert should_reject("just-some-text") is True


def test_should_reject_bilibili_returns_false():
    """bilibili_video URL 不应被拒绝。"""
    assert should_reject("https://www.bilibili.com/video/BV1xx411c7mD") is False
    assert should_reject("https://b23.tv/abc123") is False


def test_should_reject_web_returns_false():
    """web URL 不应被拒绝。"""
    assert should_reject("https://example.com/article") is False
    assert should_reject("http://example.com") is False


def test_should_reject_empty_string():
    """空字符串应被拒绝。"""
    assert should_reject("") is True


# ── _is_bilibili 内部辅助 ────────────────────────────────────


def test_is_bilibili_bv_pattern():
    """BV 号模式匹配。"""
    assert _is_bilibili("https://www.bilibili.com/video/BV1xx411c7mD") is True
    assert _is_bilibili("https://www.bilibili.com/video/BV1GJ411x7h7") is True


def test_is_bilibili_av_pattern():
    """av 号模式匹配。"""
    assert _is_bilibili("https://www.bilibili.com/video/av170001") is True


def test_is_bilibili_b23_pattern():
    """b23.tv 短链模式匹配。"""
    assert _is_bilibili("https://b23.tv/abc123") is True


def test_is_bilibili_bangumi_pattern():
    """番剧播放页模式匹配。"""
    assert _is_bilibili("https://www.bilibili.com/bangumi/play/ep12345") is True


def test_is_bilibili_non_bilibili():
    """非 B站 URL 不匹配。"""
    assert _is_bilibili("https://example.com/video/BV1xx411c7mD") is False
    assert _is_bilibili("https://www.youtube.com/watch?v=abc") is False
    assert _is_bilibili("not a url") is False


# ── _is_valid_web_url 内部辅助 ──────────────────────────────


def test_is_valid_web_url_valid():
    """有效 web URL。"""
    assert _is_valid_web_url("https://example.com") is True
    assert _is_valid_web_url("http://sub.domain.co.uk/path") is True


def test_is_valid_web_url_missing_protocol():
    """缺协议无效。"""
    assert _is_valid_web_url("www.example.com") is False
    assert _is_valid_web_url("example.com/path") is False


def test_is_valid_web_url_missing_domain():
    """缺有效域名(无点号)无效。"""
    assert _is_valid_web_url("https://localhost") is False
    assert _is_valid_web_url("https:///path-only") is False


def test_is_valid_web_url_wrong_protocol():
    """非 http/https 协议无效。"""
    assert _is_valid_web_url("ftp://example.com/file") is False
    assert _is_valid_web_url("file:///local/path") is False


def test_is_valid_web_url_empty():
    """空字符串无效。"""
    assert _is_valid_web_url("") is False
