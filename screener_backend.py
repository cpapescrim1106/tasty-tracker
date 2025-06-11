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
    
    def __init__(self, tasty_client: Session):
        self.tasty_client = tasty_client
        self.base_url = "https://api.tastyworks.com"
        
        # Cache for market data (refresh every 15 minutes)
        self.market_data_cache = {}
        self.cache_timestamp = {}
        self.cache_duration = 900  # 15 minutes in seconds
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    def get_watchlists(self) -> List[Dict[str, Any]]:
        """Fetch user's watchlists from Tastytrade"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(f"{self.base_url}/watchlists", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                watchlists = data.get('data', {}).get('items', [])
                
                # Format watchlists for frontend
                formatted_watchlists = []
                for wl in watchlists:
                    formatted_watchlists.append({
                        'name': wl.get('name', 'Unnamed'),
                        'group_name': wl.get('group-name', ''),
                        'count': len(wl.get('watchlist-entries', [])),
                        'symbols': [entry.get('symbol', '') for entry in wl.get('watchlist-entries', [])]
                    })
                
                self.logger.info(f"✅ Fetched {len(formatted_watchlists)} watchlists")
                return formatted_watchlists
            else:
                self.logger.error(f"❌ Failed to fetch watchlists: {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching watchlists: {e}")
            return []
    
    def get_market_metrics(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch market metrics for a specific symbol"""
        try:
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
                
                # Apply filters
                iv_rank = metrics.get('implied_volatility_rank', 0) or 0
                last_price = metrics.get('last_price', 0) or 0
                volume = metrics.get('volume', 0) or 0
                avg_volume = metrics.get('average_volume', 0) or 0
                liquidity_rank = metrics.get('liquidity_rank', 0) or 0
                
                # Check all criteria
                if (min_iv_rank <= iv_rank <= max_iv_rank and
                    min_price <= last_price <= max_price and
                    volume >= min_volume and
                    avg_volume >= min_avg_volume and
                    liquidity_rank >= min_liquidity_rank):
                    
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
    
    screener = ScreenerEngine(tracker.tasty_client)
    
    @app.route('/api/screener/watchlists')
    def get_watchlists():
        """Get user's watchlists"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            watchlists = screener.get_watchlists()
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

    return screener