"""分类器扩展单元测试(T062 覆盖补充)。

补充 clipper/categorizer.py 未覆盖的分支:
  - line 19:  默认 config_path 解析(Categorizer() 无参数)
  - line 48:  无任何关键词时 _classify_with_score 返回其他收藏
  - lines 70-86:  add_category 新增分类(写 config + 建目录)
  - lines 93-107: replace_category 替换分类
  - lines 111-114: _save_config 回写 yaml
"""

from pathlib import Path

import pytest
import yaml

from clipper.categorizer import Categorizer

# ── fixture ────────────────────────────────────────────────


@pytest.fixture
def small_categorizer(tmp_path: Path) -> Categorizer:
    """创建一个分类数 < 6 的分类器(允许新增分类)。"""
    cfg = {
        "categories": ["科技与AI", "其他收藏"],
        "category_keywords": {"科技与AI": ["python", "ai"], "其他收藏": []},
        "storage": {"base_dir": str(tmp_path / "clipped_pages")},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    return Categorizer(str(cfg_path))


@pytest.fixture
def empty_keywords_categorizer(tmp_path: Path) -> Categorizer:
    """创建一个无任何关键词的分类器(命中 line 48)。"""
    cfg = {
        "categories": ["科技与AI", "其他收藏"],
        "category_keywords": {},  # 空 → scores 为空
        "storage": {"base_dir": str(tmp_path / "clipped_pages")},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    return Categorizer(str(cfg_path))


@pytest.fixture
def full_categorizer(tmp_path: Path) -> Categorizer:
    """创建一个已达 6 上限的分类器(用于上限与替换测试)。"""
    cfg = {
        "categories": [
            "科技与AI",
            "财经与商业",
            "游戏与文化",
            "阅读与思考",
            "工具与技巧",
            "视频与影音",
            "其他收藏",
        ],
        "category_keywords": {
            "科技与AI": ["python"],
            "财经与商业": ["股票"],
            "游戏与文化": ["游戏"],
            "阅读与思考": ["读书"],
            "工具与技巧": ["工具"],
            "视频与影音": ["视频"],
        },
        "storage": {"base_dir": str(tmp_path / "clipped_pages")},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    return Categorizer(str(cfg_path))


# ── line 19: 默认 config_path ───────────────────────────────


def test_default_config_path_resolves_to_project_root():
    """Categorizer() 无参数时使用项目根 config.yaml(line 19)。"""
    c = Categorizer()  # 使用默认路径
    # 默认路径应指向项目根的 config.yaml
    assert c.config_path.endswith("config.yaml")
    # 应成功加载分类(项目根 config.yaml 含 7 大分类)
    assert len(c.categories) >= 2
    assert "其他收藏" in c.categories


# ── line 48: 无关键词时返回其他收藏 ────────────────────────────


def test_classify_no_keywords_returns_other(empty_keywords_categorizer: Categorizer):
    """无任何关键词命中 _classify_with_score 走 line 48(空 scores 分支)。"""
    assert empty_keywords_categorizer.classify("Python 编程", "") == "其他收藏"
    assert empty_keywords_categorizer.classify("任何内容", "") == "其他收藏"


def test_classify_with_score_zero_when_empty_keywords(empty_keywords_categorizer: Categorizer):
    """空关键词时 _classify_with_score 返回 (其他收藏, 0)。"""
    best, score = empty_keywords_categorizer._classify_with_score("任意标题", "任意内容")
    assert best == "其他收藏"
    assert score == 0


def test_needs_suggestion_true_when_no_keywords(empty_keywords_categorizer: Categorizer):
    """空关键词时 needs_suggestion 返回 True。"""
    assert empty_keywords_categorizer.needs_suggestion("任意", "") is True


# ── can_add_category / 上限 ──────────────────────────────────


def test_can_add_category_when_below_limit(small_categorizer: Categorizer):
    """分类数 < 6 时 can_add_category 返回 True。"""
    assert small_categorizer.can_add_category() is True


def test_cannot_add_category_at_limit(full_categorizer: Categorizer):
    """已达 6 上限时 can_add_category 返回 False。"""
    assert full_categorizer.can_add_category() is False


# ── lines 70-86 + 111-114: add_category ─────────────────────


def test_add_category_success(small_categorizer: Categorizer, tmp_path: Path):
    """新增分类:更新内存、写 config.yaml、建目录。"""
    added = small_categorizer.add_category("新分类", ["关键词1", "关键词2"])
    assert added is True
    # 内存更新:插在"其他收藏"前面
    assert "新分类" in small_categorizer.categories
    assert small_categorizer.categories[-1] == "其他收藏"
    idx_new = small_categorizer.categories.index("新分类")
    idx_other = small_categorizer.categories.index("其他收藏")
    assert idx_new < idx_other
    # 关键词更新
    assert small_categorizer.keywords["新分类"] == ["关键词1", "关键词2"]
    # config.yaml 已回写(_save_config, line 111-114)
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert "新分类" in saved["categories"]
    assert saved["category_keywords"]["新分类"] == ["关键词1", "关键词2"]
    # 目录已创建
    assert (tmp_path / "clipped_pages" / "新分类").is_dir()


def test_add_category_default_keywords(small_categorizer: Categorizer):
    """新增分类不传关键词时用分类名自身作为关键词。"""
    added = small_categorizer.add_category("默认分类")
    assert added is True
    assert small_categorizer.keywords["默认分类"] == ["默认分类"]


def test_add_category_at_limit_returns_false(full_categorizer: Categorizer):
    """已达 6 上限时 add_category 返回 False(line 70-71)。"""
    added = full_categorizer.add_category("多余分类", ["x"])
    assert added is False
    assert "多余分类" not in full_categorizer.categories


def test_add_category_empty_name_returns_false(small_categorizer: Categorizer):
    """空名(或纯空白)新增返回 False(line 74)。"""
    assert small_categorizer.add_category("   ") is False
    assert small_categorizer.add_category("") is False


def test_add_category_duplicate_returns_false(small_categorizer: Categorizer):
    """已存在的分类名新增返回 False(line 74)。"""
    assert small_categorizer.add_category("科技与AI", ["x"]) is False


def test_add_category_multiple_until_limit(small_categorizer: Categorizer):
    """连续新增直到达上限(6 个非其他收藏)。"""
    c = small_categorizer
    # 当前 1 个非其他收藏(科技与AI),还能加 5 个
    for i in range(5):
        assert c.add_category(f"分类{i}") is True
    # 现在有 6 个非其他收藏,再加应失败
    assert c.can_add_category() is False
    assert c.add_category("第七个") is False


# ── lines 93-107 + 111-114: replace_category ────────────────


def test_replace_category_success(full_categorizer: Categorizer, tmp_path: Path):
    """替换分类:更新内存、写 config、建新目录。"""
    replaced = full_categorizer.replace_category("工具与技巧", "效率工具", ["效率", "工具"])
    assert replaced is True
    assert "工具与技巧" not in full_categorizer.categories
    assert "效率工具" in full_categorizer.categories
    # 关键词迁移:旧名移除,新名写入
    assert "工具与技巧" not in full_categorizer.keywords
    assert full_categorizer.keywords["效率工具"] == ["效率", "工具"]
    # 位置保持不变
    idx = full_categorizer.categories.index("效率工具")
    assert full_categorizer.categories[idx - 1] == "阅读与思考"
    # config.yaml 已回写
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert "效率工具" in saved["categories"]
    assert "工具与技巧" not in saved["categories"]
    # 新目录已创建
    assert (tmp_path / "clipped_pages" / "效率工具").is_dir()


def test_replace_category_default_keywords(full_categorizer: Categorizer):
    """替换分类不传关键词时用新分类名自身。"""
    replaced = full_categorizer.replace_category("游戏与文化", "娱乐文化")
    assert replaced is True
    assert full_categorizer.keywords["娱乐文化"] == ["娱乐文化"]


def test_replace_category_nonexistent_returns_false(full_categorizer: Categorizer):
    """旧分类不存在时替换返回 False(line 93)。"""
    assert full_categorizer.replace_category("不存在", "新名") is False


def test_replace_category_other_returns_false(full_categorizer: Categorizer):
    """不能替换"其他收藏"(line 93)。"""
    assert full_categorizer.replace_category("其他收藏", "新收藏") is False
    assert "其他收藏" in full_categorizer.categories


def test_replace_category_empty_new_returns_false(full_categorizer: Categorizer):
    """新分类名为空时替换返回 False(line 95-96)。"""
    assert full_categorizer.replace_category("科技与AI", "   ") is False
    assert full_categorizer.replace_category("科技与AI", "") is False


def test_replace_category_duplicate_new_returns_false(full_categorizer: Categorizer):
    """新分类名已存在时替换返回 False(line 96)。"""
    assert full_categorizer.replace_category("科技与AI", "财经与商业") is False


# ── _save_config 内容验证 ───────────────────────────────────


def test_save_config_preserves_other_fields(tmp_path: Path):
    """_save_config 回写时保留 config 中的其他字段(不丢失)。"""
    cfg = {
        "categories": ["科技与AI", "其他收藏"],
        "category_keywords": {"科技与AI": ["python"]},
        "storage": {"base_dir": str(tmp_path / "clipped_pages")},
        "features": {"download_images": True, "ai_summary": False},
        "extra_field": "should_be_preserved",
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    c = Categorizer(str(cfg_path))
    c.add_category("新分类", ["kw"])
    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    # 其他字段保留
    assert saved["features"]["download_images"] is True
    assert saved["extra_field"] == "should_be_preserved"
    # categories 与 category_keywords 已更新
    assert "新分类" in saved["categories"]
    assert saved["category_keywords"]["新分类"] == ["kw"]
