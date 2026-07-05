"""火山引擎豆包 2.0 ASR 后端(T035)。

封装火山引擎录音文件识别 API 的两段式 submit→poll 调用。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from clipper.asr_backend import ASRBackend
from clipper.config import get_config
from clipper.logging import get_logger

_log = get_logger("clipper.asr_volcengine")

_VOLC_BASE = "https://openspeech.bytedance.com/api/v1/auc"


class VolcengineBackend(ASRBackend):
    """火山引擎豆包 2.0 ASR 后端,付费兜底。"""

    @property
    def name(self) -> str:
        return "volcengine"

    def available(self) -> bool:
        cfg = get_config().get("asr", {}).get("volcengine", {}) or {}
        return bool(cfg.get("appid") and cfg.get("token") and cfg.get("cluster"))

    def supports_language(self, language: str) -> bool:
        return True  # 火山引擎支持所有语言

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> tuple[bool, str, list[str]]:
        cfg = get_config().get("asr", {}).get("volcengine", {}) or {}
        warns: list[str] = []

        appid = cfg.get("appid", "")
        token = cfg.get("token", "")
        cluster = cfg.get("cluster", "")

        if not (appid and token and cluster):
            return False, "", ["火山引擎未配置 appid/token/cluster,付费兜底不可用"]

        # 供给可下载 URL
        from clipper.asr import provision_audio_url

        url_cfg = cfg.get("audio_url", {}) or {}
        audio_url, url_warns = await provision_audio_url(audio_path, url_cfg)
        warns += url_warns
        if not audio_url:
            warns.append("火山引擎音频URL供给失败,跳过")
            return False, "", warns

        headers = {
            "Authorization": f"Bearer; {token}",
            "Content-Type": "application/json",
        }
        fmt = _guess_audio_format(audio_path)
        submit_body = {
            "app": {"appid": appid, "token": token, "cluster": cluster},
            "user": {"uid": "glean-clip"},
            "audio": {"format": fmt, "url": audio_url},
            "additions": {
                "language": cfg.get("language", "zh-CN"),
                "use_itn": "True",
                "use_punc": "True",
            },
        }

        poll_interval = cfg.get("poll_interval", 5)
        poll_timeout = cfg.get("poll_timeout", 600)

        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                # 提交任务
                r = await client.post(
                    f"{_VOLC_BASE}/submit",
                    headers=headers,
                    json=submit_body,
                )
                data = r.json().get("resp", {})
                code = int(data.get("code", 0))
                if code != 1000:
                    warns.append(f"火山提交失败 code={code}: {data.get('message', '')}")
                    return False, "", warns
                task_id = data["id"]

                # 轮询结果
                query_body = {
                    "appid": appid,
                    "token": token,
                    "cluster": cluster,
                    "id": task_id,
                }
                elapsed = 0
                while elapsed < poll_timeout:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                    rq = await client.post(
                        f"{_VOLC_BASE}/query",
                        headers=headers,
                        json=query_body,
                    )
                    qd = rq.json().get("resp", {})
                    qc = int(qd.get("code", 0))
                    if qc == 1000:
                        text = (qd.get("text") or "").strip()
                        if text:
                            _log.info("asr_success", engine="volcengine")
                            return True, text, warns
                        warns.append("火山返回成功但 text 为空")
                        return False, "", warns
                    if qc < 2000:
                        warns.append(f"火山识别失败 code={qc}: {qd.get('message', '')}")
                        return False, "", warns
                    # 2000/2001 处理中/排队,继续轮询

            warns.append(f"火山轮询超时({poll_timeout}s)")
            return False, "", warns
        except Exception as e:
            _log.warning("asr_failed", engine="volcengine", error=str(e)[:200])
            warns.append(f"火山引擎异常: {e}")
            return False, "", warns


def _guess_audio_format(audio_path: Path) -> str:
    """根据文件扩展名猜火山引擎 audio.format 字段值。"""
    ext = audio_path.suffix.lower()
    mapping = {
        ".wav": "wav",
        ".mp3": "mp3",
        ".ogg": "ogg",
        ".m4a": "mp4",
        ".mp4": "mp4",
        ".m4r": "mp4",
    }
    return mapping.get(ext, "mp4")
