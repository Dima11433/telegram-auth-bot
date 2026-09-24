from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery
from typing import Union
from config import ADMIN_IDS

class IsAdmin(Filter):
    """
    Filter to verify if user is listed in ADMIN_IDS or if no admins are specified yet.
    """
    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        user_id = event.from_user.id if event.from_user else 0
        if not ADMIN_IDS:
            # If no admins configured, allow first user or notify
            return True
        return user_id in ADMIN_IDS
