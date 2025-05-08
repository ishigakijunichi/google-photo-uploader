from flask import Flask, render_template, request, jsonify
import subprocess
import os
import signal
from pathlib import Path
import logging
import platform
import atexit

app = Flask(__name__)

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(Path.home() / '.google_photos_uploader' / 'app.log'),
        logging.NullHandler()  # 標準出力への出力を無効化
    ]
)
logger = logging.getLogger(__name__)

def cleanup():
    """アプリケーション終了時に実行される関数"""
    try:
        # auto_uploader.pyのプロセスを停止
        subprocess.run(['pkill', '-f', 'python.*auto_uploader.py'], check=False)
        # slideshow.pyのプロセスを停止
        subprocess.run(['pkill', '-f', 'python.*slideshow.py'], check=False)
        logger.info('全プロセスを停止しました')
    except Exception as e:
        logger.error(f'プロセス停止中にエラーが発生しました: {e}')

# 終了時の処理を登録
atexit.register(cleanup)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_upload', methods=['POST'])
def start_upload():
    try:
        data = request.get_json()
        album_name = data.get('album_name', 'Photo Uploader')
        watch = data.get('watch', True)
        interval = data.get('interval', 60)
        slideshow = data.get('slideshow', True)
        fullscreen = data.get('fullscreen', True)
        all_photos = data.get('all_photos', False)
        current_only = data.get('current_only', False)
        slideshow_interval = data.get('slideshow_interval', 5)
        random = data.get('random', False)
        no_pending = data.get('no_pending', False)
        verbose = data.get('verbose', False)
        
        # auto_uploader.pyのパスを取得
        uploader_script = Path(__file__).parent / "auto_uploader.py"
        
        # コマンドを構築
        command = ['python3', str(uploader_script)]
        
        # オプションを追加
        if album_name:
            command.extend(['--album', album_name])
        if watch:
            command.append('--watch')
        if interval != 60:  # デフォルト値と異なる場合のみ追加
            command.extend(['--interval', str(interval)])
        if slideshow:
            command.append('--slideshow')
        if not fullscreen:
            command.append('--no-fullscreen')
        if all_photos:
            command.append('--all-photos')
        if current_only:
            command.append('--current-only')
        if slideshow_interval != 5:  # デフォルト値と異なる場合のみ追加
            command.extend(['--slideshow-interval', str(slideshow_interval)])
        if random:
            command.append('--random')
        if no_pending:
            command.append('--no-pending')
        if verbose:
            command.append('--verbose')
        
        # バックグラウンドで実行
        subprocess.Popen(command)
        
        return jsonify({'status': 'success', 'message': '起動中'})
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop_upload', methods=['POST'])
def stop_upload():
    try:
        # 実行中のプロセスを終了
        os.system("pkill -f auto_uploader.py")
        return jsonify({'status': 'success', 'message': '停止しました'})
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/unmount_sd', methods=['POST'])
def unmount_sd():
    try:
        # プラットフォームに応じたアンマウントコマンドを実行
        if platform.system() == 'Darwin':  # macOS
            subprocess.run(['diskutil', 'unmount', '/Volumes/Untitled'], check=True)
            message = 'SDカードをアンマウントしました'
        elif platform.system() == 'Linux':
            # Linuxの場合、ユーザー名を取得
            user = os.environ.get('USER', 'user')
            mount_point = f'/media/{user}/Untitled'
            if not os.path.exists(mount_point):
                mount_point = '/media/Untitled'
            subprocess.run(['umount', mount_point], check=True)
            message = 'SDカードをアンマウントしました'
        elif platform.system() == 'Windows':
            # Windowsの場合は、ドライブレターを探してアンマウント
            import win32api
            drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
            for drive in drives:
                try:
                    volume_name = win32api.GetVolumeInformation(drive)[0]
                    if volume_name == 'Untitled':
                        subprocess.run(['eject', drive], check=True)
                        message = 'SDカードをアンマウントしました'
                        break
                except:
                    continue
            else:
                message = 'SDカードが見つかりません'
        else:
            message = 'このプラットフォームではSDカードのアンマウントをサポートしていません'
        
        return jsonify({'message': message})
    except subprocess.CalledProcessError as e:
        return jsonify({'message': f'アンマウント中にエラーが発生しました: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'message': f'予期せぬエラーが発生しました: {str(e)}'}), 500

@app.route('/get_log')
def get_log():
    try:
        log_file = Path.home() / '.google_photos_uploader' / 'uploader.log'
        if not log_file.exists():
            return jsonify({'logs': []})
        
        # 最新の100行を取得
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = f.readlines()[-100:]
        
        # 空行を削除し、各行の末尾の改行を削除
        logs = [log.strip() for log in logs if log.strip()]
        
        return jsonify({'logs': logs})
    except Exception as e:
        logger.error(f"ログの取得中にエラーが発生しました: {e}")
        return jsonify({'logs': [f"ログの取得中にエラーが発生しました: {str(e)}"]})

# Flaskのアクセスログを無効化
logging.getLogger('werkzeug').setLevel(logging.ERROR)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False) 