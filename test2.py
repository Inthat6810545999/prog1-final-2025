import json
import threading
import requests
import websocket
import customtkinter as ctk
import pandas as pd
import datetime as dt

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates


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

        color = "#26A69A" if chg >= 0 else "#EF5350"
        sign = "+" if chg >= 0 else ""

        self.price_lbl.after(0, lambda:
            self.price_lbl.configure(text=f"${price:,.2f}", text_color=color)
        )
        self.chg_lbl.after(0, lambda:
            self.chg_lbl.configure(
                text=f"{sign}{chg:.2f} ({sign}{pct:.2f}%)",
                text_color=color
            )
        )

    def stop(self):
        self.stop_flag = True
        try:
            if self.ws:
                self.ws.close()
        except:
            pass


# ============================================
# TradingView-like line chart
# ============================================
class TVLineChart(ctk.CTkFrame):
    def __init__(self, parent, symbol="BTCUSDT", interval="30m"):
        super().__init__(parent, fg_color="white")

        self.symbol = symbol.upper()
        self.interval = interval
        self.ws = None
        self._countdown_job = None

        self.fig = plt.Figure(figsize=(8,4), dpi=100)
        self.fig.subplots_adjust(right=0.86, hspace=0.12)

        self.ax = self.fig.add_subplot(2,1,1)
        self.ax_vol = self.fig.add_subplot(2,1,2, sharex=self.ax)

        self.canvas = FigureCanvasTkAgg(self.fig, self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.count_lbl = ctk.CTkLabel(
            self, text="Close in 00:00",
            text_color="#26A69A",
            font=("Georgia", 12, "bold")
        )
        self.count_lbl.place(relx=0.98, rely=0.01, anchor="ne")

        self.df = load_klines(self.symbol, self.interval)
        self.draw_chart()
        self.start_ws()
        self._update_countdown()

    # ---- utilities ----
    def _get_tf_seconds(self, tf: str) -> int:
        return {
            "1m":60, "3m":180, "5m":300, "15m":900, "30m":1800,
            "1h":3600, "2h":7200, "4h":14400,
            "1d":86400, "1w":604800
        }.get(tf, 1800)

    def _volume_width(self):
        if len(self.df) < 2:
            return 0.0005
        sec = (self.df.index[-1] - self.df.index[-2]).total_seconds()
        return (sec / 86400) * 0.8

    # ---- chart ----
    def draw_chart(self):
        self.ax.clear()
        self.ax_vol.clear()

        for a in (self.ax, self.ax_vol):
            a.set_facecolor("#FFFFFF")
            a.grid(True, linestyle="--", color="#E6E6E6", alpha=0.6)

        if len(self.df) < 2:
            self.canvas.draw_idle()
            return

        df = self.df.sort_index()

        # segmented line
        for i in range(1, len(df)):
            color = "#26A69A" if df["close"].iloc[i] >= df["close"].iloc[i-1] else "#EF5350"
            self.ax.plot(df.index[i-1:i+1],
                         df["close"].iloc[i-1:i+1],
                         color=color, linewidth=1.3)

        # right price axis
        self.ax.yaxis.tick_right()
        self.ax.yaxis.set_label_position("right")

        last = df["close"].iloc[-1]
        o = df["open"].iloc[-1]
        last_color = "#26A69A" if last >= o else "#EF5350"

        self.ax.axhline(last, linestyle="--", color=last_color, linewidth=1)

        self.ax.annotate(
            f"{last:,.2f}",
            xy=(1.0, last),
            xycoords=("axes fraction", "data"),
            xytext=(8,0),
            textcoords="offset points",
            va="center",
            bbox=dict(boxstyle="round,pad=0.25", fc=last_color, ec="none"),
            color="white",
            fontsize=10,
            clip_on=False
        )

        # volume
        colors = ["#26A69A" if c>=o else "#EF5350"
                  for o,c in zip(df["open"], df["close"])]
        self.ax_vol.bar(df.index, df["volume"],
                        color=colors, width=self._volume_width())

        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.ax.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(self.ax.xaxis.get_major_locator())
        )

        self.canvas.draw_idle()

    # ---- websocket ----
    def start_ws(self):
        self.stop_ws()
        url = f"wss://stream.binance.com:9443/ws/{self.symbol.lower()}@kline_{self.interval}"

        def on_msg(ws, msg):
            k = json.loads(msg)["k"]
            ts = pd.to_datetime(k["t"], unit="ms")
            row = [float(k["o"]), float(k["h"]),
                   float(k["l"]), float(k["c"]),
                   float(k["v"])]

            if ts in self.df.index:
                self.df.loc[ts] = row
            else:
                self.df = pd.concat(
                    [self.df, pd.DataFrame([row], index=[ts])]
                )

            self.df = self.df.sort_index().iloc[-1500:]
            self.after(0, self.draw_chart)

        self.ws = websocket.WebSocketApp(
            url,
            on_message=on_msg,
            on_error=lambda ws,e: print("WS ERR:", e),
            on_open=lambda ws: print("chart ws open:", self.symbol)
        )

        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    def stop_ws(self):
        try:
            if self.ws:
                self.ws.close()
        except:
            pass
        self.ws = None

    # ---- countdown ----
    def _update_countdown(self):
        if len(self.df) == 0:
            return

        tf_sec = self._get_tf_seconds(self.interval)
        last_open = self.df.index[-1].to_pydatetime()
        next_close = last_open + dt.timedelta(seconds=tf_sec)

        remain = int((next_close - dt.datetime.utcnow()).total_seconds())
        remain = max(0, remain)

        mm, ss = divmod(remain, 60)
        self.count_lbl.configure(text=f"Close in {mm:02d}:{ss:02d}")

        self._countdown_job = self.after(1000, self._update_countdown)

    def refresh(self):
        self.df = load_klines(self.symbol, self.interval)
        self.draw_chart()
        self.start_ws()

    def stop(self):
        if self._countdown_job:
            self.after_cancel(self._countdown_job)
        self.stop_ws()


# =========================
# Dashboard
# =========================
class AtlasDashboard(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")

        self.title("TradingView-Style Dashboard")
        self.geometry("1500x850")

        main = ctk.CTkFrame(self, fg_color="#F4F4F4")
        main.pack(fill="both", expand=True)

        ctrl = ctk.CTkFrame(main, fg_color="white")
        ctrl.pack(fill="x", padx=20, pady=10)

        for tf in ["5m","15m","30m","1h","4h","1d"]:
            ctk.CTkButton(
                ctrl, text=tf, width=50,
                command=lambda t=tf: self.change_tf(t)
            ).pack(side="left", padx=4)

        self.chart = TVLineChart(main, "BTCUSDT", "30m")
        self.chart.pack(fill="both", expand=True, padx=20, pady=10)

    def change_tf(self, tf):
        self.chart.interval = tf
        self.chart.refresh()


if __name__ == "__main__":
    app = AtlasDashboard()
    app.mainloop()
