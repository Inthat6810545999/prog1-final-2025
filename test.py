import tkinter as tk
from tkinter import ttk
import json, threading, time, math
import ssl, certifi, traceback
import urllib.request, urllib.parse
import websocket
from collections import deque

# Matplotlib embed + candlesticks
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------------- Utilities ----------------

def ssl_context():
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(certifi.where())
    return ctx

def http_get(url, params=None, timeout=15):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ssl_context(), timeout=timeout) as resp:
        return resp.read()

def ema(series, window):
    k = 2 / (window + 1.0)
    out = []
    ema_val = None
    for v in series:
        if ema_val is None:
            ema_val = v
        else:
            ema_val = v * k + ema_val * (1 - k)
        out.append(ema_val)
    return out

# ---------------- Finance API (Binance REST) ----------------
class BinanceFinanceAPI:
    """
    Simple wrapper for Binance klines.
    symbol: e.g. 'btcusdt'
    interval: e.g. '1m', '5m', '1h', '4h', '1d'
    """
    BASE = "https://api.binance.com/api/v3/klines"

    @staticmethod
    def get_klines(symbol, interval="1h", limit=300):
        data = http_get(BinanceFinanceAPI.BASE, {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        })
        raw = json.loads(data)
        # Each kline: [openTime, open, high, low, close, volume, closeTime, ...]
        candles = []
        for k in raw:
            candles.append({
                "t": k[0] / 1000.0,           # seconds
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
            })
        return candles

# ---------------- Candlestick Canvas ----------------
class CandleChart(ttk.Frame):
    """
    Matplotlib candlestick chart with EMA lines.
    """
    def __init__(self, parent, symbol="btcusdt", interval="1h", limit=300):
        super().__init__(parent, padding=10)
        self.symbol = symbol.lower()
        self.interval = interval
        self.limit = limit

        # Figure
        self.fig = Figure(figsize=(8.5, 3.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title(f"{self.symbol.upper()} — {self.interval} Candles", loc="left", fontsize=12)
        self.ax.grid(True, alpha=0.2)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Load once initially
        threading.Thread(target=self.reload_data, daemon=True).start()

        # Auto refresh every 60s
        self.after(5_000, self.trigger_reload)

    def trigger_reload(self):
        threading.Thread(target=self.reload_data, daemon=True).start()
        self.after(5_000, self.trigger_reload)

    def reload_data(self):
        try:
            candles = BinanceFinanceAPI.get_klines(self.symbol, self.interval, self.limit)
            self.after(0, self._draw, candles)
        except Exception as e:
            print("chart reload error:", e)
            traceback.print_exc()

    def _draw(self, candles):
        if not candles:
            return

        self.ax.clear()
        self.ax.grid(True, alpha=0.2)
        self.ax.set_title(f"{self.symbol.upper()} — {self.interval} Candles", loc="left", fontsize=12)

        # Prepare data
        o = [c["o"] for c in candles]
        h = [c["h"] for c in candles]
        l = [c["l"] for c in candles]
        c = [c["c"] for c in candles]

        # X index
        x = list(range(len(candles)))

        # Candles
        # body: rectangle between open/close; wick: line from low to high
        for i in x:
            up = c[i] >= o[i]
            color = "#14b814" if up else "#d64545"  # green/red
            lo, hi = l[i], h[i]
            op, cl = o[i], c[i]
            # Wick
            self.ax.vlines(i, lo, hi, linewidth=1, color=color, alpha=0.9)
            # Body
            body_low = min(op, cl)
            body_high = max(op, cl)
            # If tiny body, ensure visible
            height = max(body_high - body_low, (hi - lo) * 0.02)
            body_low = cl if up else op
            body_low = min(op, cl)  # keep proper base
            rect_y = body_low
            rect_h = max(abs(cl - op), (hi - lo) * 0.02)
            self.ax.add_patch(
                self._rect(i - 0.35, rect_y, 0.70, rect_h, facecolor=color, edgecolor=color, alpha=0.85)
            )

        # EMA lines
        ema20 = ema(c, 20)
        ema50 = ema(c, 50)
        self.ax.plot(x, ema20, linewidth=1.4, label="EMA20")
        self.ax.plot(x, ema50, linewidth=1.4, label="EMA50")
        self.ax.legend(loc="upper right", frameon=False, fontsize=9)

        # Limits & formatting
        y_min = min(l)
        y_max = max(h)
        pad = (y_max - y_min) * 0.06
        self.ax.set_ylim(y_min - pad, y_max + pad)
        self.ax.set_xlim(-1, len(x))

        # Clean x ticks
        self.ax.set_xticks([])
        self.ax.set_ylabel("Price")

        self.canvas.draw_idle()

    def _rect(self, x, y, w, h, **kwargs):
        from matplotlib.patches import Rectangle
        return Rectangle((x, y), w, h, **kwargs)

# ---------------- Real-time Ticker ----------------
class CryptoTicker:
    """Ticker + tiny sparkline (last N prices)."""
    def __init__(self, parent, symbol, display_name, max_points=200):
        self.parent = parent
        self.symbol = symbol.lower()
        self.display_name = display_name
        self.is_active = False
        self.ws = None

        self.ssl_ctx = ssl_context()
        self.prices = deque(maxlen=max_points)

        # UI card
        self.frame = ttk.Frame(parent, relief="solid", borderwidth=1, padding=12)
        head = ttk.Frame(self.frame)
        head.pack(fill=tk.X)
        ttk.Label(head, text=display_name, font=("Georgia", 14, "bold")).pack(side=tk.LEFT)

        mid = ttk.Frame(self.frame)
        mid.pack(fill=tk.X, pady=(4, 2))
        self.price_label = tk.Label(mid, text="--,---", font=("Georgia", 26, "bold"))
        self.price_label.pack(side=tk.LEFT)
        self.change_label = ttk.Label(mid, text="--", font=("Georgia", 11))
        self.change_label.pack(side=tk.RIGHT)

        # tiny sparkline
        self.fig = Figure(figsize=(3.6, 1.0), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        for s in self.ax.spines.values(): s.set_visible(False)
        self.line, = self.ax.plot([], [], linewidth=1.7)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def start(self):
        if self.is_active: return
        self.is_active = True
        ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol}@ticker"

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_message,
            on_error=lambda ws, err: print(f"{self.symbol} error: {err}"),
            on_close=lambda ws, s, m: print(f"{self.symbol} closed"),
            on_open=lambda ws: print(f"{self.symbol} connected")
        )

        def _run():
            try:
                self.ws.run_forever(sslopt={"ssl_context": self.ssl_ctx})
            except Exception as e:
                print(f"{self.symbol} run_forever error:", e)
                traceback.print_exc()

        threading.Thread(target=_run, daemon=True).start()

    def stop(self):
        self.is_active = False
        if self.ws:
            try: self.ws.close()
            except: pass
            self.ws = None

    def on_message(self, ws, message):
        if not self.is_active: return
        data = json.loads(message)
        price = float(data["c"])
        change = float(data["p"])
        percent = float(data["P"])
        self.prices.append(price)

        # update UI
        self.parent.after(0, self.update_display, price, change, percent)
        self.parent.after(0, self.update_spark)

    def update_display(self, price, change, percent):
        up = (change >= 0)
        color = "#14b814" if up else "#d64545"
        sign = "+" if up else ""
        self.price_label.config(text=f"{price:,.2f}", fg=color)
        self.change_label.config(text=f"{sign}{change:,.2f} ({sign}{percent:.2f}%)", foreground=color)

    def update_spark(self):
        if not self.prices:
            return
        y = list(self.prices)
        x = list(range(len(y)))
        self.line.set_data(x, y)
        ymin, ymax = min(y), max(y)
        if math.isclose(ymin, ymax): ymin -= 1; ymax += 1
        pad = (ymax - ymin) * 0.15
        self.ax.set_ylim(ymin - pad, ymax + pad)
        self.ax.set_xlim(0, max(1, len(x)-1))
        self.line.set_color("#14b814" if y[-1] >= y[0] else "#d64545")
        self.canvas.draw_idle()

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def pack_forget(self):
        self.frame.pack_forget()

# ---------------- App Shell ----------------
class ModernDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Crypto Dashboard — Modern (Binance REST + WebSocket)")
        self.root.geometry("1280x720")

        # style (dark-ish)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background="#0f1116", foreground="#e8e8e8")
        style.configure("TFrame", background="#0f1116")
        style.configure("TLabel", background="#0f1116", foreground="#e8e8e8")
        style.configure("TButton", background="#22252e", foreground="#e8e8e8", padding=6)
        style.map("TButton", background=[("active", "#2b2f3a")])

        # Top controls
        top = ttk.Frame(root, padding=10)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Pairs:", font=("Georgia", 12, "bold")).pack(side=tk.LEFT, padx=(0, 8))

        # Interval selector for main chart
        self.interval = tk.StringVar(value="1h")
        interval_cb = ttk.Combobox(top, textvariable=self.interval, values=["1m", "5m", "15m", "1h", "4h", "1d"], width=6, state="readonly")
        interval_cb.pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Label(top, text="Interval", font=("Georgia", 11)).pack(side=tk.RIGHT, padx=(0, 6))
        interval_cb.bind("<<ComboboxSelected>>", self._on_interval_change)

        # Main area: left tickers, right chart
        main = ttk.Frame(root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y)

        self.btc = CryptoTicker(left, "btcusdt", "BTC/USDT")
        self.btc.pack(padx=8, pady=6, fill=tk.X)

        self.eth = CryptoTicker(left, "ethusdt", "ETH/USDT")
        self.eth.pack(padx=8, pady=6, fill=tk.X)

        self.sol = CryptoTicker(left, "solusdt", "SOL/USDT")
        self.sol.pack(padx=8, pady=6, fill=tk.X)

        # Start tickers
        self.btc.start()
        self.eth.start()
        self.sol.start()

        # Right: big candlestick (default BTC/USDT)
        right = ttk.Frame(main)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.chart_symbol = "btcusdt"
        self.chart = CandleChart(right, symbol=self.chart_symbol, interval=self.interval.get(), limit=300)
        self.chart.pack(fill=tk.BOTH, expand=True)

        # Buttons to switch chart symbol
        switch = ttk.Frame(right, padding=(0, 6))
        switch.pack(fill=tk.X)
        ttk.Button(switch, text="BTC/USDT", command=lambda: self._set_chart_symbol("btcusdt")).pack(side=tk.LEFT, padx=4)
        ttk.Button(switch, text="ETH/USDT", command=lambda: self._set_chart_symbol("ethusdt")).pack(side=tk.LEFT, padx=4)
        ttk.Button(switch, text="SOL/USDT", command=lambda: self._set_chart_symbol("solusdt")).pack(side=tk.LEFT, padx=4)

    def _set_chart_symbol(self, symbol):
        self.chart_symbol = symbol
        # rebuild CandleChart for simplicity
        parent = self.chart.master
        self.chart.destroy()
        self.chart = CandleChart(parent, symbol=self.chart_symbol, interval=self.interval.get(), limit=300)
        self.chart.pack(fill=tk.BOTH, expand=True)

    def _on_interval_change(self, _evt):
        # rebuild chart on interval change
        self._set_chart_symbol(self.chart_symbol)

    def on_closing(self):
        for t in (self.btc, self.eth, self.sol):
            t.stop()
        self.root.destroy()

# ---------------- Main ----------------
if __name__ == "__main__":
    root = tk.Tk()
    app = ModernDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
