#!/usr/bin/env python3
"""
TastyTracker Delta Backend
Streams live delta data from Tastytrade and serves it via Flask API
"""

import os, sys, time, json, asyncio, threading, logging, websockets
from datetime import datetime, timezone
from collections import defaultdict, deque
from typing import Dict, List, Optional, Any

# Flask and CORS
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

# Environment and Tastytrade API
import dotenv
dotenv.load_dotenv()

from tastytrade import Session, Account
from tastytrade_sdk import Tastytrade
from tastytrade_sdk.market_data.streamer_symbol_translation import StreamerSymbolTranslationsFactory
import requests

# --- Configuration & Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('tastytrade').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)

# Enable debug logging for pricing issues
price_logger = logging.getLogger('pricing')
price_logger.setLevel(logging.INFO)

class DeltaTracker:
    # --- Field Index Constants for Websocket Data ---
    GREEKS_SYMBOL_IDX = 1
    GREEKS_PRICE_IDX = 7
    GREEKS_DELTA_IDX = 9
    GREEKS_RECORD_SIZE = 14

    QUOTE_SYMBOL_IDX = 1
    QUOTE_BID_PRICE_IDX = 7
    QUOTE_ASK_PRICE_IDX = 11
    QUOTE_RECORD_SIZE = 13
    # --- End of Constants ---

    def __init__(self):
        # Account and session details
        self.tasty_client = None
        self.tasty_sdk = None
        self.symbol_translations_factory = None
        self.dxlink_url = None
        self.api_quote_token = None
        self.target_accounts = ["5WX84566", "5WU39639"]
        
        # Data storage with locks for thread safety
        self.positions = {}          # Key: account_specific_key, Value: position info
        self.account_balances = {}   # Key: account_number, Value: balance info
        self.underlying_prices = {}  # Key: underlying_symbol, Value: price
        self.streamer_to_position = {}  # Map streamer symbol to position key
        self.positions_lock = threading.Lock()
        self.balances_lock = threading.Lock()
        self.prices_lock = threading.Lock()
        
        # Websocket and streaming state
        self.websocket = None
        self.running = False

    def _get_login_credentials(self):
        login = os.getenv("TASTYTRADE_LOGIN")
        password = os.getenv("TASTYTRADE_PASSWORD")
        if not login or not password:
            logging.error("🚨 TASTYTRADE_LOGIN and TASTYTRADE_PASSWORD must be set in .env file")
        return login, password

    def initialize_session(self):
        login, password = self._get_login_credentials()
        if not login or not password:
            return False
        try:
            logging.info("🔄 Establishing Tastytrade session...")
            # Initialize old SDK for existing functionality
            self.tasty_client = Session(login, password)
            self.api_quote_token = self.tasty_client.streamer_token
            self.dxlink_url = self.tasty_client.dxlink_url
            
            # Initialize new SDK for symbol conversion
            self.tasty_sdk = Tastytrade().login(login, password)
            self.symbol_translations_factory = StreamerSymbolTranslationsFactory(self.tasty_sdk.api)
            
            logging.info(f"✅ Session established.")
            return True
        except Exception as e:
            logging.error(f"❌ Session error: {e}")
            return False

    def _update_account_balances_sync(self):
        if not self.tasty_client:
            return
        with self.balances_lock:
            for acc_num in self.target_accounts:
                try:
                    account = Account.get(self.tasty_client, acc_num)
                    balance = account.get_balances(self.tasty_client)
                    if balance:
                        self.account_balances[acc_num] = balance
                        logging.info(f"💰 Fetched balance for {acc_num}: Net Liq = ${balance.net_liquidating_value:,.2f}")
                except Exception as e:
                    logging.error(f"❌ Could not fetch balance for account {acc_num}: {e}")

    def _balance_update_thread(self):
        while True:
            self._update_account_balances_sync()
            time.sleep(30)

    def fetch_positions(self):
        """Fetch positions from all target accounts"""
        try:
            logging.info("🔄 Fetching positions...")
            
            with self.positions_lock:
                self.positions.clear()
                for acc_num in self.target_accounts:
                    account = Account.get(self.tasty_client, acc_num)
                    positions_list = account.get_positions(self.tasty_client)
                    logging.info(f"    ✅ Found {len(positions_list)} positions in account {acc_num}")
                    for pos in positions_list:
                        quantity = float(pos.quantity) * (-1 if pos.quantity_direction == 'Short' else 1)
                        if quantity == 0: continue

                        # Handle None mark_price by setting to 0 for now
                        mark_price = float(pos.mark_price) if pos.mark_price is not None else 0.0

                        key = f"{acc_num}:{pos.symbol}"
                        self.positions[key] = {
                            'account_number': acc_num,
                            'symbol_occ': pos.symbol,
                            'underlying_symbol': pos.underlying_symbol,
                            'instrument_type': pos.instrument_type,
                            'quantity': quantity,
                            'strike_price': float(pos.strike_price) if hasattr(pos, 'strike_price') and pos.strike_price else None,
                            'option_type': getattr(pos, 'option_type', None),
                            'price': mark_price,
                            'notional': 0, # will be calculated
                            'delta': 1.0 if pos.instrument_type == 'Equity' else 0,
                            'position_delta': quantity if pos.instrument_type == 'Equity' else 0,
                            'net_liq': mark_price * quantity * (100 if pos.instrument_type == 'Equity Option' else 1)
                        }

            # Set fallback underlying prices from CSV data
            self._set_csv_underlying_prices()

            logging.info(f"✅ Position loading complete. Total loaded: {len(self.positions)}")
            return len(self.positions) > 0
        except Exception as e:
            logging.error(f"❌ Error fetching positions: {e}")
            return False

    def _convert_occ_to_streamer(self, occ_symbol):
        """Convert OCC format to streamer symbol format using the SDK."""
        try:
            if not self.symbol_translations_factory:
                logging.error("Symbol translations factory not initialized")
                return None
            
            # Create translations for this symbol
            translations = self.symbol_translations_factory.create([occ_symbol])
            streamer_symbol = translations.get_streamer_symbol(occ_symbol)
            
            if streamer_symbol:
                logging.debug(f"✅ Converted {occ_symbol} -> {streamer_symbol}")
                return streamer_symbol
            else:
                logging.warning(f"⚠️ No streamer symbol found for {occ_symbol}")
                return None
        except Exception as e:
            logging.error(f"Error converting {occ_symbol}: {e}")
            return None

    def _set_csv_underlying_prices(self):
        """Set underlying prices from CSV data as fallback since Quote feeds aren't working"""
        csv_prices = {
            'AMD': 123.68,
            'HOOD': 71.69, 
            'IBIT': 61.90,
            'AMZN': 216.37,
            'ASML': 787.68,
            'GOOGL': 179.75,
            'META': 698.65,
            'PYPL': 74.85,
            'QQQ': 532.85,
            'SHOP': 109.14,
            'SOFI': 14.30,
            'TSLA': 317.05
        }
        
        with self.prices_lock:
            for symbol, price in csv_prices.items():
                self.underlying_prices[symbol] = price
                logging.info(f"📊 Set fallback price for {symbol}: ${price:.2f}")
        
        # Immediately recalculate notionals to update stock prices
        self._recalculate_notionals()
        
        logging.info(f"✅ Set {len(csv_prices)} fallback underlying prices from CSV data")

    async def _connect_and_subscribe(self):
        try:
            logging.info(f"🔄 Connecting to DXLink websocket at {self.dxlink_url}...")
            async with websockets.connect(self.dxlink_url) as self.websocket:
                logging.info("✅ Websocket connected!")
                
                await self.websocket.send(json.dumps({"type": "SETUP", "channel": 0, "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60, "version": "1.0.0"}))
                await self.websocket.recv() 
                await self.websocket.recv() 

                await self.websocket.send(json.dumps({"type": "AUTH", "channel": 0, "token": self.api_quote_token}))
                auth_response = json.loads(await self.websocket.recv())
                if auth_response.get('state') != 'AUTHORIZED':
                    logging.error("❌ Websocket authorization failed.")
                    return False
                
                logging.info("✅ Websocket authorized.")
                await self.websocket.send(json.dumps({"type": "CHANNEL_REQUEST", "channel": 1, "service": "FEED", "parameters": {"contract": "AUTO"}}))
                await self.websocket.recv()

                # Create symbol mapping and subscription lists
                self.streamer_to_position = {}  # Map streamer symbol to list of position keys
                option_subscriptions = []
                underlying_symbols = set()
                subscribed_symbols = set()  # Track symbols we've already subscribed to
                
                with self.positions_lock:
                    for key, pos in self.positions.items():
                        underlying_symbols.add(pos['underlying_symbol'])
                        
                        if pos['instrument_type'] == 'Equity Option':
                            # Convert OCC symbol to streamer symbol
                            streamer_symbol = self._convert_occ_to_streamer(pos['symbol_occ'])
                            if streamer_symbol:
                                # Support multiple positions with the same streamer symbol
                                if streamer_symbol not in self.streamer_to_position:
                                    self.streamer_to_position[streamer_symbol] = []
                                self.streamer_to_position[streamer_symbol].append(key)
                                
                                # Only subscribe once per unique streamer symbol
                                if streamer_symbol not in subscribed_symbols:
                                    option_subscriptions.append({"symbol": streamer_symbol, "type": "Greeks"})
                                    option_subscriptions.append({"symbol": streamer_symbol, "type": "Quote"})
                                    subscribed_symbols.add(streamer_symbol)
                                
                                logging.info(f"📈 Mapped {pos['symbol_occ']} -> {streamer_symbol}")
                            else:
                                logging.warning(f"⚠️ Could not convert symbol: {pos['symbol_occ']}")
                
                # Subscribe to underlying quotes
                underlying_subscriptions = [{"symbol": s, "type": "Quote"} for s in underlying_symbols]
                
                all_subscriptions = option_subscriptions + underlying_subscriptions
                
                await self.websocket.send(json.dumps({"type": "FEED_SUBSCRIPTION", "channel": 1, "add": all_subscriptions}))
                logging.info(f"📈 Subscribed to {len(all_subscriptions)} feeds ({len(option_subscriptions)} options, {len(underlying_subscriptions)} underlyings).")

                self.running = True
                await self._streaming_loop()
        except Exception as e:
            logging.error(f"❌ Websocket connection failed: {e}")
            self.running = False

    async def _streaming_loop(self):
        logging.info("🚀 Delta tracking started! Waiting for live data...\n")
        while self.running:
            try:
                message = await asyncio.wait_for(self.websocket.recv(), timeout=65)
                data = json.loads(message)
                if data.get('type') == 'FEED_DATA':
                    await self._handle_feed_data(data['data'])
                elif data.get('type') == 'KEEPALIVE':
                    await self.websocket.send(json.dumps({"type": "KEEPALIVE"}))
            except asyncio.TimeoutError:
                logging.warning("Connection timed out, will attempt to reconnect.")
                break
            except websockets.exceptions.ConnectionClosed:
                logging.warning("❌ Websocket connection closed.")
                break
            except Exception as e:
                logging.error(f"❌ Streaming error: {e}")

    async def _handle_feed_data(self, events):
        """Handle incoming live data from WebSocket in flat array format"""
        try:
            if len(events) < 2:
                return
                
            event_type = events[0]
            
            if event_type == 'Greeks':
                greeks_data = events[1]
                i = 0
                while i + self.GREEKS_RECORD_SIZE <= len(greeks_data):
                    if greeks_data[i] == 'Greeks':
                        symbol = greeks_data[i + self.GREEKS_SYMBOL_IDX]
                        price = greeks_data[i + self.GREEKS_PRICE_IDX]
                        delta = greeks_data[i + self.GREEKS_DELTA_IDX]
                        
                        if symbol and delta is not None and isinstance(delta, (int, float)):
                            # Use streamer symbol mapping to find all positions with this symbol
                            position_keys = self.streamer_to_position.get(symbol, [])
                            if position_keys:
                                with self.positions_lock:
                                    for position_key in position_keys:
                                        if position_key in self.positions:
                                            pos = self.positions[position_key]
                                            pos['delta'] = float(delta)
                                            pos['position_delta'] = pos['quantity'] * float(delta) * 100
                                            if price is not None and isinstance(price, (int, float)):
                                                pos['price'] = float(price)
                                                pos['net_liq'] = pos['quantity'] * float(price) * 100
                                            logging.info(f"📊 Updated {pos['symbol_occ']} (Acct: {pos['account_number']}): Δ={delta:.4f}, P=${price:.2f}")
                    
                    i += self.GREEKS_RECORD_SIZE  # Move to next Greeks record
                    
            elif event_type == 'Quote':
                quote_data = events[1]
                i = 0
                while i < len(quote_data):
                    if i + 1 < len(quote_data) and quote_data[i] == 'Quote':
                        symbol = quote_data[i + self.QUOTE_SYMBOL_IDX]
                        
                        # Quote structure - look for bid/ask in specific positions
                        if i + self.QUOTE_RECORD_SIZE <= len(quote_data):
                            try:
                                bid_price = quote_data[i + self.QUOTE_BID_PRICE_IDX]
                                ask_price = quote_data[i + self.QUOTE_ASK_PRICE_IDX]
                                
                                if (isinstance(bid_price, (int, float)) and isinstance(ask_price, (int, float)) 
                                    and bid_price > 0 and ask_price > 0 and ask_price >= bid_price):
                                    
                                    price = (float(bid_price) + float(ask_price)) / 2
                                    
                                    if symbol and symbol.startswith('.'): # It's an option
                                        # Use streamer symbol mapping to find all positions with this symbol
                                        position_keys = self.streamer_to_position.get(symbol, [])
                                        if position_keys:
                                            with self.positions_lock:
                                                for position_key in position_keys:
                                                    if position_key in self.positions:
                                                        pos = self.positions[position_key]
                                                        pos['price'] = price
                                                        pos['net_liq'] = pos['quantity'] * price * 100
                                    elif symbol: # It's an underlying
                                        with self.prices_lock:
                                            self.underlying_prices[symbol] = price
                            except (IndexError, TypeError, ValueError):
                                pass  # Skip malformed quote data
                        
                        i += self.QUOTE_RECORD_SIZE
                    else:
                        i += 1
            
            self._recalculate_notionals()
            
        except Exception as e:
            logging.error(f"❌ Error parsing feed data: {e}")
            # Don't raise to avoid stopping the stream

    def _recalculate_notionals(self):
        """Calculate notional values for all positions"""
        with self.positions_lock, self.prices_lock:
            for pos in self.positions.values():
                underlying_price = self.underlying_prices.get(pos['underlying_symbol'], 0)
                if pos['instrument_type'] == 'Equity':
                    # For stocks, set the position price to the underlying price
                    pos['price'] = underlying_price
                    pos['notional'] = pos['quantity'] * underlying_price
                    pos['net_liq'] = pos['notional']
                else: # Option
                    pos['notional'] = pos['position_delta'] * underlying_price

    def get_dashboard_data(self, filter_accounts=None):
        with self.positions_lock, self.balances_lock, self.prices_lock:
            positions_copy = list(self.positions.values())
            balances_copy = self.account_balances.copy()
            
            # Filter by account if specified
            if filter_accounts:
                positions_copy = [p for p in positions_copy if p['account_number'] in filter_accounts]
                balances_copy = {k: v for k, v in balances_copy.items() if k in filter_accounts}
            
            grouped_positions = {}
            for pos in positions_copy:
                symbol = pos['underlying_symbol']
                if symbol not in grouped_positions:
                    grouped_positions[symbol] = []
                grouped_positions[symbol].append(pos)

            flattened_list = []
            grouped_list = []
            for symbol, positions_list in sorted(grouped_positions.items()):
                summary_row = {
                    'is_summary': True, 'symbol_root': symbol,
                    'price': self.underlying_prices.get(symbol, 0),
                    'quantity': sum(p['quantity'] for p in positions_list if p['instrument_type'] == 'Equity'),
                    'position_delta': sum(p['position_delta'] for p in positions_list),
                    'notional': sum(p['notional'] for p in positions_list),
                    'net_liq': sum(p['net_liq'] for p in positions_list),
                    'leverage': None, 'delta': None
                }
                if summary_row['quantity'] == 0: summary_row['quantity'] = '-'
                flattened_list.append(summary_row)

                # Add to grouped list for charts
                grouped_list.append({
                    'symbol': symbol,
                    'total_notional': summary_row['notional'],
                    'total_net_liq': summary_row['net_liq']
                })

                for pos in sorted(positions_list, key=lambda p: p.get('strike_price') or 0):
                    pos_copy = pos.copy()
                    notional = pos_copy.get('notional', 0)
                    net_liq = pos_copy.get('net_liq', 0)
                    pos_copy['leverage'] = (notional / net_liq) if net_liq != 0 else 0
                    pos_copy['symbol_root'] = symbol  # Add symbol_root for JavaScript grouping
                    flattened_list.append(pos_copy)

            net_liq_deployed = sum(p['net_liq'] for p in positions_copy)
            total_notional = sum(p['notional'] for p in positions_copy)
            total_net_liq = sum(b.net_liquidating_value for b in balances_copy.values())

            totals = {
                'total_net_liquidating_value': total_net_liq,
                'net_liq_deployed': net_liq_deployed,
                'total_notional': total_notional,
                'total_delta': sum(p['position_delta'] for p in positions_copy),
                'portfolio_leverage': (total_notional / net_liq_deployed) if net_liq_deployed != 0 else 0,
            }
            return {'positions': flattened_list, 'totals': totals, 'grouped_positions': grouped_list}

    async def start(self):
        if not self.initialize_session(): return
        threading.Thread(target=self._balance_update_thread, daemon=True).start()
        
        while True:
            if self.fetch_positions():
                await self._connect_and_subscribe()
            logging.info("Attempting to reconnect in 10 seconds...")
            await asyncio.sleep(10)

# --- Flask App and Endpoints ---
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)
tracker = DeltaTracker()

# Import and setup screener functionality
from screener_backend import create_screener_routes


@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/data')
def api_data():
    # Get account filter from query parameters
    requested_accounts = request.args.getlist('accounts')
    
    # If no accounts specified, return all data
    if not requested_accounts:
        return jsonify(tracker.get_dashboard_data())
    
    # Filter data by requested accounts
    return jsonify(tracker.get_dashboard_data(filter_accounts=requested_accounts))

def run_async_tracker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(tracker.start())

if __name__ == '__main__':
    logging.info("🚀 Starting TastyTracker backend...")
    
    # Initialize screener routes after tracker is created
    create_screener_routes(app, tracker)
    
    threading.Thread(target=run_async_tracker, daemon=True).start()
    logging.info("🌐 Starting dashboard server on http://localhost:5001")
    app.run(host='0.0.0.0', port=5001, debug=False) 