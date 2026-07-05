"""文档内容哈希去重测试(T049)。"""

from clipper.image import file_content_hash
from clipper.indexer import Indexer


def test_doc_dedup_same_content(tmp_path):
    """相同内容文档判定为重复。"""
    idx = Indexer(str(tmp_path), "_index.json")
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"same doc content")
    h = file_content_hash(src)
    idx.add_entry(
        url="local://doc1",
        title="文档1",
        category="阅读与思考",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="doc",
        source="doc.pdf",
        content_hash=h,
        fetch_backend="local",
    )
    result = idx.check_dedup("local://doc2", content_hash=h)
    assert result["status"] == "duplicate"


def test_doc_dedup_different_content(tmp_path):
    """不同内容文档判定为新。"""
    idx = Indexer(str(tmp_path), "_index.json")
    idx.add_entry(
        url="local://doc1",
        title="文档1",
        category="阅读与思考",
        folder="f1",
        files=[],
        warnings=[],
        errors=[],
        status="ok",
        item_type="doc",
        source="doc1.pdf",
        content_hash="hash_a",
        fetch_backend="local",
    )
    result = idx.check_dedup("local://doc2", content_hash="hash_b")
    assert result["status"] == "new"
