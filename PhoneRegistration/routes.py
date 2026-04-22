from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from .models import OTPStartRequest, OTPVerifyRequest
from .utils import generate_otp, _send_sms, get_otp_collection

router = APIRouter()
otp_collection = get_otp_collection()

# ---------------------------------------------------
# SEND OTP
# ---------------------------------------------------
@router.post("/phone/start")
async def send_otp(payload: OTPStartRequest):
    phone = payload.phone.strip()

    if len(phone) < 10:
        raise HTTPException(400, "Invalid phone number")

    otp = generate_otp()

    # Save to DB (overwrite old OTP)
    await otp_collection.update_one(
        {"phone": phone},
        {
            "$set": {
                "otp": otp,
                "expires_at": datetime.utcnow() + timedelta(minutes=10)
            }
        },
        upsert=True
    )

    ok = await _send_sms(phone, otp)
    if not ok:
        raise HTTPException(500, "Failed to send OTP")

    return {"success": True, "message": "OTP sent"}


# ---------------------------------------------------
# VERIFY OTP
# ---------------------------------------------------
@router.post("/phone/verify")
async def verify_otp(payload: OTPVerifyRequest):
    phone = payload.phone.strip()
    otp = payload.otp.strip()

    record = await otp_collection.find_one({"phone": phone})

    if not record:
        raise HTTPException(404, "No OTP found")

    if record["expires_at"] < datetime.utcnow():
        raise HTTPException(400, "OTP expired")

    if record["otp"] != otp:
        raise HTTPException(400, "Invalid OTP")

    return {"verified": True}
