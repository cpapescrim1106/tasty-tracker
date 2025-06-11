#!/usr/bin/env python3
"""
TastyTracker Screener Backend
Stock screening and options strategy engine for automated trading
"""

import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from flask import jsonify, request

# Tastytrade imports
from tastytrade import Session, Account

class ScreenerEngine:
    """Main screener engine for fetching and analyzing market data"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance  # Store reference to tracker instead of client
        self.base_url = "https://api.tastyworks.com"
        
        # Cache for market data (refresh every 15 minutes)
        self.market_data_cache = {}
        self.cache_timestamp = {}
        self.cache_duration = 900  # 15 minutes in seconds
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    @property
    def tasty_client(self):
        """Get the current tasty client from tracker (dynamic access)"""
        return self.tracker.tasty_client if self.tracker else None
    
    def get_watchlists(self) -> List[Dict[str, Any]]:
        """Fetch user's watchlists from Tastytrade"""
        try:
            # Check if session is established
            if not self.tasty_client or not hasattr(self.tasty_client, 'session_token') or not self.tasty_client.session_token:
                self.logger.warning("⚠️ Tastytrade session not established yet")
                return []
            
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            self.logger.info(f"🔄 Fetching watchlists from {self.base_url}/watchlists")
            response = requests.get(f"{self.base_url}/watchlists", headers=headers)
            
            self.logger.info(f"📡 Watchlists API response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.logger.info(f"📋 Raw watchlists data: {data}")
                
                watchlists = data.get('data', {}).get('items', [])
                self.logger.info(f"📝 Found {len(watchlists)} raw watchlists")
                
                # Format watchlists for frontend
                formatted_watchlists = []
                for wl in watchlists:
                    formatted_wl = {
                        'name': wl.get('name', 'Unnamed'),
                        'group_name': wl.get('group-name', ''),
                        'count': len(wl.get('watchlist-entries', [])),
                        'symbols': [entry.get('symbol', '') for entry in wl.get('watchlist-entries', [])]
                    }
                    formatted_watchlists.append(formatted_wl)
                    self.logger.info(f"📌 Formatted watchlist: {formatted_wl['name']} ({formatted_wl['count']} symbols)")
                
                self.logger.info(f"✅ Fetched {len(formatted_watchlists)} watchlists")
                return formatted_watchlists
            else:
                self.logger.error(f"❌ Failed to fetch watchlists: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching watchlists: {e}")
            return []
    
    def get_market_data_by_type(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get market data by type for multiple symbols to get volume and other data"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Build equity parameter - TastyTrade expects comma-separated symbols
            equity_symbols = ','.join(symbols)
            
            response = requests.get(
                f"{self.base_url}/market-data/by-type",
                params={'equity': equity_symbols},
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                
                result = {}
                for item in items:
                    symbol = item.get('symbol')
                    if symbol:
                        # Parse volume as float and convert to int
                        volume_str = item.get('volume')
                        volume = None
                        if volume_str:
                            try:
                                volume = int(float(volume_str))
                            except (ValueError, TypeError):
                                volume = None
                        
                        result[symbol] = {
                            'last_price': self._safe_float(item.get('last')),
                            'bid_price': self._safe_float(item.get('bid')),
                            'ask_price': self._safe_float(item.get('ask')),
                            'volume': volume,
                            'open': self._safe_float(item.get('open')),
                            'day_high': self._safe_float(item.get('day-high-price')),
                            'day_low': self._safe_float(item.get('day-low-price')),
                            'prev_close': self._safe_float(item.get('prev-close')),
                            'beta': self._safe_float(item.get('beta'))
                        }
                
                return result
            else:
                self.logger.error(f"❌ Failed to fetch market data by type: {response.status_code}")
                return {}
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching market data by type: {e}")
            return {}
    
    def _safe_float(self, value, default=None):
        """Safely convert value to float"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    

    def get_market_metrics(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch market metrics for a specific symbol"""
        try:
            # Check if session is established
            if not self.tasty_client or not hasattr(self.tasty_client, 'session_token') or not self.tasty_client.session_token:
                self.logger.error(f"❌ Tastytrade session not available for market metrics. Client: {self.tasty_client}, Token: {getattr(self.tasty_client, 'session_token', 'N/A') if self.tasty_client else 'N/A'}")
                return None
            
            # Check cache first
            cache_key = f"metrics_{symbol}"
            now = datetime.now().timestamp()
            
            if (cache_key in self.market_data_cache and 
                cache_key in self.cache_timestamp and
                now - self.cache_timestamp[cache_key] < self.cache_duration):
                return self.market_data_cache[cache_key]
            
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(f"{self.base_url}/market-metrics", 
                                  params={'symbols': symbol}, 
                                  headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                
                if items:
                    metrics = items[0]  # First (and should be only) result
                    
                    # Extract key screening metrics and convert string values to float
                    formatted_metrics = {
                        'symbol': metrics.get('symbol', symbol),
                        'implied_volatility_index': self._safe_float(metrics.get('implied-volatility-index')),
                        'implied_volatility_index_5_day_change': self._safe_float(metrics.get('implied-volatility-index-5-day-change')),
                        'implied_volatility_rank': self._safe_float(metrics.get('tw-implied-volatility-index-rank')),  # Use TastyTrade's IV rank!
                        'implied_volatility_percentile': self._safe_float(metrics.get('implied-volatility-percentile')),
                        'liquidity': self._safe_float(metrics.get('liquidity-value')),  # CORRECTED FIELD NAME!
                        'liquidity_rank': self._safe_float(metrics.get('liquidity-rank')),
                        'liquidity_rating': metrics.get('liquidity-rating'),
                        'volume': None,  # Will be filled from market-data/by-type
                        'average_volume': None,  # Not available in TastyTrade API
                        'last_price': self._safe_float(metrics.get('market-data', {}).get('last-price')) if metrics.get('market-data') else None,
                        # Add additional useful fields from the API response
                        'beta': self._safe_float(metrics.get('beta')),
                        'market_cap': self._safe_float(metrics.get('market-cap')),
                        'historical_volatility_30_day': self._safe_float(metrics.get('historical-volatility-30-day')),
                        'iv_hv_30_day_difference': self._safe_float(metrics.get('iv-hv-30-day-difference')),
                        'price_earnings_ratio': self._safe_float(metrics.get('price-earnings-ratio'))
                    }
                    
                    # Try to get real-time price from tracker's WebSocket feed first
                    if formatted_metrics['last_price'] is None and self.tracker:
                        with self.tracker.prices_lock:
                            real_time_price = self.tracker.underlying_prices.get(symbol)
                            if real_time_price and real_time_price > 0:
                                formatted_metrics['last_price'] = real_time_price
                                self.logger.debug(f"📊 Using real-time price for {symbol}: ${real_time_price:.2f}")
                    

                    

                    
                    # Log data availability for debugging
                    price_str = f"${formatted_metrics['last_price']:.2f}" if formatted_metrics['last_price'] else 'N/A'
                    iv_perc_str = f"{formatted_metrics['implied_volatility_percentile']:.1f}%" if formatted_metrics['implied_volatility_percentile'] else 'N/A'
                    iv_rank_str = f"{formatted_metrics['implied_volatility_rank']:.1f}%" if formatted_metrics['implied_volatility_rank'] is not None else 'N/A'
                    vol_str = str(formatted_metrics['volume']) if formatted_metrics['volume'] else 'N/A'
                    self.logger.debug(f"📊 {symbol} data: Price={price_str}, IV%={iv_perc_str}, IVRank={iv_rank_str}, Vol={vol_str}")
                    
                    # Convert IV percentile and IV rank from decimal to percentage if needed
                    if formatted_metrics['implied_volatility_percentile'] is not None:
                        iv_perc = formatted_metrics['implied_volatility_percentile']
                        if iv_perc <= 1.0:  # Convert from decimal to percentage
                            formatted_metrics['implied_volatility_percentile'] = iv_perc * 100
                    
                    if formatted_metrics['implied_volatility_rank'] is not None:
                        iv_rank = formatted_metrics['implied_volatility_rank']
                        if iv_rank <= 1.0:  # Convert from decimal to percentage
                            formatted_metrics['implied_volatility_rank'] = iv_rank * 100
                    
                    # Log if IV rank is available
                    if formatted_metrics['implied_volatility_rank'] is not None:
                        self.logger.debug(f"✅ IV rank available for {symbol}: {formatted_metrics['implied_volatility_rank']:.1f}%")
                    else:
                        self.logger.debug(f"⚠️ IV rank not available for {symbol}")
                    
                    # Cache the result
                    self.market_data_cache[cache_key] = formatted_metrics
                    self.cache_timestamp[cache_key] = now
                    
                    return formatted_metrics
                else:
                    self.logger.warning(f"⚠️ No market metrics found for {symbol}")
                    return None
            else:
                self.logger.error(f"❌ Failed to fetch market metrics for {symbol}: {response.status_code}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching market metrics for {symbol}: {e}")
            return None
    
    def screen_symbols(self, symbols: List[str], criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Screen a list of symbols based on provided criteria"""
        results = []
        
        # Extract screening criteria
        min_iv_rank = criteria.get('min_iv_rank', 0)
        max_iv_rank = criteria.get('max_iv_rank', 100)
        min_price = criteria.get('min_price', 0)
        max_price = criteria.get('max_price', float('inf'))
        min_volume = criteria.get('min_volume', 0)
        min_avg_volume = criteria.get('min_avg_volume', 0)
        min_liquidity_rank = criteria.get('min_liquidity_rank', 0)
        
        self.logger.info(f"🔍 Screening {len(symbols)} symbols with criteria: {criteria}")
        
        # Get market data for all symbols at once for efficiency
        market_data_batch = self.get_market_data_by_type(symbols)
        
        for symbol in symbols:
            try:
                metrics = self.get_market_metrics(symbol)
                
                if not metrics:
                    continue
                
                # Merge with batch market data if available
                if symbol in market_data_batch:
                    batch_data = market_data_batch[symbol]
                    # Update metrics with batch market data
                    if metrics['last_price'] is None:
                        metrics['last_price'] = batch_data.get('last_price')
                    if metrics['volume'] is None:
                        metrics['volume'] = batch_data.get('volume')
                    
                    # Add additional fields
                    metrics['bid_price'] = batch_data.get('bid_price')
                    metrics['ask_price'] = batch_data.get('ask_price')
                    metrics['day_high'] = batch_data.get('day_high')
                    metrics['day_low'] = batch_data.get('day_low')
                    metrics['prev_close'] = batch_data.get('prev_close')
                    metrics['beta'] = batch_data.get('beta')
                
                # Apply filters with type conversion and null handling
                iv_rank = metrics.get('implied_volatility_rank')
                last_price = metrics.get('last_price')
                volume = metrics.get('volume')
                avg_volume = metrics.get('average_volume')
                liquidity_rank = metrics.get('liquidity_rank')
                
                # Convert to float/int with null handling - preserve nulls, don't convert to 0
                try:
                    iv_rank = float(iv_rank) if iv_rank is not None else None
                    last_price = float(last_price) if last_price is not None else None
                    volume = int(volume) if volume is not None else None
                    avg_volume = int(avg_volume) if avg_volume is not None else None
                    liquidity_rank = float(liquidity_rank) if liquidity_rank is not None else None
                except (ValueError, TypeError):
                    # Skip symbol if data conversion fails
                    self.logger.warning(f"⚠️ Data conversion failed for {symbol}, skipping")
                    continue
                
                # For after-hours, be more lenient with null values
                # Only apply filters for non-null values
                passes_criteria = True
                
                # IV rank filter - only apply if data is available
                if iv_rank is not None:
                    if not (min_iv_rank <= iv_rank <= max_iv_rank):
                        passes_criteria = False
                
                # Price filter - only apply if data is available  
                if last_price is not None:
                    if not (min_price <= last_price <= max_price):
                        passes_criteria = False
                
                # Volume filters - only apply if data is available
                if volume is not None and volume < min_volume:
                    passes_criteria = False
                    
                if avg_volume is not None and avg_volume < min_avg_volume:
                    passes_criteria = False
                
                # Liquidity rank filter - only apply if data is available
                if metrics.get('liquidity_rank') is not None:
                    if liquidity_rank < min_liquidity_rank:
                        passes_criteria = False
                
                # If symbol passes all available criteria
                if passes_criteria:
                    
                    # Add to results - preserve None values for missing data
                    result = {
                        'symbol': symbol,
                        'last_price': last_price,
                        'iv_rank': iv_rank,
                        'iv_percentile': metrics.get('implied_volatility_percentile'),
                        'volume': volume,
                        'avg_volume': avg_volume,
                        'liquidity_rank': liquidity_rank,
                        'liquidity_rating': metrics.get('liquidity_rating'),
                        'passes_screen': True
                    }
                    results.append(result)
                    
            except Exception as e:
                self.logger.error(f"❌ Error screening {symbol}: {e}")
                continue
        
        # Sort by IV rank (descending) by default, handling None values
        results.sort(key=lambda x: x.get('iv_rank') or 0, reverse=True)
        
        self.logger.info(f"✅ Screening complete: {len(results)} symbols passed criteria")
        return results

def create_screener_routes(app, tracker):
    """Add screener routes to the Flask app"""
    
    screener = ScreenerEngine(tracker)
    
    # Import strategy, order management, risk management, portfolio analytics, hedge engine, and position manager
    from strategy_engine import StrategyEngine
    from order_manager import OrderManager
    from risk_manager import RiskManager, RiskLevel
    from portfolio_analytics import PortfolioAnalytics
    from hedge_engine import HedgeEngine, RebalanceTarget
    from position_manager import PositionManager
    
    # Create wrapper functions to get the client dynamically
    def get_strategy_engine():
        return StrategyEngine(tracker.tasty_client) if tracker.tasty_client else None
    
    def get_order_manager():
        return OrderManager(tracker.tasty_client) if tracker.tasty_client else None
    
    def get_risk_manager():
        return RiskManager(tracker)
    
    def get_portfolio_analytics():
        return PortfolioAnalytics(tracker)
    
    def get_hedge_engine():
        return HedgeEngine(tracker)
    
    def get_position_manager():
        return PositionManager(tracker)
    
    @app.route('/api/screener/watchlists')
    def get_watchlists():
        """Get user's watchlists"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            watchlists = screener.get_watchlists()
            
            # Add a default test watchlist if no watchlists exist
            if not watchlists:
                default_watchlist = {
                    'name': 'Test Watchlist (Default)',
                    'group_name': 'System',
                    'count': 8,
                    'symbols': ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'AMZN', 'META', 'NVDA', 'AMD']
                }
                watchlists.append(default_watchlist)
                logging.info("📝 Added default test watchlist since no user watchlists found")
            
            return jsonify({'watchlists': watchlists})
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/watchlists: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/screener/market-metrics/<symbol>')
    def get_market_metrics(symbol):
        """Get market metrics for a specific symbol"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            metrics = screener.get_market_metrics(symbol.upper())
            if metrics:
                return jsonify({'metrics': metrics})
            else:
                return jsonify({'error': 'No data found'}), 404
                
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/market-metrics/{symbol}: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/screener/screen', methods=['POST'])
    def screen_stocks():
        """Screen stocks based on criteria"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            
            # Get symbols from watchlist or custom list
            symbols = data.get('symbols', [])
            if not symbols:
                return jsonify({'error': 'No symbols provided'}), 400
            
            # Get screening criteria
            criteria = data.get('criteria', {})
            
            # Run the screen
            results = screener.screen_symbols(symbols, criteria)
            
            return jsonify({
                'results': results,
                'total_screened': len(symbols),
                'total_passed': len(results),
                'criteria': criteria,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/screen: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/screener/analyze-strategy', methods=['POST'])
    def analyze_strategy():
        """Analyze trading strategies for selected stocks"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            strategy_engine = get_strategy_engine()
            if not strategy_engine:
                return jsonify({'error': 'Strategy engine not available'}), 503
            
            data = request.get_json()
            symbols = data.get('symbols', [])
            strategy_params = data.get('strategy_params', {})
            
            if not symbols:
                return jsonify({'error': 'No symbols provided'}), 400
            
            results = []
            for symbol_data in symbols:
                symbol = symbol_data.get('symbol')
                underlying_price = symbol_data.get('last_price', 0)
                
                if symbol and underlying_price > 0:
                    analysis = strategy_engine.analyze_symbol_for_strategies(
                        symbol, underlying_price, strategy_params
                    )
                    results.append(analysis)
            
            return jsonify({
                'results': results,
                'total_analyzed': len(results),
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/analyze-strategy: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/screener/create-trades', methods=['POST'])
    def create_trades():
        """Create trades for selected strategies"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            order_manager = get_order_manager()
            if not order_manager:
                return jsonify({'error': 'Order manager not available'}), 503
            
            data = request.get_json()
            strategies = data.get('strategies', [])
            account_number = data.get('account_number')
            quantity = data.get('quantity', 1)
            price_adjustment = data.get('price_adjustment', 0.0)
            dry_run_only = data.get('dry_run_only', False)
            
            if not strategies:
                return jsonify({'error': 'No strategies provided'}), 400
            
            if not account_number:
                return jsonify({'error': 'Account number is required'}), 400
            
            # Validate account number is in target accounts
            if account_number not in tracker.target_accounts:
                return jsonify({'error': 'Invalid account number'}), 403
            
            if dry_run_only:
                # Just validate orders without submitting
                results = {
                    'total_strategies': len(strategies),
                    'orders_validated': 0,
                    'validation_failed': 0,
                    'orders': [],
                    'errors': []
                }
                
                for strategy in strategies:
                    try:
                        best_strategy = strategy.get('best_strategy')
                        if not best_strategy:
                            continue
                            
                        order = order_manager.create_put_credit_spread_order(
                            account_number, best_strategy, quantity, price_adjustment
                        )
                        
                        validation = order_manager.validate_order(order)
                        dry_run_result = order_manager.submit_order_dry_run(order)
                        
                        order_result = {
                            'symbol': strategy.get('symbol'),
                            'validation': validation,
                            'dry_run': dry_run_result,
                            'estimated_premium': best_strategy.get('net_premium', 0)
                        }
                        
                        if validation['valid'] and dry_run_result['success']:
                            results['orders_validated'] += 1
                        else:
                            results['validation_failed'] += 1
                            error_msg = f"{strategy.get('symbol')}: "
                            if not validation['valid']:
                                error_msg += f"Validation failed - {', '.join(validation['errors'])}"
                            if not dry_run_result['success']:
                                error_msg += f"Dry run failed - {dry_run_result['message']}"
                            results['errors'].append(error_msg)
                        
                        results['orders'].append(order_result)
                        
                    except Exception as e:
                        results['validation_failed'] += 1
                        results['errors'].append(f"{strategy.get('symbol', 'Unknown')}: {str(e)}")
                
                return jsonify(results)
            
            else:
                # Actually create and submit orders
                best_strategies = []
                for strategy in strategies:
                    best_strategy = strategy.get('best_strategy')
                    if best_strategy:
                        best_strategy['underlying_symbol'] = strategy.get('symbol')
                        best_strategies.append(best_strategy)
                
                results = order_manager.create_bulk_orders(
                    account_number, best_strategies, quantity, price_adjustment
                )
                
                return jsonify(results)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/create-trades: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/screener/order-status/<order_id>')
    def get_order_status(order_id):
        """Get order status"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            order_manager = get_order_manager()
            if not order_manager:
                return jsonify({'error': 'Order manager not available'}), 503
            
            account_number = request.args.get('account')
            if not account_number:
                return jsonify({'error': 'Account number required'}), 400
            
            result = order_manager.get_order_status(order_id, account_number)
            return jsonify(result)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/order-status: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/risk/position-size', methods=['POST'])
    def calculate_position_size():
        """Calculate optimal position size based on risk parameters"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            risk_manager = get_risk_manager()
            data = request.get_json()
            
            account_number = data.get('account_number')
            strategy_data = data.get('strategy_data', {})
            risk_level_str = data.get('risk_level', 'moderate')
            custom_risk_pct = data.get('custom_risk_pct')
            
            if not account_number:
                return jsonify({'error': 'Account number is required'}), 400
            
            if not strategy_data:
                return jsonify({'error': 'Strategy data is required'}), 400
            
            # Convert risk level string to enum
            try:
                risk_level = RiskLevel(risk_level_str.lower())
            except ValueError:
                risk_level = RiskLevel.MODERATE
            
            # Calculate position size
            recommendation = risk_manager.calculate_position_size(
                account_number, strategy_data, risk_level, custom_risk_pct
            )
            
            return jsonify({
                'recommended_quantity': recommendation.recommended_quantity,
                'max_loss_amount': recommendation.max_loss_amount,
                'max_loss_percentage': recommendation.max_loss_percentage,
                'buying_power_required': recommendation.buying_power_required,
                'risk_score': recommendation.risk_score,
                'warnings': recommendation.warnings,
                'concentration_impact': recommendation.concentration_impact,
                'delta_impact': recommendation.delta_impact,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/risk/position-size: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/risk/portfolio-summary/<account_number>')
    def get_portfolio_risk_summary(account_number):
        """Get comprehensive portfolio risk summary"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            risk_manager = get_risk_manager()
            summary = risk_manager.get_portfolio_risk_summary(account_number)
            
            return jsonify(summary)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/risk/portfolio-summary: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/risk/analyze-strategy', methods=['POST'])
    def analyze_strategy_with_risk():
        """Analyze strategies with integrated position sizing"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            strategy_engine = get_strategy_engine()
            risk_manager = get_risk_manager()
            
            if not strategy_engine:
                return jsonify({'error': 'Strategy engine not available'}), 503
            
            data = request.get_json()
            symbols = data.get('symbols', [])
            strategy_params = data.get('strategy_params', {})
            account_number = data.get('account_number', '5WX84566')  # Default account
            risk_level_str = data.get('risk_level', 'moderate')
            
            if not symbols:
                return jsonify({'error': 'No symbols provided'}), 400
            
            # Convert risk level
            try:
                risk_level = RiskLevel(risk_level_str.lower())
            except ValueError:
                risk_level = RiskLevel.MODERATE
            
            results = []
            for symbol_data in symbols:
                symbol = symbol_data.get('symbol')
                underlying_price = symbol_data.get('last_price', 0)
                
                if symbol and underlying_price > 0:
                    # Get strategy analysis
                    analysis = strategy_engine.analyze_symbol_for_strategies(
                        symbol, underlying_price, strategy_params
                    )
                    
                    # Add position sizing recommendation if strategy is viable
                    if analysis.get('best_strategy'):
                        try:
                            position_size = risk_manager.calculate_position_size(
                                account_number, analysis['best_strategy'], risk_level
                            )
                            analysis['position_sizing'] = {
                                'recommended_quantity': position_size.recommended_quantity,
                                'max_loss_amount': position_size.max_loss_amount,
                                'max_loss_percentage': position_size.max_loss_percentage,
                                'risk_score': position_size.risk_score,
                                'warnings': position_size.warnings
                            }
                        except Exception as e:
                            logging.warning(f"⚠️ Could not calculate position size for {symbol}: {e}")
                            analysis['position_sizing'] = {'error': str(e)}
                    
                    results.append(analysis)
            
            return jsonify({
                'results': results,
                'total_analyzed': len(results),
                'account_number': account_number,
                'risk_level': risk_level_str,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/risk/analyze-strategy: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/analytics/comprehensive-report/<account_number>')
    def get_comprehensive_analytics_report(account_number):
        """Get comprehensive risk and analytics report"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            analytics = get_portfolio_analytics()
            report = analytics.generate_risk_report(account_number)
            
            return jsonify(report)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/analytics/comprehensive-report: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/analytics/var/<account_number>')
    def get_var_analysis(account_number):
        """Get Value at Risk analysis"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            analytics = get_portfolio_analytics()
            var_result = analytics.calculate_portfolio_var(account_number)
            
            return jsonify({
                'var_1d_95': var_result.var_1d_95,
                'var_1d_99': var_result.var_1d_99,
                'var_10d_95': var_result.var_10d_95,
                'expected_shortfall_95': var_result.expected_shortfall_95,
                'portfolio_volatility': var_result.portfolio_volatility,
                'worst_case_scenario': var_result.worst_case_scenario,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/analytics/var: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/analytics/greeks/<account_number>')
    def get_greeks_exposure(account_number):
        """Get Greeks exposure analysis"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            analytics = get_portfolio_analytics()
            greeks = analytics.calculate_greeks_exposure(account_number)
            
            return jsonify({
                'total_delta': greeks.total_delta,
                'total_gamma': greeks.total_gamma,
                'total_theta': greeks.total_theta,
                'total_vega': greeks.total_vega,
                'delta_dollars': greeks.delta_dollars,
                'gamma_dollars': greeks.gamma_dollars,
                'theta_dollars': greeks.theta_dollars,
                'vega_dollars': greeks.vega_dollars,
                'delta_hedge_required': greeks.delta_hedge_required,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/analytics/greeks: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/analytics/performance/<account_number>')
    def get_performance_metrics(account_number):
        """Get performance analytics"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            analytics = get_portfolio_analytics()
            performance = analytics.calculate_performance_metrics(account_number)
            
            return jsonify({
                'total_pnl': performance.total_pnl,
                'daily_pnl': performance.daily_pnl,
                'weekly_pnl': performance.weekly_pnl,
                'monthly_pnl': performance.monthly_pnl,
                'ytd_pnl': performance.ytd_pnl,
                'win_rate': performance.win_rate,
                'profit_factor': performance.profit_factor,
                'sharpe_ratio': performance.sharpe_ratio,
                'max_drawdown': performance.max_drawdown,
                'avg_win': performance.avg_win,
                'avg_loss': performance.avg_loss,
                'largest_win': performance.largest_win,
                'largest_loss': performance.largest_loss,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/analytics/performance: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/analytics/scenarios/<account_number>')
    def get_scenario_analysis(account_number):
        """Get scenario analysis (P&L under different market conditions)"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            analytics = get_portfolio_analytics()
            scenarios = analytics.get_risk_scenarios(account_number)
            
            return jsonify({
                'scenarios': scenarios,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/analytics/scenarios: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/hedge/portfolio-delta/<account_number>')
    def get_portfolio_delta(account_number):
        """Get portfolio delta metrics for hedging analysis"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            hedge_engine = get_hedge_engine()
            delta_metrics = hedge_engine.calculate_portfolio_delta(account_number)
            
            return jsonify(delta_metrics)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/hedge/portfolio-delta: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/hedge/analyze', methods=['POST'])
    def analyze_hedge_requirement():
        """Analyze hedge requirement for portfolio"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            account_number = data.get('account_number')
            target_delta = data.get('target_delta', 0.0)
            delta_tolerance = data.get('delta_tolerance', 50.0)
            max_hedge_cost_pct = data.get('max_hedge_cost_pct', 1.0)
            hedge_symbols = data.get('hedge_symbols', None)
            
            if not account_number:
                return jsonify({'error': 'Account number is required'}), 400
            
            # Create rebalance target
            target = RebalanceTarget(
                target_delta=target_delta,
                delta_tolerance=delta_tolerance,
                max_hedge_cost_pct=max_hedge_cost_pct,
                hedge_symbols=hedge_symbols
            )
            
            hedge_engine = get_hedge_engine()
            recommendation = hedge_engine.analyze_hedge_requirement(account_number, target)
            
            return jsonify({
                'account_number': recommendation.account_number,
                'current_delta': recommendation.current_delta,
                'target_delta': recommendation.target_delta,
                'delta_imbalance': recommendation.delta_imbalance,
                'hedge_required': recommendation.hedge_required,
                'recommended_action': recommendation.recommended_action,
                'hedge_symbol': recommendation.hedge_symbol,
                'hedge_quantity': recommendation.hedge_quantity,
                'hedge_cost': recommendation.hedge_cost,
                'confidence': recommendation.confidence,
                'warnings': recommendation.warnings,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/hedge/analyze: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/hedge/rebalance-summary/<account_number>')
    def get_rebalance_summary(account_number):
        """Get comprehensive portfolio rebalancing summary"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            hedge_engine = get_hedge_engine()
            summary = hedge_engine.get_portfolio_rebalance_summary(account_number)
            
            return jsonify(summary)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/hedge/rebalance-summary: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/hedge/execute', methods=['POST'])
    def execute_hedge():
        """Execute hedge recommendation (placeholder for future implementation)"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            account_number = data.get('account_number')
            hedge_symbol = data.get('hedge_symbol')
            quantity = data.get('quantity')
            action = data.get('action')  # BUY/SELL
            dry_run = data.get('dry_run', True)
            
            if not all([account_number, hedge_symbol, quantity, action]):
                return jsonify({'error': 'Missing required parameters'}), 400
            
            # For now, just return a placeholder response
            # In a full implementation, this would use the order manager
            return jsonify({
                'message': 'Hedge execution not yet implemented',
                'dry_run': dry_run,
                'account_number': account_number,
                'hedge_symbol': hedge_symbol,
                'quantity': quantity,
                'action': action,
                'status': 'PENDING_IMPLEMENTATION',
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/hedge/execute: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/positions/rules/<account_number>')
    def get_position_rules(account_number):
        """Get position management rules summary"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            position_manager = get_position_manager()
            summary = position_manager.get_position_rules_summary(account_number)
            
            return jsonify(summary)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/positions/rules: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/positions/monitor/<account_number>')
    def monitor_positions(account_number):
        """Monitor positions for trigger conditions"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            position_manager = get_position_manager()
            monitoring_result = position_manager.monitor_all_positions()
            
            # Filter results by account
            if account_number != 'all':
                filtered_events = [
                    event for event in monitoring_result.get('triggered_events', [])
                    if event.position_key.startswith(f"{account_number}:")
                ]
                filtered_alerts = [
                    alert for alert in monitoring_result.get('new_alerts', [])
                    if alert.position_key.startswith(f"{account_number}:")
                ]
                monitoring_result['triggered_events'] = filtered_events
                monitoring_result['new_alerts'] = filtered_alerts
            
            return jsonify(monitoring_result)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/positions/monitor: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/positions/add-rule', methods=['POST'])
    def add_position_rule():
        """Add a new position management rule"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            position_key = data.get('position_key')
            rule_config = {
                'rule_type': data.get('rule_type'),
                'trigger_type': data.get('trigger_type'),
                'trigger_value': data.get('trigger_value'),
                'action': data.get('action'),
                'quantity_pct': data.get('quantity_pct', 100.0),
                'notes': data.get('notes', '')
            }
            
            if not position_key:
                return jsonify({'error': 'Position key is required'}), 400
            
            if not all([rule_config['rule_type'], rule_config['trigger_type'], rule_config['trigger_value'], rule_config['action']]):
                return jsonify({'error': 'Missing required rule parameters'}), 400
            
            position_manager = get_position_manager()
            rule_id = position_manager.add_position_rule(position_key, rule_config)
            
            return jsonify({
                'rule_id': rule_id,
                'position_key': position_key,
                'status': 'rule_added',
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/positions/add-rule: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/positions/create-sample-rules', methods=['POST'])
    def create_sample_rules():
        """Create sample rules for a position"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            position_key = data.get('position_key')
            
            if not position_key:
                return jsonify({'error': 'Position key is required'}), 400
            
            position_manager = get_position_manager()
            rule_ids = position_manager.create_sample_rules(position_key)
            
            return jsonify({
                'rule_ids': rule_ids,
                'position_key': position_key,
                'rules_created': len(rule_ids),
                'status': 'sample_rules_created',
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/positions/create-sample-rules: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/positions/check-triggers/<position_key>')
    def check_position_triggers(position_key):
        """Check trigger conditions for a specific position"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            position_manager = get_position_manager()
            triggers = position_manager.check_position_triggers(position_key)
            
            # Convert trigger events to JSON-serializable format
            trigger_data = []
            for trigger in triggers:
                trigger_data.append({
                    'position_key': trigger.position_key,
                    'rule_id': trigger.rule_id,
                    'trigger_type': trigger.trigger_type,
                    'current_value': trigger.current_value,
                    'trigger_value': trigger.trigger_value,
                    'action_required': trigger.action_required,
                    'confidence': trigger.confidence,
                    'timestamp': trigger.timestamp.isoformat(),
                    'warnings': trigger.warnings
                })
            
            return jsonify({
                'position_key': position_key,
                'triggers': trigger_data,
                'triggers_found': len(trigger_data),
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/positions/check-triggers: {e}")
            return jsonify({'error': str(e)}), 500

    return screener