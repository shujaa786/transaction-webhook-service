# from decimal import Decimal
# from typing import Annotated

# from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# AccountId = Annotated[
#     str,
#     StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
# ]

# TransactionId = Annotated[
#     str,
#     StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
# ]


# class TransactionWebhookRequest(BaseModel):
#     model_config = ConfigDict(extra="forbid")

#     transaction_id: TransactionId
#     source_account: AccountId
#     destination_account: AccountId
#     amount: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
#     currency: Annotated[
#         str,
#         StringConstraints(strip_whitespace=True, min_length=3, max_length=3),
#     ]


# class TransactionResponse(BaseModel):
#     transaction_id: str
#     status: str


from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

AccountId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]

TransactionId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class TransactionWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: TransactionId
    source_account: AccountId
    destination_account: AccountId
    amount: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
    currency: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=3),
    ]


class TransactionAcceptedResponse(BaseModel):
    transaction_id: str
    status: str


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    source_account: str
    destination_account: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime
    processed_at: datetime | None = None
