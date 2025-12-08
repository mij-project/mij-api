from datetime import datetime, timezone
from app.models import BankRequestHistories, Banks
from app.models.user_banks import UserBanks
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.logger import Logger
from app.schemas.user_banks import ExternalBank, ExternalBranch

logger = Logger.get_logger()


def get_default_bank_information_by_user_id(db: Session, user_id: UUID) -> UserBanks:
    try:
        bank = (
            db.query(
                UserBanks,
                Banks.bank_code.label("bank_code"),
                Banks.bank_name.label("bank_name"),
                Banks.bank_name_kana.label("bank_name_kana"),
                Banks.branch_code.label("branch_code"),
                Banks.branch_name.label("branch_name"),
                Banks.branch_name_kana.label("branch_name_kana"),
            )
            .join(Banks, UserBanks.bank_id == Banks.id)
            .filter(UserBanks.user_id == user_id)
            .order_by(UserBanks.updated_at.desc())
            .first()
        )
        return bank
    except Exception as e:
        logger.exception(f"Failed to get default bank: {e}")
        return None


def check_bank_request_history(
    db: Session, user_id: UUID, request_type: int, search: str
):
    try:
        if search:
            history = (
                db.query(BankRequestHistories)
                .filter(
                    BankRequestHistories.request_type == request_type,
                    BankRequestHistories.bank_code == search,
                )
                .order_by(BankRequestHistories.created_at.desc())
                .first()
            )
        else:
            history = (
                db.query(BankRequestHistories)
                .filter(
                    BankRequestHistories.request_type == request_type,
                    BankRequestHistories.bank_code.is_(None),
                )
                .order_by(BankRequestHistories.created_at.desc())
                .first()
            )
        return history
    except Exception as e:
        logger.exception(f"Failed to check bank request history: {e}")
        return None


def create_bank_request_history(
    db: Session, user_id: UUID, request_type: int, bank_code: str, response_data: dict
):
    try:
        history = BankRequestHistories(
            user_id=user_id,
            request_type=request_type,
            bank_code=bank_code,
            response_data=response_data,
        )
        db.add(history)
        db.commit()
        return
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to create bank request history: {e}")
        return


def check_branch_request_history(
    db: Session, user_id: UUID, request_type: int, search: str, bank_code: str
):
    try:
        if search:
            history = (
                db.query(BankRequestHistories)
                .filter(
                    BankRequestHistories.request_type == request_type,
                    BankRequestHistories.bank_code == bank_code,
                    BankRequestHistories.branch_code == search,
                )
                .order_by(BankRequestHistories.created_at.desc())
                .first()
            )
        else:
            history = (
                db.query(BankRequestHistories)
                .filter(
                    BankRequestHistories.request_type == request_type,
                    BankRequestHistories.bank_code == bank_code,
                    BankRequestHistories.branch_code.is_(None),
                )
                .order_by(BankRequestHistories.created_at.desc())
                .first()
            )
        return history
    except Exception as e:
        logger.exception(f"Failed to check branch request history: {e}")
        return None


def create_branch_request_history(
    db: Session,
    user_id: UUID,
    request_type: int,
    bank_code: str,
    branch_code: str,
    response_data: dict,
):
    try:
        history = BankRequestHistories(
            user_id=user_id,
            request_type=request_type,
            bank_code=bank_code,
            branch_code=branch_code,
            response_data=response_data,
        )
        db.add(history)
        db.commit()
        return
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to create branch request history: {e}")
        return


def check_existing_bank_master(db: Session, bank_code: str, branch_code: str) -> bool:
    try:
        bank = (
            db.query(Banks)
            .filter(Banks.bank_code == bank_code, Banks.branch_code == branch_code)
            .first()
        )
        return bank
    except Exception as e:
        logger.exception(f"Failed to check existing bank master: {e}")
        return None


def create_bank_master(
    db: Session, bank: ExternalBank, branch: ExternalBranch
) -> Banks:
    try:
        bank_master = Banks(
            bank_code=bank.code,
            bank_name=bank.name,
            bank_name_kana=bank.hiragana,
            branch_code=branch.code,
            branch_name=branch.name,
            branch_name_kana=branch.hiragana,
        )
        db.add(bank_master)
        db.commit()
        return bank_master
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to create bank master: {e}")
        return None


def create_user_bank(
    db: Session,
    user_id: UUID,
    bank_id: UUID,
    account_type: int,
    account_number: str,
    account_holder: str,
) -> UserBanks:
    try:
        user_bank = UserBanks(
            user_id=user_id,
            bank_id=bank_id,
            account_type=account_type,
            account_number=account_number,
            account_holder_name=account_holder,
        )
        db.add(user_bank)
        db.commit()
        return user_bank
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to create user bank: {e}")
        return None


def check_user_bank_existing(
    db: Session, user_id: UUID, bank_id: UUID, account_number: str, account_holder: str
) -> UserBanks:
    try:
        user_bank = (
            db.query(UserBanks)
            .filter(
                UserBanks.user_id == user_id,
                UserBanks.bank_id == bank_id,
                UserBanks.account_number == account_number,
                UserBanks.account_holder_name == account_holder,
            )
            .first()
        )
        if user_bank:
            user_bank.updated_at = datetime.now(timezone.utc)
            db.add(user_bank)
            db.commit()
            db.refresh(user_bank)
        return user_bank
    except Exception as e:
        logger.exception(f"Failed to check user bank existing: {e}")
        return None
