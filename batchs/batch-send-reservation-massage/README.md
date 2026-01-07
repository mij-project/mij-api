# 予約メッセージ送信バッチ

予約送信されたメッセージを指定時刻に送信し、受信者に通知（DB通知 + メール通知）を送るバッチ処理です。

## 機能概要

1. **予約メッセージの送信**
   - 環境変数`GROUP_BY`で指定されたグループに属する予約中メッセージを取得
   - 各メッセージのステータスを「送信済み」に更新
   - 会話の`last_message_id`と`last_message_at`を更新

2. **通知の送信**
   - 会話参加者のうち、送信者以外の全員に通知を送信
   - ユーザー設定（`user_settings.settings.message`）がfalseの場合は通知をスキップ
   - 通知がミュートされている参加者にはスキップ

3. **DB通知**
   - `notifications`テーブルに通知を挿入
   - 通知タイプ: `2` (users -> users)
   - ペイロード内容: 送信者名、アバター、会話へのリンク等

4. **メール通知**
   - HTMLメールを送信
   - テンプレート: `mailtemplates/new_message.html`

## 環境変数

| 変数名 | 必須 | 説明 | 例 |
|--------|------|------|-----|
| `GROUP_BY` | ✅ | 送信対象メッセージのグループID（UUID文字列） | `"89359892-8cf1-406d-aefb-0f0e39f093b1"` |
| `SENDER_USER_ID` | ✅ | 送信者のユーザーID（UUID） | `"550e8400-e29b-41d4-a716-446655440000"` |
| `FRONTEND_URL` | ❌ | フロントエンドURL（メール内リンク用） | `"https://mijfans.jp"` |
| `CDN_BASE_URL` | ❌ | CDNのベースURL（アバター画像用） | `"https://cdn.mijfans.jp"` |
| `EMAIL_ENABLED` | ❌ | メール送信の有効/無効 | `"true"` / `"false"` |
| `EMAIL_BACKEND` | ❌ | メールバックエンド | `"auto"` / `"mailhog"` / `"ses"` |
| `MAIL_FROM` | ❌ | 送信元メールアドレス | `"no-reply@mijfans.jp"` |
| `MAIL_FROM_NAME` | ❌ | 送信元名 | `"mijfans"` |

## 実行方法

### 基本的な実行

```bash
cd /Users/dkdk_23/workspace/02_mij-project/mij-project/apps/mij-api/batchs/batch-send-reservation-massage

# 環境変数を設定して実行
export GROUP_BY="89359892-8cf1-406d-aefb-0f0e39f093b1"
export SENDER_USER_ID="0d3c6214-977a-456e-b93b-2e953da114b5"

python main.py
```

### .envファイルを使った実行

```bash
# .envファイルを作成
cat << EOF > .env
GROUP_BY="89359892-8cf1-406d-aefb-0f0e39f093b1"
SENDER_USER_ID="550e8400-e29b-41d4-a716-446655440000"
FRONTEND_URL="https://mijfans.jp"
CDN_BASE_URL="https://cdn.mijfans.jp"
EMAIL_ENABLED="true"
EMAIL_BACKEND="ses"
EOF

# .envを読み込んで実行
set -a && source .env && set +a && python main.py
```

## データフロー

```
1. GROUP_BY環境変数から送信対象メッセージのグループIDを取得
   ↓
2. ConversationMessagesテーブルから以下を満たすメッセージを取得:
   - group_by = GROUP_BY
   - status = PENDING (2)
   - deleted_at = NULL
   ↓
3. 各メッセージに対して:
   a. conversation_participantsから受信者リストを取得（送信者を除く）
   b. 各受信者について:
      - user_settingsで「message」がtrueか確認（デフォルトはtrue）
      - notifications_mutedがfalseか確認
      - 条件を満たす場合のみ通知送信
   ↓
4. 通知送信:
   a. Notificationsテーブルに挿入（各通知ごとにコミット）
   b. メール送信
   ↓
5. メッセージの更新:
   a. statusを「送信済み」(1)に更新
   b. updated_atをReservationMessage.scheduled_atに設定
   c. Conversationsのlast_message_idとlast_message_atを更新
   ↓
6. すべてのメッセージ処理完了後にDBコミット
```

## メッセージステータス

- `PENDING (2)`: 予約中（送信待ち）
- `SENT (1)`: 送信済み

## user_settings.settings の「message」設定

`user_settings`テーブルの`settings`フィールド（JSONB型）で、メッセージ通知のON/OFFを制御します。

```json
{
  "message": true   // メッセージ通知を受け取る
}
```

```json
{
  "message": false  // メッセージ通知を受け取らない
}
```

設定がない場合はデフォルトで`true`として扱われます。

## 通知ペイロード構造

```json
{
  "type": "new_message",
  "title": "送信者名からメッセージが届きました",
  "subtitle": "送信者名からメッセージが届きました",
  "message": "送信者名からメッセージが届きました",
  "avatar": "https://cdn.mijfans.jp/path/to/avatar.jpg",
  "redirect_url": "/message/conversation/{conversation_id}",
  "conversation_id": "xxxxx-xxxxx-xxxxx",
  "message_id": "yyyyy-yyyyy-yyyyy"
}
```

## ログ出力例

```json
{"level": "INFO", "message": "START BATCH SEND RESERVATION MESSAGE"}
{"level": "INFO", "message": "GROUP_BY from env: '89359892-8cf1-406d-aefb-0f0e39f093b1', length=36"}
{"level": "INFO", "message": "Searching messages with group_by='89359892-8cf1-406d-aefb-0f0e39f093b1', status=2"}
{"level": "INFO", "message": "Messages with group_by='89359892-8cf1-406d-aefb-0f0e39f093b1': 2"}
{"level": "INFO", "message": "Found 2 messages matching all conditions for group_by=89359892-8cf1-406d-aefb-0f0e39f093b1"}
{"level": "INFO", "message": "[SEND] conversation_id=d737265c-c9fe-46ca-b09c-bd62d753a725 message_id=58f1f044-4fca-45e5-a2ab-12faee8fc737"}
{"level": "INFO", "message": "Notification inserted for user: user123"}
{"level": "INFO", "message": "Email sent to: user@example.com"}
{"level": "INFO", "message": "Done. sent=2, failed=0 for group_by=89359892-8cf1-406d-aefb-0f0e39f093b1"}
{"level": "INFO", "message": "END BATCH SEND RESERVATION MESSAGE"}
```

## エラーハンドリング

- `GROUP_BY`が設定されていない場合: エラーログを出力して処理を終了
- メッセージが存在しない場合: 情報ログを出力して処理を終了
- 送信者IDが不正な形式の場合: エラーログを出力（送信者情報なしで処理継続）
- 通知送信に失敗した場合: エラーログを出力して次の受信者へ進む
- メールアドレスがない場合: 警告ログを出力してメール送信をスキップ
- 個別のメッセージ処理でエラーが発生した場合: ロールバックして次のメッセージへ進む

## ディレクトリ構造

```
batch-send-reservation-massage/
├── main.py                          # エントリーポイント
├── send_reservation_message.py      # メイン処理ロジック
├── README.md                        # このファイル
├── common/
│   ├── db_session.py               # DB接続
│   ├── logger.py                   # ロガー
│   ├── constants.py                # 定数
│   └── email_service.py            # メール送信サービス
├── models/
│   ├── conversation_messages.py    # メッセージモデル
│   ├── conversation_participants.py # 参加者モデル
│   ├── conversations.py            # 会話モデル
│   ├── user.py                     # ユーザーモデル
│   ├── user_settings.py            # ユーザー設定モデル
│   ├── profiles.py                 # プロフィールモデル
│   ├── notifications.py            # 通知モデル
│   └── reservation_message.py      # 予約メッセージモデル
└── mailtemplates/
    └── new_message.html            # メール通知HTMLテンプレート
```

## 注意事項

1. **外部キー制約なし**: このバッチのモデルファイルは外部キー制約を使用していません（バッチ実行の安定性のため）
2. **トランザクション**: すべてのメッセージ処理が完了後に一括コミットします（通知挿入は個別にコミット）
3. **GROUP_BY必須**: `GROUP_BY`環境変数が設定されていない場合、処理は実行されません
4. **送信者ID**: `SENDER_USER_ID`が設定されていない場合、送信者情報が取得できず通知内容が不完全になる可能性があります
5. **メール送信**: 環境に応じて自動的にMailHog（開発環境）またはSES（本番環境）を使用します
6. **GROUP_BYの処理**: 環境変数から取得した`GROUP_BY`の前後の空白や引用符は自動的に削除されます

## トラブルシューティング

### メッセージが取得されない

- `GROUP_BY`が正しく設定されているか確認
- `conversation_messages`テーブルで該当する`group_by`のメッセージが存在するか確認
- メッセージの`status`が`PENDING (2)`になっているか確認
- メッセージの`deleted_at`が`NULL`になっているか確認
- ログで`GROUP_BY`の実際の値と検索条件を確認

### 通知が送信されない

- `user_settings.settings.message`が`false`になっていないか確認
- `conversation_participants.notifications_muted`が`true`になっていないか確認
- `SENDER_USER_ID`が正しく設定されているか確認
- ログで具体的なエラーメッセージを確認

### メールが届かない

- `EMAIL_ENABLED`が`true`になっているか確認
- 受信者のメールアドレスが正しく設定されているか確認
- SES設定（本番環境）またはMailHog起動（開発環境）を確認

### 外部キーエラーが発生する

- モデルファイルから`ForeignKey`が削除されているか確認
- 他のバッチ（`batch-notification-newpost-arrival`）のモデルと同じ構造になっているか確認
