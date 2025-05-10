import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# --------------------------------------------------
# スライドショー起動用のヘルパー
# --------------------------------------------------

def launch_slideshow(
    fullscreen: bool = True,
    recent: bool = True,
    current_only: bool = False,
    interval: int = 5,
    random_order: bool = False,
    no_pending: bool = False,
    verbose: bool = False,
    bgm_files: List[str] | None = None,
):
    """slideshow.py を別プロセスで起動

    Args:
        fullscreen: フルスクリーン表示
        recent: 最近のみ表示
        current_only: 現在アップロード中のみ表示
        interval: 秒数
        random_order: ランダム順
        no_pending: 未アップロード/失敗ファイルを含めない
        verbose: 詳細ログ
        bgm_files: BGM ファイル/フォルダのリスト
    """
    slideshow_script = Path(__file__).resolve().parent.parent / "slideshow.py"
    command: List[str] = [sys.executable, str(slideshow_script)]

    if fullscreen:
        command.append("--fullscreen")
    if current_only:
        command.append("--current")
    elif recent:
        command.append("--recent")
    if interval != 5:
        command.extend(["--interval", str(interval)])
    if random_order:
        command.append("--random")
    if no_pending:
        command.append("--no-pending")
    if verbose:
        command.append("--verbose")
    if bgm_files is not None:
        command.append("--bgm")
        if len(bgm_files) > 0:
            command.extend(bgm_files)

    try:
        logger.info("スライドショーを起動: %s", " ".join(command))
        if sys.platform == "win32":
            subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(command, start_new_session=True)
    except Exception as e:
        logger.error("スライドショー起動に失敗: %s", e)
