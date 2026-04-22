from motor.motor_asyncio import AsyncIOMotorClient

# Database Connection - Only the required DB
TEST_URI = "mongodb://admin:YenE580nOOUE6cDhQERP@194.233.78.90:27017/admin?appName=mongosh+2.1.1&authSource=admin&authMechanism=SCRAM-SHA-256&replicaSet=yenerp-cluster"
client = AsyncIOMotorClient(TEST_URI)
db_flutter = client["YENERP_LIVE_DB"]
customers = db_flutter["customer"]

# Helper function
def get_customer_collection():
    return customers