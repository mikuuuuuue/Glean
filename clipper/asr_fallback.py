"""ASR 分级回退编排器(T036)。

注入 backend 列表,逐级尝试,每级 structlog 记录(FR-005)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clipper.asr_backend import ASRBackend
from clipper.config import get_config
from clipper.logging import get_logger

_log = get_logger("clipper.asr_fallback")


class FallbackChain:
    """ASR 分级回退编排器。

    注入 backend 列表,逐级尝试:
    - 跳过 unavailable 的 backend
    - 跳过不支持指定语言的 backend
    - 每级失败经 structlog 记录
    - 首个成功即返回
    """

    def __init__(self, backends: list[ASRBackend], log: Any = None):
        self._backends = backends
        self._log = log or _log

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> dict[str, Any]:
        """逐级尝试转写。

        Returns:
            dict: {success, text, engine, transcript_file, warnings, error}
            匹配 transcribe_with_fallback() 的返回结构
        """
        result: dict[str, Any] = {
            "success": False,
            "text": "",
            "engine": None,
            "transcript_file": None,
            "warnings": [],
            "error": None,
        }

        if not audio_path or not audio_path.exists():
            result["error"] = "音频文件不存在,无法 ASR"
            return result

        cfg = get_config().get("asr", {})
        keep_transcript = cfg.get("keep_transcript", True)

        for backend in self._backends:
            if not backend.available():
                self._log.info("asr_backend_unavailable", backend=backend.name)
                continue

            if not backend.supports_language(language):
                self._log.info("asr_backend_lang_skip", backend=backend.name, language=language)
                continue

            self._log.info("asr_backend_try", backend=backend.name, language=language)
            ok, text, warns = await backend.transcribe(audio_path, language)

            result["warnings"] += warns

            if ok and text.strip():
                result.update(success=True, text=text, engine=backend.name)
                if keep_transcript:
                    tf = audio_path.parent / "transcript.txt"
                    tf.parent.mkdir(parents=True, exist_ok=True)
                    tf.write_text(text, encoding="utf-8")
                    result["transcript_file"] = str(tf)
                self._log.info("asr_success", engine=backend.name)
                return result

            self._log.info(
                "asr_backend_failed", backend=backend.name, error=warns[-1] if warns else "unknown"
            )

        if not result["success"]:
            result["error"] = "ASR 全部回退失败"
        return result


def build_default_chain() -> FallbackChain:
    """根据配置构建默认的 ASR 回退链。"""
    from clipper.asr_bijian import BijianBackend
    from clipper.asr_jianying import JianyingBackend
    from clipper.asr_volcengine import VolcengineBackend

    cfg = get_config().get("asr", {})
    chain_config = cfg.get(
        "fallback_chain",
        [
            "videocaptioner:bijian",
            "videocaptioner:jianying",
            "volcengine",
        ],
    )

    backend_map: dict[str, ASRBackend] = {
        "videocaptioner:bijian": BijianBackend(),
        "videocaptioner:jianying": JianyingBackend(),
        "volcengine": VolcengineBackend(),
    }

    backends = [backend_map[step] for step in chain_config if step in backend_map]
    return FallbackChain(backends)
