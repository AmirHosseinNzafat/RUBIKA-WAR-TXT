# -*- coding: utf-8 -*-
"""پیکربندی راه‌اندازی ربات روبیکا - نسخه سازگار با rubpy"""

import json
import os
import re

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_config.json')

# قواعد اعتبارسنجی بر اساس نمونه‌های ارائه‌شده
# توکن: 64 کاراکتر حروف بزرگ
TOKEN_RE = re.compile(r'^[A-Z]{64}$')
# GUID: g0/u0/c0 + 32 کاراکتر هگز
GUID_RE = re.compile(r'^[guc]0[0-9a-f]{32}$')


class ConfigError(ValueError):
    """خطای اعتبارسنجی پیکربندی"""


def _clean_token(raw):
    """اعتبارسنجی توکن ربات روبیکا (نمونه: CBAEJE0SNEEOIVHMEQPLHSXHKVHWUIZWABFUDUUOVLMQPQGLYFDVRIZKJJYSKEBW)"""
    value = str(raw).strip()
    if not value:
        raise ConfigError('empty')
    if not TOKEN_RE.match(value):
        raise ConfigError('shape')
    return value


def _clean_guid(raw):
    """اعتبارسنجی GUID روبیکا (نمونه‌ها: g0GdOav08b49697ae345813d086390c7 / c0DdIqc057ca4cadf20faa354de6075a / u0Hlb9H0510a64cd6029655af31e2c16)"""
    value = str(raw).strip()
    if not value:
        raise ConfigError('empty')
    if not GUID_RE.match(value):
        raise ConfigError('shape')
    return value


def _clean_optional_guid(raw):
    """GUID اختیاری — خالی مجاز است، در این صورت از مقدار پیش‌فرض استفاده می‌شود"""
    value = str(raw).strip()
    if not value:
        return ''
    return _clean_guid(value)


FIELDS = (
    ('token', 'RUBIKA_BOT_TOKEN', _clean_token),
    ('admin_id', 'RUBIKA_ADMIN_ID', _clean_guid),      # GUID کاربر ادمین
    ('channel_id', 'RUBIKA_CHANNEL_ID', _clean_guid),  # GUID کانال اخبار
    ('war_channel_id', 'RUBIKA_WAR_CHANNEL_ID', _clean_optional_guid),  # کانال جنگ اختیاری
)

PROMPTS = {
    'fa': {
        'intro': "\n=== پیکربندی ربات روبیکا ===\n"
                 "مقادیر زیر یک بار پرسیده می‌شوند و در bot_config.json ذخیره می‌گردند.\n"
                 "(این فایل در .gitignore است و نباید کامیت شود.)\n",
        'saved': "✅ تنظیمات در {path} ذخیره شد.\n",
        'token': "توکن ربات روبیکا (از @BotFather دریافت شده، 64 کاراکتر حروف بزرگ): ",
        'admin_id': "GUID مدیر ربات (مثال: u0Hlb9H0510a64cd6029655af31e2c16): ",
        'channel_id': "GUID کانال اخبار (مثال: c0DdIqc057ca4cadf20faa354de6075a): ",
        'war_channel_id': "GUID کانال جنگ (برای استفاده از همان کانال اخبار خالی بگذارید): ",
        'err_empty': "❌ این مقدار نمی‌تواند خالی باشد.",
        'err_shape': "❌ قالب مقدار وارد شده درست نیست.",
        'err_noninteractive': "پیکربندی ناقص است و ترمینال تعاملی نیست. "
                              "متغیرهای محیطی RUBIKA_BOT_TOKEN، RUBIKA_ADMIN_ID و RUBIKA_CHANNEL_ID را تنظیم کنید "
                              "یا bot_config.json را بسازید.",
    },
}


def _read_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_file(path, data):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load(lang='fa', path=None, env=None, input_fn=None, out=None, interactive=None):
    """خواندن پیکربندی با ترتیب اولویت: متغیر محیطی > فایل > ورودی تعاملی"""
    import sys

    words = PROMPTS.get(lang, PROMPTS['fa'])
    path = CONFIG_FILE if path is None else path
    env = os.environ if env is None else env
    input_fn = input if input_fn is None else input_fn
    out = (lambda text: print(text, end='')) if out is None else out
    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()

    stored = _read_file(path)
    resolved = {}
    dirty = False
    greeted = False

    for key, env_var, clean in FIELDS:
        value = None
        # مرحله ۱: متغیر محیطی
        candidate = env.get(env_var)
        if candidate is not None:
            try:
                value = clean(candidate)
            except ConfigError:
                pass
        # مرحله ۲: فایل
        if value is None:
            candidate = stored.get(key)
            if candidate is not None:
                try:
                    value = clean(candidate)
                except ConfigError:
                    pass

        # مرحله ۳: ورودی تعاملی
        while value is None:
            if not interactive:
                try:
                    value = clean('')
                    break
                except ConfigError:
                    raise SystemExit(words['err_noninteractive'])
            if not greeted:
                out(words['intro'])
                greeted = True
            try:
                value = clean(input_fn(words[key]))
            except ConfigError as exc:
                out(words['err_empty' if str(exc) == 'empty' else 'err_shape'] + '\n')
                value = None
                continue
            dirty = True

        resolved[key] = value

    if dirty:
        to_store = dict(stored)
        to_store.update({k: resolved[k] for k, _, _ in FIELDS})
        _write_file(path, to_store)
        out(words['saved'].format(path=path))

    # کانال جنگ خالی = استفاده از کانال اخبار
    if not resolved['war_channel_id']:
        resolved['war_channel_id'] = resolved['channel_id']

    return resolved
