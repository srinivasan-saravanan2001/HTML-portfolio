from pydantic import BaseModel
from typing import List, Optional

class ItemOrder(BaseModel):
    itemOrderId: Optional[str] = None
    billDate: Optional[str] = None
    billNo: Optional[str] = None
    netAmount: Optional[float] = None   
    billTotalAmount: Optional[float] = None
    locationName: Optional[str] = None
    customerNo: Optional[str] = None
    customerName: Optional[str] = None
    empId: Optional[str] = None 
    salesPersonName: Optional[str] = None
    types: Optional[str] = None

class PaginatedResponse(BaseModel):
    totalcount: int
    totalpages: int
    limit: int
    page: int
    skip: int
    items: List[ItemOrder]
    hasNextPage: bool = False  