1. 概要

Raspberry Pi 5 (常時GPUモードで起動）に SD カードを挿すと
1.未アップロードの写真を検出
2.Google Photos にアップロード
3.同時にスライドショー表示
を自動で行うツールです。フォルダ名 DCIM/ を前提としています。

⸻

2. ディレクトリ構成

bgm/                  効果音 MP3  
bgm_sample/           サンプル音源  
src/                  本体コード  
tests/                pytest テスト  
credential.json.example  Google OAuth 認証情報の雛形  
google-photo-uploader.service  systemd サービス定義


⸻

3. セットアップ（開発環境）

# 依存ライブラリ
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # pytest 含む

# 認証ファイルを配置
cp credential.json.example credential.json
export GOOGLE_PHOTOS_CREDENTIALS=$(pwd)/credential.json

Raspberry Pi への常駐設定（任意）

sudo cp google-photo-uploader.service /etc/systemd/system/
sudo systemctl enable --now google-photo-uploader


⸻

4. テスト

pytest -q

•すべてグリーンになるまでコミット不可。

⸻

5. 実行例（手動）

python -m google_photo_uploader /media/pi/DCIM


⸻

6. コーディング規約

項目方針
フォーマッタBlack & isort 自動整形必須
Linterruff (flake8 互換) を推奨
変数/関数名snake_case
ログlogger = logging.getLogger(__name__)


⸻

7. コミット / PR ルール
1.Conventional Commits を使用
例: feat(uploader): SDカード自動検出を追加
2.PR には以下を必ず記載
•目的 / 変更点
•手動テスト手順
•pytest 結果
3.main 直コミット禁止。必ず PR → Review → Merge。

⸻

8. よくある落とし穴

症状 / 罠対処
認証失敗 (invalid_grant)credential.json と token.json のペアが不整合。両方削除して再認証。
写真が検出されないSD カード直下に DCIM/ が無い。
Wayland でスライドショーが映らない Pi 5 では Full KMS (kms/drm) GPU を常時有効にすれば Wayland でも表示可能。映らない場合は X11 (legacy) へ切替して確認。サービスが起動しないsystemd に登録後 sudo systemctl daemon-reload 済みか確認。


⸻

9. Codex への指示（このファイルを読む AI へ）
•前提コマンド は §3 のシェルをそのまま実行すること。
•変更を加えたら 必ず pytest を通してから PR を作成。
•不明点・追加の暗黙仕様があれば PR コメントで質問すること。

