from typing import List, Optional
from fastapi import APIRouter, HTTPException, Response
from datetime import date, datetime, time
import io
import pandas as pd
from .models import PaginatedResponse, ItemOrder
from .utils import invoices, customers, ensure_customer_indexes, ensure_invoice_indexes

router = APIRouter()


# ---------------- HELPER ----------------
def normalize_phone(phone):
    """Always returns both int and str variants for a phone value."""
    try:
        return [int(str(phone).strip()), str(phone).strip()]
    except (ValueError, TypeError):
        return [str(phone).strip()]


def phone_match_query(field: str, phone_str: str):
    """
    Builds a $or query that matches both string and integer stored phone numbers.
    Uses regex for partial/live matching on string values.
    """
    query = {"$or": [
        {field: {"$regex": phone_str, "$options": "i"}},  # string stored, partial match
    ]}
    if phone_str.isdigit():
        # Also match integer-stored phones that START with the typed digits
        # MongoDB can't regex integers, so match exact int only when fully typed
        query["$or"].append({field: int(phone_str)})
    return query


async def build_customer_map(phone_values: list) -> dict:
    """
    Looks up customer names from the customers collection.
    Handles both int and str stored phone numbers gracefully.
    Returns a dict keyed by str(phone) -> customerName.
    """
    if not phone_values:
        return {}

    str_phones = [str(p) for p in phone_values]
    int_phones = []
    for p in str_phones:
        try:
            int_phones.append(int(p))
        except ValueError:
            pass

    # Query with both types to handle mixed storage
    cursor = customers.find(
        {"$or": [
            {"customerPhoneNumber": {"$in": str_phones}},
            {"customerPhoneNumber": {"$in": int_phones}} if int_phones else {"customerPhoneNumber": None}
        ]},
        {"customerPhoneNumber": 1, "customerName": 1, "_id": 0}
    )
    cust_docs = await cursor.to_list(length=len(phone_values) * 2)

    return {
        str(c["customerPhoneNumber"]): c.get("customerName", "")
        for c in cust_docs
    }


# ---------------- MAIN API ----------------
@router.get("/", response_model=PaginatedResponse)
async def get_item_order_report(
    page: int = 1,
    limit: int = 30,
    startDate: Optional[date] = None,
    endDate: Optional[date] = None,
    billNo: Optional[str] = None,
    locationName: Optional[str] = None,
    customerNo: Optional[str] = None,
    customerName: Optional[str] = None,
    salesPersonName: Optional[str] = None,
    types: Optional[str] = None,
    topLimit: Optional[int] = None,
    mostFrequent: Optional[bool] = None,
):
    skip = (page - 1) * limit
    match = {}

    # ✅ DATE FILTER
    if startDate and endDate:
        match["invoiceDateTime"] = {
            "$gte": datetime.combine(startDate, time.min),
            "$lte": datetime.combine(endDate, time.max)
        }

    # ✅ OTHER FILTERS
    if billNo:
        match["invoiceNo"] = {"$regex": f"^{billNo}", "$options": "i"}

    if locationName:
        match["branchName"] = {"$regex": f"^{locationName}", "$options": "i"}

    if salesPersonName:
        match["salesPersonName"] = {"$regex": f"^{salesPersonName}", "$options": "i"}

    if types:
        match["salesType"] = {"$regex": f"^{types}", "$options": "i"}

    # ✅ CUSTOMER PHONE FILTER — live partial match, handles int & string storage
    if customerNo:
        phone_str = customerNo.strip()
        phone_query = phone_match_query("customerPhoneNumber", phone_str)
        match["$or"] = phone_query["$or"]

    # ✅ CUSTOMER NAME FILTER — lookup phones from customers, match both types in invoices
    if customerName:
        cursor = customers.find(
            {"customerName": {"$regex": customerName.strip(), "$options": "i"}},
            {"customerPhoneNumber": 1, "_id": 0}
        )
        customer_docs = await cursor.to_list(length=10000)

        if not customer_docs:
            return PaginatedResponse(
                totalcount=0, totalpages=0, limit=limit, page=page,
                skip=skip, items=[], hasNextPage=False
            )

        # Collect both int and str variants so invoices match regardless of storage type
        phone_variants = []
        for c in customer_docs:
            raw = c.get("customerPhoneNumber")
            if raw is not None:
                phone_variants.append(str(raw))
                try:
                    phone_variants.append(int(str(raw)))
                except ValueError:
                    pass

        if not phone_variants:
            return PaginatedResponse(
                totalcount=0, totalpages=0, limit=limit, page=page,
                skip=skip, items=[], hasNextPage=False
            )

        match["customerPhoneNumber"] = {"$in": phone_variants}

    # ✅ TOP N CUSTOMERS BY TOTAL SPEND
    if topLimit and topLimit > 0:
        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": "$customerPhoneNumber",
                    "totalSpend": {"$sum": "$totalAmount"},
                    "lastInvoice": {"$last": "$$ROOT"}
                }
            },
            {"$sort": {"totalSpend": -1}},
            {"$limit": topLimit},
        ]
        top_docs = await invoices.aggregate(pipeline).to_list(length=topLimit)

        if not top_docs:
            return PaginatedResponse(
                totalcount=0, totalpages=0, limit=limit, page=1,
                skip=0, items=[], hasNextPage=False
            )

        raw_phones = [d["_id"] for d in top_docs if d["_id"] is not None]
        customer_map = await build_customer_map(raw_phones)  # ✅ fixed lookup

        items = []
        for d in top_docs:
            last = d.get("lastInvoice", {})
            dt = last.get("invoiceDateTime")
            phone = str(d["_id"]) if d["_id"] is not None else ""
            items.append(ItemOrder(
                billDate=dt.strftime("%d-%m-%Y") if isinstance(dt, datetime) else None,
                billNo=last.get("invoiceNo"),
                netAmount=last.get("netAmount"),
                billTotalAmount=last.get("totalAmount"),
                locationName=last.get("branchName"),
                customerNo=phone,
                customerName=customer_map.get(phone, ""),
                empId=str(last.get("salesPersonId", "")),
                salesPersonName=last.get("salesPersonName"),
                types=last.get("salesType"),
            ))

        return PaginatedResponse(
            totalcount=len(items), totalpages=1, limit=limit,
            page=1, skip=0, items=items, hasNextPage=False
        )

    # ✅ MOST FREQUENT CUSTOMERS
    if mostFrequent:
        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": "$customerPhoneNumber",
                    "visitCount": {"$sum": 1},
                    "lastInvoice": {"$last": "$$ROOT"}
                }
            },
            {"$sort": {"visitCount": -1}},
            {"$limit": 50},
        ]
        freq_docs = await invoices.aggregate(pipeline).to_list(length=50)

        raw_phones = [d["_id"] for d in freq_docs if d["_id"] is not None]
        customer_map = await build_customer_map(raw_phones)  # ✅ fixed lookup

        items = []
        for d in freq_docs:
            last = d.get("lastInvoice", {})
            dt = last.get("invoiceDateTime")
            phone = str(d["_id"]) if d["_id"] is not None else ""
            items.append(ItemOrder(
                billDate=dt.strftime("%d-%m-%Y") if isinstance(dt, datetime) else None,
                billNo=last.get("invoiceNo"),
                netAmount=last.get("netAmount"),
                billTotalAmount=last.get("totalAmount"),
                locationName=last.get("branchName"),
                customerNo=phone,
                customerName=customer_map.get(phone, ""),
                empId=str(last.get("salesPersonId", "")),
                salesPersonName=last.get("salesPersonName"),
                types=last.get("salesType"),
            ))

        return PaginatedResponse(
            totalcount=len(items), totalpages=1, limit=limit,
            page=1, skip=0, items=items, hasNextPage=False
        )

    # 🚀 NORMAL PAGINATED FETCH
    docs = await invoices.find(match)\
        .sort("invoiceDateTime", -1)\
        .skip(skip)\
        .limit(limit)\
        .to_list(length=limit)

    raw_phones = [d.get("customerPhoneNumber") for d in docs if d.get("customerPhoneNumber")]
    customer_map = await build_customer_map(raw_phones)  # ✅ fixed lookup

    total_count = await invoices.count_documents(match)
    total_pages = (total_count + limit - 1) // limit

    items = []
    for d in docs:
        dt = d.get("invoiceDateTime")
        items.append(
            ItemOrder(
                billDate=dt.strftime("%d-%m-%Y") if isinstance(dt, datetime) else None,
                billNo=d.get("invoiceNo"),
                netAmount=d.get("netAmount"),
                billTotalAmount=d.get("totalAmount"),
                locationName=d.get("branchName"),
                customerNo=str(d.get("customerPhoneNumber", "")),
                customerName=customer_map.get(str(d.get("customerPhoneNumber")), ""),
                empId=str(d.get("salesPersonId")),
                salesPersonName=d.get("salesPersonName"),
                types=d.get("salesType"),
            )
        )

    return PaginatedResponse(
        totalcount=total_count,
        totalpages=total_pages,
        limit=limit,
        page=page,
        skip=skip,
        items=items,
        hasNextPage=page < total_pages
    )


# ---------------- EXPORT ----------------
@router.get("/export")
async def export_item_order_reports(
    startDate: Optional[date] = None,
    endDate: Optional[date] = None,
    billNo: Optional[str] = None,
    locationName: Optional[str] = None,
    customerNo: Optional[str] = None,
    customerName: Optional[str] = None,
    salesPersonName: Optional[str] = None,
):
    match = {}

    if startDate and endDate:
        match["invoiceDateTime"] = {
            "$gte": datetime.combine(startDate, time.min),
            "$lte": datetime.combine(endDate, time.max)
        }

    if billNo:
        match["invoiceNo"] = {"$regex": f"^{billNo}", "$options": "i"}

    if locationName:
        match["branchName"] = {"$regex": f"^{locationName}", "$options": "i"}

    if salesPersonName:
        match["salesPersonName"] = {"$regex": f"^{salesPersonName}", "$options": "i"}

    # ✅ CUSTOMER PHONE FILTER — same fix as main route
    if customerNo:
        phone_str = customerNo.strip()
        phone_query = phone_match_query("customerPhoneNumber", phone_str)
        match["$or"] = phone_query["$or"]

    # ✅ CUSTOMER NAME FILTER — same fix as main route
    if customerName:
        cursor = customers.find(
            {"customerName": {"$regex": customerName.strip(), "$options": "i"}},
            {"customerPhoneNumber": 1, "_id": 0}
        )
        customer_docs = await cursor.to_list(length=10000)

        phone_variants = []
        for c in customer_docs:
            raw = c.get("customerPhoneNumber")
            if raw is not None:
                phone_variants.append(str(raw))
                try:
                    phone_variants.append(int(str(raw)))
                except ValueError:
                    pass

        if phone_variants:
            match["customerPhoneNumber"] = {"$in": phone_variants}

    docs = await invoices.find(match).to_list(length=5000)

    if not docs:
        raise HTTPException(status_code=404, detail="No data found")

    raw_phones = [d.get("customerPhoneNumber") for d in docs if d.get("customerPhoneNumber")]
    customer_map = await build_customer_map(raw_phones)  # ✅ fixed lookup

    data = []
    for d in docs:
        dt = d.get("invoiceDateTime")
        data.append({
            "Bill No": d.get("invoiceNo"),
            "Location": d.get("branchName"),
            "Customer Name": customer_map.get(str(d.get("customerPhoneNumber")), ""),
            "Phone Number": str(d.get("customerPhoneNumber", "")),
            "Sales Person": d.get("salesPersonName"),
            "Amount (₹)": d.get("totalAmount"),
            "Bill Date": dt.strftime("%d-%m-%Y") if isinstance(dt, datetime) else "",
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Customer Report")

        workbook = writer.book
        worksheet = writer.sheets["Customer Report"]

        header_format = workbook.add_format({
            "bold": True, "align": "center",
            "fg_color": "#2F75B5", "font_color": "white", "border": 1
        })
        cell_format = workbook.add_format({"border": 1})
        amount_format = workbook.add_format({"num_format": "₹#,##0", "border": 1})

        for col_num, col_name in enumerate(df.columns):
            worksheet.write(0, col_num, col_name, header_format)

        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, width, amount_format if col == "Amount (₹)" else cell_format)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Customer_Report.xlsx"}
    )


# ---------------- STARTUP ----------------
@router.on_event("startup")
async def startup_event():
    await ensure_invoice_indexes()
    await ensure_customer_indexes()