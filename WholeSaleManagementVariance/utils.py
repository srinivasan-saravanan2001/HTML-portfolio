from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException
from typing import Dict

MONGO_URL = "mongodb://safeuser:5pB4f6vaEFb%40%23%24@194.233.78.90:27017/?authSource=admin&replicaSet=yenerp-cluster"
DATABASE_NAME = "MasterAdmin_DB"

COLLECTION_ITEM_MASTER = "ItemMaster"
COLLECTION_UOM = "Uom"


client = AsyncIOMotorClient(MONGO_URL)
db = client[DATABASE_NAME]

def get_birthdaycakevariance_collection():
    return db[COLLECTION_ITEM_MASTER]

def get_uom_collection():
    return db[COLLECTION_UOM]

async def bulk_uom_ids_to_names(uom_ids: list[str]) -> Dict[str, str]:
    if not uom_ids:
        return {}
    unique_ids = list(set(uom_ids))
    
    cursor = get_uom_collection().find(
        {"uomId": {"$in": unique_ids}, "status": "active"},
        {"uomId": 1, "uom": 1, "_id": 0}
    )
    
    uom_docs = await cursor.to_list(length=len(unique_ids))
    return {doc["uomId"]: doc["uom"] for doc in uom_docs if doc.get("uom")}

async def uom_name_to_id(uom_name: str) -> str:
    uom_data = await get_uom_collection().find_one(
        {"uom": uom_name, "status": "active"},
        {"uomId": 1}
    )
    
    if not uom_data:
        raise HTTPException(status_code=404, detail=f"UOM '{uom_name}' not found")
    
    return uom_data["uomId"]