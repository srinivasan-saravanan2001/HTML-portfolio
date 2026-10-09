


from motor.motor_asyncio import AsyncIOMotorClient


client = AsyncIOMotorClient("mongodb://localhost:27017/")

def get_payment_master_collection():
    db=client["salesorder"]
    return db["paymentmaster"]
