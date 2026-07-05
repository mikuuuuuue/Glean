"""ASR 后端抽象基类(T032)。

定义统一的 ASR 后端接口,支持分级回退(FR-005)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ASRBackend(ABC):
    """ASR 后端抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """后端名称(bijian/jianying/volcengine)。"""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> tuple[bool, str, list[str]]:
        """转写音频。

        Args:
            audio_path: 音频文件路径
            language: 语言代码(auto/zh/en 等)

        Returns:
            (success, text, warnings)
        """

    @abstractmethod
    def available(self) -> bool:
        """检查后端是否可用(配置/依赖就绪)。"""

    @abstractmethod
    def supports_language(self, language: str) -> bool:
        """检查后端是否支持指定语言。"""
