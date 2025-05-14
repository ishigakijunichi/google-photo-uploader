from pathlib import Path
import json
import logging
from typing import Optional
import os
import socket
import contextlib
import qrcode
import io
import base64
from PIL import Image

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

# APIのスコープを定義
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]

# 認証情報のパス
CREDENTIALS_DIR = Path.home() / '.google_photos_uploader'
TOKEN_FILE = CREDENTIALS_DIR / 'token.json'
CREDENTIALS_FILE = CREDENTIALS_DIR / 'credentials.json'

def get_credentials() -> Optional[Credentials]:
    """Google API認証情報を取得

    Returns:
        Optional[Credentials]: 認証情報。認証に失敗した場合はNone
    """
    creds = None
    
    # 既存のトークンファイルがあるか確認
    if TOKEN_FILE.exists():
        try:
            # 安全にトークンを読み込む
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                token_data = json.load(f)
            
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            logger.info("既存のトークンを読み込みました")
        except json.JSONDecodeError as e:
            logger.error(f"トークンファイルの形式が不正です: {e}")
            # 破損したトークンファイルをバックアップ
            try:
                backup_file = TOKEN_FILE.with_suffix('.json.bak')
                TOKEN_FILE.rename(backup_file)
                logger.info(f"破損したトークンファイルをバックアップしました: {backup_file}")
            except Exception as backup_err:
                logger.error(f"トークンファイルのバックアップに失敗: {backup_err}")
            creds = None
        except Exception as e:
            logger.error(f"トークンファイルの読み込みに失敗: {e}")
            creds = None
    
    # 有効な認証情報がない場合
    if not creds or not creds.valid:
        # リフレッシュトークンがある場合は更新
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error(f"トークンの更新に失敗: {e}")
                creds = None
        
        # リフレッシュに失敗または認証情報がない場合は新規認証
        if not creds:
            if not CREDENTIALS_FILE.exists():
                logger.error(f"credentials.jsonファイルが見つかりません: {CREDENTIALS_FILE}")
                return None
                
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES)
                
                # まず GUI があればブラウザ自動起動の loop-back フローを試みる
                def _has_display() -> bool:
                    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY") or os.getenv("MIR_SOCKET"))

                def _pick_free_port() -> int:
                    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                        s.bind(("", 0))
                        return s.getsockname()[1]

                creds = None  # type: ignore
                if _has_display():
                    try:
                        port = _pick_free_port()
                        creds = flow.run_local_server(
                            host="127.0.0.1",
                            port=port,
                            open_browser=True,
                            prompt="consent",
                            success_message="認証が完了しました。ウィンドウを閉じてください。",
                        )
                        logger.info("ブラウザを使用した認証が完了しました")
                    except Exception as e:
                        logger.error(f"ブラウザ認証に失敗しました: {e}")
                        return None
                else:
                    # GUIがない場合は認証できないので終了
                    logger.error("GUIが見つかりません。認証を続行できません。")
                    return None
                
            except Exception as e:
                logger.error(f"新規認証に失敗: {e}")
                return None
        
        # トークンを保存
        try:
            CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            # to_json()メソッドがない場合は、jsonモジュールを使用してシリアライズ
            try:
                # 最新のGoogle Auth Libraryでのシリアライズ方法を試す
                token_data = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes
                }
                
                # トークンファイルを書き込む前に一時的なファイルを使用し、書き込みが成功したら移動
                temp_token_file = CREDENTIALS_DIR / 'token.json.tmp'
                with open(temp_token_file, 'w', encoding='utf-8') as f:
                    json.dump(token_data, f)
                    
                # 一時ファイルを本来のファイルに置き換え
                temp_token_file.replace(TOKEN_FILE)
                logger.info("トークンを正常に保存しました")
            except Exception as e:
                logger.error(f"トークンのシリアライズに失敗: {e}")
        except Exception as e:
            logger.error(f"トークンの保存に失敗: {e}")
    
    return creds
