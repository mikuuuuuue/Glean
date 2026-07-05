"""VideoCaptioner API 契约测试(T031a)。

验证 bijian/jianying 后端的模块路径与类名契约(宪法原则 IV)。
"""

from unittest.mock import patch

from clipper.asr_bijian import BijianBackend
from clipper.asr_jianying import JianyingBackend


def test_bijian_backend_name():
    assert BijianBackend().name == "bijian"


def test_jianying_backend_name():
    assert JianyingBackend().name == "jianying"


def test_bijian_supports_chinese():
    assert BijianBackend().supports_language("zh") is True
    assert BijianBackend().supports_language("zh-CN") is True


def test_bijian_not_support_japanese():
    assert BijianBackend().supports_language("ja") is False


def test_jianying_supports_english():
    assert JianyingBackend().supports_language("en") is True


def test_bijian_not_available_without_install():
    """VideoCaptioner 未安装时 available() 返回 False。"""
    backend = BijianBackend()
    # 模拟 videocaptioner 未安装(import 时抛 ImportError)
    with patch.dict("sys.modules", {"videocaptioner": None}):
        assert backend.available() is False


def test_jianying_not_available_without_install():
    backend = JianyingBackend()
    with patch.dict("sys.modules", {"videocaptioner": None}):
        assert backend.available() is False
