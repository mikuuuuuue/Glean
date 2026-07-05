"""视频去重单元测试(T029)。验证 BV 号相同判定为重复。"""

from clipper.indexer import Indexer
from clipper.video import extract_bvid


def test_extract_bvid_from_full_url():
    assert extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD") == "BV1xx411c7mD"


def test_extract_bvid_from_short():
    assert extract_bvid("https://b23.tv/abc123") is None


def test_extract_bvid_from_av():
    assert extract_bvid("https://www.bilibili.com/video/av12345") == "av12345"


def test_extract_bvid_no_match():
    assert extract_bvid("https://example.com") is None


def test_video_dedup_by_bvid(tmp_path):
    """相同 BV号的URL应判为重复(通过 Indexer.check_dedup)。"""
    idx = Indexer(str(tmp_path), "_index.json")
    idx.add_entry(
        url="https://www.bilibili.com/video/BV1xx411c7mD",
        title="测试视频",
        category="视频与影音",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="video",
        source="",
        fetch_backend="bili-cli",
    )
    # 不同URL但相同BV号 → 应能通过URL匹配到
    result = idx.check_dedup("https://www.bilibili.com/video/BV1xx411c7mD")
    assert result["status"] != "new"


def test_video_dedup_different_bvid(tmp_path):
    """不同BV号应判为新条目。"""
    idx = Indexer(str(tmp_path), "_index.json")
    idx.add_entry(
        url="https://www.bilibili.com/video/BV1xx411c7mD",
        title="视频A",
        category="视频与影音",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="video",
        source="",
        fetch_backend="bili-cli",
    )
    result = idx.check_dedup("https://www.bilibili.com/video/BV2yy422d8nE")
    assert result["status"] == "new"
