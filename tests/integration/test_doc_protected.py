"""加密/损坏文档优雅降级测试(T050, FR-013)。"""

from clipper.doc import clip_doc


def test_corrupted_pdf_graceful(tmp_path):
    """损坏的 PDF 不崩溃,生成失败占位 md。"""
    src = tmp_path / "corrupt.pdf"
    src.write_bytes(b"not a real pdf")
    out = tmp_path / "output"
    result = clip_doc(str(src), out, category="阅读与思考")
    # Should not crash, should produce some result
    assert result["doc_type"] == "pdf"
    assert result["md_file"] is not None  # placeholder md
    # Error should be recorded
    assert result["error"] is not None or "抽取失败" in str(result.get("warnings", []))


def test_encrypted_docx_graceful(tmp_path):
    """加密的 Word 不崩溃。"""
    src = tmp_path / "encrypted.docx"
    src.write_bytes(b"encrypted content not a real docx")
    out = tmp_path / "output"
    result = clip_doc(str(src), out, category="阅读与思考")
    assert result["doc_type"] == "docx"
    assert result["md_file"] is not None  # placeholder md


def test_no_half_dir_on_failure(tmp_path):
    """失败时不产生半成品目录(原文件应已归档)。"""
    src = tmp_path / "bad.pdf"
    src.write_bytes(b"bad content")
    out = tmp_path / "output"
    result = clip_doc(str(src), out, category="阅读与思考")
    # output dir should exist with at least the original file
    assert out.exists()
    assert len(result["files"]) >= 1
