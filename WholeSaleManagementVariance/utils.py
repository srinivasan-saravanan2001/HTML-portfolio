from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb://localhost:27017/"
DATABASE_NAME = "salesorder"

COLLECTION_ITEM_MASTER = "ItemMaster"


client = AsyncIOMotorClient(MONGO_URL)
db = client[DATABASE_NAME]

def get_birthdaycakevariance_collection():
    
    return db[COLLECTION_ITEM_MASTER]
