# Google Photos Uploader

ローカルのファイルを Google Photos にアップロードするシンプルなコマンドラインツールです。

## 前提条件

- Python 3.6 以上
- Google Cloud プロジェクトでの認証情報の設定

## インストール

1. リポジトリをクローンするか、ダウンロードします:

```
git clone https://github.com/yourusername/google_photos_uploader.git
cd google_photos_uploader
```

2. 依存関係をインストールします:

```
pip install -r requirements.txt
```

## Google Cloud Project の設定

1. [Google Cloud Console](https://console.cloud.google.com/)にアクセスします
2. 新しいプロジェクトを作成するか、既存のプロジェクトを選択します
3. 「API とサービス」 > 「ライブラリ」を選択します
4. 「Photos Library API」を検索し、有効にします
5. 「API とサービス」 > 「認証情報」を選択します
6. 「認証情報を作成」 > 「OAuth クライアント ID」を選択します
7. アプリケーションタイプとして「デスクトップアプリケーション」を選択し、名前を入力します
8. 「作成」をクリックし、クライアント ID とクライアントシークレットが表示されたら「OK」をクリックします
9. 認証情報のリストで、作成したクライアント ID の右側にある「ダウンロード」アイコンをクリックします
10. ダウンロードした JSON ファイル（`client_secret_XXX.json`）を`~/.google_photos_uploader/credentials.json`に保存します

```
mkdir -p ~/.google_photos_uploader
mv ~/Downloads/client_secret_XXX.json ~/.google_photos_uploader/credentials.json
```

## 使い方

### 手動アップロード

#### 単一ファイルのアップロード

```
python src/google_photos_uploader.py /path/to/your/photo.jpg
```

#### 複数ファイルのアップロード

```
python src/google_photos_uploader.py /path/to/photo1.jpg /path/to/photo2.png
```

#### 特定のアルバムにアップロード

```
python src/google_photos_uploader.py --album "休日の写真" /path/to/photo1.jpg /path/to/photo2.jpg
```

指定したアルバムが存在しない場合は、自動的に作成されます。

### 自動アップロード (SD カード)

SD カードがマウントされたときに自動的に写真をアップロードするための機能も提供しています。

#### 追加の依存関係のインストール

自動アップロード機能を使用するには、watchdog ライブラリをインストールする必要があります：

```
pip install watchdog
```

Windows の場合は、pywin32 も必要です：

```
pip install pywin32
```

#### SD カードからの自動アップロード

##### 一度だけ実行する場合

```
python src/auto_uploader.py --album "カメラアップロード"
```

##### ファイルシステムの変更を監視（推奨）

```
python src/auto_uploader.py --watch --album "カメラアップロード"
```

これにより、SD カードが挿入されたときに自動的に検出され、写真がアップロードされます。

##### 定期的なチェック

```
python src/auto_uploader.py --interval 30 --album "カメラアップロード"
```

このコマンドは 30 秒ごとに SD カードをチェックし、見つかった場合は写真をアップロードします。

#### 自動起動の設定

システム起動時に自動的にアップローダーを実行するように設定することができます：

##### macOS

```
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.user.google_photos_uploader.plist << EOL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.google_photos_uploader</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(which python3)</string>
        <string>$(pwd)/src/auto_uploader.py</string>
        <string>--watch</string>
        <string>--album</string>
        <string>カメラアップロード</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOL
launchctl load ~/Library/LaunchAgents/com.user.google_photos_uploader.plist
```

## スライドショー機能

アップロードした写真を使ってスライドショーを表示することができます。

### スライドショーの実行

```
python src/slideshow.py
```

### オプション

```
python src/slideshow.py --interval 3 --random --fullscreen --recent --current --no-pending
```

- `--interval N`: 画像の表示間隔を秒単位で指定（デフォルト: 5 秒）
- `--random`: 画像をランダムな順序で表示
- `--fullscreen`: フルスクリーンモードで表示
- `--recent`: 最近アップロードした写真のみ表示（デフォルトは 24 時間以内）
- `--current`: 現在アップロード中の写真のみ表示
- `--no-pending`: アップロード予定/失敗ファイルを含めない
- `--verbose`: 詳細なログを出力

### 操作方法

- 左クリック / 右矢印キー: 次の画像に進む
- 左矢印キー: 前の画像に戻る
- スペースキー: 再生/一時停止の切り替え
- ESC キー / q キー: スライドショーを終了（フルスクリーンモード時）

## 注意点

- 初回実行時は、ブラウザで Google アカウントの認証を求められます
- 認証情報は`~/.google_photos_uploader/token.json`に保存され、次回以降の実行時に再利用されます
- アップロードされたメディアは Google Photos のライブラリに追加されます
- 自動アップローダーはアップロード済みのファイルを`~/.google_photos_uploader/uploaded_files.txt`に記録し、重複アップロードを防ぎます
