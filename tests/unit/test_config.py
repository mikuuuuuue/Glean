"""T014: 验证 clipper.config 单例配置加载器。

测试范围:
- get_config() 单例缓存
- tmp_path 注入测试配置
- 环境变量覆盖层(GLEAN_FIRECRAWL_API_KEY)
- 默认配置回退
"""

from pathlib import Path

import pytest


class TestConfigSingleton:
    """get_config() 单例与缓存行为"""

    def test_get_config_returns_dict(self, tmp_config: Path):
        from clipper.config import get_config

        cfg = get_config()
        assert isinstance(cfg, dict)

    def test_get_config_caches_singleton(self, tmp_config: Path):
        from clipper.config import get_config

        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_get_config_reset_reload(self, tmp_config: Path, monkeypatch: pytest.MonkeyPatch):
        from clipper.config import get_config

        cfg1 = get_config()
        monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
        cfg2 = get_config()
        assert cfg1 is not cfg2


class TestConfigPathInjection:
    """tmp_path 配置注入"""

    def test_loads_from_custom_path(self, tmp_config: Path):
        from clipper.config import get_config

        cfg = get_config()
        assert cfg["storage"]["base_dir"] == str(Path(tmp_config).parent / "clipped_pages")

    def test_config_has_categories(self, tmp_config: Path):
        from clipper.config import get_config

        cfg = get_config()
        assert "科技与AI" in cfg["categories"]

    def test_config_has_limits(self, tmp_config: Path):
        from clipper.config import get_config

        cfg = get_config()
        assert cfg["limits"]["max_file_size_mb"] == 20
        assert cfg["limits"]["max_video_duration_min"] == 15


class TestEnvOverride:
    """环境变量覆盖层(密钥类)"""

    def test_env_overrides_firecrawl_key(self, tmp_config: Path, monkeypatch: pytest.MonkeyPatch):
        from clipper.config import get_config

        monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
        monkeypatch.setenv("GLEAN_FIRECRAWL_API_KEY", "env-key-12345")

        cfg = get_config()
        assert cfg["scraping"]["firecrawl"]["api_key"] == "env-key-12345"

    def test_env_overrides_volc_token(self, tmp_config: Path, monkeypatch: pytest.MonkeyPatch):
        from clipper.config import get_config

        monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
        monkeypatch.setenv("GLEAN_VOLC_TOKEN", "env-token-abc")

        cfg = get_config()
        assert cfg["asr"]["volcengine"]["token"] == "env-token-abc"


class TestConfigDefaults:
    """默认值回退"""

    def test_missing_keys_use_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """配置文件缺少某些字段时应使用默认值"""
        import yaml as yaml_lib

        # 写一个最小配置,故意缺少 limits 和 screenshot
        minimal_cfg = {
            "storage": {"base_dir": str(tmp_path / "pages"), "index_file": "_index.json"}
        }
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml_lib.dump(minimal_cfg), encoding="utf-8")

        monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
        monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)

        from clipper.config import get_config

        cfg = get_config()
        assert cfg["limits"]["max_file_size_mb"] == 20
        assert cfg["screenshot"]["enabled"] is True
