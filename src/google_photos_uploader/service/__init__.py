import json
import logging
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional, Union

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from ..auth import SCOPES

logger = logging.getLogger(__name__)

# Google Photos APIのエンドポイント
API_BASE_URL = 'https://photoslibrary.googleapis.com/v1'

# --------------------------------------------------
# 内部ヘルパー: アクセストークンの自動リフレッシュ
# --------------------------------------------------

def _ensure_valid_credentials(creds: Credentials) -> None:
    """必要に応じてアクセストークンをリフレッシュする

    Args:
        creds: google.oauth2.credentials.Credentials オブジェクト
    """
    try:
        if creds and (not creds.valid or creds.expired):
            if creds.refresh_token:
                creds.refresh(Request())
    except Exception as e:
        # リフレッシュ失敗時でも後続で 401 を検知できるようにログのみ
        logger.error(f"アクセストークンのリフレッシュに失敗: {e}")

def get_mime_type(file_path: Union[str, Path]) -> str:
    """ファイルのMIMEタイプを取得

    Args:
        file_path: ファイルパス

    Returns:
        str: MIMEタイプ
    """
    mime_type, _ = mimetypes.guess_type(str(file_path))
    return mime_type or 'application/octet-stream'

def upload_media(file_path: Union[str, Path], creds: Credentials, token_only: bool = False) -> Optional[Union[bool, str]]:
    """メディアファイルをアップロード

    Args:
        file_path: メディアファイルのパス
        creds: 認証情報
        token_only: Trueの場合、アップロードトークンのみを返す

    Returns:
        token_only=Falseの場合はアップロード成功の有無(bool)
        token_only=Trueの場合はアップロードトークン(str)
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        logger.error(f"ファイルが見つかりません: {file_path}")
        return None if token_only else False
    
    try:
        # ---------- A. トークン有効性チェック ----------
        _ensure_valid_credentials(creds)

        # ファイルのMIMEタイプを推定
        mime_type = get_mime_type(file_path)
        
        # アップロードリクエストのヘッダーを設定
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/octet-stream',
            'X-Goog-Upload-Content-Type': mime_type,
            'X-Goog-Upload-Protocol': 'raw',
        }
        
        # ファイルをバイナリモードで開く
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        # アップロードリクエスト
        logger.info(f"ファイルバイトをアップロード中: {file_path}")
        response = requests.post(API_BASE_URL + '/uploads', headers=headers, data=file_data)
        
        if response.status_code == 200:
            upload_token = response.text
            logger.info(f"アップロードトークン取得: {upload_token[:10]}...")
            
            if token_only:
                return upload_token
            
            # メディアアイテムの作成
            return create_media_item(upload_token, file_path.name, creds)
        else:
            logger.error(f"アップロード失敗: {response.status_code} - {response.text}")
            return None if token_only else False
    
    except Exception as e:
        logger.error(f"アップロード中にエラーが発生: {e}")
        return None if token_only else False

def create_media_item(upload_token: str, file_name: str, creds: Credentials, album_name: Optional[str] = None) -> bool:
    """メディアアイテムを作成

    Args:
        upload_token: アップロードトークン
        file_name: ファイル名
        creds: 認証情報
        album_name: アルバム名（オプション）

    Returns:
        bool: 成功した場合はTrue
    """
    try:
        _ensure_valid_credentials(creds)
        # リクエストヘッダーを設定
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json'
        }
        
        # リクエスト本文を作成
        request_body = {
            'newMediaItem': {
                'simpleMediaItem': {
                    'uploadToken': upload_token,
                    'fileName': file_name  # オリジナルのファイル名を保持
                }
            }
        }
        
        # アルバムIDを指定（アルバム名がある場合）
        if album_name:
            album_id = get_or_create_album(album_name, creds)
            if album_id:
                request_body['albumId'] = album_id
        
        # メディアアイテム作成リクエストを送信
        logger.info(f"メディアアイテムを作成中: {file_name}")
        response = requests.post(API_BASE_URL + '/mediaItems', headers=headers, json=request_body)
        
        if response.status_code == 200:
            logger.info(f"メディアアイテム作成成功: {file_name}")
            return True
        else:
            logger.error(f"メディアアイテム作成失敗: {response.status_code} - {response.text}")
            return False
    
    except Exception as e:
        logger.error(f"メディアアイテム作成中にエラーが発生: {e}")
        return False

def get_or_create_album(album_name: str, creds: Credentials) -> Optional[str]:
    """アルバムを取得または作成

    Args:
        album_name: アルバム名
        creds: 認証情報

    Returns:
        Optional[str]: アルバムID。失敗した場合はNone
    """
    try:
        _ensure_valid_credentials(creds)
        # 既存のアルバムを検索
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json'
        }
        
        # アルバム一覧を取得
        response = requests.get(API_BASE_URL + '/albums', headers=headers)
        
        if response.status_code == 200:
            albums = response.json().get('albums', [])
            
            # 同名のアルバムを探す
            for album in albums:
                if album['title'] == album_name:
                    logger.info(f"既存のアルバムを使用: {album_name}")
                    return album['id']
        
        # アルバムが存在しない場合は新規作成
        create_response = requests.post(
            API_BASE_URL + '/albums',
            headers=headers,
            json={'album': {'title': album_name}}
        )
        
        if create_response.status_code == 200:
            album_id = create_response.json()['id']
            logger.info(f"新規アルバムを作成: {album_name}")
            return album_id
        else:
            logger.error(f"アルバム作成失敗: {create_response.status_code} - {create_response.text}")
            return None
    
    except Exception as e:
        logger.error(f"アルバム操作中にエラーが発生: {e}")
        return None

def batch_create_media_items(tokens: List[str], album_name: Optional[str], creds: Credentials) -> Dict[str, List[str]]:
    """複数のメディアアイテムをバッチで作成

    Args:
        tokens: アップロードトークンのリスト
        album_name: アルバム名（オプション）
        creds: 認証情報

    Returns:
        Dict[str, List[str]]: 成功と失敗したトークンのリスト
    """
    if not tokens:
        logger.error("アップロードトークンが指定されていません")
        return {"success": [], "failed": []}
    
    try:
        # A. トークン有効性チェック
        _ensure_valid_credentials(creds)

        # リクエストヘッダーを設定
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json'
        }
        
        # リクエスト本文を作成
        request_body = {
            'newMediaItems': []
        }
        
        # --------------------------------------------------
        # トークンとファイル名の対応付け
        # tokens は以下いずれかの形式を許容する
        # 1. ["uploadToken1", "uploadToken2", ...]
        # 2. [("uploadToken1", "fileName1.jpg"), ("uploadToken2", "fileName2.png"), ...]
        # 3. [{"token": "uploadToken1", "fileName": "fileName1.jpg"}, ...]
        #   バックワードコンパチのため、従来どおりトークンのみのリストも受け付ける。

        def _extract_pair(item):
            """内部ヘルパー: item から (token, file_name) タプルを取り出す"""
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                return item[0], item[1]
            if isinstance(item, dict):
                return item.get('token') or item.get('uploadToken'), item.get('fileName') or item.get('file_name')
            # 旧形式: トークンのみ
            return item, None

        tokens_only: List[str] = []  # トークン文字列のみを格納

        for elem in tokens:
            token, fname = _extract_pair(elem)
            if not token:
                # token が取得できない場合はスキップ
                logger.warning("トークンが解析できませんでした。スキップします")
                continue

            tokens_only.append(token)

            item = {
                'simpleMediaItem': {
                    'uploadToken': token
                }
            }
            # ファイル名が指定されている場合のみ fileName を付与
            if fname:
                item['simpleMediaItem']['fileName'] = fname
            request_body['newMediaItems'].append(item)
        
        # アルバムIDを指定（アルバム名がある場合）
        if album_name:
            album_id = get_or_create_album(album_name, creds)
            if album_id:
                request_body['albumId'] = album_id
        
        # バッチ作成リクエストを送信
        logger.info(f"{len(tokens_only)}個のメディアアイテムをバッチ作成中")
        response = requests.post(API_BASE_URL + '/mediaItems:batchCreate', headers=headers, json=request_body)
        
        if response.status_code == 200:
            response_data = response.json()
            
            # 結果をパース
            success_tokens = []
            failed_tokens = []
            
            for result, token in zip(response_data.get('newMediaItemResults', []), tokens_only):
                status = result.get('status', {})
                # 成功判定: status.code が 0 または 'mediaItem' キーが存在
                is_success = False
                if 'mediaItem' in result:
                    is_success = True
                else:
                    code = status.get('code')
                    # 重複などで既に存在する場合はエラーコード 9 または 10 で返ることがある
                    if code in (6, 9, 10):  # ALREADY_EXISTS=6, PERMISSION_DENIED=7 etc.
                        if 'already' in status.get('message', '').lower():
                            is_success = True
                    elif code == 0:
                        is_success = True

                if is_success:
                    success_tokens.append(token)
                else:
                    logger.warning(f"アイテム作成失敗: {status.get('message', 'UNKNOWN')}")
                    failed_tokens.append(token)
            
            logger.info(f"バッチ作成完了: 成功={len(success_tokens)}, 失敗={len(failed_tokens)}")
            return {
                "success": success_tokens,
                "failed": failed_tokens
            }
        else:
            logger.error(f"バッチ作成リクエスト失敗: {response.status_code} - {response.text}")
            return {"success": [], "failed": tokens_only}
    
    except Exception as e:
        logger.error(f"バッチ作成中にエラーが発生: {e}")
        return {"success": [], "failed": tokens_only}
