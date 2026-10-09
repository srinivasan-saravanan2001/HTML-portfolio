from motor.motor_asyncio import AsyncIOMotorClient

# Database Connection - Only the required DB
TEST_URI = "mongodb://localhost:27017/"
client = AsyncIOMotorClient(TEST_URI)
db_flutter = client["salesorder"]
customers = db_flutter["customer"]

def get_customer_collection():
    return customers