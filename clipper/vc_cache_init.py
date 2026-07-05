"""videocaptioner diskcache 预初始化辅助(T075)。

diskcache 5.6.3 在空目录首次创建 cache.db 时,PRAGMA 语句在
Settings/Cache 表创建之前执行,导致 sqlite3 抛出
"unable to open database file" 错误。

此模块在导入 videocaptioner 前预创建合法的空 cache.db,
避免初始化竞态。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from clipper.logging import get_logger

_log = get_logger("clipper.diskcache_init")

# videocaptioner 在 cache.py 中创建这 5 个 Cache 实例
_VC_CACHE_SUBDIRS = [
    "llm_translation",
    "asr_results",
    "video_summary",
    "audio_download",
    "local_voice",
]

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS Settings (
    key TEXT NOT NULL UNIQUE,
    value
);
CREATE TABLE IF NOT EXISTS Cache (
    key TEXT NOT NULL,
    value BLOB,
    raw BLOB,
    store_time REAL,
    expire_time REAL,
    access_time REAL,
    access_count INTEGER DEFAULT 0,
    tag BLOB,
    size INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS Cache_key_idx ON Cache(key);
"""


def ensure_videocaptioner_cache() -> bool:
    """预初始化 videocaptioner 的 diskcache 数据库。

    检测 CACHE_PATH 下的各子目录,若 cache.db 不存在则用
    sqlite3 手动创建含 Settings 和 Cache 表的空数据库。

    Returns:
        True 表示全部成功(或已存在),False 表示部分失败。
    """
    try:
        from videocaptioner.config import CACHE_PATH
    except Exception:
        # videocaptioner 未安装,无法预初始化
        return True

    cache_root: Path = Path(CACHE_PATH)
    cache_root.mkdir(parents=True, exist_ok=True)
    all_ok = True

    for subdir in _VC_CACHE_SUBDIRS:
        sub_path = cache_root / subdir
        db_path = sub_path / "cache.db"

        if db_path.exists():
            continue  # 已有数据库,跳过

        try:
            sub_path.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(_INIT_SQL)
            conn.commit()
            conn.close()
        except Exception as e:
            _log.warning("diskcache_preinit_failed", subdir=subdir, error=str(e)[:200])
            all_ok = False

    if all_ok:
        _log.debug("diskcache_preinit_ok", root=str(cache_root))
    return all_ok
