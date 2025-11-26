import enum
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

class SeasonType(enum.Enum):
    SPRING = "spring"
    SUMMER = "summer" 
    AUTUMN = "autumn"
    WINTER = "winter"
    HALLOWEEN = "halloween"
    CHRISTMAS = "christmas"
    NEW_YEAR = "new_year"

@dataclass
class Season:
    id: int
    name: str
    type: SeasonType
    start_date: datetime
    end_date: datetime
    xp_multiplier: float
    coin_multiplier: float
    special_items: List[int]
    is_active: bool
