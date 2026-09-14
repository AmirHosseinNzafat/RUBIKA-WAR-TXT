# -*- coding: utf-8 -*-
"""جادوگر پیشنهاد تجارت — انتخاب نوع، کالا، وسیله، مسیر.

از trade_core برای منطق استفاده می‌کنه و از trade_offer برای ارسال پیشنهاد.
نسخه روبیکا.
"""

import json
import time

from rubpy.bot.models import Button, Keypad, KeypadRow
from rubpy.bot.enums import ButtonTypeEnum

import trade_core as core
import asset_catalog
from admin_panel import next_step


# ---------------------------------------------------------------------------
# وضعیت جادوگر برای هر کاربر
# ---------------------------------------------------------------------------
_ctx = {}  # user_id -> {'chat_id', 'mode', 'goods', 'vehicles', 'dest', ...}


# ---------------------------------------------------------------------------
# ابزار دکمه و پیام
# ---------------------------------------------------------------------------


def _btn(btn_id, text):
    return Button(id=str(btn_id), type=ButtonTypeEnum.SIMPLE, button_text=text)


def _kp(rows):
    return Keypad(rows=[KeypadRow(buttons=r) for r in rows if r])


async def _send(chat_id, text, rows=None):
    text = core._to_markdown(text)
    kwargs = {}
    if rows:
        kwargs['inline_keypad'] = _kp(rows)
    return await _bot_send(chat_id, text, **kwargs)


async def _bot_send(chat_id, text, **kwargs):
    return await core._bot.send_message(chat_id, text, **kwargs)


async def _answer(call, text=None, alert=False):
    try:
        if hasattr(call, 'answer'):
            await call.answer(text or '')
    except Exception:
        pass


def _get_ctx(call):
    c = _ctx.get(str(call.user_id))
    if not c:
        return None
    return c


# ---------------------------------------------------------------------------
# ورودی منوی تجارت
# ---------------------------------------------------------------------------


async def menu(update, user_id):
    """دکمه 🚢 تجارت جهانی."""
    chat_id = update.chat_id
    lord = core.lord_row(chat_id)
    if lord is None:
        await _send(chat_id, core._t('not_registered'))
        return
    if not core.is_lord(chat_id, user_id):
        await _send(chat_id, core._t('not_lord'))
        return

    # شمارش تجارت‌های در جریان
    rows = core._q(
        "SELECT COUNT(*) AS n FROM trades WHERE sender_group_id=? "
        "AND status IN ('offered','active')", (str(chat_id),))
    n = rows[0]['n'] if rows else 0

    text = core._t('menu_title')
    if n:
        text += core._t('menu_active', n=n)

    # دکمه‌ها بر اساس mode باز
    buttons = []
    for mode in core.PHOTO_MODES:
        if core.mode_open(chat_id, mode):
            buttons.append([_btn(f'trd:m:{mode}',
                                 core._t('btn_' + mode))])

    if not buttons:
        await _send(chat_id, core._t('tm_all_closed'))
        return

    buttons.append([_btn('trd:x', core._t('btn_cancel'))])
    await _send(chat_id, text, buttons)
    await _answer(update)


# ---------------------------------------------------------------------------
# مرحله ۱: انتخاب نوع تجارت (دریایی / زمینی)
# ---------------------------------------------------------------------------


async def choose_mode(call, mode):
    chat_id = call.chat_id
    user_id = call.user_id

    if not core.is_lord(chat_id, user_id):
        await _answer(call, core._t('not_lord'), alert=True)
        return

    if not core.mode_open(chat_id, mode):
        await _answer(call)
        await _send(chat_id, core._t('tm_closed_here', mode=core.mode_name(mode)))
        return

    home_col = 'home_sea' if mode == 'sea' else 'home_land'
    lord = core.lord_row(chat_id)
    if lord is None or not lord[home_col]:
        await _answer(call)
        await _send(chat_id, core._t('need_home', mode=core.mode_name(mode)))
        return

    # مقصدهای ممکن
    dests = [d for d in core._q(
        f"SELECT DISTINCT group_id FROM users WHERE group_id != ? AND {home_col} != ''",
        (str(chat_id),))
        if core.mode_open(d['group_id'], mode)]

    if not dests:
        await _answer(call)
        await _send(chat_id, core._t('no_dest', mode=core.mode_name(mode)))
        return

    _ctx[str(user_id)] = {
        'chat_id': chat_id,
        'mode': mode,
        'goods': {},
        'vehicles': {},
    }

    rows = []
    for d in dests:
        t = await core.title(d['group_id'])
        rows.append([_btn(f"trd:d:{d['group_id']}", t)])
    rows.append([_btn('trd:x', core._t('btn_cancel'))])

    await _send(chat_id, core._t('choose_dest'), rows)
    await _answer(call)


# ---------------------------------------------------------------------------
# مرحله ۲: انتخاب مقصد
# ---------------------------------------------------------------------------


async def choose_dest(call, dest_gid):
    c = _get_ctx(call)
    if not c:
        await _answer(call, core._t('session_expired'), alert=True)
        return
    c['dest'] = dest_gid
    await _answer(call)
    await send_goods_menu(call.user_id)


# ---------------------------------------------------------------------------
# مرحله ۳: انتخاب کالاها
# ---------------------------------------------------------------------------


def _goods_lines(goods):
    if not goods:
        return core._t('goods_none')
    return '\n'.join(
        f"• {core.asset_catalog.label(col, core._lang)}: {amt}"
        for col, amt in goods.items()
    )


async def send_goods_menu(user_id):
    c = _ctx.get(str(user_id))
    if not c:
        return

    rows = []
    for col in asset_catalog.tradeable_resources():
        amt = c['goods'].get(col, 0)
        label = asset_catalog.label(col, core._lang)
        if amt:
            label += f" ({amt})"
        rows.append([_btn(f'trd:g:{col}', label)])

    rows.append([_btn('trd:gok', core._t('btn_goods_done')),
                 _btn('trd:x', core._t('btn_cancel'))])

    vol = sum(c['goods'].values())
    text = core._t('goods_title',
                   lines=_goods_lines(c['goods']),
                   vol=vol)
    await _send(c['chat_id'], text, rows)


def _balance(group_id, col):
    with core._lock:
        row = core._conn.execute(
            f"SELECT {col} FROM users WHERE group_id=?",
            (str(group_id),)).fetchone()
    return row[0] if row else 0


async def ask_amount(call, code):
    c = _get_ctx(call)
    if not c:
        await _answer(call, core._t('session_expired'), alert=True)
        return
    if code not in asset_catalog.tradeable_resources():
        await _answer(call, core._t('err_generic'))
        return
    user_id = call.user_id
    bal = _balance(c['chat_id'], code)
    await _answer(call)
    await _send(c['chat_id'],
                core._t('ask_amount',
                        res=asset_catalog.label(code, core._lang),
                        bal=bal))

    async def on_amount(update):
        cc = _ctx.get(str(user_id))
        if not cc:
            return
        try:
            val = int((update.new_message.text or '').strip())
        except (ValueError, AttributeError):
            await _send(cc['chat_id'], core._t('bad_number'))
            await send_goods_menu(user_id)
            return
        if val < 0:
            await _send(cc['chat_id'], core._t('bad_number'))
        elif val > _balance(cc['chat_id'], code):
            await _send(cc['chat_id'],
                        core._t('too_much',
                                bal=_balance(cc['chat_id'], code)))
        elif val == 0:
            cc['goods'].pop(code, None)
        else:
            cc['goods'][code] = val
        await send_goods_menu(user_id)

    next_step(user_id, on_amount)


async def goods_done(call):
    c = _get_ctx(call)
    if not c:
        return
    if not c['goods']:
        await _answer(call, core._t('need_goods'), alert=True)
        return
    await _answer(call)
    await send_vehicles_menu(call.user_id)


# ---------------------------------------------------------------------------
# مرحله ۴: انتخاب وسایل حمل
# ---------------------------------------------------------------------------


def _veh_name(col):
    label = asset_catalog.label(col, core._lang)
    return label if label != col else col


def _veh_capacity(col):
    key = core.CAP_KEY.get(col)
    return core.cfg(key) if key else 0


def _fleet_capacity(c):
    total = 0
    for _, col, cap_key in core.VEHICLES[c['mode']]:
        n = c['vehicles'].get(col, 0)
        total += n * core.cfg(cap_key)
    return total


def _veh_lines(vehicles):
    lines = []
    for col, n in vehicles.items():
        if not n:
            continue
        cap = _veh_capacity(col)
        lines.append(f"• {_veh_name(col)}: {n} × {cap} = {n * cap}")
    return '\n'.join(lines) if lines else '—'


def _fleet_table(group_id, mode):
    """یه خط برای هر وسیله که این mode می‌تونه استفاده کنه."""
    out = []
    for _code, col, _cap in core.VEHICLES[mode]:
        own = _balance(group_id, col)
        cap = _veh_capacity(col)
        out.append(f"{_veh_name(col)}: ظرفیت هرکدام {cap} — در اختیار شما {own}")
    return '\n'.join(out)


async def send_vehicles_menu(user_id):
    c = _ctx.get(str(user_id))
    if not c:
        return

    vol = sum(c['goods'].values())
    cap = _fleet_capacity(c)

    rows = []
    for code, col, _cap in core.VEHICLES[c['mode']]:
        n = c['vehicles'].get(col, 0)
        label = _veh_name(col)
        if n:
            label += f" ({n})"
        rows.append([_btn(f'trd:v:{code}', label)])

    rows.append([_btn('trd:vok', core._t('btn_veh_done')),
                 _btn('trd:x', core._t('btn_cancel'))])

    if c['mode'] == 'sea':
        text = core._t('veh_title_sea',
                       lines=_veh_lines(c['vehicles']),
                       vol=vol, cap=cap,
                       fleet=_fleet_table(c['chat_id'], 'sea'))
    else:
        text = core._t('veh_title_land',
                       lines=_veh_lines(c['vehicles']),
                       vol=vol, cap=cap,
                       fleet=_fleet_table(c['chat_id'], 'land'),
                       p=core.cfg('caravan_cost'))

    await _send(c['chat_id'], text, rows)


async def ask_vcount(call, code):
    c = _get_ctx(call)
    if not c:
        return
    user_id = call.user_id
    col = core.VEH_BY_CODE.get(code)
    if not col or col not in [v[1] for v in core.VEHICLES[c['mode']]]:
        await _answer(call, core._t('err_generic'))
        return

    bal = _balance(c['chat_id'], col)
    await _answer(call)

    if col == 'caravans':
        await _send(c['chat_id'],
                    core._t('ask_caravans',
                            bal=bal,
                            cap=_veh_capacity(col),
                            p=core.cfg('caravan_cost')))
    else:
        await _send(c['chat_id'],
                    core._t('ask_vcount',
                            v=_veh_name(col),
                            bal=bal,
                            cap=_veh_capacity(col)))

    async def on_count(update):
        cc = _ctx.get(str(user_id))
        if not cc:
            return
        try:
            val = int((update.new_message.text or '').strip())
        except (ValueError, AttributeError):
            await _send(cc['chat_id'], core._t('bad_number'))
            await send_vehicles_menu(user_id)
            return
        if val < 0:
            await _send(cc['chat_id'], core._t('bad_number'))
        elif val > _balance(cc['chat_id'], col):
            await _send(cc['chat_id'],
                        core._t('not_enough_units',
                                bal=_balance(cc['chat_id'], col)))
        elif val == 0:
            cc['vehicles'].pop(col, None)
        else:
            cc['vehicles'][col] = val
        await send_vehicles_menu(user_id)

    next_step(user_id, on_count)


# ---------------------------------------------------------------------------
# مرحله ۵: محاسبه مسیر
# ---------------------------------------------------------------------------


async def vehicles_done(call):
    c = _get_ctx(call)
    if not c:
        return
    vol = sum(c['goods'].values())
    cap = _fleet_capacity(c)
    if cap < vol:
        await _answer(call, core._t('not_enough_cap', vol=vol, cap=cap), alert=True)
        return

    mode = c['mode']
    home_col = 'home_sea' if mode == 'sea' else 'home_land'
    src_row = core.lord_row(c['chat_id'])
    dst_row = core.lord_row(c['dest'])

    if not src_row or not src_row[home_col] or not dst_row or not dst_row[home_col]:
        await _answer(call)
        await _send(c['chat_id'], core._t('need_home', mode=core.mode_name(mode)))
        return

    routes = core.find_routes(mode, src_row[home_col], dst_row[home_col],
                              sender_gid=c['chat_id'])
    if not routes:
        await _answer(call)
        await _send(c['chat_id'], core._t('no_route'))
        return

    c['routes'] = routes
    await _answer(call)

    # ساخت بلوک‌های مسیر
    blocks = []
    rows = []
    for i, r in enumerate(routes):
        tolls = ', '.join(
            f"{core.node_name(mode, nid)}: {amt}" for nid, amt in r['tolls']
        ) or core._t('tolls_none')

        blocks.append(core._t('route_block',
                              label=f"{i + 1}️⃣ {core._t(r['label'])}",
                              dur=_dur(r['minutes']),
                              path=core.path_names(mode, r['path']),
                              fee=r['base_fee'],
                              tolls=tolls,
                              total=r['money']))
        rows.append([_btn(f'trd:r:{i}',
                          core._t('btn_route', i=i + 1))])

    rows.append([_btn('trd:x', core._t('btn_cancel'))])

    text = core._t('routes_title',
                   src=core.node_name(mode, src_row[home_col]),
                   dst=core.node_name(mode, dst_row[home_col]))
    text += '\n\n' + '\n\n'.join(blocks)
    await _send(c['chat_id'], text, rows)


def _dur(minutes):
    h, m = divmod(int(minutes), 60)
    if h:
        return core._t('dur_hm', h=h, m=m)
    return core._t('dur_m', m=m)


# ---------------------------------------------------------------------------
# مرحله ۶: تأیید نهایی
# ---------------------------------------------------------------------------


def _trade_cost(c, route):
    caravan_cost = 0
    if c['mode'] == 'land':
        caravan_cost = c['vehicles'].get('caravans', 0) * core.cfg('caravan_cost')
    return route['money'] + caravan_cost


async def route_chosen(call, i):
    c = _get_ctx(call)
    if not c or 'routes' not in c or not (0 <= i < len(c['routes'])):
        await _answer(call, core._t('session_expired'), alert=True)
        return

    c['route_i'] = i
    r = c['routes'][i]
    mode = c['mode']

    veh = ', '.join(
        f"{n}× {_veh_name(col)}" for col, n in c['vehicles'].items() if n
    )

    rows = [[_btn('trd:go', core._t('btn_send')),
             _btn('trd:x', core._t('btn_cancel'))]]

    dest_title = await core.title(c['dest'])
    await _answer(call)
    text = core._t('confirm_title',
                   dest=core._esc(dest_title),
                   goods=_goods_lines(c['goods']),
                   veh=veh or '—',
                   path=core.path_names(mode, r['path']),
                   dur=_dur(r['minutes']),
                   cost=_trade_cost(c, r))
    await _send(c['chat_id'], text, rows)


# ---------------------------------------------------------------------------
# لغو
# ---------------------------------------------------------------------------


async def cancel_wizard(call):
    _ctx.pop(str(call.user_id), None)
    await _answer(call)
    await _send(call.chat_id, core._t('wizard_cancelled'))


# ---------------------------------------------------------------------------
# Dispatcher — از main.py صدا بزن
# ---------------------------------------------------------------------------


async def handle_callback(call):
    """callback های مربوط به پیشنهاد تجارت را پردازش کن."""
    try:
        parts = call.data.split(':')
        op = parts[1] if len(parts) > 1 else ''

        if op == 'menu':
            # این از منوی اصلی میاد، نه callback
            return
        elif op == 'm':
            await choose_mode(call, parts[2])
        elif op == 'd':
            await choose_dest(call, parts[2])
        elif op == 'g':
            await ask_amount(call, parts[2])
        elif op == 'gok':
            await goods_done(call)
        elif op == 'v':
            await ask_vcount(call, parts[2])
        elif op == 'vok':
            await vehicles_done(call)
        elif op == 'r':
            await route_chosen(call, int(parts[2]))
        elif op == 'x':
            await cancel_wizard(call)
        elif op == 'go':
            # این در trade_offer.py پیاده‌سازی می‌شه
            import trade_offer
            await trade_offer.confirm_send(call)
        else:
            await _answer(call, core._t('err_generic'))
    except Exception:
        import traceback
        traceback.print_exc()
        await _answer(call, core._t('err_generic'))
