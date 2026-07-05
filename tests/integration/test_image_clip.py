"""图片剪藏集成测试(T043)。"""

from pathlib import Path

from clipper.image import clip_image, file_content_hash


def test_single_image_clip(tmp_path):
    """单图归档:原图保存,索引记录。"""
    src = tmp_path / "test.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n fake png")
    out = tmp_path / "output"
    result = clip_image([str(src)], out, category="其他收藏")
    assert result["success"] is True
    assert result["md_file"] is not None
    assert len(result["files"]) == 1
    assert Path(result["files"][0]).exists() if result["files"] else True


def test_multi_image_same_dir(tmp_path):
    """多张图片归档于同一目录。"""
    imgs = []
    for i in range(3):
        src = tmp_path / f"img{i}.png"
        src.write_bytes(f"fake image {i}".encode())
        imgs.append(str(src))
    out = tmp_path / "output"
    result = clip_image(imgs, out, category="其他收藏")
    assert result["success"] is True
    assert len(result["files"]) == 3
    # All files in same directory
    for f in result["files"]:
        assert Path(f).parent == out


def test_image_content_hash(tmp_path):
    """相同图片内容哈希相同。"""
    src1 = tmp_path / "img1.png"
    src1.write_bytes(b"same content")
    src2 = tmp_path / "img2.png"
    src2.write_bytes(b"same content")
    assert file_content_hash(src1) == file_content_hash(src2)


def test_image_no_valid_files(tmp_path):
    """无有效图片时返回错误。"""
    out = tmp_path / "output"
    result = clip_image(["/nonexistent/img.png"], out, category="其他收藏")
    assert result["success"] is False
    assert "没有有效" in result["error"]
