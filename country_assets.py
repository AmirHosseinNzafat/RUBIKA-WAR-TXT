# -*- coding: utf-8 -*-
"""override های هر کشور روی کاتالوگ دارایی‌ها.

کاتالوگ می‌گوید در بازی چه وجود دارد. این فایل می‌گوید *برای یک کشور خاص*
چه وجود دارد، چون این دو همیشه یکی نیستند: یک کشور محصور در خشکی
کارخانه کشتی‌سازی ندارد، یک کشور غیرنظامی ارتش ندارد و...

    country_assets   یک ردیف برای هر (کشور، نوع) که ادمین override کرده

دو سوئیچ مستقل:

    hidden   این نوع اصلاً جزو این کشور نیست. از پیام وضعیت و منوی ارتقا
             ناپدید می‌شود، ساختمان‌هایش تولید را متوقف می‌کنند. عدد ذخیره‌شده
             دست نمی‌خورد، پس برگرداندن نوع، کشور را دقیقاً به حالت قبل برمی‌گرداند.

    paused   ساختمانی که این کشور دارد ولی کار نمی‌کند. سطحش دست نمی‌خورد
             و قابل ارتقا هست؛ فقط در چرخه هفتگی چیزی تولید نمی‌کند.

هیچ ردیفی برای کشوری که override ندارد نوشته نمی‌شود، پس حالت عادی
هیچ ردیفی هزینه ندارد و نبود ردیف یعنی «طبق کاتالوگ».

نسخه روبیکا — بدون وابستگی به تلگرام.
"""

import threading

import asset_catalog as catalog

_conn = None
_lock = threading.RLock()


def attach(conn):
    """اتصال به دیتابیس و ساخت جدول در صورت نیاز."""
    global _conn
    _conn = conn
    _migrate()


def _migrate():
    with _lock:
        _conn.execute('''CREATE TABLE IF NOT EXISTS country_assets (
            group_id INTEGER NOT NULL,
            key      TEXT NOT NULL,
            hidden   INTEGER NOT NULL DEFAULT 0,
            paused   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (group_id, key)
        )''')
        _conn.commit()


# ---------------------------------------------------------------------------
# خواندن
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


def hidden_keys(group_id):
    """نوع‌هایی که این کشور ندارد، هر چه کاتالوگ بگوید."""
    return frozenset(row['key'] for row in
                     _q("SELECT key FROM country_assets WHERE group_id=? AND hidden=1",
                        (group_id,)))


def paused_keys(group_id):
    """ساختمان‌هایی که این کشور دارد ولی خاموش است."""
    return frozenset(row['key'] for row in
                     _q("SELECT key FROM country_assets WHERE group_id=? AND paused=1",
                        (group_id,)))


def is_hidden(group_id, key):
    return key in hidden_keys(group_id)


def is_paused(group_id, key):
    """وقتی این ساختمان اینجا چیزی تولید نمی‌کند — خاموش، یا رفته."""
    row = _row(group_id, key)
    return bool(row and (row['paused'] or row['hidden']))


def _row(group_id, key):
    rows = _q("SELECT hidden, paused FROM country_assets WHERE group_id=? AND key=?",
              (group_id, key))
    return rows[0] if rows else None


def keys_for(group_id, kind=None):
    """کلیدهای کاتالوگ منهای آن‌هایی که این کشور ندارد."""
    gone = hidden_keys(group_id)
    return tuple(key for key in catalog.keys(kind) if key not in gone)


def production_for(group_id):
    """(building, produces, flat_output) که این کشور واقعاً اجرا می‌کند.

    ساختمانی که اینجا مخفی یا متوقف باشد حذف می‌شود، و همچنین آن‌که
    محصولش را این کشور ندارد.
    """
    gone = hidden_keys(group_id)
    off = paused_keys(group_id)
    return [(building, produces, output)
            for building, produces, output in catalog.production()
            if building not in gone and building not in off and produces not in gone]


def overrides(group_id):
    """(تعداد hidden، تعداد paused) برای صفحه‌ای که باید بگوید چقدر تنظیم شده."""
    rows = _q("SELECT hidden, paused FROM country_assets WHERE group_id=?", (group_id,))
    return (sum(1 for r in rows if r['hidden']), sum(1 for r in rows if r['paused']))


# ---------------------------------------------------------------------------
# نوشتن
# ---------------------------------------------------------------------------


def _set(group_id, key, field, value):
    if field not in ('hidden', 'paused'):
        raise ValueError(field)
    with _lock:
        _conn.execute(
            "INSERT INTO country_assets (group_id, key, hidden, paused) VALUES (?, ?, 0, 0) "
            "ON CONFLICT(group_id, key) DO NOTHING", (group_id, key))
        _conn.execute(f"UPDATE country_assets SET {field}=? WHERE group_id=? AND key=?",
                      (1 if value else 0, group_id, key))
        # ردیفی که می‌گوید «هیچ override ای نیست» مساوی نبود ردیف است
        _conn.execute("DELETE FROM country_assets WHERE group_id=? AND key=? "
                      "AND hidden=0 AND paused=0", (group_id, key))
        _conn.commit()


def set_hidden(group_id, key, value):
    _set(group_id, key, 'hidden', value)


def set_paused(group_id, key, value):
    _set(group_id, key, 'paused', value)


def clear(group_id):
    """کاتالوگ را دقیقاً همان‌طور که هست به کشور برگردان."""
    rows = _q("SELECT COUNT(*) AS n FROM country_assets WHERE group_id=?", (group_id,))
    _exec("DELETE FROM country_assets WHERE group_id=?", (group_id,))
    return rows[0]['n'] if rows else 0


def forget(key):
    """حذف override همه کشورها برای نوعی که دیگر وجود ندارد."""
    _exec("DELETE FROM country_assets WHERE key=?", (key,))


def forget_group(group_id):
    _exec("DELETE FROM country_assets WHERE group_id=?", (group_id,))
