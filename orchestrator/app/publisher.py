"""social-auto-upload (sau) CLI 封装: 抖音/小红书/B站/视频号 等自动发布"""
import shutil
import subprocess
from pathlib import Path

from . import config as C


class PublishError(RuntimeError):
    pass


def sau_available() -> bool:
    return shutil.which("sau") is not None or Path(C.SAU_BIN).exists()


def _bin() -> str:
    return C.SAU_BIN if Path(C.SAU_BIN).exists() else "sau"


def _run(*args: str) -> subprocess.CompletedProcess:
    cmd = [_bin(), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise PublishError(f"{' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    return proc


def check_login(platform: str = "douyin", account: str | None = None) -> str:
    return _run(platform, "check", "--account", account or C.SAU_ACCOUNT).stdout


def upload_video(video: Path, title: str, desc: str = "",
                 tags: list[str] | None = None,
                 platform: str = "douyin", account: str | None = None,
                 schedule: str | None = None) -> str:
    """schedule: 'YYYY-MM-DD HH:MM' 为定时发布; None=立即发布"""
    args = [platform, "upload-video",
            "--account", account or C.SAU_ACCOUNT,
            "--file", str(video),
            "--title", title,
            "--desc", desc]
    if tags:
        args += ["--tags", ",".join(tags)]
    if schedule:
        args += ["--schedule", schedule]
    return _run(*args).stdout
