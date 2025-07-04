#!/usr/bin/env python3

import os
import sys
import time
import random
import argparse
import logging
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ExifTags
from datetime import datetime, timedelta
import socket
# 共通メディアユーティリティ
from google_photos_uploader.utils.media import BackgroundMusicPlayer, AUDIO_EXTENSIONS, VideoPlayer
import cv2
import threading
import queue
import pygame
from google_photos_uploader.ui.base_slideshow import BaseSlideshowApp  # 追加
from collections import OrderedDict  # 追加

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 動画ファイルの拡張子
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.wmv', '.mkv'}

# --------------------------------------------------
# スライドショー本体
# --------------------------------------------------

def get_ip_address():
    """IPアドレスを取得する"""
    try:
        # ローカルIPアドレスを取得
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "IPアドレス取得エラー"

class SlideshowApp(BaseSlideshowApp):
    """
    アップロード済み写真と動画を使ってスライドショーを表示するアプリケーション
    """
    def __init__(self, root, image_files, interval=5, random_order=False, fullscreen=False, bgm_files=None, random_bgm=False):
        # Base クラス初期化
        super().__init__(root,
                         interval=interval,
                         random_order=random_order,
                         fullscreen=fullscreen,
                         # bgm_files が None の場合のみ自動探索を行う
                         bgm_files=bgm_files,
                         random_bgm=random_bgm)

        self.root = root
        self.image_files = image_files
        self.current_index = 0
        # 現在と次の 1 枚だけを保持する軽量 LRU キャッシュ
        self.image_cache: "OrderedDict[str, ImageTk.PhotoImage]" = OrderedDict()
        self.video_player = None  # 動画プレーヤー
        
        # ウィンドウタイトル
        self.root.title("Google Photos Uploader - スライドショー")
        
        # 画像表示用のラベル
        self.image_label = tk.Label(root, bg="black")
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # IPアドレス表示用のラベル（画像の上に重ねて配置）
        self.ip_label = tk.Label(root, text=f"IP: {get_ip_address()}", bg="black", fg="gray", font=("Helvetica", 14), anchor="ne")
        self.ip_label.place(relx=0.99, rely=0.01, anchor="ne")
        
        # アップロード進捗表示用のラベル（画像の上に重ねて配置）
        self.status_label = tk.Label(root, text="", bg="black", fg="gray", font=("Helvetica", 14), anchor="sw")
        # place を用いて下部に重ねる
        self.status_label.place(relx=0.01, rely=0.97, anchor="sw")
        
        # 表示するファイルがあるか確認
        if not self.image_files:
            self.show_error("アップロードされたファイルが見つかりません")
            return
        
        # 最初のファイルを表示
        if self.random_order:
            random.shuffle(self.image_files)
        
        # 最初の画像を先読みしてから表示
        self.status_label.config(text="画像を読み込み中...")
        self.root.update()  # ラベルを即時更新
        
        # 最初の画像を先読み
        first_file = self.image_files[0]
        if Path(first_file).suffix.lower() not in VIDEO_EXTENSIONS:
            try:
                img = Image.open(first_file)
                sw = self.root.winfo_width() or 3840
                sh = self.root.winfo_height() or 2160
                if sw > 0 and sh > 0:
                    img.thumbnail((sw, sh), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.image_cache[first_file] = photo
            except Exception as e:
                logger.error(f"最初の画像の読み込みに失敗: {e}")
        
        # 最初のファイルを表示
        self.show_file()
        
        # 進捗表示の更新を開始
        self.update_status()
        
        # BGM 更新の開始
        self.update_music()
        
    def show_error(self, message):
        """エラーメッセージを表示"""
        self.image_label.config(text=message, fg="white", font=("Helvetica", 16))
        
    def show_file(self):
        """現在のインデックスのファイルを表示"""
        if not self.image_files:
            return
        
        # ステータスを即時更新
        self.update_status()
        
        file_path = self.image_files[self.current_index]
        try:
            # ファイルが存在するか確認
            if not os.path.exists(file_path):
                logger.warning(f"ファイルが存在しません: {file_path}")
                # ファイルが存在しない場合は次のファイルへ
                self.current_index = (self.current_index + 1) % len(self.image_files)
                self.schedule_next_file()
                return

            # 動画ファイルの場合
            if Path(file_path).suffix.lower() in VIDEO_EXTENSIONS:
                # 既存の動画プレーヤーを停止
                if self.video_player:
                    self.video_player.stop()
                
                # 新しい動画プレーヤーを作成して開始
                self.video_player = VideoPlayer(file_path, self.image_label, self.interval)
                if not self.video_player.start():
                    self.next_file()
                    return
                
                # 動画表示の更新を開始
                self.update_video()
                
                # 次のファイルへの切り替えをスケジュール
                self.schedule_next_file()
            else:
                # 画像ファイルの場合
                if self.video_player:
                    self.video_player.stop()
                    self.video_player = None
                
                # キャッシュ確認
                cached = self.image_cache.get(file_path)
                if cached is not None:
                    photo = cached
                else:
                    # 画像を読み込み
                    img = Image.open(file_path)
                    
                    # EXIF情報から回転情報を取得して適用
                    try:
                        for orientation in ExifTags.TAGS.keys():
                            if ExifTags.TAGS[orientation] == 'Orientation':
                                break
                        
                        exif = img._getexif()
                        if exif is not None and orientation in exif:
                            if exif[orientation] == 2:
                                img = img.transpose(Image.FLIP_LEFT_RIGHT)
                            elif exif[orientation] == 3:
                                img = img.transpose(Image.ROTATE_180)
                            elif exif[orientation] == 4:
                                img = img.transpose(Image.FLIP_TOP_BOTTOM)
                            elif exif[orientation] == 5:
                                img = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)
                            elif exif[orientation] == 6:
                                img = img.transpose(Image.ROTATE_270)
                            elif exif[orientation] == 7:
                                img = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270)
                            elif exif[orientation] == 8:
                                img = img.transpose(Image.ROTATE_90)
                    except (AttributeError, KeyError, IndexError):
                        # EXIFデータがない場合やエラーの場合は無視
                        pass
                    
                    # 画像をリサイズ (thumbnail は in-place, アスペクト比保持)
                    sw = self.root.winfo_width() or 3840
                    sh = self.root.winfo_height() or 2160
                    if sw > 0 and sh > 0:
                        # 4K ディスプレイ想定: Pillow が自動で縮小してくれる
                        img.thumbnail((sw, sh), Image.Resampling.LANCZOS)

                    # Tk 用イメージ生成
                    photo = ImageTk.PhotoImage(img)

                    # キャッシュへ追加し、サイズを 2 枚に制限
                    self.image_cache[file_path] = photo
                    if len(self.image_cache) > 2:
                        # 先頭 (最も古い) を削除
                        self.image_cache.popitem(last=False)
                
                # 画像を表示
                self.image_label.configure(image=photo)
                self.image_label.image = photo  # 参照を保持
                
                # 次画像を非同期で先読み
                next_idx = (self.current_index + 1) % len(self.image_files)
                next_path = self.image_files[next_idx]
                if next_path not in self.image_cache:
                    threading.Thread(target=self._prefetch_image, args=(next_path,), daemon=True).start()
                
                # 次の画像への切り替えをスケジュール
                self.schedule_next_file()
                
        except Exception as e:
            logger.error(f"ファイルの表示中にエラーが発生しました: {e}")
            self.next_file()
            return

    def update_video(self):
        """動画表示を更新"""
        if self.video_player and self.video_player.playing:
            self.video_player.update_display()
            self.root.after(33, self.update_video)  # 約30fps

    def schedule_next_file(self):
        """次のファイル表示をスケジュール"""
        # 既存のスケジュールをキャンセル
        if self.after_id:
            self.root.after_cancel(self.after_id)
        
        # 次のファイル表示をスケジュール
        self.after_id = self.root.after(self.interval, self.next_file)
        
    def next_file(self, event=None):
        """次のファイルに進む"""
        if self.video_player:
            self.video_player.stop()
            self.video_player = None
        self.current_index = (self.current_index + 1) % len(self.image_files)
        self.show_file()
        # ステータスを即時更新
        self.update_status()

    def prev_file(self, event=None):
        """前のファイルに戻る"""
        if self.video_player:
            self.video_player.stop()
            self.video_player = None
        self.current_index = (self.current_index - 1) % len(self.image_files)
        self.show_file()
        # ステータスを即時更新
        self.update_status()

    def toggle_play(self, event=None):
        """再生/一時停止を切り替え"""
        self.playing = not self.playing
        if self.playing:
            if self.video_player:
                self.video_player.playing = True
            if self.music_player and self.music_player.enabled:
                self.music_player.resume()
            self.schedule_next_file()
        else:
            if self.video_player:
                self.video_player.playing = False
            if self.music_player and self.music_player.enabled:
                self.music_player.pause()
            if self.after_id:
                self.root.after_cancel(self.after_id)
                self.after_id = None
        # ステータスを即時更新
        self.update_status()

    def update_status(self):
        """アップロード進捗を読み取り、ラベルを更新する"""
        progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
        status_text = ""
        if progress_path.exists():
            try:
                with open(progress_path, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                total = progress.get('total', 0)
                success = progress.get('success', 0)
                failed = progress.get('failed', 0)
                completed = progress.get('completed', False)
                album_name = progress.get('album_name', '')
                custom_message = progress.get('message', '')
                
                if custom_message:
                    # カスタムメッセージがある場合はそれを表示
                    status_text = custom_message
                elif completed:
                    status_text = f"アルバム「{album_name}」にアップロードされました ({success}/{total}枚)"
                else:
                    status_text = f"アップロード中: {success}/{total} (失敗 {failed})"
                    if album_name:
                        status_text += f" - アルバム: {album_name}"
            except Exception as e:
                logger.debug(f"進捗ファイルの読み込みに失敗しました: {e}")
        
        # スライドショーの現在の位置を表示
        if self.image_files:
            position_text = f"{self.current_index + 1}/{len(self.image_files)}"
            if status_text:
                status_text += f" {position_text}"
            else:
                status_text = position_text
                
        # ラベルを更新
        self.status_label.config(text=status_text)
        # ポーリングは廃止
        # self.root.after(2000, self.update_status)

    def update_music(self):
        """BGM の再生状況を監視し次曲を再生"""
        if self.music_player and self.music_player.enabled:
            self.music_player.update()
        self.root.after(1000, self.update_music)

    # ------------------------------------------------------------------
    # BaseSlideshowApp 互換メソッド
    # ------------------------------------------------------------------

    def next_item(self, event=None):
        self.next_file(event)

    def prev_item(self, event=None):
        self.prev_file(event)

    def schedule_next_item(self):
        self.schedule_next_file()

    # --------------------------------------------------
    # 画像先読み
    # --------------------------------------------------

    def _prefetch_image(self, path: str):
        """次に表示する画像を事前に読み込みキャッシュ"""
        try:
            img = Image.open(path)
            sw = self.root.winfo_width() or 3840
            sh = self.root.winfo_height() or 2160
            img.thumbnail((sw, sh), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            # キャッシュ登録 (LRU 制御)
            self.image_cache[path] = photo
            if len(self.image_cache) > 2:
                self.image_cache.popitem(last=False)
        except Exception as e:
            logger.debug(f"prefetch 失敗: {e}")

def find_pending_upload_files():
    """アップロード予定のファイルを探す"""
    # 失敗したファイルの記録を保持するファイル
    failed_log = Path.home() / '.google_photos_uploader' / 'failed_files.json'
    
    pending_files = []
    
    # 失敗ログが存在すれば読み込む
    if failed_log.exists():
        try:
            import json
            with open(failed_log, 'r', encoding='utf-8') as f:
                failed_files = json.load(f)
                
            # 失敗ファイルのパスを取得
            for file_path in failed_files.keys():
                if os.path.exists(file_path):
                    pending_files.append(file_path)
                    
            logger.info(f"アップロード予定/失敗ファイル: {len(pending_files)}件が見つかりました")
            
        except Exception as e:
            logger.error(f"失敗ファイルの読み込み中にエラーが発生しました: {e}")
    
    return pending_files

def load_uploaded_files(only_recent=False, include_pending=True):
    """アップロード済みファイルの一覧を読み込む
    
    Args:
        only_recent (bool): 最近アップロードされたファイルのみ取得する場合はTrue
        include_pending (bool): アップロード予定/失敗ファイルも含める場合はTrue
    """
    uploaded_log = Path.home() / '.google_photos_uploader' / 'uploaded_files.txt'
    
    result_files = []
    pending_files = []  # type: list
    
    # アップロード予定/失敗ファイルを追加
    if include_pending:
        pending_files = find_pending_upload_files()
        result_files.extend(pending_files)
    
    if not uploaded_log.exists():
        logger.warning(f"アップロード済みファイルのログが見つかりません: {uploaded_log}")
        return result_files
        
    try:
        # ファイルの更新時間を取得
        log_mtime = None
        if only_recent:
            if uploaded_log.exists():
                log_stat = uploaded_log.stat()
                log_mtime = datetime.fromtimestamp(log_stat.st_mtime)
                logger.info(f"最近のアップロードを表示します（ログ更新日時: {log_mtime}）")
        
        # ファイルの内容を読み込む
        with open(uploaded_log, 'r', encoding='utf-8') as f:
            file_paths = [line.strip() for line in f.readlines()]
        
        # 存在するファイルのみをフィルタリング
        existing_files = []
        
        if only_recent and log_mtime:
            # 指定時間内 (デフォルト24時間) にアップロードされたファイルのみを対象
            RECENT_HOURS = 24
            recent_threshold = datetime.now() - timedelta(hours=RECENT_HOURS)
            for path in reversed(file_paths):  # 新しい順に確認
                if not os.path.exists(path):
                    continue
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(path))
                    if mtime >= recent_threshold:
                        existing_files.insert(0, path)
                except Exception:
                    # タイムスタンプ取得に失敗した場合はスキップせず追加
                    existing_files.insert(0, path)
        
            # 24時間以内のファイルが見つからない場合は、直近の200件のみを表示
            if not existing_files:
                temp_files = [p for p in file_paths if os.path.exists(p)]
                existing_files = temp_files[-200:]
        
        else:
            # すべてのファイルを返す場合
            for path in file_paths:
                if os.path.exists(path):
                    existing_files.append(path)
                else:
                    logger.debug(f"ファイルが見つかりません（スキップします）: {path}")
        
        # 結果に追加
        result_files.extend(existing_files)
        
        # 重複を排除
        result_files = list(dict.fromkeys(result_files))

        # アップロードがない（pending_files が空）場合は最新 100 件のみに制限し、
        # その 100 件を古い順に再生できるように並び順は維持する
        if not pending_files and not only_recent and len(result_files) > 100:
            logger.info(f"アップロード中ファイルがないため、最新 100 件に絞り込みます (全 {len(result_files)} 件) → 100 件")
            # result_files は古い順になっているため、末尾 100 件が最新 100 件
            result_files = result_files[-100:]
        
        mode_str = "最近の" if only_recent else "すべての"
        logger.info(f"{mode_str}ファイル: {len(result_files)}件が利用可能")
        return result_files
        
    except Exception as e:
        logger.error(f"アップロード済みファイルの読み込み中にエラーが発生しました: {e}")
        return result_files

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='アップロード済み写真のスライドショーを表示する')
    parser.add_argument('--interval', type=int, default=5, help='画像の表示間隔（秒）')
    parser.add_argument('--random', action='store_true', help='ランダム順で表示する')
    parser.add_argument('--fullscreen', action='store_true', help='フルスクリーンモードで表示する')
    parser.add_argument('--verbose', action='store_true', help='詳細なログを出力する')
    parser.add_argument('--current', action='store_true', help='現在アップロード中の写真のみ表示する')
    parser.add_argument('--no-pending', action='store_true', help='アップロード予定/失敗ファイルを含めない')
    parser.add_argument('--bgm', nargs='*', help='BGMとして再生する音楽ファイルまたはディレクトリ（複数指定可）')
    parser.add_argument('--random-bgm', action='store_true', help='BGMをランダムに再生する')
    args = parser.parse_args()
    
    # 詳細ログモードが指定された場合
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("詳細ログモードが有効です")
    
    # --current が指定されている場合は、アップロード進捗ファイルから取得
    if args.current:
        image_files = load_current_upload_files()
    else:
        image_files = load_uploaded_files(only_recent=False, include_pending=not args.no_pending)
    
    if not image_files:
        logger.error("表示できる画像がありません")
        print("アップロード済み写真が見つかりません。先に写真をアップロードしてください。")
        sys.exit(1)
    
    # Tkinterの初期化
    root = tk.Tk()
    
    # BGM ファイルの収集
    bgm_files = None
    if args.bgm is not None:
        # 引数なし（--bgm のみ）の場合は空リストを渡して ~/bgm を探索
        if len(args.bgm) == 0:
            bgm_files = []
        else:
            def collect(paths):
                files = []
                for p in paths:
                    if os.path.isdir(p):
                        for dirpath, _, filenames in os.walk(p):
                            for fn in filenames:
                                if Path(fn).suffix.lower() in AUDIO_EXTENSIONS:
                                    files.append(os.path.join(dirpath, fn))
                    elif os.path.isfile(p):
                        if Path(p).suffix.lower() in AUDIO_EXTENSIONS:
                            files.append(p)
                return files
            bgm_files = collect(args.bgm)
    else:
        # BGM オプションが指定されていない場合は None（無効）
        bgm_files = None

    # アプリケーションの作成
    app = SlideshowApp(
        root=root,
        image_files=image_files,
        interval=args.interval,
        random_order=args.random,
        fullscreen=args.fullscreen,
        bgm_files=bgm_files,
        random_bgm=args.random_bgm
    )
    
    # イベントループの開始
    root.mainloop()

def load_current_upload_files():
    """現在アップロード対象になっているファイルのリストを取得する"""
    progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
    if not progress_path.exists():
        logger.warning(f"進捗ファイルが見つかりません: {progress_path}")
        return []
    try:
        with open(progress_path, 'r', encoding='utf-8') as f:
            progress = json.load(f)
        files = progress.get('files', [])
        # 存在するファイルのみ返す
        existing = [p for p in files if os.path.exists(p)]
        
        logger.info(f"現在アップロード中のファイル {len(existing)} 件を読み込みました")
        return existing
    except Exception as e:
        logger.error(f"進捗ファイルの読み込み中にエラーが発生しました: {e}")
        return []

if __name__ == "__main__":
    main() 