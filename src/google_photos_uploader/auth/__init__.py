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
            creds = Credentials.from_authorized_user_info(
                json.loads(TOKEN_FILE.read_text()), SCOPES)
        except Exception as e:
            logger.error(f"トークンファイルの読み込みに失敗: {e}")
    
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
                        logger.warning(f"ローカルサーバ方式に失敗: {e}. QR方式にフォールバックします。")
                        creds = None
                
                # GUI が無い、またはブラウザ方式に失敗した場合は QR コード方式
                if creds is None:
                    auth_url, _ = flow.authorization_url(
                        prompt='consent',
                        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
                    )
                    
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(auth_url)
                    qr.make(fit=True)
                    qr_image = qr.make_image(fill_color="black", back_color="white")
                    qr_path = CREDENTIALS_DIR / 'auth_qr.png'
                    qr_image.save(qr_path)
                    print(f"\nQRコードを保存しました: {qr_path}")
                    print("このQRコードをスキャンして認証を完了してください。")
                    print("ブラウザが開いたら、表示される認証コードをこの端末に入力してください。\n")
                    code = input("認証コード: ")
                    flow.fetch_token(code=code)
                    creds = flow.credentials
                
            except Exception as e:
                logger.error(f"新規認証に失敗: {e}")
                return None
        
        # トークンを保存
        try:
            CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(creds.to_json())
        except Exception as e:
            logger.error(f"トークンの保存に失敗: {e}")
            # トークン保存に失敗しても認証情報は返す
    
    return creds
