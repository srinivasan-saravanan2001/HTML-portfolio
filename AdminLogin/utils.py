import secrets
from pymongo import MongoClient
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from .models import UserInDB
from fastapi import HTTPException, status
from typing import Optional

client = MongoClient("mongodb+srv://srini462001:srini654693@cluster0.60oy4.mongodb.net/?appName=Cluster0")
db = client["salesorder"] 
users_collection = db['adminlogin']  

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = secrets.token_hex(32)
print(f"Generated Secret Key: {SECRET_KEY}")  
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise JWTError
        return username
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_user(username: str) -> Optional[UserInDB]:
    user = users_collection.find_one({"username": username})
    if user:
        return UserInDB(username=user["username"], hashed_password=user["hashed_password"])
    return None

def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
