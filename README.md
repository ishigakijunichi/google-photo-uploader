# Google Photos Uploader

SD カードの写真を Google Photos にアップロードしながら、スライドショーで表示するツールです。
- TV などのディスプレイに接続した Raspberry Pi での動作を前提にしています。\*Rasberry Pi 5 で動作確認済み
- 写真が格納されたフォルダ名が**DCIM**であることを前提にしています。


## 主な機能

### 1. 自動アップロード機能

SD カードが挿入されると自動的に写真を検出し、Google Photos にアップロードします。

#### 動作の流れ

1. SD カードに未アップロードの写真が存在するか確認
2. アップロード済み写真のログと比較して、新規写真を特定
3. 新規写真を Google Photos にアップロード
4. アップロード完了後、ログを更新

#### ローカルデータの保存

- アップロード済み写真のログ: `~/.google_photos_uploader/uploaded_files.txt`
- 認証情報: `~/.google_photos_uploader/token.json`
- アップロードされた写真のサムネイル: `~/.google_photos_uploader/thumbnails/`
- アップロード状態のログ: `~/.google_photos_uploader/upload_logs/`

### 2. スライドショー機能

アップロード中の写真をリアルタイムでスライドショー表示します。

#### 動作の流れ

1. 新規写真が検出された場合：

   - 新規写真をスライドショーで表示
   - アップロードと並行して表示を継続
   - アップロード完了後も表示を継続

2. 新規写真がない場合：

   - SD カード内の最新 100 枚の写真をスライドショーで表示

3. 写真が存在しない場合：
   - 写真がない旨のメッセージを表示



#### BGM の設定

BGM を使用するには、以下のいずれかの方法を選択できます:

1. BGM セットアップスクリプトを使用する（推奨）

   ```
   # BGMフォルダを作成してサンプル音楽をダウンロード
   python src/setup_bgm.py --sample

   # 自分の音楽フォルダから音楽ファイルをコピー
   python src/setup_bgm.py --copy-from ~/Music/MyFavorite
   ```

2. 手動でプロジェクトルートに`bgm`フォルダを作成し、その中に音楽ファイルを配置する

   ```
   mkdir -p bgm
   cp /path/to/your/music/*.mp3 bgm/
   ```

3. コマンドラインで直接 BGM フォルダやファイルを指定する

   ```
   python src/slideshow.py --bgm /path/to/music/folder /path/to/another/music.mp3
   ```

4. ランダム再生を有効にする
   ```
   python src/slideshow.py --bgm bgm/ --random-bgm
   ```

対応音楽形式: MP3, WAV, OGG, FLAC, AAC, M4A

#### 操作方法

- 左クリック / 右矢印キー: 次の画像に進む
- 左矢印キー: 前の画像に戻る
- スペースキー: 再生/一時停止の切り替え
- ESC キー / q キー: スライドショーを終了

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

## 注意点

- 初回実行時は、ブラウザで Google アカウントの認証を求められます
- 認証情報は`~/.google_photos_uploader/token.json`に保存され、次回以降の実行時に再利用されます
- アップロードされたメディアは Google Photos のライブラリに追加されます
- 自動アップローダーはアップロード済みのファイルを`~/.google_photos_uploader/uploaded_files.txt`に記録し、重複アップロードを防ぎます
- BGM 機能を使用する場合は、`bgm`ディレクトリに音楽ファイルを配置してください
- ローカルに保存されるデータは、アプリケーションの再インストール時や手動で削除しない限り保持されます
- ローカルデータのバックアップを取ることをお勧めします
