#!/usr/bin/env python3

import os
import sys
import time
import glob
import argparse
import logging
import subprocess
import json
from pathlib import Path
import re
import concurrent.futures
import threading

# --------------------------------------------------
# ログディレクトリの準備
# --------------------------------------------------
_LOG_DIR = Path.home() / '.google_photos_uploader'
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------
# ロギングの設定
# 先に logging.basicConfig() を実行しておかないと、後から import する
# slideshow.py などが logging.basicConfig() を呼び出した際に FileHandler
# が登録されず、uploader.log が生成されない問題が発生する。
# `force=True` で既存設定を上書きし、確実に FileHandler を追加する。
# --------------------------------------------------
logging.basicConfig(
    level=logging.INFO,  # デフォルトは INFO。--verbose 指定時に DEBUG に変更
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / 'uploader.log', encoding='utf-8')
    ],
    force=True  # 既存設定を上書き
)
logger = logging.getLogger(__name__)

# 遅延インポート — ログ設定後に行うことで FileHandler が有効になる
from google_photos_uploader.uploader import upload_photos as core_upload_photos  # noqa: E402
from google_photos_uploader.uploader import _collect_media_files  # noqa: E402
from slideshow import load_uploaded_files  # noqa: E402

# 設定値
DCIM_PATH = "DCIM"  # DCIMフォルダのパス
SUPPORTED_EXTENSIONS = [
    '.jpg', '.jpeg', '.png', '.gif', '.bmp',  # 画像ファイル
    '.mp4', '.mov', '.avi', '.wmv', '.mkv'    # 動画ファイル
]
MAX_RETRIES = 3  # 失敗した場合の最大再試行回数
RETRY_DELAY = 5  # 再試行までの待機時間（秒）
DEFAULT_ALBUM = "Photo Uploader"  # デフォルトのアルバム名
MAX_WORKERS = 5  # 並列アップロードの最大ワーカー数
MAX_BATCH_SIZE = 50  # 一度に作成できるメディアアイテムの最大数

def _is_valid_sd_root(path: Path) -> bool:
    """SDカードのルート候補にDCIMフォルダが存在するかどうかを判定"""
    if not path or not path.exists():
        logger.debug(f"パスが存在しません: {path}")
        return False
        
    try:
        # 直接DCIMフォルダが存在するか確認
        dcim_path = path / DCIM_PATH
        dcim_exists = dcim_path.exists()
        if dcim_exists:
            logger.debug(f"DCIMフォルダを発見: {dcim_path}")
            return True
            
        # 1階層下にDCIMがある場合（例: /run/media/pi/volname/Some/Sub/DCIM）
        for sub in path.iterdir():
            if not sub.is_dir():
                continue
                
            sub_dcim = sub / DCIM_PATH
            try:
                if sub_dcim.exists():
                    logger.debug(f"サブディレクトリ内にDCIMフォルダを発見: {sub_dcim}")
                    return True
            except PermissionError as e:
                logger.warning(f"サブディレクトリへのアクセス権限がありません: {sub_dcim}, エラー: {e}")
            except Exception as e:
                logger.warning(f"サブディレクトリ確認中のエラー: {sub_dcim}, {type(e).__name__}: {e}")
    except PermissionError as e:
        logger.warning(f"パスへのアクセス権限がありません: {path}, エラー: {e}")
    except Exception as e:
        logger.warning(f"パス確認中の予期せぬエラー: {path}, {type(e).__name__}: {e}")
        
    return False

def find_sd_card():
    """SDカードのパスを探す"""
    # macOSの場合は/Volumes以下を探す
    if sys.platform == 'darwin':
        volumes_dir = Path('/Volumes')
        if volumes_dir.exists():
            try:
                for volume in volumes_dir.iterdir():
                    if _is_valid_sd_root(volume):
                        return volume
            except PermissionError:
                logger.warning("ボリュームディレクトリの読み取り権限がありません")
    # Linuxの場合は複数のマウントポイントを探す
    elif sys.platform.startswith('linux'):
        user = os.environ.get('USER', 'user')
        # 一般的なマウントパスをチェック
        mount_paths = [
            Path(f'/media/{user}/disk'),  # Raspberry Pi Desktop などの自動マウント
            Path('/media/disk'),        # 後方互換: /media/disk
            Path(f'/media/{user}'),  # ユーザー固有のマウントポイント
            Path('/media'),          # システム全体のマウントポイント
            Path('/mnt'),            # 別の一般的なマウントポイント
            Path('/run/media'),       # 一部のディストリビューションで使用
        ]
        
        for mount_path in mount_paths:
            if mount_path.exists():
                # 1階層目と2階層目を探索
                search_dirs = [mount_path]
                try:
                    search_dirs.extend([p for p in mount_path.iterdir() if p.is_dir()])
                except PermissionError:
                    logger.warning(f"マウントポイントの読み取り権限がありません: {mount_path}")
                    continue  # 権限のないディレクトリは無視

                for search_dir in search_dirs:
                    # DCIMフォルダを含む任意のディレクトリを探す
                    try:
                        # まず直接チェック
                        if _is_valid_sd_root(search_dir):
                            return search_dir
                            
                        # サブディレクトリをチェック
                        for sub in search_dir.iterdir():
                            if sub.is_dir() and _is_valid_sd_root(sub):
                                return sub
                    except PermissionError:
                        logger.warning(f"ディレクトリの読み取り権限がありません: {search_dir}")
                        continue
    # Windowsの場合はドライブレターを探す
    elif sys.platform == 'win32':
        import win32api
        for drive in win32api.GetLogicalDriveStrings().split('\000')[:-1]:
            try:
                drive_path = Path(drive)
                if _is_valid_sd_root(drive_path):
                    return drive_path
            except:
                continue
    return None

def upload_single_file(file_path, album_name=None, verbose=False):
    """
    単一ファイルをアップロードしてアップロードトークンを取得
    
    Args:
        file_path (str): アップロードするファイルのパス
        album_name (str): アップロード先のアルバム名（オプション）
        verbose (bool): 詳細なログを出力するかどうか
        
    Returns:
        str or None: 成功した場合はアップロードトークン、失敗した場合はNone
    """
    uploader_script = Path(__file__).parent / "google_photos_uploader.py"
    
    # アップロードコマンドを構築（トークン取得モード）
    command = [sys.executable, str(uploader_script), "--token-only"]
    if verbose:
        command.append("--verbose")
    
    # ファイルパスを追加
    command.append(file_path)
    
    try:
        logger.info(f"アップロード開始: {file_path}")
        if verbose:
            logger.debug(f"実行コマンド: {' '.join(command)}")
        
        # 標準出力と標準エラー出力の両方をキャプチャ
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        
        # 出力からトークンを取得
        token = result.stdout.strip()
        if token:
            logger.info(f"ファイルアップロード成功: {file_path}")
            return token
        else:
            logger.error(f"トークンの取得に失敗: {file_path}")
            return None
    except subprocess.CalledProcessError as e:
        logger.error(f"ファイルアップロード中にエラーが発生: {file_path}")
        logger.error(f"終了コード: {e.returncode}")
        logger.error(f"標準出力: {e.stdout}")
        logger.error(f"標準エラー出力: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"予期せぬエラーが発生: {str(e)}")
        return None

def batch_create_media_items(upload_tokens, album_name=None, verbose=False):
    """
    複数のアップロードトークンを使用してメディアアイテムをバッチ作成
    
    Args:
        upload_tokens (list): アップロードトークンのリスト
        album_name (str): アップロード先のアルバム名（オプション）
        verbose (bool): 詳細なログを出力するかどうか
        
    Returns:
        bool: 成功した場合はTrue
    """
    uploader_script = Path(__file__).parent / "google_photos_uploader.py"
    
    # バッチ作成コマンドを構築
    command = [sys.executable, str(uploader_script), "--batch-create"]
    if album_name:
        command.extend(["--album", album_name])
    if verbose:
        command.append("--verbose")
    
    # トークンをJSON形式でファイルに保存
    tokens_file = Path.home() / '.google_photos_uploader' / 'temp_tokens.json'
    try:
        with open(tokens_file, 'w', encoding='utf-8') as f:
            json.dump(upload_tokens, f)
        
        # トークンファイルを指定
        command.extend(["--tokens-file", str(tokens_file)])
        
        logger.info(f"メディアアイテムのバッチ作成開始: {len(upload_tokens)}個")
        if verbose:
            logger.debug(f"実行コマンド: {' '.join(command)}")
        
        # 実行
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        
        # 成功したトークンを解析
        try:
            success_data = json.loads(result.stdout)
            logger.info(f"バッチ作成成功: {len(success_data.get('success', []))}個, 失敗: {len(success_data.get('failed', []))}個")
            return success_data
        except json.JSONDecodeError:
            logger.warning("バッチ作成結果の解析に失敗しました")
            return {"success": [], "failed": upload_tokens}
    
    except subprocess.CalledProcessError as e:
        logger.error(f"バッチ作成中にエラーが発生")
        logger.error(f"終了コード: {e.returncode}")
        logger.error(f"標準出力: {e.stdout}")
        logger.error(f"標準エラー出力: {e.stderr}")
        return {"success": [], "failed": upload_tokens}
    except Exception as e:
        logger.error(f"予期せぬエラーが発生: {str(e)}")
        return {"success": [], "failed": upload_tokens}
    finally:
        # 一時ファイルを削除
        if tokens_file.exists():
            tokens_file.unlink()

def upload_photos(dcim_path, album_name=None, show_slideshow=False, fullscreen=True, recent=True, current_only=False,
                 interval=5, random_order=False, no_pending=False, verbose=False, bgm_files=None, all_photos=False,
                 random_bgm=False):
    """
    SDカードから写真をアップロードする

    Args:
        dcim_path (str): DCIMディレクトリのパス
        album_name (str, optional): アップロード先のアルバム名
        show_slideshow (bool, optional): スライドショーを表示するかどうか
        fullscreen (bool, optional): フルスクリーンモードで表示するかどうか
        recent (bool, optional): 最近アップロードした写真のみ表示するかどうか
        current_only (bool, optional): 現在アップロード中の写真のみ表示するかどうか
        interval (int, optional): 画像の表示間隔（秒）
        random_order (bool, optional): ランダム順で表示するかどうか
        no_pending (bool, optional): アップロード予定/失敗ファイルを含めないかどうか
        verbose (bool, optional): 詳細なログを出力するかどうか
        bgm_files (list, optional): BGMとして再生する音楽ファイルまたはディレクトリのリスト
        all_photos (bool, optional): すべての写真をスライドショーに表示するかどうか
        random_bgm (bool, optional): BGMをランダムに再生するかどうか
    """
    from google_photos_uploader.uploader import _collect_media_files, _load_logs
    
    # 1. アップロードする写真を特定
    photo_files = _collect_media_files(Path(dcim_path))
    if verbose:
        logger.debug(f"{len(photo_files)} 件のメディアファイルを検出: {photo_files[:10]}")  # 先頭10件のみ表示
    if not photo_files:
        logger.info(f"DCIM に対象ファイルがありません: {dcim_path}")
        
        # 写真がない場合でも、SDカードの写真をスライドショーで表示
        logger.info("アップロードする写真はありませんが、SDカードの写真をスライドショーで表示します")
        # photo_files から最大100枚をピックアップ
        limited_files = photo_files[:min(len(photo_files), 100)]
        logger.info(f"スライドショー用に {len(limited_files)}/{len(photo_files)} 枚を使用します")
        
        # 進捗ファイルを作成
        progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with open(progress_path, 'w', encoding='utf-8') as f:
            progress_data = {
                "files": limited_files,
                "total": len(limited_files),
                "success": 0,
                "failed": 0,
                "completed": False,
                "album_name": album_name or "SDカード",
                "message": "アップロードする写真はありません。SDカードの最近の写真を再生します。"
            }
            json.dump(progress_data, f)
        
        # 限定ファイルのみを表示
        show_uploaded_slideshow(
            fullscreen=fullscreen,
            recent=True,
            current_only=True,
            interval=interval,
            random_order=random_order,
            no_pending=no_pending,
            verbose=verbose,
            bgm_files=bgm_files,
            random_bgm=random_bgm
        )
        return False
    
    # アップロード済み/失敗ログを読み込み
    uploaded_files, failed_files, _, _ = _load_logs()
    
    # 新規ファイルとリトライ対象を選定
    new_files = []
    retry_files = []
    for f in photo_files:
        if f in uploaded_files:
            continue
        if f in failed_files and failed_files[f].get("retry_count", 0) < MAX_RETRIES:
            retry_files.append(f)
        elif f not in failed_files:
            new_files.append(f)
    
    all_upload_files = new_files + retry_files
    
    if not all_upload_files:
        logger.info("アップロード対象ファイルはありません")
        
        # 写真がない場合でも、SDカードの写真をスライドショーで表示
        logger.info("アップロードする写真はありませんが、SDカードの写真をスライドショーで表示します")
        # photo_files から最大100枚をピックアップ
        limited_files = photo_files[:min(len(photo_files), 100)]
        logger.info(f"スライドショー用に {len(limited_files)}/{len(photo_files)} 枚を使用します")
        
        # 進捗ファイルを作成
        progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with open(progress_path, 'w', encoding='utf-8') as f:
            progress_data = {
                "files": limited_files,
                "total": len(limited_files),
                "success": 0,
                "failed": 0,
                "completed": False,
                "album_name": album_name or "SDカード",
                "message": "アップロードする写真はありません。SDカードの最近の写真を再生します。"
            }
            json.dump(progress_data, f)
        
        # 限定ファイルのみを表示
        show_uploaded_slideshow(
            fullscreen=fullscreen,
            recent=True,
            current_only=True,
            interval=interval,
            random_order=random_order,
            no_pending=no_pending,
            verbose=verbose,
            bgm_files=bgm_files,
            random_bgm=random_bgm
        )
        return False
    
    # 2. スライドショーを表示（アップロード対象の写真を表示）
    if show_slideshow:
        # 一時的な進捗ファイルを作成してアップロード対象ファイルをスライドショーに表示
        progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(progress_path, 'w', encoding='utf-8') as f:
            progress_data = {
                "files": all_upload_files,
                "total": len(all_upload_files),
                "success": 0,
                "failed": 0,
                "completed": False,
                "album_name": album_name or DEFAULT_ALBUM
            }
            json.dump(progress_data, f)
        
        # スライドショーを開始（現在アップロード対象のファイルを表示）
        show_uploaded_slideshow(
            fullscreen=fullscreen,
            recent=recent,
            current_only=True,  # 現在アップロードする写真のみを表示
            interval=interval,
            random_order=random_order,
            no_pending=no_pending,
            verbose=verbose,
            bgm_files=bgm_files,
            random_bgm=random_bgm
        )
    
    # 3. 写真のアップロード処理
    success = core_upload_photos(Path(dcim_path), album_name=album_name, verbose=verbose)
    return success

def show_uploaded_slideshow(fullscreen=True, recent=True, current_only=False, interval=5, random_order=False, 
                           no_pending=False, verbose=False, bgm_files=None, random_bgm=False):
    """
    アップロードした写真のスライドショーを表示
    
    Args:
        fullscreen (bool): フルスクリーンモードで表示するかどうか
        recent (bool): 最近アップロードした写真のみ表示するかどうか
        current_only (bool): 最新の写真のみ表示するかどうか
        interval (int): 画像の表示間隔（秒）
        random_order (bool): ランダム順で表示するかどうか
        no_pending (bool): アップロード予定/失敗ファイルを含めないかどうか
        verbose (bool): 詳細なログを出力するかどうか
        bgm_files (list): BGMとして再生する音楽ファイルまたはディレクトリのリスト
        random_bgm (bool): BGMをランダムに再生するかどうか
    """
    slideshow_script = Path(__file__).parent / "slideshow.py"
    
    # スライドショーのコマンドを構築
    command = [sys.executable, str(slideshow_script)]
    
    # オプションを追加
    if fullscreen:
        command.append("--fullscreen")
    if current_only:
        command.append("--current")
    
    # 追加オプション
    if interval != 5:  # デフォルト値と異なる場合のみ追加
        command.extend(["--interval", str(interval)])
    if random_order:
        command.append("--random")
    if no_pending:
        command.append("--no-pending")
    if verbose:
        command.append("--verbose")
    if random_bgm:
        command.append("--random-bgm")
    
    # BGM オプションが有効な場合
    if bgm_files is not None:
        command.append("--bgm")
        # 明示的にファイルやディレクトリが指定されていれば追加
        if len(bgm_files) > 0:
            command.extend(bgm_files)
    
    try:
        logger.info(f"スライドショーを開始します: {' '.join(command)}")
        # 環境変数の設定
        env = os.environ.copy()
        if 'DISPLAY' not in env:
            env['DISPLAY'] = ':0'
        logger.info(f"DISPLAY環境変数: {env.get('DISPLAY')}")
        
        # バックグラウンドで実行
        if sys.platform == 'win32':
            subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE, env=env)
        else:
            subprocess.Popen(command, start_new_session=True, env=env)
            
        logger.info("スライドショーをバックグラウンドで起動しました")
    except Exception as e:
        logger.error(f"スライドショーの起動中にエラーが発生しました: {e}")

def main():
    """
    メイン関数
    """
    parser = argparse.ArgumentParser(description='SDカードから自動的に写真をアップロードする')
    parser.add_argument('--album', type=str, default=DEFAULT_ALBUM, help='アップロード先のアルバム名')
    parser.add_argument('--slideshow', action='store_true', help='アップロードと同時にスライドショーを表示する')
    parser.add_argument('--no-fullscreen', action='store_true', help='スライドショーをフルスクリーンで表示しない')
    parser.add_argument('--fullscreen', action='store_true', help='スライドショーをフルスクリーンで表示する')
    parser.add_argument('--all-photos', action='store_true', help='すべての写真をスライドショーに表示する（デフォルトは最新のみ）')
    parser.add_argument('--current-only', action='store_true', help='最新の写真のみ表示する')
    # スライドショー用の追加オプション
    parser.add_argument('--slideshow-interval', type=int, default=5, help='スライドショーの画像表示間隔（秒）')
    parser.add_argument('--random', action='store_true', help='スライドショーをランダム順で表示する')
    parser.add_argument('--no-pending', action='store_true', help='アップロード予定/失敗ファイルを含めない')
    parser.add_argument('--verbose', action='store_true', help='詳細なログを出力する')
    parser.add_argument('--bgm', nargs='*', help='BGMとして再生する音楽ファイルまたはディレクトリ（複数指定可）')
    parser.add_argument('--random-bgm', action='store_true', help='BGMをランダムに再生する')
    args = parser.parse_args()
    
    # 詳細ログモードが指定された場合は DEBUG レベルに変更
    if args.verbose:
        # ルートロガーも含めて DEBUG に変更
        logging.getLogger().setLevel(logging.DEBUG)

    # フルスクリーン設定: --fullscreen が指定されていれば優先
    if args.fullscreen:
        fullscreen = True
    else:
        fullscreen = not args.no_fullscreen
    
    # recent モード: --all-photos が指定されていなければ recent=True
    recent = not args.all_photos
    
    # SDカードの確認
    sd_path = find_sd_card()
    if not sd_path or not (sd_path / DCIM_PATH).exists():
        logger.error("SDカードが見つかりません。SDカードを挿入してから再度実行してください。")
        return
        
    logger.info(f"SDカード検出: {sd_path}")
    # 写真特定 → スライドショー表示 → アップロード開始
    upload_photos(
        sd_path / DCIM_PATH, 
        args.album, 
        args.slideshow,
        fullscreen, 
        recent, 
        args.current_only,
        args.slideshow_interval, 
        args.random, 
        args.no_pending, 
        args.verbose, 
        args.bgm, 
        args.all_photos,
        args.random_bgm
    )
    
    logger.info("処理を完了しました。")

if __name__ == "__main__":
    main() 