import re
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, status
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from .utils import get_payment_master_collection
from .models import PaymentMasterResponse, PaymentMasterWrite

router = APIRouter()




def _response(document: dict) -> PaymentMasterResponse:
    return PaymentMasterResponse(
        id=str(document["_id"]),
        paymentType=document["paymentType"],
        status=document.get("status") or "active",
    )


def _object_id(payment_id: str) -> ObjectId:
    if not ObjectId.is_valid(payment_id):
        raise HTTPException(status_code=404, detail="Payment method not found")
    return ObjectId(payment_id)


async def _duplicate(collection, payment_type: str, exclude_id=None) -> bool:
    key = payment_type.casefold()
    query = {
        "$or": [
            {"paymentTypeKey": key},
            {"paymentType": {"$regex": f"^{re.escape(payment_type)}$", "$options": "i"}},
        ]
    }
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    return await collection.find_one(query, {"_id": 1}) is not None


@router.get("/", response_model=List[PaymentMasterResponse])
async def list_payment_methods(status_filter: Optional[str] = Query(None, alias="status")):
    if status_filter not in (None, "active", "inactive"):
        raise HTTPException(status_code=422, detail="status must be active or inactive")
    query = {"status": status_filter} if status_filter == "inactive" else (
        {"$or": [{"status": "active"}, {"status": None}]} if status_filter == "active" else {}
    )
    documents = await get_payment_master_collection().find(query).sort("paymentType", ASCENDING).to_list(length=1000)
    return [_response(document) for document in documents]


@router.post("/", response_model=PaymentMasterResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_method(item: PaymentMasterWrite):
    collection = get_payment_master_collection()
    await collection.create_index(
        [("paymentTypeKey", ASCENDING)],
        unique=True,
        partialFilterExpression={"paymentTypeKey": {"$exists": True}},
        name="payment_master_type_unique",
    )
    if await _duplicate(collection, item.paymentType):
        raise HTTPException(status_code=409, detail="Payment method already exists")
    document = {
        "paymentType": item.paymentType,
        "paymentTypeKey": item.paymentType.casefold(),
        "status": "active",
    }
    try:
        result = await collection.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Payment method already exists")
    document["_id"] = result.inserted_id
    return _response(document)


@router.put("/{payment_id}", response_model=PaymentMasterResponse)
async def update_payment_method(payment_id: str, item: PaymentMasterWrite):
    collection = get_payment_master_collection()
    object_id = _object_id(payment_id)
    if await _duplicate(collection, item.paymentType, object_id):
        raise HTTPException(status_code=409, detail="Payment method already exists")
    try:
        document = await collection.find_one_and_update(
            {"_id": object_id},
            {"$set": {"paymentType": item.paymentType, "paymentTypeKey": item.paymentType.casefold()}},
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Payment method already exists")
    if document is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    return _response(document)


async def _set_status(payment_id: str, new_status: str) -> PaymentMasterResponse:
    document = await get_payment_master_collection().find_one_and_update(
        {"_id": _object_id(payment_id)},
        {"$set": {"status": new_status}},
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    return _response(document)


@router.patch("/{payment_id}/activate", response_model=PaymentMasterResponse)
async def activate_payment_method(payment_id: str):
    return await _set_status(payment_id, "active")


@router.patch("/{payment_id}/deactivate", response_model=PaymentMasterResponse)
async def deactivate_payment_method(payment_id: str):
    return await _set_status(payment_id, "inactive")
