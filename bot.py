import os, io, re, json, time, asyncio, logging, threading, functools, hashlib, hmac
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests, ccxt, matplotlib
import urllib.parse, concurrent.futures
# Optional adaptive-ML stack. Core bot remains available if not installed.
try:
    import joblib as _joblib
except Exception:
    _joblib = None
try:
    from sklearn.cluster import KMeans as _KMeans
    from sklearn.preprocessing import StandardScaler as _StandardScaler
except Exception:
    _KMeans = _StandardScaler = None
# ===================== RYMA HYBRID SIGNAL CORE =====================
# The live direction/entry decision is the deterministic 4H + 1H + 15M rules engine.
# Optional local ML features are auxiliary and are never presented as calibrated confidence.
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = ["DejaVu Sans", "Noto Naskh Arabic", "Amiri", "sans-serif"]
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import FancyBboxPatch, Rectangle, Polygon
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    def _ar_shape(s): return get_display(arabic_reshaper.reshape(s))
except Exception:
    def _ar_shape(s): return s
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      BotCommand, LinkPreviewOptions, CopyTextButton)
from telegram.constants import ParseMode
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler,
                          ContextTypes, filters, CallbackQueryHandler, TypeHandler)
try:
    from aiohttp import web as _aiohttp_web
except Exception:
    _aiohttp_web = None

def _e(k, d=""): return (os.getenv(k, d) or d).strip()
def _int(k, d=0):
    try: return int(_e(k, str(d)))
    except Exception: return d
def _chat(v):
    v = (v or "").strip()
    if not v: return None
    return int(v) if re.fullmatch(r"-?\d+", v) else v

BOT_TOKEN = _e("BOT_TOKEN")
CHANNEL_ID = _chat(_e("CHANNEL_ID"))
VIP_CHANNEL_ID = _chat(_e("VIP_CHANNEL_ID"))
ADMIN_ID = _int("ADMIN_ID", 0)  
GIST_ID = _e("GIST_ID")
GITHUB_TOKEN = _e("GITHUB_TOKEN")
WHALE_ALERT_KEY = _e("WHALE_ALERT_KEY")
ETHERSCAN_KEY = _e("ETHERSCAN_API_KEY")
ETH_WATCH = [a.strip().lower() for a in _e("ETH_EXCHANGE_ADDRESSES").split(",") if a.strip()]
ETH_MIN_TX = 100
CONTACT_LINK = _e("CONTACT_LINK")
CHANNEL_LINK = _e("CHANNEL_LINK", "https://t.me/rym_rima16")
VIP_INVITE_LINK = _e("VIP_INVITE_LINK", "https://t.me/+gTMJiBiiC_IyZjZk")
CONTACT_URL = f"https://t.me/{CONTACT_LINK.lstrip('@')}" if CONTACT_LINK else CHANNEL_LINK
PAYMENT_INFO = _e("PAYMENT_INFO")
PROTECT = _e("PROTECT_CONTENT", "1") == "1"
# Adaptive AI layer (optional until a properly walk-forward-trained model is deployed)
RYMA_AI_ENABLED = _e("RYMA_AI_ENABLED", "1") == "1"
RYMA_AI_PROVIDER = "hybrid_rules"  # local deterministic MTF rules; optional ML is auxiliary
RYMA_AI_API_KEY = _e("RYMA_AI_API_KEY", _e("OPENAI_API_KEY"))
RYMA_AI_BASE_URL = _e("RYMA_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
RYMA_AI_MODEL = "Ryma v10 MTF rules"
RYMA_AI_TIMEOUT = max(15, _int("RYMA_AI_TIMEOUT", 45))
RYMA_AI_MAX_TOKENS = max(300, min(3000, _int("RYMA_AI_MAX_TOKENS", 600)))
# Free-tier protection: serialize calls, keep below the observed 8 RPM ceiling,
# and cap daily requests. Values can be overridden in Railway if Google changes quotas.
RYMA_AI_MIN_INTERVAL = max(5, _int("RYMA_AI_MIN_INTERVAL", 8))
RYMA_AI_DAILY_CALL_CAP = max(1, _int("RYMA_AI_DAILY_CALL_CAP", 20))
RYMA_AI_USAGE_PATH = _e("RYMA_AI_USAGE_PATH", "/app/ryma_ai_usage.json")
RYMA_AI_BACKTEST_MAX_CALLS = max(100, min(3000, _int("RYMA_AI_BACKTEST_MAX_CALLS", 1200)))
RYMA_AI_TEMPERATURE = 0.1
RYMA_ML_ENABLED = True  # optional auxiliary classifier; the MTF rules engine controls live decisions
RYMA_ML_MODEL_PATH = "models/ryma_local_model.joblib"
RYMA_ML_MIN_PROB = 0.55
RYMA_AI_CACHE_TTL = max(60, _int("RYMA_AI_CACHE_TTL", 300))
RYMA_AI_DECISION_CACHE_TTL = max(300, _int("RYMA_AI_DECISION_CACHE_TTL", 21600))
RYMA_CVD_TRADES = max(100, min(1000, _int("RYMA_CVD_TRADES", 500)))
MAINTENANCE = _e("MAINTENANCE", "0") == "1"
BRAND = "💎 Ryma Crypto 💎"
BOT_VERSION = "Ryma Crypto v10 Adaptive Hybrid Engine RC7.0 · 2026-11-20"
# PRINCIPLE: alerts & analysis only — never places exchange orders
CYCLE_RADAR = 900
WHALE_MIN_USD = 500000

# Optional TrendSpider -> Ryma webhook bridge. Disabled until Railway variables are set.
TRENDSPIDER_ENABLED = _e("TRENDSPIDER_ENABLED", "0") == "1"
TRENDSPIDER_SECRET = _e("TRENDSPIDER_SECRET")
TRENDSPIDER_PORT = max(1, min(65535, _int("PORT", _int("TRENDSPIDER_PORT", 8080))))
TRENDSPIDER_MAX_SKEW_SEC = max(30, min(1800, _int("TRENDSPIDER_MAX_SKEW_SEC", 300)))
TRENDSPIDER_QUEUE_MAX = max(10, min(1000, _int("TRENDSPIDER_QUEUE_MAX", 100)))

RISK_WARNING_AR = "⚠️ <i>التداول ينطوي على مخاطر عالية. البوت للتنبيه والتحليل فقط ولا ينفّذ صفقات. ليست نصيحة مالية.</i>"
RISK_WARNING_EN = "⚠️ <i>Trading involves high risk. This bot is alerts/analysis only and does not execute trades. Not financial advice.</i>"
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

def _btn(text, style=None, **kw):
    """أزرار بمظهر سكانر: 🟢 أخضر / 🔵 أزرق / 🟡 ذهبي / 🔴 خطر.
    تيليجرام لا يدعم ألوان CSS؛ نعتمد إيموجي + style إن توفر."""
    t = text or ""
    if style is None:
        if t.startswith("❌") or "إغلاق" in t or "Close" in t:
            style = "danger"
        elif any(x in t for x in ("اشترك", "Subscribe", "VIP", "ذهبية", "سبوت", "أرباح", "🚀", "🌱")):
            style = "success"
        elif any(x in t for x in ("شارت", "Chart", "تحديث", "Refresh", "تحليل", "رادار", "فحص", "⚡", "📊")):
            style = "primary"
        elif any(x in t for x in ("ذهبي", "💎", "⭐", "🏆")):
            style = "primary"
    # بادئات لونية إن لم تكن موجودة
    if style == "success" and not any(t.startswith(e) for e in ("🟢", "✅", "🌱", "🚀", "💎")):
        t = "🟢 " + t
    elif style == "primary" and not any(t.startswith(e) for e in ("🔵", "⚡", "📊", "🔮", "🐋")):
        t = "🔵 " + t
    elif style == "danger" and not t.startswith(("❌", "🔴")):
        t = "🔴 " + t
    try:
        return InlineKeyboardButton(t, style=style, **kw) if style else InlineKeyboardButton(t, **kw)
    except TypeError:
        return InlineKeyboardButton(t, **kw)

EXCLUDE_TICKERS = {"MU","SPCX","SNXX","SOXS","CL","TSLA","AAPL","NVDA","META","GOOG","AMZN","MSFT","NFLX","AMD","INTC","BABA","COIN","MSTR","GME","AMC"}

REFERRAL_LINKS = {
    "binance": ("Binance","https://www.binance.com/register?ref=WELCOMBAKC"),
    "okx":     ("OKX","https://okx.com/join/QW22UB2Y"),
    "bybit":   ("Bybit","https://www.bybit.com/invite?ref=A3YBDWZ"),
    "gateio":  ("Gate","https://www.gate.com/ar/referral/registry?ref=VANEUF1XBW"),
    "mexc":    ("MEXC","https://s.mexc.com/referral/o0HbNZxKxg"),
    "kucoin":  ("KuCoin","https://www.kucoin.com/r/rf/CXEJQGFK"),
    "bitget":  ("Bitget","https://www.bitget.com/ar/referral/register?clacCode=UX7TVDCT"),
    "bingx":   ("BingX","https://bingxdao.com/invite/6Y2TXMV4/"),
}

PLATFORM_META = {
    "binance":{"emoji":"🟡","name":"Binance Square","tags":"#Binance","ref":"binance"},
    "bybit":{"emoji":"🔵","name":"Bybit","tags":"#Bybit","ref":"bybit"},
    "okx":{"emoji":"⚫","name":"OKX","tags":"#OKX","ref":"okx"},
    "bitget":{"emoji":"🟢","name":"Bitget","tags":"#Bitget","ref":"bitget"},
    "kucoin":{"emoji":"🟢","name":"KuCoin","tags":"#KuCoin","ref":"kucoin"},
    "gateio":{"emoji":"⚪","name":"Gate.io","tags":"#Gate","ref":"gateio"},
    "twitter":{"emoji":"🐦","name":"Twitter (X)","tags":"#Crypto","ref":"binance"},
    "telegram":{"emoji":"📱","name":"Telegram","tags":"#Crypto","ref":"binance"},
    "facebook":{"emoji":"📘","name":"Facebook","tags":"#Crypto","ref":"binance"},
    "whatsapp":{"emoji":"💬","name":"WhatsApp","tags":"#Crypto","ref":"binance"},
    "reddit":{"emoji":"🔴","name":"Reddit","tags":"#Crypto","ref":"binance"},
    "discord":{"emoji":"🎮","name":"Discord","tags":"#Crypto","ref":"binance"},
}

def referral_for(source):
    s = (source or "binance").lower()
    if s.startswith("binance"): s = "binance"
    return REFERRAL_LINKS.get(s, REFERRAL_LINKS["binance"])

def display_source(src):
    s = (src or "binance_fut").lower()
    if s in ("binance","binance_fut","binance_usdm"): return "BINANCE FUTURES"
    if s == "binance_spot_mirror": return "BINANCE SPOT (DEGRADED)"
    if s.endswith("_linear_swap"): return f"{s.split('_',1)[0].upper()} USDT-M FUTURES"
    if "future" in s or "swap" in s or "perp" in s: return s.upper()
    return f"{s.upper()} (CHECK MARKET TYPE)"

def coin_link(sym, source="binance_fut"):
    s = (source or "binance").lower(); u = sym.upper()
    if s.endswith("_linear_swap"): s=s.split("_",1)[0]
    if s in ("binance_fut", "binance_usdm", "binance"): return f"https://www.binance.com/futures/{u}USDT?ref=WELCOMBAKC"
    if s == "okx": return f"https://www.okx.com/trade-swap/{u.lower()}-usdt-swap"
    if s == "bybit": return f"https://www.bybit.com/trade/usdt/{u}USDT"
    if s == "gateio": return f"https://www.gate.com/futures/USDT/{u}_USDT"
    if s == "mexc": return f"https://futures.mexc.com/exchange/{u}_USDT"
    if s == "kucoin": return f"https://www.kucoin.com/futures/trade/{u}USDTM"
    if s == "bitget": return f"https://www.bitget.com/futures/usdt/{u}USDT"
    if s == "bingx": return f"https://bingx.com/en-us/perpetual/{u}-USDT/"
    return REFERRAL_LINKS["binance"][1]

FAST_EXCHANGES = ["okx","bybit","gateio","mexc","kucoin","bitget","htx","binance"]
EXCHANGES = ["okx","bybit","gateio","mexc","kucoin","bitget","htx","binance","bingx","lbank","bitmart","poloniex"]
BINANCE_FAPI_BASE = "https://fapi.binance.com"
BINANCE_SPOT_MIRRORS = ["https://data-api.binance.vision","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com"]
BINANCE_INTERVAL_MAP = {"15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d"}

MAJORS = {"BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","LINK","DOT","LTC","TRX"}
CORE_COINS = ["BTC","ETH","BNB","XRP","ADA","DOGE","AVAX","LTC","NEAR","SUI","ATOM","TRX","BONK","OP"]
MEME_COINS = ["TIA","FLOKI","INJ"] 
ALPHA_COINS = ["ETH","BNB","SOL","SUI","NEAR","INJ","TIA","FLOKI","APT","ARB"]
COINS = CORE_COINS + MEME_COINS
WEAK_COINS = set()
DAILY_EXCLUDE = {"BTC","ETH","BNB","SOL","XRP","DOGE","ADA","TRX","LTC","DOT","LINK","AVAX","TON","SHIB","PEPE","USDC","FDUSD","TUSD","USDT","DAI","BUSD","USDP","USDD","USDE","PYUSD","EUR","AEUR"} | EXCLUDE_TICKERS
STABLES = {"USDC","FDUSD","TUSD","USDT","DAI","BUSD","USDP","USDD","USDE","PYUSD","EUR","AEUR"}

POINTS_DAILY = 1; POINTS_PROMO = 5; POINTS_REFERRAL = 20
VIP_THRESHOLD = 200; VIP_REWARD_DAYS = 1
ALPHA_MAJORS_EXCLUDE = {"BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","LINK","DOT","LTC","TRX","TON","SHIB","PEPE","USDC","FDUSD","TUSD","USDT","DAI","BUSD","USDP","USDD","USDE","PYUSD"}
TRIAL_DAYS = 7
VIP_FORCE_DAY = 12 
FEE, SLIP = 0.0008, 0.0005
TF_MS = {"15m":900_000,"30m":1_800_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000}
CANDLE_TTL, PRICE_TTL = 180, 45
MIN_BARS = 215; CHART_BARS = 90; SCAN_WORKERS = 4; MAX_OPEN = 100
VIP_POSTS_PER_CYCLE = 5; FREE_POSTS_PER_CYCLE = 10; FREE_MAX_PER_DAY = 40
CYCLE_AUTOPOST=900; CYCLE_SHORT_FREE=14400; CYCLE_MARKET_SUMMARY=16200
CYCLE_PREDICT=14400; CYCLE_ALPHA_SUMMARY=14400; CYCLE_BOTTOMS_AUTO=21600
CYCLE_GOLDEN=18000; CYCLE_PROMO=604800; CROSS_CHECK_INTERVAL=3600
SMART_PROFIT_DAYS=99; SMART_MAX_AGE_DAYS=3; SMART_FORCE_DAYS=99   # live-only early exits off: live == backtest (48h time stop only)
SMART_FILL_TRIGGER=0.8; CLEANUP_EVERY_CYCLES=12
BE_OFFSET_R=0.05; TRAIL_ATR=2.0; MAX_HOLD_HOURS=48; MAX_HOLD=12   # hard cap: 48 hours (12 x 4H bars)

# ===== Ryma v10: single source of truth (live signals, radars, tracking and /bt all read THESE numbers) =====
V10_RR=(1.0,1.7,2.6,3.8); V10_FRACS=(0.35,0.30,0.20,0.15)      # targets in R and the share closed at each
V10_ATR_MULT=1.6; V10_RISK_MIN_PCT=0.0035; V10_RISK_MAX_PCT=0.025  # stop = 1.6*ATR(15m) clamped to 0.35%..2.5%
V10_EXEC_TF="15m"; V10_MAX_HOLD_BARS=192                          # 192 x 15m = 48 hours maximum
FUNDING_8H=0.0001                                                # funding estimate charged per 8h held (live + /bt)
ALLOW_C_POSTS=_e("ALLOW_C_POSTS","0")=="1"                      # grade C = radar only (no confirmed 15M trigger): never published unless explicitly enabled
FREE_TP_COUNT=3; VIP_TP_COUNT=4                                  # FREE sees 3 targets, VIP sees 4
VIP_B_PER_DAY=_int("VIP_B_PER_DAY",3); VIP_B_MIN_SCORE=_int("VIP_B_MIN_SCORE",7)   # best B setups are ALSO sent to VIP (4 targets)
VIP_RESULTS_IN_FREE=_e("VIP_RESULTS_IN_FREE","1")=="1"         # mirror VIP results (wins AND losses) into FREE as teasers
VIP_CHART_MODE=_e("VIP_CHART_MODE","pattern").lower()           # pattern = chart only for A trades / when a pattern is detected
RYMA_AUTOPOST=_e("RYMA_AUTOPOST","0" if TRENDSPIDER_ENABLED else "1")=="1"   # own scanner: off when TrendSpider is the trigger
SHORT_FREE_LOOP=_e("SHORT_FREE_LOOP","0")=="1"                  # legacy RSI-only short list for FREE: off by default
BT_MAX_DECISIONS=max(200,min(50000,_int("BT_MAX_DECISIONS",20000)))
SHADOW_MAX_OPEN=60

# ===== v10 tunables: ONE parameter set shared by live signals, tracking and every backtest ========================
V10_DEFAULTS=dict(stop_tf="15m",stop_k=1.6,min_adx=0.0,cooldown=0,rr="base")
V10_RR_SETS={"base":(1.0,1.7,2.6,3.8),"runner":(1.5,2.5,4.0,6.0)}
REAL_FEE=0.0005; REAL_SLIP=0.0002     # realistic majors cost (taker 0.05% + 0.02% slippage per side), shown next to the configured one

def _v10_clean(p):
    out=dict(V10_DEFAULTS); out.update(p or {})
    if out["stop_tf"] not in ("15m","1h"): raise ValueError("stop_tf must be 15m or 1h")
    out["stop_k"]=float(out["stop_k"]); out["min_adx"]=float(out["min_adx"]); out["cooldown"]=int(out["cooldown"])
    if not 0.5<=out["stop_k"]<=3.0: raise ValueError("stop_k must be within 0.5..3")
    if not 0<=out["min_adx"]<=40: raise ValueError("min_adx must be within 0..40")
    if not 0<=out["cooldown"]<=96: raise ValueError("cooldown must be within 0..96 (15m bars)")
    if out["rr"] not in V10_RR_SETS: raise ValueError("rr must be base or runner")
    return out

def v10_params(override=None):
    p=dict(V10_DEFAULTS)
    try:
        with store.lock: p.update(store.data.get("settings",{}).get("v10_params") or {})
    except Exception: pass
    if override: p.update(override)
    try: return _v10_clean(p)
    except ValueError: return dict(V10_DEFAULTS)

def in_cooldown(sym):
    """After a LOSING real trade on a coin, skip that coin for `cooldown` 15m bars (same rule in /bt)."""
    n=v10_params()["cooldown"]
    if n<=0: return False
    with store.lock:
        h=[x for x in store.data.get("history",[]) if x.get("coin")==sym and not x.get("shadow") and x.get("setup")!="RADAR"]
    if not h: return False
    last=max(h,key=lambda x:x.get("closed") or 0)
    return (last.get("R") or 0)<0 and int(time.time()*1000)-int(last.get("closed") or 0)<n*TF_MS["15m"]
MIN_DAILY_VOLUME_USD=5_000_000; VIP_MIN_LIQUIDITY=3_000_000; RISK_SIZE={"A+":0.10,"A":0.08,"B":0.05,"C":0.02}
PREDICT_BB_SQZ=0.75; PREDICT_VOL_BUILDUP=1.4; PREDICT_RSI_NEUTRAL=(42,58)
PREDICT_OI_CHANGE_MIN=3.0; PREDICT_FUNDING_EXTREME=0.05; PREDICT_TOP_N=10; PREDICT_TF="4h"
BOTTOM_MIN_DIFF=-60; BOTTOM_MAX_DIFF=-10; BOTTOM_RSI_RANGE=(25,55)
BOTTOM_MIN_VOL_RATIO=0.8; BOTTOM_MIN_REBOUND=1.5; BOTTOM_AVOID_BREAK=0.98
SR_LOOKBACK=50; SR_MERGE_PCT=0.5
FIB_LEVELS=[0.236,0.382,0.5,0.618,0.786,1.272,1.618]
MACD_FAST,MACD_SLOW,MACD_SIGNAL=12,26,9
DAILY_LONGS=2; DAILY_SHORTS=2; DAILY_TP_COUNT=4; DAILY_TOP_N=20
DAILY_MIN_CHANGE=12.0; DAILY_MIN_VOLUME=5_000_000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ryma")
# httpx يطبع رابط كل طلب وفيه التوكن كاملاً: نخفضه حتى لا يتسرب التوكن في الـlogs ولتقليل الضجيج
for _n in ("httpx","httpcore","telegram.ext.Updater"): logging.getLogger(_n).setLevel(logging.WARNING)
START_TS = time.time(); DAY = 86400
def now_s(): return int(time.time())

KEYS = ["users","vip","signals","history","posted","settings","portfolios"]
DEFAULTS = {"users":{},"vip":{},"signals":[],"history":[],"posted":{},"portfolios":{},
    "settings":{"maintenance":_e("MAINTENANCE","0")=="1","multi_exchange":True}}

class Store:
    def __init__(self, local_path="data_local.json"):
        self.lock=threading.RLock(); self.local_path=local_path
        self.data=json.loads(json.dumps(DEFAULTS)); self.dirty=set()
        self.fname={k:k+".json" for k in KEYS}
        self.remote_ok,self.remote_msg=False,"in-memory"; self._load()
    def _hdr(self): return {"Authorization":f"Bearer {GITHUB_TOKEN}","Accept":"application/vnd.github+json"}
    def _load(self):
        if GIST_ID and GITHUB_TOKEN:
            try:
                r=requests.get(f"https://api.github.com/gists/{GIST_ID}",headers=self._hdr(),timeout=20)
                r.raise_for_status(); files=r.json().get("files",{})
                for k in KEYS:
                    f=files.get(k+".json")
                    if not f: continue
                    txt=f.get("content")
                    if f.get("truncated"):
                        txt=requests.get(f["raw_url"],headers=self._hdr(),timeout=20).text
                    val=json.loads(txt) if txt and txt.strip() else DEFAULTS[k]
                    if type(val) is type(DEFAULTS[k]): self.data[k]=val
                self.remote_ok,self.remote_msg=True,"Gist OK"; return
            except Exception as e: self.remote_msg=f"Gist fail: {str(e)[:60]}"
        if os.path.exists(self.local_path):
            try:
                with open(self.local_path,encoding="utf-8") as fh: self.data.update(json.load(fh))
            except Exception as _ex: log.debug('ignored: %s', _ex)
    def save(self,*keys):
        with self.lock: self.dirty.update(keys)
    def flush(self):
        with self.lock:
            keys = list(self.dirty)
            if not keys: return
            if "users" in keys and len(json.dumps(self.data["users"], ensure_ascii=False)) > 900_000:
                cutoff = time.time() - 90*DAY
                vip_ids = set(self.data.get("vip", {}).keys())
                self.data["users"] = {k: v for k, v in self.data["users"].items()
                                      if (v.get("last_seen") or 0) > cutoff or k in vip_ids}
            if "history" in keys:
                self.data["history"] = self.data["history"][-500:]
            snap = {k: json.dumps(self.data[k], ensure_ascii=False) for k in keys}
            if not self.remote_ok:
                try:
                    with open(self.local_path, "w", encoding="utf-8") as fh:
                        json.dump(self.data, fh, ensure_ascii=False)
                except Exception as e:
                    self.remote_msg = f"local save fail: {str(e)[:60]}"
                self.dirty.clear(); return
        try:
            r = requests.patch(f"https://api.github.com/gists/{GIST_ID}",
                               headers=self._hdr(), timeout=25,
                               json={"files":{self.fname[k]:{"content":snap[k]} for k in keys}})
            r.raise_for_status()
            with self.lock: self.dirty.difference_update(keys)
        except Exception as e:
            self.remote_msg = f"flush fail: {str(e)[:60]}"
    def start_flusher(self,every=20):
        def loop():
            while True:
                time.sleep(every)
                try: self.flush()
                except Exception as _ex: log.debug('ignored: %s', _ex)
        threading.Thread(target=loop,daemon=True).start()
store=Store()

def detect_lang(text):
    if not text: return "ar"
    if re.search(r'[\u0600-\u06FF]',text): return "ar"
    if re.search(r'[a-zA-Z]',text): return "en"
    return "ar"

def get_user_lang(uid):
    with store.lock:
        u=store.data["users"].get(str(uid),{})
        return u.get("lang","en")

def set_user_lang(uid,lang):
    with store.lock:
        if str(uid) in store.data["users"]:
            store.data["users"][str(uid)]["lang"]=lang; store.save("users")

TEXTS = {
    "ar": {
        "analyzing": "⏳ جارٍ تحليل {sym}...",
        "not_found": "❌ لم يتم العثور على العملة: {sym}",
        "no_data": "⚠️ البيانات غير متوفرة حالياً.",
        "error": "⚠️ حدث خطأ أثناء التحليل.",
        "invalid_symbol": "📝 إدخال رمز عملة صحيح.",
        "not_supported": "⛔ هذا الرمز غير مدعوم (أسهم أو غير متاح).",
        "maintenance": "🔧 صيانة.\n📞 {contact}",
        "blocked": "⛔ انتهت التجربة.\n📞 {contact}",
        "warning_trial": "⚠️ تنبيه: تجربتك المجانية تنتهي خلال {left} أيام.\n💎 استعد للاشتراك في VIP للاستمرار دون انقطاع.",
        "wait_3s": "⏳ انتظار 3 ثوان...",
        "vip_only": "🔒 VIP فقط",
        "admin_only": "⛔ للأدمن فقط",
        "welcome": "أهلاً {name}! 👋\n\nمرحباً بك في بوت **Ryma Crypto** للتحليل الفني الذكي.\n\n📌 **طريقة الاستخدام:**\nفقط أرسل اسم أي عملة (مثل BTC أو ETH) وسأقوم بتحليلها فوراً وتزويدك بـ:\n- نقاط الدخول والخروج.\n- 4 أهداف ذكية.\n- وقف الخسارة المناسب.\n- النماذج الفنية.\n\n📊 الأزرار بالأسفل تتيح لك الوصول السريع لحاسبة المخاطر، محفظتك، والشارتات.",
        "risk_btn": "🧮 حاسبة المخاطر",
        "port_btn": "📊 محفظتي",
        "chart_btn": "📈 شارت TradingView",
        "pat_btn": "🕯️ النماذج",
        "news_btn": "📰 الأخبار",
        "refs_btn": "🌐 المنصات",
        "vip_btn": "💎 اشترك VIP",
        "free_btn": "🆓 القناة المجانية",
        "contact_btn": "📞 تواصل معنا",
        "refresh_btn": "🔄 تحديث",
        "close_btn": "❌ إغلاق",
        "calc_prompt": "🧮 **حاسبة إدارة المخاطر ({sym})**\n\nأرسل رأس مالك ونسبة المخاطرة مفصولة بمسافة.\nمثال: `1000 2`",
        "port_prompt": "📊 **إضافة {sym} للمحفظة**\n\nكم المبلغ الذي استثمرته بالدولار؟\nمثال: `100`",
        "risk_res": "🧮 **نتيجة إدارة المخاطر لـ {sym}:**\n\n💰 رأس المال: ${cap}\n🛑 المخاطرة ({risk_pct}%): ${risk_amt:.2f}\n➡️ حجم العقد: {size:.4f}\n💵 قيمة الصفقة: ${value:.2f}\n\n⚙️ **الرافعة المقترحة:** {lev:.1f}x\n<i>(استخدم دائماً العزل Isolated)</i>",
        "risk_err": "⚠️ صيغة خاطئة (مثال: 1000 2)",
        "port_added": "✅ تمت إضافة {sym} إلى محفظتك (${amount}).",
        "port_err": "⚠️ أرسل رقماً صحيحاً (مثال: 100)",
    },
    "en": {
        "analyzing": "⏳ Analyzing {sym}...",
        "not_found": "❌ Coin not found: {sym}",
        "no_data": "⚠️ Data currently unavailable.",
        "error": "⚠️ An error occurred.",
        "invalid_symbol": "📝 Please enter a valid coin symbol.",
        "not_supported": "⛔ This symbol is not supported.",
        "maintenance": "🔧 Maintenance.\n📞 {contact}",
        "blocked": "⛔ Trial expired.\n📞 {contact}",
        "warning_trial": "⚠️ Heads up: your free trial ends in {left} days.\n💎 Get ready to subscribe to VIP to keep access.",
        "wait_3s": "⏳ Please wait 3 seconds...",
        "vip_only": "🔒 VIP only",
        "admin_only": "⛔ Admin only",
        "welcome": "Welcome {name}! 👋\n\nWelcome to **Ryma Crypto Bot** for smart technical analysis.\n\n📌 **How to use:**\nJust send any coin symbol (e.g., BTC or ETH) and I will instantly analyze it for you, providing:\n- Entry and exit points.\n- 4 smart targets.\n- Proper Stop Loss.\n- Chart patterns.\n\n📊 Use the buttons below for quick access to the Risk Calculator, Portfolio, and Charts.",
        "risk_btn": "🧮 Risk Calculator",
        "port_btn": "📊 Portfolio",
        "chart_btn": "📈 TradingView Chart",
        "pat_btn": "🕯️ Patterns",
        "news_btn": "📰 News",
        "refs_btn": "🌐 Exchanges",
        "vip_btn": "💎 Subscribe VIP",
        "free_btn": "🆓 Free Channel",
        "contact_btn": "📞 Contact Us",
        "refresh_btn": "🔄 Refresh",
        "close_btn": "❌ Close",
        "calc_prompt": "🧮 **Risk Calculator ({sym})**\n\nSend your capital and risk % separated by a space.\nExample: `1000 2`",
        "port_prompt": "📊 **Add {sym} to Portfolio**\n\nHow much did you invest in USD?\nExample: `100`",
        "risk_res": "🧮 **Risk Management Result for {sym}:**\n\n💰 Capital: ${cap}\n🛑 Risk ({risk_pct}%): ${risk_amt:.2f}\n➡️ Position Size: {size:.4f}\n💵 Position Value: ${value:.2f}\n\n⚙️ **Suggested Leverage:** {lev:.1f}x\n<i>(Always use Isolated margin)</i>",
        "risk_err": "⚠️ Invalid format (e.g., 1000 2)",
        "port_added": "✅ {sym} added to your portfolio (${amount}).",
        "port_err": "⚠️ Send a valid number (e.g., 100)",
    }
}

def t(key, lang="en", **kw):
    text = TEXTS.get(lang, TEXTS["en"]).get(key, TEXTS["en"].get(key, key))
    try: return text.format(**kw)
    except Exception: return text

def is_maintenance():
    with store.lock: return bool(store.data.get("settings",{}).get("maintenance",False))
def set_maintenance(flag):
    with store.lock:
        store.data.setdefault("settings",{})["maintenance"]=bool(flag); store.save("settings")
    return bool(flag)
def is_multi_exchange():
    with store.lock: return bool(store.data.get("settings",{}).get("multi_exchange",True))
def set_multi_exchange(flag):
    with store.lock:
        store.data.setdefault("settings",{})["multi_exchange"]=bool(flag); store.save("settings")
    return bool(flag)
def touch_user(user,cmd="text"):
    uid=str(user.id)
    with store.lock:
        u=store.data["users"].get(uid) or dict(id=user.id,first_seen=now_s(),requests=0,cmds={},last_cmd=None,points=0)
        if "lang" not in u:
            u["lang"] = "ar" if (user.language_code or "").startswith("ar") else "en"
        last_seen_date=dt.datetime.fromtimestamp(u.get("last_seen",0)).date()
        current_date=dt.datetime.now().date()
        if current_date>last_seen_date: u["points"]=u.get("points",0)+POINTS_DAILY
        u.update(name=getattr(user,"first_name","") or "",username=getattr(user,"username","") or "",last_seen=now_s())
        u["requests"]=u.get("requests",0)+1; u["last_cmd"]=cmd
        u["cmds"]=u.get("cmds") or {}; u["cmds"][cmd]=u["cmds"].get(cmd,0)+1
        store.data["users"][uid]=u; store.save("users")
    return u

def vip_until(uid): return int(store.data["vip"].get(str(uid),{}).get("expires",0))
def is_vip(uid): return vip_until(uid)>now_s()

def user_status(uid,rec):
    if ADMIN_ID and uid==ADMIN_ID: return "admin",0
    if is_vip(uid): return "vip",0
    actual_days=(now_s()-int(rec.get("first_seen",now_s())))//DAY+1
    if actual_days > VIP_FORCE_DAY:
        grace_until = rec.get("grace_until", 0)
        if grace_until == 0:
            with store.lock:
                rec["grace_until"] = now_s() + (3 * DAY)
                store.save("users")
            return "grace", actual_days
        elif now_s() < grace_until:
            return "grace", actual_days
        return "blocked", actual_days
    if actual_days <= TRIAL_DAYS: return "trial", actual_days
    if actual_days <= VIP_FORCE_DAY: return "warning", actual_days
    return "blocked", actual_days

def add_vip(uid,days):
    with store.lock:
        exp=max(now_s(),vip_until(uid))+int(days)*DAY
        store.data["vip"][str(uid)]=dict(expires=exp,added=now_s(),days=int(days)); store.save("vip")
    return exp
def remove_vip(uid):
    with store.lock:
        ok=store.data["vip"].pop(str(uid),None) is not None; store.save("vip")
    return ok
def time_ago(ts):
    if not ts: return "—"
    d=now_s()-int(ts)
    if d<60: return "الآن"
    if d<3600: return f"{d//60} د"
    if d<86400: return f"{d//3600} س"
    if d<604800: return f"{d//86400} يوم"
    return f"{d//604800} أسبوع"

def check_points_reward(uid):
    with store.lock:
        u=store.data["users"].get(str(uid))
        if not u: return (0,None)
        pts=u.get("points",0)
        if pts>=VIP_THRESHOLD:
            u["points"]=pts-VIP_THRESHOLD; store.save("users")
            add_vip(uid,VIP_REWARD_DAYS); return (u["points"],VIP_REWARD_DAYS)
    return (pts,None)

def points_visual(pts,threshold=VIP_THRESHOLD):
    pct=(pts/threshold) if threshold>0 else 0
    if pct>=1.0: bar,status="🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢","🎉 مكتمل!"
    elif pct>=0.9: bar,status="🟢🟢🟢🟢🟢🟢🟢🟢🟢⚪","🔥 قريب جداً"
    elif pct>=0.7: bar,status="🟢🟢🟢🟢🟢🟢🟢⚪⚪⚪","💪 ممتاز"
    elif pct>=0.5: bar,status="🟡🟡🟡🟡🟡⚪⚪⚪⚪⚪","⭐ في منتصف الطريق"
    elif pct>=0.3: bar,status="🟠🟠🟠⚪⚪⚪⚪⚪⚪⚪","🌱 استمر"
    else: bar,status="🔴🔴⚪⚪⚪⚪⚪⚪⚪⚪","🚀 ابدأ الجمع"
    return f"{bar}\n<b>{pts}/{threshold}</b> — {status}"

async def send_points_flash(msg_obj,pts,uid,bot_username=None):
    base="🎯 نقاطك: {c} <b>{p}/{t}</b>"
    try:
        sent=await msg_obj.reply_text(base.format(c="🔴",p=pts,t=VIP_THRESHOLD),
                                       parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
        for c in ["🟡","🔴"]:
            await asyncio.sleep(0.5)
            try: await sent.edit_text(base.format(c=c,p=pts,t=VIP_THRESHOLD),parse_mode=ParseMode.HTML)
            except Exception: break
        await asyncio.sleep(0.5)
        ref_link=f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else "—"
        final=(f"🎯 نقاطك: <b>{pts}/{VIP_THRESHOLD}</b>\n{points_visual(pts)}\n\n"
               f"📢 <b>نشر رابط القناة أو البوت = {POINTS_PROMO} نقاط</b>\n"
               f"👥 <b>دعوة مشترك جديد = {POINTS_REFERRAL} نقطة</b>\n\n"
               f"🔗 <b>رابط البوت (إحالتك):</b>\n<code>{ref_link}</code>\n\n"
               f"📢 <b>قناة التوصيات:</b>\n<code>{CHANNEL_LINK}</code>\n\n"
               f"🎁 عند الوصول لـ {VIP_THRESHOLD} = <b>VIP {VIP_REWARD_DAYS} يوم مجاناً</b>")
        try: await sent.edit_text(final,parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
        except Exception as _ex: log.debug('ignored: %s', _ex)
    except Exception as e: log.warning(f"send_points_flash: {e}")
def binance_futures_klines(sym,tf,bars=500):
    interval=BINANCE_INTERVAL_MAP.get(tf)
    if not interval: return None
    try:
        r=requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/klines",
                       params={"symbol":f"{sym}USDT","interval":interval,"limit":min(bars,1500)},timeout=10)
        if r.status_code==200:
            data=r.json()
            if isinstance(data,list) and data:
                return [[int(k[0]),float(k[1]),float(k[2]),float(k[3]),float(k[4]),float(k[5])] for k in data]
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return None

def binance_futures_ticker(sym):
    try:
        r=requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/24hr",params={"symbol":f"{sym}USDT"},timeout=10)
        if r.status_code==200:
            d=r.json()
            return {"last":float(d.get("lastPrice",0)),"percentage":float(d.get("priceChangePercent",0)),
                    "quoteVolume":float(d.get("quoteVolume",0)),"high":float(d.get("highPrice",0)),
                    "low":float(d.get("lowPrice",0))}
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return None

def binance_futures_all_tickers():
    try:
        r=requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/24hr",timeout=15)
        if r.status_code!=200: return None
        data=r.json()
        if not isinstance(data,list): return None
        rows=[]
        for t in data:
            try:
                sym_full=t.get("symbol","")
                if not sym_full.endswith("USDT"): continue
                base_sym=sym_full[:-4]
                if base_sym in STABLES or base_sym in EXCLUDE_TICKERS: continue
                if re.search(r"(UP|DOWN|BULL|BEAR|3L|3S|USDC)$",base_sym): continue
                ch=float(t.get("priceChangePercent",0)); price=float(t.get("lastPrice",0))
                qv=float(t.get("quoteVolume",0))
                if price<=0: continue
                rows.append({"symbol":base_sym,"change":ch,"price":price,"volume":qv})
            except Exception: continue
        return rows
    except Exception: return None

def _binance_mirror_request(path,params):
    for base in BINANCE_SPOT_MIRRORS:
        try:
            r=requests.get(f"{base}{path}",params=params,timeout=10)
            if r.status_code==200: return r.json(),base
        except Exception: continue
    return None,None

def binance_mirror_klines(sym,tf,bars=500):
    interval=BINANCE_INTERVAL_MAP.get(tf)
    if not interval: return None
    data,base=_binance_mirror_request("/api/v3/klines",{"symbol":f"{sym}USDT","interval":interval,"limit":min(bars,1000)})
    if not data or not isinstance(data,list): return None
    rows=[]
    for k in data:
        try: rows.append([int(k[0]),float(k[1]),float(k[2]),float(k[3]),float(k[4]),float(k[5])])
        except Exception: continue
    return rows

class PairNotFound(Exception): pass
class NoData(Exception): pass
_exch,_ex_lock,_down={},{},{}
_ex_init=threading.Lock()

def get_ex(name):
    with _ex_init:
        if name not in _exch:
            _exch[name]=getattr(ccxt,name)({"enableRateLimit":True,"timeout":12000})
            _ex_lock[name]=threading.Lock()
    return _exch[name]

# Major, high-liquidity markets receive a 1D/4H/1H context; other markets
# use 4H/1H/15M. The ML feature frame remains 4H to match model training.
RYMA_MAJOR_SYMBOLS = {"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "LINK", "AVAX", "LTC", "BCH", "DOT", "TON", "SUI"}
def default_tf(sym): return "4h"
def ryma_timeframes(sym):
    return ("4h", "1h", "15m")   # the engine always uses this stack, for every coin

def _rows_to_df(rows,tf,bars):
    cols=["t","open","high","low","close","volume"]
    if not rows: return pd.DataFrame(columns=cols)
    df=pd.DataFrame(rows,columns=cols).dropna()
    df=df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    df["t"]=df["t"].astype("int64")
    df=df[df["t"]+TF_MS[tf]<=int(time.time()*1000)]
    return df.tail(bars).reset_index(drop=True)

def _fetch_exchange(name,sym,tf,bars):
    ex=get_ex(name); tfms=TF_MS[tf]
    now=int(time.time()*1000); since=now-bars*tfms
    rows,last_ts=[],None
    with _ex_lock[name]:
        for _ in range(80):
            chunk=ex.fetch_ohlcv(f"{sym}/USDT",tf,since=since,limit=1000)
            if not chunk: break
            rows+=chunk
            if last_ts is not None and chunk[-1][0]<=last_ts: break
            last_ts=chunk[-1][0]
            if last_ts+tfms>=now: break
            since=last_ts+tfms
    return rows

_fut_syms={"t":0.0,"s":set()}
def _fut_symbol_known(sym):
    """هل الرمز موجود في عقود Binance Futures؟ (لرسالة 'لم يتم العثور' الصحيحة)"""
    if time.time()-_fut_syms["t"]>3600 or not _fut_syms["s"]:
        try:
            r=requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo",timeout=15)
            if r.status_code==200:
                _fut_syms["s"]={x["symbol"] for x in r.json().get("symbols",[])}; _fut_syms["t"]=time.time()
        except Exception as _ex: log.debug('ignored: %s', _ex)
    if not _fut_syms["s"]: return True
    return f"{sym}USDT" in _fut_syms["s"]

_candle_cache={}

def normalize_futures_source(source):
    s=str(source or "binance_fut").lower()
    if s in ("binance_fut","binance_usdm"): return s
    if s=="binance_spot_mirror": return "binance_fut"
    if s.endswith("_spot_ccxt"): return s.split("_",1)[0]+"_linear_swap"
    if s.endswith("_linear_swap"): return s
    return "binance_fut"

def get_candles(sym,tf,bars=450,ttl=CANDLE_TTL,min_bars=MIN_BARS,binance_only=False,preferred_source=None):
    preferred_source=normalize_futures_source(preferred_source) if preferred_source else None
    key=(sym,tf,bars,min_bars,binance_only,preferred_source)
    if len(_candle_cache)>400: _candle_cache.clear()
    hit=_candle_cache.get(key)
    if hit and time.time()-hit[0]<ttl: return hit[1]
    # Binance data is tried first for fresh analyses and for signals originally sourced there.
    if preferred_source is None or preferred_source in ("binance_fut","binance_usdm"):
        try:
            rows=binance_futures_klines(sym,tf,bars)
            if rows and len(rows)>=min_bars:
                df=_rows_to_df(rows,tf,bars)
                if len(df)>=min_bars and df["close"].min()>0 and df["high"].max()>0:
                    df.attrs.update(source="binance_fut",degraded=False,market_type="future")
                    _candle_cache[key]=(time.time(),df); return df
        except Exception as _ex: log.debug('ignored: %s', _ex)
    # For a tracked trade, pin every candle request to the same Futures venue used for its entry.
    if not binance_only:
        try:
            rows, futures_source = v10_futures_history(sym,tf,bars,preferred_source=preferred_source,minimum_override=min_bars)
            if rows and len(rows)>=min_bars:
                df=_rows_to_df(rows,tf,bars)
                if len(df)>=min_bars and df["close"].min()>0 and df["high"].max()>0:
                    df.attrs.update(source=futures_source,degraded=(futures_source not in ("binance_fut","binance_usdm")),
                                    market_type="future")
                    _candle_cache[key]=(time.time(),df); return df
        except Exception as _ex:
            log.debug("live Futures fallback %s %s via %s: %s",sym,tf,preferred_source or "auto",_ex)
    # A pinned Futures source must never fall through to spot or another exchange.
    if preferred_source:
        raise NoData(f"{sym}: pinned Futures source {preferred_source} unavailable for {tf}")
    try:
        rows=binance_mirror_klines(sym,tf,bars)
        if rows and len(rows)>=min_bars:
            df=_rows_to_df(rows,tf,bars)
            if len(df)>=min_bars and df["close"].min()>0 and df["high"].max()>0:
                df.attrs.update(source="binance_spot_mirror",degraded=True,market_type="spot")
                _candle_cache[key]=(time.time(),df); return df
    except Exception as _ex: log.debug('ignored: %s', _ex)
    # Cross-exchange OHLCV fallback is deliberately marked degraded (spot candles may differ from futures).
    if not binance_only:
        for ex_name in ("okx","bybit","gateio","kucoin"):
            try:
                rows=_fetch_exchange(ex_name,sym,tf,bars)
                if not rows or len(rows)<min_bars: continue
                df=_rows_to_df(rows,tf,bars)
                if len(df)>=min_bars and df["close"].min()>0 and df["high"].max()>0:
                    df.attrs.update(source=f"{ex_name}_spot_ccxt",degraded=True,market_type="spot")
                    _candle_cache[key]=(time.time(),df); return df
            except Exception as _ex: log.debug("candle fallback %s %s: %s",ex_name,sym,_ex)
    if not _fut_symbol_known(sym): raise PairNotFound(sym)
    raise NoData(sym)

_price_cache={}
def live_price(sym,source="binance_fut"):
    source=normalize_futures_source(source)
    cache_key=(sym,source)
    if len(_price_cache)>400: _price_cache.clear()
    hit=_price_cache.get(cache_key)
    if hit and time.time()-hit[0]<PRICE_TTL: return hit[1],hit[2]
    try:
        if source in ("binance_fut","binance_usdm"):
            t=binance_futures_ticker(sym)
            price=float(t["last"]) if t else 0.0
        else:
            venue=source[:-len("_linear_swap")]
            match=next(((eid,opts) for label,eid,opts in _V10_FUTURE_EXCHANGES if label==venue),None)
            if not match: return None,None
            exchange_id,options=match
            ex=_v10_get_futures_exchange(exchange_id,options)
            market_symbol=_v10_linear_swap_symbol(ex,sym)
            with _v10_futures_locks[exchange_id]:
                ticker=ex.fetch_ticker(market_symbol)
            price=float(ticker.get("last") or ticker.get("close") or 0.0)
        if price>0:
            _price_cache[cache_key]=(time.time(),price,source)
            return price,source
    except Exception as _ex:
        log.debug("Futures live price %s via %s: %s",sym,source,_ex)
    return None,None

def all_prices(sym):
    def one(name):
        try:
            ex=get_ex(name)
            with _ex_lock[name]: t=ex.fetch_ticker(f"{sym}/USDT")
            p=float(t.get("last") or 0)
            return name,p if p>0 else None
        except Exception: return name,None
    with ThreadPoolExecutor(len(EXCHANGES)) as pool:
        return {n:p for n,p in pool.map(one,EXCHANGES) if p}

def ticker_change(sym):
    price,change_24h=0.0,0.0
    try:
        t=binance_futures_ticker(sym)
        if t and t["last"]>0: price=t["last"]; change_24h=t["percentage"]
    except Exception as _ex: log.debug('ignored: %s', _ex)
    change_7d=0.0
    try:
        df=get_candles(sym,"1d",10,ttl=600,min_bars=8)
        if len(df)>=8 and float(df["close"].iloc[-8])>0:
            change_7d=(float(df["close"].iloc[-1])/float(df["close"].iloc[-8])-1)*100
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return price,change_24h,change_7d

_top_movers_cache=[0,[],[]]
def _movers_from_ccxt(ex_name,min_change=DAILY_MIN_CHANGE,min_vol=DAILY_MIN_VOLUME):
    try:
        if _down.get(ex_name,0)>time.time(): return []
        ex=get_ex(ex_name)
        with _ex_lock[ex_name]: tickers=ex.fetch_tickers()
        rows=[]
        for s,t in tickers.items():
            if not s.endswith("/USDT") or ":" in s: continue
            base=s.split("/")[0]
            if not base or base in DAILY_EXCLUDE or base in EXCLUDE_TICKERS: continue
            if re.search(r"(UP|DOWN|BULL|BEAR|3L|3S|USDT|USDC)$",base): continue
            try:
                ch=float(t.get("percentage") or 0); price=float(t.get("last") or 0)
                qv=float(t.get("quoteVolume") or 0)
            except Exception: continue
            if price<=0 or qv<min_vol or abs(ch)<min_change: continue
            rows.append(dict(symbol=base,change=ch,price=price,volume=qv,src=ex_name))
        return rows
    except Exception: return []

def _movers_from_binance_mirror(min_change=DAILY_MIN_CHANGE,min_vol=DAILY_MIN_VOLUME):
    try:
        rows=binance_futures_all_tickers()
        if not rows: return []
        return [dict(symbol=x["symbol"],change=x["change"],price=x["price"],volume=x["volume"],src="binance_fut")
                for x in rows if abs(x["change"])>=min_change and x["volume"]>=min_vol
                and x["symbol"] not in DAILY_EXCLUDE]
    except Exception: return []

def get_top_movers(force=False):
    if not force and time.time()-_top_movers_cache[0]<180:
        return _top_movers_cache[1],_top_movers_cache[2]
    all_rows=_movers_from_binance_mirror()
    if is_multi_exchange():
        for ex_name in ["okx","kucoin","bitget","gateio","mexc","bybit"]:
            all_rows+=_movers_from_ccxt(ex_name)
    best_by_sym={}
    for x in all_rows:
        sym=x["symbol"]
        if sym not in best_by_sym: best_by_sym[sym]=x
        else:
            if best_by_sym[sym].get("src","").startswith("binance"): continue
            if x.get("src","").startswith("binance"): best_by_sym[sym]=x
            elif abs(x["change"])>abs(best_by_sym[sym]["change"]): best_by_sym[sym]=x
    rows=list(best_by_sym.values())
    gainers=sorted([x for x in rows if x["change"]>0],key=lambda x:-x["change"])[:DAILY_TOP_N]
    losers=sorted([x for x in rows if x["change"]<0],key=lambda x:x["change"])[:DAILY_TOP_N]
    _top_movers_cache[0]=time.time(); _top_movers_cache[1]=gainers; _top_movers_cache[2]=losers
    return gainers,losers

def _bybit_get(path,params):
    try:
        r=requests.get(f"https://api.bybit.com{path}",params=params,timeout=8)
        if r.status_code==200: return r.json()
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return None

def futures_oi_history(sym,period="4h",limit=20):
    try:
        bp={"15m":"15min","1h":"1h","4h":"4h","1d":"1d"}.get(period,"4h")
        d=_bybit_get("/v5/market/open-interest",{"category":"linear","symbol":f"{sym}USDT","intervalTime":bp,"limit":limit})
        if d and d.get("retCode")==0:
            lst=d.get("result",{}).get("list",[])
            if lst and len(lst)>=3:
                curr=float(lst[0].get("openInterest",0)); old=float(lst[-1].get("openInterest",0))
                if old>0 and curr>0:
                    return dict(current=curr,change_pct=round((curr/old-1)*100,2),src="bybit")
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return None

def futures_funding_rate(sym):
    try:
        d=_bybit_get("/v5/market/tickers",{"category":"linear","symbol":f"{sym}USDT"})
        if d and d.get("retCode")==0:
            lst=d.get("result",{}).get("list",[])
            if lst: return float(lst[0].get("fundingRate",0))*100
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return None

def futures_long_short_ratio(sym,period="4h",limit=10):
    try:
        bp={"15m":"15min","1h":"1h","4h":"4h","1d":"1d"}.get(period,"4h")
        d=_bybit_get("/v5/market/account-ratio",{"category":"linear","symbol":f"{sym}USDT","period":bp,"limit":1})
        if d and d.get("retCode")==0:
            lst=d.get("result",{}).get("list",[])
            if lst:
                buy=float(lst[0].get("buyRatio",0)); sell=float(lst[0].get("sellRatio",0))
                if sell>0: return round(buy/sell,3)
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return None

def futures_taker_flow(sym,limit=500):
    try:
        r=requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/aggTrades",params={"symbol":f"{sym}USDT","limit":limit},timeout=8)
        if r.status_code!=200: return None
        buy=sell=0.0
        for t in r.json():
            q=float(t.get("q",0))
            if t.get("m"): sell+=q
            else: buy+=q
        total=buy+sell
        if total<=0: return None
        return round(buy/total,3)
    except Exception: return None

def futures_liquidations(sym,limit=100):
    try:
        r=requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/allForceOrders",params={"symbol":f"{sym}USDT","limit":limit},timeout=8)
        if r.status_code!=200: return None
        longs=shorts=0.0
        for o in r.json():
            notional=float(o.get("price",0))*float(o.get("origQty",0))
            if o.get("side")=="SELL": longs+=notional
            else: shorts+=notional
        return dict(long_liq=longs,short_liq=shorts)
    except Exception: return None

_derivatives_snapshot_cache={}
_derivatives_snapshot_lock=threading.RLock()
def derivatives_snapshot(sym, ttl=90):
    """Fetch OI/funding/ratio/liquidation/taker once per symbol and reuse briefly."""
    now=time.time()
    with _derivatives_snapshot_lock:
        hit=_derivatives_snapshot_cache.get(sym)
        if hit and now-hit[0]<ttl: return dict(hit[1])
    data={"oi":None,"funding":None,"ls_ratio":None,"liquidations":None,"taker":None,"source_status":{}}
    calls={
        "oi":lambda:futures_oi_history(sym,"4h",20),
        "funding":lambda:futures_funding_rate(sym),
        "ls_ratio":lambda:futures_long_short_ratio(sym),
        "liquidations":lambda:futures_liquidations(sym),
        "taker":lambda:futures_taker_flow(sym),
    }
    def run(item):
        key,fn=item
        try: return key,fn(),None
        except Exception as ex: return key,None,f"{type(ex).__name__}: {ex}"
    with ThreadPoolExecutor(max_workers=5) as pool:
        for key,value,error in pool.map(run,calls.items()):
            data[key]=value; data["source_status"][key]="ok" if value is not None else (error or "unavailable")
    with _derivatives_snapshot_lock:
        if len(_derivatives_snapshot_cache)>500: _derivatives_snapshot_cache.clear()
        _derivatives_snapshot_cache[sym]=(now,dict(data))
    return data

# ===================== Adaptive AI / Order Flow context =====================
_ai_context_cache = {}
_ai_context_lock = threading.RLock()
_ai_model_cache = {"path": None, "mtime": None, "model": None, "error": None}
_AI_FEATURES = ["ret_1", "ret_4", "atr_pct", "rv_ratio", "ema_spread", "rsi", "cvd_imbalance", "oi_change_pct", "funding_pct", "book_imbalance"]

def _ai_orderflow_snapshot(sym):
    """Public futures tape + order-book snapshot. No trading endpoints are called."""
    out = {"cvd_base": None, "taker_buy_base": None, "taker_sell_base": None,
           "cvd_imbalance": None, "book_imbalance": None, "source": "binance_usdm"}
    symbol = f"{clean_symbol(sym)}USDT"
    try:
        r = requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/aggTrades",
                         params={"symbol": symbol, "limit": RYMA_CVD_TRADES}, timeout=8)
        r.raise_for_status()
        trades = r.json()
        buy = sell = 0.0
        for tr in trades:
            q = float(tr.get("q", 0) or 0)
            if tr.get("m"):
                sell += q
            else:
                buy += q
        total = buy + sell
        if total > 0:
            out.update(taker_buy_base=buy, taker_sell_base=sell,
                       cvd_base=buy-sell, cvd_imbalance=(buy-sell)/total)
    except Exception as ex:
        out["tape_error"] = type(ex).__name__
    try:
        r = requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/depth",
                         params={"symbol": symbol, "limit": 20}, timeout=8)
        r.raise_for_status()
        book = r.json()
        bids = sum(float(x[1]) for x in book.get("bids", [])[:20])
        asks = sum(float(x[1]) for x in book.get("asks", [])[:20])
        if bids + asks > 0:
            out["book_imbalance"] = (bids-asks)/(bids+asks)
    except Exception as ex:
        out["book_error"] = type(ex).__name__
    return out


def _ai_regime_from_df(df, timeframe):
    """Rolling unsupervised KMeans regime; cluster labels mapped by volatility/trend.
    Uses only completed candles supplied by get_candles()."""
    result = {"name": "غير حاسم", "code": "unknown", "timeframe": timeframe,
              "method": "statistical_fallback", "trend_strength": None, "volatility_ratio": None}
    if df is None or len(df) < 80:
        return result
    try:
        x = df.copy().tail(180).reset_index(drop=True)
        close = pd.to_numeric(x["close"], errors="coerce")
        high = pd.to_numeric(x["high"], errors="coerce")
        low = pd.to_numeric(x["low"], errors="coerce")
        ret = close.pct_change()
        atr = (high-low).rolling(14, min_periods=10).mean()/close.replace(0, np.nan)
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        trend = (ema20-ema50)/close.replace(0, np.nan)
        vol = ret.rolling(20, min_periods=10).std()
        feat = pd.DataFrame({"trend":trend, "vol":vol, "atr":atr}).replace([np.inf,-np.inf],np.nan).dropna()
        if len(feat) < 50:
            return result
        cur=feat.iloc[-1]
        vol_base=float(feat["vol"].rolling(80,min_periods=30).median().iloc[-1])
        vr=float(cur["vol"]/vol_base) if vol_base and np.isfinite(vol_base) else 1.0
        tr=float(cur["trend"])
        result.update(trend_strength=round(tr*100,3),volatility_ratio=round(vr,2))
        # KMeans is used when sklearn exists; use the current cluster's centroid
        # plus explicit volatility mapping, not arbitrary numeric cluster IDs.
        if _KMeans is not None and _StandardScaler is not None:
            mat=feat.to_numpy(dtype=float)
            scaler=_StandardScaler()
            z=scaler.fit_transform(mat)
            km=_KMeans(n_clusters=3, random_state=17, n_init=10, max_iter=150)
            labels=km.fit_predict(z)
            label=int(labels[-1]); members=feat.iloc[np.where(labels==label)[0]]
            centroid=members.mean()
            cvol=float(centroid["vol"])
            ctrend=float(centroid["trend"])
            # Identify high-vol cluster by volatility rank; trend/range by centroid slope.
            cluster_vols=[float(feat.iloc[np.where(labels==j)[0]]["vol"].mean()) for j in range(3)]
            if cvol >= sorted(cluster_vols)[-1] * 0.92 and vr >= 1.35:
                code,name="high_vol","تقلبات مرتفعة"
            elif abs(ctrend) >= max(float(feat["trend"].abs().quantile(.65)),0.0015):
                code,name=("trend_up","اتجاه قوي صاعد") if ctrend>0 else ("trend_down","اتجاه قوي هابط")
            else:
                code,name="range","عرضي"
            result["method"]="kmeans_rolling"
        else:
            if vr>=1.8: code,name="high_vol","تقلبات مرتفعة"
            elif abs(tr)>=0.002: code,name=("trend_up","اتجاه قوي صاعد") if tr>0 else ("trend_down","اتجاه قوي هابط")
            else: code,name="range","عرضي"
        result.update(code=code,name=name)
    except Exception as ex:
        result["error"]=type(ex).__name__
    return result


def _ai_load_local_model():
    """Load the versioned local model artifact; artifact contains estimator + feature schema."""
    if not RYMA_ML_ENABLED or _joblib is None or not os.path.isfile(RYMA_ML_MODEL_PATH):
        return None, "model_not_configured"
    try:
        mtime=os.path.getmtime(RYMA_ML_MODEL_PATH)
        if (_ai_model_cache["model"] is None or _ai_model_cache["path"]!=RYMA_ML_MODEL_PATH
                or _ai_model_cache["mtime"]!=mtime):
            artifact=_joblib.load(RYMA_ML_MODEL_PATH)
            if isinstance(artifact,dict) and "model" in artifact:
                model=artifact["model"]
                features=list(artifact.get("features") or getattr(model,"feature_names_in_",_AI_FEATURES))
                metrics=artifact.get("metrics",{})
            else:
                model=artifact
                features=list(getattr(model,"feature_names_in_",_AI_FEATURES))
                metrics={}
            _ai_model_cache.update(path=RYMA_ML_MODEL_PATH,mtime=mtime,model={"estimator":model,"features":features,"metrics":metrics},error=None)
        return _ai_model_cache["model"], "local_model_ready"
    except Exception as ex:
        _ai_model_cache["error"]=f"{type(ex).__name__}: {str(ex)[:120]}"
        return None, "model_error"


def _ai_predict_distribution(features):
    """Return calibrated class probabilities only when a trained local artifact exists."""
    loaded,status=_ai_load_local_model()
    if not loaded: return None,status
    try:
        model=loaded["estimator"]; names=loaded["features"]
        row=pd.DataFrame([[float(features.get(k,0.0) or 0.0) for k in names]],columns=names)
        probs=model.predict_proba(row)[0]
        classes=list(getattr(model,"classes_",[-1,1]))
        return {int(c):float(v) for c,v in zip(classes,probs)},status
    except Exception as ex:
        _ai_model_cache["error"]=f"{type(ex).__name__}: {str(ex)[:120]}"
        return None,"model_error"


def _ai_predict_probability(features):
    """Compatibility field: probability of upward direction from the local classifier."""
    distribution,status=_ai_predict_distribution(features)
    if not distribution: return None,status
    return float(distribution.get(1,0.0)),status


def adaptive_ai_context(sym, df_1h=None, df_15m=None, deriv=None, primary_df=None):
    """Market regime + derivatives/tape features; never fabricates ML confidence."""
    now=time.time(); key=clean_symbol(sym)
    with _ai_context_lock:
        hit=_ai_context_cache.get(key)
        if hit and now-hit[0] < RYMA_AI_CACHE_TTL:
            return dict(hit[1])
    if deriv is None: deriv=derivatives_snapshot(sym)
    oi=deriv.get("oi") if isinstance(deriv,dict) else None
    oi_pct=oi.get("change_pct") if isinstance(oi,dict) else None
    funding=deriv.get("funding") if isinstance(deriv,dict) else None
    flow=_ai_orderflow_snapshot(sym) if RYMA_AI_ENABLED else {}
    r1=_ai_regime_from_df(df_1h,"1h")
    r15=_ai_regime_from_df(df_15m,"15m")
    df=primary_df if primary_df is not None and len(primary_df)>55 else (df_1h if df_1h is not None and len(df_1h)>55 else df_15m)
    feat={k:0.0 for k in _AI_FEATURES}
    try:
        if df is not None and len(df)>=55:
            c=pd.to_numeric(df["close"],errors="coerce")
            h=pd.to_numeric(df["high"],errors="coerce"); l=pd.to_numeric(df["low"],errors="coerce")
            ret1=float(c.pct_change().iloc[-1]*100); ret4=float(c.pct_change(4).iloc[-1]*100)
            atrp=float((h-l).rolling(14).mean().iloc[-1]/c.iloc[-1]*100)
            rv=float(c.pct_change().rolling(20).std().iloc[-1])
            e20=float(c.ewm(span=20,adjust=False).mean().iloc[-1]); e50=float(c.ewm(span=50,adjust=False).mean().iloc[-1])
            rsi=float(add_indicators(df.copy(),50)["rsi"].iloc[-1])
            vol=pd.to_numeric(df["volume"],errors="coerce")
            rv_ratio=float(vol.iloc[-1]/vol.rolling(20,min_periods=10).mean().iloc[-1])
            feat.update(ret_1=ret1,ret_4=ret4,atr_pct=atrp,rv_ratio=rv_ratio,
                        ema_spread=(e20-e50)/c.iloc[-1]*100,rsi=rsi)
    except Exception: pass
    feat.update(cvd_imbalance=float(flow.get("cvd_imbalance") or 0),
                oi_change_pct=float(oi_pct or 0),funding_pct=float(funding or 0),
                book_imbalance=float(flow.get("book_imbalance") or 0))
    prob,model_status=_ai_predict_probability(feat)
    out={"enabled":RYMA_AI_ENABLED,"regime_1h":r1,"regime_15m":r15,
         "flow":flow,"features":feat,"ml_probability":prob,
         "ml_probability_pct":round(prob*100,1) if prob is not None else None,
         "ml_status":model_status,"signal_threshold":RYMA_ML_MIN_PROB,
         "signal_eligible":bool(prob is not None and prob>=RYMA_ML_MIN_PROB),
         "confidence_is_calibrated":False,
         "notes":[]}
    if prob is None: out["notes"].append("لا يوجد نموذج احتمالي معاير منشور؛ لا تُعرض نسبة ثقة AI")
    if flow.get("cvd_imbalance") is None: out["notes"].append("بيانات CVD غير متاحة حالياً")
    if flow.get("book_imbalance") is None: out["notes"].append("بيانات دفتر الأوامر غير متاحة حالياً")
    with _ai_context_lock:
        if len(_ai_context_cache)>500: _ai_context_cache.clear()
        _ai_context_cache[key]=(now,out)
    return out


def market_regime_snapshot():
    """BTC market regime comes from the same AI decision engine as coin signals."""
    try:
        r=get_analysis("BTC",force=True)
        side=int(r.get("side",0)); grade=r.get("grade","C")
        regime=("ميل صاعد وفق AI" if side==1 else "ميل هابط وفق AI")
        if grade=="C": regime+=" · إشارة ضعيفة/متعارضة"
        return dict(regime=regime,bias=side,grade=grade,details=list(r.get("reasons",[]))+list(r.get("warnings",[])),
                    source=r.get("source"),price=r.get("price"))
    except Exception as ex:
        return dict(regime="غير متاح",bias=0,grade="—",details=[f"تعذر تحليل BTC عبر AI: {str(ex)[:120]}"],source=None)

def smart_money_snapshot(sym):
    """AI interpretation of flow context; raw exchange observations remain data only."""
    r=get_analysis(sym,force=True)
    side=int(r.get("side",0)); grade=r.get("grade","C")
    ctx=r.get("ai_context",{}) if isinstance(r,dict) else {}
    flow=ctx.get("flow",{}) if isinstance(ctx,dict) else {}
    notes=list(r.get("reasons",[]))+list(r.get("warnings",[]))
    if flow.get("cvd_imbalance") is not None: notes.append(f"CVD imbalance: {float(flow['cvd_imbalance']):+.3f}")
    if flow.get("book_imbalance") is not None: notes.append(f"Order book imbalance: {float(flow['book_imbalance']):+.3f}")
    rank={"A":2,"B":1,"C":0}.get(grade,0)
    return dict(symbol=sym,bias=("ميل شرائي وفق AI" if side==1 else "ميل بيعي وفق AI"),
      score=side*rank,available=sum(flow.get(k) is not None for k in ("cvd_imbalance","book_imbalance")),
      notes=notes,source_status=r.get("derivatives_status",{}),
      warning="التفسير الاتجاهي من نموذج AI؛ مؤشرات التدفق بيانات مساعدة ولا تثبت هوية المحافظ أو دخول مؤسسات.")

def futures_signal(sym):
    """Futures command consumes the canonical AI signal; no second scoring model."""
    try:
        r=get_analysis(sym,force=True)
        if not r or not r.get("lv"): return None
        return dict(direction="LONG" if r["side"]==1 else "SHORT",
          confidence=r.get("grade","C"),score=int(r.get("score",0)),
          reasons=list(r.get("reasons",[]))+list(r.get("warnings",[])),price=r.get("price"),
          ai_model=RYMA_AI_MODEL)
    except Exception as ex:
        log.warning("AI futures signal failed %s: %s",sym,ex)
        return None

_futures_score_cache={}
def check_liquidity(sym,min_usd=MIN_DAILY_VOLUME_USD):
    try:
        df=get_candles(sym,"1h",24,ttl=600,min_bars=20)
        if df.empty or len(df)<20: return False
        return float((df["volume"]*df["close"]).sum())>=min_usd
    except Exception: return False

def whale_radar(sym):
    try:
        for ex_name in ["binance","okx","bybit"]:
            try:
                ex=get_ex(ex_name)
                with _ex_lock[ex_name]: trades=ex.fetch_trades(f"{sym}/USDT",limit=200)
                if not trades: continue
                large,largest,buy_vol,sell_vol=0,0.0,0.0,0.0
                for t in trades:
                    notional=float(t.get("price",0))*float(t.get("amount",0))
                    largest=max(largest,notional)
                    if notional>=5000:
                        large+=1
                        if t.get("side")=="buy": buy_vol+=notional
                        elif t.get("side")=="sell": sell_vol+=notional
                if largest>0: return large,largest,buy_vol,sell_vol
            except Exception: continue
        return None,None,0,0
    except Exception: return None,None,0,0

def liquidity_radar(sym):
    try:
        for ex_name in ["okx","bybit","gateio","mexc","kucoin"]:
            try:
                ex=get_ex(ex_name)
                with _ex_lock[ex_name]: ob=ex.fetch_order_book(f"{sym}/USDT",limit=50)
                bids=sum(b[0]*b[1] for b in ob.get("bids",[]))
                asks=sum(a[0]*a[1] for a in ob.get("asks",[]))
                total=bids+asks
                if total>0: return dict(bids=bids,asks=asks,ratio=bids/total,source=ex_name)
            except Exception: continue
        return None
    except Exception: return None

def _ai_radar_result(sym, kind="opportunity"):
    """All directional radar classifications are sourced from the AI decision."""
    try:
        res=get_analysis(sym)
        if not res or res.get("wait") or not res.get("lv"):
            return None
        side=int(res.get("side",0))
        if side not in (-1,1): return None
        return dict(sym=sym, side=side, price=float(res["price"]), grade=res.get("grade","C"),
                    score=float(res.get("score",0) or 0), reasons=list(res.get("reasons") or []),
                    warnings=list(res.get("warnings") or []), ai_kind=kind,
                    entry=float(res["lv"]["entry"]), sl=float(res["lv"]["sl"]), df=res.get("df"), opportunity=bool(res.get("opportunity")),
                    tps=[float(x["px"]) for x in res["lv"].get("tps",[])])
    except Exception as ex:
        log.debug("AI radar failed %s/%s: %s", sym, kind, ex)
        return None


def explosion_radar(sym):
    """Radar: volume spike (>=2x) AND a real 4h move (>=2%). Direction comes from the v10 engine."""
    r=_ai_radar_result(sym,"liquidity_explosion_watch")
    if not r: return None
    try:
        d=get_candles(sym,"1h",60,ttl=120,min_bars=30)
        if d is None or len(d)<20: return None
        avg=float(d["volume"].iloc[-20:-1].mean())
        vol_ratio=float(d["volume"].iloc[-1]/avg) if avg>0 else 0.0
        change=float(d["close"].iloc[-1]/d["close"].iloc[-5]-1)*100
        if vol_ratio<2.0 or abs(change)<2.0: return None
        r.update(vol_ratio=round(vol_ratio,2),price_change=round(change,2))
        return r
    except Exception: return None

def pump_radar(sym):
    """Radar: LONG engine side + rising 4h (>=2%) + volume >=1.5x."""
    r=_ai_radar_result(sym,"momentum_opportunity")
    if not r or r["side"]!=1: return None
    try:
        d=get_candles(sym,"1h",60,ttl=120,min_bars=30)
        if d is None or len(d)<20: return None
        avg=float(d["volume"].iloc[-20:-1].mean())
        c1=(float(d["close"].iloc[-1])/float(d["close"].iloc[-2])-1)*100
        c4=(float(d["close"].iloc[-1])/float(d["close"].iloc[-5])-1)*100
        vr=float(d["volume"].iloc[-1]/avg) if avg>0 else 0.0
        if c4<2.0 or vr<1.5 or c1<=0: return None
        r.update(change_1h=round(c1,2),change_4h=round(c4,2),vol_ratio=round(vr,2))
        return r
    except Exception: return None

def bottom_radar(sym):
    """Radar: LONG engine side while price is stretched under EMA200 and already rebounding (BOTTOM_* thresholds)."""
    r=_ai_radar_result(sym,"potential_reversal")
    if not r or r["side"]!=1: return None
    try:
        d=add_indicators(r["df"],100); last=d.iloc[-1]; price=float(r["price"])
        ema=float(last["ema200"]) if pd.notna(last["ema200"]) else price
        diff=(price/ema-1)*100 if ema>0 else 0.0
        low10=float(d["low"].tail(10).min()); rebound=(price/low10-1)*100 if low10>0 else 0.0
        rsi=float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0
        vol_base=float(d["volume"].tail(30).mean()) if len(d)>=30 else 0.0
        vol_recent=float(d["volume"].tail(5).mean()) if len(d)>=5 else 0.0
        vr=vol_recent/vol_base if vol_base>0 else 0.0
        if not (BOTTOM_MIN_DIFF<=diff<=BOTTOM_MAX_DIFF): return None
        if not (BOTTOM_RSI_RANGE[0]<=rsi<=BOTTOM_RSI_RANGE[1]): return None
        if rebound<BOTTOM_MIN_REBOUND or vr<BOTTOM_MIN_VOL_RATIO: return None
        grade=r.get("grade","C")
        r.update(diff=round(diff,1),rsi=round(rsi,1),rebound=round(rebound,2),vol_ratio=round(vr,2),
                 severity={"A":"فرصة قوية وفق v10","B":"فرصة جيدة وفق v10","C":"مراقبة عالية المخاطر"}.get(grade,"مراقبة"))
        return r
    except Exception: return None

def short_radar(sym):
    """Radar: confirmed-grade SHORT from the v10 engine."""
    r=_ai_radar_result(sym,"short_opportunity")
    if not r or r["side"]!=-1 or not _grade_ok(r.get("grade","C")): return None
    try:
        d=r["df"]; last=d.iloc[-1]
        r["rsi"]=round(float(last["rsi"]),1) if pd.notna(last["rsi"]) else 50.0
        return r
    except Exception: return None

def alpha_radar(sym):
    """Radar: confirmed-grade LONG on a non-major coin that is also up over 7 days."""
    if sym in ALPHA_MAJORS_EXCLUDE: return None
    r=_ai_radar_result(sym,"alpha_opportunity")
    if not r or r["side"]!=1 or not _grade_ok(r.get("grade","C")): return None
    try:
        d=get_candles(sym,"1d",60,ttl=600,min_bars=30)
        if d is None or len(d)<30: return None
        close=d["close"]
        c7=(float(close.iloc[-1])/float(close.iloc[-7])-1)*100
        if c7<=0: return None
        r.update(change_7d=round(c7,2),change_30d=round((float(close.iloc[-1])/float(close.iloc[-30])-1)*100,2),
                 rsi=round(float(add_indicators(d,50)["rsi"].iloc[-1]),1))
        return r
    except Exception: return None

def hype_radar(limit=10):
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=10)
        if r.status_code != 200: return []
        coins = r.json().get("coins", [])
        results = []
        for item in coins[:limit]:
            cd = item.get("item", {})
            sym = (cd.get("symbol", "") or "").upper()
            name = cd.get("name", "")
            rank = cd.get("market_cap_rank", "N/A")
            score = cd.get("score", 0)
            if sym in ALPHA_MAJORS_EXCLUDE or sym in STABLES: continue
            pd_ = cd.get("data", {}) or {}
            ch_raw = (pd_.get("price_change_percentage_24h") or {}).get("usd", 0)
            try: change = float(ch_raw or 0)
            except Exception: change = 0.0
            price_raw = (pd_.get("price") or 0)
            try: price = float(price_raw or 0)
            except Exception: price = 0.0
            categories = pd_.get("categories") or []
            is_web3 = any(("web3" in str(c).lower() or "defi" in str(c).lower()) for c in categories)
            results.append(dict(sym=sym, name=name, rank=rank, score=score,
                                change=change, price=price, is_web3=is_web3))
        return results
    except Exception as e:
        log.warning(f"hype_radar: {e}")
        return []

def build_hype_radar_text(results):
    if not results: return "🔥 لا توجد ترندات حالياً"
    lines = ["🔥 <b>رادار الضجة (Hype Radar)</b>","━━━━━━━━━━━━━━━━",""]
    web3_count = 0
    for r in results:
        icon = "🟢" if r["change"] > 2 else ("🔴" if r["change"] < -2 else "🟡")
        w3 = " 🌐 Web3" if r["is_web3"] else ""
        lines.append(f"{icon} <b>#{r['sym']}</b> ({r['name']}){w3}")
        lines.append(f"   📊 ترتيب: #{r['rank']} | زخم: {r['score']} | {r['change']:+.2f}%")
        if r["price"]: lines.append(f"   💵 ${r['price']:,.6f}")
        lines.append("")
        if r["is_web3"]: web3_count += 1
    lines.append(f"📈 إجمالي: {len(results)} | 🌐 Web3: {web3_count}")
    return "\n".join(lines)
_top_cache=[0,[]]
def top_symbols(n=60,binance_only=False):
    if not binance_only and time.time()-_top_cache[0]<1800 and _top_cache[1]: return _top_cache[1][:n]
    try:
        rows=binance_futures_all_tickers()
        if rows:
            rows=[(x["volume"],x["symbol"]) for x in rows if x["volume"]>2e6 and x["symbol"] not in EXCLUDE_TICKERS]
            rows.sort(reverse=True)
            if rows:
                _top_cache[0],_top_cache[1]=time.time(),[b for _,b in rows]
                return _top_cache[1][:n]
    except Exception as _ex: log.debug('ignored: %s', _ex)
    if binance_only: return COINS[:n]
    if is_multi_exchange():
        for name in FAST_EXCHANGES:
            if name=="binance": continue
            if _down.get(name,0)>time.time(): continue
            try:
                ex=get_ex(name)
                with _ex_lock[name]: tk=ex.fetch_tickers()
                rows=[]
                for s,t in tk.items():
                    if not s.endswith("/USDT") or ":" in s: continue
                    base=s.split("/")[0]
                    if base in DAILY_EXCLUDE or base in EXCLUDE_TICKERS: continue
                    if re.search(r"(UP|DOWN|BULL|BEAR|3L|3S)$",base): continue
                    qv=t.get("quoteVolume") or 0
                    if qv and qv>2e6: rows.append((qv,base))
                rows.sort(reverse=True)
                if rows:
                    _top_cache[0],_top_cache[1]=time.time(),[b for _,b in rows]
                    return _top_cache[1][:n]
            except Exception: continue
    return COINS[:n]

_HOT=[0,["BTC","ETH"]]
def hot_coins_for(sym):
    if time.time()-_HOT[0]>3600:
        try:
            rows=binance_futures_all_tickers()
            if rows:
                pop=sorted([r for r in rows if r["symbol"] in ("BTC","ETH","SOL","BNB","XRP","DOGE","ADA")],
                           key=lambda x:-x["volume"])
                _HOT[0]=time.time()
                _HOT[1]=[r["symbol"] for r in pop[:2]] or ["BTC","ETH"]
        except Exception as _ex: log.debug('ignored: %s', _ex)
    others=[c for c in _HOT[1] if c!=sym]
    coins=([sym]+others)[:3]
    while len(coins)<3:
        for c in ("BTC","ETH","SOL"):
            if c not in coins: coins.append(c); break
    return coins

def wilder(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def ema(s,n): return s.ewm(span=n,adjust=False,min_periods=n).mean()
def true_range(df):
    pc=df["close"].shift()
    return pd.concat([df["high"]-df["low"],(df["high"]-pc).abs(),(df["low"]-pc).abs()],axis=1).max(axis=1)
def rsi_calc(close,n=14):
    d=close.diff()
    up,dn=wilder(d.clip(lower=0),n),wilder((-d).clip(lower=0),n)
    out=100-100/(1+up/dn.replace(0,np.nan))
    out[(dn==0)&up.notna()]=100.0
    return out
def macd_calc(close,fast=MACD_FAST,slow=MACD_SLOW,sig=MACD_SIGNAL):
    efast=ema(close,fast); eslow=ema(close,slow)
    macd=efast-eslow; signal_line=ema(macd,sig); hist=macd-signal_line
    return macd,signal_line,hist


def adx_calc(df,n=14):
    """Wilder ADX (causal). Computed once per frame so a decision is O(1)."""
    up=df["high"].diff(); down=-df["low"].diff()
    plus=pd.Series(np.where((up>down)&(up>0),up,0.0),index=df.index)
    minus=pd.Series(np.where((down>up)&(down>0),down,0.0),index=df.index)
    atr=wilder(true_range(df),n).replace(0,np.nan)
    pdi=100*wilder(plus,n)/atr; mdi=100*wilder(minus,n)/atr
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return wilder(dx,n)

def add_indicators(df,atrp_win=100):
    df=df.copy(); c=df["close"]
    df["ema20"],df["ema50"],df["ema200"]=ema(c,20),ema(c,50),ema(c,200)
    df["rsi"]=rsi_calc(c); df["atr"]=wilder(true_range(df),14); df["adx"]=adx_calc(df)
    df["rvol"]=df["volume"]/df["volume"].rolling(20).mean().replace(0,np.nan)
    df["macd"],df["macd_sig"],df["macd_hist"]=macd_calc(c)
    mid,sd=c.rolling(20).mean(),c.rolling(20).std()
    df["bb_mid"],df["bb_up"],df["bb_lo"]=mid,mid+2*sd,mid-2*sd
    atrp=df["atr"]/c
    df["atrp"]=atrp.rolling(atrp_win,min_periods=min(atrp_win,30)).apply(lambda x:(x[-1]>=x).mean()*100,raw=True)
    rng=(df["high"]-df["low"]).replace(0,np.nan)
    df["wick_up"]=(df["high"]-df[["close","open"]].max(axis=1))/rng
    df["wick_dn"]=(df[["close","open"]].min(axis=1)-df["low"])/rng
    df["ext_atr"]=(c-df["ema20"])/df["atr"]
    tp=(df["high"]+df["low"]+df["close"])/3
    df["vwap"]=(tp*df["volume"]).rolling(50).sum()/df["volume"].rolling(50).sum().replace(0,np.nan)
    df["highest_10"]=df["high"].rolling(10).max()
    df["lowest_10"]=df["low"].rolling(10).min()
    return df

def detect_trend(df,i):
    if i<50: return "unknown"
    r=df.iloc[i]
    if pd.isna(r["ema20"]) or pd.isna(r["ema50"]) or pd.isna(r["ema200"]): return "unknown"
    if r["ema20"]>r["ema50"]>r["ema200"] and r["close"]>r["ema20"]: return "strong_up"
    if r["ema20"]>r["ema50"] and r["close"]>r["ema200"]: return "up"
    if r["ema20"]<r["ema50"]<r["ema200"] and r["close"]<r["ema20"]: return "strong_down"
    if r["ema20"]<r["ema50"] and r["close"]<r["ema200"]: return "down"
    return "range"

def daily_bias(df_d):
    try:
        if df_d is None or len(df_d)<200: return 0
        last=df_d.iloc[-1]; c=float(last["close"])
        e20=float(last["ema20"]) if not pd.isna(last["ema20"]) else c
        e50=float(last["ema50"]) if not pd.isna(last["ema50"]) else c
        e200=float(last["ema200"]) if not pd.isna(last["ema200"]) else c
        rsi_v=float(last["rsi"]) if not pd.isna(last["rsi"]) else 50
        score=0
        if c<e50: score-=1
        if c<e200: score-=1
        if c>e50: score+=1
        if c>e200: score+=1
        if e20<e50: score-=1
        if e50<e200: score-=1
        if e20>e50: score+=1
        if e50>e200: score+=1
        if rsi_v<45: score-=1
        if rsi_v>55: score+=1
        try:
            change_7d=(c/float(df_d["close"].iloc[-8])-1)*100
            if change_7d<-5: score-=1
            if change_7d>5: score+=1
        except Exception as _ex: log.debug('ignored: %s', _ex)
        if score<=-2: return -1
        if score>=2: return 1
        return 0
    except Exception: return 0

def _find_pattern_pivots(df,left=5,right=5,max_pivots=8):
    highs,lows=[],[]; n=len(df)
    if n<left+right+5: return highs,lows
    for i in range(left,n-right):
        try:
            h=float(df["high"].iloc[i]); l=float(df["low"].iloc[i])
            is_high=all(h>=float(df["high"].iloc[i-j]) for j in range(1,left+1)) and all(h>=float(df["high"].iloc[i+j]) for j in range(1,right+1))
            if is_high: highs.append((i,h))
            is_low=all(l<=float(df["low"].iloc[i-j]) for j in range(1,left+1)) and all(l<=float(df["low"].iloc[i+j]) for j in range(1,right+1))
            if is_low: lows.append((i,l))
        except Exception: continue
    return highs[-max_pivots:],lows[-max_pivots:]

def _approx_equal(a,b,tol_pct=2.0):
    if a==0 or b==0: return False
    return abs(a-b)/max(a,b)*100<=tol_pct

def _pt(df,i,price): return (int(df["t"].iloc[i]),float(price))
def _seg(p1,p2,color="neutral",ext=False):
    return dict(t1=int(p1[0]),p1=float(p1[1]),t2=int(p2[0]),p2=float(p2[1]),ext=ext,color=color)
def _mark(p,label): return dict(t=int(p[0]),p=float(p[1]),label=label)
def _fit_seg(sub,slope,icpt,color):
    last=len(sub)-1
    return _seg((int(sub["t"].iloc[0]),icpt),(int(sub["t"].iloc[-1]),icpt+slope*last),color,True)

def detect_double_top_bottom(df):
    highs,lows=_find_pattern_pivots(df,5,5,8)
    patterns=[]
    last_t=int(df["t"].iloc[-1]); cur=float(df["close"].iloc[-1])
    if len(highs)>=2:
        h1_i,h1_p=highs[-2]; h2_i,h2_p=highs[-1]
        if h2_i-h1_i>=5 and _approx_equal(h1_p,h2_p,1.5):
            neck=float(df["low"].iloc[h1_i:h2_i+1].min())
            if cur<neck:
                p1=_pt(df,h1_i,h1_p); p2=_pt(df,h2_i,h2_p)
                patterns.append(dict(name="Double Top",bias="bearish",confirmed=True,
                    pivot1=h1_p,pivot2=h2_p,neckline=neck,
                    segments=[_seg(p1,p2,"bearish"),_seg((p1[0],neck),(last_t,neck),"neck",True)],
                    marks=[_mark(p1,"T1"),_mark(p2,"T2")]))
    if len(lows)>=2:
        l1_i,l1_p=lows[-2]; l2_i,l2_p=lows[-1]
        if l2_i-l1_i>=5 and _approx_equal(l1_p,l2_p,1.5):
            neck=float(df["high"].iloc[l1_i:l2_i+1].max())
            if cur>neck:
                p1=_pt(df,l1_i,l1_p); p2=_pt(df,l2_i,l2_p)
                patterns.append(dict(name="Double Bottom",bias="bullish",confirmed=True,
                    pivot1=l1_p,pivot2=l2_p,neckline=neck,
                    segments=[_seg(p1,p2,"bullish"),_seg((p1[0],neck),(last_t,neck),"neck",True)],
                    marks=[_mark(p1,"B1"),_mark(p2,"B2")]))
    return patterns

def detect_head_shoulders(df):
    highs,lows=_find_pattern_pivots(df,5,5,10)
    patterns=[]
    last_t=int(df["t"].iloc[-1]); cur=float(df["close"].iloc[-1])
    if len(highs)>=3:
        l_sh,head,r_sh=highs[-3],highs[-2],highs[-1]
        if head[1]>l_sh[1] and head[1]>r_sh[1]:
            if _approx_equal(l_sh[1],r_sh[1],3.0) and (r_sh[0]-l_sh[0])>=15:
                neck=float(df["low"].iloc[l_sh[0]:r_sh[0]+1].min())
                if cur<neck:
                    pl=_pt(df,l_sh[0],l_sh[1]); ph=_pt(df,head[0],head[1]); pr=_pt(df,r_sh[0],r_sh[1])
                    patterns.append(dict(name="Head & Shoulders",bias="bearish",confirmed=True,
                        head=head[1],neckline=neck,
                        segments=[_seg(pl,ph,"bearish"),_seg(ph,pr,"bearish"),_seg((pl[0],neck),(last_t,neck),"neck",True)],
                        marks=[_mark(pl,"LS"),_mark(ph,"H"),_mark(pr,"RS")]))
    if len(lows)>=3:
        l_sh,head,r_sh=lows[-3],lows[-2],lows[-1]
        if head[1]<l_sh[1] and head[1]<r_sh[1]:
            if _approx_equal(l_sh[1],r_sh[1],3.0) and (r_sh[0]-l_sh[0])>=15:
                neck=float(df["high"].iloc[l_sh[0]:r_sh[0]+1].max())
                if cur>neck:
                    pl=_pt(df,l_sh[0],l_sh[1]); ph=_pt(df,head[0],head[1]); pr=_pt(df,r_sh[0],r_sh[1])
                    patterns.append(dict(name="Inverse H&S",bias="bullish",confirmed=True,
                        head=head[1],neckline=neck,
                        segments=[_seg(pl,ph,"bullish"),_seg(ph,pr,"bullish"),_seg((pl[0],neck),(last_t,neck),"neck",True)],
                        marks=[_mark(pl,"LS"),_mark(ph,"H"),_mark(pr,"RS")]))
    return patterns

def detect_triangle(df,lookback=40):
    if len(df)<lookback: return []
    sub=df.tail(lookback).reset_index(drop=True)
    x=np.arange(len(sub))
    try:
        hs,hb=np.polyfit(x,sub["high"].values.astype(float),1)
        ls,lb=np.polyfit(x,sub["low"].values.astype(float),1)
    except Exception: return []
    if abs(hs)<1e-9 or abs(ls)<1e-9: return []
    patterns=[]
    if abs(hs)/max(sub["high"].mean(),1e-9)<0.0005 and ls>0:
        patterns.append(dict(name="Ascending Triangle",bias="bullish",confirmed=True,
            segments=[_fit_seg(sub,hs,hb,"bullish"),_fit_seg(sub,ls,lb,"bullish")],marks=[]))
    elif abs(ls)/max(sub["low"].mean(),1e-9)<0.0005 and hs<0:
        patterns.append(dict(name="Descending Triangle",bias="bearish",confirmed=True,
            segments=[_fit_seg(sub,hs,hb,"bearish"),_fit_seg(sub,ls,lb,"bearish")],marks=[]))
    elif hs<0 and ls>0:
        patterns.append(dict(name="Symmetrical Triangle",bias="neutral",confirmed=False,
            segments=[_fit_seg(sub,hs,hb,"neutral"),_fit_seg(sub,ls,lb,"neutral")],marks=[]))
    return patterns

def detect_flags(df,lookback=30):
    if len(df)<lookback+10: return []
    recent=df.tail(lookback).reset_index(drop=True)
    split=int(lookback*0.3)
    imp=recent.iloc[:split]; consol=recent.iloc[split:]
    if len(imp)<5 or len(consol)<5: return []
    try:
        imp_move=(float(imp["close"].iloc[-1])/float(imp["close"].iloc[0])-1)*100
        consol_move=(float(consol["close"].iloc[-1])/float(consol["close"].iloc[0])-1)*100
        consol_range=(float(consol["high"].max())/float(consol["low"].min())-1)*100
    except Exception: return []
    t_c1=int(consol["t"].iloc[0]); t_c2=int(consol["t"].iloc[-1])
    hi_c=float(consol["high"].max()); lo_c=float(consol["low"].min())
    channel=[_seg((t_c1,hi_c),(t_c2,hi_c),"neutral",True),_seg((t_c1,lo_c),(t_c2,lo_c),"neutral",True)]
    pole_p1=(int(imp["t"].iloc[0]),float(imp["close"].iloc[0]))
    pole_p2=(int(imp["t"].iloc[-1]),float(imp["close"].iloc[-1]))
    patterns=[]
    if imp_move>5 and -5<consol_move<0 and consol_range<imp_move*0.5:
        patterns.append(dict(name="Bull Flag",bias="bullish",confirmed=True,
            segments=[_seg(pole_p1,pole_p2,"bullish")]+channel,marks=[]))
    elif imp_move<-5 and 0<consol_move<5 and consol_range<abs(imp_move)*0.5:
        patterns.append(dict(name="Bear Flag",bias="bearish",confirmed=True,
            segments=[_seg(pole_p1,pole_p2,"bearish")]+channel,marks=[]))
    return patterns

def detect_wedge(df,lookback=40):
    if len(df)<lookback: return []
    sub=df.tail(lookback).reset_index(drop=True)
    x=np.arange(len(sub))
    try:
        hs,hb=np.polyfit(x,sub["high"].values.astype(float),1)
        ls,lb=np.polyfit(x,sub["low"].values.astype(float),1)
    except Exception: return []
    patterns=[]
    if hs>0 and ls>0 and ls>hs*1.5:
        patterns.append(dict(name="Rising Wedge",bias="bearish",confirmed=True,
            segments=[_fit_seg(sub,hs,hb,"bearish"),_fit_seg(sub,ls,lb,"bearish")],marks=[]))
    elif hs<0 and ls<0 and hs<ls*1.5:
        patterns.append(dict(name="Falling Wedge",bias="bullish",confirmed=True,
            segments=[_fit_seg(sub,hs,hb,"bullish"),_fit_seg(sub,ls,lb,"bullish")],marks=[]))
    return patterns

def detect_all_patterns(df,tf=None):
    out=[]
    try: out+=detect_head_shoulders(df)
    except Exception as _ex: log.debug('ignored: %s', _ex)
    try: out+=detect_double_top_bottom(df)
    except Exception as _ex: log.debug('ignored: %s', _ex)
    try: out+=detect_triangle(df)
    except Exception as _ex: log.debug('ignored: %s', _ex)
    try: out+=detect_flags(df)
    except Exception as _ex: log.debug('ignored: %s', _ex)
    try: out+=detect_wedge(df)
    except Exception as _ex: log.debug('ignored: %s', _ex)
    confirmed=[p for p in out if p.get("confirmed")]
    if tf:
        for p in confirmed: p["tf"]=tf
    return confirmed

def find_sr_levels(df,lookback=SR_LOOKBACK):
    try:
        sub=df.tail(lookback).reset_index(drop=True)
        if len(sub)<20: return [],[]
        highs,lows=[],[]
        for i in range(3,len(sub)-3):
            h=float(sub["high"].iloc[i]); l=float(sub["low"].iloc[i])
            if pd.isna(h) or pd.isna(l): continue
            if all(h>=float(sub["high"].iloc[i-j]) for j in range(1,4)) and all(h>=float(sub["high"].iloc[i+j]) for j in range(1,4)): highs.append(h)
            if all(l<=float(sub["low"].iloc[i-j]) for j in range(1,4)) and all(l<=float(sub["low"].iloc[i+j]) for j in range(1,4)): lows.append(l)
        def merge(levels):
            if not levels: return []
            levels=sorted(levels); merged=[levels[0]]
            for lv in levels[1:]:
                if abs(lv-merged[-1])/merged[-1]*100<SR_MERGE_PCT: merged[-1]=(merged[-1]+lv)/2
                else: merged.append(lv)
            return merged
        return merge(highs),merge(lows)
    except Exception: return [],[]

def detect_candle_pattern(df,i):
    if i<5: return None
    r=df.iloc[i]; o,h,l,c=float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"])
    body=abs(c-o); rng=h-l
    if rng==0: return None
    upper=h-max(o,c); lower=min(o,c)-l
    if lower>body*2 and upper<body*0.5 and body>0: return "مطرقة"
    if upper>body*2 and lower<body*0.5 and body>0: return "شهاب"
    if body<rng*0.1: return "دوجي"
    if i>=1:
        prev=df.iloc[i-1]
        if c>o and prev["close"]<prev["open"] and c>float(prev["open"]) and o<float(prev["close"]): return "ابتلاع صاعد"
        if c<o and prev["close"]>prev["open"] and c<float(prev["open"]) and o>float(prev["close"]): return "ابتلاع هابط"
    return None

def fib_levels(df,lookback=SR_LOOKBACK):
    try:
        sub=df.tail(lookback); hi=float(sub["high"].max()); lo=float(sub["low"].min())
        diff=hi-lo
        if diff<=0: return []
        return [round(hi-diff*f,6) for f in FIB_LEVELS]
    except Exception: return []

_analysis_cache={}
_ai_decision_cache={}
_ai_http_session=requests.Session()
_ai_api_lock=threading.Lock()
_ai_last_request_at=0.0


def _ai_usage_read():
    """Small local usage ledger; protects against repeated scans/restarts in one deployment."""
    today=dt.datetime.now(dt.timezone.utc).date().isoformat()
    try:
        with open(RYMA_AI_USAGE_PATH,"r",encoding="utf-8") as f: state=json.load(f)
        if state.get("day")!=today: state={"day":today,"calls":0,"blocked_until":0}
    except Exception:
        state={"day":today,"calls":0,"blocked_until":0}
    return state


def _ai_usage_write(state):
    try:
        tmp=RYMA_AI_USAGE_PATH+".tmp"
        with open(tmp,"w",encoding="utf-8") as f: json.dump(state,f)
        os.replace(tmp,RYMA_AI_USAGE_PATH)
    except Exception as ex:
        log.warning("AI usage ledger could not be saved: %s",type(ex).__name__)




def v10_levels(price,side,atr,atr_1h=None,params=None):
    """The ONLY place where v10 stop/targets are built (decision, live tracking and backtest share it)."""
    prm=params or v10_params()
    price=float(price); side=int(side)
    atr=float(atr) if atr is not None and np.isfinite(atr) and float(atr)>0 else price*0.004
    ref=atr
    if prm["stop_tf"]=="1h" and atr_1h is not None and np.isfinite(atr_1h) and float(atr_1h)>0: ref=float(atr_1h)
    risk=min(max(ref*prm["stop_k"],price*V10_RISK_MIN_PCT),price*V10_RISK_MAX_PCT)
    rr=V10_RR_SETS[prm["rr"]]
    return {"entry":price,"sl":price-side*risk,"risk":risk,"atr":atr,
            "tps":[{"px":price+side*risk*r,"pct":round(100*risk*r/price,3),"frac":f,"hit":False,"src":"V10_HYBRID"}
                   for r,f in zip(rr,V10_FRACS)]}


def _v10_trigger_mask(m15):
    """Vectorised twin of the 15M trigger in the decision (liquidity sweep/reclaim OR volume breakout, either side).
    Used to skip bars that can never be an opportunity; tests assert it equals the decision's own trigger."""
    prior_hi=m15["high"].shift(1).rolling(20).max(); prior_lo=m15["low"].shift(1).rolling(20).min()
    o,h,l,c=m15["open"],m15["high"],m15["low"],m15["close"]; rv=m15["rvol"].fillna(0)
    low_sweep=(l<prior_lo)&(c>prior_lo)&(c>o); high_sweep=(h>prior_hi)&(c<prior_hi)&(c<o)
    brk_up=(c>prior_hi)&(rv>=1.15); brk_dn=(c<prior_lo)&(rv>=1.15)
    return (low_sweep|brk_up|high_sweep|brk_dn)


def _ryma_v10_hybrid_decision(sym, df_1h, df_15m, price, ai_context, params=None):
    """Ryma v10 Adaptive Hybrid: 4H regime + 1H confirmation + 15M liquidity trigger.
    An OPPORTUNITY needs all three (regime aligned, 1H confirmed, fresh 15M trigger). Anything less is a
    RADAR reading (setup forming) and is graded C, so it can never be mistaken for a confirmed entry."""
    prm=params or v10_params()
    d4=(ai_context or {}).get("_df_4h")
    if d4 is None or len(d4)<210: raise NoData(f"{sym}: 4H context unavailable")
    if df_1h is None or len(df_1h)<205: raise NoData(f"{sym}: 1H context unavailable")
    if df_15m is None or len(df_15m)<60: raise NoData(f"{sym}: 15M trigger context unavailable")
    need=lambda x: "ema200" not in x.columns or "adx" not in x.columns
    d4=add_indicators(d4,100) if need(d4) else d4
    h1=add_indicators(df_1h,100) if need(df_1h) else df_1h
    m15=add_indicators(df_15m,50) if need(df_15m) else df_15m
    a,b,c=d4.iloc[-1],h1.iloc[-1],m15.iloc[-1]
    adx4=float(a["adx"]) if np.isfinite(a["adx"]) else 0.0
    bull4=(float(a["ema50"])>float(a["ema200"]) and float(a["close"])>float(a["ema50"]))
    bear4=(float(a["ema50"])<float(a["ema200"]) and float(a["close"])<float(a["ema50"]))
    bull1=(float(b["ema20"])>float(b["ema50"]) and float(b["close"])>float(b["ema50"]) and float(b["macd_hist"])>0)
    bear1=(float(b["ema20"])<float(b["ema50"]) and float(b["close"])<float(b["ema50"]) and float(b["macd_hist"])<0)
    if bull4 and not bear4: side=1
    elif bear4 and not bull4: side=-1
    else: side=1 if float(a["ema50"])>=float(a["ema200"]) else -1
    prev=m15.iloc[-21:-1]
    prior_hi=float(prev["high"].max()); prior_lo=float(prev["low"].min())
    rv=float(c["rvol"]) if np.isfinite(c["rvol"]) else 0.0
    low_sweep=float(c["low"])<prior_lo and float(c["close"])>prior_lo and float(c["close"])>float(c["open"])
    high_sweep=float(c["high"])>prior_hi and float(c["close"])<prior_hi and float(c["close"])<float(c["open"])
    breakout_up=float(c["close"])>prior_hi and rv>=1.15
    breakout_dn=float(c["close"])<prior_lo and rv>=1.15
    rsi15=float(c["rsi"]) if np.isfinite(c["rsi"]) else 50.0
    vol_ok=rv>=1.0
    trigger=(low_sweep or breakout_up) if side==1 else (high_sweep or breakout_dn)
    confirm=bull1 if side==1 else bear1
    regime_ok=bull4 if side==1 else bear4
    score=0
    score+=2 if regime_ok else 0
    score+=2 if confirm else 0
    score+=2 if trigger else 0
    score+=1 if adx4>=18 else 0
    score+=1 if vol_ok else 0
    score+=1 if ((45<=rsi15<=72) if side==1 else (28<=rsi15<=55)) else 0
    opportunity=bool(regime_ok and confirm and trigger and adx4>=prm["min_adx"])
    grade=("A" if score>=8 else "B") if opportunity else "C"
    warnings=[]
    reasons=[f"4H regime={'bullish' if bull4 else 'bearish' if bear4 else 'mixed'}; ADX={adx4:.1f}",
             f"1H confirmation={'yes' if confirm else 'no'}",
             f"15M trigger={'liquidity sweep/reclaim' if (low_sweep or high_sweep) else 'breakout' if (breakout_up or breakout_dn) else 'not confirmed'}"]
    if not regime_ok: warnings.append("نظام 4H غير متوافق مع الاتجاه")
    if not confirm: warnings.append("تأكيد 1H غير مكتمل")
    if not trigger: warnings.append("محفز 15M غير مكتمل؛ هذه قراءة رادار للمراقبة وليست فرصة")
    if adx4<max(18,prm["min_adx"]): warnings.append("ADX منخفض؛ السوق قد يكون عرضياً أو أقل من الحد المطلوب")
    if not opportunity: warnings.append("ليست فرصة مؤكدة (درجة C): الشروط الثلاثة غير متوفرة معاً")
    atr=float(c["atr"]) if np.isfinite(c["atr"]) and float(c["atr"])>0 else float(price)*0.004
    atr_1h=float(b["atr"]) if np.isfinite(b["atr"]) else None
    lv=v10_levels(price,side,atr,atr_1h,prm)
    return {"side":side,"grade":grade,"score":score,"opportunity":opportunity,"reasons":reasons,"warnings":warnings,
            "factors":{"regime_4h":"bullish" if bull4 else "bearish" if bear4 else "mixed",
                       "regime_aligned":bool(regime_ok),"confirm_1h":bool(confirm),"trigger_15m":bool(trigger),
                       "adx_4h":round(adx4,2),"rvol_15m":round(rv,2) if rv else None},
            "atr":atr,"atr_1h":atr_1h,"lv":lv,"forced":not opportunity,"strategy":"Ryma v10 Adaptive Hybrid",
            "confidence":None,"confidence_type":"not_calibrated",
            "setup":"LGR / Breakout MTF","invalidation":"إغلاق 15M خلف مستوى الوقف"}


def _ryma_ai_decision(sym, df, df_1h, df_15m, price, deriv, ai_context):
    """ONE decision engine for everything (live scan, radars, golden, spot, backtest): Ryma v10.
    No second strategy, no hidden fallback, no remote model."""
    if df is None or len(df)<60 or not np.isfinite(float(price)) or float(price)<=0: raise NoData(sym)
    return _ryma_v10_hybrid_decision(sym,df_1h,df_15m,float(price),ai_context)



def analyze(sym):
    """Live analysis = the v10 engine evaluated AS-OF the last closed 15m candle (exactly what /bt replays).
    4H and 1H frames are clipped to candles already closed at that moment; entry price = that 15m close."""
    tf="1h"
    df_raw=get_candles(sym,tf,450)
    degraded=bool(df_raw.attrs.get("degraded")); source=df_raw.attrs.get("source","unknown")
    df_15m=get_candles(sym,"15m",220,ttl=120,min_bars=80)          # mandatory: it is the trigger timeframe
    df_4h=get_candles(sym,"4h",260,ttl=180,min_bars=100)           # mandatory: it is the regime timeframe
    required_frames={"1h":df_raw,"15m":df_15m,"4h":df_4h}
    frame_sources={tf:frame.attrs.get("source","unknown") for tf,frame in required_frames.items()}
    def _futures_venue(src):
        if src in ("binance_fut","binance_usdm"): return "binance"
        if src.endswith("_linear_swap"): return src.split("_",1)[0]
        return None
    venues={tf:_futures_venue(src) for tf,src in frame_sources.items()}
    non_futures=[tf for tf,frame in required_frames.items()
                 if frame.attrs.get("market_type")=="spot" or venues[tf] is None]
    if non_futures or len(set(venues.values()))!=1:
        raise NoData(f"{sym}: Futures candles unavailable or timeframe venues differ ({frame_sources}); signal withheld")
    source=frame_sources["1h"]
    degraded=venues["1h"]!="binance"
    df_d=None
    try:
        daily_frame=get_candles(sym,"1d",260,ttl=300,min_bars=100)
        if _futures_venue(daily_frame.attrs.get("source","unknown"))==venues["1h"]:
            df_d=daily_frame
    except Exception as ex: log.debug("daily Futures context unavailable %s: %s",sym,ex)
    asof=int(df_15m["t"].iloc[-1])+TF_MS["15m"]
    df_raw=df_raw[df_raw["t"]+TF_MS["1h"]<=asof].reset_index(drop=True)
    df_4h=df_4h[df_4h["t"]+TF_MS["4h"]<=asof].reset_index(drop=True)
    df=add_indicators(df_raw,100)
    if len(df)<220: raise NoData(f"{sym}: شموع غير كافية للتحليل")
    price=float(df_15m["close"].iloc[-1]); bar_t=int(df_15m["t"].iloc[-1])
    if not np.isfinite(price) or price<=0: raise NoData(sym)
    try: deriv=derivatives_snapshot(sym)
    except Exception as ex:
        log.debug("derivatives unavailable %s: %s",sym,ex); deriv={}
    try: ai_context=adaptive_ai_context(sym,df_raw,df_15m,deriv,primary_df=df)
    except Exception as ex:
        log.warning("context partial for %s: %s",sym,ex); ai_context={"notes":["بيانات مشتقات/تدفق غير مكتملة"]}
    if df_4h is not None and len(df_4h)>=210:
        ai_context["_df_4h"]=add_indicators(df_4h,100)
    ai_context["timeframe_stack"]=["4h","1h","15m"]
    ai_context["regime_1d"]=_ai_regime_from_df(df_d,"1d") if df_d is not None and len(df_d)>55 else None
    ai_context["regime_4h"]=_ai_regime_from_df(df_4h,"4h") if df_4h is not None else None
    ai_context["regime_1h"]=_ai_regime_from_df(df_raw,"1h")
    ai_context["regime_15m"]=_ai_regime_from_df(df_15m,"15m")
    df_15m_ai=add_indicators(df_15m,50)
    decision=_ryma_ai_decision(sym,df,df,df_15m_ai,price,deriv,ai_context)
    side=int(decision["side"]); grade=decision["grade"]; lv=decision["lv"]
    trend=detect_trend(df,len(df)-1); bias_d=daily_bias(add_indicators(df_d,100)) if df_d is not None and len(df_d)>100 else 0
    candle=detect_candle_pattern(df,len(df)-1)
    sr_high,sr_low=find_sr_levels(df); fibs=fib_levels(df)
    patterns=[]; seen=set()
    for pat_tf in ("1d","4h","1h"):
        try:
            if pat_tf=="1d":
                if df_d is None: continue
                p_df=add_indicators(df_d,100)
            else:
                p_df=df if pat_tf==tf else add_indicators(get_candles(sym,pat_tf,300,ttl=600,min_bars=100,preferred_source=source),100)
            for pat in detect_all_patterns(p_df,pat_tf):
                if pat.get("name") not in seen: seen.add(pat.get("name")); patterns.append(pat)
        except Exception as ex: log.debug("pattern context %s/%s: %s",sym,pat_tf,ex)
    warnings=list(decision.get("warnings") or [])
    if degraded: warnings.append("مصدر الشموع بديل؛ تحقق من تطابق السعر مع منصة تنفيذك.")
    warnings.append("القرار من محرك Ryma v10 (قواعد 4H+1H+15M) وليس نموذج تعلّم آلي؛ احتمالات ML المعروضة للمعلومات فقط.")
    opp=bool(decision.get("opportunity"))
    return dict(sym=sym,tf=tf,exec_tf=V10_EXEC_TF,timeframe_stack=["4h","1h","15m"],df=df,side=side,strategy=decision["strategy"],
      rank={"A":2,"B":1,"C":0}.get(grade,0),grade=grade,setup=decision.get("setup",decision["strategy"]),
      opportunity=opp,ok=1 if opp else 0,total=3,wait=False,forced=not opp,wait_reasons=warnings,
      reasons=decision.get("reasons",[]),warnings=list(dict.fromkeys(warnings)),score=decision.get("score",0),
      confidence=None,confidence_type="not_calibrated",watch=None,trends={"1d":bias_d,"4h":0,"1h":0},
      lv=lv,price=price,degraded=degraded,source=source,bar_t=bar_t,bar_t_1h=int(df.iloc[-1]["t"]),
      rsi=float(df.iloc[-1]["rsi"]) if pd.notna(df.iloc[-1]["rsi"]) else 50.0,
      macd=float(df.iloc[-1]["macd"]) if pd.notna(df.iloc[-1]["macd"]) else 0.0,
      candle=candle,trend=trend,trend_d=("down" if bias_d==-1 else ("up" if bias_d==1 else "range")),
      sr_high=sr_high[:3],sr_low=sr_low[:3],fibs=fibs,fut_score=0,fut_details=[],patterns=patterns,
      factor_scores=decision.get("factors",{}),derivatives_status=deriv.get("source_status",{}),
      ai_context=ai_context,ai_model=RYMA_AI_MODEL,invalidation=decision.get("invalidation",""))

def get_analysis(sym,force=False):
    if len(_analysis_cache)>300: _analysis_cache.clear()
    hit=_analysis_cache.get(sym)
    if hit and not force and time.time()-hit[0]<45: return hit[1]
    res=analyze(sym); _analysis_cache[sym]=(time.time(),res); return res

def scan_sync(symbols,workers=SCAN_WORKERS):
    def one(s):
        try: return get_analysis(s)
        except Exception: return None
    with ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(one,symbols) if r]

def _is_shadow(p): return bool(p.get("shadow")) or p.get("setup")=="RADAR"

MAX_HOLD_BARS_BY_TF = {"15m":V10_MAX_HOLD_BARS, "30m":96, "1h":48, "4h":12, "1d":2}

def max_hold_bars(tf, requested=None):
    """Return a hard-capped holding period: never more than MAX_HOLD_HOURS wall-clock hours."""
    cap=int(MAX_HOLD_BARS_BY_TF.get(tf, 1))
    try:
        wanted=int(requested) if requested is not None else cap
    except (TypeError, ValueError):
        wanted=cap
    return max(1, min(cap, wanted))

def new_trade(sym,tf,side,lv,bar_t,grade,setup,size_pct=0.05,shadow=False,max_hold=None):
    created_ms=int(time.time()*1000)
    hold=max_hold_bars(tf,max_hold)
    expiry_ms=created_ms+min(hold*TF_MS.get(tf,TF_MS["15m"]),MAX_HOLD_HOURS*60*60*1000)
    return dict(id=f"{sym}-{tf}-{bar_t}"+("-S" if shadow else ""),coin=sym,tf=tf,side=side,grade=grade,setup=setup,
                entry=lv["entry"],sl=lv["sl"],original_sl=lv["sl"],risk=lv["risk"],shadow=bool(shadow),
                size_pct=size_pct,tps=[dict(t) for t in lv["tps"]],state="open",
                wait=0,fill=lv["entry"],ext=lv["entry"],last_mark=None,remaining=1.0,realized=0.0,
                bars=0,be=False,trail_on=False,mfe=0.0,mae=0.0,max_hold=hold,
                created=created_ms,opened=created_ms,expires_at=expiry_ms,
                closed=None,next_t=int(bar_t)+TF_MS[tf],R=None,result=None)

def _tighten(side,cur,new): return max(cur,new) if side==1 else min(cur,new)

def trade_cost_r(p):
    """Round-trip fees + slippage + funding estimate, in R. Same formula for live trades and /bt."""
    fill=float(p.get("fill") or p.get("entry") or 0.0); risk=float(p.get("risk") or 0.0)
    if fill<=0 or risk<=0: return 0.0
    hours=min(float(MAX_HOLD_HOURS),max(0,int(p.get("bars",0)))*TF_MS.get(p.get("tf"),TF_MS["15m"])/3_600_000)
    return (2*(FEE+SLIP)+FUNDING_8H*hours/8.0)*fill/risk

def _finish(p,ev,kind):
    p["remaining"],p["state"],p["result"]=0.0,"closed",kind
    p["closed"]=int(time.time()*1000)
    p["R"]=round(p["realized"]-trade_cost_r(p),3); ev.append(dict(kind="DONE")); return ev

def close_at(p,price,kind,ev=None):
    ev=[] if ev is None else ev
    p["realized"]+=p["remaining"]*p["side"]*(price-p["fill"])/p["risk"]
    ev.append(dict(kind=kind,px=price)); return _finish(p,ev,kind)

def trade_step(p,o,h,l,c,atr):
    """One closed bar of trade management. Used by the live tracker AND by /bt (identical behaviour).
    Order on every bar: stop first (conservative) -> targets -> break-even -> trailing -> time stop."""
    ev,s=[],p["side"]
    if p["state"] not in ("pending","open"): return ev
    p["bars"]+=1; fill,risk=p["fill"],p["risk"]
    p["last_mark"]=float(c)
    fav,adv=(h,l) if s==1 else (l,h)
    p["mfe"]=max(p["mfe"],s*(fav-fill)/risk); p["mae"]=max(p["mae"],s*(fill-adv)/risk)
    if (s==1 and l<=p["sl"]) or (s==-1 and h>=p["sl"]):
        kind="TRAIL" if p["trail_on"] else ("BE" if p["be"] else "SL")
        stop_px=min(o,p["sl"]) if s==1 else max(o,p["sl"])      # a gap through the stop fills at the open
        return close_at(p,stop_px,kind,ev)
    for j,tp in enumerate(p["tps"]):
        if tp["hit"]: continue
        if not ((s==1 and h>=tp["px"]) or (s==-1 and l<=tp["px"])): break
        tp["hit"]=True
        p["realized"]+=tp["frac"]*s*(tp["px"]-fill)/risk
        p["remaining"]-=tp["frac"]
        ev.append(dict(kind="TP",j=j+1,px=tp["px"],pct=tp["pct"]))
    if p["remaining"]<=1e-9: return _finish(p,ev,"TP")
    if p["tps"][0]["hit"] and not p["be"]:
        p["sl"]=_tighten(s,p["sl"],fill+s*BE_OFFSET_R*risk); p["be"]=True
        ev.append(dict(kind="BE_MOVED",px=p["sl"]))
    p["ext"]=max(p["ext"],h) if s==1 else min(p["ext"],l)
    if sum(t["hit"] for t in p["tps"])>=2:
        p["trail_on"]=True
        if atr and atr>0: p["sl"]=_tighten(s,p["sl"],p["ext"]-s*TRAIL_ATR*atr)
    # Conservative same-candle handling: if TP1/TP2 moves the stop and that NEW
    # stop is also inside this candle's range, assume target first then stop.
    # OHLC cannot reveal the intrabar path; ignoring this touch would be optimistic.
    if (s==1 and l<=p["sl"]) or (s==-1 and h>=p["sl"]):
        kind="TRAIL" if p["trail_on"] else ("BE" if p["be"] else "SL")
        return close_at(p,float(p["sl"]),kind,ev)
    # Bar-count stop is capped at MAX_HOLD_HOURS for every timeframe.
    tf_hold=max_hold_bars(p.get("tf"),p.get("max_hold"))
    if p["bars"]>=tf_hold: return close_at(p,c,"TIME",ev)
    return ev

def fmt(x):
    x=float(x)
    if x>=1000: return f"{x:,.2f}"
    if x>=1: return f"{x:.4f}".rstrip("0").rstrip(".")
    if x>=0.01: return f"{x:.5f}"
    return f"{x:.8f}"

def smart_cleanup_trades():
    now_ms=int(time.time()*1000); act=active_signals()
    fill_ratio=len(act)/MAX_OPEN if MAX_OPEN>0 else 0
    closed_profit=closed_age=closed_forced=0
    archived=[]
    with store.lock:
        for p in list(store.data["signals"]):
            if p.get("state") not in ("pending","open"): continue
            # Expired trades must be settled by check_signals_sync at a current/last-known mark,
            # not archived here using stale partial realized P/L after a restart.
            if now_ms>=_trade_expiry_ms(p,now_ms):
                continue
            age_days=(now_ms-p.get("created",now_ms))/(DAY*1000)
            cur_r=float(p.get("realized",0.0) or 0.0)
            fill=float(p.get("fill") or p.get("entry") or 0.0)
            risk=float(p.get("risk") or 0.0)
            net_r=cur_r-(trade_cost_r(p) if fill>0 and risk>0 else 0.0)
            reason=None
            if age_days>SMART_MAX_AGE_DAYS:
                reason="AGE_CLOSE"; closed_age+=1
            elif age_days>SMART_PROFIT_DAYS and cur_r>2.0:
                reason="PROFIT_TAKE"; closed_profit+=1
            elif fill_ratio>SMART_FILL_TRIGGER and age_days>SMART_FORCE_DAYS and cur_r<0:
                reason="SMART_EXIT"; closed_forced+=1
            if reason:
                p["state"]="closed"; p["result"]=reason
                p["R"]=round(net_r,3); p["closed"]=now_ms
                archived.append(dict(p))
        if archived: store.save("signals")
    # Route every forced close through the same archive path as normal SL/TP exits.
    for p in archived:
        try: _archive(p)
        except Exception as ex: log.warning("cleanup archive failed %s: %s",p.get("id"),ex)
    return len(archived)

def _trade_expiry_ms(p, now_ms=None):
    now_ms=int(now_ms or time.time()*1000)
    tf=p.get("tf","15m")
    hold=max_hold_bars(tf,p.get("max_hold"))
    created=int(p.get("created") or p.get("opened") or now_ms)
    tf_duration=TF_MS.get(tf,TF_MS["15m"])
    hard_deadline=created+MAX_HOLD_HOURS*60*60*1000
    calculated=min(created+hold*tf_duration,hard_deadline)
    expiry=int(p.get("expires_at") or calculated)
    # Clamp old persisted records too: a legacy expiry must never extend beyond MAX_HOLD_HOURS.
    expiry=min(expiry,hard_deadline,calculated)
    if p.get("expires_at")!=expiry or p.get("max_hold")!=hold:
        p["expires_at"]=expiry
        p["max_hold"]=hold
        store.save("signals")
    return expiry

def check_signals_sync():
    notes=[]; by={}
    for p in active_signals(include_shadow=True):
        source=normalize_futures_source(p.get("source","binance_fut"))
        by.setdefault((p["coin"],p["tf"],source),[]).append(p)
    for (coin,tf,source),plist in by.items():
        remaining=[]
        # Expire by UTC wall clock before attempting candle catch-up or holding a store lock over HTTP.
        for p in list(plist):
            try:
                now_ms=int(time.time()*1000)
                with store.lock:
                    if p.get("state") not in ("pending","open"): continue
                    expiry_ms=_trade_expiry_ms(p,now_ms)
                    if p.get("source")!=source: p["source"]=source; store.save("signals")
                    expired=now_ms>=expiry_ms
                if not expired:
                    remaining.append(p)
                    continue
                mark,mark_source=live_price(coin,source)
                if not mark:
                    mark=float(p.get("last_mark") or p.get("fill") or p.get("entry") or 0.0)
                    mark_source="last_known_mark" if p.get("last_mark") else "entry_fallback"
                if mark<=0:
                    log.error("Cannot expire %s: no usable mark price",p.get("id"))
                    continue
                with store.lock:
                    if p.get("state") not in ("pending","open"): continue
                    p["bars"]=max(int(p.get("bars",0)),max_hold_bars(tf,p.get("max_hold")))
                    p["expiry_price_source"]=mark_source
                    close_at(p,float(mark),"TIME",[])
                    store.save("signals")
                    notes.append((coin,tf,p["side"],{"kind":"TIME","px":float(mark),"expiry":True},p.get("R"),p["id"]))
                if p.get("state")=="closed": _archive(p)
            except Exception:
                log.exception("signal expiry failed for %s %s",coin,tf)
        if not remaining:
            continue
        try:
            raw=get_candles(coin,tf,450,min_bars=60,preferred_source=source)
            d=add_indicators(raw,100)
        except Exception:
            log.exception("signal candles unavailable for %s %s",coin,tf)
            continue
        for p in remaining:
            try:
                with store.lock:
                    if p.get("state") not in ("pending","open"): continue
                    # Re-check the deadline after candle retrieval.
                    if int(time.time()*1000)>=_trade_expiry_ms(p):
                        continue
                    rows=d[d["t"]>=p["next_t"]]
                    for row in rows.itertuples():
                        if p.get("state") not in ("pending","open"): break
                        ev=trade_step(p,row.open,row.high,row.low,row.close,row.atr)
                        p["next_t"]=int(row.t)+TF_MS[tf]
                        notes += [(coin,tf,p["side"],e,p.get("R"),p["id"]) for e in ev if e["kind"]!="DONE"]
                        if p["state"] in ("closed","expired"): break
                    store.save("signals")
                if p.get("state")=="closed": _archive(p)
            except Exception:
                log.exception("signal tracker failed for %s %s",coin,tf)
    return notes

def _archive(p):
    with store.lock:
        store.data["history"].append(dict(
            coin=p["coin"],tf=p["tf"],side=p["side"],grade=p["grade"],setup=p["setup"],
            source=p.get("source","binance_fut"),R=p["R"],result=p["result"],opened=p["opened"],closed=p["closed"],
            bars=p["bars"],tps=sum(1 for t in p["tps"] if t["hit"]),
            mfe=round(p["mfe"],2),mae=round(p["mae"],2),fill=p.get("fill"),sl=p.get("sl"),
            tps_list=[dict(t) for t in p["tps"]],realized=p.get("realized",0.0),shadow=_is_shadow(p),tier=p.get("tier","both"),trigger=p.get("trigger","Ryma")))
        del store.data["history"][:-1500]
        cutoff=time.time()*1000-3*DAY*1000
        store.data["signals"]=[q for q in store.data["signals"]
                               if q.get("state","open") in ("pending","open") or
                                  (q.get("closed") or q.get("created",0))>cutoff]
        store.save("signals","history")


def grade_history_stats(grade=None, limit=500):
    """نسبة نجاح تاريخية من سجل الصفقات المغلقة (للأدمن/الشفافية)."""
    try:
        with store.lock:
            h = [x for x in (store.data.get("history") or []) if not x.get("shadow") and x.get("setup")!="RADAR"][-limit:]
        if grade:
            h = [x for x in h if x.get("grade") == grade]
        if not h:
            return None
        wins = sum(1 for x in h if float(x.get("R") or 0) > 0)
        n = len(h)
        rate = 100.0 * wins / n if n else 0.0
        return dict(n=n, wins=wins, rate=round(rate, 1), grade=grade)
    except Exception:
        return None


def format_trade_card(p,event_kind=None,event_data=None,tier="vip"):
    side=p.get("side",1); side_lbl="LONG" if side==1 else "SHORT"; dot="🔵" if side==1 else "🔴"
    coin=p.get("coin") or p.get("sym") or "?"
    tps_all=p.get("tps") or []; tps=tps_all[:FREE_TP_COUNT] if tier=="free" else tps_all
    lines=[f"{dot} <b>{coin}/USDT {side_lbl}</b>","",f"{dot} Entry: {fmt(p.get('fill') or p.get('entry') or 0)}",
           f"📡 Source: {display_source(p.get('source','binance_fut'))}"]
    for i,tp in enumerate(tps,1): lines.append(f"🎯 TP{i}: {fmt(tp['px'])}{'✅' if tp.get('hit') else ''}")
    if p.get("be") and p.get("trail_on"): lines.append(f"🛑 Trail SL: {fmt(p['sl'])}")
    elif p.get("be"): lines.append(f"🛑 BE: {fmt(p['sl'])}")
    else: lines.append(f"🛑 SL: {fmt(p['sl'])}")
    hits=sum(1 for t in tps if t.get("hit"))
    if tier=="free": lines+=["",f"📊 الأهداف المحققة: {hits}/{len(tps)}"]
    else: lines+=["",f"📊 R: {p.get('realized',0.0):+.2f} | TP: {hits}/{len(tps)}"]
    st=grade_history_stats(p.get("grade"))
    if st and st["n"]>=5: lines.append(f"📊 درجة {p.get('grade','?')}: نجاح تاريخي {st['rate']}% من {st['n']} صفقة")
    if p.get("state")=="closed":
        labels={"TP":"✅ صفقة ناجحة بالكامل","SL":"🛑 ضرب وقف الخسارة","BE":"🔒 خروج على التعادل","TRAIL":"🔁 خروج بالوقف المتحرك",
                "TIME":"⏱ انتهت المدة","PROFIT_TAKE":"💰 أخذ الربح الذكي","SMART_EXIT":"🧹 خروج ذكي","AGE_CLOSE":"📅 انتهاء العمر"}
        tail=labels.get(p.get("result",""),"🏁 انتهت")
        lines+=["",tail if tier=="free" else f"{tail} | {p.get('R',0):+.2f}R"]
    lines+=["","📋 تنبيه معلومات — البوت لا ينفّذ صفقات"]
    return "\n".join(lines)


def event_text(coin,tf,side,e,R,tier="free",trade=None):
    k=e["kind"]
    if trade is not None:
        card=format_trade_card(trade,k,e,tier=tier)
        headers={"TP":f"🎯 <b>تحقق الهدف {e['j']}</b>\n\n","SL":"🛑 <b>ضرب وقف الخسارة</b>\n\n",
                 "BE":"🔒 <b>خروج على التعادل</b>\n\n","TRAIL":"🔁 <b>خروج بالوقف المتحرك</b>\n\n",
                 "TIME":"⏱ <b>انتهت المدة</b>\n\n","BE_MOVED":"🔒 <b>نُقل الوقف للتعادل</b>\n\n",
                 "ENTRY":"✅ <b>تفعّل الدخول</b>\n\n"}
        return headers.get(k,"")+card
    return None

def _build_daily_lists(force_side=None):
    """يبني دائماً حتى 2 LONG و 2 SHORT قدر الإمكان (A+/A/B أولاً ثم C كاحتياطي)."""
    gainers, losers = get_top_movers(force=True)
    all_movers = gainers + losers
    top_syms = [x["symbol"] for x in all_movers[:40]]
    if len(top_syms) < 20:
        top_syms.extend(top_symbols(30))
    # أضف أقوى الرابحين/الخاسرين صراحةً لضمان توازن الاتجاه
    top_syms = list(dict.fromkeys(
        [x["symbol"] for x in gainers[:15]] +
        [x["symbol"] for x in losers[:15]] +
        top_syms + top_symbols(40)
    ))
    results = scan_sync(top_syms[:50])
    longs, shorts = [], []

    def _add(pool, r, mv):
        if any(x["res"]["sym"] == r["sym"] for x in pool):
            return
        pool.append(dict(res=r, change=mv.get("change", 0), volume=mv.get("volume", 0)))

    # مرور 1: درجات جيدة
    for r in sorted(results, key=lambda x: -{"A+":3,"A":2,"B":1,"C":0}.get(x.get("grade"), -1)):
        if r.get("grade") not in ("A+", "A", "B"):
            continue
        if r["sym"] in EXCLUDE_TICKERS:
            continue
        mv = next((x for x in all_movers if x["symbol"] == r["sym"]), {"change": 0, "volume": 0})
        if r["side"] == 1 and len(longs) < 2:
            _add(longs, r, mv)
        elif r["side"] == -1 and len(shorts) < 2:
            _add(shorts, r, mv)

    # مرور 2: أي درجة (بما فيها C) لملء الناقص
    if len(longs) < 2 or len(shorts) < 2:
        for r in results:
            if r["sym"] in EXCLUDE_TICKERS:
                continue
            mv = next((x for x in all_movers if x["symbol"] == r["sym"]), {"change": 0, "volume": 0})
            if r["side"] == 1 and len(longs) < 2:
                _add(longs, r, mv)
            elif r["side"] == -1 and len(shorts) < 2:
                _add(shorts, r, mv)

    # مرور 3: من أقوى الرابحين/الخاسرين مع قبول أي اتجاه محلل
    if len(longs) < 2:
        for g in gainers:
            if len(longs) >= 2: break
            if g["symbol"] in EXCLUDE_TICKERS: continue
            if any(x["res"]["sym"] == g["symbol"] for x in longs + shorts): continue
            try:
                r = get_analysis(g["symbol"], force=True)
                if not r or not r.get("lv"): continue
                if r.get("wait") or r.get("side") != 1: continue
                _add(longs, r, g)
            except Exception:
                continue
    if len(shorts) < 2:
        for g in losers:
            if len(shorts) >= 2: break
            if g["symbol"] in EXCLUDE_TICKERS: continue
            if any(x["res"]["sym"] == g["symbol"] for x in longs + shorts): continue
            try:
                r = get_analysis(g["symbol"], force=True)
                if not r or not r.get("lv"): continue
                if r.get("wait") or r.get("side") != -1: continue
                _add(shorts, r, g)
            except Exception:
                continue
    return longs[:2], shorts[:2]

def _format_daily_card(res,side_label,change,volume):
    lv=res["lv"]; decision="🟢 شراء" if res["side"]==1 else "🔴 بيع"
    cl=coin_link(res['sym'],res.get("source","binance_fut"))
    lines=[side_label,"",
           f"📌 <a href='{cl}'>#{res['sym']}/USDT</a> 👆 اضغط هنا",
           f"📡 {display_source(res.get('source','binance_fut'))}",
           f"➡️ Entry: {fmt(lv['entry'])}"]
    for i,tp in enumerate(lv["tps"][:DAILY_TP_COUNT],1):
        lines.append(f"🎯 Target {i}: {fmt(tp['px'])}")
    lines+=[f"🛑 Stop loss: {fmt(lv['sl'])}",""]
    pats=res.get("patterns",[])
    if pats:
        pat_names=" | ".join(
            f"{p['name']}{'[' + p.get('tf','').upper() + ']' if p.get('tf') else ''} {'🟢' if p['bias']=='bullish' else ('🔴' if p['bias']=='bearish' else '⚪')}"
            for p in pats[:2])
        lines.append(f"🕯 النموذج: {pat_names}"); lines.append("")
    lines+=[f"🎯 <b>القرار المتوقع: {decision}</b>",
            f"📊 {'🔺' if change >= 0 else '🔻'} {change:+.1f}% | 💰 ${volume/1_000_000:.1f}M"]
    return "\n".join(lines)


def golden_score(sym,debug=False,relaxed=False):
    """Golden = a CONFIRMED v10 opportunity. Strict: grade A. Relaxed: grade B. Unconfirmed (C) is never golden."""
    try:
        res=get_analysis(sym)
        if not res or not res.get("lv") or not res.get("opportunity"): return None
        grade=res.get("grade","C")
        if grade not in ("A+","A") and not (relaxed and grade=="B"): return None
        rank={"A+":4,"A":3,"B":2,"C":1}.get(grade,0)
        return dict(sym=sym,side=res["side"],score=rank*100+float(res.get("score",0)),
          reasons=list(res.get("reasons",[]))+list(res.get("warnings",[])),price=res["price"],
          atr=res["lv"].get("atr"),sl=res["lv"]["sl"],tps=[x["px"] for x in res["lv"]["tps"]],
          risk=res["lv"]["risk"],trend_1d=res.get("trend_d"),trend_4h=res.get("trend"),
          change_7d=0,rsi=res.get("rsi"),rvol=None,source=res.get("source"),patterns=res.get("patterns",[]),grade=grade)
    except Exception as ex:
        if debug: return dict(sym=sym,score=0,reasons=[str(ex)[:160]])
        return None

def _run_golden_scan(syms,max_results,progress_cb,relaxed=False):
    results=[]; total=len(syms)
    def scan_one(sym):
        try:
            time.sleep(0.05)
            return golden_score(sym,debug=False,relaxed=relaxed)
        except Exception: return None
    processed=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures={executor.submit(scan_one,s):s for s in syms}
        for future in concurrent.futures.as_completed(futures):
            processed+=1
            res=future.result()
            if res: results.append(res)
            if progress_cb and processed%50==0:
                try: progress_cb(processed,total,len(results))
                except Exception as _ex: log.debug('ignored: %s', _ex)
    results.sort(key=lambda x:-x["score"])
    return results[:max_results]

def golden_scan(max_results=2,progress_cb=None):
    try:
        rows=binance_futures_all_tickers()
        if rows:
            rows_sorted=sorted(rows,key=lambda x:-x["volume"])
            syms=[x["symbol"] for x in rows_sorted if x["volume"]>2_000_000 and x["symbol"] not in EXCLUDE_TICKERS][:150]
        else: syms=top_symbols(600,binance_only=True)
    except Exception: syms=top_symbols(600,binance_only=True)
    if not syms: return []
    results=_run_golden_scan(syms,max_results,progress_cb,relaxed=False)
    if not results:
        log.info("golden_scan: no strict results, trying relaxed mode on top 200")
        results=_run_golden_scan(syms[:150],max_results,progress_cb,relaxed=True)
    return results

def format_golden_post(g,tier="vip"):
    side_word="🟢 شراء (LONG)" if g["side"]==1 else "🔴 بيع (SHORT)"
    decision="🟢 شراء" if g["side"]==1 else "🔴 بيع"
    cl=coin_link(g['sym'],g.get("source","binance_fut"))
    lines=["🏆✨ <b>الفرصة الذهبية</b> ✨🏆","━━━━━━━━━━━━━━━━━━━━━",
        f"📌 <a href='{cl}'>#{g['sym']}/USDT</a> 👆 اضغط هنا",
        f"📡 المصدر: <b>{display_source(g.get('source','binance_fut'))}</b>",
        f"🏆 التقييم: <b>{g['score']} نقطة</b>","━━━━━━━━━━━━━━━━━━━━━","",
        f"🎯 الاتجاه: <b>{side_word}</b>",
        f"💵 الدخول: <code>{fmt(g['price'])}</code>",
        f"🛑 وقف الخسارة: <code>{fmt(g['sl'])}</code>","",
        "🎯 <b>الأهداف (الأسعار):</b>"]
    for i,tp in enumerate(g["tps"],1):
        emoji=["🥇","🥈","🥉","🏅"][i-1]
        lines.append(f"{emoji} هدف {i}: <code>{fmt(tp)}</code>")
    lines+=["","━━━━━━━━━━━━━━━━━━━━━",f"🎯 <b>القرار المتوقع: {decision}</b>",
            "","🔍 <b>لماذا الفرصة الذهبية؟</b>"]
    for r in g["reasons"][:8]: lines.append(f"  • {r}")
    if g.get("patterns"):
        lines.append(""); lines.append("🕯 <b>النماذج الفنية:</b>")
        for p in g["patterns"][:3]:
            emoji="🟢" if p["bias"]=="bullish" else ("🔴" if p["bias"]=="bearish" else "⚪")
            tf_lbl=f" [{p.get('tf','').upper()}]" if p.get('tf') else ""
            lines.append(f"  {emoji} {p['name']}{tf_lbl}")
    lines+=["","━━━━━━━━━━━━━━━━━━━━━",RISK_WARNING_AR,f"👤 {BRAND}"]
    return "\n".join(lines)

def build_whale_tweet(sym,side,notional,price):
    side_emoji="🟢 شراء" if side=="buy" else "🔴 بيع"
    name,ref=referral_for("binance_fut")
    text=(f"📢 صفقة كبيرة مرصودة على Binance\n\n"
          f"💰 صفقة {side_emoji} ضخمة على #{sym}/USDT\n"
          f"💵 بقيمة: ${notional:,.0f}\n📊 السعر: {fmt(price)}\n\n"
          f"⚡️ الصفقات الكبيرة قد تؤثر على السعر\n"
          f"🔗 للتداول على المنصة:\n{ref}\n\n👤 Ryma Crypto")
    share_url=f"https://twitter.com/intent/tweet?text={urllib.parse.quote(text)}"
    return text,share_url

def build_social_text(res,platform="binance"):
    side=res["side"]; lv=res["lv"]; sym=res["sym"]
    side_word="LONG 🟢" if side==1 else "SHORT 🔴"
    meta=PLATFORM_META.get(platform,PLATFORM_META["binance"])
    emoji=meta["emoji"]; trade_link=coin_link(sym,"binance_fut")
    tag=meta.get("tags","#Binance")
    hashtags=f"#{sym}USDT {tag} #CryptoTrading"
    return (f"{emoji} {sym}/USDT — {side_word}\n\n"
            f"💵 Entry: {fmt(lv['entry'])}\n"
            f"🎯 TP1: {fmt(lv['tps'][0]['px'])}\n"
            f"🎯 TP2: {fmt(lv['tps'][1]['px'])}\n"
            f"🎯 TP3: {fmt(lv['tps'][2]['px'])}\n"
            f"🎯 TP4: {fmt(lv['tps'][3]['px'])}\n"
            f"🛑 SL: {fmt(lv['sl'])}\n\n"
            f"👉 {trade_link}\n\n"
            f"{hashtags}")

def build_copy_post(res):
    side,lv,sym=res["side"],res["lv"],res["sym"]
    side_word="LONG" if side==1 else "SHORT"
    dot="🔵" if side==1 else "🔴"
    lines=[f"{dot} {sym}/USDT {side_word}","",f"{dot} Entry: {fmt(lv['entry'])}"]
    for i,tp in enumerate(lv["tps"][:4],1):
        lines.append(f"🎯 TP{i}: {fmt(tp['px'])}")
    lines.append(f"🛑 SL: {fmt(lv['sl'])}")
    grade=res.get("grade","?")
    lines+=["",f"🏆 الدرجة: {grade}"]
    st=grade_history_stats(grade)
    if st and st["n"]>=5:
        lines.append(f"📊 درجة {grade}: نجاح تاريخي {st['rate']}% من {st['n']} صفقة")
    return chr(10).join(lines)


async def send_admin_copy(msg_obj,res):
    try:
        await msg_obj.reply_text(build_copy_post(res)+"\n\n"+admin_stats_line(res),
                                  parse_mode=None,link_preview_options=NO_PREVIEW)
    except Exception as e: log.warning(f"send_admin_copy: {e}")

def keyboard_share_post(res):
    trade_meta=[("binance","🟡","Binance Square"),("bybit","🔵","Bybit"),("okx","⚫","OKX"),
                ("bitget","🟢","Bitget"),("kucoin","🟢","KuCoin"),("gateio","⚪","Gate"),
                ("twitter","🐦","Twitter (X)"),("telegram","📱","Telegram"),("facebook","📘","Facebook"),
                ("whatsapp","💬","WhatsApp"),("reddit","🔴","Reddit"),("discord","🎮","Discord")]
    trade_rows=[]; general_text=build_copy_post(res)
    trade_rows.append([_btn("📋 نسخ الصفقة",copy_text=CopyTextButton(text=general_text[:250]))])
    for key,emoji,name in trade_meta:
        short_text=build_social_text(res,key)
        trade_rows.append([_btn(f"📋 نسخ لـ {emoji} {name}",copy_text=CopyTextButton(text=short_text[:250]))])
    return InlineKeyboardMarkup(trade_rows+[[_btn("❌ إغلاق",callback_data="close_menu")]])

async def notify_both(bot,text,protect=True):
    for chat in (VIP_CHANNEL_ID,ADMIN_ID or None):
        if not chat: continue
        try:
            await bot.send_message(chat,text,parse_mode=ParseMode.HTML,
                                   protect_content=PROTECT if chat!=ADMIN_ID else False,
                                   link_preview_options=NO_PREVIEW)
        except Exception as e: log.warning(f"notify_both {chat}: {str(e)[:80]}")

async def notify_free(bot,text):
    if CHANNEL_ID:
        try:
            await bot.send_message(CHANNEL_ID,text,parse_mode=ParseMode.HTML,
                                   protect_content=PROTECT,link_preview_options=NO_PREVIEW)
        except Exception as e: log.warning(f"notify_free: {str(e)[:80]}")
def _new_fig(w=12,h=8,bg="#ffffff"):
    fig=Figure(figsize=(w,h),facecolor=bg,dpi=200)
    FigureCanvasAgg(fig); return fig
def _to_png(fig):
    buf=io.BytesIO(); fig.savefig(buf,format="png",dpi=200,facecolor=fig.get_facecolor())
    buf.seek(0); return buf
def _draw_candles(ax,df,up,down,width=0.62):
    x=np.arange(len(df))
    o=df["open"].values.astype(float); h=df["high"].values.astype(float)
    l=df["low"].values.astype(float); c=df["close"].values.astype(float)
    colors=np.where(c>=o,up,down)
    ax.vlines(x,l,h,colors=colors,linewidth=1.1,zorder=2)
    body=np.maximum(np.abs(c-o),(h.max()-l.min())*0.0008)
    ax.bar(x,body,bottom=np.minimum(o,c),color=colors,width=width,linewidth=0,zorder=3)
    return x
def _style_axes(axes,bg,fg,grid):
    for a in axes:
        a.set_facecolor(bg); a.tick_params(colors=fg,labelsize=9)
        a.grid(color=grid,lw=0.6,alpha=0.8)
        for sp in a.spines.values(): sp.set_color(grid)
        a.yaxis.tick_right()
def _time_ticks(ax,df,n_ticks=7):
    ts=pd.to_datetime(df["t"],unit="ms")
    step=max(len(df)//n_ticks,1); idx=list(range(0,len(df),step))
    daily=ts.diff().dropna().median()>=pd.Timedelta(hours=24)
    fmt_="%Y-%m-%d" if daily else "%m-%d %H:%M"
    ax.set_xticks(idx)
    ax.set_xticklabels([ts.iloc[i].strftime(fmt_) for i in idx],fontsize=9)
def _right_labels(ax,levels,n,ylo,yhi,fs=9):
    gap=(yhi-ylo)*0.042
    items=sorted([dict(y=px,text=f"{name}  {fmt(px)}",col=col) for name,px,col,_ls in levels],key=lambda z:z["y"])
    for i in range(1,len(items)):
        if items[i]["y"]-items[i-1]["y"]<gap: items[i]["y"]=items[i-1]["y"]+gap
    for it in items:
        ax.text(n+0.8,it["y"]," "+it["text"]+" ",color="white",fontsize=fs,fontweight="bold",
                va="center",ha="left",clip_on=False,zorder=9,
                bbox=dict(boxstyle="round,pad=0.3",fc=it["col"],ec="none"))
def _x_index(t_arr,t_ms): return float(np.clip(np.searchsorted(t_arr,t_ms),0,len(t_arr)-1))

# ======================= شارت TradingView الاحترافي (نماذج + خطوط مرسومة) =======================
TV_BARS=120
TV_BG="#131722"; TV_GRID="#1c2230"; TV_TXT="#b2b5be"; TV_UP="#26a69a"; TV_DN="#ef5350"
TV_COL={"bullish":"#2ebd85","bearish":"#f6465d","neutral":"#f0b90b"}
TV_IV={"15m":"15","1h":"60","4h":"240","1d":"D"}

def _tv_pivots(df,w=4):
    H=df["high"].to_numpy(float); L=df["low"].to_numpy(float); n=len(df); hs=[]; ls=[]
    for k in range(w,n-w):
        if H[k]>=H[k-w:k+w+1].max(): hs.append((k,float(H[k])))
        if L[k]<=L[k-w:k+w+1].min(): ls.append((k,float(L[k])))
    def dedupe(p,keep_max):
        out=[]
        for k,v in p:
            if out and k-out[-1][0]<w:
                if (v>out[-1][1])==keep_max: out[-1]=(k,v)
            else: out.append((k,v))
        return out
    return dedupe(hs,True),dedupe(ls,False)

def _tv_classify(mh,ml,conv,L,pole,prior):
    """mh/ml: ميل الخطين بوحدات ATR على كامل النافذة. conv: عرض النهاية/عرض البداية."""
    flat,_ = 1.2,0
    h_flat=abs(mh)<flat; l_flat=abs(ml)<flat
    h_up=mh>=flat; h_dn=mh<=-flat; l_up=ml>=flat; l_dn=ml<=-flat
    pb="bullish" if prior>0 else ("bearish" if prior<0 else "neutral")
    if conv<0.78:
        if L<=35 and conv<0.65 and abs(pole)>=5: return "Pennant","bullish" if pole>0 else "bearish"
        if h_flat and l_up: return "Ascending Triangle","bullish"
        if l_flat and h_dn: return "Descending Triangle","bearish"
        if h_dn and l_up: return "Symmetrical Triangle",pb
        if h_up and l_up: return "Rising Wedge","bearish"
        if h_dn and l_dn: return "Falling Wedge","bullish"
        return None
    if conv<=1.35:
        if abs(pole)>=5 and L<=45:
            if pole>0 and mh<=0.5 and ml<=0.5: return "Bull Flag","bullish"
            if pole<0 and mh>=-0.5 and ml>=-0.5: return "Bear Flag","bearish"
        if h_flat and l_flat: return "Rectangle",pb
        if h_up and l_up: return "Ascending Channel","bullish"
        if h_dn and l_dn: return "Descending Channel","bearish"
    return None

def _tv_channel_patterns(df,hs,ls):
    """مثلثات/أوتاد/أعلام/قنوات/مستطيل: خطوط مرسومة على القمم والقيعان الفعلية."""
    H=df["high"].to_numpy(float); L=df["low"].to_numpy(float); C=df["close"].to_numpy(float)
    n=len(df); atr=float(df["atr"].iloc[-1]) if "atr" in df and not pd.isna(df["atr"].iloc[-1]) else float(np.mean(H-L))
    if atr<=0: return []
    e=n-1; best=None
    for Lw in (25,35,50,70,95):
        s=max(0,e-Lw)
        if e-s<20: continue
        ph=[(k,v) for k,v in hs if s<=k<=e]; pl=[(k,v) for k,v in ls if s<=k<=e]
        if len(ph)<2 or len(pl)<2: continue
        xh=np.array([k for k,_ in ph],float); yh=np.array([v for _,v in ph])
        xl=np.array([k for k,_ in pl],float); yl=np.array([v for _,v in pl])
        mh=float(np.polyfit(xh,yh,1)[0]); ml=float(np.polyfit(xl,yl,1)[0])
        bh=float(np.max(yh-mh*xh)); bl=float(np.min(yl-ml*xl))
        up=lambda x:mh*x+bh; lo=lambda x:ml*x+bl
        span=e-s; w0=up(s)-lo(s); w1=up(e)-lo(e)
        if w0<=0.5*atr or w1<=0.3*atr: continue
        th=sum(1 for k,v in ph if abs(v-up(k))<=0.45*atr); tl=sum(1 for k,v in pl if abs(v-lo(k))<=0.45*atr)
        if th<2 or tl<2: continue
        xs=np.arange(s,e+1)
        out_frac=float(np.mean((C[s:e+1]>up(xs)+0.5*atr)|(C[s:e+1]<lo(xs)-0.5*atr)))
        if out_frac>0.10: continue
        pole=(C[s]-C[max(0,s-12)])/atr; prior=C[s]-C[max(0,s-30)]
        prior=1 if prior>2*atr else (-1 if prior<-2*atr else 0)
        cl=_tv_classify(mh*span/atr,ml*span/atr,w1/w0,span,pole,prior)
        if not cl: continue
        name,bias=cl; score=th+tl+min(span,60)/30
        if best is None or score>best["score"]:
            best=dict(score=score,s=s,e=e,up=up,lo=lo,name=name,bias=bias,w0=w0,pole=abs(pole)*atr,th=ph,tl=pl)
    if best is None:
        return []
    s,e,up,lo,name,bias=best["s"],best["e"],best["up"],best["lo"],best["name"],best["bias"]
    ext=10 if "Channel" not in name and name!="Rectangle" else 8
    c_last=C[-1]
    status="forming"; target=None
    if c_last>up(e)+0.1*atr: status="breakout ↑"
    elif c_last<lo(e)-0.1*atr: status="breakout ↓"
    if name not in ("Ascending Channel","Descending Channel","Rectangle"):
        h=best["pole"] if name in ("Bull Flag","Bear Flag","Pennant") and best["pole"]>0 else best["w0"]
        if bias=="bullish" or status=="breakout ↑": target=up(e)+h
        elif bias=="bearish" or status=="breakout ↓": target=lo(e)-h
        else: target=None
    lines=[dict(i1=s,p1=up(s),i2=e+ext,p2=up(e+ext),role="upper"),
           dict(i1=s,p1=lo(s),i2=e+ext,p2=lo(e+ext),role="lower")]
    poly=[(s,up(s)),(e,up(e)),(e,lo(e)),(s,lo(s))]
    marks=[(k,v,"") for k,v in best["th"]+best["tl"]]
    return [dict(name=name,bias=bias,status=status,lines=lines,poly=poly,marks=marks,
                 target=target,anchor=(s,up(s)),tf_span=e-s,kind="channel",e=e)]

def _tv_pivot_patterns(df,hs,ls):
    """قمة/قاع مزدوج وثلاثي + رأس وكتفين (ومقلوب) مع خط العنق."""
    H=df["high"].to_numpy(float); L=df["low"].to_numpy(float); C=df["close"].to_numpy(float); n=len(df)
    out=[]; last=C[-1]
    def near(a,b,tol): return abs(a-b)/max(a,b)*100<=tol
    def add(name,bias,conf,lines,marks,target,anchor,e):
        out.append(dict(name=name,bias=bias,status="confirmed" if conf else "forming",lines=lines,poly=None,
                        marks=marks,target=target,anchor=anchor,kind="pivot",e=e))
    # H&S
    if len(hs)>=3 and n-hs[-1][0]<=45 and len(ls)>=2:
        a,b,c=hs[-3],hs[-2],hs[-1]
        if b[1]>a[1] and b[1]>c[1] and near(a[1],c[1],4.0) and c[0]-a[0]>=14:
            t1=[x for x in ls if a[0]<x[0]<b[0]]; t2=[x for x in ls if b[0]<x[0]<c[0]]
            if t1 and t2:
                n1=min(t1,key=lambda x:x[1]); n2=min(t2,key=lambda x:x[1])
                m=(n2[1]-n1[1])/(n2[0]-n1[0]); neck=lambda x:n1[1]+m*(x-n1[0])
                conf=last<neck(n-1)
                add("Head & Shoulders","bearish",conf,
                    [dict(i1=a[0],p1=a[1],i2=b[0],p2=b[1],role="pattern"),dict(i1=b[0],p1=b[1],i2=c[0],p2=c[1],role="pattern"),
                     dict(i1=n1[0],p1=n1[1],i2=n-1+8,p2=neck(n-1+8),role="neck")],
                    [(a[0],a[1],"LS"),(b[0],b[1],"H"),(c[0],c[1],"RS"),(n1[0],n1[1],""),(n2[0],n2[1],"")],
                    neck(c[0])-(b[1]-neck(b[0])),(a[0],a[1]),n-1)
    if len(ls)>=3 and n-ls[-1][0]<=45 and len(hs)>=2:
        a,b,c=ls[-3],ls[-2],ls[-1]
        if b[1]<a[1] and b[1]<c[1] and near(a[1],c[1],4.0) and c[0]-a[0]>=14:
            t1=[x for x in hs if a[0]<x[0]<b[0]]; t2=[x for x in hs if b[0]<x[0]<c[0]]
            if t1 and t2:
                n1=max(t1,key=lambda x:x[1]); n2=max(t2,key=lambda x:x[1])
                m=(n2[1]-n1[1])/(n2[0]-n1[0]); neck=lambda x:n1[1]+m*(x-n1[0])
                conf=last>neck(n-1)
                add("Inverse Head & Shoulders","bullish",conf,
                    [dict(i1=a[0],p1=a[1],i2=b[0],p2=b[1],role="pattern"),dict(i1=b[0],p1=b[1],i2=c[0],p2=c[1],role="pattern"),
                     dict(i1=n1[0],p1=n1[1],i2=n-1+8,p2=neck(n-1+8),role="neck")],
                    [(a[0],a[1],"LS"),(b[0],b[1],"H"),(c[0],c[1],"RS"),(n1[0],n1[1],""),(n2[0],n2[1],"")],
                    neck(c[0])+(neck(b[0])-b[1]),(a[0],a[1]),n-1)
    # Triple / Double top
    if len(hs)>=3 and n-hs[-1][0]<=40 and near(hs[-1][1],hs[-2][1],1.6) and near(hs[-2][1],hs[-3][1],1.6) \
       and hs[-1][0]-hs[-3][0]>=12:
        a,b,c=hs[-3],hs[-2],hs[-1]; neck=float(L[a[0]:c[0]+1].min()); conf=last<neck
        top=(a[1]+b[1]+c[1])/3
        add("Triple Top","bearish",conf,
            [dict(i1=a[0],p1=top,i2=n-1+8,p2=top,role="pattern"),dict(i1=a[0],p1=neck,i2=n-1+8,p2=neck,role="neck")],
            [(a[0],a[1],"1"),(b[0],b[1],"2"),(c[0],c[1],"3")],neck-(top-neck),(a[0],top),n-1)
    elif len(hs)>=2 and n-hs[-1][0]<=40 and near(hs[-1][1],hs[-2][1],1.5) and hs[-1][0]-hs[-2][0]>=6:
        a,b=hs[-2],hs[-1]; neck=float(L[a[0]:b[0]+1].min()); conf=last<neck; top=(a[1]+b[1])/2
        add("Double Top","bearish",conf,
            [dict(i1=a[0],p1=top,i2=b[0]+6,p2=top,role="pattern"),dict(i1=a[0],p1=neck,i2=n-1+8,p2=neck,role="neck")],
            [(a[0],a[1],"1"),(b[0],b[1],"2")],neck-(top-neck),(a[0],top),n-1)
    if len(ls)>=3 and n-ls[-1][0]<=40 and near(ls[-1][1],ls[-2][1],1.6) and near(ls[-2][1],ls[-3][1],1.6) \
       and ls[-1][0]-ls[-3][0]>=12:
        a,b,c=ls[-3],ls[-2],ls[-1]; neck=float(H[a[0]:c[0]+1].max()); conf=last>neck
        bot=(a[1]+b[1]+c[1])/3
        add("Triple Bottom","bullish",conf,
            [dict(i1=a[0],p1=bot,i2=n-1+8,p2=bot,role="pattern"),dict(i1=a[0],p1=neck,i2=n-1+8,p2=neck,role="neck")],
            [(a[0],a[1],"1"),(b[0],b[1],"2"),(c[0],c[1],"3")],neck+(neck-bot),(a[0],bot),n-1)
    elif len(ls)>=2 and n-ls[-1][0]<=40 and near(ls[-1][1],ls[-2][1],1.5) and ls[-1][0]-ls[-2][0]>=6:
        a,b=ls[-2],ls[-1]; neck=float(H[a[0]:b[0]+1].max()); conf=last>neck; bot=(a[1]+b[1])/2
        add("Double Bottom","bullish",conf,
            [dict(i1=a[0],p1=bot,i2=b[0]+6,p2=bot,role="pattern"),dict(i1=a[0],p1=neck,i2=n-1+8,p2=neck,role="neck")],
            [(a[0],a[1],"1"),(b[0],b[1],"2")],neck+(neck-bot),(a[0],bot),n-1)
    return out

def tv_detect(df):
    """يرجع قائمة نماذج جاهزة للرسم (بإحداثيات رقم الشمعة داخل df). لا يرجع قائمة فارغة أبداً:
    إذا لم يوجد نموذج يرسم قناة الاتجاه (Trend Channel) كي يكون هناك دائماً خطوط واضحة."""
    df=df.reset_index(drop=True)
    hs,ls=_tv_pivots(df,4)
    pats=_tv_channel_patterns(df,hs,ls)+_tv_pivot_patterns(df,hs,ls)
    if not pats:
        n=len(df); k=min(60,n); x=np.arange(n-k,n,dtype=float); C=df["close"].to_numpy(float)[n-k:]
        m,b=np.polyfit(x,C,1); res_=C-(m*x+b); sd=float(res_.std()) or 1e-9
        top=float(np.max(df["high"].to_numpy(float)[n-k:]-(m*x+b))); bot=float(np.min(df["low"].to_numpy(float)[n-k:]-(m*x+b)))
        atr=float(df["atr"].iloc[-1]) if "atr" in df and not pd.isna(df["atr"].iloc[-1]) else sd
        slope=m*k/atr
        name="Ascending Channel" if slope>1.5 else ("Descending Channel" if slope<-1.5 else "Range / Sideways")
        bias="bullish" if slope>1.5 else ("bearish" if slope<-1.5 else "neutral")
        s,e=n-k,n-1; up=lambda i:m*i+b+top; lo=lambda i:m*i+b+bot
        pats=[dict(name="Trend "+name if "Channel" in name else name,bias=bias,status="forming",
                   lines=[dict(i1=s,p1=up(s),i2=e+8,p2=up(e+8),role="upper"),dict(i1=s,p1=lo(s),i2=e+8,p2=lo(e+8),role="lower")],
                   poly=[(s,up(s)),(e,up(e)),(e,lo(e)),(s,lo(s))],marks=[],target=None,anchor=(s,up(s)),kind="channel",e=e)]
    return pats[:3]

def render_tv_chart(df,sym,tf,lv=None,side=0,sr_high=(),sr_low=(),src="Binance Futures"):
    """شارت بنمط TradingView الداكن: شموع + خطوط النماذج مرسومة كأنها يدوية + أداة الصفقة (Long/Short position)."""
    d=df.tail(TV_BARS).reset_index(drop=True).copy()
    c_=d["close"]; d["ema20"]=c_.ewm(span=20,adjust=False).mean(); d["ema50"]=c_.ewm(span=50,adjust=False).mean()
    if "atr" not in d or d["atr"].isna().all():
        pc=c_.shift(); tr=pd.concat([d["high"]-d["low"],(d["high"]-pc).abs(),(d["low"]-pc).abs()],axis=1).max(axis=1)
        d["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    n=len(d); pats=tv_detect(d)
    fig=_new_fig(14,9,TV_BG)
    ax=fig.add_axes([0.035,0.24,0.875,0.66]); axv=fig.add_axes([0.035,0.075,0.875,0.15],sharex=ax)
    _draw_candles(ax,d,TV_UP,TV_DN,0.7)
    o=d["open"].to_numpy(float); cl=d["close"].to_numpy(float); v=d["volume"].to_numpy(float)
    axv.bar(np.arange(n),v,color=np.where(cl>=o,TV_UP,TV_DN),alpha=0.55,width=0.7,linewidth=0)
    ax.plot(np.arange(n),d["ema20"],color="#f7a600",lw=1.8,alpha=0.9,zorder=4)
    ax.plot(np.arange(n),d["ema50"],color="#2962ff",lw=1.8,alpha=0.9,zorder=4)
    if "vwap" in d:
        ax.plot(np.arange(n),d["vwap"],color="#ff6d00",lw=1.5,ls="--",alpha=0.9,zorder=4)
    ys=[float(d["low"].min()),float(d["high"].max())]
    for lvl in list(sr_high)[:2]:
        ax.axhline(lvl,color="#787b86",lw=1.0,ls=(0,(6,4)),alpha=0.8,zorder=2)
    for lvl in list(sr_low)[:2]:
        ax.axhline(lvl,color="#787b86",lw=1.0,ls=(0,(6,4)),alpha=0.8,zorder=2)
    shadow=[pe.withStroke(linewidth=6,foreground="black",alpha=0.25),pe.Normal()]
    for pi,p in enumerate(pats):
        col=TV_COL.get(p["bias"],"#f0b90b")
        if p.get("poly"):
            ax.add_patch(Polygon(p["poly"],closed=True,facecolor=col,alpha=0.12,edgecolor="none",zorder=3))
        for ln in p["lines"]:
            ls_="-" if ln["role"] in ("upper","lower","pattern") else (0,(8,4))
            lw=3.0 if ln["role"]!="neck" else 2.0
            ax.plot([ln["i1"],ln["i2"]],[ln["p1"],ln["p2"]],color=col if ln["role"]!="neck" else "#f0b90b",
                    lw=lw,ls=ls_,solid_capstyle="round",zorder=6,path_effects=shadow)
            ys+= [ln["p1"],ln["p2"]]
        for (i,pv,lab) in p["marks"]:
            ax.scatter([i],[pv],s=46,color=TV_BG,edgecolor=col,linewidth=2.0,zorder=8)
            if lab and pi==0:
                ax.annotate(lab,(i,pv),xytext=(0,12 if p["bias"]!="bullish" else -16),textcoords="offset points",
                            ha="center",fontsize=10,fontweight="bold",color="white",zorder=9,
                            bbox=dict(boxstyle="round,pad=0.25",fc=col,ec="none"))
        if p.get("target") and pi==0:
            tgt=float(p["target"]); e=p["e"]; ys.append(tgt)
            ax.annotate("",xy=(e+11,tgt),xytext=(e,cl[-1]),zorder=7,
                        arrowprops=dict(arrowstyle="-|>",color=col,lw=2.0,ls=(0,(5,3)),shrinkA=0,shrinkB=0))
            ax.text(e+11.4,tgt,f" TARGET {fmt(tgt)} ",color="white",fontsize=9,fontweight="bold",va="center",ha="left",
                    zorder=9,bbox=dict(boxstyle="round,pad=0.3",fc=col,ec="none"),clip_on=False)
        ax_,ay_=p["anchor"]
        arrow="▲" if p["bias"]=="bullish" else ("▼" if p["bias"]=="bearish" else "◆")
        ax.text(ax_+0.5,ay_,f" {p['name']}  {arrow} {p['bias'].capitalize()}  ·  {p['status']} ",color="white",
                fontsize=11 if pi==0 else 9.5,fontweight="bold",va="bottom" if pi==0 else "top",ha="left",zorder=10,
                bbox=dict(boxstyle="round,pad=0.35",fc=col,ec="none",alpha=0.95))
    levels=[]
    if lv:
        e0,sl=lv["entry"],lv["sl"]; tps=[t["px"] for t in lv["tps"]]
        gcol,rcol=TV_UP,TV_DN
        zx=n-1
        ax.add_patch(Rectangle((zx,min(e0,tps[0])),12,abs(tps[0]-e0),facecolor=gcol,alpha=0.16,edgecolor="none",zorder=2))
        ax.add_patch(Rectangle((zx,min(e0,sl)),12,abs(sl-e0),facecolor=rcol,alpha=0.16,edgecolor="none",zorder=2))
        levels=[("ENTRY",e0,"#2962ff","-."),("STOP",sl,rcol,"--")]+[(f"TP{j}",px,gcol,"--") for j,px in enumerate(tps[:4],1)]
        for name,px,col,ls_ in levels:
            ax.plot([zx-6,zx+12],[px,px],color=col,lw=1.4,ls=ls_,zorder=5); ys.append(px)
    lo_,hi_=min(ys),max(ys)
    base_lo,base_hi=float(d["low"].min()),float(d["high"].max()); rng=base_hi-base_lo
    lo_=max(lo_,base_lo-0.9*rng); hi_=min(hi_,base_hi+0.9*rng)
    pad=(hi_-lo_)*0.05; ylo,yhi=lo_-pad,hi_+pad
    ax.set_ylim(ylo,yhi); ax.set_xlim(-1,n+16)
    if levels: _right_labels(ax,levels,n+12,ylo,yhi,fs=8.5)
    last=float(cl[-1]); up=cl[-1]>=o[-1]
    ax.text(n+0.3,last,f" {fmt(last)} ",color="white",fontsize=9.5,fontweight="bold",va="center",ha="left",clip_on=False,zorder=11,
            bbox=dict(boxstyle="square,pad=0.25",fc=TV_UP if up else TV_DN,ec="none"))
    ax.axhline(last,color=TV_UP if up else TV_DN,lw=0.8,ls=(0,(2,3)),alpha=0.8,zorder=1)
    _style_axes([ax,axv],TV_BG,TV_TXT,TV_GRID)
    for a in (ax,axv):
        for sp in a.spines.values(): sp.set_visible(False)
        a.grid(color=TV_GRID,lw=0.7,alpha=1)
    ax.tick_params(labelbottom=False); axv.set_ylim(0,float(v.max())*1.15 if v.max()>0 else 1)
    axv.tick_params(labelleft=False,labelright=False); _time_ticks(axv,d)
    chg=(cl[-1]/o[0]-1)*100
    fig.text(0.04,0.955,f"{sym}/USDT · {tf.upper()} · {src}",fontsize=16,fontweight="bold",color="white",ha="left")
    fig.text(0.04,0.925,f"O {fmt(o[-1])}   H {fmt(d['high'].iloc[-1])}   L {fmt(d['low'].iloc[-1])}   C {fmt(cl[-1])}   {chg:+.2f}%",
             fontsize=10.5,color=TV_UP if chg>=0 else TV_DN,ha="left")
    fig.text(0.62,0.925,"━ EMA20",fontsize=10,color="#f7a600",ha="left"); fig.text(0.70,0.925,"━ EMA50",fontsize=10,color="#2962ff",ha="left"); fig.text(0.78,0.925,"╌ VWAP",fontsize=10,color="#ff6d00",ha="left")
    fig.text(0.5,0.5,"Ryma Crypto",fontsize=70,color="white",alpha=0.03,ha="center",va="center",rotation=18,fontweight="bold")
    fig.text(0.04,0.012,"Auto-drawn patterns · Not financial advice",fontsize=9,color="#787b86",ha="left")
    fig.text(0.965,0.012,"Ryma Crypto",fontsize=11,color="#c9a227",ha="right",fontweight="bold")
    return _to_png(fig),pats

def tv_caption(sym,tf,pats,lang="ar"):
    ico={"bullish":"🟢","bearish":"🔴","neutral":"🟡"}
    if lang=="en":
        lines=[f"📈 <b>#{sym}/USDT · {tf.upper()} — TradingView style</b>",""]
        lines+=[f"{ico.get(p['bias'],'⚪')} <b>{p['name']}</b> — {p['bias']} ({p['status']})"
                +(f" | 🎯 {fmt(p['target'])}" if p.get('target') else "") for p in pats]
        lines+=["","ℹ️ Lines are auto-drawn on real swing highs/lows. Wait for a candle close beyond the line before entering.",RISK_WARNING_EN]
    else:
        lines=[f"📈 <b>#{sym}/USDT · {tf.upper()} — شارت بنمط TradingView</b>",""]
        lines+=[f"{ico.get(p['bias'],'⚪')} <b>{p['name']}</b> — {p['bias']} ({p['status']})"
                +(f" | 🎯 {fmt(p['target'])}" if p.get('target') else "") for p in pats]
        lines+=["","ℹ️ الخطوط مرسومة تلقائياً على القمم والقيعان الحقيقية. لا تدخل قبل إغلاق شمعة خارج الخط (اختراق مؤكد).",RISK_WARNING_AR]
    return "\n".join(lines)

def tv_keyboard(sym,tf,lang="ar"):
    ar=(lang=="ar"); iv=TV_IV.get(tf,"240")
    url=f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{sym}USDT.P&interval={iv}"
    tfs=[("15m","15m"),("1h","1H"),("4h","4H"),("1d","1D")]
    row=[_btn(("✅ " if k==tf else "")+lab,callback_data=f"tv:{sym}:{k}",style="primary" if k==tf else None) for k,lab in tfs]
    return InlineKeyboardMarkup([row,
        [_btn("🔗 افتح في TradingView" if ar else "🔗 Open in TradingView",url=url)],
        [_btn("🔄 تحديث" if ar else "🔄 Refresh",callback_data=f"tv:{sym}:{tf}"),
         _btn("❌ إغلاق" if ar else "❌ Close",callback_data="close_menu")]])

def build_tv_for(sym,tf,res):
    if res and tf==res.get("tf"):
        return render_tv_chart(res["df"],sym,tf,lv=res.get("lv"),side=res.get("side",0),
                               sr_high=res.get("sr_high",[]),sr_low=res.get("sr_low",[]),
                               src=display_source(res.get("source","binance_fut")).title())
    df=get_candles(sym,tf,300,ttl=120,min_bars=100); df=add_indicators(df,100)
    sh,sl=find_sr_levels(df)
    return render_tv_chart(df,sym,tf,lv=None,sr_high=sh[:2],sr_low=sl[:2],
                           src=display_source(df.attrs.get("source","binance_fut")).title())


def render_chart(res,tier="free",published=False):
    df=res["df"].tail(CHART_BARS).reset_index(drop=True)
    lv,side,sym,tf=res["lv"],res["side"],res["sym"],res["tf"]
    n=len(df); x=np.arange(n)
    bg,fg,grid="#ffffff","#0f172a","#e2e8f0"
    fig=_new_fig(12,8.2,bg)
    ax=fig.add_axes([0.065,0.36,0.80,0.54])
    axr=fig.add_axes([0.065,0.10,0.80,0.17],sharex=ax)
    close=df["close"].values.astype(float)
    ax.fill_between(x,df["bb_lo"].values,df["bb_up"].values,color="#1e88e5",alpha=0.07,lw=0,zorder=1)
    ax.plot(x,df["bb_up"],color="#1e88e5",lw=1.0,ls="--",alpha=0.6,zorder=2)
    ax.plot(x,df["bb_lo"],color="#1e88e5",lw=1.0,ls="--",alpha=0.6,zorder=2)
    ax.plot(x,df["ema20"],color="#f59e0b",lw=2.0,label="EMA 20",zorder=3)
    ax.plot(x,df["ema50"],color="#7c3aed",lw=2.0,label="EMA 50",zorder=3)
    ax.plot(x,close,color="#1565c0",lw=2.6,label="Price",zorder=4,solid_capstyle="round")
    ax.scatter([n-1],[close[-1]],s=60,color="#1565c0",edgecolor="white",linewidth=1.2,zorder=5)
    n_tps=4
    levels=[("ENTRY",lv["entry"],"#1d4ed8","-."),("STOP",lv["sl"],"#dc2626","--")]
    for j,tp in enumerate(lv["tps"][:n_tps],1):
        levels.append((f"TP{j}",tp["px"],"#15803d","--"))
    if res.get("wait"): levels=[]
    for name,px,col,ls in levels: ax.axhline(px,color=col,lw=1.7,ls=ls,zorder=3)
    lo=min([float(df["low"].min())]+[v[1] for v in levels])
    hi=max([float(df["high"].max())]+[v[1] for v in levels])
    if hi<=lo: hi=lo+1e-6
    pad=(hi-lo)*0.06
    ylo,yhi=lo-pad,hi+pad
    ax.set_ylim(ylo,yhi); ax.set_xlim(-1,n+12)
    _right_labels(ax,levels,n,ylo,yhi)
    ax.legend(loc="upper left",fontsize=9,frameon=True,facecolor="white",edgecolor=grid)
    ax.tick_params(labelbottom=False)
    axr.plot(x,df["rsi"],color="#7c3aed",lw=1.8,zorder=3)
    axr.axhline(70,color="#dc2626",lw=0.9,ls=":")
    axr.axhline(30,color="#15803d",lw=0.9,ls=":")
    axr.fill_between(x,30,70,color="#7c3aed",alpha=0.05,lw=0)
    axr.set_ylim(10,90); axr.set_xlim(-1,n+12)
    last_rsi=float(df["rsi"].iloc[-1])
    axr.text(n+0.8,last_rsi,f" RSI {last_rsi:.1f} ",color="white",fontsize=9,fontweight="bold",
             va="center",ha="left",clip_on=False,bbox=dict(boxstyle="round,pad=0.3",fc="#7c3aed",ec="none"))
    _style_axes([ax,axr],bg,fg,grid); _time_ticks(axr,df)
    fig.text(0.065,0.945,f"{sym}/USDT  ·  {display_source(res.get('source', 'binance_fut'))}  ·  {tf.upper()}",fontsize=17,fontweight="bold",color=fg,ha="left")
    fig.text(0.065,0.915,f"Direction: {'WAIT' if res.get('wait') else ('LONG' if side == 1 else 'SHORT')}   |   EMA 20 / EMA 50   |   Bollinger (20, 2)   |   RSI (14)",fontsize=10,color="#475569",ha="left")
    fig.text(0.065,0.012,f"Source: {display_source(res.get('source', 'binance_fut'))}",fontsize=9,color="#2563eb",ha="left")
    fig.text(0.985,0.012,"Ryma Crypto",fontsize=11,color="#b8860b",ha="right",fontweight="bold")
    return _to_png(fig)

def render_pattern_chart(res, tier="free"):
    df=res["df"].tail(CHART_BARS).reset_index(drop=True)
    lv,side,sym,tf=res["lv"],res["side"],res["sym"],res["tf"]
    n=len(df); t_arr=df["t"].values.astype("int64")
    bg,fg,grid="#131722","#d1d4dc","#1e222d"
    fig=_new_fig(12,8,bg)
    ax=fig.add_axes([0.065,0.10,0.80,0.80])
    _draw_candles(ax,df,"#26a69a","#ef5350")
    
    sr_high = res.get("sr_high", [])
    sr_low = res.get("sr_low", [])
    for lvl in sr_high:
        ax.axhline(lvl, color="#ef5350", lw=1.5, ls="--", alpha=0.7, zorder=4)
        ax.text(n+1, lvl, f" RES {fmt(lvl)}", color="#ef5350", va="center", fontsize=9, fontweight="bold")
    for lvl in sr_low:
        ax.axhline(lvl, color="#2962ff", lw=1.5, ls="--", alpha=0.7, zorder=4)
        ax.text(n+1, lvl, f" SUP {fmt(lvl)}", color="#2962ff", va="center", fontsize=9, fontweight="bold")

    col_map={"bullish":"#22c55e","bearish":"#facc15","neck":"#facc15","neutral":"#facc15"}
    ys=[float(df["low"].min()),float(df["high"].max())]
    pats=res.get("patterns",[])
    
    for p in pats:
        pname = p.get('name', '')
        pseg = p.get("segments", [])
        
        if pname in ["Ascending Triangle", "Descending Triangle", "Symmetrical Triangle",
                     "Rising Wedge", "Falling Wedge"] and len(pseg) >= 2:
            top = pseg[0]; bot = pseg[1]
            x1_top = _x_index(t_arr, top["t1"]); x2_top = _x_index(t_arr, top["t2"])
            x1_bot = _x_index(t_arr, bot["t1"]); x2_bot = _x_index(t_arr, bot["t2"])
            poly_x = [x1_top, x2_top, x2_bot, x1_bot]
            poly_y = [top["p1"], top["p2"], bot["p2"], bot["p1"]]
            fill_col = col_map.get(p["bias"], "#facc15")
            ax.add_patch(Polygon(list(zip(poly_x, poly_y)), closed=True,
                                 facecolor=fill_col, alpha=0.18, edgecolor=fill_col,
                                 linewidth=2.2, zorder=5))
            ax.plot([x1_top, x2_top], [top["p1"], top["p2"]], color=fill_col,
                    lw=2.5, zorder=6, solid_capstyle="round")
            ax.plot([x1_bot, x2_bot], [bot["p1"], bot["p2"]], color=fill_col,
                    lw=2.5, zorder=6, solid_capstyle="round")
            ys += [top["p1"], top["p2"], bot["p1"], bot["p2"]]
        else:
            for s in pseg:
                x1 = _x_index(t_arr, s["t1"])
                x2 = (n+5) if s["ext"] else _x_index(t_arr, s["t2"])
                seg_col = col_map.get(s["color"], "#facc15")
                ax.plot([x1,x2],[s["p1"],s["p2"]], color=seg_col, lw=2.5,
                        solid_capstyle="round", zorder=6,
                        path_effects=[pe.withStroke(linewidth=6, foreground=seg_col, alpha=0.2), pe.Normal()])
                ys += [s["p1"], s["p2"]]
        
        for m in p.get("marks", []):
            xm = _x_index(t_arr, m["t"]); c = col_map.get(p["bias"], "#facc15")
            ax.scatter([xm], [m["p"]], s=70, color=c, edgecolor="white", linewidth=1.5, zorder=7)
            ax.annotate(m["label"], (xm, m["p"]), xytext=(0, 12 if p["bias"]=="bearish" else -15),
                        textcoords="offset points", ha="center", fontsize=10, color="white",
                        fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.3", fc="#1c2230", ec=c, lw=1.2), zorder=8)
                        
    n_tps=4
    levels=[("ENTRY",lv["entry"],"#5c9dff","-."),("STOP",lv["sl"],"#ff5252","--")]
    for j,tp in enumerate(lv["tps"][:n_tps],1):
        levels.append((f"TP{j}",tp["px"],"#26a69a","--"))
    for name,px,col,ls in levels:
        ax.axhline(px,color=col,lw=1.8,ls=ls,zorder=5); ys.append(px)
    lo,hi=min(ys),max(ys)
    if hi<=lo: hi=lo+1e-6
    pad=(hi-lo)*0.07
    ylo,yhi=lo-pad,hi+pad
    ax.set_ylim(ylo,yhi); ax.set_xlim(-1,n+12)
    _right_labels(ax,levels,n,ylo,yhi)
    _style_axes([ax],bg,fg,grid); _time_ticks(ax,df)
    if pats:
        legend_lines=[f"● {p['name']}  [{p.get('tf','').upper()}]  {p['bias'].capitalize()}" for p in pats[:4]]
        ax.text(0.01,0.90,"\n".join(legend_lines),transform=ax.transAxes,va="top",ha="left",
                fontsize=10,color=fg,bbox=dict(boxstyle="round,pad=0.4",fc="#1c2230",ec=grid))
    fig.text(0.065,0.945,f"{sym}/USDT  ·  {tf.upper()}  ·  {'LONG' if side == 1 else 'SHORT'}",
             fontsize=18,fontweight="bold",color="#26a69a" if side==1 else "#ff5252",ha="left")
    fig.text(0.5,0.5,"Ryma Crypto",fontsize=64,color="#ffffff",alpha=0.035,ha="center",va="center",rotation=20,fontweight="bold")
    fig.text(0.065,0.012,f"Automated analysis  ·  Source: {display_source(res.get('source', 'binance_fut'))}",fontsize=9,color="#94a3b8",ha="left")
    fig.text(0.985,0.012,"Ryma Crypto",fontsize=11,color="#c9a227",ha="right",fontweight="bold")
    return _to_png(fig)

def render_trade_card(res,tier="free"):
    lv,side,sym,tf=res["lv"],res["side"],res["sym"],res["tf"]
    grade=res.get("grade","?")
    is_long=side==1
    accent="#00ff9c" if is_long else "#ff4d6d"
    entry,sl=lv["entry"],lv["sl"]; tps=lv["tps"]
    risk=abs(entry-sl)
    rr=abs(tps[0]["px"]-entry)/risk if (risk>0 and tps) else 0.0
    fig=_new_fig(12,7.2,"#050a10")
    ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis("off")
    grad=LinearSegmentedColormap.from_list("card",["#0a1d15" if is_long else "#1d0a11","#050a10"])
    ax.imshow(np.linspace(0,1,256).reshape(-1,1),extent=[0,1,0,1],aspect="auto",cmap=grad,zorder=0)
    ax.add_patch(FancyBboxPatch((0.012,0.02),0.976,0.96,boxstyle="round,pad=0,rounding_size=0.03",fc="none",ec=accent,lw=2.2,zorder=1))
    glow=[pe.withStroke(linewidth=6,foreground=accent,alpha=0.18),pe.Normal()]
    ax.text(0.5,0.925,"RYMA CRYPTO",ha="center",va="center",color=accent,fontsize=26,fontweight="bold",zorder=4,path_effects=glow)
    ax.text(0.5,0.878,f"Automated Signal Card  ·  {display_source(res.get('source', 'binance_fut'))}",ha="center",va="center",color="#94a3b8",fontsize=12,zorder=4)
    ax.text(0.5,0.79,f"{sym}",ha="center",va="center",color="#ffffff",fontsize=60,fontweight="bold",zorder=4)
    ax.text(0.5,0.725,"/USDT PERPETUAL",ha="center",va="center",color="#94a3b8",fontsize=14,zorder=4)
    ax.add_patch(FancyBboxPatch((0.36,0.615),0.28,0.07,boxstyle="round,pad=0,rounding_size=0.015",
                                fc="#06150f" if is_long else "#150609",ec=accent,lw=2.0,zorder=3))
    ax.text(0.5,0.65,"▲ LONG" if is_long else "▼ SHORT",ha="center",va="center",color=accent,
            fontsize=24,fontweight="bold",zorder=4,path_effects=glow)
    def box(x,y,w,h,label,value,col,dim=False):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0,rounding_size=0.012",
                                    fc="#0b1220",ec=col if not dim else "#334155",lw=1.6,zorder=2))
        if not dim: ax.add_patch(Rectangle((x+0.012,y+h-0.01),w-0.024,0.008,color=col,zorder=3))
        ax.text(x+w/2,y+h*0.72,label,ha="center",va="center",color="#94a3b8" if not dim else "#475569",fontsize=12,zorder=4)
        tt=ax.text(x+w/2,y+h*0.33,value,ha="center",va="center",color=col if not dim else "#475569",fontsize=24,fontweight="bold",zorder=4)
        if not dim: tt.set_path_effects([pe.withStroke(linewidth=5,foreground=col,alpha=0.2),pe.Normal()])
    w,h=0.27,0.15; xs=[0.07,0.365,0.66]
    box(xs[0],0.40,w,h,"ENTRY",fmt(entry),"#60a5fa")
    box(xs[1],0.40,w,h,"STOP LOSS",fmt(sl),"#ff4d6d")
    box(xs[2],0.40,w,h,"TARGET 1",fmt(tps[0]["px"]),accent)
    box(xs[0],0.20,w,h,"TARGET 2",fmt(tps[1]["px"]),accent)
    if len(tps)>=4:
        box(xs[1],0.20,w,h,"TARGET 3",fmt(tps[2]["px"]),accent)
        box(xs[2],0.20,w,h,"TARGET 4",fmt(tps[3]["px"]),accent)
    ax.text(0.5,0.10,f"R:R  {rr:.1f}:1     ·     GRADE  {grade}     ·     TIMEFRAME  {tf.upper()}",
            ha="center",va="center",color="#e2e8f0",fontsize=14,fontweight="bold",zorder=4)
    ax.text(0.5,0.045,f"Source: {display_source(res.get('source', 'binance_fut'))}  ·  Trading involves risk  ·  Not financial advice",
            ha="center",va="center",color="#64748b",fontsize=10,zorder=4)
    return _to_png(fig)

def caption_wait(res,lang="ar"):
    sym=res["sym"]; tr=res.get("trends") or {}
    nm={2:"صاعد قوي",1:"صاعد",0:"عرضي",-1:"هابط",-2:"هابط قوي"}
    nm_en={2:"Strong up",1:"Up",0:"Range",-1:"Down",-2:"Strong down"}
    N=nm if lang=="ar" else nm_en
    lines=[]
    if lang=="ar":
        lines+=[f"⏳ <b>#{sym}/USDT — لا توجد صفقة مناسبة الآن</b>","",
                f"💵 السعر: <code>{fmt(res['price'])}</code>",
                f"🧭 يومي: {N.get(tr.get('d1',0))} | 4س: {N.get(tr.get('h4',0))} | 1س: {N.get(tr.get('h1',0))}","",
                "📌 <b>لماذا الانتظار؟</b>"]
        lines+=[f"  • {r}" for r in res.get("wait_reasons",[])[:3]] or ["  • الشروط غير مكتملة"]
        if res.get("watch"): lines+=["",f"👀 منطقة المراقبة للدخول: <code>{fmt(res['watch'])}</code>"]
        lines+=["","💡 الدقة أهم من عدد الصفقات: البوت لا يعطيك صفقة إلا إذا توافقت الشروط (اتجاه يومي + 4س، ستوب هيكلي، مساحة للأهداف).",
                "",RISK_WARNING_AR,f"👤 {BRAND}"]
    else:
        lines+=[f"⏳ <b>#{sym}/USDT — No quality setup right now</b>","",
                f"💵 Price: <code>{fmt(res['price'])}</code>",
                f"🧭 1D: {N.get(tr.get('d1',0))} | 4H: {N.get(tr.get('h4',0))} | 1H: {N.get(tr.get('h1',0))}","",
                "📌 <b>Why wait?</b>"]
        lines+=[f"  • {r}" for r in res.get("wait_reasons",[])[:3]] or ["  • Conditions incomplete"]
        if res.get("watch"): lines+=["",f"👀 Watch entry zone: <code>{fmt(res['watch'])}</code>"]
        lines+=["","💡 Accuracy over quantity: a trade is issued only when trend (1D+4H), structural stop and room-to-target all agree.",
                "",RISK_WARNING_EN,f"👤 {BRAND}"]
    return "\n".join(lines)

def caption_core(res,tier="free",lang="ar"):
    if res.get("wait"): return caption_wait(res,lang)
    if lang!="en": return caption_vip_ar(res) if tier=="vip" else caption_free_ar(res)
    side,lv,sym=res["side"],res["lv"],res["sym"]
    if lang=="en":
        side_word="🟢 LONG" if side==1 else "🔴 SHORT"
        decision="🟢 Buy" if side==1 else "🔴 Sell"
        now_ts=dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        source=display_source(res.get("source","binance_fut"))
        cl=coin_link(sym,res.get("source","binance_fut"))
        grade=res.get("grade","?")
        lines=["╭━━━ 💎 RYMA CRYPTO 💎 ━━━╮",f"┃ 🎯 Signal: {side_word}",
            f"┃ 📌 <a href='{cl}'>#{sym}/USDT</a> 👆 Click here",
            f"┃ 📡 Source: {source}",f"┃ 🏆 Grade: {grade}",
            "╰━━━━━━━━━━━━━━━━━━━━━━━╯","",f"💵 Entry: {fmt(lv['entry'])}",
            f"🛑 Stop Loss: {fmt(lv['sl'])}",
            "⏱ Frames: 4H regime · 1H confirm · 15M execution | Max hold: 48 hours",
            "📊 Confidence: not calibrated (rule-based grade only)",""]
        n_tps=4
        for i,tp in enumerate(lv["tps"][:n_tps],1):
            emoji="🎯" if i<=2 else "🏆"; lines.append(f"{emoji} Target {i}: {fmt(tp['px'])}")
        
        if res.get("trendspider_alert"):
            lines.append("🔔 Trigger: TrendSpider · levels validated/calculated by Ryma")
        pats=res.get("patterns",[])
        if pats:
            lines.append("")
            pat_names=" | ".join(f"{p['name']}{'[' + p.get('tf','').upper() + ']' if p.get('tf') else ''}" for p in pats[:2])
            lines.append(f"🕯 Pattern: {pat_names}")
        if grade=="C": lines+=["","👁 <b>Watch setup:</b> enter only after breakout/breakdown is confirmed"]
        if res.get("forced") or grade == "C":
            lines += ["",
                      "⚠️ <b>Grade C warning — low quality setup:</b>",
                      "• Several confirmation conditions are missing",
                      "• Published as a high-risk C setup; confirmation is weak",
                      "• Use half normal risk size or less",
                      "• Invalidate immediately if stop is broken"]
            for r in res.get("wait_reasons", [])[:3]:
                lines.append(f"  • {r}")
            for w in res.get("warnings", [])[:2]:
                lines.append(f"  ⚡ {w}")
        lines+=["","━━━━━━━━━━━━━━━━",f"🎯 <b>Expected Decision: {decision}</b>"]
        ai=res.get("ai_context") or {}
        if ai:
            rg=ai.get("regime_1h",{}); prob=ai.get("ml_probability_pct")
            lines += ["",f"🧠 <b>AI Market Regime (1H):</b> {rg.get('name','unknown')}"]
            lines.append(f"📊 <b>ML model score:</b> {prob:.1f}%" if prob is not None else "🧪 <b>ML probability:</b> unavailable — calibrated model not configured")
            flow=ai.get("flow",{}); cvd=flow.get("cvd_imbalance"); book=flow.get("book_imbalance")
            if cvd is not None: lines.append(f"🌊 CVD imbalance: {cvd*100:+.1f}%")
            if book is not None: lines.append(f"📚 Order book imbalance: {book*100:+.1f}%")
        lines+=["",RISK_WARNING_EN,f"👤 {BRAND}"]
        return "\n".join(lines)
        
    side_word="🟢 شراء (LONG)" if side==1 else "🔴 بيع (SHORT)"
    decision="🟢 شراء" if side==1 else "🔴 بيع"
    now_ts=dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    source=display_source(res.get("source","binance_fut"))
    cl=coin_link(sym,res.get("source","binance_fut"))
    grade=res.get("grade","?")
    lines=["╭━━━ 💎 RYMA CRYPTO 💎 ━━━╮",f"┃ 🎯 التوصية: {side_word}",
        f"┃ 📌 <a href='{cl}'>#{sym}/USDT</a> 👆 اضغط هنا",
        f"┃ 📡 المصدر: {source}",f"┃ 🏆 الدرجة: {grade}",
        "╰━━━━━━━━━━━━━━━━━━━━━━━╯","",f"💵 الدخول: {fmt(lv['entry'])}",
        f"🛑 وقف الخسارة: {fmt(lv['sl'])}",
        "⏱ الإطارات: 4س نظام · 1س تأكيد · 15د تنفيذ | أقصى مدة: 48 ساعة",
        "📊 الثقة الرقمية غير معايرة؛ الدرجة تقييم قواعدي فقط",""]
    n_tps=4
    for i,tp in enumerate(lv["tps"][:n_tps],1):
        emoji="🎯" if i<=2 else "🏆"; lines.append(f"{emoji} الهدف {i}: {fmt(tp['px'])}")
    if res.get("trendspider_alert"):
        lines.append("🔔 المحفّز: TrendSpider · المستويات يتحقق منها/يحسبها Ryma")
    
    pats=res.get("patterns",[])
    if pats:
        lines.append("")
        pat_names=" | ".join(f"{p['name']}{'[' + p.get('tf','').upper() + ']' if p.get('tf') else ''}" for p in pats[:2])
        lines.append(f"🕯 النموذج: {pat_names}")
    if grade=="C": lines+=["","👁 <b>صفقة مراقبة:</b> ادخل فقط بعد تأكيد الاختراق أو الكسر"]
    if res.get("forced") or grade == "C":
        lines += ["",
                  "⚠️ <b>تحذير درجة C — صفقة منخفضة الجودة:</b>",
                  "• بعض شروط التأكيد غير متحققة",
                  "• تُنشر كإشارة C عالية المخاطر مع ضعف التأكيد",
                  "• استخدم نصف حجم المخاطرة المعتاد أو أقل",
                  "• راقب الإبطال فوراً إذا كسر الوقف"]
        for r in res.get("wait_reasons", [])[:3]:
            lines.append(f"  • {r}")
        for w in res.get("warnings", [])[:2]:
            lines.append(f"  ⚡ {w}")
    lines+=["","━━━━━━━━━━━━━━━━",f"🎯 <b>القرار المتوقع: {decision}</b>"]
    ai=res.get("ai_context") or {}
    if ai:
        rg=ai.get("regime_1h",{}); prob=ai.get("ml_probability_pct")
        lines += ["",f"🧠 <b>نظام السوق AI (1H):</b> {rg.get('name','غير حاسم')}"]
        lines.append(f"📊 <b>احتمال النموذج المعاير:</b> {prob:.1f}%" if prob is not None else "🧪 <b>احتمال AI:</b> غير متاح — لم يتم إعداد نموذج معاير")
        flow=ai.get("flow",{}); cvd=flow.get("cvd_imbalance"); book=flow.get("book_imbalance")
        if cvd is not None: lines.append(f"🌊 اختلال CVD: {cvd*100:+.1f}%")
        if book is not None: lines.append(f"📚 اختلال دفتر الأوامر: {book*100:+.1f}%")
    lines+=["",RISK_WARNING_AR,f"👤 {BRAND}"]
    return "\n".join(lines)

def keyboard_free(sym,tf,source="binance_fut",lang="en"):
    return InlineKeyboardMarkup([
        [_btn(t("risk_btn",lang),callback_data=f"calc_risk:{sym}"),_btn(t("port_btn",lang),callback_data=f"add_port:{sym}")],
        [_btn(t("chart_btn",lang),callback_data=f"chart:{sym}"), _btn(t("refresh_btn",lang),callback_data=f"tf:{sym}:{tf}")],
        [_btn(t("news_btn",lang),callback_data=f"news:{sym}")],
        [_btn(t("refs_btn",lang),callback_data=f"refs:{source}")],
        [_btn(t("vip_btn",lang),url=VIP_INVITE_LINK)],
        [_btn(t("free_btn",lang),url=CHANNEL_LINK)],
        [_btn(t("contact_btn",lang),url=CONTACT_URL)]
    ])

def keyboard_vip(sym,tf,source="binance_fut",lang="en"):
    return InlineKeyboardMarkup([
        [_btn(t("risk_btn",lang),callback_data=f"calc_risk:{sym}"),_btn(t("port_btn",lang),callback_data=f"add_port:{sym}")],
        [_btn("📤 مشاركة الصفقة" if lang=="ar" else "📤 Share Trade",callback_data=f"share:{sym}"),_btn(t("news_btn",lang),callback_data=f"news:{sym}")],
        [_btn(t("refs_btn",lang),callback_data=f"refs:{source}")],
        [_btn("📋 القائمة" if lang=="ar" else "📋 Menu",callback_data="vip_menu")],
        [_btn(t("chart_btn",lang),callback_data=f"chart:{sym}")],
        [_btn(t("refresh_btn",lang),callback_data=f"tf:{sym}:{tf}")]])

def keyboard_admin(sym,tf,source="binance_fut",lang="en"):
    ar = (lang == "ar")
    return InlineKeyboardMarkup([
        [_btn("🧮 حاسبة المخاطر" if ar else "🧮 Risk Calc",callback_data=f"calc_risk:{sym}"),
         _btn("📊 محفظتي" if ar else "📊 Portfolio",callback_data="my_portfolio")],
        [_btn("📈 شارت TradingView" if ar else "📈 TradingView Chart",callback_data=f"tv:{sym}:{tf}")],
        [_btn("🌐 جميع المنصات" if ar else "🌐 All Platforms",callback_data=f"refs:{source}")],
        [_btn("📊 المؤشرات" if ar else "📊 Indicators",callback_data=f"ind:{sym}:{tf}"),
         _btn("💧 السيولة" if ar else "💧 Liquidity",callback_data=f"liq:{sym}")],
        [_btn("🐋 الحيتان" if ar else "🐋 Whales",callback_data=f"whale:{sym}"),
         _btn("🕯️ النماذج" if ar else "🕯️ Patterns",callback_data=f"pat:{sym}")],
        [_btn("🖼️ شارت النماذج (أدمن)" if ar else "🖼️ Patterns Chart (Admin)",callback_data=f"pchart:{sym}:{tf}")],
        [_btn("💳 بطاقة النيون" if ar else "💳 Neon Card",callback_data=f"neon:{sym}")],
        [_btn("🔥 رادار الضجة" if ar else "🔥 Hype Radar",callback_data="hype_radar")],
        [_btn("🧪 Backtest",callback_data=f"btcb:{sym}")],
        [_btn("📋 قائمة الأوامر الكاملة" if ar else "📋 Full Admin Menu",callback_data="admin_menu")],
        [_btn("🎯 صفقة اليوم" if ar else "🎯 Daily Trade",callback_data="adm:/daily")],
        [_btn("🔄 تحديث" if ar else "🔄 Refresh",callback_data=f"tf:{sym}:{tf}")]])

def keyboard(sym,tf,tier,source="binance_fut",lang="en"):
    if tier=="admin": return keyboard_admin(sym,tf,source,lang)
    if tier=="vip": return keyboard_vip(sym,tf,source,lang)
    return keyboard_free(sym,tf,source,lang)

def keyboard_refs(current="binance_fut"):
    cur=(current or "binance").lower()
    if cur.startswith("binance"): cur="binance"
    rows=[]
    name,url=REFERRAL_LINKS["binance"]
    rows.append([_btn(f"🚀 {name} Futures (رسوم أقل)",url=url)])
    for key,(name,url) in REFERRAL_LINKS.items():
        if key=="binance": continue
        label=f"✅ {name}" if key==cur else f"🔗 {name}"
        rows.append([_btn(label,url=url)])
    rows.append([_btn("❌ إغلاق",callback_data="close_menu")])
    return InlineKeyboardMarkup(rows)

def keyboard_vip_menu():
    return InlineKeyboardMarkup([
        [_btn("💎✨ الفرصة الذهبية",callback_data="vip_cmd:/golden")],
        [_btn("🎯 صفقة اليوم",callback_data="vip_cmd:/daily")],
        [_btn("⚡ رادار الفرص المبكرة",callback_data="vip_cmd:/radar")],
        [_btn("🚀 رادار النخبة (Alpha/Web3)",callback_data="vip_cmd:/alpha_v2")],
        [_btn("🔮 التنبؤ بالانفجارات",callback_data="vip_cmd:/predict")],
        [_btn("🐋 رادار الصفقات الكبيرة",callback_data="vip_cmd:/whales")],
        [_btn("💥 رادار الانفجارات",callback_data="vip_cmd:/explosions")],
        [_btn("🚀 عملات صاعدة",callback_data="vip_cmd:/pump")],
        [_btn("📉 رادار القيعان الذكي",callback_data="vip_cmd:/bottom")],
        [_btn("🌱 فرص السبوت (1–2 شهر)",callback_data="vip_cmd:/spot")],
        [_btn("🔻 رادار فرص الشورت",callback_data="vip_cmd:/shortsradar")],
        [_btn("⭐ رادار Alpha الأسبوعي",callback_data="vip_cmd:/alpha")],
        [_btn("💧 رادار السيولة",callback_data="vip_cmd_args:liquidity")],
        [_btn("📊 بيانات الفيوتشر",callback_data="vip_cmd_args:futures")],
        [_btn("📈 الصفقات النشطة",callback_data="vip_cmd:/active")],
        [_btn("🔗 رابط الإحالة",callback_data="my_ref"),_btn("🎯 نقاطي",callback_data="my_points")],
        [_btn("🌐 منصات التداول",callback_data="refs:binance_fut")],
        [_btn("🆓 قناة التوصيات المجانية",url=CHANNEL_LINK)],
        [_btn("❌ إغلاق القائمة",callback_data="close_menu")]])

def build_vip_menu_text():
    return ("╭━━━ 💎 قائمة VIP الكاملة 💎 ━━━╮\n┃ 🔥 كل الخدمات متاحة 🔥\n╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "🎯 الأزرار متاحة للوصول للخدمة مباشرة\n\n📌 ملاحظات:\n"
        "• 💧 السيولة و 📊 الفيوتشر يتطلبان كتابة الرمز\n"
        "• 📈 الصفقات النشطة تعرض الصفقات الحالية\n"
        "• 🔗 رابط الإحالة = +20 نقطة لكل مشترك\n"
        "• 📢 القناة المجانية للتنبيهات العامة\n\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯")

def build_vip_page():
    return ("╭━━━ 💎 RYMA CRYPTO VIP 💎 ━━━╮\n┃ 🔥 حصري · جودة · أرباح 🔥\n╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "✨ لماذا VIP؟\n\n🔥 💎✨ الفرصة الذهبية\n🔥 🎯 صفقة اليوم\n🔥 🎯 4 أهداف كاملة في جميع الإشارات (مجاني وVIP)\n"
        "🔥 📡 تتبع لحظي لـ TP + SL\n🔥 ⚡ تنبيهات فورية\n🔥 🚀 رادار النخبة (Alpha/Web3/DEX)\n"
        "🔥 🔮 رادار تنبؤي للانفجارات\n🔥 🐋 رادار الحيتان\n🔥 💧 رادار السيولة\n"
        "🔥 💥 رادار الانفجارات\n🔥 📉 رادار القيعان\n🔥 🔻 رادار الفرص الشورت\n"
        "🔥 ⭐ رادار عملات Alpha\n🔥 🕯️ كشف النماذج الفنية\n🔥 🤖 محرك Ryma متعدد الأطر + ML مساعد عند توفر نموذج مدرّب\n\n"
        "💎 3 باقات VIP متاحة\n💰 الأسعار عند الطلب\n\n"
        f"📞 للاستفسار والاشتراك: {CONTACT_LINK or CHANNEL_LINK}\n\n👇 للانضمام")

def build_admin_menu_text():
    return "👑 <b>قائمة أوامر الأدمن الكاملة</b>\n\nالأزرار متاحة للتنفيذ المباشر.\n"

def keyboard_admin_menu():
    multi_icon="✅" if is_multi_exchange() else "❌"
    return InlineKeyboardMarkup([
        [_btn("⚡ تشغيل النشر",callback_data="adm:/forcepost"),_btn("🧹 تفريغ الصفقات",callback_data="adm:/clearsignals")],
        [_btn("🛠 وضع الصيانة",callback_data="toggle_maintenance"),_btn(f"🌐 تعدد المنصات: {multi_icon}",callback_data="toggle_multi_exchange")],
        [_btn("💳 بطاقة النيون (يدوي)",callback_data="neon_card_manual")],
        [_btn("🔥 رادار الضجة",callback_data="hype_radar")],
        [_btn("🖼️ شارت النماذج (يدوي)",callback_data="patterns_chart_manual")],
        [_btn("📤 مشاركة صفقة اجتماعياً",callback_data="adm_args:share")],
        [_btn("💎✨ الفرصة الذهبية",callback_data="adm:/golden"),_btn("🎯 صفقة اليوم",callback_data="adm:/daily")],
        [_btn("⚡ رادار الفرص المبكرة",callback_data="adm:/radar")],
        [_btn("🤖 مسح AI للسوق",callback_data="adm:/cross"),_btn("🔍 تشخيص",callback_data="adm:/debug")],
        [_btn("📊 فحص السوق",callback_data="adm:/scan"),_btn("🔻 فرص شورت",callback_data="adm:/short")],
        [_btn("🔮 التنبؤ",callback_data="adm:/predict"),_btn("🐋 الحيتان",callback_data="adm:/whales")],
        [_btn("💥 الانفجارات",callback_data="adm:/explosions"),_btn("🚀 الصعود",callback_data="adm:/pump")],
        [_btn("📉 القيعان",callback_data="adm:/bottom"),_btn("🌱 فرص السبوت",callback_data="adm:/spot")],
        [_btn("🔻 شورت رادار",callback_data="adm:/shortsradar"),_btn("📋 خطة DCA/Grid",callback_data="adm:/plan")],
        [_btn("⭐ Alpha",callback_data="adm:/alpha"),_btn("🚀 رادار النخبة (Alpha Pro)",callback_data="adm:/alpha_v2")],
        [_btn("🕯️ فحص النماذج (تلقائي)",callback_data="adm:/patterns"),_btn("🧪 Backtest",callback_data="adm:/bt")],
        [_btn("🧪 Backtest TOP50",callback_data="adm:/bt50"),_btn("👥 المستخدمون",callback_data="adm:/users")],
        [_btn("💎 قائمة VIP",callback_data="adm:/viplist"),_btn("📈 إحصائيات",callback_data="adm:/stats")],
        [_btn("🗂 السجل",callback_data="adm:/history"),_btn("🎛 لوحة التحكم",callback_data="adm:/dashboard")],
        [_btn("📢 اختبار القنوات",callback_data="adm:/testchannels"),_btn("🗑 قائمة الحذف",callback_data="adm:/delist")],
        [_btn("🎁 إضافة نقاط",callback_data="adm_args:addpoints")],
        [_btn("💧 السيولة",callback_data="adm_args:liquidity"),_btn("📊 فيوتشر",callback_data="adm_args:futures")],
        [_btn("💲 أسعار",callback_data="adm_args:price"),_btn("🔎 لماذا",callback_data="adm_args:why")],
        [_btn("📝 نشر توصية",callback_data="adm_args:post"),_btn("➕ إضافة VIP",callback_data="adm_args:addvip")],
        [_btn("➖ إزالة VIP",callback_data="adm_args:removevip"),_btn("❌ إغلاق القائمة",callback_data="close_menu")]])

def build_admin_extras(res):
    trend_ar={"strong_up":"صاعد قوي","up":"صاعد","strong_down":"هابط قوي","down":"هابط","range":"عرضي","unknown":"—"}.get(res.get("trend",""),"—")
    lines=[f"📊 المؤشرات - {res['sym']}/{res['tf']}","",
        f"📈 RSI: {res['rsi']:.1f}",f"📊 ATR: {res['lv']['atr']:.4f}",
        f"📉 MACD: {res['macd']:.4f}",f"🎯 الاستراتيجية: {res['strategy']}",
        f"🏆 الدرجة: {res['grade']}",f"📊 اتجاه: {trend_ar}"]
    if res.get("candle"): lines.append(f"🕯 الشمعة: {res['candle']}")
    pats=res.get("patterns",[])
    if pats:
        lines.append(""); lines.append("🕯️ <b>النماذج الفنية:</b>")
        for p in pats[:4]:
            emoji="🟢" if p["bias"]=="bullish" else ("🔴" if p["bias"]=="bearish" else "⚪")
            tf_lbl=f" [{p.get('tf','').upper()}]" if p.get('tf') else ""
            lines.append(f"  {emoji} {p['name']}{tf_lbl}")
    lines.append("")
    for i,tp in enumerate(res['lv']['tps'],1): lines.append(f"🎯 هدف {i}: {tp['pct']}%")
    liq=futures_liquidations(res['sym'])
    if liq: lines.append(f"💥 تصفيات: شراء ${liq['long_liq']:,.0f} | بيع ${liq['short_liq']:,.0f}")
    return "\n".join(lines)


def active_signals(include_shadow=False):
    with store.lock:
        return [p for p in store.data["signals"] if p.get("state","open") in ("pending","open")
                and (include_shadow or not _is_shadow(p))]

def can_track(res):
    if res["sym"] in WEAK_COINS or in_cooldown(res["sym"]): return False
    act=active_signals()
    if len(act)>=MAX_OPEN: return False
    return not any(p["coin"]==res["sym"] for p in act)

def track_signal(res,shadow=False):
    sz=RISK_SIZE.get(res["grade"],0.02)
    tf=res.get("exec_tf") or res["tf"]          # v10 trades are managed on 15m bars
    p=new_trade(res["sym"],tf,res["side"],res["lv"],res["bar_t"],res["grade"],"RADAR" if shadow else res["setup"],
                size_pct=sz,shadow=shadow)
    p["source"]=normalize_futures_source(res.get("source","binance_fut"))
    p["tier"]=res.get("tier","both"); p["trigger"]="TrendSpider" if res.get("trendspider_alert") else "Ryma"
    with store.lock: store.data["signals"].append(p); store.save("signals")
    return p

async def publish(bot,res,vip=True,free=False,admin_copy=False):
    """VIP: text + (TradingView-style chart when a pattern exists / A trade). FREE: text only. Failures never block the other channel."""
    if res.get("wait"): return []
    sent=[]; source=res.get("source","binance_fut")
    text_vip=caption_core(res,tier="vip",lang="ar"); text_free=caption_core(res,tier="free",lang="ar")
    copy_text=build_copy_post(res)
    st=grade_history_stats(res.get("grade")); admin_extra=""
    if st and st["n"]>=5:
        admin_extra=f"\n📊 [أدمن] درجة {res.get('grade')}: نجاح تاريخي {st['rate']}% من {st['n']} صفقة"
    try:
        kb_v=keyboard_vip(res["sym"],res["tf"],source,"ar"); kb_f=keyboard_free(res["sym"],res["tf"],source,"ar")
        if vip and VIP_CHANNEL_ID:
            try:
                await bot.send_message(VIP_CHANNEL_ID,text_vip[:4000],parse_mode=ParseMode.HTML,protect_content=PROTECT,
                                       reply_markup=kb_v,link_preview_options=NO_PREVIEW)
                sent.append("VIP_TEXT")
            except Exception as e: log.warning("vip text: %s",e)
            if VIP_CHART_MODE!="never":
                try:
                    img,pats=await asyncio.to_thread(build_tv_for,res["sym"],res["tf"],res)
                    real=[p for p in pats if not str(p.get("name","")).startswith(("Trend","Range"))]
                    if VIP_CHART_MODE=="always" or real or res.get("grade") in ("A+","A"):
                        await bot.send_photo(VIP_CHANNEL_ID,img,caption=tv_caption(res["sym"],res["tf"],pats)[:1000],
                                             parse_mode=ParseMode.HTML,protect_content=PROTECT,reply_markup=kb_v)
                        sent.append("VIP_CHART")
                except Exception as e: log.debug("vip chart skip: %s",e)
        if free and CHANNEL_ID:
            try:
                await bot.send_message(CHANNEL_ID,text_free[:4000],parse_mode=ParseMode.HTML,protect_content=PROTECT,
                                       reply_markup=kb_f,link_preview_options=NO_PREVIEW)
                sent.append("FREE_TEXT")
            except Exception as e: log.warning("free text: %s",e)
        if admin_copy and ADMIN_ID:
            try:
                await bot.send_message(ADMIN_ID,(copy_text+admin_extra)[:4000],parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
            except Exception as _ex: log.debug("admin copy: %s",_ex)
            try:
                card=await asyncio.to_thread(render_trade_card,res,"admin")
                await bot.send_photo(ADMIN_ID,card)
            except Exception as _ex: log.debug("admin card: %s",_ex)
    except Exception as e:
        sent.append(f"err:{str(e)[:40]}")
    return sent


# ======================= RC7: two-tier channel model (FREE = B/C · VIP = A + selected B) =======================
_vip_b_day={"d":"","n":0}
TIER_LABEL={"A+":"⭐ صفقة قوية A+","A":"⭐ صفقة قوية A","B":"🔹 فرصة B","C":"👁 صفقة مراقبة C"}

def _lv_with_n_tps(lv,n):
    """Copy of the levels with the first n targets only; fractions re-normalised so they still sum to 1."""
    tps=[dict(t) for t in lv["tps"][:n]]
    tot=sum(float(t.get("frac",0)) for t in tps) or 1.0
    for t in tps: t["frac"]=round(float(t.get("frac",0))/tot,4)
    out=dict(lv); out["tps"]=tps; return out

def route_tier(res):
    """A/A+ -> VIP only · B -> FREE (and VIP too for the best few per day) · C -> FREE only."""
    g=res.get("grade","C")
    if g in ("A+","A"): return "vip"
    if g=="B":
        today=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
        if _vip_b_day["d"]!=today: _vip_b_day.update(d=today,n=0)
        if VIP_CHANNEL_ID and _vip_b_day["n"]<VIP_B_PER_DAY and float(res.get("score",0))>=VIP_B_MIN_SCORE: return "both"
    return "free"

def _ts_lines(res):
    ta=res.get("trendspider_alert")
    if not ta: return []
    nm=str(ta.get("strategy") or "").strip()
    out=["🔔 المحفّز: TrendSpider"+(f" · {nm}" if nm else "")]
    conf={"full":"✅ تأكيد Ryma: كامل (4H + 1H + 15M)",
          "partial":"🟡 تأكيد Ryma: جزئي — الاتجاه متوافق والمحفّز من TrendSpider",
          "none":"⚪ تأكيد Ryma: بدون — إشارة TrendSpider منفردة، خفّض الحجم"}.get(res.get("ts_confirm"))
    if conf: out.append(conf)
    return out

def caption_free_ar(res):
    lv=res["lv"]; sym=res["sym"]; side=res["side"]; grade=res.get("grade","C")
    cl=coin_link(sym,res.get("source","binance_fut"))
    word="شراء (LONG)" if side==1 else "بيع (SHORT)"
    lines=[f"{'🟢' if side==1 else '🔴'} <b>{word}</b> · <a href='{cl}'>#{sym}/USDT</a> 👆",
           f"{TIER_LABEL.get(grade,grade)} · ⏱ المدة: حتى {MAX_HOLD_HOURS} ساعة","━━━━━━━━━━━━━━",
           f"💵 الدخول: <code>{fmt(lv['entry'])}</code>",f"🛑 وقف الخسارة: <code>{fmt(lv['sl'])}</code>"]
    for i,tp in enumerate(lv["tps"][:FREE_TP_COUNT],1): lines.append(f"🎯 الهدف {i}: <code>{fmt(tp['px'])}</code>")
    lines.append("━━━━━━━━━━━━━━")
    lines+=_ts_lines(res)
    lines.append(f"📡 {display_source(res.get('source','binance_fut'))}")
    if grade=="C":
        lines+=["","⚠️ <b>مخاطرة أعلى:</b> تأكيد Ryma ضعيف — استخدم نصف حجمك المعتاد أو أقل والتزم بالوقف."]
    lines+=["","🔄 بعد تحقق الهدف الأول يُنقل الوقف قرب الدخول. نتابع الصفقة هنا حتى نهايتها (ربحًا أو خسارة).",
            "","💎 <b>VIP</b>: صفقات A القوية + الهدف الرابع + شارتات بنماذج فنية + متابعة لحظية — للاشتراك تواصل معنا 👇",
            RISK_WARNING_AR,f"👤 {BRAND}"]
    return "\n".join(lines)

def caption_vip_ar(res):
    lv=res["lv"]; sym=res["sym"]; side=res["side"]; grade=res.get("grade","B")
    cl=coin_link(sym,res.get("source","binance_fut"))
    word="🟢 شراء (LONG)" if side==1 else "🔴 بيع (SHORT)"
    lines=["╭━━━ 💎 RYMA VIP 💎 ━━━╮",f"┃ 🎯 {word}",f"┃ 📌 <a href='{cl}'>#{sym}/USDT</a> 👆",
           f"┃ {TIER_LABEL.get(grade,grade)}",f"┃ 📡 {display_source(res.get('source','binance_fut'))}",
           "╰━━━━━━━━━━━━━━━━━━━━━━━╯","",
           f"💵 الدخول: <code>{fmt(lv['entry'])}</code>",f"🛑 وقف الخسارة: <code>{fmt(lv['sl'])}</code>"]
    for i,tp in enumerate(lv["tps"][:VIP_TP_COUNT],1):
        lines.append(f"{'🎯' if i<=2 else '🏆'} الهدف {i}: <code>{fmt(tp['px'])}</code>")
    lines+=["",f"⏱ المدة: حتى {MAX_HOLD_HOURS} ساعة",
            "🔄 الإدارة: بعد الهدف 1 → الوقف قرب الدخول · بعد الهدف 2 → وقف متحرك"]
    lines+=[""]+_ts_lines(res)
    why=[str(x) for x in (res.get("reasons") or [])[:3]]
    if why: lines+=["","🧭 <b>سبب الفرصة:</b>"]+[f"• {x}" for x in why]
    pats=res.get("patterns",[])
    if pats:
        lines.append("🕯 النموذج: "+" | ".join(f"{p['name']}{'['+p.get('tf','').upper()+']' if p.get('tf') else ''}" for p in pats[:2]))
    lines+=["",RISK_WARNING_AR,f"👤 {BRAND}"]
    return "\n".join(x for x in lines if x is not None)

def vip_result_teaser(coin,side,e,trade):
    """FREE-channel post about a VIP trade: coin, direction and outcome only (never entry/levels). Losses are always included."""
    k=e["kind"]; n=len(trade.get("tps") or []); hits=sum(1 for t in (trade.get("tps") or []) if t.get("hit"))
    d="🟢 LONG" if side==1 else "🔴 SHORT"
    if k=="TP": head=f"✅ تحقق الهدف {e.get('j')} من {n}"
    elif k=="SL": head="🛑 ضربت وقف الخسارة"
    elif k=="BE": head="🔒 أُغلقت عند التعادل"+(" بعد تأمين جزء من الربح" if hits else "")
    elif k=="TRAIL": head="🔁 أُغلقت بالوقف المتحرك"
    else: head="⏱ أُغلقت بانتهاء المدة"
    lines=["💎 <b>نتيجة صفقة VIP</b>","",f"#{coin}/USDT · {d}",head]
    if trade.get("state")=="closed" and trade.get("R") is not None:
        lines.append(f"📊 النتيجة النهائية: <b>{float(trade['R']):+.2f}R</b> · الأهداف المحققة {hits}/{n}")
    lines+=["","👀 الدخول والأهداف قبل تحققها تُنشر في VIP فقط — للاشتراك تواصل معنا.",RISK_WARNING_AR]
    return "\n".join(lines)

async def _send_photo_safe(bot,chat,data):
    try: await bot.send_photo(chat,io.BytesIO(data),protect_content=PROTECT)
    except Exception as ex: log.warning("result photo %s: %s",chat,str(ex)[:80])

async def _announce_event(bot,coin,tf,side,e,R,trade):
    """Route one tracker event: VIP gets everything of its trades; FREE gets its own trades (3 targets) and teasers for VIP trades."""
    tier=trade.get("tier","both"); k=e["kind"]; j=int(e.get("j") or 0)
    to_vip=tier in ("vip","both"); to_free=tier in ("free","both")
    free_event=to_free and not (k=="TP" and j>FREE_TP_COUNT)
    if k in ("TP","SL","BE","TRAIL","TIME") and (to_vip or (tier=="free" and free_event)):
        try:
            data=(await asyncio.to_thread(render_result_card,coin,tf,side,e,trade)).getvalue()
            if to_vip and VIP_CHANNEL_ID: await _send_photo_safe(bot,VIP_CHANNEL_ID,data)
            if tier=="free" and free_event and CHANNEL_ID: await _send_photo_safe(bot,CHANNEL_ID,data)
        except Exception: log.exception("result card")
    if to_vip:
        msg=event_text(coin,tf,side,e,R,"vip",trade=trade)
        if msg: await notify_both(bot,msg,protect=True)
    if free_event and CHANNEL_ID:
        msg=free_event_text(coin,tf,side,e,R,trade)
        if msg: await notify_free(bot,msg)
    if tier=="vip" and VIP_RESULTS_IN_FREE and CHANNEL_ID and k in ("TP","SL","BE","TRAIL","TIME"):
        await notify_free(bot,vip_result_teaser(coin,side,e,trade))

async def dispatch_signal(bot,res,admin_copy=True):
    """Single publishing path (TrendSpider and own scanner): decide tier, trim targets for FREE, publish, then track."""
    res=dict(res)                                     # never mutate the shared analysis cache
    tier=route_tier(res); res["tier"]=tier
    if tier=="free": res["lv"]=_lv_with_n_tps(res["lv"],FREE_TP_COUNT)
    sent=await publish(bot,res,vip=tier in ("vip","both"),free=tier in ("free","both"),admin_copy=admin_copy)
    vip_ok=_sent_ok(sent,"VIP_"); free_ok=_sent_ok(sent,"FREE_")
    ok=vip_ok if tier=="vip" else (free_ok if tier=="free" else (vip_ok or free_ok))
    if ok:
        if tier=="both" and vip_ok: _vip_b_day["n"]+=1
        _mark_posted(res)
    return tier,sent,ok,res

def _trendspider_signal(alert):
    """TrendSpider decides direction and timing. Ryma contributes the price, ATR-based levels and a confluence grade:
    A/B = Ryma's own engine confirms (full) · B/C = direction agrees but no 15M trigger (partial) · C = Ryma neutral/against (none).
    A confirmed Ryma opportunity in the OPPOSITE direction vetoes the alert."""
    sym=alert["symbol"]; side=int(alert["side"])
    if sym in WEAK_COINS or sym in EXCLUDE_TICKERS: return None
    base=get_analysis(sym,True)
    if not base or not base.get("lv") or base.get("wait"):
        log.info("TrendSpider alert skipped: no usable Ryma analysis for %s",sym); return None
    agree=int(base.get("side",0))==side
    if not agree and base.get("opportunity"):
        log.info("TrendSpider alert vetoed: Ryma has a confirmed opposite opportunity on %s",sym); return None
    price=float(base["price"]); atr=float(base["lv"].get("atr") or 0.0)
    if price<=0: return None
    lv=base["lv"] if agree else v10_levels(price,side,atr if atr>0 else None)
    if agree and base.get("opportunity"):
        grade=base.get("grade","B"); grade=grade if grade in ("A+","A","B") else "B"; confirm="full"
    elif agree:
        grade="B" if float(base.get("score",0))>=5 else "C"; confirm="partial"
    else:
        grade="C"; confirm="none"
    res=dict(base)
    res.update(side=side,lv=lv,grade=grade,rank={"A+":2,"A":2,"B":1,"C":0}[grade],opportunity=True,forced=False,
               setup="TS",strategy="TrendSpider",ts_confirm=confirm,
               trendspider_alert={"id":alert["id"],"timestamp":alert["timestamp"],"strategy":alert.get("strategy","")})
    return res

def build_market_summary(symbols):
    now_ts=dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines=["📊 تنبيهات السوق",f"🕐 {now_ts}","━━━━━━━━━━━━━━━━",""]
    ok_count=0
    for s in symbols:
        try:
            price,ch24,ch7=ticker_change(s)
            if price<=0: continue
            lines.append(f"💠 {s} — {fmt(price)}")
            lines.append(f"{'🔺' if ch24 >= 0 else '🔻'} 24h: {ch24:+.2f}%")
            lines.append(f"{'🔺' if ch7 >= 0 else '🔻'} 7d: {ch7:+.2f}%")
            lines.append(""); ok_count+=1
        except Exception: continue
    if ok_count==0: return None
    lines.append(f"📣 {CHANNEL_LINK}")
    return "\n".join(lines)


def pick_short_opportunities(n=5):
    syms=top_symbols(50); rows=[]
    for s in syms[:40]:
        r=short_radar(s)
        if r: rows.append((s,r))
    rows.sort(key=lambda x:-x[1].get("score",0))
    return rows[:n]

_free_day={"d":"","n":0}


def _can_post(r):
    key=f"{r['sym']}:{r['tf']}:{r['bar_t']}"
    if key in store.data["posted"]: return False
    if recently_posted(r["sym"],6) or in_cooldown(r["sym"]): return False
    act=active_signals()
    if len(act)>=MAX_OPEN: return False
    return not any(p["coin"]==r["sym"] for p in act)

def _mark_posted(r):
    key=f"{r['sym']}:{r['tf']}:{r['bar_t']}"
    track_signal(r)
    with store.lock:
        store.data["posted"][key]=now_s()
        cut=now_s()-14*DAY
        store.data["posted"]={k:v for k,v in store.data["posted"].items() if v>cut}
        store.save("posted")


def _sent_ok(sent,prefix):
    """publish() returns tags like VIP_TEXT / FREE_CHART; the old code compared them to "VIP"/"FREE" and never matched."""
    return any(str(x).startswith(prefix) for x in (sent or []))

def _grade_ok(g): return g in ("A+","A","B") or (g=="C" and ALLOW_C_POSTS)

async def run_autopost(bot):
    log.info("run_autopost: بدء المسح")
    syms=await asyncio.to_thread(top_symbols,60)
    results=await asyncio.to_thread(scan_sync,syms[:40])
    # own scanner: only CONFIRMED opportunities (regime + 1H + fresh 15M trigger); tiering decided by route_tier()
    cands=[r for r in results if (r.get("opportunity") or ALLOW_C_POSTS) and _grade_ok(r["grade"])
           and r["sym"] not in WEAK_COINS and r["sym"] not in EXCLUDE_TICKERS]
    today=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    if _free_day["d"]!=today: _free_day.update(d=today,n=0)
    if len(active_signals())>=MAX_OPEN:
        log.warning(f"MAX_OPEN {len(active_signals())}/{MAX_OPEN}"); return dict(vip=0,free=0,total=0)
    order=sorted(cands,key=lambda r:(-{"A+":3,"A":2,"B":1,"C":0}.get(r["grade"],0),-r.get("score",0),-r["rank"]))
    vip_n=free_n=posted=0
    for r in order:
        tier=route_tier(r)
        if tier in ("vip","both") and vip_n>=VIP_POSTS_PER_CYCLE: continue
        if tier in ("free","both") and (free_n>=FREE_POSTS_PER_CYCLE or _free_day["n"]>=FREE_MAX_PER_DAY):
            if tier=="free": continue
        if not _can_post(r): continue
        try: tier,sent,ok,_r=await dispatch_signal(bot,r,admin_copy=False)
        except Exception: continue
        if ok:
            posted+=1
            if tier in ("vip","both"): vip_n+=1
            if tier in ("free","both"): free_n+=1; _free_day["n"]+=1
            await asyncio.sleep(1.0)
    log.info(f"run_autopost: VIP={vip_n}, FREE={free_n}")
    return dict(vip=vip_n,free=free_n,total=posted)

def build_promo_post():
    lines=["💎✨ <b>لماذا نتداول على هذه المنصات؟</b> ✨💎","━━━━━━━━━━━━━━━━━━━━━","","🚀 <b>مزايا المنصات المعتمدة:</b>",""]
    for key,(name,url) in REFERRAL_LINKS.items():
        lines+=[f"🔗 <b>{name}</b>",f"   <a href='{url}'>سجّل الآن واحصل على مكافآت</a>",""]
    lines+=["━━━━━━━━━━━━━━━━━━━━━","✅ رسوم منخفضة","✅ سيولة عالية",
        "✅ عقود فيوتشر احترافية","✅ دعم فني 24/7","",
        "🎁 <b>للحصول على تجربة مجانية:</b> اكتب كلمة (تجربة) في الردود","",
        RISK_WARNING_AR,f"👤 {BRAND}"]
    return "\n".join(lines)

async def autopost_loop(app):
    await asyncio.sleep(20)
    while True:
        try:
            now=time.time()
            nxt=(int(now//CYCLE_AUTOPOST)+1)*CYCLE_AUTOPOST+60
            await asyncio.sleep(max(5,nxt-now))
            if RYMA_AUTOPOST: await run_autopost(app.bot)
        except asyncio.CancelledError: raise
        except Exception: log.exception("autopost")
        await asyncio.sleep(60)

def render_result_card(coin,tf,side,e,trade):
    kind=e["kind"]
    titles={"TP":f"TARGET {e.get('j',1)} HIT","SL":"STOP LOSS HIT","BE":"BREAKEVEN EXIT",
            "TRAIL":"TRAILING EXIT","TIME":"TIME EXIT"}
    rr=trade.get("R"); closed=trade.get("state")=="closed" and rr is not None
    good=(kind=="TP") or (closed and rr>0)
    accent="#00ff9c" if good else "#ff4d6d"
    fig=_new_fig(12,6.4,"#050a10")
    ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.012,0.02),0.976,0.96,boxstyle="round,pad=0,rounding_size=0.03",
                                fc="#0b1220",ec=accent,lw=2.2,zorder=1))
    glow=[pe.withStroke(linewidth=6,foreground=accent,alpha=0.18),pe.Normal()]
    ax.text(0.5,0.84,"RYMA CRYPTO  ·  RESULT",ha="center",va="center",color=accent,fontsize=22,fontweight="bold",zorder=4,path_effects=glow)
    ax.text(0.5,0.68,f"{coin}/USDT  ·  {'LONG' if side==1 else 'SHORT'}  ·  {tf.upper()}",ha="center",va="center",color="#e2e8f0",fontsize=20,fontweight="bold",zorder=4)
    ax.text(0.5,0.50,titles.get(kind,kind),ha="center",va="center",color=accent,fontsize=36,fontweight="bold",zorder=4,path_effects=glow)
    lines=[]
    if kind=="TP": lines.append(f"Move: {float(e.get('pct',0)):+.2f}%  (partial exit)")
    if closed: lines.append(f"Result: {rr:+.2f} R")
    for k,line in enumerate(lines):
        ax.text(0.5,0.32-0.08*k,line,ha="center",va="center",color="#e2e8f0",fontsize=18,zorder=4)
    ax.text(0.5,0.08,f"Source: {display_source(trade.get('source', 'binance_fut'))}  ·  Trading involves risk  ·  Not financial advice",
            ha="center",va="center",color="#64748b",fontsize=10,zorder=4)
    return _to_png(fig)

async def send_result_image(bot,img_buf,free_ok):
    data=img_buf.getvalue()
    if VIP_CHANNEL_ID:
        try: await bot.send_photo(VIP_CHANNEL_ID,io.BytesIO(data),protect_content=PROTECT)
        except Exception as ex: log.warning(f"result vip: {str(ex)[:80]}")
    if free_ok and CHANNEL_ID:
        try: await bot.send_photo(CHANNEL_ID,io.BytesIO(data),protect_content=PROTECT)
        except Exception as ex: log.warning(f"result free: {str(ex)[:80]}")

async def trial_notice_loop(app):
    await asyncio.sleep(120)
    while True:
        try:
            today=dt.datetime.now().strftime("%Y%m%d")
            with store.lock: users=list(store.data["users"].items())
            for uid,rec in users:
                try: st,day=user_status(int(uid),rec)
                except Exception: continue
                if st!="warning" or rec.get("trial_notice")==today: continue
                lang=get_user_lang(int(uid)); left=VIP_FORCE_DAY-day
                kb=InlineKeyboardMarkup([[_btn("💎 اشترك في VIP" if lang=="ar" else "💎 Subscribe to VIP",url=VIP_INVITE_LINK)]])
                try: await app.bot.send_message(int(uid),t("warning_trial",lang,left=left),reply_markup=kb)
                except Exception: continue
                with store.lock:
                    store.data["users"][uid]["trial_notice"]=today; store.save("users")
                await asyncio.sleep(0.5)
        except asyncio.CancelledError: raise
        except Exception: log.exception("trial_notice")
        await asyncio.sleep(3600)

ALG_TZ=dt.timezone(dt.timedelta(hours=1))
MORNING_HOUR=8
async def morning_brief_loop(app):
    await asyncio.sleep(60)
    while True:
        try:
            now=dt.datetime.now(ALG_TZ)
            nxt=now.replace(hour=MORNING_HOUR,minute=0,second=0,microsecond=0)
            if nxt<=now: nxt+=dt.timedelta(days=1)
            await asyncio.sleep((nxt-now).total_seconds())
            txt=await asyncio.to_thread(build_market_summary,["BTC","ETH","BNB","SOL","XRP"])
            if txt:
                txt=txt.replace("📊 تنبيهات السوق","🌅 <b>الإحاطة الصباحية</b>",1)
                await notify_both(app.bot,txt,protect=True)
                await notify_free(app.bot,txt)
        except asyncio.CancelledError: raise
        except Exception: log.exception("morning_brief")
        await asyncio.sleep(60)

async def tracker_loop(app):
    await asyncio.sleep(30); cycle=0
    while True:
        try:
            cycle+=1
            if cycle%CLEANUP_EVERY_CYCLES==0: await asyncio.to_thread(smart_cleanup_trades)
            notes=await asyncio.to_thread(check_signals_sync)
            for coin,tf,side,e,R,trade_id in notes:
                with store.lock:
                    found=next((dict(p) for p in store.data["signals"] if p.get("id")==trade_id),None)
                if not found: continue
                try: await _announce_event(app.bot,coin,tf,side,e,R,found)
                except Exception: log.exception("announce event")
        except asyncio.CancelledError: raise
        except Exception: log.exception("tracker")
        await asyncio.sleep(60)

async def short_free_loop(app):
    await asyncio.sleep(300)
    while True:
        try:
            if CHANNEL_ID:
                rows=await asyncio.to_thread(pick_short_opportunities,5)
                if rows:
                    lines=["🔻 فرص الشورت المجانية",f"🕐 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}","━━━━━━━━━━━━━━━━",""]
                    for s,r in rows:
                        cl=coin_link(s,"binance_fut")
                        lines+=[f"💠 <a href='{cl}'>#{s}</a> 👆 — RSI {r['rsi']}",f"💵 {fmt(r['price'])}",f"🎯 القرار المتوقع: 🔴 بيع",""]
                    lines.append("💎 للأدق → VIP"); lines.append(RISK_WARNING_AR)
                    try: await app.bot.send_message(CHANNEL_ID,"\n".join(lines),protect_content=PROTECT,link_preview_options=NO_PREVIEW)
                    except Exception as _ex: log.debug('ignored: %s', _ex)
        except asyncio.CancelledError: raise
        except Exception: log.exception("short_free")
        await asyncio.sleep(CYCLE_SHORT_FREE)

async def market_summary_loop(app):
    await asyncio.sleep(180)
    FREE_SYMS=["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","DOT","LINK","AVAX"]
    while True:
        try:
            if CHANNEL_ID:
                txt=await asyncio.to_thread(build_market_summary,FREE_SYMS)
                if txt:
                    try: await app.bot.send_message(CHANNEL_ID,txt,protect_content=PROTECT,link_preview_options=NO_PREVIEW)
                    except Exception as _ex: log.debug('ignored: %s', _ex)
            if VIP_CHANNEL_ID:
                txt=await asyncio.to_thread(build_market_summary,ALPHA_COINS[:10])
                if txt:
                    try: await app.bot.send_message(VIP_CHANNEL_ID,txt,protect_content=PROTECT,link_preview_options=NO_PREVIEW)
                    except Exception as _ex: log.debug('ignored: %s', _ex)
        except asyncio.CancelledError: raise
        except Exception: log.exception("market_summary")
        await asyncio.sleep(CYCLE_MARKET_SUMMARY)

async def predict_loop(app):
    await asyncio.sleep(120)
    while True:
        try:
            if VIP_CHANNEL_ID:
                syms=await asyncio.to_thread(top_symbols,40)
                preds=await asyncio.to_thread(predictive_scan,syms[:30])
                if preds:
                    lines=["🔮 رادار التنبؤ — إعدادات قيد التكوّن","━━━━━━━━━━━━━━━━",""]
                    for p in preds[:7]:
                        icon="🟢" if p["direction"]=="LONG" else "🔴"
                        decision="🟢 شراء" if p["direction"]=="LONG" else "🔴 بيع"
                        reasons=" | ".join(p["reasons"][:3])
                        lines+=[f"{icon} #{p['sym']} ({p['score']}/9)",f"   {reasons}",f"   🎯 القرار المتوقع: {decision}"]
                    await app.bot.send_message(VIP_CHANNEL_ID,"\n".join(lines),protect_content=PROTECT,link_preview_options=NO_PREVIEW)
        except asyncio.CancelledError: raise
        except Exception: log.exception("predict")
        await asyncio.sleep(CYCLE_PREDICT)

async def alpha_summary_loop(app):
    await asyncio.sleep(240)
    while True:
        try:
            if VIP_CHANNEL_ID:
                syms=await asyncio.to_thread(top_symbols,60); rows=[]
                for s in syms[:50]:
                    r=await asyncio.to_thread(alpha_radar,s)
                    if r: rows.append((s,r))
                if rows:
                    rows.sort(key=lambda x:-x[1]["change_7d"])
                    lines=["⭐ رادار عملات Alpha",f"🕐 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}","━━━━━━━━━━━━━━━━",""]
                    for s,r in rows[:10]:
                        lines+=[f"⭐ #{s}",f"   7ي {r['change_7d']:+.2f}% | 30ي {r['change_30d']:+.2f}%",f"   RSI {r['rsi']}",f"   🎯 القرار المتوقع: 🟢 شراء"]
                    await app.bot.send_message(VIP_CHANNEL_ID,"\n".join(lines),protect_content=PROTECT,link_preview_options=NO_PREVIEW)
        except asyncio.CancelledError: raise
        except Exception: log.exception("alpha_summary")
        await asyncio.sleep(CYCLE_ALPHA_SUMMARY)

async def bottoms_auto_loop(app):
    await asyncio.sleep(300)
    while True:
        try:
            if VIP_CHANNEL_ID:
                syms=await asyncio.to_thread(top_symbols,70); rows=[]
                for s in syms[:55]:
                    r=await asyncio.to_thread(bottom_radar,s)
                    if r: rows.append((s,r))
                if rows:
                    rows.sort(key=lambda x:x[1]["diff"])
                    lines=["📉 رادار القيعان الذكي",f"🕐 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}","━━━━━━━━━━━━━━━━",""]
                    for s,r in rows[:10]:
                        lines+=[f"{r['severity']} #{s}",f"   {r['diff']}% تحت EMA200 | RSI {r['rsi']}",
                                f"   تعافي: +{r['rebound']}% | حجم: x{r['vol_ratio']}",f"   💵 {fmt(r['price'])}",f"   🎯 القرار المتوقع: 🟢 شراء"]
                    await app.bot.send_message(VIP_CHANNEL_ID,"\n".join(lines),protect_content=PROTECT,link_preview_options=NO_PREVIEW)
        except asyncio.CancelledError: raise
        except Exception: log.exception("bottoms_auto")
        await asyncio.sleep(CYCLE_BOTTOMS_AUTO)

async def golden_loop(app):
    await asyncio.sleep(600); _golden_posted={}
    while True:
        try:
            if len(_golden_posted)>500:
                cutoff=time.time()-14*DAY
                _golden_posted={k:v for k,v in _golden_posted.items() if v>cutoff}
            log.info("golden_loop: بدء البحث الشامل")
            results=await asyncio.to_thread(golden_scan,2,None)
            for g in results:
                key=f"{g['sym']}:{g['side']}"
                if key in _golden_posted and time.time()-_golden_posted[key]<48*3600: continue
                _golden_posted[key]=time.time()
                txt=format_golden_post(g,"vip")
                try: await notify_both(app.bot,txt,protect=True)
                except Exception as _ex: log.debug('ignored: %s', _ex)
                log.info(f"الفرصة الذهبية: {g['sym']} (score={g['score']}) - VIP فقط")
                await asyncio.sleep(3)
        except asyncio.CancelledError: raise
        except Exception: log.exception("golden_loop")
        await asyncio.sleep(CYCLE_GOLDEN)

_whale_day = {"date": "", "count": 0}
async def whale_hunter_loop(app):
    await asyncio.sleep(60)
    log.info("whale_hunter_loop: بدء مراقبة الحيتان")
    _seen_whales=set()
    while True:
        try:
            today = dt.datetime.now().strftime("%Y%m%d")
            if _whale_day["date"] != today:
                _whale_day["date"] = today
                _whale_day["count"] = 0
            
            if _whale_day["count"] >= 5:
                await asyncio.sleep(300)
                continue

            syms=await asyncio.to_thread(top_symbols,20)
            for s in syms[:10]:
                if _whale_day["count"] >= 5: break
                try:
                    ex=get_ex("binance")
                    with _ex_lock["binance"]: trades=ex.fetch_trades(f"{s}/USDT",limit=50)
                    for tr in trades:
                        if _whale_day["count"] >= 5: break
                        notional=float(tr.get("price",0))*float(tr.get("amount",0))
                        if notional >= WHALE_MIN_USD:
                            trade_id=f"{s}_{tr.get('id')}"
                            if trade_id in _seen_whales: continue
                            _seen_whales.add(trade_id)
                            if len(_seen_whales)>2000:
                                _seen_whales=set(list(_seen_whales)[-1000:])
                            side=tr.get("side","buy"); price=float(tr.get("price",0))
                            ai=await asyncio.to_thread(get_analysis,s)
                            ai_direction="شراء" if ai["side"]==1 else "بيع"
                            text,share_url=build_whale_tweet(s,side,notional,price)
                            text += f"\n\n🤖 قرار Ryma AI: {ai_direction} · درجة {ai['grade']}"
                            kb=InlineKeyboardMarkup([
                                [_btn("🚀 انشر على تويتر (X)",url=share_url)],
                                [_btn("📋 رابط التسجيل فقط",url=REFERRAL_LINKS["binance"][1])]])
                            await app.bot.send_message(ADMIN_ID,f"🚨 <b>صيد جديد (جاهز للنشر):</b>\n\n{text}",
                                parse_mode=ParseMode.HTML,reply_markup=kb,link_preview_options=NO_PREVIEW)
                            _whale_day["count"] += 1
                except Exception: continue
        except asyncio.CancelledError: raise
        except Exception: log.exception("whale_hunter")
        await asyncio.sleep(120)

async def promo_loop(app):
    await asyncio.sleep(3600)
    while True:
        try:
            txt=build_promo_post()
            try: await notify_both(app.bot,txt)
            except Exception as _ex: log.debug('ignored: %s', _ex)
            try: await notify_free(app.bot,txt)
            except Exception as _ex: log.debug('ignored: %s', _ex)
            log.info("promo_loop: نشر المنشور الترويجي")
        except asyncio.CancelledError: raise
        except Exception: log.exception("promo")
        await asyncio.sleep(CYCLE_PROMO)

def build_weekly_report():
    since = (time.time() - 7*DAY) * 1000
    with store.lock:
        h = [x for x in store.data["history"] if (x.get("closed") or 0) >= since and not x.get("shadow") and x.get("setup")!="RADAR"]
    if len(h) < 5: return None
    R = np.array([float(x.get("R") or 0) for x in h], dtype=float)
    wins = int((R > 0).sum()); g = R[R > 0].sum(); l = -R[R <= 0].sum()
    pf = round(float(g/l), 2) if l > 0 else 999.0
    best = max(h, key=lambda x: x.get("R") or 0)
    lines = ["📊 <b>التقرير الأسبوعي</b>", f"🕐 {dt.datetime.now().strftime('%Y-%m-%d')}",
             "━━━━━━━━━━━━━━━━", "",
             f"📈 الصفقات المغلقة: <b>{len(R)}</b>",
             f"✅ نسبة النجاح: <b>{100*wins/len(R):.1f}%</b>",
             f"⚖️ معامل الربح: <b>{pf}</b>",
             f"💰 صافي النتيجة: <b>{R.sum():+.1f}R</b>", "",
             f"🏆 أفضل صفقة: #{best['coin']} {float(best.get('R') or 0):+.2f}R", "",
             "⚠️ الأرقام من الصفقات المسجلة فعلياً فقط، ونتائج الماضي لا تضمن المستقبل.",
             RISK_WARNING_AR]
    return "\n".join(lines)

async def weekly_report_loop(app):
    await asyncio.sleep(900)
    while True:
        try:
            txt = await asyncio.to_thread(build_weekly_report)
            if txt:
                await notify_both(app.bot, txt, protect=True)
                await notify_free(app.bot, txt)
        except asyncio.CancelledError: raise
        except Exception: log.exception("weekly_report")
        await asyncio.sleep(CYCLE_PROMO)

def recently_posted(sym, hours=6):
    cut = now_s() - hours*3600
    with store.lock:
        return any(k.startswith(f"{sym}:") and v > cut for k, v in store.data["posted"].items())


def predictive_scan(symbols):
    """Radar of setups that are FORMING: 4H regime aligned and 1H confirmed, but the 15M trigger has not fired yet.
    The moment the trigger fires the coin becomes an opportunity (autopost), so it leaves this list."""
    out=[]
    for sym in symbols:
        try:
            r=get_analysis(sym)
            if not r or not r.get("lv") or r.get("opportunity"): continue
            f=r.get("factor_scores") or {}
            if not (f.get("regime_aligned") and f.get("confirm_1h")): continue
            out.append(dict(sym=sym,score=float(r.get("score",0)),direction="LONG" if r["side"]==1 else "SHORT",
              grade=r.get("grade","C"),reasons=["نظام 4H متوافق + تأكيد 1H — بانتظار محفز 15M (سحب سيولة/اختراق بحجم)"]))
        except Exception as ex: log.debug("predictive scan %s: %s",sym,ex)
    out.sort(key=lambda x:x["score"],reverse=True)
    return out[:PREDICT_TOP_N]

def binance_futures_klines_long(sym, tf, bars):
    """Long Binance USD-M history. Returns normalized OHLCV rows or None."""
    interval = BINANCE_INTERVAL_MAP.get(tf)
    if not interval: return None
    out, end = [], None
    try:
        while len(out) < bars:
            params = {"symbol": f"{sym}USDT", "interval": interval, "limit": 1500}
            if end is not None: params["endTime"] = end
            r = requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/klines", params=params, timeout=15)
            if r.status_code != 200:
                log.warning("V10 history Binance %s %s HTTP %s: %s", sym, tf, r.status_code, r.text[:180])
                break
            data = r.json()
            if not isinstance(data, list) or not data: break
            page = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
            out = page + out
            new_end = int(data[0][0]) - 1
            if end is not None and new_end >= end: break
            end = new_end
            if len(data) < 1500: break
    except Exception as ex:
        log.warning("V10 history Binance %s %s exception: %s", sym, tf, str(ex)[:180])
    return out[-bars:] if out else None

# Dedicated CCXT instances for linear perpetual history. The ordinary exchange
# instances used elsewhere in the bot may be configured for spot markets.
_v10_futures_ex = {}
_v10_futures_locks = {}
_v10_futures_init_lock = threading.Lock()
_V10_FUTURE_EXCHANGES = [
    ("bybit", "bybit", {"defaultType": "swap", "defaultSubType": "linear"}),
    ("okx", "okx", {"defaultType": "swap"}),
    ("kucoin", "kucoinfutures", {"defaultType": "swap"}),
    ("gateio", "gateio", {"defaultType": "swap"}),
    ("bitget", "bitget", {"defaultType": "swap"}),
    ("mexc", "mexc", {"defaultType": "swap"}),
    ("htx", "htx", {"defaultType": "swap"}),
]

def _v10_get_futures_exchange(exchange_id, options):
    key = exchange_id
    with _v10_futures_init_lock:
        if key not in _v10_futures_ex:
            cls = getattr(ccxt, exchange_id)
            _v10_futures_ex[key] = cls({
                "enableRateLimit": True, "timeout": 25000,
                "options": dict(options),
            })
            _v10_futures_locks[key] = threading.Lock()
    return _v10_futures_ex[key]

def _v10_linear_swap_symbol(ex, base):
    markets = ex.load_markets()
    candidates = []
    for market in markets.values():
        if market.get("base") != base or market.get("quote") != "USDT":
            continue
        if not market.get("swap") or market.get("settle") != "USDT":
            continue
        if market.get("active") is False:
            continue
        candidates.append(market)
    if not candidates:
        raise PairNotFound(f"لا يوجد عقد USDT-M نشط لـ {base}")
    candidates.sort(key=lambda m: (not bool(m.get("linear")), not bool(m.get("active", True))))
    return candidates[0]["symbol"]

def _v10_fetch_ccxt_futures_long(exchange_id, base, tf, bars, options):
    ex = _v10_get_futures_exchange(exchange_id, options)
    symbol = _v10_linear_swap_symbol(ex, base)
    tfms = TF_MS[tf]
    since = int(time.time() * 1000) - int(bars) * tfms
    rows, last_seen = [], None
    lock = _v10_futures_locks[exchange_id]
    with lock:
        # CCXT venues usually cap a single OHLCV request at 500-1000 bars.
        # Paginate forward and reject non-advancing pages to avoid infinite loops.
        for _ in range(min(120, int(bars / 200) + 10)):
            chunk = ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=1000)
            if not chunk:
                break
            clean = []
            for k in chunk:
                if len(k) < 6 or k[0] is None: continue
                clean.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
            if not clean: break
            clean.sort(key=lambda x: x[0])
            newest = clean[-1][0]
            if last_seen is not None and newest <= last_seen:
                break
            rows.extend(clean)
            last_seen = newest
            since = newest + tfms
            if len(rows) >= bars or newest + tfms >= int(time.time() * 1000):
                break
    # Normalize duplicate timestamps and keep only completed candles.
    dedup = {r[0]: r for r in rows}
    now_ms = int(time.time() * 1000)
    out = [dedup[k] for k in sorted(dedup) if k + tfms <= now_ms]
    return out[-bars:], f"{exchange_id}_linear_swap"

def v10_futures_history(sym, tf, bars, preferred_source=None, minimum_override=None):
    """Fetch only linear Futures; optionally pin the request to one venue."""
    errors = []
    minimum = max(1,int(minimum_override)) if minimum_override is not None else {"4h": 210, "1h": 205, "15m": 60}.get(tf, 60)
    preferred_source=normalize_futures_source(preferred_source) if preferred_source else None
    if preferred_source is None or preferred_source in ("binance_fut","binance_usdm"):
        rows = binance_futures_klines_long(sym, tf, bars)
        if rows and len(rows) >= minimum:
            return rows, "binance_usdm"
        errors.append(f"binance: only {len(rows or [])}/{minimum} minimum bars")
        if preferred_source in ("binance_fut","binance_usdm"):
            raise NoData(f"{sym}: pinned Binance Futures history unavailable for {tf}")
    for label, exchange_id, options in _V10_FUTURE_EXCHANGES:
        if preferred_source and preferred_source != f"{label}_linear_swap":
            continue
        try:
            rows, _source = _v10_fetch_ccxt_futures_long(exchange_id, sym, tf, bars, options)
            if rows and len(rows) >= minimum:
                log.info("V10 historical data %s %s from %s (%d bars)", sym, tf, label, len(rows))
                return rows, f"{label}_linear_swap"
            errors.append(f"{label}: only {len(rows or [])} bars")
        except Exception as ex:
            errors.append(f"{label}: {type(ex).__name__}: {str(ex)[:100]}")
            log.warning("V10 history fallback failed %s %s via %s: %s", sym, tf, label, str(ex)[:180])
    raise NoData(f"{sym}: لا توجد بيانات Futures كافية لـ {tf}. " + " | ".join(errors[:5]))

def metrics(trs):
    if not trs: return dict(n=0,wr=0.0,pf=0.0,total=0.0,avg=0.0,dd=0.0,tp1=0.0)
    srt=sorted(trs,key=lambda z:z["t"]); R=np.array([x["R"] for x in srt],dtype=float)
    g,l=R[R>0].sum(),-R[R<=0].sum(); eq=np.r_[0.0,np.cumsum(R)]
    peak=np.maximum.accumulate(eq)
    return dict(n=len(R),wr=round(100*float((R>0).mean()),1),pf=round(float(g/l),2) if l>0 else 999.0,
                total=round(float(R.sum()),1),avg=round(float(R.mean()),3),
                dd=round(float((peak-eq).max()),1),
                tp1=round(100*float(np.mean([x.get("tps",0)>=1 for x in srt])),1))

def split_trades_by_symbol(trades, tmin=None, tmax=None, ratio=0.65):
    """Split each symbol by its own available history, avoiding one global cut."""
    groups={}
    for item in trades or []:
        if not isinstance(item,dict): continue
        groups.setdefault(item.get("sym",item.get("coin","__all__")),[]).append(item)
    train=[]; test=[]
    for _,items in groups.items():
        starts=[x.get("data_start") for x in items if isinstance(x.get("data_start"),(int,float))]
        ends=[x.get("data_end") for x in items if isinstance(x.get("data_end"),(int,float))]
        a=min(starts) if starts else tmin
        b=max(ends) if ends else tmax
        if not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or b<=a:
            # If no usable per-symbol range exists, keep the sample in TEST, never TRAIN.
            test.extend(items); continue
        cut=a+float(ratio)*(b-a)
        train.extend(x for x in items if x.get("t",0)<cut)
        test.extend(x for x in items if x.get("t",0)>=cut)
    return sorted(train,key=lambda x:x.get("t",0)),sorted(test,key=lambda x:x.get("t",0))


def _v10_visible(t1,t4,sig_close):
    """How many 1H / 4H candles are fully CLOSED at sig_close (candle open time + length <= sig_close). Nothing later is visible."""
    return (int(np.searchsorted(t1,sig_close-TF_MS["1h"],side="right")),
            int(np.searchsorted(t4,sig_close-TF_MS["4h"],side="right")))


def v10_replay(sym,d4,h1,m15,max_decisions=None,params=None):
    """Replay the LIVE engine on every closed 15m candle, then manage each trade with the SAME trade_step as live.
    - decision sees only candles already closed at that moment (4H/1H/15M clipped to the signal time)
    - entry = open of the next 15m candle (live: the 15m close ~ the same price), costs = trade_cost_r (fees+slip+funding est.)
    - one open trade per symbol; only CONFIRMED opportunities are traded (same rule as autopost)
    Returns (trades, data_start_ms, data_end_ms)."""
    max_decisions=int(max_decisions or BT_MAX_DECISIONS); prm=params or v10_params()
    t4=d4["t"].to_numpy(dtype="int64"); t1=h1["t"].to_numpy(dtype="int64"); t15=m15["t"].to_numpy(dtype="int64")
    if len(t1)<206 or len(t4)<211 or len(t15)<100: return [],0,0
    mask=_v10_trigger_mask(m15).to_numpy()
    o15=m15["open"].to_numpy(dtype=float); h15=m15["high"].to_numpy(dtype=float)
    l15=m15["low"].to_numpy(dtype=float); c15=m15["close"].to_numpy(dtype=float); a15=m15["atr"].to_numpy(dtype=float)
    first=max(60,int(np.searchsorted(t15,int(t1[204])+TF_MS["1h"],side="left")))
    if first>=len(t15)-2: return [],0,0
    data_start,data_end=int(t15[first]),int(t15[-1])
    trades=[]; calls=0; next_ok=0
    for j in range(first,len(t15)-1):
        if not mask[j]: continue
        sig_close=int(t15[j])+TF_MS["15m"]
        if sig_close<next_ok: continue
        e1,e4=_v10_visible(t1,t4,sig_close)
        if e1<205 or e4<210: continue
        calls+=1
        if calls>max_decisions: break
        try: dec=_ryma_v10_hybrid_decision(sym,h1.iloc[:e1],m15.iloc[:j+1],float(c15[j]),{"_df_4h":d4.iloc[:e4]},prm)
        except NoData: continue
        if not dec["opportunity"]: continue
        side=int(dec["side"]); entry_i=j+1
        fill=float(o15[entry_i]); lv=v10_levels(fill,side,dec["atr"],dec.get("atr_1h"),prm)
        p=new_trade(sym,V10_EXEC_TF,side,lv,int(t15[j]),dec["grade"],dec.get("setup","V10"))
        k=entry_i
        while k<len(t15) and p["state"] in ("pending","open"):
            trade_step(p,o15[k],h15[k],l15[k],c15[k],a15[k]); k+=1
        if p["state"]!="closed": break          # ran out of data: an unfinished trade is not counted
        exit_i=k-1
        gross=round(p["realized"],4)
        trades.append(dict(coin=sym,sym=sym,t=int(t15[entry_i]),signal_t=sig_close,R=p["R"],gross_R=gross,
            exit=p["result"],bars=p["bars"],tps=sum(1 for x in p["tps"] if x["hit"]),cost=round(gross-p["R"],4),
            grade=dec["grade"],score=dec["score"],side=side,setup=dec.get("setup","V10"),
            strategy="Ryma v10 Adaptive Hybrid",risk_pct=round(100*lv["risk"]/fill,4),hours=p["bars"]*0.25,entry=fill,sl=lv["sl"],tp=[x["px"] for x in lv["tps"]],
            data_start=data_start,data_end=data_end,signal_tf="1h",trigger_tf="15m",regime_tf="4h"))
        next_ok=int(t15[exit_i])+TF_MS["15m"]+(prm["cooldown"]*TF_MS["15m"] if p["R"]<0 else 0)
    return trades,data_start,data_end



def _bt_frames(sym,years=1.0):
    """Legacy long-history loader retained for the optimiser and research tools."""
    years=min(max(float(years),0.1),3.0)
    bars={"15m":int(years*365*96)+400,"1h":int(years*365*24)+300,"4h":int(years*365*6)+300}
    return _bt_frames_bars(sym,bars)


def _bt_frames_bars(sym,bars):
    """Load synchronized linear-futures OHLCV from one venue, with warm-up history."""
    minimum={"4h":210,"1h":205,"15m":100}
    frames={}; sources={}; pinned_source=None
    for tf in ("4h","1h","15m"):
        rows,source=v10_futures_history(sym,tf,int(bars[tf]),preferred_source=pinned_source)
        source=normalize_futures_source(source)
        if pinned_source is None: pinned_source=source
        elif source!=pinned_source:
            raise NoData(f"{sym}: mixed Futures venues rejected ({pinned_source} vs {source} on {tf})")
        raw=_rows_to_df(rows,tf,int(bars[tf]))
        if len(raw)<minimum[tf]:
            raise NoData(f"{sym}: بيانات Futures غير كافية لـ {tf} من {source} ({len(raw)}/{minimum[tf]})")
        frames[tf]=add_indicators(raw,100); sources[tf]=source
    return frames["4h"],frames["1h"],frames["15m"],", ".join(f"{tf}:{s}" for tf,s in sources.items())


def _bt_frames_days(sym,days=60):
    """Exact recent intraday window plus closed-candle warm-up for 4H/1H indicators."""
    days=int(min(max(int(days),30),60))
    # The replay waits for 204 closed 1H and 210 closed 4H candles.
    # These are warm-up only; the first eligible 15M decision is approximately `days` ago.
    bars={"15m":days*96+120,"1h":days*24+205,"4h":days*6+212}
    return _bt_frames_bars(sym,bars)


def backtest_symbol(sym, years=1.0, params=None):
    """Replay the live v10 engine (current live parameters unless `params` is given) over futures history."""
    d4,h1,m15,summary=_bt_frames(sym,years)
    trades,a,b=v10_replay(sym,d4,h1,m15,params=params)
    for tr in trades: tr["data_source"]=summary
    if not a: raise NoData(f"{sym}: تاريخ غير كافٍ للتشغيل")
    return trades,a,b


V10_GRID=[dict(stop_tf=tf,stop_k=k,min_adx=adx,cooldown=cd,rr=rr)
          for tf,k in (("15m",1.6),("1h",0.8),("1h",1.2),("1h",1.6))
          for adx in (0,20,25) for cd in (0,16) for rr in ("base","runner")]


def _real_cost_trades(trs):
    """Same trades re-priced with realistic majors costs (REAL_FEE/REAL_SLIP) instead of the configured conservative ones."""
    out=[]
    for x in trs:
        rp=max(float(x.get("risk_pct") or 0.5),1e-6)/100.0
        cost=(2*(REAL_FEE+REAL_SLIP)+FUNDING_8H*float(x.get("hours",0))/8.0)/rp
        out.append(dict(x,R=round(float(x["gross_R"])-cost,4)))
    return out


def v10_optimize(data,grid=None,progress=None):
    """Walk-forward style grid search on ALREADY LOADED frames: rank by TRAIN only, then report TEST (never used to rank)."""
    grid=grid or V10_GRID; rows=[]
    for gi,raw in enumerate(grid):
        prm=_v10_clean(raw); allt=[]; a=b=None
        for sym,(d4,h1,m15,_) in data.items():
            trs,s,e=v10_replay(sym,d4,h1,m15,params=prm)
            allt+=trs
            if s: a=s if a is None else min(a,s); b=e if b is None else max(b,e)
        tr,te=split_trades_by_symbol(allt,a,b,0.65)
        rows.append(dict(params=prm,train=metrics(tr),test=metrics(te),test_real=metrics(_real_cost_trades(te)),
                         gross=round(float(np.mean([x["gross_R"] for x in te])),3) if te else 0.0))
        if progress: progress(gi+1,len(grid))
    return rows


def opt_report(rows,syms,years,errors=None):
    def fmt_p(p): return f"stop={p['stop_tf']}×{p['stop_k']:g} adx≥{p['min_adx']:g} cd={p['cooldown']} rr={p['rr']}"
    base=rows[0]
    elig=[r for r in rows[1:] if r["train"]["n"]>=150 and r["test"]["n"]>=60]
    elig.sort(key=lambda r:r["train"]["avg"],reverse=True)
    L=[f"🔬 Optimiser v10 · {len(syms)} عملة · {years:g} سنة · {len(rows)} تركيبة · {BOT_VERSION}",
       "الترتيب حسب TRAIN فقط. TEST للتحقق ولم يُستعمل في الاختيار.",
       f"⚠️ {len(rows)} تركيبة = احتمال أن يظهر رابح بالصدفة؛ لا تعتمد إلا ما كان موجباً في TEST بعد التكلفة الواقعية وأعده على فترة/عملات أخرى.","",
       f"الأساس: {fmt_p(base['params'])}",
       f"  TRAIN n={base['train']['n']} avg {base['train']['avg']:+}R PF {base['train']['pf']} | TEST n={base['test']['n']} avg {base['test']['avg']:+}R PF {base['test']['pf']}",
       f"  إجمالي قبل التكلفة (TEST) {base['gross']:+}R | بتكلفة واقعية {base['test_real']['avg']:+}R PF {base['test_real']['pf']}",""]
    if not elig: L.append("لا توجد تركيبة بعينة كافية (TRAIN≥150 وTEST≥60).")
    for i,r in enumerate(elig[:6],1):
        ok=r["test"]["avg"]>0 and r["test"]["pf"]>=1.1 and r["train"]["avg"]>0
        L.append(f"{i}. {fmt_p(r['params'])}  {'✅ ثابتة' if ok else '❌ لا تصمد في TEST'}")
        L.append(f"   TRAIN n={r['train']['n']} avg {r['train']['avg']:+}R PF {r['train']['pf']} | TEST n={r['test']['n']} avg {r['test']['avg']:+}R PF {r['test']['pf']} | واقعية {r['test_real']['avg']:+}R")
    stable=[r for r in elig[:6] if r["test"]["avg"]>0 and r["test"]["pf"]>=1.1 and r["train"]["avg"]>0]
    L.append("")
    if stable:
        p=stable[0]["params"]
        L.append(f"المقترح (أعلى TRAIN وصامد في TEST):\n/v10set stop_tf={p['stop_tf']} stop_k={p['stop_k']:g} min_adx={p['min_adx']:g} cooldown={p['cooldown']} rr={p['rr']}")
        L.append("بعد التطبيق أعد /bt على فترة أو عملات مختلفة قبل الاعتماد.")
    else:
        L.append("🔴 لا توجد تركيبة موجبة وصامدة: تعديل هذه المعاملات لا يكفي، والمشكلة في المحفز/النظام نفسه وليست في الوقف والأهداف.")
    if errors: L+=["",f"⚠️ فشل تحميل {len(errors)} عملة: "+", ".join(list(errors)[:6])]
    return "\n".join(L)

# ======================= الرادارات الأربعة (Radars → Opportunities) =======================
# المبدأ: كل رادار يقرأ شموعاً مغلقة فقط ويُخرج فرصة كاملة: دخول + وقف هيكلي + 4 أهداف + تقييم.
# بلا نظر للمستقبل: الإشارة على إغلاق الشمعة t، والدخول عند افتتاح t+1، والقمم/القيعان لا تُرى قبل تأكيدها،
# وفريم الفلتر الأعلى لا يُرى قبل إغلاقه. كل ما يُنشر يحمل وسم التحقق (موثّق / تجريبي / مرفوض).
RADAR_TP_FRACS = [0.50, 0.25, 0.15, 0.10]
RADAR_STOP_PCT = (0.15, 3.0)          # (أدنى, أقصى) وقف الخسارة كنسبة من الدخول — السقف 3% كما في البوت
RADAR_GRADES = (("A+", 85.0), ("A", 75.0), ("B", 60.0))
RADAR_FUNDING_8H = 0.0001             # تكلفة تمويل تقديرية لكل 8 ساعات (تُعامل كتكلفة دائماً: متحفظة)
RADAR_VERDICT_AR = {
    "validated": "✅ موثّق (اجتاز اختبار OOS بعد التكاليف)",
    "experimental": "🧪 تجريبي — لم يُثبت إحصائياً بعد",
    "rejected": "⛔ مرفوض في الباك تست"}
RADAR_VERDICT_EN = {
    "validated": "✅ Validated (passed out-of-sample test after costs)",
    "experimental": "🧪 Experimental — not statistically proven yet",
    "rejected": "⛔ Rejected in backtest"}
RADAR_FRAME_TTL = {"15m": 50, "1h": 240, "4h": 600, "1d": 1800}

RADARS = {
    "liquidity_sweep": dict(
        cmd="sweep", emoji="🌊", ar="رادار سحب السيولة", en="Liquidity Sweep Radar",
        tf="15m", frames=("15m", "4h"), min_bars=400, r=(1.5, 2.5, 3.5, 5.0), hold=16, fresh=2, bt_years=0.5,
        p=dict(htf="4h", htf_ema=50, atr_n=14, pl=3, pr=3, k=3, max_age=96,
               min_depth=0.10, min_pos=0.60, buf=0.10)),
    "fvg": dict(
        cmd="fvg", emoji="🧩", ar="رادار فجوات القيمة العادلة", en="Fair Value Gap Radar",
        tf="15m", frames=("15m", "1h"), min_bars=300, r=(1.5, 2.5, 3.5, 5.0), hold=16, fresh=2, bt_years=0.5,
        p=dict(htf="1h", htf_ema=50, atr_n=14, disp=1.0, gmin=0.20, gmax=3.00, max_age=32, buf=0.20)),
    "hourly_momentum": dict(
        cmd="momentum", emoji="🚀", ar="رادار زخم الساعة", en="Hourly Momentum Radar",
        tf="1h", frames=("1h",), min_bars=260, r=(1.5, 2.5, 3.5, 5.0), hold=4, fresh=1, bt_years=2.0,
        p=dict(move=3.0, vol_win=24, vol_mult=1.5, loc=0.70, atr_n=14, sl_atr=1.5, shorts=True)),
    "bollinger_pctb_short": dict(
        cmd="bbshort", emoji="🔻", ar="رادار بولينجر %B (بيع)", en="Bollinger %B Short Radar",
        tf="4h", frames=("4h",), min_bars=120, r=(1.0, 2.0, 3.0, 4.0), hold=1, fresh=1, bt_years=3.0,
        p=dict(n=20, k=2.0, rsi_n=14, rsi_min=65.0, pb_hi=1.0, atr_n=14, buf=0.25)),
}
RADAR_BY_CMD = {v["cmd"]: k for k, v in RADARS.items()}


def radar_label(name, lang="ar"):
    s = RADARS[name]
    return f"{s['emoji']} {s['ar'] if lang != 'en' else s['en']}"


# ----------------------------------------------------------------- مؤشرات سببية
def _r_frame(df):
    """شموع البوت (عمود t بالملي ثانية) -> إطار مفهرس بزمن فتح الشمعة (UTC)."""
    out = df[["open", "high", "low", "close", "volume"]].astype(float).copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(df["t"].to_numpy(dtype="int64"), unit="ms", utc=True))
    return out


def _r_atr(d, n=14):
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _r_ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _r_rsi(c, n=14):
    dl = c.diff()
    up, dn = dl.clip(lower=0.0), -dl.clip(upper=0.0)
    au = up.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    out = 100.0 - 100.0 / (1.0 + au / ad)
    out = out.mask((ad == 0) & (au > 0), 100.0)
    return out.mask((ad == 0) & (au == 0), 50.0)


def _r_bb(c, n=20, k=2.0):
    mid = c.rolling(n, min_periods=n).mean()
    sd = c.rolling(n, min_periods=n).std(ddof=0)
    up, lo = mid + k * sd, mid - k * sd
    w = up - lo
    return pd.DataFrame({"mid": mid, "up": up, "lo": lo, "pb": (c - lo) / w.where(w > 0)})


def _r_pivots(d, left, right, k, max_age):
    """آخر k قيعان/قمم محورية *مؤكدة* (الأحدث أولاً) كما تُرى عند إغلاق كل شمعة.
    القمة عند p لا تظهر إلا من الشمعة p+right (لا نظر للمستقبل). الأعمدة lo1..lok و hi1..hik."""
    h, l = d["high"].to_numpy(float), d["low"].to_numpy(float)
    n = len(d)
    lo_hist, hi_hist = [], []
    out_lo, out_hi = np.full((n, k), np.nan), np.full((n, k), np.nan)
    for t in range(n):
        p = t - right
        if p >= left:
            if l[p] == l[p - left:p + right + 1].min() and l[p] < l[p - left:p].min():
                lo_hist.append((p, l[p]))
            if h[p] == h[p - left:p + right + 1].max() and h[p] > h[p - left:p].max():
                hi_hist.append((p, h[p]))
            del lo_hist[:-64], hi_hist[:-64]
        for hist, out in ((lo_hist, out_lo), (hi_hist, out_hi)):
            j = 0
            for idx, lvl in reversed(hist):
                if t - idx > max_age or j >= k:
                    break
                out[t, j] = lvl
                j += 1
    cols = {f"lo{j + 1}": out_lo[:, j] for j in range(k)}
    cols.update({f"hi{j + 1}": out_hi[:, j] for j in range(k)})
    return pd.DataFrame(cols, index=d.index)


def _r_align(base_idx, base_tf, htf_feat, htf_tf):
    """يُسقط ميزات الفريم الأعلى على شموع الفريم الأساسي بدون نظر للمستقبل:
    صف الفريم الأعلى لا يُرى إلا بعد إغلاقه (فتح + مدته)."""
    h = htf_feat.copy()
    h.index = h.index + pd.Timedelta(milliseconds=TF_MS[htf_tf])
    target = base_idx + pd.Timedelta(milliseconds=TF_MS[base_tf])
    out = h.reindex(target, method="ffill")
    out.index = base_idx
    return out


def _r_resample(df, tf):
    """يبني فريماً أعلى من شموع أدق (للباك تست). الشموع غير المكتملة تُحذف."""
    tfms = TF_MS[tf]
    step = int(np.median(np.diff(df["t"].to_numpy(dtype="int64")[-200:])))
    need = max(tfms // max(step, 1), 1)
    b = (df["t"].astype("int64") // tfms) * tfms
    g = df.groupby(b, sort=True)
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), volume=("volume", "sum"), n=("t", "count"))
    out = out[out["n"] >= need].drop(columns="n")
    out.insert(0, "t", out.index.astype("int64"))
    return out.reset_index(drop=True)


def _r_finish(d, side, stop, score, reason, info, atr):
    """يوحّد مخرجات الرادارات ويُسقط الإشارات ذات المخاطرة خارج الحدود (قبل الدخول الفعلي)."""
    c = d["close"]
    side = pd.Series(side, index=d.index).astype(float).fillna(0.0)
    pct = (c - stop).abs() / c * 100.0
    ok = (((side > 0) & (stop < c)) | ((side < 0) & (stop > c))) & pct.between(*RADAR_STOP_PCT)
    return pd.DataFrame({"side": side.where(ok, 0.0).astype(int), "stop": stop,
                         "score": score.clip(0, 100).round(1), "reason": reason,
                         "info": info, "atr": atr}, index=d.index)


def _r_info(d, mask, fn):
    out = pd.Series([None] * len(d), index=d.index, dtype=object)
    for ts in d.index[np.asarray(mask)]:
        out[ts] = fn(ts)
    return out


# ----------------------------------------------------------------- 1) سحب السيولة
def _radar_sweep(d, aux, p, tf):
    a = _r_atr(d, p["atr_n"])
    piv = _r_pivots(d, p["pl"], p["pr"], p["k"], p["max_age"])
    htf = aux[p["htf"]]
    feat = pd.DataFrame({"c": htf["close"], "e": _r_ema(htf["close"], p["htf_ema"])})
    al = _r_align(d.index, tf, feat, p["htf"])
    up, dn = al["c"] > al["e"], al["c"] < al["e"]
    o, h, l, c = d["open"], d["high"], d["low"], d["close"]
    rng = (h - l).where(h > l)
    lo_l = pd.Series(np.nan, index=d.index)
    hi_l = pd.Series(np.nan, index=d.index)
    for j in range(1, p["k"] + 1):
        lv, hv = piv[f"lo{j}"], piv[f"hi{j}"]
        lo_l = lo_l.where(lo_l.notna(), lv.where((l < lv) & (c > lv)))
        hi_l = hi_l.where(hi_l.notna(), hv.where((h > hv) & (c < hv)))
    dep_l, dep_s = (lo_l - l) / a, (h - hi_l) / a
    pos_l, pos_s = (c - l) / rng, (h - c) / rng
    long_m = lo_l.notna() & up & (dep_l >= p["min_depth"]) & (pos_l >= p["min_pos"])
    short_m = hi_l.notna() & dn & (dep_s >= p["min_depth"]) & (pos_s >= p["min_pos"]) & ~long_m
    side = pd.Series(0, index=d.index)
    side[long_m], side[short_m] = 1, -1
    stop = pd.Series(np.nan, index=d.index)
    stop[long_m] = (l - p["buf"] * a)[long_m]
    stop[short_m] = (h + p["buf"] * a)[short_m]
    dep = dep_l.where(long_m, dep_s).fillna(0.0)
    pos = pos_l.where(long_m, pos_s).fillna(0.0)
    score = 50.0 + 15.0 * dep.clip(0, 2) + 25.0 * ((pos - p["min_pos"]) / (1 - p["min_pos"])).clip(0, 1)
    reason = pd.Series(np.where(long_m, f"سحب سيولة تحت قاع محوري ثم إغلاق داخله · 4س فوق EMA{p['htf_ema']}",
                       np.where(short_m, f"سحب سيولة فوق قمة محورية ثم رفض · 4س تحت EMA{p['htf_ema']}", "")),
                       index=d.index, dtype=object)
    info = _r_info(d, long_m | short_m, lambda ts: dict(
        kind="low" if long_m[ts] else "high", level=float(lo_l[ts] if long_m[ts] else hi_l[ts])))
    sig = _r_finish(d, side, stop, score, reason, info, a)
    t_up, t_dn = bool(up.iloc[-1]), bool(dn.iloc[-1])
    sig.attrs["diag"] = ["فلتر 4س: " + ("صاعد (يسمح بالشراء)" if t_up else ("هابط (يسمح بالبيع)" if t_dn else "غير متاح")),
                         "لا سحب سيولة مؤكد على آخر شمعة"]
    return sig


# ----------------------------------------------------------------- 2) فجوة القيمة العادلة
def _radar_fvg(d, aux, p, tf):
    n = len(d)
    a = _r_atr(d, p["atr_n"])
    av = a.to_numpy()
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    htf = aux[p["htf"]]
    feat = pd.DataFrame({"c": htf["close"], "e": _r_ema(htf["close"], p["htf_ema"])})
    al = _r_align(d.index, tf, feat, p["htf"])
    up, dn = (al["c"] > al["e"]).to_numpy(), (al["c"] < al["e"]).to_numpy()
    side, stop, score = np.zeros(n, int), np.full(n, np.nan), np.zeros(n)
    reason = np.full(n, "", dtype=object)
    infos = {}
    gaps = []  # [born, side, bottom, top]
    for t in range(2, n):
        at = av[t]
        if not np.isfinite(at) or at <= 0:
            continue
        alive, fired = [], None
        for g in gaps:
            born, gs, bot, top = g
            if t - born > p["max_age"]:
                continue
            if gs == 1:
                if c[t] < bot:
                    continue
                if fired is None and l[t] <= top and c[t] > o[t] and c[t] > bot and up[t]:
                    fired = g
                    continue
            else:
                if c[t] > top:
                    continue
                if fired is None and h[t] >= bot and c[t] < o[t] and c[t] < top and dn[t]:
                    fired = g
                    continue
            alive.append(g)
        gaps = alive
        if fired is not None:
            born, gs, bot, top = fired
            side[t] = gs
            size = (top - bot) / at
            if gs == 1:
                stop[t] = min(bot, l[t]) - p["buf"] * at
                reason[t] = "إعادة اختبار فجوة صاعدة + شمعة إغلاق صاعدة · 1س فوق EMA%d" % p["htf_ema"]
            else:
                stop[t] = max(top, h[t]) + p["buf"] * at
                reason[t] = "إعادة اختبار فجوة هابطة + شمعة إغلاق هابطة · 1س تحت EMA%d" % p["htf_ema"]
            score[t] = 60.0 + 15.0 * min(size, 2.0) + 10.0
            infos[t] = dict(bot=float(bot), top=float(top), born_t=int(d.index[born].value // 10**6))
        if np.isfinite(av[t - 1]) and abs(c[t - 1] - o[t - 1]) >= p["disp"] * av[t - 1]:
            if l[t] > h[t - 2] and c[t - 1] > o[t - 1]:
                gs_ = (l[t] - h[t - 2]) / at
                if p["gmin"] <= gs_ <= p["gmax"]:
                    gaps.append([t, 1, h[t - 2], l[t]])
            elif h[t] < l[t - 2] and c[t - 1] < o[t - 1]:
                gs_ = (l[t - 2] - h[t]) / at
                if p["gmin"] <= gs_ <= p["gmax"]:
                    gaps.append([t, -1, h[t], l[t - 2]])
    idx = d.index
    info = pd.Series([infos.get(i) for i in range(n)], index=idx, dtype=object)
    sig = _r_finish(d, pd.Series(side, index=idx), pd.Series(stop, index=idx), pd.Series(score, index=idx),
                    pd.Series(reason, index=idx, dtype=object), info, a)
    sig.attrs["diag"] = ["فلتر 1س: " + ("صاعد" if up[-1] else ("هابط" if dn[-1] else "غير متاح")),
                         f"فجوات نشطة بانتظار إعادة الاختبار: {len(gaps)}"]
    return sig


# ----------------------------------------------------------------- 3) زخم الساعة
def _radar_momentum(d, aux, p, tf):
    o, h, l, c, v = (d[k] for k in ("open", "high", "low", "close", "volume"))
    a = _r_atr(d, p["atr_n"])
    ret = (c / c.shift(1) - 1.0) * 100.0
    va = v.rolling(p["vol_win"], min_periods=p["vol_win"]).mean().shift(1)
    vr = v / va.where(va > 0)
    rng = (h - l).where(h > l)
    pu, pdn = (c - l) / rng, (h - c) / rng
    long_m = (ret >= p["move"]) & (vr >= p["vol_mult"]) & (pu >= p["loc"])
    short_m = (ret <= -p["move"]) & (vr >= p["vol_mult"]) & (pdn >= p["loc"])
    if not p["shorts"]:
        short_m = short_m & False
    side = pd.Series(0, index=d.index)
    side[long_m], side[short_m] = 1, -1
    stop = pd.Series(np.nan, index=d.index)
    stop[long_m] = (c - p["sl_atr"] * a)[long_m]
    stop[short_m] = (c + p["sl_atr"] * a)[short_m]
    score = 45.0 + 10.0 * (ret.abs() / p["move"]).clip(0, 3) + 8.0 * (vr.fillna(0) / p["vol_mult"]).clip(0, 3)
    reason = pd.Series(np.where(long_m, f"شمعة ساعة ≥ +{p['move']:g}% مع فوليوم ≥ {p['vol_mult']:g}× وإغلاق قوي",
                       np.where(short_m, f"شمعة ساعة ≤ -{p['move']:g}% مع فوليوم ≥ {p['vol_mult']:g}× وإغلاق ضعيف", "")),
                       index=d.index, dtype=object)
    info = _r_info(d, long_m | short_m, lambda ts: dict(move=float(ret[ts]), vol_ratio=float(vr[ts])))
    sig = _r_finish(d, side, stop, score, reason, info, a)
    lr, lv_ = float(ret.iloc[-1]) if np.isfinite(ret.iloc[-1]) else 0.0, float(vr.iloc[-1]) if np.isfinite(vr.iloc[-1]) else 0.0
    sig.attrs["diag"] = [f"آخر شمعة ساعة: {lr:+.2f}% (الحد ±{p['move']:g}%)", f"الفوليوم: ×{lv_:.1f} (الحد ×{p['vol_mult']:g})"]
    return sig


# ----------------------------------------------------------------- 4) بولينجر %B بيع
def _radar_bbshort(d, aux, p, tf):
    o, h, c = d["open"], d["high"], d["close"]
    bb = _r_bb(c, p["n"], p["k"])
    pb = bb["pb"]
    a = _r_atr(d, p["atr_n"])
    r = _r_rsi(c, p["rsi_n"])
    short_m = (pb.shift(1) >= p["pb_hi"]) & (pb < p["pb_hi"]) & (c < o) & (r.shift(1) >= p["rsi_min"])
    side = pd.Series(0, index=d.index)
    side[short_m] = -1
    stop = pd.Series(np.nan, index=d.index)
    stop[short_m] = (pd.concat([h, h.shift(1)], axis=1).max(axis=1) + p["buf"] * a)[short_m]
    score = 50.0 + (pb.shift(1) - p["pb_hi"]).clip(0, 0.5) * 40.0 + (r.shift(1) - p["rsi_min"]).clip(0, 20)
    reason = pd.Series(np.where(short_m, "إغلاق سابق فوق باند بولينجر العلوي + RSI مرتفع ثم شمعة رفض هابطة", ""),
                       index=d.index, dtype=object)
    info = _r_info(d, short_m, lambda ts: dict(pb_prev=float(pb.shift(1)[ts]), rsi_prev=float(r.shift(1)[ts])))
    sig = _r_finish(d, side, stop, score, reason, info, a)
    lp = float(pb.iloc[-1]) if np.isfinite(pb.iloc[-1]) else 0.0
    lr = float(r.iloc[-1]) if np.isfinite(r.iloc[-1]) else 50.0
    sig.attrs["diag"] = [f"%B الحالي = {lp:.2f} (يلزم إغلاق ≥ {p['pb_hi']:g} ثم رفض)", f"RSI = {lr:.0f} (يلزم ≥ {p['rsi_min']:g} قبل الرفض)"]
    return sig


_RADAR_FN = {"liquidity_sweep": _radar_sweep, "fvg": _radar_fvg,
             "hourly_momentum": _radar_momentum, "bollinger_pctb_short": _radar_bbshort}


def radar_signals(name, frames):
    """frames = {tf: شموع البوت}. يرجع إطار إشارات (side/stop/score/reason/info/atr + t بالملي ثانية)
    على شموع الفريم الأساسي للرادار، أو None إذا البيانات غير كافية."""
    spec = RADARS[name]
    base = frames.get(spec["tf"])
    if base is None or len(base) < spec["min_bars"]:
        return None
    for tf in spec["frames"]:
        if tf != spec["tf"] and (frames.get(tf) is None or len(frames[tf]) < 60):
            return None
    d = _r_frame(base)
    aux = {tf: _r_frame(frames[tf]) for tf in spec["frames"] if tf != spec["tf"]}
    sig = _RADAR_FN[name](d, aux, spec["p"], spec["tf"])
    sig["t"] = base["t"].to_numpy(dtype="int64")
    return sig


# ----------------------------------------------------------------- مستويات الصفقة
def radar_grade(score):
    for g, th in RADAR_GRADES:
        if score >= th:
            return g
    return "C"


def radar_levels(side, entry, stop, atr, r_mults):
    """مستويات الفرصة بصيغة البوت (4 أهداف بنسب 50/25/15/10). None إن كانت المخاطرة خارج الحدود."""
    risk = side * (entry - stop)
    if not (entry > 0 and risk > 0):
        return None
    if not (RADAR_STOP_PCT[0] <= risk / entry * 100.0 <= RADAR_STOP_PCT[1]):
        return None
    tps = []
    for k, m in enumerate(r_mults):
        px = entry + side * risk * m
        tps.append(dict(px=float(px), pct=round(100 * side * (px - entry) / entry, 2),
                        frac=RADAR_TP_FRACS[k], hit=False, src="R"))
    return dict(entry=float(entry), sl=float(stop), risk=float(risk), tps=tps, atr=float(atr or 0.0))


def radar_eval(name, frames, price=None):
    """يقيّم رادارًا واحدًا على آخر شمعة مغلقة.
    يرجع (opp, diag): opp = dict جاهز للنشر/التتبع، أو None مع diag = أسطر تشرح الحالة."""
    spec = RADARS[name]
    sig = radar_signals(name, frames)
    if sig is None:
        return None, ["بيانات غير كافية لهذا الرادار"]
    n = len(sig)
    lo = max(0, n - spec["fresh"])
    rows = sig.iloc[lo:]
    hit = rows[rows["side"] != 0]
    diag = list(sig.attrs.get("diag", []))
    if hit.empty:
        return None, diag
    row = hit.iloc[-1]
    side = int(row["side"])
    pos = sig.index.get_loc(hit.index[-1])
    ref = float(frames[spec["tf"]]["close"].iloc[pos])          # سعر إغلاق شمعة الإشارة
    entry = float(price) if price else float(frames[spec["tf"]]["close"].iloc[-1])
    stop = float(row["stop"])
    # لا مطاردة: إن ابتعد السعر أكثر من نصف المخاطرة عن نقطة الإشارة فالفرصة انتهت
    if side * (entry - ref) > 0.5 * abs(ref - stop):
        return None, diag + ["إشارة منتهية: السعر ابتعد أكثر من نصف المخاطرة عن نقطة الإشارة (لا مطاردة)"]
    lv = radar_levels(side, entry, stop, float(row["atr"]), spec["r"])
    if lv is None:
        return None, diag + ["إشارة ملغاة: السعر الحالي جعل المخاطرة خارج الحدود (0.15%–3%) أو تجاوز الوقف"]
    score = float(row["score"])
    opp = dict(radar=name, side=side, tf=spec["tf"], score=score, grade=radar_grade(score),
               reasons=[x for x in str(row["reason"]).split(" · ") if x], lv=lv,
               bar_t=int(row["t"]), info=row["info"] if isinstance(row["info"], dict) else {},
               max_hold=spec["hold"], age_bars=int(n - 1 - sig.index.get_loc(hit.index[-1])))
    return opp, diag


# ======================================================================================================================
# Strategy lab: backtest-only. These radars are NOT wired to live publishing until /btx proves them on real data.
# ======================================================================================================================
def radar_replay(name, frames, max_hold=None):
    """Replay one radar strategy: signals are causal (verified), entry = open of the NEXT candle of the radar's own
    timeframe, management = the SAME trade_step as live (partial TPs 50/25/15/10, BE after TP1, trailing after TP2,
    per-radar bar limit), cost = trade_cost_r (fees + slippage + funding estimate). One open trade per symbol.
    Returns (trades, data_start_ms, data_end_ms)."""
    spec = RADARS[name]; tf = spec["tf"]
    sig = radar_signals(name, frames)
    if sig is None: return [], 0, 0
    base = frames[tf]
    t = base["t"].to_numpy(dtype="int64"); o = base["open"].to_numpy(float); h = base["high"].to_numpy(float)
    l = base["low"].to_numpy(float); c = base["close"].to_numpy(float)
    atr_arr = sig["atr"].to_numpy(float)
    side_arr = sig["side"].to_numpy(int); stop_arr = sig["stop"].to_numpy(float); score_arr = sig["score"].to_numpy(float)
    hold = int(max_hold or spec["hold"]); step_ms = TF_MS[tf]
    data_start, data_end = int(t[min(len(t) - 1, spec["min_bars"])]), int(t[-1])
    trades = []; next_ok = 0
    for j in range(spec["min_bars"], len(t) - 1):
        s = int(side_arr[j])
        if s == 0 or t[j] < next_ok: continue
        fill = float(o[j + 1]); stop = float(stop_arr[j]); ref = float(c[j])
        if s * (fill - ref) > 0.5 * abs(ref - stop): continue          # same no-chase rule as radar_eval
        lv = radar_levels(s, fill, stop, atr_arr[j], spec["r"])
        if lv is None: continue
        p = new_trade(name, tf, s, lv, int(t[j]), radar_grade(float(score_arr[j])), name, max_hold=hold)
        k = j + 1
        while k < len(t) and p["state"] in ("pending", "open"):
            trade_step(p, o[k], h[k], l[k], c[k], atr_arr[k] if np.isfinite(atr_arr[k]) else 0.0); k += 1
        if p["state"] != "closed": break
        gross = round(p["realized"], 4)
        trades.append(dict(coin=name, sym=None, t=int(t[j + 1]), signal_t=int(t[j]) + step_ms, R=p["R"], gross_R=gross,
            exit=p["result"], bars=p["bars"], tps=sum(1 for x in p["tps"] if x["hit"]), cost=round(gross - p["R"], 4),
            grade=p["grade"], score=float(score_arr[j]), side=s, setup=name, strategy=name,
            risk_pct=round(100 * lv["risk"] / fill, 4), hours=p["bars"] * step_ms / 3_600_000, entry=fill,
            data_start=data_start, data_end=data_end))
        next_ok = int(t[k - 1]) + step_ms
    return trades, data_start, data_end


def _lab_frames(sym, name, years):
    spec = RADARS[name]; years = min(max(float(years), 0.1), 3.0)
    per_year = {"15m": 365 * 96, "1h": 365 * 24, "4h": 365 * 6}
    out = {}
    for tf in spec["frames"]:
        n = int(years * per_year[tf]) + 400
        rows, _ = v10_futures_history(sym, tf, n)
        raw = _rows_to_df(rows, tf, n)
        if len(raw) < 100: raise NoData(f"{sym}: بيانات {tf} غير كافية ({len(raw)})")
        out[tf] = raw
    return out


def lab_many(symbols, name, years=None):
    """Backtest one radar over many symbols; returns (per, tmin, tmax, errors) like backtest_many."""
    years = years or RADARS[name]["bt_years"]
    per, errors, tmin, tmax = {}, {}, None, None
    for sym in dict.fromkeys(symbols):
        try:
            trs, a, b = radar_replay(name, _lab_frames(sym, name, years))
            for x in trs: x["sym"] = sym; x["coin"] = sym
            per[sym] = trs
            if a: tmin = a if tmin is None else min(tmin, a); tmax = b if tmax is None else max(tmax, b)
        except Exception as ex:
            errors[sym] = f"{type(ex).__name__}: {str(ex)[:100]}"
    return per, tmin, tmax, errors


def lab_report(name, per, tmin, tmax, errors=None, years=None):
    spec = RADARS[name]; errors = errors or {}
    allt = [x for tr in per.values() for x in tr]
    L = [f"🧪 Strategy Lab · {radar_label(name)} · {len(per)} عملة · {years or spec['bt_years']:g} سنة · {BOT_VERSION}",
         f"الإطار {spec['tf']} | أهداف R={spec['r']} | حد {spec['hold']} شمعة | دخول عند افتتاح الشمعة التالية | إدارة = trade_step الحي",
         f"💸 رسوم {FEE*100:.2f}% + انزلاق {SLIP*100:.2f}% لكل جهة + تمويل تقديري. التقسيم TRAIN/TEST زمني لكل عملة."]
    if not allt:
        L += ["", "⚠️ لا صفقات في الفترة — لا حكم."]
    else:
        tr, te = split_trades_by_symbol(allt, tmin, tmax, 0.65)
        mt, me = metrics(tr), metrics(te)
        L += ["", f"TRAIN: n={mt['n']} | WR {mt['wr']}% | PF {mt['pf']} | {mt['total']:+}R | متوسط {mt['avg']:+}R",
              f"TEST : n={me['n']} | WR {me['wr']}% | PF {me['pf']} | {me['total']:+}R | متوسط {me['avg']:+}R | أقصى تراجع {me['dd']}R"]
        if te:
            mr = metrics(_real_cost_trades(te))
            L.append(f"🧮 قبل التكلفة {np.mean([x['gross_R'] for x in te]):+.3f}R | التكلفة {np.mean([x['cost'] for x in te]):.3f}R | "
                     f"بتكلفة واقعية {mr['avg']:+}R PF {mr['pf']}")
            for side, nm in ((1, "BUY"), (-1, "SELL")):
                sub = [x for x in te if x["side"] == side]
                if sub:
                    m = metrics(sub); L.append(f"{nm}: n={m['n']} · WR {m['wr']}% · PF {m['pf']} · {m['total']:+}R")
        L += ["", f"الحكم: {bt_verdict(mt, me)}"]
    if errors:
        L += ["", f"⚠️ فشل {len(errors)} عملة: " + " | ".join(f"{k}: {v[:60]}" for k, v in list(errors.items())[:3])]
    return "\n".join(L)


# ======================================================================================================================
# Swing lab (backtest-only): low-frequency strategies where costs are small relative to the move.
# ======================================================================================================================
SWING_DEFAULTS = dict(don_n=55, exit_n=20, atr_n=20, stop_atr=3.0, ema_n=200, max_hold=250, mom_n=28, hold_days=7, k=3)

def _wilder_np(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()

def trend_replay(d, params=None):
    """Daily Donchian trend-following, long AND short.
    Signal on the close of day j: close breaks the prior `don_n`-day high (low) with close above (below) EMA(ema_n).
    Entry = open of day j+1. Stop = entry -/+ stop_atr*ATR. Exit = intraday stop (fills at the open when gapped),
    or a close beyond the prior `exit_n`-day low (high) -> exit at the NEXT open, or max_hold. One position at a time.
    R unit = initial risk. Cost = fees+slippage both ways + funding estimate (trade_cost_r)."""
    p = dict(SWING_DEFAULTS); p.update(params or {})
    t = d["t"].to_numpy("int64"); o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float); c = d["close"].to_numpy(float); n = len(c)
    if n < p["ema_n"] + p["don_n"] + 10: return [], 0, 0
    s = pd.Series
    hi = s(h).shift(1).rolling(p["don_n"]).max().to_numpy(); lo = s(l).shift(1).rolling(p["don_n"]).min().to_numpy()
    ex_lo = s(l).shift(1).rolling(p["exit_n"]).min().to_numpy(); ex_hi = s(h).shift(1).rolling(p["exit_n"]).max().to_numpy()
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = _wilder_np(tr, p["atr_n"]); ema = s(c).ewm(span=p["ema_n"], adjust=False, min_periods=p["ema_n"]).mean().to_numpy()
    first = max(p["ema_n"], p["don_n"]) + 2
    trades = []; j = first; day = TF_MS["1d"]
    while j < n - 1:
        side = 0
        if np.isfinite(hi[j]) and c[j] > hi[j] and c[j] > ema[j]: side = 1
        elif np.isfinite(lo[j]) and c[j] < lo[j] and c[j] < ema[j]: side = -1
        if side == 0 or not np.isfinite(atr[j]) or atr[j] <= 0: j += 1; continue
        fill = float(o[j + 1]); risk = p["stop_atr"] * float(atr[j]); stop = fill - side * risk
        if risk / fill > 0.35: j += 1; continue                         # absurd stop (>35% of price): skip
        k = j + 1; exit_px = None; kind = None
        while k < n:
            if (side == 1 and l[k] <= stop) or (side == -1 and h[k] >= stop):
                exit_px = min(o[k], stop) if side == 1 else max(o[k], stop); kind = "STOP"; break
            if k - j >= p["max_hold"]: exit_px = float(c[k]); kind = "TIME"; break
            brk = (side == 1 and np.isfinite(ex_lo[k]) and c[k] < ex_lo[k]) or (side == -1 and np.isfinite(ex_hi[k]) and c[k] > ex_hi[k])
            if brk and k + 1 < n: exit_px = float(o[k + 1]); kind = "CHANNEL"; k += 1; break
            k += 1
        if exit_px is None: break                                       # still open at the end of data: not counted
        bars = k - j; gross = side * (exit_px - fill) / risk
        cost = (2 * (FEE + SLIP) + FUNDING_8H * (bars * 24) / 8.0) * fill / risk
        trades.append(dict(t=int(t[j + 1]), signal_t=int(t[j]) + day, R=round(gross - cost, 4), gross_R=round(gross, 4), cost=round(cost, 4),
                           exit=kind, bars=bars, side=side, grade="A", tps=0, entry=fill, risk_pct=round(100 * risk / fill, 3),
                           hours=bars * 24.0, ret_pct=round(100 * side * (exit_px / fill - 1), 3), strategy="trend"))
        j = k + 1                                                       # flat for the next day at least
    return trades, int(t[first]), int(t[-1])


def xsmom_replay(closes, opens, times, params=None):
    """Weekly cross-sectional momentum. closes/opens: dict sym -> aligned numpy arrays over the SAME daily dates.
    Every `hold_days` days (decision at the close of day j) rank symbols by their `mom_n`-day return, go long the top k
    and short the bottom k; entries at the open of j+1, exits at the open of j+1+hold_days. Funding is charged to longs only.
    Returns weekly rows: long/short/spread/benchmark net returns in % per week."""
    p = dict(SWING_DEFAULTS); p.update(params or {})
    syms = list(closes); n = len(times)
    if len(syms) < 2 * p["k"] + 2 or n < p["mom_n"] + p["hold_days"] + 5: return []
    C = np.vstack([closes[s] for s in syms]); O = np.vstack([opens[s] for s in syms])
    rows = []; j = p["mom_n"]
    cost_side = 2 * (FEE + SLIP) * 100.0
    fund_long = FUNDING_8H * (p["hold_days"] * 3) * 100.0
    while j + 1 + p["hold_days"] < n:
        mom = C[:, j] / C[:, j - p["mom_n"]] - 1.0
        ok = np.isfinite(mom) & np.isfinite(O[:, j + 1]) & np.isfinite(O[:, j + 1 + p["hold_days"]]) & (O[:, j + 1] > 0)
        idx = np.where(ok)[0]
        if len(idx) >= 2 * p["k"] + 2:
            order = idx[np.argsort(mom[idx])]
            shorts, longs = order[:p["k"]], order[-p["k"]:]
            ret = (O[:, j + 1 + p["hold_days"]] / O[:, j + 1] - 1.0) * 100.0
            lr = float(np.mean(ret[longs])) - cost_side - fund_long
            sr = float(np.mean(-ret[shorts])) - cost_side
            bench = float(np.mean(ret[idx]))
            rows.append(dict(t=int(times[j + 1]), long=lr, short=sr, spread=0.5 * (lr + sr), bench=bench))
        j += p["hold_days"]
    return rows


def _swing_stats(x):
    x = np.asarray(x, float)
    if len(x) < 2: return dict(n=len(x), mean=0.0, t=0.0, wr=0.0, dd=0.0)
    sd = float(x.std(ddof=1)); eq = np.cumsum(x)
    return dict(n=len(x), mean=round(float(x.mean()), 3), t=round(float(x.mean() / (sd / np.sqrt(len(x)))) if sd > 0 else 0.0, 2),
                wr=round(100 * float((x > 0).mean()), 1), dd=round(float((np.maximum.accumulate(eq) - eq).max()), 1))


def swing_data(symbols, years):
    n = int(min(max(float(years), 0.5), 5.0) * 365) + 300
    out, errors = {}, {}
    for sym in dict.fromkeys(symbols):
        try:
            rows, _ = v10_futures_history(sym, "1d", n)
            out[sym] = _rows_to_df(rows, "1d", n)
        except Exception as ex: errors[sym] = f"{type(ex).__name__}: {str(ex)[:90]}"
    return out, errors


def trend_report(data, errors=None, years=3.0):
    errors = errors or {}; allt = []; a = b = None; per_sym = {}
    for sym, d in data.items():
        trs, s, e = trend_replay(d)
        for x in trs: x["sym"] = sym; x["coin"] = sym; x["data_start"] = s; x["data_end"] = e
        allt += trs; per_sym[sym] = trs
        if s: a = s if a is None else min(a, s); b = e if b is None else max(b, e)
    L = [f"🧭 Swing Lab · اتجاه يومي (Donchian {SWING_DEFAULTS['don_n']}/{SWING_DEFAULTS['exit_n']} + EMA{SWING_DEFAULTS['ema_n']}) · {len(data)} عملة · {BOT_VERSION}",
         f"وقف {SWING_DEFAULTS['stop_atr']}×ATR | الخروج: وقف أو كسر قناة {SWING_DEFAULTS['exit_n']} يوم | دخول عند افتتاح اليوم التالي | شراء وبيع",
         f"💸 رسوم {FEE*100:.2f}% + انزلاق {SLIP*100:.2f}% لكل جهة + تمويل تقديري. TRAIN/TEST زمني لكل عملة."]
    if not allt: return "\n".join(L + ["", "⚠️ لا صفقات — لا حكم."])
    tr, te = split_trades_by_symbol(allt, a, b, 0.65); mt, me = metrics(tr), metrics(te)
    L += ["", f"TRAIN: n={mt['n']} | WR {mt['wr']}% | PF {mt['pf']} | {mt['total']:+}R | متوسط {mt['avg']:+}R",
          f"TEST : n={me['n']} | WR {me['wr']}% | PF {me['pf']} | {me['total']:+}R | متوسط {me['avg']:+}R | أقصى تراجع {me['dd']}R"]
    if te:
        mr = metrics(_real_cost_trades(te))
        L.append(f"🧮 قبل التكلفة {np.mean([x['gross_R'] for x in te]):+.3f}R | التكلفة {np.mean([x['cost'] for x in te]):.3f}R | بتكلفة واقعية {mr['avg']:+}R PF {mr['pf']}")
        for side, nm in ((1, "BUY"), (-1, "SELL")):
            sub = [x for x in te if x["side"] == side]
            if sub: m = metrics(sub); L.append(f"{nm}: n={m['n']} · WR {m['wr']}% · PF {m['pf']} · {m['total']:+}R · متوسط {m['avg']:+}R")
        by = sorted(((c, metrics([x for x in te if x["sym"] == c])) for c in {x["sym"] for x in te}), key=lambda z: z[1]["total"])
        L.append("الأسوأ: " + " | ".join(f"{c} {m['total']:+.1f}R" for c, m in by[:3]) + "  ||  الأفضل: " + " | ".join(f"{c} {m['total']:+.1f}R" for c, m in by[::-1][:3]))
        # concentration: profits from a handful of trades are fragile
        Rs = sorted([x["R"] for x in te], reverse=True)
        if len(Rs) >= 10 and sum(Rs) > 0:
            L.append(f"🎯 أفضل 10% من الصفقات تمثل {100*sum(Rs[:max(1, len(Rs)//10)])/max(sum(r for r in Rs if r > 0), 1e-9):.0f}% من إجمالي الأرباح")
    L += ["", f"الحكم: {bt_verdict(mt, me)}"]
    if errors: L += ["", f"⚠️ فشل {len(errors)} عملة: " + " | ".join(f"{k}: {v[:50]}" for k, v in list(errors.items())[:3])]
    return "\n".join(L)


def xsmom_report(data, errors=None, years=3.0):
    errors = errors or {}
    common = None
    for d in data.values():
        ts = set(d["t"].tolist()); common = ts if common is None else common & ts
    if not common or len(data) < 8:
        return "⚠️ Swing Lab · زخم مقطعي: يحتاج 8 عملات على الأقل بتاريخ مشترك."
    times = np.array(sorted(common), dtype="int64")
    closes = {s: d.set_index("t").loc[times, "close"].to_numpy(float) for s, d in data.items()}
    opens = {s: d.set_index("t").loc[times, "open"].to_numpy(float) for s, d in data.items()}
    rows = xsmom_replay(closes, opens, times)
    L = [f"🧭 Swing Lab · زخم مقطعي أسبوعي (ترتيب {SWING_DEFAULTS['mom_n']} يوم، شراء أعلى {SWING_DEFAULTS['k']} وبيع أدنى {SWING_DEFAULTS['k']}) · {len(data)} عملة · {BOT_VERSION}",
         f"إعادة موازنة كل {SWING_DEFAULTS['hold_days']} أيام | دخول/خروج عند الافتتاح | رسوم+انزلاق للطرفين، والتمويل على الشراء فقط. الأرقام % لكل أسبوع بعد التكلفة."]
    if len(rows) < 30: return "\n".join(L + ["", f"⚠️ {len(rows)} أسبوعاً فقط — لا حكم."])
    cut = int(len(rows) * 0.65); tr, te = rows[:cut], rows[cut:]
    def line(name, key, part): s = _swing_stats([r[key] for r in part]); return f"{name}: أسابيع={s['n']} | متوسط {s['mean']:+}% | t={s['t']} | WR {s['wr']}% | تراجع {s['dd']}%"
    L += ["", "— TRAIN —", line("شراء الأقوى", "long", tr), line("بيع الأضعف", "short", tr), line("الفرق (محايد للسوق)", "spread", tr), line("المؤشر (كل العملات)", "bench", tr),
          "— TEST —", line("شراء الأقوى", "long", te), line("بيع الأضعف", "short", te), line("الفرق (محايد للسوق)", "spread", te), line("المؤشر (كل العملات)", "bench", te)]
    ts_, tt_ = _swing_stats([r["spread"] for r in tr]), _swing_stats([r["spread"] for r in te])
    if tt_["n"] < 30: verdict = "⚪ عينة TEST صغيرة — لا حكم"
    elif tt_["mean"] > 0 and tt_["t"] >= 1.5 and ts_["mean"] > 0: verdict = "✅ الفرق موجب ومعنوي في TEST ومتسق مع TRAIN"
    elif tt_["mean"] > 0 and ts_["mean"] > 0: verdict = "🟡 موجب لكن غير معنوي إحصائياً (t<1.5) — لا يكفي للاعتماد"
    else: verdict = "🔴 لا ميزة بعد التكلفة"
    L += ["", f"الحكم (على الفرق المحايد): {verdict}", "ملاحظة: الشراء وحده يتبع اتجاه السوق؛ قارنه دائماً بالمؤشر. المحايد هو الاختبار الحقيقي للميزة."]
    if errors: L += ["", f"⚠️ فشل {len(errors)} عملة: " + " | ".join(f"{k}" for k in list(errors)[:5])]
    return "\n".join(L)


# ======================================================================================================================
# Intraday lab (backtest-only): does the previous hour's move predict the next 1-4h, depending on the UTC hour?
# Hours are chosen on TRAIN only (strict t-stat on per-day cross-sectional means); TEST is never used for selection.
# ======================================================================================================================
MAKER_FEE = 0.0002                       # maker fee per side (entry limit order model)
INTRA_DEFAULTS = dict(holds=(1, 2, 4), zmin=1.0, tmin=3.0, min_days=60, stop_atr=1.5, atr_n=14, vol_span=72,
                      train_ratio=0.65, maker_through_atr=0.1)
_HMS = 3_600_000

def _intra_feats(d, p):
    t = d["t"].to_numpy("int64"); o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float); c = d["close"].to_numpy(float); n = len(c)
    lr = np.diff(np.log(c), prepend=np.log(c[0]))
    sig = pd.Series(lr).ewm(span=p["vol_span"], adjust=False, min_periods=p["vol_span"]).std().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"): z = np.log(c / o) / sig
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return dict(t=t, o=o, h=h, l=l, c=c, n=n, sig=sig, z=z, atr=_wilder_np(tr, p["atr_n"]), hour=((t // _HMS) % 24).astype(int))

def _intra_valid(f, hold, p):
    """Signal bar j (closed), entry = open of j+1, exit = close of bar j+hold. Requires gap-free hourly bars."""
    n = f["n"]
    if n <= hold + 2: return np.zeros(0, int), np.zeros(0, bool)
    j = np.arange(n - hold)
    ok = (np.isfinite(f["z"][j]) & (np.abs(f["z"][j]) > p["zmin"]) & np.isfinite(f["atr"][j]) & (f["atr"][j] > 0)
          & (f["t"][j + hold] - f["t"][j] == hold * _HMS))
    return j, ok

def intra_hour_select(feats, hold, cut, params=None):
    """Per UTC hour: mean of sign(z)*y (y = forward return / (sigma*sqrt(hold)), winsorised) averaged over symbols per day,
    then a t-stat across days. Only observations whose trade has ENDED before `cut` are used. Returns ({hour: +1 momentum / -1 reversal}, table)."""
    p = dict(INTRA_DEFAULTS); p.update(params or {})
    parts = []
    for f in feats.values():
        j, ok = _intra_valid(f, hold, p)
        if len(j) == 0: continue
        ok = ok & (f["t"][j + hold] + _HMS <= cut)
        if not ok.any(): continue
        jj = j[ok]
        y = np.clip(np.log(f["c"][jj + hold] / f["o"][jj + 1]) / (f["sig"][jj] * np.sqrt(hold)), -5, 5)
        parts.append(pd.DataFrame(dict(day=f["t"][jj] // 86_400_000, hour=f["hour"][jj], s=np.sign(f["z"][jj]) * y)))
    if not parts: return {}, {}
    df = pd.concat(parts); dd = df.groupby(["day", "hour"])["s"].mean().reset_index()
    g = dd.groupby("hour")["s"].agg(["mean", "std", "count"])
    tab = {}; dirs = {}
    for hr, r in g.iterrows():
        tt = float(r["mean"] / (r["std"] / np.sqrt(r["count"]))) if r["count"] > 2 and r["std"] > 0 else 0.0
        tab[int(hr)] = dict(mean=float(r["mean"]), t=tt, days=int(r["count"]))
        if r["count"] >= p["min_days"] and abs(tt) >= p["tmin"]: dirs[int(hr)] = 1 if r["mean"] > 0 else -1
    return dirs, tab

def intra_trades(sym, f, hold, dirs, t_from, t_to, params=None):
    """Trades whose SIGNAL candle opens in [t_from, t_to). One position per symbol at a time. Gross return in price terms;
    costs are applied separately per cost model (see _intra_pack)."""
    p = dict(INTRA_DEFAULTS); p.update(params or {})
    j, ok = _intra_valid(f, hold, p)
    if len(j) == 0 or not dirs: return []
    hours_ok = np.isin(f["hour"][j], list(dirs))
    cand = j[ok & hours_ok & (f["t"][j] >= t_from) & (f["t"][j] < t_to)]
    out = []; busy = -1
    for jj in cand:
        jj = int(jj)
        if jj < busy: continue
        busy = jj + hold
        side = dirs[int(f["hour"][jj])] * (1 if f["z"][jj] > 0 else -1)
        fill = float(f["o"][jj + 1]); frac = min(max(p["stop_atr"] * float(f["atr"][jj]) / fill, 0.0025), 0.05)
        stop = fill * (1 - side * frac); exit_px = float(f["c"][jj + hold]); kind = "TIME"
        for k in range(jj + 1, jj + hold + 1):
            if side == 1 and f["l"][k] <= stop: exit_px = min(float(f["o"][k]), stop); kind = "STOP"; break
            if side == -1 and f["h"][k] >= stop: exit_px = max(float(f["o"][k]), stop); kind = "STOP"; break
        thr = p["maker_through_atr"] * float(f["atr"][jj])
        filled = bool(f["l"][jj + 1] <= fill - thr) if side == 1 else bool(f["h"][jj + 1] >= fill + thr)
        out.append(dict(t=int(f["t"][jj + 1]), signal_t=int(f["t"][jj]) + _HMS, sym=sym, side=side, hold=hold, hour=int(f["hour"][jj]),
                        gross=side * (exit_px / fill - 1.0), risk=frac, exit=kind, filled=filled,
                        fund=FUNDING_8H * hold / 8.0))
    return out

def _intra_cost(model, x):
    base = {"cfg": 2 * (FEE + SLIP), "real": 2 * (REAL_FEE + REAL_SLIP), "maker": MAKER_FEE + REAL_FEE + REAL_SLIP}[model]
    return base + x["fund"]

def _intra_pack(trs, model):
    """Trades -> dicts for metrics(); R = (gross - cost)/risk. The maker model drops unfilled entries."""
    return [dict(t=x["t"], R=round((x["gross"] - _intra_cost(model, x)) / x["risk"], 4), tps=0, sym=x["sym"])
            for x in trs if model != "maker" or x["filled"]]

def _intra_day_t(trs):
    if len(trs) < 5: return 0.0
    s = pd.DataFrame(dict(d=[x["t"] // 86_400_000 for x in trs], g=[x["gross"] for x in trs])).groupby("d")["g"].mean()
    return float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))) if len(s) > 2 and s.std(ddof=1) > 0 else 0.0

def intra_data(symbols, years):
    n = int(min(max(float(years), 0.5), 3.0) * 365 * 24) + 200
    out, errors = {}, {}
    for sym in dict.fromkeys(symbols):
        try:
            rows, _ = v10_futures_history(sym, "1h", n)
            out[sym] = _rows_to_df(rows, "1h", n)
        except Exception as ex: errors[sym] = f"{type(ex).__name__}: {str(ex)[:90]}"
    return out, errors

def intra_report(data, errors=None, years=2.0, params=None):
    p = dict(INTRA_DEFAULTS); p.update(params or {}); errors = errors or {}
    feats = {s: _intra_feats(d, p) for s, d in data.items() if len(d) > p["vol_span"] + 100}
    L = [f"⏱️ Intraday Lab · زخم/انعكاس حسب ساعة UTC (شموع 1h) · {len(feats)} عملة · {BOT_VERSION}",
         f"الإشارة: حركة الساعة المغلقة |z|>{p['zmin']:g}σ → دخول عند افتتاح الساعة التالية → خروج بعد {'/'.join(map(str, p['holds']))} ساعات أو وقف {p['stop_atr']}×ATR.",
         f"اختيار الساعات على TRAIN فقط (|t|≥{p['tmin']:g} على متوسطات يومية عبر العملات)، وTEST لا يُلمس. تقسيم زمني {int(p['train_ratio']*100)}/{100-int(p['train_ratio']*100)}.",
         f"💸 cfg: {2*(FEE+SLIP)*1e4:.0f}bp | واقعي: {2*(REAL_FEE+REAL_SLIP)*1e4:.0f}bp | ميكر دخول فقط: {(MAKER_FEE+REAL_FEE+REAL_SLIP)*1e4:.0f}bp (+تمويل تقديري). "
         f"الميكر يتطلب كسر السعر {p['maker_through_atr']:g}×ATR لتنفيذ أمر الحد؛ غير المنفَّذ يُحذف."]
    if not feats: return "\n".join(L + ["", "⚠️ بيانات غير كافية."])
    a = min(int(f["t"][p["vol_span"]]) for f in feats.values()); b = max(int(f["t"][-1]) for f in feats.values())
    cut = a + p["train_ratio"] * (b - a)
    verdicts = []
    for hold in p["holds"]:
        dirs, tab = intra_hour_select(feats, hold, cut, p)
        L += ["", f"━━ احتفاظ {hold} ساعة ━━"]
        best = sorted(tab.items(), key=lambda kv: -abs(kv[1]["t"]))[:3]
        L.append("أقوى 3 ساعات في TRAIN: " + " | ".join(f"{h:02d}h t={v['t']:+.1f}" for h, v in best))
        # baselines: no hour selection at all
        base = {}
        for nm, dv in (("زخم", 1), ("انعكاس", -1)):
            tt = [x for s, f in feats.items() for x in intra_trades(s, f, hold, {h: dv for h in range(24)}, cut, b + 1, p)]
            base[nm] = (1e4 * float(np.mean([x["gross"] for x in tt])) if tt else 0.0, len(tt))
        L.append(f"مرجع TEST بلا اختيار ساعات (قبل التكلفة): زخم {base['زخم'][0]:+.1f}bp · انعكاس {base['انعكاس'][0]:+.1f}bp (n≈{base['زخم'][1]})")
        if not dirs:
            L.append("⚪ لا ساعة تجتاز العتبة في TRAIN → لا استراتيجية لهذا الاحتفاظ."); verdicts.append("لا ساعات"); continue
        L.append("ساعات مختارة: " + " ".join(f"{h:02d}h{'↑زخم' if d > 0 else '↓انعكاس'}" for h, d in sorted(dirs.items())))
        tr_t = [x for s, f in feats.items() for x in intra_trades(s, f, hold, dirs, a, cut, p) if x["t"] + hold * _HMS <= cut]
        te_t = [x for s, f in feats.items() for x in intra_trades(s, f, hold, dirs, cut, b + 1, p)]
        if not te_t: L.append("⚪ لا صفقات TEST."); verdicts.append("لا صفقات"); continue
        gb = 1e4 * float(np.mean([x["gross"] for x in te_t])); gtr = 1e4 * float(np.mean([x["gross"] for x in tr_t])) if tr_t else 0.0
        te_s = sorted(te_t, key=lambda x: x["t"]); h2 = len(te_s) // 2
        g1 = 1e4 * float(np.mean([x["gross"] for x in te_s[:h2]])) if h2 else 0.0; g2 = 1e4 * float(np.mean([x["gross"] for x in te_s[h2:]]))
        L.append(f"قبل التكلفة: TRAIN {gtr:+.1f}bp (داخل العينة) | TEST {gb:+.1f}bp (t يومي {_intra_day_t(te_t):+.1f}, n={len(te_t)}) | نصفا TEST: {g1:+.1f} / {g2:+.1f}bp")
        for model, nm in (("cfg", "رسوم الإعداد"), ("real", "تكلفة واقعية"), ("maker", "ميكر")):
            m_te = metrics(_intra_pack(te_t, model));
            extra = f" · تنفيذ {100*np.mean([x['filled'] for x in te_t]):.0f}%" if model == "maker" else ""
            L.append(f"{nm}: n={m_te['n']} · WR {m_te['wr']}% · PF {m_te['pf']} · متوسط {m_te['avg']:+}R · مجموع {m_te['total']:+}R{extra}")
        if sum(not x["filled"] for x in te_t):
            miss = [x["gross"] for x in te_t if not x["filled"]]
            L.append(f"🪤 الصفقات غير المنفَّذة (ميكر) كان متوسطها {1e4*np.mean(miss):+.1f}bp — الفرق مع المنفَّذة = انتقاء عكسي.")
        v = bt_verdict(metrics(_intra_pack(tr_t, "real")), metrics(_intra_pack(te_t, "real"))); L.append(f"الحكم (تكلفة واقعية): {v}"); verdicts.append(v)
    L += ["", "⚠️ اختُبرت 3 فترات احتفاظ × 24 ساعة: أي ✅ منفرد يضعف إحصائيًا — أعد الاختبار على فترة/عملات أخرى قبل أي اعتماد.",
          "ℹ️ الصفقات بين العملات مترابطة؛ لذلك t محسوب على متوسطات يومية."]
    if errors: L += ["", f"⚠️ فشل {len(errors)} عملة: " + " | ".join(f"{k}: {v[:50]}" for k, v in list(errors.items())[:3])]
    return "\n".join(L)

def backtest_many(symbols, years=1.0, max_workers=1):
    """Run backtest_symbol over a list of symbols; every failure is recorded per symbol, never swallowed."""
    per,tmin,tmax,errors={},None,None,{}
    symbols=list(dict.fromkeys(s.strip().upper() for s in (symbols or []) if isinstance(s,str) and s.strip()))
    if not symbols: return per,tmin,tmax,errors
    def _one(sym):
        try:
            trs,a,b=backtest_symbol(sym,years)
            return sym,(trs,int(a),int(b)),None
        except Exception as ex:
            log.warning("backtest_symbol failed for %s: %s",sym,str(ex)[:160])
            return sym,None,f"{type(ex).__name__}: {ex}"
    workers=max(1,min(int(max_workers or 1),2,len(symbols)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for sym,result,error in pool.map(_one,symbols):
            if error: errors[sym]=error; continue
            trs,a,b=result; per[sym]=trs
            tmin=a if tmin is None else min(tmin,a); tmax=b if tmax is None else max(tmax,b)
    return per,tmin,tmax,errors


def backtest_symbol_days(sym,days=60,params=None):
    """Replay the live MTF engine over the most recent 30/60 days."""
    d4,h1,m15,summary=_bt_frames_days(sym,days)
    trades,a,b=v10_replay(sym,d4,h1,m15,params=params)
    for tr in trades:
        tr["data_source"]=summary
        tr["test_window_days"]=int(days)
    if not a: raise NoData(f"{sym}: تاريخ غير كافٍ للتشغيل")
    return trades,a,b


def backtest_many_days(symbols,days=60,max_workers=1):
    """Run recent-window tests and preserve per-symbol loading errors."""
    per,tmin,tmax,errors={},None,None,{}
    symbols=list(dict.fromkeys(s.strip().upper() for s in (symbols or []) if isinstance(s,str) and s.strip()))
    if not symbols: return per,tmin,tmax,errors
    def _one(sym):
        try:
            trs,a,b=backtest_symbol_days(sym,days)
            return sym,(trs,int(a),int(b)),None
        except Exception as ex:
            log.warning("recent backtest failed for %s: %s",sym,str(ex)[:160])
            return sym,None,f"{type(ex).__name__}: {ex}"
    workers=max(1,min(int(max_workers or 1),2,len(symbols)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for sym,result,error in pool.map(_one,symbols):
            if error: errors[sym]=error; continue
            trs,a,b=result; per[sym]=trs
            tmin=a if tmin is None else min(tmin,a); tmax=b if tmax is None else max(tmax,b)
    return per,tmin,tmax,errors


def bt_verdict(mt,me):
    """Verdict needs a big enough TEST sample, positive expectancy AFTER costs and a TRAIN period that does not contradict it."""
    if me["n"]<30: return "⚪ عينة TEST صغيرة (أقل من 30 صفقة) — لا حكم"
    if me["avg"]<=0 or me["pf"]<1.1: return "🔴 ضعيف: لا ربح بعد الرسوم"
    if mt["n"]<30 or mt["pf"]<=1.0: return "🟡 ربح في TEST لكن TRAIN لا يدعمه — غير مستقر"
    if me["pf"]<1.5: return "🟡 مقبول"
    return "✅ جيد" if me["pf"]<1.8 else "🏆 ممتاز (أعد الاختبار على فترة/عملات أخرى قبل الاعتماد)"


def bt_report(per,tmin,tmax,label,errors=None):
    errors=errors or {}
    _window_match=re.search(r"(\\d+)D",str(label).upper())
    _window_days=_window_match.group(1) if _window_match else "غير محددة"
    allt=[x for tr in (per or {}).values() if isinstance(tr,list) for x in tr
          if isinstance(x,dict) and isinstance(x.get("t"),(int,float)) and isinstance(x.get("R"),(int,float))]
    lines=[f"📊 Backtest v10 · {label} ({len(per or {})} عملة صالحة) · {BOT_VERSION}",
           f"📥 عملات فشل تحميلها/اختبارها: {len(errors)}",
           "🧠 المحرك المُختبَر = نفس محرك الإشارات الحية: 4H نظام + 1H تأكيد + 15M محفز (فرص مؤكدة فقط).",
           "🕯️ القرار عند إغلاق شمعة 15M، الدخول عند افتتاح التالية، والإدارة بنفس trade_step الحي (TP جزئي، BE بعد TP1، Trailing بعد TP2، حد أقصى 48 ساعة).",
           f"⚙️ المعاملات: {v10_params()}",
           f"💸 الرسوم {FEE*100:.2f}% + انزلاق {SLIP*100:.2f}% لكل جهة + تمويل تقديري {FUNDING_8H*100:.3f}%/8س. التمويل التاريخي الفعلي غير مضمّن.",
           f"🧪 نافذة حديثة: {_window_days} يوم؛ تقسيم زمني لكل عملة بنسبة 2/3 TRAIN و1/3 TEST. القواعد ثابتة غير مضبوطة على البيانات."]
    if str(label).upper().startswith("TOP"):
        lines.append("⚠️ قائمة TOP مبنية على سيولة اليوم؛ فيها انحياز بقاء (survivorship).")
    if not allt:
        lines += ["","⚠️ لم تنتج الفترة أي فرصة مؤكدة للاختبار — لا يمكن الحكم، ولا أرقام وهمية."]
    else:
        tr,te=split_trades_by_symbol(allt,tmin,tmax,2.0/3.0)
        mt,me=metrics(tr),metrics(te)
        def _bt_dates(rows):
            ts=[int(x.get("t",0)) for x in rows if isinstance(x.get("t"),(int,float)) and int(x.get("t",0))>0]
            if not ts: return "—"
            a=dt.datetime.fromtimestamp(min(ts)/1000,dt.timezone.utc).strftime("%Y-%m-%d")
            b=dt.datetime.fromtimestamp(max(ts)/1000,dt.timezone.utc).strftime("%Y-%m-%d")
            return f"{a} → {b} UTC"
        def _bt_sides(rows):
            buy=sum(1 for x in rows if int(x.get("side",0))==1)
            sell=sum(1 for x in rows if int(x.get("side",0))==-1)
            return f"BUY {buy} | SELL {sell}"
        lines += ["",f"📈 TRAIN: n={mt['n']} | WR {mt['wr']}% | PF {mt['pf']} | {mt['total']:+}R | متوسط {mt['avg']:+}R",
                  f"📊 TEST : n={me['n']} | WR {me['wr']}% | PF {me['pf']} | {me['total']:+}R | متوسط {me['avg']:+}R",
                  f"🗓️ فترة TRAIN: {_bt_dates(tr)} | {_bt_sides(tr)}",
                  f"🗓️ فترة TEST: {_bt_dates(te)} | {_bt_sides(te)}",
                  f"🎯 وصول TP1 في TEST: {me['tp1']}% | أقصى تراجع TEST: {me['dd']}R"]
        if te:
            gross=float(np.mean([x["gross_R"] for x in te])); cost=float(np.mean([x["cost"] for x in te]))
            mr=metrics(_real_cost_trades(te))
            lines += [f"🧮 تشخيص التكلفة (TEST): قبل التكلفة {gross:+.3f}R | التكلفة المخصومة {cost:.3f}R | الصافي {me['avg']:+.3f}R",
                      f"🧮 بتكلفة واقعية (رسوم {REAL_FEE*100:.2f}% + انزلاق {REAL_SLIP*100:.2f}% لكل جهة): متوسط {mr['avg']:+}R | PF {mr['pf']}"]
        lines += [""]
        for g in ("A","B"):
            sub=[x for x in te if x.get("grade")==g]
            if sub:
                m=metrics(sub); lines.append(f"درجة {g}: n={m['n']} · WR {m['wr']}% · PF {m['pf']} · {m['total']:+}R")
        for side,name in ((1,"BUY"),(-1,"SELL")):
            sub=[x for x in te if int(x.get("side",0))==side]
            if sub:
                m=metrics(sub); lines.append(f"{name}: n={m['n']} · WR {m['wr']}% · PF {m['pf']} · {m['total']:+}R")
        for kind,name in (("SL","ضرب SL"),("BE","BE بعد TP1"),("TRAIL","Trailing بعد TP2"),("TP","إكمال الأهداف"),("TIME","خروج زمني")):
            sub=[x for x in te if x.get("exit")==kind]
            if sub: lines.append(f"{name}: {len(sub)} صفقة · {sum(float(x['R']) for x in sub):+.1f}R")
        bysym=sorted(((c,metrics([x for x in te if x.get('sym')==c])) for c in {x.get("sym") for x in te}),key=lambda z:z[1]["total"])
        if bysym:
            lines.append("أسوأ: "+" | ".join(f"{c} {m['total']:+.1f}R (n={m['n']})" for c,m in bysym[:4]))
            lines.append("أفضل: "+" | ".join(f"{c} {m['total']:+.1f}R (n={m['n']})" for c,m in bysym[::-1][:4]))
        lines += ["",f"الحكم: {bt_verdict(mt,me)}"]
    if errors:
        lines += ["","⚠️ أسباب الفشل:"]+[f"• {s}: {str(e)[:110]}" for s,e in list(errors.items())[:5]]
    return "\n".join(lines),""

def admin_only(fn):
    @functools.wraps(fn)
    async def wrapper(update,ctx):
        if not ADMIN_ID or ADMIN_ID == 0 or not update.effective_user or update.effective_user.id!=ADMIN_ID:
            lang=get_user_lang(update.effective_user.id) if update.effective_user else "ar"
            await update.message.reply_text(t("admin_only",lang)); return
        try: return await fn(update,ctx)
        except Exception as e:
            log.exception("admin"); await update.message.reply_text(f"⚠️ {str(e)[:200]}")
    return wrapper

def vip_only(fn):
    @functools.wraps(fn)
    async def wrapper(update,ctx):
        u=update.effective_user
        if not u: return
        lang=get_user_lang(u.id)
        rec=store.data["users"].get(str(u.id),{})
        st,_=user_status(u.id,rec)
        if st not in ("admin","vip","trial","warning"):
            kb=InlineKeyboardMarkup([[_btn("💎 اشترك في VIP" if lang=="ar" else "💎 Subscribe to VIP",url=VIP_INVITE_LINK)]])
            await update.message.reply_text(t("vip_only",lang),reply_markup=kb); return
        try: return await fn(update,ctx)
        except Exception as e:
            log.exception("vip"); await update.message.reply_text(f"⚠️ {str(e)[:200]}")
    return wrapper

_cb_last={}
def cb_throttled(uid,secs=5):
    now=time.time()
    if now-_cb_last.get(uid,0)<secs: return True
    _cb_last[uid]=now; return False

def clean_symbol(text):
    s=(text or "").upper().strip().replace("$","").replace("/","").replace("-","")
    for suf in ("USDT","USDC","PERP","USD"):
        if s.endswith(suf) and len(s)>len(suf): s=s[:-len(suf)]
    return s if re.fullmatch(r"[A-Z0-9]{1,12}",s) else ""

_cooldown={}

async def gate(update):
    user=update.effective_user
    lang=get_user_lang(user.id)
    if is_maintenance() and user.id!=ADMIN_ID:
        await update.message.reply_text(t("maintenance",lang,contact=(CONTACT_LINK or CHANNEL_LINK))); return "maintenance",False
    rec=touch_user(user); st,day=user_status(user.id,rec)
    if st=="blocked":
        await update.message.reply_text(t("blocked",lang,contact=(CONTACT_LINK or CHANNEL_LINK))); return st,False
    if st=="warning":
        left=VIP_FORCE_DAY-day
        await update.message.reply_text(t("warning_trial",lang,left=left))
    if st not in ("admin", "grace"):
        if time.time()-_cooldown.get(user.id,0)<3:
            await update.message.reply_text(t("wait_3s",lang)); return st,False
        _cooldown[user.id]=time.time()
    return st,True

async def cmd_start(update,ctx):
    if is_maintenance() and update.effective_user.id!=ADMIN_ID:
        lang=get_user_lang(update.effective_user.id)
        await update.message.reply_text(t("maintenance",lang,contact=(CONTACT_LINK or CHANNEL_LINK))); return
    u=update.effective_user; uid=str(u.id); lang=get_user_lang(u.id)
    if ctx.args and len(ctx.args)>0 and ctx.args[0].startswith("ref_"):
        try:
            referrer_id=int(ctx.args[0][4:])
            if referrer_id!=u.id:
                is_new=uid not in store.data["users"]
                if is_new:
                    awarded=False
                    with store.lock:
                        ref_uid=str(referrer_id)
                        if ref_uid in store.data["users"]:
                            store.data["users"][ref_uid]["points"]=store.data["users"][ref_uid].get("points",0)+POINTS_REFERRAL
                            store.save("users"); awarded=True
                    if awarded:
                        new_pts,reward=check_points_reward(referrer_id)
                        try:
                            ref_lang=get_user_lang(referrer_id)
                            if ref_lang=="en":
                                msg=f"🎉 Someone joined via your link!\n💰 +{POINTS_REFERRAL} points\n📊 Balance: {new_pts}/{VIP_THRESHOLD}"
                                if reward: msg+=f"\n\n🎁 <b>Congrats!</b> Reached {VIP_THRESHOLD} → VIP {reward} day free!"
                            else:
                                msg=f"🎉 شخص جديد انضم عبر رابطك!\n💰 +{POINTS_REFERRAL} نقطة\n📊 رصيدك: {new_pts}/{VIP_THRESHOLD}"
                                if reward: msg+=f"\n\n🎁 <b>مبروك!</b> وصلت {VIP_THRESHOLD} → VIP {reward} يوم مجاناً!"
                            await ctx.bot.send_message(referrer_id,msg,parse_mode=ParseMode.HTML)
                        except Exception as _ex: log.debug('ignored: %s', _ex)
        except Exception as _ex: log.debug('ignored: %s', _ex)
    rec=touch_user(u,"/start"); st,day=user_status(u.id,rec)
    reward_pts,reward_days=check_points_reward(u.id)
    if reward_days:
        try:
            if lang=="en": reward_msg=f"🎉 <b>Congrats!</b> Reached {VIP_THRESHOLD} points\n✅ You got <b>VIP {reward_days} day free</b>!"
            else: reward_msg=f"🎉 <b>مبروك!</b> وصلت {VIP_THRESHOLD} نقطة\n✅ حصلت على <b>VIP {reward_days} يوم مجاناً</b>!"
            await update.message.reply_text(reward_msg,parse_mode=ParseMode.HTML)
        except Exception as _ex: log.debug('ignored: %s', _ex)
        rec["points"]=reward_pts
    bot_username=ctx.application.bot_data.get("username","")
    ref_link=f"https://t.me/{bot_username}?start=ref_{u.id}" if bot_username else None
    if lang=="en":
        rows=[[_btn("📊 My Portfolio",callback_data="my_portfolio")]]
        if ref_link: rows.append([_btn("🔗 Referral Link",copy_text=CopyTextButton(text=ref_link))])
        rows+=[ [_btn("💎 Subscribe to VIP ✨",url=VIP_INVITE_LINK)],
            [_btn("🆓 Signals Channel",url=CHANNEL_LINK)],
            [_btn("📞 Contact",url=CONTACT_URL)]]
        ref_text=f"\n\n🔗 Your link:\n<code>{ref_link}</code>" if ref_link else ""
        welcome=(f"Welcome {u.first_name}! 👋\n\nSend any coin symbol to analyze.\n\n"
            f"{points_visual(rec.get('points',0))}\n\n📌 <b>Ways to earn points:</b>\n"
            f"• Daily login = <b>{POINTS_DAILY}</b>\n• Share channel/bot link = <b>{POINTS_PROMO} points</b>\n"
            f"• Invite new subscriber = <b>{POINTS_REFERRAL} points</b>\n\n"
            f"🎁 {VIP_THRESHOLD} points = VIP {VIP_REWARD_DAYS} day free{ref_text}")
    else:
        rows=[[_btn("📊 محفظتي",callback_data="my_portfolio")]]
        if ref_link: rows.append([_btn("🔗 رابط الإحالة",copy_text=CopyTextButton(text=ref_link))])
        rows+=[ [_btn("💎 اشترك في VIP ✨",url=VIP_INVITE_LINK)],
            [_btn("🆓 قناة التوصيات",url=CHANNEL_LINK)],
            [_btn("📞 تواصل",url=CONTACT_URL)]]
        ref_text=f"\n\n🔗 رابطك:\n<code>{ref_link}</code>" if ref_link else ""
        welcome=(f"أهلاً {u.first_name}! 👋\n\nأرسل اسم أي عملة لتحليلها.\n\n"
            f"{points_visual(rec.get('points',0))}\n\n📌 <b>طرق جمع النقاط:</b>\n"
            f"• دخول يومي = <b>{POINTS_DAILY}</b>\n• نشر رابط القناة أو البوت = <b>{POINTS_PROMO} نقاط</b>\n"
            f"• دعوة مشترك جديد = <b>{POINTS_REFERRAL} نقطة</b>\n\n"
            f"🎁 {VIP_THRESHOLD} نقطة = VIP {VIP_REWARD_DAYS} يوم مجاناً{ref_text}")
    await update.message.reply_text(welcome,reply_markup=InlineKeyboardMarkup(rows),
                                    parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)

async def cmd_help(update,ctx):
    touch_user(update.effective_user,"/help")
    u=update.effective_user; lang=get_user_lang(u.id)
    rec=store.data["users"].get(str(u.id),{})
    st,_=user_status(u.id,rec)
    if st in ("admin","vip"):
        await update.message.reply_text(
            "ℹ️ <b>مساعدة VIP</b>\n\n📝 إرسال رمز عملة → تحليل + 4 أهداف\n"
            "📋 /menu — قائمة VIP\n💎✨ /golden — الفرصة الذهبية\n"
            "🎯 /daily — صفقة اليوم\n📊 /futures BTC — الفيوتشر\n"
            "📈 /portfolio — محفظتي\n🎯 /points — نقاطي\n🔗 /myref — رابط الإحالة"
            if lang=="ar" else
            "ℹ️ <b>VIP Help</b>\n\n📝 Send coin symbol → analysis + 4 targets\n"
            "📋 /menu — VIP menu\n💎✨ /golden — Golden Setup\n"
            "🎯 /daily — Daily trade\n📊 /futures BTC — Futures data\n"
            "📈 /portfolio — My portfolio\n🎯 /points — My points\n🔗 /myref — Referral link",
            parse_mode=ParseMode.HTML); return
    await update.message.reply_text(
        "ℹ️ مساعدة Ryma Crypto\n\n📝 إرسال رمز عملة للتحليل\n🆔 /myid\n💎 /vip\n📈 /portfolio\n🎯 /points\n🔗 /myref"
        if lang=="ar" else
        "ℹ️ Ryma Crypto Help\n\n📝 Send coin symbol to analyze\n🆔 /myid\n💎 /vip\n📈 /portfolio\n🎯 /points\n🔗 /myref")

async def cmd_myid(update,ctx):
    touch_user(update.effective_user,"/myid")
    await update.message.reply_text(f"🆔 رقم الحساب: {update.effective_user.id}")

async def cmd_vip(update,ctx):
    u=update.effective_user; touch_user(u,"/vip")
    kb=InlineKeyboardMarkup([
        [_btn("💎 اشترك الآن ✨",url=VIP_INVITE_LINK)],
        [_btn("🆓 قناة التوصيات المجانية",url=CHANNEL_LINK)],
        [_btn("📞 تواصل معنا",url=CONTACT_URL)]])
    await update.message.reply_text(build_vip_page(),reply_markup=kb)

async def cmd_menu(update,ctx):
    touch_user(update.effective_user,"/menu")
    u=update.effective_user; rec=store.data["users"].get(str(u.id),{})
    st,_=user_status(u.id,rec)
    if st=="admin":
        await update.message.reply_text(build_admin_menu_text(),reply_markup=keyboard_admin_menu(),parse_mode=ParseMode.HTML); return
    if st not in ("vip","trial","warning"):
        kb=InlineKeyboardMarkup([[_btn("💎 اشترك في VIP",url=VIP_INVITE_LINK)]])
        await update.message.reply_text("🔒 القائمة لمشتركي VIP فقط",reply_markup=kb); return
    await update.message.reply_text(build_vip_menu_text(),reply_markup=keyboard_vip_menu())

async def cmd_daily(update,ctx):
    u=update.effective_user
    if not u: return
    rec=store.data["users"].get(str(u.id),{}); st,_=user_status(u.id,rec)
    if st not in ("admin","vip","trial","warning"):
        kb=InlineKeyboardMarkup([[_btn("💎 اشترك في VIP",url=VIP_INVITE_LINK)]])
        await update.message.reply_text("🔒 الأمر حصري للمشتركين",reply_markup=kb); return
    touch_user(u,"/daily")
    wait=await update.message.reply_text("🎯 جلب Top Movers...")
    try:
        longs,shorts=await asyncio.to_thread(_build_daily_lists)
        if not longs and not shorts:
            await wait.edit_text("🎯 لا توجد صفقات مطابقة حالياً بمعايير العقل المركزي."); return
        await wait.delete()
        for idx,item in enumerate(longs,1):
            txt=_format_daily_card(item["res"],f"🟢 LONG {idx}",item.get("change",0),item.get("volume",0))
            await update.message.reply_text(txt,parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
            await asyncio.sleep(0.7)
        for idx,item in enumerate(shorts,1):
            txt=_format_daily_card(item["res"],f"🔴 SHORT {idx}",item.get("change",0),item.get("volume",0))
            await update.message.reply_text(txt,parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
            await asyncio.sleep(0.7)
        await update.message.reply_text(f"📊 النتيجة: {len(longs)} LONG + {len(shorts)} SHORT\n\n"
            f"💡 الصفقات جاهزة للنشر يدوياً\n\n{RISK_WARNING_AR}",parse_mode=ParseMode.HTML)
    except Exception as e:
        log.exception("daily"); await wait.edit_text(f"⚠️ {str(e)[:200]}")

async def cmd_portfolio(update,ctx):
    u=update.effective_user; uid=str(u.id); touch_user(u,"/portfolio")
    port=store.data["portfolios"].get(uid,[])
    if not port:
        await update.message.reply_text("محفظتك فارغة. استخدم زر (إضافة للمحفظة) في أي تحليل."); return
    msg="📊 <b>محفظتك الاستثمارية:</b>\n\n"; total_pnl=0
    for item in port:
        p,_=live_price(item["sym"])
        if p:
            pnl=(p-item["entry"])*(item["amount"]/item["entry"]); total_pnl+=pnl
            emoji="🟢" if pnl>=0 else "🔴"
            msg+=f"{emoji} <b>#{item['sym']}</b> | دخل: {fmt(item['entry'])} | حالي: {fmt(p)}\n"
            msg+=f"   استثمرت: ${item['amount']} | الربح: {pnl:+.2f}$\n\n"
    msg+=f"━━━━━━━━━━━━━━━\nإجمالي الأرباح/الخسائر: <b>{total_pnl:+.2f}$</b>"
    await update.message.reply_text(msg,parse_mode=ParseMode.HTML)

async def cmd_myref(update,ctx):
    u=update.effective_user
    bot_username=ctx.application.bot_data.get("username","")
    if not bot_username:
        await update.message.reply_text("⚠️ غير متاح حالياً، جرب بعد دقيقة"); return
    ref_link=f"https://t.me/{bot_username}?start=ref_{u.id}"
    rec=store.data["users"].get(str(u.id),{}); pts=rec.get("points",0)
    await update.message.reply_text(
        f"🔗 <b>رابط الإحالة الخاص بك:</b>\n\n<code>{ref_link}</code>\n\n"
        f"💰 كل مشترك جديد = <b>{POINTS_REFERRAL} نقطة</b>\n\n"
        f"🎯 نقاطك: <b>{pts}/{VIP_THRESHOLD}</b>\n{points_visual(pts)}",
        parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)

async def cmd_points(update,ctx):
    u=update.effective_user; rec=store.data["users"].get(str(u.id),{}); pts=rec.get("points",0)
    bot_username=ctx.application.bot_data.get("username","")
    ref_link=f"https://t.me/{bot_username}?start=ref_{u.id}" if bot_username else "—"
    await update.message.reply_text(
        f"🎯 <b>نقاطك:</b> {pts}/{VIP_THRESHOLD}\n\n{points_visual(pts)}\n\n"
        f"📌 <b>طرق جمع النقاط:</b>\n• دخول يومي = <b>{POINTS_DAILY}</b>\n"
        f"• نشر رابط القناة أو البوت = <b>{POINTS_PROMO} نقاط</b>\n"
        f"• دعوة مشترك جديد = <b>{POINTS_REFERRAL} نقطة</b>\n\n"
        f"🔗 <b>رابط البوت (إحالتك):</b>\n<code>{ref_link}</code>\n\n"
        f"📢 <b>قناة التوصيات:</b>\n<code>{CHANNEL_LINK}</code>\n\n"
        f"🎁 عند {VIP_THRESHOLD} نقطة = <b>VIP {VIP_REWARD_DAYS} يوم مجاناً</b>",
        parse_mode=ParseMode.HTML)

@admin_only
async def cmd_addpoints(update,ctx):
    if len(ctx.args)<2:
        await update.message.reply_text(
            "📝 <b>الصيغة:</b>\n/addpoints ID POINTS [reason]\n\n"
            f"مثال: <code>/addpoints 123456789 {POINTS_PROMO} ترويج</code>",parse_mode=ParseMode.HTML); return
    try:
        target_uid=int(ctx.args[0]); pts=int(ctx.args[1])
        reason=" ".join(ctx.args[2:]) if len(ctx.args)>2 else "مكافأة"
        with store.lock:
            exists=str(target_uid) in store.data["users"]
            if exists:
                store.data["users"][str(target_uid)]["points"]=store.data["users"][str(target_uid)].get("points",0)+pts
                store.save("users"); new_pts=store.data["users"][str(target_uid)]["points"]
        if not exists:
            await update.message.reply_text("❌ المستخدم غير موجود"); return
        await update.message.reply_text(
            f"✅ +{pts} نقطة → <code>{target_uid}</code>\n📝 السبب: {reason}\n📊 رصيده: {new_pts}/{VIP_THRESHOLD}",
            parse_mode=ParseMode.HTML)
        final_pts,reward=check_points_reward(target_uid)
        try:
            msg=f"🎁 حصلت على <b>+{pts} نقطة</b> ({reason})\n📊 رصيدك: {new_pts}/{VIP_THRESHOLD}"
            if reward: msg+=f"\n\n🎉 <b>مبروك!</b> {VIP_THRESHOLD} نقطة → VIP {reward} يوم مجاناً!"
            await ctx.bot.send_message(target_uid,msg,parse_mode=ParseMode.HTML)
        except Exception as _ex: log.debug('ignored: %s', _ex)
    except ValueError: await update.message.reply_text("⚠️ صيغة خاطئة")

@admin_only
async def cmd_cross(update,ctx):
    """Legacy /cross shortcut now runs the canonical AI market scan."""
    wait=await update.message.reply_text("🤖 جارٍ فحص فرص AI...")
    try:
        syms=await asyncio.to_thread(top_symbols,20)
        rows=await asyncio.to_thread(scan_sync,syms[:20],3)
        rows.sort(key=lambda r:({"A+":4,"A":3,"B":2,"C":1}.get(r.get("grade"),0),float(r.get("score",0))),reverse=True)
        if not rows:
            await wait.edit_text("⚠️ لم تتوفر نتائج AI. تحقق من مفتاح المزود والبيانات."); return
        lines=["🤖 <b>مسح فرص السوق بواسطة AI</b>","━━━━━━━━━━━━━━━━",""]
        for r in rows[:12]:
            side="🟢 شراء" if r["side"]==1 else "🔴 بيع"
            lines.append(f"{side} <b>#{r['sym']}</b> · درجة {r['grade']} · {fmt(r['price'])}")
            lines.append(f"  دخول {fmt(r['lv']['entry'])} | وقف {fmt(r['lv']['sl'])} | هدف1 {fmt(r['lv']['tps'][0]['px'])}")
        await wait.edit_text("\n".join(lines)[:3900],parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
    except Exception as ex:
        log.exception("AI scan command")
        await wait.edit_text(f"⚠️ تعذر مسح AI: {str(ex)[:180]}")

@vip_only
async def cmd_active(update,ctx):
    act=active_signals()
    if not act: await update.message.reply_text("📊 لا توجد صفقات نشطة"); return
    act.sort(key=lambda p:-p.get("created",0))
    lines=[f"📊 الصفقات النشطة ({len(act)}/{MAX_OPEN})",""]
    for p in act[:20]:
        side_icon="🟢" if p["side"]==1 else "🔴"
        decision="🟢 شراء" if p["side"]==1 else "🔴 بيع"
        cur_r=p.get("realized",0.0); tp_hits=sum(1 for t in p["tps"] if t["hit"])
        lines+=[f"{side_icon} #{p['coin']}/{p['tf']} R:{cur_r:+.2f} TP:{tp_hits}/4",f"   🎯 القرار المتوقع: {decision}"]
    await update.message.reply_text("\n".join(lines)[:4000],link_preview_options=NO_PREVIEW)

@vip_only
async def cmd_predict(update,ctx):
    wait=await update.message.reply_text("🔮 جارٍ الفحص...")
    try:
        syms=await asyncio.to_thread(top_symbols,40)
        preds=await asyncio.to_thread(predictive_scan,syms[:30])
        if not preds: await wait.edit_text("🔮 لا توجد عملات"); return
        lines=["🔮 رادار التنبؤ (إعدادات قيد التكوّن — بانتظار محفز 15M):",""]
        for p in preds[:7]:
            icon="🟢" if p["direction"]=="LONG" else "🔴"
            decision="🟢 شراء" if p["direction"]=="LONG" else "🔴 بيع"
            lines.append(f"{icon} #{p['sym']} — {p['score']}/9")
            for r in p["reasons"][:3]: lines.append(f"   ✅ {r}")
            lines+=[f"   🎯 القرار المتوقع: {decision}",""]
        await wait.edit_text("\n".join(lines),link_preview_options=NO_PREVIEW)
    except Exception as e: await wait.edit_text(f"⚠️ {str(e)[:150]}")

@vip_only
async def cmd_whales(update,ctx):
    wait=await update.message.reply_text("🐋 فحص الصفقات الكبيرة...")
    syms=await asyncio.to_thread(top_symbols,30); rows=[]
    for s in syms[:15]:
        w,largest,bv,sv=await asyncio.to_thread(whale_radar,s)
        if w and w>=1: rows.append((s,w,largest,bv,sv))
    lines=[]
    if rows:
        rows.sort(key=lambda x:-x[2])
        lines+=["🐋 <b>رادار الصفقات الكبيرة (فوق 5 آلاف دولار)</b>","━━━━━━━━━━━━━━━━",""]
        for s,w,largest,bv,sv in rows[:10]:
            total=bv+sv; buy_pct=(bv/total*100) if total>0 else 0
            direction="🟢 شراء" if buy_pct>55 else ("🔴 بيع" if buy_pct<45 else "⚖️ متذبذب")
            lines+=[f"🐋 <b>#{s}</b>",f"   🔢 {w} صفقة كبيرة",f"   💰 أكبر صفقة: <b>${largest:,.0f}</b>",
                    f"   📊 الاتجاه: <b>{direction}</b> ({buy_pct:.0f}%)",f"   🎯 القرار المتوقع: {direction}",""]
    else:
        fallback_syms=await asyncio.to_thread(top_symbols,5)
        lines+=["🐋 <b>لا توجد صفقات كبيرة حالياً على Binance</b>","👇 إليك أنشط العملات للمراقبة:",""]
        for s in fallback_syms: lines.append(f"• #{s} — 🎯 القرار المتوقع: مراقبة")
    if ETHERSCAN_KEY and ETH_WATCH:
        eth_flows=await asyncio.to_thread(eth_exchange_flows,1)
        if eth_flows: lines+=["","🔷 <b>تدفقات ETH من عناوين البورصات (آخر ساعة):</b>"]+eth_flows
    if WHALE_ALERT_KEY:
        onchain=await asyncio.to_thread(whale_alert_recent,1_000_000)
        if onchain: lines+=["","🌍 <b>تحويلات on-chain كبيرة (آخر 60 دقيقة):</b>"]+onchain[:6]
    await wait.edit_text("\n".join(lines)[:4000],parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)

@vip_only
async def cmd_liquidity(update,ctx):
    if not ctx.args: await update.message.reply_text("مثال: /liquidity BTC"); return
    sym=clean_symbol(ctx.args[0]); wait=await update.message.reply_text(f"💧 تحليل {sym}...")
    liq=await asyncio.to_thread(liquidity_radar,sym)
    if not liq: await wait.edit_text("💧 لا توجد بيانات"); return
    bias="🟢 ضغط شراء" if liq["ratio"]>0.55 else ("🔴 ضغط بيع" if liq["ratio"]<0.45 else "⚖️")
    decision="🟢 شراء" if liq["ratio"]>0.55 else ("🔴 بيع" if liq["ratio"]<0.45 else "⚖️ حياد")
    await wait.edit_text(f"💧 {sym}\n🟢 ${liq['bids']:,.0f}\n🔴 ${liq['asks']:,.0f}\n"
        f"📊 {liq['ratio']*100:.1f}% | {bias}\n\n🎯 القرار المتوقع: {decision}")

@vip_only
async def cmd_futures(update,ctx):
    if not ctx.args: await update.message.reply_text("مثال: /futures BTC"); return
    sym=clean_symbol(ctx.args[0]); wait=await update.message.reply_text(f"⏳ {sym}...")
    try:
        oi=await asyncio.to_thread(futures_oi_history,sym,"4h",20)
        fr=await asyncio.to_thread(futures_funding_rate,sym)
        ls=await asyncio.to_thread(futures_long_short_ratio,sym)
        lines=[f"📊 <b>الفيوتشر - {sym}/USDT</b>","━━━━━━━━━━━━━━━━",""]
        if oi and oi.get("current",0)>0:
            lines.append(f"📈 OI: <code>{oi['current']:,.0f}</code>")
            if oi.get("change_pct",0)!=0:
                icon="🟢" if oi["change_pct"]>0 else "🔴"
                lines.append(f"{icon} تغير OI: <b>{oi['change_pct']:+.2f}%</b>")
        else: lines.append("📈 OI: <i>لا توجد بيانات</i>")
        if fr is not None:
            icon="🟢" if fr>0 else "🔴"; lines.append(f"{icon} Funding: <b>{fr:+.4f}%</b>")
        else: lines.append("💰 Funding: <i>لا توجد بيانات</i>")
        if ls is not None:
            icon="🟢" if ls>1.2 else ("🔴" if ls<0.83 else "⚖️")
            lines.append(f"{icon} L/S: <b>{ls}</b>")
        else: lines.append("⚖️ L/S: <i>لا توجد بيانات</i>")
        sig=await asyncio.to_thread(futures_signal,sym)
        if sig and sig["direction"]:
            decision="🟢 شراء" if sig['direction']=='LONG' else "🔴 بيع"
            lines+=["","━━━━━━━━━━━━━━━━",
                f"🎯 <b>الإشارة: {'🟢 شراء (LONG)' if sig['direction']=='LONG' else '🔴 بيع (SHORT)'}</b>",
                f"💪 القوة: {sig['confidence']} (Score: {sig['score']:+d})",
                f"🎯 <b>القرار المتوقع: {decision}</b>","","🔍 <b>الأسباب:</b>"]
            for r in sig["reasons"][:5]: lines.append(f"  • {r}")
        else: lines+=["","━━━━━━━━━━━━━━━━","⚖️ <b>لا توجد إشارة واضحة</b>"]
        await wait.edit_text("\n".join(lines),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.exception("futures")
        try: await wait.edit_text(f"⚠️ {str(e)[:150]}")
        except Exception as _ex: log.debug('ignored: %s', _ex)

@vip_only
async def cmd_golden(update,ctx):
    wait=await update.message.reply_text("💎 جارٍ البحث...\n⏳ فحص 500 عملة")
    try: running_loop=asyncio.get_running_loop()
    except RuntimeError: running_loop=asyncio.new_event_loop()
    async def update_progress(processed,total,found):
        try:
            await wait.edit_text(
                f"💎 <b>جارٍ المسح الشامل...</b>\n\n📊 تم فحص: <b>{processed}</b> من <b>{total}</b> عملة\n"
                f"🎯 تم إيجاد: <b>{found}</b> فرصة حتى الآن\n\n⏳ يرجى الانتظار...",parse_mode=ParseMode.HTML)
        except Exception as _ex: log.debug('ignored: %s', _ex)
    def sync_progress(proc,tot,fnd):
        try: asyncio.run_coroutine_threadsafe(update_progress(proc,tot,fnd),running_loop)
        except Exception as _ex: log.debug('ignored: %s', _ex)
    try:
        results=await asyncio.to_thread(golden_scan,2,sync_progress)
        if not results:
            syms=await asyncio.to_thread(top_symbols,20,True)
            near_misses=[]
            for s in syms[:8]:
                try:
                    r=await asyncio.to_thread(golden_score,s,True,True)
                    if r: near_misses.append(r)
                except Exception: continue
            near_misses.sort(key=lambda x:-x["score"])
            msg="💎 <b>لا توجد فرصة ذهبية حالياً</b>\n\n"
            if near_misses:
                msg+="🔍 <b>أقرب العملات للفرصة (Score):</b>\n"
                for nm in near_misses[:3]:
                    msg+=f"<b>#{nm['sym']}</b> — النقاط: {nm['score']}\n  ↳ {', '.join(nm['reasons'][:4])}\n\n"
            msg+="💡 <b>ملاحظة:</b> لم يجد نموذج AI فرصة بدرجة كافية في هذه الجولة."
            await wait.edit_text(msg,parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW); return
        await wait.delete()
        for g in results:
            txt=format_golden_post(g,"vip")
            await update.message.reply_text(txt,parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
            await asyncio.sleep(1)
    except Exception as e:
        log.exception("golden")
        try: await wait.edit_text(f"⚠️ {str(e)[:200]}")
        except Exception as _ex: log.debug('ignored: %s', _ex)

@vip_only
async def cmd_alpha_radar_v2(update,ctx):
    wait=await update.message.reply_text("🚀 <b>رادار النخبة (Alpha/Web3/DEX)</b>\n⏳ جلب الترند + فحص...",parse_mode=ParseMode.HTML)
    try:
        trending_url="https://api.coingecko.com/api/v3/search/trending"
        r=await asyncio.to_thread(requests.get,trending_url,timeout=10)
        trending_coins=r.json().get("coins",[]) if r.status_code==200 else []
        if not trending_coins:
            await wait.edit_text("⚠️ تعذر جلب بيانات الزخم"); return
        lines=["💎 <b>رادار النخبة (Alpha/Web3/DEX)</b>","━━━━━━━━━━━━━━━━",
            "🔍 <i>مستبعد: BTC, ETH, BNB, العملات الأساسية والستيبل</i>",""]
        count=0
        for item in trending_coins:
            if count>=6: break
            cd=item.get("item",{}); symbol=(cd.get("symbol","") or "").upper()
            name=cd.get("name",""); rank=cd.get("market_cap_rank","N/A"); score=cd.get("score",0)
            if symbol in ALPHA_MAJORS_EXCLUDE: continue
            pd_=cd.get("data",{}) or {}
            ch_raw=(pd_.get("price_change_percentage_24h") or {}).get("usd",0)
            try: change=float(ch_raw or 0)
            except Exception: change=0.0
            try:
                ai=await asyncio.to_thread(get_analysis,symbol)
                ai_side="🟢 شراء" if ai["side"]==1 else "🔴 بيع"
                ai_grade=ai.get("grade","C")
            except Exception:
                continue
            emoji="🟢" if ai["side"]==1 else "🔴"
            lines+=[f"{emoji} <b>{name} ({symbol})</b>",f"   📊 ترتيب: #{rank} | زخم خارجي: {score} | 24س: {change:+.1f}%",
                    f"   🤖 قرار AI: {ai_side} · درجة {ai_grade}",""]
            count+=1
        if count==0:
            await wait.edit_text("⚠️ لا توجد عملات Alpha/Web3 في الترند حالياً"); return
        lines+=["━━━━━━━━━━━━━━━━","💡 <b>استراتيجية:</b>",
            "1. هذه العملات جديدة/صغيرة (Web3, DEX, Alpha)",
            "2. ابحث عن الرمز في محفظتك (MetaMask, Trust, إلخ)",
            "3. استخدم حاسبة المخاطر لتحديد الحجم","",RISK_WARNING_AR,f"👤 {BRAND}"]
        await wait.edit_text("\n".join(lines),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.exception("alpha_radar_v2")
        try: await wait.edit_text(f"⚠️ {str(e)[:150]}")
        except Exception as _ex: log.debug('ignored: %s', _ex)

@vip_only
async def cmd_explosions(update,ctx):
    wait=await update.message.reply_text("💥 رادار الانفجارات...")
    syms=await asyncio.to_thread(top_symbols,40); rows=[]
    for s in syms[:30]:
        r=await asyncio.to_thread(explosion_radar,s)
        if r: rows.append((s,r))
    if not rows:
        fallback_syms=await asyncio.to_thread(top_symbols,5)
        lines=["💥 <b>لا توجد انفجارات حالياً (السوق هادئ)</b>","👇 إليك أنشط العملات للمراقبة:",""]
        for s in fallback_syms: lines.append(f"• #{s} — 🎯 القرار المتوقع: مراقبة")
        await wait.edit_text("\n".join(lines),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW); return
    rows.sort(key=lambda x:-x[1]["vol_ratio"])
    lines=["💥 رادار الانفجارات:",""]
    for s,r in rows[:10]:
        decision="🟢 شراء" if r["side"]==1 else "🔴 بيع"
        lines+=[f"💥 #{s}: حجم x{r['vol_ratio']} | تغير {r['price_change']:+.2f}% | AI {r['grade']}",f"   🎯 قرار AI: {decision}"]
    await wait.edit_text("\n".join(lines),link_preview_options=NO_PREVIEW)

@vip_only
async def cmd_pump(update,ctx):
    wait=await update.message.reply_text("🚀 عملات صاعدة...")
    syms=await asyncio.to_thread(top_symbols,40); rows=[]
    for s in syms[:30]:
        r=await asyncio.to_thread(pump_radar,s)
        if r: rows.append((s,r))
    if not rows:
        fallback_syms=await asyncio.to_thread(top_symbols,5)
        lines=["🚀 <b>لا توجد عملات صاعدة حالياً (السوق هادئ)</b>","👇 إليك أنشط العملات للمراقبة:",""]
        for s in fallback_syms: lines.append(f"• #{s} — 🎯 القرار المتوقع: مراقبة")
        await wait.edit_text("\n".join(lines),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW); return
    rows.sort(key=lambda x:-x[1]["change_1h"])
    lines=["🚀 عملات في صعود:",""]
    for s,r in rows[:10]:
        lines+=[f"🚀 #{s}: 1س {r['change_1h']:+.2f}% | 4س {r['change_4h']:+.2f}%",f"   🎯 القرار المتوقع: 🟢 شراء"]
    await wait.edit_text("\n".join(lines),link_preview_options=NO_PREVIEW)

@vip_only
async def cmd_plan(update,ctx):
    """/plan dca|grid ... معلومات فقط — بدون تنفيذ."""
    touch_user(update.effective_user,"/plan")
    args = ctx.args or []
    try:
        mode = (args[0] if args else "").lower()
        if mode not in ("dca","grid"):
            msg = (
                "📋 <b>خطط معلوماتية فقط (لا تنفيذ)</b>\n\n"
                "DCA: <code>/plan dca سعر رأس_المال [شرائح] [نسبة_الخطوة]</code>\n"
                "مثال: <code>/plan dca 0.05 500 3 5</code>\n\n"
                "Grid: <code>/plan grid منتصف رأس_المال [عدد] [تباعد%]</code>\n"
                "مثال: <code>/plan grid 65000 1000 6 1.5</code>\n\n"
                "⚠️ البوت لا يرسل أوامر للبورصة."
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            return
        if mode == "dca":
            entry=float(args[1]); cap=float(args[2])
            slices=int(args[3]) if len(args)>3 else 3
            step=float(args[4]) if len(args)>4 else 4.0
            pl=info_dca_plan(entry,cap,slices,step)
            lines=["📥 <b>خطة DCA (معلومات فقط)</b>",f"رأس المال: ${pl['capital']}",f"متوسط دخول تقريبي: {pl['avg_entry']}",""]
            for lv in pl["levels"]:
                lines.append(f"• شريحة {lv['n']}: {lv['price']} ≈ ${lv['amount']} ({lv['qty']})")
            lines+=["", "⚠️ لا تنفيذ تلقائي — للتنبيه والتخطيط اليدوي فقط."]
            await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)
        else:
            mid=float(args[1]); cap=float(args[2])
            grids=int(args[3]) if len(args)>3 else 6
            sp=float(args[4]) if len(args)>4 else 1.5
            pl=info_grid_plan(mid,cap,grids,sp)
            lines=["▦ <b>خطة Grid (معلومات فقط)</b>",f"المحور: {pl['mid']} | رأس المال: ${pl['capital']}",""]
            for lv in pl["levels"]:
                lines.append(f"• {lv['side']}: {lv['price']} ≈ ${lv['amount']}")
            lines+=["", "⚠️ لا تنفيذ تلقائي — للمستويات على الشارت يدوياً."]
            await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("صيغة غير صحيحة. مثال: /plan dca 0.05 500 3 5")

async def cmd_spot(update,ctx):
    wait=await update.message.reply_text("🌱 جارٍ مسح فرص السبوت (أفق 1–2 شهر)...")
    try:
        rows=await asyncio.to_thread(spot_opportunities,12)
        lang=get_user_lang(update.effective_user.id)
        txt=build_spot_text(rows,lang)
        await wait.edit_text(txt[:4000],parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.exception("cmd_spot")
        try: await wait.edit_text(f"⚠️ {str(e)[:150]}")
        except Exception: pass

async def cmd_bottoms(update,ctx):
    wait=await update.message.reply_text("📉 رادار القيعان...")
    syms=await asyncio.to_thread(top_symbols,70); rows=[]
    for s in syms[:55]:
        r=await asyncio.to_thread(bottom_radar,s)
        if r: rows.append((s,r))
    if not rows: await wait.edit_text("📉 لا توجد قيعان حالياً (السوق في حالة استقرار)."); return
    rows.sort(key=lambda x:x[1]["diff"])
    lines=["📉 رادار القيعان:",""]
    for s,r in rows[:10]:
        lines+=[f"{r['severity']} #{s}",f"   {r['diff']}% تحت EMA200 | RSI {r['rsi']} | تعافي +{r['rebound']}%",
                f"   🎯 القرار المتوقع: 🟢 شراء"]
    await wait.edit_text("\n".join(lines)[:4000],link_preview_options=NO_PREVIEW)

@vip_only
async def cmd_shorts_radar(update,ctx):
    wait=await update.message.reply_text("🔻 فرص الشورت...")
    syms=await asyncio.to_thread(top_symbols,40); rows=[]
    for s in syms[:30]:
        r=await asyncio.to_thread(short_radar,s)
        if r: rows.append((s,r))
    if not rows:
        fallback_syms=await asyncio.to_thread(top_symbols,5)
        lines=["🔻 <b>لا توجد فرص شورت حالياً (السوق يميل للصعود)</b>","👇 إليك أنشط العملات للمراقبة:",""]
        for s in fallback_syms: lines.append(f"• #{s} — 🎯 القرار المتوقع: مراقبة")
        await wait.edit_text("\n".join(lines),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW); return
    lines=["🔻 رادار الشورت:",""]
    for s,r in rows[:10]:
        lines+=[f"🔻 #{s}: RSI {r['rsi']} | {fmt(r['price'])}",f"   🎯 القرار المتوقع: 🔴 بيع"]
    await wait.edit_text("\n".join(lines),link_preview_options=NO_PREVIEW)

@vip_only
async def cmd_alpha(update,ctx):
    wait=await update.message.reply_text("⭐ رادار Alpha...")
    syms=await asyncio.to_thread(top_symbols,50); rows=[]
    for s in syms[:35]:
        r=await asyncio.to_thread(alpha_radar,s)
        if r: rows.append((s,r))
    if not rows: await wait.edit_text("⭐ لا توجد عملات Alpha قوية حالياً."); return
    rows.sort(key=lambda x:-x[1]["change_7d"])
    lines=["⭐ رادار Alpha:",""]
    for s,r in rows[:10]:
        lines+=[f"⭐ #{s} 7ي {r['change_7d']:+.2f}% | 30ي {r['change_30d']:+.2f}% | AI {r['grade']}",f"   🎯 قرار AI: 🟢 شراء"]
    await wait.edit_text("\n".join(lines),link_preview_options=NO_PREVIEW)

@admin_only
async def cmd_patterns(update,ctx):
    if ctx.args:
        sym=clean_symbol(ctx.args[0])
        wait=await update.message.reply_text(f"🕯️ فحص النماذج لـ {sym} على كل الفريمات...")
        try:
            all_pats=[]
            for tf in ["1d","4h","1h","15m"]:
                try:
                    df=await asyncio.to_thread(get_candles,sym,tf,300,300,100)
                    if df.empty or len(df)<100: continue
                    df=add_indicators(df,100); pats=detect_all_patterns(df,tf); all_pats.extend(pats)
                except Exception: continue
            if not all_pats:
                await wait.edit_text(f"🕯️ #{sym} — لا نماذج مؤكدة على أي فريم"); return
            lines=[f"🕯️ <b>نماذج #{sym}</b>","━━━━━━━━━━━━━━━━",""]
            for p in all_pats:
                em="🟢" if p["bias"]=="bullish" else ("🔴" if p["bias"]=="bearish" else "⚪")
                lines.append(f"{em} <b>{p['name']}</b> [{p.get('tf','?').upper()}]")
                if p.get("neckline"): lines.append(f"   📏 Neckline: {fmt(p['neckline'])}")
                lines.append("")
            await wait.edit_text("\n".join(lines),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
        except Exception as e: await wait.edit_text(f"⚠️ {str(e)[:150]}")
        return
    wait=await update.message.reply_text(
        "🕯️ <b>جاري فحص النماذج على كل العملات النشطة وكل الفريمات...</b>\n\n⏳ قد يستغرق 30-60 ثانية",parse_mode=ParseMode.HTML)
    try:
        syms=await asyncio.to_thread(top_symbols,40); all_results=[]
        for sym in syms[:25]:
            for tf in ["1d","4h","1h"]:
                try:
                    df=await asyncio.to_thread(get_candles,sym,tf,300,600,100)
                    if df.empty or len(df)<100: continue
                    df=add_indicators(df,100); pats=detect_all_patterns(df,tf)
                    for p in pats: all_results.append({**p,"sym":sym})
                except Exception: continue
        if not all_results:
            await wait.edit_text("🕯️ <b>لا نماذج مؤكدة على السوق حالياً</b>\n\nالسوق في حالة عرضية، انتظر فرصة أفضل.",parse_mode=ParseMode.HTML); return
        by_sym={}
        for p in all_results: by_sym.setdefault(p["sym"],[]).append(p)
        ordered=sorted(by_sym.items(),key=lambda x:-len(x[1]))[:15]
        lines=["🕯️ <b>النماذج المكتشفة على السوق</b>",f"📊 {len(all_results)} نموذج على {len(by_sym)} عملة","━━━━━━━━━━━━━━━━",""]
        for sym,pats in ordered:
            cl=coin_link(sym,"binance_fut"); lines.append(f"<a href='{cl}'>#{sym}</a> 👆")
            for p in pats[:3]:
                em="🟢" if p["bias"]=="bullish" else ("🔴" if p["bias"]=="bearish" else "⚪")
                lines.append(f"  {em} {p['name']} [{p.get('tf','?').upper()}]")
            lines.append("")
        lines+=["━━━━━━━━━━━━━━━━",RISK_WARNING_AR]
        await wait.edit_text("\n".join(lines)[:4000],parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.exception("patterns_scan")
        try: await wait.edit_text(f"⚠️ {str(e)[:150]}")
        except Exception as _ex: log.debug('ignored: %s', _ex)

@admin_only
async def cmd_share(update,ctx):
    if not ctx.args: await update.message.reply_text("مثال: /share BTC"); return
    sym=clean_symbol(ctx.args[0]); wait=await update.message.reply_text(f"⏳ جارٍ تجهيز {sym}...")
    try:
        res=await asyncio.to_thread(get_analysis,sym,True)
        if res.get("wait"):
            await wait.edit_text("⏳ لا توجد صفقة مؤهلة لـ "+sym+" (انتظار)."); return
        await wait.delete()
        img=await asyncio.to_thread(render_chart,res,"vip")
        await update.message.reply_photo(photo=img)
        await update.message.reply_text("👇 اختر المنصة:",reply_markup=keyboard_share_post(res),link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.exception("share")
        try: await wait.edit_text(f"⚠️ {str(e)[:200]}")
        except Exception as _ex: log.debug('ignored: %s', _ex)

@admin_only
async def cmd_neon(update,ctx):
    if not ctx.args:
        await update.message.reply_text("مثال: /neon BTC"); return
    sym = clean_symbol(ctx.args[0])
    wait = await update.message.reply_text(f"💳 جارٍ توليد بطاقة النيون لـ {sym}...")
    try:
        res = await asyncio.to_thread(get_analysis, sym, True)
        if res.get("wait"):
            await wait.edit_text("⏳ لا توجد صفقة مؤهلة لـ "+sym+" (انتظار)."); return
        card = await asyncio.to_thread(render_trade_card, res, "admin")
        await update.message.reply_photo(photo=card)
        await wait.delete()
    except Exception as e:
        await wait.edit_text(f"⚠️ {str(e)[:150]}")

@admin_only
async def cmd_forcepost(update,ctx):
    wait=await update.message.reply_text("⏳ جارٍ المسح والنشر...")
    try:
        res=await run_autopost(ctx.bot); stats=res or {}
        await wait.edit_text(f"✅ انتهى\n\nVIP: {stats.get('vip',0)} | FREE: {stats.get('free',0)}\nإجمالي: {stats.get('total',0)}")
    except Exception as e:
        log.exception("forcepost"); await wait.edit_text(f"⚠️ {str(e)[:200]}")

@admin_only
async def cmd_clearsignals(update,ctx):
    with store.lock:
        n=len(store.data["signals"]); store.data["signals"]=[]; store.save("signals")
    await update.message.reply_text(f"✅ تم حذف {n} صفقة")

@admin_only
async def cmd_smartcleanup(update,ctx):
    wait=await update.message.reply_text("🧹 جارٍ التنظيف...")
    n=await asyncio.to_thread(smart_cleanup_trades)
    await wait.edit_text(f"✅ تم إغلاق {n} صفقة")

@admin_only
async def cmd_debug(update,ctx):
    lines=["🔍 تشخيص","",f"💾 Storage: {store.remote_msg}",
        f"🔧 Maintenance: {'ON' if is_maintenance() else 'OFF'}",
        f"🌐 Multi-Exchange: {'ON' if is_multi_exchange() else 'OFF'}",
        f"📢 FREE: {'✅' if CHANNEL_ID else '❌'} | VIP: {'✅' if VIP_CHANNEL_ID else '❌'}",
        f"📊 MAX_OPEN: {MAX_OPEN} | نشطة: {len(active_signals())}",
        f"📝 posted: {len(store.data['posted'])}",
        f"📡 Binance Futures API: {BINANCE_FAPI_BASE}",
        f"🤖 محرك القرار: {RYMA_AI_PROVIDER} / {RYMA_AI_MODEL} | النموذج المحلي: {'جاهز' if os.path.isfile(RYMA_ML_MODEL_PATH) else 'بانتظار التدريب'}",
        f"💎 AI Golden scan: كل {CYCLE_GOLDEN//3600}س | Model: {RYMA_AI_MODEL}",
        f"🕯️ Patterns: MTF (1D+4H+1H) ✅",
        f"🎯 Points: {VIP_THRESHOLD}=VIP{VIP_REWARD_DAYS}d | +{POINTS_REFERRAL}/referral"]
    syms=await asyncio.to_thread(top_symbols,60); lines.append(f"🎯 top_symbols: {len(syms)}")
    if syms: lines.append(f"   {', '.join(syms[:10])}")
    g,l=await asyncio.to_thread(get_top_movers,True)
    lines.append(f"🟢 Gainers: {len(g)} | 🔴 Losers: {len(l)}")
    await update.message.reply_text("\n".join(lines)[:4000],link_preview_options=NO_PREVIEW)

def _runtime_health_report():
    lines=[f"🧪 Ryma Crypto Health Check",f"نسخة التشغيل: {BOT_VERSION}"]
    try:
        lines.append(f"CCXT: {getattr(ccxt,'__version__','unknown')}")
    except Exception as ex:
        lines.append(f"CCXT: ERROR {type(ex).__name__}: {ex}")
    try:
        df=get_candles("BTC","4h",240,ttl=0,min_bars=200)
        ed=add_indicators(df,100)
        ready=len(ed)>=100 and pd.notna(ed['atr'].iloc[-1])
        lines.append(f"شموع BTC 4H: {len(df)} | المصدر: {df.attrs.get('source','unknown')} | المؤشرات: {'OK' if ready else 'FAIL'}")
        if ready:
            last=ed.iloc[-1]
            lines.append(f"ATR: {float(last['atr']):.6g} | RSI: {float(last['rsi']):.1f}")
    except Exception as ex:
        lines.append(f"بيانات BTC: FAIL — {type(ex).__name__}: {str(ex)[:100]}")
    try:
        snap=derivatives_snapshot("BTC",ttl=60)
        ok=sum(1 for k in ("oi","funding","ls_ratio","liquidations","taker") if snap.get(k) is not None)
        lines.append(f"مصادر المشتقات: {ok}/5 متاحة")
        for k,v in snap.get("source_status",{}).items():
            if v!="ok": lines.append(f"  • {k}: {str(v)[:70]}")
    except Exception as ex:
        lines.append(f"المشتقات: FAIL — {type(ex).__name__}: {str(ex)[:100]}")
    lines.append(f"Decision Engine: {RYMA_AI_PROVIDER} | Local model: {'READY' if os.path.isfile(RYMA_ML_MODEL_PATH) else 'NOT TRAINED'}")
    lines.append(f"AI cache: {len(_ai_decision_cache)} | AI daily cap: {RYMA_AI_DAILY_CALL_CAP} | min interval: {RYMA_AI_MIN_INTERVAL}s")
    try:
        _u=_ai_usage_read(); lines.append(f"AI requests today (UTC): {_u.get('calls',0)}/{RYMA_AI_DAILY_CALL_CAP}")
    except Exception: pass
    lines.append(f"Cache: candles={len(_candle_cache)} | prices={len(_price_cache)} | derivatives={len(_derivatives_snapshot_cache)}")
    lines.append("ملاحظة: هذا فحص اتصال وصحة بيانات، وليس حكماً على ربحية الاستراتيجية.")
    return "\n".join(lines)

@vip_only
async def cmd_regime(update,ctx):
    wait=await update.message.reply_text("⏳ أفحص حالة السوق عبر BTC...")
    data=await asyncio.to_thread(market_regime_snapshot)
    lines=[f"🌐 نظام السوق: {data.get('regime','غير معروف')}",
           f"ميل الاتجاه: {data.get('bias',0):+d}"]
    lines += data.get("details",[])
    lines.append("⚠️ هذا سياق عام للسوق وليس إشارة دخول مستقلة.")
    await wait.edit_text("\n".join(lines)[:3900])

@vip_only
async def cmd_smartmoney(update,ctx):
    if not ctx.args:
        await update.message.reply_text("مثال: /smartmoney BTC")
        return
    sym=clean_symbol(ctx.args[0])
    wait=await update.message.reply_text(f"⏳ أفحص تدفقات {sym}...")
    data=await asyncio.to_thread(smart_money_snapshot,sym)
    lines=[f"🧭 رادار التدفقات: {sym}",f"النتيجة: {data['bias']} ({data['score']:+d})",
           f"المصادر المتاحة: {data['available']}/6"]
    lines += ["• "+x for x in data.get("notes",[])]
    lines += ["", "⚠️ "+data["warning"]]
    await wait.edit_text("\n".join(lines)[:3900])


@admin_only
async def cmd_health(update,ctx):
    wait=await update.message.reply_text("⏳ فحص صحة المحرك ومصادر البيانات...")
    try:
        report=await asyncio.to_thread(_runtime_health_report)
        await wait.edit_text(report[:3900],link_preview_options=NO_PREVIEW)
    except Exception as ex:
        await wait.edit_text(f"Health check failed: {type(ex).__name__}: {str(ex)[:200]}")

@admin_only
async def cmd_post(update,ctx):
    if not ctx.args: await update.message.reply_text("مثال: /post BTC"); return
    sym=clean_symbol(ctx.args[0])
    res=await asyncio.to_thread(get_analysis,sym,True)
    force=len(ctx.args)>1 and ctx.args[1].lower()=="force"
    if res.get("wait") or (not res.get("opportunity") and not force):
        await update.message.reply_text(f"⛔ {sym}: ليست فرصة مؤكدة (رادار فقط) — لا تُنشر. للنشر القسري: /post {sym} force"); return
    sent=await publish(ctx.bot,res,vip=True,free=True,admin_copy=False)
    if any(x.startswith(("VIP_", "FREE_")) for x in sent) and can_track(res): track_signal(res)
    await update.message.reply_text(f"✅ نُشر: {', '.join(sent)}")


def _parse_bt_days(value=None,default=60):
    """Accept the agreed 30/60-day windows; default safely to 60 days."""
    if value is None: return int(default)
    raw=str(value).strip().lower()
    if raw.endswith("d"):
        try: n=int(float(raw[:-1]))
        except ValueError: return int(default)
        return min(max(n,30),60)
    try: n=float(raw)
    except (TypeError,ValueError): return int(default)
    if n in (30,60): return int(n)
    return int(default)


async def _run_bt(update,ctx,syms,label,days):
    """Recent 30/60-day backtest runner; live engine and trade_step remain unchanged."""
    syms=[x for x in (syms or []) if x]
    if not syms:
        await update.message.reply_text("❌ لا توجد عملات للاختبار"); return
    if _BT_BUSY[0]:
        await update.message.reply_text("⏳ يوجد اختبار آخر قيد التشغيل؛ انتظر حتى ينتهي."); return
    _BT_BUSY[0]=True
    try:
        label=f"{label} · {int(days)}D"
        wait=await update.message.reply_text(
            f"⏳ Backtest v10 على {len(syms)} عملة · آخر {int(days)} يوماً\\n"
            "4H + 1H + 15M — بيانات تمهيدية للمؤشرات خارج نافذة القياس.")
        per,a,b,errors=await asyncio.to_thread(backtest_many_days,syms,int(days),1)
        text,_=bt_report(per,a,b,label,errors)
        await wait.edit_text(text[:4000],link_preview_options=NO_PREVIEW)
        rows=[dict(x) for tr in (per or {}).values() for x in (tr or []) if isinstance(x,dict)]
        if rows:
            csv_bytes=pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
            buf=io.BytesIO(csv_bytes)
            safe_label=re.sub(r"[^A-Za-z0-9_-]+","_",str(label)).strip("_") or "ALL"
            buf.name=f"Ryma_v10_{safe_label}_{int(days)}d_trades.csv"
            try:
                await ctx.bot.send_document(update.effective_chat.id,document=buf,filename=buf.name,
                    caption=f"سجل صفقات Backtest {BOT_VERSION} · {len(rows)} صفقة · نافذة {int(days)} يوم · للتحليل فقط",
                    protect_content=False,read_timeout=120,write_timeout=120,connect_timeout=30)
            except Exception as ex:
                log.warning("bt csv export failed: %s",ex)
                await update.message.reply_text("⚠️ تعذّر إرسال ملف CSV (التقرير أعلاه سليم).")
    finally:
        _BT_BUSY[0]=False


@admin_only
async def cmd_bt(update,ctx):
    """/bt [SYMBOL|ALL|TOP50] [60|30|60d|30d] — default: last 60 days."""
    arg=ctx.args[0].upper() if ctx.args else "ALL"
    days=_parse_bt_days(ctx.args[1] if len(ctx.args)>1 else None,60)
    if arg in ("ALL",""): syms,label=list(COINS),"ALL"
    elif arg in ("TOP","TOP50"): syms,label=await asyncio.to_thread(top_symbols,50),"TOP50"
    else: syms,label=[clean_symbol(arg)],clean_symbol(arg)
    await _run_bt(update,ctx,syms,label,days)

# ======================= AI walk-forward backtest (/btdiag) =======================
_BT_BUSY=[False]


async def _run_opt(update,syms,years):
    if _BT_BUSY[0]:
        await update.message.reply_text("⏳ يوجد اختبار آخر قيد التشغيل؛ انتظر حتى ينتهي."); return
    _BT_BUSY[0]=True
    state={"stage":"load","done":0,"total":len(syms)}
    wait=await update.message.reply_text(f"⏳ Optimiser v10 · {len(syms)} عملة · {years:g} سنة · {len(V10_GRID)} تركيبة\nتحميل البيانات ثم تشغيل التركيبات (قد يستغرق 15–40 دقيقة).")
    try:
        def work():
            data={}; errors={}
            for i,sym in enumerate(syms,1):
                try: data[sym]=_bt_frames(sym,years)
                except Exception as ex: errors[sym]=str(ex)[:100]
                state.update(stage="load",done=i,total=len(syms))
            if not data: return None,errors,[]
            rows=v10_optimize(data,progress=lambda d,t:state.update(stage="run",done=d,total=t))
            return rows,errors,list(data)
        task=asyncio.create_task(asyncio.to_thread(work))
        while not task.done():
            await asyncio.sleep(30)
            try: await wait.edit_text(f"⏳ Optimiser v10 · {'تحميل' if state['stage']=='load' else 'تشغيل التركيبات'} {state['done']}/{state['total']}")
            except Exception: pass
        rows,errors,loaded=task.result()
        if not rows:
            await wait.edit_text("⚠️ لم يُحمَّل أي بيان: "+"; ".join(f"{k}: {v}" for k,v in list(errors.items())[:3])); return
        await wait.edit_text(opt_report(rows,loaded,years,errors)[:4000],link_preview_options=NO_PREVIEW)
    except Exception as ex:
        log.exception("optimiser")
        try: await wait.edit_text(f"⚠️ {type(ex).__name__}: {str(ex)[:150]}")
        except Exception: pass
    finally:
        _BT_BUSY[0]=False


@admin_only
async def cmd_btopt(update,ctx):
    """/btopt [ALL|TOP12|BTC,ETH,...] [years<=3] — grid search of stop/ADX/cooldown/targets; ranks on TRAIN, verifies on TEST."""
    arg=(ctx.args[0].upper() if ctx.args else "TOP12")
    try: years=min(max(float(ctx.args[1]),0.1),3.0) if len(ctx.args)>1 else 1.0
    except ValueError: years=1.0
    if arg=="ALL": syms=list(COINS)[:20]
    elif arg.startswith("TOP"):
        try: n=min(max(int(arg[3:] or 12),3),20)
        except ValueError: n=12
        syms=list(await asyncio.to_thread(top_symbols,n))
    else: syms=[clean_symbol(x) for x in arg.replace(" ","").split(",") if x][:20]
    await _run_opt(update,syms,years)


@admin_only
async def cmd_v10show(update,ctx):
    p=v10_params()
    await update.message.reply_text(
        "⚙️ معاملات v10 الحالية (حي + باك تست):\n"
        f"• stop_tf={p['stop_tf']}  stop_k={p['stop_k']:g}  (الوقف = stop_k × ATR على هذا الإطار، بين {V10_RISK_MIN_PCT*100:.2f}% و{V10_RISK_MAX_PCT*100:.1f}%)\n"
        f"• min_adx={p['min_adx']:g}  (أدنى ADX على 4H لقبول الفرصة)\n"
        f"• cooldown={p['cooldown']}  (شموع 15m بعد صفقة خاسرة على نفس العملة)\n"
        f"• rr={p['rr']}  {V10_RR_SETS[p['rr']]}\n"
        "تغيير: /v10set stop_tf=1h stop_k=1.2 min_adx=20 cooldown=16 rr=runner\nإرجاع الافتراضي: /v10set reset")


@admin_only
async def cmd_v10set(update,ctx):
    if not ctx.args:
        await update.message.reply_text("مثال: /v10set stop_tf=1h stop_k=1.2 min_adx=20 cooldown=16 rr=runner\nأو: /v10set reset"); return
    try:
        if ctx.args[0].lower()=="reset": new=dict(V10_DEFAULTS)
        else:
            upd={}
            for a in ctx.args:
                k,_,v=a.partition("=")
                if k not in V10_DEFAULTS or not v: raise ValueError(f"معامل غير معروف أو بلا قيمة: {a}")
                upd[k]=v
            new=_v10_clean({**v10_params(),**upd})
    except ValueError as ex:
        await update.message.reply_text(f"❌ {ex}"); return
    with store.lock:
        store.data.setdefault("settings",{})["v10_params"]=new; store.save("settings")
    _analysis_cache.clear()
    await update.message.reply_text("✅ حُفظت المعاملات ويعمل بها المحرك الحي و/bt فوراً.\n"
        f"stop={new['stop_tf']}×{new['stop_k']:g} | adx≥{new['min_adx']:g} | cooldown={new['cooldown']} | rr={new['rr']}")


@admin_only
async def cmd_btx(update, ctx):
    """/btx [sweep|fvg|momentum|bbshort|all] [ALL|TOP12|BTC,ETH,...] [years] — backtest the 4 radar strategies, one engine/report."""
    arg = (ctx.args[0].lower() if ctx.args else "all")
    names = list(RADARS) if arg == "all" else ([RADAR_BY_CMD[arg]] if arg in RADAR_BY_CMD else None)
    if not names:
        await update.message.reply_text("الاستعمال: /btx sweep|fvg|momentum|bbshort|all [TOP12|ALL|BTC,ETH] [years]"); return
    sel = (ctx.args[1].upper() if len(ctx.args) > 1 else "TOP12")
    try: years = min(max(float(ctx.args[2]), 0.1), 3.0) if len(ctx.args) > 2 else None
    except ValueError: years = None
    if sel == "ALL": syms = list(COINS)[:20]
    elif sel.startswith("TOP"):
        try: n = min(max(int(sel[3:] or 12), 3), 20)
        except ValueError: n = 12
        syms = list(await asyncio.to_thread(top_symbols, n))
    else: syms = [clean_symbol(x) for x in sel.replace(" ", "").split(",") if x][:20]
    if _BT_BUSY[0]:
        await update.message.reply_text("⏳ يوجد اختبار آخر قيد التشغيل؛ انتظر حتى ينتهي."); return
    _BT_BUSY[0] = True
    wait = await update.message.reply_text(f"⏳ Strategy Lab · {len(names)} استراتيجية × {len(syms)} عملة — تحميل البيانات قد يستغرق عدة دقائق.")
    try:
        summary = []
        for nm in names:
            per, a, b, errors = await asyncio.to_thread(lab_many, syms, nm, years)
            text = lab_report(nm, per, a, b, errors, years)
            allt = [x for tr in per.values() for x in tr]
            tr, te = split_trades_by_symbol(allt, a, b, 0.65) if allt else ([], [])
            m = metrics(te); summary.append(f"{radar_label(nm)}: TEST n={m['n']} avg {m['avg']:+}R PF {m['pf']}")
            if len(names) == 1: await wait.edit_text(text[:4000], link_preview_options=NO_PREVIEW)
            else:
                await update.message.reply_text(text[:4000], link_preview_options=NO_PREVIEW)
                try: await wait.edit_text(f"⏳ اكتملت {len(summary)}/{len(names)}")
                except Exception: pass
        if len(names) > 1:
            await wait.edit_text("📋 ملخص المقارنة (TEST):\n" + "\n".join(summary))
    except Exception as ex:
        log.exception("btx")
        try: await wait.edit_text(f"⚠️ {type(ex).__name__}: {str(ex)[:150]}")
        except Exception: pass
    finally:
        _BT_BUSY[0] = False


@admin_only
async def cmd_bts(update, ctx):
    """/bts [trend|xsmom|all] [TOP20|BTC,ETH,...] [years<=5] — swing (daily/weekly) strategies lab."""
    arg = (ctx.args[0].lower() if ctx.args else "all")
    if arg not in ("trend", "xsmom", "all"):
        await update.message.reply_text("الاستعمال: /bts trend|xsmom|all [TOP20|BTC,ETH,..] [years]"); return
    sel = (ctx.args[1].upper() if len(ctx.args) > 1 else "TOP20")
    try: years = min(max(float(ctx.args[2]), 0.5), 5.0) if len(ctx.args) > 2 else 3.0
    except ValueError: years = 3.0
    if sel.startswith("TOP"):
        try: n = min(max(int(sel[3:] or 20), 8), 40)
        except ValueError: n = 20
        syms = list(await asyncio.to_thread(top_symbols, n))
    else: syms = [clean_symbol(x) for x in sel.replace(" ", "").split(",") if x][:40]
    if _BT_BUSY[0]:
        await update.message.reply_text("⏳ يوجد اختبار آخر قيد التشغيل؛ انتظر حتى ينتهي."); return
    _BT_BUSY[0] = True
    wait = await update.message.reply_text(f"⏳ Swing Lab · {len(syms)} عملة · {years:g} سنة — تحميل البيانات اليومية.")
    try:
        data, errors = await asyncio.to_thread(swing_data, syms, years)
        if not data:
            await wait.edit_text("⚠️ لم تُحمَّل أي بيانات: " + "; ".join(f"{k}: {v}" for k, v in list(errors.items())[:3])); return
        texts = []
        if arg in ("trend", "all"): texts.append(await asyncio.to_thread(trend_report, data, errors, years))
        if arg in ("xsmom", "all"): texts.append(await asyncio.to_thread(xsmom_report, data, errors, years))
        await wait.edit_text(texts[0][:4000], link_preview_options=NO_PREVIEW)
        for tx in texts[1:]: await update.message.reply_text(tx[:4000], link_preview_options=NO_PREVIEW)
    except Exception as ex:
        log.exception("bts")
        try: await wait.edit_text(f"⚠️ {type(ex).__name__}: {str(ex)[:150]}")
        except Exception: pass
    finally:
        _BT_BUSY[0] = False


@admin_only
async def cmd_btt(update, ctx):
    """/btt [TOP12|BTC,ETH,...] [years<=3] — intraday hour-of-day lab (1-4h holds, TRAIN-only hour selection)."""
    sel = (ctx.args[0].upper() if ctx.args else "TOP12")
    try: years = min(max(float(ctx.args[1]), 0.5), 3.0) if len(ctx.args) > 1 else 2.0
    except ValueError: years = 2.0
    if sel.startswith("TOP"):
        try: n = min(max(int(sel[3:] or 12), 5), 30)
        except ValueError: n = 12
        syms = list(await asyncio.to_thread(top_symbols, n))
    else: syms = [clean_symbol(x) for x in sel.replace(" ", "").split(",") if x][:30]
    if _BT_BUSY[0]:
        await update.message.reply_text("⏳ يوجد اختبار آخر قيد التشغيل؛ انتظر حتى ينتهي."); return
    _BT_BUSY[0] = True
    wait = await update.message.reply_text(f"⏳ Intraday Lab · {len(syms)} عملة · {years:g} سنة — تحميل شموع الساعة.")
    try:
        data, errors = await asyncio.to_thread(intra_data, syms, years)
        if not data:
            await wait.edit_text("⚠️ لم تُحمَّل أي بيانات: " + "; ".join(f"{k}: {v}" for k, v in list(errors.items())[:3])); return
        tx = await asyncio.to_thread(intra_report, data, errors, years)
        await wait.edit_text(tx[:4000], link_preview_options=NO_PREVIEW)
        if len(tx) > 4000: await update.message.reply_text(tx[4000:8000], link_preview_options=NO_PREVIEW)
    except Exception as ex:
        log.exception("btt")
        try: await wait.edit_text(f"⚠️ {type(ex).__name__}: {str(ex)[:150]}")
        except Exception: pass
    finally:
        _BT_BUSY[0] = False

@admin_only
async def cmd_btdiag(update,ctx):
    """Quick diagnostic on the 3 most liquid coins, last 30/60 days."""
    days=_parse_bt_days(ctx.args[0] if ctx.args else None,60)
    syms=await asyncio.to_thread(top_symbols,3)
    await _run_bt(update,ctx,syms,"TOP3",days)

# ======================= تصدير بيانات البحث (/exportdata) =======================
# يقرأ بيانات عامة من Binance فقط (لا توكن ولا مفاتيح) ويرسل ملفات ZIP للأدمن.
EXP_PACE=0.35               # ثوانٍ بين الطلبات: نحمي حد الطلبات المشترك مع باقي البوت
EXP_4H_BARS=11000           # ~5 سنوات
EXP_1D_BARS=1900
EXP_1H_BARS=13000           # ~1.5 سنة
EXP_15M_BARS=17520          # ~6 أشهر فعلية لفريم الدخول
EXP_FUND_YEARS=5.0
EXP_ZIP_MAX=44*1024*1024    # حد تيليغرام للملف 50MB
_EXP_BUSY=[False]

def _exp_get(url,params,tries=5):
    """طلب مع إعادة محاولة. يرجع None إذا الرمز غير موجود/فشل. 418 = حظر IP فنوقف."""
    for k in range(tries):
        try:
            r=requests.get(url,params=params,timeout=15)
            if r.status_code==200: return r.json()
            if r.status_code==418: raise RuntimeError("418: Binance حظر الـIP مؤقتاً، أعد المحاولة بعد دقائق")
            if r.status_code==400: return None
            if r.status_code==429: time.sleep(min(int(r.headers.get("Retry-After","5") or 5),60)); continue
            time.sleep(1+k)
        except RuntimeError: raise
        except Exception: time.sleep(1+k)
    return None

def _exp_klines(sym,interval,bars,tf_ms):
    """يرجع (rows, complete). rows: قوائم كلاينز Binance الخام، بدون الشمعة غير المغلقة."""
    out,end,complete=[],None,True
    while len(out)<bars:
        p={"symbol":f"{sym}USDT","interval":interval,"limit":1000}
        if end: p["endTime"]=end
        data=_exp_get(f"{BINANCE_FAPI_BASE}/fapi/v1/klines",p); time.sleep(EXP_PACE)
        if data is None: complete=False; break          # فشل الطلب: بيانات ناقصة
        if not isinstance(data,list) or not data: break # [] = بداية التاريخ
        out=data+out; end=int(data[0][0])-1
        if len(data)<1000: break
    now=int(time.time()*1000)
    by_t={int(k[0]):k for k in out}
    rows=[by_t[t] for t in sorted(by_t) if t+tf_ms<=now]
    return rows[-bars:],complete

def _exp_funding(sym,years):
    cur=int((time.time()-years*365*86400)*1000); out=[]
    while True:
        data=_exp_get(f"{BINANCE_FAPI_BASE}/fapi/v1/fundingRate",{"symbol":f"{sym}USDT","startTime":cur,"limit":1000})
        time.sleep(EXP_PACE)
        if not isinstance(data,list) or not data: break
        out+=data; last=int(data[-1]["fundingTime"])
        if len(data)<1000 or last<cur: break
        cur=last+1
    return out

def exp_collect(syms,tmp,lite,progress=None):
    import csv
    meta=dict(version=BOT_VERSION,created_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              lite=bool(lite),symbols={},failed=[])
    sets=[("4h","4h",14_400_000,EXP_4H_BARS if not lite else 6900),("1d","1d",86_400_000,EXP_1D_BARS)]
    if not lite:
        sets.extend([("1h","1h",3_600_000,EXP_1H_BARS),("15m","15m",900_000,EXP_15M_BARS)])
    for d_ in ("4h","1d","1h","15m","funding"): os.makedirs(os.path.join(tmp,d_),exist_ok=True)
    for i,sy in enumerate(syms,1):
        if progress and (i==1 or i%3==0): progress(i,len(syms),sy)
        info={}
        try:
            for name,interval,tfms,bars in sets:
                rows,ok=_exp_klines(sy,interval,bars,tfms)
                if len(rows)<50: raise ValueError(f"{name}: بيانات قليلة")
                with open(os.path.join(tmp,name,f"{sy}.csv"),"w",newline="") as f:
                    w=csv.writer(f); w.writerow(["t","open","high","low","close","volume","quote_volume","trades","taker_buy_base","taker_buy_quote"])
                    for k in rows: w.writerow([k[0],k[1],k[2],k[3],k[4],k[5],k[7],k[8],k[9],k[10]])
                info[name]=dict(bars=len(rows),first=int(rows[0][0]),last=int(rows[-1][0]),complete=bool(ok))
            fr=_exp_funding(sy,EXP_FUND_YEARS)
            with open(os.path.join(tmp,"funding",f"{sy}.csv"),"w",newline="") as f:
                w=csv.writer(f); w.writerow(["fundingTime","fundingRate","markPrice"])
                for r in fr: w.writerow([r.get("fundingTime"),r.get("fundingRate"),r.get("markPrice","")])
            info["funding"]=dict(rows=len(fr))
            meta["symbols"][sy]=info
        except RuntimeError: raise
        except Exception as e:
            meta["failed"].append(dict(symbol=sy,error=str(e)[:120]))
    return meta

EXP_README="""Ryma research data (public Binance USDT-M futures data only)
- t / fundingTime: milliseconds since epoch, UTC. Candle t = OPEN time.
- Only CLOSED candles are included (the forming candle is dropped).
- klines columns: t,open,high,low,close,volume,quote_volume,trades,taker_buy_base,taker_buy_quote
- funding columns: fundingTime,fundingRate,markPrice (every 8h)
- 15m history is about six months; 1h about 1.5 years; 4h/daily/funding about five years.
- Symbols = top by current 24h volume (survivorship bias: coins that died are missing; new coins have short history).
- meta.json lists bars per symbol, and `complete=false` if a download was cut short.
"""

def exp_zip(tmp,meta):
    import zipfile
    meta_path=os.path.join(tmp,"meta.json")
    with open(meta_path,"w",encoding="utf-8") as f: json.dump(meta,f,ensure_ascii=False,indent=1)
    readme=os.path.join(tmp,"README.txt")
    with open(readme,"w",encoding="utf-8") as f: f.write(EXP_README)
    groups=[("ryma_4h",["4h"]),("ryma_1d_funding",["1d","funding"]),("ryma_1h",["1h"]),("ryma_15m",["15m"])]
    outs=[]
    for base,dirs in groups:
        files=[]
        for d_ in dirs:
            p=os.path.join(tmp,d_)
            if os.path.isdir(p): files+=[(os.path.join(p,x),f"{d_}/{x}") for x in sorted(os.listdir(p))]
        if not files: continue
        parts=[]
        def open_part(n):
            path=os.path.join(tmp,f"{base}_p{n}.zip")
            z=zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED,compresslevel=6)
            z.write(meta_path,"meta.json"); z.write(readme,"README.txt"); parts.append(path); return z,path
        n=1; zf,path=open_part(n)
        for full,arc in files:
            zf.fp.flush()
            if os.path.getsize(path)>=EXP_ZIP_MAX:      # الجزء امتلأ: نبدأ جزءاً جديداً قبل الملف التالي
                zf.close(); n+=1; zf,path=open_part(n)
            zf.write(full,arc)
        zf.close()
        if len(parts)==1:
            final=os.path.join(tmp,f"{base}.zip"); os.replace(parts[0],final); outs.append(final)
        else: outs+=parts
    return outs

async def _safe_edit(msg,text):
    try: await msg.edit_text(text)
    except Exception as _ex: log.debug('ignored: %s',_ex)

@admin_only
async def cmd_exportdata(update,ctx):
    """/exportdata [lite] — يصدّر بيانات 50 عملة (4س/يومي/ساعة/تمويل) كملفات ZIP لغرض البحث."""
    if _EXP_BUSY[0]:
        await update.message.reply_text("⏳ تصدير آخر قيد التشغيل"); return
    import shutil, tempfile
    lite=any(a.lower()=="lite" for a in ctx.args)
    _EXP_BUSY[0]=True; tmp=None
    try:
        msg=await update.message.reply_text(
            "⏳ بدأ التصدير (%s). يأخذ حوالي %s، ويرسل الملفات في الآخر. لا تعيد الأمر."%(
                BOT_VERSION,"4–6 دقائق" if lite else "15–25 دقيقة"))
        syms=await asyncio.to_thread(top_symbols,50)
        syms=["BTC"]+[x for x in syms if x!="BTC"]; syms=syms[:50]
        tmp=tempfile.mkdtemp(prefix="ryma_exp_")
        loop=asyncio.get_running_loop()
        def progress(i,n,sy): asyncio.run_coroutine_threadsafe(_safe_edit(msg,f"⏳ {i}/{n} · {sy}"),loop)
        meta=await asyncio.to_thread(exp_collect,syms,tmp,lite,progress)
        if not meta["symbols"]:
            await msg.edit_text("❌ ما اتجمعت بيانات. الأخطاء: "+"; ".join(f"{x['symbol']}:{x['error']}" for x in meta["failed"][:5])); return
        files=await asyncio.to_thread(exp_zip,tmp,meta)
        await msg.edit_text(f"✅ تم الجمع: {len(meta['symbols'])} عملة، فشل {len(meta['failed'])}. جارٍ إرسال {len(files)} ملف...")
        for path in files:
            mb=os.path.getsize(path)/1048576
            with open(path,"rb") as fh:
                await ctx.bot.send_document(update.effective_chat.id,document=fh,filename=os.path.basename(path),
                    caption=f"{os.path.basename(path)} · {mb:.1f}MB · {BOT_VERSION}",protect_content=False,
                    read_timeout=600,write_timeout=600,connect_timeout=60)
        if meta["failed"]:
            await update.message.reply_text("⚠️ فشل: "+", ".join(f"{x['symbol']}" for x in meta["failed"])[:3500])
    finally:
        _EXP_BUSY[0]=False
        if tmp: shutil.rmtree(tmp,ignore_errors=True)

@admin_only
async def cmd_bt50(update,ctx):
    days=_parse_bt_days(ctx.args[0] if ctx.args else None,60)
    syms=await asyncio.to_thread(top_symbols,50)
    await _run_bt(update,ctx,syms if isinstance(syms,(list,tuple)) else [],"TOP50",days)


@admin_only
async def cmd_scan(update,ctx):
    wait=await update.message.reply_text("⏳ فحص...")
    syms=await asyncio.to_thread(top_symbols,60,True)
    res=await asyncio.to_thread(scan_sync,syms[:30])
    res=[r for r in res if r["rank"]>=0]; res.sort(key=lambda r:-r["rank"])
    if not res: await wait.edit_text("لا شيء"); return
    lines=["🎯 أفضل الإعدادات:",""]
    for r in res[:10]:
        s="🟢" if r["side"]==1 else "🔴"; dec="🟢 شراء" if r["side"]==1 else "🔴 بيع"
        pats=r.get("patterns",[]); pat_txt=""
        if pats:
            p=pats[0]; tf_lbl=f"[{p.get('tf','').upper()}]" if p.get('tf') else ""
            pat_txt=f" 🕯️{p['name']}{tf_lbl}"
        lines+=[f"{r['grade']} | #{r['sym']} {s}{pat_txt}",f"   🎯 القرار المتوقع: {dec}"]
    await wait.edit_text("\n".join(lines),link_preview_options=NO_PREVIEW)

@admin_only
async def cmd_short(update,ctx):
    wait=await update.message.reply_text("⏳...")
    res=await asyncio.to_thread(scan_sync,COINS)
    res=[r for r in res if r["side"]==-1 and r["rank"]>=0]
    if not res: await wait.edit_text("لا شورت"); return
    lines=["🔻 فرص شورت:"]+[f"{r['grade']} | #{r['sym']} | 🎯 بيع" for r in res[:15]]
    await wait.edit_text("\n".join(lines),link_preview_options=NO_PREVIEW)

@admin_only
async def cmd_delist(update,ctx):
    wait=await update.message.reply_text("⏳...")
    try:
        r=await asyncio.to_thread(requests.get,"https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                       params=dict(type=1,catalogId=161,pageNo=1,pageSize=20),timeout=10)
        arts=r.json()["data"]["catalogs"][0]["articles"]
        skip={"BINANCE","WILL","DELIST","ON","AND","THE","FOR","USD","USDT","FROM","SPOT","TRADING",
            "PAIRS","PAIR","TOKEN","TOKENS","ANNOUNCEMENT","API","BNB","LISTING","MARGIN","FUTURES",
            "MONITORING","DELISTING"}
        now_ms=int(time.time()*1000); rows=[]
        for a in arts[:40]:
            title=a.get("title",""); release_ts=a.get("releaseDate",0)
            if release_ts and release_ts>now_ms:
                dt_str=dt.datetime.utcfromtimestamp(release_ts/1000).strftime("%Y-%m-%d")
                for w in re.findall(r'\b[A-Z0-9]{2,10}\b',title):
                    if w in skip or w.isdigit() or len(w)<2: continue
                    rows.append((w,dt_str))
        if not rows: await wait.edit_text("✅ لا توجد"); return
        seen=set(); lines=["⚠️ للحذف قريباً:",""]
        for c,d in rows:
            if c in seen: continue
            seen.add(c); lines.append(f"🔻 {c} — 📅 {d}")
        await wait.edit_text("\n".join(lines[:40]),link_preview_options=NO_PREVIEW)
    except Exception as e: await wait.edit_text(f"⚠️ {str(e)[:150]}")

@admin_only
async def cmd_price(update,ctx):
    if not ctx.args: await update.message.reply_text("مثال: /price BTC"); return
    sym=clean_symbol(ctx.args[0]); prices=await asyncio.to_thread(all_prices,sym)
    if not prices: await update.message.reply_text("لا بيانات"); return
    lo,hi=min(prices.values()),max(prices.values())
    lines=[f"💲 {sym}/USDT"]+[f"• {n}: {fmt(p)}" for n,p in sorted(prices.items(),key=lambda z:z[1])]
    lines.append(f"\n📊 الفرق: {100*(hi/lo-1):.2f}%")
    await update.message.reply_text("\n".join(lines),link_preview_options=NO_PREVIEW)


@admin_only
async def cmd_why(update,ctx):
    if not ctx.args: await update.message.reply_text("مثال: /why BTC"); return
    sym=clean_symbol(ctx.args[0])
    try:
        res=await asyncio.to_thread(get_analysis,sym,True); f=res.get("factor_scores") or {}; lv=res["lv"]
        side="شراء 🟢" if res["side"]==1 else "بيع 🔴"
        status="✅ فرصة مؤكدة" if res.get("opportunity") else "👀 رادار فقط (ليست فرصة)"
        lines=[f"🔎 {sym} · محرك v10 · {res.get('source')}",
               f"الحالة: {status} | الاتجاه: {side} | درجة {res['grade']} | نقاط {res['score']}/9",
               f"• نظام 4H: {f.get('regime_4h')} ({'متوافق' if f.get('regime_aligned') else 'غير متوافق'}) | ADX {f.get('adx_4h')}",
               f"• تأكيد 1H: {'نعم' if f.get('confirm_1h') else 'لا'}",
               f"• محفز 15M: {'نعم' if f.get('trigger_15m') else 'لا'} | RVOL {f.get('rvol_15m')}",
               f"• دخول {fmt(lv['entry'])} | وقف {fmt(lv['sl'])} ({100*lv['risk']/lv['entry']:.2f}%) | هدف1 {fmt(lv['tps'][0]['px'])}"]
        for w in res.get("warnings",[])[:4]: lines.append(f"⚠️ {w}")
        pats=res.get("patterns",[])
        if pats: lines.append(f"🕯️ النماذج: {', '.join(p['name'] + '[' + p.get('tf','').upper() + ']' for p in pats[:3])}")
        await update.message.reply_text("\n".join(lines)[:4000])
    except Exception as e: await update.message.reply_text(f"⚠️ {str(e)[:150]}")

@admin_only
async def cmd_users(update,ctx):
    with store.lock: users=list(store.data["users"].values())
    users.sort(key=lambda u:-u.get("last_seen",0))
    lines=[f"👥 ({len(users)})",""]
    for u in users[:30]:
        n=(u.get("name") or "").strip(); un=(u.get("username") or "").strip()
        label=f"{n} (@{un})" if n and un else (n or (f"@{un}" if un else f"ID:{u['id']}"))
        st,_=user_status(int(u["id"]),u)
        icon={"admin":"👑","vip":"💎","trial":"🆓","warning":"⚠️","blocked":"⛔","grace":"🎁"}.get(st,"•")
        lines+=[f"{icon} {label}",f"    📊 {u.get('requests',0)} | نقاط: {u.get('points',0)} | آخر: {time_ago(u.get('last_seen'))}"]
    await update.message.reply_text("\n".join(lines)[:4000],link_preview_options=NO_PREVIEW)

@admin_only
async def cmd_testchannels(update,ctx):
    out=[]
    for name,chat in (("FREE",CHANNEL_ID),("VIP",VIP_CHANNEL_ID)):
        if not chat: out.append(f"❌ {name}"); continue
        try:
            await ctx.bot.send_message(chat,f"✅ اختبار - {BRAND}"); out.append(f"✅ {name}")
        except Exception as e: out.append(f"❌ {name}: {str(e)[:80]}")
    await update.message.reply_text("\n".join(out))

@admin_only
async def cmd_stats(update,ctx):
    since=(time.time()-7*DAY)*1000
    with store.lock: h=[x for x in store.data["history"] if (x.get("closed") or 0)>=since and not x.get("shadow") and x.get("setup")!="RADAR"]
    if not h: await update.message.reply_text("لا صفقات"); return
    R=np.array([x["R"] for x in h]); g,l=R[R>0].sum(),-R[R<=0].sum()
    pf=round(float(g/l),2) if l>0 else 999
    await update.message.reply_text(f"📈 آخر 7 أيام\n\nصفقات: {len(R)} | WR: {100*(R>0).mean():.1f}%\nPF: {pf} | {R.sum():+.1f}R")

@admin_only
async def cmd_history(update,ctx):
    with store.lock: h=[x for x in store.data["history"] if not x.get("shadow") and x.get("setup")!="RADAR"][-15:][::-1]
    if not h: await update.message.reply_text("لا يوجد"); return
    await update.message.reply_text("🗂 آخر 15:\n"+"\n".join(
        f"{'✅' if x['R']>0 else '❌'} #{x['coin']} {x['R']:+.2f}R | {x['result']}" for x in h))

@admin_only
async def cmd_dashboard(update,ctx):
    act=active_signals()
    with store.lock:
        nu=len(store.data["users"]); nv=sum(1 for k in store.data["vip"] if is_vip(int(k)))
    maint="🔧 صيانة" if is_maintenance() else "✅ يعمل"
    msg=(f"🎛 لوحة التحكم — {maint}\n\n👥 {nu} | 💎 VIP: {nv}\n"
         f"📊 نشطة: {len(act)}/{MAX_OPEN}\n💾 {store.remote_msg}\n"
         f"📡 Binance Futures: ✅\n"
         f"📢 FREE {'✅' if CHANNEL_ID else '—'} | VIP {'✅' if VIP_CHANNEL_ID else '—'}\n\n"
         f"🎯 نقاط: {VIP_THRESHOLD}=VIP{VIP_REWARD_DAYS}d | +{POINTS_REFERRAL}/إحالة\n"
         f"🕯️ النماذج: MTF ✅")
    await update.message.reply_text(msg)

@admin_only
async def cmd_addvip(update,ctx):
    try: uid,days=int(ctx.args[0]),int(ctx.args[1])
    except Exception: await update.message.reply_text("/addvip ID DAYS"); return
    exp=add_vip(uid,days); e=dt.datetime.utcfromtimestamp(exp).strftime("%Y-%m-%d")
    await update.message.reply_text(f"✅ VIP {uid} حتى {e}")

@admin_only
async def cmd_removevip(update,ctx):
    try: uid=int(ctx.args[0])
    except Exception: await update.message.reply_text("/removevip ID"); return
    await update.message.reply_text("✅" if remove_vip(uid) else "ليس VIP")

@admin_only
async def cmd_viplist(update,ctx):
    with store.lock: rows=sorted(store.data["vip"].items(),key=lambda kv:kv[1].get("expires",0))
    lines=[f"👑 VIP ({len(rows)})"]
    for uid,v in rows[:40]:
        left=(int(v.get("expires",0))-now_s())//DAY
        lines.append(f"{uid} - {'متبقي '+str(left)+' يوم' if left>=0 else 'منتهي'}")
    await update.message.reply_text("\n".join(lines))

class _FakeUpdate:
    def __init__(self,msg,user):
        self.message=msg; self.effective_user=user; self.callback_query=None


@vip_only
async def cmd_radar(update, ctx):
    """Radar view: confirmed opportunities (trigger fired) + setups still forming (waiting for the 15M trigger)."""
    wait = await update.message.reply_text("⚡ <b>الرادار</b>\n⏳ مسح السوق...", parse_mode=ParseMode.HTML)
    try:
        syms = await asyncio.to_thread(top_symbols, 80)
        hits = await asyncio.to_thread(radar_scan, syms)
        opps = [h for h in hits if h.get("opportunity") and _grade_ok(h.get("grade", "C"))]
        forming = [h for h in hits if not h.get("opportunity")
                   and (h.get("factor_scores") or {}).get("regime_aligned") and (h.get("factor_scores") or {}).get("confirm_1h")]
        if not opps and not forming:
            await wait.edit_text("⚡ لا توجد فرص مؤكدة ولا إعدادات قيد التكوّن حالياً."); return
        lines = [f"⚡ <b>الرادار</b> · {len(opps)} فرصة مؤكدة · {len(forming)} قيد التكوّن", "━━━━━━━━━━━━━━━━", ""]
        for h in opps[:10]:
            side_e = "🟢 LONG" if h["side"] == 1 else "🔴 SHORT"
            cl = coin_link(h["sym"], "binance_fut"); lv = h["lv"]
            lines.append(f"✅ {side_e} <a href='{cl}'>#{h['sym']}</a> · {fmt(h['price'])} · درجة {h['grade']}")
            lines.append(f"   ➡️ {fmt(lv['entry'])} | 🛑 {fmt(lv['sl'])} | 🎯 {fmt(lv['tps'][0]['px'])}")
            lines.append(f"   حجم ×{h['vol_ratio']} | تحرك {h['move']:+.1f}% | 24س {h['ch24']:+.1f}%")
            lines.append("")
            key = f"{h['sym']}:{h['bar_t']}"
            if key not in _radar_seen:
                _radar_seen[key] = time.time()
                if not any(p.get("coin") == h["sym"] for p in active_signals(include_shadow=True) if _is_shadow(p)):
                    try: await asyncio.to_thread(track_signal, h, True)
                    except Exception: pass
        if forming:
            lines.append("👀 <b>قيد التكوّن (بانتظار محفز 15M):</b>")
            for h in forming[:8]:
                lines.append(f"   {'🟢' if h['side'] == 1 else '🔴'} #{h['sym']} · نقاط {h['score']}/9")
            lines.append("")
        lines += [RISK_WARNING_AR, f"👤 {BRAND}"]
        await wait.edit_text("\n".join(lines)[:4000], parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.exception("cmd_radar")
        try: await wait.edit_text(f"⚠️ {str(e)[:150]}")
        except Exception: pass

ADMIN_CMD_MAP={
    "/forcepost":cmd_forcepost,"/clearsignals":cmd_clearsignals,
    "/smartcleanup":cmd_smartcleanup,"/debug":cmd_debug,"/daily":cmd_daily,
    "/cross":cmd_cross,"/predict":cmd_predict,"/whales":cmd_whales,
    "/explosions":cmd_explosions,"/pump":cmd_pump,"/bottom":cmd_bottoms,
    "/shortsradar":cmd_shorts_radar,"/alpha":cmd_alpha,"/scan":cmd_scan,
    "/short":cmd_short,"/bt":cmd_bt,"/btv10":cmd_bt,"/btx":cmd_btx,"/bts":cmd_bts,"/btt":cmd_btt,"/btopt":cmd_btopt,"/v10set":cmd_v10set,"/v10show":cmd_v10show,"/bt50":cmd_bt50,"/users":cmd_users,
    "/viplist":cmd_viplist,"/stats":cmd_stats,"/history":cmd_history,
    "/dashboard":cmd_dashboard,"/testchannels":cmd_testchannels,"/delist":cmd_delist,
    "/golden":cmd_golden,"/share":cmd_share,
    "/alpha_v2":cmd_alpha_radar_v2,"/patterns":cmd_patterns,"/neon":cmd_neon,
    "/radar":cmd_radar,"/spot":cmd_spot,"/plan":cmd_plan,"/active":cmd_active}

ADMIN_ARGS_HINTS={
    "liquidity":"أرسل: /liquidity BTC","futures":"أرسل: /futures BTC",
    "price":"أرسل: /price BTC","why":"أرسل: /why BTC","post":"أرسل: /post BTC (أو /post BTC force)",
    "addvip":"أرسل: /addvip ID DAYS","removevip":"أرسل: /removevip ID",
    "share":"أرسل: /share BTC","patterns":"أرسل: /patterns BTC (أو /patterns بدون رمز للفحص التلقائي)",
    "addpoints":"أرسل: /addpoints ID 5 ترويج"}

async def cb_handler(update,ctx):
    q=update.callback_query
    try: await q.answer()
    except Exception as _ex: log.debug('ignored: %s', _ex)
    if q.data == "hype_radar":
        if q.from_user.id != ADMIN_ID:
            await q.message.reply_text("⛔ للأدمن فقط"); return
        wait = await q.message.reply_text("🔥 رادار الضجة... يجلب الترندات")
        try:
            results = await asyncio.to_thread(hype_radar, 10)
            if not results:
                await wait.edit_text("🔥 لا توجد ترندات حالياً"); return
            txt = build_hype_radar_text(results)
            txt += "\n\n" + RISK_WARNING_AR
            await wait.edit_text(txt[:4000], parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
        except Exception as e:
            await wait.edit_text(f"⚠️ {str(e)[:150]}")
        return
    if q.data.startswith("neon:"):
        if q.from_user.id != ADMIN_ID: return
        sym = q.data.split(":")[1]
        wait = await q.message.reply_text(f"💳 جارٍ توليد بطاقة النيون لـ {sym}...")
        try:
            res = await asyncio.to_thread(get_analysis, sym, True)
            if res.get("wait"):
                await wait.edit_text("⏳ لا توجد صفقة مؤهلة (انتظار)."); return
            card = await asyncio.to_thread(render_trade_card, res, "admin")
            await q.message.reply_photo(photo=card)
            await wait.delete()
        except Exception as e:
            await wait.edit_text(f"⚠️ {str(e)[:150]}")
        return
    if q.data == "neon_card_manual":
        if q.from_user.id != ADMIN_ID: return
        await q.message.reply_text("💳 <b>بطاقة النيون</b>\n\nأرسل: <code>/neon BTC</code>", parse_mode=ParseMode.HTML)
        return
    if q.data == "patterns_chart_manual":
        if q.from_user.id != ADMIN_ID: return
        await q.message.reply_text("🖼️ <b>شارت النماذج</b>\n\nأرسل: <code>/patterns BTC</code>", parse_mode=ParseMode.HTML)
        return
    if q.data=="toggle_maintenance":
        if q.from_user.id!=ADMIN_ID:
            await q.message.reply_text("⛔ للأدمن فقط"); return
        new_state=set_maintenance(not is_maintenance())
        msg="🔧 <b>وضع الصيانة مفعّل</b>" if new_state else "✅ <b>وضع الصيانة معطّل</b>"
        await q.message.reply_text(msg,parse_mode=ParseMode.HTML); return
    if q.data=="toggle_multi_exchange":
        if q.from_user.id!=ADMIN_ID:
            await q.message.reply_text("⛔ للأدمن فقط"); return
        new_state=set_multi_exchange(not is_multi_exchange())
        if new_state: msg=("🌐 <b>تعدد المنصات: مفعّل</b>\n\n✅ سيبحث البوت في جميع المنصات\n✅ سيظهر اسم المنصة المصدر في كل توصية.")
        else: msg=("🛑 <b>تعدد المنصات: معطّل</b>\n\n✅ سيعتمد البوت على Binance فقط.")
        await q.message.reply_text(msg,parse_mode=ParseMode.HTML)
        try: await q.message.edit_reply_markup(reply_markup=keyboard_admin_menu())
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data=="admin_menu":
        if q.from_user.id!=ADMIN_ID: return
        try: await q.message.reply_text(build_admin_menu_text(),reply_markup=keyboard_admin_menu(),parse_mode=ParseMode.HTML)
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data=="my_portfolio":
        await cmd_portfolio(_FakeUpdate(q.message,q.from_user),ctx); return
    if q.data=="my_points":
        rec=store.data["users"].get(str(q.from_user.id),{}); pts=rec.get("points",0)
        bot_username=ctx.application.bot_data.get("username","")
        ref_link=f"https://t.me/{bot_username}?start=ref_{q.from_user.id}" if bot_username else "—"
        await q.message.reply_text(
            f"🎯 <b>نقاطك:</b> {pts}/{VIP_THRESHOLD}\n\n{points_visual(pts)}\n\n"
            f"📢 <b>نشر رابط القناة أو البوت = {POINTS_PROMO} نقاط</b>\n"
            f"👥 <b>دعوة مشترك جديد = {POINTS_REFERRAL} نقطة</b>\n\n"
            f"🔗 <b>رابط البوت (إحالتك):</b>\n<code>{ref_link}</code>\n\n"
            f"📢 <b>قناة التوصيات:</b>\n<code>{CHANNEL_LINK}</code>",
            parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
        return
    if q.data=="my_ref":
        bot_username=ctx.application.bot_data.get("username","")
        if not bot_username:
            await q.message.reply_text("⚠️ جرب بعد دقيقة"); return
        ref_link=f"https://t.me/{bot_username}?start=ref_{q.from_user.id}"
        rec=store.data["users"].get(str(q.from_user.id),{}); pts=rec.get("points",0)
        await q.message.reply_text(
            f"🔗 <b>رابط الإحالة:</b>\n\n<code>{ref_link}</code>\n\n"
            f"💰 كل مشترك جديد = <b>{POINTS_REFERRAL} نقطة</b>\n\n"
            f"🎯 نقاطك: <b>{pts}/{VIP_THRESHOLD}</b>\n{points_visual(pts)}",
            parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
        return
    if q.data=="close_menu":
        try: await q.message.delete()
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data.startswith("calc_risk:"):
        sym=q.data.split(":")[1]; ctx.user_data['awaiting_risk']=sym
        await q.message.reply_text(
            f"🧮 <b>حاسبة إدارة المخاطر ({sym})</b>\n\nأرسل رأس مالك ونسبة المخاطرة (مفصولة بمسافة).\n"
            f"مثال: <code>1000 2</code>",parse_mode=ParseMode.HTML); return
    if q.data.startswith("add_port:"):
        sym=q.data.split(":")[1]; ctx.user_data['awaiting_port']=sym
        await q.message.reply_text(
            f"📊 <b>إضافة {sym} للمحفظة</b>\n\nكم المبلغ الذي استثمرته بالدولار؟ (مثال: <code>100</code>)",
            parse_mode=ParseMode.HTML); return
    if q.data.startswith("news:"):
        sym=q.data.split(":")[1]
        news=await asyncio.to_thread(get_crypto_news,sym)
        await q.message.reply_text(f"📰 <b>آخر أخبار {sym}:</b>\n\n{news}",parse_mode=ParseMode.HTML); return
    if q.data.startswith("share:"):
        sym=q.data.split(":")[1]
        try:
            res=await asyncio.to_thread(get_analysis,sym,True)
            if res.get("wait"):
                await q.message.reply_text("⏳ لا توجد صفقة مؤهلة حالياً."); return
            await q.message.reply_text("👇 اختر المنصة لنسخ المنشور:",reply_markup=keyboard_share_post(res))
        except Exception: pass
        return
    if q.data.startswith("pat:"):
        if q.from_user.id!=ADMIN_ID: return
        try:
            sym=q.data.split(":")[1]; res=await asyncio.to_thread(get_analysis,sym,True); pats=res.get("patterns",[])
            if not pats:
                await q.message.reply_text(f"🕯️ #{sym} — لا نماذج مؤكدة."); return
            lines=[f"🕯️ <b>نماذج #{sym} (MTF)</b>",""]
            for p in pats:
                emoji="🟢" if p["bias"]=="bullish" else ("🔴" if p["bias"]=="bearish" else "⚪")
                tf_lbl=f" [{p.get('tf','').upper()}]" if p.get('tf') else ""
                lines.append(f"{emoji} {p['name']}{tf_lbl} — {p['bias']}")
                if p.get("neckline"): lines.append(f"   📏 Neckline: {fmt(p['neckline'])}")
            await q.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data.startswith("refs:"):
        try:
            msg=("🌐 <b>منصات التداول المعتمدة</b>\n\n💡 <b>لماذا التسجيل عبر البوت؟</b>\n"
                "✅ رسوم تداول أقل\n✅ دعم فني من فريقنا\n✅ دعم استمرارية القناة المجانية\n\n👇 اختر منصتك للتسجيل:")
            await q.message.reply_text(msg,reply_markup=keyboard_refs("binance_fut"),parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data.startswith("adm_args:"):
        if q.from_user.id!=ADMIN_ID: return
        key=q.data.split(":",1)[1]
        await q.message.reply_text(f"✏️ {ADMIN_ARGS_HINTS.get(key,'الأمر مع الوسيط')}"); return
    if q.data.startswith("adm:"):
        if q.from_user.id!=ADMIN_ID: return
        cmd_name=q.data.split(":",1)[1]; fn=ADMIN_CMD_MAP.get(cmd_name)
        if not fn:
            await q.message.reply_text("⚠️ غير معروف"); return
        fake=_FakeUpdate(q.message,q.from_user)
        try: await fn(fake,ctx)
        except Exception as e:
            try: await q.message.reply_text(f"⚠️ {str(e)[:150]}")
            except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data in ("vip","vip_page"):
        kb=InlineKeyboardMarkup([
            [_btn("💎 الانضمام لقناة VIP ✨",url=VIP_INVITE_LINK)],
            [_btn("🆓 قناة التوصيات المجانية",url=CHANNEL_LINK)],
            [_btn("🎁 تجربة يوم",callback_data="vip_trial")]])
        try: await q.message.reply_text(build_vip_page(),reply_markup=kb)
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data=="vip_trial":
        u=q.from_user; uid=str(u.id)
        with store.lock:
            u_rec=store.data["users"].get(uid,{})
            if u_rec.get("trial_used"):
                await q.message.reply_text("⛔ استخدمت التجربة",
                    reply_markup=InlineKeyboardMarkup([[_btn("💎 اشترك",url=VIP_INVITE_LINK)]])); return
            u_rec["trial_used"]=True; store.data["users"][uid]=u_rec; store.save("users")
        add_vip(u.id,1)
        await q.message.reply_text("🎉 تجربة VIP 24 ساعة!",
            reply_markup=InlineKeyboardMarkup([[_btn("📋 البدء",callback_data="vip_menu")]])); return
    if q.data=="vip_menu":
        u=q.from_user; rec=store.data["users"].get(str(u.id),{}); st,_=user_status(u.id,rec)
        if st not in ("admin","vip","trial","warning"):
            await q.message.reply_text("🔒 VIP فقط"); return
        await q.message.reply_text(build_vip_menu_text(),reply_markup=keyboard_vip_menu()); return
    if q.data.startswith("vip_cmd_args:"):
        key=q.data.split(":",1)[1]
        u=q.from_user; rec=store.data["users"].get(str(u.id),{}); st,_=user_status(u.id,rec)
        if st not in ("admin","vip","trial","warning"):
            await q.message.reply_text("🔒 VIP فقط"); return
        hints={"liquidity":"💧 /liquidity BTC","futures":"📊 /futures BTC"}
        await q.message.reply_text(f"✏️ {hints.get(key,'الأمر مع الرمز')}"); return
    if q.data.startswith("vip_cmd:"):
        cmd=q.data.split(":",1)[1]
        u=q.from_user; rec=store.data["users"].get(str(u.id),{}); st,_=user_status(u.id,rec)
        if st not in ("admin","vip","trial","warning"):
            await q.message.reply_text("🔒 VIP فقط"); return
        try:
            fake=_FakeUpdate(q.message,q.from_user)
            handlers={"/predict":cmd_predict,"/whales":cmd_whales,"/explosions":cmd_explosions,
                "/pump":cmd_pump,"/bottom":cmd_bottoms,"/shortsradar":cmd_shorts_radar,
                "/alpha":cmd_alpha,"/active":cmd_active,"/golden":cmd_golden,"/daily":cmd_daily,
                "/alpha_v2":cmd_alpha_radar_v2,"/radar":cmd_radar,"/spot":cmd_spot}
            fn=handlers.get(cmd)
            if fn: await fn(fake,ctx)
        except Exception as e:
            try: await q.message.reply_text(f"⚠️ {str(e)[:150]}")
            except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data.startswith("ind:"):
        if q.from_user.id!=ADMIN_ID: return
        try:
            sym=q.data.split(":")[1]; res=await asyncio.to_thread(get_analysis,sym)
            await q.message.reply_text(build_admin_extras(res))
        except Exception as e: await q.message.reply_text(f"⚠️ {str(e)[:200]}")
        return
    if q.data.startswith("liq:"):
        if q.from_user.id!=ADMIN_ID: return
        try:
            sym=q.data.split(":")[1]; liq=await asyncio.to_thread(liquidity_radar,sym)
            if not liq: await q.message.reply_text("لا بيانات"); return
            bias="🟢" if liq["ratio"]>0.55 else ("🔴" if liq["ratio"]<0.45 else "⚖️")
            await q.message.reply_text(f"💧 {sym}\n🟢 ${liq['bids']:,.0f}\n🔴 ${liq['asks']:,.0f}\n{liq['ratio']*100:.1f}% | {bias}")
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data.startswith("whale:"):
        if q.from_user.id!=ADMIN_ID: return
        try:
            sym=q.data.split(":")[1]; w,largest,bv,sv=await asyncio.to_thread(whale_radar,sym)
            if w is None: await q.message.reply_text("لا بيانات"); return
            total=bv+sv; buy_pct=(bv/total*100) if total>0 else 0
            raw_direction="شراء" if buy_pct>55 else ("بيع" if buy_pct<45 else "مختلط")
            ai=await asyncio.to_thread(get_analysis,sym)
            ai_direction="🟢 شراء" if ai["side"]==1 else "🔴 بيع"
            await q.message.reply_text(f"🐋 {sym}\n📊 {w} صفقة كبيرة\n💰 ${largest:,.0f}\nتدفق السوق: {raw_direction} {buy_pct:.0f}%\n🤖 قرار AI: {ai_direction} · {ai['grade']}")
        except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data.startswith("btcb:"):
        if q.from_user.id!=ADMIN_ID: return
        sym=q.data.split(":")[1]
        if _BT_BUSY[0]:
            await q.message.reply_text("⏳ يوجد اختبار آخر قيد التشغيل؛ انتظر."); return
        _BT_BUSY[0]=True
        try:
            per,a,b,errors=await asyncio.to_thread(backtest_many,[sym],1.0,1)
            text,_=bt_report(per,a,b,sym,errors)
            await q.message.reply_text(text[:4000])
        except Exception as ex:
            log.warning("btcb failed: %s",ex)
            try: await q.message.reply_text(f"⚠️ {str(ex)[:150]}")
            except Exception: pass
        finally:
            _BT_BUSY[0]=False
        return
    if q.data.startswith(("tv:","chart:")):
        parts=q.data.split(":"); sym=parts[1]; tf=parts[2] if len(parts)>2 and parts[2] in TV_IV else None
        if cb_throttled(q.from_user.id,4):
            await q.message.reply_text("⏳ انتظر قليلاً ثم أعد المحاولة"); return
        user=touch_user(q.from_user,"tvchart"); st,_=user_status(q.from_user.id,user)
        if st=="blocked":
            await q.message.reply_text(t("blocked",get_user_lang(q.from_user.id),contact=(CONTACT_LINK or CHANNEL_LINK))); return
        lang=get_user_lang(q.from_user.id)
        wait_m=await q.message.reply_text("📈 جارٍ رسم الشارت والنماذج..." if lang=="ar" else "📈 Drawing chart & patterns...")
        try:
            res=await asyncio.to_thread(get_analysis,sym)
            tf=tf or res["tf"]
            img,pats=await asyncio.to_thread(build_tv_for,sym,tf,res)
            await ctx.bot.send_photo(q.message.chat.id,photo=img,caption=tv_caption(sym,tf,pats,lang)[:1000],
                                     parse_mode=ParseMode.HTML,reply_markup=tv_keyboard(sym,tf,lang),
                                     protect_content=(st!="admin" and PROTECT))
        except PairNotFound: await q.message.reply_text(t("not_found",lang,sym=sym))
        except NoData: await q.message.reply_text(t("no_data",lang))
        except Exception:
            log.exception("tvchart"); await q.message.reply_text("⚠️ تعذر إنشاء الشارت الآن" if lang=="ar" else "⚠️ Couldn't build the chart now")
        finally:
            try: await wait_m.delete()
            except Exception as _ex: log.debug('ignored: %s', _ex)
        return
    if q.data.startswith("pchart:"):
        parts=q.data.split(":"); sym=parts[1]
        if q.from_user.id != ADMIN_ID:
            await q.message.reply_text("⛔ للأدمن فقط"); return
        if cb_throttled(q.from_user.id): await q.message.reply_text("⏳ انتظر قليلاً ثم أعد المحاولة"); return
        try:
            res=await asyncio.to_thread(get_analysis,sym)
            img=await asyncio.to_thread(render_pattern_chart,res,"admin")
            await ctx.bot.send_photo(q.message.chat.id,photo=img)
        except Exception:
            log.exception("pchart"); await q.message.reply_text("⚠️ تعذر إنشاء الشارت الآن")
        return
    if q.data.startswith("tf:"):
        parts=q.data.split(":"); sym,tf=parts[1],parts[2]
        if cb_throttled(q.from_user.id): await q.message.reply_text("⏳ انتظر قليلاً ثم أعد المحاولة"); return
        user=touch_user(q.from_user,"refresh"); st,_=user_status(q.from_user.id,user)
        tier="admin" if st=="admin" else ("vip" if st=="vip" else "free")
        lang=get_user_lang(q.from_user.id)
        _candle_cache.pop((sym,tf,450,215,False,None),None); _analysis_cache.pop(sym,None)
        try:
            res=await asyncio.to_thread(get_analysis,sym); source=res.get("source","binance_fut")
            kb=keyboard(sym,res["tf"],tier,source,lang)
            img=await asyncio.to_thread(render_chart,res,tier)
            await ctx.bot.send_photo(q.message.chat.id,photo=img,protect_content=(st!="admin" and PROTECT),reply_markup=kb)
            if tier=="admin" and not res.get("wait"): await send_admin_copy(q.message,res)
            cur_pts=store.data["users"].get(str(q.from_user.id),{}).get("points",0)
            bot_un=ctx.application.bot_data.get("username","")
            await send_points_flash(q.message,cur_pts,q.from_user.id,bot_un)
        except Exception as _ex: log.debug('ignored: %s', _ex)

def free_event_text(coin,tf,side,e,R,trade):
    k=e["kind"]
    if k in ("ENTRY","BE_MOVED"): return None
    return event_text(coin,tf,side,e,R,"free",trade=trade)

def grade_winrate(grade):
    with store.lock: h=[x for x in store.data["history"] if x.get("grade")==grade and not x.get("shadow") and x.get("setup")!="RADAR"]
    if len(h)<20: return None,len(h)
    wins=sum(1 for x in h if (x.get("R") or 0)>0)
    return round(100*wins/len(h),1),len(h)

def admin_stats_line(res):
    wr,n=grade_winrate(res.get("grade"))
    if wr is None:
        return f"📊 [أدمن] درجة {res.get('grade')}: بيانات غير كافية ({n}/20 صفقة مغلقة)"
    return f"📊 [أدمن] درجة {res.get('grade')}: نجاح تاريخي {wr}% من {n} صفقة"

def eth_exchange_flows(hours=1,min_eth=ETH_MIN_TX):
    if not ETHERSCAN_KEY or not ETH_WATCH: return []
    out=[]; start_ts=time.time()-hours*3600
    for addr in ETH_WATCH[:10]:
        try:
            r=requests.get("https://api.etherscan.io/v2/api",
                params={"chainid":1,"module":"account","action":"txlist","address":addr,
                    "startblock":0,"endblock":99999999,"page":1,"offset":50,"sort":"desc","apikey":ETHERSCAN_KEY},timeout=10)
            data=r.json()
            if str(data.get("status"))!="1": continue
            for tx in data.get("result",[]):
                if int(tx.get("timeStamp",0))<start_ts: break
                eth=int(tx.get("value",0))/1e18
                if eth<min_eth: continue
                frm=(tx.get("from") or "").lower(); to=(tx.get("to") or "").lower()
                if to==addr: flow="إيداع في البورصة (ضغط بيع محتمل)"
                elif frm==addr: flow="سحب من البورصة (تجميع محتمل)"
                else: continue
                out.append(f"• ETH {eth:,.0f} — {flow}")
        except Exception: continue
        time.sleep(0.25)
    return out[:10]

def whale_alert_recent(min_usd=1_000_000,minutes=60):
    if not WHALE_ALERT_KEY: return []
    try:
        start=int(time.time())-minutes*60
        r=requests.get("https://api.whale-alert.io/v1/transactions",
            params={"api_key":WHALE_ALERT_KEY,"min_value":int(min_usd),"start":start},timeout=10)
        if r.status_code!=200: return []
        out=[]
        for tx in r.json().get("transactions",[]):
            sym=(tx.get("symbol") or "").upper(); usd=float(tx.get("amount_usd") or 0)
            frm=(tx.get("from") or {}).get("owner_type","unknown"); to=(tx.get("to") or {}).get("owner_type","unknown")
            if to=="exchange" and frm!="exchange": flow="إيداع في بورصة (ضغط بيع محتمل)"
            elif frm=="exchange" and to!="exchange": flow="سحب من بورصة (تجميع محتمل)"
            else: flow="تحويل بين محافظ"
            out.append(f"• {sym} ${usd:,.0f} — {flow}")
        return out
    except Exception: return []

async def on_error(update,ctx):
    err=ctx.error
    if err.__class__.__name__=="Conflict":
        log.error("⚠️ 409 Conflict: نسخة أخرى من البوت تعمل بنفس التوكن (Railway: أوقف النشر القديم/اجعل replicas=1، وأوقف أي نسخة محلية)")
        return
    log.error("err: %s",err,exc_info=err)

async def log_updates(update,ctx):
    q=update.callback_query
    if q: log.info("🔘 callback %s من %s",q.data,q.from_user.id)

async def cmd_version(update,ctx):
    if not update.message: return
    ai_state = "مفعّل" if RYMA_AI_ENABLED else "متوقف"
    ml_state = "مفعّل" if RYMA_ML_ENABLED and os.path.isfile(RYMA_ML_MODEL_PATH) else "غير مهيأ"
    await update.message.reply_text(
        f"💎 Ryma Crypto\nالإصدار: {BOT_VERSION}\nطبقة AI: {ai_state}\nنموذج ML: {ml_state}\nالتنفيذ الآلي: معطّل (تنبيهات فقط)"
    )


async def cmd_botinfo(update,ctx):
    if update.effective_user.id!=ADMIN_ID: return
    w=await ctx.bot.get_webhook_info()
    await update.message.reply_text(
        f"version: {BOT_VERSION}\nwebhook: {w.url or 'لا يوجد ✅'}\nallowed_updates: {w.allowed_updates or 'الافتراضي ✅'}\n"
        f"pending: {w.pending_update_count}\nlast_error: {w.last_error_message or '-'}")

async def on_text(update,ctx):
    if not update.message or not update.message.text: return
    text=update.message.text.strip(); uid=str(update.effective_user.id)
    if ctx.user_data is None: ctx.user_data={}
    if re.search(r'[؀-ۿ]',text): lang="ar"
    elif len(text.split())>=3: lang="en"
    else: lang=get_user_lang(update.effective_user.id)
    set_user_lang(update.effective_user.id,lang)
    st,ok=await gate(update)
    if not ok: return
    if 'awaiting_risk' in ctx.user_data:
        sym=ctx.user_data.pop('awaiting_risk')
        try:
            cap,risk_pct=map(float,text.split())
            res=await asyncio.to_thread(get_analysis,sym,True)
            if res.get("wait"):
                await update.message.reply_text("⏳ لا توجد صفقة حالياً لهذه العملة، فلا حساب مخاطر." if lang!="en" else "⏳ No active setup for this coin, so no risk calc."); return
            entry=res['lv']['entry']; sl=res['lv']['sl']
            risk_amount=cap*(risk_pct/100); price_diff=abs(entry-sl)
            position_size=risk_amount/price_diff; position_value=position_size*entry
            leverage=position_value/cap if cap>0 else 0
            if lang=="en":
                msg=(f"🧮 <b>Risk Management Result for {sym}:</b>\n\n💰 Capital: ${cap}\n"
                    f"🛑 Risk ({risk_pct}%): ${risk_amount:.2f}\n➡️ Position Size: {position_size:.4f}\n"
                    f"💵 Position Value: ${position_value:.2f}\n\n⚙️ <b>Suggested Leverage:</b> {leverage:.1f}x\n"
                    f"<i>(Always use Isolated margin)</i>")
            else:
                msg=(f"🧮 <b>نتيجة إدارة المخاطر لـ {sym}:</b>\n\n💰 رأس المال: ${cap}\n"
                    f"🛑 المخاطرة ({risk_pct}%): ${risk_amount:.2f}\n➡️ حجم العقد: {position_size:.4f}\n"
                    f"💵 قيمة الصفقة: ${position_value:.2f}\n\n⚙️ <b>الرافعة المقترحة:</b> {leverage:.1f}x\n"
                    f"<i>(استخدم دائماً العزل Isolated)</i>")
            await update.message.reply_text(msg,parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text("⚠️ Invalid format (1000 2)" if lang=="en" else "⚠️ صيغة خاطئة (مثال: 1000 2)")
        return
    if 'awaiting_port' in ctx.user_data:
        sym=ctx.user_data.pop('awaiting_port')
        try:
            amount=float(text)
            res=await asyncio.to_thread(get_analysis,sym,True); entry=res['price']
            with store.lock:
                if uid not in store.data["portfolios"]: store.data["portfolios"][uid]=[]
                store.data["portfolios"][uid].append({"sym":sym,"entry":entry,"amount":amount})
                store.save("portfolios")
            await update.message.reply_text(
                f"✅ {sym} added to your portfolio (${amount}).\n/portfolio" if lang=="en"
                else f"✅ تمت إضافة {sym} إلى محفظتك (${amount}).\n/portfolio")
        except Exception:
            await update.message.reply_text("⚠️ Send a valid number (100)" if lang=="en" else "⚠️ أرسل رقماً صحيحاً (مثال: 100)")
        return
    sym=clean_symbol(text.split()[0])
    if not sym:
        await update.message.reply_text(t("invalid_symbol",lang)); return
    if sym in EXCLUDE_TICKERS:
        await update.message.reply_text(t("not_supported",lang)); return
    wait=await update.message.reply_text(t("analyzing",lang,sym=sym))
    try:
        res=await asyncio.to_thread(get_analysis,sym)
        tier="admin" if st=="admin" else ("vip" if st=="vip" else "free")
        
        kb=keyboard(sym,res["tf"],tier,"binance_fut",lang)
        text_caption = caption_core(res, tier, lang)
        img=await asyncio.to_thread(render_chart,res,tier)
        await update.message.reply_photo(photo=img, reply_markup=kb)
        await update.message.reply_text(text_caption, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
        
        if tier == "admin" and not res.get("wait"):
            await send_admin_copy(update.message, res)
            
        cur_pts=store.data["users"].get(uid,{}).get("points",0)
        bot_un=ctx.application.bot_data.get("username","")
        await send_points_flash(update.message,cur_pts,update.effective_user.id,bot_un)
    except PairNotFound: await update.message.reply_text(t("not_found",lang,sym=sym))
    except NoData: await update.message.reply_text(t("no_data",lang))
    except Exception:
        log.exception("handle"); await update.message.reply_text(t("error",lang))
    finally:
        try: await wait.delete()
        except Exception as _ex: log.debug('ignored: %s', _ex)

# ======================= أوامر عامة إضافية (من النسخة الخفيفة) =======================
def _http_json(url,timeout=15):
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=timeout); r.raise_for_status(); return r.json()

def _big(n):
    for u,d in (("T",1e12),("B",1e9),("M",1e6),("K",1e3)):
        if abs(n)>=d: return f"{n/d:.2f}{u}"
    return f"{n:.0f}"

async def cmd_fear(update,ctx):
    touch_user(update.effective_user,"/fear")
    try:
        d=(await asyncio.to_thread(_http_json,"https://api.alternative.me/fng/?limit=2"))["data"]
        await update.message.reply_text(f"😱 <b>مؤشر الخوف والطمع</b>\nالآن: <b>{d[0]['value']}</b> — {d[0]['value_classification']}\n"
                                        f"أمس: {d[1]['value']} — {d[1]['value_classification']}",parse_mode=ParseMode.HTML)
    except Exception: await update.message.reply_text("⚠️ تعذر جلب المؤشر حالياً")

async def cmd_market(update,ctx):
    touch_user(update.effective_user,"/market")
    try:
        g=(await asyncio.to_thread(_http_json,"https://api.coingecko.com/api/v3/global"))["data"]
        p=g["market_cap_percentage"]
        await update.message.reply_text(
            f"🌍 <b>السوق</b>\nالقيمة السوقية: ${_big(g['total_market_cap']['usd'])} "
            f"({g['market_cap_change_percentage_24h_usd']:+.2f}% / 24س)\n"
            f"هيمنة BTC: {p.get('btc',0):.1f}% | ETH: {p.get('eth',0):.1f}%\n"
            f"حجم 24س: ${_big(g['total_volume']['usd'])}",parse_mode=ParseMode.HTML)
    except Exception: await update.message.reply_text("⚠️ تعذر جلب بيانات السوق حالياً")

async def cmd_top(update,ctx):
    touch_user(update.effective_user,"/top")
    try:
        rows=await asyncio.to_thread(binance_futures_all_tickers)
        rows=[r for r in (rows or []) if r["volume"]>20e6]
        rows.sort(key=lambda r:-r["change"])
        f=lambda r:f"• {r['symbol']}: {r['change']:+.2f}% (${_big(r['volume'])})"
        await update.message.reply_text("🚀 <b>الأكثر ارتفاعاً</b>\n"+"\n".join(map(f,rows[:7]))+
                                        "\n\n📉 <b>الأكثر انخفاضاً</b>\n"+"\n".join(map(f,rows[-7:][::-1])),parse_mode=ParseMode.HTML)
    except Exception: await update.message.reply_text("⚠️ تعذر جلب البيانات حالياً")

async def cmd_tools(update,ctx):
    touch_user(update.effective_user,"/tools")
    await update.message.reply_text(
        "🧰 <b>أدوات مفيدة</b>\n• coinmarketcap.com — الأسعار\n• coingecko.com — بيانات اجتماعية\n"
        "• tradingview.com — الرسوم والتحليل\n• defillama.com — القيمة المقفلة DeFi\n"
        "• cryptoquant.com — تحليلات on-chain\n• token.unlocks.app — فتح الرموز\n"
        "• arkhamintelligence.com — تتبع المحافظ\n• dappradar.com — التطبيقات اللامركزية",
        parse_mode=ParseMode.HTML,link_preview_options=NO_PREVIEW)

async def cmd_riskcalc(update,ctx):
    touch_user(update.effective_user,"/risk")
    try:
        cap,rk,entry,sl=[float(x) for x in ctx.args[:4]]
        dist=abs(entry-sl); amt=cap*rk/100; size=amt/dist
        await update.message.reply_text(f"🧮 <b>حجم الصفقة</b>\nالمخاطرة: ${amt:.2f}\nالكمية: <code>{size:.6g}</code>\n"
                                        f"قيمة الصفقة: ${size*entry:,.2f}",parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("الاستخدام: <code>/risk رأس_المال نسبة_المخاطرة دخول وقف</code>\nمثال: /risk 1000 1 65000 63500",
                                        parse_mode=ParseMode.HTML)

PUBLIC_COMMANDS=[("start","ابدأ / Start"),("help","المساعدة / Help"),("myid","رقمي / My ID"),
                 ("vip","VIP"),("menu","قائمتي / Menu 📋"),("portfolio","محفظتي / Portfolio 📊"),
                 ("points","نقاطي / Points 🎯"),("myref","رابط الإحالة / Referral 🔗"),
                 ("fear","الخوف والطمع"),("market","حالة السوق"),("top","الأكثر ارتفاعاً"),("risk","حاسبة المخاطر"),("spot","فرص السبوت"),("plan","خطة DCA/Grid")]


def info_dca_plan(entry, capital=1000.0, slices=3, step_pct=4.0):
    """خطة DCA معلوماتية فقط — لا تنفّذ أوامر."""
    levels = []
    per = capital / max(1, slices)
    for i in range(slices):
        px = entry * (1 - (i * step_pct / 100.0))
        levels.append(dict(n=i+1, price=round(px, 8), amount=round(per, 2), qty=round(per/px, 6) if px>0 else 0))
    avg = sum(x["price"]*x["amount"] for x in levels) / capital if capital else entry
    return dict(levels=levels, avg_entry=round(avg, 8), capital=capital, note="معلومات فقط — لا تنفيذ تلقائي")


def info_grid_plan(mid, capital=1000.0, grids=6, spacing_pct=1.5):
    """خطة Grid معلوماتية فقط — مستويات للمراقبة اليدوية."""
    half = grids // 2
    levels = []
    per = capital / max(1, grids)
    for i in range(-half, half+1):
        if i == 0 and grids % 2 == 0:
            continue
        px = mid * (1 + i * spacing_pct / 100.0)
        side = "شراء" if i < 0 else ("بيع" if i > 0 else "محور")
        levels.append(dict(side=side, price=round(px, 8), amount=round(per, 2)))
    return dict(levels=levels[:grids], mid=mid, capital=capital, note="معلومات فقط — لا تنفيذ تلقائي")


def get_crypto_news(symbol):
    try:
        url=f"https://min-api.cryptocompare.com/data/v2/news/?lang=EN&categories={symbol}"
        r=requests.get(url,timeout=5); data=r.json()
        if data.get('Data'): return data['Data'][0]['title']
    except Exception as _ex: log.debug('ignored: %s', _ex)
    return "لا توجد أخبار هامة حالياً."

# ============ رادار الفرص المبكرة (وضع الظل) ============
_radar_seen = {}



def spot_opportunities(limit=12):
    """Spot watch-list built from the SAME v10 engine: LONG side, 4H regime bullish, 1H confirmed.
    (The previous version called the engine without 4H/15M context, raised NoData for every coin and always returned nothing.)"""
    out=[]
    try: rows=binance_futures_all_tickers() or []
    except Exception: rows=[]
    candidates=[]
    for x in rows:
        try:
            sym=x["symbol"]; price=float(x["price"]); vol=float(x["volume"])
            if sym in STABLES or sym in EXCLUDE_TICKERS or sym in DAILY_EXCLUDE or price<=0 or vol<1_000_000: continue
            candidates.append((vol,sym,float(x.get("change",0))))
        except Exception: continue
    candidates.sort(reverse=True)
    for _,sym,ch24 in candidates[:max(30,limit*4)]:
        try:
            r=get_analysis(sym)
            f=(r or {}).get("factor_scores") or {}
            if not r or r["side"]!=1 or f.get("regime_4h")!="bullish" or not f.get("confirm_1h"): continue
            daily=add_indicators(get_candles(sym,"1d",100,ttl=600,min_bars=40),100)
            close=daily["close"]; price=float(r["price"]); lv=r["lv"]
            low60=float(daily["low"].tail(60).min())
            out.append(dict(sym=sym,price=price,ch24=round(ch24,1),
              ch7=round((price/float(close.iloc[-7])-1)*100,1),ch30=round((price/float(close.iloc[-30])-1)*100,1) if len(close)>=30 else 0.0,
              rsi=round(float(daily["rsi"].iloc[-1]),1) if pd.notna(daily["rsi"].iloc[-1]) else 50.0,
              score=r["score"],side=1,horizon="1–2 شهر",grade=r["grade"],
              note="قراءة v10 (نظام 4H صاعد + تأكيد 1H) — للمراقبة فقط، لا تنفيذ تلقائي",
              reasons=list(r.get("reasons",[])),low60=low60,dist_low=round((price/low60-1)*100,1) if low60>0 else 0,
              plan=dict(buy1=price,buy2=max(price-1.2*lv["atr"],low60),buy3=max(price-2.2*lv["atr"],low60*0.98),
                invalid=lv["sl"],tp1=lv["tps"][2]["px"],tp2=lv["tps"][3]["px"],atr=lv["atr"])))
            if len(out)>=limit*2: break
        except Exception as ex: log.debug("spot radar %s: %s",sym,ex)
    out.sort(key=lambda x:({"A":3,"B":2,"C":1}.get(x["grade"],0),x["score"]),reverse=True)
    return out[:limit]

def build_spot_text(rows, lang="ar"):
    if not rows:
        return "🌱 لا توجد فرص سبوت مؤهلة حالياً." if lang != "en" else "🌱 No qualifying spot setups now."
    lines = [
        "🌱 <b>فرص السبوت (أفق 1–2 شهر)</b>",
        "📋 تنبيه ومعلومات فقط — البوت لا ينفّذ أي صفقة.",
        "تجميع حذر محتمل بعد هبوط، مع خطة مستويات للمراقبة.",
        "━━━━━━━━━━━━━━━━",
        ""
    ]
    for r in rows[:10]:
        plan = r.get("plan") or {}
        lines.append(f"• <b>#{r['sym']}</b> · ${r['price']:.6g} · نقاط {r['score']}")
        lines.append(f"  30ي {r['ch30']:+.1f}% | 7ي {r['ch7']:+.1f}% | RSI {r['rsi']} | قرب القاع {r.get('dist_low', '—')}%")
        if r.get("reasons"):
            lines.append(f"  ✓ {' · '.join(r['reasons'][:4])}")
        if plan:
            lines.append(f"  📥 تجميع مقترح: {plan.get('buy1')} / {plan.get('buy2')} / {plan.get('buy3')}")
            lines.append(f"  🎯 أهداف مراقبة: {plan.get('tp1')} → {plan.get('tp2')}")
            lines.append(f"  🛑 إبطال الفكرة: {plan.get('invalid')}")
        lines.append(f"  <i>{r.get('note','')}</i>")
        lines.append("")
    lines += [
        "⚠️ ليست نصيحة مالية ولا أمر شراء.",
        "البوت للتنبيه والتحليل فقط — التنفيذ قرارك اليدوي.",
        RISK_WARNING_AR
    ]
    return chr(10).join(lines)


def radar_scan(symbols):
    """Early-opportunity radar ranked by the canonical AI signal engine."""
    out=[]
    for sym in symbols:
        try:
            r=get_analysis(sym)
            if not r or not r.get("lv"): continue
            d=r.get("df")
            move=float(d["close"].pct_change(2).iloc[-1]*100) if d is not None and len(d)>2 else 0.0
            v=d["volume"] if d is not None and "volume" in d else None
            vol_ratio=float(v.iloc[-1]/v.tail(21).iloc[:-1].mean()) if v is not None and len(v)>20 and v.tail(21).iloc[:-1].mean()>0 else 0.0
            try: _p,ch24,_c7=ticker_change(sym)
            except Exception: ch24=0.0
            hit=dict(r)
            hit.update(move=round(move,2),vol_ratio=round(vol_ratio,2),ch24=round(float(ch24 or 0),2),
                       engine_aligned=True,ai_radar=True)
            out.append(hit)
        except Exception as ex: log.debug("AI radar %s: %s",sym,ex)
    out.sort(key=lambda x:({"A+":4,"A":3,"B":2,"C":1}.get(x.get("grade"),0),float(x.get("score",0))),reverse=True)
    return out


async def shadow_loop(app):
    """Internal paper tracking of CONFIRMED v10 opportunities. Never published; reported by /shadow only."""
    await asyncio.sleep(120)
    while True:
        try:
            cutoff = time.time() - 48 * 3600
            for k in [k for k, t in _radar_seen.items() if t < cutoff]: _radar_seen.pop(k, None)
            syms = await asyncio.to_thread(top_symbols, 80)
            hits = await asyncio.to_thread(radar_scan, syms)
            new = []
            for hit in hits:
                if not hit.get("opportunity") or not _grade_ok(hit.get("grade", "C")): continue
                key = f"{hit['sym']}:{hit['bar_t']}"
                if key in _radar_seen: continue
                _radar_seen[key] = time.time()
                shadows = [p for p in active_signals(include_shadow=True) if _is_shadow(p)]
                if any(p.get("coin") == hit["sym"] for p in shadows) or len(shadows) >= SHADOW_MAX_OPEN: continue
                await asyncio.to_thread(track_signal, hit, True)
                new.append(hit)
            if new and ADMIN_ID:
                lines = [f"🧪 <b>الظل</b> · {len(new)} فرصة v10 مؤكدة (تتبع داخلي)", "━━━━━━━━━━━━━━━━"]
                for h in new:
                    lines.append(f"{'🟢 LONG' if h['side'] == 1 else '🔴 SHORT'} <b>#{h['sym']}</b> | {fmt(h['price'])} | {h['grade']}")
                try: await app.bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
                except Exception as _ex: log.debug("shadow notify: %s", _ex)
        except asyncio.CancelledError: raise
        except Exception: log.exception("shadow_loop")
        await asyncio.sleep(CYCLE_RADAR)



async def cmd_shadow(update, ctx):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    with store.lock:
        hist = [x for x in store.data["history"] if x.get("setup") == "RADAR"]
        act = [p for p in store.data["signals"] if p.get("setup") == "RADAR" and p.get("state") in ("pending", "open")]
    rs = [x["R"] for x in hist if x.get("R") is not None]
    wins = sum(1 for r in rs if r > 0)
    gross = sum(r for r in rs if r > 0); loss = -sum(r for r in rs if r <= 0)
    pf = round(gross / loss, 2) if loss > 0 else "—"
    await update.message.reply_text(
        f"🧪 وضع الظل — الرادار\nمغلقة: {len(rs)} | رابحة: {wins}\nمجموع R بعد الرسوم: {sum(rs):+.2f} | PF: {pf}\nمفتوحة الآن: {len(act)}\n"
        f"ملاحظة: هذه نتائج داخلية فقط، لم تُنشر لأحد.")

_trendspider_queue = None
_trendspider_seen = {}

def _trendspider_timestamp(value):
    if isinstance(value, (int, float)):
        stamp=float(value)
        if stamp > 10_000_000_000: stamp /= 1000.0
        return int(stamp)
    if isinstance(value, str) and value.strip():
        raw=value.strip()
        try:
            stamp=float(raw)
            if stamp > 10_000_000_000: stamp /= 1000.0
            return int(stamp)
        except ValueError:
            try:
                parsed=dt.datetime.fromisoformat(raw.replace("Z","+00:00"))
                if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=dt.timezone.utc)
                return int(parsed.timestamp())
            except Exception:
                return None
    return None

def _trendspider_normalize(payload):
    raw=(payload.get("symbol") or payload.get("ticker") or payload.get("instrument") or "")
    raw=str(raw).strip().upper()
    if ":" in raw: raw=raw.rsplit(":",1)[-1]
    raw=raw.replace(".P","").replace("_PERP","").replace("-PERP","")
    sym=clean_symbol(raw)
    action=str(payload.get("action") or payload.get("side") or payload.get("signal") or "").strip().upper()
    side=1 if action in ("BUY","LONG","BULL","BULLISH") else (-1 if action in ("SELL","SHORT","BEAR","BEARISH") else 0)
    stamp=_trendspider_timestamp(payload.get("timestamp") or payload.get("time") or payload.get("timenow"))
    event_id=str(payload.get("id") or payload.get("alert_id") or payload.get("event_id") or "")
    if not event_id:
        event_id=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    if not sym or not side or not stamp:
        raise ValueError("required fields: symbol, action (buy/sell), timestamp")
    safe_payload={k:v for k,v in payload.items() if str(k).lower() not in ("secret","token")}
    return {"id":event_id,"symbol":sym,"side":side,"timestamp":stamp,"raw":safe_payload,
            "strategy":str(payload.get("strategy") or payload.get("name") or payload.get("alert") or "")[:40]}

async def _trendspider_webhook(request):
    if _aiohttp_web is None:
        raise RuntimeError("aiohttp is not installed")
    if not TRENDSPIDER_SECRET:
        return _aiohttp_web.json_response({"ok":False,"error":"webhook disabled"},status=503)
    try:
        payload=await request.json()
        if not isinstance(payload,dict): raise ValueError("JSON object required")
    except Exception as ex:
        return _aiohttp_web.json_response({"ok":False,"error":f"invalid JSON: {str(ex)[:120]}"},status=400)
    supplied=request.headers.get("X-Ryma-Secret","")
    auth=request.headers.get("Authorization","")
    if auth.lower().startswith("bearer "):
        supplied=auth[7:].strip()
    if not supplied:
        supplied=str(payload.get("secret") or payload.get("token") or "")
    if not hmac.compare_digest(str(supplied).encode("utf-8","replace"),TRENDSPIDER_SECRET.encode("utf-8")):
        return _aiohttp_web.json_response({"ok":False,"error":"unauthorized"},status=401)
    try:
        alert=_trendspider_normalize(payload)
    except Exception as ex:
        return _aiohttp_web.json_response({"ok":False,"error":str(ex)[:160]},status=400)
    now=int(time.time())
    if abs(now-alert["timestamp"])>TRENDSPIDER_MAX_SKEW_SEC:
        return _aiohttp_web.json_response({"ok":False,"error":"stale/future alert timestamp"},status=400)
    # Keep a bounded replay cache; event IDs are consumed before enqueueing.
    for key,seen_at in list(_trendspider_seen.items()):
        if now-seen_at>86400: _trendspider_seen.pop(key,None)
    if alert["id"] in _trendspider_seen:
        return _aiohttp_web.json_response({"ok":True,"duplicate":True},status=200)
    if _trendspider_queue is None or _trendspider_queue.full():
        return _aiohttp_web.json_response({"ok":False,"error":"queue unavailable/full"},status=503)
    _trendspider_seen[alert["id"]]=now
    if len(_trendspider_seen)>5000:
        oldest=sorted(_trendspider_seen.items(),key=lambda x:x[1])[:1000]
        for key,_ in oldest: _trendspider_seen.pop(key,None)
    await _trendspider_queue.put(alert)
    return _aiohttp_web.json_response({"ok":True,"queued":True,"symbol":alert["symbol"]},status=202)

async def _trendspider_health(request):
    return _aiohttp_web.json_response({"ok":True,"service":"ryma-trendspider-bridge"})

async def _trendspider_worker(app):
    while True:
        alert=await _trendspider_queue.get()
        try:
            res=await asyncio.to_thread(_trendspider_signal,alert)
            if res is None: continue
            if not _can_post(res):
                log.info("TrendSpider duplicate/active/cooldown skipped for %s",res["sym"]); continue
            tier,sent,ok,_r=await dispatch_signal(app.bot,res,admin_copy=True)
            if ok: log.info("TrendSpider alert published for %s (tier=%s grade=%s confirm=%s)",res["sym"],tier,res["grade"],res["ts_confirm"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("TrendSpider webhook processing failed")
        finally:
            _trendspider_queue.task_done()

async def post_init(app):
    global _trendspider_queue
    try: await app.bot.delete_webhook(drop_pending_updates=False)
    except Exception as _ex: log.debug('ignored: %s', _ex)
    try: await app.bot.set_my_commands([BotCommand(c,d) for c,d in PUBLIC_COMMANDS])
    except Exception as _ex: log.debug('ignored: %s', _ex)
    try:
        me=await app.bot.get_me(); app.bot_data["username"]=me.username
        log.info(f"bot username: @{me.username}")
    except Exception as e: log.warning(f"get_me: {e}")
    try:
        n=await asyncio.to_thread(smart_cleanup_trades)
        log.info(f"startup: smart_cleanup نظّفت {n} صفقة")
    except Exception as e: log.warning(f"startup cleanup: {e}")
    app.bot_data["tasks"]=[]
    if TRENDSPIDER_ENABLED:
        if not TRENDSPIDER_SECRET:
            log.error("TrendSpider enabled but TRENDSPIDER_SECRET is missing; receiver remains disabled")
        elif _aiohttp_web is None:
            log.error("TrendSpider enabled but aiohttp is unavailable; install aiohttp")
        else:
            runner=None
            try:
                _trendspider_queue=asyncio.Queue(maxsize=TRENDSPIDER_QUEUE_MAX)
                http_app=_aiohttp_web.Application(client_max_size=16*1024)
                http_app.router.add_post("/trendspider",_trendspider_webhook)
                http_app.router.add_get("/health",_trendspider_health)
                runner=_aiohttp_web.AppRunner(http_app,access_log=None)
                await runner.setup()
                site=_aiohttp_web.TCPSite(runner,"0.0.0.0",TRENDSPIDER_PORT)
                await site.start()
                app.bot_data["trendspider_runner"]=runner
                app.bot_data["tasks"].append(asyncio.create_task(_trendspider_worker(app)))
                log.info("TrendSpider receiver listening on port %s",TRENDSPIDER_PORT)
            except Exception:
                log.exception("TrendSpider receiver failed to start; Telegram bot will continue")
                if runner:
                    try: await runner.cleanup()
                    except Exception: pass
                _trendspider_queue=None
    app.bot_data["tasks"] += [
        asyncio.create_task(autopost_loop(app)),asyncio.create_task(tracker_loop(app)),
        asyncio.create_task(predict_loop(app)),asyncio.create_task(market_summary_loop(app)),
        *([asyncio.create_task(short_free_loop(app))] if SHORT_FREE_LOOP else []),asyncio.create_task(alpha_summary_loop(app)),
        asyncio.create_task(bottoms_auto_loop(app)),
        asyncio.create_task(golden_loop(app)),asyncio.create_task(promo_loop(app)),
        asyncio.create_task(whale_hunter_loop(app)),
        asyncio.create_task(weekly_report_loop(app)),asyncio.create_task(trial_notice_loop(app)),
        asyncio.create_task(morning_brief_loop(app)),
        asyncio.create_task(shadow_loop(app))]
    log.info("version %s",BOT_VERSION)
    log.info("Ryma v10 Hybrid RC7.0 | max_open=%d | golden=%ds | engine=%s/%s | multi=%s | points=%d→VIP%d | SL≤3%% hard",
             MAX_OPEN,CYCLE_GOLDEN,RYMA_AI_PROVIDER,RYMA_AI_MODEL,is_multi_exchange(),
             VIP_THRESHOLD,VIP_REWARD_DAYS)

async def post_shutdown(app):
    for t in app.bot_data.get("tasks",[]): t.cancel()
    runner=app.bot_data.get("trendspider_runner")
    if runner:
        try: await runner.cleanup()
        except Exception: log.exception("TrendSpider HTTP shutdown")
    try: store.flush()
    except Exception as _ex: log.debug('ignored: %s', _ex)

def main():
    if not BOT_TOKEN: raise SystemExit("BOT_TOKEN not set")
    store.start_flusher()
    app=(ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build())
    handlers=[
        ("version",cmd_version),("start",cmd_start),("help",cmd_help),("myid",cmd_myid),("vip",cmd_vip),
        ("menu",cmd_menu),("daily",cmd_daily),("cross",cmd_cross),("predict",cmd_predict),
        ("forcepost",cmd_forcepost),("clearsignals",cmd_clearsignals),
        ("smartcleanup",cmd_smartcleanup),("debug",cmd_debug),("health",cmd_health),("regime",cmd_regime),("smartmoney",cmd_smartmoney),("active",cmd_active),
        ("post",cmd_post),("bt",cmd_bt),("backtest",cmd_bt),("btv10",cmd_bt),("btx",cmd_btx),("bts",cmd_bts),("btt",cmd_btt),("btopt",cmd_btopt),("v10set",cmd_v10set),("v10show",cmd_v10show),("bt50",cmd_bt50),
        ("scan",cmd_scan),("short",cmd_short),("delist",cmd_delist),("price",cmd_price),
        ("users",cmd_users),("testchannels",cmd_testchannels),("stats",cmd_stats),
        ("history",cmd_history),("dashboard",cmd_dashboard),
        ("addvip",cmd_addvip),("removevip",cmd_removevip),("viplist",cmd_viplist),
        ("whales",cmd_whales),("liquidity",cmd_liquidity),("futures",cmd_futures),
        ("explosions",cmd_explosions),("pump",cmd_pump),
        ("bottom",cmd_bottoms),("bottoms",cmd_bottoms),
        ("shortsradar",cmd_shorts_radar),("alpha",cmd_alpha),("why",cmd_why),
        ("golden",cmd_golden),("share",cmd_share),
        ("portfolio",cmd_portfolio),("alpha_v2",cmd_alpha_radar_v2),
        ("patterns",cmd_patterns),("neon",cmd_neon),
        ("points",cmd_points),("myref",cmd_myref),("addpoints",cmd_addpoints),("radar",cmd_radar),("spot",cmd_spot),("plan",cmd_plan),
        ("btdiag",cmd_btdiag),("exportdata",cmd_exportdata),("fear",cmd_fear),("market",cmd_market),("top",cmd_top),("tools",cmd_tools),("risk",cmd_riskcalc)]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.add_handler(TypeHandler(Update,log_updates),group=-1)
    app.add_handler(CommandHandler("shadow", cmd_shadow))
    app.add_handler(CommandHandler("botinfo",cmd_botinfo))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,on_text))
    app.add_error_handler(on_error)
    # allowed_updates صريحة: تيليغرام يتذكر آخر قيمة، وأي نسخة قديمة طلبت message فقط تُسقط callback_query (الأزرار)
    app.run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=True)

if __name__ == "__main__":
    main()
