"""ASR 分级回退模块 - VideoCaptioner(免费首选) + 火山引擎豆包2.0(付费兜底)

设计：
  - VideoCaptioner 通过 Python API 直接调用（绕过 FFmpeg，传原始 bytes）
  - 火山引擎用 httpx async 调 REST API（与 resolve_b23/_download_cover 一致）
  - 转写文本照存（transcript.txt），不做 LLM 总结（交 clawbot agent）
  - 每级失败仅记 warning，不阻断下一级
"""

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

import httpx
import yaml


def _load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_CONFIG = _load_config()
_ASR_CONFIG = _CONFIG.get("asr", {}) or {}

# bijian/jianying 仅支持中英文
_ZH_EN_LANGS = {"auto", "zh", "en", "zh-CN", "en-US", "zh-Hans", "zh-TW"}

_VOLC_BASE = "https://openspeech.bytedance.com/api/v1/auc"


# ═══════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════

async def transcribe_with_fallback(
    audio_path: Path,
    out_dir: Path,
    language: str = "auto",
) -> dict:
    """分级回退转写。

    Returns:
        dict: {success, text, engine, transcript_file, warnings, error}
        engine 取值: "bijian" | "jianying" | "volcengine" | None
    """
    result = {
        "success": False,
        "text": "",
        "engine": None,
        "transcript_file": None,
        "warnings": [],
        "error": None,
    }

    if not audio_path or not audio_path.exists():
        result["error"] = "音频文件不存在，无法 ASR"
        return result

    chain = _ASR_CONFIG.get("fallback_chain", [
        "videocaptioner:bijian",
        "videocaptioner:jianying",
        "volcengine",
    ])

    # 非中英语言跳过 bijian/jianying（两者仅支持中英文）
    if language not in _ZH_EN_LANGS:
        chain = [c for c in chain if not c.startswith("videocaptioner:")]
        if not chain:
            result["warnings"].append(
                f"语言 '{language}' 非中英文，bijian/jianying 不可用，且未配置其他引擎")
            result["error"] = "ASR 全部回退失败"
            return result

    for step in chain:
        engine = None
        ok, text, warns = False, "", []

        if step.startswith("videocaptioner:"):
            engine = step.split(":", 1)[1]
            vc_cfg = _ASR_CONFIG.get("videocaptioner", {}) or {}
            ok, text, warns = await transcribe_with_videocaptioner(
                audio_path, engine,
                vc_cfg.get("timeout", 600),
            )
        elif step == "volcengine":
            engine = "volcengine"
            ok, text, warns = await transcribe_with_volcengine(
                audio_path, _ASR_CONFIG.get("volcengine", {}) or {},
            )

        result["warnings"] += warns
        if ok and text.strip():
            result.update(success=True, text=text, engine=engine)
            # 照存 transcript.txt
            if _ASR_CONFIG.get("keep_transcript", True):
                tf = out_dir / "transcript.txt"
                tf.parent.mkdir(parents=True, exist_ok=True)
                tf.write_text(text, encoding="utf-8")
                result["transcript_file"] = str(tf)
            break

    if not result["success"]:
        result["error"] = "ASR 全部回退失败"
    return result


# ═══════════════════════════════════════════════════════════
# VideoCaptioner 转写（Python API，绕过 FFmpeg）
# ═══════════════════════════════════════════════════════════

def videocaptioner_available() -> bool:
    """检测 VideoCaptioner Python 包是否可用"""
    try:
        import videocaptioner  # noqa: F401
        return True
    except ImportError:
        return False


def _clear_proxy_env():
    """清除代理环境变量（避免本地代理未运行时连接失败）"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


# ASR 引擎类映射
_ASR_ENGINES = {
    "bijian": ("videocaptioner.core.asr.bcut", "BcutASR"),
    "jianying": ("videocaptioner.core.asr.jianying", "JianYingASR"),
}


async def transcribe_with_videocaptioner(
    audio_path: Path,
    engine: str,
    timeout: int,
) -> tuple:
    """用 VideoCaptioner Python API 转写音频。

    直接传原始文件 bytes 给 ASR 引擎，绕过系统 FFmpeg（精简版无音频解码器）。
    清除代理环境变量避免本地代理未运行时连接被拒。

    Args:
        engine: 'bijian' | 'jianying'
    Returns:
        (ok, text, warnings)
    """
    warns = []
    if not videocaptioner_available():
        return False, "", ["VideoCaptioner 未安装: pip install videocaptioner"]

    module_path, class_name = _ASR_ENGINES.get(engine, (None, None))
    if not module_path:
        return False, "", [f"未知 ASR 引擎: {engine}"]

    loop = asyncio.get_event_loop()

    def _run():
        try:
            import importlib
            _clear_proxy_env()
            module = importlib.import_module(module_path)
            ASRClass = getattr(module, class_name)

            # 读取原始文件 bytes（绕过 FFmpeg）
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()

            asr = ASRClass(audio_bytes)
            result = asr.run()
            text = result.to_txt()
            return True, text, []
        except Exception as e:
            return False, "", [f"{engine} 转写失败: {str(e)[:200]}"]

    try:
        ok, text, w = await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=timeout,
        )
        return ok, text, warns + w
    except asyncio.TimeoutError:
        warns.append(f"{engine} 转写超时({timeout}s)")
        return False, "", warns


# ═══════════════════════════════════════════════════════════
# 火山引擎豆包 2.0 转写
# ═══════════════════════════════════════════════════════════

def _guess_audio_format(audio_path: Path) -> str:
    """根据文件扩展名猜火山引擎 audio.format 字段值"""
    ext = audio_path.suffix.lower()
    mapping = {".wav": "wav", ".mp3": "mp3", ".ogg": "ogg",
               ".m4a": "mp4", ".mp4": "mp4", ".m4r": "mp4"}
    return mapping.get(ext, "mp4")


async def transcribe_with_volcengine(
    audio_path: Path,
    vc_cfg: dict,
) -> tuple:
    """用火山引擎录音文件识别 API 转写。

    Returns:
        (ok, text, warnings)
    """
    warns = []
    appid = vc_cfg.get("appid", "")
    token = vc_cfg.get("token", "")
    cluster = vc_cfg.get("cluster", "")

    if not (appid and token and cluster):
        return False, "", ["火山引擎未配置 appid/token/cluster，付费兜底不可用"]

    # 1) 供给可下载 URL
    url_cfg = vc_cfg.get("audio_url", {}) or {}
    audio_url, url_warns = await provision_audio_url(audio_path, url_cfg)
    warns += url_warns
    if not audio_url:
        warns.append("火山引擎音频URL供给失败，跳过")
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
            "language": vc_cfg.get("language", "zh-CN"),
            "use_itn": "True",
            "use_punc": "True",
        },
    }

    poll_interval = vc_cfg.get("poll_interval", 5)
    poll_timeout = vc_cfg.get("poll_timeout", 600)

    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            # 2) 提交任务
            r = await client.post(
                f"{_VOLC_BASE}/submit", headers=headers, json=submit_body,
            )
            data = r.json().get("resp", {})
            code = int(data.get("code", 0))
            if code != 1000:
                warns.append(f"火山提交失败 code={code}: {data.get('message', '')}")
                return False, "", warns
            task_id = data["id"]

            # 3) 轮询结果
            query_body = {
                "appid": appid, "token": token,
                "cluster": cluster, "id": task_id,
            }
            elapsed = 0
            while elapsed < poll_timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                rq = await client.post(
                    f"{_VOLC_BASE}/query", headers=headers, json=query_body,
                )
                qd = rq.json().get("resp", {})
                qc = int(qd.get("code", 0))
                if qc == 1000:
                    text = (qd.get("text") or "").strip()
                    if text:
                        return True, text, warns
                    warns.append("火山返回成功但 text 为空")
                    return False, "", warns
                if qc < 2000:
                    warns.append(f"火山识别失败 code={qc}: {qd.get('message', '')}")
                    return False, "", warns
                # 2000/2001 处理中/排队，继续轮询

            warns.append(f"火山轮询超时({poll_timeout}s)")
            return False, "", warns
    except Exception as e:
        warns.append(f"火山引擎异常: {e}")
        return False, "", warns


# ═══════════════════════════════════════════════════════════
# 音频 URL 供给（可插拔）
# ═══════════════════════════════════════════════════════════

async def provision_audio_url(
    audio_path: Path, url_cfg: dict,
) -> tuple:
    """把本地音频文件供给为公网可下载 URL。

    Returns:
        (url, warnings)
    """
    method = url_cfg.get("method", "")
    if method == "local_http":
        return await _serve_local_http(audio_path, url_cfg.get("local_http", {}))
    if method == "tos":
        return await _upload_to_tos(audio_path, url_cfg.get("tos", {}))
    if method == "tunnel":
        return await _serve_via_tunnel(audio_path, url_cfg.get("tunnel", {}))
    return None, [f"未配置 audio_url.method，火山引擎不可用"]


async def _serve_local_http(
    audio_path: Path, cfg: dict,
) -> tuple:
    """方案A：本地 HTTP 服务托管音频文件"""
    warns = []
    public_base = cfg.get("public_base", "")
    port = cfg.get("port", 8765)
    if not public_base:
        return None, ["local_http 未配置 public_base（公网可达基址）"]

    import threading
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import functools

    serve_dir = audio_path.parent
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(serve_dir))
    httpd = HTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    url = f"{public_base.rstrip('/')}/{audio_path.name}"
    warns.append(f"本地HTTP服务已启动(端口{port})，URL: {url}")
    return url, warns


async def _serve_via_tunnel(
    audio_path: Path, cfg: dict,
) -> tuple:
    """方案B：cloudflared 隧道暴露临时公网域名"""
    warns = []
    binary = cfg.get("binary", "cloudflared")
    serve_dir = audio_path.parent

    import threading
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import functools
    import re as re_mod

    port = 8765
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(serve_dir))
    httpd = HTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    loop = asyncio.get_event_loop()

    def _start_tunnel():
        try:
            proc = subprocess.Popen(
                [binary, "tunnel", "--url", f"http://localhost:{port}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            import time
            deadline = time.time() + 15
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                m = re_mod.search(r"https://[\w-]+\.trycloudflare\.com", line)
                if m:
                    return m.group(0), proc
            return None, proc
        except Exception:
            return None, None

    tunnel_url, proc = await loop.run_in_executor(None, _start_tunnel)
    if not tunnel_url:
        warns.append("cloudflared 隧道启动失败，未获取到公网域名")
        if proc:
            proc.kill()
        return None, warns

    url = f"{tunnel_url}/{audio_path.name}"
    warns.append(f"隧道已建立: {url}")
    return url, warns


async def _upload_to_tos(
    audio_path: Path, cfg: dict,
) -> tuple:
    """方案C：上传到火山引擎 TOS 对象存储，返回 presigned URL"""
    warns = []
    access_key = cfg.get("access_key", "")
    secret_key = cfg.get("secret_key", "")
    bucket = cfg.get("bucket", "")
    if not (access_key and secret_key and bucket):
        return None, ["TOS 未配置 access_key/secret_key/bucket"]

    try:
        import tos  # type: ignore
    except ImportError:
        return None, ["TOS SDK 未安装: pip install tos"]

    endpoint = cfg.get("endpoint", "tos-cn-beijing.volces.com")
    region = cfg.get("region", "cn-beijing")
    prefix = cfg.get("prefix", "glean-asr/")
    expire_seconds = cfg.get("expire_seconds", 3600)
    object_key = f"{prefix}{audio_path.name}"

    loop = asyncio.get_event_loop()

    def _upload():
        try:
            client = tos.TosClientV2(access_key, secret_key, endpoint, region)
            client.put_object_from_file(bucket, object_key, str(audio_path))
            url = client.pre_signed_url(
                "GET", bucket, object_key, expires=expire_seconds,
            )
            return url
        except Exception as e:
            return str(e)

    result = await loop.run_in_executor(None, _upload)
    if result and result.startswith("http"):
        return result, warns
    warns.append(f"TOS 上传失败: {result}")
    return None, warns
