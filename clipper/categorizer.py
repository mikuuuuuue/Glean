"""领域分类模块 - 基于关键词匹配"""
import os
import shutil
from pathlib import Path
from typing import Optional

import yaml


class Categorizer:
    """根据标题和内容自动分类"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        self.config_path = config_path
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.categories = list(self.config.get("categories", ["其他收藏"]))
        self.keywords = dict(self.config.get("category_keywords", {}))

        self.base_dir = self.config.get("storage", {}).get("base_dir", "./clipped_pages")
        self.base_dir = os.path.abspath(
            os.path.join(Path(__file__).parent.parent, self.base_dir)
        )

        # 确保所有分类目录存在
        for cat in self.categories:
            os.makedirs(os.path.join(self.base_dir, cat), exist_ok=True)

    def classify(self, title: str = "", content: str = "") -> str:
        """根据标题和内容判断分类，返回分类名"""
        best, _ = self._classify_with_score(title, content)
        return best

    def _classify_with_score(self, title: str = "", content: str = "") -> tuple:
        """返回 (分类名, 最高分)"""
        text = (title + " " + content).lower()
        scores = {}
        for category, keywords in self.keywords.items():
            score = sum(1 for kw in keywords if kw.lower() in text)
            scores[category] = score

        best = max(scores, key=scores.get)
        return (best, scores[best]) if scores[best] > 0 else ("其他收藏", 0)

    def needs_suggestion(self, title: str = "", content: str = "") -> bool:
        """是否应该建议用户新增分类（当前分类为"其他收藏"且无任何关键词命中）"""
        _, score = self._classify_with_score(title, content)
        return score == 0

    def get_active_categories(self) -> list:
        """获取除"其他收藏"外的所有分类"""
        return [c for c in self.categories if c != "其他收藏"]

    def can_add_category(self) -> bool:
        """是否还能新增分类（限制6个，不含其他收藏）"""
        return len(self.get_active_categories()) < 6

    def add_category(self, name: str, keywords: list = None) -> bool:
        """新增一个分类（写入 config.yaml 并创建目录）

        返回 False 如果已达上限（6个）。
        """
        if not self.can_add_category():
            return False

        name = name.strip()
        if not name or name in self.categories:
            return False

        # 更新内存
        self.categories.insert(-1, name)  # 插在"其他收藏"前面
        self.keywords[name] = keywords or [name]

        # 写入 config.yaml
        self._save_config()

        # 创建目录
        os.makedirs(os.path.join(self.base_dir, name), exist_ok=True)
        return True

    def replace_category(self, old: str, new: str, keywords: list = None) -> bool:
        """替换一个分类（删除旧分类目录，创建新分类目录）

        文件移动由调用方负责。
        """
        if old not in self.categories or old == "其他收藏":
            return False
        new = new.strip()
        if not new or new in self.categories:
            return False

        idx = self.categories.index(old)
        self.categories[idx] = new
        self.keywords.pop(old, None)
        self.keywords[new] = keywords or [new]

        self._save_config()

        os.makedirs(os.path.join(self.base_dir, new), exist_ok=True)
        return True

    def _save_config(self):
        """回写 config.yaml"""
        self.config["categories"] = self.categories
        self.config["category_keywords"] = self.keywords
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)