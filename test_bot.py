import asyncio
import os
import unittest
from utils.code_extractor import extract_telegram_code, parse_telegram_service_message
from database.db import (
    init_db,
    add_or_update_account,
    get_account_by_phone,
    get_account_by_id,
    get_accounts_list,
    get_all_accounts,
    create_order_link,
    get_order_link_by_token,
    mark_order_link_accessed,
    delete_account_by_id
)
from database.models import AccountStatus

class TestTelegramBotFeatures(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()

    def test_code_extractor(self):
        msg1 = "Login code: 74819. Do not give this code to anyone, even if they say they are from Telegram!"
        code1, details1 = parse_telegram_service_message(msg1)
        self.assertEqual(code1, "74819")

        msg2 = "Код подтверждения: 91823. Никому не сообщайте этот код!\n\nУстройство: Telegram Desktop\nМестоположение: Москва, Россия\nIP: 185.220.101.5"
        code2, details2 = parse_telegram_service_message(msg2)
        self.assertEqual(code2, "91823")
        self.assertIn("Telegram Desktop", details2)
        self.assertIn("Москва", details2)

    async def test_db_account_lifecycle(self):
        import time
        ts = int(time.time())
        test_phone_1 = f"+79998{ts % 1000000:06d}"
        test_phone_2 = f"+79991{ts % 1000000:06d}"
        session_name_1 = f"test_acc_1_{ts}.session"
        session_name_2 = f"test_acc_2_{ts}.session"
        
        initial_all = len(await get_all_accounts(owner_tg_id=None))

        # 1. User A (id: 111) adds Account 1
        acc1 = await add_or_update_account(
            phone=test_phone_1,
            session_name=session_name_1,
            first_name="UserA",
            owner_tg_id=111,
            owner_username="seller_a",
            status=AccountStatus.ACTIVE
        )

        # 2. User B (id: 222) adds Account 2
        acc2 = await add_or_update_account(
            phone=test_phone_2,
            session_name=session_name_2,
            first_name="UserB",
            owner_tg_id=222,
            owner_username="seller_b",
            status=AccountStatus.ACTIVE
        )

        # 3. Test Isolation: User A only sees Account 1
        accs_a, count_a = await get_accounts_list(owner_tg_id=111)
        self.assertEqual(count_a, 1)
        self.assertEqual(accs_a[0].phone, test_phone_1)

        # User A cannot get Account 2
        forbidden_acc = await get_account_by_id(acc2.id, owner_tg_id=111)
        self.assertIsNone(forbidden_acc)

        # 4. Test Superadmin: can see ALL accounts
        all_accs = await get_all_accounts(owner_tg_id=None)
        self.assertEqual(len(all_accs), initial_all + 2)

        # Superadmin can get Account 2 directly
        admin_acc = await get_account_by_id(acc2.id, owner_tg_id=None)
        self.assertIsNotNone(admin_acc)

        # 5. Order link creation
        order = await create_order_link(acc1.id)
        self.assertIsNotNone(order.token)

        # 6. Cleanup
        await delete_account_by_id(acc1.id)
        await delete_account_by_id(acc2.id)

if __name__ == "__main__":
    unittest.main()
