 """
Ryma Crypto Bot — Configuration
================================
بوت تنبيهات وتحليل فني — لا ينفذ صفقات ولا يحتاج مفاتيح API لمنصات التداول.
كل الإعدادات هنا. عدّل بحذر.
"""

import os
import re
from datetime import timezone


# ============================================================
# 🔑 1) المتغيرات الأساسية (Environment Variables على Railway)
# ============================================================

def _env(key: str, default: str = "") -> str:
    return (os.getenv(key, default) or default).strip()


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, "1" if default else "0") == "1"


# --- تيليجرام ---
BOT_TOKEN        = _env("BOT_TOKEN")
FREE_CHANNEL_ID  = _env("FREE_CHANNEL_ID")   # مثال: -1001234567890
VIP_CHANNEL_ID   = _env("VIP_CHANNEL_ID")
ADMIN_ID         = _env_int("ADMIN_ID", 0)

# --- قنوات التواصل ---
CONTACT_LINK   = _env("CONTACT_LINK", "@rym_rima16")
CHANNEL_LINK   = _env("CHANNEL_LINK", "https://t.me/rym_rima16")
VIP_INVITE_URL = _env("VIP_INVITE_URL", "")

# --- إعدادات اختيارية ---
MAINTENANCE       = _env_bool("MAINTENANCE", False)
LEVERAGE_DISPLAY  = _env_int("LEVERAGE_DISPLAY", 10)  # تظهر في حاسبة المخاطر فقط
PROTECT_CONTENT   = _env_bool("PROTECT_CONTENT", True)


# ============================================================
# 💎 2) هوية البوت
# ============================================================

BRAND       = "💎 Ryma Crypto"
BRAND_SHORT = "Ryma"
BOT_VERSION = "v1.0 · 2026-11-20"

# ألوان وزخارف احترافية (Ninja style)
LINE  = "━━━━━━━━━━━━━━━━━━━━"
DOT   = "•"
ARROW = "→"


# ============================================================
# 📊 3) إعدادات الاستراتيجية (Ryma v10)
# ============================================================

# --- الفريمات ---
TF_REGIME   = "4h"    # 4 ساعات — نظام السوق
TF_CONFIRM  = "1h"    # ساعة — تأكيد الاتجاه
TF_ENTRY    = "15m"   # 15 دقيقة — توقيت الدخول

# --- الاتجاه (Trend) ---
EMA_FAST    = 20
EMA_SLOW    = 50
EMA_LONG    = 200

# --- الزخم (Momentum) ---
RSI_PERIOD       = 14
RSI_LONG_MAX     = 70     # لا نشتري فوق هذا
RSI_SHORT_MIN    = 30     # لا نبيع تحت هذا
RSI_LONG_MIN     = 45     # الحد الأدنى للشراء (زخم صحي)
RSI_SHORT_MAX    = 55     # الحد الأعلى للبيع

# --- الحجم (Volume) ---
OBV_REQUIRED     = True   # OBV إلزامي — لا صفقة بدونه
OBV_SLOPE_BARS   = 10     # عدد الشموع لقياس ميل OBV
RVOL_MIN         = 1.15   # حجم أدنى مقارنة بمتوسط 20 شمعة

# --- الوقف والأهداف ---
ATR_PERIOD       = 14
ATR_MULT         = 1.6
STOP_MIN_PCT     = 0.0035  # 0.35%
STOP_MAX_PCT     = 0.025   # 2.5%
TP_RR            = (1.0, 1.7, 2.6, 3.8)   # مضاعفات R
TP_FRACS         = (0.35, 0.30, 0.20, 0.15)  # نسبة الإغلاق

# --- الوقت ---
MAX_HOLD_HOURS   = 48     # إغلاق قسري بعد 48 ساعة (لا استثناء)
MAX_HOLD_BARS    = {      # بالشموع حسب الفريم
    "15m": 192,   # 192 × 15m = 48h
    "1h":  48,
    "4h":  12,
}

# --- إدارة المخاطر ---
RISK_PER_TRADE_PCT     = 1.0    # 1% من رأس المال لكل صفقة
MAX_OPEN_TRADES        = 5      # أقصى عدد صفقات مفتوحة
DAILY_LOSS_STREAK_STOP = 3      # إيقاف 24 ساعة بعد 3 خسائر متتالية
COOLDOWN_AFTER_LOSS    = 4      # شموع 15m نتجنب فيها العملة بعد خسارة


# ============================================================
# 💰 4) تكاليف التداول (للحساب الواقعي)
# ============================================================

TAKER_FEE       = 0.0005    # 0.05% لكل جانب
SLIPPAGE        = 0.0002    # 0.02% لكل جانب
FUNDING_8H      = 0.0001    # ~0.01% كل 8 ساعات (تقديري)
TOTAL_COST_RT   = TAKER_FEE * 2 + SLIPPAGE * 2  # التكلفة الكلية ذهاب وعودة


# ============================================================
# 🔬 5) إعدادات الباكتيست
# ============================================================

BT_DEFAULT_DAYS   = 60     # الافتراضي: شهرين
BT_IS_DAYS        = 30     # In-Sample (ضبط)
BT_OOS_DAYS       = 30     # Out-of-Sample (تحقق — لا يُلمس)
BT_MAX_BARS       = 3000   # حماية من التحميل الزائد
BT_WARMUP_BARS    = 250    # شموع تسخين المؤشرات

# عملات الباكتيست الافتراضية
BT_DEFAULT_COINS  = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI"]


# ============================================================
# 🌐 6) مصادر البيانات (Binance Public API — مجاني)
# ============================================================

BINANCE_FAPI     = "https://fapi.binance.com"
BINANCE_SPOT     = "https://api.binance.com"
KLINE_LIMIT      = 1500    # أقصى عدد شموع في طلب واحد

API_TIMEOUT      = 15      # ثانية
API_RETRIES      = 3
CACHE_TTL        = 60      # ثانية — تخزين مؤقت للشموع

TF_MS = {
    "5m":  300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h":  3_600_000,
    "4h":  14_400_000,
    "1d":  86_400_000,
}


# ============================================================
# ⏰ 7) التوقيت والمهام الخلفية
# ============================================================

SCAN_INTERVAL_MIN    = 60        # فحص السوق كل ساعة
UPDATE_INTERVAL_MIN  = 5         # تحديث الصفقات كل 5 دقائق
PUBLISH_INTERVAL_MIN = 60        # مراجعة النشر كل ساعة
CLEANUP_INTERVAL_H   = 6         # تنظيف الذاكرة كل 6 ساعات

# --- جدولة محتوى القنوات ---
FREE_MORNING_HOUR      = 8       # ملخص السوق (UTC)
FREE_EVENING_HOUR      = 20      # نتائج اليوم
VIP_DAILY_REPORT_HOUR  = 22      # تقرير VIP المسائي


# ============================================================
# 🎨 8) النشر الاحترافي
# ============================================================

# إعدادات Teaser (القناة المجانية)
TEASER_TP_DELAY_MIN   = 30       # تأخير نشر Teaser بعد تحقق TP1 (دقائق)
TEASER_MIN_GRADE      = "B"      # أقل درجة تُنشر كـ Teaser
TEASER_SHOW_RESULT    = True     # إظهار النتيجة (+3.2%) أو إخفاؤها

# إعدادات VIP
VIP_SHOW_REASONS      = False    # إخفاء أسباب الدخول (Ninja style)
VIP_LIVE_UPDATES      = True     # تحديثات لحظية (TP hit, BE, close)
VIP_EMOJI_RICH        = True     # إيموجي احترافية


# ============================================================
# 🗣️ 9) اللغة (تلقائية من تيليجرام)
# ============================================================

DEFAULT_LANG     = "en"
SUPPORTED_LANGS  = ("ar", "en")
CHANNEL_BILINGUAL = True    # القنوات تنشر بالعربي والإنجليزي معاً

def detect_lang(language_code: str | None) -> str:
    """يحدد لغة المستخدم من تيليجرام تلقائياً."""
    if not language_code:
        return DEFAULT_LANG
    code = language_code.lower()
    if code.startswith("ar"):
        return "ar"
    if code.startswith("en"):
        return "en"
    return DEFAULT_LANG


# ============================================================
# 🎯 10) قوائم العملات
# ============================================================

MAJORS = {"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
          "AVAX", "LINK", "DOT", "LTC", "TRX", "BCH", "TON", "SUI"}

STABLES = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP",
           "USDD", "USDE", "PYUSD", "EUR", "AEUR"}

# رموز ممنوعة (أسهم، ETF، أو غير مناسبة)
BLACKLIST = {"TSLA", "AAPL", "NVDA", "META", "GOOG", "AMZN",
             "MSFT", "NFLX", "AMD", "INTC", "BABA", "COIN",
             "MSTR", "GME", "AMC", "SPY", "QQQ"}

MIN_DAILY_VOLUME_USD = 5_000_000   # حجم يومي أدنى


# ============================================================
# 🖼️ 11) الروابط الثابتة
# ============================================================

URL_FUTURES = "https://www.binance.com/futures/{symbol}USDT"
URL_SPOT    = "https://www.binance.com/en/trade/{symbol}_USDT"
URL_TV      = "https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT.P"


# ============================================================
# ✅ 12) تحقق نهائي
# ============================================================

def validate() -> list[str]:
    """يرجع قائمة بالمشاكل إن وُجدت."""
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN غير موجود")
    if not FREE_CHANNEL_ID:
        problems.append("FREE_CHANNEL_ID غير موجود")
    if not VIP_CHANNEL_ID:
        problems.append("VIP_CHANNEL_ID غير موجود")
    if LEVERAGE_DISPLAY not in (1, 2, 3, 5, 10, 20, 25, 50, 75, 100):
        problems.append(f"LEVERAGE_DISPLAY={LEVERAGE_DISPLAY} غير معتاد (سيُستخدم {LEVERAGE_DISPLAY})")
    return problems


if __name__ == "__main__":
    issues = validate()
    if issues:
        print("⚠️  مشاكل في الإعدادات:")
        for i in issues:
            print(f"   • {i}")
    else:
        print("✅ كل الإعدادات سليمة.")
        print(f"   البوت: {BRAND} {BOT_VERSION}")
        print(f"   الفريمات: {TF_REGIME} + {TF_CONFIRM} + {TF_ENTRY}")
        print(f"   الإغلاق القسري: {MAX_HOLD_HOURS} ساعة")
        print(f"   أقصى صفقات: {MAX_OPEN_TRADES}")
        print(f"   الفحص: كل {SCAN_INTERVAL_MIN} دقيقة")
        print(f"   الرافعة (للعرض فقط): {LEVERAGE_DISPLAY}x")
        """
Ryma Crypto — Core Engine & Backtest
=====================================
محرك القرار (نفس الدالة للـ live والـ backtest — لا فرق) + باكتيست كامل + Walk-Forward.
لا ينفذ صفقات. يُنتج إشارات فقط.
"""

import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from config import (
    BINANCE_FAPI, KLINE_LIMIT, API_TIMEOUT, API_RETRIES, CACHE_TTL, TF_MS,
    TF_REGIME, TF_CONFIRM, TF_ENTRY,
    EMA_FAST, EMA_SLOW, EMA_LONG,
    RSI_PERIOD, RSI_LONG_MAX, RSI_SHORT_MIN, RSI_LONG_MIN, RSI_SHORT_MAX,
    OBV_SLOPE_BARS, RVOL_MIN,
    ATR_PERIOD, ATR_MULT, STOP_MIN_PCT, STOP_MAX_PCT,
    TP_RR, TP_FRACS, MAX_HOLD_HOURS, MAX_HOLD_BARS,
    TAKER_FEE, SLIPPAGE, FUNDING_8H,
    BT_WARMUP_BARS, BT_MAX_BARS,
    MIN_DAILY_VOLUME_USD, STABLES, BLACKLIST,
)

log = logging.getLogger("ryma.core")


# ============================================================
# 1) جلب البيانات
# ============================================================

_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}


def _binance_klines(symbol: str, interval: str, limit: int = 1000,
                    end_ms: Optional[int] = None) -> list:
    """طلب شموع من Binance Futures (عام، لا يحتاج مفتاح)."""
    params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": min(limit, KLINE_LIMIT)}
    if end_ms:
        params["endTime"] = int(end_ms)
    for attempt in range(API_RETRIES):
        try:
            r = requests.get(f"{BINANCE_FAPI}/fapi/v1/klines", params=params, timeout=API_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:  # rate limit
                time.sleep(2 ** attempt)
                continue
        except requests.RequestException as e:
            log.debug("kline fetch %s %s: %s", symbol, interval, e)
            time.sleep(1)
    return []


def fetch_ohlcv(symbol: str, tf: str, bars: int = 500,
                end_ms: Optional[int] = None, use_cache: bool = True) -> pd.DataFrame:
    """يرجع DataFrame موحد: [ts, open, high, low, close, volume]."""
    key = (symbol, tf, bars, end_ms)
    if use_cache and not end_ms:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1].copy()

    # Binance يسمح 1500 شمعة/طلب — نجمع على دفعات لو bars > 1500
    all_rows = []
    cursor = end_ms
    remaining = bars
    while remaining > 0:
        chunk = min(remaining, KLINE_LIMIT)
        rows = _binance_klines(symbol, tf, chunk, cursor)
        if not rows:
            break
        all_rows = rows + all_rows
        remaining -= len(rows)
        if len(rows) < chunk:
            break
        cursor = int(rows[0][0]) - 1
        if remaining > 0:
            time.sleep(0.1)

    if not all_rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_rows, columns=[
        "ts", "open", "high", "low", "close", "volume",
        "close_ts", "quote_vol", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df = df[["ts", "open", "high", "low", "close", "volume"]].copy()
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts"] = pd.to_numeric(df["ts"], errors="coerce").astype("int64")
    df = df.dropna().drop_duplicates("ts").sort_values("ts").reset_index(drop=True)

    # استبعاد الشمعة الجارية (غير مغلقة)
    if not end_ms:
        now_ms = int(time.time() * 1000)
        df = df[df["ts"] + TF_MS[tf] <= now_ms].reset_index(drop=True)

    if use_cache and not end_ms:
        _cache[key] = (time.time(), df.copy())
    return df


def daily_volume_usd(symbol: str) -> float:
    """حجم يومي تقريبي بالدولار — فلتر السيولة."""
    df = fetch_ohlcv(symbol, "1d", 2)
    if df.empty:
        return 0.0
    return float((df["volume"] * df["close"]).iloc[-1])


# ============================================================
# 2) المؤشرات الفنية (كلها causal — لا future leakage)
# ============================================================

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"],
                      (df["high"] - pc).abs(),
                      (df["low"] - pc).abs()], axis=1).max(axis=1)


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = _wilder(d.clip(lower=0), n)
    dn = _wilder((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out[(dn == 0) & up.notna()] = 100.0
    return out


def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr = _wilder(_true_range(df), n).replace(0, np.nan)
    pdi = 100 * _wilder(plus, n) / atr
    mdi = 100 * _wilder(minus, n) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return _wilder(dx, n)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """كل المؤشرات على نسخة واحدة. القرار يقرأ من هنا فقط."""
    if df.empty:
        return df
    d = df.copy()
    c = d["close"]

    # --- الاتجاه ---
    d["ema20"]  = _ema(c, EMA_FAST)
    d["ema50"]  = _ema(c, EMA_SLOW)
    d["ema200"] = _ema(c, EMA_LONG)

    # --- الزخم ---
    d["rsi"]    = _rsi(c, RSI_PERIOD)
    d["atr"]    = _wilder(_true_range(d), ATR_PERIOD)
    d["adx"]    = _adx(d)

    # --- الحجم ---
    d["rvol"]   = d["volume"] / d["volume"].rolling(20).mean().replace(0, np.nan)
    d["obv"]    = (np.sign(c.diff()).fillna(0) * d["volume"]).cumsum()
    d["obv_slope"] = d["obv"].diff(OBV_SLOPE_BARS)

    # --- MACD (للتأكيد فقط، ليس شرطاً إلزامياً) ---
    efast = _ema(c, 12)
    eslow = _ema(c, 26)
    macd = efast - eslow
    d["macd"] = macd
    d["macd_sig"] = _ema(macd, 9)
    d["macd_hist"] = macd - d["macd_sig"]

    return d


# ============================================================
# 3) محرك القرار — قلب النظام (نفس الدالة للـ live والـ backtest)
# ============================================================

@dataclass
class TradeLevels:
    entry: float
    stop: float
    risk: float
    tps: list[dict]     # [{px, r_mult, frac, hit}]
    atr: float


@dataclass
class Signal:
    symbol: str
    side: int              # +1 long, -1 short, 0 none
    grade: str             # A / B / C
    score: int
    opportunity: bool      # فرصة مؤكدة أم قراءة رادار
    price: float
    bar_ts: int
    levels: Optional[TradeLevels]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    factors: dict = field(default_factory=dict)
    setup: str = ""
    source: str = "binance_fut"

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["levels"] is None:
            d["levels"] = None
        return d


def v10_levels(price: float, side: int, atr: float) -> TradeLevels:
    """بناء الوقف والأهداف. مكان واحد فقط — يستخدمه الـ live والـ backtest."""
    if not np.isfinite(atr) or atr <= 0:
        atr = price * 0.004
    risk = min(max(atr * ATR_MULT, price * STOP_MIN_PCT), price * STOP_MAX_PCT)
    tps = []
    for r, frac in zip(TP_RR, TP_FRACS):
        tps.append({
            "px": price + side * risk * r,
            "r_mult": r,
            "frac": frac,
            "hit": False,
        })
    return TradeLevels(entry=price, stop=price - side * risk, risk=risk, tps=tps, atr=atr)


def v10_decision(
    symbol: str,
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_15m: pd.DataFrame,
    bar_index: int = -1,
) -> Optional[Signal]:
    """
    محرك Ryma v10: 4H نظام + 1H تأكيد + 15M محفز.
    - يُستدعى من الـ live بـ bar_index=-1 (آخر شمعة مغلقة)
    - يُستدعى من الباكتيست بـ bar_index محدد
    - كل الحسابات causal — تعتمد فقط على شموع مغلقة ≤ bar_index
    """
    if df_4h is None or len(df_4h) < 210:
        return None
    if df_1h is None or len(df_1h) < 205:
        return None
    if df_15m is None or len(df_15m) < 60:
        return None

    d4 = add_indicators(df_4h)
    h1 = add_indicators(df_1h)
    m15 = add_indicators(df_15m)

    a = d4.iloc[bar_index] if bar_index >= 0 else d4.iloc[-1]
    b = h1.iloc[bar_index] if bar_index >= 0 else h1.iloc[-1]
    c = m15.iloc[bar_index] if bar_index >= 0 else m15.iloc[-1]

    # --- حماية من NaN ---
    if any(pd.isna(x) for x in [a["ema50"], a["ema200"], b["ema20"], b["ema50"],
                                 b["rsi"], c["atr"]]):
        return None

    price = float(c["close"])
    if not np.isfinite(price) or price <= 0:
        return None

    # --- 1) نظام 4H ---
    bull4 = float(a["ema50"]) > float(a["ema200"]) and float(a["close"]) > float(a["ema50"])
    bear4 = float(a["ema50"]) < float(a["ema200"]) and float(a["close"]) < float(a["ema50"])
    adx4 = float(a["adx"]) if np.isfinite(a["adx"]) else 0.0

    # --- 2) اتجاه 1H ---
    bull1 = (float(b["ema20"]) > float(b["ema50"])
             and float(b["close"]) > float(b["ema50"])
             and float(b["macd_hist"]) > 0)
    bear1 = (float(b["ema20"]) < float(b["ema50"])
             and float(b["close"]) < float(b["ema50"])
             and float(b["macd_hist"]) < 0)

    # --- اختيار الاتجاه ---
    if bull4 and not bear4:
        side = 1
    elif bear4 and not bull4:
        side = -1
    else:
        side = 1 if float(a["ema50"]) >= float(a["ema200"]) else -1

    # --- 3) OBV إلزامي ---
    obv_ok = (float(c["obv_slope"]) > 0) if side == 1 else (float(c["obv_slope"]) < 0)

    # --- 4) RSI فلتر ---
    rsi15 = float(c["rsi"]) if np.isfinite(c["rsi"]) else 50.0
    if side == 1:
        rsi_ok = RSI_LONG_MIN <= rsi15 <= RSI_LONG_MAX
    else:
        rsi_ok = RSI_SHORT_MIN <= rsi15 <= RSI_SHORT_MAX

    # --- 5) محفز 15M ---
    prev20 = m15.iloc[max(0, (bar_index if bar_index >= 0 else len(m15)) - 21):
                       (bar_index if bar_index >= 0 else len(m15)) - 1]
    if len(prev20) < 20:
        return None
    prior_hi = float(prev20["high"].max())
    prior_lo = float(prev20["low"].min())
    rvol = float(c["rvol"]) if np.isfinite(c["rvol"]) else 0.0

    low_sweep  = float(c["low"]) < prior_lo and float(c["close"]) > prior_lo and float(c["close"]) > float(c["open"])
    high_sweep = float(c["high"]) > prior_hi and float(c["close"]) < prior_hi and float(c["close"]) < float(c["open"])
    brk_up = float(c["close"]) > prior_hi and rvol >= RVOL_MIN
    brk_dn = float(c["close"]) < prior_lo and rvol >= RVOL_MIN

    trigger = (low_sweep or brk_up) if side == 1 else (high_sweep or brk_dn)
    confirm = (bull1 if side == 1 else bear1) and obv_ok
    regime_ok = bull4 if side == 1 else bear4

    # --- النقاط ---
    score = 0
    if regime_ok: score += 2
    if confirm:   score += 2
    if trigger:   score += 2
    if adx4 >= 18: score += 1
    if rvol >= 1.0: score += 1
    if rsi_ok:    score += 1

    opportunity = bool(regime_ok and confirm and trigger and adx4 >= 18)
    grade = ("A" if score >= 8 else "B") if opportunity else "C"

    # --- التفسيرات ---
    reasons = [
        f"4H regime={'bullish' if bull4 else 'bearish' if bear4 else 'mixed'}, ADX={adx4:.1f}",
        f"1H confirm={'yes' if confirm else 'no'}, OBV={'ok' if obv_ok else 'no'}",
        f"15M trigger={'sweep' if (low_sweep or high_sweep) else 'breakout' if (brk_up or brk_dn) else 'no'}",
    ]
    warnings = []
    if not regime_ok: warnings.append("4H regime غير متوافق")
    if not confirm:   warnings.append("1H confirm غير مكتمل (اتجاه أو OBV)")
    if not trigger:   warnings.append("لا محفز 15M — قراءة رادار فقط")
    if adx4 < 18:     warnings.append("ADX منخفض — سوق عرضي")
    if not opportunity: warnings.append("ليست فرصة مؤكدة (درجة C)")

    atr = float(c["atr"]) if np.isfinite(c["atr"]) else price * 0.004
    levels = v10_levels(price, side, atr) if opportunity else None

    return Signal(
        symbol=symbol, side=side, grade=grade, score=score,
        opportunity=opportunity, price=price, bar_ts=int(c["ts"]),
        levels=levels, reasons=reasons, warnings=warnings,
        factors={
            "regime_4h": "bull" if bull4 else "bear" if bear4 else "mixed",
            "adx_4h": round(adx4, 2),
            "rvol_15m": round(rvol, 2),
            "rsi_15m": round(rsi15, 1),
            "obv_ok": obv_ok,
        },
        setup="MTF Hybrid (4H+1H+15M)",
    )


# ============================================================
# 4) تحليل مباشر (live)
# ============================================================

def analyze(symbol: str) -> Optional[Signal]:
    """تحليل فوري للسوق — يستخدم آخر شموع مغلقة."""
    try:
        df_4h = fetch_ohlcv(symbol, TF_REGIME, 260)
        df_1h = fetch_ohlcv(symbol, TF_CONFIRM, 250)
        df_15m = fetch_ohlcv(symbol, TF_ENTRY, 220)
        if df_4h.empty or df_1h.empty or df_15m.empty:
            return None
        return v10_decision(symbol, df_4h, df_1h, df_15m)
    except Exception as e:
        log.warning("analyze %s: %s", symbol, e)
        return None


def scan(symbols: list[str], workers: int = 4) -> list[Signal]:
    """فحص قائمة عملات بالتوازي."""
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(analyze, symbols))
    return [r for r in results if r is not None]


# ============================================================
# 5) الباكتيست (نفس المحرك — لا فرق)
# ============================================================

@dataclass
class BTTrade:
    symbol: str
    side: int
    entry_ts: int
    entry: float
    stop: float
    risk: float
    tps: list
    exit_ts: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl_pct: float = 0.0
    r_multiple: float = 0.0
    duration_hours: float = 0.0
    grade: str = "C"


def _simulate_trade(
    entry_bar_idx: int,
    df_15m: pd.DataFrame,
    levels: TradeLevels,
    side: int,
    symbol: str,
    grade: str,
) -> Optional[BTTrade]:
    """محاكاة صفقة واحدة على 15m حتى الإغلاق (TP/SL/48h)."""
    entry_ts = int(df_15m["ts"].iloc[entry_bar_idx])
    entry = levels.entry
    stop = levels.stop
    risk = levels.risk

    # نسخة قابلة للتعديل من TPs
    tps = [dict(t) for t in levels.tps]
    remaining = 1.0
    realized_pnl = 0.0

    max_bars = MAX_HOLD_BARS["15m"]
    end_idx = min(entry_bar_idx + max_bars, len(df_15m) - 1)

    exit_reason = "timeout"
    exit_price = float(df_15m["close"].iloc[end_idx])
    exit_ts = int(df_15m["ts"].iloc[end_idx])

    for i in range(entry_bar_idx + 1, end_idx + 1):
        bar = df_15m.iloc[i]
        hi, lo, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

        # فحص الوقف أولاً (أكثر تحفظاً)
        if side == 1 and lo <= stop:
            exit_reason, exit_price, exit_ts = "stop", stop, int(bar["ts"])
            realized_pnl += remaining * (stop - entry) / entry
            remaining = 0
            break
        if side == -1 and hi >= stop:
            exit_reason, exit_price, exit_ts = "stop", stop, int(bar["ts"])
            realized_pnl += remaining * (entry - stop) / entry
            remaining = 0
            break

        # فحص الأهداف
        for tp in tps:
            if tp["hit"]:
                continue
            if side == 1 and hi >= tp["px"]:
                realized_pnl += tp["frac"] * (tp["px"] - entry) / entry
                tp["hit"] = True
                remaining -= tp["frac"]
            elif side == -1 and lo <= tp["px"]:
                realized_pnl += tp["frac"] * (entry - tp["px"]) / entry
                tp["hit"] = True
                remaining -= tp["frac"]

        if remaining <= 0.01:
            exit_reason = "all_tps"
            exit_price = float(tps[-1]["px"])
            exit_ts = int(bar["ts"])
            break

    # لو ما زال هناك جزء مفتوح → إغلاق قسري
    if remaining > 0.01:
        if side == 1:
            realized_pnl += remaining * (exit_price - entry) / entry
        else:
            realized_pnl += remaining * (entry - exit_price) / entry

    # --- خصم التكاليف ---
    cost = (TAKER_FEE * 2 + SLIPPAGE * 2)
    duration_h = (exit_ts - entry_ts) / 3_600_000
    funding = FUNDING_8H * (duration_h / 8.0)
    net_pnl = realized_pnl - cost - funding

    r_multiple = (net_pnl * entry) / risk if risk > 0 else 0.0

    return BTTrade(
        symbol=symbol, side=side, entry_ts=entry_ts, entry=entry,
        stop=stop, risk=risk, tps=tps,
        exit_ts=exit_ts, exit_price=exit_price, exit_reason=exit_reason,
        pnl_pct=net_pnl * 100, r_multiple=r_multiple,
        duration_hours=duration_h, grade=grade,
    )


def backtest_symbol(
    symbol: str,
    start_ms: int,
    end_ms: int,
    max_bars: int = BT_MAX_BARS,
) -> list[BTTrade]:
    """باكتيست لعملة واحدة على فترة محددة. يستخدم نفس v10_decision."""
    df_4h = fetch_ohlcv(symbol, TF_REGIME, 1500, end_ms=end_ms, use_cache=False)
    df_1h = fetch_ohlcv(symbol, TF_CONFIRM, 1500, end_ms=end_ms, use_cache=False)
    df_15m = fetch_ohlcv(symbol, TF_ENTRY, 3000, end_ms=end_ms, use_cache=False)

    if len(df_4h) < 250 or len(df_1h) < 250 or len(df_15m) < 300:
        return []

    df_4h = df_4h[df_4h["ts"] >= start_ms].reset_index(drop=True)
    df_1h = df_1h[df_1h["ts"] >= start_ms].reset_index(drop=True)
    df_15m = df_15m[(df_15m["ts"] >= start_ms) & (df_15m["ts"] <= end_ms)].reset_index(drop=True)

    if len(df_15m) < 100:
        return []

    trades: list[BTTrade] = []
    last_entry_bar = -1

    for i in range(BT_WARMUP_BARS, min(len(df_15m), max_bars)):
        bar_ts = int(df_15m["ts"].iloc[i])

        # حماية: صفقة كل ساعة كحد أقصى لكل عملة
        if last_entry_bar >= 0 and (i - last_entry_bar) < 4:
            continue

        # جلب شموع 4H و 1H المغلقة حتى هذه اللحظة
        cur_4h = df_4h[df_4h["ts"] + TF_MS[TF_REGIME] <= bar_ts]
        cur_1h = df_1h[df_1h["ts"] + TF_MS[TF_CONFIRM] <= bar_ts]
        if len(cur_4h) < 210 or len(cur_1h) < 205:
            continue

        sig = v10_decision(
            symbol,
            cur_4h.reset_index(drop=True),
            cur_1h.reset_index(drop=True),
            df_15m.iloc[:i + 1].reset_index(drop=True),
        )
        if sig is None or not sig.opportunity or sig.levels is None:
            continue

        # محاكاة الصفقة
        trade = _simulate_trade(i, df_15m, sig.levels, sig.side, symbol, sig.grade)
        if trade is not None:
            trades.append(trade)
            last_entry_bar = i

    return trades


# ============================================================
# 6) Walk-Forward (In-Sample + Out-of-Sample)
# ============================================================

def _stats(trades: list[BTTrade]) -> dict:
    """حساب الإحصائيات من قائمة صفقات."""
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "profit_factor": 0.0, "avg_r": 0.0, "total_r": 0.0,
            "max_dd_pct": 0.0, "avg_hours": 0.0, "max_hours": 0.0,
        }
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    # equity curve للـ Drawdown
    equity = [0.0]
    for r in rs:
        equity.append(equity[-1] + r)
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = (peak - e) / max(abs(peak), 1.0) * 100
        max_dd = max(max_dd, dd)

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        "avg_r": sum(rs) / len(rs),
        "total_r": sum(rs),
        "max_dd_pct": max_dd,
        "avg_hours": sum(t.duration_hours for t in trades) / len(trades),
        "max_hours": max(t.duration_hours for t in trades),
    }


def walk_forward(
    symbols: list[str],
    days: int = 60,
    is_days: int = 30,
    oos_days: int = 30,
    progress_cb=None,
) -> dict:
    """
    Walk-Forward: يقسم الفترة إلى IS + OOS.
    لا يُعدّل أي شيء في OOS — فقط قياس أداء.
    """
    now_ms = int(time.time() * 1000)
    total_ms = days * 86_400_000
    start_ms = now_ms - total_ms
    split_ms = start_ms + is_days * 86_400_000
    end_ms = start_ms + (is_days + oos_days) * 86_400_000
    if end_ms > now_ms:
        end_ms = now_ms

    all_is: list[BTTrade] = []
    all_oos: list[BTTrade] = []
    per_symbol: dict[str, dict] = {}

    for idx, sym in enumerate(symbols):
        if progress_cb:
            progress_cb(idx, len(symbols), sym)

        # In-Sample
        is_trades = backtest_symbol(sym, start_ms, split_ms)
        # Out-of-Sample
        oos_trades = backtest_symbol(sym, split_ms, end_ms)

        all_is.extend(is_trades)
        all_oos.extend(oos_trades)
        per_symbol[sym] = {
            "is": _stats(is_trades),
            "oos": _stats(oos_trades),
        }

    return {
        "period": {
            "start": start_ms,
            "split": split_ms,
            "end": end_ms,
            "days_total": days,
            "days_is": is_days,
            "days_oos": oos_days,
        },
        "in_sample": _stats(all_is),
        "out_of_sample": _stats(all_oos),
        "per_symbol": per_symbol,
        "all_trades_is": all_is,
        "all_trades_oos": all_oos,
    }


# ============================================================
# 7) اختبار سريع
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print("📥 جلب BTC...")
    df = fetch_ohlcv("BTC", "1h", 500)
    print(f"   عدد الشموع: {len(df)}")
    print(f"   آخر سعر: ${df['close'].iloc[-1]:,.2f}")

    print("\n🔍 تحليل BTC...")
    sig = analyze("BTC")
    if sig:
        print(f"   الاتجاه: {'LONG' if sig.side == 1 else 'SHORT'}")
        print(f"   الدرجة: {sig.grade} (score={sig.score})")
        print(f"   فرصة مؤكدة: {sig.opportunity}")
        if sig.levels:
            print(f"   الدخول: {sig.levels.entry:.2f}")
            print(f"   الوقف: {sig.levels.stop:.2f}")
            for i, tp in enumerate(sig.levels.tps, 1):
                print(f"   TP{i}: {tp['px']:.2f} ({tp['r_mult']}R)")
    else:
        print("   لا إشارة حالياً")

    print("\n📊 باكتيست BTC (60 يوم)...")
    wf = walk_forward(["BTC"], days=60)
    print(f"\n   In-Sample (30d):")
    for k, v in wf["in_sample"].items():
        print(f"     {k}: {v}")
    print(f"\n   Out-of-Sample (30d):")
    for k, v in wf["out_of_sample"].items():
        print(f"     {k}: {v}")
