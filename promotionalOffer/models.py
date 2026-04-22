from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union

class PromotionalOffer(BaseModel):
    promotionalOfferId: Optional[str] = None
    appTypes: List[str]
    offerName: Optional[str] = None
    locations: List[str]
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    fromTime: Optional[str] = None
    toTime: Optional[str] = None
    weekdays: List[str] = Field(default_factory=list)
    selectionType: Optional[str] = None
    itemName: Optional[List[str]] = None
    varianceName: Optional[List[str]] = None
    category: Optional[List[str]] = None
    subcategory: Optional[List[str]] = None
    selectionType1: Optional[str] = None
    itemName1: Optional[List[str]] = None
    varianceName1: Optional[List[str]] = None
    category1: Optional[List[str]] = None
    subcategory1: Optional[List[str]] = None
    configuration: Optional[str] = None
    discountValue: Optional[str] = None
    discountPercentage: Optional[str] = None
    orderValue: Optional[str] = None
    orderDiscountValue: Optional[str] = None
    orderDiscountPercentage: Optional[str] = None
    customers: Optional[List[str]] = None
    image: Optional[str] = None
    buy: Optional[int] = None
    get: Optional[int] = None
    offerType: Optional[str] = None
    status: Optional[str] = None
    freeoffer: Optional[str] = None
    discountOffer: Optional[str] = None
    coupencode: Optional[str] = None
    coupenmode: Optional[str] = None
    itemGrams: Optional[Dict[str, Union[float, List[float]]]] = Field(
        default=None,
        description="Kilograms per itemName (key = item name/code, value = kg or list of kg)"
    )
    varianceGrams: Optional[Dict[str, Union[float, List[float]]]] = Field(
        default=None,
        description="Kilograms per varianceName (key = variance name/code, value = kg or list of kg)"
    )
    freeItemGrams: Optional[Dict[str, Union[float, List[float]]]] = Field(
        default=None,
        description="Kilograms for free section items (buy/get)"
    )
    freeVarianceGrams: Optional[Dict[str, Union[float, List[float]]]] = Field(
        default=None,
        description="Kilograms for free section variances (buy/get)"
    )



class PromotionalOfferCreate(BaseModel):
    appTypes: List[str]
    offerName: Optional[str] = None
    locations: List[str]
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    fromTime: Optional[str] = None
    toTime: Optional[str] = None
    weekdays: List[str] = Field(default_factory=list)
    selectionType: Optional[str] = "All Items"
    itemName: List[str] = Field(default_factory=list)
    varianceName: List[str] = Field(default_factory=list)
    category: List[str] = Field(default_factory=list)
    subcategory: List[str] = Field(default_factory=list)
    selectionType1: Optional[str] = None
    itemName1: List[str] = Field(default_factory=list)
    varianceName1: List[str] = Field(default_factory=list)
    category1: List[str] = Field(default_factory=list)
    subcategory1: List[str] = Field(default_factory=list)
    configuration: Optional[str] = None
    discountValue: Optional[str] = ""
    discountPercentage: Optional[str] = ""
    orderValue: Optional[str] = ""
    orderDiscountValue: Optional[str] = ""
    orderDiscountPercentage: Optional[str] = ""
    customers: List[str] = Field(default_factory=list)
    image: Optional[str] = ""
    buy: Optional[int] = 0
    get: Optional[int] = 0
    offerType: Optional[str] = ""
    status: Optional[str] = "active"
    freeoffer: Optional[str] = "false"
    discountOffer: Optional[str] = "false"
    coupencode: Optional[str] = None
    coupenmode: Optional[str] = None
    itemGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None
    varianceGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None
    freeItemGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None
    freeVarianceGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None


class PromotionalOfferUpdate(BaseModel):
    appTypes: Optional[List[str]] = None
    offerName: Optional[str] = None
    locations: Optional[List[str]] = None
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    fromTime: Optional[str] = None
    toTime: Optional[str] = None
    weekdays: Optional[List[str]] = None
    selectionType: Optional[str] = None
    itemName: Optional[List[str]] = None
    varianceName: Optional[List[str]] = None
    category: Optional[List[str]] = None
    subcategory: Optional[List[str]] = None
    selectionType1: Optional[str] = None
    itemName1: Optional[List[str]] = None
    varianceName1: Optional[List[str]] = None
    category1: Optional[List[str]] = None
    subcategory1: Optional[List[str]] = None
    configuration: Optional[str] = None
    discountValue: Optional[str] = None
    discountPercentage: Optional[str] = None
    orderValue: Optional[str] = None
    orderDiscountValue: Optional[str] = None
    orderDiscountPercentage: Optional[str] = None
    customers: Optional[List[str]] = None
    image: Optional[str] = None
    buy: Optional[int] = None
    get: Optional[int] = None
    offerType: Optional[str] = None
    status: Optional[str] = None
    freeoffer: Optional[str] = None
    discountOffer: Optional[str] = None
    coupencode: Optional[str] = None
    coupenmode: Optional[str] = None
    itemGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None
    varianceGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None
    freeItemGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None
    freeVarianceGrams: Optional[Dict[str, Union[int, float, List[Union[int, float]]]]] = None