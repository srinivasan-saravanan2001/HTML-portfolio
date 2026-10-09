from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ItemMasterWrite(BaseModel):
    itemName: str = Field(min_length=1)
    varianceName: str = Field(min_length=1)
    variance_Defaultprice: float = Field(ge=0)
    variance_Uom: str = Field(min_length=1)
    tax: float = Field(ge=0, le=100)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ItemMasterResponse(BaseModel):
    id: Optional[str] = None
    itemCode: Optional[str] = None
    itemName: Optional[str] = None
    varianceName: Optional[str] = None
    variance_Defaultprice: Optional[float] = None
    variance_Uom: Optional[str] = None
    tax: Optional[float] = None
    status: Optional[str] = "active"

    model_config = ConfigDict(from_attributes=True)
