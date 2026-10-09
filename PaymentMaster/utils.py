


from motor.motor_asyncio import AsyncIOMotorClient


client = AsyncIOMotorClient("mongodb+srv://srini462001:srini654693@cluster0.60oy4.mongodb.net/?appName=Cluster0")

def get_payment_master_collection():
    db=client["salesorder"]
    return db["paymentmaster"]
