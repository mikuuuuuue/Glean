"""ASR 全部失败时仍归档视频信息测试(T031, FR-006)。"""

import pytest

from clipper.asr_backend import ASRBackend
from clipper.asr_fallback import FallbackChain


class FailBackend(ASRBackend):
    """始终失败的 ASR 后端,用于测试全失败路径。"""

    def __init__(self, name):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def available(self) -> bool:
        return True

    def supports_language(self, lang: str) -> bool:
        return True

    async def transcribe(self, audio_path, lang="auto"):
        return False, "", [f"{self._name} failed"]


@pytest.mark.asyncio
async def test_asr_all_fail_still_returns_result(tmp_path, tmp_config):
    """所有 ASR 失败时仍返回结构化结果(非崩溃)。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    chain = FallbackChain(
        [FailBackend("bijian"), FailBackend("jianying"), FailBackend("volcengine")],
    )
    result = await chain.transcribe(audio, "auto")
    assert result["success"] is False
    assert result["error"] == "ASR 全部回退失败"
    assert len(result["warnings"]) == 3
    assert result["engine"] is None


@pytest.mark.asyncio
async def test_asr_all_fail_warnings_include_all(tmp_path, tmp_config):
    """所有失败原因都在 warnings 中。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    chain = FallbackChain([FailBackend("bijian"), FailBackend("volcengine")])
    result = await chain.transcribe(audio, "auto")
    assert "bijian failed" in result["warnings"][0]
    assert "volcengine failed" in result["warnings"][1]
