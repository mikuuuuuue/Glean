"""文档剪藏集成测试(T048)。"""

from clipper.doc import clip_doc


def test_pdf_clip(tmp_path):
    """PDF 正文抽取与原文件归档。"""
    # Create a minimal fake PDF
    src = tmp_path / "test.pdf"
    src.write_bytes(b"%PDF-1.4\n%%EOF\n")
    out = tmp_path / "output"
    result = clip_doc(str(src), out, category="阅读与思考")
    assert result["doc_type"] == "pdf"
    assert result["md_file"] is not None
    assert len(result["files"]) >= 1  # original file archived


def test_docx_clip(tmp_path):
    """Word 文档正文抽取。"""
    # Create a minimal fake docx (zip)
    import io
    import zipfile

    src = tmp_path / "test.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:t>Hello World</w:t></w:p></w:body></w:document>",
        )
    src.write_bytes(buf.getvalue())
    out = tmp_path / "output"
    result = clip_doc(str(src), out, category="阅读与思考")
    assert result["doc_type"] == "docx"
    assert result["md_file"] is not None


def test_unsupported_doc_type(tmp_path):
    """不支持的文档类型返回错误。"""
    src = tmp_path / "test.txt"
    src.write_text("hello")
    out = tmp_path / "output"
    result = clip_doc(str(src), out, category="阅读与思考")
    assert result["success"] is False
    assert "不支持" in result["error"]
