# -*- coding: utf-8 -*-
"""بیانیه‌ها و لشکرکشی‌ها — کارهایی که ربات به صورت عمومی پست می‌کنه.

هر دو قبلاً سه بار تکرار شده بودن (یه بار توی هر main*.py) و هر دو
بلافاصله بعد از آخرین سوال شلیک می‌شدن: بدون پیش‌نمایش، بدون راه برگشت.
این ماژول هر دو رو یک بار مالک می‌شه و سه چیز اضافه می‌کنه:

    تأیید.       هیچی به کانال نمی‌رسه تا کسی نخونده باشه و دکمه رو بزنه.
                 لغو کردن هیچ هزینه‌ای نداره.

    بدون محدودیت طول.  پیام‌های طولانی به چند تا می‌شن.

    کشور.       بیانیه "از" جایی میاد، پس لرد فقط از داخل گروه خودش
                 می‌تونه یکی صادر کنه. ادمین می‌تونه از هرجا.

نسخه روبیکا — با BotClient و Keypad.
"""

import html
import threading

from rubpy.bot.models import Button, Keypad, KeypadRow, Update
from rubpy.bot.enums import ButtonTypeEnum


# ---------------------------------------------------------------------------
# وضعیت ماژول
# ---------------------------------------------------------------------------
_bot = None
_conn = None
_channel = None
_war_channel = None
_lang = 'fa'
_is_admin = None
_notify_admins = None
_lock = threading.RLock()

# پیش‌نویس‌های در انتظار تأیید، کلید: user_id
_drafts = {}

# محدودیت طول متن روبیکا (تقریباً مشابه تلگرامه، ولی محتاطانه 4000 می‌ذاریم)
TEXT_LIMIT = 4000
CAPTION_LIMIT = 1000

# انواع رسانه‌ای که ممکنه توی پیام باشن
MEDIA = ('photo', 'video', 'document', 'audio', 'voice', 'animation')


# ---------------------------------------------------------------------------
# رشته‌ها
# ---------------------------------------------------------------------------
STRINGS = {
    'fa': {
        'err_generic': "خطایی رخ داد. دوباره تلاش کنید.",
        'not_registered': "این گروه هنوز کشوری ندارد.",
        'no_groups': "هنوز هیچ کشوری ثبت نشده است.",
        'st_group_only': "🙌 بیانیه باید از داخل گروه کشور خودتان فرستاده شود، نه در چت خصوصی.",
        'st_not_lord': "شما لرد این گروه نیستید.",
        'st_pick_country': "🙌 بیانیه از طرف کدام کشور فرستاده شود؟",
        'st_ask': "**بیانیه خود را بفرستید**\nمتن، عکس، ویدیو یا صدا — به هر طولی.",
        'st_empty': "چیزی برای فرستادن پیدا نشد. دوباره تلاش کنید.",
        'st_preview': "🙌 **پیش‌نمایش بیانیه**\n\n{body}\n\n🌍 از طرف: {g}\n\nفرستاده شود؟",
        'st_preview_media': "\n📎 به همراه یک فایل ({kind})",
        'st_preview_long': "\n\nℹ️ این بیانیه بلند است و در {n} پیام فرستاده می‌شود.",
        'st_footer': "\n\n🌍 از {g}\n👤 فرمانده: {u}",
        'st_sent': "✅ بیانیه شما **فرستاده شد**.",
        'st_failed': "❌ فرستادن بیانیه ممکن نشد. با مدیریت تماس بگیرید.",
        'st_cancelled': "🚫 بیانیه لغو شد؛ چیزی فرستاده نشد.",
        'btn_send': "✅ بله، بفرست",
        'btn_cancel': "🚫 لغو",
        'at_pick_type': "نوع لشکرکشی را انتخاب کنید:",
        'at_land': "زمینی",
        'at_sea': "دریایی",
        'at_ask_details': "اطلاعات ارتش خود را وارد کنید:",
        'at_ask_origin': "مبدا لشکرکشی را وارد کنید:",
        'at_ask_dest': "مقصد لشکرکشی را وارد کنید:",
        'at_ask_time': "زمان رسیدن را وارد کنید:",
        'at_preview': "⚔️ **پیش‌نمایش لشکرکشی**\n\n{headline}\n\n📝 جزئیات: {details}\n\nفرستاده شود؟",
        'at_headline': "🔖 ارتش کشور {src} به مقصد {dst} حرکت کردند ({kind})\n\n"
                       "⚜️ فرمانده: {u}\n⌛️ زمان رسیدن: {when}",
        'at_report': "{headline}\n📝 جزئیات: {details}",
        'at_sent': "✅ اطلاعات لشکرکشی فرستاده شد.",
        'at_cancelled': "🚫 لشکرکشی لغو شد؛ چیزی فرستاده نشد.",
        'at_empty': "چیزی وارد نشد. دوباره تلاش کنید.",
    },
    'en': {
        'err_generic': "Something went wrong. Please try again.",
        'not_registered': "This group has no country yet.",
        'no_groups': "No country is registered yet.",
        'st_group_only': "🙌 A statement has to be sent from inside your own country's group.",
        'st_not_lord': "You are not a lord of this group.",
        'st_pick_country': "🙌 Which country is this statement from?",
        'st_ask': "**Send your statement**\nText, a photo, a video or audio — any length.",
        'st_empty': "There was nothing to send. Please try again.",
        'st_preview': "🙌 **Statement preview**\n\n{body}\n\n🌍 From: {g}\n\nSend it?",
        'st_preview_media': "\n📎 With one attachment ({kind})",
        'st_preview_long': "\n\nℹ️ This is long, and goes out as {n} messages.",
        'st_footer': "\n\n🌍 From {g}\n👤 Commander: {u}",
        'st_sent': "✅ Your statement has been **sent**.",
        'st_failed': "❌ The statement could not be sent. Please tell an admin.",
        'st_cancelled': "🚫 Statement cancelled; nothing was sent.",
        'btn_send': "✅ Yes, send it",
        'btn_cancel': "🚫 Cancel",
        'at_pick_type': "Choose the type of military campaign:",
        'at_land': "Land",
        'at_sea': "Sea",
        'at_ask_details': "Please enter your army information:",
        'at_ask_origin': "Enter the origin of the campaign:",
        'at_ask_dest': "Enter the destination of the campaign:",
        'at_ask_time': "Enter the arrival time:",
        'at_preview': "⚔️ **Campaign preview**\n\n{headline}\n\n📝 Details: {details}\n\nSend it?",
        'at_headline': "🔖 The army of {src} has set out for {dst} ({kind})\n\n"
                       "⚜️ Commander: {u}\n⌛️ Arrival time: {when}",
        'at_report': "{headline}\n📝 Details: {details}",
        'at_sent': "✅ The campaign has been announced.",
        'at_cancelled': "🚫 Campaign cancelled; nothing was sent.",
        'at_empty': "Nothing was entered. Please try again.",
    },
    'tr': {
        'err_generic': "Bir hata oluştu. Lütfen tekrar deneyin.",
        'not_registered': "Bu grubun henüz bir ülkesi yok.",
        'no_groups': "Henüz kayıtlı bir ülke yok.",
        'st_group_only': "🙌 Bildiri, kendi ülkenizin grup sohbetinden gönderilmelidir.",
        'st_not_lord': "Bu grubun lordu değilsiniz.",
        'st_pick_country': "🙌 Bu bildiri hangi ülkeden?",
        'st_ask': "**Bildirinizi gönderin**\nMetin, fotoğraf, video veya ses — istediğiniz uzunlukta.",
        'st_empty': "Gönderilecek bir şey bulunamadı. Lütfen tekrar deneyin.",
        'st_preview': "🙌 **Bildiri önizlemesi**\n\n{body}\n\n🌍 Gönderen: {g}\n\nGönderilsin mi?",
        'st_preview_media': "\n📎 Bir ek ile ({kind})",
        'st_preview_long': "\n\nℹ️ Bu bildiri uzun; arka arkaya {n} mesaj olarak gider.",
        'st_footer': "\n\n🌍 {g} grubundan\n👤 Komutan: {u}",
        'st_sent': "✅ Bildiriniz **gönderildi**.",
        'st_failed': "❌ Bildiri gönderilemedi. Lütfen bir yöneticiye haber verin.",
        'st_cancelled': "🚫 Bildiri iptal edildi; hiçbir şey gönderilmedi.",
        'btn_send': "✅ Evet, gönder",
        'btn_cancel': "🚫 İptal",
        'at_pick_type': "Sefer türünü seçin:",
        'at_land': "Kara",
        'at_sea': "Deniz",
        'at_ask_details': "Ordu bilgilerinizi girin:",
        'at_ask_origin': "Seferin çıkış yerini girin:",
        'at_ask_dest': "Seferin hedefini girin:",
        'at_ask_time': "Varış zamanını girin:",
        'at_preview': "⚔️ **Sefer önizlemesi**\n\n{headline}\n\n📝 Detaylar: {details}\n\nGönderilsin mi?",
        'at_headline': "🔖 {src} ordusu {dst} hedefine doğru harekete geçti ({kind})\n\n"
                       "⚜️ Komutan: {u}\n⌛️ Varış zamanı: {when}",
        'at_report': "{headline}\n📝 Detaylar: {details}",
        'at_sent': "✅ Sefer duyuruldu.",
        'at_cancelled': "🚫 Sefer iptal edildi; hiçbir şey gönderilmedi.",
        'at_empty': "Hiçbir şey girilmedi. Lütfen tekrar deneyin.",
    },
}


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def init(bot, conn, channel_id, war_channel_id=None, lang='fa',
         is_admin=None, notify_admins=None, war_photo=None, audit=None):
    """اتصال ماژول به BotClient. یک بار در startup صدا بزن."""
    global _bot, _conn, _channel, _war_channel, _lang, _is_admin, _notify_admins
    assert lang in STRINGS, f"unsupported lang: {lang}"
    _bot = bot
    _conn = conn
    _channel = channel_id
    _war_channel = war_channel_id or channel_id
    _lang = lang
    _is_admin = is_admin if is_admin is not None else (lambda uid: False)
    _notify_admins = notify_admins


# ---------------------------------------------------------------------------
# ابزارها
# ---------------------------------------------------------------------------


def _t(string_id, **kw):
    text = STRINGS[_lang][string_id]
    return text.format(**kw) if kw else text


def _esc(text):
    return html.escape(str(text), quote=False) if text else ''


async def _answer(call, text=None, alert=False):
    """پاسخ به callback."""
    try:
        if hasattr(call, 'answer'):
            await call.answer(text or '')
    except Exception:
        pass


def _log(actor_id, action, target='', detail=''):
    if _audit_fn is None:
        return
    try:
        _audit_fn(actor_id, action, target, detail)
    except Exception:
        pass


_audit_fn = None


def set_audit(fn):
    """اتصال به لاگر پنل ادمین."""
    global _audit_fn
    _audit_fn = fn


def _q(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _groups():
    return [r['group_id'] for r in
            _q("SELECT DISTINCT group_id FROM users ORDER BY group_id")]


def _is_lord(group_id, user_id):
    rows = _q("SELECT 1 FROM users WHERE group_id=? AND user_id=?",
              (group_id, user_id))
    return bool(rows)


async def _title(group_id):
    try:
        chat = await _bot.get_chat(group_id)
        return getattr(chat, 'title', None) or str(group_id)
    except Exception:
        return str(group_id)


async def _user_link(user_id):
    try:
        info = await _bot.get_chat(user_id)
        name = getattr(info, 'first_name', '') or str(user_id)
        return name
    except Exception:
        return str(user_id)


def _confirm_keypad(ok_data, cancel_data):
    """ساخت Keypad تأیید/لغو."""
    return Keypad(rows=[
        KeypadRow(buttons=[
            Button(id=ok_data, type=ButtonTypeEnum.SIMPLE,
                   button_text=_t('btn_send')),
            Button(id=cancel_data, type=ButtonTypeEnum.SIMPLE,
                   button_text=_t('btn_cancel')),
        ])
    ])


def chunks(text, limit=TEXT_LIMIT):
    """تقسیم متن به تکه‌های قابل قبول برای روبیکا.

    متن رو از خط جدید قطع می‌کنیم اگه ممکن باشه، وگرنه از وسط خط.
    """
    text = text or ''
    if len(text) <= limit:
        return [text] if text else []
    out, current = [], ''
    for line in text.split('\n'):
        while len(line) > limit:
            if current:
                out.append(current)
                current = ''
            out.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + '\n' + line
        if len(candidate) > limit:
            out.append(current)
            current = line
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def _media_of(message):
    """(kind, file_id) هر چیزی که پیام حمل می‌کنه، یا (None, None)."""
    for kind in MEDIA:
        found = getattr(message, kind, None)
        if found:
            if isinstance(found, (list, tuple)):
                item = found[-1]
            else:
                item = found
            file_id = getattr(item, 'file_id', None)
            return kind, file_id
    return None, None


# ---------------------------------------------------------------------------
# بیانیه‌ها
# ---------------------------------------------------------------------------


async def start_statement(update, user_id):
    """دکمه 🙌. از کجا مجازه بستگی به کسی داره که زده."""
    msg = update.new_message
    chat_id = update.chat_id
    in_group = True  # در rubpy گروه و کاربر یکی نیست؛ فرض می‌کنیم گروه

    if in_group:
        if not _q("SELECT 1 FROM users WHERE group_id=?", (chat_id,)):
            await _bot.send_message(chat_id, _t('not_registered'))
            return
        if not (_is_lord(chat_id, user_id) or _is_admin(user_id)):
            await _bot.send_message(chat_id, _t('st_not_lord'))
            return
        await _ask_statement(chat_id, user_id, chat_id)
        return

    # چت خصوصی: فقط ادمین
    if not _is_admin(user_id):
        await _bot.send_message(chat_id, _t('st_group_only'))
        return
    groups = _groups()
    if not groups:
        await _bot.send_message(chat_id, _t('no_groups'))
        return

    rows = []
    for gid in groups:
        t = await _title(gid)
        rows.append([Button(id=f'bc:sg:{gid}', type=ButtonTypeEnum.SIMPLE,
                            button_text=t)])
    await _bot.send_message(chat_id, _t('st_pick_country'),
                            inline_keypad=Keypad(rows=[KeypadRow(buttons=r) for r in rows]))


async def _pick_country(call, gid):
    if not _is_admin(call.user_id):
        await _answer(call, _t('st_group_only'), alert=True)
        return
    await _answer(call)
    await _ask_statement(call.chat_id, call.user_id, gid)


async def _ask_statement(chat_id, user_id, group_id):
    _drafts[str(user_id)] = {'kind': 'statement', 'chat_id': chat_id,
                              'group_id': group_id}
    await _bot.send_message(chat_id, _t('st_ask'))
    # در main.py باید handle_pending_text رو وصل کنی
    from admin_panel import next_step
    next_step(user_id, lambda msg: _collect_statement(msg, user_id))


async def _collect_statement(update, user_id):
    draft = _drafts.get(str(user_id))
    if not draft or draft.get('kind') != 'statement':
        return

    msg = update.new_message
    kind, file_id = _media_of(msg)
    text = (msg.text or '').strip() if msg else ''

    if not text and not file_id:
        await _bot.send_message(draft['chat_id'], _t('st_empty'))
        return

    # فایل رو (اگه هست) به صورت file_id نگه می‌داریم
    draft['media_kind'] = kind
    draft['media_id'] = file_id
    draft['body'] = text
    draft['preview_chat'] = draft['chat_id']

    # پیش‌نمایش
    preview = _t('st_preview', body=text or '(بدون متن)', g=draft['group_id'])
    if kind:
        preview += _t('st_preview_media', kind=kind)
    parts = chunks(text)
    if len(parts) > 1:
        preview += _t('st_preview_long', n=len(parts))

    await _bot.send_message(draft['chat_id'], preview,
                            inline_keypad=_confirm_keypad(f'bc:ss:{user_id}',
                                                          f'bc:sc:{user_id}'))


async def _send_statement(call, user_id):
    draft = _drafts.pop(str(user_id), None)
    if not draft:
        await _answer(call, _t('err_generic'))
        return

    # footer
    try:
        commander = await _user_link(user_id)
    except Exception:
        commander = str(user_id)
    g = await _title(draft['group_id'])
    footer = _t('st_footer', g=g, u=commander)

    body = (draft.get('body') or '') + footer
    parts = chunks(body)
    if not parts:
        parts = [footer.strip()]

    ok = True
    try:
        for part in parts:
            await _bot.send_message(_channel, part)
    except Exception:
        ok = False

    if ok:
        await _answer(call)
        await _bot.send_message(draft['chat_id'], _t('st_sent'))
        _log(user_id, 'statement', g, body[:200])
    else:
        await _bot.send_message(draft['chat_id'], _t('st_failed'))


async def _cancel_statement(call, user_id):
    _drafts.pop(str(user_id), None)
    await _answer(call)
    await _bot.send_message(call.chat_id, _t('st_cancelled'))


# ---------------------------------------------------------------------------
# لشکرکشی
# ---------------------------------------------------------------------------


async def start_campaign(update, user_id):
    """دکمه ⚔️. از کاربر نوع رو می‌پرسه."""
    chat_id = update.chat_id
    if not _is_lord(chat_id, user_id) and not _is_admin(user_id):
        await _bot.send_message(chat_id, _t('st_not_lord'))
        return

    rows = [
        [Button(id='bc:at:l', type=ButtonTypeEnum.SIMPLE,
                button_text=_t('at_land'))],
        [Button(id='bc:at:s', type=ButtonTypeEnum.SIMPLE,
                button_text=_t('at_sea'))],
    ]
    await _bot.send_message(chat_id, _t('at_pick_type'),
                            inline_keypad=Keypad(rows=[KeypadRow(buttons=r) for r in rows]))


async def _campaign_pick_type(call, mcode):
    mode = 'land' if mcode == 'l' else 'sea'
    draft = {
        'kind': 'campaign',
        'chat_id': call.chat_id,
        'user_id': call.user_id,
        'mode': mode,
        'step': 'details',
    }
    _drafts[str(call.user_id)] = draft
    await _answer(call)
    await _bot.send_message(call.chat_id, _t('at_ask_details'))

    from admin_panel import next_step
    next_step(call.user_id, lambda msg: _campaign_collect(msg, call.user_id, 'details'))


async def _campaign_collect(update, user_id, field):
    draft = _drafts.get(str(user_id))
    if not draft or draft.get('kind') != 'campaign':
        return
    text = (update.new_message.text or '').strip()
    if not text:
        await _bot.send_message(draft['chat_id'], _t('at_empty'))
        return

    draft[field] = text
    from admin_panel import next_step

    if field == 'details':
        draft['step'] = 'origin'
        await _bot.send_message(draft['chat_id'], _t('at_ask_origin'))
        next_step(user_id, lambda msg: _campaign_collect(msg, user_id, 'origin'))
    elif field == 'origin':
        draft['step'] = 'dest'
        await _bot.send_message(draft['chat_id'], _t('at_ask_dest'))
        next_step(user_id, lambda msg: _campaign_collect(msg, user_id, 'dest'))
    elif field == 'dest':
        draft['step'] = 'time'
        await _bot.send_message(draft['chat_id'], _t('at_ask_time'))
        next_step(user_id, lambda msg: _campaign_collect(msg, user_id, 'time'))
    elif field == 'time':
        draft['time'] = text
        await _campaign_preview(draft)


async def _campaign_preview(draft):
    src = await _title(draft['chat_id'])
    commander = await _user_link(draft['user_id'])
    kind = _t('at_land') if draft['mode'] == 'land' else _t('at_sea')
    headline = _t('at_headline', src=src, dst=draft['dest'],
                  kind=kind, u=commander, when=draft['time'])
    details = draft['details']

    _drafts[str(draft['user_id'])]['preview'] = headline
    draft['preview'] = headline

    text = _t('at_preview', headline=headline, details=details)
    await _bot.send_message(
        draft['chat_id'], text,
        inline_keypad=_confirm_keypad(f"bc:as:{draft['user_id']}",
                                      f"bc:ac:{draft['user_id']}"))


async def _send_campaign(call, user_id):
    draft = _drafts.pop(str(user_id), None)
    if not draft or draft.get('kind') != 'campaign':
        await _answer(call, _t('err_generic'))
        return

    headline = draft.get('preview') or ''
    body = _t('at_report', headline=headline, details=draft.get('details', ''))

    ok = True
    try:
        for part in chunks(body):
            await _bot.send_message(_war_channel, part)
    except Exception:
        ok = False

    if ok:
        await _answer(call)
        await _bot.send_message(draft['chat_id'], _t('at_sent'))
        _log(user_id, 'campaign', draft.get('mode', ''), headline[:200])
    else:
        await _bot.send_message(draft['chat_id'], _t('st_failed'))


async def _cancel_campaign(call, user_id):
    _drafts.pop(str(user_id), None)
    await _answer(call)
    await _bot.send_message(call.chat_id, _t('at_cancelled'))


# ---------------------------------------------------------------------------
# Dispatcher — در main.py این رو صدا بزن
# ---------------------------------------------------------------------------


async def handle_callback(call):
    """`bc:` callback ها رو پردازش کن. call از نوع CallContext."""
    try:
        parts = call.data.split(':')
        op = parts[1] if len(parts) > 1 else ''

        if op == 'sg':
            await _pick_country(call, parts[2])
        elif op == 'ss':
            await _send_statement(call, parts[2])
        elif op == 'sc':
            await _cancel_statement(call, parts[2])
        elif op == 'at':
            await _campaign_pick_type(call, parts[2])
        elif op == 'as':
            await _send_campaign(call, parts[2])
        elif op == 'ac':
            await _cancel_campaign(call, parts[2])
        else:
            await _answer(call, _t('err_generic'))
    except Exception:
        import traceback
        traceback.print_exc()
        await _answer(call, _t('err_generic'))
