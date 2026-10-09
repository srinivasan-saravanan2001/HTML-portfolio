import re
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, status
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from .models import ItemMasterResponse, ItemMasterWrite
from .utils import get_birthdaycakevariance_collection

router = APIRouter()

ITEM_FIELDS = {
    "_id": 1,
    "itemCode": 1,
    "itemName": 1,
    "varianceName": 1,
    "variance_Defaultprice": 1,
    "variance_Uom": 1,
    "tax": 1,
    "status": 1,
}


def _response(document: dict) -> ItemMasterResponse:
    return ItemMasterResponse(
        id=str(document["_id"]),
        itemCode=document.get("itemCode"),
        itemName=document.get("itemName"),
        varianceName=document.get("varianceName"),
        variance_Defaultprice=document.get("variance_Defaultprice"),
        variance_Uom=document.get("variance_Uom"),
        tax=document.get("tax"),
        status=document.get("status") or "active",
    )


def _document_id(item_id: str):
    return ObjectId(item_id) if ObjectId.is_valid(item_id) else item_id


async def _next_item_code(collection) -> str:
    # Read numeric codes from ItemMaster itself; no UOM or counter collection is used.
    latest = await collection.aggregate([
        {"$match": {"itemCode": {"$regex": "^[0-9]{1,18}$"}}},
        {"$project": {"number": {"$toLong": "$itemCode"}}},
        {"$sort": {"number": -1}},
        {"$limit": 1},
    ]).to_list(length=1)
    next_number = (latest[0]["number"] if latest else 0) + 1
    return f"{next_number:06d}"


@router.get("/", response_model=List[ItemMasterResponse])
async def get_all_item_master(
    variance_name: Optional[str] = Query(None, description="Search item, variance, or item code"),
    page: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    if status_filter not in (None, "active", "inactive"):
        raise HTTPException(status_code=422, detail="status must be active or inactive")

    conditions = []
    if variance_name and variance_name.strip():
        expression = {"$regex": re.escape(variance_name.strip()), "$options": "i"}
        conditions.append({"$or": [
            {"varianceName": expression},
            {"itemName": expression},
            {"itemCode": expression},
        ]})
    if status_filter == "active":
        # Older ItemMaster records without status remain available to orders.
        conditions.append({"$or": [{"status": "active"}, {"status": None}]})
    elif status_filter == "inactive":
        conditions.append({"status": "inactive"})

    query = {"$and": conditions} if conditions else {}
    collection = get_birthdaycakevariance_collection()
    cursor = collection.find(query, ITEM_FIELDS).sort("_id", -1).skip(page * limit).limit(limit)
    documents = await cursor.to_list(length=limit)
    return [_response(document) for document in documents]


@router.post("/", response_model=ItemMasterResponse, status_code=status.HTTP_201_CREATED)
async def create_item_master(item: ItemMasterWrite):
    collection = get_birthdaycakevariance_collection()
    # Existing records may share a code. Uniqueness applies to records created here.
    await collection.create_index(
        [("itemCode", ASCENDING)],
        unique=True,
        partialFilterExpression={"_generatedItemCode": True},
        name="item_master_generated_code_unique",
    )

    for _ in range(10):
        code = await _next_item_code(collection)
        if await collection.find_one({"itemCode": code}, {"_id": 1}):
            continue
        document = item.model_dump()
        document.update({
            "itemCode": code,
            "status": "active",
            "_generatedItemCode": True,
        })
        try:
            result = await collection.insert_one(document)
        except DuplicateKeyError:
            continue
        document["_id"] = result.inserted_id
        return _response(document)

    raise HTTPException(status_code=409, detail="Could not reserve a unique item code. Please retry.")


@router.put("/{item_id}", response_model=ItemMasterResponse)
async def update_item_master(item_id: str, item: ItemMasterWrite):
    collection = get_birthdaycakevariance_collection()
    document = await collection.find_one_and_update(
        {"_id": _document_id(item_id)},
        {"$set": item.model_dump()},
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _response(document)


async def _set_status(item_id: str, new_status: str) -> ItemMasterResponse:
    collection = get_birthdaycakevariance_collection()
    document = await collection.find_one_and_update(
        {"_id": _document_id(item_id)},
        {"$set": {"status": new_status}},
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _response(document)


@router.patch("/{item_id}/activate", response_model=ItemMasterResponse)
async def activate_item_master(item_id: str):
    return await _set_status(item_id, "active")


@router.patch("/{item_id}/deactivate", response_model=ItemMasterResponse)
async def deactivate_item_master(item_id: str):
    return await _set_status(item_id, "inactive")
