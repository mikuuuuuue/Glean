"""图片内容哈希去重测试(T044)。"""

from clipper.image import file_content_hash
from clipper.indexer import Indexer


def test_image_dedup_same_hash(tmp_path):
    """相同内容哈希判定为重复。"""
    idx = Indexer(str(tmp_path), "_index.json")
    src = tmp_path / "img.png"
    src.write_bytes(b"image data")
    h = file_content_hash(src)
    idx.add_entry(
        url="local://img1",
        title="图片1",
        category="其他收藏",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="image",
        source="img.png",
        content_hash=h,
        fetch_backend="local",
    )
    result = idx.check_dedup("local://img2", content_hash=h)
    assert result["status"] == "duplicate"


def test_image_dedup_different_hash(tmp_path):
    """不同内容哈希判定为新或更新。"""
    idx = Indexer(str(tmp_path), "_index.json")
    idx.add_entry(
        url="local://img1",
        title="图片1",
        category="其他收藏",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="image",
        source="img1.png",
        content_hash="hash_a",
        fetch_backend="local",
    )
    result = idx.check_dedup("local://img2", content_hash="hash_b")
    # Same URL not found, but different hash → new
    assert result["status"] == "new"
