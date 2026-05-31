import os
import pandas as pd
import ccxt.async_support as ccxt # Use async version of ccxt
from typing import Optional, Dict, List, Any
from abc import ABC, abstractmethod
import random
from datetime import datetime, timezone, timedelta

from .config import data_folder, EXCHANGE_CREDENTIALS
from .utils.logging_config import get_logger

logger = get_logger(__name__)

class BaseDataProvider(ABC):
    """
    Abstract base class for data providers.
    Requires subclasses to implement get_market_data_rest.
    """
    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.error: Optional[str] = None

    @abstractmethod
    async def get_market_data_rest(self, symbol: str, exchange_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the latest market data for a single symbol from a specific exchange.
        Expected return keys: 'timestamp', 'bid', 'ask', 'mid_price', 'baseVolume' (or 'volume'), 'symbol'.
        Timestamp should be ISO 8601 format string with 'Z' for UTC.
        """
        pass

class SimulatedSingleExchangeDataProvider(BaseDataProvider):
    """
    Provides simulated market data for a single exchange using a random walk.
    """
    def __init__(self, symbols: List[str], initial_prices: Optional[Dict[str, float]] = None):
        super().__init__(symbols)
        self.last_prices: Dict[str, float] = {}
        self.last_volumes: Dict[str, float] = {}
        self._is_generating = False

        self.default_initial_prices = {
            'BTC/USDT': 60000.0, # Adjusted to a more common current range
            'ETH/USDT': 3500.0,
            'BNB/USDT': 600.0,
        }
        
        for symbol in self.symbols:
            self.last_prices[symbol] = (initial_prices.get(symbol) if initial_prices 
                                       else self.default_initial_prices.get(symbol, 100.0))
            self.last_volumes[symbol] = random.uniform(1, 100)

    async def start_data_generation(self):
        """Start generating simulated market data."""
        if not self._is_generating:
            self._is_generating = True
            logger.info("Started simulated data generation")
            # Initialize data for all symbols
            for symbol in self.symbols:
                await self._generate_initial_data(symbol)

    async def _generate_initial_data(self, symbol: str):
        """Generate initial data for a symbol."""
        try:
            # Generate initial data point
            data = {
                'timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                'bid': self.last_prices[symbol] * 0.9999,  # Small spread
                'ask': self.last_prices[symbol] * 1.0001,
                'mid_price': self.last_prices[symbol],
                'baseVolume': self.last_volumes[symbol],
                'symbol': symbol,
                'exchange': 'simulated'
            }
            self.last_prices[symbol] = data['mid_price']
            self.last_volumes[symbol] = data['baseVolume']
            logger.info(f"Generated initial data for {symbol}")
        except Exception as e:
            logger.error(f"Error generating initial data for {symbol}: {str(e)}")

    async def get_market_data_rest(self, symbol: str, exchange_name: str) -> Optional[Dict[str, Any]]:
        self.error = None
        try:
            # Handle URL-encoded symbols (e.g., "BTC%2FUSDT" -> "BTC/USDT")
            symbol = symbol.replace("%2F", "/").replace("%2f", "/")
            
            # Handle case where symbol is not in the list but matches when normalized
            normalized_symbol = symbol.upper()
            normalized_symbols = [s.upper() for s in self.symbols]
            if normalized_symbol not in normalized_symbols:
                self.error = f"Symbol {symbol} not configured for SimulatedSingleExchangeDataProvider."
                logger.warning(self.error)
                return None

            # Get the original symbol with correct case
            symbol = self.symbols[normalized_symbols.index(normalized_symbol)]

            # Simulate price movement (random walk)
            price_change_factor = 1 + random.uniform(-0.0005, 0.0005) # +/- 0.05%
            current_mid_price = self.last_prices[symbol] * price_change_factor
            # No artificial exchange offset. Both exchanges share the same random walk baseline,
            # which is realistic for highly liquid pairs. Real arbitrage opportunities arise from
            # natural microstructure noise, not a planted offset.

            # Simulate a small spread
            spread_percentage = random.uniform(0.0001, 0.0005) # 0.01% to 0.05% spread
            bid_price = current_mid_price * (1 - spread_percentage / 2)
            ask_price = current_mid_price * (1 + spread_percentage / 2)

            # Simulate volume
            volume_change_factor = 1 + random.uniform(-0.05, 0.05) # +/- 5%
            current_volume = self.last_volumes[symbol] * volume_change_factor
            current_volume = max(0.1, current_volume) # Ensure volume is positive

            # Update last known values
            self.last_prices[symbol] = (bid_price + ask_price) / 2 # Use the new mid_price based on simulated bid/ask
            self.last_volumes[symbol] = current_volume
            
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

            return {
                'timestamp': timestamp,
                'bid': bid_price,
                'ask': ask_price,
                'mid_price': self.last_prices[symbol],
                'baseVolume': current_volume, # For CCXT compatibility, 'baseVolume' is common
                'symbol': symbol,
                'exchange': exchange_name # Include the exchange name for clarity
            }
        except Exception as e:
            self.error = f"Error generating simulated data for {symbol} on {exchange_name}: {str(e)}"
            logger.error(self.error, exc_info=True)
            return None

    async def get_historical_data(self, symbol: str, exchange_name: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        # timeframe is not strictly used in this simulated version but kept for interface consistency
        self.error = None
        records = []

        # Try to get an initial price for the historical generation
        # Start from a point further in the "past" for the series
        base_historical_price = self.last_prices.get(symbol, self.default_initial_prices.get(symbol, 100.0))
        temp_current_mid_price = base_historical_price * (1 - 0.0001 * limit) # Start simulation from a slightly "older" price
        temp_current_volume = self.last_volumes.get(symbol, random.uniform(1,100))

        for i in range(limit):
            # Create a unique timestamp for each historical point by going back in time
            mock_timestamp = datetime.now(timezone.utc) - timedelta(minutes=(limit - i))
            
            # Simulate price movement for this historical point
            price_change_factor = 1 + random.uniform(-0.0003, 0.0003) # Slightly smaller changes for historical stability
            temp_current_mid_price *= price_change_factor

            # No artificial exchange offset — use raw price for all exchanges.
            adjusted_historical_mid_price = temp_current_mid_price

            spread_percentage = random.uniform(0.0001, 0.0005)
            bid_price = adjusted_historical_mid_price * (1 - spread_percentage / 2)
            ask_price = adjusted_historical_mid_price * (1 + spread_percentage / 2)
            
            volume_change_factor = 1 + random.uniform(-0.03, 0.03)
            temp_current_volume *= volume_change_factor
            temp_current_volume = max(0.1, temp_current_volume)

            data_point = {
                'timestamp': mock_timestamp.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                'open': adjusted_historical_mid_price * (1 - random.uniform(0, 0.0001)),
                'high': adjusted_historical_mid_price * (1 + random.uniform(0, 0.0002)),
                'low': adjusted_historical_mid_price * (1 - random.uniform(0, 0.0002)),
                'close': adjusted_historical_mid_price,
                'volume': temp_current_volume,
                'bid': bid_price,
                'ask': ask_price,
                'mid_price': adjusted_historical_mid_price 
            }
            records.append(data_point)

        if not records:
            self.error = f"No historical data generated for {symbol} on {exchange_name}"
            logger.warning(self.error)
            return None

        df = pd.DataFrame(records)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
        return df

class CCXTSingleExchangeDataProvider(BaseDataProvider):
    """
    Provides live market data from Binance and Kraken via CCXT public endpoints.

    Uses NO API credentials — fetch_ticker is a public endpoint on both exchanges.
    This avoids the issue where ccxt sends an invalid key header and Binance
    rejects even public requests.
    """
    def __init__(self, symbols: List[str]):
        super().__init__(symbols)
        self.ccxt_clients: Dict[str, ccxt.Exchange] = {}
        # Public-only clients — no API key sent in headers.
        public_params = {"enableRateLimit": True, "options": {"defaultType": "spot"}}
        self.ccxt_clients['binance'] = ccxt.binance(public_params)
        self.ccxt_clients['kraken']  = ccxt.kraken(public_params)

    async def start_data_generation(self):
        """No-op for the CCXT provider — data is fetched on demand."""
        logger.info("CCXTSingleExchangeDataProvider ready (real market data via public API).")

    async def get_historical_data(self, symbol: str, exchange_name: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        """Fetch recent OHLCV bars to pre-seed the signal processor."""
        client = await self._get_client(exchange_name)
        if not client:
            return None
        try:
            ohlcv = await client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv:
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df = df.set_index('timestamp')
            # Approximate bid/ask from close ± half the typical 0.01% spread
            df['bid'] = df['close'] * 0.9999
            df['ask'] = df['close'] * 1.0001
            return df
        except Exception as e:
            logger.warning(f"Could not fetch historical OHLCV for {symbol} on {exchange_name}: {e}")
            return None

    async def _get_client(self, exchange_name: str) -> Optional[ccxt.Exchange]:
        exchange_id = exchange_name.lower()
        if exchange_id not in self.ccxt_clients:
            try:
                exchange_class = getattr(ccxt, exchange_id)
                self.ccxt_clients[exchange_id] = exchange_class({"enableRateLimit": True, "options": {"adjustForTimeDifference": True}})
                logger.info(f"Initialized CCXT client for {exchange_id} on demand.")
            except AttributeError:
                self.error = f"CCXT does not support exchange: {exchange_name}"
                logger.error(self.error)
                return None
            except Exception as e:
                self.error = f"Failed to initialize CCXT client for {exchange_name}: {str(e)}"
                logger.error(self.error, exc_info=True)
                return None
        return self.ccxt_clients[exchange_id]

    async def get_market_data_rest(self, symbol: str, exchange_name: str) -> Optional[Dict[str, Any]]:
        self.error = None
        client = await self._get_client(exchange_name)
        if not client:
            return None

        try:
            # fetch_ticker provides a snapshot including bid, ask, volume, timestamp
            ticker = await client.fetch_ticker(symbol)
            
            if not ticker or ticker.get('bid') is None or ticker.get('ask') is None:
                self.error = f"Incomplete ticker data for {symbol} on {exchange_name}."
                logger.warning(self.error)
                return None

            timestamp_ms = ticker.get('timestamp')
            iso_timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z') if timestamp_ms else datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            
            bid_price = float(ticker['bid'])
            ask_price = float(ticker['ask'])
            mid_price = (bid_price + ask_price) / 2
            # Volume keys can vary: 'baseVolume', 'volume', 'quoteVolume'
            # 'baseVolume' is preferred if available (volume in terms of the base currency)
            base_volume = float(ticker.get('baseVolume', ticker.get('volume', 0.0)))

            return {
                'timestamp': iso_timestamp,
                'bid': bid_price,
                'ask': ask_price,
                'mid_price': mid_price,
                'baseVolume': base_volume,
                'symbol': symbol,
                'exchange': exchange_name
            }
        except ccxt.NetworkError as e:
            self.error = f"CCXT NetworkError for {symbol} on {exchange_name}: {str(e)}"
            logger.error(self.error)
            return None
        except ccxt.ExchangeError as e:
            self.error = f"CCXT ExchangeError for {symbol} on {exchange_name}: {str(e)}"
            logger.error(self.error)
            # Specific handling for "symbol not found" type errors
            if 'not found' in str(e).lower() or 'unavailable' in str(e).lower():
                 logger.warning(f"Symbol {symbol} may not be available on {exchange_name}. Error: {e}")
            return None
        except Exception as e:
            self.error = f"General error fetching CCXT data for {symbol} on {exchange_name}: {str(e)}"
            logger.error(self.error, exc_info=True)
            return None
        # Ensure client is closed if it was dynamically created and might not be reused soon.
        # For long-running app, keeping clients might be better.
        # await client.close() # Consider session management for HTTP clients in ccxt

# --- Old InterExchangeDataProvider (Commented out, can be renamed/repurposed if needed) ---
"""
class OldDataProvider: # Renamed to avoid conflict, was DataProvider
    def __init__(self, live: bool = True, backtest_dir: str = None):
        self.live = live
        self.error = None
        
        if self.live:
            try:
                common_params = {"enableRateLimit": True, "options": {"adjustForTimeDifference": True}}
                self.binance = ccxt.binance(common_params) # ccxt.binance, not ccxt.async_support.binance
                self.kraken  = ccxt.kraken(common_params)
            except Exception as e:
                self.live = False 
                self.error = f"Failed to initialize CCXT clients: {str(e)}"
        else:
            self.backtest_dir = backtest_dir or os.path.join(data_folder, "processed")
            self._dfs = {}
            self._ptrs = {}
            if not os.path.isdir(self.backtest_dir):
                 self.error = f"Backtest directory not found: {self.backtest_dir}"

    def get_top_of_book(self, symbol: str) -> Optional[Dict]:
        self.error = None 

        if self.live:
            if not hasattr(self, 'binance') or not hasattr(self, 'kraken'):
                 self.error = "CCXT clients not initialized for live mode."
                 return None
            try:
                bkb = self.binance.fetch_order_book(symbol, limit=1)
                krb = self.kraken.fetch_order_book(symbol, limit=1)

                if not bkb or not bkb.get('bids') or not bkb['bids'] or not bkb.get('asks') or not bkb['asks']:
                    raise ValueError(f"Binance order book for {symbol} is empty or malformed.")
                if not krb or not krb.get('bids') or not krb['bids'] or not krb.get('asks') or not krb['asks']:
                    raise ValueError(f"Kraken order book for {symbol} is empty or malformed.")

                return {
                    'binance': {'bid': bkb['bids'][0][0], 'ask': bkb['asks'][0][0]},
                    'kraken' : {'bid': krb['bids'][0][0], 'ask': krb['asks'][0][0]},
                }
            except ccxt.NetworkError as e: # ccxt.NetworkError, not ccxt.async_support.NetworkError
                self.error = f"NetworkError fetching live data for {symbol}: {str(e)}"
                return None
            except ccxt.ExchangeError as e: # ccxt.ExchangeError
                self.error = f"ExchangeError fetching live data for {symbol}: {str(e)}"
                return None
            except Exception as e:
                self.error = f"General error fetching live data for {symbol}: {str(e)}"
                return None
        else: 
            if hasattr(self, 'error') and self.error and "Backtest directory not found" in self.error:
                return None 

            if symbol not in self._dfs:
                try:
                    path = os.path.join(self.backtest_dir, f"{symbol.replace('/', '_')}.csv")
                    if not os.path.exists(path):
                        self.error = f"Backtest file not found: {path}"
                        self._dfs[symbol] = None 
                        return None
                    
                    df = pd.read_csv(path)
                    if df.empty:
                        self.error = f"Backtest file is empty: {path}"
                        self._dfs[symbol] = None 
                        return None
                    
                    required_cols = ['binance_bid', 'binance_ask', 'kraken_bid', 'kraken_ask']
                    if not all(col in df.columns for col in required_cols):
                        self.error = f"Backtest file {path} missing one or more required columns: {required_cols}"
                        self._dfs[symbol] = None
                        return None

                    self._dfs[symbol] = df
                    self._ptrs[symbol] = 0
                except Exception as e:
                    self.error = f"Error loading backtest data for {symbol} from {path}: {str(e)}"
                    self._dfs[symbol] = None 
                    return None
            
            if self._dfs.get(symbol) is None:
                if not self.error: 
                    self.error = f"Failed to load backtest data for {symbol}, DataFrame is None."
                return None

            df = self._dfs[symbol]
            idx = self._ptrs[symbol]

            if idx >= len(df):
                self.error = f"End of backtest data reached for {symbol} (index {idx} >= length {len(df)})."
                return None 

            row = df.iloc[idx]
            self._ptrs[symbol] = idx + 1

            return {
                'binance': {'bid': row['binance_bid'], 'ask': row['binance_ask']},
                'kraken' : {'bid': row['kraken_bid'], 'ask': row['kraken_ask']},
            }
""" 