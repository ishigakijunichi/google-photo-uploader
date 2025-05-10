import logging
import os
from pathlib import Path
from typing import List

import pygame
import cv2
import threading
import queue
import time
from tkinter import Label
import random

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'
}

class BackgroundMusicPlayer:
    """BGM 再生を管理する共通クラス"""

    def __init__(self, music_files: List[str] | None = None, volume: float = 0.5, random_order: bool = False):
        """コンストラクタ

        Args:
            music_files: BGM に使用する音楽ファイルのリスト。
                * None  … BGM を無効化（再生しない）
                * []    … BGM ディレクトリ（~/bgm）を自動探索して再生。
                * list  … 指定されたパスのみを再生。
            volume: 再生音量（0.0〜1.0）
            random_order: True の場合は曲順をランダムにする。
        """

        # music_files が None の場合は BGM 無効
        if music_files is None:
            self.music_files = []
            self.volume = volume
            self.current_index = 0
            self.enabled = False
            self.random_order = random_order
            logger.info("BGM は無効です (--bgm オプションが指定されていません)")
            return

        # music_files が空リストの場合も ~/bgm を探索
        if isinstance(music_files, list) and len(music_files) == 0:
            # 探索ディレクトリ（プロジェクト直下の bgm のみ）
            candidates = [Path(__file__).resolve().parents[3] / 'bgm']

            for bgm_dir in candidates:
                if not bgm_dir.exists():
                    continue
                for ext in AUDIO_EXTENSIONS:
                    music_files.extend([str(p) for p in bgm_dir.glob(f'*{ext}')])
                if music_files:
                    logger.info(f"BGMフォルダから{len(music_files)}個の音楽ファイルを読み込みました: {bgm_dir}")
                    break  # 最初に見つかったディレクトリを使用

            if len(music_files) == 0:
                logger.info("候補ディレクトリに音楽ファイルが見つかりません。BGM は再生しません")
                self.music_files = []
                self.volume = volume
                self.current_index = 0
                self.enabled = False
                self.random_order = random_order
                return

        # 対応拡張子 & 実在ファイルをフィルタ
        self.music_files = [p for p in music_files if Path(p).suffix.lower() in AUDIO_EXTENSIONS and os.path.exists(p)]
        self.volume = volume
        self.current_index = 0
        self.enabled = bool(self.music_files)
        self.random_order = random_order

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

    # --------------------------------------------------
    # 制御メソッド
    # --------------------------------------------------

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
            if self.random_order:
                # ランダムに次の曲を選択（現在の曲以外）
                available_indices = [i for i in range(len(self.music_files)) if i != self.current_index]
                if available_indices:
                    self.current_index = random.choice(available_indices)
            else:
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

# --------------------------------------------------
# 動画プレイヤー共通クラス
# --------------------------------------------------

class VideoPlayer:
    """OpenCV + Tkinter ラベルで動画を再生するユーティリティ"""

    def __init__(self, video_path: str, label: Label, interval: int):
        self.video_path = video_path
        self.label = label
        self.interval = interval
        self.cap: cv2.VideoCapture | None = None
        self.playing = False
        # 4K フレームは 1 枚あたりメモリ消費が大きいため、保持数を最小限に抑える
        self.frame_queue: queue.Queue = queue.Queue(maxsize=5)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    # --------------------------------------------------
    # 公開 API
    # --------------------------------------------------

    def start(self) -> bool:
        """動画再生を開始"""
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            logger.error("動画を開けません: %s", self.video_path)
            return False

        self.playing = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._update_frame, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        """動画再生を停止"""
        self.playing = False
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        if self.cap:
            self.cap.release()
        self.cap = None

    def update_display(self):
        """Tkinter ラベルを最新フレームで更新"""
        if not self.playing:
            return
        try:
            photo = self.frame_queue.get_nowait()
            self.label.configure(image=photo)
            self.label.image = photo  # keep reference
        except queue.Empty:
            pass

    # --------------------------------------------------
    # 内部処理
    # --------------------------------------------------

    def _update_frame(self):
        while not self.stop_event.is_set():
            if self.cap is None:
                break
            ret, frame = self.cap.read()
            if not ret:
                # 終端 → 先頭に戻る
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            h, w = frame.shape[:2]
            sw = self.label.winfo_width()
            sh = self.label.winfo_height()
            if sw > 0 and sh > 0:
                aspect = w / h
                if w > sw:
                    w = sw
                    h = int(w / aspect)
                if h > sh:
                    h = sh
                    w = int(h * aspect)
                frame = cv2.resize(frame, (w, h))

            from PIL import Image, ImageTk

            image = Image.fromarray(frame)
            photo = ImageTk.PhotoImage(image=image)

            try:
                self.frame_queue.put(photo, block=False)
            except queue.Full:
                pass

            time.sleep(1 / 30)  # 30fps 