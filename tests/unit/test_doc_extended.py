"""文档剪藏扩展单元测试(T062 覆盖补充)。

补充 clipper/doc.py 未覆盖的分支:
  - lines 62-63:  文件大小超限 warning
  - lines 72-75:  原文件存档失败
  - lines 89-109: docx 正文抽取(段落 / 标题样式 / 字数)
  - lines 114-123: pdf 正文抽取(页数 / 文本 / 字数)
  - category_fn 回调与结果结构字段
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from clipper.doc import clip_doc

# ── 辅助:创建最小占位源文件 ──────────────────────────────────


def _make_pdf(tmp_path: Path, name: str = "test.pdf") -> Path:
    src = tmp_path / name
    src.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return src


def _make_docx(tmp_path: Path, name: str = "test.docx") -> Path:
    src = tmp_path / name
    src.write_bytes(b"fake docx bytes")
    return src


# ── lines 62-63: 文件大小超限 warning ────────────────────────


def test_clip_doc_size_warning(tmp_path: Path):
    """文件大小超限时 warnings 含拒绝原因(line 62-63)。

    注: doc.py 用 ``size_ok, size_err = validate_file_size(src)`` 解包,
    而 validators 返回 dict。这里 mock validate_file_size 返回元组 (False, err)
    以触发超限分支。
    """
    src = _make_pdf(tmp_path)
    out = tmp_path / "output"

    # mock pypdf 抽取,避免真实解析占位 pdf 失败干扰断言
    mock_reader = MagicMock()
    mock_reader.pages = []
    with (
        patch(
            "clipper.validators.validate_file_size",
            return_value=(False, "文件大小 25.0MB 超过限制 20MB"),
        ),
        patch("pypdf.PdfReader", return_value=mock_reader),
    ):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True  # 抽取本身成功(空 pages)
    assert "文件大小 25.0MB 超过限制 20MB" in result["warnings"]
    assert result["doc_type"] == "pdf"
    # 原文件仍归档
    assert len(result["files"]) >= 1


# ── lines 72-75: 原文件存档失败 ──────────────────────────────


def test_clip_doc_save_original_failure(tmp_path: Path):
    """原文件存档失败时返回 error 并提前返回(line 72-75)。"""
    src = _make_pdf(tmp_path)
    out = tmp_path / "output"

    with patch("clipper.doc.shutil.copy2", side_effect=OSError("disk full")):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is False
    assert "保存原文件失败" in result["error"]
    assert "disk full" in result["error"]
    # files 为空(未成功归档)
    assert result["files"] == []
    # md_file 未生成(提前返回)
    assert result["md_file"] is None


# ── lines 89-109: docx 正文抽取 ──────────────────────────────


def _make_docx_mock(paragraphs):
    """构造 python-docx Document mock,paragraphs 为 [(text, style_name), ...]。"""
    para_objs = []
    for text, style_name in paragraphs:
        para = MagicMock()
        para.text = text
        if style_name is None:
            para.style = None
        else:
            para.style = MagicMock()
            para.style.name = style_name
        para_objs.append(para)
    doc = MagicMock()
    doc.paragraphs = para_objs
    return doc


def test_clip_docx_extraction_with_headings(tmp_path: Path):
    """docx 抽取:Heading 1/2/3/Title/普通段落 正确转 markdown(line 89-109)。"""
    src = _make_docx(tmp_path, "报告.docx")
    out = tmp_path / "output"

    paragraphs = [
        ("文档主标题", "Title"),  # → # 文档主标题
        ("", "Normal"),  # 空段落 → ""
        ("第一章 概述", "Heading 1"),  # → # 第一章 概述
        ("正文内容一", "Normal"),  # → 正文内容一
        ("1.1 背景", "Heading 2"),  # → ## 1.1 背景
        ("详细描述", "Normal"),
        ("1.1.1 细节", "Heading 3"),  # → ### 1.1.1 细节
        ("四级标题", "Heading 4"),  # → #### 四级标题(通用 heading)
        ("结尾段落", "Normal"),
    ]
    mock_doc = _make_docx_mock(paragraphs)

    with patch("docx.Document", return_value=mock_doc):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True
    assert result["doc_type"] == "docx"
    assert result["md_file"] is not None
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    # 标题样式正确转换
    assert "# 文档主标题" in md
    assert "# 第一章 概述" in md
    assert "## 1.1 背景" in md
    assert "### 1.1.1 细节" in md
    assert "#### 四级标题" in md
    assert "正文内容一" in md
    # 原文件已归档
    assert any("报告.docx" in f for f in result["files"])
    # word_count 为非空段落字符数总和
    assert result["word_count"] is not None
    assert result["word_count"] > 0


def test_clip_docx_extraction_normal_only(tmp_path: Path):
    """docx 全为普通段落(无 heading)时 body_md 为纯文本。"""
    src = _make_docx(tmp_path, "plain.docx")
    out = tmp_path / "output"

    paragraphs = [("第一段正文", "Normal"), ("第二段正文", "Normal")]
    mock_doc = _make_docx_mock(paragraphs)

    with patch("docx.Document", return_value=mock_doc):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "第一段正文" in md
    assert "第二段正文" in md
    assert result["word_count"] == len("第一段正文") + len("第二段正文")


def test_clip_docx_extraction_none_style(tmp_path: Path):
    """docx 段落 style 为 None 时不报错(line 95 的 None 判断)。"""
    src = _make_docx(tmp_path, "nostyle.docx")
    out = tmp_path / "output"

    mock_doc = _make_docx_mock([("无样式段落", None)])
    with patch("docx.Document", return_value=mock_doc):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "无样式段落" in md


def test_clip_docx_extraction_failure_falls_back(tmp_path: Path):
    """docx 抽取抛异常时仍落占位 md,success=False(line 124-130)。"""
    src = _make_docx(tmp_path, "broken.docx")
    out = tmp_path / "output"

    with patch("docx.Document", side_effect=RuntimeError("加密文档无法解析")):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is False
    assert "正文抽取失败" in result["error"]
    assert any("正文抽取失败" in w for w in result["warnings"])
    # 仍生成占位 md
    assert result["md_file"] is not None
    assert Path(result["md_file"]).exists()
    # 原文件仍归档
    assert len(result["files"]) >= 1


# ── lines 114-123: pdf 正文抽取 ──────────────────────────────


def _make_pdf_reader_mock(pages_text):
    """构造 pypdf PdfReader mock,pages_text 为每页文本列表。"""
    pages = []
    for txt in pages_text:
        page = MagicMock()
        page.extract_text = MagicMock(return_value=txt)
        pages.append(page)
    reader = MagicMock()
    reader.pages = pages
    return reader


def test_clip_pdf_extraction_with_pages(tmp_path: Path):
    """pdf 抽取:多页文本正确拼接,page_count/word_count 正确(line 114-123)。"""
    src = _make_pdf(tmp_path, "文档.pdf")
    out = tmp_path / "output"

    mock_reader = _make_pdf_reader_mock(["第一页内容", "第二页内容"])
    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True
    assert result["doc_type"] == "pdf"
    assert result["page_count"] == 2
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "## 页 1" in md
    assert "第一页内容" in md
    assert "## 页 2" in md
    assert "第二页内容" in md
    # word_count = 各页文本长度之和(含 "## 页 N\n\n" 前缀)
    assert result["word_count"] > 0


def test_clip_pdf_extraction_single_page(tmp_path: Path):
    """pdf 单页抽取。"""
    src = _make_pdf(tmp_path, "single.pdf")
    out = tmp_path / "output"

    mock_reader = _make_pdf_reader_mock(["唯一一页的文本"])
    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True
    assert result["page_count"] == 1
    assert "唯一一页的文本" in Path(result["md_file"]).read_text(encoding="utf-8")


def test_clip_pdf_extraction_page_text_failure(tmp_path: Path):
    """pdf 某页 extract_text 抛异常时该页文本为空(不阻断整体,line 119-120)。"""
    src = _make_pdf(tmp_path, "partial.pdf")
    out = tmp_path / "output"

    page1 = MagicMock()
    page1.extract_text = MagicMock(return_value="正常页")
    page2 = MagicMock()
    page2.extract_text = MagicMock(side_effect=RuntimeError("parse error"))
    mock_reader = MagicMock()
    mock_reader.pages = [page1, page2]

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True
    assert result["page_count"] == 2
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "正常页" in md
    # 第二页文本为空但仍有页标题
    assert "## 页 2" in md


def test_clip_pdf_empty_pages(tmp_path: Path):
    """pdf 无页时 page_count=0,正文为空提示。"""
    src = _make_pdf(tmp_path, "empty.pdf")
    out = tmp_path / "output"

    mock_reader = MagicMock()
    mock_reader.pages = []
    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is True
    assert result["page_count"] == 0
    assert result["word_count"] == 0


def test_clip_pdf_extraction_failure_falls_back(tmp_path: Path):
    """pdf 抽取抛异常时仍落占位 md,success=False。"""
    src = _make_pdf(tmp_path, "broken.pdf")
    out = tmp_path / "output"

    with patch("pypdf.PdfReader", side_effect=RuntimeError("加密 pdf")):
        result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is False
    assert "正文抽取失败" in result["error"]
    assert result["md_file"] is not None
    assert Path(result["md_file"]).exists()


# ── category_fn 回调 ────────────────────────────────────────


def test_clip_doc_category_fn_overrides_category(tmp_path: Path):
    """category_fn 返回新分类时覆盖默认 category。"""
    src = _make_pdf(tmp_path, "ai.pdf")
    out = tmp_path / "output"

    mock_reader = _make_pdf_reader_mock(["AI 与 机器学习 内容"])

    def cat_fn(title, body):
        assert "ai" in body.lower()
        return "科技与AI"

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(str(src), out, category="阅读与思考", category_fn=cat_fn)

    assert result["success"] is True
    assert result["category"] == "科技与AI"


def test_clip_doc_category_fn_returns_falsy_keeps_default(tmp_path: Path):
    """category_fn 返回 falsy 时保持默认 category。"""
    src = _make_pdf(tmp_path, "x.pdf")
    out = tmp_path / "output"

    mock_reader = _make_pdf_reader_mock(["内容"])

    def cat_fn(title, body):
        return ""  # falsy

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(str(src), out, category="阅读与思考", category_fn=cat_fn)

    assert result["category"] == "阅读与思考"


def test_clip_doc_category_fn_raises_keeps_default(tmp_path: Path):
    """category_fn 抛异常时被 suppress,保持默认 category。"""
    src = _make_pdf(tmp_path, "x.pdf")
    out = tmp_path / "output"

    mock_reader = _make_pdf_reader_mock(["内容"])

    def cat_fn(title, body):
        raise ValueError("boom")

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(str(src), out, category="阅读与思考", category_fn=cat_fn)

    assert result["category"] == "阅读与思考"


# ── 结果结构字段 ────────────────────────────────────────────


def test_clip_doc_result_structure_fields(tmp_path: Path):
    """结果 dict 含全部约定字段(success/title/md_file/files/page_count/...)。"""
    src = _make_pdf(tmp_path, "struct.pdf")
    out = tmp_path / "output"

    mock_reader = _make_pdf_reader_mock(["正文"])
    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = clip_doc(
            str(src), out, category="阅读与思考", source_url="https://example.com/doc"
        )

    expected_keys = {
        "success",
        "title",
        "md_file",
        "files",
        "page_count",
        "word_count",
        "doc_type",
        "warnings",
        "error",
        "fetch_backend",
        "category",
    }
    assert expected_keys.issubset(result.keys())
    assert result["success"] is True
    assert result["title"] == "struct"  # src.stem
    assert result["doc_type"] == "pdf"
    assert result["fetch_backend"] == "local"
    assert result["page_count"] == 1
    assert result["error"] is None
    # source_url 写入 md
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "https://example.com/doc" in md


def test_clip_doc_unsupported_type(tmp_path: Path):
    """不支持的文档类型返回 error(line 53-54)。"""
    src = tmp_path / "file.txt"
    src.write_text("hello")
    out = tmp_path / "output"

    result = clip_doc(str(src), out, category="阅读与思考")

    assert result["success"] is False
    assert "不支持" in result["error"]
    assert result["doc_type"] is None
