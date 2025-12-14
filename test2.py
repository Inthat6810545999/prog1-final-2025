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
import customtkinter
from CTkMessagebox import CTkMessagebox
FONT_FAMILY = "Inter"
THEME = {
    "light": {
        "bg": "#FFFFFF",
        "card": "#FFFFFF",
        "border": "#E5E7EB",
        "text": "#0F172A",

        "sidebar": "#F1F5F9",          # ขาว/เทาอ่อน
        "sidebar_text": "#0F172A",

        "button": "#E5E7EB",
        "button_hover": "#CBD5E1"
    }
,
    "dark": {
        "bg": "#0B1220",
        "card": "#111827",
        "border": "#1F2937",
        "text": "#E5E7EB",

        "sidebar": "#020617",
        "sidebar_text": "#E5E7EB",

        "button": "#1E293B",
        "button_hover": "#334155",
        "button_text": "#E5E7EB"
    }
}
def load_klines(symbol="BTCUSDT", interval="30m", limit=800) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    headers = {"User-Agent": "Mozilla/5.0"}

    r = requests.get(url, params=params, headers=headers, timeout=12)
    r.raise_for_status()
    raw = r.json()

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
        if self.stop_flag: return
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
        except:
            pass

# ============================================
# TradingView-like line chart + colored volume
# ============================================
class TVLineChart(ctk.CTkFrame):
    def __init__(self, parent, symbol="BTCUSDT", interval="30m", ):
        mode = ctk.get_appearance_mode().lower()

        super().__init__(
            parent,
            fg_color="#FFFFFF"   # ← ตรงนี้แหละ สีเทาหาย
        )


        self.symbol = symbol.upper()
        self.interval = interval
        self.ws = None
        self.ws_thread = None
        self._countdown_job = None
        self.timeframe = "ALL"
        # Figure
        mode = ctk.get_appearance_mode().lower()

        self.fig = Figure(
            figsize=(8,4),
            dpi=100,
            constrained_layout=False,
            facecolor="#FFFFFF"   
        )

        # leave room on right for price label box
        self.fig.subplots_adjust(right=0.86, hspace=0.12)
        self.ax = self.fig.add_subplot(2,1,1)
        self.ax_vol = self.fig.add_subplot(2,1,2, sharex=self.ax)

        self.canvas = FigureCanvasTkAgg(self.fig, self)
        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.configure(bg='#FFFFFF')  # ← Tk canvas
        canvas_widget.pack(fill="both", expand=True)


        # Countdown label
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

    def _apply_timeframe(self, tf: str):
        if self.df.empty:
            return self.df

        end = self.df.index.max()

        if tf == "5D":
            start = end - pd.Timedelta(days=5)
        elif tf == "1M":
            start = end - pd.DateOffset(months=1)
        elif tf == "3M":
            start = end - pd.DateOffset(months=3)
        elif tf == "6M":
            start = end - pd.DateOffset(months=6)
        elif tf == "YTD":
            start = pd.Timestamp(year=end.year, month=1, day=1)
        elif tf == "1Y":
            start = end - pd.DateOffset(years=1)
        elif tf == "5Y":
            start = end - pd.DateOffset(years=5)
        elif tf == "ALL":
            return self.df
        else:
            return self.df

        return self.df.loc[self.df.index >= start]

    # ---- chart ----
    def draw_chart(self):
        self.ax.clear()

        self.ax_vol.clear()
        for spine in self.ax.spines.values():
            spine.set_color("#FFFFFF")

        for spine in self.ax_vol.spines.values():
            spine.set_color("#FFFFFF")

        bg = "#FFFFFF"
        grid = "#E6E6E6"
        for a in (self.ax, self.ax_vol):
            a.set_facecolor(bg)
            a.grid(True, linestyle="--", color=grid, alpha=0.6)

        if len(self.df) == 0:
            self.ax.text(0.5,0.5,"No chart data", ha="center", va="center")
            self.canvas.draw_idle()
            return

        df = self._apply_timeframe(self.timeframe).sort_index().copy()

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

        self.fig.canvas.draw_idle()
        self.canvas.draw_idle()


    # ---- websocket ----
    def start_ws(self):
        self.stop_ws()
        url = f"wss://stream.binance.com:9443/ws/{self.symbol.lower()}@kline_{self.interval}"

        def on_msg(ws, msg):
            k = json.loads(msg)["k"]
            ts = pd.to_datetime(k["t"], unit="ms")
            row = [float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])]
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
            if self.ws: self.ws.close()
        except:
            pass
        self.ws = None

    # ---- countdown like TradingView ----
    def _update_countdown(self):
        tf_sec = self._get_tf_seconds(self.interval)
        # ใช้ timezone-aware แทน utcnow() (แก้ DeprecationWarning)
        now = dt.datetime.now(dt.timezone.utc)
        next_close_ts = (int(now.timestamp()) // tf_sec + 1) * tf_sec
        remain = max(0, int(next_close_ts - now.timestamp()))

        mm = remain // 60
        ss = remain % 60
        self.count_lbl.configure(text=f"Close in {mm:02d}:{ss:02d}")

        self._countdown_job = self.after(1000, self._update_countdown)

    def refresh(self):
        self.df = load_klines(self.symbol, self.interval)
        self.draw_chart()
        self.start_ws()
        # restart countdown
        if self._countdown_job is not None:
            try: self.after_cancel(self._countdown_job)
            except: pass
        self._update_countdown()

    def stop(self):
        try:
            if self._countdown_job is not None:
                self.after_cancel(self._countdown_job)
        except: pass
        self.stop_ws()

# =========================
# Pages
# =========================
class OverviewPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        mode = ctk.get_appearance_mode().lower()

        super().__init__(
            parent,
            fg_color=THEME[mode]["bg"]   # <<<<< ตรงนี้
        )
        self.app = app

        # --------------------
        # Top cards
        # --------------------
        mode = ctk.get_appearance_mode().lower()
        cards = ctk.CTkFrame(self, fg_color=THEME[mode]["bg"])

        cards.pack(fill="x", padx=20, pady=20)
        cards.grid_columnconfigure((0,1,2), weight=1)

        app.btc_price, app.btc_chg = app._card(cards, 0, "BTC / USD")
        app.eth_price, app.eth_chg = app._card(cards, 1, "ETH / USD")
        app._card(cards, 2, "Portfolio Value", fixed="$68,420")

        # --------------------
        # Controls
        # --------------------
        ctrl = ctk.CTkFrame(
            self,
            fg_color=THEME[mode]["bg"]
        )


        ctrl.pack(fill="x", padx=20, pady=(0,10))

        mode = ctk.get_appearance_mode().lower()

        for tf in ["1m","5m","15m","30m","1h","4h","1d"]:
            ctk.CTkButton(
                ctrl,
                text=tf,
                width=50,
                fg_color=THEME[mode]["card"],
                text_color=THEME[mode]["text"],
                hover_color=THEME[mode]["button_hover"],
                border_width=1,
                border_color=THEME[mode]["bg"],
                command=lambda t=tf: app.change_tf(t)
            ).pack(side="left", padx=4)

        ctk.CTkLabel(ctrl, text="  |  ").pack(side="left", padx=6)

        for tf in ["5D","1M","3M","6M","YTD","1Y","5Y","ALL"]:
            ctk.CTkButton(
                ctrl,
                text=tf,
                width=55,
                fg_color=THEME[mode]["card"],
                text_color=THEME[mode]["text"],
                hover_color=THEME[mode]["button_hover"],
                border_width=1,
                border_color=THEME[mode]["border"],
                command=lambda t=tf: app.change_tf(t)
            ).pack(side="left", padx=3)

        ctk.CTkLabel(ctrl, text="   ").pack(side="left", padx=10)

        mode = ctk.get_appearance_mode().lower()

        for s in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
            ctk.CTkButton(
                ctrl,
                text=s,
                width=80,
                fg_color=THEME[mode]["card"],
                text_color=THEME[mode]["text"],
                hover_color=THEME[mode]["button_hover"],
                border_width=1,
                border_color=THEME[mode]["border"],
                command=lambda ss=s: app.change_symbol(ss)
            ).pack(side="left", padx=6)


        # --------------------
        # Chart (มีแค่ตัวเดียว!)
        # --------------------
        self.chart = TVLineChart(self, symbol="BTCUSDT", interval="30m")
        self.chart.pack(fill="both", expand=True, padx=20, pady=10)

        # --------------------
        # Live prices
        # --------------------
        app.live_btc = LivePrice(app.btc_price, app.btc_chg, "btcusdt")
        app.live_eth = LivePrice(app.eth_price, app.eth_chg, "ethusdt")

class OrdersPage(ctk.CTkFrame):
    """
    ฟอร์มคำสั่งซื้อขาย (ยังไม่ต่อ Binance)
    - BUY/SELL
    - Market / Limit
    - Quantity, Price (enable เฉพาะ Limit)
    - คำนวณมูลค่ารวม
    - ปุ่มยืนยัน (แค่ print / แสดง popup)
    """
    def __init__(self, parent):
        super().__init__(parent)

        box = ctk.CTkFrame(self)
        box.pack(padx=40, pady=40, fill="x")

        ctk.CTkLabel(box, text="Place Order",
                     font=(FONT_FAMILY, 22, "bold")).pack(anchor="w", padx=10, pady=10)

        form = ctk.CTkFrame(box)
        form.pack(fill="x", padx=10, pady=10)

        # BUY/SELL
        self.side = ctk.StringVar(value="BUY")
        side_switch = ctk.CTkSegmentedButton(
            form, values=["BUY","SELL"], variable=self.side, width=200
        )
        side_switch.pack(anchor="w", pady=6)

        # Market / Limit
        self.otype = ctk.StringVar(value="Market")
        type_switch = ctk.CTkSegmentedButton(
            form, values=["Market","Limit"], variable=self.otype, width=200
        )
        type_switch.pack(anchor="w", pady=6)

        # Inputs
        self.qty = ctk.CTkEntry(form, placeholder_text="Quantity (e.g. 0.01)")
        self.qty.pack(fill="x", pady=6)

        self.price = ctk.CTkEntry(form, placeholder_text="Price (for Limit)")
        self.price.pack(fill="x", pady=6)

        # Total
        self.total_lbl = ctk.CTkLabel(form, text="Total: --", font=("Georgia", 14))
        self.total_lbl.pack(anchor="w", pady=6)

        # Submit
        self.btn = ctk.CTkButton(form, text="BUY", fg_color="#2ECC71", command=self.submit)
        self.btn.pack(fill="x", pady=12)

        # bindings
        self.side.trace_add("write", self._refresh_btn)
        self.otype.trace_add("write", self._refresh_price_state)
        self.qty.bind("<KeyRelease>", lambda e: self._recalc_total())
        self.price.bind("<KeyRelease>", lambda e: self._recalc_total())
        self._refresh_price_state()

    def _refresh_btn(self, *args):
        if self.side.get() == "BUY":
            self.btn.configure(text="BUY", fg_color="#2ECC71")
        else:
            self.btn.configure(text="SELL", fg_color="#E74C3C")

    def _refresh_price_state(self, *args):
        is_limit = self.otype.get() == "Limit"
        self.price.configure(state="normal" if is_limit else "disabled")
        self._recalc_total()

    def _recalc_total(self):
        try:
            q = float(self.qty.get())
        except:
            self.total_lbl.configure(text="Total: --")
            return
        if self.otype.get() == "Limit":
            try:
                p = float(self.price.get())
            except:
                self.total_lbl.configure(text="Total: --")
                return
            total = q * p
        else:
            # Market: แสดงเฉพาะจำนวน (ราคาจริงไม่รู้ เพราะยังไม่ต่อ API)
            total = q
        self.total_lbl.configure(text=f"Total: {total:,.4f}")

    def submit(self):
        # Validate Quantity
        qty = self.qty.get().strip()
        if not qty:
            CTkMessagebox(
                title="Error",
                message="Please enter quantity.",
                icon="cancel"
            )
            return

        # Validate price if Limit order
        otype = self.otype.get()
        if otype == "Limit":
            price = self.price.get().strip()
            if not price:
                CTkMessagebox(
                    title="Error",
                    message="Please enter price for Limit orders.",
                    icon="cancel"
                )
                return

        # ---- SUCCESS POPUP ----
        msg = f"{self.side.get()} order placed!\nQuantity: {qty}"
        if otype == "Limit":
            msg += f"\nPrice: {self.price}"

        CTkMessagebox(
            title="Success",
            message=msg,
            icon="check"
        )

# =========================
# Dashboard
# =========================
class AtlasDashboard(ctk.CTk):
    def __init__(self):
        super().__init__()
        mode = ctk.get_appearance_mode().lower()

        self.configure(fg_color=THEME[mode]["bg"])

        self.title("FirstForFun(D) — Python Line Dashboard")
        self.geometry("1500x850")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        mode = ctk.get_appearance_mode().lower()
        # Sidebar
        self.sidebar = ctk.CTkFrame(
            self,
            fg_color=THEME[mode]["sidebar"],
            width=220
        )
        self.sidebar.grid(row=0, column=0, sticky="ns")

        mode = ctk.get_appearance_mode().lower()

        ctk.CTkLabel(
            self.sidebar,
            text="FirstFOr\nFun(D)",
        text_color=THEME[mode].get("sidebar_text", THEME[mode]["text"])
        ,
            font=("Georgia", 30, "bold")
        ).pack(pady=40)


        # Main container (switch pages)
        self.container = ctk.CTkFrame(
            self,
            fg_color=THEME[mode]["bg"]
        )

        self.container.grid(row=0, column=1, sticky="nsew")

        # Pages
        self.pages = {
            "Overview": OverviewPage(self.container, self),
            "Orders": OrdersPage(self.container),
            "Settings": SettingsPage(self.container, self)
        }
        self.current_page = None

        # Sidebar buttons
        for m in ["Overview","Orders","Insights","Wallet","Settings"]:
            mode = ctk.get_appearance_mode().lower()

            ctk.CTkButton(
                self.sidebar,
                text=m,
                width=180,
                fg_color=THEME[mode]["button"],
                hover_color=THEME[mode]["button_hover"],
                command=(lambda x=m: self.show(x)) if m in self.pages else None
            ).pack(pady=8)


        self.show("Overview")
        self.protocol("WM_DELETE_WINDOW", self.close_all)

    def apply_theme(self):
        mode = ctk.get_appearance_mode().lower()

        # root window (สำคัญมาก)
        self.configure(fg_color=THEME[mode]["bg"])

        # container
        self.container.configure(fg_color=THEME[mode]["bg"])

        # sidebar
        self.sidebar.configure(fg_color=THEME[mode]["sidebar"])

    def _get_chart(self):
        if self.current_page and hasattr(self.current_page, "chart"):
            return self.current_page.chart
        return None

    # ------- page switch -------
    def show(self, name):
        if self.current_page:
            self.current_page.pack_forget()
        self.current_page = self.pages[name]
        self.current_page.pack(fill="both", expand=True)

    # ------- chart controls (Overview uses) -------
    def change_range(self, tf):
        chart = self._get_chart()
        if chart:
            chart.timeframe = tf
            chart.draw_chart()
    def change_tf(self, tf):
        chart = self._get_chart()
        if not chart:
            return
        chart.interval = tf
        chart.refresh()

    def change_symbol(self, sym):
        chart = self._get_chart()
        if not chart:
            return
        chart.stop_ws()
        chart.symbol = sym.upper()
        chart.refresh()


    # ------- cards -------
    def _card(self, parent, col, title, fixed=None):
        mode = ctk.get_appearance_mode().lower()

        c = ctk.CTkFrame(
            parent,
            fg_color=THEME[mode]["card"],
            border_width=1,
            border_color=THEME[mode]["border"]
        )
        c.grid(row=0, column=col, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            c,
            text=title,
            font=("Georgia", 15),
            text_color=THEME[mode]["text"]
        ).pack(anchor="w", padx=15)

        price = ctk.CTkLabel(
            c,
            text=fixed or "$--",
            font=(FONT_FAMILY, 30, "bold"),
            text_color=THEME[mode]["text"]
        )
        price.pack(anchor="w", padx=15)

        chg = ctk.CTkLabel(
            c,
            text="--",
            font=("Georgia", 14)
        )
        if not fixed:
            chg.pack(anchor="w", padx=15)

        return price, chg


    def close_all(self):
        chart = self._get_chart()
        if chart:
            chart.stop()
        self.destroy()

class SettingsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        box = ctk.CTkFrame(self)
        box.pack(padx=40, pady=40, fill="x")

        ctk.CTkLabel(
            box,
            text="Appearance",
            font=(FONT_FAMILY, 20, "bold")
        ).pack(anchor="w", pady=(10, 20))

        self.mode = ctk.StringVar(value=ctk.get_appearance_mode())

        ctk.CTkSegmentedButton(
            box,
            values=["Light", "Dark"],
            variable=self.mode,
            command=self.change_mode
        ).pack(anchor="w")
    def change_mode(self, value):
        ctk.set_appearance_mode(value.lower())
        self.app.apply_theme()
        self.app.show("Overview")  # บังคับ rebuild card



if __name__ == "__main__":
    app = AtlasDashboard()
    app.mainloop()
