# bot_config.py — Rubika version
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_config.json')

PLACEHOLDERS = ('', 'YOUR TOKEN', '0', '000')

FIELDS = (
    ('token',      'RUBIKA_BOT_TOKEN', _clean_token),
    ('admin_id',   'RUBIKA_ADMIN_ID',  _clean_admin_id),
    ('channel_id', 'RUBIKA_CHANNEL',   _clean_channel),
    ('war_channel_id', 'RUBIKA_WAR_CHANNEL', _clean_optional_channel),
)

PROMPTS = {
    'fa': {
        'intro': "...",
        'token': "توکن ربات روبیکا (از @BotFather روبیکا): ",
        'admin_id': "شناسه عددی مالک (GUID روبیکا، مثال: b0IY...): ",
        'channel_id': "GUID کانال خبری (مثال: b0IY... یا c0...): ",
        'war_channel_id': "GUID کانال جنگ (خالی = همان کانال خبری): ",
        ...
    },
    ...
}
