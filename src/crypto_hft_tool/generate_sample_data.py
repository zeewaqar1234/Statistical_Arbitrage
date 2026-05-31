import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
from .config import data_folder

def generate_sample_data(symbol: str, num_rows: int = 1000):
    """Generate synthetic order book data for testing."""
    # Base prices (approximate market prices)
    base_prices = {
        "BTC/USDT": 60000,
        "ETH/USDT": 3000
    }
    base_price = base_prices.get(symbol, 100)
    
    # Generate timestamps
    start_time = datetime.now() - timedelta(hours=num_rows/60)  # 1 minute intervals
    timestamps = [int((start_time + timedelta(minutes=i)).timestamp()) for i in range(num_rows)]
    
    # Generate price movements with some randomness
    price_movement = np.random.normal(0, 0.001, num_rows)  # Small random movements
    price_multiplier = np.cumprod(1 + price_movement)  # Cumulative effect
    
    # Generate data for each exchange
    data = []
    for i in range(num_rows):
        current_price = base_price * price_multiplier[i]
        
        # Both exchanges trade around the same mid-price with independent micro-noise.
        # No injected cross-exchange offset — that would fabricate arbitrage.
        binance_noise = np.random.normal(0, 0.5)   # USDT
        kraken_noise  = np.random.normal(0, 0.5)

        # Generate order book data (each exchange has a 1.0 USDT bid/ask spread)
        row = {
            'timestamp': timestamps[i],
            'binance_bid': current_price + binance_noise,
            'binance_ask': current_price + binance_noise + 1.0,
            'kraken_bid': current_price + kraken_noise,
            'kraken_ask': current_price + kraken_noise + 1.0,
        }
        data.append(row)
    
    return pd.DataFrame(data)

def save_sample_data():
    """Generate and save SYNTHETIC data for unit-testing only.
    
    WARNING: This data is not suitable for backtesting strategy performance.
    For real backtests use scripts/download_real_data.py to fetch genuine
    1-minute candles from Binance and Kraken via ccxt.
    """
    processed_dir = os.path.join(data_folder, "processed")
    os.makedirs(processed_dir, exist_ok=True)

    symbols = ["BTC/USDT", "ETH/USDT"]
    for symbol in symbols:
        df = generate_sample_data(symbol)
        output_file = os.path.join(processed_dir, f"{symbol.replace('/', '_')}.csv")
        df.to_csv(output_file, index=False)
        print(f"[SYNTHETIC DATA — unit-test only] Saved {symbol} to {output_file}")

if __name__ == "__main__":
    save_sample_data() 