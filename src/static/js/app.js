// ログを定期的に更新する関数
async function updateLog() {
    try {
        const response = await fetch(buildLogUrl('/get_log'));
        const data = await response.json();
        const logElement = document.getElementById('log');
        logElement.innerHTML = data.logs.map(log => `<div class="log-entry">${log}</div>`).join('');
        logElement.scrollTop = logElement.scrollHeight; // 最新のログまで自動スクロール
    } catch (error) {
        console.error('ログの取得に失敗しました:', error);
    }
}

// // コンソールログを定期的に更新する関数
// async function updateConsoleLog() {
//     try {
//         const response = await fetch(buildLogUrl('/get_console_log'));
//         const data = await response.json();
//         const consoleLogElement = document.getElementById('console-log');
//         consoleLogElement.innerHTML = data.logs.join('\n');
//         consoleLogElement.scrollTop = consoleLogElement.scrollHeight; // 最新のログまで自動スクロール
//     } catch (error) {
//         console.error('コンソールログの取得に失敗しました:', error);
//     }
// }

// フィルタ状態を管理
let filterDisabled = false;

// フィルタ切替ボタンのイベントリスナー
document.getElementById('toggle_filter').addEventListener('click', () => {
    filterDisabled = !filterDisabled;
    // ボタンのラベルを更新
    document.getElementById('toggle_filter').textContent = filterDisabled ? 'フィルタ有効' : 'フィルタ解除';
    // すぐにログをリフレッシュ
    updateLog();
    // updateConsoleLog();
});

function buildLogUrl(baseUrl) {
    return filterDisabled ? `${baseUrl}?all=true` : baseUrl;
}

// 5秒ごとにログを更新
setInterval(updateLog, 5000);
// 5秒ごとにコンソールログも更新
// setInterval(updateConsoleLog, 5000);

// ページ読み込み時に初期状態を設定
document.addEventListener('DOMContentLoaded', function () {
    checkProcessStatus();
    updateLog(); // 初期ログを表示
    // updateConsoleLog(); // 初期コンソールログを表示
});

// タブ切り替え
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        // タブのアクティブ状態を切り替え
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        // タブコンテンツの表示を切り替え
        const tabName = tab.getAttribute('data-tab');
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        document.getElementById(`${tabName}-tab`).classList.add('active');

        // ステータスをチェック
        checkProcessStatus();
    });
});

// プロセスのステータスをチェックする関数
async function checkProcessStatus() {
    try {
        const response = await fetch('/check_status');
        const data = await response.json();

        // アップロードとスライドショーのボタンを状態に応じて有効/無効化
        const uploadRunning = data.uploader_running;
        const slideshowRunning = data.slideshow_running;

        // 起動ボタンはどちらかが動いていれば無効化
        document.getElementById('start_upload').disabled = uploadRunning || slideshowRunning;
        document.getElementById('start_slideshow').disabled = uploadRunning || slideshowRunning;

        // 停止ボタンはどちらかが動いていれば有効化
        const stopEnabled = uploadRunning || slideshowRunning;
        document.getElementById('stop_upload').disabled = !stopEnabled;
        document.getElementById('stop_slideshow').disabled = !stopEnabled;

        // ステータスメッセージを更新
        if (uploadRunning) {
            document.getElementById('status').textContent = 'Uploading...';
        } else if (slideshowRunning) {
            document.getElementById('status').textContent = 'Slideshow is running';
        } else {
            document.getElementById('status').textContent = 'Ready';
        }
        console.debug('checkProcessStatus:', { uploadRunning, slideshowRunning });
    } catch (error) {
        console.error('ステータスの取得に失敗しました:', error);
    }
}

// 定期的にプロセスのステータスをチェック
setInterval(checkProcessStatus, 5000);

document.getElementById('start_upload').addEventListener('click', async () => {
    const data = {
        album_name: document.getElementById('album_name').value,
        fullscreen: document.getElementById('fullscreen').checked,
        slideshow_interval: parseInt(document.getElementById('slideshow_interval').value),
        random: document.getElementById('random').checked,
        bgm: document.getElementById('bgm').checked,
        // Upload & Play ボタンでは必ずスライドショーを起動する
        slideshow: true,
        no_pending: true
    };

    try {
        const response = await fetch('/start_upload', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();
        document.getElementById('status').textContent = result.message;

        // ステータスを更新
        checkProcessStatus();
    } catch (error) {
        document.getElementById('status').textContent = 'エラーが発生しました: ' + error;
    }
});

document.getElementById('stop_upload').addEventListener('click', async () => {
    try {
        // アップロード停止
        const uploadResp = await fetch('/stop_upload', { method: 'POST' });
        const uploadResult = await uploadResp.json();

        console.debug('stop_upload response:', uploadResult);

        // スライドショーも停止（実行中でなくてもOK）
        const slideResp = await fetch('/stop_slideshow', { method: 'POST' });
        const slideResult = await slideResp.json();

        console.debug('stop_slideshow response:', slideResult);

        // メッセージを表示（どちらか成功メッセージを表示）
        document.getElementById('status').textContent = uploadResult.message || slideResult.message || '停止しました';

        // ステータスを更新
        checkProcessStatus();
    } catch (error) {
        document.getElementById('status').textContent = 'エラーが発生しました: ' + error;
        console.error('停止中にエラー:', error);
    }
});

document.getElementById('unmount_sd').addEventListener('click', async () => {
    try {
        const response = await fetch('/unmount_sd', {
            method: 'POST'
        });

        const result = await response.json();
        document.getElementById('status').textContent = result.message;
    } catch (error) {
        document.getElementById('status').textContent = 'エラーが発生しました: ' + error;
    }
});

// アルバム一覧を取得する関数
async function fetchAlbums() {
    try {
        document.getElementById('status').textContent = 'アルバム一覧を取得中...';
        document.getElementById('fetch_albums').disabled = true;

        const response = await fetch('/get_albums');
        const albums = await response.json();

        if (albums.error) {
            document.getElementById('status').textContent = `エラー: ${albums.error}`;
            return;
        }

        // セレクトボックスをクリア
        const selectElement = document.getElementById('slideshow_album_select');
        selectElement.innerHTML = '<option value="">アルバムを選択してください</option>';

        // アルバムを追加
        albums.sort((a, b) => a.title.localeCompare(b.title)); // アルバム名でソート
        albums.forEach(album => {
            const option = document.createElement('option');
            option.value = album.title;
            option.textContent = `${album.title} (${album.itemCount}枚)`;
            selectElement.appendChild(option);
        });

        document.getElementById('status').textContent = `${albums.length}個のアルバムを取得しました`;
    } catch (error) {
        document.getElementById('status').textContent = `アルバム一覧取得中にエラー: ${error}`;
    } finally {
        document.getElementById('fetch_albums').disabled = false;
    }
}

// アルバム一覧取得ボタンのイベントリスナー
document.getElementById('fetch_albums').addEventListener('click', fetchAlbums);

// アルバム選択時のイベントリスナー
document.getElementById('slideshow_album_select').addEventListener('change', function () {
    const selectedAlbum = this.value;
    if (selectedAlbum) {
        document.getElementById('slideshow_album_name').value = selectedAlbum;
    }
});

document.getElementById('start_slideshow').addEventListener('click', async () => {
    const albumName = document.getElementById('slideshow_album_name').value.trim();
    if (!albumName) {
        document.getElementById('status').textContent = 'アルバム名を入力または選択してください';
        return;
    }

    const data = {
        album_name: albumName,
        interval: parseInt(document.getElementById('slideshow_only_interval').value),
        fullscreen: document.getElementById('slideshow_fullscreen').checked,
        random: document.getElementById('slideshow_random').checked,
        bgm: document.getElementById('slideshow_bgm').checked,
        verbose: document.getElementById('slideshow_verbose').checked
    };

    try {
        document.getElementById('status').textContent = 'スライドショーを起動中...';

        const response = await fetch('/start_slideshow', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();
        document.getElementById('status').textContent = result.message;

        // ステータスを更新
        checkProcessStatus();
    } catch (error) {
        document.getElementById('status').textContent = 'エラーが発生しました: ' + error;
    }
});

document.getElementById('stop_slideshow').addEventListener('click', async () => {
    try {
        // まずスライドショー停止
        const slideResp = await fetch('/stop_slideshow', { method: 'POST' });
        const slideResult = await slideResp.json();
        console.debug('stop_slideshow response:', slideResult);

        // アップローダーも停止（実行中でなくてもOK）
        const upResp = await fetch('/stop_upload', { method: 'POST' });
        const upResult = await upResp.json();
        console.debug('stop_upload response:', upResult);

        document.getElementById('status').textContent = slideResult.message || upResult.message || '停止しました';

        // ステータスを更新
        checkProcessStatus();
    } catch (error) {
        document.getElementById('status').textContent = 'エラーが発生しました: ' + error;
        console.error('停止中にエラー:', error);
    }
}); 