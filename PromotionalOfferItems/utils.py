

from motor.motor_asyncio import AsyncIOMotorClient
MONGO_URI = ("mongodb://admin:YenE580nOOUE6cDhQERP@194.233.78.90:27017/admin?appName=mongosh+2.1.1&authSource=admin&authMechanism=SCRAM-SHA-256&replicaSet=yenerp-cluster")
client = AsyncIOMotorClient(MONGO_URI)

def get_db(name: str):
    return client[name]
def get_itemMaster_collection():
    return get_db("MasterAdmin_DB")["ItemMaster"]
def get_location_collection():
    return get_db("MasterAdmin_DB")["Location"]
def get_uom_collection():
    return get_db("MasterAdmin_DB")["Uom"]
def get_category_collection():
    return get_db("MasterAdmin_DB")["ItemCategory"]
def get_itemsubcategory_collection():
    return get_db("MasterAdmin_DB")["ItemSubCategory"]  
def get_orderType_collection():
    return get_db("MasterAdmin_DB")["OrderType"]