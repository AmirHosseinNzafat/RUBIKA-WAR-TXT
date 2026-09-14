# -*- coding: utf-8 -*-
"""پنل‌های ادمین برای ویرایش دنیای تجارت.

از trade_system جدا شده تا آن فایل درباره تجارت بماند نه جغرافیا.
helper هایش را از طریق init() دریافت می‌کند نه با import کردن trade_system،
پس وابستگی یک‌طرفه می‌رود، و رشته‌های خودش را حمل می‌کند تا جدول STRINGS
تجارت یک صفحه دیگر بزرگ نشود.

فضای callback: همه‌چیز زیر 'trd:m…'، که توسط trade_system به اینجا
route می‌شود.

ویرایش در سطح ادمین است. حذف یک گره یا یال در سطح owner است:
تنها کاری که اینجا می‌تواند یک محموله را رها کند یا کشوری را از نقشه ببرد.

نسخه روبیکا — با rubpy.BotClient و Keypad.
"""

import html

from rubpy.bot.models import Button, Keypad, KeypadRow, Update
from rubpy.bot.enums import ButtonTypeEnum

import trade_map

_bot = None
_lang = 'fa'
_require_admin = None
_require_owner = None
_answer = None
_next_step = None
_log = None
_toll = None
_set_toll = None
_owner_label = None

PAGE_SIZE = 8

# callback هایی که این ماژول پاسخ می‌دهد. trade_system بر اساس عضویت
# dispatch می‌کند نه بر اساس prefix، چون 'm' و 'menu' op های خودش هستند.
OPS = frozenset({
    'map', 'mn', 'mnd', 'mrn', 'mkd', 'mks', 'mhm', 'mtl', 'mdn', 'mdnc',
    'me', 'med', 'meu', 'mem', 'mde', 'mdec',
    'man', 'mank', 'manh', 'mae', 'maep', 'mae1', 'mae1p', 'mae2',
})

# wizard های "افزودن گره" در حال انجام، کلید: user id
_wizards = {}


def init(bot, lang, require_admin, require_owner, answer, next_step, log,
         toll, set_toll, owner_label):
    global _bot, _lang, _require_admin, _require_owner, _answer, _next_step, _log
    global _toll, _set_toll, _owner_label
    _bot = bot
    _lang = lang if lang in STRINGS else 'fa'
    _require_admin = require_admin
    _require_owner = require_owner
    _answer = answer
    _next_step = next_step
    _log = log
    _toll = toll
    _set_toll = set_toll
    _owner_label = owner_label


def _t(string_id, **kw):
    text = STRINGS[_lang][string_id]
    return text.format(**kw) if kw else text


def _esc(text):
    return html.escape(str(text), quote=False)


def _err(exc):
    return STRINGS[_lang].get('map_err_' + str(exc), STRINGS[_lang]['map_err_generic'])


def _name(nid):
    return trade_map.name(nid, _lang)


async def _send(chat_id, text, keypad=None):
    """ارسال پیام با Keypad اختیاری. روبیکا از HTML پشتیبانی نمی‌کند، پس
    تگ‌های HTML را حذف می‌کنیم و متن را Markdown تمیز می‌فرستیم."""
    # روبیکا HTML را پارس نمی‌کند، پس <b> و <blockquote> را حذف می‌کنیم
    text = text.replace('<b>', '**').replace('</b>', '**')
    text = text.replace('<blockquote>', '\n').replace('</blockquote>', '\n')
    text = text.replace('<code>', '`').replace('</code>', '`')
    kwargs = {}
    if keypad is not None:
        kwargs['inline_keypad'] = keypad
    await _bot.send_message(chat_id, text, **kwargs)


def _kind_label(kind):
    return STRINGS[_lang].get('map_kind_' + kind, kind)


def _btn(btn_id, text):
    """ساخت یک Button ساده."""
    return Button(id=btn_id, type=ButtonTypeEnum.SIMPLE, button_text=text)


def _kp(rows):
    """ساخت Keypad از لیست ردیف‌ها. هر ردیف لیستی از Button است."""
    return Keypad(rows=[KeypadRow(buttons=row) for row in rows if row])


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


async def handle(call, parts):
    """parts لیست call.data.split(':') است؛ parts[1] همیشه با 'm' شروع می‌شود."""
    op = parts[1]
    if op == 'map':
        await _home(call)
    elif op == 'mn':
        await _node_list(call, parts[2], int(parts[3]))
    elif op == 'mnd':
        await _node_screen(call, parts[2])
    elif op == 'mrn':
        await _ask_rename(call, parts[2])
    elif op == 'mkd':
        await _pick_kind(call, parts[2])
    elif op == 'mks':
        await _set_kind(call, parts[2], parts[3])
    elif op == 'mhm':
        await _toggle_home(call, parts[2])
    elif op == 'mtl':
        await _ask_toll(call, parts[2])
    elif op == 'mdn':
        await _node_delete_confirm(call, parts[2])
    elif op == 'mdnc':
        await _node_delete_apply(call, parts[2])
    elif op == 'me':
        await _edge_list(call, parts[2], int(parts[3]))
    elif op == 'med':
        await _edge_screen(call, parts[2], parts[3], parts[4])
    elif op == 'meu':
        await _ask_units(call, parts[2], parts[3], parts[4])
    elif op == 'mem':
        await _ask_minutes(call, parts[2], parts[3], parts[4])
    elif op == 'mde':
        await _edge_delete_confirm(call, parts[2], parts[3], parts[4])
    elif op == 'mdec':
        await _edge_delete_apply(call, parts[2], parts[3], parts[4])
    elif op == 'man':
        await _add_node_start(call, parts[2])
    elif op == 'mank':
        await _add_node_kind(call, parts[2])
    elif op == 'manh':
        await _add_node_home(call, parts[2])
    elif op == 'mae':
        await _add_edge_first(call, parts[2])
    elif op == 'maep':
        await _add_edge_first(call, parts[2], int(parts[3]))
    elif op == 'mae1':
        await _add_edge_second(call, parts[2], parts[3])
    elif op == 'mae1p':
        await _add_edge_second(call, parts[2], parts[3], int(parts[4]))
    elif op == 'mae2':
        await _add_edge_units(call, parts[2], parts[3], parts[4])
    else:
        await _answer(call, _t('map_err_generic'))


# ---------------------------------------------------------------------------
# مرور
# ---------------------------------------------------------------------------


async def _home(call):
    if not await _require_admin(call):
        return
    rows = []
    for mode in trade_map.MODES:
        n = len(trade_map.nodes(mode))
        rows.append([_btn(f'trd:mn:{mode}:0', _t('map_btn_mode_' + mode, n=n))])
    await _send(call.message.chat_id, _t('map_title'), _kp(rows))
    await _answer(call)


def _page(items, page):
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    return items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], page, pages


def _nav(rows, page, pages, prefix):
    row = []
    if page > 0:
        row.append(_btn(f'{prefix}{page - 1}', _t('map_btn_prev')))
    if page < pages - 1:
        row.append(_btn(f'{prefix}{page + 1}', _t('map_btn_next')))
    if row:
        rows.append(row)
    return rows


async def _node_list(call, mode, page):
    if not await _require_admin(call):
        return
    if mode not in trade_map.MODES:
        await _answer(call, _t('map_err_bad_mode'), alert=True)
        return
    nids = list(trade_map.nodes(mode).keys())
    window, page, pages = _page(nids, page)
    rows = []
    for nid in window:
        rows.append([_btn(f'trd:mnd:{nid}', _name(nid))])
    _nav(rows, page, pages, f'trd:mn:{mode}:')
    rows.append([_btn(f'trd:man:{mode}', _t('map_btn_add_node'))])
    rows.append([_btn(f'trd:me:{mode}:0', _t('map_btn_edges'))])
    await _send(call.message.chat_id,
                _t('map_nodes_title', mode=_t('map_mode_' + mode), p=page + 1, n=pages),
                _kp(rows))
    await _answer(call)


async def _node_screen(call, nid):
    if not await _require_admin(call):
        return
    mode = trade_map.mode_of(nid)
    if mode is None:
        await _answer(call, _t('map_err_unknown_node'), alert=True)
        return
    row = trade_map.node(mode, nid)
    links = trade_map.edges_of(nid)
    neighbours = ' · '.join(_name(b if a == nid else a) for a, b in
                            ((e['a'], e['b']) for e in links)) or _t('map_no_edges')
    owner = _owner_label(nid) or _t('map_no_owner')

    rows = [
        [_btn(f'trd:mrn:{nid}', _t('map_btn_rename'))],
        [_btn(f'trd:mkd:{nid}', _t('map_btn_kind'))],
        [_btn(f'trd:mhm:{nid}', _t('map_btn_home'))],
        [_btn(f'trd:mtl:{nid}', _t('map_btn_toll'))],
    ]
    # فقط یک chokepoint می‌تواند مالک داشته باشد
    if row['kind'] in trade_map.CHOKEPOINT_KINDS:
        rows.append([_btn(f'trd:on:{nid}', _t('map_btn_owner'))])
    rows.append([_btn(f'trd:mdn:{nid}', _t('map_btn_del_node'))])
    rows.append([_btn(f'trd:mn:{mode}:0', _t('map_btn_back_nodes'))])

    text = _t('map_node', name=_esc(_name(nid)), id=_esc(nid),
              mode=_t('map_mode_' + mode),
              kind=_kind_label(row['kind']),
              home=_t('map_yes') if row['home'] else _t('map_no'),
              toll=_toll(nid), owner=_esc(owner), neighbours=_esc(neighbours))
    await _send(call.message.chat_id, text, _kp(rows))
    await _answer(call)


async def _edge_list(call, mode, page):
    if not await _require_admin(call):
        return
    if mode not in trade_map.MODES:
        await _answer(call, _t('map_err_bad_mode'), alert=True)
        return
    rows_data = trade_map.edges(mode)
    window, page, pages = _page(rows_data, page)
    rows = []
    for a, b, units, minutes in window:
        mark = ' ⏱' if minutes else ''
        label = f"{_name(a)} — {_name(b)} ({units}){mark}"
        rows.append([_btn(f'trd:med:{mode}:{a}:{b}', label)])
    _nav(rows, page, pages, f'trd:me:{mode}:')
    rows.append([_btn(f'trd:mae:{mode}', _t('map_btn_add_edge'))])
    rows.append([_btn(f'trd:mn:{mode}:0', _t('map_btn_back_nodes'))])
    await _send(call.message.chat_id,
                _t('map_edges_title', mode=_t('map_mode_' + mode), p=page + 1, n=pages),
                _kp(rows))
    await _answer(call)


async def _edge_screen(call, mode, a, b):
    if not await _require_admin(call):
        return
    found = trade_map.leg(mode, a, b)
    if found is None:
        await _answer(call, _t('map_err_no_edge'), alert=True)
        return
    units, minutes = found
    timing = (_t('map_minutes_exact', m=minutes) if minutes
              else _t('map_minutes_auto', units=units))

    rows = [
        [_btn(f'trd:meu:{mode}:{a}:{b}', _t('map_btn_units'))],
        [_btn(f'trd:mem:{mode}:{a}:{b}', _t('map_btn_minutes'))],
        [_btn(f'trd:mde:{mode}:{a}:{b}', _t('map_btn_del_edge'))],
        [_btn(f'trd:me:{mode}:0', _t('map_btn_back_edges'))],
    ]
    text = _t('map_edge', a=_esc(_name(a)), b=_esc(_name(b)), units=units, timing=timing)
    await _send(call.message.chat_id, text, _kp(rows))
    await _answer(call)


# ---------------------------------------------------------------------------
# ویرایش گره
# ---------------------------------------------------------------------------


async def _ask_rename(call, nid):
    if not await _require_admin(call):
        return
    if trade_map.mode_of(nid) is None:
        await _answer(call, _t('map_err_unknown_node'), alert=True)
        return
    await _answer(call)
    await _collect_names(call.message.chat_id, call.from_user.id, {},
                         lambda names: _apply_rename(call, nid, names),
                         current=trade_map.labels(nid))


async def _apply_rename(call, nid, names):
    trade_map.set_labels(nid, names)
    _log(call.from_user.id, 'map_node_edit', nid, 'renamed')
    await _send(call.message.chat_id, _t('map_renamed'))
    await _node_screen(call, nid)


async def _collect_names(chat_id, user_id, store, done, current=None):
    """درخواست نام نمایشی به هر زبان، سپس تحویل نقشه به done.

    پاسخ خالی نام فعلی را نگه می‌دارد، و اگر نداشته باشد دوباره می‌پرسد —
    تغییر نام هرگز نباید جایی را بدتر نام‌گذاری کند.
    """
    remaining = [lang for lang in trade_map.LANGS if lang not in store]
    if not remaining:
        await done(dict(store))
        return
    lang = remaining[0]
    kept = (current or {}).get(lang, '')
    text = (_t('map_ask_name_keep', lang=_t('map_lang_' + lang), current=_esc(kept))
            if kept else _t('map_ask_name', lang=_t('map_lang_' + lang)))
    await _send(chat_id, text)

    async def on_text(update: Update):
        # بررسی اینکه پیام از همان کاربر است
        if update.new_message and update.new_message.sender_id != user_id:
            return
        text_val = (update.new_message.text or '').strip() or kept
        if not text_val:
            await _send(update.chat_id, _t('map_name_required'))
            await _next_step(update, user_id, on_text)
            return
        store[lang] = text_val
        await _collect_names(update.chat_id, user_id, store, done, current)

    await _next_step(None, user_id, on_text)


async def _pick_kind(call, nid):
    if not await _require_admin(call):
        return
    mode = trade_map.mode_of(nid)
    if mode is None:
        await _answer(call, _t('map_err_unknown_node'), alert=True)
        return
    rows = [[_btn(f'trd:mks:{nid}:{kind}', _kind_label(kind))]
            for kind in trade_map.KINDS[mode]]
    await _send(call.message.chat_id, _t('map_pick_kind'), _kp(rows))
    await _answer(call)


async def _set_kind(call, nid, kind):
    if not await _require_admin(call):
        return
    try:
        trade_map.set_kind(nid, kind)
    except trade_map.MapError as exc:
        await _answer(call, _err(exc), alert=True)
        return
    _log(call.from_user.id, 'map_node_edit', nid, f'kind={kind}')
    await _answer(call, _t('map_saved'))
    await _node_screen(call, nid)


async def _toggle_home(call, nid):
    if not await _require_admin(call):
        return
    mode = trade_map.mode_of(nid)
    if mode is None:
        await _answer(call, _t('map_err_unknown_node'), alert=True)
        return
    new_state = not trade_map.node(mode, nid)['home']
    trade_map.set_home(nid, new_state)
    _log(call.from_user.id, 'map_node_edit', nid, f'home={int(new_state)}')
    await _answer(call, _t('map_home_on') if new_state else _t('map_home_off'))
    await _node_screen(call, nid)


async def _ask_toll(call, nid):
    if not await _require_admin(call):
        return
    if trade_map.mode_of(nid) is None:
        await _answer(call, _t('map_err_unknown_node'), alert=True)
        return
    await _answer(call)
    await _ask_number(call, _t('map_ask_toll', name=_name(nid), val=_toll(nid)),
                      lambda value: _apply_toll(call, nid, value))


async def _apply_toll(call, nid, value):
    _set_toll(nid, value)
    _log(call.from_user.id, 'map_node_edit', nid, f'toll={value}')
    await _send(call.message.chat_id,
                _t('map_toll_set', name=_esc(_name(nid)), val=value))
    await _node_screen(call, nid)


async def _node_delete_confirm(call, nid):
    if not await _require_owner(call):
        return
    mode = trade_map.mode_of(nid)
    if mode is None:
        await _answer(call, _t('map_err_unknown_node'), alert=True)
        return
    links = len(trade_map.edges_of(nid))
    rows = [
        [_btn(f'trd:mdnc:{nid}', _t('map_btn_del_yes'))],
        [_btn(f'trd:mnd:{nid}', _t('map_btn_back_node'))],
    ]
    await _send(call.message.chat_id,
                _t('map_del_node_confirm', name=_esc(_name(nid)), id=_esc(nid), n=links),
                _kp(rows))
    await _answer(call)


async def _node_delete_apply(call, nid):
    if not await _require_owner(call):
        return
    mode = trade_map.mode_of(nid)
    label = _name(nid)
    try:
        trade_map.remove_node(nid)
    except trade_map.MapError as exc:
        await _answer(call, _err(exc), alert=True)
        return
    _log(call.from_user.id, 'map_node_remove', nid, label)
    await _send(call.message.chat_id, _t('map_node_deleted', name=_esc(label)))
    await _node_list(call, mode or trade_map.MODES[0], 0)


# ---------------------------------------------------------------------------
# ویرایش یال
# ---------------------------------------------------------------------------


async def _ask_units(call, mode, a, b):
    if not await _require_admin(call):
        return
    if trade_map.leg(mode, a, b) is None:
        await _answer(call, _t('map_err_no_edge'), alert=True)
        return
    await _answer(call)
    await _ask_number(call, _t('map_ask_units'),
                      lambda value: _apply_edge(call, mode, a, b, units=value), minimum=1)


async def _ask_minutes(call, mode, a, b):
    if not await _require_admin(call):
        return
    if trade_map.leg(mode, a, b) is None:
        await _answer(call, _t('map_err_no_edge'), alert=True)
        return
    await _answer(call)
    await _ask_number(call, _t('map_ask_minutes'),
                      lambda value: _apply_edge(call, mode, a, b, minutes=value))


async def _apply_edge(call, mode, a, b, units=None, minutes=None):
    try:
        trade_map.set_edge(mode, a, b, units=units, minutes=minutes)
    except trade_map.MapError as exc:
        await _send(call.message.chat_id, _err(exc))
        return
    detail = f'units={units}' if units is not None else f'minutes={minutes}'
    _log(call.from_user.id, 'map_edge_edit', f'{a}-{b}', detail)
    await _send(call.message.chat_id, _t('map_saved'))
    await _edge_screen(call, mode, a, b)


async def _edge_delete_confirm(call, mode, a, b):
    if not await _require_owner(call):
        return
    if trade_map.leg(mode, a, b) is None:
        await _answer(call, _t('map_err_no_edge'), alert=True)
        return
    rows = [
        [_btn(f'trd:mdec:{mode}:{a}:{b}', _t('map_btn_del_yes'))],
        [_btn(f'trd:me:{mode}:0', _t('map_btn_back_edges'))],
    ]
    await _send(call.message.chat_id,
                _t('map_del_edge_confirm', a=_esc(_name(a)), b=_esc(_name(b))), _kp(rows))
    await _answer(call)


async def _edge_delete_apply(call, mode, a, b):
    if not await _require_owner(call):
        return
    try:
        trade_map.remove_edge(mode, a, b)
    except trade_map.MapError as exc:
        await _answer(call, _err(exc), alert=True)
        return
    _log(call.from_user.id, 'map_edge_remove', f'{a}-{b}', '')
    await _send(call.message.chat_id, _t('map_edge_deleted'))
    await _edge_list(call, mode, 0)


# ---------------------------------------------------------------------------
# افزودن گره (wizard چند مرحله‌ای)
# ---------------------------------------------------------------------------


async def _add_node_start(call, mode):
    if not await _require_admin(call):
        return
    if mode not in trade_map.MODES:
        await _answer(call, _t('map_err_bad_mode'), alert=True)
        return
    _wizards[call.from_user.id] = {'mode': mode, 'step': 'id'}
    await _answer(call)
    await _send(call.message.chat_id, _t('map_ask_node_id'))

    async def on_id(update: Update):
        if update.new_message and update.new_message.sender_id != call.from_user.id:
            return
        nid = (update.new_message.text or '').strip().lower()
        try:
            trade_map.check_new_id(nid)
        except trade_map.MapError as exc:
            await _send(update.chat_id, _err(exc))
            await _next_step(update, call.from_user.id, on_id)
            return
        _wizards[call.from_user.id]['nid'] = nid
        _wizards[call.from_user.id]['step'] = 'kind'
        await _add_node_kind_send(update.chat_id, mode, nid)

    await _next_step(None, call.from_user.id, on_id)


async def _add_node_kind_send(chat_id, mode, nid):
    rows = [[_btn(f'trd:mank:{nid}:{kind}', _kind_label(kind))]
            for kind in trade_map.KINDS[mode]]
    # ذخیره mode در wizard
    for uid, w in _wizards.items():
        if w.get('nid') == nid:
            w['mode'] = mode
            break
    await _send(chat_id, _t('map_ask_node_kind'), _kp(rows))


async def _add_node_kind(call, nid):
    parts = call.data.split(':')
    # فرمت: trd:mank:{nid}:{kind}
    if len(parts) < 4:
        await _answer(call, _t('map_err_generic'), alert=True)
        return
    kind = parts[3]
    wizard = _wizards.get(call.from_user.id)
    if not wizard or wizard.get('nid') != nid:
        await _answer(call, _t('map_err_generic'), alert=True)
        return
    wizard['kind'] = kind
    rows = [
        [_btn(f'trd:manh:{nid}:1', _t('map_yes'))],
        [_btn(f'trd:manh:{nid}:0', _t('map_no'))],
    ]
    await _send(call.message.chat_id, _t('map_ask_node_home'), _kp(rows))
    await _answer(call)


async def _add_node_home(call, nid):
    parts = call.data.split(':')
    if len(parts) < 4:
        await _answer(call, _t('map_err_generic'), alert=True)
        return
    home = parts[3] == '1'
    wizard = _wizards.pop(call.from_user.id, None)
    if not wizard or wizard.get('nid') != nid:
        await _answer(call, _t('map_err_generic'), alert=True)
        return
    mode = wizard['mode']
    kind = wizard['kind']
    try:
        trade_map.add_node(mode, nid, kind, home, {})
    except trade_map.MapError as exc:
        await _answer(call, _err(exc), alert=True)
        return
    _log(call.from_user.id, 'map_node_add', nid, f'{mode}/{kind}')
    await _answer(call, _t('map_node_added'))
    await _node_screen(call, nid)


# ---------------------------------------------------------------------------
# افزودن یال (wizard)
# ---------------------------------------------------------------------------


async def _add_edge_first(call, mode, page=0):
    if not await _require_admin(call):
        return
    if mode not in trade_map.MODES:
        await _answer(call, _t('map_err_bad_mode'), alert=True)
        return
    nids = list(trade_map.nodes(mode).keys())
    window, page, pages = _page(nids, page)
    rows = [[_btn(f'trd:mae1:{mode}:{nid}', _name(nid))] for nid in window]
    _nav(rows, page, pages, f'trd:maep:{mode}:')
    rows.append([_btn(f'trd:me:{mode}:0', _t('map_btn_back_edges'))])
    await _send(call.message.chat_id, _t('map_ask_edge_first'), _kp(rows))
    await _answer(call)


async def _add_edge_second(call, mode, a, page=0):
    if not await _require_admin(call):
        return
    nids = [n for n in trade_map.nodes(mode).keys() if n != a]
    window, page, pages = _page(nids, page)
    rows = [[_btn(f'trd:mae2:{mode}:{a}:{nid}', _name(nid))] for nid in window]
    _nav(rows, page, pages, f'trd:mae1:{mode}:{a}:')
    rows.append([_btn(f'trd:me:{mode}:0', _t('map_btn_back_edges'))])
    await _send(call.message.chat_id,
                _t('map_ask_edge_second', name=_esc(_name(a))), _kp(rows))
    await _answer(call)


async def _add_edge_units(call, mode, a, b):
    if not await _require_admin(call):
        return
    if a == b:
        await _answer(call, _t('map_err_self_edge'), alert=True)
        return
    await _answer(call)
    await _ask_number(call, _t('map_ask_edge_units', a=_name(a), b=_name(b)),
                      lambda value: _apply_new_edge(call, mode, a, b, value), minimum=1)


async def _apply_new_edge(call, mode, a, b, units):
    try:
        trade_map.add_edge(mode, a, b, units)
    except trade_map.MapError as exc:
        await _send(call.message.chat_id, _err(exc))
        return
    _log(call.from_user.id, 'map_edge_add', f'{a}-{b}', f'units={units}')
    await _send(call.message.chat_id, _t('map_edge_added'))
    await _edge_list(call, mode, 0)


# ---------------------------------------------------------------------------
# دریافت عدد از کاربر
# ---------------------------------------------------------------------------


async def _ask_number(call, prompt, callback, minimum=None):
    """از کاربر یک عدد بخواه و callback را با مقدار فراخوانی کن."""
    await _send(call.message.chat_id, prompt)

    async def on_number(update: Update):
        if update.new_message and update.new_message.sender_id != call.from_user.id:
            return
        text = (update.new_message.text or '').strip()
        try:
            value = int(text)
        except ValueError:
            await _send(update.chat_id, _t('map_bad_number'))
            await _next_step(update, call.from_user.id, on_number)
            return
        if minimum is not None and value < minimum:
            await _send(update.chat_id, _t('map_min_number', min=minimum))
            await _next_step(update, call.from_user.id, on_number)
            return
        await callback(value)

    await _next_step(None, call.from_user.id, on_number)


# ---------------------------------------------------------------------------
# رشته‌ها
# ---------------------------------------------------------------------------

STRINGS = {
    'fa': {
        'map_title': '🗺 ویرایش نقشه تجارت\n\nکدام نوع را می‌خواهید ببینید؟',
        'map_btn_mode_sea': '🚢 دریایی ({n} گره)',
        'map_btn_mode_land': '🐫 زمینی ({n} گره)',
        'map_mode_sea': 'دریایی',
        'map_mode_land': 'زمینی',
        'map_btn_prev': '➡️ قبلی',
        'map_btn_next': 'بعدی ⬅️',
        'map_nodes_title': '{mode} — گره‌ها (صفحه {p} از {n})',
        'map_edges_title': '{mode} — یال‌ها (صفحه {p} از {n})',
        'map_btn_add_node': '➕ افزودن گره',
        'map_btn_edges': '🔗 یال‌ها',
        'map_btn_add_edge': '➕ افزودن یال',
        'map_btn_back_nodes': '🔙 بازگشت به گره‌ها',
        'map_btn_back_edges': '🔙 بازگشت به یال‌ها',
        'map_btn_back_node': '🔙 بازگشت به گره',
        'map_btn_rename': '✏️ تغییر نام',
        'map_btn_kind': '🏷 تغییر نوع',
        'map_btn_home': '🏠 کلید home',
        'map_btn_toll': '🛣 تنظیم عوارض',
        'map_btn_owner': '👑 مالکیت',
        'map_btn_del_node': '🗑 حذف گره',
        'map_btn_del_yes': '✅ بله، حذف کن',
        'map_btn_units': '📏 طول (واحد)',
        'map_btn_minutes': '⏱ زمان (دقیقه)',
        'map_btn_del_edge': '🗑 حذف یال',
        'map_node': '📍 {name}\nشناسه: {id}\nmode: {mode}\nنوع: {kind}\nhome: {home}\nعوارض: {toll}\nمالک: {owner}\n\n🔗 یال‌ها: {neighbours}',
        'map_edge': '🔗 یال {a} — {b}\nطول: {units} واحد\nزمان: {timing}',
        'map_pick_kind': 'نوع جدید را انتخاب کنید:',
        'map_ask_name': 'نام جدید ({lang}) را وارد کنید:',
        'map_ask_name_keep': 'نام جدید ({lang}) را وارد کنید (فعلی: {current}). خالی = نگه‌داشتن فعلی.',
        'map_name_required': 'نام نمی‌تواند خالی باشد.',
        'map_renamed': '✅ نام به‌روزرسانی شد.',
        'map_saved': '✅ ذخیره شد.',
        'map_toll_set': '✅ عوارض {name} روی {val} تنظیم شد.',
        'map_ask_toll': 'عوارض جدید {name} را وارد کنید (فعلی: {val}):',
        'map_del_node_confirm': '⚠️ حذف گره {name} ({id})؟\n{links} یال قطع خواهند شد.',
        'map_del_edge_confirm': '⚠️ حذف یال {a} — {b}؟',
        'map_node_deleted': '🗑 گره {name} حذف شد.',
        'map_edge_deleted': '🗑 یال حذف شد.',
        'map_node_added': '✅ گره اضافه شد.',
        'map_edge_added': '✅ یال اضافه شد.',
        'map_home_on': '✅ home روشن شد.',
        'map_home_off': '✅ home خاموش شد.',
        'map_ask_node_id': 'شناسه گره جدید را وارد کنید (حروف کوچک، بدون فاصله):',
        'map_ask_node_kind': 'نوع گره را انتخاب کنید:',
        'map_ask_node_home': 'آیا این گره می‌تواند محل کشور باشد؟',
        'map_ask_edge_first': 'گره اول را انتخاب کنید:',
        'map_ask_edge_second': 'گره دوم را انتخاب کنید (به جز {name}):',
        'map_ask_edge_units': 'طول یال {a} — {b} (واحد):',
        'map_ask_units': 'طول جدید یال را وارد کنید:',
        'map_ask_minutes': 'زمان جدید یال به دقیقه (0 = خودکار):',
        'map_no_edges': 'بدون یال',
        'map_no_owner': 'بدون مالک',
        'map_yes': 'بله',
        'map_no': 'خیر',
        'map_minutes_exact': '{m} دقیقه',
        'map_minutes_auto': 'خودکار ({units} واحد)',
        'map_lang_fa': 'فارسی',
        'map_lang_en': 'انگلیسی',
        'map_lang_tr': 'ترکی',
        'map_kind_ocean': 'اقیانوس',
        'map_kind_sea': 'دریا',
        'map_kind_strait': 'تنگه',
        'map_kind_canal': 'کانال',
        'map_kind_cape': 'دماغه',
        'map_kind_region': 'منطقه',
        'map_kind_pass': 'گذرگاه',
        'map_err_generic': 'خطایی رخ داد.',
        'map_err_bad_mode': 'نوع نامعتبر.',
        'map_err_unknown_node': 'گره ناشناس.',
        'map_err_no_edge': 'یال وجود ندارد.',
        'map_err_bad_id': 'شناسه نامعتبر (حروف کوچک و _ مجاز).',
        'map_err_exists': 'این شناسه قبلاً وجود دارد.',
        'map_err_bad_kind': 'نوع نامعتبر.',
        'map_err_self_edge': 'یال به خود مجاز نیست.',
        'map_err_mode_mismatch': 'دو گره در mode یکسان نیستند.',
        'map_err_bad_units': 'طول باید مثبت باشد.',
        'map_err_edge_exists': 'این یال قبلاً وجود دارد.',
        'map_err_in_transit': 'محموله‌ای در حال عبور است.',
        'map_err_guard_unavailable': 'سیستم محافظ در دسترس نیست.',
        'map_err_reserved': 'این شناسه رزرو شده است.',
        'map_bad_number': 'عدد نامعتبر.',
        'map_min_number': 'عدد باید حداقل {min} باشد.',
    },
}
