 # ===================== Ryma Crypto v10.1 Hybrid Signal Engine =====================
# Hybrid: Liquidity Sweep (4H/1H) + TrendRider factors + Funding Filter
# Alerts & Intelligence only — no real order execution

import os, io, re, json, time, asyncio, logging, threading, functools
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests, ccxt, matplotlib
import urllib.parse, concurrent.futures
import types as _types

# ===================== إعدادات المحرك =====================
ENG_TP_FRACS = [0.50, 0.30, 0.20]

ENG_CFG = dict(
    min_score=3.0,
    grade_a=4.0,
    min_adx=18.0,
    long_min_adx=18.0,
    short_min_adx=18.0,
    rsi_long_max=72.0,
    rsi_short_min=28.0,
    min_sl_atr=1.4,
    max_sl_atr=1.8,
    sl_buffer_atr=0.05,
    min_rr_tp1=1.8,
    max_tp_atr=7.0,
    pivot_w=3,
    pivot_lb_entry=80,
    swing_lb=30,
    be_offset_r=0.05,
    trail_atr=2.0,
    max_risk_pct=0.04,
    max_hold=10,
    bb_period=20,
    bb_std=2.0,
    # إعدادات سحب السيولة
    sweep_lookback=20,
    wick_ratio=0.55,
    # فلتر التمويل
    min_funding_short=0.00025,   # 0.025%
    max_funding_long=-0.00012,
)

# ----------------------------------------------------------------- مؤشرات
def _eng_wilder(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()

def eng_prepare(df):
    """تحضير المؤشرات بشكل سببي (بدون تسريب مستقبلي)."""
    required = {"t", "open", "high", "low", "close", "volume"}
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or not required.issubset(df.columns):
        return pd.DataFrame()
    
    out = df.copy().reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["t", "open", "high", "low", "close", "volume"]).copy()
    out["t"] = pd.to_numeric(out["t"], errors="coerce")
    out = out.dropna(subset=["t"]).sort_values("t").drop_duplicates("t", keep="last").reset_index(drop=True)
    
    if out.empty or (out[["open", "high", "low", "close"]] <= 0).any().any():
        return pd.DataFrame()
    
    c, h, l, v = out["close"], out["high"], out["low"], out["volume"].clip(lower=0)
    
    # EMAs
    for period in (9, 20, 21, 50, 200):
        out[f"ema{period}"] = c.ewm(span=period, adjust=False, min_periods=period).mean()
    
    # ATR
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    out["atr"] = _eng_wilder(tr, 14)
    
    # RSI
    delta = c.diff()
    up = _eng_wilder(delta.clip(lower=0), 14)
    dn = _eng_wilder((-delta).clip(lower=0), 14)
    rs = up / dn.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi[(dn == 0) & (up > 0)] = 100.0
    rsi[(dn == 0) & (up == 0)] = 50.0
    out["rsi"] = rsi
    
    # MACD Histogram
    ema12 = c.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = c.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    out["macd_hist"] = macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()
    
    # ADX / DMI
    upm, dnm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((upm > dnm) & (upm > 0), upm, 0.0), index=out.index)
    mdm = pd.Series(np.where((dnm > upm) & (dnm > 0), dnm, 0.0), index=out.index)
    atr14 = _eng_wilder(tr, 14).replace(0, np.nan)
    pdi = 100 * _eng_wilder(pdm, 14) / atr14
    mdi = 100 * _eng_wilder(mdm, 14) / atr14
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    out["pdi"], out["mdi"], out["adx"] = pdi, mdi, _eng_wilder(dx, 14)
    
    # Bollinger
    bb_mid = c.rolling(20, min_periods=20).mean()
    bb_sd = c.rolling(20, min_periods=20).std(ddof=0)
    out["bb_mid"] = bb_mid
    out["bb_upper"] = bb_mid + 2.0 * bb_sd
    out["bb_lower"] = bb_mid - 2.0 * bb_sd
    out["bb_percent"] = (c - out["bb_lower"]) / (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
    
    # Volume
    out["rvol"] = v / v.shift(1).rolling(20, min_periods=10).mean().replace(0, np.nan)
    
    return out

def eng_find_swing_levels(df, lookback=20, w=2):
    """ إيجاد أحدث قمة وقاع مؤكدين """
    if df is None or len(df) < lookback + 5:
        return None, None
    
    H = df["high"].to_numpy()
    L = df["low"].to_numpy()
    n = len(df)
    
    swing_high = None
    swing_low = None
    
    # نبحث في آخر lookback شمعة (بدون الشمعة الحالية)
    for i in range(n - lookback - 1, n - 3):
        if i < w or i + w >= n:
            continue
        # قمة
        if H[i] >= H[i-w:i+w+1].max():
            if swing_high is None or H[i] > swing_high:
                swing_high = float(H[i])
        # قاع
        if L[i] <= L[i-w:i+w+1].min():
            if swing_low is None or L[i] < swing_low:
                swing_low = float(L[i])
    
    return swing_high, swing_low

def detect_liquidity_sweep(df_h4, df_h1, cfg=None):
    """
    Liquidity Sweep:
    - السعر يكسر قمة/قاع 4H بذيل واضح
    - ثم يغلق شمعة 1H داخل النطاق مرة أخرى
    """
    cfg = cfg or ENG_CFG
    if df_h4 is None or df_h1 is None or len(df_h4) < 40 or len(df_h1) < 30:
        return None
    
    df_h4 = eng_prepare(df_h4)
    df_h1 = eng_prepare(df_h1)
    
    if df_h4.empty or df_h1.empty:
        return None
    
    # آخر شمعة مغلقة
    h1 = df_h1.iloc[-2]
    h4_last = df_h4.iloc[-2]
    
    swing_high, swing_low = eng_find_swing_levels(df_h4, lookback=cfg.get("sweep_lookback", 20))
    
    if swing_high is None and swing_low is None:
        return None
    
    wick_ratio = cfg.get("wick_ratio", 0.55)
    signal = None
    
    # ===== SHORT : سحب سيولة القمة =====
    if swing_high is not None:
        upper_wick = h1["high"] - max(h1["open"], h1["close"])
        full_range = h1["high"] - h1["low"] + 1e-9
        if (h1["high"] > swing_high and 
            h1["close"] < swing_high and 
            (upper_wick / full_range) >= wick_ratio):
            
            signal = {
                "direction": "SHORT",
                "side": -1,
                "type": "Liquidity Sweep",
                "reason": f"سحب سيولة قمة 4H عند {swing_high:.5f} + إغلاق ضعيف على 1H",
                "entry": float(h1["close"]),
                "atr": float(h1["atr"]),
                "level": swing_high,
                "strength": 1.3
            }
    
    # ===== LONG : سحب سيولة القاع =====
    if signal is None and swing_low is not None:
        lower_wick = min(h1["open"], h1["close"]) - h1["low"]
        full_range = h1["high"] - h1["low"] + 1e-9
        if (h1["low"] < swing_low and 
            h1["close"] > swing_low and 
            (lower_wick / full_range) >= wick_ratio):
            
            signal = {
                "direction": "LONG",
                "side": 1,
                "type": "Liquidity Sweep",
                "reason": f"سحب سيولة قاع 4H عند {swing_low:.5f} + إغلاق قوي على 1H",
                "entry": float(h1["close"]),
                "atr": float(h1["atr"]),
                "level": swing_low,
                "strength": 1.3
            }
    
    return signal

def detect_bollinger_exhaustion(df_h4, cfg=None):
    """تشبع قوي على إطار 4 ساعات"""
    cfg = cfg or ENG_CFG
    if df_h4 is None or len(df_h4) < 50:
        return None
    
    df = eng_prepare(df_h4)
    if df.empty:
        return None
    
    last = df.iloc[-2]
    
    # Short Exhaustion
    if last.get("bb_percent", 0) > 0.97 and last["rsi"] > 73:
        return {
            "direction": "SHORT",
            "side": -1,
            "type": "Bollinger Exhaustion",
            "reason": f"تشبع شرائي عنيف | %B={last['bb_percent']:.2f} + RSI={last['rsi']:.1f}",
            "entry": float(last["close"]),
            "atr": float(last["atr"]),
            "level": float(last["bb_upper"]),
            "strength": 1.1
        }
    
    # Long Exhaustion
    if last.get("bb_percent", 1) < 0.03 and last["rsi"] < 27:
        return {
            "direction": "LONG",
            "side": 1,
            "type": "Bollinger Exhaustion",
            "reason": f"تشبع بيعي عنيف | %B={last['bb_percent']:.2f} + RSI={last['rsi']:.1f}",
            "entry": float(last["close"]),
            "atr": float(last["atr"]),
            "level": float(last["bb_lower"]),
            "strength": 1.1
        }
    
    return None

def eng_build_levels(entry, atr, side, cfg=None):
    """حساب الوقف والأهداف"""
    cfg = cfg or ENG_CFG
    if not np.isfinite(atr) or atr <= 0 or not np.isfinite(entry) or entry <= 0:
        return None
    
    risk = float(cfg.get("min_sl_atr", 1.5)) * atr
    risk = min(risk, entry * float(cfg.get("max_risk_pct", 0.04)))
    
    if side == 1:  # LONG
        sl = entry - risk
        tp1 = entry + risk * 2.0
        tp2 = entry + risk * 3.0
    else:          # SHORT
        sl = entry + risk
        tp1 = entry - risk * 2.0
        tp2 = entry - risk * 3.0
    
    if sl <= 0:
        return None
    
    return {
        "entry": round(float(entry), 6),
        "sl": round(float(sl), 6),
        "tp1": round(float(tp1), 6),
        "tp2": round(float(tp2), 6),
        "risk": round(float(risk), 6),
        "atr": round(float(atr), 6)
    }

def apply_funding_filter(direction, funding, cfg=None):
    """فلتر التمويل - مهم جداً خاصة على الـ Short"""
    cfg = cfg or ENG_CFG
    if funding is None:
        return True  # إذا ما قدرنا نجيب البيانات نسمح
    
    if direction == "SHORT":
        return funding >= cfg.get("min_funding_short", 0.00025)
    if direction == "LONG":
        return funding <= cfg.get("max_funding_long", -0.00012)
    
    return True

def eng_evaluate_hybrid(df_h4, df_h1, funding=None, cfg=None):
    """
    المحرك الهجين الجديد:
    1. يبحث أولاً عن Liquidity Sweep
    2. إذا ما لقاش → يبحث عن Bollinger Exhaustion
    3. يطبق فلتر التمويل
    4. يحسب المستويات
    """
    cfg = cfg or ENG_CFG
    res = {
        "status": "WAIT",
        "side": 0,
        "score": 0.0,
        "grade": "WAIT",
        "confidence": 0,
        "lv": None,
        "reasons": [],
        "warnings": [],
        "type": None,
        "strategy": "Hybrid Liquidity Sweep + Exhaustion v10.1"
    }
    
    # 1. Liquidity Sweep (الأولوية)
    sweep = detect_liquidity_sweep(df_h4, df_h1, cfg)
    
    signal = None
    if sweep:
        signal = sweep
    else:
        # 2. Bollinger Exhaustion كخيار ثاني
        signal = detect_bollinger_exhaustion(df_h4, cfg)
    
    if signal is None:
        res["wait_reasons"] = ["لا يوجد سحب سيولة أو تشبع واضح"]
        return res
    
    # 3. فلتر التمويل
    if not apply_funding_filter(signal["direction"], funding, cfg):
        res["wait_reasons"] = [f"التمويل لا يدعم الصفقة (Funding={funding})"]
        return res
    
    # 4. حساب المستويات
    levels = eng_build_levels(signal["entry"], signal["atr"], signal["side"], cfg)
    if levels is None:
        res["wait_reasons"] = ["تعذر حساب مستويات الدخول والوقف"]
        return res
    
    # 5. بناء النتيجة
    score = 3.5 + (0.5 if signal["type"] == "Liquidity Sweep" else 0)
    
    res.update({
        "status": signal["direction"],
        "side": signal["side"],
        "score": score,
        "grade": "A" if signal["type"] == "Liquidity Sweep" else "B",
        "confidence": 68 if signal["type"] == "Liquidity Sweep" else 58,
        "lv": levels,
        "reasons": [signal["reason"]],
        "type": signal["type"],
        "entry": levels["entry"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"]
    })
    
    if funding is not None:
        res["funding"] = funding
        res["reasons"].append(f"Funding: {funding*100:.4f}%")
    
    return res

# ===================== نهاية الجزء الأول =====================
print("Part 1 loaded successfully — Hybrid Engine Ready")
# ===================== الجزء الثاني : Data + Telegram + Scanner =====================

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from dotenv import load_dotenv

load_dotenv()

# ====================== الإعدادات ======================
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHANNEL_ID") or os.getenv("TELEGRAM_CHAT_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

TOP_SYMBOLS_LIMIT = 70
REQUEST_DELAY = 0.12

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ryma_hybrid")

# ====================== طبقة البيانات ======================
class BinanceData:
    def __init__(self):
        self.exchange = ccxt.binanceusdm({
            "apiKey": BINANCE_API_KEY,
            "secret": BINANCE_API_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": "future"}
        })

    def get_top_symbols(self, limit=TOP_SYMBOLS_LIMIT):
        try:
            tickers = self.exchange.fetch_tickers()
            pairs = []
            for symbol, data in tickers.items():
                if symbol.endswith("/USDT") and data.get("quoteVolume"):
                    pairs.append({
                        "symbol": symbol,
                        "volume": float(data["quoteVolume"])
                    })
            pairs = sorted(pairs, key=lambda x: x["volume"], reverse=True)
            return [p["symbol"] for p in pairs[:limit]]
        except Exception as e:
            logger.error(f"Error getting top symbols: {e}")
            return []

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 120):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["t", "open", "high", "low", "close", "volume"])
            return df
        except Exception as e:
            logger.warning(f"OHLCV error {symbol} {timeframe}: {e}")
            return None

    def get_funding_rate(self, symbol: str) -> float:
        try:
            s = symbol.replace("/", "")
            data = self.exchange.fetch_funding_rate(s)
            return float(data.get("fundingRate", 0))
        except Exception:
            return 0.0

    def get_h4_and_h1(self, symbol: str):
        df_h4 = self.fetch_ohlcv(symbol, "4h", 100)
        time.sleep(REQUEST_DELAY)
        df_h1 = self.fetch_ohlcv(symbol, "1h", 100)
        return df_h4, df_h1

# ====================== تنسيق رسالة التنبيه ======================
def format_signal_message(symbol: str, result: dict) -> str:
    direction = result.get("status", "WAIT")
    emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    
    lv = result.get("lv") or {}
    reasons = result.get("reasons", [])
    signal_type = result.get("type", "Hybrid")
    
    funding = result.get("funding")
    funding_txt = f"{funding*100:.4f}%" if funding is not None else "—"
    
    msg = f"""
━━━━━━━━━━━━━━━━━━━━
{emoji}  <b>{symbol}</b>
━━━━━━━━━━━━━━━━━━━━

📌 <b>نوع الإشارة:</b> {signal_type}
📝 <b>السبب:</b>
{chr(10).join(['• ' + r for r in reasons])}

💰 <b>الدخول المقترح:</b> <code>{lv.get('entry', '—')}</code>
🛑 <b>وقف الخسارة:</b> <code>{lv.get('sl', '—')}</code>
🎯 <b>الهدف 1 (1:2):</b> <code>{lv.get('tp1', '—')}</code>
🎯 <b>الهدف 2 (1:3):</b> <code>{lv.get('tp2', '—')}</code>

📊 <b>Funding Rate:</b> {funding_txt}
⏱ <b>الإطار:</b> تأكيد 1H | فلتر 4H
⭐ <b>الدرجة:</b> {result.get('grade', '—')}
🕒 {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC
━━━━━━━━━━━━━━━━━━━━
⚠️ البوت للتنبيه والتحليل فقط ولا ينفذ صفقات.
"""
    return msg.strip()

# ====================== المحرك الرئيسي ======================
class HybridSignalBot:
    def __init__(self):
        self.data = BinanceData()
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

    async def scan_market(self, chat_id: int = None):
        target_chat = chat_id or TELEGRAM_CHAT_ID
        if not target_chat:
            logger.error("No chat_id provided")
            return 0

        symbols = self.data.get_top_symbols()
        logger.info(f"Scanning {len(symbols)} symbols...")

        signals_found = 0

        for symbol in symbols:
            try:
                df_h4, df_h1 = self.data.get_h4_and_h1(symbol)
                if df_h4 is None or df_h1 is None:
                    continue

                funding = self.data.get_funding_rate(symbol)
                
                # استدعاء المحرك الهجين من الجزء الأول
                result = eng_evaluate_hybrid(df_h4, df_h1, funding=funding)

                if result.get("status") in ("LONG", "SHORT"):
                    text = format_signal_message(symbol, result)
                    
                    if self.bot:
                        await self.bot.send_message(
                            chat_id=target_chat,
                            text=text,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True
                        )
                    signals_found += 1
                    logger.info(f"Signal sent: {symbol} {result['status']}")

            except Exception as e:
                logger.error(f"Error on {symbol}: {e}")
                continue

        summary = f"✅ انتهى الفحص\nتم فحص {len(symbols)} عملة\nالإشارات المرسلة: {signals_found}"
        if self.bot:
            await self.bot.send_message(chat_id=target_chat, text=summary)
        
        return signals_found

# ====================== أوامر تيليجرام ======================
signal_engine = HybridSignalBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً 👋\n"
        "هذا بوت <b>التنبيهات والمعلومات</b> (Hybrid Engine)\n\n"
        "الأوامر المتاحة:\n"
        "/scan — فحص السوق الآن\n"
        "/status — حالة البوت\n",
        parse_mode=ParseMode.HTML
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ جاري فحص السوق... قد يستغرق عدة دقائق")
    try:
        count = await signal_engine.scan_market(chat_id=update.effective_chat.id)
        await msg.edit_text(f"تم الفحص ✅\nعدد الإشارات: {count}")
    except Exception as e:
        await msg.edit_text(f"حدث خطأ: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 البوت يعمل\n"
        f"الوقت: {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
        f"يفحص أعلى {TOP_SYMBOLS_LIMIT} عملة\n"
        f"المحرك: Hybrid Liquidity Sweep + Exhaustion"
    )

# ====================== التشغيل ======================
def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("BOT_TOKEN غير موجود في ملف .env")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("status", status))

    logger.info("Hybrid Signal Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
