import re
import socket
import logging
from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import urlparse, parse_qs
import socks

logger = logging.getLogger(__name__)

def parse_proxy_string(proxy_str: str) -> Optional[Tuple[str, str, int, Optional[str], Optional[str]]]:
    """
    Parses various proxy formats into (protocol, host, port, username, password/secret):
    - ip:port:user:pass (or ip:port:login:password)
    - user:pass:ip:port (or login:password:ip:port)
    - user:pass@ip:port
    - ip:port@user:pass
    - socks5://user:pass@host:port or http://user:pass@host:port or mtproto://secret@host:port
    - Telegram MTProto links: https://t.me/proxy?server=...&port=...&secret=... or tg://proxy?...
    - Telegram SOCKS links: https://t.me/socks?server=...&port=...&user=...&pass=... or tg://socks?...
    - Telegram Text format:
        Server: ad1.arixo.shop
        Port: 443
        Secret: ee609a...
    - host:port:secret (MTProto)
    - host:port
    """
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None

    # Clean whitespace or surrounding quotes
    proxy_str = proxy_str.strip("\"'` ")

    # 1. Telegram MTProto link (https://t.me/proxy?... or tg://proxy?...)
    if "t.me/proxy" in proxy_str or "tg://proxy" in proxy_str or "tg:proxy" in proxy_str:
        q_str = proxy_str.split("?", 1)[1] if "?" in proxy_str else ""
        qs = parse_qs(q_str)
        server = qs.get("server", [None])[0]
        port = qs.get("port", [None])[0]
        secret = qs.get("secret", [None])[0]
        if server and port and port.isdigit() and secret:
            return "mtproto", server.strip(), int(port), None, secret.strip()

    # 2. Telegram SOCKS link (https://t.me/socks?... or tg://socks?...)
    if "t.me/socks" in proxy_str or "tg://socks" in proxy_str or "tg:socks" in proxy_str:
        q_str = proxy_str.split("?", 1)[1] if "?" in proxy_str else ""
        qs = parse_qs(q_str)
        server = qs.get("server", [None])[0]
        port = qs.get("port", [None])[0]
        user = qs.get("user", [None])[0]
        password = qs.get("pass", [None])[0]
        if server and port and port.isdigit():
            return "socks5", server.strip(), int(port), user, password

    # 3. Text block format from Telegram posts / settings
    server_m = re.search(r'(?:Server|Сервер|Host|IP|Айпи)[:\s]+([^\s\n\r]+)', proxy_str, re.IGNORECASE)
    port_m = re.search(r'(?:Port|Порт)[:\s]+(\d+)', proxy_str, re.IGNORECASE)
    secret_m = re.search(r'(?:Secret|Секрет|Ключ)[:\s]+([0-9a-fA-F]+)', proxy_str, re.IGNORECASE)
    user_m = re.search(r'(?:User|Username|Login|Логин|Пользователь)[:\s]+([^\s\n\r]+)', proxy_str, re.IGNORECASE)
    pass_m = re.search(r'(?:Pass|Password|Пароль)[:\s]+([^\s\n\r]+)', proxy_str, re.IGNORECASE)

    if server_m and port_m:
        srv = server_m.group(1).strip()
        prt = int(port_m.group(1))
        if secret_m:
            return "mtproto", srv, prt, None, secret_m.group(1).strip()
        usr = user_m.group(1).strip() if user_m else None
        pwd = pass_m.group(1).strip() if pass_m else None
        return "socks5", srv, prt, usr, pwd

    # 4. Format: protocol://[user:pass@]host:port or mtproto://secret@host:port
    if "://" in proxy_str:
        try:
            parsed = urlparse(proxy_str)
            protocol = parsed.scheme.lower()
            if protocol in ("mtproto", "mtproxy", "tg", "tgproxy"):
                host = parsed.hostname
                port = parsed.port
                secret = parsed.username or parsed.password or (parsed.query and parse_qs(parsed.query).get("secret", [None])[0])
                if host and port and secret:
                    return "mtproto", host, port, None, secret
            else:
                host = parsed.hostname
                port = parsed.port
                username = parsed.username
                password = parsed.password
                if host and port:
                    proto_clean = "http" if "http" in protocol else "socks5"
                    return proto_clean, host, port, username, password
        except Exception:
            pass

    # 5. Format: user:pass@host:port or host:port@user:pass
    if "@" in proxy_str:
        try:
            p1, p2 = proxy_str.split("@", 1)
            p1 = p1.strip()
            p2 = p2.strip()
            if ":" in p1 and ":" in p2:
                # Check which side is host:port
                p1_parts = p1.split(":")
                p2_parts = p2.split(":")
                if p1_parts[1].isdigit() and not p2_parts[1].isdigit():
                    # host:port @ user:pass
                    return "socks5", p1_parts[0].strip(), int(p1_parts[1].strip()), p2_parts[0].strip(), p2_parts[1].strip()
                elif p2_parts[1].isdigit():
                    # user:pass @ host:port
                    return "socks5", p2_parts[0].strip(), int(p2_parts[1].strip()), p1_parts[0].strip(), p1_parts[1].strip()
        except Exception:
            pass

    # 6. Colon-separated format:
    # Delimiters can be : or ; or tab or space
    cleaned_delims = proxy_str.replace(";", ":").replace("\t", ":").replace(" ", ":")
    parts = [p.strip() for p in cleaned_delims.split(":") if p.strip()]

    # Format: host:port:secret (MTProto with 32+ hex char secret)
    if len(parts) == 3:
        host, port_str, secret = parts
        if port_str.isdigit() and len(secret) >= 32:
            return "mtproto", host, int(port_str), None, secret

    # Format: host:port:user:pass OR user:pass:host:port
    if len(parts) == 4:
        # Check if parts[1] is port (ip:port:user:pass)
        if parts[1].isdigit():
            return "socks5", parts[0], int(parts[1]), parts[2], parts[3]
        # Check if parts[3] is port (user:pass:ip:port)
        elif parts[3].isdigit():
            return "socks5", parts[2], int(parts[3]), parts[0], parts[1]

    # Format: host:port
    if len(parts) == 2:
        host, port_str = parts
        if port_str.isdigit():
            return "socks5", host, int(port_str), None, None

    return None


def build_telethon_proxy_dict(protocol: str, host: str, port: int, username: Optional[str] = None, password: Optional[str] = None) -> Dict:
    if protocol.lower() in ("mtproto", "mtproxy"):
        return {
            "proxy_type": "mtproto",
            "addr": host,
            "port": port,
            "secret": password or username or ""
        }
    scheme_map = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP
    }
    return {
        "proxy_type": scheme_map.get(protocol.lower(), socks.SOCKS5),
        "addr": host,
        "port": port,
        "username": username,
        "password": password,
        "rdns": True
    }


async def test_proxy_connection(
    protocol: str,
    host: str,
    port: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 6.0
) -> Tuple[bool, str, str]:
    """
    Tests proxy connection. If protocol is socks5/http without explicit choice,
    tries SOCKS5 then HTTP to auto-detect the working protocol.
    Returns (success: bool, status_message: str, detected_protocol: str).
    """
    import asyncio
    loop = asyncio.get_running_loop()

    # 1. MTProto Proxy Check
    if protocol.lower() in ("mtproto", "mtproxy"):
        def _sync_mtproto_check():
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            return True
        try:
            await loop.run_in_executor(None, _sync_mtproto_check)
            return True, "✅ MTProto прокси доступен и отвечает", "mtproto"
        except Exception as e:
            return False, f"❌ MTProto недоступен: {e}", "mtproto"

    # 2. SOCKS5 / HTTP Proxy Check with Auto-Fallback
    protocols_to_try = ["socks5", "http"] if protocol.lower() in ("socks5", "http") else [protocol.lower()]
    last_err = ""

    for proto in protocols_to_try:
        def _sync_check(p_type_name):
            p_const = socks.SOCKS5 if p_type_name == "socks5" else (socks.SOCKS4 if p_type_name == "socks4" else socks.HTTP)
            s = socks.socksocket()
            s.set_proxy(p_const, host, port, True, username, password)
            s.settimeout(timeout)
            # Connect to Telegram MTProto DC2 IP
            s.connect(("149.154.167.50", 443))
            s.close()
            return True

        try:
            await loop.run_in_executor(None, lambda: _sync_check(proto))
            proto_title = "SOCKS5" if proto == "socks5" else "HTTP"
            return True, f"✅ {proto_title} прокси работает отлично!", proto
        except Exception as e:
            last_err = str(e)
            logger.debug(f"Proxy test {proto} failed: {e}")

    return False, f"❌ Ошибка подключения: {last_err}", protocol
