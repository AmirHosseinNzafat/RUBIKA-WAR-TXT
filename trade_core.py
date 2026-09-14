# -*- coding: utf-8 -*-
"""هسته سیستم تجارت — پیکربندی، دیتابیس، مسیریابی، escrow.

بدون UI. صرفاً منطق. بقیه ماژول‌های trade_* به این وابسته‌ن.

نسخه روبیکا.
"""

import heapq
import html
import json
import sqlite3
import threading

import asset_catalog
import trade_map

# ---------------------------------------------------------------------------
# وضعیت
# ---------------------------------------------------------------------------
_bot = None
_conn = None
_admin_id = None
_channel = None
_lang = 'fa'
_is_admin = None
_is_owner = None
_lock = threading.RLock()
_title_cache = {}


CONFIG_DEFAULTS = {
    'sea_min_per_unit': 30,
    'land_min_per_unit': 45,
    'fee_per_unit': 20,
    'cap_small': 500, 'cap_medium': 1500, 'cap_large': 4000,
    'cap_caravan': 250, 'caravan_cost': 50,
    'offer_expiry_min': 120,
    'toll_sue': 500, 'toll_pan': 500, 'toll_kie': 150, 'toll_dan': 50,
    'toll_gib': 100, 'toll_bos': 100, 'toll_dar': 100, 'toll_hor': 100,
    'toll_bab': 100, 'toll_mal': 200, 'toll_sun': 100, 'toll_lom': 100,
    'toll_tsu': 100, 'toll_ber': 100, 'toll_mag': 150, 'toll_moz': 50,
    'toll_sin': 50, 'toll_sah': 100, 'toll_cau': 100, 'toll_zag': 100,
    'toll_pam': 150, 'toll_khy': 100,
}

PHOTO_KEY = 'trade_photo'
PHOTO_KEYS = {'sea': 'trade_photo_sea', 'land': 'trade_photo_land'}
PHOTO_MODES = ('sea', 'land')

SHIPS = (
    ('s', 'small_ships', 'cap_small'),
    ('m', 'medium_ships', 'cap_medium'),
    ('l', 'large_ships', 'cap_large'),
)
CARAVANS = (('c', 'caravans', 'cap_caravan'),)
VEHICLES = {'sea': SHIPS, 'land': CARAVANS}
VEH_BY_CODE = {code: col for table in VEHICLES.values() for code, col, _ in table}
CAP_KEY = {col: cap for table in VEHICLES.values() for _, col, cap in table}

LIVE_STATUSES = ('offered', 'active')


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def init(bot, conn, admin_id, channel_id, lang='fa',
         is_admin=None, is_owner=None):
    global _bot, _conn, _admin_id, _channel, _lang, _is_admin, _is_owner
    _bot = bot
    _conn = conn
    _admin_id = admin_id
    _channel = channel_id
    _lang = lang
    _is_admin = is_admin if is_admin is not None else (lambda uid: uid == admin_id)
    _is_owner = is_owner if is_owner is not None else (lambda uid: uid == admin_id)
    _migrate()
    _seed_config()
    trade_map.init(conn)
    trade_map.set_node_guard(active_route_nodes)


def _migrate():
    with _lock:
        for col in ('home_sea', 'home_land'):
            try:
                _conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
        _conn.execute('''CREATE TABLE IF NOT EXISTS group_trade_modes (
            group_id TEXT NOT NULL,
            mode     TEXT NOT NULL,
            open     INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (group_id, mode)
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_group_id   TEXT NOT NULL,
            sender_user_id    TEXT NOT NULL,
            receiver_group_id TEXT NOT NULL,
            receiver_user_id  TEXT NOT NULL,
            mode        TEXT NOT NULL,
            goods       TEXT NOT NULL,
            vehicles    TEXT NOT NULL,
            route       TEXT NOT NULL,
            leg_minutes TEXT NOT NULL,
            tolls       TEXT DEFAULT '[]',
            leg         INTEGER DEFAULT 0,
            fee_paid    INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'offered',
            offered_at  INTEGER,
            departed_at INTEGER,
            next_eta    INTEGER,
            offer_chat_id TEXT, offer_msg_id TEXT,
            track_chat_id TEXT, track_msg_id TEXT,
            offer_photo INTEGER DEFAULT 0,
            track_photo INTEGER DEFAULT 0
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS trade_config (
            key TEXT PRIMARY KEY, value INTEGER NOT NULL)''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS trade_settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS chokepoint_owners (
            node_id TEXT PRIMARY KEY, group_id TEXT NOT NULL)''')
        _conn.commit()


def _seed_config():
    with _lock:
        for k, v in CONFIG_DEFAULTS.items():
            _conn.execute("INSERT OR IGNORE INTO trade_config (key, value) VALUES (?, ?)",
                          (k, v))
        _conn.commit()


def cfg(key):
    with _lock:
        row = _conn.execute("SELECT value FROM trade_config WHERE key=?", (key,)).fetchone()
    return row[0] if row else CONFIG_DEFAULTS.get(key, 0)


def set_cfg(key, value):
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO trade_config (key, value) VALUES (?, ?)",
                      (key, int(value)))
        _conn.commit()


# ---------------------------------------------------------------------------
# ابزار
# ---------------------------------------------------------------------------


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


def _t(string_id, **kw):
    from trade_strings import STRINGS
    s = STRINGS[_lang][string_id]
    return s.format(**kw) if kw else s


def _esc(text):
    return html.escape(text, quote=False) if text else text


# ---------------------------------------------------------------------------
# عکس‌ها
# ---------------------------------------------------------------------------


def _setting(key):
    with _lock:
        row = _conn.execute("SELECT value FROM trade_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else ''


def photo(mode=None):
    if mode in PHOTO_KEYS:
        own = _setting(PHOTO_KEYS[mode])
        if own:
            return own
    return _setting(PHOTO_KEY)


def own_photo(mode):
    return _setting(PHOTO_KEYS[mode]) if mode in PHOTO_KEYS else _setting(PHOTO_KEY)


def set_photo(file_id, mode=None):
    key = PHOTO_KEYS.get(mode, PHOTO_KEY)
    with _lock:
        if file_id:
            _conn.execute("INSERT OR REPLACE INTO trade_settings (key, value) VALUES (?, ?)",
                          (key, str(file_id)))
        else:
            _conn.execute("DELETE FROM trade_settings WHERE key=?", (key,))
        _conn.commit()


# ---------------------------------------------------------------------------
# عنوان گروه
# ---------------------------------------------------------------------------


async def title(gid):
    key = str(gid)
    if key in _title_cache:
        return _title_cache[key]
    try:
        chat = await _bot.get_chat(gid)
        _title_cache[key] = getattr(chat, 'title', None) or key
    except Exception:
        _title_cache[key] = key
    return _title_cache[key]


def title_sync(gid):
    """نسخه sync — از کش می‌خونه، اگه نبود خودش id برمی‌گردونه."""
    return _title_cache.get(str(gid), str(gid))


# ---------------------------------------------------------------------------
# lord
# ---------------------------------------------------------------------------


def is_lord(group_id, user_id):
    with _lock:
        row = _conn.execute("SELECT 1 FROM users WHERE group_id=? AND user_id=?",
                            (group_id, user_id)).fetchone()
    return row is not None


def lord_row(group_id):
    rows = _q("SELECT user_id, home_sea, home_land FROM users WHERE group_id=?",
              (group_id,))
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# مسیریابی (Dijkstra)
# ---------------------------------------------------------------------------


def _nodes(mode):
    return trade_map.nodes(mode)


def _node(mode, nid):
    return trade_map.node(mode, nid)


def node_name(mode, nid):
    return trade_map.name(nid, _lang)


def mode_name(mode):
    return _t('mode_sea' if mode == 'sea' else 'mode_land')


def mode_emoji(mode):
    return '🚢' if mode == 'sea' else '🐫'


def toll(nid):
    return cfg('toll_' + nid)


def owner_of(nid):
    with _lock:
        row = _conn.execute("SELECT group_id FROM chokepoint_owners WHERE node_id=?",
                            (nid,)).fetchone()
    return row[0] if row else None


def set_owner(nid, gid):
    with _lock:
        if gid:
            _conn.execute("INSERT OR REPLACE INTO chokepoint_owners "
                          "(node_id, group_id) VALUES (?, ?)", (nid, gid))
        else:
            _conn.execute("DELETE FROM chokepoint_owners WHERE node_id=?", (nid,))
        _conn.commit()


def set_toll(nid, amount):
    set_cfg('toll_' + nid, max(0, int(amount)))


def owner_name(nid):
    gid = owner_of(nid)
    return title_sync(gid) if gid else None


def toll_for(nid, sender_gid=None):
    amt = toll(nid)
    if amt and sender_gid is not None and owner_of(nid) == str(sender_gid):
        return 0
    return amt


def mode_of_node(nid):
    return trade_map.mode_of(nid) or 'sea'


def _adj(mode):
    return trade_map.adjacency(mode)


def _dijkstra(adj, src, dst, blocked=frozenset(), cost_fn=None):
    if src in blocked or dst in blocked or src not in adj or dst not in adj:
        return None
    dist = {src: 0}
    prev = {}
    pq = [(0, src)]
    done = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        if u == dst:
            path = [dst]
            while path[-1] != src:
                path.append(prev[path[-1]])
            return d, path[::-1]
        for v, w in adj[u]:
            if v in blocked or v in done:
                continue
            nd = d + (cost_fn(u, v, w) if cost_fn else w)
            if nd < dist.get(v, float('inf')):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return None


def _route_info(mode, path, label, local=False, sender_gid=None):
    mpu = cfg('sea_min_per_unit' if mode == 'sea' else 'land_min_per_unit')
    if local:
        leg_units = [1]
        leg_minutes = [mpu]
    else:
        legs = [trade_map.leg(mode, path[i], path[i + 1]) or (0, 0)
                for i in range(len(path) - 1)]
        leg_units = [u for u, _m in legs]
        leg_minutes = [m if m > 0 else u * mpu for u, m in legs]
    units = sum(leg_units)
    tolls = [(nid, toll_for(nid, sender_gid)) for nid in path]
    tolls = [(nid, amt) for nid, amt in tolls if amt > 0]
    base_fee = units * cfg('fee_per_unit')
    toll_total = sum(a for _, a in tolls)
    return {
        'label': label, 'path': path, 'units': units,
        'minutes': sum(leg_minutes), 'leg_minutes': leg_minutes,
        'base_fee': base_fee, 'tolls': tolls, 'toll_total': toll_total,
        'money': base_fee + toll_total,
    }


def find_routes(mode, src, dst, sender_gid=None):
    if src == dst:
        return [_route_info(mode, [src, src], 'route_fast',
                            local=True, sender_gid=sender_gid)]
    adj = _adj(mode)
    fee = cfg('fee_per_unit')
    tolled = frozenset(n for n in _nodes(mode) if toll_for(n, sender_gid) > 0)
    candidates = []
    r = _dijkstra(adj, src, dst)
    if r:
        candidates.append((r[1], 'route_fast'))
    r = _dijkstra(adj, src, dst, blocked=tolled)
    if r:
        candidates.append((r[1], 'route_free'))
    r = _dijkstra(adj, src, dst,
                  cost_fn=lambda u, v, w: (w * fee + toll_for(v, sender_gid)) * 1000 + w)
    if r:
        candidates.append((r[1], 'route_cheap'))
    out, seen = [], set()
    for path, label in candidates:
        key = tuple(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(_route_info(mode, path, label, sender_gid=sender_gid))
    return out


def path_names(mode, path):
    if len(path) == 2 and path[0] == path[1]:
        return node_name(mode, path[0])
    arrow = ' ← ' if _lang == 'fa' else ' → '
    return arrow.join(node_name(mode, nid) for nid in path)


# ---------------------------------------------------------------------------
# اقتصاد: escrow / refund / credit
# ---------------------------------------------------------------------------


def escrow(group_id, goods, vehicles, fee):
    need = dict(goods)
    need['money'] = need.get('money', 0) + fee
    for col, n in vehicles.items():
        if n:
            need[col] = need.get(col, 0) + n
    cols = list(need)
    with _lock:
        row = _conn.execute(
            f"SELECT {', '.join(cols)} FROM users WHERE group_id=?",
            (group_id,)).fetchone()
        if row is None or any(row[i] < need[c] for i, c in enumerate(cols)):
            return False
        sets = ', '.join(f"{c} = {c} - ?" for c in cols)
        _conn.execute(f"UPDATE users SET {sets} WHERE group_id=?",
                      [need[c] for c in cols] + [group_id])
        _conn.commit()
    return True


def give(group_id, amounts):
    amounts = {c: n for c, n in amounts.items() if n}
    if not amounts:
        return
    cols = list(amounts)
    sets = ', '.join(f"{c} = {c} + ?" for c in cols)
    _exec(f"UPDATE users SET {sets} WHERE group_id=?",
          [amounts[c] for c in cols] + [group_id])


def refund(trade):
    back = dict(json.loads(trade['goods']))
    back['money'] = back.get('money', 0) + trade['fee_paid']
    for col, n in json.loads(trade['vehicles']).items():
        if n:
            back[col] = back.get(col, 0) + n
    give(trade['sender_group_id'], back)


# ---------------------------------------------------------------------------
# گاردهای حذف
# ---------------------------------------------------------------------------


def active_goods_keys():
    keys = set()
    placeholders = ', '.join('?' * len(LIVE_STATUSES))
    for row in _q(f"SELECT goods, vehicles FROM trades "
                  f"WHERE status IN ({placeholders})", LIVE_STATUSES):
        keys.update(json.loads(row['goods']))
        keys.update(json.loads(row['vehicles']))
    keys.add('money')
    return keys


def active_route_nodes():
    nodes = set()
    placeholders = ', '.join('?' * len(LIVE_STATUSES))
    for row in _q(f"SELECT route FROM trades WHERE status IN ({placeholders})",
                  LIVE_STATUSES):
        nodes.update(json.loads(row['route']))
    return nodes


def active_trade_groups():
    groups = set()
    placeholders = ', '.join('?' * len(LIVE_STATUSES))
    for row in _q(f"SELECT sender_group_id, receiver_group_id FROM trades "
                  f"WHERE status IN ({placeholders})", LIVE_STATUSES):
        groups.add(row['sender_group_id'])
        groups.add(row['receiver_group_id'])
    return groups


# ---------------------------------------------------------------------------
# حالت تجارت هر کشور
# ---------------------------------------------------------------------------


def mode_open(group_id, mode):
    rows = _q("SELECT open FROM group_trade_modes WHERE group_id=? AND mode=?",
              (str(group_id), mode))
    return bool(rows[0]['open']) if rows else True


def set_mode_open(group_id, mode, is_open):
    if mode not in PHOTO_MODES:
        return
    _exec("INSERT OR REPLACE INTO group_trade_modes (group_id, mode, open) "
          "VALUES (?, ?, ?)", (str(group_id), mode, 1 if is_open else 0))


def open_modes(group_id):
    return {mode: mode_open(group_id, mode) for mode in PHOTO_MODES}


# ---------------------------------------------------------------------------
# ابزار کمکی برای پیام
# ---------------------------------------------------------------------------


async def send_rich(chat_id, text, mode=None, **kwargs):
    """ارسال متن به صورت caption عکس اگه عکسی تنظیم شده باشه.
    Returns (message_id, used_photo)
    """
    file_id = photo(mode)
    text_clean = _to_markdown(text)
    if file_id and len(text_clean) <= 1000:
        try:
            mid = await _bot.send_file(chat_id, file_id=file_id,
                                       type="Image", text=text_clean, **kwargs)
            return mid, True
        except Exception:
            pass
    mid = await _bot.send_message(chat_id, text_clean, **kwargs)
    return mid, False


def _to_markdown(text):
    if not text:
        return text
    text = text.replace('<b>', '**').replace('</b>', '**')
    text = text.replace('<code>', '`').replace('</code>', '`')
    text = text.replace('<blockquote>', '\n').replace('</blockquote>', '\n')
    return text
