import datetime
import uuid
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload

from config import DATABASE_URL
from database.models import Base, Account, OrderLink, Proxy, BotSetting, BotUser, AccountStatus

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate email column if not present in sqlite
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE accounts ADD COLUMN email VARCHAR(128)"))
        except Exception:
            pass

# --- Account CRUD ---

async def add_or_update_account(
    phone: str,
    session_name: str,
    tg_user_id: Optional[int] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    dc_id: Optional[int] = None,
    two_fa: Optional[str] = None,
    email: Optional[str] = None,
    status: str = AccountStatus.ACTIVE,
    proxy_id: Optional[int] = None,
    owner_tg_id: Optional[int] = None,
    owner_username: Optional[str] = None
) -> Account:
    async with async_session() as session:
        stmt = select(Account).where(Account.phone == phone)
        res = await session.execute(stmt)
        account = res.scalar_one_or_none()

        if account is None:
            account = Account(
                phone=phone,
                session_name=session_name,
                tg_user_id=tg_user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                dc_id=dc_id,
                two_fa=two_fa,
                email=email,
                status=status,
                proxy_id=proxy_id,
                owner_tg_id=owner_tg_id,
                owner_username=owner_username
            )
            session.add(account)
        else:
            account.session_name = session_name
            account.tg_user_id = tg_user_id or account.tg_user_id
            account.first_name = first_name or account.first_name
            account.last_name = last_name or account.last_name
            account.username = username or account.username
            account.dc_id = dc_id or account.dc_id
            if two_fa is not None:
                account.two_fa = two_fa
            if email is not None:
                account.email = email
            account.status = status
            if proxy_id:
                account.proxy_id = proxy_id
            if owner_tg_id:
                account.owner_tg_id = owner_tg_id
            if owner_username:
                account.owner_username = owner_username
            account.updated_at = datetime.datetime.now(datetime.timezone.utc)

        await session.commit()
        await session.refresh(account)
        return account

async def get_account_by_id(account_id: int, owner_tg_id: Optional[int] = None) -> Optional[Account]:
    async with async_session() as session:
        query = select(Account).options(selectinload(Account.proxy)).where(Account.id == account_id)
        if owner_tg_id is not None:
            query = query.where(Account.owner_tg_id == owner_tg_id)
        res = await session.execute(query)
        return res.scalar_one_or_none()

async def get_account_by_phone(phone: str, owner_tg_id: Optional[int] = None) -> Optional[Account]:
    async with async_session() as session:
        query = select(Account).options(selectinload(Account.proxy)).where(Account.phone == phone)
        if owner_tg_id is not None:
            query = query.where(Account.owner_tg_id == owner_tg_id)
        res = await session.execute(query)
        return res.scalar_one_or_none()

async def get_accounts_list(
    owner_tg_id: Optional[int] = None,
    status: Optional[str] = None,
    offset: int = 0,
    limit: int = 10,
    include_unassigned: bool = False
) -> Tuple[List[Account], int]:
    async with async_session() as session:
        from sqlalchemy import or_
        query = select(Account).options(selectinload(Account.proxy))
        count_query = select(func.count(Account.id))

        if owner_tg_id is not None:
            if include_unassigned:
                condition = or_(Account.owner_tg_id == owner_tg_id, Account.owner_tg_id.is_(None))
            else:
                condition = (Account.owner_tg_id == owner_tg_id)
            query = query.where(condition)
            count_query = count_query.where(condition)

        if status:
            query = query.where(Account.status == status)
            count_query = count_query.where(Account.status == status)

        query = query.order_by(Account.id.desc()).offset(offset).limit(limit)
        
        accounts_res = await session.execute(query)
        count_res = await session.execute(count_query)

        return list(accounts_res.scalars().all()), count_res.scalar() or 0

async def get_all_accounts(
    owner_tg_id: Optional[int] = None,
    status: Optional[str] = None,
    include_unassigned: bool = False
) -> List[Account]:
    async with async_session() as session:
        from sqlalchemy import or_
        query = select(Account).options(selectinload(Account.proxy))
        if owner_tg_id is not None:
            if include_unassigned:
                query = query.where(or_(Account.owner_tg_id == owner_tg_id, Account.owner_tg_id.is_(None)))
            else:
                query = query.where(Account.owner_tg_id == owner_tg_id)
        if status:
            query = query.where(Account.status == status)
        res = await session.execute(query.order_by(Account.id.asc()))
        return list(res.scalars().all())

async def count_unique_sellers() -> int:
    async with async_session() as session:
        query = select(func.count(func.distinct(Account.owner_tg_id))).where(Account.owner_tg_id.isnot(None))
        res = await session.execute(query)
        return res.scalar() or 0

async def sync_sessions_from_disk():
    """
    Auto-recovery scanner: scans SESSIONS_DIR for .session files on disk
    and adds any missing accounts into the SQLite database automatically.
    """
    import logging
    from services.session_manager import validate_session
    from config import SESSIONS_DIR, ADMIN_IDS

    logger = logging.getLogger("recovery_sync")
    primary_admin = ADMIN_IDS[0] if ADMIN_IDS else None
    session_files = list(SESSIONS_DIR.glob("*.session"))
    if not session_files:
        return

    async with async_session() as session:
        res = await session.execute(select(Account.session_name))
        existing_names = set(res.scalars().all())

    restored_count = 0
    for s_file in session_files:
        if s_file.name not in existing_names:
            logger.info(f"🔄 Восстановление сессии с диска: {s_file.name}...")
            is_valid, user_info, err = await validate_session(s_file)
            if is_valid and user_info:
                phone = user_info.get("phone") or s_file.name.replace(".session", "")
                await add_or_update_account(
                    phone=phone,
                    session_name=s_file.name,
                    tg_user_id=user_info.get("tg_user_id"),
                    first_name=user_info.get("first_name"),
                    last_name=user_info.get("last_name"),
                    username=user_info.get("username"),
                    dc_id=user_info.get("dc_id"),
                    owner_tg_id=primary_admin,
                    status=AccountStatus.ACTIVE
                )
                logger.info(f"✅ Сессия {phone} ({s_file.name}) успешно восстановлена в базе данных!")
                restored_count += 1
            else:
                logger.warning(f"⚠️ Файл {s_file.name} не удалось валидировать: {err}")

    if restored_count > 0:
        logger.info(f"🎉 Восстановлено {restored_count} аккаунтов с диска в базу данных!")

async def update_account_status(account_id: int, status: str):
    async with async_session() as session:
        stmt = update(Account).where(Account.id == account_id).values(status=status, updated_at=datetime.datetime.now(datetime.timezone.utc))
        await session.execute(stmt)
        await session.commit()

async def update_account_info(account_id: int, **kwargs):
    async with async_session() as session:
        kwargs["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        stmt = update(Account).where(Account.id == account_id).values(**kwargs)
        await session.execute(stmt)
        await session.commit()

async def delete_account_by_id(account_id: int) -> bool:
    async with async_session() as session:
        stmt = delete(Account).where(Account.id == account_id)
        res = await session.execute(stmt)
        await session.commit()
        return res.rowcount > 0

# --- OrderLink CRUD ---

async def create_order_link(account_id: int, expires_hours: Optional[int] = None) -> OrderLink:
    async with async_session() as session:
        # Deactivate any previous active links for this account
        await session.execute(
            update(OrderLink)
            .where(OrderLink.account_id == account_id, OrderLink.is_active == True)
            .values(is_active=False)
        )
        token = uuid.uuid4().hex[:14]
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=expires_hours) if expires_hours else None
        
        order = OrderLink(
            token=token,
            account_id=account_id,
            expires_at=expires_at,
            is_active=True
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order

async def get_order_link_by_token(token: str) -> Optional[OrderLink]:
    async with async_session() as session:
        stmt = (
            select(OrderLink)
            .options(selectinload(OrderLink.account).selectinload(Account.proxy))
            .where(OrderLink.token == token)
            .order_by(OrderLink.id.desc())
        )
        res = await session.execute(stmt)
        return res.scalars().first()

async def mark_order_link_accessed(token: str, buyer_tg_id: int, buyer_username: Optional[str] = None):
    async with async_session() as session:
        stmt = (
            update(OrderLink)
            .where(OrderLink.token == token)
            .values(
                buyer_tg_id=buyer_tg_id,
                buyer_username=buyer_username,
                is_used=True,
                last_accessed_at=datetime.datetime.now(datetime.timezone.utc)
            )
        )
        await session.execute(stmt)
        await session.commit()

async def get_existing_active_link_for_account(account_id: int) -> Optional[OrderLink]:
    async with async_session() as session:
        stmt = (
            select(OrderLink)
            .where(OrderLink.account_id == account_id, OrderLink.is_active == True)
            .order_by(OrderLink.created_at.desc(), OrderLink.id.desc())
        )
        res = await session.execute(stmt)
        return res.scalars().first()


async def get_or_create_web_token_for_account(account_id: int) -> str:
    link = await get_existing_active_link_for_account(account_id)
    if link and link.token:
        return link.token
    new_link = await create_order_link(account_id)
    return new_link.token

# --- Proxy CRUD ---

async def add_proxy(protocol: str, host: str, port: int, username: Optional[str] = None, password: Optional[str] = None) -> Proxy:
    async with async_session() as session:
        proxy = Proxy(
            protocol=protocol.lower(),
            host=host,
            port=port,
            username=username,
            password=password
        )
        session.add(proxy)
        await session.commit()
        await session.refresh(proxy)
        return proxy

async def get_all_proxies() -> List[Proxy]:
    async with async_session() as session:
        res = await session.execute(select(Proxy).order_by(Proxy.id.asc()))
        return list(res.scalars().all())

async def delete_proxy(proxy_id: int) -> bool:
    async with async_session() as session:
        res = await session.execute(delete(Proxy).where(Proxy.id == proxy_id))
        await session.commit()
        return res.rowcount > 0

async def get_first_active_proxy() -> Optional[Proxy]:
    async with async_session() as session:
        res = await session.execute(select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id.asc()))
        return res.scalars().first()

async def get_proxy_by_id(proxy_id: int) -> Optional[Proxy]:
    async with async_session() as session:
        res = await session.execute(select(Proxy).where(Proxy.id == proxy_id))
        return res.scalars().first()

async def set_active_proxy(proxy_id: Optional[int]) -> None:
    async with async_session() as session:
        await session.execute(update(Proxy).values(is_active=False))
        if proxy_id is not None:
            await session.execute(update(Proxy).where(Proxy.id == proxy_id).values(is_active=True))
        await session.commit()

async def update_proxy_status(proxy_id: int, is_active: bool, protocol: Optional[str] = None) -> None:
    async with async_session() as session:
        vals = {"is_active": is_active}
        if protocol:
            vals["protocol"] = protocol.lower()
        await session.execute(update(Proxy).where(Proxy.id == proxy_id).values(**vals))
        await session.commit()

# --- Settings ---

async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    async with async_session() as session:
        res = await session.execute(select(BotSetting).where(BotSetting.key == key))
        setting = res.scalars().first()
        return setting.value if setting else default

async def set_setting(key: str, value: str):
    async with async_session() as session:
        res = await session.execute(select(BotSetting).where(BotSetting.key == key))
        setting = res.scalars().first()
        if setting:
            setting.value = value
        else:
            session.add(BotSetting(key=key, value=value))
        await session.commit()

# --- Bot Users Tracking ---

async def register_or_update_bot_user(
    tg_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None
) -> Tuple[BotUser, bool]:
    """
    Registers a new bot user or updates existing user's activity.
    Returns (bot_user, is_new).
    """
    async with async_session() as session:
        res = await session.execute(select(BotUser).where(BotUser.tg_id == tg_id))
        user = res.scalars().first()
        is_new = False
        
        if user is None:
            user = BotUser(
                tg_id=tg_id,
                username=username,
                full_name=full_name
            )
            session.add(user)
            is_new = True
        else:
            user.username = username or user.username
            user.full_name = full_name or user.full_name
            user.last_active = datetime.datetime.now(datetime.timezone.utc)

        await session.commit()
        await session.refresh(user)
        return user, is_new


async def get_bot_user_by_tg_id(tg_id: int) -> Optional[BotUser]:
    async with async_session() as session:
        res = await session.execute(select(BotUser).where(BotUser.tg_id == tg_id))
        return res.scalars().first()


async def count_total_bot_users() -> int:
    async with async_session() as session:
        res = await session.execute(select(func.count(BotUser.id)))
        return res.scalar() or 0

