"""
文件鎖工具 — 防止多進程並發讀寫 JSON 文件導致數據丟失。

用法:
    from file_lock import atomic_json_update, atomic_json_read

    # 原子讀取
    data = atomic_json_read(path, default=[])

    # 原子更新（讀 → 修改 → 寫回，全程持鎖）
    def modifier(tasks):
        tasks.append(new_task)
        return tasks 
    atomic_json_update(path, modifier, default=[])
"""
import json
import os
import pathlib
import tempfile
from typing import Any, Callable

_IS_WINDOWS = os.name == 'nt'

if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl


# ── 平臺抽象：文件鎖 ────────────────────────────────────────────

def _lock_shared(fd: int) -> None:
    """獲取共享鎖（讀鎖）。"""
    if _IS_WINDOWS:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_SH)


def _lock_exclusive(fd: int) -> None:
    """獲取排他鎖（寫鎖）。"""
    if _IS_WINDOWS:
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    """釋放鎖。"""
    if _IS_WINDOWS:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _lock_path(path: pathlib.Path) -> pathlib.Path:
    return path.parent / (path.name + '.lock')


def atomic_json_read(path: pathlib.Path, default: Any = None) -> Any:
    """持鎖讀取 JSON 文件。"""
    lock_file = _lock_path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
    try:
        _lock_shared(fd)
        try:
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
        except Exception:
            return default
    finally:
        _unlock(fd)
        os.close(fd)


def atomic_json_update(
    path: pathlib.Path,
    modifier: Callable[[Any], Any],
    default: Any = None,
) -> Any:
    """
    原子地讀取 → 修改 → 寫回 JSON 文件。
    modifier(data) 應返回修改後的數據。
    使用臨時文件 + rename 保證寫入原子性。
    """
    lock_file = _lock_path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
    try:
        _lock_exclusive(fd)
        # Read
        try:
            data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
        except Exception:
            data = default
        # Modify
        result = modifier(data)
        # Atomic write via temp file + rename
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix='.tmp', prefix=path.stem + '_'
        )
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            os.unlink(tmp_path)
            raise
        return result
    finally:
        _unlock(fd)
        os.close(fd)


def atomic_json_write(path: pathlib.Path, data: Any) -> None:
    """原子寫入 JSON 文件（持排他鎖 + tmpfile rename）。
    直接寫入，不讀取現有內容（避免 atomic_json_update 的多餘讀開銷）。
    """
    lock_file = _lock_path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
    try:
        _lock_exclusive(fd)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix='.tmp', prefix=path.stem + '_'
        )
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            os.unlink(tmp_path)
            raise
    finally:
        _unlock(fd)
        os.close(fd)
