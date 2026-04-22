from asyncio import gather
from fastapi import APIRouter, HTTPException, Query, Response
from bson import ObjectId
from typing import Any, Dict, List, Optional
from datetime import datetime
import urllib
from fastapi.responses import StreamingResponse
import pandas as pd
from pymongo import UpdateOne
from .models import PaymentModeUpdate, WholeSaleTakeaway, WholeSaleTakeawayPost
from .utils import get_wholesale_collection
from io import BytesIO
from .utils import (
    get_wholesale_collection,
    generate_order_id,
    generate_invoice_no,
    calculate_amount_status,
    serialize_item,
    round_amount,
    round_percentage,
    round_order_amounts,
    round_item_amounts,
    distribute_integer,          # ✅ new import
)
from .pdf_generator import get_company_details, _build_invoice_pdf, build_ledger_pdf, build_order_pdf

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# CREATE  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/create", response_model=WholeSaleTakeaway)
async def create_takeaway(item: WholeSaleTakeawayPost):
    collection = get_wholesale_collection()
    data = item.dict()

    data["grossAmount"]        = round_amount(data.get("grossAmount", 0))
    data["discountPercentage"] = round_percentage(data.get("discountPercentage", 0))
    data["discountAmount"]     = round_amount(data.get("discountAmount", 0))
    data["discountValue"]      = round_amount(data.get("discountValue", 0))
    data["totalAmount"]        = round_amount(data.get("totalAmount", 0))
    data["paidAmount"]         = round_amount(data.get("paidAmount", 0))

    if "items" in data and isinstance(data["items"], list):
        data["items"] = [round_item_amounts(i) for i in data["items"]]

    data["orderId"]       = await generate_order_id(collection)
    data["pendingAmount"] = round_amount(data["totalAmount"] - data["paidAmount"])
    data["createdDate"]   = datetime.utcnow()
    data["invoicedDate"]  = None
    data["fullyPaidDate"] = None
    data["status"]        = "active"
    data["companyStatus"] = "order"
    data["invoiceNo"]     = None
    data["amountStatus"]  = calculate_amount_status(data["paidAmount"], data["totalAmount"])
    data["paymentHistory"] = []

    result   = await collection.insert_one(data)
    new_item = await collection.find_one({"_id": result.inserted_id})
    return serialize_item(new_item)


# ─────────────────────────────────────────────────────────────────────────────
# GET ALL  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/all", response_model=dict)
async def get_all_takeaways(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    item: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    company_status: Optional[str] = Query(None),
    amount_status: Optional[str] = Query(None),
    exclude_company_status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_field: Optional[str] = Query("createdDate"),
    sort_by: Optional[str] = Query("createdDate"),
    sort_order: Optional[str] = Query("desc"),
):
    collection = get_wholesale_collection()
    filter_query: Dict = {}

    if status:                  filter_query["status"] = status
    if company_status:          filter_query["companyStatus"] = company_status
    if amount_status:           filter_query["amountStatus"] = amount_status
    if exclude_company_status:  filter_query["companyStatus"] = {"$ne": exclude_company_status}
    if search:                  filter_query["companyName"] = {"$regex": search, "$options": "i"}
    if item:                    filter_query["items.varianceName"] = {"$regex": item, "$options": "i"}

    if start_date or end_date:
        date_filter: Dict = {}
        if start_date: date_filter["$gte"] = datetime.fromisoformat(start_date)
        if end_date:
            end_datetime = datetime.fromisoformat(end_date)
            end_datetime = end_datetime.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter["$lte"] = end_datetime
        filter_query[date_field] = date_filter

    total_count    = await collection.count_documents(filter_query)
    skip           = (page - 1) * limit
    sort_direction = -1 if sort_order == "desc" else 1
    cursor         = collection.find(filter_query).sort(sort_by, sort_direction).skip(skip).limit(limit)

    items = []
    async for item_doc in cursor:
        item_doc["id"] = str(item_doc["_id"])
        del item_doc["_id"]
        item_doc = round_order_amounts(item_doc)
        for field in ["createdDate", "invoicedDate", "fullyPaidDate", "deliveryDate"]:
            if field in item_doc and isinstance(item_doc[field], datetime):
                item_doc[field] = item_doc[field].isoformat()
        items.append(item_doc)

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET INVOICED  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/invoiced", response_model=dict)
async def get_invoiced_items(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    company_name: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_field: Optional[str] = Query("createdDate"),
    sort_by: Optional[str] = Query("createdDate"),
    sort_order: Optional[str] = Query("desc"),
):
    collection = get_wholesale_collection()

    filter_query: Dict = {
        "companyStatus": "invoiced",
        "status": "active",
        "amountStatus": {"$ne": "fully"},
    }
    if company_name:
        filter_query["companyName"] = company_name

    db_date_field = date_field
    if date_field == "invoiceDate":  db_date_field = "createdDate"
    elif date_field == "dueDate":    db_date_field = "deliveryDate"

    if start_date or end_date:
        date_filter: Dict = {}
        if start_date: date_filter["$gte"] = datetime.fromisoformat(start_date)
        if end_date:
            end_datetime = datetime.fromisoformat(end_date)
            end_datetime = end_datetime.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter["$lte"] = end_datetime
        filter_query[db_date_field] = date_filter

    db_sort_by = sort_by
    if sort_by == "invoiceDate":    db_sort_by = "createdDate"
    elif sort_by == "dueDate":      db_sort_by = "deliveryDate"
    elif sort_by == "invoicedDate": db_sort_by = "invoicedDate"

    sort_direction = -1 if sort_order == "desc" else 1

    pipeline = [
        {"$match": filter_query},
        {"$sort": {db_sort_by: sort_direction}},
        {
            "$group": {
                "_id":                    "$invoiceNo",
                "invoiceNo":              {"$first": "$invoiceNo"},
                "companyName":            {"$first": "$companyName"},
                "address":               {"$first": "$address"},
                "phoneNumber":           {"$first": "$phoneNumber"},
                "invoicedDate":          {"$first": "$invoicedDate"},
                "createdDate":           {"$first": "$createdDate"},
                "deliveryDate":          {"$first": "$deliveryDate"},
                "paymentMode":           {"$first": "$paymentMode"},
                "paymentHistoryArrays":  {"$push": "$paymentHistory"},
                "totalAmount":           {"$sum": "$totalAmount"},
                "paidAmount":            {"$sum": "$paidAmount"},
                "pendingAmount":         {"$sum": "$pendingAmount"},
                "grossAmount":           {"$sum": "$grossAmount"},
                "discountAmount":        {"$sum": "$discountAmount"},
                "orders": {"$push": {
                    "id":             {"$toString": "$_id"},
                    "orderId":        "$orderId",
                    "items":          "$items",
                    "totalAmount":    "$totalAmount",
                    "paidAmount":     "$paidAmount",
                    "pendingAmount":  "$pendingAmount",
                    "grossAmount":    "$grossAmount",
                    "discountAmount": "$discountAmount",
                    "amountStatus":   "$amountStatus",
                    "createdDate":    "$createdDate",
                    "deliveryDate":   "$deliveryDate",
                }},
                "amountStatus": {"$first": "$amountStatus"},
                "id":           {"$first": {"$toString": "$_id"}},
            }
        },
        {"$sort": {"invoiceNo": sort_direction}},
    ]

    count_pipeline = pipeline + [{"$count": "total"}]
    count_result   = await collection.aggregate(count_pipeline).to_list(length=1)
    total_count    = count_result[0]["total"] if count_result else 0

    paged_pipeline = pipeline + [{"$skip": (page - 1) * limit}, {"$limit": limit}]
    raw_groups     = await collection.aggregate(paged_pipeline).to_list(length=limit)

    def iso(val):
        if isinstance(val, datetime): return val.isoformat()
        return val or ""

    result_items = []
    for i, grp in enumerate(raw_groups):
        total   = round_amount(grp.get("totalAmount", 0))
        paid    = round_amount(grp.get("paidAmount", 0))
        pending = round_amount(grp.get("pendingAmount", 0))

        if paid <= 0:      amt_status = "Pending"
        elif paid < total: amt_status = "Partial"
        else:              amt_status = "Fully"

        seen_keys: set = set()
        all_history: List = []
        for sub in grp.get("paymentHistoryArrays", []):
            entries = sub if isinstance(sub, list) else ([sub] if sub else [])
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                dedup_key = f"{entry.get('date')}_{entry.get('mode')}_{entry.get('amount')}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                rounded_entry = dict(entry)
                rounded_entry["amount"] = round_amount(entry.get("amount", 0))
                all_history.append(rounded_entry)
        all_history.sort(key=lambda e: e.get("date", "") or "")

        all_items = []
        for order in grp.get("orders", []):
            for it in order.get("items", []):
                all_items.append(round_item_amounts(it))

        result_items.append({
            "id":                grp.get("id"),
            "sNo":               (page - 1) * limit + i + 1,
            "invoiceNumber":     grp.get("invoiceNo", "N/A"),
            "invoiceNo":         grp.get("invoiceNo", "N/A"),
            "companyName":       grp.get("companyName", ""),
            "address":           grp.get("address", ""),
            "phoneNumber":       grp.get("phoneNumber", ""),
            "items":             all_items,
            "orders":            grp.get("orders", []),
            "invoiceDate":       iso(grp.get("createdDate")),
            "deliveryDate":      iso(grp.get("deliveryDate")),
            "invoicedDate":      iso(grp.get("invoicedDate")),
            "amount":            total,
            "totalAmount":       total,
            "paidAmount":        paid,
            "pendingAmount":     pending,
            "status":            amt_status,
            "paymentMethod":     grp.get("paymentMode", ""),
            "paymentHistory":    all_history,
            "createdDate":       iso(grp.get("createdDate")),
            "grossAmount":       round_amount(grp.get("grossAmount", 0)),
            "discountPercentage": round_percentage(grp.get("discountPercentage", 0)),
            "discountValue":     round_amount(grp.get("discountValue", 0)),
            "discountAmount":    round_amount(grp.get("discountAmount", 0)),
        })

    return {
        "items": result_items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET FULLY PAID  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/fully-paid", response_model=dict)
async def get_fully_paid_items(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    company_name: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_field: Optional[str] = Query("fullyPaidDate"),
    sort_by: Optional[str] = Query("fullyPaidDate"),
    sort_order: Optional[str] = Query("desc"),
):
    collection = get_wholesale_collection()

    filter_query: Dict = {"amountStatus": "fully", "status": "active"}
    if company_name:
        filter_query["companyName"] = company_name

    if start_date or end_date:
        date_filter: Dict = {}
        if start_date: date_filter["$gte"] = datetime.fromisoformat(start_date)
        if end_date:
            end_datetime = datetime.fromisoformat(end_date)
            end_datetime = end_datetime.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter["$lte"] = end_datetime
        filter_query[date_field] = date_filter

    sort_direction = -1 if sort_order == "desc" else 1

    pipeline = [
        {"$match": filter_query},
        {"$sort": {sort_by: sort_direction}},
        {
            "$group": {
                "_id":                   "$invoiceNo",
                "invoiceNo":             {"$first": "$invoiceNo"},
                "companyName":           {"$first": "$companyName"},
                "address":              {"$first": "$address"},
                "phoneNumber":          {"$first": "$phoneNumber"},
                "invoicedDate":         {"$first": "$invoicedDate"},
                "createdDate":          {"$first": "$createdDate"},
                "deliveryDate":         {"$first": "$deliveryDate"},
                "fullyPaidDate":        {"$max": "$fullyPaidDate"},
                "paymentMode":          {"$first": "$paymentMode"},
                "paymentHistoryArrays": {"$push": "$paymentHistory"},
                "totalAmount":          {"$sum": "$totalAmount"},
                "paidAmount":           {"$sum": "$paidAmount"},
                "pendingAmount":        {"$sum": "$pendingAmount"},
                "companyStatus":        {"$first": "$companyStatus"},
                "amountStatus":         {"$first": "$amountStatus"},
                "grossAmount":          {"$first": "$grossAmount"},
                "discountPercentage":   {"$first": "$discountPercentage"},
                "discountValue":        {"$first": "$discountValue"},
                "discountAmount":       {"$first": "$discountAmount"},
                "orders": {"$push": {
                    "id":             {"$toString": "$_id"},
                    "orderId":        "$orderId",
                    "items":          "$items",
                    "totalAmount":    "$totalAmount",
                    "paidAmount":     "$paidAmount",
                    "pendingAmount":  "$pendingAmount",
                    "createdDate":    "$createdDate",
                    "deliveryDate":   "$deliveryDate",
                    "grossAmount":    "$grossAmount",
                    "discountAmount": "$discountAmount",
                }},
                "id": {"$first": {"$toString": "$_id"}},
            }
        },
        {"$sort": {"invoiceNo": sort_direction}},
    ]

    count_pipeline = pipeline + [{"$count": "total"}]
    count_result   = await collection.aggregate(count_pipeline).to_list(length=1)
    total_count    = count_result[0]["total"] if count_result else 0

    paged_pipeline = pipeline + [{"$skip": (page - 1) * limit}, {"$limit": limit}]
    raw_groups     = await collection.aggregate(paged_pipeline).to_list(length=limit)

    def iso(val):
        if isinstance(val, datetime): return val.isoformat()
        return val or ""

    result_items = []
    for i, grp in enumerate(raw_groups):
        seen_keys: set = set()
        all_history: List = []
        for sub in grp.get("paymentHistoryArrays", []):
            entries = sub if isinstance(sub, list) else ([sub] if sub else [])
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                dedup_key = f"{entry.get('date')}_{entry.get('mode')}_{entry.get('amount')}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                rounded_entry = dict(entry)
                rounded_entry["amount"] = round_amount(entry.get("amount", 0))
                all_history.append(rounded_entry)
        all_history.sort(key=lambda e: e.get("date", "") or "")

        all_items = []
        for order in grp.get("orders", []):
            for it in order.get("items", []):
                all_items.append(round_item_amounts(it))

        result_items.append({
            "id":                grp.get("id"),
            "sNo":               (page - 1) * limit + i + 1,
            "invoiceNumber":     grp.get("invoiceNo", "N/A"),
            "invoiceNo":         grp.get("invoiceNo", "N/A"),
            "companyId":         "",
            "companyName":       grp.get("companyName", ""),
            "address":           grp.get("address", ""),
            "phoneNumber":       grp.get("phoneNumber", ""),
            "items":             all_items,
            "orders":            grp.get("orders", []),
            "totalAmount":       round_amount(grp.get("totalAmount", 0)),
            "paidAmount":        round_amount(grp.get("paidAmount", 0)),
            "pendingAmount":     round_amount(grp.get("pendingAmount", 0)),
            "createdDate":       iso(grp.get("createdDate")),
            "deliveryDate":      iso(grp.get("deliveryDate")),
            "invoicedDate":      iso(grp.get("invoicedDate")),
            "fullyPaidDate":     iso(grp.get("fullyPaidDate")),
            "status":            grp.get("status", ""),
            "companyStatus":     grp.get("companyStatus", ""),
            "amountStatus":      grp.get("amountStatus", ""),
            "paymentMode":       grp.get("paymentMode", ""),
            "paymentHistory":    all_history,
            "grossAmount":       round_amount(grp.get("grossAmount", 0)),
            "discountPercentage": round_percentage(grp.get("discountPercentage", 0)),
            "discountValue":     round_amount(grp.get("discountValue", 0)),
            "discountAmount":    round_amount(grp.get("discountAmount", 0)),
        })

    return {
        "items": result_items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# VIEW / UPDATE / DELETE / ACTIVATE  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/view/{item_id}", response_model=WholeSaleTakeaway)
async def get_takeaway(item_id: str):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    item = await collection.find_one({"_id": ObjectId(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return serialize_item(item)


@router.patch("/update/{item_id}", response_model=WholeSaleTakeaway)
async def update_takeaway(item_id: str, item: WholeSaleTakeawayPost):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    existing_item = await collection.find_one({"_id": ObjectId(item_id)})
    if not existing_item:
        raise HTTPException(status_code=404, detail="Not found")

    update_data = item.dict()

    update_data["grossAmount"]        = round_amount(update_data.get("grossAmount", 0))
    update_data["discountPercentage"] = round_percentage(update_data.get("discountPercentage", 0))
    update_data["discountAmount"]     = round_amount(update_data.get("discountAmount", 0))
    update_data["discountValue"]      = round_amount(update_data.get("discountValue", 0))
    update_data["totalAmount"]        = round_amount(update_data.get("totalAmount", 0))
    update_data["paidAmount"]         = round_amount(update_data.get("paidAmount", 0))

    if "items" in update_data and isinstance(update_data["items"], list):
        update_data["items"] = [round_item_amounts(i) for i in update_data["items"]]

    update_data["pendingAmount"] = round_amount(update_data["totalAmount"] - update_data["paidAmount"])
    update_data["amountStatus"]  = calculate_amount_status(
        update_data["paidAmount"], update_data["totalAmount"]
    )

    protected_fields = [
        "orderId", "createdDate", "status", "invoicedDate",
        "fullyPaidDate", "companyStatus", "invoiceNo", "paymentHistory",
    ]
    for field in protected_fields:
        update_data.pop(field, None)

    await collection.update_one({"_id": ObjectId(item_id)}, {"$set": update_data})
    updated_item = await collection.find_one({"_id": ObjectId(item_id)})
    return serialize_item(updated_item)


# @router.patch("/update-paid/{invoice_no}")
# async def update_paid_amount(invoice_no: str, paid_amount: float = Query(...)):
#     collection = get_wholesale_collection()

#     # ✅ 1. Fetch only required fields (reduces DB payload)
#     orders = await collection.find(
#         {"invoiceNo": invoice_no, "status": "active"},
#         {"_id": 1, "totalAmount": 1}
#     ).to_list(length=500)

#     if not orders:
#         raise HTTPException(status_code=404, detail="Invoice not found")

#     # ✅ 2. Convert to integer (safe financial handling)
#     paid_int = round_amount(paid_amount)
#     order_totals = [round_amount(o.get("totalAmount", 0)) for o in orders]
#     total_int = sum(order_totals)

#     # ✅ 3. Validation
#     if paid_int < 0 or paid_int > total_int:
#         raise HTTPException(status_code=400, detail="Invalid amount")

#     # ✅ 4. Distribute amount accurately
#     distributed_paid = distribute_integer(paid_int, order_totals)

#     now = datetime.utcnow()
#     operations = []

#     # ✅ 5. Prepare bulk operations (NO loop DB calls)
#     for idx, order in enumerate(orders):
#         order_total = order_totals[idx]
#         order_paid = distributed_paid[idx]
#         order_pending = order_total - order_paid
#         status = calculate_amount_status(order_paid, order_total)

#         update_fields: Dict[str, Any] = {
#             "paidAmount": order_paid,
#             "pendingAmount": order_pending,
#             "amountStatus": status,
#         }

#         if status == "fully":
#             update_fields["fullyPaidDate"] = now

#         operations.append(
#             UpdateOne(
#                 {"_id": order["_id"]},
#                 {"$set": update_fields}
#             )
#         )

#     # ✅ 6. Execute ALL updates in ONE DB call
#     if operations:
#         await collection.bulk_write(operations)

#     # ✅ 7. Final response
#     final_paid = sum(distributed_paid)
#     final_pending = total_int - final_paid

#     return {
#         "success": True,
#         "message": "Paid amount updated accurately across all orders",
#         "data": {
#             "invoiceNo": invoice_no,
#             "totalPaid": final_paid,
#             "totalPending": final_pending,
#             "calculatedStatus": "fully" if final_pending <= 0 else "partial",
#             "orderCount": len(orders),
#         },
#     }




@router.patch("/update-paid/{invoice_no}")
async def update_paid_amount(invoice_no: str, paid_amount: float = Query(...)):
    collection = get_wholesale_collection()

    # ✅ 1. Fetch orders with ALL required fields for accurate total calculation
    orders = await collection.find(
        {"invoiceNo": invoice_no, "status": "active"},
        {"_id": 1, "totalAmount": 1, "paidAmount": 1, "pendingAmount": 1, "amountStatus": 1}
    ).to_list(length=500)

    if not orders:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # ✅ 2. Calculate ACTUAL total amount from orders
    order_totals = [round_amount(o.get("totalAmount", 0)) for o in orders]
    total_int = sum(order_totals)
    paid_int = round_amount(paid_amount)

    # ✅ 3. Validation - paid amount cannot exceed total
    if paid_int < 0 or paid_int > total_int:
        raise HTTPException(status_code=400, detail=f"Invalid amount. Total invoice amount is {total_int}")

    # ✅ 4. Calculate current total paid across all orders
    current_total_paid = sum(round_amount(o.get("paidAmount", 0)) for o in orders)
    
    # ✅ 5. Calculate additional amount to distribute
    additional_amount = paid_int - current_total_paid
    
    if additional_amount < 0:
        raise HTTPException(status_code=400, detail="Cannot reduce paid amount")
    
    if additional_amount == 0:
        return {
            "success": True,
            "message": "No change in paid amount",
            "data": {
                "invoiceNo": invoice_no,
                "totalPaid": paid_int,
                "totalPending": total_int - paid_int,
                "calculatedStatus": "fully" if paid_int >= total_int else "partial",
                "orderCount": len(orders),
            },
        }

    # ✅ 6. Distribute ONLY the additional amount across orders based on pending amounts
    current_pending = [total - round_amount(o.get("paidAmount", 0)) for total, o in zip(order_totals, orders)]
    total_pending = sum(current_pending)
    
    if total_pending <= 0:
        return {
            "success": True,
            "message": "All orders are already fully paid",
            "data": {
                "invoiceNo": invoice_no,
                "totalPaid": total_int,
                "totalPending": 0,
                "calculatedStatus": "fully",
                "orderCount": len(orders),
            },
        }
    
    # Distribute additional amount proportionally based on pending amounts
    distributed_additional = distribute_integer(additional_amount, current_pending)

    now = datetime.utcnow()
    operations = []

    # ✅ 7. Prepare bulk operations
    for idx, order in enumerate(orders):
        order_total = order_totals[idx]
        current_paid = round_amount(order.get("paidAmount", 0))
        new_paid = current_paid + distributed_additional[idx]
        new_pending = order_total - new_paid
        
        # Round to handle any floating point issues
        new_paid = round_amount(new_paid)
        new_pending = round_amount(new_pending)
        
        status = calculate_amount_status(new_paid, order_total)

        update_fields: Dict[str, Any] = {
            "paidAmount": new_paid,
            "pendingAmount": new_pending,
            "amountStatus": status,
        }

        if status == "fully":
            update_fields["fullyPaidDate"] = now

        operations.append(
            UpdateOne(
                {"_id": order["_id"]},
                {"$set": update_fields}
            )
        )

    # ✅ 8. Execute ALL updates in ONE DB call
    if operations:
        await collection.bulk_write(operations)

    # ✅ 9. Verify final totals
    final_paid = sum(distributed_additional) + current_total_paid
    final_pending = total_int - final_paid

    return {
        "success": True,
        "message": f"Paid amount updated: +{additional_amount} distributed across {len(orders)} orders",
        "data": {
            "invoiceNo": invoice_no,
            "previousTotalPaid": current_total_paid,
            "additionalAmount": additional_amount,
            "totalPaid": final_paid,
            "totalPending": final_pending,
            "calculatedStatus": "fully" if final_pending <= 0 else "partial",
            "orderCount": len(orders),
        },
    }


@router.patch("/update-payment-mode/{invoice_no}")
async def update_payment_mode(invoice_no: str, update_data: PaymentModeUpdate):
    collection = get_wholesale_collection()

    rounded_amount = round_amount(update_data.paid_amount or 0)

    history_entry = {
        "mode":   update_data.payment_mode,
        "amount": rounded_amount,
        "date":   datetime.utcnow().isoformat(),
    }

    await collection.update_many(
        {"invoiceNo": invoice_no, "status": "active"},
        {"$set": {"paymentMode": update_data.payment_mode}},
    )

    # ✅ FIX: always push to PRIMARY order (oldest createdDate) — consistent location
    primary_order = await collection.find_one(
        {"invoiceNo": invoice_no, "status": "active"},
        sort=[("createdDate", 1)],
    )

    if primary_order:
        await collection.update_one(
            {"_id": primary_order["_id"]},
            {"$push": {"paymentHistory": history_entry}},
        )

    return {
        "success": True,
        "message": "Payment recorded successfully",
        "data": {
            "invoiceNo":   invoice_no,
            "paymentMode": update_data.payment_mode,
            "paidAmount":  rounded_amount,
        },
    }


@router.post("/move-to-printed")
async def move_to_printed(item_ids: List[str]):
    collection    = get_wholesale_collection()
    updated_items = []
    for item_id in item_ids:
        if not ObjectId.is_valid(item_id):
            continue
        item = await collection.find_one({"_id": ObjectId(item_id)})
        if not item:
            continue
        await collection.update_one(
            {"_id": ObjectId(item_id)}, {"$set": {"companyStatus": "printed"}}
        )
        updated_item = await collection.find_one({"_id": ObjectId(item_id)})
        updated_items.append(serialize_item(updated_item))
    if not updated_items:
        raise HTTPException(status_code=404, detail="No items found or updated")
    return {"message": "Items marked as printed successfully", "items": updated_items}


@router.patch("/move-to-invoiced/{item_id}")
async def move_to_invoiced(item_id: str):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    item = await collection.find_one({"_id": ObjectId(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.get("companyStatus") != "printed":
        raise HTTPException(
            status_code=400, detail="Can only move to invoiced from printed status"
        )
    current_time = datetime.utcnow()
    await collection.update_one(
        {"_id": ObjectId(item_id)},
        {"$set": {"companyStatus": "invoiced", "invoicedDate": current_time}},
    )
    updated_item = await collection.find_one({"_id": ObjectId(item_id)})
    return serialize_item(updated_item)


@router.delete("/delete/{item_id}")
async def delete_takeaway(item_id: str):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    result = await collection.update_one(
        {"_id": ObjectId(item_id)}, {"$set": {"status": "inactive"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"message": "Item deactivated successfully"}


@router.patch("/activate/{item_id}")
async def activate_takeaway(item_id: str):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    result = await collection.update_one(
        {"_id": ObjectId(item_id)}, {"$set": {"status": "active"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"message": "Item activated successfully"}



# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTION (Renamed for clarity)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES (Helper function included)
# ─────────────────────────────────────────────────────────────────────────────

async def _get_company_total_outstanding(
    collection,
    company_name: str,
) -> float:
    """
    Returns the total pending amount owed by `company_name` across ALL
    invoiced orders.
    """
    match: Dict[str, Any] = {
        "companyName":   company_name,
        "companyStatus": "invoiced",
        "status":        "active",
    }

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id":          "$invoiceNo",
                "total_amount": {"$sum": "$totalAmount"},
                "paid_amount":  {"$sum": "$paidAmount"},
            }
        },
        {
            "$group": {
                "_id": None,
                "total_outstanding": {
                    "$sum": {"$subtract": ["$total_amount", "$paid_amount"]}
                },
            }
        },
    ]

    result = await collection.aggregate(pipeline).to_list(length=1)
    if result:
        return max(round(result[0].get("total_outstanding", 0.0), 2), 0.0)
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate-order-pdf/{item_id}")
async def generate_order_pdf(item_id: str):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    item = await collection.find_one({"_id": ObjectId(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.get("companyStatus") == "order":
        await collection.update_one(
            {"_id": ObjectId(item_id)}, {"$set": {"companyStatus": "printed"}}
        )
        item = await collection.find_one({"_id": ObjectId(item_id)})

    item["id"] = str(item["_id"])
    del item["_id"]
    for field in ["createdDate", "deliveryDate", "invoicedDate", "fullyPaidDate"]:
        if field in item and isinstance(item[field], datetime):
            item[field] = item[field].isoformat()

    # Calculate TOTAL outstanding
    company_name = item.get("companyName", "")
    total_outstanding = await _get_company_total_outstanding(
        collection, company_name
    )

    company_info = await get_company_details()
    pdf_bytes    = build_order_pdf(item, company_info, previous_outstanding=total_outstanding)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=Order_{datetime.now().strftime('%Y%m%d')}.pdf"
        },
    )


@router.post("/generate-pdf")
async def generate_invoices_pdf(item_ids: List[str]):
    collection        = get_wholesale_collection()
    common_invoice_no = await generate_invoice_no(collection)
    items             = []
    company_name      = None

    for item_id in item_ids:
        if not ObjectId.is_valid(item_id):
            continue
        await collection.update_one(
            {"_id": ObjectId(item_id)},
            {
                "$set": {
                    "invoiceNo":     common_invoice_no,
                    "companyStatus": "invoiced",
                    "invoicedDate":  datetime.utcnow(),
                }
            },
        )
        item = await collection.find_one({"_id": ObjectId(item_id)})
        if item:
            if company_name is None:
                company_name = item.get("companyName", "")
            items.append(serialize_item(item))

    if not items:
        raise HTTPException(status_code=404, detail="No items found")

    items.sort(key=lambda x: x.get("orderId", ""))

    # Calculate TOTAL outstanding
    total_outstanding = await _get_company_total_outstanding(
        collection,
        company_name or "",
    )

    company_info = await get_company_details()
    pdf_bytes    = _build_invoice_pdf(
        items,
        common_invoice_no,
        company_info,
        previous_outstanding=total_outstanding,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{common_invoice_no}.pdf"},
    )


@router.post("/generate-invoice-with-payment/{invoice_no}")
async def generate_invoice_with_payment(
    invoice_no: str, paymentMode: Optional[str] = None
):
    collection    = get_wholesale_collection()
    orders_cursor = collection.find({"invoiceNo": invoice_no, "status": "active"})
    orders        = await orders_cursor.to_list(length=1000)
    if not orders:
        raise HTTPException(status_code=404, detail="Invoice not found")

    total_invoice_amount = sum(o.get("totalAmount", 0) for o in orders)
    total_paid_amount    = sum(o.get("paidAmount",  0) for o in orders)
    total_pending_amount = sum(o.get("pendingAmount", 0) for o in orders)

    is_fully_paid = round_amount(total_paid_amount) >= round_amount(total_invoice_amount)

    now         = datetime.utcnow()
    update_data: Dict[str, Any] = {"companyStatus": "invoiced", "invoicedDate": now}

    if paymentMode:
        update_data["paymentMode"] = paymentMode
    if is_fully_paid:
        update_data["amountStatus"]  = "fully"
        update_data["fullyPaidDate"] = now
        update_data["pendingAmount"] = 0

    await collection.update_many(
        {"invoiceNo": invoice_no, "status": "active"}, {"$set": update_data}
    )

    orders = await collection.find({"invoiceNo": invoice_no}).to_list(length=1000)
    items  = [serialize_item(dict(order)) for order in orders]
    items.sort(key=lambda x: x.get("orderId", ""))

    company_name = items[0].get("companyName", "") if items else ""

    if is_fully_paid:             amount_status = "fully"
    elif total_paid_amount == 0:  amount_status = "pending"
    else:                         amount_status = "partial"

    # Calculate TOTAL outstanding
    total_outstanding = await _get_company_total_outstanding(
        collection,
        company_name,
    )

    company_info = await get_company_details()
    pdf_bytes    = _build_invoice_pdf(
        items,
        invoice_no,
        company_info,
        paid_amount=total_paid_amount,
        pending_amount=0 if is_fully_paid else total_pending_amount,
        amount_status=amount_status,
        previous_outstanding=total_outstanding,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=Invoice_{invoice_no}.pdf",
            "X-Payment-Status":    amount_status,
            "X-Invoice-Number":    invoice_no,
        },
    )

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD & STATS  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard-stats", response_model=dict)
async def get_dashboard_stats(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
):
    collection  = get_wholesale_collection()
    base_match  = {"status": "active"}
    search_match = {"status": "active"}

    if search:
        search_filter = {
            "$or": [
                {"companyName": {"$regex": search, "$options": "i"}},
                {"invoiceNo":   {"$regex": search, "$options": "i"}},
            ]
        }
        base_match.update(search_filter)
        search_match.update(search_filter)

    post_group_filter: Dict = {}
    if status and status != "all":
        if status == "invoiced":
            post_group_filter = {"companyStatus": "invoiced"}
        elif status == "fully":
            post_group_filter = {"invoice_amount_status": "fully"}
        elif status == "partial":
            post_group_filter = {"invoice_amount_status": "partial"}
        elif status == "pending":
            post_group_filter = {"invoice_amount_status": "pending"}
        elif status == "realized":
            post_group_filter = {"paid_amount": {"$gt": 0}}

    chart_prefilter_stages: List = []
    if post_group_filter:
        chart_prefilter_stages = [
            {
                "$group": {
                    "_id": {
                        "$cond": {
                            "if":   {"$and": [{"$ne": ["$invoiceNo", None]}, {"$ne": ["$invoiceNo", ""]}]},
                            "then": "$invoiceNo",
                            "else": "$orderId",
                        }
                    },
                    "companyStatus": {"$first": "$companyStatus"},
                    "paid_amount":   {"$sum": "$paidAmount"},
                    "total_amount":  {"$sum": "$totalAmount"},
                    "orderIds":      {"$push": "$_id"},
                }
            },
            {
                "$addFields": {
                    "invoice_amount_status": {
                        "$switch": {
                            "branches": [
                                {"case": {"$eq":  ["$paid_amount", 0]},               "then": "pending"},
                                {"case": {"$lt":  ["$paid_amount", "$total_amount"]}, "then": "partial"},
                            ],
                            "default": "fully",
                        }
                    }
                }
            },
            {"$match": post_group_filter},
            {"$unwind": "$orderIds"},
            {
                "$lookup": {
                    "from":         "WholeSale",
                    "localField":   "orderIds",
                    "foreignField": "_id",
                    "as":           "orderDoc",
                }
            },
            {"$unwind": "$orderDoc"},
            {"$replaceRoot": {"newRoot": "$orderDoc"}},
        ]

    top_items_pipeline = (
        [{"$match": search_match}] + chart_prefilter_stages + [{"$unwind": "$items"}]
        if chart_prefilter_stages
        else [{"$match": search_match}, {"$unwind": "$items"}]
    )
    top_items_pipeline += [
        {
            "$addFields": {
                "effectiveQty": {
                    "$add": [
                        {"$ifNull": ["$items.quantityKg", {"$ifNull": ["$items.quantity", 1]}]},
                        {"$divide": [{"$ifNull": ["$items.quantityGrams", 0]}, 1000]},
                    ]
                },
                "perUnitDiscount": {
                    "$cond": [
                        {"$gt": [{"$ifNull": ["$items.discountValue", 0]}, 0]},
                        {"$min": [{"$ifNull": ["$items.discountValue", 0]}, "$items.variance_Defaultprice"]},
                        {
                            "$multiply": [
                                "$items.variance_Defaultprice",
                                {"$divide": [{"$ifNull": ["$items.discountPercentage", 0]}, 100]},
                            ]
                        },
                    ]
                },
            }
        },
        {
            "$addFields": {
                "netRevenue": {
                    "$multiply": [
                        {"$subtract": ["$items.variance_Defaultprice", "$perUnitDiscount"]},
                        "$effectiveQty",
                    ]
                }
            }
        },
        {
            "$group": {
                "_id":           "$items.varianceName",
                "totalQuantity": {"$sum": "$effectiveQty"},
                "totalRevenue":  {"$sum": {"$round": ["$netRevenue", 0]}},
                "count":         {"$sum": 1},
            }
        },
        {"$sort": {"totalRevenue": -1}},
        {"$limit": 5},
        {
            "$project": {
                "name":     "$_id",
                "quantity": {"$round": ["$totalQuantity", 2]},
                "revenue":  {"$round": ["$totalRevenue",  0]},
                "orders":   "$count",
                "_id":       0,
            }
        },
    ]

    trend_pipeline = (
        [{"$match": search_match}] + chart_prefilter_stages
        if chart_prefilter_stages
        else [{"$match": search_match}]
    ) + [
        {
            "$project": {
                "dateStr": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date":   {"$ifNull": ["$createdDate", datetime(1970, 1, 1)]},
                    }
                },
                "totalAmount":    1,
                "discountAmount": 1,
            }
        },
        {
            "$group": {
                "_id":       "$dateStr",
                "revenue":   {"$sum": "$totalAmount"},
                "orders":    {"$sum": 1},
                "discounts": {"$sum": {"$ifNull": ["$discountAmount", 0]}},
            }
        },
        {"$sort": {"_id": -1}},
        {"$limit": 7},
        {
            "$project": {
                "date":      "$_id",
                "revenue":   {"$round": ["$revenue",   0]},
                "orders":    1,
                "discounts": {"$round": ["$discounts", 0]},
                "_id":        0,
            }
        },
    ]

    facet_pipeline = [
        {"$match": base_match},
        {
            "$facet": {
                "invoices": [
                    {
                        "$group": {
                            "_id":            {"$ifNull": ["$invoiceNo", "$orderId"]},
                            "total_amount":   {"$sum": {"$ifNull": ["$totalAmount",   0]}},
                            "paid_amount":    {"$sum": {"$ifNull": ["$paidAmount",    0]}},
                            "pending_amount": {"$sum": {"$ifNull": ["$pendingAmount", 0]}},
                            "companyStatus":  {"$first": "$companyStatus"},
                        }
                    },
                    {
                        "$addFields": {
                            "invoice_amount_status": {
                                "$switch": {
                                    "branches": [
                                        {"case": {"$eq": ["$paid_amount", 0]},               "then": "pending"},
                                        {"case": {"$lt": ["$paid_amount", "$total_amount"]}, "then": "partial"},
                                    ],
                                    "default": "fully",
                                }
                            }
                        }
                    },
                ],
                "workflow_counts": [
                    {
                        "$group": {
                            "_id":       {"$ifNull": ["$invoiceNo", "$orderId"]},
                            "status":    {"$first": "$companyStatus"},
                            "amtStatus": {"$first": "$amountStatus"},
                        }
                    },
                    {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                ],
                "items": [
                    {"$match": search_match},
                    {
                        "$group": {
                            "_id": {
                                "$cond": {
                                    "if":   {"$and": [{"$ne": ["$invoiceNo", None]}, {"$ne": ["$invoiceNo", ""]}]},
                                    "then": "$invoiceNo",
                                    "else": "$orderId",
                                }
                            },
                            "invoiceNo":     {"$first": "$invoiceNo"},
                            "companyName":   {"$first": "$companyName"},
                            "phoneNumber":   {"$first": "$phoneNumber"},
                            "companyStatus": {"$first": "$companyStatus"},
                            "totalAmount":   {"$sum": {"$ifNull": ["$totalAmount",   0]}},
                            "paidAmount":    {"$sum": {"$ifNull": ["$paidAmount",    0]}},
                            "pendingAmount": {"$sum": {"$ifNull": ["$pendingAmount", 0]}},
                            "createdDate":   {"$min": "$createdDate"},
                            "docId":         {"$first": {"$toString": "$_id"}},
                        }
                    },
                    {
                        "$addFields": {
                            "paid_amount":  "$paidAmount",
                            "total_amount": "$totalAmount",
                            "invoice_amount_status": {
                                "$switch": {
                                    "branches": [
                                        {"case": {"$eq":  ["$paidAmount", 0]},              "then": "pending"},
                                        {"case": {"$lt":  ["$paidAmount", "$totalAmount"]}, "then": "partial"},
                                    ],
                                    "default": "fully",
                                }
                            },
                        }
                    },
                    *(
                        [{"$match": post_group_filter}]
                        if post_group_filter
                        else []
                    ),
                    {"$sort": {"createdDate": -1}},
                    {"$skip":  (page - 1) * limit},
                    {"$limit": limit},
                    {
                        "$project": {
                            "id":            "$docId",
                            "invoiceNo":     1,
                            "companyName":   1,
                            "phoneNumber":   1,
                            "companyStatus": 1,
                            "amountStatus":  "$invoice_amount_status",
                            "totalAmount":   {"$round": ["$totalAmount",   2]},
                            "paidAmount":    {"$round": ["$paidAmount",    2]},
                            "pendingAmount": {"$round": ["$pendingAmount", 2]},
                            "createdDate":   {
                                "$dateToString": {"format": "%Y-%m-%d", "date": "$createdDate"}
                            },
                            "_id": 0,
                        }
                    },
                ],
                "total_count": [
                    {"$match": search_match},
                    {
                        "$group": {
                            "_id": {
                                "$cond": {
                                    "if":   {"$and": [{"$ne": ["$invoiceNo", None]}, {"$ne": ["$invoiceNo", ""]}]},
                                    "then": "$invoiceNo",
                                    "else": "$orderId",
                                }
                            },
                            "paidAmount":    {"$sum": {"$ifNull": ["$paidAmount",  0]}},
                            "totalAmount":   {"$sum": {"$ifNull": ["$totalAmount", 0]}},
                            "companyStatus": {"$first": "$companyStatus"},
                        }
                    },
                    {
                        "$addFields": {
                            "invoice_amount_status": {
                                "$switch": {
                                    "branches": [
                                        {"case": {"$eq": ["$paidAmount", 0]},              "then": "pending"},
                                        {"case": {"$lt": ["$paidAmount", "$totalAmount"]}, "then": "partial"},
                                    ],
                                    "default": "fully",
                                }
                            }
                        }
                    },
                    *(
                        [{"$match": post_group_filter}]
                        if post_group_filter
                        else []
                    ),
                    {"$count": "total"},
                ],
            }
        },
    ]

    try:
        top_items_res, trend_res, facet_res = await gather(
            collection.aggregate(top_items_pipeline).to_list(length=5),
            collection.aggregate(trend_pipeline).to_list(length=7),
            collection.aggregate(facet_pipeline).to_list(length=1),
        )

        facet            = facet_res[0] if facet_res else {}
        invoices_list    = facet.get("invoices", [])
        workflow_list    = facet.get("workflow_counts", [])
        table_items      = facet.get("items", [])
        total_count_list = facet.get("total_count", [])
        total_count      = total_count_list[0]["total"] if total_count_list else 0

        total_amount  = sum(float(i.get("total_amount",   0)) for i in invoices_list)
        total_paid    = sum(float(i.get("paid_amount",    0)) for i in invoices_list)
        total_pending = sum(float(i.get("pending_amount", 0)) for i in invoices_list)
        total_orders  = len(invoices_list)

        fully_count   = sum(1 for i in invoices_list if i.get("invoice_amount_status") == "fully")
        partial_count = sum(1 for i in invoices_list if i.get("invoice_amount_status") == "partial")
        pending_count = sum(1 for i in invoices_list if i.get("invoice_amount_status") == "pending")

        wf_map          = {w["_id"]: w["count"] for w in workflow_list}
        collection_rate = round((total_paid / total_amount * 100) if total_amount > 0 else 0.0, 2)
        avg_transaction = round((total_amount / total_orders) if total_orders > 0 else 0.0, 2)

        return {
            "summary": {
                "total_orders":           total_orders,
                "total_amount":           round(total_amount,  2),
                "total_realized_revenue": round(total_paid,    2),
                "total_pending_amount":   round(total_pending, 2),
                "collection_rate":        collection_rate,
                "avg_transaction":        avg_transaction,
                "takeaway_count":         wf_map.get("takeaway",  0),
                "printed_count":          wf_map.get("printed",   0),
                "invoiced_count":         wf_map.get("invoiced",  0),
                "fully_paid_count":       fully_count,
                "partial_count":          partial_count,
                "pending_payment_count":  pending_count,
            },
            "top_selling_items": top_items_res,
            "revenue_trend":     trend_res,
            "items":             table_items,
            "total":             total_count,
            "page":              page,
            "limit":             limit,
            "total_pages":       (total_count + limit - 1) // limit if limit > 0 else 0,
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Dashboard error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PAYMENT TRACKING  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/payment-tracking", response_model=dict)
async def get_payment_tracking(
    customer:   Optional[str] = Query(None),
    start_date: Optional[str] = Query(None), # Expecting YYYY-MM-DD
    end_date:   Optional[str] = Query(None),   # Expecting YYYY-MM-DD
):
    collection = get_wholesale_collection()

    # ✅ LOGIC UPDATE: Filter by 'invoiced' status
    match: Dict = {"status": "active", "companyStatus": "invoiced"}

    if customer:
        match["companyName"] = {"$regex": customer, "$options": "i"}

    # ✅ FIX: Use deliveryDate for filtering revenue (more accurate for "realized" revenue)
    # You can switch this to "createdDate" or "invoicedDate" depending on business logic.
    if start_date or end_date:
        date_f: Dict = {}
        if start_date:
            # ✅ Start of the selected day (00:00:00)
            # We append 00:00:00 to ensure we get the very beginning of that day
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            date_f["$gte"] = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            
        if end_date:
            # ✅ End of the selected day (23:59:59.999999)
            # This ensures we capture records logged late in the evening on the end date
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            date_f["$lte"] = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # ✅ APPLYING FILTER TO deliveryDate
        match["deliveryDate"] = date_f

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id":           {"$ifNull": ["$invoiceNo", "$orderId"]},
                "total_revenue": {"$sum": "$totalAmount"},
                "total_paid":    {"$sum": "$paidAmount"},
                "total_pending": {"$sum": "$pendingAmount"},
            }
        },
        {
            "$group": {
                "_id":            None,
                "total_revenue":  {"$sum": "$total_revenue"},
                "total_paid":     {"$sum": "$total_paid"},
                "total_pending":  {"$sum": "$total_pending"},
                "total_invoices": {"$sum": 1},
            }
        },
    ]

    result = await collection.aggregate(pipeline).to_list(length=1)

    totals = {"revenue": 0.0, "paid": 0.0, "pending": 0.0, "collection_rate": 0.0}
    if result:
        d = result[0]
        totals["revenue"] = round(d.get("total_revenue", 0.0), 2)
        totals["paid"]    = round(d.get("total_paid",    0.0), 2)
        totals["pending"] = round(d.get("total_pending", 0.0), 2)
        if totals["revenue"] > 0:
            totals["collection_rate"] = round(totals["paid"] / totals["revenue"] * 100, 2)

    return {"totals": totals}


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER OPTIONS  — unchanged
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/customer-options")
async def get_customer_options(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    collection = get_wholesale_collection()
    query: Dict = {"status": "active"}
    if search:
        query["companyName"] = {"$regex": search, "$options": "i"}
    pipeline = [
        {"$match": query},
        {"$group": {"_id": "$companyName"}},
        {"$match": {"_id": {"$ne": None, "$ne": ""}}},
        {"$sort": {"_id": 1}},
        {"$skip": (page - 1) * limit},
        {"$limit": limit},
        {"$project": {"name": "$_id", "_id": 0}},
    ]
    count_pipeline = [
        {"$match": query},
        {"$group": {"_id": "$companyName"}},
        {"$count": "total"},
    ]
    results   = await collection.aggregate(pipeline).to_list(length=limit)
    count_res = await collection.aggregate(count_pipeline).to_list(length=1)
    total     = count_res[0]["total"] if count_res else 0
    return {
        "items": [r["name"] for r in results if r.get("name")],
        "total": total,
        "page":  page,
        "pages": (total + limit - 1) // limit if limit > 0 else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER LEDGER  — FIXED (running balance before date filter)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/customer-ledger/{company_name}")
async def get_customer_ledger(
    company_name: str,
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
):
    collection           = get_wholesale_collection()
    decoded_company_name = urllib.parse.unquote(company_name)

    parsed_start = datetime.fromisoformat(start_date) if start_date else None
    parsed_end   = None
    if end_date:
        parsed_end = datetime.fromisoformat(end_date)
        parsed_end = parsed_end.replace(hour=23, minute=59, second=59, microsecond=999999)

    filter_query = {
        "companyName":   decoded_company_name,
        "companyStatus": "invoiced",
    }

    orders = await collection.find(filter_query).sort("createdDate", 1).to_list(length=1000)

    if not orders:
        return {
            "summary": {"total_billed": 0, "total_paid": 0, "current_outstanding": 0},
            "ledger":  [],
        }

    # Group by invoice, deduplicate payments — same logic as before
    invoice_map: Dict = {}
    for order in orders:
        invoice_no = order.get("invoiceNo") or order.get("orderId", "N/A")
        if invoice_no not in invoice_map:
            invoice_map[invoice_no] = {
                "invoice_no":        invoice_no,
                "date":              order.get("createdDate"),
                "total":             0,
                "payment_history":   [],
                "seen_payment_keys": set(),
            }
        invoice_map[invoice_no]["total"] += order.get("totalAmount", 0)

        for pmt in order.get("paymentHistory", []):
            pmt_amt   = pmt.get("amount", 0)
            pmt_mode  = pmt.get("mode", "N/A")
            pmt_date  = pmt.get("date")
            dedup_key = f"{pmt_date}_{pmt_mode}_{pmt_amt}"
            if dedup_key in invoice_map[invoice_no]["seen_payment_keys"]:
                continue
            invoice_map[invoice_no]["seen_payment_keys"].add(dedup_key)
            invoice_map[invoice_no]["payment_history"].append(
                {"mode": pmt_mode, "amount": pmt_amt, "date": pmt_date}
            )

    raw_events: List = []
    for inv in invoice_map.values():
        inv_date = inv["date"]
        if isinstance(inv_date, str):
            try:    inv_date = datetime.fromisoformat(inv_date)
            except: inv_date = None

        raw_events.append({
            "date":        inv_date.isoformat() if inv_date else None,
            "type":        "Invoice",
            "ref_id":      inv["invoice_no"],
            "description": f"Invoice for {decoded_company_name}",
            "debit":       inv["total"],
            "credit":      0,
        })

        for pmt in inv["payment_history"]:
            pmt_date = pmt["date"]
            if isinstance(pmt_date, str):
                try:    pmt_date = datetime.fromisoformat(pmt_date).isoformat()
                except: pmt_date = inv_date.isoformat() if inv_date else None

            raw_events.append({
                "date":        pmt_date,
                "type":        "Payment",
                "ref_id":      pmt["mode"],
                "description": f"Payment via {pmt['mode']}",
                "debit":       0,
                "credit":      pmt["amount"],
            })

    raw_events.sort(key=lambda x: x["date"] if x["date"] else "")

    # ✅ FIX: calculate running balance over ALL events first
    running_balance = 0.0
    all_events_with_balance = []
    for event in raw_events:
        running_balance += event["debit"]
        running_balance -= event["credit"]
        all_events_with_balance.append({**event, "balance": running_balance})

    # ✅ FIX: then filter for display only — balance values are already correct
    ledger_entries = []
    for event in all_events_with_balance:
        event_date_str = event["date"]
        if event_date_str and (parsed_start or parsed_end):
            try:
                event_dt = datetime.fromisoformat(event_date_str)
                if parsed_start and event_dt < parsed_start:
                    continue
                if parsed_end and event_dt > parsed_end:
                    continue
            except Exception:
                pass
        ledger_entries.append(event)

    total_billed = sum(e["debit"]  for e in ledger_entries if e["type"] == "Invoice")
    total_paid   = sum(e["credit"] for e in ledger_entries if e["type"] == "Payment")

    return {
        "summary": {
            "total_billed":        total_billed,
            "total_paid":          total_paid,
            # ✅ always the real outstanding over full history, not just filtered window
            "current_outstanding": running_balance,
        },
        "ledger": ledger_entries,
    }


@router.get("/customer-ledger-pdf/{company_name}")
async def download_customer_ledger_pdf(
    company_name: str,
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
):
    company_info         = await get_company_details()
    collection           = get_wholesale_collection()
    decoded_company_name = urllib.parse.unquote(company_name)

    parsed_start = datetime.fromisoformat(start_date) if start_date else None
    parsed_end   = None
    if end_date:
        parsed_end = datetime.fromisoformat(end_date)
        parsed_end = parsed_end.replace(hour=23, minute=59, second=59, microsecond=999999)

    filter_query = {
        "companyName":   decoded_company_name,
        "companyStatus": "invoiced",
    }
    orders = await collection.find(filter_query).sort("createdDate", 1).to_list(length=1000)

    if not orders:
        buffer = build_ledger_pdf(
            company_name, company_info, [], 0, 0, 0, start_date, end_date, 0
        )
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Ledger_{decoded_company_name}.pdf"},
        )

    invoice_map: Dict         = {}
    total_discount_all: float = 0.0

    for order in orders:
        invoice_no = order.get("invoiceNo") or order.get("orderId", "N/A")
        total_discount_all += order.get("discountAmount", 0) or 0

        if invoice_no not in invoice_map:
            invoice_map[invoice_no] = {
                "invoice_no":        invoice_no,
                "date":              order.get("createdDate"),
                "total":             0,
                "payment_history":   [],
                "seen_payment_keys": set(),
            }

        invoice_map[invoice_no]["total"] += order.get("totalAmount", 0)

        for pmt in order.get("paymentHistory", []):
            pmt_amt   = pmt.get("amount", 0)
            pmt_mode  = pmt.get("mode", "N/A")
            pmt_date  = pmt.get("date")
            dedup_key = f"{pmt_date}_{pmt_mode}_{pmt_amt}"
            if dedup_key in invoice_map[invoice_no]["seen_payment_keys"]:
                continue
            invoice_map[invoice_no]["seen_payment_keys"].add(dedup_key)
            invoice_map[invoice_no]["payment_history"].append(
                {"mode": pmt_mode, "amount": pmt_amt, "date": pmt_date}
            )

    raw_events = []
    for inv in invoice_map.values():
        inv_date = inv["date"]
        if isinstance(inv_date, str):
            try:    inv_date = datetime.fromisoformat(inv_date)
            except: inv_date = None

        raw_events.append({
            "date":        inv_date,
            "type":        "Invoice",
            "ref_id":      inv["invoice_no"],
            "description": f"Invoice for {decoded_company_name}",
            "debit":       inv["total"],
            "credit":      0,
        })

        for pmt in inv["payment_history"]:
            pmt_date = pmt["date"]
            if isinstance(pmt_date, str):
                try:    pmt_date = datetime.fromisoformat(pmt_date)
                except: pmt_date = inv_date

            raw_events.append({
                "date":        pmt_date,
                "type":        "Payment",
                "ref_id":      pmt["mode"],
                "description": f"Payment via {pmt['mode']}",
                "debit":       0,
                "credit":      pmt["amount"],
            })

    raw_events.sort(key=lambda x: x["date"] if x["date"] else datetime.min)

    # ✅ FIX: full running balance before date filter
    running_balance = 0.0
    all_events_with_balance = []
    for event in raw_events:
        running_balance += event["debit"]
        running_balance -= event["credit"]
        all_events_with_balance.append({**event, "balance": running_balance})

    # ✅ FIX: filter for display only
    ledger_entries = []
    for event in all_events_with_balance:
        event_date = event["date"]
        if event_date and (parsed_start or parsed_end):
            try:
                event_dt = (
                    event_date if isinstance(event_date, datetime)
                    else datetime.fromisoformat(str(event_date))
                )
                if parsed_start and event_dt < parsed_start:
                    continue
                if parsed_end and event_dt > parsed_end:
                    continue
            except Exception:
                pass
        ledger_entries.append(event)

    total_billed = sum(e["debit"]  for e in ledger_entries if e["type"] == "Invoice")
    total_paid   = sum(e["credit"] for e in ledger_entries if e["type"] == "Payment")

    buffer = build_ledger_pdf(
        company_name,
        company_info,
        ledger_entries,
        total_billed,
        total_paid,
        running_balance,   # ✅ full outstanding always
        start_date,
        end_date,
        total_discount_amount=total_discount_all,
    )

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Ledger_{decoded_company_name}.pdf"},
    )


@router.get("/customer-ledger-csv/{company_name}")
async def download_customer_ledger_csv(
    company_name: str,
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
):
    collection           = get_wholesale_collection()
    decoded_company_name = urllib.parse.unquote(company_name)

    parsed_start = datetime.fromisoformat(start_date) if start_date else None
    parsed_end   = None
    if end_date:
        parsed_end = datetime.fromisoformat(end_date)
        parsed_end = parsed_end.replace(hour=23, minute=59, second=59, microsecond=999999)

    filter_query = {
        "companyName":   decoded_company_name,
        "companyStatus": "invoiced",
    }
    orders = await collection.find(filter_query).sort("createdDate", 1).to_list(length=1000)

    invoice_map: Dict = {}
    for order in orders:
        invoice_no = order.get("invoiceNo") or order.get("orderId", "N/A")
        if invoice_no not in invoice_map:
            invoice_map[invoice_no] = {
                "invoice_no":        invoice_no,
                "date":              order.get("createdDate"),
                "total":             0,
                "payment_history":   [],
                "seen_payment_keys": set(),
            }
        invoice_map[invoice_no]["total"] += order.get("totalAmount", 0)

        for pmt in order.get("paymentHistory", []):
            pmt_amt   = pmt.get("amount", 0)
            pmt_mode  = pmt.get("mode", "N/A")
            pmt_date  = pmt.get("date")
            dedup_key = f"{pmt_date}_{pmt_mode}_{pmt_amt}"
            if dedup_key in invoice_map[invoice_no]["seen_payment_keys"]:
                continue
            invoice_map[invoice_no]["seen_payment_keys"].add(dedup_key)
            invoice_map[invoice_no]["payment_history"].append(
                {"mode": pmt_mode, "amount": pmt_amt, "date": pmt_date}
            )

    raw_events = []
    for inv in invoice_map.values():
        inv_date = inv["date"]
        if isinstance(inv_date, str):
            try:    inv_date = datetime.fromisoformat(inv_date)
            except: inv_date = None

        raw_events.append({
            "date":        inv_date,
            "type":        "Invoice",
            "ref_id":      inv["invoice_no"],
            "description": f"Invoice {inv['invoice_no']}",
            "debit":       inv["total"],
            "credit":      0,
        })

        for pmt in inv["payment_history"]:
            pmt_date = pmt["date"]
            if isinstance(pmt_date, str):
                try:    pmt_date = datetime.fromisoformat(pmt_date)
                except: pmt_date = inv_date

            raw_events.append({
                "date":        pmt_date,
                "type":        "Payment",
                "ref_id":      pmt["mode"],
                "description": f"Payment via {pmt['mode']}",
                "debit":       0,
                "credit":      pmt["amount"],
            })

    raw_events.sort(key=lambda x: x["date"] if x["date"] else datetime.min)

    # ✅ FIX: full running balance before date filter
    running_balance = 0.0
    all_events_with_balance = []
    for event in raw_events:
        running_balance += event["debit"]
        running_balance -= event["credit"]
        all_events_with_balance.append({**event, "balance": running_balance})

    # ✅ FIX: filter for display only
    ledger_data = []
    for event in all_events_with_balance:
        event_date = event["date"]
        if event_date and (parsed_start or parsed_end):
            try:
                event_dt = (
                    event_date if isinstance(event_date, datetime)
                    else datetime.fromisoformat(str(event_date))
                )
                if parsed_start and event_dt < parsed_start:
                    continue
                if parsed_end and event_dt > parsed_end:
                    continue
            except Exception:
                pass
        ledger_data.append({
            "Date":          event["date"],
            "Type":          event["type"],
            "Reference":     event["ref_id"],
            "Description":   event["description"],
            "Debit (Rs.)":   event["debit"],
            "Credit (Rs.)":  event["credit"],
            "Balance (Rs.)": event["balance"],
        })

    df = pd.DataFrame(ledger_data)
    if not df.empty:
        df.sort_values(by=["Date"], inplace=True)

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine="xlsxwriter")
    df.to_excel(writer, index=False, sheet_name="Ledger")

    workbook  = writer.book
    worksheet = writer.sheets["Ledger"]

    # ─────────────────────────────────────────────────────────────
    # 1. DEFINE ATTRACTIVE FORMATS
    # ─────────────────────────────────────────────────────────────

    # --- Header Format (Pink & Professional) ---
    header_format = workbook.add_format({
        "bold": True, 
        "font_name": "Arial",
        "font_size": 12,
        "font_color": "#FFFFFF",          # White text
        "bg_color": "#b43880",            # Primary Pink
        "border": 1, 
        "border_color": "#8e2e64",        # Darker Pink Border
        "align": "center",
        "valign": "vcenter",
        "text_wrap": True,
    })

    # --- Money Format (Numbers) ---
    money_format = workbook.add_format({
        "num_format": "#,##0.00",
        "font_name": "Arial",
        "font_size": 10,
        "valign": "vcenter",
        "border": 1, 
        "border_color": "#E0E0E0",        # Light Grey Border
        "text_wrap": True,
    })

    # --- Date Format ---
    date_format = workbook.add_format({
        "num_format": "dd-mm-yyyy",
        "font_name": "Arial",
        "font_size": 10,
        "valign": "vcenter",
        "border": 1, 
        "border_color": "#E0E0E0",
        "text_wrap": True,
    })

    # --- Text Format (Default) ---
    text_format = workbook.add_format({
        "font_name": "Arial",
        "font_size": 10,
        "valign": "vcenter",
        "border": 1,
        "border_color": "#E0E0E0",
        "text_wrap": True,
    })

    # --- Row Alternating Colors (Zebra Striping) ---
    # Pink tint for even rows, White for odd rows
    even_row_format = workbook.add_format({
        "font_name": "Arial",
        "font_size": 10,
        "valign": "vcenter",
        "border": 1,
        "border_color": "#E0E0E0",
        "bg_color": "#FFF0F5",            # Lavender Blush (Very light pink)
        "text_wrap": True,
    })
    
    # Currency format specifically for even rows
    even_row_money_format = workbook.add_format({
        "num_format": "#,##0.00",
        "font_name": "Arial",
        "font_size": 10,
        "valign": "vcenter",
        "border": 1,
        "border_color": "#E0E0E0",
        "bg_color": "#FFF0F5",            # Lavender Blush
    })
    
    # Date format specifically for even rows
    even_row_date_format = workbook.add_format({
        "num_format": "dd-mm-yyyy",
        "font_name": "Arial",
        "font_size": 10,
        "valign": "vcenter",
        "border": 1,
        "border_color": "#E0E0E0",
        "bg_color": "#FFF0F5",            # Lavender Blush
    })

    # ─────────────────────────────────────────────────────────────
    # 2. APPLY COLUMN WIDTHS
    # ─────────────────────────────────────────────────────────────
    worksheet.set_column("A:A", 18) # Date
    worksheet.set_column("B:B", 14) # Type
    worksheet.set_column("C:C", 20) # Reference
    worksheet.set_column("D:D", 35) # Description
    worksheet.set_column("E:E", 16) # Debit
    worksheet.set_column("F:F", 16) # Credit
    worksheet.set_column("G:G", 18) # Balance

    # Set a subtle grey background for the whole sheet for a premium feel
    worksheet.set_default_row(hide_unused_rows=False)

    # ─────────────────────────────────────────────────────────────
    # 3. WRITE HEADER
    # ─────────────────────────────────────────────────────────────
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)

    # ─────────────────────────────────────────────────────────────
    # 4. WRITE DATA WITH STYLING
    # ─────────────────────────────────────────────────────────────
    for row_num in range(1, len(df) + 1):
        # Determine if this is an even row for zebra striping
        is_even = (row_num % 2 == 0)
        
        # Select formats based on row parity
        curr_date_fmt = even_row_date_format if is_even else date_format
        curr_text_fmt  = even_row_format if is_even else text_format
        curr_money_fmt = even_row_money_format if is_even else money_format

        # Write Date (Column A)
        if pd.notna(df.iloc[row_num - 1]["Date"]):
            worksheet.write_datetime(row_num, 0, df.iloc[row_num - 1]["Date"], curr_date_fmt)
        else:
            worksheet.write(row_num, 0, "", curr_text_fmt)

        # Write Text Columns (B, C, D)
        for col_num in [1, 2, 3]:
            val = df.iloc[row_num - 1, col_num]
            worksheet.write(row_num, col_num, val if pd.notna(val) else "", curr_text_fmt)

        # Write Money Columns (E, F, G)
        worksheet.write(row_num, 4, df.iloc[row_num - 1]["Debit (Rs.)"],   curr_money_fmt)
        worksheet.write(row_num, 5, df.iloc[row_num - 1]["Credit (Rs.)"],  curr_money_fmt)
        worksheet.write(row_num, 6, df.iloc[row_num - 1]["Balance (Rs.)"], curr_money_fmt)

    # Freeze the top header row
    worksheet.freeze_panes(1, 0)
    
    # Add a filter to the header row (Dropdowns)
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

    writer.close()
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=Ledger_{decoded_company_name}.xlsx"
        },
    )