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

# ロギングの設定
logging.basicConfig(
    level=logging.DEBUG,  # INFOからDEBUGに変更してより詳細なログを出力
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path.home() / '.google_photos_uploader' / 'uploader.log')
    ]
)
logger = logging.getLogger(__name__)

# 設定値
VOLUME_NAME = "Untitled"  # SDカードのボリューム名
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
                 interval=5, random_order=False, no_pending=False, verbose=False, bgm_files=None, all_photos=False):
    """
    指定されたDCIMパス内の写真と動画をGoogle Photosにアップロード
    
    Args:
        dcim_path (Path): DCIMフォルダのパス
        album_name (str): アップロード先のアルバム名（オプション）
        show_slideshow (bool): アップロード後にスライドショーを表示するかどうか
        fullscreen (bool): スライドショーをフルスクリーンで表示するかどうか
        recent (bool): 最新の写真のみ表示するかどうか
        current_only (bool): 最新の写真のみアップロードするかどうか
        interval (int): 画像の表示間隔（秒）
        random_order (bool): ランダム順で表示するかどうか
        no_pending (bool): アップロード予定/失敗ファイルを含めないかどうか
        verbose (bool): 詳細なログを出力するかどうか
        bgm_files (list): BGMとして再生する音楽ファイルまたはディレクトリのリスト
        all_photos (bool): すべての写真をスライドショーに表示するかどうか
        
    Returns:
        bool: 成功した場合はTrue
    """
    # DCIMパス内のすべてのフォルダを探索
    photo_files = []
    for ext in SUPPORTED_EXTENSIONS:
        photo_files.extend(glob.glob(str(dcim_path / "**" / f"*{ext}"), recursive=True))
        photo_files.extend(glob.glob(str(dcim_path / "**" / f"*{ext.upper()}"), recursive=True))
    
    if not photo_files:
        logger.info(f"DCIMフォルダ {dcim_path} に写真が見つかりません")
        return False
    
    logger.info(f"{len(photo_files)}枚の写真が見つかりました")
    
    # アップロード済みファイルの記録を保持するファイル
    uploaded_log = Path.home() / '.google_photos_uploader' / 'uploaded_files.txt'
    uploaded_log.parent.mkdir(parents=True, exist_ok=True)
    
    # アップロード済みファイルのリストを読み込み
    uploaded_files = set()
    if uploaded_log.exists():
        with open(uploaded_log, 'r', encoding='utf-8') as f:
            uploaded_files = set(line.strip() for line in f.readlines())
    
    # 失敗したファイルの記録を保持するファイル
    failed_log = Path.home() / '.google_photos_uploader' / 'failed_files.json'
    failed_files = {}
    
    # 失敗ログがあれば読み込む
    if failed_log.exists():
        try:
            with open(failed_log, 'r', encoding='utf-8') as f:
                failed_files = json.load(f)
        except json.JSONDecodeError:
            logger.warning("失敗ログの解析に失敗しました。新しいログを作成します。")
            failed_files = {}
    
    # アップロードするファイルをフィルタリング
    new_files = []
    retry_files = []
    
    for f in photo_files:
        if f in uploaded_files:
            continue
        
        # 失敗記録があり、最大試行回数に達していない場合は再試行リストに追加
        if f in failed_files:
            retry_count = failed_files[f].get('retry_count', 0)
            if retry_count < MAX_RETRIES:
                retry_files.append(f)
                logger.info(f"再試行予定のファイル (試行回数: {retry_count+1}/{MAX_RETRIES}): {f}")
            else:
                logger.warning(f"最大試行回数に達したためスキップ: {f}")
        else:
            new_files.append(f)
    
    # 新規ファイルと再試行ファイルをまとめる
    all_files = new_files + retry_files
    
    if not all_files:
        logger.info("新しい写真はありません")
        return False
    
    logger.info(f"{len(new_files)}枚の新しい写真と{len(retry_files)}枚の再試行写真、合計{len(all_files)}枚をアップロードします")
    
    # アップロード進捗を記録するファイルを準備
    progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
    progress_lock = threading.Lock()  # 進捗データ更新用のロック
    progress_data = {
        'total': len(all_files),
        'success': 0,
        'failed': 0,
        'current': 0,
        'completed': False,
        'files': all_files,  # スライドショーでアップロード対象のみ表示するため
        'album_name': album_name or DEFAULT_ALBUM  # アルバム名を追加
    }
    try:
        with open(progress_path, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"進捗ファイルの作成に失敗しました: {e}")
    
    # アップロード開始前にスライドショーを表示（アップロードと同時に表示）
    if show_slideshow:
        logger.info("アップロードと同時にスライドショーを開始します")
        show_uploaded_slideshow(fullscreen=fullscreen, recent=not all_photos, current_only=current_only,
                              interval=interval, random_order=random_order, no_pending=no_pending,
                              verbose=verbose, bgm_files=bgm_files)
    
    # ステップ1: 並列ファイルアップロード
    # アップロード結果を保存するディクショナリ
    upload_results = []
    success_files = []
    failed_files_dict = {}
    
    # 進捗更新関数
    def update_progress(success_count, failed_count, current_count):
        with progress_lock:
            progress_data['success'] = success_count
            progress_data['failed'] = failed_count
            progress_data['current'] = current_count
            try:
                with open(progress_path, 'w', encoding='utf-8') as f:
                    json.dump(progress_data, f, ensure_ascii=False)
            except Exception as e:
                logger.debug(f"進捗ファイルの更新に失敗しました: {e}")
    
    # 並列アップロード関数
    def parallel_upload_task(file_path, idx):
        retry_count = failed_files.get(file_path, {}).get('retry_count', 0) if file_path in failed_files else 0
        
        try:
            # ファイルバイトをアップロードしてトークンを取得
            token = upload_single_file(file_path, album_name, verbose)
            
            if token:
                return {
                    'file': file_path,
                    'token': token,
                    'success': True,
                    'idx': idx
                }
            else:
                # 失敗情報を記録
                failed_info = {
                    'file': file_path,
                    'retry_count': retry_count + 1,
                    'success': False,
                    'last_error': 'トークン取得に失敗',
                    'last_attempt': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'idx': idx
                }
                return failed_info
        except Exception as e:
            # 例外が発生した場合の失敗情報
            failed_info = {
                'file': file_path,
                'retry_count': retry_count + 1,
                'success': False,
                'last_error': str(e),
                'last_attempt': time.strftime('%Y-%m-%d %H:%M:%S'),
                'idx': idx
            }
            return failed_info
    
    # 効率的なワーカー数を決定（CPUコア数と設定値の小さい方）
    workers = min(MAX_WORKERS, os.cpu_count() or 4)
    logger.info(f"並列アップロードを開始します（ワーカー数: {workers}）")
    
    # ファイルアップロードを並列実行
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        # すべてのファイルについてアップロードタスクを送信
        future_to_file = {executor.submit(parallel_upload_task, file, idx): (file, idx) 
                         for idx, file in enumerate(all_files, start=1)}
        
        # 完了したタスクを処理
        for future in concurrent.futures.as_completed(future_to_file):
            file, idx = future_to_file[future]
            try:
                result = future.result()
                upload_results.append(result)
                
                # 進捗を更新
                success_count = len([r for r in upload_results if r.get('success', False)])
                failed_count = len(upload_results) - success_count
                update_progress(success_count, failed_count, len(upload_results))
                
                if result.get('success', False):
                    logger.info(f"ファイルアップロード成功 ({len(upload_results)}/{len(all_files)}): {file}")
                else:
                    logger.warning(f"ファイルアップロード失敗 ({len(upload_results)}/{len(all_files)}): {file}")
                    failed_files_dict[file] = {
                        'retry_count': result.get('retry_count', 1),
                        'last_error': result.get('last_error', '不明なエラー'),
                        'last_attempt': result.get('last_attempt', time.strftime('%Y-%m-%d %H:%M:%S'))
                    }
            except Exception as e:
                logger.error(f"タスク処理中にエラーが発生: {e}")
                upload_results.append({
                    'file': file,
                    'success': False,
                    'last_error': str(e),
                    'idx': idx
                })
    
    # 成功したファイルとトークンを抽出
    successful_uploads = [r for r in upload_results if r.get('success', False)]
    
    # ステップ2: バッチでメディアアイテムを作成
    if successful_uploads:
        logger.info(f"{len(successful_uploads)}個のファイルが正常にアップロードされました。メディアアイテム作成を開始します。")
        
        # バッチサイズごとに処理
        for i in range(0, len(successful_uploads), MAX_BATCH_SIZE):
            batch = successful_uploads[i:i + MAX_BATCH_SIZE]
            tokens = [item['token'] for item in batch]
            files = [item['file'] for item in batch]
            
            logger.info(f"バッチ作成開始: {i+1}〜{i+len(batch)}/{len(successful_uploads)}")
            
            # バッチ作成実行
            batch_result = batch_create_media_items(tokens, album_name, verbose)
            
            # 成功したファイルと失敗したファイルを処理
            success_indices = batch_result.get('success', [])
            failed_indices = batch_result.get('failed', [])
            
            # 成功したファイルをリストに追加
            for idx, token in enumerate(tokens):
                if token in success_indices:
                    success_files.append(files[idx])
                else:
                    failed_files_dict[files[idx]] = {
                        'retry_count': failed_files.get(files[idx], {}).get('retry_count', 0) + 1,
                        'last_error': 'バッチ作成に失敗',
                        'last_attempt': time.strftime('%Y-%m-%d %H:%M:%S')
                    }
            
            # 進捗を更新
            update_progress(len(success_files), len(failed_files_dict), len(upload_results))
    else:
        logger.warning("成功したファイルアップロードがありません。メディアアイテム作成はスキップします。")
    
    # 成功したファイルをアップロード済みリストに追加
    with open(uploaded_log, 'a', encoding='utf-8') as f:
        for file in success_files:
            f.write(f"{file}\n")
    
    # 今回失敗したファイルを失敗リストに追加/更新
    # 既存の失敗リストと今回の失敗リストをマージ
    updated_failed_files = {**failed_files, **failed_files_dict}
    
    # 成功したファイルは失敗リストから削除
    for file in success_files:
        if file in updated_failed_files:
            del updated_failed_files[file]
    
    # 失敗リストを保存
    with open(failed_log, 'w', encoding='utf-8') as f:
        json.dump(updated_failed_files, f, ensure_ascii=False, indent=2)
    
    logger.info(f"アップロード完了: 成功={len(success_files)}枚, 失敗={len(failed_files_dict)}枚")
    
    # 進捗ファイルを完了状態に更新
    progress_data['completed'] = True
    try:
        with open(progress_path, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False)
        
        # アップロード完了後の進捗ファイルは保持し、Web UI の停止操作で削除します
        logger.info("アップロード完了: 進捗ファイルを保持しました (Web 停止ボタンで削除されます)")
    except Exception as e:
        logger.debug(f"進捗ファイルの更新に失敗しました: {e}")
    
    return len(success_files) > 0

def show_uploaded_slideshow(fullscreen=True, recent=True, current_only=False, interval=5, random_order=False, 
                           no_pending=False, verbose=False, bgm_files=None):
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
            success = upload_photos(sd_path / DCIM_PATH, self.album_name, self.show_slideshow, 
                         self.fullscreen, self.recent, self.current_only,
                         self.interval, self.random_order, self.no_pending, 
                         self.verbose, self.bgm_files)
            self.last_processed = current_time
            
            # アップロードが成功しない場合でもスライドショーだけ表示
            if not success and self.show_slideshow:
                logger.info("アップロードする写真はありませんでしたが、スライドショーを表示します")
                show_uploaded_slideshow(fullscreen=self.fullscreen, recent=self.recent, 
                                     current_only=self.current_only, interval=self.interval,
                                     random_order=self.random_order, no_pending=self.no_pending,
                                     verbose=self.verbose, bgm_files=self.bgm_files)
    
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
                            # アップロード実行
                            success = upload_photos(volume / DCIM_PATH, self.album_name, self.show_slideshow,
                                                  self.fullscreen, self.recent, self.current_only,
                                                  self.interval, self.random_order, self.no_pending, 
                                                  self.verbose, self.bgm_files)
                            self.last_processed = time.time()
                            
                            # アップロードが成功しない場合でもスライドショーだけ表示
                            if not success and self.show_slideshow:
                                logger.info("アップロードする写真はありませんでしたが、スライドショーを表示します")
                                show_uploaded_slideshow(fullscreen=self.fullscreen, recent=not (not self.recent), 
                                                     current_only=self.current_only, interval=self.interval,
                                                     random_order=self.random_order, no_pending=self.no_pending,
                                                     verbose=self.verbose, bgm_files=self.bgm_files)
                                
                            break
                        else:
                            logger.info(f"ボリュームは見つかりましたが、DCIMフォルダがありません: {volume}")
            except Exception as e:
                logger.error(f"ボリュームチェック中のエラー: {e}")

def check_periodically(interval=10, album_name=None, show_slideshow=False, fullscreen=True, recent=True, 
                     current_only=False, slideshow_interval=5, random_order=False, no_pending=False, 
                     verbose=False, bgm_files=None):
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
    """
    while True:
        sd_path = find_sd_card()
        if sd_path and (sd_path / DCIM_PATH).exists():
            logger.info(f"SDカード検出: {sd_path}")
            success = upload_photos(sd_path / DCIM_PATH, album_name, show_slideshow, fullscreen, recent, current_only,
                        slideshow_interval, random_order, no_pending, verbose, bgm_files)
            
            # アップロードが成功しない場合でもスライドショーだけ表示
            if not success and show_slideshow:
                logger.info("アップロードする写真はありませんでしたが、スライドショーを表示します")
                show_uploaded_slideshow(fullscreen=fullscreen, recent=recent, 
                                     current_only=current_only, interval=slideshow_interval,
                                     random_order=random_order, no_pending=no_pending,
                                     verbose=verbose, bgm_files=bgm_files)
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
    args = parser.parse_args()
    
    # フルスクリーンモードとrecentモードの設定
    fullscreen = not args.no_fullscreen
    recent = not args.all_photos
    
    # まず、現在接続されているSDカードをチェック
    sd_path = find_sd_card()
    if sd_path and (sd_path / DCIM_PATH).exists():
        logger.info(f"SDカード検出: {sd_path}")
        success = upload_photos(sd_path / DCIM_PATH, args.album, args.slideshow, fullscreen, recent, args.current_only,
                    args.slideshow_interval, args.random, args.no_pending, args.verbose, args.bgm, args.all_photos)
        
        # アップロードが成功しない場合でも、スライドショーが指定されていれば表示する
        if not success and args.slideshow:
            logger.info("アップロードする写真はありませんでしたが、スライドショーを表示します")
            show_uploaded_slideshow(fullscreen=fullscreen, recent=not args.all_photos, current_only=args.current_only,
                                 interval=args.slideshow_interval, random_order=args.random, 
                                 no_pending=args.no_pending, verbose=args.verbose, bgm_files=args.bgm)
    
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
                             args.slideshow_interval, args.random, args.no_pending, args.verbose, args.bgm)
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
                         args.slideshow_interval, args.random, args.no_pending, args.verbose, args.bgm)

if __name__ == "__main__":
    main() 