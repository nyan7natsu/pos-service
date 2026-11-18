# POS Service

一般的なレジシステムおよびそれに付随する在庫管理システムなど

# Installation

前提として`just`，`uv`，`pnpm`がインストールされている必要があります．

各種依存パッケージのインストールは`just install`で行うことができます．

起動は`just dev`，ビルドは`just build`で行うことができます．

# API Reference

常にAPIは `/api` から始まります．  
ドキュメント内では省略されます．

## Authentication

認証状態は3状態あります．  
まず，ログインなしの状態．  
次に，一般ログイン状態．  
最後に，管理者ログイン状態です．

管理者ログイン状態になるには，DiscordのOAuth2認証を行う必要があります．  
事前に設定されたユーザーのみが管理者ログイン状態になることができます．

一般ログイン状態になるには，`X-Auth-Password`ヘッダーに共通パスワードを付与する必要があります．  
パスワードはDiscord上から取得・再発行する事ができます．

ログインなしの状態では，基本的に多くのAPIが利用できません．

## Endpoints

### POST `/auth`

一般ログイン用のパスワードをチェックして，ログインが可能かどうかを返すAPIです．

ヘッダーに`X-Auth-Password`を付与してそこにパスワードを入れることで認証が可能です．

- 200 OK: ログイン可能
- 401 Unauthorized: ログイン失敗

### GET `/backstage/discord/login`

管理者用のページにログインするため，DiscordのOAuth2認証を行うためのURLにリダイレクトします．

- 302 Found: DiscordのOAuth2認証ページにリダイレクト
- 500 Internal Server Error: POSサービスがDiscordにログインできていない場合

### GET `/backstage/discord/redirect`

DiscordのOAuth2認証が完了した後にリダイレクトされるURLです．

- 200 OK: `/backstage`にリダイレクト (`/api/backstage`ではなく`/backstage`にリダイレクトされます)
- 500 Internal Server Error: ユーザー情報が取得できなかった場合，またはPOSサービスがDiscordにログインできていない場合

### GET `/backstage/discord/logout`

DiscordのOAuth2認証をログアウトするためのURLです．

- 200 OK: ログアウト完了のメッセージ

### POST `/backstage/open`

レジを開局するAPIです．

リクエストボディは以下のようなJSON形式です．

```json
{
  "idempotency_key": "add6f466-72e8-4ee1-a33f-af1e7aa72650",
  "cash_count": {
    "yen_10000": 1,
    "yen_5000": 0,
    "yen_2000": 0,
    "yen_1000": 2,
    "yen_500": 1,
    "yen_100": 3,
    "yen_50": 0,
    "yen_10": 4,
    "yen_5": 0,
    "yen_1": 5
  },
  "ignore_mismatch": false
}
```

想定されている現金残高と，指定された `cash_count` が一致しない場合はエラーが発生します．  
この誤差が許容できる場合，または想定した誤差の場合は，`ignore_mismatch`を`true`にすることで無視して開局することができます．

- 200 OK: 開局成功
  ```json
  {
    "event_id": 1
  }
  ```
- 400 Bad Request: リクエストが不正な場合
- 401 Unauthorized: ログイン失敗
- 409 Conflict: レジがすでに開局されている場合
- 422 Unprocessable Entity: リクエストボディの形式が不正な場合，または想定金額と指定金額に誤差があるのにもかかわらず，`ignore_mismatch`が`false`の場合
- 500 Internal Server Error: 認証サービスが利用できない場合

### POST `/backstage/void`

VOID処理を行うAPIです．

リクエストボディは以下のようなJSON形式です．

```json
{
  "idempotency_key": "add6f466-72e8-4ee1-a33f-af1e7aa72650",
  "target_key": "add6f466-72e8-4ee1-a33f-af1e7aa72650",
  "reason": "VOID処理の理由"
}
```

`target_key`には，VOID処理を行う対象のレシートの`idempotency_key`を指定します．

- 200 OK: VOID処理成功
  ```json
  {
    "void_event_id": 1
  }
  ```
- 401 Unauthorized: ログイン失敗
- 409 Conflict: キーのイベントが見つからない場合，または対象のイベントがVOID済みの場合
- 422 Unprocessable Entity: リクエストボディの形式が不正な場合
- 500 Internal Server Error: 認証サービスが利用できない場合

### GET `/register/status`

POSサービスの状態を返すAPIです．
レジが空いているかどうかと，現在の現金残高を返します．

ヘッダーに`X-Auth-Password`を付与してそこにパスワードを入れることで認証が可能です．

- 200 OK: レジの状態を返す

  ```json
  {
    "is_open": true,
    "cash_count": {
      "yen_10000": 1,
      "yen_5000": 0,
      "yen_2000": 0,
      "yen_1000": 2,
      "yen_500": 1,
      "yen_100": 3,
      "yen_50": 0,
      "yen_10": 4,
      "yen_5": 0,
      "yen_1": 5
    }
  }
  ```

- 401 Unauthorized: ログイン失敗

### GET `/register/operators`

レジを操作する事ができる担当者の一覧を返すAPIエンドポイントです．

- 200 OK: 担当者の一覧を返す
  ```json
  {
    "operators": [
      {
        "id": "175928847299117063",
        "name": "ユーザー1"
      },
      {
        "id": "175928847300165639",
        "name": "ユーザー2"
      }
    ]
  }
  ```

`id`はDiscordのSnowflake IDであり，`name`はDiscordのサーバーでの表示名です．

### GET `/register/products`

販売可能な商品の一覧を返すAPIエンドポイントです．

- 200 OK: 商品の一覧を返す
  ```json
  {
    "products": [
      {
        "id": 1,
        "name": "商品1",
        "price": 1000,
        "category": "カテゴリ1",
        "enabled": true
      },
      {
        "id": 2,
        "name": "商品2",
        "price": 2000,
        "category": "カテゴリ2",
        "enabled": true
      }
    ]
  }
  ```

### POST `/register/sale`

販売処理を行うAPIエンドポイントです．販売処理の結果としてレシート番号を返します．再送の場合は前回の結果を返します．

ヘッダーに`X-Auth-Password`を付与してそこにパスワードを入れることで認証が可能です．

リクエストボディは以下のようなJSON形式です．

```json
{
  "idempotency_key": "add6f466-72e8-4ee1-a33f-af1e7aa72650",
  "items": [
    {
      "product_id": 1,
      "quantity": 2,
      "unit_price": 1000
    },
    {
      "product_id": 2,
      "quantity": 1,
      "unit_price": 2000
    }
  ],
  "discount": 100,
  "cash_count": {
    "yen_10000": 1,
    "yen_5000": 0,
    "yen_2000": 0,
    "yen_1000": 2,
    "yen_500": 1,
    "yen_100": 3,
    "yen_50": 0,
    "yen_10": 4,
    "yen_5": 0,
    "yen_1": 5
  },
  "occurred_at": "2024-06-01T12:00:00Z",
  "operator": "175928847299117063"
}
```

- 200 OK: 販売処理が成功した場合，レシート番号を返す
  ```json
  {
    "receipt_id": 2
  }
  ```
- 401 Unauthorized: ログイン失敗
- 409 Conflict: レジが開局されていない場合
- 422 Unprocessable Entity: リクエストボディの形式が不正な場合

### GET `/health`

POSサービスのヘルスチェック用のAPIです．

- 200 OK: POSサービスが正常に稼働している場合
