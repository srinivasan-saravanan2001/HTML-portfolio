from fastapi import APIRouter, Query
from typing import List, Optional
from .models import ItemMasterResponse
from .utils import get_birthdaycakevariance_collection, bulk_uom_ids_to_names

router = APIRouter()

@router.get("/", response_model=List[ItemMasterResponse])
async def get_all_item_master(
    variance_name: Optional[str] = Query(None, description="Search by variance name or item name"),
    page: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
):
    collection = get_birthdaycakevariance_collection()

    query = {
        "$and": [
            {"itemName": {"$ne": "SFGitem"}},
            {"$or": [
                {"variance_Defaultprice": {"$ne": 0}},
                {"variance_Defaultprice": {"$exists": False}} 
            ]}
        ]
    }

    if variance_name:
        query["$and"].append({
            "$or": [
                {"varianceName": {"$regex": variance_name, "$options": "i"}},
                {"itemName": {"$regex": variance_name, "$options": "i"}},
            ]
        })

    cursor = collection.find(
        query,
        {
            "_id": 0,
            "itemCode": 1,
            "itemName": 1,
            "varianceName": 1,
            "variance_Defaultprice": 1,
            "variance_Uom": 1,
            "tax": 1,
        }
    ).skip(page * limit).limit(limit)

    documents = await cursor.to_list(length=limit)

    if not documents:
        return []

    uom_ids = list({doc.get("variance_Uom") for doc in documents if doc.get("variance_Uom")})

    uom_mapping = await bulk_uom_ids_to_names(uom_ids)

    items = []
    for doc in documents:
        uom_id = doc.get("variance_Uom", "")
        
        doc["variance_Uom"] = uom_mapping.get(uom_id, uom_id) 
        items.append(ItemMasterResponse(**doc))

    return items