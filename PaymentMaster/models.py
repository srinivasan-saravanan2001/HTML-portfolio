from pydantic import BaseModel, ConfigDict, Field


class PaymentMasterWrite(BaseModel):
    paymentType: str = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PaymentMasterResponse(BaseModel):
    id: str
    paymentType: str
    status: str
