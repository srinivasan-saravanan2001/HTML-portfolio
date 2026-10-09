from asyncio import gather
from datetime import date, datetime, time as datetime_time, timedelta
from fastapi import APIRouter, HTTPException, Query, Response
from bson import ObjectId
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta
import urllib
from fastapi.responses import StreamingResponse
import pandas as pd
from pymongo import UpdateOne
from CustomerManagement.utils import get_customer_collection
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
    distribute_integer,
)
from .pdf_generator import _build_invoice_pdf, build_ledger_pdf, build_order_pdf

router = APIRouter()


async def _batch_fetch_customers(company_ids: List[str]) -> Dict[str, Any]:
    """Single query to fetch all needed customers; returns {customerId: doc}."""
    if not company_ids:
        return {}
    customer_map: Dict[str, Any] = {}
    async for cust in get_customer_collection().find(
        {"customerId": {"$in": company_ids}, "status": "customer"},
        {"customerId": 1, "customerName": 1, "address": 1, "customerPhoneNumber": 1},
    ):
        customer_map[cust["customerId"]] = cust
    return customer_map


def _apply_customer(doc: Dict, cust: Optional[Dict]) -> None:
    """Mutates doc in-place with live customer data if available."""
    if not cust:
        return
    doc["companyName"] = cust.get("customerName",        doc.get("companyName", ""))
    doc["address"]     = cust.get("address",             doc.get("address", ""))
    doc["phoneNumber"] = cust.get("customerPhoneNumber", doc.get("phoneNumber", ""))


def _iso(val: Any) -> Optional[str]:
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, str):
        return val
    return None


def _dedup_payment_history(raw_arrays: List) -> List[Dict]:
    """Flatten, de-duplicate and sort payment history arrays."""
    seen: set = set()
    history: List[Dict] = []
    for sub in raw_arrays:
        entries = sub if isinstance(sub, list) else ([sub] if sub else [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = f"{entry.get('date')}_{entry.get('mode')}_{entry.get('amount')}"
            if key in seen:
                continue
            seen.add(key)
            rounded = dict(entry)
            rounded["amount"] = round_amount(entry.get("amount", 0))
            history.append(rounded)
    history.sort(key=lambda e: e.get("date", "") or "")
    return history

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
    data["chargeAmount"]       = round_amount(data.get("chargeAmount", 0))

    if "items" in data and isinstance(data["items"], list):
        data["items"] = [round_item_amounts(i) for i in data["items"]]

    data["orderId"]        = await generate_order_id(collection)
    data["pendingAmount"]  = round_amount(data["totalAmount"] - data["paidAmount"])
    data["createdDate"]    = datetime.utcnow()
    data["invoicedDate"]   = None
    data["fullyPaidDate"]  = None
    data["status"]         = "active"
    data["companyStatus"]  = "order"
    data["invoiceNo"]      = None
    data["amountStatus"]   = calculate_amount_status(data["paidAmount"], data["totalAmount"])
    data["paymentHistory"] = []

    result   = await collection.insert_one(data)
    new_item = await collection.find_one({"_id": result.inserted_id})
    return serialize_item(new_item)

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
    items_page: int = Query(1, ge=1),
    items_limit: int = Query(5, ge=1, le=100),
    customer_id: Optional[str] = Query(None),
):
    collection = get_wholesale_collection()
    filter_query: Dict = {}

    if status:                  filter_query["status"] = status
    if company_status:          filter_query["companyStatus"] = company_status
    if amount_status:           filter_query["amountStatus"] = amount_status
    if exclude_company_status:  filter_query["companyStatus"] = {"$ne": exclude_company_status}
    if search:                  filter_query["companyName"] = {"$regex": search, "$options": "i"}
    if item:                    filter_query["items.varianceName"] = {"$regex": item, "$options": "i"}
    if customer_id:             filter_query["companyId"] = customer_id

    if start_date or end_date:
        date_filter: Dict = {}
        if start_date:
            date_filter["$gte"] = datetime.fromisoformat(start_date)
        if end_date:
            end_datetime = datetime.fromisoformat(end_date)
            end_datetime = end_datetime.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter["$lte"] = end_datetime
        filter_query[date_field] = date_filter

    sort_direction = -1 if sort_order == "desc" else 1
    total_count_coro = collection.count_documents(filter_query)
    cursor = (
        collection.find(filter_query)
        .sort(sort_by, sort_direction)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    raw_items_coro = cursor.to_list(length=limit)

    total_count, raw_items = await gather(total_count_coro, raw_items_coro)
    company_ids  = list({doc.get("companyId") for doc in raw_items if doc.get("companyId")})
    customer_map = await _batch_fetch_customers(company_ids)

    items_skip        = (items_page - 1) * items_limit
    total_item_pages_cache: Dict[int, int] = {}

    result_items = []
    for doc in raw_items:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
        doc = round_order_amounts(doc)

        for field in ["createdDate", "invoicedDate", "fullyPaidDate", "deliveryDate"]:
            if field in doc and isinstance(doc[field], datetime):
                doc[field] = doc[field].isoformat()

        _apply_customer(doc, customer_map.get(doc.get("companyId", "")))

        all_sub_items: list = doc.get("items", [])
        items_total   = len(all_sub_items)
        sliced_items  = all_sub_items[items_skip: items_skip + items_limit]
        total_pages   = (items_total + items_limit - 1) // items_limit if items_limit > 0 else 1

        doc["items"]             = sliced_items
        doc["items_total"]       = items_total
        doc["items_page"]        = items_page
        doc["items_limit"]       = items_limit
        doc["items_total_pages"] = total_pages
        result_items.append(doc)

    return {
        "items":       result_items,
        "total":       total_count,
        "page":        page,
        "limit":       limit,
        "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,
    }


@router.get("/items-page/{item_id}", response_model=dict)
async def get_order_items_page(
    item_id: str,
    items_page: int = Query(1, ge=1),
    items_limit: int = Query(5, ge=1, le=100),
):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")

    doc = await collection.find_one({"_id": ObjectId(item_id)}, {"items": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")

    all_items:  list = doc.get("items", [])
    items_total      = len(all_items)
    items_skip       = (items_page - 1) * items_limit
    sliced           = all_items[items_skip: items_skip + items_limit]
    total_pages      = (items_total + items_limit - 1) // items_limit if items_limit > 0 else 1
    has_more         = (items_page * items_limit) < items_total

    return {
        "items":             sliced,
        "items_total":       items_total,
        "items_page":        items_page,
        "items_limit":       items_limit,
        "items_total_pages": total_pages,
        "has_more":          has_more,
    }


@router.get("/invoiced", response_model=dict)
async def get_invoiced_items(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    company_name: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_field: Optional[str] = Query("createdDate"),
    sort_by: Optional[str] = Query("createdDate"),
    sort_order: Optional[str] = Query("desc"),
    order_page: int = Query(1, ge=1),
    order_limit: int = Query(2, ge=1, le=50),
):
    collection = get_wholesale_collection()

    filter_query: Dict = {"companyStatus": "invoiced", "status": "active"}
    if company_name:  filter_query["companyName"] = company_name
    if customer_id:   filter_query["companyId"]   = customer_id

    db_date_field = date_field
    if date_field == "invoiceDate":   db_date_field = "createdDate"
    elif date_field == "dueDate":     db_date_field = "deliveryDate"
    elif date_field == "invoicedDate": db_date_field = "invoicedDate"

    if start_date or end_date:
        date_filter: Dict = {}
        if start_date:
            date_filter["$gte"] = datetime.fromisoformat(start_date)
        if end_date:
            end_datetime = datetime.fromisoformat(end_date)
            end_datetime = end_datetime.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter["$lte"] = end_datetime
        filter_query[db_date_field] = date_filter

    db_sort_by = sort_by
    if sort_by == "invoiceDate":   db_sort_by = "createdDate"
    elif sort_by == "dueDate":     db_sort_by = "deliveryDate"
    elif sort_by == "invoicedDate": db_sort_by = "invoicedDate"

    sort_direction = -1 if sort_order == "desc" else 1

    base_pipeline = [
        {"$match": filter_query},
        {"$sort": {db_sort_by: sort_direction}},
        {
            "$group": {
                "_id": "$invoiceNo",
                "invoiceNo":              {"$first": "$invoiceNo"},
                "companyId":              {"$first": "$companyId"},
                "companyName":            {"$first": "$companyName"},
                "address":                {"$first": "$address"},
                "phoneNumber":            {"$first": "$phoneNumber"},
                "invoicedDate":           {"$first": "$invoicedDate"},
                "createdDate":            {"$first": "$createdDate"},
                "deliveryDate":           {"$first": "$deliveryDate"},
                "paymentMode":            {"$first": "$paymentMode"},
                "paymentHistoryArrays":   {"$push": "$paymentHistory"},
                "totalAmount":            {"$sum": {"$ifNull": ["$totalAmount",   0]}},
                "paidAmount":             {"$sum": {"$ifNull": ["$paidAmount",    0]}},
                "grossAmount":            {"$sum": {"$ifNull": ["$grossAmount",   0]}},
                "discountAmount":         {"$sum": {"$ifNull": ["$discountAmount",0]}},
                "chargeAmount":           {"$sum": {"$ifNull": ["$chargeAmount",  0]}},
                "orders": {
                    "$push": {
                        "id":            {"$toString": "$_id"},
                        "orderId":       "$orderId",
                        "items":         "$items",
                        "totalAmount":   "$totalAmount",
                        "paidAmount":    "$paidAmount",
                        "pendingAmount": "$pendingAmount",
                        "grossAmount":   "$grossAmount",
                        "discountAmount":"$discountAmount",
                        "chargeAmount":  "$chargeAmount",
                        "remarks":       "$remarks",
                        "amountStatus":  "$amountStatus",
                        "createdDate": {
                            "$dateToString": {
                                "format": "%Y-%m-%dT%H:%M:%S",
                                "date": {"$ifNull": ["$createdDate", datetime(1970, 1, 1)]}
                            }
                        },
                        "deliveryDate": {
                            "$dateToString": {
                                "format": "%Y-%m-%dT%H:%M:%S",
                                "date": {"$ifNull": ["$deliveryDate", datetime(1970, 1, 1)]}
                            }
                        },
                    }
                },
                "amountStatus": {"$first": "$amountStatus"},
                "id":           {"$first": {"$toString": "$_id"}},
            }
        },
        {"$addFields": {"pendingAmount": {"$subtract": ["$totalAmount", "$paidAmount"]}}},
        {"$match": {"pendingAmount": {"$gt": 0}}},
        {"$sort": {"invoiceNo": sort_direction}},
    ]

    count_pipeline = base_pipeline + [{"$count": "total"}]
    paged_pipeline = base_pipeline + [{"$skip": (page - 1) * limit}, {"$limit": limit}]

    count_result, raw_groups = await gather(
        collection.aggregate(count_pipeline).to_list(length=1),
        collection.aggregate(paged_pipeline).to_list(length=limit),
    )
    total_count = count_result[0]["total"] if count_result else 0

    # Batch customer lookup for this page
    company_ids  = list({g.get("companyId") for g in raw_groups if g.get("companyId")})
    customer_map = await _batch_fetch_customers(company_ids)

    order_skip = (order_page - 1) * order_limit
    result_items = []
    for i, grp in enumerate(raw_groups):
        total   = round_amount(grp.get("totalAmount",   0))
        paid    = round_amount(grp.get("paidAmount",    0))
        pending = round_amount(grp.get("pendingAmount", 0))

        if paid <= 0:         amt_status = "Pending"
        elif paid < total:    amt_status = "Partial"
        else:                 amt_status = "Fully"

        live_company_name = grp.get("companyName", "")
        live_address      = grp.get("address",     "")
        live_phone        = grp.get("phoneNumber",  "")
        cust = customer_map.get(grp.get("companyId", ""))
        if cust:
            live_company_name = cust.get("customerName",        live_company_name)
            live_address      = cust.get("address",             live_address)
            live_phone        = cust.get("customerPhoneNumber", live_phone)

        all_history = _dedup_payment_history(grp.get("paymentHistoryArrays", []))

        all_orders        = grp.get("orders", [])
        total_orders      = len(all_orders)
        paged_orders      = all_orders[order_skip: order_skip + order_limit]
        order_total_pages = (total_orders + order_limit - 1) // order_limit if order_limit > 0 else 1

        result_items.append({
            "id":                 grp.get("id"),
            "sNo":                (page - 1) * limit + i + 1,
            "invoiceNumber":      grp.get("invoiceNo", "N/A"),
            "invoiceNo":          grp.get("invoiceNo", "N/A"),
            "companyName":        live_company_name,
            "address":            live_address,
            "phoneNumber":        live_phone,
            "orders":             paged_orders,
            "orders_total":       total_orders,
            "orders_page":        order_page,
            "orders_limit":       order_limit,
            "orders_total_pages": order_total_pages,
            "invoiceDate":        _iso(grp.get("createdDate")),
            "deliveryDate":       _iso(grp.get("deliveryDate")),
            "invoicedDate":       _iso(grp.get("invoicedDate")),
            "totalAmount":        total,
            "paidAmount":         paid,
            "pendingAmount":      pending,
            "status":             amt_status,
            "paymentMethod":      grp.get("paymentMode", ""),
            "paymentHistory":     all_history,
            "createdDate":        _iso(grp.get("createdDate")),
            "grossAmount":        round_amount(grp.get("grossAmount",    0)),
            "discountAmount":     round_amount(grp.get("discountAmount", 0)),
            "chargeAmount":       round_amount(grp.get("chargeAmount",   0)),
        })

    return {
        "items":       result_items,
        "total":       total_count,
        "page":        page,
        "limit":       limit,
        "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,
    }



@router.get("/fully-paid", response_model=dict)
async def get_fully_paid_items(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    company_name: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_field: Optional[str] = Query("fullyPaidDate"),
    sort_by: Optional[str] = Query("fullyPaidDate"),
    sort_order: Optional[str] = Query("desc"),
    cursor: Optional[str] = Query(None),
    order_page: int = Query(1, ge=1),
    order_limit: int = Query(5, ge=1, le=50),
):
    collection = get_wholesale_collection()
    filter_query: Dict = {"status": "active", "companyStatus": "invoiced"}

    if company_name: filter_query["companyName"] = company_name
    if customer_id:  filter_query["companyId"]   = customer_id

    if start_date or end_date:
        date_filter: Dict = {}
        if start_date:
            date_filter["$gte"] = datetime.fromisoformat(start_date)
        if end_date:
            end_datetime = datetime.fromisoformat(end_date)
            end_datetime = end_datetime.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter["$lte"] = end_datetime
        filter_query[date_field] = date_filter

    sort_direction   = -1 if sort_order == "desc" else 1
    is_scroll_mode   = bool(cursor and ObjectId.is_valid(cursor))
    if is_scroll_mode:
        filter_query["_id"] = {"$lt": ObjectId(cursor)}

    base_pipeline = [
        {"$match": filter_query},
        {"$sort": {"_id": sort_direction}},
        *(  [{"$limit": limit}] if is_scroll_mode else [] ),
        {
            "$group": {
                "_id":                  "$invoiceNo",
                "invoiceNo":            {"$first": "$invoiceNo"},
                "companyId":            {"$first": "$companyId"},
                "companyName":          {"$first": "$companyName"},
                "address":              {"$first": "$address"},
                "phoneNumber":          {"$first": "$phoneNumber"},
                "invoicedDate":         {"$first": "$invoicedDate"},
                "createdDate":          {"$first": "$createdDate"},
                "deliveryDate":         {"$first": "$deliveryDate"},
                "fullyPaidDate":        {"$max":   "$fullyPaidDate"},
                "paymentMode":          {"$first": "$paymentMode"},
                "paymentHistoryArrays": {"$push":  "$paymentHistory"},
                "totalAmount":          {"$sum":   {"$ifNull": ["$totalAmount",         0]}},
                "paidAmount":           {"$sum":   {"$ifNull": ["$paidAmount",          0]}},
                "companyStatus":        {"$first": "$companyStatus"},
                "grossAmount":          {"$sum":   {"$ifNull": ["$grossAmount",         0]}},
                "discountPercentage":   {"$first": "$discountPercentage"},
                "discountValue":        {"$first": "$discountValue"},
                "discountAmount":       {"$sum":   {"$ifNull": ["$discountAmount",      0]}},
                "chargeAmount":         {"$sum":   {"$ifNull": ["$chargeAmount",        0]}},
                "orders": {
                    "$push": {
                        "id":            {"$toString": "$_id"},
                        "orderId":       "$orderId",
                        "items":         "$items",
                        "totalAmount":   "$totalAmount",
                        "paidAmount":    "$paidAmount",
                        "pendingAmount": "$pendingAmount",
                        "grossAmount":   "$grossAmount",
                        "discountAmount":"$discountAmount",
                        "chargeAmount":  "$chargeAmount",
                        "remarks":       "$remarks",
                        "amountStatus":  "$amountStatus",
                        "createdDate": {
                            "$dateToString": {
                                "format": "%Y-%m-%dT%H:%M:%S",
                                "date": {"$ifNull": ["$createdDate", datetime(1970, 1, 1)]}
                            }
                        },
                        "deliveryDate": {
                            "$dateToString": {
                                "format": "%Y-%m-%dT%H:%M:%S",
                                "date": {"$ifNull": ["$deliveryDate", datetime(1970, 1, 1)]}
                            }
                        },
                    }
                },
                "last_id": {"$last":  "$_id"},
                "id":      {"$first": {"$toString": "$_id"}},
            }
        },
        {
            "$addFields": {
                "pendingAmount": {"$subtract": ["$totalAmount", "$paidAmount"]},
                "invoice_amount_status": {
                    "$switch": {
                        "branches": [
                            {"case": {"$eq": ["$paidAmount", 0]},               "then": "pending"},
                            {"case": {"$lt": ["$paidAmount", "$totalAmount"]},  "then": "partial"},
                        ],
                        "default": "fully",
                    }
                }
            }
        },
        {"$match": {"invoice_amount_status": "fully"}},
        {"$sort": {sort_by: sort_direction}},
    ]

    if not is_scroll_mode:
        count_pipeline = base_pipeline + [{"$count": "total"}]
        paged_pipeline = base_pipeline + [{"$skip": (page - 1) * limit}, {"$limit": limit}]
        count_result, raw_groups = await gather(
            collection.aggregate(count_pipeline).to_list(length=1),
            collection.aggregate(paged_pipeline).to_list(length=limit),
        )
        total_count = count_result[0]["total"] if count_result else 0
    else:
        raw_groups  = await collection.aggregate(base_pipeline).to_list(length=limit)
        total_count = 0

    # Batch customer lookup
    company_ids  = list({g.get("companyId") for g in raw_groups if g.get("companyId")})
    customer_map = await _batch_fetch_customers(company_ids)

    order_skip = (order_page - 1) * order_limit
    result_items = []
    for i, grp in enumerate(raw_groups):
        total   = round_amount(grp.get("totalAmount",   0))
        paid    = round_amount(grp.get("paidAmount",    0))
        pending = round_amount(grp.get("pendingAmount", 0))

        live_company_name = grp.get("companyName", "")
        live_address      = grp.get("address",     "")
        live_phone        = grp.get("phoneNumber",  "")
        cust = customer_map.get(grp.get("companyId", ""))
        if cust:
            live_company_name = cust.get("customerName",        live_company_name)
            live_address      = cust.get("address",             live_address)
            live_phone        = cust.get("customerPhoneNumber", live_phone)

        all_history = _dedup_payment_history(grp.get("paymentHistoryArrays", []))

        all_orders        = grp.get("orders", [])
        total_orders      = len(all_orders)
        paged_orders      = all_orders[order_skip: order_skip + order_limit]
        order_total_pages = (total_orders + order_limit - 1) // order_limit if order_limit > 0 else 1

        result_items.append({
            "id":                 grp.get("id"),
            "sNo":                (page - 1) * limit + i + 1,
            "invoiceNumber":      grp.get("invoiceNo", "N/A"),
            "invoiceNo":          grp.get("invoiceNo", "N/A"),
            "companyId":          "",
            "companyName":        live_company_name,
            "address":            live_address,
            "phoneNumber":        live_phone,
            "orders":             paged_orders,
            "orders_total":       total_orders,
            "orders_page":        order_page,
            "orders_limit":       order_limit,
            "orders_total_pages": order_total_pages,
            "totalAmount":        total,
            "paidAmount":         paid,
            "pendingAmount":      pending,
            "createdDate":        _iso(grp.get("createdDate")),
            "deliveryDate":       _iso(grp.get("deliveryDate")),
            "invoicedDate":       _iso(grp.get("invoicedDate")),
            "fullyPaidDate":      _iso(grp.get("fullyPaidDate")),
            "status":             grp.get("status", ""),
            "companyStatus":      grp.get("companyStatus", ""),
            "amountStatus":       "fully",
            "paymentMode":        grp.get("paymentMode", ""),
            "paymentHistory":     all_history,
            "grossAmount":        round_amount(grp.get("grossAmount",       0)),
            "discountPercentage": round_percentage(grp.get("discountPercentage", 0)),
            "discountValue":      round_amount(grp.get("discountValue",     0)),
            "discountAmount":     round_amount(grp.get("discountAmount",    0)),
            "chargeAmount":       round_amount(grp.get("chargeAmount",      0)),
        })

    next_cursor = str(raw_groups[-1]["last_id"]) if raw_groups else None
    has_more = (
        len(raw_groups) == limit
        if is_scroll_mode
        else (page < (total_count + limit - 1) // limit if limit > 0 else False)
    )

    return {
        "items":       result_items,
        "total":       total_count,
        "page":        page,
        "limit":       limit,
        "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,
        "next_cursor": next_cursor,
        "has_more":    has_more,
    }

@router.get("/view/{item_id}", response_model=WholeSaleTakeaway)
async def get_takeaway(item_id: str):
    collection = get_wholesale_collection()
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid ID")

    item = await collection.find_one({"_id": ObjectId(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")

    _lookup_id = item.get("companyId")
    if _lookup_id:
        cust = await get_customer_collection().find_one(
            {"customerId": _lookup_id, "status": "customer"},
            {"customerName": 1, "address": 1, "customerPhoneNumber": 1},
        )
        _apply_customer(item, cust)

    if "phoneNumber" in item and not isinstance(item.get("phoneNumber"), str):
        item["phoneNumber"] = str(item.get("phoneNumber"))
    if "pendingAmount" not in item:
        item["pendingAmount"] = round_amount(item.get("totalAmount", 0) - item.get("paidAmount", 0))
    if "amountStatus" not in item:
        item["amountStatus"] = calculate_amount_status(
            item.get("paidAmount", 0), item.get("totalAmount", 0)
        )
    if "items" in item and isinstance(item["items"], list):
        item["items"] = [round_item_amounts(i) for i in item["items"]]

    item["id"] = str(item["_id"])
    del item["_id"]
    return item

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
    update_data["chargeAmount"]       = round_amount(update_data.get("chargeAmount", 0))

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

@router.patch("/update-paid/{invoice_no}")
async def update_paid_amount(invoice_no: str, paid_amount: float = Query(...)):
    collection = get_wholesale_collection()
    orders = await collection.find(
        {"invoiceNo": invoice_no, "status": "active"},
        {"_id": 1, "totalAmount": 1, "paidAmount": 1, "createdDate": 1},
    ).to_list(length=500)

    if not orders:
        raise HTTPException(status_code=404, detail="Invoice not found")

    order_totals         = [round_amount(o.get("totalAmount", 0)) for o in orders]
    total_invoice_amount = sum(order_totals)
    paid_int             = round_amount(paid_amount)

    if paid_int < 0 or paid_int > total_invoice_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid amount. Total invoice amount is {total_invoice_amount}",
        )

    current_total_paid = sum(round_amount(o.get("paidAmount", 0)) for o in orders)
    additional_amount  = paid_int - current_total_paid

    if additional_amount < 0:
        raise HTTPException(status_code=400, detail="Cannot reduce paid amount")

    if additional_amount == 0:
        return {
            "success": True,
            "message": "No change in paid amount",
            "data": {
                "invoiceNo":         invoice_no,
                "totalPaid":         paid_int,
                "totalPending":      total_invoice_amount - paid_int,
                "calculatedStatus":  "fully" if paid_int >= total_invoice_amount else "partial",
                "orderCount":        len(orders),
            },
        }

    invoice_is_fully_paid = paid_int >= total_invoice_amount
    invoice_pending       = total_invoice_amount - paid_int
    invoice_status        = "fully" if invoice_is_fully_paid else ("partial" if paid_int > 0 else "pending")
    primary_order         = sorted(orders, key=lambda o: o.get("createdDate") or datetime.min)[0]

    update_fields: Dict[str, Any] = {
        "invoicePaidAmount":    round_amount(paid_int),
        "invoicePendingAmount": round_amount(invoice_pending),
        "invoiceAmountStatus":  invoice_status,
    }
    if invoice_is_fully_paid:
        update_fields["fullyPaidDate"] = datetime.utcnow()

    await collection.update_one({"_id": primary_order["_id"]}, {"$set": update_fields})

    return {
        "success": True,
        "message": f"Paid amount updated: +{additional_amount} at invoice level",
        "data": {
            "invoiceNo":          invoice_no,
            "previousTotalPaid":  current_total_paid,
            "additionalAmount":   additional_amount,
            "totalPaid":          paid_int,
            "totalPending":       invoice_pending,
            "calculatedStatus":   invoice_status,
            "orderCount":         len(orders),
        },
    }


@router.patch("/update-payment-mode/{invoice_no}")
async def update_payment_mode(invoice_no: str, update_data: PaymentModeUpdate):
    collection = get_wholesale_collection()

    rounded_amount = round_amount(update_data.paid_amount or 0)
    orders = await collection.find(
        {"invoiceNo": invoice_no, "status": "active"},
        {"_id": 1, "totalAmount": 1, "paidAmount": 1, "createdDate": 1},
    ).to_list(length=500)

    if not orders:
        raise HTTPException(status_code=404, detail="Invoice not found")

    total_invoice_amount = sum(round_amount(o.get("totalAmount", 0)) for o in orders)
    current_paid         = sum(round_amount(o.get("paidAmount",  0)) for o in orders)
    new_paid             = min(current_paid + rounded_amount, total_invoice_amount)
    new_pending          = total_invoice_amount - new_paid
    is_fully_paid        = new_paid >= total_invoice_amount
    invoice_status       = "fully" if is_fully_paid else ("partial" if new_paid > 0 else "pending")
    now                  = datetime.utcnow()
    primary_order        = sorted(orders, key=lambda o: o.get("createdDate") or datetime.min)[0]

    history_entry = {
        "mode":   update_data.payment_mode,
        "amount": rounded_amount,
        "date":   now.isoformat(),
    }

    operations: List[UpdateOne] = []
    for order in orders:
        fields: Dict[str, Any] = {
            "paymentMode":    update_data.payment_mode,
            "pendingAmount":  round_amount(new_pending),
            "amountStatus":   invoice_status,
        }
        if order["_id"] == primary_order["_id"]:
            fields["paidAmount"] = round_amount(new_paid)
        if is_fully_paid:
            fields["fullyPaidDate"] = now
        operations.append(UpdateOne({"_id": order["_id"]}, {"$set": fields}))

    operations.append(
        UpdateOne({"_id": primary_order["_id"]}, {"$push": {"paymentHistory": history_entry}})
    )

    if operations:
        await collection.bulk_write(operations)

    return {
        "success": True,
        "message": "Payment recorded successfully at invoice level",
        "data": {
            "invoiceNo":        invoice_no,
            "paymentMode":      update_data.payment_mode,
            "paidAmount":       rounded_amount,
            "totalPaid":        new_paid,
            "totalPending":     new_pending,
            "calculatedStatus": invoice_status,
        },
    }

@router.post("/move-to-printed")
async def move_to_printed(item_ids: List[str]):
    collection  = get_wholesale_collection()
    valid_ids   = [ObjectId(i) for i in item_ids if ObjectId.is_valid(i)]
    if not valid_ids:
        raise HTTPException(status_code=404, detail="No items found or updated")

    await collection.update_many(
        {"_id": {"$in": valid_ids}},
        {"$set": {"companyStatus": "printed"}},
    )

    updated_cursor = collection.find({"_id": {"$in": valid_ids}})
    updated_docs   = await updated_cursor.to_list(length=len(valid_ids))
    updated_items  = [serialize_item(doc) for doc in updated_docs]

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
        raise HTTPException(status_code=400, detail="Can only move to invoiced from printed status")

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


# ──────────────────────────────────────────────────────────────────────────────
# UPDATED: Calculate Outstanding using Company ID (supports Invoiced & Printed)
# ──────────────────────────────────────────────────────────────────────────────

async def _get_company_total_outstanding(collection, company_id: str) -> float:
    """
    Calculates the total outstanding amount for a specific company ID 
    across all 'invoiced' and 'printed' orders.
    Groups by invoiceNo to ensure accurate billing aggregation.
    """
    if not company_id:
        return 0.0

    match: Dict[str, Any] = {
        "companyId":      company_id,  # Use ID for precise matching
        "companyStatus":  {"$in": ["invoiced", "printed"]},
        "status":         "active",
    }

    pipeline = [
        {"$match": match},
        # Group by Invoice/Order ID to get totals per bill
        {
            "$group": {
                "_id":          {"$ifNull": ["$invoiceNo", "$orderId"]},
                "total_amount": {"$sum": "$totalAmount"},
                "paid_amount":  {"$sum": "$paidAmount"},
            }
        },
        # Calculate pending per bill
        {
            "$addFields": {
                "invoice_pending": {"$subtract": ["$total_amount", "$paid_amount"]}
            }
        },
        # Sum up all pending amounts
        {
            "$group": {
                "_id": None,
                "total_outstanding": {"$sum": "$invoice_pending"},
            },
        },
    ]

    result = await collection.aggregate(pipeline).to_list(length=1)
    if result and result[0].get("total_outstanding"):
        return max(round(result[0]["total_outstanding"], 2), 0.0)
    return 0.0



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

    # --- CHANGED: Use companyId instead of companyName ---
    company_id = item.get("companyId", "")
    total_outstanding = await _get_company_total_outstanding(collection, company_id)
    
    company_info = {}
    pdf_bytes = build_order_pdf(item, company_info, previous_outstanding=total_outstanding)

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
    company_name: Optional[str] = None
    company_id: Optional[str] = None  # 1. Define variable for ID

    for item_id in item_ids:
        if not ObjectId.is_valid(item_id):
            continue
        await collection.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {
                "invoiceNo":     common_invoice_no,
                "companyStatus": "invoiced",
                "invoicedDate":  datetime.utcnow(),
            }},
        )
        item = await collection.find_one({"_id": ObjectId(item_id)})
        if item:
            # 2. Capture ID and Name from the first valid item
            if company_name is None:
                company_name = item.get("companyName", "")
            if company_id is None:
                company_id = item.get("companyId", "")
                
            items.append(serialize_item(item))

    if not items:
        raise HTTPException(status_code=404, detail="No items found")

    items.sort(key=lambda x: x.get("orderId", ""))
    total_invoice_amount = sum(float(i.get("totalAmount", 0)) for i in items)
    total_paid_amount    = sum(float(i.get("paidAmount",  0)) for i in items)
    total_pending_amount = total_invoice_amount - total_paid_amount

    if total_paid_amount >= total_invoice_amount:     amount_status = "fully"
    elif total_paid_amount == 0:                      amount_status = "pending"
    else:                                             amount_status = "partial"

    total_outstanding = await _get_company_total_outstanding(collection, company_id or "")
    
    company_info = {}
    pdf_bytes         = _build_invoice_pdf(
        items,
        common_invoice_no,
        company_info,
        paid_amount=total_paid_amount,
        pending_amount=total_pending_amount,
        amount_status=amount_status,
        previous_outstanding=total_outstanding,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{common_invoice_no}.pdf"},
    )


@router.post("/generate-invoice-with-payment/{invoice_no}")
async def generate_invoice_with_payment(invoice_no: str, paymentMode: Optional[str] = None):
    collection = get_wholesale_collection()
    orders = await collection.find({"invoiceNo": invoice_no, "status": "active"}).to_list(length=1000)
    if not orders:
        raise HTTPException(status_code=404, detail="Invoice not found")

    now          = datetime.utcnow()
    update_data: Dict[str, Any] = {"companyStatus": "invoiced", "invoicedDate": now}
    if paymentMode:
        update_data["paymentMode"] = paymentMode

    await collection.update_many({"invoiceNo": invoice_no, "status": "active"}, {"$set": update_data})
    orders = await collection.find({"invoiceNo": invoice_no, "status": "active"}).to_list(length=1000)

    total_invoice_amount = sum(round_amount(o.get("totalAmount", 0)) for o in orders)
    total_paid_amount    = sum(round_amount(o.get("paidAmount",  0)) for o in orders)
    total_pending_amount = total_invoice_amount - total_paid_amount
    is_fully_paid        = total_paid_amount >= total_invoice_amount

    if is_fully_paid:
        await collection.update_many(
            {"invoiceNo": invoice_no, "status": "active"},
            {"$set": {"amountStatus": "fully", "fullyPaidDate": now, "pendingAmount": 0}},
        )
        orders               = await collection.find({"invoiceNo": invoice_no, "status": "active"}).to_list(length=1000)
        total_pending_amount = 0

    items        = [serialize_item(dict(order)) for order in orders]
    items.sort(key=lambda x: x.get("orderId", ""))
    
    # --- CHANGED: Get companyId from the first order ---
    company_id = items[0].get("companyId", "") if items else ""
    company_name = items[0].get("companyName", "") if items else ""

    if is_fully_paid:              amount_status = "fully"
    elif total_paid_amount == 0:   amount_status = "pending"
    else:                          amount_status = "partial"

    # --- CHANGED: Pass company_id ---
    total_outstanding = await _get_company_total_outstanding(collection, company_id)
    company_info = {}
    pdf_bytes         = _build_invoice_pdf(
        items,
        invoice_no,
        company_info,
        paid_amount=total_paid_amount,
        pending_amount=total_pending_amount,
        amount_status=amount_status,
        previous_outstanding=total_outstanding,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition":  f"attachment; filename=Invoice_{invoice_no}.pdf",
            "X-Payment-Status":     amount_status,
            "X-Invoice-Number":     invoice_no,
        },
    )




@router.get("/dashboard-stats", response_model=dict)
async def get_dashboard_stats(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    collection = get_wholesale_collection()

    base_match: Dict[str, Any] = {
        "status": "active"
    }

    search_match: Dict[str, Any] = {
        "status": "active"
    }

    # Customer filter
    if customer_id:
        base_match["companyId"] = customer_id
        search_match["companyId"] = customer_id

    # createdDate filter
    if start_date or end_date:
        created_date_filter: Dict[str, Any] = {}

        if start_date:
            created_date_filter["$gte"] = datetime.combine(
                start_date,
                datetime_time.min,
            )

        if end_date:
            created_date_filter["$lt"] = datetime.combine(
                end_date + timedelta(days=1),
                datetime_time.min,
            )

        base_match["createdDate"] = created_date_filter
        search_match["createdDate"] = created_date_filter

    # Existing search behaviour remains unchanged.
    if search:
        search_filter = {
            "$or": [
                {
                    "companyName": {
                        "$regex": search,
                        "$options": "i",
                    }
                },
                {
                    "invoiceNo": {
                        "$regex": search,
                        "$options": "i",
                    }
                },
            ]
        }

        base_match.update(search_filter)
        search_match.update(search_filter)

    # ---------------------------------------------------------------
    # Existing transaction-level status filter used for trend chart.
    # There is NO facet stage anywhere in this endpoint.
    # ---------------------------------------------------------------
    transaction_post_filter: Dict[str, Any] = {}

    if status and status != "all":
        if status == "invoiced":
            transaction_post_filter = {
                "companyStatus": "invoiced"
            }
        elif status == "fully":
            transaction_post_filter = {
                "invoice_amount_status": "fully"
            }
        elif status == "partial":
            transaction_post_filter = {
                "invoice_amount_status": "partial"
            }
        elif status == "pending":
            transaction_post_filter = {
                "invoice_amount_status": "pending"
            }
        elif status == "realized":
            transaction_post_filter = {
                "paid_amount": {"$gt": 0}
            }

    chart_prefilter_stages: List = []

    if transaction_post_filter:
        chart_prefilter_stages = [
            {
                "$group": {
                    "_id": {
                        "$cond": {
                            "if": {
                                "$and": [
                                    {"$ne": ["$invoiceNo", None]},
                                    {"$ne": ["$invoiceNo", ""]},
                                ]
                            },
                            "then": "$invoiceNo",
                            "else": "$orderId",
                        }
                    },
                    "companyStatus": {"$first": "$companyStatus"},
                    "paid_amount": {
                        "$sum": {"$ifNull": ["$paidAmount", 0]}
                    },
                    "total_amount": {
                        "$sum": {"$ifNull": ["$totalAmount", 0]}
                    },
                    "document_ids": {"$push": "$_id"},
                }
            },
            {
                "$addFields": {
                    "invoice_amount_status": {
                        "$switch": {
                            "branches": [
                                {
                                    "case": {"$eq": ["$paid_amount", 0]},
                                    "then": "pending",
                                },
                                {
                                    "case": {
                                        "$lt": ["$paid_amount", "$total_amount"]
                                    },
                                    "then": "partial",
                                },
                            ],
                            "default": "fully",
                        }
                    }
                }
            },
            {"$match": transaction_post_filter},
            {"$unwind": "$document_ids"},
            {
                "$lookup": {
                    "from": "WholeSale",
                    "localField": "document_ids",
                    "foreignField": "_id",
                    "as": "orderDoc",
                }
            },
            {"$unwind": "$orderDoc"},
            {"$replaceRoot": {"newRoot": "$orderDoc"}},
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
                        "date": {
                            "$ifNull": ["$createdDate", datetime(1970, 1, 1)]
                        },
                    }
                },
                "totalAmount": 1,
                "discountAmount": 1,
            }
        },
        {
            "$group": {
                "_id": "$dateStr",
                "revenue": {
                    "$sum": {"$ifNull": ["$totalAmount", 0]}
                },
                "orders": {"$sum": 1},
                "discounts": {
                    "$sum": {"$ifNull": ["$discountAmount", 0]}
                },
            }
        },
        {"$sort": {"_id": -1}},
        {"$limit": 7},
        {
            "$project": {
                "date": "$_id",
                "revenue": {"$round": ["$revenue", 0]},
                "orders": 1,
                "discounts": {"$round": ["$discounts", 0]},
                "_id": 0,
            }
        },
    ]

    # ---------------------------------------------------------------
    # Existing dashboard summary behaviour.
    # Group by invoice/order first, exactly like the original endpoint,
    # but do it linearly instead of using facet stage.
    # ---------------------------------------------------------------
    summary_pipeline = [
        {"$match": base_match},
        {
            "$group": {
                "_id": {
                    "$cond": {
                        "if": {
                            "$and": [
                                {"$ne": ["$invoiceNo", None]},
                                {"$ne": ["$invoiceNo", ""]},
                            ]
                        },
                        "then": "$invoiceNo",
                        "else": "$orderId",
                    }
                },
                "total_amount": {
                    "$sum": {"$ifNull": ["$totalAmount", 0]}
                },
                "paid_amount": {
                    "$sum": {"$ifNull": ["$paidAmount", 0]}
                },
                "companyStatus": {"$first": "$companyStatus"},
            }
        },
        {
            "$addFields": {
                "pending_amount": {
                    "$subtract": ["$total_amount", "$paid_amount"]
                },
                "invoice_amount_status": {
                    "$switch": {
                        "branches": [
                            {
                                "case": {"$eq": ["$paid_amount", 0]},
                                "then": "pending",
                            },
                            {
                                "case": {
                                    "$lt": ["$paid_amount", "$total_amount"]
                                },
                                "then": "partial",
                            },
                        ],
                        "default": "fully",
                    }
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "total_orders": {"$sum": 1},
                "total_amount": {"$sum": "$total_amount"},
                "paid_amount": {"$sum": "$paid_amount"},
                "pending_amount": {"$sum": "$pending_amount"},
                "fully_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$invoice_amount_status", "fully"]},
                            1,
                            0,
                        ]
                    }
                },
                "partial_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$invoice_amount_status", "partial"]},
                            1,
                            0,
                        ]
                    }
                },
                "pending_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$invoice_amount_status", "pending"]},
                            1,
                            0,
                        ]
                    }
                },
                "takeaway_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$companyStatus", "takeaway"]},
                            1,
                            0,
                        ]
                    }
                },
                "printed_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$companyStatus", "printed"]},
                            1,
                            0,
                        ]
                    }
                },
                "invoiced_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$companyStatus", "invoiced"]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]

    # ---------------------------------------------------------------
    # Company-wise table.
    # One company = one row. Order/invoice numbers are NOT used as the
    # grouping key for the table.
    # ---------------------------------------------------------------
    company_group_stages: List = [
        {"$match": search_match},
        {
            "$group": {
                "_id": "$companyId",
                "companyId": {"$first": "$companyId"},
                "companyName": {"$first": "$companyName"},
                "phoneNumber": {"$first": "$phoneNumber"},
                "totalAmount": {
                    "$sum": {"$ifNull": ["$totalAmount", 0]}
                },
                "paidAmount": {
                    "$sum": {"$ifNull": ["$paidAmount", 0]}
                },
                "createdDate": {"$max": "$createdDate"},
                "firstCompanyStatus": {"$first": "$companyStatus"},
                "has_invoiced": {
                    "$max": {
                        "$cond": [
                            {"$eq": ["$companyStatus", "invoiced"]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$addFields": {
                "paid_amount": "$paidAmount",
                "total_amount": "$totalAmount",
                "pending_amount": {
                    "$max": [
                        {"$subtract": ["$totalAmount", "$paidAmount"]},
                        0,
                    ]
                },
                "invoice_amount_status": {
                    "$switch": {
                        "branches": [
                            {
                                "case": {"$eq": ["$paidAmount", 0]},
                                "then": "pending",
                            },
                            {
                                "case": {
                                    "$lt": ["$paidAmount", "$totalAmount"]
                                },
                                "then": "partial",
                            },
                        ],
                        "default": "fully",
                    }
                },
                "companyStatus": {
                    "$cond": [
                        {"$eq": ["$has_invoiced", 1]},
                        "invoiced",
                        "$firstCompanyStatus",
                    ]
                },
            }
        },
    ]

    # Status filter for the COMPANY-WISE table only.
    company_post_filter: Dict[str, Any] = {}

    if status and status != "all":
        if status == "invoiced":
            company_post_filter = {"has_invoiced": 1}
        elif status == "fully":
            company_post_filter = {"invoice_amount_status": "fully"}
        elif status == "partial":
            company_post_filter = {"invoice_amount_status": "partial"}
        elif status == "pending":
            company_post_filter = {"invoice_amount_status": "pending"}
        elif status == "realized":
            company_post_filter = {"paid_amount": {"$gt": 0}}

    table_pipeline = list(company_group_stages)

    if company_post_filter:
        table_pipeline.append({"$match": company_post_filter})

    table_pipeline.extend(
        [
            {"$sort": {"createdDate": -1, "companyName": 1}},
            {"$skip": (page - 1) * limit},
            {"$limit": limit},
            {
                "$project": {
                    "id": "$companyId",
                    "companyId": 1,
                    "companyName": 1,
                    "phoneNumber": 1,
                    "companyStatus": 1,
                    "amountStatus": "$invoice_amount_status",
                    "totalAmount": {"$round": ["$totalAmount", 2]},
                    "paidAmount": {"$round": ["$paidAmount", 2]},
                    "pendingAmount": {"$round": ["$pending_amount", 2]},
                    "createdDate": {
                        "$cond": [
                            {"$ne": ["$createdDate", None]},
                            {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$createdDate",
                                }
                            },
                            None,
                        ]
                    },
                    "_id": 0,
                }
            },
        ]
    )

    count_pipeline = list(company_group_stages)

    if company_post_filter:
        count_pipeline.append({"$match": company_post_filter})

    count_pipeline.append({"$count": "total"})

    try:
        # Independent aggregations run concurrently.
        # IMPORTANT: there is no facet stage in any of these pipelines.
        trend_res, summary_res, table_items, count_res = await gather(
            collection.aggregate(trend_pipeline).to_list(length=7),
            collection.aggregate(summary_pipeline).to_list(length=1),
            collection.aggregate(table_pipeline).to_list(length=limit),
            collection.aggregate(count_pipeline).to_list(length=1),
        )

        summary_data = summary_res[0] if summary_res else {}

        total_count = (
            int(count_res[0].get("total", 0))
            if count_res
            else 0
        )

        # Existing batch customer lookup remains unchanged.
        company_ids = list(
            {
                item.get("companyId")
                for item in table_items
                if item.get("companyId")
            }
        )

        customer_map = await _batch_fetch_customers(company_ids)

        for item in table_items:
            cust = customer_map.get(item.get("companyId", ""))
            if cust:
                item["companyName"] = cust.get(
                    "customerName",
                    item.get("companyName", ""),
                )
                item["phoneNumber"] = cust.get(
                    "customerPhoneNumber",
                    item.get("phoneNumber", ""),
                )

        total_orders = int(summary_data.get("total_orders", 0) or 0)
        total_amount = float(summary_data.get("total_amount", 0) or 0)
        total_paid = float(summary_data.get("paid_amount", 0) or 0)
        total_pending = float(summary_data.get("pending_amount", 0) or 0)

        collection_rate = round(
            (total_paid / total_amount * 100)
            if total_amount > 0
            else 0.0,
            2,
        )

        avg_transaction = round(
            (total_amount / total_orders)
            if total_orders > 0
            else 0.0,
            2,
        )

        return {
            "summary": {
                "total_orders": total_orders,
                "total_amount": round(total_amount, 2),
                "total_realized_revenue": round(total_paid, 2),
                "total_pending_amount": round(total_pending, 2),
                "collection_rate": collection_rate,
                "avg_transaction": avg_transaction,
                "takeaway_count": int(
                    summary_data.get("takeaway_count", 0) or 0
                ),
                "printed_count": int(
                    summary_data.get("printed_count", 0) or 0
                ),
                "invoiced_count": int(
                    summary_data.get("invoiced_count", 0) or 0
                ),
                "fully_paid_count": int(
                    summary_data.get("fully_count", 0) or 0
                ),
                "partial_count": int(
                    summary_data.get("partial_count", 0) or 0
                ),
                "pending_payment_count": int(
                    summary_data.get("pending_count", 0) or 0
                ),
            },
            "revenue_trend": trend_res,
            "items": table_items,
            "total": total_count,
            "page": page,
            "limit": limit,
            "total_pages": (
                (total_count + limit - 1) // limit
                if limit > 0
                else 0
            ),
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Dashboard error: {e}",
        )
# Add this endpoint to the SAME router file that already contains /dashboard-stats.
# It uses the existing imports/helpers in WholeSaleManagement/routes.py:
# router, Query, Optional, date, datetime, datetime_time, timedelta,
# Dict, Any, get_wholesale_collection, HTTPException.

@router.get("/dashboard-company-transactions", response_model=dict)
async def get_dashboard_company_transactions(
    company_id: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    """
    Paginated lazy-loaded drill-down for one company.

    The main dashboard stays grouped company-wise. This endpoint is called
    only when a company row is expanded. MongoDB performs the previous
    invoice/order grouping and pagination; the frontend only renders pages.

    `printed` workflow rows are returned as `order` for this transaction view.
    """
    from asyncio import gather

    collection = get_wholesale_collection()

    match_filter: Dict[str, Any] = {
        "status": "active",
        "companyId": company_id,
    }

    if start_date or end_date:
        created_date_filter: Dict[str, Any] = {}

        if start_date:
            created_date_filter["$gte"] = datetime.combine(
                start_date,
                datetime_time.min,
            )

        if end_date:
            created_date_filter["$lt"] = datetime.combine(
                end_date + timedelta(days=1),
                datetime_time.min,
            )

        match_filter["createdDate"] = created_date_filter

    transaction_key = {
        "$cond": {
            "if": {
                "$and": [
                    {"$ne": ["$invoiceNo", None]},
                    {"$ne": ["$invoiceNo", ""]},
                ]
            },
            "then": "$invoiceNo",
            "else": "$orderId",
        }
    }

    group_stage = {
        "$group": {
            "_id": transaction_key,
            "invoiceNo": {"$first": "$invoiceNo"},
            "orderId": {"$first": "$orderId"},
            "companyId": {"$first": "$companyId"},
            "companyName": {"$first": "$companyName"},
            "phoneNumber": {"$first": "$phoneNumber"},
            "companyStatus": {"$first": "$companyStatus"},
            "totalAmount": {"$sum": {"$ifNull": ["$totalAmount", 0]}},
            "paidAmount": {"$sum": {"$ifNull": ["$paidAmount", 0]}},
            "createdDate": {"$max": "$createdDate"},
            "docId": {"$first": {"$toString": "$_id"}},
        }
    }

    calculated_stage = {
        "$addFields": {
            # In this transaction table, a printed sales order is displayed
            # as Order. Other workflow statuses remain unchanged.
            "companyStatus": {
                "$cond": [
                    {"$eq": ["$companyStatus", "printed"]},
                    "order",
                    "$companyStatus",
                ]
            },
            "pendingAmount": {
                "$max": [
                    {"$subtract": ["$totalAmount", "$paidAmount"]},
                    0,
                ]
            },
            "amountStatus": {
                "$switch": {
                    "branches": [
                        {
                            "case": {"$eq": ["$paidAmount", 0]},
                            "then": "pending",
                        },
                        {
                            "case": {"$lt": ["$paidAmount", "$totalAmount"]},
                            "then": "partial",
                        },
                    ],
                    "default": "fully",
                }
            },
        }
    }

    project_stage = {
        "$project": {
            "_id": 0,
            "id": "$docId",
            "invoiceNo": 1,
            "orderId": 1,
            "companyId": 1,
            "companyName": 1,
            "phoneNumber": 1,
            "companyStatus": 1,
            "amountStatus": 1,
            "totalAmount": {"$round": ["$totalAmount", 2]},
            "paidAmount": {"$round": ["$paidAmount", 2]},
            "pendingAmount": {"$round": ["$pendingAmount", 2]},
            "createdDate": {
                "$cond": [
                    {"$ne": ["$createdDate", None]},
                    {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$createdDate",
                        }
                    },
                    None,
                ]
            },
        }
    }

    skip = (page - 1) * limit

    # Page query: grouping/calculation happen on MongoDB before skip/limit.
    items_pipeline = [
        {"$match": match_filter},
        group_stage,
        calculated_stage,
        {"$sort": {"createdDate": -1, "_id": -1}},
        {"$skip": skip},
        {"$limit": limit},
        project_stage,
    ]

    # Count grouped invoice/order records, not raw MongoDB documents.
    count_pipeline = [
        {"$match": match_filter},
        {"$group": {"_id": transaction_key}},
        {"$count": "total"},
    ]

    # Full-company financial summary stays accurate even though items are paged.
    summary_pipeline = [
        {"$match": match_filter},
        {
            "$group": {
                "_id": None,
                "total_amount": {"$sum": {"$ifNull": ["$totalAmount", 0]}},
                "paid_amount": {"$sum": {"$ifNull": ["$paidAmount", 0]}},
            }
        },
        {
            "$project": {
                "_id": 0,
                "total_amount": {"$round": ["$total_amount", 2]},
                "paid_amount": {"$round": ["$paid_amount", 2]},
                "pending_amount": {
                    "$round": [
                        {
                            "$max": [
                                {"$subtract": ["$total_amount", "$paid_amount"]},
                                0,
                            ]
                        },
                        2,
                    ]
                },
            }
        },
    ]

    try:
        items, count_result, summary_result = await gather(
            collection.aggregate(items_pipeline).to_list(length=limit),
            collection.aggregate(count_pipeline).to_list(length=1),
            collection.aggregate(summary_pipeline).to_list(length=1),
        )

        total = int(count_result[0]["total"]) if count_result else 0
        total_pages = (total + limit - 1) // limit if limit > 0 else 0
        summary = (
            summary_result[0]
            if summary_result
            else {
                "total_amount": 0.0,
                "paid_amount": 0.0,
                "pending_amount": 0.0,
            }
        )

        return {
            "company_id": company_id,
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_more": page < total_pages,
            "summary": summary,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Company transaction dashboard error: {e}",
        )


@router.get("/dashboard-items", response_model=dict)
async def get_dashboard_items(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
 
    collection = get_wholesale_collection()

    # ------------------------------------------------------------
    # Existing base filters
    # ------------------------------------------------------------
    match_query: Dict[str, Any] = {
        "status": "active",
    }

    if customer_id:
        match_query["companyId"] = customer_id

    # ------------------------------------------------------------
    # Existing date filter
    # ------------------------------------------------------------
    if start_date or end_date:
        created_date_filter: Dict[str, Any] = {}

        if start_date:
            created_date_filter["$gte"] = datetime.combine(
                start_date,
                datetime_time.min,
            )

        if end_date:
            created_date_filter["$lt"] = datetime.combine(
                end_date + timedelta(days=1),
                datetime_time.min,
            )

        match_query["createdDate"] = created_date_filter

    # ------------------------------------------------------------
    # Existing search filter
    # ------------------------------------------------------------
    if search:
        match_query["$or"] = [
            {
                "companyName": {
                    "$regex": search,
                    "$options": "i",
                }
            },
            {
                "invoiceNo": {
                    "$regex": search,
                    "$options": "i",
                }
            },
            {
                "orderId": {
                    "$regex": search,
                    "$options": "i",
                }
            },
            {
                "items.itemName": {
                    "$regex": search,
                    "$options": "i",
                }
            },
            {
                "items.varianceName": {
                    "$regex": search,
                    "$options": "i",
                }
            },
            {
                "items.itemCode": {
                    "$regex": search,
                    "$options": "i",
                }
            },
        ]

    # ------------------------------------------------------------
    # Existing dashboard status filtering
    # ------------------------------------------------------------
    post_group_filter: Dict[str, Any] = {}

    if status and status != "all":
        if status == "invoiced":
            post_group_filter = {
                "companyStatus": "invoiced",
            }

        elif status == "fully":
            post_group_filter = {
                "invoice_amount_status": "fully",
            }

        elif status == "partial":
            post_group_filter = {
                "invoice_amount_status": "partial",
            }

        elif status == "pending":
            post_group_filter = {
                "invoice_amount_status": "pending",
            }

        elif status == "realized":
            post_group_filter = {
                "paid_amount": {
                    "$gt": 0,
                }
            }

    status_filter_stages: List[Dict[str, Any]] = []

    if post_group_filter:
        status_filter_stages = [
            {
                "$group": {
                    "_id": {
                        "$cond": {
                            "if": {
                                "$and": [
                                    {
                                        "$ne": [
                                            "$invoiceNo",
                                            None,
                                        ]
                                    },
                                    {
                                        "$ne": [
                                            "$invoiceNo",
                                            "",
                                        ]
                                    },
                                ]
                            },
                            "then": "$invoiceNo",
                            "else": "$orderId",
                        }
                    },
                    "companyStatus": {
                        "$first": "$companyStatus",
                    },
                    "paid_amount": {
                        "$sum": {
                            "$ifNull": [
                                "$paidAmount",
                                0,
                            ]
                        }
                    },
                    "total_amount": {
                        "$sum": {
                            "$ifNull": [
                                "$totalAmount",
                                0,
                            ]
                        }
                    },
                    "orderIds": {
                        "$push": "$_id",
                    },
                }
            },
            {
                "$addFields": {
                    "invoice_amount_status": {
                        "$switch": {
                            "branches": [
                                {
                                    "case": {
                                        "$eq": [
                                            "$paid_amount",
                                            0,
                                        ]
                                    },
                                    "then": "pending",
                                },
                                {
                                    "case": {
                                        "$lt": [
                                            "$paid_amount",
                                            "$total_amount",
                                        ]
                                    },
                                    "then": "partial",
                                },
                            ],
                            "default": "fully",
                        }
                    }
                }
            },
            {
                "$match": post_group_filter,
            },
            {
                "$unwind": "$orderIds",
            },
            {
                "$lookup": {
                    "from": "WholeSale",
                    "localField": "orderIds",
                    "foreignField": "_id",
                    "as": "orderDoc",
                }
            },
            {
                "$unwind": "$orderDoc",
            },
            {
                "$replaceRoot": {
                    "newRoot": "$orderDoc",
                }
            },
        ]

    # ------------------------------------------------------------
    # Grouped item pipeline
    # ------------------------------------------------------------
    pipeline: List[Dict[str, Any]] = [
        {
            "$match": match_query,
        },

        # Existing invoice/payment status filtering.
        *status_filter_stages,

        # Latest matching record first.
        {
            "$sort": {
                "createdDate": -1,
                "_id": -1,
            }
        },

        # Convert items array into individual item lines.
        {
            "$unwind": {
                "path": "$items",
                "includeArrayIndex": "itemIndex",
            }
        },

        # Prepare item values before grouping.
        {
            "$project": {
                "_id": 0,

                "documentId": {
                    "$toString": "$_id",
                },

                "orderId": {
                    "$ifNull": [
                        "$orderId",
                        "",
                    ]
                },

                "invoiceNo": {
                    "$ifNull": [
                        "$invoiceNo",
                        "",
                    ]
                },

                "orderReference": {
                    "$cond": [
                        {
                            "$and": [
                                {
                                    "$ne": [
                                        "$invoiceNo",
                                        None,
                                    ]
                                },
                                {
                                    "$ne": [
                                        "$invoiceNo",
                                        "",
                                    ]
                                },
                            ]
                        },
                        "$invoiceNo",
                        {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$ne": [
                                                "$orderId",
                                                None,
                                            ]
                                        },
                                        {
                                            "$ne": [
                                                "$orderId",
                                                "",
                                            ]
                                        },
                                    ]
                                },
                                "$orderId",
                                {
                                    "$toString": "$_id",
                                },
                            ]
                        },
                    ]
                },

                "companyId": {
                    "$ifNull": [
                        "$companyId",
                        "",
                    ]
                },

                "companyName": {
                    "$ifNull": [
                        "$companyName",
                        "",
                    ]
                },

                "phoneNumber": {
                    "$ifNull": [
                        "$phoneNumber",
                        "",
                    ]
                },

                "companyStatus": {
                    "$ifNull": [
                        "$companyStatus",
                        "",
                    ]
                },

                "createdDate": {
                    "$ifNull": [
                        "$createdDate",
                        datetime(1970, 1, 1),
                    ]
                },

                "itemCode": {
                    "$ifNull": [
                        "$items.itemCode",
                        "",
                    ]
                },

                "itemName": {
                    "$ifNull": [
                        "$items.itemName",
                        "",
                    ]
                },

                "varianceName": {
                    "$ifNull": [
                        "$items.varianceName",
                        "",
                    ]
                },

                "variance_Defaultprice": {
                    "$ifNull": [
                        "$items.variance_Defaultprice",
                        0,
                    ]
                },

                "variance_Uom": {
                    "$ifNull": [
                        "$items.variance_Uom",
                        "",
                    ]
                },

                # Used to identify KG, gram and count UOM values.
                "normalizedUom": {
                    "$toUpper": {
                        "$trim": {
                            "input": {
                                "$ifNull": [
                                    "$items.variance_Uom",
                                    "",
                                ]
                            }
                        }
                    }
                },

                "tax": {
                    "$ifNull": [
                        "$items.tax",
                        0,
                    ]
                },

                "quantity": {
                    "$ifNull": [
                        "$items.quantity",
                        0,
                    ]
                },

                # Uses existing saved quantityKg field.
                "quantityKg": {
                    "$ifNull": [
                        "$items.quantityKg",
                        0,
                    ]
                },

                "quantityGrams": {
                    "$ifNull": [
                        "$items.quantityGrams",
                        0,
                    ]
                },

                "lineTotal": {
                    "$ifNull": [
                        "$items.lineTotal",
                        0,
                    ]
                },

                "discountPercentage": {
                    "$ifNull": [
                        "$items.discountPercentage",
                        0,
                    ]
                },

                "discountValue": {
                    "$ifNull": [
                        "$items.discountValue",
                        0,
                    ]
                },

                "netTotal": {
                    "$ifNull": [
                        "$items.netTotal",
                        0,
                    ]
                },

                "chargeAmount": {
                    "$ifNull": [
                        "$items.chargeAmount",
                        0,
                    ]
                },

                "remarks": {
                    "$ifNull": [
                        "$items.remarks",
                        "",
                    ]
                },
            }
        },

        # --------------------------------------------------------
        # Group same item + same variance + same UOM
        # --------------------------------------------------------
        {
            "$group": {
                "_id": {
                    "itemCode": "$itemCode",
                    "itemName": "$itemName",
                    "varianceName": "$varianceName",
                    "variance_Uom": "$variance_Uom",
                },
                "latestOrderId": {
                    "$first": "$orderId",
                },

                "latestInvoiceNo": {
                    "$first": "$invoiceNo",
                },

                "latestCompanyId": {
                    "$first": "$companyId",
                },

                "latestCompanyName": {
                    "$first": "$companyName",
                },

                "latestPhoneNumber": {
                    "$first": "$phoneNumber",
                },

                "latestCompanyStatus": {
                    "$first": "$companyStatus",
                },

                "latestCreatedDate": {
                    "$max": "$createdDate",
                },

                "variance_Defaultprice": {
                    "$first": "$variance_Defaultprice",
                },

                "tax": {
                    "$first": "$tax",
                },

                "remarks": {
                    "$first": "$remarks",
                },

                # Prevent the same order reference from being counted twice.
                "orderReferences": {
                    "$addToSet": "$orderReference",
                },

                # Used to determine whether one or multiple customers
                # ordered this grouped item.
                "customerIds": {
                    "$addToSet": "$companyId",
                },

                # Sum normal quantity.
                "quantity": {
                    "$sum": "$quantity",
                },

                # Convert every weight quantity into KG.
                "quantityKg": {
                    "$sum": {
                        "$let": {
                            "vars": {
                                "explicitWeightKg": {
                                    "$add": [
                                        "$quantityKg",
                                        {
                                            "$divide": [
                                                "$quantityGrams",
                                                1000,
                                            ]
                                        },
                                    ]
                                }
                            },
                            "in": {
                                "$cond": [
                                    # Use quantityKg / quantityGrams when saved.
                                    {
                                        "$gt": [
                                            "$$explicitWeightKg",
                                            0,
                                        ]
                                    },
                                    "$$explicitWeightKg",

                                    # Otherwise calculate from quantity + UOM.
                                    {
                                        "$switch": {
                                            "branches": [
                                                {
                                                    "case": {
                                                        "$in": [
                                                            "$normalizedUom",
                                                            [
                                                                "KG",
                                                                "KGS",
                                                                "KILOGRAM",
                                                                "KILOGRAMS",
                                                            ],
                                                        ]
                                                    },
                                                    "then": "$quantity",
                                                },
                                                {
                                                    "case": {
                                                        "$in": [
                                                            "$normalizedUom",
                                                            [
                                                                "G",
                                                                "GM",
                                                                "GMS",
                                                                "GRAM",
                                                                "GRAMS",
                                                            ],
                                                        ]
                                                    },
                                                    "then": {
                                                        "$divide": [
                                                            "$quantity",
                                                            1000,
                                                        ]
                                                    },
                                                },
                                            ],
                                            "default": 0,
                                        }
                                    },
                                ]
                            },
                        }
                    }
                },

                "lineTotal": {
                    "$sum": "$lineTotal",
                },

                "discountPercentage": {
                    "$max": "$discountPercentage",
                },

                "discountValue": {
                    "$sum": "$discountValue",
                },

                "netTotal": {
                    "$sum": "$netTotal",
                },

                "chargeAmount": {
                    "$sum": "$chargeAmount",
                },
            }
        },

        # Count how many separate orders contain this item.
        {
            "$addFields": {
                "orderCount": {
                    "$size": "$orderReferences",
                }
            }
        },
        {
            "$facet": {
                "records": [
                    {
                        "$sort": {
                            "latestCreatedDate": -1,
                            "_id.varianceName": 1,
                            "_id.itemName": 1,
                        }
                    },
                    {
                        "$skip": (page - 1) * limit,
                    },
                    {
                        "$limit": limit,
                    },
                    {
                        "$project": {
                            "_id": 0,

                            # Stable unique React key.
                            "id": {
                                "$concat": [
                                    {
                                        "$ifNull": [
                                            "$_id.itemCode",
                                            "",
                                        ]
                                    },
                                    "::",
                                    {
                                        "$ifNull": [
                                            "$_id.itemName",
                                            "",
                                        ]
                                    },
                                    "::",
                                    {
                                        "$ifNull": [
                                            "$_id.varianceName",
                                            "",
                                        ]
                                    },
                                    "::",
                                    {
                                        "$ifNull": [
                                            "$_id.variance_Uom",
                                            "",
                                        ]
                                    },
                                ]
                            },

                            # Preserve existing response properties.
                            "orderId": {
                                "$ifNull": [
                                    "$latestOrderId",
                                    "",
                                ]
                            },

                            "invoiceNo": {
                                "$ifNull": [
                                    "$latestInvoiceNo",
                                    "",
                                ]
                            },

                            "companyId": {
                                "$ifNull": [
                                    "$latestCompanyId",
                                    "",
                                ]
                            },

                            "companyName": {
                                "$ifNull": [
                                    "$latestCompanyName",
                                    "",
                                ]
                            },

                            "phoneNumber": {
                                "$ifNull": [
                                    "$latestPhoneNumber",
                                    "",
                                ]
                            },

                            "companyStatus": {
                                "$ifNull": [
                                    "$latestCompanyStatus",
                                    "",
                                ]
                            },

                            "createdDate": {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$latestCreatedDate",
                                    "onNull": "",
                                }
                            },

                            "itemCode": {
                                "$ifNull": [
                                    "$_id.itemCode",
                                    "",
                                ]
                            },

                            "itemName": {
                                "$ifNull": [
                                    "$_id.itemName",
                                    "",
                                ]
                            },

                            "varianceName": {
                                "$ifNull": [
                                    "$_id.varianceName",
                                    "",
                                ]
                            },

                            "variance_Uom": {
                                "$ifNull": [
                                    "$_id.variance_Uom",
                                    "",
                                ]
                            },

                            "variance_Defaultprice": {
                                "$round": [
                                    "$variance_Defaultprice",
                                    2,
                                ]
                            },

                            "tax": {
                                "$round": [
                                    "$tax",
                                    2,
                                ]
                            },

                            # Grouped PCS/count quantity.
                            "quantity": {
                                "$round": [
                                    "$quantity",
                                    2,
                                ]
                            },

                            # All KG and gram quantities are returned in KG.
                            "quantityKg": {
                                "$round": [
                                    "$quantityKg",
                                    3,
                                ]
                            },

                            # Grams have already been converted into KG.
                            "quantityGrams": {
                                "$literal": 0,
                            },

                            "orderCount": 1,

                            "lineTotal": {
                                "$round": [
                                    "$lineTotal",
                                    2,
                                ]
                            },

                            "discountPercentage": {
                                "$round": [
                                    "$discountPercentage",
                                    2,
                                ]
                            },

                            "discountValue": {
                                "$round": [
                                    "$discountValue",
                                    2,
                                ]
                            },

                            "netTotal": {
                                "$round": [
                                    "$netTotal",
                                    2,
                                ]
                            },

                            "chargeAmount": {
                                "$round": [
                                    "$chargeAmount",
                                    2,
                                ]
                            },

                            "remarks": {
                                "$ifNull": [
                                    "$remarks",
                                    "",
                                ]
                            },

                            # Internal field used only to identify whether
                            # this item belongs to one or multiple customers.
                            "customerIds": 1,
                        }
                    },
                ],

                # Total number of grouped item variants.
                "metadata": [
                    {
                        "$count": "total",
                    }
                ],
            }
        },
    ]

    try:
        result = await collection.aggregate(
            pipeline
        ).to_list(length=1)

        facet = result[0] if result else {}

        records = facet.get(
            "records",
            [],
        )

        metadata = facet.get(
            "metadata",
            [],
        )

        total = (
            metadata[0]["total"]
            if metadata
            else 0
        )

        total_pages = (
            (total + limit - 1) // limit
            if limit > 0
            else 0
        )

        # --------------------------------------------------------
        # Preserve existing customer-name lookup behavior
        # --------------------------------------------------------
        company_ids = list(
            {
                company_id
                for item in records
                for company_id in item.get(
                    "customerIds",
                    [],
                )
                if company_id
            }
        )

        customer_map = await _batch_fetch_customers(
            company_ids
        )

        for item in records:
            grouped_customer_ids = list(
                {
                    company_id
                    for company_id in item.get(
                        "customerIds",
                        [],
                    )
                    if company_id
                }
            )

            if len(grouped_customer_ids) == 1:
                grouped_company_id = grouped_customer_ids[0]

                customer = customer_map.get(
                    grouped_company_id
                )

                item["companyId"] = grouped_company_id

                if customer:
                    item["companyName"] = customer.get(
                        "customerName",
                        item.get(
                            "companyName",
                            "",
                        ),
                    )

                    item["phoneNumber"] = customer.get(
                        "customerPhoneNumber",
                        item.get(
                            "phoneNumber",
                            "",
                        ),
                    )

            elif len(grouped_customer_ids) > 1:
                item["companyId"] = ""
                item["companyName"] = (
                    f"{len(grouped_customer_ids)} customers"
                )
                item["phoneNumber"] = ""

            # Remove internal aggregation-only property.
            item.pop(
                "customerIds",
                None,
            )

        return {
            "items": records,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_more": page < total_pages,
        }

    except Exception as e:
        import traceback

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Dashboard items error: {e}",
        )


@router.get("/payment-tracking", response_model=dict)
async def get_payment_tracking(
    customer:    Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    start_date:  Optional[str] = Query(None),
    end_date:    Optional[str] = Query(None),
):
    collection = get_wholesale_collection()
    match: Dict = {
        "status":        "active",
        "companyStatus": {"$in": ["invoiced", "printed"]},
    }

    if customer_id:   match["companyId"]   = customer_id
    elif customer:    match["companyName"]  = {"$regex": customer, "$options": "i"}

    if start_date or end_date:
        date_f: Dict = {}
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            date_f["$gte"] = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            date_f["$lte"] = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        match["deliveryDate"] = date_f

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id":           {"$ifNull": ["$invoiceNo", "$orderId"]},
                "total_revenue": {"$sum": "$totalAmount"},
                "total_paid":    {"$sum": "$paidAmount"},
            }
        },
        {"$addFields": {"total_pending": {"$subtract": ["$total_revenue", "$total_paid"]}}},
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



def _build_ledger_events(
    orders: List[Dict],
    display_company_name: str,
) -> List[Dict]:
    """Build raw ledger events from orders list."""
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
                "company_status":    order.get("companyStatus", "invoiced"),
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

    raw_events: List[Dict] = []
    for inv in invoice_map.values():
        inv_date = inv["date"]
        if isinstance(inv_date, str):
            try:    inv_date = datetime.fromisoformat(inv_date)
            except: inv_date = None

        _is_printed = inv.get("company_status") == "printed"
        _entry_type = "Order" if _is_printed else "Invoice"
        raw_events.append({
            "date":        inv_date,
            "type":        _entry_type,
            "ref_id":      inv["invoice_no"],
            "description": f"{_entry_type} for {display_company_name}",
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
    return raw_events


def _apply_date_filter(
    events: List[Dict],
    parsed_start: Optional[datetime],
    parsed_end: Optional[datetime],
) -> List[Dict]:
    if not parsed_start and not parsed_end:
        return events
    filtered = []
    for event in events:
        event_date = event.get("date")
        if event_date:
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
        filtered.append(event)
    return filtered


@router.get("/customer-ledger/{company_name}")
async def get_customer_ledger(
    company_name: str,
    customer_id: Optional[str] = Query(None),
    start_date:  Optional[str] = Query(None),
    end_date:    Optional[str] = Query(None),
):
    collection           = get_wholesale_collection()
    decoded_company_name = urllib.parse.unquote(company_name)
    match: Dict = {
        "status":        "active",
        "companyStatus": {"$in": ["invoiced", "printed"]},
    }

    if customer_id:
        match["companyId"] = customer_id
    else:
        match["companyName"] = decoded_company_name

    if start_date or end_date:
        date_f: Dict = {}
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            date_f["$gte"] = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            date_f["$lte"] = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        match["deliveryDate"] = date_f
    orders = await collection.find(match).sort("createdDate", 1).to_list(length=1000)

    display_company_name = decoded_company_name
    _lookup_id = customer_id or (orders[0].get("companyId") if orders else None)
    if _lookup_id:
        cust = await get_customer_collection().find_one(
            {"customerId": _lookup_id, "status": "customer"},
            {"customerName": 1},
        )
        if cust:
            display_company_name = cust.get("customerName", display_company_name)

    if not orders:
        return {
            "summary": {"total_billed": 0, "total_paid": 0, "current_outstanding": 0},
            "ledger":  [],
        }

    raw_events = _build_ledger_events(orders, display_company_name)

    running_balance = 0.0
    events_with_balance = []
    for event in raw_events:
        running_balance += event["debit"]
        running_balance -= event["credit"]
        iso_date = event["date"].isoformat() if isinstance(event["date"], datetime) else event["date"]
        events_with_balance.append({**event, "date": iso_date, "balance": running_balance})

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id":           {"$ifNull": ["$invoiceNo", "$orderId"]},
                "total_revenue": {"$sum": "$totalAmount"},
                "total_paid":    {"$sum": "$paidAmount"},
            }
        },
        {"$addFields": {"total_pending": {"$subtract": ["$total_revenue", "$total_paid"]}}},
        {
            "$group": {
                "_id":            None,
                "total_revenue":  {"$sum": "$total_revenue"},
                "total_paid":     {"$sum": "$total_paid"},
                "total_pending":  {"$sum": "$total_pending"},
            }
        },
    ]
    
    result = await collection.aggregate(pipeline).to_list(length=1)
    totals = result[0] if result else {}
    total_billed = round(totals.get("total_revenue", 0.0), 2)
    total_paid   = round(totals.get("total_paid", 0.0), 2)
    current_outstanding = total_billed - total_paid

    return {
        "summary": {
            "total_billed":        total_billed,
            "total_paid":          total_paid,
            "current_outstanding": current_outstanding,
        },
        "ledger": events_with_balance,
    }


@router.get("/customer-ledger-pdf/{company_name}")
async def download_customer_ledger_pdf(
    company_name: str,
    customer_id: Optional[str] = Query(None),
    start_date:  Optional[str] = Query(None),
    end_date:    Optional[str] = Query(None),
):
    company_info = {}
    collection           = get_wholesale_collection()
    decoded_company_name = urllib.parse.unquote(company_name)

    # Build match query similar to JSON endpoint
    match: Dict = {
        "status":        "active",
        "companyStatus": {"$in": ["invoiced", "printed"]},
    }

    if customer_id:
        match["companyId"] = customer_id
    else:
        match["companyName"] = decoded_company_name

    # Apply date filter on deliveryDate (matching JSON endpoint)
    if start_date or end_date:
        date_f: Dict = {}
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            date_f["$gte"] = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            date_f["$lte"] = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        match["deliveryDate"] = date_f

    orders = await collection.find(match).sort("createdDate", 1).to_list(length=1000)

    display_company_name = decoded_company_name
    _lookup_id = customer_id or (orders[0].get("companyId") if orders else None)
    if _lookup_id:
        cust = await get_customer_collection().find_one(
            {"customerId": _lookup_id, "status": "customer"},
            {"customerName": 1},
        )
        if cust:
            display_company_name = cust.get("customerName", display_company_name)

    if not orders:
        buffer = build_ledger_pdf(
            display_company_name, company_info, [], 0, 0, 0, start_date, end_date, 0
        )
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Ledger_{display_company_name}.pdf"},
        )

    # Build raw events
    raw_events = _build_ledger_events(orders, display_company_name)

    # Calculate running balance (matching JSON endpoint logic)
    running_balance = 0.0
    events_with_balance = []
    for event in raw_events:
        running_balance += event["debit"]
        running_balance -= event["credit"]
        events_with_balance.append({**event, "balance": running_balance})

    # Apply date filter on the events (if needed)
    parsed_start = datetime.fromisoformat(start_date) if start_date else None
    parsed_end = None
    if end_date:
        parsed_end = datetime.fromisoformat(end_date)
        parsed_end = parsed_end.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    ledger_entries = _apply_date_filter(events_with_balance, parsed_start, parsed_end)

    # Calculate totals using aggregation pipeline (matching JSON endpoint)
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id":           {"$ifNull": ["$invoiceNo", "$orderId"]},
                "total_revenue": {"$sum": "$totalAmount"},
                "total_paid":    {"$sum": "$paidAmount"},
            }
        },
        {"$addFields": {"total_pending": {"$subtract": ["$total_revenue", "$total_paid"]}}},
        {
            "$group": {
                "_id":            None,
                "total_revenue":  {"$sum": "$total_revenue"},
                "total_paid":     {"$sum": "$total_paid"},
                "total_pending":  {"$sum": "$total_pending"},
            }
        },
    ]
    
    result = await collection.aggregate(pipeline).to_list(length=1)
    totals = result[0] if result else {}
    total_billed = round(totals.get("total_revenue", 0.0), 2)
    total_paid = round(totals.get("total_paid", 0.0), 2)
    current_outstanding = total_billed - total_paid
    total_discount_all: float = sum(order.get("discountAmount", 0) or 0 for order in orders)

    buffer = build_ledger_pdf(
        display_company_name,
        company_info,
        ledger_entries,
        total_billed,
        total_paid,
        current_outstanding, 
        start_date,
        end_date,
        total_discount_amount=total_discount_all,
    )

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Ledger_{display_company_name}.pdf"},
    )





@router.get("/customer-ledger-csv/{company_name}")
async def download_customer_ledger_csv(
    company_name: str,
    customer_id: Optional[str] = Query(None),
    start_date:  Optional[str] = Query(None),
    end_date:    Optional[str] = Query(None),
):
    collection           = get_wholesale_collection()
    decoded_company_name = urllib.parse.unquote(company_name)
    match: Dict = {
        "status":        "active",
        "companyStatus": {"$in": ["invoiced", "printed"]},
    }

    if customer_id:
        match["companyId"] = customer_id
    else:
        match["companyName"] = decoded_company_name
    if start_date or end_date:
        date_f: Dict = {}
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            date_f["$gte"] = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            date_f["$lte"] = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        match["deliveryDate"] = date_f

    orders = await collection.find(match).sort("createdDate", 1).to_list(length=1000)

    display_company_name = decoded_company_name
    _lookup_id = customer_id or (orders[0].get("companyId") if orders else None)
    if _lookup_id:
        cust = await get_customer_collection().find_one(
            {"customerId": _lookup_id, "status": "customer"},
            {"customerName": 1},
        )
        if cust:
            display_company_name = cust.get("customerName", display_company_name)

    if not orders:
        ledger_data = []
        df = pd.DataFrame(ledger_data)
        output = BytesIO()
        writer = pd.ExcelWriter(output, engine="xlsxwriter")
        df.to_excel(writer, index=False, sheet_name="Ledger")
        workbook = writer.book
        worksheet = writer.sheets["Ledger"]
        
        header_format = workbook.add_format({
            "bold": True, "font_name": "Arial", "font_size": 12,
            "font_color": "#1e293b", "bg_color": "#ccfbf1",
            "border": 1, "border_color": "#0f766e",
            "align": "center", "valign": "vcenter", "text_wrap": True,
        })
        
        for col_num, value in enumerate(["Date", "Type", "Reference", "Description", "Debit (Rs.)", "Credit (Rs.)", "Balance (Rs.)"]):
            worksheet.write(0, col_num, value, header_format)
        
        writer.close()
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Ledger_{display_company_name}.xlsx"},
        )

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
                "company_status":    order.get("companyStatus", "invoiced"),
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

    raw_events: List[Dict] = []
    for inv in invoice_map.values():
        inv_date = inv["date"]
        if isinstance(inv_date, str):
            try:    inv_date = datetime.fromisoformat(inv_date)
            except: inv_date = None
        _is_printed = inv.get("company_status") == "printed"
        _entry_type = "Order" if _is_printed else "Invoice"
        raw_events.append({
            "date":        inv_date,
            "type":        _entry_type,
            "ref_id":      inv["invoice_no"],
            "description": f"{_entry_type} {inv['invoice_no']}",   
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
    running_balance = 0.0
    events_with_balance = []
    for event in raw_events:
        running_balance += event["debit"]
        running_balance -= event["credit"]
        events_with_balance.append({**event, "balance": running_balance})
    parsed_start = datetime.fromisoformat(start_date) if start_date else None
    parsed_end = None
    if end_date:
        parsed_end = datetime.fromisoformat(end_date)
        parsed_end = parsed_end.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    filtered = _apply_date_filter(events_with_balance, parsed_start, parsed_end)

    ledger_data = [
        {
            "Date":          e["date"],
            "Type":          e["type"],
            "Reference":     e["ref_id"],
            "Description":   e["description"],
            "Debit (Rs.)":   e["debit"],
            "Credit (Rs.)":  e["credit"],
            "Balance (Rs.)": e["balance"],
        }
        for e in filtered
    ]

    df = pd.DataFrame(ledger_data)
    if not df.empty:
        df.sort_values(by=["Date"], inplace=True)

    output = BytesIO()
    writer = pd.ExcelWriter(output, engine="xlsxwriter")
    df.to_excel(writer, index=False, sheet_name="Ledger")
    workbook  = writer.book
    worksheet = writer.sheets["Ledger"]

    header_format = workbook.add_format({
        "bold": True, "font_name": "Arial", "font_size": 12,
        "font_color": "#1e293b", "bg_color": "#ccfbf1",
        "border": 1, "border_color": "#0f766e",
        "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    money_format = workbook.add_format({
        "num_format": "#,##0.00", "font_name": "Arial", "font_size": 10,
        "valign": "vcenter", "border": 1, "border_color": "#E0E0E0", "text_wrap": True,
    })
    date_format = workbook.add_format({
        "num_format": "dd-mm-yyyy", "font_name": "Arial", "font_size": 10,
        "valign": "vcenter", "border": 1, "border_color": "#E0E0E0", "text_wrap": True,
    })
    text_format = workbook.add_format({
        "font_name": "Arial", "font_size": 10,
        "valign": "vcenter", "border": 1, "border_color": "#E0E0E0", "text_wrap": True,
    })
    even_row_format = workbook.add_format({
        "font_name": "Arial", "font_size": 10, "valign": "vcenter",
        "border": 1, "border_color": "#E0E0E0", "bg_color": "#EEF3F2", "text_wrap": True,
    })
    even_row_money_format = workbook.add_format({
        "num_format": "#,##0.00", "font_name": "Arial", "font_size": 10,
        "valign": "vcenter", "border": 1, "border_color": "#E0E0E0", "bg_color": "#EEF3F2",
    })
    even_row_date_format = workbook.add_format({
        "num_format": "dd-mm-yyyy", "font_name": "Arial", "font_size": 10,
        "valign": "vcenter", "border": 1, "border_color": "#E0E0E0", "bg_color": "#EEF3F2",
    })

    worksheet.set_column("A:A", 18)
    worksheet.set_column("B:B", 14)
    worksheet.set_column("C:C", 20)
    worksheet.set_column("D:D", 35)
    worksheet.set_column("E:E", 16)
    worksheet.set_column("F:F", 16)
    worksheet.set_column("G:G", 18)
    worksheet.set_default_row(hide_unused_rows=False)

    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)

    for row_num in range(1, len(df) + 1):
        is_even        = (row_num % 2 == 0)
        curr_date_fmt  = even_row_date_format  if is_even else date_format
        curr_text_fmt  = even_row_format       if is_even else text_format
        curr_money_fmt = even_row_money_format if is_even else money_format

        if pd.notna(df.iloc[row_num - 1]["Date"]):
            worksheet.write_datetime(row_num, 0, df.iloc[row_num - 1]["Date"], curr_date_fmt)
        else:
            worksheet.write(row_num, 0, "", curr_text_fmt)

        for col_num in [1, 2, 3]:
            val = df.iloc[row_num - 1, col_num]
            worksheet.write(row_num, col_num, val if pd.notna(val) else "", curr_text_fmt)

        worksheet.write(row_num, 4, df.iloc[row_num - 1]["Debit (Rs.)"],   curr_money_fmt)
        worksheet.write(row_num, 5, df.iloc[row_num - 1]["Credit (Rs.)"],  curr_money_fmt)
        worksheet.write(row_num, 6, df.iloc[row_num - 1]["Balance (Rs.)"], curr_money_fmt)

    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

    writer.close()
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Ledger_{display_company_name}.xlsx"},
    )







@router.get("/print-invoice/{invoice_no}")
async def print_invoice(invoice_no: str):

    collection = get_wholesale_collection()
    orders = await collection.find(
        {"invoiceNo": invoice_no, "status": "active"}
    ).to_list(length=1000)

    if not orders:
        raise HTTPException(status_code=404, detail="Invoice not found")

    items = [serialize_item(dict(order)) for order in orders]
    items.sort(key=lambda x: x.get("orderId", ""))

    total_invoice_amount = sum(float(i.get("totalAmount", 0)) for i in items)
    total_paid_amount    = sum(float(i.get("paidAmount",  0)) for i in items)
    total_pending_amount = total_invoice_amount - total_paid_amount

    if total_paid_amount >= total_invoice_amount:  amount_status = "fully"
    elif total_paid_amount == 0:                   amount_status = "pending"
    else:                                          amount_status = "partial"

    company_id = items[0].get("companyId", "") if items else ""
    total_outstanding = await _get_company_total_outstanding(collection, company_id)
    company_info = {}

    pdf_bytes = _build_invoice_pdf(
        items,
        invoice_no,
        company_info,
        paid_amount=total_paid_amount,
        pending_amount=total_pending_amount,
        amount_status=amount_status,
        previous_outstanding=total_outstanding,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=Invoice_{invoice_no}.pdf",
            "X-Payment-Status": amount_status,
            "X-Invoice-Number": invoice_no,
        },
    )
