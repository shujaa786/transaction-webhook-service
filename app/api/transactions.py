from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import OutboxEvent, Transaction
from app.db.session import SessionLocal
from app.schemas.transaction import (
    TransactionAcceptedResponse,
    TransactionResponse,
    TransactionWebhookRequest,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post(
    "/webhooks/transactions",
    response_model=TransactionAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def receive_transaction(
    payload: TransactionWebhookRequest,
    db: Session = Depends(get_db),
):
    if payload.source_account == payload.destination_account:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Source and destination accounts must be different.",
        )

    existing = db.scalar(
        select(Transaction).where(Transaction.transaction_id == payload.transaction_id)
    )
    if existing:
        return TransactionAcceptedResponse(
            transaction_id=existing.transaction_id,
            status=existing.status,
        )

    transaction = Transaction(
        transaction_id=payload.transaction_id,
        source_account=payload.source_account,
        destination_account=payload.destination_account,
        amount=payload.amount,
        currency=payload.currency.upper(),
        status="PROCESSING",
    )
    event = OutboxEvent(
        transaction_id=payload.transaction_id,
        event_type="TRANSACTION_RECEIVED",
        status="PENDING",
        attempts=0,
    )

    try:
        db.add(transaction)
        db.flush()
        db.add(event)
        db.commit()
        db.refresh(transaction)
    except IntegrityError:
        db.rollback()
        # A concurrent request may have inserted the same transaction ID.
        existing = db.scalar(
            select(Transaction).where(
                Transaction.transaction_id == payload.transaction_id
            )
        )
        if existing:
            return TransactionAcceptedResponse(
                transaction_id=existing.transaction_id,
                status=existing.status,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transaction could not be created due to a database conflict.",
        )

    return TransactionAcceptedResponse(
        transaction_id=transaction.transaction_id,
        status=transaction.status,
    )


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
)
def get_transaction_status(
    transaction_id: str,
    db: Session = Depends(get_db),
):
    transaction = db.scalar(
        select(Transaction).where(Transaction.transaction_id == transaction_id)
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found.",
        )
    return transaction
