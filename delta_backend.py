#!/usr/bin/env python3
"""
TastyTracker Delta Backend
Streams live delta data from Tastytrade and serves it via Flask API
"""

import os
import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from flask import Flask, jsonify, render_template
from flask_cors import CORS
import websockets
from tastytrade import Session, Account
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging to be less verbose
import logging
logging.getLogger('tastytrade').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)

class DeltaTracker:
    def __init__(self):
        self.positions = {}      # symbol -> position info
        self.deltas = {}         # symbol -> Greeks data
        self.underlying_prices = {}  # underlying symbol -> current price
        self.websocket = None
        self.session = None
        self.account = None
        self.last_update = None
        self.total_delta = 0.0
        self.running = False
        self.api_quote_token = None
        self.dxlink_url = None
        self.account_numbers = []
        
    def initialize_session(self):
        """Initialize Tastytrade session"""
        try:
            print("🔄 Establishing Tastytrade session...")
            self.session = Session(
                login=os.environ['TASTYTRADE_LOGIN'],
                password=os.environ['TASTYTRADE_PASSWORD']
            )
            
            # Validate session has token
            if hasattr(self.session, 'session_token') and self.session.session_token:
                token = self.session.session_token
                self.api_quote_token = self.session.streamer_token
                self.dxlink_url = self.session.dxlink_url
            else:
                print("❌ No valid token found in session. Please check credentials in .env file.")
                return False
                
            print(f"✅ Session established with token: {token[:20]}...")
            
            # Set your specific account numbers
            self.account_numbers = ["5WX84566", "5WU39639"]
            print(f"🏦 Using accounts: {', '.join(self.account_numbers)}")
            
            return True
        except KeyError as e:
            print(f"❌ Missing environment variable: {e}. Please ensure TASTYTRADE_LOGIN and TASTYTRADE_PASSWORD are in your .env file.")
            return False
        except Exception as e:
            print(f"❌ Session error: {e}")
            return False

    def fetch_positions(self):
        """Fetch all stock and option positions from the broker."""
        try:
            print("🔄 Fetching positions...")
            all_positions_with_accounts = []
            
            all_accounts = Account.get(self.session)
            target_accounts = [acc for acc in all_accounts if acc.account_number in self.account_numbers]
            print(f"📋 Using {len(target_accounts)} target accounts.")
            
            for account in target_accounts:
                print(f"📋 Fetching positions for account: {account.account_number}")
                positions = account.get_positions(self.session)
                for pos in positions:
                    all_positions_with_accounts.append((pos, account.account_number))
            
            print(f"📊 Total positions across all accounts: {len(all_positions_with_accounts)}")
            
            for pos, account_number in all_positions_with_accounts:
                symbol = pos.symbol
                quantity = float(pos.quantity)
                instrument_type = pos.instrument_type
                
                if quantity == 0:
                    continue

                if instrument_type == 'Equity Option':
                    parts = symbol.split()
                    if len(parts) >= 2:
                        underlying = parts[0]
                        option_part = parts[1]
                        date_str, option_type, strike_str = option_part[:6], option_part[6], option_part[7:]
                        strike_dollars = int(strike_str) / 1000
                        strike_display = f"{strike_dollars:.3f}".rstrip('0').rstrip('.')
                        if strike_dollars == int(strike_dollars):
                            strike_display = str(int(strike_dollars))
                        
                        streamer_symbol = f".{underlying}{date_str}{option_type}{strike_display}"
                        
                        self.positions[streamer_symbol] = {
                            'original_symbol': symbol, 'underlying': underlying, 'strike': strike_dollars,
                            'option_type': 'Call' if option_type == 'C' else 'Put', 'quantity': quantity,
                            'expiration': date_str, 'account_number': account_number, 'instrument_type': instrument_type
                        }
                elif instrument_type == 'Equity':
                    self.positions[symbol] = {
                        'original_symbol': symbol, 'underlying': symbol, 'strike': None, 'option_type': 'Stock',
                        'quantity': quantity, 'expiration': None, 'account_number': account_number,
                        'instrument_type': instrument_type
                    }
            
            print(f"✅ Found {len(self.positions)} total stock and option positions.")
            return len(self.positions) > 0
        except Exception as e:
            print(f"❌ Error fetching positions: {e}")
            return False

    async def connect_websocket(self):
        """Connect to DXLink websocket"""
        try:
            print("🔄 Connecting to DXLink websocket...")
            self.websocket = await websockets.connect(self.dxlink_url)
            print("✅ Websocket connected!")
            return True
        except Exception as e:
            print(f"❌ Websocket connection error: {e}")
            return False

    async def setup_dxlink(self):
        """Setup DXLink protocol and channels for Greeks and Quotes."""
        try:
            print("\n--- Setting up DXLink protocol ---")
            
            # 1. SETUP
            setup_msg = {
                "type": "SETUP",
                "channel": 0,
                "keepaliveTimeout": 60,
                "acceptKeepaliveTimeout": 60,
                "version": "1.0.0"
            }
            await self.websocket.send(json.dumps(setup_msg))
            print("📤 Sent SETUP message")
            
            # Receive SETUP response
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            setup_response = json.loads(response)
            print(f"📥 SETUP Response: {setup_response}")
            
            # Wait for AUTH_STATE
            auth_state = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            auth_state_data = json.loads(auth_state)
            print(f"📥 AUTH_STATE: {auth_state_data}")
            
            # 2. AUTHORIZE
            auth_msg = {
                "type": "AUTH",
                "channel": 0,
                "token": self.api_quote_token
            }
            await self.websocket.send(json.dumps(auth_msg))
            print("📤 Sent AUTH message")
            
            # Receive AUTH_STATE response
            auth_response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            auth_data = json.loads(auth_response)
            print(f"📥 AUTH Response: {auth_data}")
            
            if auth_data.get('state') != 'AUTHORIZED':
                print("❌ Authorization failed")
                return False
            
            print("✅ Successfully authorized!")
            
            # 3. CHANNEL_REQUEST for FEED (Greeks and Quotes on same channel)
            channel_msg = {
                "type": "CHANNEL_REQUEST",
                "channel": 1,
                "service": "FEED",
                "parameters": {"contract": "AUTO"}
            }
            await self.websocket.send(json.dumps(channel_msg))
            print("📤 Sent FEED CHANNEL_REQUEST message")
            
            # Receive CHANNEL_OPENED response
            channel_response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            channel_data = json.loads(channel_response)
            print(f"📥 FEED CHANNEL Response: {channel_data}")
            
            print("✅ DXLink connection setup complete!")
            return True
            
        except asyncio.TimeoutError:
            print("❌ Timeout during DXLink setup")
            return False
        except Exception as e:
            print(f"❌ Error setting up DXLink connection: {e}")
            return False

    async def subscribe_to_feeds(self):
        """Subscribe to Greeks for options and Quotes for underlyings."""
        try:
            option_symbols = [s for s, p in self.positions.items() if p['instrument_type'] == 'Equity Option']
            underlying_symbols = list(set(p['underlying'] for p in self.positions.values()))
            
            # Subscribe to both Greeks and Quotes on Channel 1
            subscriptions = []
            
            # Add Greeks subscriptions for options
            for symbol in option_symbols:
                subscriptions.append({"symbol": symbol, "type": "Greeks"})
            
            # Add Quote subscriptions for underlyings
            for symbol in underlying_symbols:
                subscriptions.append({"symbol": symbol, "type": "Quote"})
            
            # Send single subscription message
            subscription_msg = {
                "type": "FEED_SUBSCRIPTION",
                "channel": 1,
                "add": subscriptions
            }
            
            await self.websocket.send(json.dumps(subscription_msg))
            print(f"📈 Subscribed to Greeks for {len(option_symbols)} options and Quotes for {len(underlying_symbols)} underlyings on channel 1")

            self.initialize_all_positions()
            
            # Fallback: Initialize underlying prices if not getting quotes
            await self.initialize_fallback_prices()
            
            return True
        except Exception as e:
            print(f"❌ Subscription error: {e}")
            return False

    def initialize_all_positions(self):
        """Initialize delta records for all positions."""
        for symbol, position in self.positions.items():
            delta_payload = {k: v for k, v in position.items()}
            delta_payload.update({
                'position_delta': 0, 
                'notional_value': 0, 
                'delta_per_contract': 0,
                'price': 0,
                'net_liq': 0  # Will be calculated from mark price
            })
            if position['instrument_type'] == 'Equity':
                delta_payload['position_delta'] = position['quantity']
                delta_payload['delta_per_contract'] = 1.0
            self.deltas[symbol] = delta_payload

    async def initialize_fallback_prices(self):
        """Initialize fallback prices for underlying symbols"""
        fallback_prices = {
            'AMD': 121.78, 'AMZN': 217.45, 'ASML': 773.25, 'GOOGL': 176.07,
            'HOOD': 71.7, 'IBIT': 61.76, 'META': 698.04, 'PYPL': 73.81,
            'QQQ': 531.96, 'SHOP': 109.87, 'SOFI': 14.1, 'TSLA': 301.76
        }
        
        # Only initialize if we don't have real prices yet
        for symbol, price in fallback_prices.items():
            if symbol not in self.underlying_prices:
                self.underlying_prices[symbol] = price
                print(f"📊 Initialized {symbol}: ${price:.2f} (fallback)")
                await self.update_notional_for_underlying(symbol)

    async def handle_feed_data(self, data):
        """Handle incoming live feed data for Greeks and Quotes."""
        try:
            events = data.get('data', [])
            if len(events) >= 2:
                event_type = events[0]
                if event_type == 'Greeks':
                    await self.handle_greeks_data(events[1])
                elif event_type == 'Quote':
                    await self.handle_quote_data(events[1])
                else:
                    # Debug: print unknown event types
                    print(f"📊 Unknown event type: {event_type}")
        except Exception as e:
            # Add more detailed error info
            print(f"⚠️ Error handling feed data: {e}")
            print(f"📊 Raw data: {data}")

    async def handle_greeks_data(self, greeks_data):
        """Handle Greeks data and update position deltas and notional value."""
        i = 0
        while i + 13 < len(greeks_data):
            if greeks_data[i] == 'Greeks':
                symbol = greeks_data[i + 1]
                price = greeks_data[i + 7]
                delta = greeks_data[i + 9]
                
                if symbol in self.deltas and delta is not None and isinstance(delta, (int, float)):
                    try:
                        delta_info = self.deltas[symbol]
                        delta_info['position_delta'] = float(delta) * delta_info['quantity'] * 100
                        delta_info['delta_per_contract'] = float(delta)
                        if price is not None and isinstance(price, (int, float)):
                            delta_info['price'] = float(price)
                            # Calculate net liquidation for options when we get option price
                            if delta_info['instrument_type'] != 'Equity':
                                old_net_liq = delta_info.get('net_liq', 0)
                                delta_info['net_liq'] = float(price) * delta_info['quantity'] * 100
                                if abs(old_net_liq - delta_info['net_liq']) > 10:  # Only log significant changes
                                    print(f"💵 Net Liq Update: {delta_info.get('original_symbol', symbol)} ${old_net_liq:.0f} → ${delta_info['net_liq']:.0f}")
                        await self.update_notional_for_underlying(delta_info['underlying'])
                        print(f"🔥 {delta_info.get('original_symbol', symbol):<25} | Δ={delta:>8.4f} | Position Δ={delta_info['position_delta']:>10.2f}")
                    except (ValueError, TypeError) as e:
                        print(f"⚠️ Error processing Greeks for {symbol}: {e}")
            i += 14

    async def handle_quote_data(self, quote_data):
        """Handle Quote data and update underlying prices."""
        print(f"🔍 Quote data received: {quote_data[:20]}...")  # Debug first 20 elements
        
        # Quote data format: [flat array of Quote records]
        i = 0
        while i + 10 < len(quote_data):  # Reduced from 15 to 10 for safety
            if quote_data[i] == 'Quote':
                symbol = quote_data[i + 1]
                
                try:
                    # Extract price fields - adjust indices based on actual format
                    bid_price = quote_data[i + 7] if len(quote_data) > i + 7 else None
                    ask_price = quote_data[i + 11] if len(quote_data) > i + 11 else None
                    
                    # Use bid/ask mid-point for price
                    price = None
                    if bid_price and ask_price and isinstance(bid_price, (int, float)) and isinstance(ask_price, (int, float)):
                        price = (float(bid_price) + float(ask_price)) / 2
                        print(f"💰 {symbol}: bid=${bid_price:.2f}, ask=${ask_price:.2f}, mid=${price:.2f}")
                    
                    if symbol and price and abs(self.underlying_prices.get(symbol, 0) - price) > 0.01:
                        old_price = self.underlying_prices.get(symbol, 0)
                        self.underlying_prices[symbol] = price
                        print(f"💲 Price Update: {symbol} ${old_price:.2f} → ${price:.2f}")
                        await self.update_notional_for_underlying(symbol)
                        
                except (ValueError, TypeError, IndexError) as e:
                    print(f"⚠️ Error processing Quote for {symbol}: {e}")
                    print(f"🔍 Quote data around index {i}: {quote_data[i:i+15]}")
            i += 12  # Adjust step size based on actual quote record length

    async def update_notional_for_underlying(self, underlying_symbol):
        """Update notional values for all positions with a given underlying."""
        underlying_price = self.underlying_prices.get(underlying_symbol, 0)
        if underlying_price == 0: 
            print(f"⚠️ No price available for {underlying_symbol}")
            return # Don't calculate if price is unknown

        updated_positions = []
        for symbol, delta_info in self.deltas.items():
            if delta_info['underlying'] == underlying_symbol:
                old_notional = delta_info.get('notional_value', 0)
                delta_info['notional_value'] = delta_info['position_delta'] * underlying_price
                
                # Calculate net liquidation value for stocks only here
                # (Options net liq is calculated when we receive option prices from Greeks)
                if delta_info['instrument_type'] == 'Equity':
                    # For stocks: net liq = current price × quantity
                    delta_info['net_liq'] = underlying_price * delta_info['quantity']
                
                updated_positions.append(f"{delta_info.get('original_symbol', symbol)}: ${old_notional:.0f} → ${delta_info['notional_value']:.0f}")
        
        self.last_update = datetime.now(timezone.utc)
        total_notional = sum(d.get('notional_value', 0) for d in self.deltas.values())
        
        if updated_positions:
            print(f"💰 Notional updated for {underlying_symbol} @ ${underlying_price:.2f}:")
            for update in updated_positions[:3]:  # Show first 3 positions
                print(f"   {update}")
            if len(updated_positions) > 3:
                print(f"   ... and {len(updated_positions) - 3} more")
            print(f"📊 Portfolio Notional: ${total_notional:,.2f}")

    async def stream_data(self):
        """Main streaming loop."""
        self.running = True
        print("\n🚀 Delta tracking started! Waiting for live data...\n")
        while self.running:
            try:
                message = await asyncio.wait_for(self.websocket.recv(), timeout=65)
                data = json.loads(message)
                if data.get('type') == 'FEED_DATA':
                    await self.handle_feed_data(data)
                elif data.get('type') == 'KEEPALIVE':
                    await self.websocket.send(json.dumps({"type": "KEEPALIVE"}))
                elif data.get('type') == 'FEED_CONFIG':
                    print(f"📊 Feed configured: {data.get('eventFields', {}).keys()}")
                else:
                    # Debug: print other message types
                    print(f"📥 Other message: {data.get('type')}")
            except asyncio.TimeoutError:
                print("Connection timed out. Reconnecting...")
                break # Break to allow outer loop to reconnect
            except websockets.exceptions.ConnectionClosed:
                print("❌ Websocket connection closed.")
                self.running = False
            except Exception as e:
                print(f"❌ Streaming error: {e}")
                import traceback
                traceback.print_exc()

    async def start(self):
        """Start the delta tracking system."""
        if not self.initialize_session(): return
        if not self.fetch_positions(): return
        
        while True: # Main loop to handle reconnects
            if await self.connect_websocket():
                if await self.setup_dxlink():
                    await self.subscribe_to_feeds()
                    await self.stream_data()
            print("Attempting to reconnect in 10 seconds...")
            await asyncio.sleep(10)

    def get_dashboard_data(self, selected_accounts=None):
        """Get formatted data for dashboard, safely."""
        selected_accounts = selected_accounts or self.account_numbers
        filtered_deltas = {s: d for s, d in self.deltas.items() if d.get('account_number') in selected_accounts}
        
        grouped_positions = {}
        for symbol, delta_info in filtered_deltas.items():
            underlying = delta_info.get('underlying')
            if not underlying: continue

            if underlying not in grouped_positions:
                grouped_positions[underlying] = {'symbol': underlying, 'positions': [], 'total_delta': 0, 'total_notional': 0}
            
            group = grouped_positions[underlying]
            group['positions'].append(delta_info)
            group['total_delta'] += delta_info.get('position_delta', 0)
            group['total_notional'] += delta_info.get('notional_value', 0)
            group['total_net_liq'] = group.get('total_net_liq', 0) + delta_info.get('net_liq', 0)
            
        return {
            'portfolio_delta': sum(d.get('position_delta', 0) for d in filtered_deltas.values()),
            'total_notional': sum(d.get('notional_value', 0) for d in filtered_deltas.values()),
            'total_net_liq': sum(d.get('net_liq', 0) for d in filtered_deltas.values()),
            'position_count': len(filtered_deltas),
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'grouped_positions': sorted(grouped_positions.values(), key=lambda x: abs(x.get('total_net_liq', 0)), reverse=True),
            'all_accounts': self.account_numbers,
            'selected_accounts': selected_accounts,
        }

# Global tracker instance & Flask app
tracker = DeltaTracker()
app = Flask(__name__)
CORS(app)

@app.route('/')
def dashboard():
    """Serve the dashboard HTML"""
    return render_template('dashboard.html')

@app.route('/api/data')
def get_data():
    from flask import request
    data = tracker.get_dashboard_data(request.args.getlist('accounts'))
    return jsonify(data)

@app.route('/api/debug')
def debug_data():
    """Debug endpoint to see raw data"""
    return jsonify({
        'underlying_prices': tracker.underlying_prices,
        'total_deltas': len(tracker.deltas),
        'sample_positions': {k: v for k, v in list(tracker.deltas.items())[:3]},
        'all_notionals': {k: v.get('notional_value', 0) for k, v in tracker.deltas.items()},
        'all_net_liq': {k: v.get('net_liq', 0) for k, v in tracker.deltas.items()},
        'total_notional': sum(d.get('notional_value', 0) for d in tracker.deltas.values()),
        'total_net_liq': sum(d.get('net_liq', 0) for d in tracker.deltas.values())
    })

@app.route('/api/calculate_netliq')
def calculate_netliq():
    """Force calculate net liquidation using current prices"""
    total_calculated = 0
    for symbol, delta_info in tracker.deltas.items():
        if delta_info['instrument_type'] == 'Equity':
            # For stocks: net liq = current underlying price × quantity
            underlying_price = tracker.underlying_prices.get(delta_info['underlying'], 0)
            if underlying_price > 0:
                delta_info['net_liq'] = underlying_price * delta_info['quantity']
                total_calculated += delta_info['net_liq']
        else:
            # For options: net liq = option price × quantity × 100
            option_price = delta_info.get('price', 0)
            if option_price > 0:
                delta_info['net_liq'] = option_price * delta_info['quantity'] * 100
                total_calculated += delta_info['net_liq']
    
    return jsonify({
        'message': 'Net liquidation values calculated',
        'total_net_liq': total_calculated,
        'sample_calculations': [
            {
                'symbol': k,
                'instrument_type': v['instrument_type'],
                'price': v.get('price', 0),
                'quantity': v['quantity'],
                'net_liq': v.get('net_liq', 0)
            }
            for k, v in list(tracker.deltas.items())[:5]
        ]
    })

def run_tracker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(tracker.start())

if __name__ == '__main__':
    print("🚀 Starting TastyTracker backend...")
    tracker_thread = threading.Thread(target=run_tracker, daemon=True)
    tracker_thread.start()
    
    print("🌐 Starting dashboard server on http://localhost:5001")
    # Turn off debug mode for production/stable use
    app.run(host='0.0.0.0', port=5001, debug=False) 