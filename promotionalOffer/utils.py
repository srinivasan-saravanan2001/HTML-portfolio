# promotionalOffer/utils.py
from datetime import datetime, time, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── DB CLIENT SETUP ──
_client = AsyncIOMotorClient(
    'mongodb://admin:YenE580nOOUE6cDhQERP@194.233.78.90:27017/'
    'admin?appName=mongosh+2.1.1&authSource=admin'
    '&authMechanism=SCRAM-SHA-256&replicaSet=yenerp-cluster',
    maxPoolSize=20,
    minPoolSize=5,
    serverSelectionTimeoutMS=5000,
)
_db = _client["MasterAdmin_DB"]


IST = timezone(timedelta(hours=5, minutes=30))

def get_database(name: str):
    return _client[name]


def get_promtionaloffer_collection():
    return _db["PromotionalOffer"]


def parse_date(date_str):
    if not date_str:
        return None
    try:
        if isinstance(date_str, datetime):
            return date_str.date()
        if isinstance(date_str, str):
            if 'T' in date_str:
                date_str = date_str.split('T')[0]
            # Try YYYY-MM-DD
            if '-' in date_str and len(date_str.split('-')[0]) == 4:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            # Try DD-MM-YYYY
            elif '-' in date_str:
                return datetime.strptime(date_str, '%d-%m-%Y').date()
    except (ValueError, AttributeError) as e:
        logger.error(f"Date parsing error for '{date_str}': {e}")
    return None


def parse_time(time_str):
    if not time_str:
        return None
    try:
        if isinstance(time_str, time):
            return time_str
        if isinstance(time_str, str):
            time_str = time_str.strip().upper()
            if 'AM' in time_str or 'PM' in time_str:
                return datetime.strptime(time_str, '%I:%M %p').time()
            if ':' in time_str:
                parts = time_str.split(':')
                fmt = '%H:%M' if len(parts) == 2 else '%H:%M:%S'
                return datetime.strptime(time_str, fmt).time()
            if time_str.isdigit() and len(time_str) in [3, 4]:
                time_str = time_str.zfill(4)
                return time(int(time_str[:2]), int(time_str[2:]))
    except (ValueError, AttributeError) as e:
        logger.error(f"Time parsing error for '{time_str}': {e}")
    return None


def is_offer_expired(offer: dict) -> bool:
    now_utc = datetime.now(timezone.utc)
    
    # 2. Convert to IST
    now_ist = now_utc.astimezone(IST)
    
    # 3. Remove timezone info for comparison logic (cleaner for date/time extraction)
    now = now_ist.replace(tzinfo=None)
    
    current_date = now.date()
    current_time = now.time()
    current_weekday = now.strftime('%A')

    offer_id = offer.get('promotionalOfferId', 'unknown')
    logger.info(f"[{offer_id}] Server Check. IST Time: {now} | Date: {current_date}")

    # 1. End Date Check
    end_date_str = offer.get('endDate')
    if end_date_str:
        end_date = parse_date(end_date_str)
        if end_date:
            if current_date > end_date:
                logger.info(f"  -> Expired: {current_date} > {end_date}")
                return True

    # 2. Start Date Check
    start_date_str = offer.get('startDate')
    if start_date_str:
        start_date = parse_date(start_date_str)
        if start_date:
            if current_date < start_date:
                logger.info(f"  -> Not Started: {current_date} < {start_date}")
                return True

    # 3. Weekday Check
    allowed_days = offer.get('weekdays', [])
    if allowed_days and len(allowed_days) > 0:
        if current_weekday not in allowed_days:
            logger.info(f"  -> Expired: {current_weekday} not in {allowed_days}")
            return True

    # 4. Time Window Check
    from_time_str = offer.get('fromTime')
    to_time_str = offer.get('toTime')
    if from_time_str and to_time_str and from_time_str.strip() and to_time_str.strip():
        from_time = parse_time(from_time_str)
        to_time = parse_time(to_time_str)
        if from_time and to_time:
            logger.info(f"  -> Time: {current_time} vs {from_time}-{to_time}")
            
            if from_time < to_time:
                if not (from_time <= current_time <= to_time):
                    logger.info(f"  -> Expired: Time outside window")
                    return True
            else:
                if not (current_time >= from_time or current_time <= to_time):
                    logger.info(f"  -> Expired: Time outside overnight window")
                    return True

    logger.info(f"  -> Offer ACTIVE")
    return False