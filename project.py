import json
import threading
import requests
import websocket
import customtkinter as ctk
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
import datetime as dt

# =========================
# Helpers
# =========================
def load_klines(symbol="BTCUSDT", interval="30m", limit=800) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        print("KL REST ERROR:", e)
        return pd.DataFrame(columns=["open","high","low","close","volume"],
                            index=pd.to_datetime([]))

    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","q","n","tbv","tbq","ignore"
    ])

    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)

    df["t"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("t", inplace=True)
    return df[["open","high","low","close","volume"]]


# =========================
# Live price card
# =========================
class LivePrice:
    def __init__(self, price_lbl, chg_lbl, symbol):
        self.price_lbl = price_lbl
        self.chg_lbl = chg_lbl
        self.symbol = symbol.lower()
        self.ws = None
        self.stop_flag = False

        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        url = f"wss://stream.binance.com:9443/ws/{self.symbol}@ticker"
        self.ws = websocket.WebSocketApp(
            url,
            on_message=self.on_msg,
            on_error=lambda ws,e: print("PRICE WS ERR:", e),
            on_open=lambda ws: print("price ws open:", self.symbol)
        )
        self.ws.run_forever()

    def on_msg(self, ws, msg):
        if self.stop_flag:
            return
        d = json.loads(msg)

        price = float(d["c"])
        chg   = float(d["p"])
        pct   = float(d["P"])

        color = "#27AE60" if chg >= 0 else "#C0392B"
        sign = "+" if chg >= 0 else ""

        self.price_lbl.after(0, lambda:
            self.price_lbl.configure(text=f"${price:,.2f}", text_color=color)
        )
        self.chg_lbl.after(0, lambda:
            self.chg_lbl.configure(text=f"{sign}{chg:.2f} ({sign}{pct:.2f}%)",
                                   text_color=color)
        )

    def stop(self):
        self.stop_flag = True
        try:
            if self.ws: self.ws.close()
        except: pass


# ============================================
# TradingView-like line chart + colored volume
# ============================================
class TVLineChart(ctk.CTkFrame):
    def __init__(self, parent, symbol="BTCUSDT", interval="30m"):
        super().__init__(parent, fg_color="white")

        self.symbol = symbol.upper()
        self.interval = interval
        self.ws = None
        self.ws_thread = None
        self._countdown_job = None

        # Figure
        self.fig = Figure(figsize=(8,4), dpi=100, constrained_layout=False)
        # leave room on right for price label box
        self.fig.subplots_adjust(right=0.86, hspace=0.12)
        self.ax = self.fig.add_subplot(2,1,1)
        self.ax_vol = self.fig.add_subplot(2,1,2, sharex=self.ax)

        self.canvas = FigureCanvasTkAgg(self.fig, self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Countdown label (เหมือน TradingView)
        self.count_lbl = ctk.CTkLabel(
            self, text="Close in 00:00", text_color="#27AE60",
            font=("Georgia", 12, "bold")
        )
        self.count_lbl.place(relx=0.98, rely=0.01, anchor="ne")

        # Initial data
        self.df = load_klines(self.symbol, self.interval)
        self.draw_chart()

        # WS
        self.start_ws()
        self._update_countdown()

    # ---- utilities ----
    def _get_tf_seconds(self, tf: str) -> int:
        m = {
            "1m":60, "3m":180, "5m":300, "15m":900, "30m":1800,
            "1h":3600, "2h":7200, "4h":14400, "6h":21600, "8h":28800, "12h":43200,
            "1d":86400, "3d":259200, "1w":604800
        }
        return m.get(tf, 1800)

    def _volume_width(self):
        if len(self.df.index) < 2:
            return 0.0005
        sec = (self.df.index[-1] - self.df.index[-2]).total_seconds()
        return (sec/86400.0)*0.8

    # ---- chart ----
    def draw_chart(self):
        self.ax.clear()
        self.ax_vol.clear()

        bg = "#FFFFFF"
        grid = "#E6E6E6"
        for a in (self.ax, self.ax_vol):
            a.set_facecolor(bg)
            a.grid(True, linestyle="--", color=grid, alpha=0.6)

        if len(self.df) == 0:
            self.ax.text(0.5,0.5,"No chart data", ha="center", va="center")
            self.canvas.draw_idle()
            return

        df = self.df.sort_index().copy()

        # line
        for i in range(1, len(df)):
            color = "#26A69A" if df["close"].iloc[i] >= df["close"].iloc[i-1] else "#EF5350"
            self.ax.plot(
                df.index[i-1:i+1],
                df["close"].iloc[i-1:i+1],
                color=color,
                linewidth=1.3
            )

        # RIGHT SIDE PRICE AXIS
        self.ax.yaxis.tick_right()
        self.ax.yaxis.set_label_position("right")

        # last price + ohlc text
        last = df["close"].iloc[-1]
        self.ax.axhline(last, linestyle="--", color="#00C853", linewidth=1, zorder=2)

        # last price green box (outside axis, not clipped)
        self.ax.annotate(
            f"{last:,.2f}",
            xy=(1.0, last),
            xycoords=("axes fraction", "data"),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            bbox=dict(boxstyle="round,pad=0.25", fc="#00C853", ec="none", alpha=0.95),
            color="white", fontsize=10, zorder=3, clip_on=False
        )

        o = df["open"].iloc[-1]
        h = df["high"].iloc[-1]
        l = df["low"].iloc[-1]
        c = df["close"].iloc[-1]
        self.ax.text(0.01,0.98,
                     f"O {o:,.0f}  H {h:,.0f}  L {l:,.0f}  C {c:,.0f}",
                     transform=self.ax.transAxes,
                     color="#00897B", fontsize=10, va="top")

        # volume
        colors = ["#26A69A" if c_>=o_ else "#EF5350"
                  for o_,c_ in zip(df["open"], df["close"])]
        width = self._volume_width()
        self.ax_vol.bar(df.index, df["volume"], color=colors, width=width)

        # time formatting
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.ax.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(self.ax.xaxis.get_major_locator())
        )

        # tighten
        self.fig.canvas.draw_idle()
        self.canvas.draw_idle()

    # ---- websocket ----
    def start_ws(self):
        # stop old one if exists
        self.stop_ws()

        url = f"wss://stream.binance.com:9443/ws/{self.symbol.lower()}@kline_{self.interval}"

        def on_msg(ws, msg):
            k = json.loads(msg)["k"]
            ts = pd.to_datetime(k["t"], unit="ms")
            row = [
                float(k["o"]),
                float(k["h"]),
                float(k["l"]),
                float(k["c"]),
                float(k["v"])
            ]
            # update/append
            self.df.loc[ts] = row
            self.df = self.df.sort_index().iloc[-1500:]
            self.after(0, self.draw_chart)

        self.ws = websocket.WebSocketApp(
            url,
            on_message=on_msg,
            on_error=lambda ws,e: print("WS ERR:", e),
            on_open=lambda ws: print("chart ws open:", self.symbol)
        )
        self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()

    def stop_ws(self):
        try:
            if self.ws:
                self.ws.close()
        except:
            pass
        self.ws = None

    # ---- countdown like TradingView ----
    def _update_countdown(self):
        tf_sec = self._get_tf_seconds(self.interval)
        now = dt.datetime.utcnow()
        next_close_ts = (int(now.timestamp()) // tf_sec + 1) * tf_sec
        remain = max(0, int(next_close_ts - now.timestamp()))

        mm = remain // 60
        ss = remain % 60
        self.count_lbl.configure(text=f"Close in {mm:02d}:{ss:02d}")

        # reschedule every second
        self._countdown_job = self.after(1000, self._update_countdown)

    def refresh(self):
        self.df = load_klines(self.symbol, self.interval)
        self.draw_chart()
        # restart WS with new tf/symbol
        self.start_ws()
        # restart countdown
        if self._countdown_job is not None:
            self.after_cancel(self._countdown_job)
        self._update_countdown()

    def stop(self):
        if self._countdown_job is not None:
            try: self.after_cancel(self._countdown_job)
            except: pass
        self.stop_ws()


# =========================
# Dashboard
# =========================
class AtlasDashboard(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")

        self.title("FirstForFun(D) — TradingView Line Dashboard")
        self.geometry("1500x850")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        side = ctk.CTkFrame(self, fg_color="#0D1B2A", width=220)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)

        ctk.CTkLabel(side, text="FirstFOr\nFun(D)",
                     text_color="white",
                     font=("Georgia", 30, "bold")
        ).pack(pady=40)

        for m in ["Overview","Orders","Markets","Insights","Wallet","Settings"]:
            ctk.CTkButton(side, text=m, width=180,
                          fg_color="#1B263B", hover_color="#415A77"
            ).pack(pady=8)

        # Main
        main = ctk.CTkFrame(self, fg_color="#F4F4F4")
        main.grid(row=0, column=1, sticky="nsew")

        # Top cards
        cards = ctk.CTkFrame(main, fg_color="white")
        cards.pack(fill="x", padx=20, pady=20)
        cards.grid_columnconfigure((0,1,2), weight=1)

        self.btc_price, self.btc_chg = self._card(cards, 0, "BTC / USD")
        self.eth_price, self.eth_chg = self._card(cards, 1, "ETH / USD")
        self._card(cards, 2, "Portfolio Value", fixed="$128,402")

        # Controls (TF + symbol)
        ctrl = ctk.CTkFrame(main, fg_color="white")
        ctrl.pack(fill="x", padx=20)

        for tf in ["1d","5m","15m","30m","1h","4h","1d"]:
            ctk.CTkButton(ctrl,text=tf,width=50,
                          command=lambda t=tf:self.change_tf(t)).pack(side="left", padx=4)
        ctk.CTkLabel(ctrl,text="   ").pack(side="left")
        for s in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
            ctk.CTkButton(ctrl,text=s,width=80,
                          command=lambda ss=s:self.change_symbol(ss)).pack(side="left", padx=6)

        # Chart
        self.chart = TVLineChart(main, symbol="BTCUSDT", interval="30m")
        self.chart.pack(fill="both", expand=True, padx=20, pady=10)

        # Live prices
        self.live_btc = LivePrice(self.btc_price, self.btc_chg, "btcusdt")
        self.live_eth = LivePrice(self.eth_price, self.eth_chg, "ethusdt")

        self.protocol("WM_DELETE_WINDOW", self.close_all)

    def _card(self, parent, col, title, fixed=None):
        c = ctk.CTkFrame(parent, fg_color="white", border_width=1, border_color="#E0E0E0")
        c.grid(row=0, column=col, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(c,text=title,font=("Georgia",15)).pack(anchor="w", padx=15)
        price = ctk.CTkLabel(c, text=fixed or "$--", font=("Georgia",30,"bold"))
        price.pack(anchor="w", padx=15)
        chg = ctk.CTkLabel(c, text="--", font=("Georgia",14))
        if not fixed: chg.pack(anchor="w", padx=15)
        return price, chg

    def change_tf(self, tf):
        self.chart.interval = tf
        self.chart.refresh()

    def change_symbol(self, sym):
        self.chart.symbol = sym
        self.chart.refresh()

    def close_all(self):
        self.live_btc.stop()
        self.live_eth.stop()
        self.chart.stop()
        self.destroy()


if __name__ == "__main__":
    app = AtlasDashboard()
    app.mainloop()
