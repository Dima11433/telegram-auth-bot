import re
from typing import Dict, Any, List

COUNTRY_PREFIXES = [
    # Russia & Kazakhstan
    ('77', 'KZ', 'Казахстан', '🇰🇿', '+7'),
    ('76', 'KZ', 'Казахстан', '🇰🇿', '+7'),
    ('7', 'RU', 'Россия', '🇷🇺', '+7'),
    
    # CIS & Europe
    ('380', 'UA', 'Украина', '🇺🇦', '+380'),
    ('375', 'BY', 'Беларусь', '🇧🇾', '+375'),
    ('998', 'UZ', 'Узбекистан', '🇺🇿', '+998'),
    ('996', 'KG', 'Кыргызстан', '🇰🇬', '+996'),
    ('992', 'TJ', 'Таджикистан', '🇹🇯', '+992'),
    ('994', 'AZ', 'Азербайджан', '🇦🇿', '+994'),
    ('995', 'GE', 'Грузия', '🇬🇪', '+995'),
    ('374', 'AM', 'Армения', '🇦🇲', '+374'),
    ('373', 'MD', 'Молдова', '🇲🇩', '+373'),
    ('371', 'LV', 'Латвия', '🇱🇻', '+371'),
    ('370', 'LT', 'Литва', '🇱🇹', '+370'),
    ('372', 'EE', 'Эстония', '🇪🇪', '+372'),
    
    # North America
    ('1', 'US', 'США / Канада', '🇺🇸', '+1'),
    
    # Asia
    ('62', 'ID', 'Индонезия', '🇮🇩', '+62'),
    ('84', 'VN', 'Вьетнам', '🇻🇳', '+84'),
    ('63', 'PH', 'Филиппины', '🇵🇭', '+63'),
    ('91', 'IN', 'Индия', '🇮🇳', '+91'),
    ('86', 'CN', 'Китай', '🇨🇳', '+86'),
    ('880', 'BD', 'Бангладеш', '🇧🇩', '+880'),
    ('92', 'PK', 'Пакистан', '🇵🇰', '+92'),
    ('66', 'TH', 'Таиланд', '🇹🇭', '+66'),
    ('60', 'MY', 'Малайзия', '🇲🇾', '+60'),
    
    # Europe
    ('44', 'GB', 'Великобритания', '🇬🇧', '+44'),
    ('49', 'DE', 'Германия', '🇩🇪', '+49'),
    ('33', 'FR', 'Франция', '🇫🇷', '+33'),
    ('48', 'PL', 'Польша', '🇵🇱', '+48'),
    ('90', 'TR', 'Турция', '🇹🇷', '+90'),
    ('34', 'ES', 'Испания', '🇪🇸', '+34'),
    ('39', 'IT', 'Италия', '🇮🇹', '+39'),
    ('31', 'NL', 'Нидерланды', '🇳🇱', '+31'),
    ('420', 'CZ', 'Чехия', '🇨🇿', '+420'),
    ('40', 'RO', 'Румыния', '🇷🇴', '+40'),
    
    # Latin America
    ('55', 'BR', 'Бразилия', '🇧🇷', '+55'),
    ('52', 'MX', 'Мексика', '🇲🇽', '+52'),
    ('57', 'CO', 'Колумбия', '🇨🇴', '+57'),
    ('54', 'AR', 'Аргентина', '🇦🇷', '+54'),
    
    # Middle East & Africa
    ('234', 'NG', 'Нигерия', '🇳🇬', '+234'),
    ('20', 'EG', 'Египет', '🇪🇬', '+20'),
    ('254', 'KE', 'Кения', '🇰🇪', '+254'),
    ('27', 'ZA', 'ЮАР', '🇿🇦', '+27'),
    ('98', 'IR', 'Иран', '🇮🇷', '+98'),
]

def clean_phone_number(phone: str) -> str:
    if not phone:
        return ''
    return re.sub(r'\D', '', phone)

def get_country_info(phone: str) -> Dict[str, Any]:
    digits = clean_phone_number(phone)
    if not digits:
        return {
            'code': 'OTHER',
            'name': 'Другие',
            'flag': '🌐',
            'prefix': '+?',
            'display_name': '🌐 Другие'
        }

    for prefix, code, name, flag, display_prefix in COUNTRY_PREFIXES:
        if digits.startswith(prefix):
            return {
                'code': code,
                'name': name,
                'flag': flag,
                'prefix': display_prefix,
                'display_name': f'{flag} {name} ({display_prefix})'
            }

    return {
        'code': 'OTHER',
        'name': 'Другие',
        'flag': '🌐',
        'prefix': f'+{digits[:3]}',
        'display_name': f'🌐 Другие (+{digits[:3]})'
    }

def group_accounts_by_country(accounts: List[Any]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    
    for acc in accounts:
        c_info = get_country_info(acc.phone)
        code = c_info['code']
        if code not in groups:
            groups[code] = {
                'info': c_info,
                'accounts': []
            }
        groups[code]['accounts'].append(acc)

    return dict(sorted(groups.items(), key=lambda item: len(item[1]['accounts']), reverse=True))
