#!/usr/bin/env python3
"""
TastyTracker Strategy Engine
Options analysis and automated strategy implementation
"""

import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import math

# Tastytrade imports
from tastytrade import Session

@dataclass
class OptionContract:
    """Represents an option contract with all relevant data"""
    symbol: str
    underlying_symbol: str
    strike_price: float
    expiration_date: str
    option_type: str  # 'Call' or 'Put'
    days_to_expiration: int
    bid_price: float = 0.0
    ask_price: float = 0.0
    mid_price: float = 0.0
    volume: int = 0
    open_interest: int = 0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0

@dataclass
class SpreadStrategy:
    """Represents a spread trading strategy"""
    strategy_type: str
    underlying_symbol: str
    underlying_price: float
    short_leg: OptionContract
    long_leg: OptionContract
    net_premium: float
    max_profit: float
    max_loss: float
    break_even: float
    probability_of_profit: float
    days_to_expiration: int
    strategy_score: float = 0.0

class StrategyEngine:
    """Main engine for options strategy analysis and selection"""
    
    def __init__(self, tasty_client: Session):
        self.tasty_client = tasty_client
        self.base_url = "https://api.tastyworks.com"
        
        # Cache for options chains (refresh every 5 minutes during market hours)
        self.options_cache = {}
        self.cache_timestamp = {}
        self.cache_duration = 300  # 5 minutes in seconds
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Strategy configuration
        self.min_days_to_expiration = 25
        self.max_days_to_expiration = 65
        self.min_open_interest = 10
        self.min_volume = 5
        self.target_delta_range = (0.15, 0.35)  # For put credit spreads
    
    def get_options_chain(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch options chain data for a symbol"""
        try:
            # Check cache first
            cache_key = f"chain_{symbol}"
            now = datetime.now().timestamp()
            
            if (cache_key in self.options_cache and 
                cache_key in self.cache_timestamp and
                now - self.cache_timestamp[cache_key] < self.cache_duration):
                return self.options_cache[cache_key]
            
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Encode symbol for URL
            encoded_symbol = requests.utils.quote(symbol, safe='')
            response = requests.get(
                f"{self.base_url}/instruments/option-chains/{encoded_symbol}", 
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                chain_data = data.get('data', {})
                
                # Cache the result
                self.options_cache[cache_key] = chain_data
                self.cache_timestamp[cache_key] = now
                
                self.logger.info(f"✅ Fetched options chain for {symbol}")
                return chain_data
            else:
                self.logger.error(f"❌ Failed to fetch options chain for {symbol}: {response.status_code}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching options chain for {symbol}: {e}")
            return None
    
    def get_option_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, float]]:
        """Fetch bid/ask quotes for option symbols"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Get quotes for multiple symbols
            symbol_list = ','.join(symbols)
            response = requests.get(
                f"{self.base_url}/market-data/quotes", 
                params={'symbols': symbol_list},
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                quotes = {}
                
                for item in data.get('data', {}).get('items', []):
                    symbol = item.get('symbol', '')
                    if symbol:
                        quotes[symbol] = {
                            'bid': item.get('bid-price', 0.0) or 0.0,
                            'ask': item.get('ask-price', 0.0) or 0.0,
                            'mid': (item.get('bid-price', 0.0) or 0.0 + item.get('ask-price', 0.0) or 0.0) / 2,
                            'volume': item.get('volume', 0) or 0
                        }
                
                return quotes
            else:
                self.logger.error(f"❌ Failed to fetch option quotes: {response.status_code}")
                return {}
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching option quotes: {e}")
            return {}
    
    def parse_options_chain(self, symbol: str, chain_data: Dict[str, Any]) -> List[OptionContract]:
        """Parse options chain data into OptionContract objects"""
        options = []
        
        try:
            # Get the nested data structure
            items = chain_data.get('items', [])
            
            for item in items:
                # Extract option details
                option_symbol = item.get('symbol', '')
                strike_price = float(item.get('strike-price', 0))
                expiration_date = item.get('expiration-date', '')
                option_type = item.get('option-type', '').capitalize()
                
                if not all([option_symbol, strike_price, expiration_date, option_type]):
                    continue
                
                # Calculate days to expiration
                try:
                    exp_date = datetime.strptime(expiration_date, '%Y-%m-%d')
                    days_to_exp = (exp_date - datetime.now()).days
                except:
                    days_to_exp = 0
                
                # Only include options within our DTE range
                if not (self.min_days_to_expiration <= days_to_exp <= self.max_days_to_expiration):
                    continue
                
                option = OptionContract(
                    symbol=option_symbol,
                    underlying_symbol=symbol,
                    strike_price=strike_price,
                    expiration_date=expiration_date,
                    option_type=option_type,
                    days_to_expiration=days_to_exp
                )
                
                options.append(option)
        
        except Exception as e:
            self.logger.error(f"❌ Error parsing options chain for {symbol}: {e}")
        
        return options
    
    def enrich_options_with_quotes(self, options: List[OptionContract]) -> List[OptionContract]:
        """Add bid/ask/mid prices to option contracts"""
        if not options:
            return options
        
        # Get quotes for all option symbols
        symbols = [opt.symbol for opt in options]
        quotes = self.get_option_quotes(symbols)
        
        # Enrich options with quote data
        for option in options:
            if option.symbol in quotes:
                quote = quotes[option.symbol]
                option.bid_price = quote['bid']
                option.ask_price = quote['ask']
                option.mid_price = quote['mid']
                option.volume = quote['volume']
        
        return options
    
    def find_put_credit_spreads(self, symbol: str, underlying_price: float, 
                               target_premium: float = 1.0, 
                               spread_width: float = 5.0,
                               target_dte: int = 45) -> List[SpreadStrategy]:
        """Find optimal put credit spreads for a given symbol"""
        
        self.logger.info(f"🔍 Analyzing put credit spreads for {symbol} (${underlying_price:.2f})")
        
        # Get options chain
        chain_data = self.get_options_chain(symbol)
        if not chain_data:
            return []
        
        # Parse options chain
        all_options = self.parse_options_chain(symbol, chain_data)
        if not all_options:
            return []
        
        # Filter for puts only
        puts = [opt for opt in all_options if opt.option_type == 'Put']
        
        # Enrich with current market quotes
        puts = self.enrich_options_with_quotes(puts)
        
        # Group puts by expiration
        puts_by_expiration = {}
        for put in puts:
            exp_date = put.expiration_date
            if exp_date not in puts_by_expiration:
                puts_by_expiration[exp_date] = []
            puts_by_expiration[exp_date].append(put)
        
        spreads = []
        
        # Analyze each expiration
        for exp_date, exp_puts in puts_by_expiration.items():
            # Sort puts by strike price (descending for puts)
            exp_puts.sort(key=lambda x: x.strike_price, reverse=True)
            
            # Find spread opportunities
            for i, short_put in enumerate(exp_puts):
                # Short put should be out of the money but not too far
                if short_put.strike_price >= underlying_price:
                    continue
                
                # Look for long put at lower strike (spread_width away)
                target_long_strike = short_put.strike_price - spread_width
                
                # Find the closest long put
                long_put = None
                for long_candidate in exp_puts:
                    if abs(long_candidate.strike_price - target_long_strike) < 0.5:
                        long_put = long_candidate
                        break
                
                if not long_put:
                    continue
                
                # Skip if insufficient liquidity
                if (short_put.bid_price <= 0 or long_put.ask_price <= 0 or
                    short_put.volume < self.min_volume or long_put.volume < self.min_volume):
                    continue
                
                # Calculate spread metrics
                net_premium = short_put.bid_price - long_put.ask_price
                max_profit = net_premium
                max_loss = spread_width - net_premium
                break_even = short_put.strike_price - net_premium
                
                # Calculate probability of profit (simplified)
                # Distance from current price to break even as percentage
                distance_to_be = abs(underlying_price - break_even) / underlying_price
                prob_profit = min(0.9, 0.5 + distance_to_be)  # Simplified calculation
                
                # Calculate strategy score
                score = self._calculate_strategy_score(
                    net_premium, target_premium, short_put.days_to_expiration, 
                    target_dte, prob_profit, max_loss
                )
                
                spread = SpreadStrategy(
                    strategy_type="Put Credit Spread",
                    underlying_symbol=symbol,
                    underlying_price=underlying_price,
                    short_leg=short_put,
                    long_leg=long_put,
                    net_premium=net_premium,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    break_even=break_even,
                    probability_of_profit=prob_profit,
                    days_to_expiration=short_put.days_to_expiration,
                    strategy_score=score
                )
                
                spreads.append(spread)
        
        # Sort by strategy score (best first)
        spreads.sort(key=lambda x: x.strategy_score, reverse=True)
        
        self.logger.info(f"✅ Found {len(spreads)} put credit spread opportunities for {symbol}")
        return spreads[:5]  # Return top 5 spreads
    
    def _calculate_strategy_score(self, net_premium: float, target_premium: float,
                                 dte: int, target_dte: int, prob_profit: float,
                                 max_loss: float) -> float:
        """Calculate a score for ranking strategies"""
        
        # Premium score (closer to target is better)
        premium_diff = abs(net_premium - target_premium) / target_premium
        premium_score = max(0, 1 - premium_diff)
        
        # DTE score (closer to target is better)
        dte_diff = abs(dte - target_dte) / target_dte
        dte_score = max(0, 1 - dte_diff)
        
        # Probability score
        prob_score = prob_profit
        
        # Risk/reward score
        if max_loss > 0:
            reward_risk_ratio = net_premium / max_loss
            rr_score = min(1.0, reward_risk_ratio / 0.5)  # Target 0.5 ratio
        else:
            rr_score = 0
        
        # Weighted combination
        total_score = (
            premium_score * 0.3 +
            dte_score * 0.2 +
            prob_score * 0.3 +
            rr_score * 0.2
        )
        
        return total_score
    
    def analyze_symbol_for_strategies(self, symbol: str, underlying_price: float,
                                    strategy_params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a symbol and return the best strategies"""
        
        strategy_type = strategy_params.get('strategy', 'put-credit-spread')
        target_premium = strategy_params.get('target_premium', 1.0)
        target_dte = strategy_params.get('dte', 45)
        spread_width = strategy_params.get('spread_width', 5.0)
        
        results = {
            'symbol': symbol,
            'underlying_price': underlying_price,
            'strategy_type': strategy_type,
            'strategies': [],
            'best_strategy': None,
            'analysis_timestamp': datetime.now().isoformat()
        }
        
        try:
            if strategy_type == 'put-credit-spread':
                spreads = self.find_put_credit_spreads(
                    symbol, underlying_price, target_premium, spread_width, target_dte
                )
                
                # Convert to dictionaries for JSON serialization
                strategies_data = []
                for spread in spreads:
                    strategy_data = {
                        'strategy_type': spread.strategy_type,
                        'underlying_symbol': symbol,
                        'net_premium': round(spread.net_premium, 2),
                        'max_profit': round(spread.max_profit, 2),
                        'max_loss': round(spread.max_loss, 2),
                        'break_even': round(spread.break_even, 2),
                        'probability_of_profit': round(spread.probability_of_profit, 2),
                        'days_to_expiration': spread.days_to_expiration,
                        'strategy_score': round(spread.strategy_score, 3),
                        'net_delta': round((spread.short_leg.delta or 0) - (spread.long_leg.delta or 0), 4),
                        'notional_per_contract': underlying_price * 100,  # Notional exposure per contract
                        'short_leg': {
                            'symbol': spread.short_leg.symbol,
                            'strike_price': spread.short_leg.strike_price,
                            'expiration_date': spread.short_leg.expiration_date,
                            'bid_price': spread.short_leg.bid_price,
                            'ask_price': spread.short_leg.ask_price
                        },
                        'long_leg': {
                            'symbol': spread.long_leg.symbol,
                            'strike_price': spread.long_leg.strike_price,
                            'expiration_date': spread.long_leg.expiration_date,
                            'bid_price': spread.long_leg.bid_price,
                            'ask_price': spread.long_leg.ask_price
                        }
                    }
                    strategies_data.append(strategy_data)
                
                results['strategies'] = strategies_data
                
                if strategies_data:
                    results['best_strategy'] = strategies_data[0]  # Highest scored
                    
        except Exception as e:
            self.logger.error(f"❌ Error analyzing strategies for {symbol}: {e}")
            results['error'] = str(e)
        
        return results