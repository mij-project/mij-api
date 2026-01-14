class CompanyFeePercent:
    DEFAULT = 3 # デフォルトの返金率
    PARENT_DEFAULT = 2 # 親会社のデフォルトの返金率
    CHILD_DEFAULT = 3 # 子会社のデフォルトの返金率

class PlatformFeePercent:
    DEFAULT = 10 # デフォルトのプラットフォーム手数料(%)

class PaymentPlanPlatformFeePercent:
    DEFAULT = 10 # デフォルトのプランフォーム手数料(%)

class AlbatalRecurringInterval:
    PERIOD_DAYS = 30 # 日数