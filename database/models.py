import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class AccountStatus:
    ACTIVE = "ACTIVE"       # Valid and ready for sale/use
    ISSUED = "ISSUED"       # Given to a customer
    BANNED = "BANNED"       # Banned/Deactivated by Telegram
    INVALID = "INVALID"     # Session revoked/expired
    ERROR = "ERROR"         # Connection error

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(32), unique=True, index=True, nullable=False)
    session_name = Column(String(128), unique=True, nullable=False)
    
    # Telegram account profile data
    tg_user_id = Column(Integer, nullable=True)
    first_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)
    username = Column(String(128), nullable=True)
    dc_id = Column(Integer, nullable=True)
    
    # Security
    two_fa = Column(String(128), nullable=True)
    email = Column(String(128), nullable=True)
    
    # Status and Proxy
    status = Column(String(32), default=AccountStatus.ACTIVE, index=True)
    proxy_id = Column(Integer, ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True)
    
    # Owner (Seller) info
    owner_tg_id = Column(Integer, index=True, nullable=True)
    owner_username = Column(String(128), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    orders = relationship("OrderLink", back_populates="account", cascade="all, delete-orphan")
    proxy = relationship("Proxy", back_populates="accounts")

    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        name = " ".join([p for p in parts if p])
        return name if name else "Без имени"

    def display_tag(self) -> str:
        return f"@{self.username}" if self.username else f"ID: {self.tg_user_id or '—'}"


class OrderLink(Base):
    __tablename__ = "order_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    
    # Buyer who used the link
    buyer_tg_id = Column(Integer, nullable=True)
    buyer_username = Column(String(128), nullable=True)
    is_used = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime, nullable=True)
    last_accessed_at = Column(DateTime, nullable=True)

    # Relationship
    account = relationship("Account", back_populates="orders")


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    protocol = Column(String(16), default="socks5") # socks5, http, socks4, mtproto
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String(128), nullable=True)
    password = Column(String(255), nullable=True) # password or MTProto secret
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    accounts = relationship("Account", back_populates="proxy")

    def to_url(self) -> str:
        if self.protocol.lower() in ("mtproto", "mtproxy"):
            secret = self.password or self.username or ""
            return f"https://t.me/proxy?server={self.host}&port={self.port}&secret={secret}"
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"

    def to_telethon_dict(self) -> dict:
        import socks
        if self.protocol.lower() in ("mtproto", "mtproxy"):
            return {
                "proxy_type": "mtproto",
                "addr": self.host,
                "port": self.port,
                "secret": self.password or self.username or ""
            }
        scheme_map = {
            "socks5": socks.SOCKS5,
            "socks4": socks.SOCKS4,
            "http": socks.HTTP,
            "https": socks.HTTP
        }
        return {
            "proxy_type": scheme_map.get(self.protocol.lower(), socks.SOCKS5),
            "addr": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "rdns": True
        }


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)


class BotUser(Base):
    __tablename__ = "bot_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String(128), nullable=True)
    full_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_active = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

