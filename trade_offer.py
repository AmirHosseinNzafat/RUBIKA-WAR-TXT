# -*- coding: utf-8 -*-
"""چرخه حیات پیشنهاد تجارت و تیکر محموله.

این فایل:
    - ارسال پیشنهاد به کشور مقصد
    - پذیرش / رد / لغو پیشنهاد
    - تیکر پس‌زمینه که محموله‌های فعال رو حرکت می‌ده
    - پرداخت عوارض هنگام عبور از chokepoint ها
    - تحویل محموله به مقصد

نسخه روبیکا.
"""

import asyncio
import json
import time

from rubpy.bot.models import Button, Keypad, KeypadRow
from rubpy.bot.enums import ButtonTypeEnum

import trade_core as core
from trade_wizard import _ctx, _kp, _btn, _send, _answer, _goods_lines, _trade_cost, _dur


# ---------------------------------------------------------------------------
# تأیید و ارسال پیشنهاد
# ---------------------------------------------------------------------------


async def confirm_send(call):
    """دکمه ✅ ارسال پیشنهاد در مرحله تأیید."""
    c = _ctx.get(str(call.user_id))
    if not c or 'route_i' not in c:
        await _answer(call, core._t('session_expired'), alert=True)
        return

    user_id = call.user_id
    r = c['routes'][c['route_i']]
    fee = _trade_cost(c, r)
    receiver = core.lord_row(c['dest'])

    if receiver is None:
        await _answer(call, core._t('err_generic'))
        return

    # چک مجدد که ادمین بین راه mode رو نبسته باشه
    if not core.mode_open(c['chat_id'], c['mode']):
        await _answer(call)
        await _send(c['chat_id'],
                    core._t('tm_closed_here', mode=core.mode_name(c['mode'])))
        return

    if not core.mode_open(c['dest'], c['mode']):
        await _answer(call)
        dest_title = await core.title(c['dest'])
        await _send(c['chat_id'],
                    core._t('tm_closed_there',
                            mode=core.mode_name(c['mode']),
                            g=core._esc(dest_title)))
        return

    # کسر کالا و پول
    if not core.escrow(c['chat_id'], c['goods'], c['vehicles'], fee):
        await _answer(call)
        await _send(c['chat_id'], core._t('insufficient'))
        return

    # ثبت در دیتابیس
    now = int(time.time())
    cur = core._exec(
        """INSERT INTO trades (sender_group_id, sender_user_id,
                               receiver_group_id, receiver_user_id,
                               mode, goods, vehicles, route,
                               leg_minutes, tolls, fee_paid,
                               status, offered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'offered', ?)""",
        (str(c['chat_id']), str(user_id), str(c['dest']),
         str(receiver['user_id']), c['mode'],
         json.dumps(c['goods']), json.dumps(c['vehicles']),
         json.dumps(r['path']), json.dumps(r['leg_minutes']),
         json.dumps(r['tolls']), fee, now))
    tid = cur.lastrowid

    trade = core._q("SELECT * FROM trades WHERE id=?", (tid,))[0]

    # ارسال پیشنهاد به گروه مقصد
    try:
        user_info = await core._bot.get_chat(user_id)
        lord_name = getattr(user_info, 'first_name', '') or str(user_id)
    except Exception:
        lord_name = str(user_id)

    src_title = await core.title(c['chat_id'])
    offer_text = core._t('offer_msg',
                         tid=tid,
                         sender=core._esc(src_title),
                         lord=core._esc(lord_name),
                         goods=_goods_lines(c['goods']),
                         path=core.path_names(c['mode'], r['path']),
                         dur=_dur(r['minutes']),
                         exp=core.cfg('offer_expiry_min'))

    rows = [[_btn(f'trd:a:{tid}', core._t('btn_accept')),
             _btn(f'trd:n:{tid}', core._t('btn_decline'))]]

    try:
        sent, with_photo = await core.send_rich(
            c['dest'], offer_text, mode=c['mode'],
            inline_keypad=_kp(rows))
    except Exception:
        # اگه ارسال نشد، همه چی برگرده
        core.refund(trade)
        core._exec("UPDATE trades SET status='cancelled' WHERE id=?", (tid,))
        await _answer(call)
        await _send(c['chat_id'], core._t('send_failed'))
        _ctx.pop(str(user_id), None)
        return

    # ذخیره id پیام
    sent_msg_id = getattr(sent, 'message_id', None)
    if hasattr(sent_msg_id, 'message_id'):
        sent_msg_id = sent_msg_id.message_id
    core._exec(
        "UPDATE trades SET offer_chat_id=?, offer_msg_id=?, offer_photo=? WHERE id=?",
        (str(c['dest']), str(sent_msg_id), 1 if with_photo else 0, tid))

    # پیام به فرستنده با دکمه لغو
    rows2 = [[_btn(f'trd:c:{tid}', core._t('btn_cancel_offer'))]]
    dest_title = await core.title(c['dest'])
    await _send(c['chat_id'],
                core._t('offer_sent_sender', tid=tid, dest=core._esc(dest_title)),
                rows2)

    _ctx.pop(str(user_id), None)
    await _answer(call)


# ---------------------------------------------------------------------------
# پذیرش / رد / لغو
# ---------------------------------------------------------------------------


def _get_trade(tid):
    rows = core._q("SELECT * FROM trades WHERE id=?", (tid,))
    return rows[0] if rows else None


async def _edit_offer_msg(trade, suffix_key):
    """ویرایش پیام پیشنهاد (حذف دکمه + اضافه کردن وضعیت)."""
    chat_id = trade.get('offer_chat_id')
    msg_id = trade.get('offer_msg_id')
    if not chat_id or not msg_id:
        return
    try:
        await core._bot.edit_message_text(
            chat_id, msg_id,
            f"#{trade['id']}" + core._t(suffix_key))
    except Exception:
        pass


async def accept(call, tid):
    """پذیرش پیشنهاد توسط گیرنده."""
    with core._lock:
        trade = _get_trade(tid)
        if not trade or trade['status'] != 'offered':
            await _answer(call, core._t('already_handled'), alert=True)
            return
        if not core.is_lord(trade['receiver_group_id'], call.user_id):
            await _answer(call, core._t('not_lord'), alert=True)
            return

        now = int(time.time())
        leg_minutes = json.loads(trade['leg_minutes'])
        core._exec(
            "UPDATE trades SET status='active', departed_at=?, next_eta=? "
            "WHERE id=? AND status='offered'",
            (now, now + leg_minutes[0] * 60, tid))

    trade = _get_trade(tid)
    await _answer(call)
    await _edit_offer_msg(trade, 'offer_accepted_edit')

    # پیام ردیابی در گروه فرستنده
    try:
        text = _track_text(trade)
        sent, with_photo = await core.send_rich(
            trade['sender_group_id'], text, mode=trade['mode'])
        sent_msg_id = getattr(sent, 'message_id', None)
        if hasattr(sent_msg_id, 'message_id'):
            sent_msg_id = sent_msg_id.message_id
        core._exec(
            "UPDATE trades SET track_chat_id=?, track_msg_id=?, track_photo=? WHERE id=?",
            (str(trade['sender_group_id']), str(sent_msg_id),
             1 if with_photo else 0, tid))
    except Exception:
        pass

    # اعلام به کانال
    route = json.loads(trade['route'])
    src_title = await core.title(trade['sender_group_id'])
    dst_title = await core.title(trade['receiver_group_id'])
    try:
        text = core._t('depart_channel',
                       emoji=core.mode_emoji(trade['mode']),
                       src_g=core._esc(src_title),
                       dst_g=core._esc(dst_title),
                       path=core.path_names(trade['mode'], route),
                       dur=_dur(sum(json.loads(trade['leg_minutes']))))
        await core.send_rich(core._channel, text, mode=trade['mode'])
    except Exception:
        pass


async def _finish_offer(call, tid, require_sender, status, edit_key, sender_key):
    """مسیر مشترک رد/لغو: گارد، بازگشت، علامت‌گذاری، اطلاع."""
    with core._lock:
        trade = _get_trade(tid)
        if not trade or trade['status'] != 'offered':
            await _answer(call, core._t('already_handled'), alert=True)
            return
        if require_sender:
            if not core.is_lord(trade['sender_group_id'], call.user_id):
                await _answer(call, core._t('not_lord'), alert=True)
                return
        else:
            if not core.is_lord(trade['receiver_group_id'], call.user_id):
                await _answer(call, core._t('not_lord'), alert=True)
                return

        core._exec("UPDATE trades SET status=? WHERE id=? AND status='offered'",
                   (status, tid))
        core.refund(trade)

    await _answer(call)
    await _edit_offer_msg(trade, edit_key)
    try:
        await core._bot.send_message(
            trade['sender_group_id'],
            core._t(sender_key, tid=tid))
    except Exception:
        pass


async def decline(call, tid):
    await _finish_offer(call, tid, False, 'declined',
                        'offer_declined_edit', 'declined_sender')


async def cancel_offer(call, tid):
    await _finish_offer(call, tid, True, 'cancelled',
                        'offer_cancelled_edit', 'cancelled_sender')


# ---------------------------------------------------------------------------
# تیکر محموله — به صورت async task
# ---------------------------------------------------------------------------


def _track_text(trade):
    """متن پیام ردیابی محموله."""
    mode = trade['mode']
    emoji = core.mode_emoji(mode)
    route = json.loads(trade['route'])
    leg = trade['leg']

    src_title = core.title_sync(trade['sender_group_id'])
    dst_title = core.title_sync(trade['receiver_group_id'])

    parts = [core._t('track_header',
                     emoji=emoji, tid=trade['id'],
                     src_g=core._esc(src_title),
                     dst_g=core._esc(dst_title))]

    prog = []
    for i, nid in enumerate(route):
        icon = '✅' if i < leg else (emoji if i == leg else '▫️')
        prog.append(f"{icon} {core.node_name(mode, nid)}")
    parts.append('\n'.join(prog))

    if trade['status'] == 'delivered' or leg >= len(route) - 1:
        parts.append(core._t('track_done'))
    else:
        cur_nid = route[leg]
        node = core._node(mode, cur_nid)
        kind = node['kind'] if node else 'sea'
        if kind in ('strait', 'canal', 'pass'):
            charged = dict(json.loads(trade['tolls'] or '[]'))
            owner = core.owner_of(cur_nid)
            if charged.get(cur_nid) and owner:
                owner_t = core.title_sync(owner)
                parts.append(core._t('track_choke_owned',
                                     cur=core.node_name(mode, cur_nid),
                                     owner=core._esc(owner_t)))
            elif charged.get(cur_nid):
                parts.append(core._t('track_choke',
                                     cur=core.node_name(mode, cur_nid)))
            else:
                parts.append(core._t('track_pass',
                                     cur=core.node_name(mode, cur_nid)))
        elif kind == 'cape':
            parts.append(core._t('track_cape',
                                 cur=core.node_name(mode, cur_nid)))
        else:
            parts.append(core._t('track_at',
                                 cur=core.node_name(mode, cur_nid)))

        mins = max(0, (trade['next_eta'] or 0) - int(time.time())) // 60
        parts.append(core._t('track_moving',
                             next=core.node_name(mode, route[leg + 1]),
                             min=mins))
    return '\n\n'.join(parts)


async def _edit_tracking(trade):
    """ویرایش پیام ردیابی."""
    chat_id = trade.get('track_chat_id')
    msg_id = trade.get('track_msg_id')
    if not chat_id or not msg_id:
        return
    text = _track_text(trade)
    text = core._to_markdown(text)
    try:
        await core._bot.edit_message_text(chat_id, msg_id, text)
    except Exception:
        try:
            # اگه ویرایش نشد، پیام جدید بفرست
            sent, with_photo = await core.send_rich(
                chat_id, text, mode=trade['mode'])
            new_id = getattr(sent, 'message_id', None)
            if hasattr(new_id, 'message_id'):
                new_id = new_id.message_id
            core._exec(
                "UPDATE trades SET track_msg_id=?, track_photo=? WHERE id=?",
                (str(new_id), 1 if with_photo else 0, trade['id']))
        except Exception:
            pass


async def _settle_tolls(trade, route, from_leg, to_leg):
    """پرداخت عوارض گره‌های عبور شده به مالک فعلی‌شون."""
    charged = dict(json.loads(trade['tolls'] or '[]'))
    for nid in route[from_leg + 1:to_leg + 1]:
        amount = charged.get(nid)
        if not amount:
            continue
        owner = core.owner_of(nid)
        if not owner:
            continue
        core.give(owner, {'money': amount})
        try:
            await core._bot.send_message(
                owner,
                core._t('toll_income', amount=amount, tid=trade['id'],
                        node=core.node_name(trade['mode'], nid)))
        except Exception:
            pass


async def _arrive(trade):
    """تحویل یک محموله فعال. True اگه واقعاً تحویل داده شد."""
    with core._lock:
        cur_trade = _get_trade(trade['id'])
        if not cur_trade or cur_trade['status'] != 'active':
            return False
        route = json.loads(cur_trade['route'])
        core._exec(
            "UPDATE trades SET status='delivered', leg=?, next_eta=NULL WHERE id=?",
            (len(route) - 1, trade['id']))
        core.give(cur_trade['receiver_group_id'], json.loads(cur_trade['goods']))
        core.give(cur_trade['sender_group_id'], json.loads(cur_trade['vehicles']))

    trade = _get_trade(trade['id'])
    await _edit_tracking(trade)

    src_title = core.title_sync(trade['sender_group_id'])
    try:
        await core._bot.send_message(
            trade['receiver_group_id'],
            core._t('arrived_receiver', tid=trade['id'],
                    sender=core._esc(src_title),
                    goods=_goods_lines(json.loads(trade['goods']))))
    except Exception:
        pass

    dst_title = core.title_sync(trade['receiver_group_id'])
    try:
        text = core._t('arrive_channel',
                       emoji=core.mode_emoji(trade['mode']),
                       src_g=core._esc(src_title),
                       dst_g=core._esc(dst_title))
        await core.send_rich(core._channel, text, mode=trade['mode'])
    except Exception:
        pass
    return True


async def tick():
    """یک دور تیکر: منقضی کردن پیشنهادها، حرکت محموله‌ها."""
    now = int(time.time())

    # ۱. منقضی کردن پیشنهادهای قدیمی
    expiry = core.cfg('offer_expiry_min') * 60
    stale = core._q(
        "SELECT * FROM trades WHERE status='offered' AND offered_at + ? <= ?",
        (expiry, now))
    for trade in stale:
        with core._lock:
            cur_trade = _get_trade(trade['id'])
            if not cur_trade or cur_trade['status'] != 'offered':
                continue
            core._exec(
                "UPDATE trades SET status='expired' WHERE id=? AND status='offered'",
                (trade['id'],))
            core.refund(cur_trade)
        await _edit_offer_msg(cur_trade, 'offer_expired_edit')
        try:
            await core._bot.send_message(
                cur_trade['sender_group_id'],
                core._t('expired_sender', tid=cur_trade['id']))
        except Exception:
            pass

    # ۲. پیشرفت محموله‌های فعال
    active = core._q(
        "SELECT * FROM trades WHERE status='active' "
        "AND next_eta IS NOT NULL AND next_eta <= ?", (now,))
    for trade in active:
        route = json.loads(trade['route'])
        legs = json.loads(trade['leg_minutes'])
        old_leg = trade['leg']
        leg = old_leg
        eta = trade['next_eta']
        arrived = False
        while eta <= now:
            leg += 1
            if leg >= len(route) - 1:
                arrived = True
                break
            eta += legs[leg] * 60

        if arrived:
            if await _arrive(trade):
                await _settle_tolls(trade, route, old_leg, len(route) - 1)
        else:
            cur_res = core._exec(
                "UPDATE trades SET leg=?, next_eta=? "
                "WHERE id=? AND status='active'",
                (leg, eta, trade['id']))
            if cur_res.rowcount:
                await _settle_tolls(trade, route, old_leg, leg)
            trade = _get_trade(trade['id'])
            if trade and trade['status'] == 'active':
                await _edit_tracking(trade)


async def ticker_loop():
    """حلقه پس‌زمینه — هر ۲۵ ثانیه یه بار."""
    while True:
        try:
            await tick()
        except Exception:
            import traceback
            traceback.print_exc()
        await asyncio.sleep(25)


def start_ticker():
    """در main.py صدا بزن: asyncio.create_task(start_ticker())"""
    return ticker_loop()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def handle_callback(call):
    """callback های مربوط به چرخه پیشنهاد را پردازش کن."""
    try:
        parts = call.data.split(':')
        op = parts[1] if len(parts) > 1 else ''

        if op == 'go':
            await confirm_send(call)
        elif op == 'a':
            await accept(call, int(parts[2]))
        elif op == 'n':
            await decline(call, int(parts[2]))
        elif op == 'c':
            await cancel_offer(call, int(parts[2]))
        else:
            await _answer(call, core._t('err_generic'))
    except Exception:
        import traceback
        traceback.print_exc()
        await _answer(call, core._t('err_generic'))
