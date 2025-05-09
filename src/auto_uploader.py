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
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import concurrent.futures
import threading
from google_photos_uploader.uploader import upload_photos as core_upload_photos
from google_photos_uploader.uploader import _collect_media_files
from slideshow import load_uploaded_files

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,  # デフォルトは INFO。--verbose 指定時に DEBUG に変更
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path.home() / '.google_photos_uploader' / 'uploader.log')
    ]
)
logger = logging.getLogger(__name__)

# 設定値
VOLUME_NAME = "PHOTO_UPLOAD_SD"  # SDカードのボリューム名
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

def find_sd_card():
    """
    'Untitled'という名前のSDカードをマウントポイントから探す
    """
    # macOSの場合は/Volumes以下を探す
    if sys.platform == 'darwin':
        sd_path = Path('/Volumes') / VOLUME_NAME
        if sd_path.exists():
            return sd_path
    # Linuxの場合は/media/$USER以下を探す
    elif sys.platform.startswith('linux'):
        user = os.environ.get('USER', 'user')
        sd_path = Path(f'/media/{user}') / VOLUME_NAME
        if sd_path.exists():
            return sd_path
        # Ubuntuの別のパターン
        sd_path = Path('/media') / VOLUME_NAME
        if sd_path.exists():
            return sd_path
    # Windowsの場合はドライブレターを探す
    elif sys.platform == 'win32':
        import win32api
        drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
        for drive in drives:
            try:
                volume_name = win32api.GetVolumeInformation(drive)[0]
                if volume_name == VOLUME_NAME:
                    return Path(drive)
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
    if not photo_files:
        logger.info(f"DCIM に対象ファイルがありません: {dcim_path}")
        
        # 写真がない場合でもスライドショーを表示するなら最近のファイルを表示
        if show_slideshow:
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
        
        # 写真がない場合でもスライドショーを表示するなら最近のファイルを表示
        if show_slideshow:
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
    elif recent:
        command.append("--recent")
    
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
    
    # BGMファイルがある場合
    if bgm_files:
        command.append("--bgm")
        command.extend(bgm_files)
    
    try:
        logger.info(f"スライドショーを開始します: {' '.join(command)}")
        # バックグラウンドで実行
        if sys.platform == 'win32':
            subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(command, start_new_session=True)
        logger.info("スライドショーをバックグラウンドで起動しました")
    except Exception as e:
        logger.error(f"スライドショーの起動中にエラーが発生しました: {e}")

class SDCardHandler(FileSystemEventHandler):
    """
    SDカードマウントを監視するハンドラー
    """
    def __init__(self, album_name=None, show_slideshow=False, current_only=False, interval=5, 
                random_order=False, no_pending=False, verbose=False, bgm_files=None):
        self.album_name = album_name
        self.show_slideshow = show_slideshow
        self.current_only = current_only
        self.last_processed = 0
        self.min_interval = 10  # 最低処理間隔（秒）- 短くして反応性を高める
        # マウント検知のためのフラグ
        self.pending_mount_check = False
        self.mount_check_delay = 2  # マウント完了を確認するための遅延（秒）
        # スライドショーの表示設定
        self.fullscreen = True
        self.recent = True
        self.interval = interval
        self.random_order = random_order
        self.no_pending = no_pending
        self.verbose = verbose
        self.bgm_files = bgm_files
    
    def on_created(self, event):
        """
        ファイル/ディレクトリ作成時のイベントハンドラ
        """
        logger.debug(f"作成イベント: {event.src_path}")
        self._process_event(event)
    
    def on_modified(self, event):
        """
        ファイル/ディレクトリ変更時のイベントハンドラ
        """
        logger.debug(f"変更イベント: {event.src_path}")
        self._process_event(event)
    
    def on_moved(self, event):
        """
        ファイル/ディレクトリ移動時のイベントハンドラ
        """
        logger.debug(f"移動イベント: {event.src_path} -> {event.dest_path}")
        self._process_event(event)
    
    def _process_event(self, event):
        """
        イベント処理の共通ロジック
        """
        # ボリュームマウントの可能性があるパターンを確認
        is_volume_event = False
        
        # /Volumes自体か、その直下のディレクトリの場合
        if sys.platform == 'darwin' and (
            event.src_path == '/Volumes' or 
            re.match(r'^/Volumes/[^/]+$', event.src_path)
        ):
            is_volume_event = True
            logger.debug(f"ボリュームイベント検出: {event.src_path}")
            
        # ディレクトリ変更のみを処理
        if not event.is_directory and not is_volume_event:
            return
            
        # ボリュームイベントを検出したら、少し遅延してからチェック（マウント完了を待つ）
        if is_volume_event and not self.pending_mount_check:
            logger.info(f"ボリュームイベント検出: {event.src_path} - マウント完了を待機中...")
            self.pending_mount_check = True
            
            # 遅延実行の設定
            threading.Timer(self.mount_check_delay, self._delayed_volume_check).start()
            return
            
        # 短時間の連続実行を防止
        current_time = time.time()
        if current_time - self.last_processed < self.min_interval:
            return
        
        # /Volumesディレクトリ自体の変更の場合は、すべてのサブディレクトリをチェック
        if event.src_path == '/Volumes' and sys.platform == 'darwin':
            logger.debug("ボリュームディレクトリの変更を検出しました")
            self._check_all_volumes()
            return
            
        # SDカードのDCIMフォルダを探す
        sd_path = None
        
        # 特定のボリュームに関するイベントの場合
        if VOLUME_NAME in event.src_path:
            volume_path = Path(event.src_path)
            # イベントパスがボリューム自体かその親ディレクトリの場合
            if volume_path.name == VOLUME_NAME:
                sd_path = volume_path
            elif '/Volumes/' + VOLUME_NAME in event.src_path:
                sd_path = Path('/Volumes') / VOLUME_NAME
                
            logger.debug(f"対象ボリュームのイベント: {sd_path}")
        
        # 特定のボリュームが見つからない場合は通常の検索
        if not sd_path:
            sd_path = find_sd_card()
            
        if sd_path and (sd_path / DCIM_PATH).exists():
            logger.info(f"SDカード検出: {sd_path}")
            # 順序に沿って処理：写真特定 → スライドショー表示 → アップロード開始
            success = upload_photos(
                sd_path / DCIM_PATH, 
                self.album_name, 
                self.show_slideshow,  # スライドショー表示を有効に
                self.fullscreen, 
                self.recent, 
                self.current_only,
                self.interval, 
                self.random_order, 
                self.no_pending, 
                self.verbose, 
                self.bgm_files
            )
            self.last_processed = current_time
    
    def _delayed_volume_check(self):
        """
        ボリュームマウント完了後の遅延チェック
        """
        logger.debug("遅延ボリュームチェックを実行")
        self.pending_mount_check = False
        
        # すべてのボリュームを確認
        self._check_all_volumes()
    
    def _check_all_volumes(self):
        """
        すべてのボリュームをチェックして対象のSDカードを探す
        """
        if sys.platform == 'darwin':
            volumes_dir = Path('/Volumes')
            try:
                for volume in volumes_dir.iterdir():
                    logger.debug(f"ボリュームをチェック: {volume}")
                    if volume.is_dir() and volume.name == VOLUME_NAME:
                        logger.info(f"対象のボリュームを発見: {volume}")
                        if (volume / DCIM_PATH).exists():
                            logger.info(f"SDカード検出: {volume}")
                            # 順序に沿って処理：写真特定 → スライドショー表示 → アップロード開始
                            success = upload_photos(
                                volume / DCIM_PATH, 
                                self.album_name, 
                                self.show_slideshow,  # スライドショー表示を有効に
                                self.fullscreen, 
                                self.recent, 
                                self.current_only,
                                self.interval, 
                                self.random_order, 
                                self.no_pending, 
                                self.verbose, 
                                self.bgm_files
                            )
                            self.last_processed = time.time()
                            break
                        else:
                            logger.info(f"ボリュームは見つかりましたが、DCIMフォルダがありません: {volume}")
            except Exception as e:
                logger.error(f"ボリュームチェック中のエラー: {e}")

def check_periodically(interval=10, album_name=None, show_slideshow=False, fullscreen=True, recent=True, 
                     current_only=False, slideshow_interval=5, random_order=False, no_pending=False, 
                     verbose=False, bgm_files=None, random_bgm=False):
    """
    一定間隔でSDカードの存在をチェックし、見つかった場合は写真をアップロード
    
    Args:
        interval (int): チェック間隔（秒）
        album_name (str): アップロード先のアルバム名（オプション）
        show_slideshow (bool): アップロード後にスライドショーを表示するかどうか
        fullscreen (bool): スライドショーをフルスクリーンで表示するかどうか
        recent (bool): 最新の写真のみ表示するかどうか
        current_only (bool): 最新の写真のみ表示するかどうか
        slideshow_interval (int): スライドショーの画像表示間隔（秒）
        random_order (bool): スライドショーをランダム順で表示するかどうか
        no_pending (bool): アップロード予定/失敗ファイルを含めないかどうか
        verbose (bool): 詳細なログを出力するかどうか
        bgm_files (list): BGMとして再生する音楽ファイルまたはディレクトリのリスト
        random_bgm (bool): BGMをランダムに再生するかどうか
    """
    while True:
        sd_path = find_sd_card()
        if sd_path and (sd_path / DCIM_PATH).exists():
            logger.info(f"SDカード検出: {sd_path}")
            # 順序に沿って処理：写真特定 → スライドショー表示 → アップロード開始
            success = upload_photos(
                sd_path / DCIM_PATH, 
                album_name, 
                show_slideshow,  # スライドショー表示を有効に
                fullscreen, 
                recent, 
                current_only,
                slideshow_interval, 
                random_order, 
                no_pending, 
                verbose,
                bgm_files,
                random_bgm=random_bgm
            )
        else:
            logger.info("SDカードが見つかりません")
        
        time.sleep(interval)

def main():
    """
    メイン関数
    """
    parser = argparse.ArgumentParser(description='SDカードから自動的に写真をアップロードする')
    parser.add_argument('--album', type=str, default=DEFAULT_ALBUM, help='アップロード先のアルバム名')
    parser.add_argument('--watch', action='store_true', help='SDカードの挿入を監視する')
    parser.add_argument('--interval', type=int, default=60, help='ポーリング間隔（秒）')
    parser.add_argument('--slideshow', action='store_true', help='アップロードと同時にスライドショーを表示する')
    parser.add_argument('--no-fullscreen', action='store_true', help='スライドショーをフルスクリーンで表示しない')
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

    # フルスクリーンモードとrecentモードの設定
    fullscreen = not args.no_fullscreen
    recent = not args.all_photos
    
    # まず、現在接続されているSDカードをチェック
    sd_path = find_sd_card()
    if sd_path and (sd_path / DCIM_PATH).exists():
        logger.info(f"SDカード検出: {sd_path}")
        # 順序に沿って処理：写真特定 → スライドショー表示 → アップロード開始
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
    
    # 監視モードが有効な場合
    if args.watch:
        logger.info("SDカードの挿入を監視しています...")
        
        # macOSの場合は/Volumesディレクトリを監視
        if sys.platform == 'darwin':
            path = '/Volumes'
        # Linuxの場合は/mediaディレクトリを監視
        elif sys.platform.startswith('linux'):
            user = os.environ.get('USER', 'user')
            path = f'/media/{user}'
            if not os.path.exists(path):
                path = '/media'
        # Windowsの場合はドライブ監視は難しいのでポーリングモードを使用
        else:
            logger.info("このプラットフォームでは監視モードがサポートされていません。ポーリングモードに切り替えます。")
            check_periodically(args.interval, args.album, args.slideshow, fullscreen, recent, args.current_only,
                             args.slideshow_interval, args.random, args.no_pending, args.verbose, args.bgm, args.random_bgm)
            return
        
        # 設定を適用したSDカードハンドラを作成
        event_handler = SDCardHandler(args.album, args.slideshow, args.current_only, 
                                    args.slideshow_interval, args.random, args.no_pending, 
                                    args.verbose, args.bgm)
        # スライドショーの表示設定
        event_handler.fullscreen = fullscreen
        event_handler.recent = recent
        
        observer = Observer()
        
        # ボリュームディレクトリを監視（再帰的にサブディレクトリも含める）
        observer.schedule(event_handler, path, recursive=True)
        
        # macOSの場合は、特定のボリューム名も直接監視
        if sys.platform == 'darwin':
            specific_volume = Path('/Volumes') / VOLUME_NAME
            if specific_volume.exists():
                logger.info(f"特定のボリュームを監視: {specific_volume}")
                observer.schedule(event_handler, str(specific_volume), recursive=False)
        
        observer.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        # ポーリングモード
        logger.info(f"{args.interval}秒間隔でSDカードをチェックしています...")
        check_periodically(args.interval, args.album, args.slideshow, fullscreen, recent, args.current_only,
                         args.slideshow_interval, args.random, args.no_pending, args.verbose, args.bgm, args.random_bgm)

if __name__ == "__main__":
    main() 