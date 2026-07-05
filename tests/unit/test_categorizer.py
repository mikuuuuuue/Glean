"""分类器单元测试(T063)。

验证 7 大分类关键词匹配、needs_suggestion、分类上限 6。
"""

from pathlib import Path

import pytest
import yaml

from clipper.categorizer import Categorizer


@pytest.fixture
def categorizer(tmp_path: Path) -> Categorizer:
    """创建临时分类器实例。"""
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
            "科技与AI": ["ai", "代码", "编程", "python", "机器学习"],
            "财经与商业": ["股票", "基金", "投资", "财经", "经济"],
            "游戏与文化": ["游戏", "动漫", "文化", "steam"],
            "阅读与思考": ["读书", "书评", "思考", "哲学"],
            "工具与技巧": ["工具", "技巧", "效率", "教程"],
            "视频与影音": ["视频", "电影", "音乐", "b站"],
        },
        "storage": {"base_dir": str(tmp_path / "clipped_pages")},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    return Categorizer(str(cfg_path))


def test_classify_tech_keywords(categorizer: Categorizer):
    """科技与AI关键词匹配。"""
    assert categorizer.classify("Python 编程入门", "") == "科技与AI"
    assert categorizer.classify("AI 机器学习基础", "") == "科技与AI"


def test_classify_finance_keywords(categorizer: Categorizer):
    """财经与商业关键词匹配。"""
    assert categorizer.classify("股票投资指南", "") == "财经与商业"
    assert categorizer.classify("基金定投策略", "") == "财经与商业"


def test_classify_game_keywords(categorizer: Categorizer):
    """游戏与文化关键词匹配。"""
    assert categorizer.classify("Steam 新游推荐", "") == "游戏与文化"
    assert categorizer.classify("动漫文化杂谈", "") == "游戏与文化"


def test_classify_reading_keywords(categorizer: Categorizer):
    """阅读与思考关键词匹配。"""
    assert categorizer.classify("读书笔记与思考", "") == "阅读与思考"
    assert categorizer.classify("哲学入门书评", "") == "阅读与思考"


def test_classify_tools_keywords(categorizer: Categorizer):
    """工具与技巧关键词匹配。"""
    assert categorizer.classify("效率工具推荐", "") == "工具与技巧"
    assert categorizer.classify("PS 教程技巧", "") == "工具与技巧"


def test_classify_video_keywords(categorizer: Categorizer):
    """视频与影音关键词匹配。"""
    assert categorizer.classify("B站视频精选", "") == "视频与影音"
    assert categorizer.classify("电影音乐赏析", "") == "视频与影音"


def test_classify_fallback_to_other(categorizer: Categorizer):
    """无关键词命中时归入其他收藏。"""
    assert categorizer.classify("一些不相关的内容", "") == "其他收藏"
    assert categorizer.classify("", "") == "其他收藏"


def test_needs_suggestion_true(categorizer: Categorizer):
    """无关键词命中时 needs_suggestion 返回 True。"""
    assert categorizer.needs_suggestion("一些不相关的内容", "") is True


def test_needs_suggestion_false(categorizer: Categorizer):
    """有关键词命中时 needs_suggestion 返回 False。"""
    assert categorizer.needs_suggestion("Python 编程", "") is False


def test_content_based_classification(categorizer: Categorizer):
    """内容也能触发分类匹配。"""
    # 标题无关键词,但内容有
    assert categorizer.classify("随便标题", "这篇文章讲投资和股票") == "财经与商业"


def test_active_categories_excludes_other(categorizer: Categorizer):
    """get_active_categories 排除其他收藏。"""
    active = categorizer.get_active_categories()
    assert "其他收藏" not in active
    assert len(active) == 6


def test_can_add_category_at_limit(categorizer: Categorizer):
    """已有6个分类时不能再添加。"""
    # The fixture has 6 active categories + "其他收藏" = 7 total
    # can_add_category returns False when at 6 active (max)
    assert categorizer.can_add_category() is False
