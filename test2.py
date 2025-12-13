import tkinter as tk
from tkinter import ttk
import websocket
import json
import threading
import numpy as np
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt  # Correct import for matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class CryptoTicker:
    """Reusable ticker component for any cryptocurrency."""
    
    def __init__(self, parent, symbol, display_name):
        self.parent = parent
        self.symbol = symbol.lower()
        self.display_name = display_name
        self.is_active = False
        self.ws = None
        self.price_data = []
        self.ohlc_data = []
        
        # Create UI
        self.frame = ttk.Frame(parent, relief="solid", borderwidth=1, padding=20)
        
        # Title
        ttk.Label(self.frame, text=display_name, 
                 font=("Georgia", 16, "bold")).pack()
        
        # Price
        self.price_label = tk.Label(self.frame, text="--,---", 
                                    font=("Georgia", 40, "bold"))
        self.price_label.pack(pady=10)
        
        # Change
        self.change_label = ttk.Label(self.frame, text="--", 
                                      font=("Georgia", 12))
        self.change_label.pack()

        # Create Matplotlib Figure and Canvas for Candlestick Chart
        self.fig, self.ax = plt.subplots(figsize=(6, 3))
        self.canvas = FigureCanvasTkAgg(self.fig, self.frame)
        self.canvas.get_tk_widget().pack(pady=10)
        
        # Title and labels for the chart
        self.ax.set_title(f"Price of {display_name}")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Price (USDT)")
        
    def start(self):
        """Start WebSocket connection."""
        if self.is_active:
            return
        
        self.is_active = True
        ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_1m"
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_message,
            on_error=lambda ws, err: print(f"{self.symbol} error: {err}"),
            on_close=lambda ws, s, m: print(f"{self.symbol} closed"),
            on_open=lambda ws: print(f"{self.symbol} connected")
        )
        
        threading.Thread(target=self.ws.run_forever, daemon=True).start()
    
    def stop(self):
        """Stop WebSocket connection."""
        self.is_active = False
        if self.ws:
            self.ws.close()
            self.ws = None
    
    def on_message(self, ws, message):
        """Handle price updates."""
        if not self.is_active:
            return
        
        data = json.loads(message)
        kline = data['k']
        open_price = float(kline['o'])
        high_price = float(kline['h'])
        low_price = float(kline['l'])
        close_price = float(kline['c'])
        volume = float(kline['v'])
        timestamp = int(kline['t'])
        
        # Add data to the OHLC array
        self.ohlc_data.append([timestamp, open_price, high_price, low_price, close_price, volume])
        
        # If we have enough data points, we update the chart
        if len(self.ohlc_data) >= 5:  # Can adjust as needed
            self.ohlc_data = self.ohlc_data[-100:]  # Keep only the latest 100 points

        # Schedule GUI update on main thread
        self.parent.after(0, self.update_display)
    
    def update_display(self):
        """Update the candlestick chart."""
        if not self.is_active:
            return
        
        # Convert the price data to a DataFrame for mplfinance
        df = pd.DataFrame(self.ohlc_data, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit='ms')
        df.set_index("Timestamp", inplace=True)
        
        # Clear the current axes
        self.ax.clear()

        # Style for TradingView-like dark theme with volume bars
        mc = mpf.make_marketcolors(up='green', down='red', inherit=True)
        s = mpf.make_mpf_style(base_mpf_style='dark', marketcolors=mc)

        # Create the candlestick chart using mplfinance
        mpf.plot(df, ax=self.ax, type='candle', style=s, title=f"{self.display_name} - Candlestick", ylabel="Price (USDT)", volume=True)
        
        # Update the price label
        last_price = df["Close"].iloc[-1] if not df.empty else 0
        self.price_label.config(text=f"{last_price:,.2f}")
        
        # Update the change label (example, can use different logic)
        if len(df) > 1:
            change = last_price - df["Close"].iloc[-2]
            percent_change = (change / df["Close"].iloc[-2]) * 100
            color = "green" if change >= 0 else "red"
            sign = "+" if change >= 0 else ""
            self.change_label.config(
                text=f"{sign}{change:,.2f} ({sign}{percent_change:.2f}%)",
                foreground=color
            )
        
        # Redraw the canvas
        self.canvas.draw()

    def pack(self, **kwargs):
        """Allow easy placement of ticker."""
        self.frame.pack(**kwargs)
    
    def pack_forget(self):
        """Hide the ticker."""
        self.frame.pack_forget()


class MultiTickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Crypto Dashboard")
        self.root.geometry("1000x600")
        
        # Create ticker panel
        ticker_frame = ttk.Frame(root, padding=20)
        ticker_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create BTC ticker
        self.btc_ticker = CryptoTicker(ticker_frame, "btcusdt", "BTC/USDT")
        self.btc_ticker.pack(side=tk.LEFT, padx=10, fill=tk.BOTH, expand=True)
        
        # Create ETH ticker
        self.eth_ticker = CryptoTicker(ticker_frame, "ethusdt", "ETH/USDT")
        self.eth_ticker.pack(side=tk.LEFT, padx=10, fill=tk.BOTH, expand=True)
        
        # Start both tickers
        self.btc_ticker.start()
        self.eth_ticker.start()
    
    def on_closing(self):
        """Clean up when closing."""
        self.btc_ticker.stop()
        self.eth_ticker.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MultiTickerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
