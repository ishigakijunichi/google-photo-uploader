from pathlib import Path
import json
import logging
from typing import Optional

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
                creds = flow.run_local_server(port=0)
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
