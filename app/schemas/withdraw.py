from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class WithdrawalApplicationRequest(BaseModel):
    user_bank_id: str
    withdraw_amount: int = Field(..., ge=2000, description="出金申請金額（円）")
    transfer_amount: int = Field(..., ge=1650, description="実際振込金額（円）")


class WithdrawalApplication(BaseModel):
    id: str
    withdraw_amount: int
    transfer_amount: int
    # ステータス管理
    status: int
    # 処理日時
    requested_at: datetime
    # エラー情報
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None


class WithdrawalApplicationHistoryResponse(BaseModel):
    withdrawal_applications: Optional[List[WithdrawalApplication]] = Field(default=[])
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_previous: bool


class WithdrawalApplicationHistoryForAdmin(BaseModel):
    id: str
    withdraw_amount: int
    transfer_amount: int
    status: int
    requested_at: datetime
    account_holder_name: str
    account_type: int
    account_number: str

    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    creator_username: str
    bank_name: str
    bank_code: str
    branch_name: str
    branch_code: str
    completed_at: Optional[datetime] = None

class WithdrawalApplicationHistoryResponseForAdmin(BaseModel):
    withdrawal_applications: Optional[List[WithdrawalApplicationHistoryForAdmin]] = (
        Field(default=[])
    )
    total_count: int
    total_pages: int
    page: int
    limit: int

class WithdrawalApplicationUpdateRequest(BaseModel):
    application_id: str
    status: int