"""必剪 ASR 后端(T033)。

封装 VideoCaptioner bijian 引擎的 subprocess 调用。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from clipper.asr_backend import ASRBackend
from clipper.config import get_config
from clipper.logging import get_logger

_log = get_logger("clipper.asr_bijian")

# bijian 仅支持中英文
_ZH_EN_LANGS = {"auto", "zh", "en", "zh-CN", "en-US", "zh-Hans", "zh-TW"}


class BijianBackend(ASRBackend):
    """必剪 ASR 后端,通过 VideoCaptioner Python API 调用。"""

    @property
    def name(self) -> str:
        return "bijian"

    def available(self) -> bool:
        try:
            from clipper.vc_cache_init import ensure_videocaptioner_cache

            ensure_videocaptioner_cache()
            import videocaptioner  # noqa: F401
        except ImportError:
            return False
        return True

    def supports_language(self, language: str) -> bool:
        return language in _ZH_EN_LANGS

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> tuple[bool, str, list[str]]:
        if not self.available():
            return False, "", ["VideoCaptioner 未安装: pip install videocaptioner"]

        cfg = get_config().get("asr", {}).get("videocaptioner", {}) or {}
        timeout = cfg.get("timeout", 600)

        loop = asyncio.get_event_loop()

        def _run() -> tuple[bool, str, list[str]]:
            try:
                import importlib
                import os

                # 清除代理环境变量
                for k in (
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "http_proxy",
                    "https_proxy",
                    "ALL_PROXY",
                    "all_proxy",
                ):
                    os.environ.pop(k, None)
                os.environ["NO_PROXY"] = "*"

                # T075: 预初始化 diskcache 避免首次创建竞态
                from clipper.vc_cache_init import ensure_videocaptioner_cache

                ensure_videocaptioner_cache()

                module = importlib.import_module("videocaptioner.core.asr.bcut")
                asr_class = module.BcutASR

                with open(audio_path, "rb") as f:
                    audio_bytes = f.read()

                asr = asr_class(audio_bytes)
                result = asr.run()
                text = result.to_txt()
                _log.info("asr_success", engine="bijian")
                return True, text, []
            except Exception as e:
                import traceback

                full_err = traceback.format_exc()
                _log.warning("asr_failed", engine="bijian", error=full_err[:500])
                return False, "", [f"bijian 转写失败: {e}", f"完整错误链:\n{full_err}"]

        try:
            ok, text, w = await asyncio.wait_for(
                loop.run_in_executor(None, _run),
                timeout=timeout,
            )
            return ok, text, w
        except TimeoutError:
            _log.warning("asr_timeout", engine="bijian", timeout=timeout)
            return False, "", [f"bijian 转写超时({timeout}s)"]
