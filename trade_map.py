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

نسخه روبیکا — کاملاً مستقل از کتابخانه پیام‌رسان.
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
        # بدون این، حذف چیزی که بازی با آن عرضه شد، خودش را در ری‌استارت بعدی برمی‌گرداند.
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
    """حذف lookup های مشتق‌شده. هر mutator با این تمام می‌شود.

    خواننده‌ها از طریق nodes()/edges()/adjacency() می‌گذرند که اینجا
    memoize می‌کنند نه در caller، پس این تنها جایی است که نقشه کهنه
    می‌تواند پنهان شود.
    """
    with _lock:
        _cache.clear()


def _cached(key, build):
    """Memoize یک lookup مشتق‌شده، با نگه‌داشتن قفل در طول build و store.

    thread ticker مربوط به trade_system نقشه را می‌خواند در حالی که ادمین
    آن را ویرایش می‌کند. interleaving خطرناک خواندن پاره نیست — بلکه خواننده‌ای
    است که مقداری می‌سازد، _invalidate() زیرش اجرا می‌شود، و بعد مقدار
    کهنه‌اش را در کش می‌نویسد، جایی که تا ویرایش بعدی می‌ماند. ساخت زیر
    همان قفلی که mutator ها می‌گیرند این را غیرممکن می‌کند. قفل reentrant
    است و _q() از قبل آن را می‌گیرد، پس build می‌تواند آزادانه query بزند.
    """
    with _lock:
        if key not in _cache:
            _cache[key] = build()
        return _cache[key]


def set_node_guard(fn):
    """ثبت آن‌چه تعیین می‌کند یک گره برای حذف خیلی شلوغ است.

    fn شناسه گره‌هایی را برمی‌گرداند که یک تجارت در جریان هنوز باید از آن‌ها
    عبور کند. حذف یکی، آن محموله را در میانه مسیر رها می‌کند.
    """
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
        raise MapError('exists')
    return nid


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------


def nodes(mode):
    """{node id: {'kind', 'home', 'names'}} برای یک mode، به ترتیب لیست ادمین.

    دقیقاً شکل literal ای که قبلاً در trade_system بود، پس کد routing آن را
    همان‌طور که همیشه می‌خواند، می‌خواند.
    """
    if mode not in MODES:
        raise MapError('bad_mode')

    def build():
        labels = {}
        for row in _q("SELECT node_id, lang, label FROM trade_node_labels"):
            labels.setdefault(row['node_id'], {})[row['lang']] = row['label']
        out = {}
        for row in _q("SELECT id, kind, home FROM trade_nodes WHERE mode=? ORDER BY position, id",
                      (mode,)):
            out[row['id']] = {'kind': row['kind'], 'home': bool(row['home']),
                              'names': labels.get(row['id'], {})}
        return out

    return _cached(('nodes', mode), build)


def node(mode, nid):
    return nodes(mode).get(nid)


def mode_of(nid):
    rows = _q("SELECT mode FROM trade_nodes WHERE id=?", (nid,))
    return rows[0]['mode'] if rows else None


def name(nid, lang):
    """نام نمایشی یک گره، با fallback به زبان دیگر و در نهایت id آن."""
    rows = _q("SELECT label FROM trade_node_labels WHERE node_id=? AND lang=?", (nid, lang))
    if rows:
        return rows[0]['label']
    rows = _q("SELECT label FROM trade_node_labels WHERE node_id=? LIMIT 1", (nid,))
    return rows[0]['label'] if rows else nid


def labels(nid):
    return {row['lang']: row['label']
            for row in _q("SELECT lang, label FROM trade_node_labels WHERE node_id=?", (nid,))}


def edges(mode):
    """[(a, b, units, minutes)] برای یک mode."""
    if mode not in MODES:
        raise MapError('bad_mode')
    return _cached(('edges', mode), lambda: [
        (row['a'], row['b'], row['units'], row['minutes'])
        for row in _q("SELECT a, b, units, minutes FROM trade_edges WHERE mode=? "
                      "ORDER BY a, b", (mode,))])


def edge(mode, a, b):
    a, b = _pair(a, b)
    rows = _q("SELECT a, b, units, minutes FROM trade_edges WHERE mode=? AND a=? AND b=?",
              (mode, a, b))
    return rows[0] if rows else None


def edges_of(nid):
    """هر یالی که یک گره را لمس می‌کند، از هر سر که باشد."""
    return _q("SELECT mode, a, b, units, minutes FROM trade_edges WHERE a=? OR b=? ORDER BY a, b",
              (nid, nid))


def adjacency(mode):
    """{node id: [(neighbour, units)]}، هر گره حتی بدون یال حاضر است."""
    def build():
        out = {nid: [] for nid in nodes(mode)}
        for a, b, units, _minutes in edges(mode):
            if a in out and b in out:
                out[a].append((b, units))
                out[b].append((a, units))
        return out

    return _cached(('adj', mode), build)


def leg(mode, a, b):
    """(units, minutes) برای یک پای، یا None وقتی دو سر وصل نیستند."""
    legs = _cached(('legs', mode), lambda: {frozenset((x, y)): (units, minutes)
                                            for x, y, units, minutes in edges(mode)})
    return legs.get(frozenset((a, b)))


def leg_minutes(mode, a, b, per_unit):
    """چقدر یک پای طول می‌کشد: override وقتی تنظیم شده، وگرنه units x per_unit."""
    found = leg(mode, a, b)
    if found is None:
        return 0
    units, minutes = found
    return minutes if minutes > 0 else units * per_unit


def chokepoints():
    """هر گرهی که می‌توان در آن عوارض گرفت، اول دریا بعد خشکی."""
    out = []
    for mode in MODES:
        out += [nid for nid, n in nodes(mode).items() if n['kind'] in CHOKEPOINT_KINDS]
    return out


def home_nodes(mode):
    return [nid for nid, n in nodes(mode).items() if n['home']]


# ---------------------------------------------------------------------------
# نوشتن — گره‌ها
# ---------------------------------------------------------------------------


def add_node(mode, nid, kind, home, label_map):
    if mode not in MODES:
        raise MapError('bad_mode')
    _check_id(nid)
    if kind not in KINDS[mode]:
        raise MapError('bad_kind')
    if _q("SELECT 1 FROM trade_nodes WHERE id=?", (nid,)):
        raise MapError('exists')
    with _lock:
        rows = _q("SELECT COALESCE(MAX(position), 0) AS p FROM trade_nodes WHERE mode=?", (mode,))
        position = (rows[0]['p'] if rows else 0) + 10
        _conn.execute("INSERT INTO trade_nodes (id, mode, kind, home, position, builtin) "
                      "VALUES (?, ?, ?, ?, ?, 0)",
                      (nid, mode, kind, 1 if home else 0, position))
        # گره‌ای که یک بار حذف و دوباره اضافه شده باید این بار بماند.
        _conn.execute("DELETE FROM trade_map_removed WHERE kind='node' AND ref=?", (nid,))
        _conn.commit()
    set_labels(nid, label_map)
    _invalidate()
    return nid


def set_labels(nid, label_map):
    _require_node(nid)
    rows = [(nid, lang, text) for lang, text in label_map.items() if text]
    if not rows:
        return
    with _lock:
        _conn.executemany(
            "INSERT OR REPLACE INTO trade_node_labels (node_id, lang, label) VALUES (?, ?, ?)",
            rows)
        _conn.commit()
    _invalidate()


def set_kind(nid, kind):
    row = _require_node(nid)
    if kind not in KINDS[row['mode']]:
        raise MapError('bad_kind')
    _exec("UPDATE trade_nodes SET kind=? WHERE id=?", (kind, nid))
    _invalidate()


def set_home(nid, home):
    _require_node(nid)
    _exec("UPDATE trade_nodes SET home=? WHERE id=?", (1 if home else 0, nid))
    _invalidate()


def remove_node(nid):
    """حذف یک گره، برچسب‌هایش، یال‌هایش و هر ارجاع به آن.

    تا وقتی یک تجارت در جریان هنوز باید از آن عبور کند، رد می‌کند — ticker
    آن مسیر ذخیره‌شده را پای به پای می‌پیماید و هر گره را نام می‌برد.

    شناسه گره از سه جای بیرون این جدول‌های ما ارجاع داده می‌شود، و ارجاع
    آویزان بدتر از گره گمشده است: کشوری که home_sea اش به هیچ اشاره می‌کند
    به سادگی نمی‌تواند تجارت کند، بدون خطایی که توضیح دهد چرا. پس اینجا
    پاک می‌شوند، در همان تراکنش حذف.
    """
    _require_node(nid)
    if nid in nodes_in_transit():
        raise MapError('in_transit')
    with _lock:
        _conn.execute("DELETE FROM trade_edges WHERE a=? OR b=?", (nid, nid))
        _conn.execute("DELETE FROM trade_node_labels WHERE node_id=?", (nid,))
        _conn.execute("DELETE FROM trade_nodes WHERE id=?", (nid,))
        for statement, params in (
                ("UPDATE users SET home_sea='' WHERE home_sea=?", (nid,)),
                ("UPDATE users SET home_land='' WHERE home_land=?", (nid,)),
                ("DELETE FROM chokepoint_owners WHERE node_id=?", (nid,)),
                # صفر شده نه حذف: trade_config به CONFIG_DEFAULTS عرضه‌شده
                # برمی‌گردد، پس ردیف حذف‌شده عوارض قدیمی را برمی‌گرداند —
                # و در ری‌استارت بعدی دوباره seed می‌شود.
                ("INSERT OR REPLACE INTO trade_config (key, value) VALUES (?, 0)",
                 ('toll_' + nid,))):
            try:
                _conn.execute(statement, params)
            except sqlite3.OperationalError:
                # آن جدول‌ها به trade_system تعلق دارند. وقتی نقشه تنها
                # استفاده می‌شود، آن‌ها غایب‌اند، و چیزی برای پاک کردن نیست.
                pass
        _conn.commit()
    _tombstone('node', nid)
    _invalidate()


# ---------------------------------------------------------------------------
# نوشتن — یال‌ها
# ---------------------------------------------------------------------------


def add_edge(mode, a, b, units, minutes=0):
    if mode not in MODES:
        raise MapError('bad_mode')
    if a == b:
        raise MapError('self_edge')
    for nid in (a, b):
        row = _require_node(nid)
        if row['mode'] != mode:
            raise MapError('mode_mismatch')
    if int(units) <= 0:
        raise MapError('bad_units')
    a, b = _pair(a, b)
    if edge(mode, a, b):
        raise MapError('edge_exists')
    _exec("INSERT INTO trade_edges (mode, a, b, units, minutes) VALUES (?, ?, ?, ?, ?)",
          (mode, a, b, int(units), max(0, int(minutes))))
    _exec("DELETE FROM trade_map_removed WHERE kind='edge' AND ref=?", (_edge_ref(mode, a, b),))
    _invalidate()


def set_edge(mode, a, b, units=None, minutes=None):
    """یک پای را دوباره تنظیم کن. units کارمزد و routing را می‌راند، minutes زمانش را override می‌کند."""
    a, b = _pair(a, b)
    row = edge(mode, a, b)
    if row is None:
        raise MapError('no_edge')
    if units is not None:
        if int(units) <= 0:
            raise MapError('bad_units')
        _exec("UPDATE trade_edges SET units=? WHERE mode=? AND a=? AND b=?",
              (int(units), mode, a, b))
    if minutes is not None:
        _exec("UPDATE trade_edges SET minutes=? WHERE mode=? AND a=? AND b=?",
              (max(0, int(minutes)), mode, a, b))
    _invalidate()


def remove_edge(mode, a, b):
    a, b = _pair(a, b)
    if edge(mode, a, b) is None:
        raise MapError('no_edge')
    _exec("DELETE FROM trade_edges WHERE mode=? AND a=? AND b=?", (mode, a, b))
    _tombstone('edge', _edge_ref(mode, a, b))
    _invalidate()


def _require_node(nid):
    rows = _q("SELECT id, mode, kind, home, builtin FROM trade_nodes WHERE id=?", (nid,))
    if not rows:
        raise MapError('unknown_node')
    return rows[0]
