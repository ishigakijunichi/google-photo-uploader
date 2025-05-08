#!/usr/bin/env python3

import os
import sys
import json
import time
import random
import argparse
import logging
import requests
import tkinter as tk
from tkinter import ttk  # ttk モジュールを明示的にインポート
from pathlib import Path
from PIL import Image, ImageTk
import io
import threading
import queue
import pygame

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# APIのスコープを定義
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]

# Google Photos APIのエンドポイント
API_BASE_URL = 'https://photoslibrary.googleapis.com/v1'

# 一時ファイル保存ディレクトリ
TEMP_DIR = Path.home() / '.google_photos_uploader' / 'temp'

def authenticate():
    """Google APIに認証してcredentialsを返す"""
    creds = None
    token_path = Path.home() / '.google_photos_uploader' / 'token.json'
    
    # トークンファイルがあればそれを使用
    if token_path.exists():
        creds = Credentials.from_authorized_user_info(json.loads(token_path.read_text()), SCOPES)
    
    # 有効な認証情報がない場合は、ユーザーにログインを要求
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials_path = Path.home() / '.google_photos_uploader' / 'credentials.json'
            if not credentials_path.exists():
                print(f"認証情報ファイルが見つかりません: {credentials_path}")
                print("Google Cloud Consoleで認証情報を作成し、上記のパスに保存してください。")
                return None
            
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        
        # 認証情報を保存
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(json.dumps({
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': creds.scopes
        }))
    
    return creds

def get_albums(creds):
    """アルバムのリストを取得する"""
    url = f"{API_BASE_URL}/albums"
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    albums = []
    page_token = None
    
    while True:
        # ページトークンがあれば追加
        params = {'pageSize': 50}
        if page_token:
            params['pageToken'] = page_token
            
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            logger.error(f"アルバムリスト取得中にエラーが発生しました: {response.text}")
            break
            
        result = response.json()
        if 'albums' in result:
            albums.extend(result['albums'])
            
        # 次のページがあるか確認
        if 'nextPageToken' in result:
            page_token = result['nextPageToken']
        else:
            break
            
    return albums

def get_album_media_items(album_id, creds):
    """アルバムからメディアアイテムを取得する"""
    url = f"{API_BASE_URL}/mediaItems:search"
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    media_items = []
    page_token = None
    
    while True:
        # リクエストデータを作成
        data = {
            'albumId': album_id,
            'pageSize': 100
        }
        
        if page_token:
            data['pageToken'] = page_token
            
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code != 200:
            logger.error(f"メディアアイテム取得中にエラーが発生しました: {response.text}")
            break
            
        result = response.json()
        if 'mediaItems' in result:
            media_items.extend(result['mediaItems'])
            
        # 次のページがあるか確認
        if 'nextPageToken' in result:
            page_token = result['nextPageToken']
        else:
            break
            
    return media_items

def download_media_item(media_item, size='2048'):
    """メディアアイテムをダウンロードする
    
    Args:
        media_item: Google Photos APIから取得したメディアアイテム
        size: ダウンロードする画像サイズ (w*h)
        
    Returns:
        PIL.Image: ダウンロードした画像
    """
    if media_item.get('mimeType', '').startswith('video/'):
        # 動画の場合はベースURLを使用
        download_url = f"{media_item['baseUrl']}=dv"
    else:
        # 画像の場合はサイズを指定
        download_url = f"{media_item['baseUrl']}=w{size}-h{size}"
    
    response = requests.get(download_url)
    if response.status_code != 200:
        logger.error(f"メディアダウンロード中にエラーが発生しました: {response.status_code}")
        return None
    
    # 画像データをPIL.Imageオブジェクトに変換
    try:
        return Image.open(io.BytesIO(response.content))
    except Exception as e:
        logger.error(f"画像の変換中にエラーが発生しました: {e}")
        return None

class BackgroundMusicPlayer:
    """BGM 再生を管理するクラス"""
    def __init__(self, music_files=None, volume=0.5):
        # BGMフォルダから音楽ファイルを取得
        if music_files is None:
            bgm_dir = Path(__file__).parent.parent / 'bgm'
            if bgm_dir.exists():
                music_files = list(bgm_dir.glob('*.mp3')) + list(bgm_dir.glob('*.wav'))
            else:
                music_files = []
        
        self.music_files = [str(p) for p in music_files if os.path.exists(str(p))]
        self.volume = volume
        self.current_index = 0
        self.enabled = bool(self.music_files)
        
        if not self.enabled:
            logger.info("BGM ファイルが見つからないため BGM は再生しません")
            return
            
        try:
            pygame.mixer.init()
            pygame.mixer.music.set_volume(self.volume)
            self.play_current()
        except Exception as e:
            logger.error(f"pygame.mixer の初期化に失敗しました: {e}")
            self.enabled = False

    def play_current(self):
        if not self.enabled:
            return
        path = self.music_files[self.current_index]
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            logger.debug(f"BGM 再生開始: {path}")
        except Exception as e:
            logger.error(f"BGM 再生中にエラーが発生しました: {e}")

    def update(self):
        """曲が終了したかをチェックし、次の曲を再生"""
        if not self.enabled:
            return
        if not pygame.mixer.music.get_busy():
            # 次の曲へ
            self.current_index = (self.current_index + 1) % len(self.music_files)
            self.play_current()

    def pause(self):
        if self.enabled:
            pygame.mixer.music.pause()

    def resume(self):
        if self.enabled:
            pygame.mixer.music.unpause()

    def stop(self):
        if self.enabled:
            pygame.mixer.music.stop()
            pygame.mixer.quit()

class AlbumSlideshowApp:
    """
    Google Photosのアルバムからメディアを取得してスライドショーを表示するアプリケーション
    """
    def __init__(self, root, media_items, album_title="不明なアルバム", interval=5, random_order=False, fullscreen=False, bgm_files=None):
        self.root = root
        self.media_items = media_items
        self.album_title = album_title
        self.interval = interval * 1000  # ミリ秒に変換
        self.random_order = random_order
        self.current_index = 0
        self.images_cache = {}  # 画像キャッシュ
        
        # BGM プレーヤー
        self.music_player = BackgroundMusicPlayer(bgm_files)
        
        # ウィンドウの設定
        self.root.title(f"Google Photos Album - {album_title}")
        self.root.configure(bg="black")
        
        # フルスクリーンモード
        if fullscreen:
            self.root.attributes("-fullscreen", True)
            self.root.bind("<Escape>", lambda e: self.root.destroy())  # ESCキーで終了
            self.root.bind("<q>", lambda e: self.root.destroy())  # qキーで終了
        
        # 画像表示用のラベル
        self.image_label = tk.Label(root, bg="black")
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # ステータス表示用のラベル
        self.status_label = tk.Label(root, text="", bg="black", fg="white", font=("Helvetica", 14), anchor="sw")
        self.status_label.place(relx=0.01, rely=0.97, anchor="sw")
        
        # 現在のアイテム名表示用のラベル
        self.title_label = tk.Label(root, text="", bg="black", fg="white", font=("Helvetica", 16), anchor="n")
        self.title_label.place(relx=0.5, rely=0.05, anchor="n")
        
        # アルバム名表示用のラベル
        self.album_label = tk.Label(root, text=f"アルバム：{album_title}", bg="black", fg="white", font=("Helvetica", 14), anchor="ne")
        self.album_label.place(relx=0.99, rely=0.05, anchor="ne")
        
        # マウスクリックで次の画像
        self.root.bind("<Button-1>", self.next_image)
        
        # キーボードショートカット
        self.root.bind("<Right>", self.next_image)  # 右矢印キー
        self.root.bind("<Left>", self.prev_image)   # 左矢印キー
        self.root.bind("<space>", self.toggle_play)  # スペースキー
        
        # 再生/一時停止状態
        self.playing = True
        self.after_id = None
        
        # プログレスバー
        self.progress_var = tk.DoubleVar()
        self.progress = tk.ttk.Progressbar(
            root, 
            variable=self.progress_var,
            style="TProgressbar", 
            orient="horizontal", 
            length=200
        )
        self.progress.place(relx=0.5, rely=0.95, anchor="center")
        
        # ttk スタイルを設定
        style = tk.ttk.Style()
        style.configure("TProgressbar", thickness=5)
        
        # 読み込み中表示
        self.loading_text = "読み込み中..."
        self.update_status(self.loading_text)
        
        # 表示するアイテムがあるか確認
        if not self.media_items:
            self.show_error("アルバム内にメディアが見つかりません")
            return
        
        # ランダム表示の場合はシャッフル
        if self.random_order:
            random.shuffle(self.media_items)
        
        # 最初の画像の読み込みを開始
        self.load_image_thread = threading.Thread(target=self.preload_images)
        self.load_image_thread.daemon = True
        self.load_image_thread.start()
        
        # 最初の画像を表示（遅延実行）
        self.root.after(100, self.show_current_image)
        
        # BGM 更新の開始
        self.update_music()
        
    def preload_images(self):
        """バックグラウンドで画像を先読みする"""
        # 現在の画像と次の画像を先読み
        for i in range(min(5, len(self.media_items))):
            idx = (self.current_index + i) % len(self.media_items)
            self.get_image(idx)
    
    def get_image(self, index):
        """指定されたインデックスの画像を取得（キャッシュから、なければダウンロード）"""
        if index in self.images_cache:
            return self.images_cache[index]
            
        media_item = self.media_items[index]
        
        # 動画かどうかをチェック
        if media_item.get('mimeType', '').startswith('video/'):
            # 動画の場合はNoneを返す（再生しない）
            logger.info(f"メディアID: {media_item.get('id')} は動画形式 ({media_item.get('mimeType')}) なので再生できません")
            return None
        
        # 画像の場合はURLを構築してダウンロード
        download_url = f"{media_item['baseUrl']}=w2048-h2048"
    
        response = requests.get(download_url)
        if response.status_code != 200:
            logger.error(f"メディアダウンロード中にエラーが発生しました: {response.status_code}")
            return None
        
        # 画像データをPIL.Imageオブジェクトに変換
        try:
            image = Image.open(io.BytesIO(response.content))
            # キャッシュに保存
            self.images_cache[index] = image
            
            # キャッシュサイズを制限（最大10枚）
            if len(self.images_cache) > 10:
                # 現在のインデックスから最も遠いものを削除
                keys = list(self.images_cache.keys())
                keys.sort(key=lambda k: min((k - self.current_index) % len(self.media_items),
                                         (self.current_index - k) % len(self.media_items)),
                         reverse=True)
                del self.images_cache[keys[0]]
            
            return image
        except Exception as e:
            logger.error(f"画像の変換中にエラーが発生しました: {e}")
            return None
        
    def show_error(self, message):
        """エラーメッセージを表示"""
        self.image_label.config(image='')
        self.status_label.config(text=message)
        self.title_label.config(text="エラー")
        
    def show_current_image(self):
        """現在のインデックスの画像を表示"""
        if not self.media_items:
            return
            
        media_item = self.media_items[self.current_index]
        
        # 画像タイトル（ファイル名）を表示
        title = media_item.get('filename', f"画像 {self.current_index + 1}/{len(self.media_items)}")
        self.title_label.config(text=title)
        
        # ステータス更新
        self.update_status(f"{self.current_index + 1}/{len(self.media_items)}")
        
        # プログレスバー更新
        self.progress_var.set((self.current_index + 1) / len(self.media_items) * 100)
        
        try:
            # 動画かどうかをチェック
            if media_item.get('mimeType', '').startswith('video/'):
                # 動画の場合はスキップして次の画像へ
                logger.info(f"メディア '{media_item.get('filename')}' は動画なので再生できません。スキップします。")
                self.update_status(f"動画はスキップします - {self.current_index + 1}/{len(self.media_items)}")
                # 少し待ってから次の画像に進む
                self.root.after(2000, self.next_image)
                return
            
            # 画像を取得（キャッシュまたはダウンロード）
            img = self.get_image(self.current_index)
            if not img:
                # 画像の取得に失敗した場合は次へ
                self.next_image()
                return
                
            # 画像をリサイズ
            width, height = img.size
            screen_width = self.root.winfo_width()
            screen_height = self.root.winfo_height()
            
            if screen_width > 10 and screen_height > 10:  # ウィンドウサイズが正常な場合
                # アスペクト比を維持してリサイズ
                aspect_ratio = width / height
                if width > screen_width:
                    width = screen_width
                    height = int(width / aspect_ratio)
                if height > screen_height:
                    height = screen_height
                    width = int(height * aspect_ratio)
                
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            
            # 画像を表示
            photo = ImageTk.PhotoImage(img)
            self.image_label.configure(image=photo)
            self.image_label.image = photo  # 参照を保持
            
            # 次の画像を先読み
            next_idx = (self.current_index + 1) % len(self.media_items)
            threading.Thread(target=lambda: self.get_image(next_idx)).start()
            
            # 次の画像への切り替えをスケジュール
            self.schedule_next_image()
                
        except Exception as e:
            logger.error(f"画像の表示中にエラーが発生しました: {e}")
            self.show_error(f"画像の表示に失敗しました: {str(e)}")
            self.next_image()
            return

    def schedule_next_image(self):
        """次の画像表示をスケジュール"""
        # 既存のスケジュールをキャンセル
        if self.after_id:
            self.root.after_cancel(self.after_id)
        
        # 次の画像表示をスケジュール
        if self.playing:
            self.after_id = self.root.after(self.interval, self.next_image)
        
    def next_image(self, event=None):
        """次の画像に進む"""
        self.current_index = (self.current_index + 1) % len(self.media_items)
        self.show_current_image()
        
    def prev_image(self, event=None):
        """前の画像に戻る"""
        self.current_index = (self.current_index - 1) % len(self.media_items)
        self.show_current_image()
        
    def toggle_play(self, event=None):
        """再生/一時停止を切り替え"""
        self.playing = not self.playing
        if self.playing:
            self.music_player.resume()
            self.schedule_next_image()
            self.update_status(f"再生中 - {self.current_index + 1}/{len(self.media_items)}")
        else:
            self.music_player.pause()
            if self.after_id:
                self.root.after_cancel(self.after_id)
                self.after_id = None
            self.update_status(f"停止中 - {self.current_index + 1}/{len(self.media_items)}")

    def update_status(self, message):
        """ステータスラベルを更新"""
        self.status_label.config(text=message)

    def update_music(self):
        """BGM の再生状況を監視し次曲を再生"""
        if self.music_player and self.music_player.enabled:
            self.music_player.update()
        self.root.after(1000, self.update_music)

def select_album_dialog(albums):
    """アルバム選択ダイアログを表示"""
    dialog = tk.Toplevel()
    dialog.title("アルバムを選択")
    dialog.geometry("600x400")
    dialog.transient()  # ダイアログをモーダルに
    dialog.grab_set()   # ダイアログにフォーカスを設定
    
    # タイトルラベル
    tk.Label(dialog, text="表示するアルバムを選択してください", font=("Helvetica", 14)).pack(pady=10)
    
    # リストボックス
    listbox = tk.Listbox(dialog, width=50, height=15, font=("Helvetica", 12))
    listbox.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
    
    # スクロールバー
    scrollbar = tk.Scrollbar(listbox)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    listbox.config(yscrollcommand=scrollbar.set)
    scrollbar.config(command=listbox.yview)
    
    # アルバムリストを表示
    for i, album in enumerate(albums):
        title = album.get('title', f"アルバム {i+1}")
        item_count = album.get('mediaItemsCount', '0')
        listbox.insert(tk.END, f"{title} ({item_count} 枚)")
    
    # 選択結果を格納する変数
    selected_album = [None]
    
    # OKボタンの処理
    def on_ok():
        idx = listbox.curselection()
        if idx:
            selected_album[0] = albums[idx[0]]
        dialog.destroy()
    
    # キャンセルボタンの処理
    def on_cancel():
        dialog.destroy()
    
    # ダブルクリックでの選択
    def on_double_click(event):
        idx = listbox.curselection()
        if idx:
            selected_album[0] = albums[idx[0]]
            dialog.destroy()
    
    listbox.bind('<Double-1>', on_double_click)
    
    # ボタンフレーム
    button_frame = tk.Frame(dialog)
    button_frame.pack(fill=tk.X, padx=20, pady=20)
    
    tk.Button(button_frame, text="OK", command=on_ok, width=10).pack(side=tk.RIGHT, padx=5)
    tk.Button(button_frame, text="キャンセル", command=on_cancel, width=10).pack(side=tk.RIGHT, padx=5)
    
    # ダイアログが閉じるまで待機
    dialog.wait_window()
    
    return selected_album[0]

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='Google Photosのアルバムからスライドショーを表示する')
    parser.add_argument('--album', type=str, default="Photo Uploader", help='表示するアルバム名')
    parser.add_argument('--interval', type=int, default=5, help='スライドの表示間隔（秒）')
    parser.add_argument('--random', action='store_true', help='ランダムな順序で表示')
    parser.add_argument('--fullscreen', action='store_true', help='フルスクリーンモードで表示')
    parser.add_argument('--verbose', action='store_true', help='詳細なログを出力')
    parser.add_argument('--exact-match', action='store_true', help='アルバム名を完全一致で検索')
    parser.add_argument('--list-albums-only', action='store_true', help='アルバムリストをJSON形式で出力して終了')
    args = parser.parse_args()
    
    # 詳細ログモードが指定された場合
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("詳細ログモードが有効です")
    
    # Google Photos APIに認証
    logger.info("Google Photos APIに認証しています...")
    creds = authenticate()
    if not creds:
        logger.error("認証に失敗しました")
        return
    
    # アルバムのリストを取得
    logger.info("アルバムリストを取得しています...")
    albums = get_albums(creds)
    if not albums:
        logger.error("アルバムが見つかりません")
        return
    
    # アルバムリストのみ出力する場合
    if args.list_albums_only:
        # アルバム情報をJSON形式で出力
        albums_data = []
        for album in albums:
            albums_data.append({
                'id': album.get('id'),
                'title': album.get('title', '不明なアルバム'),
                'itemCount': album.get('mediaItemsCount', '0')
            })
        print(json.dumps(albums_data))
        return
    
    # アルバムの選択
    selected_album = None
    if args.album:
        # コマンドラインで指定されたアルバム名を検索
        for album in albums:
            if args.exact_match:
                # 完全一致の場合
                if album.get('title') == args.album:
                    selected_album = album
                    break
            else:
                # 部分一致の場合
                if args.album.lower() in album.get('title', '').lower():
                    selected_album = album
                    break
        
        if not selected_album:
            error_msg = f"指定されたアルバム '{args.album}' が見つかりません"
            logger.warning(error_msg)
            if args.exact_match:
                # 完全一致が要求された場合は、エラーで終了
                print(f"エラー: {error_msg}")
                print("利用可能なアルバム:")
                for album in albums:
                    print(f" - {album.get('title')}")
                return
    
    # アルバムが選択されてない場合はダイアログを表示
    if not selected_album:
        # tkinterのルートウィンドウ（表示しない）
        temp_root = tk.Tk()
        temp_root.withdraw()  # ウィンドウを非表示
        
        selected_album = select_album_dialog(albums)
        
        # ダイアログをキャンセルした場合
        if not selected_album:
            logger.info("アルバムが選択されませんでした")
            return
    
    # 選択されたアルバムからメディアアイテムを取得
    album_title = selected_album.get('title', '不明なアルバム')
    album_id = selected_album.get('id')
    logger.info(f"アルバム '{album_title}' からメディアアイテムを取得しています...")
    
    media_items = get_album_media_items(album_id, creds)
    if not media_items:
        logger.error(f"アルバム '{album_title}' にメディアアイテムが見つかりません")
        return
    
    logger.info(f"{len(media_items)}個のメディアアイテムが見つかりました")
    
    # スライドショーを表示
    root = tk.Tk()
    app = AlbumSlideshowApp(
        root, 
        media_items, 
        album_title=album_title,
        interval=args.interval, 
        random_order=args.random, 
        fullscreen=args.fullscreen
    )
    
    # ウィンドウサイズを設定（フルスクリーンでない場合）
    if not args.fullscreen:
        root.geometry("1024x768")
    
    root.mainloop()

if __name__ == '__main__':
    # 一時ディレクトリを作成
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    main() 