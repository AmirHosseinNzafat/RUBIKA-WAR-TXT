# -*- coding: utf-8 -*-
"""ربات سیاست مدرن — نسخه روبیکا.

نقطه ورود اصلی. همه‌ی ماژول‌ها رو wire می‌کنه و منوی اصلی رو نمایش می‌ده.

اجرا:
    python main.py
"""

import asyncio
import sqlite3
import traceback

from rubpy import BotClient
from rubpy.bot import filters
from rubpy.bot.models import (
    Button, Keypad, KeypadRow, Update, InlineMessage,
)
from rubpy.bot.enums import ButtonTypeEnum, ChatTypeEnum, UpdateTypeEnum

import bot_config
import admin_panel
import asset_catalog
import country_assets
import trade_map
import trade_core
import trade_wizard
import trade_offer
import trade_system
import broadcast
import asset_ui


# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------


def _build_config():
    """پیکربندی رو از bot_config می‌خونه یا از کاربر می‌پرسه."""
    # نسخه روبیکا: توکن و آیدی‌ها از bot_config میاد
    try:
        import json, os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'bot_config.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    print("لطفاً فایل bot_config.json رو بساز:")
    print(json.dumps({
        "token": "CBAE...",
        "admin_id": "u0Hlb9H0510a64cd6029655af31e2c16",
        "channel_id": "c0DdIqc057ca4cadf20faa354de6075a",
        "war_channel_id": "c0DdIqc057ca4cadf20faa354de6075a",
        "lang": "fa",
    }, ensure_ascii=False, indent=2))
    raise SystemExit(1)


_conf = _build_config()
TOKEN = _conf['token']
ADMIN_ID = _conf['admin_id']
CHANNEL_ID = _conf['channel_id']
WAR_CHANNEL_ID = _conf.get('war_channel_id') or CHANNEL_ID
LANG = _conf.get('lang', 'fa')


# ---------------------------------------------------------------------------
# دیتابیس
# ---------------------------------------------------------------------------


conn = sqlite3.connect('game_bot.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    group_id TEXT,
    clothes INTEGER DEFAULT 2000,
    money INTEGER DEFAULT 2000,
    stones INTEGER DEFAULT 2000,
    wood INTEGER DEFAULT 2000,
    iron INTEGER DEFAULT 2000,
    gold INTEGER DEFAULT 2000,
    food INTEGER DEFAULT 2000,
    meat INTEGER DEFAULT 2000,
    swordsmen INTEGER DEFAULT 1500,
    gunmen INTEGER DEFAULT 1500,
    cavalry_swordsmen INTEGER DEFAULT 1500,
    cavalry_gunmen INTEGER DEFAULT 1500,
    special_guard INTEGER DEFAULT 1500,
    medium_cannons INTEGER DEFAULT 1500,
    large_cannons INTEGER DEFAULT 1500,
    small_ships INTEGER DEFAULT 1500,
    medium_ships INTEGER DEFAULT 1500,
    large_ships INTEGER DEFAULT 1500,
    caravans INTEGER DEFAULT 1500,
    stone_factory INTEGER DEFAULT 0,
    wood_factory INTEGER DEFAULT 0,
    iron_factory INTEGER DEFAULT 0,
    gold_mine INTEGER DEFAULT 0,
    farm INTEGER DEFAULT 0,
    animal_farm INTEGER DEFAULT 0,
    clothes_factory INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0,
    swordsmen_camp INTEGER DEFAULT 0,
    gunmen_camp INTEGER DEFAULT 0,
    cavalry_swordsmen_camp INTEGER DEFAULT 0,
    cavalry_gunmen_camp INTEGER DEFAULT 0,
    special_guard_camp INTEGER DEFAULT 0,
    medium_cannon_factory INTEGER DEFAULT 0,
    large_cannon_factory INTEGER DEFAULT 0,
    small_shipyard INTEGER DEFAULT 0,
    medium_shipyard INTEGER DEFAULT 0,
    large_shipyard INTEGER DEFAULT 0,
    treaties TEXT DEFAULT ''
)''')
conn.commit()


# ---------------------------------------------------------------------------
# BotClient
# ---------------------------------------------------------------------------


bot = BotClient(token=TOKEN)


# ---------------------------------------------------------------------------
# ابزار دکمه
# ---------------------------------------------------------------------------


def _btn(btn_id, text):
    return Button(id=str(btn_id), type=ButtonTypeEnum.SIMPLE, button_text=text)


def _kp(rows):
    return Keypad(rows=[KeypadRow(buttons=r) for r in rows if r])


# ---------------------------------------------------------------------------
# CallContext — یکسان‌سازی
# ---------------------------------------------------------------------------


class CallContext:
    """wrapper برای InlineMessage که ساختارش با تلگرام یکسان بشه."""

    def __init__(self, inline_msg: InlineMessage):
        self.raw = inline_msg
        self.chat_id = getattr(inline_msg, 'chat_id', None)
        self.user_id = getattr(inline_msg, 'sender_id', None)
        self.message_id = getattr(inline_msg, 'message_id', None)
        aux = getattr(inline_msg, 'aux_data', None)
        self.data = getattr(aux, 'button_id', '') if aux else ''
        self.client = getattr(inline_msg, 'client', None)

    async def answer(self, text=None, alert=False):
        """در روبیکا معادل مستقیم نداره. سعی می‌کنیم edit کنیم یا silent رد بشیم."""
        if not text:
            return
        # بعضی نسخه‌های rubpy ممکنه answer داشته باشن
        try:
            if hasattr(self.raw, 'answer'):
                await self.raw.answer(text)
                return
        except Exception:
            pass
        # در غیر این صورت فقط لاگ می‌کنیم
        # (چون در روبیکا دکمه‌ها خودشون loading رو می‌بندن)


def wrap(inline_msg):
    return CallContext(inline_msg)


# ---------------------------------------------------------------------------
# init همه ماژول‌ها
# ---------------------------------------------------------------------------


admin_panel.init(bot, conn, ADMIN_ID, lang=LANG)
asset_catalog.init(conn)
country_assets.attach(conn)
asset_ui.init(bot, conn, lang=LANG)

# broadcast
broadcast.init(bot, conn, CHANNEL_ID, WAR_CHANNEL_ID, lang=LANG,
               is_admin=admin_panel.is_admin)
broadcast.set_audit(admin_panel.log)

# trade
trade_system.init(bot, conn, ADMIN_ID, CHANNEL_ID, lang=LANG,
                  is_admin=admin_panel.is_admin,
                  is_owner=admin_panel.is_owner)


# ---------------------------------------------------------------------------
# منوی اصلی
# ---------------------------------------------------------------------------


MENU_BUTTONS = (
    ('assets', "💰 دارایی"),
    ('upgrade', "🛠️ ارتقا"),
    ('statement', "🙌 بیانیه"),
    ('private_message', "✉️ پیام خصوصی"),
    ('treaty', "📜 معاهده"),
    ('attack', "⚔️ لشکرکشی"),
    ('trd:menu', "🚢 تجارت جهانی"),
)


async def send_main_menu(chat_id, user_id):
    """منوی اصلی /start."""
    cursor.execute("SELECT 1 FROM users WHERE user_id=?", (str(user_id),))
    if not cursor.fetchone():
        await bot.send_message(
            chat_id,
            "شما هنوز لرد نیستید. یک ادمین باید روی پیام شما در گروه "
            "ریپلای کند و /setlord بزند.")
        return

    if not admin_panel.open_to(user_id):
        await bot.send_message(chat_id, admin_panel.closed_notice())
        return

    rows = []
    for data, label in MENU_BUTTONS:
        rows.append([_btn(data, label)])

    if admin_panel.is_admin(user_id):
        rows.append([_btn('ap:home', "🛡 پنل مدیریت")])
        rows.append([_btn('change_assets', "🛠️ تنظیم دارایی")])
        rows.append([_btn('trd:adm', "🌍 مدیریت تجارت")])

    await bot.send_message(chat_id, "خوش آمدین قربان",
                           inline_keypad=_kp(rows))


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


@bot.on_update(filters.commands('start'))
async def start(c, update: Update):
    await send_main_menu(update.chat_id,
                         update.new_message.sender_id if update.new_message else None)


# ---------------------------------------------------------------------------
# callback handler واحد برای همه دکمه‌ها
#
# rubpy از filters.button استفاده می‌کنه، پس یه handler سراسری می‌سازیم
# که هر کلیک رو می‌گیره و بر اساس button_id تصمیم می‌گیره.
# ---------------------------------------------------------------------------


@bot.on_update(filters.button(r".*", regex=True))
async def on_button(c, update):
    """همه‌ی callback های دکمه‌ها اینجا میان."""
    # در rubpy، callback ها از نوع InlineMessage میان نه Update
    # ولی filters.button روی Update هم کار می‌کنه (اگه new_message.aux_data داشته باشه)
    msg = getattr(update, 'new_message', None)
    if msg is None:
        msg = getattr(update, 'updated_message', None)
    if msg is None:
        return

    aux = getattr(msg, 'aux_data', None)
    if aux is None:
        return

    button_id = getattr(aux, 'button_id', '') or ''
    if not button_id:
        return

    # ساخت CallContext
    try:
        ctx = CallContext(msg)
        ctx.chat_id = update.chat_id
        ctx.user_id = getattr(msg, 'sender_id', None)
        ctx.data = button_id
    except Exception:
        traceback.print_exc()
        return

    try:
        await _dispatch(ctx, button_id)
    except Exception:
        traceback.print_exc()


async def _dispatch(call, data):
    """مسیریابی callback بر اساس پیشوند."""
    # ap: — admin panel
    if data.startswith('ap:'):
        await admin_panel.handle_callback(call)  # اگه داشت
        return

    # ag: — assets
    if data.startswith('ag:'):
        await asset_ui.handle_callback(call)
        return

    # bc: — broadcast (statement/campaign)
    if data.startswith('bc:'):
        await broadcast.handle_callback(call)
        return

    # trd: — trade
    if data.startswith('trd:'):
        await trade_system.handle_callback(call)
        return

    # دکمه‌های منوی اصلی
    if data == 'assets':
        await asset_ui.handle_assets_button(_fake_update(call))
    elif data == 'upgrade':
        await asset_ui.handle_upgrade_button(_fake_update(call))
    elif data == 'statement':
        await broadcast.start_statement(_fake_update(call), call.user_id)
    elif data == 'attack':
        await broadcast.start_campaign(_fake_update(call), call.user_id)
    elif data == 'change_assets':
        if not admin_panel.is_admin(call.user_id):
            await call.answer('شما ادمین نیستید.')
            return
        await asset_ui.handle_editor_button(_fake_update(call))
    else:
        # ناشناخته
        await call.answer()


def _fake_update(call):
    """ساخت یه شیء که interface Update رو داشته باشه ولی از InlineMessage ساخته بشه."""
    class FakeUpdate:
        pass
    u = FakeUpdate()
    u.chat_id = call.chat_id
    u.new_message = call.raw
    u.sender_id = call.user_id
    return u


# ---------------------------------------------------------------------------
# handler پیام‌های متنی (برای next_step)
# ---------------------------------------------------------------------------


@bot.on_update(filters.text)
async def on_text(c, update: Update):
    """هر پیام متنی — اگه کاربر توی حالت انتظار باشه به callback پاس می‌شه."""
    consumed = await admin_panel.handle_pending_text(update)
    if consumed:
        return
    # در غیر این صورت، به عنوان دستور /start سعی کن
    text = (update.new_message.text or '').strip().lower()
    if text in ('panel', 'پنل'):
        await send_main_menu(update.chat_id,
                             update.new_message.sender_id if update.new_message else None)


# ---------------------------------------------------------------------------
# /setlord و /unsetlord
# ---------------------------------------------------------------------------


@bot.on_update(filters.commands('setlord'))
async def set_lord(c, update: Update):
    """فقط ادمین می‌تونه لرد تعیین کنه."""
    msg = update.new_message
    if msg is None:
        return
    sender = msg.sender_id
    if not admin_panel.is_admin(sender):
        await bot.send_message(update.chat_id, "شما ادمین نیستید.")
        return

    # اگه ریپلای باشه، روی اون کاربر setlord می‌شه
    reply_to = getattr(msg, 'reply_to_message_id', None)
    if not reply_to:
        await bot.send_message(
            update.chat_id,
            "روی پیام بازیکن مورد نظر ریپلای کن و /setlord بزن.")
        return

    # TODO: پیدا کردن sender پیام ریپلای شده
    # فعلاً پیام فعلی رو استفاده می‌کنیم
    admin_panel.log(sender, 'setlord', str(update.chat_id), str(sender))
    await bot.send_message(update.chat_id, "✅ لرد تعیین شد.")


# ---------------------------------------------------------------------------
# اجرا
# ---------------------------------------------------------------------------


async def main():
    """شروع ربات + تیکر."""
    await bot.start()

    # تیکر محموله‌های تجارت
    asyncio.create_task(trade_system.start_ticker())

    print("✅ ربات سیاست مدرن فعال شد.")
    print(f"   admin_id: {ADMIN_ID}")
    print(f"   channel_id: {CHANNEL_ID}")

    # حلقه دریافت آپدیت
    await bot.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 خداحافظ")
    except Exception as e:
        print(f"❌ خطا: {e}")
        traceback.print_exc()
