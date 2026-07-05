"""T017: 验证 clipper.validators 前置校验(FR-013b)。

测试范围:
- validate_file_size: 单文件 ≤20MB
- validate_video_duration: 视频时长 ≤15 分钟
- 超限返回明确拒绝原因
- 合法文件通过校验
"""

from pathlib import Path


class TestValidateFileSize:
    """FR-013b: 文件大小校验"""

    def test_small_file_passes(self, tmp_path: Path):
        from clipper.validators import validate_file_size

        f = tmp_path / "small.pdf"
        f.write_bytes(b"\x00" * 1024)  # 1KB
        result = validate_file_size(f, max_mb=20)
        assert result["valid"] is True

    def test_exact_limit_passes(self, tmp_path: Path):
        from clipper.validators import validate_file_size

        f = tmp_path / "exact.bin"
        f.write_bytes(b"\x00" * (20 * 1024 * 1024))  # exactly 20MB
        result = validate_file_size(f, max_mb=20)
        assert result["valid"] is True

    def test_over_limit_rejected(self, tmp_path: Path):
        from clipper.validators import validate_file_size

        f = tmp_path / "large.pdf"
        f.write_bytes(b"\x00" * (21 * 1024 * 1024))  # 21MB
        result = validate_file_size(f, max_mb=20)
        assert result["valid"] is False
        assert "20" in result["reason"]
        assert "MB" in result["reason"]

    def test_nonexistent_file_rejected(self, tmp_path: Path):
        from clipper.validators import validate_file_size

        f = tmp_path / "nonexistent.pdf"
        result = validate_file_size(f, max_mb=20)
        assert result["valid"] is False


class TestValidateVideoDuration:
    """FR-013b: 视频时长校验"""

    def test_short_video_passes(self):
        from clipper.validators import validate_video_duration

        result = validate_video_duration(300, max_min=15)  # 5 min
        assert result["valid"] is True

    def test_exact_limit_passes(self):
        from clipper.validators import validate_video_duration

        result = validate_video_duration(900, max_min=15)  # exactly 15 min
        assert result["valid"] is True

    def test_over_limit_rejected(self):
        from clipper.validators import validate_video_duration

        result = validate_video_duration(1000, max_min=15)  # 16:40
        assert result["valid"] is False
        assert "15" in result["reason"]
        assert "分钟" in result["reason"]

    def test_zero_duration_passes(self):
        from clipper.validators import validate_video_duration

        result = validate_video_duration(0, max_min=15)
        assert result["valid"] is True
