from __future__ import annotations

"""共通スライドショー UI 基底クラス

SlideshowApp / AlbumSlideshowApp が共通で利用する UI ロジック（キーバインド、
再生／一時停止、BGM 管理、フルスクリーン処理など）をまとめたクラス。

このクラスは抽象クラスではないが、以下のメソッドを派生クラスで実装する必要がある。

- next_item(self, event=None):   次のスライドへ進む
- prev_item(self, event=None):   前のスライドへ戻る
- schedule_next_item(self):      次スライドの予約処理（after 登録）

派生クラスでは ``super().__init__(root, ...)`` を呼び出した後、
個別 UI ウィジェットを初期化し、初期表示を行ってください。
"""

import logging
from typing import List, Optional

import tkinter as tk

from google_photos_uploader.utils.media import BackgroundMusicPlayer

logger = logging.getLogger(__name__)


class BaseSlideshowApp:
    """スライドショー共通機能を提供する基底クラス"""

    def __init__(
        self,
        root: tk.Tk,
        *,
        interval: int = 5,
        random_order: bool = False,
        fullscreen: bool = False,
        bgm_files: Optional[List[str]] = None,
    ) -> None:
        # tk root
        self.root = root
        # 表示間隔 (ミリ秒)
        self.interval: int = interval * 1000
        self.random_order: bool = random_order

        # 再生制御
        self.playing: bool = True
        self.after_id: Optional[str] = None

        # BGM
        self.music_player = BackgroundMusicPlayer(bgm_files or [])

        # ウィンドウ設定
        self.root.configure(bg="black")
        if fullscreen:
            self.root.attributes("-fullscreen", True)
            # ESC または q で終了
            self.root.bind("<Escape>", lambda e: self.root.destroy())
            self.root.bind("<q>", lambda e: self.root.destroy())

        # 共通キーバインド／マウスバインド
        self.root.bind("<Button-1>", self.next_item)  # クリックで次へ
        self.root.bind("<Right>", self.next_item)     # → キー
        self.root.bind("<Left>", self.prev_item)       # ← キー
        self.root.bind("<space>", self.toggle_play)    # Space キー

        # BGM 監視ループ開始
        self.root.after(1000, self._update_music_loop)

    # ---------------------------------------------------------------------
    # 以下、派生クラスでオーバーライド／使用するメソッド
    # ---------------------------------------------------------------------

    def next_item(self, event=None):  # noqa: D401,E501
        """次のスライドへ。派生クラスで実装してください"""
        raise NotImplementedError

    def prev_item(self, event=None):  # noqa: D401,E501
        """前のスライドへ。派生クラスで実装してください"""
        raise NotImplementedError

    def schedule_next_item(self):  # noqa: D401,E501
        """次スライドの予約処理を行う。派生クラスで実装してください"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 共通ロジック
    # ------------------------------------------------------------------

    def toggle_play(self, event=None):
        """スペースキー等で再生 / 一時停止を切り替え"""
        self.playing = not self.playing
        if self.playing:
            if self.music_player and self.music_player.enabled:
                self.music_player.resume()
            # 再スケジュール
            try:
                self.schedule_next_item()
            except NotImplementedError:
                logger.debug("schedule_next_item not implemented in subclass")
        else:
            if self.music_player and self.music_player.enabled:
                self.music_player.pause()
            # 予約キャンセル
            if self.after_id:
                self.root.after_cancel(self.after_id)
                self.after_id = None

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------

    def _update_music_loop(self):
        """BGM の再生状況を監視しループする内部メソッド"""
        if self.music_player and self.music_player.enabled:
            self.music_player.update()
        self.root.after(1000, self._update_music_loop) 