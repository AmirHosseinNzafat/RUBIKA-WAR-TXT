# -*- coding: utf-8 -*-
"""پنل ویرایش نقشه تجارت — نسخه روبیکا.

این فایل UI کامل ویرایش نقشه رو پیاده می‌کنه:
    - مرور گره‌ها و یال‌ها
    - تغییر نام گره (fa/en/tr)
    - تغییر نوع (ocean/sea/strait/canal/cape/region/pass)
    - تغییر home
    - تنظیم عوارض
    - مالکیت chokepoint
    - افزودن/حذف گره و یال

نسخه روبیکا با Keypad و async.
"""

import html

from rubpy.bot.models import Button, Keypad, KeypadRow
from rubpy.bot.enums import ButtonTypeEnum

import trade_map


# ---------------------------------------------------------------------------
# وضعیت
# ---------------------------------------------------------------------------
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

# wizard های در حال انجام (افزودن گره)، کلید: user_id
_wizards = {}

OPS = frozenset({
    'map', 'mn', 'mnd', 'mrn', 'mkd', 'mks', 'mhm', 'mtl', 'mdn', 'mdnc',
    'me', 'med', 'meu', 'mem', 'mde', 'mdec',
    'man', 'mank', 'manh', 'mae', 'maep', 'mae1', 'mae1p', 'mae2',
})


def init(bot, lang, require_admin, require_owner, answer, next_step, log,
         toll, set_toll, owner_label):
    global _bot, _lang, _require_admin, _require_owner, _answer, _next_step, _log
    global _toll, _set_toll, _owner_label
    _bot = bot
    _lang = lang if lang in _STRINGS else 'fa'
    _require_admin = require_admin
    _require_owner = require_owner
    _answer = answer
    _next_step = next_step
    _log = log
    _toll = toll
    _set_toll = set_toll
    _owner_label = owner_label


def _t(string_id, **kw):
    from trade_strings import STRINGS
    text = STRINGS[_lang].get(string_id, STRINGS['fa'].get(string_id, string_id))
    return text.format(**kw) if kw else text


def _esc(text):
    return html.escape(str(text), quote=False)


def _err(exc):
    from trade_strings import STRINGS
    key = 'map_err_' + str(exc)
    return STRINGS[_lang].get(key, STRINGS[_lang].get('map_err_generic', 'Error'))


def _name(nid):
    return trade_map.name(nid, _lang)


def _btn(btn_id, text):
    return Button(id=str(btn_id), type=ButtonTypeEnum.SIMPLE, button_text=text)


def _kp(rows):
    return Keypad(rows=[KeypadRow(buttons=r) for r in rows if r])


async def _send(chat_id, text, rows=None):
    kwargs = {}
    if rows:
        kwargs['inline_keypad'] = _kp(rows)
    return await _bot.send_message(chat_id, text, **kwargs)


def _kind_label(kind):
    return _t('map_kind_' + kind)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


async def handle(call, parts):
    """parts لیست call.data.split(':')."""
    op = parts[1] if len(parts) > 1 else ''
    try:
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
            await _add_node_kind(call, parts[2], parts[3])
        elif op == 'manh':
            await _add_node_home(call, parts[2], parts[3])
        elif op == 'mae':
            await _add_edge_first(call, parts[2], 0)
        elif op == 'maep':
            await _add_edge_first(call, parts[2], int(parts[3]))
        elif op == 'mae1':
            await _add_edge_second(call, parts[2], parts[3], 0)
        elif op == 'mae1p':
            await _add_edge_second(call, parts[2], parts[3], int(parts[4]))
        elif op == 'mae2':
            await _add_edge_units(call, parts[2], parts[3], parts[4])
        else:
            await _answer(call, _t('map_err_generic'))
    except Exception:
        import traceback
        traceback.print_exc()
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
        rows.append([_btn(f'trd:mn:{mode}:0',
                          _t('map_btn_mode_' + mode, n=n))])
    await _send(call.chat_id, _t('map_title'), rows)
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
    await _send(call.chat_id,
                _t('map_nodes_title', mode=_t('map_mode_' + mode),
                   p=page + 1, n=pages),
                rows)
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
    neighbours = ' · '.join(
        _name(b if a == nid else a)
        for a, b in ((e['a'], e['b']) for e in links)
    ) or _t('map_no_edges')
    owner = _owner_label(nid) or _t('map_no_owner')

    rows = [
        [_btn(f'trd:mrn:{nid}', _t('map_btn_rename'))],
        [_btn(f'trd:mkd:{nid}', _t('map_btn_kind'))],
        [_btn(f'trd:mhm:{nid}', _t('map_btn_home'))],
        [_btn(f'trd:mtl:{nid}', _t('map_btn_toll'))],
    ]
    if row['kind'] in trade_map.CHOKEPOINT_KINDS:
        rows.append([_btn(f'trd:on:{nid}', _t('map_btn_owner'))])
    rows.append([_btn(f'trd:mdn:{nid}', _t('map_btn_del_node'))])
    rows.append([_btn(f'trd:mn:{mode}:0', _t('map_btn_back_nodes'))])

    text = _t('map_node', name=_esc(_name(nid)), id=_esc(nid),
              mode=_t('map_mode_' + mode),
              kind=_kind_label(row['kind']),
              home=_t('map_yes') if row['home'] else _t('map_no'),
              toll=_toll(nid), owner=_esc(owner),
              neighbours=_esc(neighbours))
    await _send(call.chat_id, text, rows)
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
    await _send(call.chat_id,
                _t('map_edges_title', mode=_t('map_mode_' + mode),
                   p=page + 1, n=pages),
                rows)
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
    text = _t('map_edge', a=_esc(_name(a)), b=_esc(_name(b)),
              units=units, timing=timing)
    await _send(call.chat_id, text, rows)
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
    await _collect_names(call.chat_id, call.user_id, {},
                         lambda names: _apply_rename(call, nid, names),
                         current=trade_map.labels(nid))


async def _apply_rename(call, nid, names):
    trade_map.set_labels(nid, names)
    _log(call.user_id, 'map_node_edit', nid, 'renamed')
    await _send(call.chat_id, _t('map_renamed'))
    await _node_screen(call, nid)


async def _collect_names(chat_id, user_id, store, done, current=None):
    """درخواست نام به هر زبان."""
    remaining = [lang for lang in trade_map.LANGS if lang not in store]
    if not remaining:
        await done(dict(store))
        return
    lang = remaining[0]
    kept = (current or {}).get(lang, '')
    text = (_t('map_ask_name_keep', lang=_t('map_lang_' + lang),
               current=_esc(kept))
            if kept else _t('map_ask_name', lang=_t('map_lang_' + lang)))
    await _send(chat_id, text)

    async def on_text(update):
        text_val = (update.new_message.text or '').strip() or kept
        if not text_val:
            await _send(update.chat_id, _t('map_name_required'))
            _next_step(user_id, on_text)
            return
        store[lang] = text_val
        await _collect_names(update.chat_id, user_id, store, done, current)

    _next_step(user_id, on_text)


async def _pick_kind(call, nid):
    if not await _require_admin(call):
        return
    mode = trade_map.mode_of(nid)
    if mode is None:
        await _answer(call, _t('map_err_unknown_node'), alert=True)
        return
    rows = [[_btn(f'trd:mks:{nid}:{kind}', _kind_label(kind))]
            for kind in trade_map.KINDS[mode]]
    await _send(call.chat_id, _t('map_pick_kind'), rows)
    await _answer(call)


async def _set_kind(call, nid, kind):
    if not await _require_admin(call):
        return
    try:
        trade_map.set_kind(nid, kind)
    except trade_map.MapError as exc:
        await _answer(call, _err(exc), alert=True)
        return
    _log(call.user_id, 'map_node_edit', nid, f'kind={kind}')
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
    _log(call.user_id, 'map_node_edit', nid, f'home={int(new_state)}')
    await _answer(call,
                  _t('map_home_on') if new_state else _t('map_home_off'))
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
    _log(call.user_id, 'map_node_edit', nid, f'toll={value}')
    await _send(call.chat_id,
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
    await _send(call.chat_id,
                _t('map_del_node_confirm', name=_esc(_name(nid)),
                   id=_esc(nid), n=links),
                rows)
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
    _log(call.user_id, 'map_node_remove', nid, label)
    await _send(call.chat_id, _t('map_node_deleted', name=_esc(label)))
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
                      lambda value: _apply_edge(call, mode, a, b, units=value),
                      minimum=1)


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
        await _send(call.chat_id, _err(exc))
        return
    detail = f'units={units}' if units is not None else f'minutes={minutes}'
    _log(call.user_id, 'map_edge_edit', f'{a}-{b}', detail)
    await _send(call.chat_id, _t('map_saved'))
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
    await _send(call.chat_id,
                _t('map_del_edge_confirm', a=_esc(_name(a)), b=_esc(_name(b))),
                rows)
    await _answer(call)


async def _edge_delete_apply(call, mode, a, b):
    if not await _require_owner(call):
        return
    try:
        trade_map.remove_edge(mode, a, b)
    except trade_map.MapError as exc:
        await _answer(call, _err(exc), alert=True)
        return
    _log(call.user_id, 'map_edge_remove', f'{a}-{b}', '')
    await _send(call.chat_id, _t('map_edge_deleted'))
    await _edge_list(call, mode, 0)


# ---------------------------------------------------------------------------
# افزودن گره
# ---------------------------------------------------------------------------


async def _add_node_start(call, mode):
    if not await _require_admin(call):
        return
    if mode not in trade_map.MODES:
        await _answer(call, _t('map_err_bad_mode'), alert=True)
        return
    _wizards[str(call.user_id)] = {'mode': mode, 'step': 'id'}
    await _answer(call)
    await _send(call.chat_id, _t('map_ask_node_id'))

    async def on_id(update):
        nid = (update.new_message.text or '').strip().lower()
        try:
            trade_map.check_new_id(nid)
        except trade_map.MapError as exc:
            await _send(update.chat_id, _err(exc))
            _next_step(call.user_id, on_id)
            return
        _wizards[str(call.user_id)]['nid'] = nid
        _wizards[str(call.user_id)]['step'] = 'kind'
        await _add_node_kind_send(update.chat_id, mode, nid)

    _next_step(call.user_id, on_id)


async def _add_node_kind_send(chat_id, mode, nid):
    rows = [[_btn(f'trd:mank:{nid}:{kind}', _kind_label(kind))]
            for kind in trade_map.KINDS[mode]]
    await _send(chat_id, _t('map_ask_node_kind'), rows)


async def _add_node_kind(call, nid, kind):
    wizard = _wizards.get(str(call.user_id))
    if not wizard or wizard.get('nid') != nid:
        await _answer(call, _t('map_err_generic'), alert=True)
        return
    wizard['kind'] = kind
    rows = [
        [_btn(f'trd:manh:{nid}:1', _t('map_yes'))],
        [_btn(f'trd:manh:{nid}:0', _t('map_no'))],
    ]
    await _send(call.chat_id, _t('map_ask_node_home'), rows)
    await _answer(call)


async def _add_node_home(call, nid, home_str):
    home = home_str == '1'
    wizard = _wizards.pop(str(call.user_id), None)
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
    _log(call.user_id, 'map_node_add', nid, f'{mode}/{kind}')
    await _answer(call, _t('map_node_added'))
    await _node_screen(call, nid)


# ---------------------------------------------------------------------------
# افزودن یال
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
    await _send(call.chat_id, _t('map_ask_edge_first'), rows)
    await _answer(call)


async def _add_edge_second(call, mode, a, page=0):
    if not await _require_admin(call):
        return
    nids = [n for n in trade_map.nodes(mode).keys() if n != a]
    window, page, pages = _page(nids, page)
    rows = [[_btn(f'trd:mae2:{mode}:{a}:{nid}', _name(nid))] for nid in window]
    _nav(rows, page, pages, f'trd:mae1:{mode}:{a}:')
    rows.append([_btn(f'trd:me:{mode}:0', _t('map_btn_back_edges'))])
    await _send(call.chat_id,
                _t('map_ask_edge_second', name=_esc(_name(a))), rows)
    await _answer(call)


async def _add_edge_units(call, mode, a, b):
    if not await _require_admin(call):
        return
    if a == b:
        await _answer(call, _t('map_err_self_edge'), alert=True)
        return
    await _answer(call)
    await _ask_number(call,
                      _t('map_ask_edge_units', a=_name(a), b=_name(b)),
                      lambda value: _apply_new_edge(call, mode, a, b, value),
                      minimum=1)


async def _apply_new_edge(call, mode, a, b, units):
    try:
        trade_map.add_edge(mode, a, b, units)
    except trade_map.MapError as exc:
        await _send(call.chat_id, _err(exc))
        return
    _log(call.user_id, 'map_edge_add', f'{a}-{b}', f'units={units}')
    await _send(call.chat_id, _t('map_edge_added'))
    await _edge_list(call, mode, 0)


# ---------------------------------------------------------------------------
# دریافت عدد
# ---------------------------------------------------------------------------


async def _ask_number(call, prompt, callback, minimum=None):
    await _send(call.chat_id, prompt)

    async def on_number(update):
        text = (update.new_message.text or '').strip()
        try:
            value = int(text)
        except (ValueError, AttributeError):
            await _send(update.chat_id, _t('map_bad_number'))
            _next_step(call.user_id, on_number)
            return
        if minimum is not None and value < minimum:
            await _send(update.chat_id, _t('map_min_number', min=minimum))
            _next_step(call.user_id, on_number)
            return
        await callback(value)

    _next_step(call.user_id, on_number)


# alias برای چک
_STRINGS = {'fa': {}, 'en': {}, 'tr': {}}
