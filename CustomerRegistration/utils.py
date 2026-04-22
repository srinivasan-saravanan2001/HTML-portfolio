from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb://admin:YenE580nOOUE6cDhQERP@194.233.78.90:27017/admin?appName=mongosh+2.1.1&authSource=admin&authMechanism=SCRAM-SHA-256&replicaSet=yenerp-cluster"

client = AsyncIOMotorClient(MONGO_URL)
db = client["eventregistration"]

def get_customerregistration_collection():
    return db["customerregistrations"]
