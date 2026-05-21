from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class SelectedItem(BaseModel):
    itemCode: str
    itemName: Optional[str] = None   
    varianceName: str
    variance_Defaultprice: float
    variance_Uom: str
    tax: float
    quantity: int
    lineTotal: float
    quantityKg: Optional[float] = None
    discountPercentage: Optional[float] = 0.0
    discountValue: Optional[float] = 0.0
    netTotal: Optional[float] = 0.0
    chargeAmount: Optional[float] = 0.0
    remarks: Optional[str] = None

class WholeSaleTakeaway(BaseModel):
    id: Optional[str] = None
    orderId: Optional[str] = None
    companyId: str
    companyName: str
    address: str
    phoneNumber: str
    items: List[SelectedItem]
    grossAmount: Optional[float] = 0.0
    discountPercentage: Optional[float] = 0.0
    discountValue: Optional[float] = 0.0
    discountAmount: Optional[float] = 0.0
    totalAmount: float
    chargeAmount: Optional[float] = 0.0
    remarks: Optional[str] = None
    paidAmount: float
    pendingAmount: float
    deliveryDate: datetime
    createdDate: Optional[datetime] = None
    invoicedDate: Optional[datetime] = None
    fullyPaidDate: Optional[datetime] = None
    status: Optional[str] = "active"
    companyStatus: Optional[str] = "takeaway"
    invoiceNo: Optional[str] = None
    amountStatus: Optional[str] = "pending"
    paymentMode: Optional[str] = None
    paymentHistory: Optional[List[Dict[str, Any]]] = Field(default_factory=list)

class WholeSaleTakeawayPost(BaseModel):
    orderId: Optional[str] = None
    companyId: str
    companyName: str
    address: str
    phoneNumber: str
    items: List[SelectedItem]
    grossAmount: Optional[float] = 0.0
    discountPercentage: Optional[float] = 0.0
    discountValue: Optional[float] = 0.0
    discountAmount: Optional[float] = 0.0
    chargeAmount: Optional[float] = 0.0
    remarks: Optional[str] = None
    totalAmount: float
    paidAmount: float
    deliveryDate: datetime
    paymentMode: Optional[str] = None

class PaymentModeUpdate(BaseModel):
    payment_mode: str
    paid_amount: Optional[float] = 0.0