# Codex Usage（Windows常駐ウィジェット）

ChatGPTアカウントで利用するCodexの **5時間枠・1週間枠の残り割合** と、
**「利用上限のリセット」の保有残数** を常時表示します。
各枠の使用済み割合・回復予定日時、取得できる場合はリセット権の最短有効期限も表示します。

## 使い方

1. `起動.cmd` またはインストール先の `CodexUsage.exe` を起動します。
2. 初回は専用のMicrosoft Edge画面でChatGPTにログインしてください。
   いつもCodexで使用しているアカウントでログインします。
3. 取得に成功すると接続用ブラウザーは自動で隠れ、ウィジェットに残量が表示されます。
   ログイン後の反映には最大15秒程度かかります。「更新」ですぐ取得できます。

ログイン操作・パスワード・多要素認証はChatGPTの画面で直接行います。
専用Edgeプロファイルでログインを保持するため、通常使っているブラウザーとは別に初回ログインが必要です。

### 操作

- ヘッダーをドラッグ：位置を移動・保存
- `×` または `Esc`：通知領域に隠す
- 通知領域アイコンをダブルクリック：再表示
- `⋯` または右クリック：最前面、自動起動、更新間隔（30/60/120/300秒）、終了
- `接続 / ログイン`：ログイン画面を再表示。ログイン切れ・本人確認にも使用
- `使用状況 ↗`：通常のブラウザーでChatGPTの使用状況ページを開く
- 同じアプリを再起動：既存ウィジェットを再表示（二重起動しません）

初期設定は **最前面表示、60秒ごとの自動更新** です。
通信エラー時は前回値であることと最終取得時刻を表示し、自動で再試行します。
取得できない項目は `—` と表示し、ゼロとして扱いません。
回復予定時刻を過ぎても、再取得に成功するまで残量を100%に書き換えません。

## インストール・Windows自動起動

ビルド済みのexeに対して次を実行すると、現在のWindowsユーザーにインストールされます。
管理者権限は不要です。

```powershell
.\dist\CodexUsage.exe --install
& "$env:LOCALAPPDATA\CodexUsage\bin\CodexUsage.exe"
```

- 実体：`%LOCALAPPDATA%\CodexUsage\bin\CodexUsage.exe`
- 自動起動：`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` の `CodexUsage`
- Windowsへのサインイン時にウィジェットと通知領域アイコンを表示します。
- 無効化：メニューの「Windows起動時に常駐」をオフ、または `自動起動を解除.cmd`

アンインストールする場合は、自動起動を解除してアプリを終了後、
`%LOCALAPPDATA%\CodexUsage` を削除してください。専用のログイン情報も削除されます。

## データと取得方法

- 設定：`%LOCALAPPDATA%\CodexUsage\settings.json`
- 専用Edgeプロファイル：`%LOCALAPPDATA%\CodexUsage\EdgeProfile`
- 障害ログ：`%LOCALAPPDATA%\CodexUsage\app.log`（ローテーションあり）

使用量はOpenAIのCodex公開コードで使用される以下の取得先を参照します。

- `GET https://chatgpt.com/backend-api/wham/usage`
- `GET https://chatgpt.com/backend-api/wham/rate-limit-reset-credits`
- 契約の参照元：<https://github.com/openai/codex/blob/main/codex-rs/backend-client/src/client/rate_limit_resets.rs>

専用Edgeにループバック接続のDevToolsポートを開き、ChatGPTと同じオリジンで取得します。
トークンやCookieをアプリ設定・ログに保存せず、ブラウザー外へ渡すのは使用量の応答のみです。
バックグラウンドでもセッションを維持するため、専用Edgeのプロセスも動作します。
アプリ終了時に専用Edgeも終了します。

表示する%はCodex側の利用上限の割合です。絶対的なトークン数はこの応答に含まれません。
取得先はChatGPTの内部インターフェースのため、将来の変更に応じて更新が必要になる場合があります。

## 開発・ビルド

Windows 10/11、Microsoft Edge、Python 3.12で動作確認。

```powershell
python -m pip install -r requirements.txt
python app.py
python -m unittest discover -s tests -v
python app.py --smoke-test
python tools/check_ui.py
python tools/check_browser.py
python -m pip install pyinstaller
python tools/build.py
```

`--smoke-test` はサンプル値のUIを短時間表示して終了します。
ChatGPTへの接続・設定保存・自動起動の変更は行いません。
