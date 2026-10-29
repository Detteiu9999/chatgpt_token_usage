# Codex Usage（Windows常駐ウィジェット）

ChatGPTアカウントで利用するCodexの **5時間枠・1週間枠の残り割合** と、
**「利用上限のリセット」の保有残数** を常時表示します。
使用済み割合・回復予定日時、取得できる場合はリセット権の最短有効期限も表示します。

## 初回ログイン

1. `起動.cmd` または `CodexUsage.exe` を起動します。
2. **「接続 / ログイン」** を押します。
3. Windowsの**既定ブラウザー**でCodex公式のログイン・許可画面が開きます。
   いつもCodexで使用しているChatGPTアカウントで認証してください。
4. 認証が完了すると自動で使用量を取得します。ブラウザーのタブは閉じて構いません。

ログインは同梱の公式Codex CLI（0.165.0）のOAuth処理を使用します。
認証情報はWindows資格情報マネージャーに保存し、アクセストークンの更新もCodexが行います。
アプリ再起動後は保存済みの認証を使用します。サービス側で認証を失効された場合は再認証が必要です。

ログイン中はアプリからの使用量取得を停止し、公式コンポーネントの完了通知を待ちます。
専用Edgeの起動・DevTools接続・JavaScript注入・Cookieコピーは行いません。
以前のバージョンから更新した場合は、この公式認証を一度行ってください。

## 操作

- ヘッダーをドラッグ：位置を移動・保存
- タイトルバーの最小化、ウィジェットの `—`、`Esc`、`×`：タスクバーに残して最小化
- タスクバーのCodex Usageをクリック：復帰
- **`Ctrl + Alt + U`：最小化・通知領域への格納から再表示**（他アプリとのキー競合時を除く）
- メニューの「通知領域に格納」：通知領域のみで常駐
- 通知領域アイコンをダブルクリック：再表示
- `⋯` または右クリック：最前面、自動起動、更新間隔（30/60/120/300秒）、終了
- `接続 / ログイン`：通常のブラウザーで公式認証を開始・再表示
- `使用状況 ↗`：通常のブラウザーでChatGPTの使用状況ページを開く
- 同じアプリを再起動：既存ウィジェットを再表示（二重起動しません）

初期設定は **最前面表示、60秒ごとの自動更新** です。
通信エラー時は前回値と最終取得時刻を表示して自動再試行します。
取得できない項目は `—` と表示し、ゼロとして扱いません。
回復予定時刻を過ぎても、再取得成功までは残量を100%に書き換えません。

## インストール・Windows自動起動

`dist` 内の **`CodexUsage.exe` と `codex.exe` を同じフォルダーに置いて**実行します。

```powershell
.\dist\CodexUsage.exe --install
& "$env:LOCALAPPDATA\CodexUsage\bin\CodexUsage.exe"
```

- 本体：`%LOCALAPPDATA%\CodexUsage\bin\CodexUsage.exe`
- 公式コンポーネント：`%LOCALAPPDATA%\CodexUsage\bin\codex.exe`
- 自動起動：`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` の `CodexUsage`
- 自動起動を解除：メニューのチェックをオフ、または `自動起動を解除.cmd`
- 起動中のアプリを終了：`CodexUsage.exe --quit`

現在のWindowsユーザーにインストールするため、管理者権限は不要です。

## データと取得方法

- 設定：`%LOCALAPPDATA%\CodexUsage\settings.json`
- 公式Codexの専用ホーム：`%LOCALAPPDATA%\CodexUsage\Auth`
- OAuth認証情報：Windows資格情報マネージャー（専用ホーム単位）
- 障害ログ：`%LOCALAPPDATA%\CodexUsage\app.log`（ローテーションあり）

公式Codexの `app-server --stdio` を子プロセスとして起動し、次のアカウントAPIを使用します。

- `account/login/start` / `account/login/completed`：通常のブラウザーでの公式OAuth
- `account/read`：保存済み認証の確認
- `account/rateLimits/read`：使用枠・リセット権の残数

会話・タスク・モデル推論は開始しません。パスワード・トークン・認証URLをアプリのログに出力しません。
表示する%はCodex側の利用上限の割合です。
公式APIの型定義：<https://github.com/openai/codex/tree/main/codex-rs/app-server-protocol>

## 開発・ビルド

Windows 10/11向け。Windows 11、Python 3.12で動作確認。
公式コンポーネントの取得用にNode.js/npmを使用します。

まず `runtime` フォルダーで `npm ci --ignore-scripts` を実行します。
次にプロジェクトルートで以下を実行してください。

```powershell
python -m pip install -r requirements.txt
python app.py
python -m unittest discover -s tests -v
python tools/check_ui.py
python tools/check_login.py
python tools/check_codex.py
python -m pip install pyinstaller
python tools/build.py
```

`check_codex.py` は一時ホームで公式OAuthの開始・キャンセルまで確認します。
テスト中に実アカウントの認証やブラウザーの自動操作は行いません。
`CodexUsage.exe --smoke-test` はサンプル値のUIを短時間表示して終了します。
インストール済みexeの最小化・再起動による復帰は `python tools/check_installed.py` で確認できます。
