import os, time, json, logging, asyncio
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# 1) الإعدادات
# ==========================================
def _env(k, d=""): return (os.getenv(k, d) or d).strip()
def _int(k, d=0):
    try: return int(_env(k, str(d)))
    except: return d

BOT_TOKEN = _env("BOT_TOKEN")
FREE_CHANNEL_ID = _env("FREE_CHANNEL_ID")
VIP_CHANNEL_ID = _env("VIP_CHANNEL_ID")
ADMIN_ID = _int("ADMIN_ID")

BRAND = "💎 Ryma Crypto"
LINE = "━━━━━━━━━━━━━━━━━━━━"

TF_REGIME, TF_CONFIRM, TF_ENTRY = "4h", "1h", "15m"
EMA_FAST, EMA_SLOW, EMA_LONG = 20, 50, 200
RSI_PERIOD, RSI_LONG_MIN, RSI_LONG_MAX, RSI_SHORT_MIN, RSI_SHORT_MAX = 14, 45, 70, 30, 55
OBV_SLOPE_BARS, RVOL_MIN = 10, 1.15
ATR_PERIOD, ATR_MULT = 14, 1.6
STOP_MIN_PCT, STOP_MAX_PCT = 0.0035, 0.025
TP_RR, TP_FRACS = (1.0, 1.7, 2.6, 3.8), (0.35, 0.30, 0.20, 0.15)
MAX_HOLD_HOURS = 48
MAX_OPEN_TRADES = 5

TAKER_FEE, SLIPPAGE, FUNDING_8H = 0.0005, 0.0002, 0.0001
BINANCE_FAPI = "https://fapi.binance.com"
KLINE_LIMIT, API_TIMEOUT, CACHE_TTL = 1500, 15, 60
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("ryma")

def detect_lang(code):
    return "ar" if (code or "").startswith("ar") else "en"

# ==========================================
# 2) جلب البيانات والمؤشرات
# ==========================================
_cache = {}

def fetch_ohlcv(symbol, tf, bars=500, end_ms=None):
    key = (symbol, tf, bars, end_ms)
    if not end_ms and key in _cache and time.time() - _cache[key][0] < CACHE_TTL:
        return _cache[key][1].copy()
    
    params = {"symbol": f"{symbol}USDT", "interval": tf, "limit": min(bars, 1500)}
    if end_ms: params["endTime"] = int(end_ms)
    
    rows = []
    try:
        r = requests.get(f"{BINANCE_FAPI}/fapi/v1/klines", params=params, timeout=API_TIMEOUT)
        if r.status_code == 200: rows = r.json()
    except Exception as e:
        log.error(f"fetch {symbol}: {e}")
        return pd.DataFrame()

    if not rows: return pd.DataFrame()
    
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume","ct","qv","t","tb","tq","i"])
    df = df[["ts","open","high","low","close","volume"]].copy()
    for c in ["open","high","low","close","volume"]: df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts"] = pd.to_numeric(df["ts"]).astype("int64")
    df = df.dropna().drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    
    if not end_ms:
        df = df[df["ts"] + TF_MS[tf] <= int(time.time()*1000)].reset_index(drop=True)
        _cache[key] = (time.time(), df.copy())
    return df

def add_indicators(df):
    if df.empty: return df
    d = df.copy(); c = d["close"]
    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    d["ema50"] = c.ewm(span=50, adjust=False).mean()
    d["ema200"] = c.ewm(span=200, adjust=False).mean()
    
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    
    pc = c.shift(); tr = pd.concat([d["high"]-d["low"], (d["high"]-pc).abs(), (d["low"]-pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    d["rvol"] = d["volume"] / d["volume"].rolling(20).mean()
    d["obv"] = (np.sign(delta).fillna(0) * d["volume"]).cumsum()
    d["obv_slope"] = d["obv"].diff(10)
    
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    
    up_m = d["high"].diff(); dn_m = -d["low"].diff()
    p = pd.Series(np.where((up_m>dn_m)&(up_m>0), up_m, 0.0), index=d.index)
    m = pd.Series(np.where((dn_m>up_m)&(dn_m>0), dn_m, 0.0), index=d.index)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    pdi, mdi = 100*p.ewm(alpha=1/14, adjust=False).mean()/atr, 100*m.ewm(alpha=1/14, adjust=False).mean()/atr
    dx = 100*(pdi-mdi).abs()/(pdi+mdi).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()
    return d

# ==========================================
# 3) محرك القرار
# ==========================================
def v10_levels(price, side, atr):
    risk = min(max(atr * ATR_MULT, price * STOP_MIN_PCT), price * STOP_MAX_PCT)
    tps = [{"px": price + side*risk*r, "r_mult": r, "frac": f, "hit": False} for r, f in zip(TP_RR, TP_FRACS)]
    return {"entry": price, "stop": price - side*risk, "risk": risk, "tps": tps, "atr": atr}

def v10_decision(symbol, df_4h, df_1h, df_15m, idx=-1):
    if len(df_4h) < 210 or len(df_1h) < 205 or len(df_15m) < 60: return None
    d4, h1, m15 = add_indicators(df_4h), add_indicators(df_1h), add_indicators(df_15m)
    a, b, c = d4.iloc[idx], h1.iloc[idx], m15.iloc[idx]
    
    if pd.isna(a["ema50"]) or pd.isna(c["atr"]): return None
    price = float(c["close"])
    
    bull4 = a["ema50"] > a["ema200"] and a["close"] > a["ema50"]
    bear4 = a["ema50"] < a["ema200"] and a["close"] < a["ema50"]
    side = 1 if bull4 else (-1 if bear4 else (1 if a["ema50"] >= a["ema200"] else -1))
    
    bull1 = b["ema20"] > b["ema50"] and b["close"] > b["ema50"] and b["macd_hist"] > 0
    bear1 = b["ema20"] < b["ema50"] and b["close"] < b["ema50"] and b["macd_hist"] < 0
    
    obv_ok = (c["obv_slope"] > 0) if side == 1 else (c["obv_slope"] < 0)
    rsi_ok = (RSI_LONG_MIN <= c["rsi"] <= RSI_LONG_MAX) if side == 1 else (RSI_SHORT_MIN <= c["rsi"] <= RSI_SHORT_MAX)
    
    prev = m15.iloc[max(0, (idx if idx >= 0 else len(m15)) - 21):(idx if idx >= 0 else len(m15)) - 1]
    if len(prev) < 20: return None
    hi, lo = prev["high"].max(), prev["low"].min()
    rv = c["rvol"] if not pd.isna(c["rvol"]) else 0
    
    sweep = (c["low"] < lo and c["close"] > lo and c["close"] > c["open"]) if side == 1 else (c["high"] > hi and c["close"] < hi and c["close"] < c["open"])
    brk = (c["close"] > hi and rv >= RVOL_MIN) if side == 1 else (c["close"] < lo and rv >= RVOL_MIN)
    trigger = sweep or brk
    
    confirm = (bull1 if side == 1 else bear1) and obv_ok
    regime = bull4 if side == 1 else bear4
    
    score = (2 if regime else 0) + (2 if confirm else 0) + (2 if trigger else 0) + (1 if a["adx"] >= 18 else 0) + (1 if rv >= 1.0 else 0) + (1 if rsi_ok else 0)
    opp = bool(regime and confirm and trigger and a["adx"] >= 18)
    grade = ("A" if score >= 8 else "B") if opp else "C"
    
    return {
        "symbol": symbol, "side": side, "grade": grade, "score": score, "opportunity": opp,
        "price": price, "bar_ts": int(c["ts"]), "levels": v10_levels(price, side, float(c["atr"])) if opp else None
    }

def analyze(symbol):
    try:
        s4, s1, s15 = fetch_ohlcv(symbol, TF_REGIME, 260), fetch_ohlcv(symbol, TF_CONFIRM, 250), fetch_ohlcv(symbol, TF_ENTRY, 220)
        if s4.empty or s1.empty or s15.empty: return None
        return v10_decision(symbol, s4, s1, s15)
    except Exception as e:
        log.error(f"analyze {symbol}: {e}")
        return None

def scan(symbols):
    with ThreadPoolExecutor(4) as ex: res = list(ex.map(analyze, symbols))
    return [r for r in res if r is not None]
 # ==========================================
# 4) إدارة الصفقات (Tracker)
# ==========================================
@dataclass
class Trade:
    id: str
    symbol: str
    side: int
    entry: float
    stop: float
    risk: float
    tps: list
    grade: str
    opened_ts: int
    state: str = "open"
    remaining: float = 1.0
    realized_pct: float = 0.0
    be_hit: bool = False
    closed_ts: int = 0
    exit_reason: str = ""
    final_r: float = 0.0
    last_price: float = 0.0

trades = {}

def load_trades():
    global trades
    try:
        with open("trades.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            trades = {k: Trade(**v) for k, v in data.items()}
    except Exception: pass

def save_trades():
    try:
        with open("trades.json", "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in trades.items()}, f, ensure_ascii=False)
    except Exception: pass

def open_count():
    return sum(1 for t in trades.values() if t.state == "open")

def update_trade(t, current_ts, bar_high, bar_low, current_price):
    if t.state != "open": return {}
    t.last_price = current_price
    events = {}
    
    # Stop
    if (t.side == 1 and bar_low <= t.stop) or (t.side == -1 and bar_high >= t.stop):
        t.realized_pct += t.remaining * ((t.stop - t.entry) / t.entry if t.side == 1 else (t.entry - t.stop) / t.entry)
        t.remaining = 0
        t.state = "closed"; t.closed_ts = current_ts; t.exit_reason = "stop"
        events["close"] = True
        save_trades(); return events

    # Targets
    for i, tp in enumerate(t.tps):
        if tp["hit"]: continue
        if (t.side == 1 and bar_high >= tp["px"]) or (t.side == -1 and bar_low <= tp["px"]):
            tp["hit"] = True
            t.realized_pct += tp["frac"] * ((tp["px"] - t.entry) / t.entry if t.side == 1 else (t.entry - tp["px"]) / t.entry)
            t.remaining -= tp["frac"]
            events[f"tp{i+1}"] = tp
            if i == 0 and not t.be_hit:
                t.stop = t.entry; t.be_hit = True; events["be"] = True

    # 48h timeout
    if (current_ts - t.opened_ts) / 3_600_000 >= MAX_HOLD_HOURS:
        t.realized_pct += t.remaining * ((current_price - t.entry) / t.entry if t.side == 1 else (t.entry - current_price) / t.entry)
        t.remaining = 0
        t.state = "closed"; t.closed_ts = current_ts; t.exit_reason = "timeout"
        events["close"] = True

    if t.state == "closed":
        cost = (TAKER_FEE * 2 + SLIPPAGE * 2) + FUNDING_8H * (((t.closed_ts - t.opened_ts) / 3_600_000) / 8.0)
        t.realized_pct -= cost
        t.final_r = (t.realized_pct * t.entry) / t.risk

    save_trades()
    return events

# ==========================================
# 5) النشر (Publisher)
# ==========================================
def _fmt(p):
    return f"{p:,.2f}" if p >= 1000 else (f"{p:,.4f}" if p >= 1 else f"{p:.6f}")

def format_vip(t):
    s = "LONG" if t.side == 1 else "SHORT"
    txt = [f"💎 <b>#{t.symbol} · {s}</b>\n", f"الدخول: <code>{_fmt(t.entry)}</code>", f"وقف الخسارة: <code>{_fmt(t.stop)}</code>"]
    for i, tp in enumerate(t.tps, 1): txt.append(f"🎯 الهدف {i}: <code>{_fmt(tp['px'])}</code>")
    txt.append(f"\n⏱ الإغلاق القسري: {MAX_HOLD_HOURS} ساعة\n{LINE}\n{BRAND} VIP")
    return "\n".join(txt)

def format_teaser(t):
    s = "LONG" if t.side == 1 else "SHORT"
    pnl = (t.tps[0]['px'] - t.entry) / t.entry * 100 * t.side
    return (f"✅ <b>#{t.symbol} · {s}</b> — تحقق الهدف 1\n\n"
            f"الدخول: <code>{_fmt(t.entry)}</code>\nوقف الخسارة: <code>{_fmt(t.stop)}</code>\n"
            f"🎯 الهدف 1: <code>{_fmt(t.tps[0]['px'])}</code> ✅\n"
            f"📈 النتيجة: <b>{pnl:+.2f}%</b>\n\n{LINE}\n"
            "🔒 الإشارات الكاملة (4 أهداف + متابعة لحظية)\nمتاحة الآن في VIP 💎")

async def pub_vip(bot, t):
    try: await bot.send_message(VIP_CHANNEL_ID, format_vip(t), parse_mode=ParseMode.HTML)
    except Exception as e: log.error(f"pub_vip: {e}")

async def pub_teaser(bot, t):
    try: await bot.send_message(FREE_CHANNEL_ID, format_teaser(t), parse_mode=ParseMode.HTML)
    except Exception as e: log.error(f"pub_teaser: {e}")

async def pub_update(bot, t, event_type, data=None):
    s = "LONG" if t.side == 1 else "SHORT"
    try:
        if event_type.startswith("tp"):
            n = event_type[2]
            msg = f"🎯 <b>#{t.symbol} · {s}</b> — تحقق الهدف {n} ✅\nالسعر: <code>{_fmt(data['px'])}</code>\nالربح: <b>+{data['r_mult']}R</b>"
            await bot.send_message(VIP_CHANNEL_ID, msg, parse_mode=ParseMode.HTML)
        elif event_type == "be":
            await bot.send_message(VIP_CHANNEL_ID, f"🔒 <b>#{t.symbol}</b> — تم رفع الوقف إلى الدخول", parse_mode=ParseMode.HTML)
        elif event_type == "close":
            reason = "🛑 ضرب الوقف" if t.exit_reason == "stop" else f"⏱ إغلاق قسري ({MAX_HOLD_HOURS}h)"
            msg = f"{reason}\n<b>#{t.symbol} · {s}</b>\nالنتيجة: <b>{t.final_r:+.2f}R</b>"
            await bot.send_message(VIP_CHANNEL_ID, msg, parse_mode=ParseMode.HTML)
    except Exception as e: log.error(f"pub_update: {e}")

# ==========================================
# 6) أوامر البوت
# ==========================================
TEXTS = {
    "welcome": {
        "ar": f"أهلاً {{name}}! 👋\n\nمرحباً بك في <b>{BRAND}</b>\n\n📌 أرسل اسم أي عملة (مثل BTC) وسأحللها فوراً.\n\n🔍 /scan — فحص السوق\n💎 VIP — القناة المدفوعة",
        "en": f"Welcome {{name}}! 👋\n\nWelcome to <b>{BRAND}</b>\n\n📌 Send any coin symbol (e.g., BTC) and I'll analyze it.\n\n🔍 /scan — Market scan\n💎 VIP — Premium channel"
    },
    "analyzing": {"ar": "⏳ جارٍ تحليل {sym}...", "en": "⏳ Analyzing {sym}..."},
    "no_signal": {"ar": "⚪ لا توجد إشارة مؤكدة حالياً لـ {sym}", "en": "⚪ No confirmed signal for {sym} currently"},
    "scan_start": {"ar": "🔍 جارٍ فحص السوق...", "en": "🔍 Scanning market..."}
}

def T(key, lang, **kw):
    text = TEXTS.get(key, {}).get(lang) or TEXTS.get(key, {}).get("en", key)
    return text.format(**kw) if kw else text

def _lang(update):
    return detect_lang(update.effective_user.language_code if update.effective_user else None)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    name = update.effective_user.first_name or "Trader"
    await update.message.reply_text(T("welcome", lang, name=name), parse_mode=ParseMode.HTML)

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    msg = await update.message.reply_text(T("scan_start", lang))
    symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI"]
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, scan, symbols)
    opps = [r for r in results if r["opportunity"]]
    if not opps:
        await msg.edit_text("⚪ لا توجد فرص مؤكدة حالياً" if lang == "ar" else "⚪ No confirmed opportunities now")
        return
    lines = [f"🎯 <b>{len(opps)}</b> {'فرصة' if lang == 'ar' else 'opportunities'}:", ""]
    for s in opps:
        side = "LONG" if s["side"] == 1 else "SHORT"
        lines.append(f"{'🟢' if s['side'] == 1 else '🔴'} <b>#{s['symbol']}</b> · {side} · {s['grade']}")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def cmd_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    sym = (update.message.text or "").strip().upper()
    if not sym or len(sym) > 10: return
    msg = await update.message.reply_text(T("analyzing", lang, sym=sym))
    loop = asyncio.get_event_loop()
    sig = await loop.run_in_executor(None, analyze, sym)
    
    if not sig or not sig["opportunity"] or not sig["levels"]:
        await msg.edit_text(T("no_signal", lang, sym=sym))
        return
        
    side = "LONG" if sig["side"] == 1 else "SHORT"
    txt = [f"💎 <b>#{sym} · {side}</b>\n", f"الدخول: <code>{_fmt(sig['levels']['entry'])}</code>", f"وقف الخسارة: <code>{_fmt(sig['levels']['stop'])}</code>"]
    for i, tp in enumerate(sig["levels"]["tps"], 1): txt.append(f"🎯 الهدف {i}: <code>{_fmt(tp['px'])}</code>")
    txt.extend(["", LINE, f"الدرجة: {sig['grade']} · Score: {sig['score']}/9"])
    await msg.edit_text("\n".join(txt), parse_mode=ParseMode.HTML)

# ==========================================
# 7) المهام الخلفية والتشغيل
# ==========================================
async def bg_scan(app):
    symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI"]
    while True:
        await asyncio.sleep(3600)
        try:
            if open_count() >= MAX_OPEN_TRADES: continue
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, scan, symbols)
            for sig in results:
                if not sig["opportunity"] or not sig["levels"]: continue
                if any(t.symbol == sig["symbol"] for t in trades.values() if t.state == "open"): continue
                
                t = Trade(id=f"{sig['symbol']}-{sig['bar_ts']}", symbol=sig["symbol"], side=sig["side"], entry=sig["levels"]["entry"], 
                          stop=sig["levels"]["stop"], risk=sig["levels"]["risk"], tps=sig["levels"]["tps"], 
                          grade=sig["grade"], opened_ts=int(time.time()*1000))
                trades[t.id] = t; save_trades()
                await pub_vip(app.bot, t)
        except Exception as e: log.error(f"bg_scan: {e}")

async def bg_update(app):
    while True:
        await asyncio.sleep(300)
        try:
            for t in list(trades.values()):
                if t.state != "open": continue
                df = fetch_ohlcv(t.symbol, "15m", 3)
                if df.empty: continue
                last = df.iloc[-1]
                events = update_trade(t, int(last["ts"]), float(last["high"]), float(last["low"]), float(last["close"]))
                for ev, data in events.items():
                    await pub_update(app.bot, t, ev, data)
                    if ev == "tp1": await pub_teaser(app.bot, t)
        except Exception as e: log.error(f"bg_update: {e}")

async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start", "Start"), BotCommand("scan", "Scan Market")])
    asyncio.create_task(bg_scan(app))
    asyncio.create_task(bg_update(app))
    log.info("Started background tasks")

def main():
    load_trades()
    if not BOT_TOKEN: raise SystemExit("BOT_TOKEN missing")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_symbol))
    log.info(f"Starting {BRAND}")
    app.run_polling()

if __name__ == "__main__":
    main()
 
