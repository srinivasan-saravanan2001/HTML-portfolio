from fastapi import APIRouter, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional
from bson import ObjectId
from datetime import datetime
from .utils import get_dynamicfeilds_collection
from .models import DynamicFeilds, DynamicFeildsUpdate

router = APIRouter()

collection = get_dynamicfeilds_collection()


# Helper: Convert MongoDB doc → Python dict with string id
def doc_to_response(doc: dict) -> dict:
    if not doc:
        return {}
    doc["id"] = str(doc["_id"])
    doc.pop("_id", None)
    return doc


# CREATE - POST new registration (EXISTING)
@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_registration(payload: DynamicFeilds):
    doc = payload.dict(exclude_unset=True)
    doc["created_at"] = datetime.utcnow()
    doc["is_active"] = True

    result = await collection.insert_one(doc)
    created_doc = await collection.find_one({"_id": result.inserted_id})
    return doc_to_response(created_doc)


# READ ALL - GET list with pagination & filters (EXISTING)
@router.get("/", response_model=List[dict])
async def get_registrations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    phone: Optional[str] = Query(None, description="Filter by phone number (column6)"),
    event_name: Optional[str] = Query(None, description="Filter by event name"),
    start_date: Optional[str] = Query(None, description="dd-MM-yyyy"),
    end_date: Optional[str] = Query(None, description="dd-MM-yyyy"),
    active: Optional[bool] = Query(None, description="Filter by active status")
):
    query: dict = {}

    # Phone filter
    if phone:
        query["column6"] = {"$regex": phone.strip(), "$options": "i"}

    # Event name filter (exact or partial?)
    if event_name:
        query["event_name"] = {"$regex": event_name.strip(), "$options": "i"}  # case-insensitive partial

    # Active filter
    if active is not None:
        query["is_active"] = active

    # Date range filter (unchanged)
    if start_date or end_date:
        date_filter = {}
        if start_date:
            try:
                s = datetime.strptime(start_date, "%d-%m-%Y")
                date_filter["$gte"] = s
            except ValueError:
                raise HTTPException(400, "start_date must be in dd-MM-yyyy format")
        if end_date:
            try:
                e = datetime.strptime(end_date, "%d-%m-%Y")
                e = e.replace(hour=23, minute=59, second=59)
                date_filter["$lte"] = e
            except ValueError:
                raise HTTPException(400, "end_date must be in dd-MM-yyyy format")
        if date_filter:
            query["created_at"] = date_filter

    cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)

    return [doc_to_response(doc) for doc in docs]


# GET ALL EVENT NAMES ONLY - NEW SEPARATE ENDPOINT
@router.get("/events/names", response_model=List[str])
async def get_all_event_names():
    """
    Get only event names without other field data
    """
    pipeline = [
        {"$match": {"event_name": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$event_name"}},
        {"$sort": {"_id": 1}}
    ]
    
    cursor = collection.aggregate(pipeline)
    event_names = [doc["_id"] async for doc in cursor]
    
    return event_names


# GET ACTIVE EVENT NAMES ONLY - NEW SEPARATE ENDPOINT
@router.get("/events/names/active", response_model=List[str])
async def get_active_event_names():
    """
    Get only active event names without other field data
    """
    pipeline = [
        {"$match": {"event_name": {"$exists": True, "$ne": None}, "is_active": True}},
        {"$group": {"_id": "$event_name"}},
        {"$sort": {"_id": 1}}
    ]
    
    cursor = collection.aggregate(pipeline)
    event_names = [doc["_id"] async for doc in cursor]
    
    return event_names


# GET EVENT NAMES WITH BASIC INFO - NEW SEPARATE ENDPOINT
@router.get("/events/basic", response_model=List[dict])
async def get_event_names_with_basic_info():
    """
    Get event names with basic info (id, event_name, is_active)
    """
    pipeline = [
        {"$match": {"event_name": {"$exists": True, "$ne": None}}},
        {"$project": {
            "_id": 1,
            "event_name": 1,
            "is_active": 1,
            "created_at": 1
        }},
        {"$sort": {"event_name": 1}}
    ]
    
    cursor = collection.aggregate(pipeline)
    events = []
    async for doc in cursor:
        events.append({
            "id": str(doc["_id"]),
            "event_name": doc["event_name"],
            "is_active": doc.get("is_active", True),
            "created_at": doc.get("created_at", datetime.utcnow()).strftime("%d-%m-%Y")
        })
    
    return events


# GET EVENT NAMES WITH COUNT - NEW SEPARATE ENDPOINT
@router.get("/events/with-count", response_model=List[dict])
async def get_event_names_with_count():
    """
    Get event names with configuration count
    """
    pipeline = [
        {"$match": {"event_name": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": "$event_name",
            "config_count": {"$sum": 1},
            "active_configs": {
                "$sum": {"$cond": [{"$eq": ["$is_active", True]}, 1, 0]}
            }
        }},
        {"$sort": {"_id": 1}}
    ]
    
    cursor = collection.aggregate(pipeline)
    events = []
    async for doc in cursor:
        events.append({
            "event_name": doc["_id"],
            "total_configurations": doc["config_count"],
            "active_configurations": doc["active_configs"]
        })
    
    return events


# SEARCH EVENT NAMES - NEW SEPARATE ENDPOINT
@router.get("/events/search", response_model=List[str])
async def search_event_names(
    query: str = Query(..., description="Search term for event names"),
    limit: int = Query(20, ge=1, le=50)
):
    """
    Search event names by query string
    """
    pipeline = [
        {"$match": {
            "event_name": {"$regex": query.strip(), "$options": "i"}
        }},
        {"$group": {"_id": "$event_name"}},
        {"$sort": {"_id": 1}},
        {"$limit": limit}
    ]
    
    cursor = collection.aggregate(pipeline)
    event_names = [doc["_id"] async for doc in cursor]
    
    return event_names


# GET EVENT NAME BY ID - NEW SEPARATE ENDPOINT
@router.get("/{reg_id}/event-name", response_model=dict)
async def get_event_name_by_id(reg_id: str):
    """
    Get only event name for a specific configuration ID
    """
    if not ObjectId.is_valid(reg_id):
        raise HTTPException(400, "Invalid ID format")

    doc = await collection.find_one(
        {"_id": ObjectId(reg_id)},
        {"event_name": 1}  # Only return event_name field
    )
    
    if not doc:
        raise HTTPException(404, "Configuration not found")

    return {
        "id": str(doc["_id"]),
        "event_name": doc.get("event_name")
    }


# GET by ID (EXISTING)
@router.get("/{reg_id}", response_model=dict)
async def get_registration_by_id(reg_id: str):
    if not ObjectId.is_valid(reg_id):
        raise HTTPException(400, "Invalid ID format")

    doc = await collection.find_one({"_id": ObjectId(reg_id)})
    if not doc:
        raise HTTPException(404, "Registration not found")

    return doc_to_response(doc)


# UPDATE - PATCH (EXISTING)
@router.patch("/{reg_id}", response_model=dict)
async def update_registration(reg_id: str, payload: DynamicFeildsUpdate):
    if not ObjectId.is_valid(reg_id):
        raise HTTPException(400, "Invalid ID format")

    update_data = payload.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No data provided for update")

    result = await collection.update_one(
        {"_id": ObjectId(reg_id)},
        {"$set": update_data}
    )

    if result.modified_count == 0:
        # Check if exists
        exists = await collection.find_one({"_id": ObjectId(reg_id)})
        if not exists:
            raise HTTPException(404, "Registration not found")
        raise HTTPException(400, "No changes were made")

    updated_doc = await collection.find_one({"_id": ObjectId(reg_id)})
    return doc_to_response(updated_doc)


# ACTIVATE (EXISTING)
@router.post("/{reg_id}/activate", response_model=dict)
async def activate_registration(reg_id: str):
    if not ObjectId.is_valid(reg_id):
        raise HTTPException(400, "Invalid ID format")

    result = await collection.update_one(
        {"_id": ObjectId(reg_id)},
        {"$set": {"is_active": True}}
    )

    if result.modified_count == 0:
        doc = await collection.find_one({"_id": ObjectId(reg_id)})
        if not doc:
            raise HTTPException(404, "Not found")
        if doc.get("is_active"):
            raise HTTPException(400, "Already active")

    updated = await collection.find_one({"_id": ObjectId(reg_id)})
    return doc_to_response(updated)


# DEACTIVATE (EXISTING)
@router.post("/{reg_id}/deactivate", response_model=dict)
async def deactivate_registration(reg_id: str):
    if not ObjectId.is_valid(reg_id):
        raise HTTPException(400, "Invalid ID format")

    result = await collection.update_one(
        {"_id": ObjectId(reg_id)},
        {"$set": {"is_active": False}}
    )

    if result.modified_count == 0:
        doc = await collection.find_one({"_id": ObjectId(reg_id)})
        if not doc:
            raise HTTPException(404, "Not found")
        if not doc.get("is_active"):
            raise HTTPException(400, "Already deactivated")

    updated = await collection.find_one({"_id": ObjectId(reg_id)})
    return doc_to_response(updated)