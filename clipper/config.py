"""统一配置加载器 - 单例模式,支持 tmp_path 注入与环境变量覆盖。

替代各模块的 _load_config(),集中管理配置读取。
测试可通过 monkeypatch clipper.config._CONFIG_CACHE = None 强制重新加载。
"""

import os
from pathlib import Path
from typing import Any

import yaml

# ── 模块级缓存(测试可通过 monkeypatch 重置) ────────────────
_CONFIG_CACHE: dict[str, Any] | None = None

# 默认配置文件路径(测试可通过 monkeypatch 注入)
_DEFAULT_CONFIG_PATH: Path | None = None

# ── 默认值(配置文件缺失字段时回退) ──────────────────────────
_DEFAULTS: dict[str, Any] = {
    "storage": {"base_dir": "./clipped_pages", "index_file": "_index.json"},
    "categories": [
        "科技与AI",
        "财经与商业",
        "游戏与文化",
        "阅读与思考",
        "工具与技巧",
        "视频与影音",
        "其他收藏",
    ],
    "category_keywords": {},
    "features": {"download_images": True, "video_subtitle": True, "ai_summary": False},
    "scraping": {"backend": "local", "firecrawl": {"api_key": ""}},
    "limits": {
        "max_images": 20,
        "max_content_chars": 50000,
        "image_timeout": 10,
        "page_fetch_timeout": 20,
        "max_file_size_mb": 20,
        "max_video_duration_min": 15,
    },
    "screenshot": {
        "enabled": True,
        "engine": "auto",
        "timeout": 30,
        "user_agent": "",
        "full_page": True,
        "store_screenshot": True,
    },
    "asr": {
        "enabled": False,
        "fallback_chain": ["videocaptioner:bijian", "videocaptioner:jianying", "volcengine"],
        "videocaptioner": {"language": "auto", "timeout": 600},
        "volcengine": {"appid": "", "token": "", "cluster": ""},
    },
    "unsupported_image_domains": [],
}

# ── 环境变量覆盖映射 ────────────────────────────────────────
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "GLEAN_FIRECRAWL_API_KEY": ("scraping", "firecrawl", "api_key"),
    "GLEAN_VOLC_TOKEN": ("asr", "volcengine", "token"),
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并 override 到 base(override 优先)。"""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _get_config_path() -> Path:
    """获取配置文件路径(优先用注入的 _DEFAULT_CONFIG_PATH)。"""
    if _DEFAULT_CONFIG_PATH is not None:
        return Path(_DEFAULT_CONFIG_PATH)
    return Path(__file__).parent.parent / "config.yaml"


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """应用环境变量覆盖(密钥类,优先级高于文件)。"""
    for env_key, path_tuple in _ENV_OVERRIDES.items():
        env_val = os.environ.get(env_key)
        if env_val is not None:
            d = cfg
            for key in path_tuple[:-1]:
                if key not in d or not isinstance(d[key], dict):
                    d[key] = {}
                d = d[key]
            d[path_tuple[-1]] = env_val
    return cfg


def _load_config() -> dict[str, Any]:
    """从 YAML 文件加载配置,合并默认值,应用环境变量覆盖。"""
    path = _get_config_path()
    try:
        with open(path, encoding="utf-8") as f:
            file_cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        file_cfg = {}

    cfg = _deep_merge(_DEFAULTS, file_cfg)
    cfg = _apply_env_overrides(cfg)
    return cfg


def get_config() -> dict[str, Any]:
    """获取全局配置单例。

    首次调用时从 YAML 加载,后续调用返回缓存的同一 dict 对象。
    测试可通过 monkeypatch clipper.config._CONFIG_CACHE = None 强制重新加载。
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = _load_config()
    return _CONFIG_CACHE


class ConfigProxy:
    """配置代理:每次 .get() 从单例获取,支持测试时重置缓存。

    用于模块级 _CONFIG 变量,替代静态 _CONFIG = get_config()。
    这样模块级代码无需修改,只需 _CONFIG = ConfigProxy() 即可动态读取。
    """

    __slots__ = ()

    def get(self, key: str, default: Any = None) -> Any:
        return get_config().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return get_config()[key]
