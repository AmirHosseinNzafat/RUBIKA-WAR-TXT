# -*- coding: utf-8 -*-
"""دنیای تجارت به صورت داده — گره‌ها، یال‌های بین آن‌ها و نام‌هایشان.

نقشه قبلاً چهار literal پایتون داخل trade_system بود. الان در سه جدول
زندگی می‌کند، پس ادمین می‌تواند کانال سوئز را تغییر نام دهد، زمان یک
مسیر را عوض کند، یا مسیری بکشد که هرگز وجود نداشت — همه از داخل روبیکا.

    trade_nodes        یک ردیف برای هر مکان: mode، kind، آیا کشور می‌تواند
                       آنجا بنشیند، و ترتیب نمایش در لیست ادمین
    trade_node_labels  نام نمایشی به ازای هر زبان
    trade_edges        یک پای بدون جهت: دو گره، طولش، زمانش

نقشه‌ای که با بازی عرضه شد در اولین اجرا با `builtin=1` و دقیقاً همان
مقادیری که literal ها داشتند seed می‌شود، پس دیتابیس‌های موجود کار
می‌کنند — شناسه گره‌ها هنوز با users.home_sea، users.home_land،
chokepoint_owners.node_id و کلیدهای toll_<id> در trade_config مطابقت دارند.

حذف یک گره یا یال seed شده یک tombstone می‌نویسد، وگرنه ری‌استارت بعدی
آن را برمی‌گرداند.

دو فیلد هزینه یک پای را حمل می‌کنند، و یکی نیستند:

    units    فاصله. کارمزد را می‌راند و تعیین می‌کند Dijkstra کدام را ارزان‌تر می‌داند.
    minutes  زمان سفر. 0 یعنی «از units مشتق کن»، هر چیز دیگر override دقیق است.

این تفکیک به ادمین اجازه می‌دهد بگوید «سوئز به دریای سرخ ۴۰ دقیقه طول می‌کشد»
بدون اینکه قیمتی را جابه‌جا کند.

نسخه روبیکا — بدون وابستگی به تلگرام.
"""

import re
import sqlite3
import threading

MODES = ('sea', 'land')

# یک گره چه چیزی می‌تواند باشد. تنگه‌ها، کانال‌ها و گذرگاه‌ها chokepoint های
# عوارض‌دارند: آن‌ها گره هستند نه یال، تا ticker بتواند عبور از آن‌ها را
# روایت کند و یک مسیر بدون عوارض بتواند به سادگی دورشان بزند.
KINDS = {
    'sea': ('ocean', 'sea', 'strait', 'canal', 'cape'),
    'land': ('region', 'pass'),
}
CHOKEPOINT_KINDS = ('strait', 'canal', 'pass')

# شناسه گره بخشی از کلید toll_<id> می‌شود و به صورت ارجاع ساده در سه جدول
# دیگر ذخیره می‌شود، پس به قواعد identifier محدود می‌شود.
NODE_ID_RE = re.compile(r'^[a-z][a-z0-9_]{1,15}$')

LANGS = ('fa', 'en', 'tr')

_conn = None
_lock = threading.RLock()
_cache = {}
_node_guard = None


class MapError(ValueError):
    """برای گره، یال یا فیلدی که نقشه نمی‌پذیرد."""


# ---------------------------------------------------------------------------
# داده‌های اولیه — دنیا دقیقاً همان‌طور که عرضه شد
# ---------------------------------------------------------------------------


def _N(kind, home, fa, en, tr):
    return {'kind': kind, 'home': home, 'names': {'fa': fa, 'en': en, 'tr': tr}}


SEA_NODES = {
    # اقیانوس‌ها
    'nat': _N('ocean', True, 'اقیانوس اطلس شمالی', 'North Atlantic Ocean', 'Kuzey Atlantik Okyanusu'),
    'sat': _N('ocean', True, 'اقیانوس اطلس جنوبی', 'South Atlantic Ocean', 'Güney Atlantik Okyanusu'),
    'ind': _N('ocean', True, 'اقیانوس هند', 'Indian Ocean', 'Hint Okyanusu'),
    'npa': _N('ocean', True, 'اقیانوس آرام شمالی', 'North Pacific Ocean', 'Kuzey Pasifik Okyanusu'),
    'spa': _N('ocean', True, 'اقیانوس آرام جنوبی', 'South Pacific Ocean', 'Güney Pasifik Okyanusu'),
    'arc': _N('ocean', True, 'اقیانوس منجمد شمالی', 'Arctic Ocean', 'Arktik Okyanusu'),
    # دریاها و خلیج‌ها
    'nor': _N('sea', True, 'دریای شمال', 'North Sea', 'Kuzey Denizi'),
    'bal': _N('sea', True, 'دریای بالتیک', 'Baltic Sea', 'Baltık Denizi'),
    'med': _N('sea', True, 'دریای مدیترانه', 'Mediterranean Sea', 'Akdeniz'),
    'bla': _N('sea', True, 'دریای سیاه', 'Black Sea', 'Karadeniz'),
    'mar': _N('sea', True, 'دریای مرمره', 'Sea of Marmara', 'Marmara Denizi'),
    'red': _N('sea', True, 'دریای سرخ', 'Red Sea', 'Kızıldeniz'),
    'per': _N('sea', True, 'خلیج فارس', 'Persian Gulf', 'Basra Körfezi'),
    'oma': _N('sea', True, 'دریای عمان و عرب', 'Arabian Sea', 'Umman ve Arap Denizi'),
    'ade': _N('sea', True, 'دریای عدن', 'Gulf of Aden', 'Aden Körfezi'),
    'car': _N('sea', True, 'خلیج کارائیب', 'Caribbean Sea', 'Karayip Denizi'),
    'gmx': _N('sea', True, 'خلیج مکزیک', 'Gulf of Mexico', 'Meksika Körfezi'),
    'scs': _N('sea', True, 'دریای چین جنوبی', 'South China Sea', 'Güney Çin Denizi'),
    'ecs': _N('sea', True, 'دریای چین شرقی', 'East China Sea', 'Doğu Çin Denizi'),
    'yel': _N('sea', True, 'دریای زرد', 'Yellow Sea', 'Sarı Deniz'),
    'jap': _N('sea', True, 'دریای ژاپن', 'Sea of Japan', 'Japon Denizi'),
    'phi': _N('sea', True, 'دریای فیلیپین', 'Philippine Sea', 'Filipin Denizi'),
    'gui': _N('sea', True, 'خلیج گینه', 'Gulf of Guinea', 'Gine Körfezi'),
    # تنگه‌ها (chokepoint های عوارض‌دار)
    'gib': _N('strait', False, 'تنگه جبل‌الطارق', 'Strait of Gibraltar', 'Cebelitarık Boğazı'),
    'bos': _N('strait', False, 'تنگه بسفر', 'Bosphorus Strait', 'İstanbul Boğazı'),
    'dar': _N('strait', False, 'تنگه داردانل', 'Dardanelles Strait', 'Çanakkale Boğazı'),
    'dan': _N('strait', False, 'تنگه دانمارک', 'Danish Straits', 'Danimarka Boğazları'),
    'hor': _N('strait', False, 'تنگه هرمز', 'Strait of Hormuz', 'Hürmüz Boğazı'),
    'bab': _N('strait', False, 'تنگه باب‌المندب', 'Bab-el-Mandeb Strait', 'Bab-ül Mendeb Boğazı'),
    'mal': _N('strait', False, 'تنگه مالاکا', 'Strait of Malacca', 'Malakka Boğazı'),
    'tsu': _N('strait', False, 'تنگه تسوشیما', 'Tsushima Strait', 'Tsushima Boğazı'),
    'ber': _N('strait', False, 'تنگه برینگ', 'Bering Strait', 'Bering Boğazı'),
    'sun': _N('strait', False, 'تنگه سوندا', 'Sunda Strait', 'Sunda Boğazı'),
    'lom': _N('strait', False, 'تنگه لومبوک', 'Lombok Strait', 'Lombok Boğazı'),
    'mag': _N('strait', False, 'تنگه ماژلان', 'Strait of Magellan', 'Macellan Boğazı'),
    'moz': _N('strait', False, 'کانال موزامبیک', 'Mozambique Channel', 'Mozambik Kanalı'),
    # کانال‌ها (عوارض‌دار)
    'sue': _N('canal', False, 'کانال سوئز', 'Suez Canal', 'Süveyş Kanalı'),
    'pan': _N('canal', False, 'کانال پاناما', 'Panama Canal', 'Panama Kanalı'),
    'kie': _N('canal', False, 'کانال کیل', 'Kiel Canal', 'Kiel Kanalı'),
    # دماغه‌های آزاد (دورهای طولانی)
    'cgh': _N('cape', False, 'دماغه امید نیک', 'Cape of Good Hope', 'Ümit Burnu'),
    'chn': _N('cape', False, 'دماغه هورن', 'Cape Horn', 'Horn Burnu'),
}

# یال‌های بدون جهت: (a, b, وزن در واحد فاصله)
SEA_EDGES = [
    # اروپا / اطلس
    ('nat', 'nor', 2), ('nor', 'dan', 2), ('dan', 'bal', 1),
    ('nor', 'kie', 1), ('kie', 'bal', 1),
    ('nat', 'gib', 2), ('gib', 'med', 1),
    # مدیترانه / دریای سیاه
    ('med', 'dar', 2), ('dar', 'mar', 1), ('mar', 'bos', 1), ('bos', 'bla', 1),
    # کریدور سوئز
    ('med', 'sue', 2), ('sue', 'red', 1), ('red', 'bab', 2), ('bab', 'ade', 1),
    ('ade', 'oma', 2), ('oma', 'hor', 1), ('hor', 'per', 1), ('oma', 'ind', 2),
    # آفریقا / دماغه‌ها
    ('nat', 'gui', 4), ('gui', 'sat', 2), ('nat', 'sat', 5),
    ('sat', 'cgh', 5), ('cgh', 'ind', 5),
    ('cgh', 'moz', 2), ('moz', 'ind', 2),
    # آمریکاها
    ('nat', 'car', 4), ('car', 'gmx', 1), ('car', 'pan', 1), ('pan', 'spa', 2),
    ('sat', 'mag', 5), ('mag', 'spa', 3), ('sat', 'chn', 6), ('chn', 'spa', 4),
    # اقیانوس هند -> شرق آسیا
    ('ind', 'mal', 3), ('mal', 'scs', 1), ('ind', 'sun', 4), ('sun', 'scs', 2),
    ('ind', 'lom', 4), ('lom', 'phi', 3),
    # شرق آسیا
    ('scs', 'ecs', 2), ('ecs', 'yel', 1), ('ecs', 'tsu', 1), ('tsu', 'jap', 1),
    ('jap', 'npa', 2), ('scs', 'phi', 2), ('ecs', 'phi', 2), ('phi', 'npa', 2),
    ('phi', 'spa', 3),
    # آرام / منجمد شمالی
    ('npa', 'spa', 5), ('npa', 'ber', 4), ('ber', 'arc', 1),
    ('arc', 'nat', 5), ('arc', 'nor', 4),
]

LAND_NODES = {
    # مناطق
    'ibe': _N('region', True, 'ایبریا', 'Iberia', 'İberya'),
    'weu': _N('region', True, 'اروپای غربی', 'Western Europe', 'Batı Avrupa'),
    'eeu': _N('region', True, 'اروپای شرقی', 'Eastern Europe', 'Doğu Avrupa'),
    'ana': _N('region', True, 'آناتولی', 'Anatolia', 'Anadolu'),
    'lev': _N('region', True, 'شام', 'Levant', 'Levant'),
    'egy': _N('region', True, 'مصر', 'Egypt', 'Mısır'),
    'naf': _N('region', True, 'شمال آفریقا', 'North Africa', 'Kuzey Afrika'),
    'waf': _N('region', True, 'غرب آفریقا', 'West Africa', 'Batı Afrika'),
    'eaf': _N('region', True, 'شرق آفریقا', 'East Africa', 'Doğu Afrika'),
    'ara': _N('region', True, 'عربستان', 'Arabia', 'Arabistan'),
    'prs': _N('region', True, 'پارس', 'Persia', 'Pers'),
    'cas': _N('region', True, 'آسیای میانه', 'Central Asia', 'Orta Asya'),
    'hnd': _N('region', True, 'هند', 'India', 'Hindistan'),
    'chi': _N('region', True, 'چین', 'China', 'Çin'),
    'sta': _N('region', True, 'آسیای جنوب شرقی', 'Southeast Asia', 'Güneydoğu Asya'),
    # گذرگاه‌های عوارض‌دار
    'sin': _N('pass', False, 'گذرگاه سینا', 'Sinai Crossing', 'Sina Geçidi'),
    'sah': _N('pass', False, 'مسیر صحرا', 'Sahara Route', 'Sahra Yolu'),
    'cau': _N('pass', False, 'دروازه قفقاز', 'Caucasus Gates', 'Kafkas Kapıları'),
    'zag': _N('pass', False, 'دروازه زاگرس', 'Zagros Gates', 'Zagros Kapıları'),
    'pam': _N('pass', False, 'گذرگاه پامیر', 'Pamir Passes', 'Pamir Geçitleri'),
    'khy': _N('pass', False, 'گذرگاه خیبر', 'Khyber Pass', 'Hayber Geçidi'),
}

LAND_EDGES = [
    ('ibe', 'weu', 2), ('weu', 'eeu', 2), ('eeu', 'ana', 2), ('ana', 'lev', 2),
    ('lev', 'sin', 1), ('sin', 'egy', 1), ('lev', 'ara', 2), ('ara', 'egy', 2),
    ('egy', 'naf', 2), ('naf', 'ibe', 2), ('naf', 'sah', 2), ('sah', 'waf', 2),
    ('egy', 'eaf', 3), ('eaf', 'ara', 2),
    ('eeu', 'cau', 1), ('cau', 'prs', 2), ('lev', 'zag', 1), ('zag', 'prs', 1),
    ('ana', 'prs', 4),
    ('prs', 'cas', 2), ('eeu', 'cas', 4),
    ('cas', 'pam', 1), ('pam', 'chi', 3), ('cas', 'chi', 6),
    ('prs', 'khy', 1), ('khy', 'hnd', 1), ('prs', 'hnd', 4),
    ('hnd', 'sta', 3), ('sta', 'chi', 3), ('hnd', 'chi', 5),
]

SEED = {'sea': (SEA_NODES, SEA_EDGES), 'land': (LAND_NODES, LAND_EDGES)}


# ---------------------------------------------------------------------------
# راه‌اندازی
# ---------------------------------------------------------------------------


def init(conn):
    """ساخت جداول، seed کردن دنیای عرضه‌شده، و پاک کردن کش کهنه."""
    global _conn
    _conn = conn
    _migrate()
    _seed()
    _invalidate()


def _migrate():
    with _lock:
        _conn.execute('''CREATE TABLE IF NOT EXISTS trade_nodes (
            id       TEXT PRIMARY KEY,
            mode     TEXT NOT NULL,
            kind     TEXT NOT NULL,
            home     INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0,
            builtin  INTEGER NOT NULL DEFAULT 0
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS trade_node_labels (
            node_id TEXT NOT NULL,
            lang    TEXT NOT NULL,
            label   TEXT NOT NULL,
            PRIMARY KEY (node_id, lang)
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS trade_edges (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            mode    TEXT NOT NULL,
            a       TEXT NOT NULL,
            b       TEXT NOT NULL,
            units   INTEGER NOT NULL,
            minutes INTEGER NOT NULL DEFAULT 0,
            UNIQUE (mode, a, b)
        )''')
        _conn.execute('''CREATE TABLE IF NOT EXISTS trade_map_removed (
            kind TEXT NOT NULL,
            ref  TEXT NOT NULL,
            PRIMARY KEY (kind, ref)
        )''')
        _conn.commit()


def _seed():
    """درج دنیای عرضه‌شده، پرش از چیزهایی که ادمین قبلاً حذف کرده."""
    with _lock:
        gone = {(row[0], row[1]) for row in
                _conn.execute("SELECT kind, ref FROM trade_map_removed").fetchall()}
        nodes, labels, edges = [], [], []
        for mode, (seed_nodes, seed_edges) in SEED.items():
            for position, (nid, node) in enumerate(seed_nodes.items(), start=1):
                if ('node', nid) in gone:
                    continue
                nodes.append((nid, mode, node['kind'], 1 if node['home'] else 0, position * 10, 1))
                labels.extend((nid, lang, text) for lang, text in node['names'].items())
            for a, b, units in seed_edges:
                if ('edge', _edge_ref(mode, a, b)) in gone:
                    continue
                if ('node', a) in gone or ('node', b) in gone:
                    continue
                edges.append((mode,) + _pair(a, b) + (units, 0))
        _conn.executemany(
            "INSERT OR IGNORE INTO trade_nodes (id, mode, kind, home, position, builtin) "
            "VALUES (?, ?, ?, ?, ?, ?)", nodes)
        _conn.executemany(
            "INSERT OR IGNORE INTO trade_node_labels (node_id, lang, label) VALUES (?, ?, ?)",
            labels)
        _conn.executemany(
            "INSERT OR IGNORE INTO trade_edges (mode, a, b, units, minutes) VALUES (?, ?, ?, ?, ?)",
            edges)
        _conn.commit()


# ---------------------------------------------------------------------------
# ابزارهای کمکی
# ---------------------------------------------------------------------------


def _q(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _exec(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur


def _pair(a, b):
    """یال‌ها بدون جهت‌اند، پس همیشه به ترتیب متعارف ذخیره می‌شوند."""
    return (a, b) if a <= b else (b, a)


def _edge_ref(mode, a, b):
    return '%s:%s:%s' % ((mode,) + _pair(a, b))


def _tombstone(kind, ref):
    _exec("INSERT OR IGNORE INTO trade_map_removed (kind, ref) VALUES (?, ?)", (kind, ref))


def _invalidate():
    """حذف lookup های مشتق‌شده. هر mutator با این تمام می‌شود."""
    with _lock:
        _cache.clear()


def _cached(key, build):
    """Memoize یک lookup مشتق‌شده، با نگه‌داشتن قفل در طول build و store."""
    with _lock:
        if key not in _cache:
            _cache[key] = build()
        return _cache[key]


def set_node_guard(fn):
    """ثبت آن‌چه تعیین می‌کند یک گره برای حذف خیلی شلوغ است."""
    global _node_guard
    _node_guard = fn


def nodes_in_transit():
    if _node_guard is None:
        return frozenset()
    try:
        return frozenset(_node_guard())
    except Exception:
        raise MapError('guard_unavailable')


def _check_id(nid):
    if not NODE_ID_RE.match(nid or ''):
        raise MapError('bad_id')
    return nid


def check_new_id(nid):
    """خطای MapError مگر آن‌که nid شناسه‌ای قابل استفاده برای گره جدید باشد."""
    _check_id(nid)
    if _q("SELECT 1 FROM trade_nodes WHERE id=?", (nid,)):
        raise MapError('id_taken')
    return nid


# ---------------------------------------------------------------------------
# خواندن نقشه
# ---------------------------------------------------------------------------


def nodes(mode=None):
    """تمام شناسه‌های گره، اختیاری فیلتر شده بر اساس mode."""
    if mode is None:
        rows = _q("SELECT id FROM trade_nodes ORDER BY mode, position")
    else:
        if mode not in MODES:
            raise MapError('bad_mode')
        rows = _q("SELECT id FROM trade_nodes WHERE mode=? ORDER BY position", (mode,))
    return tuple(r['id'] for r in rows)


def node(mode, nid):
    if mode not in MODES:
        raise MapError('bad_mode')
    rows = _q("SELECT * FROM trade_nodes WHERE id=? AND mode=?", (nid, mode))
    if not rows:
        raise MapError('unknown_node')
    return rows[0]


def mode_of(nid):
    rows = _q("SELECT mode FROM trade_nodes WHERE id=?", (nid,))
    return rows[0]['mode'] if rows else None


def kind_of(nid):
    rows = _q("SELECT kind FROM trade_nodes WHERE id=?", (nid,))
    return rows[0]['kind'] if rows else None


def labels(nid):
    return {r['lang']: r['label'] for r in
            _q("SELECT lang, label FROM trade_node_labels WHERE node_id=?", (nid,))}


def name(nid, lang='fa'):
    rows = _q("SELECT label FROM trade_node_labels WHERE node_id=? AND lang=?", (nid, lang))
    if rows:
        return rows[0]['label']
    rows = _q("SELECT label FROM trade_node_labels WHERE node_id=? AND lang='en'", (nid,))
    return rows[0]['label'] if rows else nid


def chokepoints(mode=None):
    """گره‌هایی که عوارض می‌گیرند — تنگه، کانال، گذرگاه."""
    placeholders = ','.join('?' * len(CHOKEPOINT_KINDS))
    sql = f"SELECT id FROM trade_nodes WHERE kind IN ({placeholders})"
    params = list(CHOKEPOINT_KINDS)
    if mode:
        sql += " AND mode=?"
        params.append(mode)
    sql += " ORDER BY mode, position"
    return tuple(r['id'] for r in _q(sql, params))


def _edges(mode):
    if mode not in MODES:
        raise MapError('bad_mode')
    return _q("SELECT a, b, units, minutes FROM trade_edges WHERE mode=? ORDER BY id", (mode,))


def edges(mode):
    """(a, b, units, minutes) برای هر یال."""
    return tuple((r['a'], r['b'], r['units'], r['minutes']) for r in _edges(mode))


def edges_of(nid):
    """تمام یال‌هایی که به یک گره وصل هستند."""
    return _q("SELECT a, b, units, minutes FROM trade_edges WHERE a=? OR b=?", (nid, nid))


def leg(mode, a, b):
    """(units, minutes) برای یال بین دو گره، یا None."""
    if mode not in MODES:
        raise MapError('bad_mode')
    a, b = _pair(a, b)
    rows = _q("SELECT units, minutes FROM trade_edges WHERE mode=? AND a=? AND b=?",
              (mode, a, b))
    return (rows[0]['units'], rows[0]['minutes']) if rows else None


def adjacency(mode):
    """دیکشنری: nid -> [(همسایه, واحد), ...]"""
    def build():
        adj = {nid: [] for nid in nodes(mode)}
        for a, b, units, _minutes in edges(mode):
            adj[a].append((b, units))
            adj[b].append((a, units))
        return adj
    return _cached('adj_' + mode, build)


# ---------------------------------------------------------------------------
# نوشتن نقشه
# ---------------------------------------------------------------------------


def set_labels(nid, labels_dict):
    with _lock:
        for lang, text in labels_dict.items():
            if lang not in LANGS:
                continue
            _conn.execute("INSERT OR REPLACE INTO trade_node_labels (node_id, lang, label) "
                          "VALUES (?, ?, ?)", (nid, lang, text))
        _conn.commit()
    _invalidate()


def set_kind(nid, kind):
    mode = mode_of(nid)
    if mode is None:
        raise MapError('unknown_node')
    if kind not in KINDS[mode]:
        raise MapError('bad_kind')
    _exec("UPDATE trade_nodes SET kind=? WHERE id=?", (kind, nid))
    _invalidate()


def set_home(nid, value):
    _exec("UPDATE trade_nodes SET home=? WHERE id=?", (1 if value else 0, nid))
    _invalidate()


def set_edge(mode, a, b, units=None, minutes=None):
    if mode not in MODES:
        raise MapError('bad_mode')
    a, b = _pair(a, b)
    if a == b:
        raise MapError('self_edge')
    for nid in (a, b):
        if not _q("SELECT 1 FROM trade_nodes WHERE id=? AND mode=?", (nid, mode)):
            raise MapError('unknown_node')
    current = leg(mode, a, b)
    new_units = units if units is not None else (current[0] if current else 1)
    new_minutes = minutes if minutes is not None else (current[1] if current else 0)
    if new_units < 1:
        raise MapError('bad_units')
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO trade_edges (mode, a, b, units, minutes) "
                      "VALUES (?, ?, ?, ?, ?)", (mode, a, b, int(new_units), int(new_minutes)))
        _conn.commit()
    _invalidate()


def add_node(mode, nid, kind, home=False, names=None, position=None):
    if mode not in MODES:
        raise MapError('bad_mode')
    check_new_id(nid)
    if kind not in KINDS[mode]:
        raise MapError('bad_kind')
    if position is None:
        rows = _q("SELECT MAX(position) AS p FROM trade_nodes WHERE mode=?", (mode,))
        position = ((rows[0]['p'] or 0) + 10) if rows else 10
    with _lock:
        _conn.execute("INSERT INTO trade_nodes (id, mode, kind, home, position, builtin) "
                      "VALUES (?, ?, ?, ?, ?, 0)",
                      (nid, mode, kind, 1 if home else 0, position))
        for lang, text in (names or {}).items():
            if lang in LANGS:
                _conn.execute("INSERT INTO trade_node_labels (node_id, lang, label) "
                              "VALUES (?, ?, ?)", (nid, lang, text))
        _conn.commit()
    _invalidate()


def remove_node(nid):
    """حذف یک گره و تمام یال‌هایش، با tombstone برای گره‌های builtin."""
    mode = mode_of(nid)
    if mode is None:
        raise MapError('unknown_node')
    busy = nodes_in_transit()
    if nid in busy:
        raise MapError('in_transit')
    with _lock:
        _conn.execute("DELETE FROM trade_edges WHERE a=? OR b=?", (nid, nid))
        _conn.execute("DELETE FROM trade_node_labels WHERE node_id=?", (nid,))
        rows = _q("SELECT builtin FROM trade_nodes WHERE id=?", (nid,))
        builtin = bool(rows and rows[0]['builtin'])
        _conn.execute("DELETE FROM trade_nodes WHERE id=?", (nid,))
        if builtin:
            _tombstone('node', nid)
        _conn.commit()
    _invalidate()


def remove_edge(mode, a, b):
    if mode not in MODES:
        raise MapError('bad_mode')
    a, b = _pair(a, b)
    if leg(mode, a, b) is None:
        raise MapError('unknown_edge')
    with _lock:
        rows = _q("SELECT 1 FROM trade_edges WHERE mode=? AND a=? AND b=? AND "
                  "(SELECT COUNT(*) FROM trade_edges WHERE mode=? AND a=? AND b=?) >= 1",
                  (mode, a, b, mode, a, b))
        _conn.execute("DELETE FROM trade_edges WHERE mode=? AND a=? AND b=?", (mode, a, b))
        _tombstone('edge', _edge_ref(mode, a, b))
        _conn.commit()
    _invalidate()
