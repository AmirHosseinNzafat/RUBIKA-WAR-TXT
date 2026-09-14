# -*- coding: utf-8 -*-
"""سیستم تجارت جهانی — نقطه ورود یکپارچه.

این فایل همه‌ی بخش‌های trade_* رو به هم وصل می‌کنه:
    - trade_core       (منطق خالص)
    - trade_wizard     (پیشنهاد تجارت)
    - trade_offer      (چرخه پیشنهاد + تیکر)
    - trade_map        (نقشه)
    - trade_map_admin  (ویرایش نقشه)

همچنین پنل ادمین تجارت رو پیاده‌سازی می‌کنه:
    - تعیین موقعیت دریایی/زمینی هر کشور
    - مالکیت تنگه‌ها
    - تنظیمات تجارت
    - عکس تجارت
    - باز/بسته کردن تجارت هر کشور

نسخه روبیکا.

استفاده در main.py:

    import trade_system
    trade_system.init(bot, conn, ADMIN_ID, CHANNEL_ID, lang='fa',
                      is_admin=admin_panel.is_admin,
                      is_owner=admin_panel.is_owner)

    # در callback dispatcher:
    if call.data.startswith('trd:'):
        await trade_system.handle_callback(call)

    # در startup:
    asyncio.create_task(trade_system.start_ticker())
"""

import json
import time

from rubpy.bot.models import Button, Keypad, KeypadRow
from rubpy.bot.enums import ButtonTypeEnum

import trade_core as core
import trade_wizard as wizard
import trade_offer as offer
import trade_map
import trade_map_admin

# از core و wizard و offer استفاده می‌کنیم
_bot = None
_conn = None
_lang = 'fa'


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def init(bot, conn, admin_id, channel_id, lang='fa',
         is_admin=None, is_owner=None):
    """اتصال کل سیستم تجارت. یک بار در startup صدا بزن."""
    global _bot, _conn, _lang
    _bot = bot
    _conn = conn
    _lang = lang

    # ۱. هسته
    core.init(bot, conn, admin_id, channel_id, lang=lang,
              is_admin=is_admin, is_owner=is_owner)

    # ۲. ادمین نقشه
    trade_map_admin.init(
        bot, lang,
        _require_admin_sync,  # async wrapper
        _require_owner_sync,
        _answer_sync,
        _next_step_sync,
        _log_sync,
        core.toll,
        core.set_toll,
        core.owner_name,
    )


# ---------------------------------------------------------------------------
# wrapper های sync برای trade_map_admin (چون اون ماژول API sync می‌خواست)
# ---------------------------------------------------------------------------


async def _require_admin_sync(call):
    if not core._is_admin(call.user_id):
        await _answer_sync(call, core._t('admin_only'), alert=True)
        return False
    return True


async def _require_owner_sync(call):
    if not core._is_owner(call.user_id):
        await _answer_sync(call, core._t('owner_only'), alert=True)
        return False
    return True


async def _answer_sync(call, text=None, alert=False):
    try:
        if hasattr(call, 'answer'):
            await call.answer(text or '')
    except Exception:
        pass


def _next_step_sync(*args, **kwargs):
    """از admin_panel استفاده می‌کنه."""
    from admin_panel import next_step
    # trade_map_admin از _next_step(message, user_id, fn) استفاده می‌کرد
    # در نسخه روبیکا فقط next_step(user_id, fn) داریم
    if len(args) == 3:
        _message, user_id, fn = args
        next_step(user_id, fn)
    elif len(args) == 2:
        user_id, fn = args
        next_step(user_id, fn)


def _log_sync(*args, **kwargs):
    from admin_panel import log as _admin_log
    _admin_log(*args, **kwargs)


# ---------------------------------------------------------------------------
# dispatcher اصلی
# ---------------------------------------------------------------------------


async def handle_callback(call):
    """همه‌ی callback های trd: رو پردازش کن.

    از main.py این‌طوری صدا بزن:

        if call.data.startswith('trd:'):
            await trade_system.handle_callback(call)
            return
    """
    try:
        parts = call.data.split(':')
        op = parts[1] if len(parts) > 1 else ''

        # admin ops
        if op in ADMIN_OPS:
            await _admin_handle(call, parts)
            return

        # wizard ops (پیشنهاد تجارت)
        if op in ('m', 'd', 'g', 'gok', 'v', 'vok', 'r', 'x'):
            await wizard.handle_callback(call)
            return

        # offer ops (پذیرش/رد/لغو/ارسال)
        if op in ('go', 'a', 'n', 'c'):
            await offer.handle_callback(call)
            return

        # menu (از دکمه اصلی)
        if op == 'menu':
            await wizard.menu(call, call.user_id)
            return

        # نقشه (m* ops از trade_map_admin)
        if op in trade_map_admin.OPS:
            await trade_map_admin.handle(call, parts)
            return

        await _answer_sync(call, core._t('err_generic'))
    except Exception:
        import traceback
        traceback.print_exc()
        await _answer_sync(call, core._t('err_generic'))


# ---------------------------------------------------------------------------
# پنل ادمین تجارت
# ---------------------------------------------------------------------------


ADMIN_OPS = frozenset({
    'adm', 'hm', 'hg', 'h', 'cfgh', 'cfg', 'ck', 'ow', 'on', 'og',
    'ph', 'phm', 'phs', 'phc', 'tm', 'tmg', 'tmt',
}) | frozenset(trade_map_admin.OPS)


async def _admin_handle(call, parts):
    op = parts[1]
    if op == 'adm':
        await _admin_menu(call)
    elif op == 'hm':
        await _home_pick_group(call, parts[2])
    elif op == 'hg':
        await _home_pick_node(call, parts[2], parts[3])
    elif op == 'h':
        await _home_set(call, parts[2], parts[3], parts[4])
    elif op == 'cfgh':
        await _config_home(call)
    elif op == 'cfg':
        await _config_menu(call, parts[2], int(parts[3]))
    elif op == 'ck':
        await _ask_cfg(call, parts[2])
    elif op == 'ow':
        await _owner_list(call, int(parts[2]))
    elif op == 'on':
        await _owner_pick_group(call, parts[2])
    elif op == 'og':
        await _owner_set(call, parts[2], parts[3])
    elif op == 'ph':
        await _photo_menu(call)
    elif op == 'phm':
        await _photo_mode_menu(call, parts[2])
    elif op == 'phs':
        await _photo_ask(call, parts[2])
    elif op == 'phc':
        await _photo_clear(call, parts[2])
    elif op == 'tm':
        await _mode_list(call, int(parts[2]))
    elif op == 'tmg':
        await _mode_screen(call, parts[2])
    elif op == 'tmt':
        await _mode_toggle(call, parts[2], parts[3])
    elif op in trade_map_admin.OPS:
        await trade_map_admin.handle(call, parts)
    else:
        await _answer_sync(call, core._t('err_generic'))


def _btn(btn_id, text):
    return Button(id=str(btn_id), type=ButtonTypeEnum.SIMPLE, button_text=text)


def _kp(rows):
    return Keypad(rows=[KeypadRow(buttons=r) for r in rows if r])


async def _send(chat_id, text, rows=None):
    text = core._to_markdown(text)
    kwargs = {}
    if rows:
        kwargs['inline_keypad'] = _kp(rows)
    return await _bot.send_message(chat_id, text, **kwargs)


# ---------------------------------------------------------------------------
# منوی ادمین
# ---------------------------------------------------------------------------


async def _admin_menu(call):
    if not await _require_admin_sync(call):
        return
    rows = [
        [_btn('trd:hm:s', core._t('btn_home_sea'))],
        [_btn('trd:hm:l', core._t('btn_home_land'))],
        [_btn('trd:ow:0', core._t('btn_owners'))],
        [_btn('trd:map', core._t('btn_map'))],
        [_btn('trd:cfgh', core._t('btn_cfg'))],
        [_btn('trd:tm:0', core._t('btn_trade_modes'))],
        [_btn('trd:ph', core._t('btn_photo'))],
    ]
    await _send(call.chat_id, core._t('adm_title'), rows)
    await _answer_sync(call)


# ---------------------------------------------------------------------------
# موقعیت کشورها
# ---------------------------------------------------------------------------


async def _home_pick_group(call, mcode):
    if not await _require_admin_sync(call):
        return
    mode = 'sea' if mcode == 's' else 'land'
    home_col = 'home_sea' if mode == 'sea' else 'home_land'
    groups = core._q(f"SELECT DISTINCT group_id, {home_col} AS home FROM users")
    rows = []
    for g in groups:
        t = await core.title(g['group_id'])
        label = t
        if g['home']:
            try:
                label += f" ({core.node_name(mode, g['home'])})"
            except Exception:
                pass
        rows.append([_btn(f"trd:hg:{mcode}:{g['group_id']}", label)])
    await _send(call.chat_id, core._t('adm_pick_group'), rows)
    await _answer_sync(call)


async def _home_pick_node(call, mcode, gid):
    if not await _require_admin_sync(call):
        return
    mode = 'sea' if mcode == 's' else 'land'
    nodes = core._nodes(mode)
    rows = []
    for nid, node in nodes.items():
        if not node['home']:
            continue
        name = node['names'].get(core._lang, nid)
        rows.append([_btn(f'trd:h:{mcode}:{gid}:{nid}', name)])
    g_title = await core.title(gid)
    await _send(call.chat_id,
                core._t('adm_pick_node', mode=core.mode_name(mode),
                        g=core._esc(g_title)),
                rows)
    await _answer_sync(call)


async def _home_set(call, mcode, gid, nid):
    if not await _require_admin_sync(call):
        return
    mode = 'sea' if mcode == 's' else 'land'
    if nid not in core._nodes(mode) or not core._node(mode, nid)['home']:
        await _answer_sync(call, core._t('err_generic'))
        return
    home_col = 'home_sea' if mode == 'sea' else 'home_land'
    core._exec(f"UPDATE users SET {home_col}=? WHERE group_id=?", (nid, str(gid)))
    _log_sync(call.user_id, 'group_home', core.title_sync(gid), f"{mode}={nid}")
    await _answer_sync(call)
    g_title = await core.title(gid)
    await _send(call.chat_id,
                core._t('home_set', mode=core.mode_name(mode),
                        g=core._esc(g_title),
                        node=core.node_name(mode, nid)))


# ---------------------------------------------------------------------------
# مالکیت تنگه‌ها
# ---------------------------------------------------------------------------


OWN_PAGE_SIZE = 8


async def _owner_list(call, page):
    if not await _require_admin_sync(call):
        return
    nids = trade_map.chokepoints()
    pages = max(1, (len(nids) + OWN_PAGE_SIZE - 1) // OWN_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    rows = []
    for nid in nids[page * OWN_PAGE_SIZE:(page + 1) * OWN_PAGE_SIZE]:
        owner = core.owner_of(nid)
        owner_label = core.title_sync(owner) if owner else core._t('own_unowned')
        name = core.node_name(core.mode_of_node(nid), nid)
        rows.append([_btn(f'trd:on:{nid}', f"{name} — {owner_label}")])
    nav = []
    if page > 0:
        nav.append(_btn(f'trd:ow:{page - 1}', core._t('btn_prev')))
    if page < pages - 1:
        nav.append(_btn(f'trd:ow:{page + 1}', core._t('btn_next')))
    if nav:
        rows.append(nav)
    await _send(call.chat_id, core._t('own_title', p=page + 1), rows)
    await _answer_sync(call)


async def _owner_pick_group(call, nid):
    if not await _require_admin_sync(call):
        return
    if nid not in trade_map.chokepoints():
        await _answer_sync(call, core._t('err_generic'))
        return
    rows = []
    for g in core._q("SELECT DISTINCT group_id FROM users"):
        t = await core.title(g['group_id'])
        rows.append([_btn(f"trd:og:{nid}:{g['group_id']}", t)])
    rows.append([_btn(f'trd:og:{nid}:0', core._t('btn_no_owner'))])
    node_name = core.node_name(core.mode_of_node(nid), nid)
    await _send(call.chat_id,
                core._t('own_pick', node=node_name), rows)
    await _answer_sync(call)


async def _owner_set(call, nid, gid):
    if not await _require_admin_sync(call):
        return
    if nid not in trade_map.chokepoints():
        await _answer_sync(call, core._t('err_generic'))
        return
    gid_val = gid if gid and gid != '0' else None
    core.set_owner(nid, gid_val)
    node_name = core.node_name(core.mode_of_node(nid), nid)
    _log_sync(call.user_id, 'chokepoint_owner', node_name,
              core.title_sync(gid_val) if gid_val else '-')
    await _answer_sync(call)
    if gid_val:
        g_title = await core.title(gid_val)
        await _send(call.chat_id,
                    core._t('own_set', node=node_name, g=core._esc(g_title)))
    else:
        await _send(call.chat_id, core._t('own_cleared', node=node_name))


# ---------------------------------------------------------------------------
# تنظیمات تجارت
# ---------------------------------------------------------------------------


CFG_PAGE_SIZE = 8

CONFIG_SECTIONS = (
    ('journey', ('sea_min_per_unit', 'land_min_per_unit',
                 'fee_per_unit', 'offer_expiry_min')),
    ('capacity', ('cap_small', 'cap_medium', 'cap_large',
                  'cap_caravan', 'caravan_cost')),
    ('toll', ()),
)


def _config_keys(section):
    if section == 'toll':
        return tuple('toll_' + nid for nid in trade_map.chokepoints())
    for key, keys in CONFIG_SECTIONS:
        if key == section:
            return keys
    return ()


async def _config_home(call):
    if not await _require_admin_sync(call):
        return
    rows = []
    for section, _keys in CONFIG_SECTIONS:
        n = len(_config_keys(section))
        rows.append([_btn(f'trd:cfg:{section}:0',
                          core._t('cfg_sec_' + section, n=n))])
    await _send(call.chat_id, core._t('cfg_home'), rows)
    await _answer_sync(call)


async def _config_menu(call, section, page):
    if not await _require_admin_sync(call):
        return
    keys = _config_keys(section)
    if not keys:
        await _answer_sync(call, core._t('cfg_sec_empty'), alert=True)
        return
    pages = max(1, (len(keys) + CFG_PAGE_SIZE - 1) // CFG_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    window = keys[page * CFG_PAGE_SIZE:(page + 1) * CFG_PAGE_SIZE]

    rows = []
    body_parts = []
    for k in window:
        label = core.config_label(k)
        val = core.cfg(k)
        rows.append([_btn(f'trd:ck:{k}', f"{label} — {val}")])
        help_txt = core.config_help(k)
        body_parts.append(f"**{label}** — {val}\n{help_txt}")

    nav = []
    if page > 0:
        nav.append(_btn(f'trd:cfg:{section}:{page - 1}', core._t('btn_prev')))
    if page < pages - 1:
        nav.append(_btn(f'trd:cfg:{section}:{page + 1}', core._t('btn_next')))
    if nav:
        rows.append(nav)
    rows.append([_btn('trd:cfgh', core._t('btn_cfg_back'))])

    text = core._t('cfg_title', section=core._t('cfg_sec_name_' + section),
                   p=page + 1, n=pages) + '\n\n' + '\n\n'.join(body_parts)
    await _send(call.chat_id, text, rows)
    await _answer_sync(call)


def _known_cfg(key):
    return key in core.CONFIG_DEFAULTS or key in (
        'toll_' + nid for nid in trade_map.chokepoints())


async def _ask_cfg(call, key):
    if not await _require_admin_sync(call):
        return
    if not _known_cfg(key):
        await _answer_sync(call, core._t('err_generic'))
        return
    chat_id = call.chat_id
    user_id = call.user_id
    await _answer_sync(call)
    await _send(chat_id,
                core._t('cfg_ask', name=core.config_label(key), key=key,
                        val=core.cfg(key), help=core.config_help(key)))

    from admin_panel import next_step

    async def on_value(update):
        try:
            val = int((update.new_message.text or '').strip())
            if val < 0:
                raise ValueError
        except (ValueError, AttributeError):
            await _send(chat_id, core._t('bad_number'))
            return
        core.set_cfg(key, val)
        _log_sync(user_id, 'trade_config', key, str(val))
        await _send(chat_id, core._t('cfg_set',
                                     name=core.config_label(key), val=val))

    next_step(user_id, on_value)


# ---------------------------------------------------------------------------
# عکس تجارت
# ---------------------------------------------------------------------------


def _photo_state(mode):
    if core.own_photo(mode if mode in core.PHOTO_MODES else None):
        return core._t('ph_set')
    return core._t('ph_shared') if core.photo(mode if mode in core.PHOTO_MODES else None) \
        else core._t('ph_unset')


async def _photo_menu(call):
    if not await _require_admin_sync(call):
        return
    rows = []
    for mode in core.PHOTO_MODES:
        state = _photo_state(mode)
        rows.append([_btn(f'trd:phm:{mode}',
                          core._t('btn_ph_mode_' + mode, state=state))])
    state_both = _photo_state('both')
    rows.append([_btn('trd:phm:both',
                      core._t('btn_ph_mode_both', state=state_both))])
    await _send(call.chat_id, core._t('ph_home'), rows)
    await _answer_sync(call)


async def _photo_mode_menu(call, mode):
    if not await _require_admin_sync(call):
        return
    if mode not in core.PHOTO_MODES and mode != 'both':
        await _answer_sync(call, core._t('err_generic'))
        return
    rows = [[_btn(f'trd:phs:{mode}', core._t('btn_ph_set'))]]
    if core.own_photo(mode if mode in core.PHOTO_MODES else None):
        rows.append([_btn(f'trd:phc:{mode}', core._t('btn_ph_clear'))])
    rows.append([_btn('trd:ph', core._t('btn_ph_back'))])
    await _send(call.chat_id,
                core._t('ph_title', mode=core._t('ph_mode_' + mode),
                        state=_photo_state(mode)),
                rows)
    await _answer_sync(call)


async def _photo_ask(call, mode):
    if not await _require_admin_sync(call):
        return
    if mode not in core.PHOTO_MODES and mode != 'both':
        await _answer_sync(call, core._t('err_generic'))
        return
    user_id = call.user_id
    await _answer_sync(call)
    await _send(call.chat_id,
                core._t('ph_ask', mode=core._t('ph_mode_' + mode)))

    from admin_panel import next_step

    async def on_photo(update):
        msg = update.new_message
        if not getattr(msg, 'photo', None):
            await _send(update.chat_id, core._t('ph_not_photo'))
            return
        file_id = msg.photo[-1].file_id if isinstance(msg.photo, list) else msg.photo.file_id
        core.set_photo(file_id,
                       mode if mode in core.PHOTO_MODES else None)
        _log_sync(user_id, 'trade_photo', mode, 'set')
        await _send(update.chat_id,
                    core._t('ph_saved', mode=core._t('ph_mode_' + mode)))

    next_step(user_id, on_photo)


async def _photo_clear(call, mode):
    if not await _require_admin_sync(call):
        return
    if mode not in core.PHOTO_MODES and mode != 'both':
        await _answer_sync(call, core._t('err_generic'))
        return
    core.set_photo('', mode if mode in core.PHOTO_MODES else None)
    _log_sync(call.user_id, 'trade_photo', mode, 'cleared')
    await _answer_sync(call, core._t('ph_cleared'))
    await _photo_mode_menu(call, mode)


# ---------------------------------------------------------------------------
# باز/بسته کردن تجارت هر کشور
# ---------------------------------------------------------------------------


async def _mode_list(call, page):
    if not await _require_admin_sync(call):
        return
    groups = [g['group_id'] for g in
              core._q("SELECT DISTINCT group_id FROM users ORDER BY group_id")]
    if not groups:
        await _answer_sync(call, core._t('adm_no_groups'), alert=True)
        return
    pages = max(1, (len(groups) + OWN_PAGE_SIZE - 1) // OWN_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    rows = []
    for gid in groups[page * OWN_PAGE_SIZE:(page + 1) * OWN_PAGE_SIZE]:
        state = core.open_modes(gid)
        marks = ' '.join(
            core._t('tm_on' if state[m] else 'tm_off',
                    mode=core._t('ph_mode_' + m))
            for m in core.PHOTO_MODES)
        t = await core.title(gid)
        rows.append([_btn(f'trd:tmg:{gid}', f"{t} — {marks}")])
    nav = []
    if page > 0:
        nav.append(_btn(f'trd:tm:{page - 1}', core._t('btn_prev')))
    if page < pages - 1:
        nav.append(_btn(f'trd:tm:{page + 1}', core._t('btn_next')))
    if nav:
        rows.append(nav)
    await _send(call.chat_id, core._t('tm_title', p=page + 1, n=pages), rows)
    await _answer_sync(call)


async def _mode_screen(call, gid):
    if not await _require_admin_sync(call):
        return
    state = core.open_modes(gid)
    rows = []
    for mode in core.PHOTO_MODES:
        key = 'btn_tm_close' if state[mode] else 'btn_tm_open'
        rows.append([_btn(f'trd:tmt:{gid}:{mode}',
                          core._t(key, mode=core._t('ph_mode_' + mode)))])
    rows.append([_btn('trd:tm:0', core._t('btn_tm_back'))])
    lines = '\n'.join(
        core._t('tm_row', mode=core._t('ph_mode_' + m),
                state=core._t('tm_state_on' if state[m] else 'tm_state_off'))
        for m in core.PHOTO_MODES)
    g_title = await core.title(gid)
    await _send(call.chat_id,
                core._t('tm_group', g=core._esc(g_title), lines=lines),
                rows)
    await _answer_sync(call)


async def _mode_toggle(call, gid, mode):
    if not await _require_admin_sync(call):
        return
    if mode not in core.PHOTO_MODES:
        await _answer_sync(call, core._t('err_generic'))
        return
    new_state = not core.mode_open(gid, mode)
    core.set_mode_open(gid, mode, new_state)
    _log_sync(call.user_id, 'trade_mode', core.title_sync(gid),
              f"{mode}={'open' if new_state else 'closed'}")
    await _answer_sync(call,
                       core._t('tm_toggled', mode=core._t('ph_mode_' + mode),
                               state=core._t('tm_state_on' if new_state
                                             else 'tm_state_off')))
    await _mode_screen(call, gid)


# ---------------------------------------------------------------------------
# تیکر
# ---------------------------------------------------------------------------


async def start_ticker():
    """در main.py صدا بزن: asyncio.create_task(trade_system.start_ticker())"""
    return await offer.start_ticker()


# ---------------------------------------------------------------------------
# صادرات برای استفاده در main.py
# ---------------------------------------------------------------------------


# این‌ها رو main.py مستقیم استفاده می‌کنه
from trade_core import (
    cfg, set_cfg, find_routes, is_lord, lord_row,
    active_goods_keys, active_trade_groups,
)
