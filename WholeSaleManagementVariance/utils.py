from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb+srv://srini462001:srini654693@cluster0.60oy4.mongodb.net/?appName=Cluster0"
DATABASE_NAME = "salesorder"

COLLECTION_ITEM_MASTER = "ItemMaster"


client = AsyncIOMotorClient(MONGO_URL)
db = client[DATABASE_NAME]

def get_birthdaycakevariance_collection():
    
    return db[COLLECTION_ITEM_MASTER]
