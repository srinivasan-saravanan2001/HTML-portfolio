import random
import logging
import httpx
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

MONGO_URL = "mongodb://admin:YenE580nOOUE6cDhQERP@194.233.78.90:27017/admin?appName=mongosh+2.1.1&authSource=admin&authMechanism=SCRAM-SHA-256&replicaSet=yenerp-cluster"

client = AsyncIOMotorClient(MONGO_URL)
db = client["eventregistration"]

def get_otp_collection():
    return db["registerotp"]
    
def generate_otp():
    return str(random.randint(1000, 9999))

async def _send_sms(phone: str, otp: str) -> bool:
    url = (
        f"https://mailcon.in/vb/apikey.php"
        f"?apikey=w31prN4CCtJg7XvK"
        f"&senderid=BMUMMY"
        f"&templateid=1707171032032584299"
        f"&number={phone}"
        f"&message=Dear User, use this OTP {otp} to install the Bestmummy YenERP APP, "
        f"do not share this code with Anyone - This OTP will be valid for the next 10 mins."
    )

    logger.info(f"OTP URL => {url}")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            logger.info(f"SMS Response => {r.status_code} | {r.text}")
            return r.status_code == 200
    except Exception as e:
        logger.error(f"SMS sending failed: {e}")
        return False
