from pydantic import BaseModel, ConfigDict
from typing import Optional

class ItemMasterResponse(BaseModel):
    itemCode: Optional[str] = None
    itemName: Optional[str] = None
    varianceName: Optional[str] = None
    variance_Defaultprice: Optional[float] = None
    variance_Uom: Optional[str] = None
    tax: Optional[float] = None
    model_config = ConfigDict(from_attributes=True) 