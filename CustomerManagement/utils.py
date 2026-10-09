from motor.motor_asyncio import AsyncIOMotorClient

# Database Connection - Only the required DB
TEST_URI = "mongodb+srv://srini462001:srini654693@cluster0.60oy4.mongodb.net/?appName=Cluster0"
client = AsyncIOMotorClient(TEST_URI)
db_flutter = client["salesorder"]
customers = db_flutter["customer"]

def get_customer_collection():
    return customers