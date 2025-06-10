#!/usr/bin/env python3

import asyncio
import websockets
import json
import requests
from tastytrade import Session, Account
from datetime import datetime

class WorkingLiveDeltaStreamer:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = None
        self.websocket = None
        self.api_quote_token = None
        self.dxlink_url = None
        self.positions = {}  # streamer_symbol -> position_data
        self.deltas = {}
        self.keepalive_task = None
        
    def establish_session(self):
        """Establish Tastytrade session"""
        try:
            print("🔄 Establishing Tastytrade session...")
            self.session = Session(self.username, self.password)
            print("✅ Session established successfully!")
            return True
        except Exception as e:
            print(f"❌ Failed to establish session: {e}")
            return False
    
    def get_api_quote_token(self):
        """Get API quote token for DXLink streaming"""
        try:
            print("🔄 Getting API quote token...")
            
            if hasattr(self.session, 'streamer_token') and hasattr(self.session, 'dxlink_url'):
                self.api_quote_token = self.session.streamer_token
                self.dxlink_url = self.session.dxlink_url
                print(f"✅ Got API quote token (expires: {self.session.streamer_expiration})")
                return True
            
            return False
                
        except Exception as e:
            print(f"❌ Error getting API quote token: {e}")
            return False
    
    def get_option_positions_with_streamers(self):
        """Get option positions and their streamer symbols"""
        try:
            print("🔄 Fetching option positions...")
            accounts = Account.get(self.session)
            
            main_account = None
            for acc in accounts:
                if acc.account_number == '5WX84566':
                    main_account = acc
                    break
            
            if not main_account:
                print("❌ Main account not found")
                return False
            
            positions = main_account.get_positions(self.session)
            option_positions = [p for p in positions if p.instrument_type == 'Equity Option']
            
            print(f"✅ Found {len(option_positions)} option positions")
            
            # Get streamer symbols for each position
            headers = {
                'Authorization': f'{self.session.session_token}',
                'Content-Type': 'application/json'
            }
            base_url = str(self.session.sync_client.base_url)
            
            for position in option_positions:
                symbol = position.symbol
                quantity = float(position.quantity)
                
                # Get instrument data to find streamer symbol
                try:
                    encoded_symbol = requests.utils.quote(symbol, safe='')
                    response = requests.get(
                        f"{base_url}/instruments/equity-options/{encoded_symbol}",
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        instrument = data.get('data', {})
                        streamer_symbol = instrument.get('streamer-symbol')
                        
                        if streamer_symbol:
                            self.positions[streamer_symbol] = {
                                'original_symbol': symbol,
                                'quantity': quantity,
                                'underlying': instrument.get('underlying-symbol', ''),
                                'strike': instrument.get('strike-price', ''),
                                'option_type': instrument.get('option-type', '')
                            }
                            print(f"  ✅ {symbol} -> {streamer_symbol} (qty: {quantity})")
                        else:
                            print(f"  ⚠️ No streamer symbol for {symbol}")
                    else:
                        print(f"  ❌ Failed to get instrument data for {symbol}")
                        
                except Exception as e:
                    print(f"  ❌ Error processing {symbol}: {e}")
            
            print(f"📊 Successfully mapped {len(self.positions)} positions to streamer symbols")
            return len(self.positions) > 0
            
        except Exception as e:
            print(f"❌ Error fetching positions: {e}")
            return False
    
    async def connect_websocket(self):
        """Connect to DXLink websocket"""
        try:
            print(f"🔄 Connecting to DXLink websocket...")
            self.websocket = await websockets.connect(self.dxlink_url)
            print("✅ Websocket connected!")
            return True
        except Exception as e:
            print(f"❌ Failed to connect websocket: {e}")
            return False
    
    async def setup_dxlink_connection(self):
        """Setup DXLink connection following the correct protocol"""
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
            
            # 3. CHANNEL_REQUEST for Greeks
            channel_msg = {
                "type": "CHANNEL_REQUEST",
                "channel": 1,
                "service": "FEED",
                "parameters": {"contract": "AUTO"}
            }
            await self.websocket.send(json.dumps(channel_msg))
            print("📤 Sent CHANNEL_REQUEST message")
            
            # Receive CHANNEL_OPENED response
            channel_response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            channel_data = json.loads(channel_response)
            print(f"📥 CHANNEL Response: {channel_data}")
            
            print("✅ DXLink connection setup complete!")
            return True
            
        except asyncio.TimeoutError:
            print("❌ Timeout during DXLink setup")
            return False
        except Exception as e:
            print(f"❌ Error setting up DXLink connection: {e}")
            return False
    
    async def subscribe_to_greeks(self):
        """Subscribe to Greeks data using correct protocol"""
        try:
            if not self.positions:
                print("❌ No positions to subscribe to")
                return False
            
            print(f"\n🔄 Subscribing to Greeks for {len(self.positions)} positions:")
            
            # Build subscription list using correct format
            subscriptions = []
            for streamer_symbol, position_data in self.positions.items():
                subscriptions.append({
                    "symbol": streamer_symbol,
                    "type": "Greeks"
                })
                print(f"  📈 {position_data['original_symbol']} -> {streamer_symbol}")
            
            subscription_msg = {
                "type": "FEED_SUBSCRIPTION",
                "channel": 1,
                "add": subscriptions
            }
            
            await self.websocket.send(json.dumps(subscription_msg))
            print(f"📤 Sent subscription for {len(subscriptions)} Greeks")
            
            return True
            
        except Exception as e:
            print(f"❌ Error subscribing to Greeks: {e}")
            return False
    
    async def start_keepalive(self):
        """Send keepalive messages every 30 seconds"""
        while True:
            try:
                await asyncio.sleep(30)
                if self.websocket:
                    keepalive_msg = {"type": "KEEPALIVE"}
                    await self.websocket.send(json.dumps(keepalive_msg))
                    print("💓 Sent keepalive")
                else:
                    break
            except Exception as e:
                print(f"❌ Keepalive error: {e}")
                break
    
    async def handle_feed_data(self, data):
        """Handle incoming live Greeks data from broker"""
        try:
            events = data.get('data', [])
            
            # Data format: ['Greeks', [flat array of Greeks records]]
            if len(events) >= 2 and events[0] == 'Greeks':
                greeks_data = events[1]
                
                # Parse the flat array - each Greeks record has 14 fields
                i = 0
                updated_positions = []
                
                while i + 13 < len(greeks_data):
                    if greeks_data[i] == 'Greeks':
                        symbol = greeks_data[i + 1]      # Field 1: Symbol  
                        price = greeks_data[i + 7]       # Field 7: Price
                        volatility = greeks_data[i + 8]  # Field 8: Volatility
                        delta = greeks_data[i + 9]       # Field 9: Delta ⭐
                        gamma = greeks_data[i + 10]      # Field 10: Gamma
                        theta = greeks_data[i + 11]      # Field 11: Theta
                        rho = greeks_data[i + 12]        # Field 12: Rho
                        vega = greeks_data[i + 13]       # Field 13: Vega
                        
                        # Check if this is one of our positions
                        if symbol in self.positions and delta is not None and isinstance(delta, (int, float)):
                            position = self.positions[symbol]
                            quantity = position['quantity']
                            
                            # Calculate position delta (delta * quantity * 100 shares per contract)
                            position_delta = float(delta) * quantity * 100
                            
                            # Store the Greeks data
                            self.deltas[symbol] = {
                                'original_symbol': position['original_symbol'],
                                'underlying': position['underlying'],
                                'strike': position['strike'],
                                'option_type': position['option_type'],
                                'quantity': quantity,
                                'price': price,
                                'volatility': volatility,
                                'delta_per_contract': float(delta),
                                'position_delta': position_delta,
                                'gamma': gamma,
                                'theta': theta,
                                'rho': rho,
                                'vega': vega
                            }
                            
                            updated_positions.append(symbol)
                            print(f"🔥 {position['original_symbol']:<25} | Δ={delta:>8.4f} | Position Δ={position_delta:>10.2f} | ${price:>8.2f}")
                    
                    i += 14  # Move to next Greeks record (14 fields each)
                
                # Show portfolio summary if we have deltas
                if self.deltas and updated_positions:
                    total_delta = sum(d['position_delta'] for d in self.deltas.values())
                    print(f"\n🎯 LIVE PORTFOLIO DELTA: {total_delta:,.2f}")
                    print(f"📊 Updated {len(updated_positions)} positions | Total positions: {len(self.deltas)}")
                    
                    # Show top delta contributors
                    sorted_deltas = sorted(self.deltas.items(), 
                                         key=lambda x: abs(x[1]['position_delta']), 
                                         reverse=True)
                    
                    print(f"\n📈 Top Delta Contributors:")
                    for i, (symbol, delta_info) in enumerate(sorted_deltas[:5]):
                        print(f"  {i+1}. {delta_info['original_symbol']:<20} | {delta_info['position_delta']:>10.2f} delta")
                    
                    print("-" * 80)
                
        except Exception as e:
            print(f"❌ Error parsing Greeks data: {e}")
            import traceback
            traceback.print_exc()
    
    async def start_streaming(self):
        """Main method to start the delta streaming"""
        print("🚀 Starting Live Delta Streamer")
        print("=" * 50)
        
        # Setup session and get positions
        if not self.establish_session():
            return
        
        if not self.get_api_quote_token():
            return
        
        if not self.get_option_positions_with_streamers():
            return
        
        # Connect websocket and setup streaming
        if not await self.connect_websocket():
            return
        
        if not await self.setup_dxlink_connection():
            return
        
        if not await self.subscribe_to_greeks():
            return
        
        # Start keepalive
        self.keepalive_task = asyncio.create_task(self.start_keepalive())
        
        print("\n✅ Setup complete! Streaming live deltas from your broker...")
        print("=" * 60)
        print(f"{'Symbol':<20} | {'Delta':<8} | {'Position Δ':<10}")
        print("-" * 60)
        
        # Keep listening for data
        try:
            while True:
                message = await self.websocket.recv()
                data = json.loads(message)
                
                if data.get('type') == 'FEED_DATA':
                    await self.handle_feed_data(data)
                elif data.get('type') == 'FEED_CONFIG':
                    print(f"📊 Feed configured: {data.get('eventFields', {}).keys()}")
                elif data.get('type') == 'KEEPALIVE':
                    pass  # Ignore keepalive responses
                else:
                    print(f"📥 Other: {data.get('type')}")
                
        except KeyboardInterrupt:
            print("\n🛑 Stopping delta streamer...")
        except Exception as e:
            print(f"❌ Streaming error: {e}")
        finally:
            if self.keepalive_task:
                self.keepalive_task.cancel()
            if self.websocket:
                await self.websocket.close()
                
        print("\n👋 Delta streaming stopped")

async def main():
    username = 'cppape@gmail.com'
    password = 'Scrimulous1106'
    
    streamer = WorkingLiveDeltaStreamer(username, password)
    await streamer.start_streaming()

if __name__ == "__main__":
    print("🎯 Live Delta Streamer - Get Real Broker Deltas")
    print("Press Ctrl+C to stop\n")
    
    asyncio.run(main()) 