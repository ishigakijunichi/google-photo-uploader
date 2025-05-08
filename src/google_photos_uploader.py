#!/usr/bin/env python3

import os
import json
import argparse
import mimetypes
import requests
import logging
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# APIのスコープを定義
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]

# Google Photos APIのエンドポイント
API_BASE_URL = 'https://photoslibrary.googleapis.com/v1'

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

def upload_media(file_path, creds):
    """メディアファイルをアップロードする"""
    # ファイルのMIMEタイプを取得
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = 'application/octet-stream'
    
    # アップロードURLを設定
    upload_url = f"{API_BASE_URL}/uploads"
    
    # アップロードトークンを取得
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/octet-stream',
        'X-Goog-Upload-Content-Type': mime_type,
        'X-Goog-Upload-Protocol': 'raw'
    }
    
    try:
        with open(file_path, 'rb') as file:
            file_content = file.read()
            response = requests.post(upload_url, headers=headers, data=file_content)
            
        if response.status_code != 200:
            print(f"ファイルアップロード中にエラーが発生しました: {response.text}")
            return None
            
        upload_token = response.content.decode('utf-8')
        
        # メディアアイテムを作成
        create_url = f"{API_BASE_URL}/mediaItems:batchCreate"
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'newMediaItems': [
                {
                    'simpleMediaItem': {
                        'uploadToken': upload_token
                    }
                }
            ]
        }
        
        response = requests.post(create_url, headers=headers, data=json.dumps(data))
        
        if response.status_code != 200:
            print(f"メディアアイテム作成中にエラーが発生しました: {response.text}")
            return None
            
        response_data = response.json()
        return response_data.get('newMediaItemResults')[0].get('mediaItem').get('id')
    
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        return None

def get_albums(creds):
    """アルバムのリストを取得する"""
    url = f"{API_BASE_URL}/albums"
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"アルバムリスト取得中にエラーが発生しました: {response.text}")
        return []
        
    return response.json().get('albums', [])

def create_album(album_name, creds):
    """新しいアルバムを作成する"""
    url = f"{API_BASE_URL}/albums"
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'album': {'title': album_name}
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code != 200:
        print(f"アルバム作成中にエラーが発生しました: {response.text}")
        return None
        
    return response.json().get('id')

def add_to_album(album_id, media_id, creds):
    """メディアをアルバムに追加する"""
    url = f"{API_BASE_URL}/albums/{album_id}:batchAddMediaItems"
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'mediaItemIds': [media_id]
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(data))
    
    # 詳細なレスポンスを記録
    if response.status_code != 200:
        logger.error(f"アルバムへの追加中にエラー発生 (HTTP {response.status_code}): {response.text}")
        # レート制限に関する情報があれば記録
        if 'X-RateLimit-Limit' in response.headers:
            logger.error(f"レート制限情報: Limit={response.headers.get('X-RateLimit-Limit')}, "
                        f"Remaining={response.headers.get('X-RateLimit-Remaining')}, "
                        f"Reset={response.headers.get('X-RateLimit-Reset')}")
    
    return response.status_code == 200

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='Google Photosにファイルをアップロードする')
    parser.add_argument('files', metavar='FILE', type=str, nargs='+',
                        help='アップロードするファイルのパス')
    parser.add_argument('--album', type=str, help='アップロード先のアルバム名（オプション）')
    parser.add_argument('--verbose', action='store_true', help='詳細なログを出力する')
    args = parser.parse_args()
    
    # 詳細ログモードが指定された場合
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("詳細ログモードが有効です")
    
    # 認証
    creds = authenticate()
    if not creds:
        return
    
    # アルバムIDを取得（指定された場合）
    album_id = None
    if args.album:
        try:
            albums = get_albums(creds)
            for album in albums:
                if album.get('title') == args.album:
                    album_id = album.get('id')
                    break
            
            if not album_id:
                logger.info(f"アルバム '{args.album}' が見つかりません。新しく作成します。")
                album_id = create_album(args.album, creds)
                if album_id:
                    logger.debug(f"新しいアルバムが作成されました: ID={album_id}")
                else:
                    logger.error("アルバムの作成に失敗しました")
        except Exception as error:
            logger.error(f"アルバム操作中にエラーが発生しました: {error}")
            return
    
    # ファイルをアップロード
    for file_path in args.files:
        if not os.path.exists(file_path):
            logger.warning(f"ファイルが見つかりません: {file_path}")
            continue
        
        logger.info(f"アップロード中: {file_path}")
        
        # ファイル情報をログに記録
        if args.verbose:
            file_size = os.path.getsize(file_path) / (1024 * 1024)  # MBに変換
            logger.debug(f"ファイル情報: サイズ={file_size:.2f}MB, パス={file_path}")
        
        media_id = upload_media(file_path, creds)
        
        if media_id and album_id:
            logger.debug(f"メディアID: {media_id}, アルバムID: {album_id}")
            if add_to_album(album_id, media_id, creds):
                logger.info(f"ファイル '{file_path}' をアルバム '{args.album}' にアップロードしました")
            else:
                logger.warning(f"ファイル '{file_path}' をアップロードしましたが、アルバムへの追加に失敗しました")
        elif media_id:
            logger.info(f"ファイル '{file_path}' をアップロードしました")
        else:
            logger.error(f"ファイル '{file_path}' のアップロードに失敗しました")

if __name__ == '__main__':
    main()
