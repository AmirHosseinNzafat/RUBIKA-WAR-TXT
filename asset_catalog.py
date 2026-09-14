# -*- coding: utf-8 -*-
"""کاتالوگ دارایی‌های بازی — منابع، واحدها و ساختمان‌ها به صورت داده.

همه چیز در سه جدول ذخیره می‌شود نه در کد پایتون، پس ادمین می‌تواند
از داخل روبیکا نوع جدید اضافه کند.

نسخه روبیکا — بدون وابستگی به تلگرام.
"""

import re
import sqlite3
import threading

# نام ستون‌هایی که در `users` هستند ولی دارایی نیستند
RESERVED = frozenset({'user_id', 'group_id', 'treaties', 'home_sea', 'home_land'})

KINDS = ('resource', 'unit', 'building')

# ستون‌هایی که trade_system مستقیم به آن‌ها SQL می‌نویسد
ENGINE_KEYS = frozenset({'money', 'small_ships', 'medium_ships', 'large_ships', 'caravans'})

DEFAULT_KIND_ORDER = ('resource', 'building', 'unit')

# کلید به نام ستون SQL تبدیل می‌شود، پس قواعد identifier اعمال می‌شود
KEY_RE = re.compile(r'^[a-z][a-z0-9_]{1,30}$')

_conn = None
_lock = threading.RLock()
_delete_guard = None


# ---------------------------------------------------------------------------
# داده‌های اولیه — بازی دقیقاً همان‌طور که عرضه شد
# ---------------------------------------------------------------------------

BUILTIN_RESOURCES = ('money', 'gold', 'iron', 'stones', 'wood', 'food', 'meat', 'clothes')
RESOURCE_DEFAULT = 2000

BUILTIN_UNITS = ('swordsmen', 'gunmen', 'cavalry_swordsmen', 'cavalry_gunmen', 'special_guard',
                 'medium_cannons', 'large_cannons', 'small_ships', 'medium_ships', 'large_ships',
                 'caravans')
UNIT_DEFAULT = 1500

BUILTIN_BUILDINGS = (
    ('stone_factory', 'stones', 1500),
    ('wood_factory', 'wood', 1500),
    ('iron_factory', 'iron', 1500),
    ('gold_mine', 'gold', 1500),
    ('farm', 'food', 1500),
    ('animal_farm', 'meat', 1500),
    ('clothes_factory', 'clothes', 1500),
    ('bank', 'money', 1500),
    ('swordsmen_camp', 'swordsmen', 500),
    ('gunmen_camp', 'gunmen', 500),
    ('cavalry_swordsmen_camp', 'cavalry_swordsmen', 500),
    ('cavalry_gunmen_camp', 'cavalry_gunmen', 500),
    ('special_guard_camp', 'special_guard', 500),
    ('medium_cannon_factory', 'medium_cannons', 1500),
    ('large_cannon_factory', 'large_cannons', 1500),
    ('small_shipyard', 'small_ships', 500),
    ('medium_shipyard', 'medium_ships', 500),
    ('large_shipyard', 'large_ships', 500),
)
BUILDING_DEFAULT = 0
BUILTIN_MAX_LEVEL = 0

BUILTIN_COSTS = {
    'stone_factory': {'wood': 500, 'money': 500},
    'wood_factory': {'stones': 500, 'money': 500},
    'iron_factory': {'stones': 500, 'money': 500},
    'gold_mine': {'wood': 500, 'stones': 500, 'money': 500},
    'farm': {'wood': 500, 'stones': 500},
    'animal_farm': {'wood': 500, 'iron': 500, 'stones': 500},
    'clothes_factory': {'gold': 500, 'money': 500, 'stones': 500},
    'bank': {'stones': 500, 'iron': 500, 'gold': 500},
    'swordsmen_camp': {'money': 500, 'stones': 500, 'wood': 500},
    'gunmen_camp': {'money': 500, 'gold': 500, 'iron': 500},
    'cavalry_swordsmen_camp': {'iron': 500, 'gold': 250, 'stones': 500, 'money': 250},
    'cavalry_gunmen_camp': {'gold': 800, 'stones': 800, 'money': 500},
    'special_guard_camp': {'money': 1000, 'stones': 1000, 'wood': 1000},
    'medium_cannon_factory': {'iron': 500, 'money': 250, 'wood': 250},
    'large_cannon_factory': {'iron': 500, 'stones': 500, 'money': 250, 'gold': 200},
    'small_shipyard': {'iron': 200, 'wood': 200, 'money': 200},
    'medium_shipyard': {'iron': 500, 'wood': 500, 'money': 500},
    'large_shipyard': {'iron': 1000, 'wood': 1000, 'money': 1000},
}

BUILTIN_LABELS = {
    'fa': {
        'money': '💵 پول', 'gold': '🏅 طلا', 'iron': '🪛 آهن', 'stones': '🪨 سنگ',
        'wood': '🌲 چوب', 'food': '🍞 غذا', 'meat': '🍖 گوشت', 'clothes': '🥋 لباس',
        'swordsmen': '🗡️ سرباز شمشیرزن', 'gunmen': '🔫 سرباز تفنگدار',
        'cavalry_swordsmen': '🗡️ سواره‌نظام شمشیرزن', 'cavalry_gunmen': '🔫 سواره‌نظام تفنگدار',
        'special_guard': '🛡️ گارد ویژه', 'medium_cannons': '🎯 توپ متوسط',
        'large_cannons': '🎯 توپ بزرگ', 'small_ships': '⛵ کشتی کوچک',
        'medium_ships': '🚢 کشتی متوسط', 'large_ships': '🛳️ کشتی بزرگ', 'caravans': '🐫 کاروان',
        'stone_factory': '🏭 کارخونه سنگ', 'wood_factory': '🏭 کارخونه چوب',
        'iron_factory': '🏭 کارخونه آهن', 'gold_mine': '⛏ معدن طلا', 'farm': '🌾 زمین کشاورزی',
        'animal_farm': '🐄 دامداری', 'clothes_factory': '🧵 کارخانه لباس', 'bank': '🏦 بانک',
        'swordsmen_camp': '⚔️ کمپ سرباز شمشیرزن', 'gunmen_camp': '⚔️ کمپ سرباز تفنگدار',
        'cavalry_swordsmen_camp': '⚔️ کمپ سواره‌نظام شمشیرزن',
        'cavalry_gunmen_camp': '⚔️ کمپ سواره‌نظام تفنگدار',
        'special_guard_camp': '⚔️ کمپ گارد ویژه',
        'medium_cannon_factory': '🔧 کارخانه توپ متوسط',
        'large_cannon_factory': '🔧 کارخانه توپ بزرگ',
        'small_shipyard': '⚓ کشتی‌سازی کوچک', 'medium_shipyard': '⚓ کشتی‌سازی متوسط',
        'large_shipyard': '⚓ کشتی‌سازی بزرگ',
    },
}

LANGS = tuple(BUILTIN_LABELS)


class CatalogError(ValueError):
    """خطای کلید یا فیلد نامعتبر در کاتالوگ"""


# ---------------------------------------------------------------------------
# راه‌اندازی
# ---------------------------------------------------------------------------


def init(conn):
    """ساخت جداول کاتالوگ، مقداردهی اولیه و همگام‌سازی ستون‌های users"""
    global _conn
    _conn = conn
    _migrate()
    _seed()
    ensure_columns()


def _migrate():
    with _lock:
        _conn.execute('''CREATE TABLE IF NOT EXISTS asset_catalog (
            key           TEXT PRIMARY KEY,
            kind          TEXT NOT NULL,
            position      INTEGER NOT NULL DEFAULT 0,
            default_value INTEGER NOT NULL DEFAULT 0,
            builtin       INTEGER NOT NULL DEFAULT 0,
            hidden        INTEGER NOT NULL DEFAULT 0,
            produces      TEXT NOT NULL DEFAULT '',
            output        INTEGER NOT NULL DEFAULT 0,
            tradeable     INTEGER NOT NULL DEFAULT 0,
            max_level     INTEGER NOT NULL DEFAULT 0
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS asset_labels (
            key   TEXT NOT NULL,
            lang  TEXT NOT NULL,
            label TEXT NOT NULL,
            PRIMARY KEY (key, lang)
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS asset_upgrade_costs (
            building TEXT NOT NULL,
            resource TEXT NOT NULL,
            amount   INTEGER NOT NULL,
            PRIMARY KEY (building, resource)
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS asset_removed (
            key TEXT PRIMARY KEY
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS asset_level_costs (
            building TEXT NOT NULL,
            level    INTEGER NOT NULL,
            resource TEXT NOT NULL,
            amount   INTEGER NOT NULL,
            PRIMARY KEY (building, level, resource)
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS asset_level_output (
            building TEXT NOT NULL,
            level    INTEGER NOT NULL,
            output   INTEGER NOT NULL,
            PRIMARY KEY (building, level)
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS asset_kind_order (
            kind     TEXT PRIMARY KEY,
            position INTEGER NOT NULL
        )''')
        columns = {row[1] for row in _conn.execute("PRAGMA table_info(asset_catalog)")}
        if 'max_level' not in columns:
            _conn.execute("ALTER TABLE asset_catalog ADD COLUMN max_level INTEGER NOT NULL DEFAULT 0")
        _conn.executemany(
            "INSERT OR IGNORE INTO asset_kind_order (kind, position) VALUES (?, ?)",
            [(kind, (i + 1) * 10) for i, kind in enumerate(DEFAULT_KIND_ORDER)])
        _conn.commit()


def _builtin_rows():
    rows = []
    for keys, kind, default, tradeable in (
            (BUILTIN_RESOURCES, 'resource', RESOURCE_DEFAULT, 1),
            (BUILTIN_UNITS, 'unit', UNIT_DEFAULT, 0)):
        for index, key in enumerate(keys, start=1):
            rows.append((key, kind, index * 10, default, 1, 0, '', 0, tradeable, 0))
    for index, (key, produces, output) in enumerate(BUILTIN_BUILDINGS, start=1):
        rows.append((key, 'building', index * 10, BUILDING_DEFAULT, 1, 0, produces, output, 0,
                     BUILTIN_MAX_LEVEL))
    return rows


def _builtin_label_rows():
    return [(key, lang, label)
            for lang, table in BUILTIN_LABELS.items()
            for key, label in table.items()]


def _builtin_cost_rows():
    return [(building, resource, amount)
            for building, table in BUILTIN_COSTS.items()
            for resource, amount in table.items()]


def removed_builtins():
    return frozenset(row['key'] for row in _q("SELECT key FROM asset_removed"))


def _seed():
    dead = removed_builtins()
    with _lock:
        _conn.executemany(
            "INSERT OR IGNORE INTO asset_catalog "
            "(key, kind, position, default_value, builtin, hidden, produces, output, tradeable, max_level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [r for r in _builtin_rows() if r[0] not in dead])
        _conn.executemany(
            "INSERT OR IGNORE INTO asset_labels (key, lang, label) VALUES (?, ?, ?)",
            [r for r in _builtin_label_rows() if r[0] not in dead])
        _conn.executemany(
            "INSERT OR IGNORE INTO asset_upgrade_costs (building, resource, amount) VALUES (?, ?, ?)",
            [r for r in _builtin_cost_rows() if r[0] not in dead and r[1] not in dead])
        _conn.commit()


def ensure_columns():
    with _lock:
        existing = {r[1] for r in _conn.execute("PRAGMA table_info(users)").fetchall()}
        for row in _q("SELECT key, default_value FROM asset_catalog"):
            if row['key'] in existing:
                continue
            _check_key(row['key'])
            _conn.execute(
                f"ALTER TABLE users ADD COLUMN {row['key']} INTEGER DEFAULT {int(row['default_value'])}")
            _conn.execute(f"UPDATE users SET {row['key']}=? WHERE {row['key']} IS NULL",
                          (int(row['default_value']),))
        _conn.commit()


# ---------------------------------------------------------------------------
# ابزارهای کمکی
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


def _check_key(key):
    if not KEY_RE.match(key or ''):
        raise CatalogError('bad_key')
    if key in RESERVED:
        raise CatalogError('reserved_key')
    return key


def set_delete_guard(fn):
    global _delete_guard
    _delete_guard = fn


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------


def keys(kind=None, include_hidden=False):
    """کلیدهای کاتالوگ، به ترتیب kind و position"""
    sql = "SELECT key, kind, hidden FROM asset_catalog"
    params = ()
    if kind:
        sql += " WHERE kind=?"
        params = (kind,)
    sql += " ORDER BY kind, position"
    rows = _q(sql, params)
    if not include_hidden:
        rows = [r for r in rows if not r['hidden']]
    return tuple(r['key'] for r in rows)


def all_keys():
    return keys(include_hidden=True)


def entries(kind, include_hidden=False):
    sql = "SELECT * FROM asset_catalog WHERE kind=?"
    params = (kind,)
    if not include_hidden:
        sql += " AND hidden=0"
    sql += " ORDER BY position"
    return _q(sql, params)


def entry(key):
    rows = _q("SELECT * FROM asset_catalog WHERE key=?", (key,))
    return rows[0] if rows else None


def label(key, lang='fa'):
    rows = _q("SELECT label FROM asset_labels WHERE key=? AND lang=?", (key, lang))
    return rows[0]['label'] if rows else key


def kind_order():
    return tuple(r['kind'] for r in
                 _q("SELECT kind FROM asset_kind_order ORDER BY position"))


def kind_rank(kind):
    order = kind_order()
    if kind not in order:
        return (0, len(order))
    return (order.index(kind) + 1, len(order))


def rank(key):
    row = entry(key)
    if not row:
        return (0, 0)
    same_kind = keys(row['kind'], include_hidden=True)
    return (same_kind.index(key) + 1, len(same_kind)) if key in same_kind else (0, len(same_kind))


def tradeable_resources():
    return tuple(r['key'] for r in
                 _q("SELECT key FROM asset_catalog WHERE kind='resource' AND tradeable=1 "
                    "AND hidden=0 ORDER BY position"))


def production():
    """(building, produces, output) برای ساختمان‌های فعال"""
    return [(r['key'], r['produces'], r['output'])
            for r in _q("SELECT key, produces, output FROM asset_catalog "
                        "WHERE kind='building' AND hidden=0 AND produces != '' ORDER BY position")]


def max_level(key):
    row = entry(key)
    return (row['max_level'] or 0) if row else 0


def at_max_level(key, level):
    cap = max_level(key)
    return bool(cap and level >= cap)


def upgrade_cost(key, level=None):
    """هزینه ارتقای یک سطح خاص، یا هزینه پیش‌فرض"""
    if level is not None:
        tuned = _q("SELECT resource, amount FROM asset_level_costs "
                   "WHERE building=? AND level=?", (key, level))
        if tuned:
            return {r['resource']: r['amount'] for r in tuned}
    flat = _q("SELECT resource, amount FROM asset_upgrade_costs WHERE building=?", (key,))
    return {r['resource']: r['amount'] for r in flat}


def tuned_cost_levels(key):
    return tuple(r['level'] for r in
                 _q("SELECT DISTINCT level FROM asset_level_costs WHERE building=? ORDER BY level",
                    (key,)))


def tuned_output_levels(key):
    return tuple(r['level'] for r in
                 _q("SELECT DISTINCT level FROM asset_level_output WHERE building=? ORDER BY level",
                    (key,)))


def level_output(key, level):
    """محصول یک سطح خاص، یا مقدار پیش‌فرض"""
    tuned = _q("SELECT output FROM asset_level_output WHERE building=? AND level=?",
               (key, level))
    if tuned:
        return tuned[0]['output']
    row = entry(key)
    return (row['output'] or 0) if row else 0


def holders(key):
    """چند کشور این دارایی را دارند (برای هشدار حذف)"""
    existing = {r[1] for r in _conn.execute("PRAGMA table_info(users)").fetchall()}
    if key not in existing:
        return 0
    rows = _q(f"SELECT COUNT(*) AS n FROM users WHERE {key} > 0")
    return rows[0]['n'] if rows else 0


# ---------------------------------------------------------------------------
# نوشتن
# ---------------------------------------------------------------------------


def set_labels(key, labels):
    with _lock:
        for lang, text in labels.items():
            _conn.execute("INSERT OR REPLACE INTO asset_labels (key, lang, label) VALUES (?, ?, ?)",
                          (key, lang, text))
        _conn.commit()


def set_default(key, value):
    _exec("UPDATE asset_catalog SET default_value=? WHERE key=?", (int(value), key))


def set_output(key, produces, output):
    _exec("UPDATE asset_catalog SET produces=?, output=? WHERE key=?",
          (produces or '', int(output or 0), key))


def set_tradeable(key, value):
    _exec("UPDATE asset_catalog SET tradeable=? WHERE key=?", (1 if value else 0, key))


def set_upgrade_cost(key, resource, amount):
    _exec("INSERT OR REPLACE INTO asset_upgrade_costs (building, resource, amount) "
          "VALUES (?, ?, ?)", (key, resource, int(amount)))


def set_level_cost(key, level, resource, amount):
    _exec("INSERT OR REPLACE INTO asset_level_costs (building, level, resource, amount) "
          "VALUES (?, ?, ?, ?)", (key, int(level), resource, int(amount)))


def clear_level(key, level):
    _exec("DELETE FROM asset_level_costs WHERE building=? AND level=?", (key, int(level)))
    _exec("DELETE FROM asset_level_output WHERE building=? AND level=?", (key, int(level)))


def set_max_level(key, value):
    _exec("UPDATE asset_catalog SET max_level=? WHERE key=?", (int(value), key))


def move(key, direction):
    """جابجایی یک دارایی در ترتیب نمایش"""
    row = entry(key)
    if not row:
        raise CatalogError('unknown')
    siblings = entries(row['kind'], include_hidden=True)
    idx = next((i for i, r in enumerate(siblings) if r['key'] == key), -1)
    if idx < 0:
        return False
    target = idx - 1 if direction == 'up' else idx + 1
    if target < 0 or target >= len(siblings):
        return False
    with _lock:
        a = siblings[idx]
        b = siblings[target]
        _conn.execute("UPDATE asset_catalog SET position=? WHERE key=?",
                      (b['position'], a['key']))
        _conn.execute("UPDATE asset_catalog SET position=? WHERE key=?",
                      (a['position'], b['key']))
        _conn.commit()
    return True


def move_kind(kind, direction):
    order = list(kind_order())
    if kind not in order:
        return False
    idx = order.index(kind)
    target = idx - 1 if direction == 'up' else idx + 1
    if target < 0 or target >= len(order):
        return False
    order[idx], order[target] = order[target], order[idx]
    with _lock:
        for i, k in enumerate(order, start=1):
            _conn.execute("UPDATE asset_kind_order SET position=? WHERE kind=?",
                          (i * 10, k))
        _conn.commit()
    return True


def set_kind(key, kind):
    if kind not in KINDS:
        raise CatalogError('bad_kind')
    _exec("UPDATE asset_catalog SET kind=? WHERE key=?", (kind, key))


def add(key, kind, position=None, default=0, produces='', output=0, tradeable=0):
    """افزودن یک نوع جدید به کاتالوگ"""
    _check_key(key)
    if kind not in KINDS:
        raise CatalogError('bad_kind')
    if position is None:
        rows = _q("SELECT MAX(position) AS p FROM asset_catalog WHERE kind=?", (kind,))
        position = ((rows[0]['p'] or 0) + 10) if rows else 10
    with _lock:
        _conn.execute(
            "INSERT INTO asset_catalog (key, kind, position, default_value, builtin, hidden, "
            "produces, output, tradeable, max_level) VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, 0)",
            (key, kind, position, int(default), produces or '', int(output or 0),
             1 if tradeable else 0))
        _conn.commit()
    ensure_columns()


def hide(key):
    _exec("UPDATE asset_catalog SET hidden=1 WHERE key=?", (key,))


def unhide(key):
    _exec("UPDATE asset_catalog SET hidden=0 WHERE key=?", (key,))


def remove(key):
    """حذف دائمی. اگر در حال حمل توسط تجارت باشد یا ENGINE_KEY باشد، خطا می‌دهد"""
    if key in ENGINE_KEYS:
        raise CatalogError('engine_key')
    if _delete_guard is not None:
        try:
            in_flight = _delete_guard()
        except Exception:
            in_flight = set()
        if key in in_flight:
            raise CatalogError('in_flight')
    with _lock:
        existing = {r[1] for r in _conn.execute("PRAGMA table_info(users)").fetchall()}
        dropped = key in existing
        if dropped:
            _conn.execute(f"ALTER TABLE users DROP COLUMN {key}")
        _conn.execute("DELETE FROM asset_catalog WHERE key=?", (key,))
        _conn.execute("DELETE FROM asset_labels WHERE key=?", (key,))
        _conn.execute("DELETE FROM asset_upgrade_costs WHERE building=? OR resource=?", (key, key))
        _conn.execute("DELETE FROM asset_level_costs WHERE building=? OR resource=?", (key, key))
        _conn.execute("DELETE FROM asset_level_output WHERE building=?", (key,))
        _conn.execute("INSERT OR IGNORE INTO asset_removed (key) VALUES (?)", (key,))
        _conn.commit()
    return dropped
