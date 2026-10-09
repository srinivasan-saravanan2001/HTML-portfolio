from datetime import datetime
from typing import Optional, Any, Dict, List, Union
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient("mongodb+srv://srini462001:srini654693@cluster0.60oy4.mongodb.net/?appName=Cluster0")
db = client["salesorder"]

def get_wholesale_collection():
    return db["WholeSale"]

def round_amount(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(round(float(value)))
    except (ValueError, TypeError):
        return 0
    
def round_percentage(value: Any) -> float:
    if value is None:   
        return 0.0
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return 0.0

def distribute_integer(total_int: int, weights: List[int]) -> List[int]:
    if not weights or total_int <= 0:
        return [0] * len(weights)

    total_weight = sum(weights)
    if total_weight <= 0:
        return [0] * len(weights)
    exact = [total_int * w / total_weight for w in weights]
    floored = [int(e) for e in exact]
    shortfall = total_int - sum(floored)
    remainders = [(i, exact[i] - floored[i]) for i in range(len(exact))]
    remainders.sort(key=lambda x: -x[1])  
    for i in range(shortfall):
        idx = remainders[i][0]
        floored[idx] += 1
    
    return floored

    

def round_item_amounts(item: Dict) -> Dict:

    if not item:
        return item
    rounded = dict(item)
    amount_fields = ["lineTotal", "netTotal", "variance_Defaultprice", "quantity"]
    for field in amount_fields:
        if field in rounded and rounded[field] is not None:
            rounded[field] = round_amount(rounded[field])
    if "discountValue" in rounded and rounded["discountValue"] is not None:
        rounded["discountValue"] = round(float(rounded["discountValue"]), 2)
    percentage_fields = ["discountPercentage", "tax"]
    for field in percentage_fields:
        if field in rounded and rounded[field] is not None:
            rounded[field] = round_percentage(rounded[field])
    if "quantityKg" in rounded and rounded["quantityKg"] is not None:
        rounded["quantityKg"] = round(float(rounded["quantityKg"]), 2)

    return rounded


def round_order_amounts(data: Dict) -> Dict:
    if not data:
        return data
    rounded = dict(data)
    order_amount_fields = [
        "grossAmount",
        "discountAmount",
        "discountValue",
        "totalAmount",
        "paidAmount",
        "pendingAmount",
    ]
    for field in order_amount_fields:
        if field in rounded and rounded[field] is not None:
            rounded[field] = round_amount(rounded[field])
    percentage_fields = ["discountPercentage"]
    for field in percentage_fields:
        if field in rounded and rounded[field] is not None:
            rounded[field] = round_percentage(rounded[field])
    if "items" in rounded and isinstance(rounded["items"], list):
        rounded["items"] = [round_item_amounts(i) for i in rounded["items"]]
    return rounded


def serialize_item(item: Dict) -> Dict:
    if not item:
        return {}
    
    rounded = round_order_amounts(item)
    
    if "_id" in rounded:
        rounded["id"] = str(rounded["_id"])
        del rounded["_id"]
    if "customerId" in rounded and rounded["customerId"]:
        rounded["customerId"] = str(rounded["customerId"])
    else:
        rounded["customerId"] = None
    datetime_fields = ["createdDate", "deliveryDate", "invoicedDate", "fullyPaidDate"]
    for field in datetime_fields:
        if field in rounded and isinstance(rounded[field], datetime):
            rounded[field] = rounded[field].isoformat()

    return rounded

def get_financial_year(date=None):
    if date is None:
        date = datetime.now()
    year = date.year
    month = date.month
    if month >= 4:
        start_year = year % 100
        end_year = (year + 1) % 100
    else:
        start_year = (year - 1) % 100
        end_year = year % 100
    return f"{start_year:02d}-{end_year:02d}"


async def generate_invoice_no(collection):
    now = datetime.now()
    fy = get_financial_year(now)
    prefix = f"33{fy}CP"

    pipeline = [
        {"$match": {"invoiceNo": {"$regex": f"^33(BM)?{fy}CP\\d{{6}}$"}}},
        {
            "$project": {
                "numericSuffix": {
                    "$toInt": {"$substrBytes": ["$invoiceNo", {"$subtract": [{"$strLenBytes": "$invoiceNo"}, 6]}, 6]}
                }
            }
        },
        {"$group": {"_id": None, "maxNum": {"$max": "$numericSuffix"}}},
    ]

    result = await collection.aggregate(pipeline).to_list(length=1)

    if result and result[0].get("maxNum") is not None:
        next_number = result[0]["maxNum"] + 1
    else:
        next_number = 1

    return f"{prefix}{next_number:06d}"


async def generate_order_id(collection):
    now = datetime.now()
    fy = get_financial_year(now)
    prefix = f"33{fy}CPORD"

    pipeline = [
        {"$match": {"orderId": {"$regex": f"^33(BM)?{fy}CPORD\\d{{6}}$"}}},
        {
            "$project": {
                "numericSuffix": {
                    "$toInt": {"$substrBytes": ["$orderId", {"$subtract": [{"$strLenBytes": "$orderId"}, 6]}, 6]}
                }
            }
        },
        {"$group": {"_id": None, "maxNum": {"$max": "$numericSuffix"}}},
    ]

    result = await collection.aggregate(pipeline).to_list(length=1)

    if result and result[0].get("maxNum") is not None:
        next_number = result[0]["maxNum"] + 1
    else:
        next_number = 1

    return f"{prefix}{next_number:06d}"


def calculate_amount_status(paid_amount: float, total_amount: float) -> str:

    paid = round_amount(paid_amount)
    total = round_amount(total_amount)

    if paid <= 0:
        return "pending"
    elif paid < total:
        return "partial"
    else:
        return "fully"


def calculate_amount_status_with_date(
    paid_amount: float, total_amount: float, current_status: Optional[str] = None
) -> tuple:

    paid = round_amount(paid_amount)
    total = round_amount(total_amount)

    if paid <= 0:
        return "pending", False
    elif paid < total:
        return "partial", False
    else:
        if current_status != "fully":
            return "fully", True
        return "fully", False


def format_currency(amount: float) -> str:
    return f"₹{amount:,.2f}"