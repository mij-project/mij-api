
# アカウント種別
class AccountType:
    GENERAL_USER = 1 # 一般ユーザー
    CREATOR = 2 # クリエイター
    ADMIN = 3 # 管理者

# アカウントステータス
class AccountStatus:
    ACTIVE = 1 # 有効
    INACTIVE = 2 # 無効
    SUSPENDED = 3 # 停止
    DELETED = 4 # 削除

# クリエイターステータス
class CreatorStatus:
    ENTERED = 1 # 入力済み
    APPLICATED = 2 # 申請中
    VERIFIED = 3 # 本人確認済み
    REJECTED = 4 # 拒否
    SUSPENDED = 5 # 停止
    PHONE_NUMBER_ENTERED = 6 # 電話番号入力済み
    INFORMATION_ENTERED = 7 # 個人情報登録済み

# 本人確認ステータス
class VerificationStatus:
    PENDING = 0 # 未承認
    WAITING = 1 #承認待ち
    REJECTED = 2 # 拒否
    APPROVED = 3 # 承認

# 本人確認書類の種類
class IdentityKind:
    FRONT = 1 # 本人確認書類（正面）
    BACK = 2 # 本人確認書類（背面）
    SELFIE = 3 # 本人確認書類（本人写真）

# 投稿ステータス
class PostStatus:
    PENDING = 1 # 未承認
    REJECTED = 2 # 拒否
    UNPUBLISHED = 3 # 非公開
    DELETED = 4 # 削除
    APPROVED = 5 # 公開
    RESUBMIT = 6 # 再申請

# 投稿の種類
class PostType:
    VIDEO = 1 # ビデオ
    IMAGE = 2 # 画像

# 認証フラグ
class AuthenticatedFlag:
    NOT_AUTHENTICATED = 0 # 未認証
    AUTHENTICATED = 1 # 認証済み

# 投稿の公開範囲
class PostVisibility:
    SINGLE = 1 # 単品
    PLAN = 2 # プラン
    BOTH = 3 # 両方

# プランステータス
class PlanStatus:
    NORMAL = 1 # 普通
    RECOMMENDED = 2 # おすすめプラン

# プランライフサイクルステータス
class PlanLifecycleStatus:
    ACTIVE = 1 # アクティブ
    DELETE_REQUESTED = 2 # 削除申請中
    DELETED = 3 # 削除済み

class ProfileImage:
    AVATAR = 1 # アバター
    COVER = 2 # カバー

class ProfileImageStatus:
    PENDING = 1 # 申請中
    APPROVED = 2 # 承認済み
    REJECTED = 3 # 却下

# プランの種類
class PriceType:
    SINGLE = 1 # 単品
    PLAN = 2 # プラン

class MediaAssetStatus:
    PENDING = 1 # 未承認
    REJECTED = 2 # 拒否
    APPROVED = 3 # 承認
    DELETED = 4 # 削除
    UNPUBLISHED = 5 # 非公開
    RESUBMIT = 6 # 再申請
    CONVERTING = 7 # 変換中

# メディアアセットのkind
class MediaAssetKind:
    OGP = 1 # OGP画像
    THUMBNAIL = 2 # サムネイル画像
    IMAGES = 3 # 画像（複数）
    MAIN_VIDEO = 4 # メインビデオ
    SAMPLE_VIDEO = 5 # サンプルビデオ
    IMAGE_ORIGINAL = 6 # 画像（オリジナル）
    IMAGE_1080W = 7 # 画像（1080w）
    IMAGE_MOSAIC = 8 # 画像（モザイク）

# レンディションの種類
class RenditionKind:
    PREVIEW_MP4 = 1 # プレビュービデオ
    HLS_ABR4 = 2 # HLS_ABR4

# レンディションのバックエンド
class RenditionBackend:
    MEDIACONVERT = 1 # MediaConvert
    FARGATE_FFMPEG = 2 # Fargate FFmpeg

# レンディションのステータス
class RenditionJobStatus:
    PENDING = 1 # 未実行
    SUBMITTED = 2 # 実行中
    PROGRESSING = 3 # 進行中
    COMPLETE = 4 # 完了
    ERROR = 9 # エラー

# メディアレンディションの種類
class MediaRenditionJobKind:
    PREVIEW_MP4 = 1 # プレビュービデオ
    HLS_ABR4 = 2 # HLS_ABR4

# メディアレンディションのバックエンド
class MediaRenditionJobBackend:
    MEDIACONVERT = 1 # MediaConvert
    FARGATE_FFMPEG = 2 # Fargate FFmpeg

# メディアレンディションのステータス
class MediaRenditionJobStatus:
    PENDING = 1 # 未実行
    SUBMITTED = 2 # 実行中
    PROGRESSING = 3 # 進行中
    COMPLETE = 4 # 完了
    FAILED = 5 # エラー

# メディアレンディションの種類
class MediaRenditionKind:
    HLS_MASTER = 10 # HLS_MASTER
    HLS_VARIANT_360P  = 11 # HLS_VARIANT_360P
    HLS_VARIANT_480P  = 12 # HLS_VARIANT_480P
    HLS_VARIANT_720P  = 13 # HLS_VARIANT_720P
    HLS_VARIANT_1080P = 14 # HLS_VARIANT_1080P
    FFMPEG = 20 # FFMPEG

# 会話の種類
class ConversationType:
    SUPPORT = 1 # サポート会話
    DM = 2 # DM
    GROUP = 3 # グループ
    DELUSION = 4 # 妄想の間

# メディアアセットの向き
class MediaAssetOrientation:
    PORTRAIT = 1 # 縦
    LANDSCAPE = 2 # 横
    SQUARE = 3 # 正方形

class OrderStatus:
    PENDING = 1 # 未承認
    REJECTED = 2 # 拒否
    PAID = 3 # 支払い済み

# アイテムの種類
class ItemType:
    POST = 1 # 投稿
    PLAN = 2 # プラン

# 視聴権利のスコープ
class EntitlementScope:
    POST = 1 # 投稿
    CREATOR_ALL = 2 # プラン

# 視聴権利の付与元の種類
class GrantedByType:
    PURCHASE = 1  #単品購入
    SUBSCRIPTION= 2 #サブスクリプション

# サブスクリプションの種類
class SubscriptionStatus:
    ACTIVE = 1 # 有効
    INACTIVE = 2 # 無効
    CANCELLED = 3 # キャンセル
    EXPIRED = 4 # 期限切れ
    PENDING = 5 # 保留
    FAILED = 6 # 失敗
    REFUNDED = 7 # 返金
    REFUND_FAILED = 8 # 返金失敗
    REFUND_PENDING = 9 # 返金保留
    REFUND_PROCESSING = 10 # 返金処理中
    REFUND_COMPLETED = 11 # 返金完了

# SMS認証の目的
class SMSStatus:
    PENDING = 1 # 未使用
    VERIFIED = 2 # 使用済み
    EXPIRED = 3 # 期限切れ
    INVALIDATED = 9 # 無効化
    FAILED = 10 # 認証失敗

# SMS認証の目的
class SMSPurpose:
    CREATE_ACCOUNT = 1 # アカウント作成
    LOGIN = 2 # ログイン
    PASSWORD_RESET = 3 # パスワードリセット
    PAYMENT = 4 # 支払い
    OTHER = 9 # その他

# バナーの種類
class BannerType:
    CREATOR = 1 # クリエイター
    SPECIAL_EVENT = 2 # お知らせ

# バナーのステータス
class BannerStatus:
    INACTIVE = 0 # 無効
    ACTIVE = 1 # 有効
    DRAFT = 2 # 下書き

# バナーのソース
class BannerImageSource:
    USER_PROFILE = 1 # ユーザープロフィール
    ADMIN_POST = 2 # 管理者投稿

class EventStatus:
    INACTIVE = 0 # 無効
    ACTIVE = 1 # 有効
    DRAFT = 2 # 下書き