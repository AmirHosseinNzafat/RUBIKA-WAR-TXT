# -*- coding: utf-8 -*-
"""پنل ادمین ربات سیاست مدرن — نسخه روبیکا.

این فایل پایه‌ی همه‌ی ماژول‌های دیگه‌ست. این‌ها رو صادر می‌کنه:

    init()              — اتصال به BotClient و دیتابیس
    is_admin(user_id)   — بررسی ادمین بودن
    is_owner(user_id)   — بررسی مالک بودن
    require_admin(call) — گارد ادمین برای handler ها
    require_owner(call) — گارد مالک
    log(...)            — ثبت لاگ اقدامات
    next_step(...)      — ثبت callback برای پیام بعدی کاربر
    CallContext         — wrapper یکسان برای callback تلگرام/روبیکا

نکات مهم برای روبیکا:
    - همه‌ی handler ها async هستن
    - دکمه‌ها با Keypad ساخته می‌شن نه InlineKeyboardMarkup
    - callback_data به button.id تبدیل می‌شه
    - برای انتظار پیام بعدی از states استفاده می‌شه
"""

import asyncio
import html
import json
import os
import sqlite3
import threading
import time
import traceback

from rubpy.bot.models import (
    Button, Keypad, KeypadRow, Update, InlineMessage,
)
from rubpy.bot.enums import ButtonTypeEnum


# ---------------------------------------------------------------------------
# وضعیت ماژول
# ---------------------------------------------------------------------------

_bot = None
_conn = None
_owner_id = None
_lang = 'fa'
_lock = threading.RLock()

# جریان‌های "منتظر پیام بعدی" — user_id -> callable(async)
_pending_steps = {}

# کش برای عنوان گروه‌ها و نام کاربران
_title_cache = {}
_name_cache = {}

# کلمات ترجمه‌شده
STRINGS = {
    'fa': {
        'not_admin': "شما ادمین نیستید.",
        'not_owner': "فقط مالک ربات می‌تواند این کار را انجام دهد.",
        'err_generic': "خطایی رخ داد. دوباره تلاش کنید.",
        'bot_off': "ربات در حال حاضر بسته است. با مدیریت تماس بگیرید.",
        'btn_back': "🔙 بازگشت",
        'btn_prev': "➡️ قبلی",
        'btn_next': "بعدی ⬅️",
        'panel_title': "🛡 پنل مدیریت",
    },
    'en': {
        'not_admin': "You are not an admin.",
        'not_owner': "Only the bot owner can do that.",
        'err_generic': "Something went wrong. Please try again.",
        'bot_off': "The bot is currently closed. Please contact an admin.",
        'btn_back': "🔙 Back",
        'btn_prev': "⬅️ Prev",
        'btn_next': "Next ➡️",
        'panel_title': "🛡 Admin Panel",
    },
    'tr': {
        'not_admin': "Yönetici değilsiniz.",
        'not_owner': "Bunu yalnızca bot sahibi yapabilir.",
        'err_generic': "Bir hata oluştu. Lütfen tekrar deneyin.",
        'bot_off': "Bot şu anda kapalı. Lütfen bir yöneticiye başvurun.",
        'btn_back': "🔙 Geri",
        'btn_prev': "⬅️ Önceki",
        'btn_next': "Sonraki ➡️",
        'panel_title': "🛡 Yönetim Paneli",
    },
}


# ---------------------------------------------------------------------------
# CallContext — یکسان‌سازی callback تلگرام و روبیکا
# ---------------------------------------------------------------------------


class CallContext:
    """Wrapper برای callback های rubpy که ساختارش رو با تلگرام یکسان می‌کنه.

    در rubpy، callback معمولاً یه Update با type='ReceiveInlineMessage' هست
    و مقادیر داخل new_message / aux_data قرار دارن. این کلاس اون‌ها رو
    به فیلدهای ساده تبدیل می‌کنه تا بقیه کد نیازی به دونستن ساختار نداشته باشه.
    """

    def __init__(self, update):
        self._update = update
        self.raw = update

        # chat_id — همیشه هست
        self.chat_id = getattr(update, 'chat_id', None)

        # message_id — داخل new_message.message_id یا update.message_id
        msg = getattr(update, 'new_message', None)
        if msg is not None:
            mid = getattr(msg, 'message_id', None)
            # در rubpy، message_id یه آبجکت MessageId هست؛ ما فقط عدد رو می‌خوایم
            self.message_id = getattr(mid, 'message_id', None) if mid else None
        else:
            self.message_id = getattr(update, 'message_id', None)

        # sender_id — کاربری که دکمه رو زده
        if msg is not None:
            self.user_id = getattr(msg, 'sender_id', None)
        else:
            self.user_id = getattr(update, 'sender_id', None)

        # data — از aux_data.button_id
        aux = getattr(msg, 'aux_data', None) if msg else None
        self.data = getattr(aux, 'button_id', '') if aux else ''

        # _answer_text برای answer کردن callback
        self._answer_text = None

    async def answer(self, text=None, alert=False):
        """پاسخ به callback — در روبیکا معمولاً با answerCallbackQuery انجام می‌شه.

        اگر در rubpy این متد وجود نداشت، fallback می‌کنیم به send_message
        (چون در روبیکا، answerCallbackQuery همیشه پشتیبانی نمی‌شه).
        """
        try:
            # بعضی نسخه‌های rubpy این متد رو دارن
            if hasattr(self._update, 'answer'):
                await self._update.answer(text or '')
                return
        except Exception:
            pass
        # در غیر این صورت بی‌صدا رد می‌شیم؛ در روبیکا، دکمه‌ها به صورت خودکار
        # حالت loading رو از دست می‌دن
        self._answer_text = text


def wrap_call(update):
    """تبدیل Update به CallContext."""
    return CallContext(update)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def init(bot, conn, owner_id, lang='fa'):
    """اتصال پنل به BotClient و دیتابیس. یک بار در startup صدا بزن."""
    global _bot, _conn, _owner_id, _lang
    assert lang in STRINGS, f"unsupported lang: {lang}"
    _bot = bot
    _conn = conn
    _owner_id = int(owner_id) if owner_id else None
    _lang = lang
    _migrate()


def _migrate():
    """ساخت جداول پنل ادمین."""
    with _lock:
        _conn.execute('''CREATE TABLE IF NOT EXISTS bot_admins (
            user_id  TEXT PRIMARY KEY,
            added_by TEXT,
            added_at INTEGER,
            username TEXT DEFAULT ''
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS bot_features (
            key     TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS admin_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            action   TEXT NOT NULL,
            target   TEXT DEFAULT '',
            detail   TEXT DEFAULT ''
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )''')
        _conn.commit()


# ---------------------------------------------------------------------------
# ابزارهای کمکی
# ---------------------------------------------------------------------------


def _t(string_id, **kw):
    text = STRINGS[_lang][string_id]
    return text.format(**kw) if kw else text


def _esc(text):
    return html.escape(str(text), quote=False) if text else ''


def _q(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _exec(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur


# ---------------------------------------------------------------------------
# دسترسی‌ها
# ---------------------------------------------------------------------------


def is_owner(user_id):
    return _owner_id is not None and str(user_id) == str(_owner_id)


def is_admin(user_id):
    if is_owner(user_id):
        return True
    rows = _q("SELECT 1 FROM bot_admins WHERE user_id=?", (str(user_id),))
    return bool(rows)


def admin_ids():
    ids = [str(_owner_id)] if _owner_id else []
    rows = _q("SELECT user_id FROM bot_admins ORDER BY added_at")
    for r in rows:
        if str(r['user_id']) != str(_owner_id):
            ids.append(str(r['user_id']))
    return ids


async def require_admin(call):
    """گارد ادمین. اگه کاربر ادمین نیست، alert می‌ده و False برمی‌گردونه."""
    if not is_admin(call.user_id):
        await call.answer(_t('not_admin'), alert=True)
        return False
    return True


async def require_owner(call):
    if not is_owner(call.user_id):
        await call.answer(_t('not_owner'), alert=True)
        return False
    return True


def open_to(user_id):
    """آیا این کاربر اجازه استفاده از بازی رو داره."""
    return players_enabled() or is_admin(user_id)


def players_enabled():
    return setting('players_enabled', '1') != '0'


def set_players_enabled(value):
    set_setting('players_enabled', '1' if value else '0')


# ---------------------------------------------------------------------------
# تنظیمات متنی
# ---------------------------------------------------------------------------


def setting(key, default=''):
    rows = _q("SELECT value FROM bot_settings WHERE key=?", (key,))
    return rows[0]['value'] if rows else default


def set_setting(key, value):
    if value is None or value == '':
        _exec("DELETE FROM bot_settings WHERE key=?", (key,))
    else:
        _exec("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
              (key, str(value)))


# ---------------------------------------------------------------------------
# لاگ
# ---------------------------------------------------------------------------


def log(actor_id, action, target='', detail=''):
    _exec("INSERT INTO admin_log (ts, actor_id, action, target, detail) "
          "VALUES (?, ?, ?, ?, ?)",
          (int(time.time()), str(actor_id), action, str(target), str(detail)))


def recent_log(limit=100):
    return _q("SELECT * FROM admin_log ORDER BY id DESC LIMIT ?", (int(limit),))


# ---------------------------------------------------------------------------
# انتظار پیام بعدی (next_step)
#
# در تلگرام از register_next_step_handler استفاده می‌شد. در روبیکا این API
# وجود نداره، پس یه صف ساده می‌سازیم: وقتی یه کاربر توی "حالت انتظار" باشه،
# اولین پیام متنی بعدی‌اش به callback پاس داده می‌شه.
#
# در main.py باید یه handler کلی برای پیام‌های متنی داشته باشیم که این صف
# رو چک کنه. این‌طوری:
#
#     @bot.on_update(filters.text)
#     async def on_text(c, update):
#         await admin_panel.handle_pending_text(update)
# ---------------------------------------------------------------------------


def next_step(user_id, callback):
    """ثبت callback برای پیام بعدی کاربر. callback باید async باشه."""
    _pending_steps[str(user_id)] = callback


def cancel_next_step(user_id):
    _pending_steps.pop(str(user_id), None)


async def handle_pending_text(update):
    """اگه کاربری توی حالت انتظار باشه، پیام رو به callback‌اش پاس بده.

    Returns True اگه پیام مصرف شد، False اگه نه.
    """
    msg = getattr(update, 'new_message', None)
    if msg is None:
        return False
    sender = getattr(msg, 'sender_id', None)
    if sender is None:
        return False
    cb = _pending_steps.pop(str(sender), None)
    if cb is None:
        return False
    try:
        await cb(update)
    except Exception:
        traceback.print_exc()
    return True


# ---------------------------------------------------------------------------
# ابزار پیام و دکمه
# ---------------------------------------------------------------------------


def btn(btn_id, text):
    """ساخت یه دکمه ساده."""
    return Button(id=str(btn_id), type=ButtonTypeEnum.SIMPLE, button_text=text)


def keypad(rows):
    """ساخت Keypad از لیست ردیف‌ها."""
    return Keypad(rows=[KeypadRow(buttons=r) for r in rows if r])


async def send(chat_id, text, rows=None):
    """ارسال پیام با Keypad اختیاری.

    روبیکا HTML پارس نمی‌کنه، پس تگ‌ها رو تبدیل به Markdown می‌کنیم.
    """
    text = _markdown(text)
    kwargs = {}
    if rows is not None:
        kwargs['inline_keypad'] = keypad(rows)
    return await _bot.send_message(chat_id, text, **kwargs)


async def edit(chat_id, message_id, text, rows=None):
    """ویرایش متن یه پیام."""
    text = _markdown(text)
    kwargs = {}
    if rows is not None:
        kwargs['inline_keypad'] = keypad(rows)
    try:
        return await _bot.edit_message_text(chat_id, message_id, text, **kwargs)
    except Exception:
        # اگه edit کار نکرد (مثلاً پیام خیلی قدیمیه)، پیام جدید بفرست
        return await send(chat_id, text, rows)


def _markdown(text):
    """تبدیل HTML ساده به Markdown روبیکا.

    روبیکا از `**bold**` و `` `code` `` پشتیبانی می‌کنه، ولی از `<blockquote>`
    و `<b>` نه. این تابع تگ‌های رایج رو تبدیل می‌کنه.
    """
    if not text:
        return text
    text = text.replace('<b>', '**').replace('</b>', '**')
    text = text.replace('<i>', '_').replace('</i>', '_')
    text = text.replace('<code>', '`').replace('</code>', '`')
    # blockquote رو تبدیل به خط جدید می‌کنیم چون روبیکا معادل نداره
    text = text.replace('<blockquote>', '\n').replace('</blockquote>', '\n')
    return text


# ---------------------------------------------------------------------------
# عنوان و نام کاربر
# ---------------------------------------------------------------------------


async def title(gid):
    """عنوان یه گروه، با کش."""
    key = str(gid)
    if key in _title_cache:
        return _title_cache[key]
    try:
        chat = await _bot.get_chat(gid)
        _title_cache[key] = getattr(chat, 'title', None) or key
    except Exception:
        _title_cache[key] = key
    return _title_cache[key]


async def user_name(uid):
    key = str(uid)
    if key in _name_cache:
        return _name_cache[key]
    try:
        chat = await _bot.get_chat(uid)
        first = getattr(chat, 'first_name', '') or ''
        last = getattr(chat, 'last_name', '') or ''
        name = (first + ' ' + last).strip() or key
    except Exception:
        name = key
    _name_cache[key] = name
    return name


def admin_check_sync(user_id):
    """نسخه sync برای جاهایی که await نمی‌شه."""
    return is_admin(user_id)
