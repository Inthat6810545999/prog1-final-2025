import tkinter as tk
from tkinter import ttk
import websocket
import json
import threading

class CryptoTicker:
    """Reusable ticker component for any cryptocurrency."""
    
    def __init__(self, parent, symbol, display_name):
        self.parent = parent
        self.symbol = symbol.lower()
        self.display_name = display_name
        self.is_active = False
        self.ws = None
        
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
    
    def start(self):
        """Start WebSocket connection."""
        if self.is_active:
            return
        
        self.is_active = True
        ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol}@ticker"
        
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
        price = float(data['c'])
        change = float(data['p'])
        percent = float(data['P'])
        
        # Schedule GUI update on main thread
        self.parent.after(0, self.update_display, price, change, percent)
    
    def update_display(self, price, change, percent):
        """Update the ticker display."""
        if not self.is_active:
            return
        
        color = "green" if change >= 0 else "red"
        self.price_label.config(text=f"{price:,.2f}", fg=color)
        
        sign = "+" if change >= 0 else ""
        self.change_label.config(
            text=f"{sign}{change:,.2f} ({sign}{percent:.2f}%)",
            foreground=color
        )
    
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
        self.root.geometry("800x300")
        
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

class ToggleableTickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Crypto Dashboard with Toggle")
        self.root.geometry("1000x400")
        
        # Control panel
        control_frame = ttk.Frame(root, padding=10)
        control_frame.pack(fill=tk.X)
        
        self.sol_btn = ttk.Button(
            control_frame, 
            text="Show SOL/USDT",
            command=self.toggle_sol
        )
        self.sol_btn.pack()
        
        # Ticker panel
        self.ticker_frame = ttk.Frame(root, padding=20)
        self.ticker_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create tickers
        self.btc_ticker = CryptoTicker(self.ticker_frame, "btcusdt", "BTC/USDT")
        self.btc_ticker.pack(side=tk.LEFT, padx=10, fill=tk.BOTH, expand=True)
        
        self.eth_ticker = CryptoTicker(self.ticker_frame, "ethusdt", "ETH/USDT")
        self.eth_ticker.pack(side=tk.LEFT, padx=10, fill=tk.BOTH, expand=True)
        
        self.sol_ticker = CryptoTicker(self.ticker_frame, "solusdt", "SOL/USDT")
        # Don't pack SOL initially (hidden)
        
        # Start BTC and ETH
        self.btc_ticker.start()
        self.eth_ticker.start()
        
        self.sol_visible = False
    
    def toggle_sol(self):
        """Show or hide SOL ticker."""
        if self.sol_visible:
            # Hide SOL
            self.sol_ticker.stop()
            self.sol_ticker.pack_forget()
            self.sol_btn.config(text="Show SOL/USDT")
            self.sol_visible = False
        else:
            # Show SOL
            self.sol_ticker.pack(side=tk.LEFT, padx=10, fill=tk.BOTH, expand=True)
            self.sol_ticker.start()
            self.sol_btn.config(text="Hide SOL/USDT")
            self.sol_visible = True
    
    def on_closing(self):
        """Clean up when closing."""
        self.btc_ticker.stop()
        self.eth_ticker.stop()
        self.sol_ticker.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ToggleableTickerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
