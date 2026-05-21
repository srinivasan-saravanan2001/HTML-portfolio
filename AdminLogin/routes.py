import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from .models import User, Token
from .utils import authenticate_user, create_access_token, get_password_hash, users_collection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

@router.post("/create_user")
async def create_user(user: User):
    hashed_password = get_password_hash(user.password)
    existing_user = users_collection.find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    new_user = {"username": user.username, "hashed_password": hashed_password}
    users_collection.insert_one(new_user)
    return {"msg": "User created successfully"}

@router.post("/", response_model=Token)
async def login(user: User):
    try:
        db_user = authenticate_user(user.username, user.password)
        if not db_user:
            logger.warning(f"Login failed for user: {user.username}")
            raise HTTPException(status_code=400, detail="Incorrect username or password")

        access_token = create_access_token(data={"sub": user.username})
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        logger.error(f"Internal server error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    try:
        logger.info(f"Logout successful for token: {token[:10]}...")
        return {"msg": "Logged out successfully"}
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")