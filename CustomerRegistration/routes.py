from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timedelta
from pydantic import BaseModel
from .models import KidRegistration, KidRegistrationUpdate
from .utils import get_customerregistration_collection

router = APIRouter()
collection = get_customerregistration_collection()


# Response model with dd-mm-yyyy
class KidRegistrationResponse(BaseModel):
    id: str
    kids_name: str
    parent_name: str
    kids_age: str
    school: str
    location: str
    phone_raw_or_hash: Optional[str] = None
    is_active: bool = True
    created_at: str
    updated_at: str
    
    # Add dynamic fields
    column1: Optional[str] = None
    column2: Optional[str] = None
    column3: Optional[str] = None
    column4: Optional[str] = None
    column5: Optional[str] = None
    event_name: Optional[str] = None

    @staticmethod
    def from_doc(doc: dict) -> "KidRegistrationResponse":
        return KidRegistrationResponse(
            id=str(doc["_id"]),
            kids_name=doc["kids_name"],
            parent_name=doc["parent_name"],
            kids_age=doc["kids_age"],
            school=doc["school"],
            location=doc["location"],
            phone_raw_or_hash=doc.get("phone_raw_or_hash"),
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at", datetime.utcnow()).strftime("%d-%m-%Y"),
            updated_at=doc.get("updated_at", datetime.utcnow()).strftime("%d-%m-%Y"),
            column1=doc.get("column1"),
            column2=doc.get("column2"),
            column3=doc.get("column3"),
            column4=doc.get("column4"),
            column5=doc.get("column5"),
            event_name=doc.get("event_name"),
        )


# CREATE
@router.post("/", response_model=KidRegistrationResponse)
async def create(kid: KidRegistration):
    data = kid.model_dump(exclude={"id"})
    now = datetime.utcnow()
    data["created_at"] = data["updated_at"] = now

    result = await collection.insert_one(data)
    doc = await collection.find_one({"_id": result.inserted_id})
    return KidRegistrationResponse.from_doc(doc)


# GET ALL - NOW ACCEPTS DD-MM-YYYY (Indian Format)
@router.get("/", response_model=List[KidRegistrationResponse])
async def get_all(
    phone: Optional[str] = Query(None, description="Search by phone"),
    event_name: Optional[str] = Query(None, description="Filter by event name"),  # NEW FILTER
    start_date: Optional[str] = Query(None, description="From date: DD-MM-YYYY (e.g. 25-11-2025)"),
    end_date: Optional[str] = Query(None, description="To date: DD-MM-YYYY (e.g. 30-11-2025)"),
    active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    query = {}

    # Phone filter (EXISTING)
    if phone and phone.strip():
        if not phone.strip().isdigit():
            raise HTTPException(400, "Phone must contain only digits")
        query["phone_raw_or_hash"] = {"$regex": phone.strip(), "$options": "i"}

    # Event name filter (NEW)
    if event_name and event_name.strip():
        query["event_name"] = {"$regex": event_name.strip(), "$options": "i"}

    # Active filter (EXISTING)
    if active is not None:
        query["is_active"] = active

    # DATE FILTER - NOW ACCEPTS DD-MM-YYYY (EXISTING)
    if start_date or end_date:
        date_filter = {}

        if start_date:
            try:
                start_dt = datetime.strptime(start_date.strip(), "%d-%m-%Y")
                date_filter["$gte"] = start_dt
            except ValueError:
                raise HTTPException(400, "start_date must be in DD-MM-YYYY format (e.g. 25-11-2025)")

        if end_date:
            try:
                end_dt = datetime.strptime(end_date.strip(), "%d-%m-%Y")
                # Include full end day
                date_filter["$lte"] = end_dt + timedelta(days=1) - timedelta(seconds=1)
            except ValueError:
                raise HTTPException(400, "end_date must be in DD-MM-YYYY format (e.g. 30-11-2025)")

        if date_filter:
            query["created_at"] = date_filter

    # Execute (EXISTING)
    cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
    results = [KidRegistrationResponse.from_doc(doc) async for doc in cursor]
    return results



@router.get("/event/{event_name}", response_model=List[KidRegistrationResponse])
async def get_by_event_name(
    event_name: str,
    phone: Optional[str] = Query(None, description="Search by phone"),
    start_date: Optional[str] = Query(None, description="From date: DD-MM-YYYY"),
    end_date: Optional[str] = Query(None, description="To date: DD-MM-YYYY"),
    active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    query = {"event_name": {"$regex": event_name.strip(), "$options": "i"}}

    # Phone filter
    if phone and phone.strip():
        if not phone.strip().isdigit():
            raise HTTPException(400, "Phone must contain only digits")
        query["phone_raw_or_hash"] = {"$regex": phone.strip(), "$options": "i"}

    if active is not None:
        query["is_active"] = active

    # Date filter
    if start_date or end_date:
        date_filter = {}

        if start_date:
            try:
                start_dt = datetime.strptime(start_date.strip(), "%d-%m-%Y")
                date_filter["$gte"] = start_dt
            except ValueError:
                raise HTTPException(400, "start_date must be in DD-MM-YYYY format")

        if end_date:
            try:
                end_dt = datetime.strptime(end_date.strip(), "%d-%m-%Y")
                date_filter["$lte"] = end_dt + timedelta(days=1) - timedelta(seconds=1)
            except ValueError:
                raise HTTPException(400, "end_date must be in DD-MM-YYYY format")

        if date_filter:
            query["created_at"] = date_filter

    cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
    results = [KidRegistrationResponse.from_doc(doc) async for doc in cursor]
    
    if not results:
        raise HTTPException(404, f"No registrations found for event: {event_name}")
    
    return results



# GET ONE
@router.get("/{register_id}", response_model=KidRegistrationResponse)
async def get_one(register_id: str):
    if not ObjectId.is_valid(register_id):
        raise HTTPException(400, "Invalid ID")
    doc = await collection.find_one({"_id": ObjectId(register_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    return KidRegistrationResponse.from_doc(doc)


# UPDATE
@router.patch("/{register_id}", response_model=KidRegistrationResponse)
async def update(register_id: str, data: KidRegistrationUpdate):
    if not ObjectId.is_valid(register_id):
        raise HTTPException(400, "Invalid ID")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No data to update")

    update_data["updated_at"] = datetime.utcnow()
    result = await collection.update_one({"_id": ObjectId(register_id)}, {"$set": update_data})

    if result.modified_count == 0:
        raise HTTPException(404, "Not found or no changes")

    updated = await collection.find_one({"_id": ObjectId(register_id)})
    return KidRegistrationResponse.from_doc(updated)


# ACTIVATE / DEACTIVATE
@router.patch("/{register_id}/activate")
async def activate(register_id: str):
    if not ObjectId.is_valid(register_id):
        raise HTTPException(400, "Invalid ID")
    await collection.update_one({"_id": ObjectId(register_id)}, {"$set": {"is_active": True}})
    return {"message": "Activated"}


@router.patch("/{register_id}/deactivate")
async def deactivate(register_id: str):
    if not ObjectId.is_valid(register_id):
        raise HTTPException(400, "Invalid ID")
    await collection.update_one({"_id": ObjectId(register_id)}, {"$set": {"is_active": False}})
    return {"message": "Deactivated"}



