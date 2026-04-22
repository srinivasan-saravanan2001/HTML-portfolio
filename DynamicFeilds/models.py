from datetime import datetime, date, time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
import re

class TimeSlot(BaseModel):
    from_time: str = Field(..., description="Start time in HH:MM AM/PM format")
    to_time: str = Field(..., description="End time in HH:MM AM/PM format")

    @validator('from_time')
    def validate_from_time_format(cls, v):
        time_pattern = r'^(0?[1-9]|1[0-2]):([0-5][0-9])\s?(AM|PM|am|pm)$'
        if not re.match(time_pattern, v.strip()):
            raise ValueError('from_time must be in HH:MM AM/PM format (e.g., 09:30 AM)')
        return v.upper()

    @validator('to_time')
    def validate_to_time_format(cls, v):
        time_pattern = r'^(0?[1-9]|1[0-2]):([0-5][0-9])\s?(AM|PM|am|pm)$'
        if not re.match(time_pattern, v.strip()):
            raise ValueError('to_time must be in HH:MM AM/PM format (e.g., 05:00 PM)')
        return v.upper()

    @validator('to_time')
    def validate_time_range(cls, v, values):
        if 'from_time' in values:
            from_time_str = values['from_time']
            to_time_str = v
            
            def to_24_hour(time_str):
                time_str = time_str.strip().upper()
                time_part, meridian = time_str.split()
                hour, minute = map(int, time_part.split(':'))
                
                if meridian == 'PM' and hour != 12:
                    hour += 12
                elif meridian == 'AM' and hour == 12:
                    hour = 0
                
                return hour * 60 + minute
            
            from_minutes = to_24_hour(from_time_str)
            to_minutes = to_24_hour(to_time_str)
            
            if to_minutes <= from_minutes:
                raise ValueError('to_time must be after from_time')
        
        return v

class DynamicFeilds(BaseModel):
    id: Optional[str] = None
    event_name: str                   
    event_date: str = Field(..., description="Event date in dd-mm-yyyy format")
    time_slots: List[TimeSlot] = Field(..., description="List of time slots for the event")
    column1: str
    column2: str
    column3: str
    column4: str
    column5: str
    is_active: bool = True

    @validator('event_date')
    def validate_event_date_format(cls, v):
        try:
            datetime.strptime(v, "%d-%m-%Y")
        except ValueError:
            raise ValueError('event_date must be in dd-mm-yyyy format')
        return v

    @validator('time_slots')
    def validate_time_slots(cls, v):
        if not v:
            raise ValueError('At least one time slot is required')
        return v

    class Config:
        extra = "forbid"
        json_encoders = {
            datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S"),
            TimeSlot: lambda v: v.dict()
        }

class DynamicFeildsUpdate(BaseModel):
    event_name: Optional[str] = None   
    event_date: Optional[str] = Field(None, description="Event date in dd-mm-yyyy format")
    time_slots: Optional[List[TimeSlot]] = Field(None, description="List of time slots for the event")
    column1: Optional[str] = None
    column2: Optional[str] = None
    column3: Optional[str] = None
    column4: Optional[str] = None
    column5: Optional[str] = None
    is_active: Optional[bool] = None

    @validator('event_date')
    def validate_event_date_format(cls, v):
        if v is not None:
            try:
                datetime.strptime(v, "%d-%m-%Y")
            except ValueError:
                raise ValueError('event_date must be in dd-mm-yyyy format')
        return v