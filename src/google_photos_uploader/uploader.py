import concurrent.futures
import glob
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import List, Dict

from .auth import get_credentials
from .service import (
    upload_media as gp_upload_media,
    batch_create_media_items as gp_batch_create,
)
from .utils import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

DEFAULT_ALBUM = "Photo Uploader"
MAX_RETRIES = 3
MAX_WORKERS = 5
MAX_BATCH_SIZE = 50

# --------------------------------------------------
# 内部ヘルパー
# --------------------------------------------------

_cached_creds = None
_creds_lock = threading.Lock()

def _get_credentials():
    global _cached_creds
    with _creds_lock:
        if _cached_creds is None or not _cached_creds.valid:
            logger.debug("認証情報を新規取得します")
            _cached_creds = get_credentials()
        return _cached_creds

def _clear_credentials_cache():
    global _cached_creds
    with _creds_lock:
        _cached_creds = None
        logger.debug("認証情報キャッシュをクリアしました")

# --------------------------------------------------
# 外部公開関数
# --------------------------------------------------

def upload_single_file(file_path: str, verbose: bool = False) -> str | None:
    """単一ファイルをアップロードし、アップロードトークンを返す

    Args:
        file_path: ファイルパス
        verbose: 追加ログを出力するか

    Returns:
        str | None: 成功時はアップロードトークン、失敗時はNone
    """
    try:
        creds = _get_credentials()
        if not creds:
            logger.error("認証情報の取得に失敗しました")
            return None

        if verbose:
            logger.debug(f"アップロード開始: {file_path}")
        token = gp_upload_media(file_path, creds, token_only=True)
        if token:
            logger.info(f"アップロード成功: {file_path}")
        else:
            logger.error(f"アップロード失敗: {file_path}")
            # アップロード失敗時に認証エラーの可能性があるため、キャッシュをクリア
            _clear_credentials_cache()
        return token
    except Exception as e:
        logger.error(f"upload_single_file で例外: {e}")
        # 例外発生時に認証エラーの可能性があるため、キャッシュをクリア
        _clear_credentials_cache()
        return None

def batch_create_media_items(tokens: List[str], album_name: str | None, verbose: bool = False) -> Dict[str, List[str]]:
    """アップロードトークンからメディアアイテムを一括生成"""
    try:
        creds = _get_credentials()
        if not creds:
            logger.error("認証情報の取得に失敗しました")
            return {"success": [], "failed": tokens}
        if verbose:
            logger.debug(
                f"batch_create_media_items 開始: token={len(tokens)}, album={album_name}"
            )
        result = gp_batch_create(tokens, album_name, creds)
        if not result.get("success"):
            # 全て失敗した場合は認証エラーの可能性があるため、キャッシュをクリア
            _clear_credentials_cache()
        return result
    except Exception as e:
        logger.error(f"batch_create_media_items で例外: {e}")
        # 例外発生時に認証エラーの可能性があるため、キャッシュをクリア
        _clear_credentials_cache()
        return {"success": [], "failed": tokens}

# 進捗ファイルのパス
_PROGRESS_PATH = Path.home() / ".google_photos_uploader" / "upload_progress.json"

_progress_lock = threading.Lock()

def upload_photos(
    dcim_path: Path,
    album_name: str | None = None,
    verbose: bool = False,
) -> bool:
    """指定ディレクトリ内の写真・動画をアップロード

    Args:
        dcim_path: DCIM フォルダの Path
        album_name: アップロード先アルバム名
        verbose: 詳細ログ出力

    Returns:
        bool: 1 枚でも成功したら True
    """
    # ---------------------------------------------
    # 1. ファイル検索
    # ---------------------------------------------
    photo_files = _collect_media_files(dcim_path)

    if not photo_files:
        logger.info(f"DCIM に対象ファイルがありません: {dcim_path}")
        return False

    total_files = len(photo_files)
    logger.info(f"アップロード対象 {total_files} 件を発見")

    # 進捗ファイルを初期化
    # _initialize_progress(total_files, album_name or DEFAULT_ALBUM, file_list=photo_files)

    # 2. アップロード済み/失敗ログの読み込み
    uploaded_files, failed_files, uploaded_log, failed_log = _load_logs()

    # 3. 新規ファイルとリトライ対象を選定
    new_files: List[str] = []
    retry_files: List[str] = []
    for f in photo_files:
        if f in uploaded_files:
            continue
        if f in failed_files and failed_files[f].get("retry_count", 0) < MAX_RETRIES:
            retry_files.append(f)
        elif f not in failed_files:
            new_files.append(f)

    all_files = new_files + retry_files
    if not all_files:
        logger.info("アップロード対象ファイルはありません")
        return False

    logger.info(f"新規 {len(new_files)} 件、リトライ {len(retry_files)} 件")

    # アップロード対象ファイルのみを進捗ファイルに設定
    _initialize_progress(len(all_files), album_name or DEFAULT_ALBUM, file_list=all_files)

    # 4. 並列アップロード（トークン取得）
    upload_results: List[dict] = []

    def _upload_task(file_path: str, idx: int):
        retry_cnt = failed_files.get(file_path, {}).get("retry_count", 0)
        token = upload_single_file(file_path, verbose=verbose)
        if token:
            return {
                "file": file_path,
                "token": token,
                "success": True,
                "idx": idx,
            }
        return {
            "file": file_path,
            "retry_count": retry_cnt + 1,
            "success": False,
            "last_error": "TOKEN_FAILED",
            "last_attempt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "idx": idx,
        }

    workers = min(MAX_WORKERS, os.cpu_count() or 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_upload_task, fp, i): fp for i, fp in enumerate(all_files, start=1)
        }
        for fut in concurrent.futures.as_completed(future_map):
            try:
                upload_results.append(fut.result())
            except Exception as exc:
                logger.error(f"upload task error: {exc}")

            # スレッド完了毎に進捗を更新
            _update_progress_partial(upload_results, completed=False)

    successful = [r for r in upload_results if r.get("success")]
    if not successful:
        logger.warning("トークン取得に成功したファイルがありませんでした")
        return False

    # 5. バッチ作成
    success_files: List[str] = []
    failed_files_dict: Dict[str, dict] = {}
    for i in range(0, len(successful), MAX_BATCH_SIZE):
        batch = successful[i : i + MAX_BATCH_SIZE]
        token_pairs = [(b["token"], Path(b["file"]).name) for b in batch]
        file_paths = [b["file"] for b in batch]
        result = batch_create_media_items(token_pairs, album_name or DEFAULT_ALBUM, verbose=verbose)
        for (tkn, _), fp in zip(token_pairs, file_paths):
            if tkn in result.get("success", []):
                success_files.append(fp)
            else:
                failed_files_dict[fp] = {
                    "retry_count": failed_files.get(fp, {}).get("retry_count", 0) + 1,
                    "last_error": "BATCH_FAILED",
                    "last_attempt": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

    # 6. ログ更新
    failed_files.update(failed_files_dict)
    # 成功分を失敗リストから除外
    for fp in success_files:
        failed_files.pop(fp, None)

    _write_logs(uploaded_log, failed_log, success_files, failed_files)

    # 完了後、進捗ファイルを最終更新
    total_failed = len([r for r in upload_results if not r.get("success")]) + len(failed_files_dict)
    _finalize_progress(len(success_files), total_failed, file_list=all_files)

    logger.info(f"upload_photos 完了: success={len(success_files)}, failed={len(failed_files_dict)}")
    return bool(success_files)

# --------------------------------------------------
# 新規ヘルパー関数
# --------------------------------------------------

def _collect_media_files(dcim_path: Path) -> List[str]:
    """指定フォルダ以下の対応拡張子ファイルを再帰取得"""
    files: List[str] = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(glob.glob(str(dcim_path / "**" / f"*{ext}"), recursive=True))
        files.extend(glob.glob(str(dcim_path / "**" / f"*{ext.upper()}"), recursive=True))
    return files

def _load_logs() -> tuple[set[str], dict[str, dict], Path, Path]:
    """アップロード済みログと失敗ログを読み込む"""
    base_dir = Path.home() / ".google_photos_uploader"
    uploaded_log = base_dir / "uploaded_files.txt"
    failed_log = base_dir / "failed_files.json"

    uploaded_files: set[str] = set()
    failed_files: dict[str, dict] = {}

    if uploaded_log.exists():
        uploaded_files = {line.strip() for line in uploaded_log.read_text().splitlines() if line.strip()}
    if failed_log.exists():
        try:
            failed_files = json.loads(failed_log.read_text())
        except json.JSONDecodeError:
            logger.warning("failed_files.json の解析に失敗。新しいファイルを生成します")

    return uploaded_files, failed_files, uploaded_log, failed_log

def _write_logs(uploaded_log: Path, failed_log: Path, new_uploaded: List[str], failed_files: dict):
    """ログファイルへ書き込み"""
    uploaded_log.parent.mkdir(parents=True, exist_ok=True)
    with uploaded_log.open("a", encoding="utf-8") as f:
        for fp in new_uploaded:
            f.write(f"{fp}\n")

    failed_log.write_text(json.dumps(failed_files, ensure_ascii=False, indent=2))

# --------------------------------------------------
# 進捗ファイル関連
# --------------------------------------------------

def _initialize_progress(total: int, album_name: str, file_list: List[str] | None = None):
    """進捗ファイルを初期化"""
    try:
        _PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "total": total,
            "success": 0,
            "failed": 0,
            "completed": False,
            "album_name": album_name,
            "files": file_list or []
        }
        with _PROGRESS_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"進捗ファイルの初期化に失敗: {e}")

def _update_progress_partial(results: List[dict], completed: bool):
    """アップロード途中で進捗を更新"""
    try:
        with _progress_lock:
            if not _PROGRESS_PATH.exists():
                return
            data = json.loads(_PROGRESS_PATH.read_text(encoding="utf-8"))

            success_cnt = len([r for r in results if r.get("success")])
            failed_cnt = len([r for r in results if not r.get("success")])

            data["success"] = success_cnt
            data["failed"] = failed_cnt
            data["completed"] = completed

            _PROGRESS_PATH.write_text(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"途中進捗の更新に失敗: {e}")

def _finalize_progress(success: int, failed: int, file_list: List[str] | None = None):
    """アップロード完了時に進捗を確定"""
    try:
        with _progress_lock:
            data = {
                "total": success + failed,
                "success": success,
                "failed": failed,
                "completed": True,
                "files": file_list or []
            }
            # album_name は既存ファイルに保持。file_list はそのまま維持
            if _PROGRESS_PATH.exists():
                try:
                    old = json.loads(_PROGRESS_PATH.read_text(encoding="utf-8"))
                    data["album_name"] = old.get("album_name", "")
                except Exception:
                    pass
            _PROGRESS_PATH.write_text(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"進捗ファイルの最終更新に失敗: {e}") 