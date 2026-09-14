# -*- coding: utf-8 -*-
"""صفحه‌های دارایی برای بازیکن — کاملاً از کاتالوگ دارایی رانده می‌شن.

دارایی‌ها، ارتقا، چرخه هفتگی و ویرایشگر دارایی ادمین قبلاً
~۳۰۰ خط if/elif بودن که سه بار تکرار شده بودن. الان یک پیاده‌سازی
و یک جدول هزینه هست.

نسخه روبیکا — با BotClient و Keypad و states.
"""

import html
import threading

from rubpy.bot.models import Button, Keypad, KeypadRow, Update
from rubpy.bot.enums import ButtonTypeEnum

import asset_catalog as catalog
import country_assets
from admin_panel import next_step, is_admin as _is_admin_fn


# ---------------------------------------------------------------------------
# وضعیت
# ---------------------------------------------------------------------------
_bot = None
_conn = None
_lang = 'fa'
_lock = threading.RLock()


# ---------------------------------------------------------------------------
# رشته‌ها
# ---------------------------------------------------------------------------
STRINGS = {
    'fa': {
        'err_generic': "خطایی رخ داد. دوباره تلاش کنید.",
        'not_registered': "این گروه هنوز لردی ندارد.",
        'not_admin': "شما ادمین نیستید.",
        'btn_back': "🔙 بازگشت",
        'assets_title': "{sections}\n\n📜 معاهدات:\n{treaties}",
        'sec_resource': "💰 دارایی:",
        'sec_unit': "⚔️ ارتش:",
        'sec_building': "🏭 ساختمان‌ها:",
        'nothing': "ندارد",
        'upgrade_pick': "انتخاب کنید که کدام بخش را می‌خواهید ارتقا دهید:",
        'upgrade_confirm': "برای ارتقا {label} به سطح {level} به این مقادیر نیاز دارید:\n{costs}{cap}",
        'upgrade_free': "ارتقا {label} به سطح {level} هزینه‌ای ندارد.{cap}",
        'upgrade_cap_note': "\n🏁 سقف سطح: {max}",
        'upgrade_maxed': "🏁 {label} به سقف سطح خود ({max}) رسیده.",
        'lvl_uncapped': "بدون سقف",
        'btn_upgrade_yes': "✅ بله، ارتقا بده",
        'upgraded': "✅ {label} ارتقا یافت (سطح {level}).",
        'insufficient': "💸 موجودی شما کافی نیست.",
        'weekly_title': "🏭 محصولات جمع‌آوری شده:\n{lines}",
        'weekly_empty': "🏭 هیچ ساختمانی برای تولید ندارید.",
        'editor_pick_kind': "کدام دسته را می‌خواهید تغییر دهید؟",
        'editor_pick_asset': "کدام مورد را می‌خواهید تغییر دهید؟",
        'editor_ask_value': "مقدار جدید برای {label} را وارد کنید (فعلی: {current}):",
        'editor_set': "✅ {label} به {value} تغییر یافت.",
        'editor_bad_number': "عدد نامعتبر.",
        'editor_invalid': "دارایی نامعتبر.",
        'kind_resource': "📦 منابع",
        'kind_unit': "⚔️ واحدها",
        'kind_building': "🏭 ساختمان‌ها",
    },
    'en': {
        'err_generic': "Something went wrong. Please try again.",
        'not_registered': "This group has no lord yet.",
        'not_admin': "You are not an admin.",
        'btn_back': "🔙 Back",
        'assets_title': "{sections}\n\n📜 Treaties:\n{treaties}",
        'sec_resource': "💰 Resources:",
        'sec_unit': "⚔️ Army:",
        'sec_building': "🏭 Buildings:",
        'nothing': "none",
        'upgrade_pick': "Choose what you want to upgrade:",
        'upgrade_confirm': "Upgrading {label} to level {level} costs:\n{costs}{cap}",
        'upgrade_free': "Upgrading {label} to level {level} is free.{cap}",
        'upgrade_cap_note': "\n🏁 Level ceiling: {max}",
        'upgrade_maxed': "🏁 {label} has reached its ceiling ({max}).",
        'lvl_uncapped': "no ceiling",
        'btn_upgrade_yes': "✅ Yes, upgrade it",
        'upgraded': "✅ {label} was upgraded (level {level}).",
        'insufficient': "💸 You do not have enough for that.",
        'weekly_title': "🏭 Collected output:\n{lines}",
        'weekly_empty': "🏭 You have no buildings producing anything.",
        'editor_pick_kind': "Which category do you want to change?",
        'editor_pick_asset': "Choose which entry you want to change:",
        'editor_ask_value': "Enter the new value for {label} (currently {current}):",
        'editor_set': "✅ {label} changed to {value}.",
        'editor_bad_number': "That is not a valid number.",
        'editor_invalid': "Invalid asset.",
        'kind_resource': "📦 Resources",
        'kind_unit': "⚔️ Units",
        'kind_building': "🏭 Buildings",
    },
    'tr': {
        'err_generic': "Bir hata oluştu. Lütfen tekrar deneyin.",
        'not_registered': "Bu grubun henüz bir lordu yok.",
        'not_admin': "Yönetici değilsiniz.",
        'btn_back': "🔙 Geri",
        'assets_title': "{sections}\n\n📜 Antlaşmalar:\n{treaties}",
        'sec_resource': "💰 Kaynaklar:",
        'sec_unit': "⚔️ Ordu:",
        'sec_building': "🏭 Binalar:",
        'nothing': "yok",
        'upgrade_pick': "Neyi yükseltmek istediğinizi seçin:",
        'upgrade_confirm': "{label} seviye {level} yükseltmesi şunlara mal olur:\n{costs}{cap}",
        'upgrade_free': "{label} seviye {level} yükseltmesi ücretsiz.{cap}",
        'upgrade_cap_note': "\n🏁 Seviye tavanı: {max}",
        'upgrade_maxed': "🏁 {label} tavanına ({max}) ulaştı.",
        'lvl_uncapped': "tavan yok",
        'btn_upgrade_yes': "✅ Evet, yükselt",
        'upgraded': "✅ {label} yükseltildi (seviye {level}).",
        'insufficient': "💸 Bunun için yeterli kaynağınız yok.",
        'weekly_title': "🏭 Toplanan üretim:\n{lines}",
        'weekly_empty': "🏭 Üretim yapan bir binanız yok.",
        'editor_pick_kind': "Hangi kategoriyi değiştirmek istiyorsunuz?",
        'editor_pick_asset': "Hangi girdiyi değiştirmek istediğinizi seçin:",
        'editor_ask_value': "{label} için yeni değeri girin (şu an {current}):",
        'editor_set': "✅ {label} {value} olarak değiştirildi.",
        'editor_bad_number': "Geçersiz sayı.",
        'editor_invalid': "Geçersiz varlık.",
        'kind_resource': "📦 Kaynaklar",
        'kind_unit': "⚔️ Birimler",
        'kind_building': "🏭 Binalar",
    },
}

PREFIX = 'ag:'


def init(bot, conn, lang='fa'):
    """اتصال صفحه‌های دارایی. یک بار در startup صدا بزن."""
    global _bot, _conn, _lang
    assert lang in STRINGS, f"unsupported lang: {lang}"
    _bot = bot
    _conn = conn
    _lang = lang
    country_assets.attach(conn)


# ---------------------------------------------------------------------------
# ابزارها
# ---------------------------------------------------------------------------


def _t(string_id, **kw):
    text = STRINGS[_lang][string_id]
    return text.format(**kw) if kw else text


def _esc(text):
    return html.escape(str(text), quote=False)


def _label(key):
    return catalog.label(key, _lang)


async def _answer(call, text=None, alert=False):
    try:
        if hasattr(call, 'answer'):
            await call.answer(text or '')
    except Exception:
        pass


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


def _row(group_id, columns):
    if not columns:
        return None
    with _lock:
        cur = _conn.execute(
            f"SELECT {', '.join(columns)} FROM users WHERE group_id=?",
            (group_id,))
        found = cur.fetchone()
    return dict(zip(columns, found)) if found else None


def _btn(btn_id, text):
    return Button(id=str(btn_id), type=ButtonTypeEnum.SIMPLE, button_text=text)


def _kp(rows):
    return Keypad(rows=[KeypadRow(buttons=r) for r in rows if r])


async def _send(chat_id, text, rows=None):
    kwargs = {}
    if rows:
        kwargs['inline_keypad'] = _kp(rows)
    return await _bot.send_message(chat_id, text, **kwargs)


# ---------------------------------------------------------------------------
# صفحه دارایی
# ---------------------------------------------------------------------------


def _lines(values):
    if not values:
        return _t('nothing')
    return '\n'.join(f"{_label(key)}: {value}" for key, value in values.items())


def sections(values, group_id=None):
    """یک بلوک "هدر + لیست" برای هر kind، به ترتیب کاتالوگ."""
    def keys(kind):
        return (country_assets.keys_for(group_id, kind) if group_id is not None
                else catalog.keys(kind))

    parts = []
    for kind in catalog.kind_order():
        lines = _lines({k: values[k] for k in keys(kind) if k in values})
        parts.append(f"{_t('sec_' + kind)}\n{lines}")
    return '\n\n'.join(parts)


async def show_assets(chat_id, group_id):
    columns = catalog.all_keys()
    values = _row(group_id, list(columns) + ['treaties'])
    if values is None:
        await _send(chat_id, _t('not_registered'))
        return
    text = _t('assets_title',
              sections=sections(values, group_id=group_id),
              treaties=_esc(values['treaties']) or _t('nothing'))
    await _send(chat_id, text)


# ---------------------------------------------------------------------------
# ارتقا
# ---------------------------------------------------------------------------


MAXED = 'maxed'
INSUFFICIENT = 'insufficient'
NO_COUNTRY = 'no_country'


def _cap_note(key):
    cap = catalog.max_level(key)
    return _t('upgrade_cap_note', max=cap) if cap else ''


def _level_suffix(key, level):
    cap = catalog.max_level(key)
    return f" ({level}/{cap})" if cap else f" ({level})"


async def upgrade_menu(chat_id, group_id=None):
    group_id = chat_id if group_id is None else group_id
    buildings = country_assets.keys_for(group_id, 'building')
    if not buildings:
        await _send(chat_id, _t('err_generic'))
        return
    levels = _row(group_id, list(buildings)) or {}
    rows = []
    for key in buildings:
        rows.append([_btn(f'ag:upc:{key}',
                          _label(key) + _level_suffix(key, levels.get(key, 0)))])
    await _send(chat_id, _t('upgrade_pick'), rows)


async def confirm_upgrade(call, key):
    row = catalog.entry(key)
    if row is None or row['kind'] != 'building' or row['hidden']:
        await _answer(call, _t('err_generic'), alert=True)
        return
    group_id = call.chat_id
    if country_assets.is_hidden(group_id, key):
        await _answer(call, _t('err_generic'), alert=True)
        return
    current = _row(group_id, [key])
    if current is None:
        await _answer(call, _t('not_registered'), alert=True)
        return
    level = current[key]
    if catalog.at_max_level(key, level):
        await _answer(call)
        await _send(group_id, _t('upgrade_maxed', label=_label(key),
                                 max=catalog.max_level(key)))
        return
    target = level + 1
    costs = catalog.upgrade_cost(key, target)
    if costs:
        costs_txt = '\n'.join(f"{_label(res)}: {amount}" for res, amount in costs.items())
        text = _t('upgrade_confirm', label=_label(key), level=target,
                  cap=_cap_note(key), costs=costs_txt)
    else:
        text = _t('upgrade_free', label=_label(key), level=target, cap=_cap_note(key))
    await _answer(call)
    await _send(group_id, text, [[_btn(f'ag:upy:{key}', _t('btn_upgrade_yes'))]])


async def do_upgrade(call, key):
    row = catalog.entry(key)
    if row is None or row['kind'] != 'building' or row['hidden']:
        await _answer(call, _t('err_generic'), alert=True)
        return
    group_id = call.chat_id
    if country_assets.is_hidden(group_id, key):
        await _answer(call, _t('err_generic'), alert=True)
        return
    result = _charge_and_upgrade(group_id, key)
    await _answer(call)
    if result == MAXED:
        await _send(group_id, _t('upgrade_maxed', label=_label(key),
                                 max=catalog.max_level(key)))
        return
    if not isinstance(result, int):
        await _send(group_id, _t('insufficient'))
        return
    await _send(group_id, _t('upgraded', label=_label(key), level=result))


def _charge_and_upgrade(group_id, key):
    with _lock:
        found = _conn.execute(f"SELECT {key} FROM users WHERE group_id=?",
                              (group_id,)).fetchone()
        if found is None:
            return NO_COUNTRY
        level = found[0] or 0
        if catalog.at_max_level(key, level):
            return MAXED
        target = level + 1
        costs = catalog.upgrade_cost(key, target)
        cols = list(costs)
        if cols:
            have = _conn.execute(
                f"SELECT {', '.join(cols)} FROM users WHERE group_id=?",
                (group_id,)).fetchone()
            if have is None:
                return NO_COUNTRY
            if any(have[i] < costs[c] for i, c in enumerate(cols)):
                return INSUFFICIENT
        sets = [f"{c} = {c} - ?" for c in cols] + [f"{key} = {key} + 1"]
        _conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE group_id=?",
                      [costs[c] for c in cols] + [group_id])
        _conn.commit()
    return target


# ---------------------------------------------------------------------------
# چرخه تولید هفتگی
# ---------------------------------------------------------------------------


async def weekly_update(chat_id, group_id):
    plan = country_assets.production_for(group_id)
    if not plan:
        await _send(chat_id, _t('weekly_empty'))
        return
    levels = _row(group_id, [b for b, _, _ in plan]) or {}
    totals = {}
    for building, produces, flat_output in plan:
        lvl = levels.get(building, 0) or 0
        if lvl <= 0:
            continue
        per_level = catalog.level_output(building, lvl) or flat_output
        totals[produces] = totals.get(produces, 0) + per_level * lvl
    if not totals:
        await _send(chat_id, _t('weekly_empty'))
        return
    # اعمال به دیتابیس
    with _lock:
        for col, amount in totals.items():
            if not amount:
                continue
            _conn.execute(f"UPDATE users SET {col} = {col} + ? WHERE group_id=?",
                          (amount, group_id))
        _conn.commit()
    lines = '\n'.join(f"{_label(k)}: +{v}" for k, v in totals.items())
    await _send(chat_id, _t('weekly_title', lines=lines))


# ---------------------------------------------------------------------------
# ویرایشگر دارایی (ادمین)
# ---------------------------------------------------------------------------


async def editor_menu(chat_id):
    rows = []
    for kind in catalog.kind_order():
        rows.append([_btn(f'ag:ed:{kind}:0', _t('kind_' + kind))])
    await _send(chat_id, _t('editor_pick_kind'), rows)


async def editor_list(chat_id, kind, page=0):
    items = catalog.entries(kind, include_hidden=True)
    per_page = 8
    pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    window = items[page * per_page:(page + 1) * per_page]
    rows = []
    for item in window:
        mark = '🚫 ' if item['hidden'] else ''
        rows.append([_btn(f"ag:edv:{item['key']}", f"{mark}{_label(item['key'])}")])
    # ناوبری
    nav = []
    if page > 0:
        nav.append(_btn(f'ag:ed:{kind}:{page - 1}', '➡️ قبلی'))
    if page < pages - 1:
        nav.append(_btn(f'ag:ed:{kind}:{page + 1}', 'بعدی ⬅️'))
    if nav:
        rows.append(nav)
    await _send(chat_id, _t('editor_pick_asset'), rows)


async def editor_ask(update, key, actor_id):
    row = catalog.entry(key)
    if row is None:
        await _send(update.chat_id, _t('editor_invalid'))
        return
    current = row['default_value']
    await _send(update.chat_id,
                _t('editor_ask_value', label=_label(key), current=current))

    async def on_value(update2):
        txt = (update2.new_message.text or '').strip()
        try:
            value = int(txt)
        except ValueError:
            await _send(update2.chat_id, _t('editor_bad_number'))
            return
        catalog.set_default(key, value)
        await _send(update2.chat_id, _t('editor_set', label=_label(key), value=value))

    next_step(actor_id, on_value)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def handle_callback(call):
    """`ag:` callback ها رو پردازش کن. call از نوع CallContext."""
    try:
        parts = call.data.split(':')
        op = parts[1] if len(parts) > 1 else ''

        if op == 'upc':
            await confirm_upgrade(call, parts[2])
        elif op == 'upy':
            await do_upgrade(call, parts[2])
        elif op == 'ed':
            if not _is_admin_fn(call.user_id):
                await _answer(call, _t('not_admin'), alert=True)
                return
            kind = parts[2]
            page = int(parts[3]) if len(parts) > 3 else 0
            await editor_list(call.chat_id, kind, page)
            await _answer(call)
        elif op == 'edv':
            if not _is_admin_fn(call.user_id):
                await _answer(call, _t('not_admin'), alert=True)
                return
            await editor_ask(call, parts[2], call.user_id)
            await _answer(call)
        else:
            await _answer(call, _t('err_generic'))
    except Exception:
        import traceback
        traceback.print_exc()
        await _answer(call, _t('err_generic'))


async def handle_assets_button(update):
    """دکمه 💰 دارایی از منوی اصلی."""
    await show_assets(update.chat_id, update.chat_id)


async def handle_upgrade_button(update):
    """دکمه 🛠️ ارتقا از منوی اصلی."""
    await upgrade_menu(update.chat_id)


async def handle_weekly_button(update):
    """دکمه 🔨 آپ هفتگی (ادمین)."""
    await weekly_update(update.chat_id, update.chat_id)


async def handle_editor_button(update):
    """دکمه 🛠️ تنظیم دارایی (ادمین)."""
    if not _is_admin_fn(update.new_message.sender_id
                        if update.new_message else 0):
        await _send(update.chat_id, _t('not_admin'))
        return
    await editor_menu(update.chat_id)
