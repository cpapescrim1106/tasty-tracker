#!/usr/bin/env python3
"""
TastyTracker Screener Backend
Stock screening and options strategy engine for automated trading
"""

import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from flask import jsonify, request, render_template

# Tastytrade imports
from tastytrade import Session, Account

# Local imports
from sector_classifier import SectorClassifier
from market_data_service import MarketDataService

class ScreenerEngine:
    """Main screener engine for fetching and analyzing market data"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance  # Store reference to tracker instead of client
        self.base_url = "https://api.tastyworks.com"
        
        # Initialize market data service for caching
        self.market_data_service = MarketDataService(tracker=tracker_instance)
        
        # Legacy cache for backward compatibility (will be phased out)
        self.market_data_cache = {}
        self.cache_timestamp = {}
        self.cache_duration = 900  # 15 minutes in seconds
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Initialize sector classifier
        self.sector_classifier = SectorClassifier()
        
        # Portfolio management settings - per account limits
        self.account_active_trading_limits = {
            '5WX84566': 30000,  # $30K for account 566
            '5WU39639': 0       # $0 for account 639 (no active trading)
        }
        
        # Manual long-term position flags - stored as {account:symbol: is_long_term}
        self.long_term_position_flags = self._load_long_term_flags()
    
    def _load_long_term_flags(self) -> Dict[str, bool]:
        """Load manual long-term position flags from JSON file"""
        try:
            import os
            flags_file = "long_term_flags.json"
            if os.path.exists(flags_file):
                with open(flags_file, 'r') as f:
                    import json
                    flags = json.load(f)
                self.logger.info(f"📊 Loaded {len(flags)} long-term position flags")
                return flags
            else:
                self.logger.info("📁 No long-term flags file found, starting fresh")
                return {}
        except Exception as e:
            self.logger.error(f"❌ Failed to load long-term flags: {e}")
            return {}
    
    def _save_long_term_flags(self) -> None:
        """Save manual long-term position flags to JSON file"""
        try:
            import json
            with open("long_term_flags.json", 'w') as f:
                json.dump(self.long_term_position_flags, f, indent=2)
            self.logger.debug(f"💾 Saved {len(self.long_term_position_flags)} long-term flags")
        except Exception as e:
            self.logger.error(f"❌ Failed to save long-term flags: {e}")
    
    def set_position_long_term_flag(self, account: str, symbol: str, is_long_term: bool) -> None:
        """Set manual long-term flag for a position"""
        position_key = f"{account}:{symbol}"
        if is_long_term:
            self.long_term_position_flags[position_key] = True
        else:
            self.long_term_position_flags.pop(position_key, None)
        self._save_long_term_flags()
        self.logger.info(f"🏷️ Set {position_key} long-term flag: {is_long_term}")
    
    def is_position_long_term(self, account: str, symbol: str) -> bool:
        """Check if position is manually flagged as long-term"""
        position_key = f"{account}:{symbol}"
        return self.long_term_position_flags.get(position_key, False)
    
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
    
    def get_sector_watchlists(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Get all watchlists starting with 'Sector' and categorize them"""
        try:
            all_watchlists = self.get_watchlists()
            sector_watchlists = [w for w in all_watchlists if w['name'].startswith('Sector')]
            
            # Define non-equity sector names
            non_equity_names = ['Commodities', 'Currencies', 'Bonds', 'Futures', 'Volatility', 'Crypto']
            
            # Categorize as equity vs non-equity
            equity_sectors = []
            non_equity_sectors = []
            
            for wl in sector_watchlists:
                # Extract sector name (remove 'Sector ' prefix)
                sector_name = wl['name'].replace('Sector ', '').strip()
                
                sector_data = {
                    'name': sector_name,
                    'symbols': wl['symbols'],
                    'count': len(wl['symbols'])
                }
                
                # Check if it's a non-equity sector
                if any(ne in sector_name for ne in non_equity_names):
                    non_equity_sectors.append(sector_data)
                else:
                    equity_sectors.append(sector_data)
            
            self.logger.info(f"📊 Found {len(equity_sectors)} equity sectors and {len(non_equity_sectors)} non-equity sectors")
            return equity_sectors, non_equity_sectors
            
        except Exception as e:
            self.logger.error(f"❌ Error getting sector watchlists: {e}")
            return [], []
    
    def calculate_sector_rankings(self) -> Dict[str, List[Dict[str, Any]]]:
        """Calculate IV_EDGE scores for each sector"""
        try:
            equity_sectors, non_equity_sectors = self.get_sector_watchlists()
            
            if not equity_sectors and not non_equity_sectors:
                self.logger.warning("⚠️ No sector watchlists found")
                return {'equity_sectors': [], 'non_equity_sectors': []}
            
            # Calculate scores for equity sectors
            equity_rankings = []
            for sector in equity_sectors:
                score = self._calculate_sector_score(sector['symbols'], sector['name'])
                if score is not None:
                    equity_rankings.append({
                        'name': sector['name'],
                        'score': score,
                        'symbol_count': sector['count']
                    })
            
            # Calculate scores for non-equity sectors
            non_equity_rankings = []
            for sector in non_equity_sectors:
                score = self._calculate_sector_score(sector['symbols'], sector['name'])
                if score is not None:
                    non_equity_rankings.append({
                        'name': sector['name'],
                        'score': score,
                        'symbol_count': sector['count']
                    })
            
            # Sort by score descending
            equity_rankings.sort(key=lambda x: x['score'], reverse=True)
            non_equity_rankings.sort(key=lambda x: x['score'], reverse=True)
            
            # Return top 6 equity and top 4 non-equity
            result = {
                'equity_sectors': equity_rankings[:6],
                'non_equity_sectors': non_equity_rankings[:4],
                'timestamp': datetime.now().isoformat()
            }
            
            self.logger.info(f"✅ Calculated sector rankings: {len(result['equity_sectors'])} equity, {len(result['non_equity_sectors'])} non-equity")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating sector rankings: {e}")
            return {'equity_sectors': [], 'non_equity_sectors': []}
    
    def _calculate_sector_score(self, symbols: List[str], sector_name: str) -> Optional[float]:
        """
        Calculate IV_EDGE score for a sector based on its constituent symbols
        Formula: 30% IV Rank + 25% σ30 + 25% IV 5-day change + 20% SPY decorrelation
        """
        try:
            if not symbols:
                self.logger.warning(f"⚠️ No symbols for sector {sector_name}")
                return None
            
            # Collect metrics for all symbols in sector
            sector_metrics = []
            
            for symbol in symbols[:10]:  # Limit to top 10 symbols per sector for performance
                metrics = self.get_market_metrics(symbol)
                if metrics and metrics.get('implied_volatility_rank') is not None:
                    sector_metrics.append(metrics)
            
            if not sector_metrics:
                self.logger.warning(f"⚠️ No valid metrics for sector {sector_name}")
                return None
            
            # Calculate average metrics for the sector
            avg_iv_rank = sum(m.get('implied_volatility_rank', 0) for m in sector_metrics) / len(sector_metrics)
            avg_hv_30 = sum(m.get('historical_volatility_30_day', 0) for m in sector_metrics) / len(sector_metrics)
            avg_iv_5d_change = sum(m.get('implied_volatility_index_5_day_change', 0) for m in sector_metrics) / len(sector_metrics)
            
            # For SPY decorrelation, we'll use beta as a proxy (lower beta = higher decorrelation)
            avg_beta = sum(abs(m.get('beta', 1.0)) for m in sector_metrics) / len(sector_metrics)
            spy_decorrelation = max(0, 100 - (avg_beta * 50))  # Convert beta to decorrelation score
            
            # Calculate IV_EDGE score
            iv_edge_score = (
                0.30 * avg_iv_rank +           # 30% IV Rank
                0.25 * avg_hv_30 +             # 25% σ30
                0.25 * (avg_iv_5d_change * 10) +  # 25% IV 5-day change (amplified)
                0.20 * spy_decorrelation        # 20% SPY decorrelation
            )
            
            self.logger.info(f"📊 {sector_name} IV_EDGE Score: {iv_edge_score:.1f} "
                           f"(IVR={avg_iv_rank:.1f}, σ30={avg_hv_30:.1f}, "
                           f"IV5d={avg_iv_5d_change:.2f}, Decorr={spy_decorrelation:.1f})")
            
            return round(iv_edge_score, 1)
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating score for sector {sector_name}: {e}")
            return None
    
    def get_main_list_watchlist(self) -> Optional[Dict[str, Any]]:
        """Get the 'Main List' watchlist from user's watchlists"""
        try:
            watchlists = self.get_watchlists()
            for wl in watchlists:
                if wl['name'] == 'Main List':
                    self.logger.info(f"✅ Found Main List watchlist with {wl['count']} symbols")
                    return wl
            
            # If Main List not found, try to find the largest watchlist
            if watchlists:
                largest_watchlist = max(watchlists, key=lambda x: x['count'])
                self.logger.warning(f"⚠️ Main List not found, using largest watchlist: {largest_watchlist['name']} ({largest_watchlist['count']} symbols)")
                return largest_watchlist
            
            self.logger.error("❌ No watchlists found")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error getting Main List watchlist: {e}")
            return None
    
    def rank_main_list_underlyings(self, max_symbols: int = None, timeout_seconds: int = 120) -> List[Dict[str, Any]]:
        """Rank individual underlyings from Main List watchlist with concentration validation (OPTIMIZED)"""
        import time
        start_time = time.time()
        
        try:
            # Get Main List watchlist
            main_list = self.get_main_list_watchlist()
            if not main_list:
                self.logger.error("❌ No Main List watchlist available")
                return []
            
            
            # Process all symbols unless explicitly limited
            self.logger.info(f"🔍 Debug: max_symbols={max_symbols}, type={type(max_symbols)}, total_symbols={len(main_list['symbols'])}")
            if max_symbols is not None:
                symbols = main_list['symbols'][:max_symbols]
            else:
                symbols = main_list['symbols']
            self.logger.info(f"🚀 Ranking {len(symbols)} symbols from Main List (multi-instrument support)...")
            
            # Get current portfolio for concentration checking
            current_portfolio = self._get_current_portfolio_breakdown()
            
            # PERFORMANCE OPTIMIZATION: Batch fetch all market data with smart caching
            self.logger.info(f"📡 Batch fetching market data for {len(symbols)} symbols...")
            batch_start = time.time()
            market_data_batch = self.market_data_service.get_market_data(
                symbols, data_type='screening', max_age_minutes=15
            )
            batch_time = time.time() - batch_start
            self.logger.info(f"✅ Batch fetch completed in {batch_time:.2f}s ({len(market_data_batch)} symbols)")
            
            # Quick validation: If no valid prices found, try force refresh once
            valid_prices = sum(1 for data in market_data_batch.values() 
                             if data.last_price is not None and data.last_price > 0)
            
            # Debug: Show sample of what we're getting
            sample_data = list(market_data_batch.items())[:5]
            for symbol, data in sample_data:
                self.logger.info(f"📊 Sample data - {symbol}: price={data.last_price}, source={data.data_source}")
            
            if valid_prices == 0:
                self.logger.warning(f"⚠️ No valid prices found in batch, attempting force refresh...")
                refresh_start = time.time()
                market_data_batch = self.market_data_service.get_market_data(
                    symbols, data_type='screening', max_age_minutes=15, force_refresh=True
                )
                refresh_time = time.time() - refresh_start
                valid_prices_after = sum(1 for data in market_data_batch.values() 
                                       if data.last_price is not None and data.last_price > 0)
                
                # Debug: Show sample after refresh
                sample_data_after = list(market_data_batch.items())[:5]
                for symbol, data in sample_data_after:
                    self.logger.info(f"📊 After refresh - {symbol}: price={data.last_price}, source={data.data_source}")
                
                self.logger.info(f"🔄 Force refresh completed in {refresh_time:.2f}s, found {valid_prices_after} valid prices")
            else:
                self.logger.info(f"✅ Found {valid_prices} valid prices in initial batch")
            
            ranked_symbols = []
            processed_count = 0
            skipped_count = 0
            
            for i, symbol in enumerate(symbols):
                # Check timeout
                if time.time() - start_time > timeout_seconds:
                    self.logger.warning(f"⚠️ Ranking timeout reached after {timeout_seconds}s, processed {processed_count}/{len(symbols)} symbols")
                    break
                    
                try:
                    # Progress logging every 25 symbols
                    if i > 0 and i % 25 == 0:
                        elapsed = time.time() - start_time
                        self.logger.info(f"🔄 Progress: {i}/{len(symbols)} symbols processed in {elapsed:.1f}s")
                    
                    # OPTIMIZED: Get market metrics from batch data
                    market_data_point = market_data_batch.get(symbol)
                    if market_data_point and market_data_point.data_source != 'no_data':
                        # Convert MarketDataPoint to legacy format for compatibility
                        metrics = {
                            'symbol': symbol,
                            'last_price': market_data_point.last_price,
                            'implied_volatility_rank': market_data_point.iv_rank,
                            'implied_volatility_index': market_data_point.iv_index,
                            'implied_volatility_index_5_day_change': market_data_point.iv_5d_change,
                            'volume': market_data_point.volume,
                            'liquidity_rank': market_data_point.liquidity_rank,
                            'data_source': market_data_point.data_source
                        }
                    else:
                        # No market data available
                        metrics = {
                            'symbol': symbol,
                            'last_price': None,
                            'implied_volatility_rank': None,
                            'implied_volatility_index': None,
                            'implied_volatility_index_5_day_change': None,
                            'volume': None,
                            'liquidity_rank': None,
                            'data_source': 'no_data'
                        }
                        skipped_count += 1
                    
                    # Get sector information (auto-expanding cache)
                    sector_info = self.sector_classifier.get_symbol_sector(symbol)
                    
                    # Calculate screening score with components
                    score_data = self._calculate_screening_score(metrics)
                    
                    # Check concentration limits
                    concentration_check = self._validate_concentration(symbol, sector_info, current_portfolio)
                    
                    symbol_data = {
                        'symbol': symbol,
                        'screening_score': score_data['score'],
                        'sector': sector_info.get('sector', 'Unknown'),
                        'industry': sector_info.get('industry', 'Unknown'),
                        'last_price': metrics.get('last_price'),
                        'iv_rank': score_data['iv_rank'],
                        'iv_index': score_data['iv_index'],
                        'iv_5d_change': score_data['iv_5d_change'],
                        'trend_score': score_data['trend_score'],
                        'volume': metrics.get('volume'),
                        'liquidity_rank': metrics.get('liquidity_rank'),
                        'can_add_position': concentration_check['can_add'],
                        'concentration_warning': concentration_check.get('warning'),
                        'current_sector_weight': concentration_check.get('current_sector_weight', 0),
                        'current_equity_weight': concentration_check.get('current_equity_weight', 0)
                    }
                    
                    # Include symbols in ranking if they have ANY meaningful market data
                    has_price = metrics.get('last_price') is not None and metrics.get('last_price') > 0
                    has_analytics = (score_data['iv_rank'] is not None or 
                                   metrics.get('liquidity_rank') is not None or
                                   metrics.get('volume') is not None)
                    is_futures_with_data = (symbol.startswith('/') and 
                                          (metrics.get('liquidity_rank') is not None or 
                                           score_data['iv_rank'] is not None))
                    
                    # Include if: has price OR has analytics data OR is futures with data
                    if has_price or has_analytics or is_futures_with_data:
                        ranked_symbols.append(symbol_data)
                        processed_count += 1
                        if processed_count <= 5:  # Log first few successful ones
                            self.logger.info(f"✅ Including {symbol} in ranking: price={metrics.get('last_price')}, has_analytics={has_analytics}, futures_data={is_futures_with_data}, score={score_data['score']}")
                    else:
                        if skipped_count <= 5:  # Log first few skipped ones  
                            self.logger.info(f"⚠️ Skipping {symbol} from ranking: no valid data (price={metrics.get('last_price')}, has_analytics={has_analytics}, futures_data={is_futures_with_data})")
                        skipped_count += 1
                    
                except Exception as e:
                    self.logger.error(f"❌ Error processing {symbol}: {e}")
                    skipped_count += 1
                    continue
            
            # Sort by screening score descending
            ranked_symbols.sort(key=lambda x: x['screening_score'], reverse=True)
            
            elapsed = time.time() - start_time
            self.logger.info(f"✅ Ranked {processed_count} underlyings from Main List in {elapsed:.1f}s (skipped: {skipped_count})")
            return ranked_symbols
            
        except Exception as e:
            self.logger.error(f"❌ Error ranking Main List underlyings: {e}")
            return []
    
    def _get_current_portfolio_breakdown(self) -> Dict[str, Any]:
        """Get current portfolio breakdown for concentration checking (excluding long-term positions)"""
        try:
            if not self.tracker:
                return {'sectors': {}, 'asset_types': {'equities': 0}}
            
            # Get current dashboard data
            dashboard_data = self.tracker.get_dashboard_data()
            positions = dashboard_data.get('positions', [])
            
            total_value = 0
            active_value = 0
            long_term_value = 0
            sector_values = {}
            equity_value = 0
            
            # Track per-account active values
            account_active_values = {acc: 0 for acc in self.account_active_trading_limits.keys()}
            
            # Manual long-term flagging system - no automatic date comparison needed
            
            for pos in positions:
                if pos.get('is_summary', False):
                    continue
                
                position_value = abs(pos.get('net_liq', 0))
                total_value += position_value
                
                # Check if position is manually flagged as long-term
                account_num = pos.get('account_number', '')
                symbol_occ = pos.get('symbol_occ', '')
                is_long_term = self.is_position_long_term(account_num, symbol_occ)
                
                if is_long_term:
                    long_term_value += position_value
                    self.logger.debug(f"🏷️ Long-term flagged position: {symbol_occ} (${position_value:,.0f})")
                
                # Only count active positions for concentration limits
                if not is_long_term:
                    active_value += position_value
                    
                    # Track per-account active values
                    account_num = pos.get('account_number', '')
                    if account_num in account_active_values:
                        account_active_values[account_num] += position_value
                    
                    # Check if equity
                    if pos.get('instrument_type') == 'Equity':
                        equity_value += position_value
                    
                    # Get sector for underlying
                    underlying_symbol = pos.get('underlying_symbol', '')
                    if underlying_symbol:
                        sector_info = self.sector_classifier.get_symbol_sector(underlying_symbol)
                        sector = sector_info.get('sector', 'Unknown')
                        sector_values[sector] = sector_values.get(sector, 0) + position_value
            
            # Convert to percentages (based on active positions only)
            if active_value > 0:
                sector_percentages = {sector: (value / active_value) * 100 
                                    for sector, value in sector_values.items()}
                equity_percentage = (equity_value / active_value) * 100
            else:
                sector_percentages = {}
                equity_percentage = 0
            
            # Calculate limits for primary account (566) 
            primary_account = '5WX84566'
            primary_active_value = account_active_values.get(primary_account, 0)
            primary_limit = self.account_active_trading_limits.get(primary_account, 0)
            primary_remaining = max(0, primary_limit - primary_active_value)
            
            return {
                'sectors': sector_percentages,
                'asset_types': {'equities': equity_percentage},
                'total_value': total_value,
                'active_value': active_value,
                'long_term_value': long_term_value,
                'account_active_values': account_active_values,
                'account_active_limits': self.account_active_trading_limits,
                'primary_account': primary_account,
                'active_allocation_used': primary_active_value,
                'active_allocation_limit': primary_limit,
                'active_allocation_remaining': primary_remaining
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error getting portfolio breakdown: {e}")
            return {
                'sectors': {}, 
                'asset_types': {'equities': 0},
                'total_value': 0,
                'active_value': 0,
                'long_term_value': 0,
                'account_active_values': {},
                'account_active_limits': self.account_active_trading_limits,
                'primary_account': '5WX84566',
                'active_allocation_used': 0,
                'active_allocation_limit': 0,
                'active_allocation_remaining': 0
            }
    
    def _validate_concentration(self, symbol: str, sector_info: Dict[str, Any], 
                              current_portfolio: Dict[str, Any]) -> Dict[str, Any]:
        """Validate if adding this symbol would exceed concentration limits"""
        try:
            sector = sector_info.get('sector', 'Unknown')
            current_sector_weight = current_portfolio['sectors'].get(sector, 0)
            current_equity_weight = current_portfolio['asset_types'].get('equities', 0)
            active_allocation_remaining = current_portfolio.get('active_allocation_remaining', float('inf'))
            
            # Concentration limits
            MAX_SECTOR_PCT = 10.0
            MAX_EQUITY_PCT = 60.0
            
            # Check limits
            can_add_sector = current_sector_weight < MAX_SECTOR_PCT
            can_add_equity = current_equity_weight < MAX_EQUITY_PCT
            can_add_allocation = active_allocation_remaining > 1000  # Must have at least $1000 remaining
            can_add = can_add_sector and can_add_equity and can_add_allocation
            
            # Generate warning if needed
            warning = None
            if not can_add_allocation:
                warning = f"Active allocation limit reached (${active_allocation_remaining:.0f} remaining)"
            elif not can_add_sector:
                warning = f"Sector {sector} at {current_sector_weight:.1f}% (limit: {MAX_SECTOR_PCT}%)"
            elif not can_add_equity:
                warning = f"Equities at {current_equity_weight:.1f}% (limit: {MAX_EQUITY_PCT}%)"
            
            return {
                'can_add': can_add,
                'warning': warning,
                'current_sector_weight': current_sector_weight,
                'current_equity_weight': current_equity_weight,
                'active_allocation_remaining': active_allocation_remaining,
                'sector_limit': MAX_SECTOR_PCT,
                'equity_limit': MAX_EQUITY_PCT
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error validating concentration for {symbol}: {e}")
            return {'can_add': True, 'warning': f"Validation error: {e}"}
    
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
    
    def _calculate_trend_score(self, metrics: Dict[str, Any]) -> float:
        """Calculate TrendScore using available TastyTrade API data"""
        try:
            current_price = self._safe_float(metrics.get('last_price'), 0)
            day_high = self._safe_float(metrics.get('day_high'), current_price)
            day_low = self._safe_float(metrics.get('day_low'), current_price)
            iv_index = self._safe_float(metrics.get('implied_volatility_index'), 0)
            historical_vol_30d = self._safe_float(metrics.get('historical_volatility_30_day'), 0)
            iv_5d_change = self._safe_float(metrics.get('implied_volatility_index_5_day_change'), 0)
            
            # Component 1: Intraday momentum (0-1 scale)
            if day_high > day_low:
                intraday_momentum = (current_price - day_low) / (day_high - day_low)
            else:
                intraday_momentum = 0.5  # Neutral if no range
            
            # Component 2: IV vs HV premium (-1 to +1 scale)
            if historical_vol_30d > 0:
                iv_premium = (iv_index - historical_vol_30d / 100) / (historical_vol_30d / 100)
                iv_premium = max(-1, min(1, iv_premium))  # Clamp to [-1, 1]
            else:
                iv_premium = 0
            
            # Component 3: IV direction (-1 to +1)
            iv_direction = 1 if iv_5d_change > 0 else (-1 if iv_5d_change < 0 else 0)
            
            # Weighted combination to get -1 to +1 scale
            trend_score = (0.5 * (intraday_momentum * 2 - 1) +  # Convert 0-1 to -1 to +1
                          0.3 * iv_premium +
                          0.2 * iv_direction)
            
            return max(-1, min(1, trend_score))  # Ensure bounds
        except Exception as e:
            self.logger.warning(f"⚠️ Error calculating trend score: {e}")
            return 0.0
    
    def _calculate_screening_score(self, metrics: Dict[str, Any]) -> Dict[str, float]:
        """Calculate enhanced screening score with increased 5-day IV change weight
        Returns dict with score and all components"""
        try:
            iv_rank = self._safe_float(metrics.get('implied_volatility_rank'), 0)
            iv_index = self._safe_float(metrics.get('implied_volatility_index'), 0) * 100  # Convert to percentage
            iv_5d_change = self._safe_float(metrics.get('implied_volatility_index_5_day_change'), 0) * 100  # Convert to percentage
            trend_score = self._calculate_trend_score(metrics)
            
            # Enhanced scoring: 0.3 × IVR + 0.15 × IV Index + 0.35 × (5-Day IV Change × 10) + 0.2 × TrendScore
            score = (0.3 * iv_rank +
                    0.15 * iv_index +
                    0.35 * (iv_5d_change * 10) +  # Amplify 5-day change impact
                    0.2 * (trend_score + 1) * 50)  # Convert trend_score from [-1,1] to [0,100]
            
            return {
                'score': max(0, min(100, score)),  # Clamp to [0, 100]
                'iv_rank': iv_rank,
                'iv_index': iv_index,
                'iv_5d_change': iv_5d_change,
                'trend_score': trend_score * 100  # Convert to percentage scale for display
            }
        except Exception as e:
            self.logger.warning(f"⚠️ Error calculating screening score: {e}")
            return {
                'score': 0.0,
                'iv_rank': 0.0,
                'iv_index': 0.0,
                'iv_5d_change': 0.0,
                'trend_score': 0.0
            }
    

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
                                  headers=headers,
                                  timeout=5)
            
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
                        'implied_volatility_rank': self._safe_float(metrics.get('implied-volatility-index-rank')),  # Use correct IV rank field!
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
                    
                    # Try multiple price sources in order of preference
                    price_sources_tried = []
                    
                    # Source 1: TastyTrade market-data from API response
                    if formatted_metrics['last_price'] is not None:
                        price_sources_tried.append('tastytrade_api')
                        self.logger.debug(f"📊 Using TastyTrade API price for {symbol}: ${formatted_metrics['last_price']:.2f}")
                    
                    # Source 2: Real-time WebSocket feed
                    elif self.tracker:
                        with self.tracker.prices_lock:
                            real_time_price = self.tracker.underlying_prices.get(symbol)
                            if real_time_price and real_time_price > 0:
                                formatted_metrics['last_price'] = real_time_price
                                price_sources_tried.append('websocket_feed')
                                self.logger.debug(f"📊 Using WebSocket price for {symbol}: ${real_time_price:.2f}")
                    
                    # Source 3: Fallback to market-data/by-type API call
                    if formatted_metrics['last_price'] is None:
                        try:
                            market_data = self.get_market_data_by_type([symbol])
                            if symbol in market_data and market_data[symbol].get('last_price'):
                                formatted_metrics['last_price'] = market_data[symbol]['last_price']
                                price_sources_tried.append('market_data_by_type')
                                self.logger.debug(f"📊 Using market-data/by-type price for {symbol}: ${formatted_metrics['last_price']:.2f}")
                        except Exception as e:
                            self.logger.warning(f"⚠️ Fallback price fetch failed for {symbol}: {e}")
                            price_sources_tried.append('market_data_by_type_failed')
                    
                    # Log price fetching result
                    if formatted_metrics['last_price'] is not None:
                        self.logger.debug(f"✅ Price found for {symbol}: ${formatted_metrics['last_price']:.2f} (sources tried: {', '.join(price_sources_tried)})")
                    else:
                        self.logger.warning(f"⚠️ No price data available for {symbol} (sources tried: {', '.join(price_sources_tried)})")
                        # Store the error details in the metrics for better debugging
                        formatted_metrics['price_error'] = f"No price from: {', '.join(price_sources_tried)}"
                    
                    # Log comprehensive data availability for debugging
                    price_str = f"${formatted_metrics['last_price']:.2f}" if formatted_metrics['last_price'] else 'N/A'
                    iv_perc_str = f"{formatted_metrics['implied_volatility_percentile']:.1f}%" if formatted_metrics['implied_volatility_percentile'] else 'N/A'
                    iv_rank_str = f"{formatted_metrics['implied_volatility_rank']:.1f}%" if formatted_metrics['implied_volatility_rank'] is not None else 'N/A'
                    vol_str = str(formatted_metrics['volume']) if formatted_metrics['volume'] else 'N/A'
                    self.logger.debug(f"📊 {symbol} metrics: Price={price_str}, IV%={iv_perc_str}, IVRank={iv_rank_str}, Vol={vol_str}")
                    
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
                    self.logger.warning(f"⚠️ No market metrics found for {symbol} in API response")
                    # Try to get basic price data even if metrics aren't available
                    try:
                        market_data = self.get_market_data_by_type([symbol])
                        if symbol in market_data and market_data[symbol].get('last_price'):
                            basic_metrics = {
                                'symbol': symbol,
                                'last_price': market_data[symbol]['last_price'],
                                'volume': market_data[symbol].get('volume'),
                                'implied_volatility_rank': None,
                                'implied_volatility_index': None,
                                'implied_volatility_index_5_day_change': None,
                                'price_error': 'Limited data - no market metrics available',
                                'data_source': 'basic_market_data_only'
                            }
                            self.logger.info(f"📊 Got basic price data for {symbol}: ${basic_metrics['last_price']:.2f} (no full metrics)")
                            return basic_metrics
                    except Exception as e:
                        self.logger.warning(f"⚠️ Could not get even basic price data for {symbol}: {e}")
                    return None
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json().get('error', {}).get('message', 'Unknown API error')
                    error_msg += f": {error_detail}"
                except:
                    error_msg += f": {response.text[:100]}..." if response.text else ""
                
                self.logger.error(f"❌ Failed to fetch market metrics for {symbol}: {error_msg}")
                
                # For HTTP errors, still try to get basic price data as fallback
                if response.status_code in [404, 400]:  # Common errors for unsupported symbols
                    try:
                        market_data = self.get_market_data_by_type([symbol])
                        if symbol in market_data and market_data[symbol].get('last_price'):
                            basic_metrics = {
                                'symbol': symbol,
                                'last_price': market_data[symbol]['last_price'],
                                'volume': market_data[symbol].get('volume'),
                                'implied_volatility_rank': None,
                                'implied_volatility_index': None,
                                'implied_volatility_index_5_day_change': None,
                                'price_error': f'Metrics API error: {error_msg}',
                                'data_source': 'fallback_after_api_error'
                            }
                            self.logger.info(f"📊 Fallback price data for {symbol}: ${basic_metrics['last_price']:.2f} (after API error)")
                            return basic_metrics
                    except Exception as e:
                        self.logger.warning(f"⚠️ Fallback price fetch also failed for {symbol}: {e}")
                
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
        min_iv_index = criteria.get('min_iv_index', 0)  # New: minimum IV Index
        expanding_vol_only = criteria.get('expanding_vol_only', False)  # New: 5-day IV change > 0
        
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
                iv_index = metrics.get('implied_volatility_index')
                iv_5d_change = metrics.get('implied_volatility_index_5_day_change')
                
                # Convert to float/int with null handling - preserve nulls, don't convert to 0
                try:
                    iv_rank = float(iv_rank) if iv_rank is not None else None
                    last_price = float(last_price) if last_price is not None else None
                    volume = int(volume) if volume is not None else None
                    avg_volume = int(avg_volume) if avg_volume is not None else None
                    liquidity_rank = float(liquidity_rank) if liquidity_rank is not None else None
                    iv_index = float(iv_index) if iv_index is not None else None
                    iv_5d_change = float(iv_5d_change) if iv_5d_change is not None else None
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
                
                # New filters
                # IV Index filter - only apply if data is available
                if iv_index is not None:
                    iv_index_pct = iv_index * 100  # Convert to percentage
                    if iv_index_pct < min_iv_index:
                        passes_criteria = False
                
                # Expanding volatility filter - only apply if requested and data available
                if expanding_vol_only and iv_5d_change is not None:
                    if iv_5d_change <= 0:
                        passes_criteria = False
                
                # If symbol passes all available criteria
                if passes_criteria:
                    # Calculate enhanced scoring and trend analysis
                    screening_score_data = self._calculate_screening_score(metrics)
                    trend_score = self._calculate_trend_score(metrics)
                    
                    # Simple momentum indicator
                    momentum_signal = "High" if trend_score > 0.3 else ("Low" if trend_score < -0.3 else "Neutral")
                    
                    # Add to results - preserve None values for missing data
                    result = {
                        'symbol': symbol,
                        'last_price': last_price,
                        'iv_rank': iv_rank,
                        'iv_index': metrics.get('implied_volatility_index'),
                        'iv_index_5d_change': metrics.get('implied_volatility_index_5_day_change'),
                        'volume': volume,
                        'avg_volume': avg_volume,
                        'liquidity_rank': liquidity_rank,
                        'liquidity_rating': metrics.get('liquidity_rating'),
                        'screening_score': screening_score_data.get('score', 0),
                        'trend_score': trend_score,
                        'momentum_signal': momentum_signal,
                        'passes_screen': True
                    }
                    results.append(result)
                    
            except Exception as e:
                self.logger.error(f"❌ Error screening {symbol}: {e}")
                continue
        
        # Sort by new screening score (descending) by default, handling None values
        try:
            results.sort(key=lambda x: float(x.get('screening_score', 0)) if x.get('screening_score') is not None else 0, reverse=True)
        except Exception as e:
            self.logger.error(f"❌ Error sorting results: {e}")
            # Debug: check what's in the results
            for i, result in enumerate(results[:3]):  # Check first 3 results
                self.logger.error(f"Debug result {i}: screening_score={result.get('screening_score')}, type={type(result.get('screening_score'))}")
            # Don't sort if there's an error
        
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
    
    @app.route('/api/screener/underlying-rankings')
    def get_underlying_rankings():
        """Get individual underlying rankings from Main List watchlist"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            # Get Main List rankings
            rankings = screener.rank_main_list_underlyings()
            
            # Get portfolio limits info
            portfolio_breakdown = screener._get_current_portfolio_breakdown()
            
            return jsonify({
                'success': True,
                'data': {
                    'rankings': rankings,
                    'total_symbols': len(rankings),
                    'source_watchlist': 'Main List',
                    'eligible_symbols': len([r for r in rankings if r['can_add_position']]),
                    'portfolio_limits': {
                        'max_sector_pct': 10.0,
                        'max_equity_pct': 60.0,
                        'current_equity_pct': portfolio_breakdown['asset_types'].get('equities', 0),
                        'equity_capacity_remaining': max(0, 60.0 - portfolio_breakdown['asset_types'].get('equities', 0)),
                        'primary_account': portfolio_breakdown.get('primary_account', '5WX84566'),
                        'max_active_trading_allocation': portfolio_breakdown.get('active_allocation_limit', 0),
                        'active_allocation_used': portfolio_breakdown.get('active_allocation_used', 0),
                        'active_allocation_remaining': portfolio_breakdown.get('active_allocation_remaining', 0),
                        'long_term_value': portfolio_breakdown.get('long_term_value', 0),
                        'active_value': portfolio_breakdown.get('active_value', 0),
                        'account_breakdown': {
                            'active_values': portfolio_breakdown.get('account_active_values', {}),
                            'limits': portfolio_breakdown.get('account_active_limits', {})
                        }
                    },
                    'sector_cache_stats': screener.sector_classifier.get_cache_stats(),
                    'timestamp': datetime.now().isoformat()
                }
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/underlying-rankings: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/screener/sector-lookup/<symbol>')
    def get_symbol_sector(symbol):
        """Get sector information for a specific symbol"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            sector_info = screener.sector_classifier.get_symbol_sector(symbol.upper())
            
            return jsonify({
                'success': True,
                'symbol': symbol.upper(),
                'sector_info': sector_info
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/sector-lookup/{symbol}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/screener/max-active-allocation', methods=['POST'])
    def update_max_active_allocation():
        """Update the maximum active trading allocation for primary account"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            max_allocation = data.get('max_allocation')
            account = data.get('account', '5WX84566')  # Default to 566
            
            if max_allocation is None or max_allocation < 0:
                return jsonify({'success': False, 'error': 'Invalid allocation amount'}), 400
            
            screener.account_active_trading_limits[account] = float(max_allocation)
            
            return jsonify({
                'success': True,
                'account': account,
                'max_active_trading_allocation': screener.account_active_trading_limits[account],
                'all_limits': screener.account_active_trading_limits
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/max-active-allocation: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/screener/long-term-flags', methods=['POST'])
    def update_long_term_flag():
        """Update long-term flag for a position"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            account = data.get('account')
            symbol = data.get('symbol')
            is_long_term = data.get('is_long_term', False)
            
            if not account or not symbol:
                return jsonify({'success': False, 'error': 'Account and symbol are required'}), 400
            
            screener.set_position_long_term_flag(account, symbol, is_long_term)
            
            return jsonify({
                'success': True,
                'account': account,
                'symbol': symbol,
                'is_long_term': is_long_term,
                'position_key': f"{account}:{symbol}"
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/long-term-flags: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/screener/long-term-flags')
    def get_long_term_flags():
        """Get all long-term position flags"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            return jsonify({
                'success': True,
                'flags': screener.long_term_position_flags,
                'count': len(screener.long_term_position_flags)
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/long-term-flags: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/screener/portfolio-allocation')
    def get_portfolio_allocation():
        """Get current portfolio allocation breakdown"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            breakdown = screener._get_current_portfolio_breakdown()
            
            return jsonify({
                'success': True,
                'allocation': breakdown,
                'limits': {
                    'max_sector_pct': 10.0,
                    'max_equity_pct': 60.0
                },
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/screener/portfolio-allocation: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
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
    
    # Smart Pricing Endpoints
    
    @app.route('/api/smart-pricing/status')
    def get_smart_pricing_status():
        """Get smart pricing service status"""
        try:
            if not tracker.price_adjustment_service:
                return jsonify({'error': 'Smart pricing service not initialized'}), 503
                
            status = tracker.price_adjustment_service.get_tracking_status()
            return jsonify(status)
            
        except Exception as e:
            logging.error(f"❌ Error in /api/smart-pricing/status: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/smart-pricing/working-orders/<account_number>')
    def get_working_orders_for_adjustment(account_number):
        """Get working orders that could benefit from price adjustment"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
                
            order_manager = get_order_manager()
            if not order_manager:
                return jsonify({'error': 'Order manager not available'}), 503
                
            working_orders = order_manager.get_working_orders(account_number)
            
            # Filter orders that are good candidates for price adjustment
            adjustment_candidates = []
            for order in working_orders:
                order_age_minutes = 0
                if order.get('time-in-force') == 'Day':
                    # Calculate order age (simplified)
                    created_at = order.get('entered-time', '')
                    if created_at:
                        # This would need proper datetime parsing
                        order_age_minutes = 30  # Placeholder
                
                adjustment_candidates.append({
                    'order_id': order.get('id'),
                    'symbol': order.get('underlying-symbol'),
                    'price': order.get('price'),
                    'quantity': order.get('quantity'),
                    'status': order.get('status'),
                    'age_minutes': order_age_minutes,
                    'can_adjust': order_age_minutes >= 10  # Can adjust after 10 minutes
                })
            
            return jsonify({
                'working_orders': adjustment_candidates,
                'total_orders': len(working_orders),
                'adjustment_candidates': len([o for o in adjustment_candidates if o['can_adjust']]),
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/smart-pricing/working-orders: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/smart-pricing/track-order', methods=['POST'])
    def track_order_for_adjustment():
        """Add an order to smart pricing tracking"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
                
            if not tracker.price_adjustment_service:
                return jsonify({'error': 'Smart pricing service not available'}), 503
                
            data = request.get_json()
            required_fields = ['order_id', 'account_number', 'symbol', 'initial_price', 'mid_price']
            
            if not all(field in data for field in required_fields):
                return jsonify({'error': 'Missing required fields'}), 400
                
            tracker.price_adjustment_service.track_order(
                order_id=data['order_id'],
                account_number=data['account_number'],
                symbol=data['symbol'],
                strategy_type=data.get('strategy_type', 'directional'),
                initial_price=float(data['initial_price']),
                mid_price=float(data['mid_price']),
                is_credit=data.get('is_credit', True)
            )
            
            return jsonify({
                'success': True,
                'message': f"Order {data['order_id']} added to smart pricing tracking",
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/smart-pricing/track-order: {e}")
            return jsonify({'error': str(e)}), 500

    # Underlyings Management Routes
    
    @app.route('/underlyings')
    def underlyings_page():
        """Render the underlyings management page"""
        return render_template('underlyings.html')
    
    @app.route('/api/underlyings')
    def get_all_underlyings():
        """Get all underlyings grouped by sector and industry"""
        try:
            # Get all symbols from sector cache
            all_symbols = dict(screener.sector_classifier.sector_cache)
            
            # Group by sector and industry
            sectors = {}
            total_symbols = len(all_symbols)
            
            for symbol, data in all_symbols.items():
                sector = data.get('sector', 'Unknown')
                industry = data.get('industry', 'Unknown')
                source = data.get('source', 'unknown')
                last_updated = data.get('last_updated', '')
                
                if sector not in sectors:
                    sectors[sector] = {
                        'name': sector,
                        'symbol_count': 0,
                        'industries': {},
                        'symbols': []
                    }
                
                if industry not in sectors[sector]['industries']:
                    sectors[sector]['industries'][industry] = {
                        'name': industry,
                        'symbol_count': 0,
                        'symbols': []
                    }
                
                symbol_info = {
                    'symbol': symbol,
                    'sector': sector,
                    'industry': industry,
                    'source': source,
                    'last_updated': last_updated
                }
                
                sectors[sector]['symbols'].append(symbol_info)
                sectors[sector]['industries'][industry]['symbols'].append(symbol_info)
                sectors[sector]['symbol_count'] += 1
                sectors[sector]['industries'][industry]['symbol_count'] += 1
            
            # Convert to sorted lists
            sector_list = []
            for sector_name, sector_data in sorted(sectors.items()):
                # Sort industries within sector
                industries_list = []
                for industry_name, industry_data in sorted(sector_data['industries'].items()):
                    # Sort symbols within industry
                    industry_data['symbols'].sort(key=lambda x: x['symbol'])
                    industries_list.append(industry_data)
                
                sector_data['industries'] = industries_list
                sector_data['symbols'].sort(key=lambda x: x['symbol'])
                sector_list.append(sector_data)
            
            # Sort sectors by symbol count (descending)
            sector_list.sort(key=lambda x: x['symbol_count'], reverse=True)
            
            return jsonify({
                'success': True,
                'data': {
                    'sectors': sector_list,
                    'total_symbols': total_symbols,
                    'total_sectors': len(sector_list),
                    'cache_stats': screener.sector_classifier.get_cache_stats(),
                    'timestamp': datetime.now().isoformat()
                }
            })
            
        except Exception as e:
            logging.error(f"❌ Error in /api/underlyings: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/underlyings/<symbol>', methods=['PUT'])
    def update_underlying_classification(symbol):
        """Update sector/industry classification for a symbol"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            new_sector = data.get('sector', '').strip()
            new_industry = data.get('industry', '').strip()
            
            if not new_sector or not new_industry:
                return jsonify({'success': False, 'error': 'Sector and industry are required'}), 400
            
            symbol = symbol.upper().strip()
            
            # Update the classification
            updated_data = {
                'sector': new_sector,
                'industry': new_industry,
                'last_updated': datetime.now().isoformat(),
                'source': 'manual_edit'
            }
            
            screener.sector_classifier.sector_cache[symbol] = updated_data
            screener.sector_classifier._save_cache()
            
            return jsonify({
                'success': True,
                'symbol': symbol,
                'updated_data': updated_data,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error updating {symbol}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/underlyings/bulk-update', methods=['POST'])
    def bulk_update_underlyings():
        """Bulk update sector/industry classifications"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            updates = data.get('updates', [])
            
            if not updates:
                return jsonify({'success': False, 'error': 'No updates provided'}), 400
            
            updated_symbols = []
            failed_symbols = []
            
            for update in updates:
                try:
                    symbol = update.get('symbol', '').upper().strip()
                    new_sector = update.get('sector', '').strip()
                    new_industry = update.get('industry', '').strip()
                    
                    # Require symbol and at least one field to be provided
                    if not symbol or (not new_sector and not new_industry):
                        failed_symbols.append({'symbol': symbol, 'error': 'Symbol and at least one field (sector or industry) required'})
                        continue
                    
                    # Get existing data to preserve fields that aren't being updated
                    existing_data = screener.sector_classifier.sector_cache.get(symbol, {})
                    
                    updated_data = {
                        'sector': new_sector if new_sector else existing_data.get('sector', ''),
                        'industry': new_industry if new_industry else existing_data.get('industry', ''),
                        'last_updated': datetime.now().isoformat(),
                        'source': 'bulk_edit'
                    }
                    
                    screener.sector_classifier.sector_cache[symbol] = updated_data
                    updated_symbols.append({'symbol': symbol, 'data': updated_data})
                    
                except Exception as e:
                    failed_symbols.append({'symbol': symbol, 'error': str(e)})
            
            # Save cache after all updates
            if updated_symbols:
                screener.sector_classifier._save_cache()
            
            return jsonify({
                'success': True,
                'updated_count': len(updated_symbols),
                'failed_count': len(failed_symbols),
                'updated_symbols': updated_symbols,
                'failed_symbols': failed_symbols,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error in bulk update: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/underlyings/add-symbol', methods=['POST'])
    def add_new_symbol():
        """Add a new symbol with custom sector/industry classification"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            data = request.get_json()
            symbol = data.get('symbol', '').upper().strip()
            sector = data.get('sector', '').strip()
            industry = data.get('industry', '').strip()
            
            if not symbol or not sector or not industry:
                return jsonify({'success': False, 'error': 'Symbol, sector, and industry are required'}), 400
            
            # Check if symbol already exists
            if symbol in screener.sector_classifier.sector_cache:
                return jsonify({'success': False, 'error': f'Symbol {symbol} already exists'}), 409
            
            # Add new symbol
            new_data = {
                'sector': sector,
                'industry': industry,
                'last_updated': datetime.now().isoformat(),
                'source': 'manual_add'
            }
            
            screener.sector_classifier.sector_cache[symbol] = new_data
            screener.sector_classifier._save_cache()
            
            return jsonify({
                'success': True,
                'symbol': symbol,
                'data': new_data,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error adding symbol: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/underlyings/delete-symbol/<symbol>', methods=['DELETE'])
    def delete_symbol(symbol):
        """Delete a symbol from the classification system"""
        try:
            if not tracker.tasty_client:
                return jsonify({'error': 'Not authenticated'}), 401
            
            symbol = symbol.upper().strip()
            
            if symbol not in screener.sector_classifier.sector_cache:
                return jsonify({'success': False, 'error': f'Symbol {symbol} not found'}), 404
            
            # Remove symbol
            removed_data = screener.sector_classifier.sector_cache.pop(symbol, None)
            screener.sector_classifier._save_cache()
            
            return jsonify({
                'success': True,
                'symbol': symbol,
                'removed_data': removed_data,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logging.error(f"❌ Error deleting symbol {symbol}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/underlyings/export')
    def export_underlyings():
        """Export all underlyings as CSV"""
        try:
            import csv
            import io
            from flask import Response
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Symbol', 'Sector', 'Industry', 'Source', 'Last Updated'])
            
            # Write data
            for symbol, data in sorted(screener.sector_classifier.sector_cache.items()):
                writer.writerow([
                    symbol,
                    data.get('sector', ''),
                    data.get('industry', ''),
                    data.get('source', ''),
                    data.get('last_updated', '')
                ])
            
            output.seek(0)
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=underlyings_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
            )
            
        except Exception as e:
            logging.error(f"❌ Error exporting underlyings: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/get_long_term_flags')
    def api_get_long_term_flags():
        """Get all long-term position flags"""
        try:
            return jsonify({
                'success': True,
                'flags': screener.long_term_position_flags
            })
        except Exception as e:
            logging.error(f"❌ Error getting long-term flags: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/set_long_term_flag', methods=['POST'])
    def api_set_long_term_flag():
        """Set long-term flag for a position"""
        try:
            data = request.get_json()
            account = data.get('account')
            symbol = data.get('symbol')
            is_long_term = data.get('is_long_term', False)
            
            if not account or not symbol:
                return jsonify({'success': False, 'error': 'Account and symbol are required'}), 400
            
            screener.set_position_long_term_flag(account, symbol, is_long_term)
            
            return jsonify({'success': True})
            
        except Exception as e:
            logging.error(f"❌ Error setting long-term flag: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    return screener