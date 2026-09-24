import re
from typing import Optional, Tuple

def extract_telegram_code(text: str) -> Optional[str]:
    """
    Extracts the login/verification code from official Telegram service messages (777000).
    Handles:
    - 'Login code: 12345. Do not give this code to anyone...'
    - 'Код подтверждения: 12345. Никому не сообщайте этот код...'
    - 'Ваш код для входа: 12345'
    - 'Код для входа: 12345'
    - 'Код входа: 12345'
    - 'Web login code: 12345'
    - 'Your code is 12345' / 'Your login code is 12345'
    - '12345 is your Telegram code' / '12345 — ваш код'
    - 'Код: 12345' / 'Code: 12345'
    - 'Giriş kodu: 12345' / 'Tasdiqlash kodi: 12345'
    - 'Kod: 12345' / 'Anmeldecode: 12345'
    - Any 5 or 6 digit sequence clearly in code position.
    """
    if not text:
        return None

    # Specific Telegram keyword patterns (highest precision)
    keyword_patterns = [
        r'(?:Login\s*code|Код\s*подтверждения|Web\s*login\s*code|Ваш\s*код\s*(?:для\s*входа)?|Код\s*(?:для\s*)?входа|Your\s*(?:login\s*)?code(?:\s*is)?|Giri[sş]\s*kodu|Tasdiqlash\s*kodi|Anmeldecode|Code|Код)[:\s]+(\d{5,6})\b',
        r'\b(\d{5,6})\b(?:\s*—|\s*-|\s*is|\s*–|\s*ваш|\s*is\s*your|\s*your|\s*.\s*Do\s*not|\s*.\s*Никому)',
        r'(?:быстрый\s*вход|quick\s*login|two-step\s*verification|двухэтапная\s*аутентификация)[:\s]+(\d{5,6})\b',
        r'(\d{5,6})[.\s]+(?:Do not give|Никому не|Please enter|Пожалуйста, введите|Never share)',
    ]

    for pattern in keyword_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)

    # Fallback: remove IPs and dates, then find any 5-6 digit number
    clean_text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', ' ', text)
    clean_text = re.sub(r'\b\d{2,4}[-./]\d{2}[-./]\d{2,4}\b', ' ', clean_text)
    
    digits_matches = re.findall(r'\b(\d{5,6})\b', clean_text)
    if digits_matches:
        return digits_matches[0]

    return None


def parse_telegram_service_message(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts verification code and metadata (e.g. Device, Location, IP) from Telegram message.
    """
    code = extract_telegram_code(text)
    
    details = []
    # Search for device/location info
    device_match = re.search(r'(?:Device|Устройство|Cihaz)[:\s]+([^\n\r]+)', text, re.IGNORECASE)
    if device_match:
        details.append(f"📱 Устройство: {device_match.group(1).strip()}")

    location_match = re.search(r'(?:Location|Местоположение|Город|Страна|Konum|Joylashuv)[:\s]+([^\n\r]+)', text, re.IGNORECASE)
    if location_match:
        details.append(f"🌍 Локация: {location_match.group(1).strip()}")

    ip_match = re.search(r'(?:IP|IP-адрес|IP-manzil)[:\s]+([^\n\r]+)', text, re.IGNORECASE)
    if ip_match:
        details.append(f"🌐 IP: {ip_match.group(1).strip()}")

    detail_str = "\n".join(details) if details else None
    return code, detail_str
