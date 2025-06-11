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
    
    def get_basic_quote(self, symbol: str) -> Optional[Dict[str, float]]:
        """Get basic quote data for a symbol as fallback"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"{self.base_url}/market-data/quotes", 
                params={'symbols': symbol},
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                if items:
                    quote = items[0]
                    return {
                        'last_price': quote.get('last-price', 0.0) or 0.0,
                        'bid_price': quote.get('bid-price', 0.0) or 0.0,
                        'ask_price': quote.get('ask-price', 0.0) or 0.0,
                        'volume': quote.get('volume', 0) or 0
                    }
            return None
        except Exception as e:
            self.logger.error(f"❌ Error fetching quote for {symbol}: {e}")
            return None
    
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
                    
                    # Extract key screening metrics
                    formatted_metrics = {
                        'symbol': metrics.get('symbol', symbol),
                        'implied_volatility_index': metrics.get('implied-volatility-index'),
                        'implied_volatility_rank': metrics.get('implied-volatility-rank'),
                        'implied_volatility_percentile': metrics.get('implied-volatility-percentile'),
                        'liquidity': metrics.get('liquidity'),
                        'liquidity_rank': metrics.get('liquidity-rank'),
                        'liquidity_rating': metrics.get('liquidity-rating'),
                        'volume': metrics.get('volume'),
                        'average_volume': metrics.get('average-volume'),
                        'last_price': metrics.get('market-data', {}).get('last-price') if metrics.get('market-data') else None
                    }
                    
                    # If last_price is missing, try to get it from quotes API
                    if formatted_metrics['last_price'] is None:
                        quote_data = self.get_basic_quote(symbol)
                        if quote_data:
                            formatted_metrics['last_price'] = quote_data['last_price']
                            # Also update volume if it's missing
                            if formatted_metrics['volume'] is None:
                                formatted_metrics['volume'] = quote_data['volume']
                    
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
        
        for symbol in symbols:
            try:
                metrics = self.get_market_metrics(symbol)
                
                if not metrics:
                    continue
                
                # Apply filters with type conversion and null handling
                iv_rank = metrics.get('implied_volatility_rank')
                last_price = metrics.get('last_price')
                volume = metrics.get('volume')
                avg_volume = metrics.get('average_volume')
                liquidity_rank = metrics.get('liquidity_rank')
                
                # Convert to float/int with null handling
                try:
                    iv_rank = float(iv_rank) if iv_rank is not None else 0.0
                    last_price = float(last_price) if last_price is not None else 0.0
                    volume = int(volume) if volume is not None else 0
                    avg_volume = int(avg_volume) if avg_volume is not None else 0
                    liquidity_rank = float(liquidity_rank) if liquidity_rank is not None else 0.0
                except (ValueError, TypeError):
                    # Skip symbol if data conversion fails
                    self.logger.warning(f"⚠️ Data conversion failed for {symbol}, skipping")
                    continue
                
                # For after-hours, be more lenient with null values
                # Only apply filters for non-null values
                passes_criteria = True
                
                # IV rank filter - only apply if data is available
                if metrics.get('implied_volatility_rank') is not None:
                    if not (min_iv_rank <= iv_rank <= max_iv_rank):
                        passes_criteria = False
                
                # Price filter - only apply if data is available  
                if metrics.get('last_price') is not None:
                    if not (min_price <= last_price <= max_price):
                        passes_criteria = False
                
                # Volume filters - only apply if data is available
                if metrics.get('volume') is not None and volume < min_volume:
                    passes_criteria = False
                    
                if metrics.get('average_volume') is not None and avg_volume < min_avg_volume:
                    passes_criteria = False
                
                # Liquidity rank filter - only apply if data is available
                if metrics.get('liquidity_rank') is not None:
                    if liquidity_rank < min_liquidity_rank:
                        passes_criteria = False
                
                # If symbol passes all available criteria
                if passes_criteria:
                    
                    # Add to results
                    result = {
                        'symbol': symbol,
                        'last_price': last_price,
                        'iv_rank': iv_rank,
                        'iv_percentile': metrics.get('implied_volatility_percentile', 0),
                        'volume': volume,
                        'avg_volume': avg_volume,
                        'liquidity_rank': liquidity_rank,
                        'liquidity_rating': metrics.get('liquidity_rating', ''),
                        'passes_screen': True
                    }
                    results.append(result)
                    
            except Exception as e:
                self.logger.error(f"❌ Error screening {symbol}: {e}")
                continue
        
        # Sort by IV rank (descending) by default
        results.sort(key=lambda x: x.get('iv_rank', 0), reverse=True)
        
        self.logger.info(f"✅ Screening complete: {len(results)} symbols passed criteria")
        return results

def create_screener_routes(app, tracker):
    """Add screener routes to the Flask app"""
    
    screener = ScreenerEngine(tracker)
    
    # Import strategy, order management, risk management, and portfolio analytics
    from strategy_engine import StrategyEngine
    from order_manager import OrderManager
    from risk_manager import RiskManager, RiskLevel
    from portfolio_analytics import PortfolioAnalytics
    
    # Create wrapper functions to get the client dynamically
    def get_strategy_engine():
        return StrategyEngine(tracker.tasty_client) if tracker.tasty_client else None
    
    def get_order_manager():
        return OrderManager(tracker.tasty_client) if tracker.tasty_client else None
    
    def get_risk_manager():
        return RiskManager(tracker)
    
    def get_portfolio_analytics():
        return PortfolioAnalytics(tracker)
    
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

    return screener