"""T016: 验证 clipper.folder 目录命名工具(FR-009a)。

测试范围:
- 目录名冲突时追加 -1/-2 后缀
- 无冲突时返回原路径
- 多次冲突递增后缀
"""

from pathlib import Path


class TestUniqueFolder:
    """FR-009a: 目录命名冲突自动追加数字后缀"""

    def test_no_conflict_returns_base(self, tmp_path: Path):
        from clipper.folder import unique_folder

        base = tmp_path / "20260704_120000_Example"
        result = unique_folder(base)
        assert result == base

    def test_conflict_appends_1(self, tmp_path: Path):
        from clipper.folder import unique_folder

        base = tmp_path / "20260704_120000_Example"
        base.mkdir()

        result = unique_folder(base)
        assert result == tmp_path / "20260704_120000_Example-1"

    def test_conflict_appends_incrementing(self, tmp_path: Path):
        from clipper.folder import unique_folder

        base = tmp_path / "20260704_120000_Example"
        base.mkdir()
        (tmp_path / "20260704_120000_Example-1").mkdir()
        (tmp_path / "20260704_120000_Example-2").mkdir()

        result = unique_folder(base)
        assert result == tmp_path / "20260704_120000_Example-3"

    def test_created_dir_does_not_overwrite(self, tmp_path: Path):
        """生成的目录路径确实不存在(不会覆盖)"""
        from clipper.folder import unique_folder

        base = tmp_path / "20260704_120000_Example"
        base.mkdir()
        # 在 base 下写一个文件
        (base / "original.md").write_text("original", encoding="utf-8")

        result = unique_folder(base)
        result.mkdir()
        # 原 base 下的文件应不受影响
        assert (base / "original.md").read_text(encoding="utf-8") == "original"
        # 新目录是空的
        assert not (result / "original.md").exists()


class TestSafeFolderName:
    """safe_folder_name 截断与清洗"""

    def test_truncates_long_title(self, tmp_path: Path):
        from clipper.folder import safe_folder_name

        long_title = "A" * 100
        name = safe_folder_name(long_title)
        assert len(name) <= 50  # 时间戳+标题应受控

    def test_removes_invalid_chars(self, tmp_path: Path):
        from clipper.folder import safe_folder_name

        name = safe_folder_name("Hello<World>|?:*")
        # Windows 非法字符应被移除或替换
        assert "<" not in name
        assert ">" not in name
        assert "|" not in name
        assert "?" not in name
        assert ":" not in name
        assert "*" not in name
