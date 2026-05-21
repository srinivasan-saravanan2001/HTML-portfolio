from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from bson import ObjectId
import logging
from io import BytesIO
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pymongo.errors import DuplicateKeyError
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from .models import Customer, CustomerPost, CustomerPatch
from .utils import get_customer_collection

router = APIRouter()
logger = logging.getLogger(__name__)


async def generate_customer_id():
    collection = get_customer_collection()
    pipeline = [
        {"$match": {"customerId": {"$regex": "^CUST"}}},
        {"$sort": {"customerId": -1}},
        {"$limit": 1},
        {"$project": {"customerId": 1, "_id": 0}}
    ]
    result = await collection.aggregate(pipeline).to_list(length=1)
    
    if not result:
        return "CUST001"
    
    last_id = result[0].get("customerId", "CUST000")
    number = int(last_id.replace("CUST", ""))
    return f"CUST{number + 1:03d}"

@router.post("/", response_model=Customer)
async def create_customer(customer: CustomerPost):
    collection = get_customer_collection()
    new_customer = customer.dict()
    customer_id = await generate_customer_id()
    new_customer["customerId"] = customer_id
    if not new_customer.get("status"):
        new_customer["status"] = "customer"
    try:
        result = await collection.insert_one(new_customer)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409, 
            detail="A customer with this phone number already exists."
        )
    return Customer(
        customerId=str(result.inserted_id),
        customerName=new_customer.get("customerName", ""),
        customerPhoneNumber=new_customer.get("customerPhoneNumber", ""),
        status=new_customer.get("status", "customer"), 
        address=new_customer.get("address", "")
    )

@router.get("/")
async def get_all_customers(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    collection = get_customer_collection()
    skip = (page - 1) * limit
    match_stage = {}
    if status:
        match_stage["status"] = status

    if search:
        search_regex = {"$regex": search.strip(), "$options": "i"}
        match_stage["$or"] = [
            {"customerName": search_regex},
            {"customerPhoneNumber": search_regex},
            {"customerId": search_regex},
            {"address": search_regex}
        ]
    pipeline = [
        {"$match": match_stage},
        {"$sort": {"_id": -1}},
        {
            "$facet": {
                "metadata": [{"$count": "total"}],
                "data": [
                    {"$skip": skip},
                    {"$limit": limit},
                    {"$project": {
                        "_id": 0,
                        "customerId": {"$toString": "$_id"}, 
                        "customerName": 1,
                        "customerPhoneNumber": 1,
                        "status": 1,
                        "address": 1
                    }}
                ]
            }
        }
    ]

    results = await collection.aggregate(pipeline).to_list(length=1)
    
    if not results:
        return {"data": [], "total": 0, "page": page, "limit": limit, "hasNextPage": False}

    result_data = results[0]
    data = result_data.get("data", [])
    meta = result_data.get("metadata", [])
    total = meta[0]["total"] if meta else 0

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "hasNextPage": (skip + limit) < total,
        "data": data
    }


@router.get("/export-excel")
async def export_customers_excel(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query("active")
):
    collection = get_customer_collection()
    
    match_stage = {}
    if status:
        match_stage["status"] = status

    if search:
        search_regex = {"$regex": search.strip(), "$options": "i"}
        match_stage["$or"] = [
            {"customerName": search_regex},
            {"customerPhoneNumber": search_regex},
            {"address": search_regex}
        ]

    # Project only needed fields
    pipeline = [
        {"$match": match_stage},
        {"$sort": {"_id": -1}},
        {"$project": {
            "_id": 0,
            "customerName": 1,
            "customerPhoneNumber": 1,
            "address": 1
        }}
    ]

    # Use async cursor iterator for memory efficiency
    cursor = collection.aggregate(pipeline)
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"

    # Styles
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    center_alignment = Alignment(horizontal="center", vertical="center")
    left_alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin', color='D1D5DB'),
        right=Side(style='thin', color='D1D5DB'),
        top=Side(style='thin', color='D1D5DB'),
        bottom=Side(style='thin', color='D1D5DB')
    )

    ws.append(["S.No", "Customer Name", "Phone Number", "Address"])
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_alignment
        cell.border = thin_border

    idx = 1
    async for cust in cursor:
        ws.append([
            idx,
            cust.get("customerName", ""),
            cust.get("customerPhoneNumber", ""),
            cust.get("address", "")
        ])
        
        current_row = ws.max_row
        for col_idx, cell in enumerate(ws[current_row]):
            cell.border = thin_border
            cell.alignment = center_alignment if col_idx < 2 else left_alignment
            if idx % 2 == 0:
                cell.fill = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
        idx += 1

    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 30
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 45
    ws.freeze_panes = "A2"

    file_stream = BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return StreamingResponse(
        file_stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
        headers={'Content-Disposition': 'attachment; filename="customers_export.xlsx"'}
    )

# --- Optimized Pagination for Inactive (Aggregation) ---
@router.get("/pagination")
async def get_customers_with_pagination(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1), # Default to 20
    status: Optional[str] = Query(None),
    customerPhoneNumber: Optional[str] = Query(None)
):
    collection = get_customer_collection()
    skip = (page - 1) * limit
    
    match_stage = {}
    if status:
        match_stage["status"] = status
    if customerPhoneNumber:
        match_stage["customerPhoneNumber"] = customerPhoneNumber.strip()

    pipeline = [
        {"$match": match_stage},
        {"$sort": {"_id": -1}},
        {
            "$facet": {
                "metadata": [{"$count": "total"}],
                "data": [
                    {"$skip": skip},
                    {"$limit": limit},
                    {"$project": {
                        "_id": 0,
                        "customerId": {"$toString": "$_id"},
                        "customerName": 1,
                        "customerPhoneNumber": 1,
                        "status": 1,
                        "address": 1
                    }}
                ]
            }
        }
    ]
    
    results = await collection.aggregate(pipeline).to_list(length=1)
    
    if not results:
        return {"data": [], "total": 0, "page": page, "limit": limit, "totalPages": 0}

    result_data = results[0]
    data = result_data.get("data", [])
    meta = result_data.get("metadata", [])
    total = meta[0]["total"] if meta else 0

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "totalPages": (total + limit - 1) // limit if limit > 0 else 0,
        "data": data
    }

@router.get("/by-customer", response_model=List[Customer])
async def get_customers(customerPhoneNumber: Optional[str] = Query(None)):
    match_stage = {}
    if customerPhoneNumber:
        match_stage["customerPhoneNumber"] = customerPhoneNumber.strip()
    
    pipeline = [
        {"$match": match_stage},
        {"$project": {
            "_id": 0,
            "customerId": {"$toString": "$_id"},
            "customerName": 1,
            "customerPhoneNumber": 1,
            "status": 1,
            "address": 1
        }}
    ]
    
    cursor = get_customer_collection().aggregate(pipeline)
    return [Customer(**doc) async for doc in cursor]

@router.get("/{customer_id}", response_model=Customer)
async def get_customer_by_id(customer_id: str):
    try:
        oid = ObjectId(customer_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    pipeline = [
        {"$match": {"_id": oid}},
        {"$project": {
            "_id": 0,
            "customerId": {"$toString": "$_id"},
            "customerName": 1,
            "customerPhoneNumber": 1,
            "status": 1,
            "address": 1
        }}
    ]
    
    result = await get_customer_collection().aggregate(pipeline).to_list(length=1)
    if not result:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return Customer(**result[0])

@router.patch("/{customer_id}", response_model=Customer)
async def update_customer(customer_id: str, customer_patch: CustomerPatch):
    try:
        oid = ObjectId(customer_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    updated_fields = {
        k: v for k, v in customer_patch.dict(exclude_unset=True).items()
        if v is not None
    }
    
    if updated_fields:
        await get_customer_collection().update_one(
            {"_id": oid},
            {"$set": updated_fields}
        )
            
    # Return updated doc via aggregation to ensure ID format consistency
    pipeline = [
        {"$match": {"_id": oid}},
        {"$project": {
            "_id": 0,
            "customerId": {"$toString": "$_id"},
            "customerName": 1,
            "customerPhoneNumber": 1,
            "status": 1,
            "address": 1
        }}
    ]
    
    result = await get_customer_collection().aggregate(pipeline).to_list(length=1)
    if not result:
         raise HTTPException(status_code=404, detail="Customer not found")

    return Customer(**result[0])

@router.delete("/{customer_id}")
async def delete_customer(customer_id: str):
    try:
        oid = ObjectId(customer_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    result = await get_customer_collection().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"message": "Customer deleted successfully"}



















