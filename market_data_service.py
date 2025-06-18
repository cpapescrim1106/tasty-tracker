#!/usr/bin/env python3
"""
Market Data Service with Database Caching
Centralized service for market data with multi-tier caching strategy
"""

import sqlite3
import json
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import requests
from futures_contract_mapper import FuturesContractMapper


@dataclass
class MarketDataPoint:
    """Single market data point"""
    symbol: str
    timestamp: datetime
    last_price: Optional[float]
    bid_price: Optional[float] 
    ask_price: Optional[float]
    volume: Optional[int]
    iv_rank: Optional[float]
    iv_index: Optional[float]
    iv_5d_change: Optional[float]
    historical_vol_30d: Optional[float]
    beta: Optional[float]
    liquidity_rank: Optional[float]
    data_source: str


@dataclass
class PositionSnapshot:
    """Position snapshot for caching"""
    snapshot_id: int
    account_number: str
    timestamp: datetime
    positions_json: str
    total_notional: float
    total_delta: float
    net_liq_deployed: float


class MarketDataService:
    """Centralized market data service with database caching"""
    
    def __init__(self, db_path: str = "market_data.db", tracker=None):
        self.db_path = db_path
        self.tracker = tracker
        self.logger = logging.getLogger(__name__)
        
        # In-memory caches
        self.memory_cache: Dict[str, MarketDataPoint] = {}
        self.watchlist_cache: Dict[str, Any] = {}
        self.balance_cache: Dict[str, Any] = {}
        
        # Cache TTL settings (seconds)
        self.cache_ttl = {
            'realtime': 60,        # 1 minute for dashboard data
            'screening': 900,      # 15 minutes for screening data
            'watchlist': 86400,    # 24 hours for watchlists
            'balance': 300,        # 5 minutes for balances
            'position_snapshot': 300  # 5 minutes for position snapshots
        }
        
        # Thread safety
        self.cache_lock = threading.RLock()
        
        # Initialize futures contract mapper
        self.futures_mapper = FuturesContractMapper(tracker=tracker)
        
        # Initialize database
        self._init_database()
        
        self.logger.info("🗄️ MarketDataService initialized with database caching")
    
    def _init_database(self):
        """Initialize SQLite database with required tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript("""
                -- Market data cache table
                CREATE TABLE IF NOT EXISTS market_data_cache (
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    last_price REAL,
                    bid_price REAL,
                    ask_price REAL,
                    volume INTEGER,
                    iv_rank REAL,
                    iv_index REAL,
                    iv_5d_change REAL,
                    historical_vol_30d REAL,
                    beta REAL,
                    liquidity_rank REAL,
                    data_source TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (symbol, timestamp)
                );
                
                -- Position snapshots table
                CREATE TABLE IF NOT EXISTS position_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_number TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    positions_json TEXT NOT NULL,
                    total_notional REAL DEFAULT 0,
                    total_delta REAL DEFAULT 0,
                    net_liq_deployed REAL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Account balance history
                CREATE TABLE IF NOT EXISTS account_balances (
                    account_number TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    net_liquidating_value REAL,
                    cash_balance REAL,
                    buying_power REAL,
                    day_trading_buying_power REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (account_number, timestamp)
                );
                
                -- Watchlist cache
                CREATE TABLE IF NOT EXISTS watchlist_cache (
                    watchlist_name TEXT PRIMARY KEY,
                    watchlist_data TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Sector classification cache (permanent)
                CREATE TABLE IF NOT EXISTS sector_cache (
                    symbol TEXT PRIMARY KEY,
                    sector TEXT,
                    industry TEXT,
                    source TEXT,
                    confidence REAL DEFAULT 1.0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Create indexes for performance
                CREATE INDEX IF NOT EXISTS idx_market_data_symbol_timestamp 
                    ON market_data_cache(symbol, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_position_snapshots_account_timestamp 
                    ON position_snapshots(account_number, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_account_balances_account_timestamp 
                    ON account_balances(account_number, timestamp DESC);
                """)
                
            self.logger.info("✅ Database schema initialized successfully")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize database: {e}")
            raise
    
    def get_market_data(self, symbols: List[str], data_type: str = 'realtime', 
                       max_age_minutes: int = None, force_refresh: bool = False) -> Dict[str, MarketDataPoint]:
        """Get market data with intelligent caching and validation
        
        Args:
            symbols: List of symbols to fetch
            data_type: 'realtime', 'screening', or 'historical'
            max_age_minutes: Override default cache TTL
            force_refresh: Skip cache and force fresh API call
            
        Returns:
            Dict mapping symbol to MarketDataPoint
        """
        if max_age_minutes is None:
            max_age_minutes = self.cache_ttl.get(data_type, 900) // 60
        
        # Map generic futures symbols to active contracts
        symbol_mapping = self.futures_mapper.map_symbols(symbols)
        mapped_symbols = [symbol_mapping[symbol] for symbol in symbols]
        
        # Log any mappings that occurred
        mappings_made = {orig: mapped for orig, mapped in symbol_mapping.items() if orig != mapped}
        if mappings_made:
            self.logger.info(f"🔄 Mapped futures contracts: {mappings_made}")
        
        results = {}
        symbols_to_fetch = []
        
        # If force refresh requested, skip cache entirely
        if force_refresh:
            self.logger.info(f"🔄 Force refresh requested - skipping cache for {len(mapped_symbols)} symbols")
            symbols_to_fetch = mapped_symbols.copy()
        else:
            # Normal cache-first approach with validation
            with self.cache_lock:
                for orig_symbol, mapped_symbol in symbol_mapping.items():
                    # Check memory cache first (using mapped symbol)
                    cached_data = self._get_from_memory_cache(mapped_symbol, max_age_minutes)
                    if cached_data and self._is_valid_data(cached_data):
                        # Store with original symbol as key
                        results[orig_symbol] = cached_data
                        continue
                    
                    # Check database cache (using mapped symbol)
                    cached_data = self._get_from_database_cache(mapped_symbol, max_age_minutes)
                    if cached_data and self._is_valid_data(cached_data):
                        # Store with original symbol as key
                        results[orig_symbol] = cached_data
                        # Store in memory cache for faster access (using mapped symbol)
                        self.memory_cache[mapped_symbol] = cached_data
                        continue
                    
                    # Need to fetch from API (using mapped symbol)
                    symbols_to_fetch.append(mapped_symbol)
            
            # Cache validation: If we got cached data, validate its quality
            if results and not symbols_to_fetch:
                cache_quality = self._validate_cache_quality(results, symbols)
                if not cache_quality['is_valid']:
                    self.logger.warning(f"⚠️ Cache validation failed: {cache_quality['reason']}")
                    self.logger.info(f"🔄 Falling back to fresh API call for all {len(mapped_symbols)} symbols")
                    results = {}
                    symbols_to_fetch = mapped_symbols.copy()
                else:
                    self.logger.debug(f"✅ Cache validation passed: {cache_quality['reason']}")
        
        # Fetch missing data from API
        if symbols_to_fetch:
            # Reverse map to get original symbols for API call
            reverse_mapping = {mapped: orig for orig, mapped in symbol_mapping.items()}
            original_symbols_to_fetch = [reverse_mapping.get(mapped, mapped) for mapped in symbols_to_fetch]
            
            self.logger.info(f"📡 Fetching {len(symbols_to_fetch)} symbols from API: {symbols_to_fetch[:5]}...")
            self.logger.info(f"📡 Using original symbols for analytics: {original_symbols_to_fetch[:5]}...")
            api_results = self._fetch_from_api(original_symbols_to_fetch)
            
            # Store results in both caches - api_results are already keyed by original symbols
            for orig_symbol, data in api_results.items():
                self._store_in_caches(data)
                results[orig_symbol] = data
        
        self.logger.debug(f"📊 Retrieved market data for {len(results)}/{len(symbols)} symbols")
        return results
    
    def _get_from_memory_cache(self, symbol: str, max_age_minutes: int) -> Optional[MarketDataPoint]:
        """Get data from memory cache if not expired"""
        if symbol not in self.memory_cache:
            return None
        
        data = self.memory_cache[symbol]
        age_minutes = (datetime.now() - data.timestamp).total_seconds() / 60
        
        if age_minutes <= max_age_minutes:
            return data
        
        # Expired, remove from memory cache
        del self.memory_cache[symbol]
        return None
    
    def _get_from_database_cache(self, symbol: str, max_age_minutes: int) -> Optional[MarketDataPoint]:
        """Get data from database cache if not expired"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=max_age_minutes)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM market_data_cache 
                    WHERE symbol = ? AND timestamp >= ? 
                    ORDER BY timestamp DESC LIMIT 1
                """, (symbol, cutoff_time))
                
                row = cursor.fetchone()
                if row:
                    return MarketDataPoint(
                        symbol=row['symbol'],
                        timestamp=datetime.fromisoformat(row['timestamp']),
                        last_price=row['last_price'],
                        bid_price=row['bid_price'],
                        ask_price=row['ask_price'],
                        volume=row['volume'],
                        iv_rank=row['iv_rank'],
                        iv_index=row['iv_index'],
                        iv_5d_change=row['iv_5d_change'],
                        historical_vol_30d=row['historical_vol_30d'],
                        beta=row['beta'],
                        liquidity_rank=row['liquidity_rank'],
                        data_source=row['data_source']
                    )
                    
        except Exception as e:
            self.logger.error(f"❌ Error reading from database cache for {symbol}: {e}")
        
        return None
    
    def _is_valid_data(self, data: MarketDataPoint) -> bool:
        """Check if cached data is valid for use"""
        # Invalid if explicitly marked as no_data
        if data.data_source == 'no_data':
            return False
        
        # Invalid if missing essential price data
        if data.last_price is None:
            return False
            
        # Valid data
        return True
    
    def _validate_cache_quality(self, cached_results: Dict[str, MarketDataPoint], 
                              requested_symbols: List[str]) -> Dict[str, Any]:
        """Validate the quality of cached data batch"""
        total_symbols = len(requested_symbols)
        valid_count = 0
        price_count = 0
        no_data_count = 0
        
        # Sample up to 10 symbols for validation
        sample_size = min(10, total_symbols)
        sample_symbols = requested_symbols[:sample_size]
        
        for symbol in sample_symbols:
            if symbol in cached_results:
                data = cached_results[symbol]
                valid_count += 1
                
                if data.last_price is not None and data.last_price > 0:
                    price_count += 1
                    
                if data.data_source == 'no_data':
                    no_data_count += 1
        
        # Calculate validation metrics
        coverage_pct = (valid_count / sample_size) * 100
        price_pct = (price_count / sample_size) * 100 if sample_size > 0 else 0
        no_data_pct = (no_data_count / sample_size) * 100 if sample_size > 0 else 0
        
        # Validation rules
        is_valid = (
            coverage_pct >= 90 and  # At least 90% coverage
            price_pct >= 70 and     # At least 70% have valid prices
            no_data_pct <= 30       # No more than 30% marked as no_data
        )
        
        if is_valid:
            reason = f"{coverage_pct:.0f}% coverage, {price_pct:.0f}% valid prices"
        else:
            reason = f"Poor quality: {coverage_pct:.0f}% coverage, {price_pct:.0f}% valid prices, {no_data_pct:.0f}% no_data"
        
        return {
            'is_valid': is_valid,
            'reason': reason,
            'coverage_pct': coverage_pct,
            'price_pct': price_pct,
            'no_data_pct': no_data_pct,
            'sample_size': sample_size
        }
    
    def _fetch_from_api(self, symbols: List[str]) -> Dict[str, MarketDataPoint]:
        """Fetch market data from TastyTrade API using unified approach: analytics + pricing"""
        results = {}
        
        if not self.tracker or not hasattr(self.tracker, 'tasty_client'):
            self.logger.warning("⚠️ No tracker or tasty_client available for API calls")
            return results
        
        if not self.tracker.tasty_client or not hasattr(self.tracker.tasty_client, 'session_token'):
            self.logger.warning("⚠️ No valid tasty_client session token available")
            return results
        
        headers = {
            'Authorization': self.tracker.tasty_client.session_token,
            'Content-Type': 'application/json'
        }
        
        # Step 1: Get analytics data using ORIGINAL symbols (market-metrics needs generic futures)
        analytics_data = self._fetch_analytics_data(symbols, headers)
        
        # Step 2: Map symbols for pricing (futures need active contracts)
        mapped_symbols = self.futures_mapper.get_mapped_symbols(symbols)
        symbol_mapping = dict(zip(symbols, mapped_symbols))
        
        # Step 3: Get pricing data using MAPPED symbols (pricing needs active contracts)
        pricing_data = self._fetch_pricing_data(mapped_symbols, headers)
        
        # Step 4: Merge analytics (original symbols) and pricing (mapped symbols) data
        results = self._merge_analytics_and_pricing_with_mapping(symbols, analytics_data, pricing_data, symbol_mapping)
        
        return results
    
    def _fetch_analytics_data(self, symbols: List[str], headers: Dict[str, str]) -> Dict[str, Dict]:
        """Fetch analytics data for all symbols using /market-metrics endpoint with batching"""
        analytics_data = {}
        
        if not symbols:
            return analytics_data
        
        # Process in batches of 100 to avoid API limits
        batch_size = 100
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        
        self.logger.info(f"📊 Fetching analytics data for {len(symbols)} symbols in {total_batches} batches: {symbols[:5]}...")
        
        for i in range(0, len(symbols), batch_size):
            batch_symbols = symbols[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            
            self.logger.info(f"📊 Processing analytics batch {batch_num}/{total_batches} ({len(batch_symbols)} symbols)")
            
            try:
                symbols_param = ','.join(batch_symbols)
                api_url = "https://api.tastyworks.com/market-metrics"
                
                response = requests.get(api_url, params={'symbols': symbols_param}, headers=headers, timeout=15)
                self.logger.info(f"📊 Analytics batch {batch_num} response: Status {response.status_code}, Content-Length: {len(response.content)}")
                
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('data', {}).get('items', [])
                    self.logger.info(f"📊 Batch {batch_num}: Found {len(items)} items (requested {len(batch_symbols)})")
                    
                    for item in items:
                        symbol = item.get('symbol', '')
                        if symbol in batch_symbols:
                            analytics_data[symbol] = item
                            # Debug key futures analytics data
                            if symbol.startswith('/') and symbol in ['/CL', '/ES', '/ZN', '/GC', '/NQ']:
                                iv_rank = item.get('implied-volatility-index-rank')
                                self.logger.info(f"🔍 Debug key futures analytics: {symbol} IV Rank = {iv_rank}")
                    
                    # Check for missing symbols in this batch
                    returned_symbols = {item.get('symbol', '') for item in items}
                    missing_symbols = set(batch_symbols) - returned_symbols
                    if missing_symbols:
                        self.logger.warning(f"⚠️ Batch {batch_num} missing symbols: {missing_symbols}")
                        
                else:
                    self.logger.warning(f"⚠️ Analytics batch {batch_num} failed with status {response.status_code}: {response.text[:200]}")
                    
            except Exception as e:
                self.logger.error(f"❌ Error fetching analytics batch {batch_num}: {e}")
        
        self.logger.info(f"📊 Successfully processed analytics for {len(analytics_data)} symbols across all batches")
        return analytics_data
    
    def _fetch_pricing_data(self, symbols: List[str], headers: Dict[str, str]) -> Dict[str, Dict]:
        """Fetch pricing data for all symbols using /market-data/by-type endpoint"""
        pricing_data = {}
        
        if not symbols:
            return pricing_data
        
        # Group symbols by type for pricing API
        symbol_groups = self._group_symbols_by_type(symbols)
        
        # Fetch pricing for each instrument type
        for instrument_type, type_symbols in symbol_groups.items():
            if not type_symbols:
                continue
                
            try:
                type_pricing = self._fetch_pricing_by_type(instrument_type, type_symbols, headers)
                pricing_data.update(type_pricing)
            except Exception as e:
                self.logger.error(f"❌ Error fetching {instrument_type} pricing: {e}")
                continue
        
        return pricing_data
    
    def _fetch_pricing_by_type(self, instrument_type: str, symbols: List[str], headers: Dict[str, str]) -> Dict[str, Dict]:
        """Fetch pricing data for specific instrument type with batching"""
        results = {}
        
        if not symbols:
            return results
        
        # Use appropriate parameter name for each type
        if instrument_type == 'futures':
            param_name = 'future'
        elif instrument_type == 'equities':
            param_name = 'equity'
        elif instrument_type == 'cryptocurrencies':
            param_name = 'cryptocurrency'
        else:
            self.logger.warning(f"⚠️ Unknown instrument type for pricing: {instrument_type}")
            return results
        
        # Process in batches of 100 to avoid API limits
        batch_size = 100
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        
        self.logger.info(f"💰 Fetching pricing data for {len(symbols)} {instrument_type} in {total_batches} batches: {symbols[:5]}...")
        
        for i in range(0, len(symbols), batch_size):
            batch_symbols = symbols[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            
            self.logger.info(f"💰 Processing pricing batch {batch_num}/{total_batches} ({len(batch_symbols)} {instrument_type})")
            
            try:
                symbols_param = ','.join(batch_symbols)
                api_url = "https://api.tastyworks.com/market-data/by-type"
                params = {param_name: symbols_param}
                
                response = requests.get(api_url, params=params, headers=headers, timeout=15)
                self.logger.info(f"💰 Pricing batch {batch_num} response: Status {response.status_code}, Content-Length: {len(response.content)}")
                
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('data', {}).get('items', [])
                    self.logger.info(f"💰 Batch {batch_num}: Found {len(items)} pricing items (requested {len(batch_symbols)})")
                    
                    for item in items:
                        symbol = item.get('symbol', '')
                        if symbol in batch_symbols:
                            results[symbol] = item
                    
                    # Check for missing symbols in this batch
                    returned_symbols = {item.get('symbol', '') for item in items}
                    missing_symbols = set(batch_symbols) - returned_symbols
                    if missing_symbols:
                        self.logger.warning(f"⚠️ Pricing batch {batch_num} missing symbols: {missing_symbols}")
                        
                else:
                    self.logger.warning(f"⚠️ Pricing batch {batch_num} failed with status {response.status_code}: {response.text[:200]}")
                    
            except Exception as e:
                self.logger.error(f"❌ Error fetching pricing batch {batch_num}: {e}")
        
        self.logger.info(f"💰 Successfully processed pricing for {len(results)} {instrument_type} across all batches")
        return results
    
    def _merge_analytics_and_pricing_with_mapping(self, symbols: List[str], analytics_data: Dict[str, Dict], pricing_data: Dict[str, Dict], symbol_mapping: Dict[str, str]) -> Dict[str, MarketDataPoint]:
        """Merge analytics and pricing data with futures symbol mapping"""
        results = {}
        
        for symbol in symbols:
            # Analytics data uses original symbol (e.g., /CL)
            analytics = analytics_data.get(symbol, {})
            # Pricing data uses mapped symbol (e.g., /CLN5)
            mapped_symbol = symbol_mapping.get(symbol, symbol)
            pricing = pricing_data.get(mapped_symbol, {})
            
            # Debug futures mapping
            if symbol.startswith('/') and symbol != mapped_symbol:
                self.logger.info(f"🔄 Merging data: {symbol} analytics + {mapped_symbol} pricing")
            
            # Extract analytics data
            iv_rank = self._safe_float(analytics.get('implied-volatility-index-rank'))
            # Debug futures IV rank processing
            if symbol.startswith('/'):
                self.logger.info(f"🔍 Debug {symbol} merge: raw IV rank = {analytics.get('implied-volatility-index-rank')}, after _safe_float = {iv_rank}")
            # Convert IV rank from decimal to percentage (0.487 -> 48.7)
            if iv_rank is not None:
                iv_rank = iv_rank * 100
                if symbol.startswith('/'):
                    self.logger.info(f"🔍 Debug {symbol} merge: after *100 = {iv_rank}")
            iv_index = self._safe_float(analytics.get('implied-volatility-index'))
            iv_5d_change = self._safe_float(analytics.get('implied-volatility-index-5-day-change'))
            historical_vol_30d = self._safe_float(analytics.get('historical-volatility-30-day'))
            beta = self._safe_float(analytics.get('beta'))
            liquidity_rank = self._safe_float(analytics.get('liquidity-rank'))
            
            # Extract pricing data - try multiple field names
            last_price = None
            bid_price = None
            ask_price = None
            volume = None
            
            if pricing:
                # Try common pricing field names
                last_price = self._safe_float(
                    pricing.get('last') or 
                    pricing.get('mark') or 
                    pricing.get('last-price') or
                    pricing.get('mark-price')
                )
                bid_price = self._safe_float(pricing.get('bid') or pricing.get('bid-price'))
                ask_price = self._safe_float(pricing.get('ask') or pricing.get('ask-price'))
                volume = self._safe_int(pricing.get('volume'))
            
            # Determine data source
            has_analytics = bool(analytics)
            has_pricing = bool(pricing)
            
            if has_analytics and has_pricing:
                data_source = 'tastytrade_combined'
            elif has_analytics:
                data_source = 'tastytrade_analytics_only'
            elif has_pricing:
                data_source = 'tastytrade_pricing_only'
            else:
                data_source = 'no_data'
            
            # Create MarketDataPoint
            market_data = MarketDataPoint(
                symbol=symbol,  # Always use original symbol in result
                timestamp=datetime.now(),
                last_price=last_price,
                bid_price=bid_price,
                ask_price=ask_price,
                volume=volume,
                iv_rank=iv_rank,
                iv_index=iv_index,
                iv_5d_change=iv_5d_change,
                historical_vol_30d=historical_vol_30d,
                beta=beta,
                liquidity_rank=liquidity_rank,
                data_source=data_source
            )
            
            results[symbol] = market_data
            
        self.logger.info(f"🔗 Mapped merge completed for {len(results)} symbols: "
                        f"{len([r for r in results.values() if r.data_source == 'tastytrade_combined'])} combined, "
                        f"{len([r for r in results.values() if r.data_source == 'tastytrade_analytics_only'])} analytics-only, "
                        f"{len([r for r in results.values() if r.data_source == 'tastytrade_pricing_only'])} pricing-only")
        
        return results
    
    def _merge_analytics_and_pricing(self, symbols: List[str], analytics_data: Dict[str, Dict], pricing_data: Dict[str, Dict]) -> Dict[str, MarketDataPoint]:
        """Merge analytics and pricing data into MarketDataPoint objects"""
        results = {}
        
        for symbol in symbols:
            analytics = analytics_data.get(symbol, {})
            pricing = pricing_data.get(symbol, {})
            
            # Extract analytics data
            iv_rank = self._safe_float(analytics.get('implied-volatility-index-rank'))
            # Debug futures IV rank processing
            if symbol.startswith('/'):
                self.logger.info(f"🔍 Debug {symbol} merge: raw IV rank = {analytics.get('implied-volatility-index-rank')}, after _safe_float = {iv_rank}")
            # Convert IV rank from decimal to percentage (0.487 -> 48.7)
            if iv_rank is not None:
                iv_rank = iv_rank * 100
                if symbol.startswith('/'):
                    self.logger.info(f"🔍 Debug {symbol} merge: after *100 = {iv_rank}")
            iv_index = self._safe_float(analytics.get('implied-volatility-index'))
            iv_5d_change = self._safe_float(analytics.get('implied-volatility-index-5-day-change'))
            historical_vol_30d = self._safe_float(analytics.get('historical-volatility-30-day'))
            beta = self._safe_float(analytics.get('beta'))
            liquidity_rank = self._safe_float(analytics.get('liquidity-rank'))
            
            # Extract pricing data - try multiple field names
            last_price = None
            bid_price = None
            ask_price = None
            volume = None
            
            if pricing:
                # Try common pricing field names
                last_price = self._safe_float(
                    pricing.get('last') or 
                    pricing.get('mark') or 
                    pricing.get('last-price') or
                    pricing.get('mark-price')
                )
                bid_price = self._safe_float(pricing.get('bid') or pricing.get('bid-price'))
                ask_price = self._safe_float(pricing.get('ask') or pricing.get('ask-price'))
                volume = self._safe_int(pricing.get('volume'))
            
            # Determine data source
            has_analytics = bool(analytics)
            has_pricing = bool(pricing)
            
            if has_analytics and has_pricing:
                data_source = 'tastytrade_combined'
            elif has_analytics:
                data_source = 'tastytrade_analytics_only'
            elif has_pricing:
                data_source = 'tastytrade_pricing_only'
            else:
                data_source = 'no_data'
            
            # Create MarketDataPoint
            market_data = MarketDataPoint(
                symbol=symbol,
                timestamp=datetime.now(),
                last_price=last_price,
                bid_price=bid_price,
                ask_price=ask_price,
                volume=volume,
                iv_rank=iv_rank,
                iv_index=iv_index,
                iv_5d_change=iv_5d_change,
                historical_vol_30d=historical_vol_30d,
                beta=beta,
                liquidity_rank=liquidity_rank,
                data_source=data_source
            )
            
            results[symbol] = market_data
            
        self.logger.info(f"🔗 Merged data for {len(results)} symbols: "
                        f"{len([r for r in results.values() if r.data_source == 'tastytrade_combined'])} combined, "
                        f"{len([r for r in results.values() if r.data_source == 'tastytrade_analytics_only'])} analytics-only, "
                        f"{len([r for r in results.values() if r.data_source == 'tastytrade_pricing_only'])} pricing-only")
        
        return results
    
    def _group_symbols_by_type(self, symbols: List[str]) -> Dict[str, List[str]]:
        """Group symbols by instrument type for appropriate API calls"""
        groups = {
            'futures': [],
            'equities': [],
            'cryptocurrencies': []
        }
        
        for symbol in symbols:
            if symbol.startswith('/'):
                # Futures contracts start with '/' (includes /BTC, /ETH, /ZB, etc.)
                groups['futures'].append(symbol)
            elif '/' in symbol and len(symbol.split('/')) == 2:
                # Cryptocurrencies format: BTC/USD, ETH/USD
                groups['cryptocurrencies'].append(symbol)
            else:
                # Default to equities for regular symbols
                groups['equities'].append(symbol)
        
        # Log the distribution
        total = len(symbols)
        self.logger.info(f"📊 Symbol distribution: {len(groups['futures'])} futures, "
                        f"{len(groups['equities'])} equities, {len(groups['cryptocurrencies'])} crypto out of {total}")
        
        return groups
    
    def _fetch_by_instrument_type(self, instrument_type: str, symbols: List[str]) -> Dict[str, MarketDataPoint]:
        """Fetch market data for specific instrument type using appropriate API endpoint"""
        results = {}
        
        if not symbols:
            return results
            
        headers = {
            'Authorization': self.tracker.tasty_client.session_token,
            'Content-Type': 'application/json'
        }
        
        try:
            if instrument_type == 'futures':
                results = self._fetch_futures(symbols, headers)
            elif instrument_type == 'equities':
                results = self._fetch_equities(symbols, headers)
            elif instrument_type == 'cryptocurrencies':
                results = self._fetch_cryptocurrencies(symbols, headers)
            else:
                self.logger.warning(f"⚠️ Unknown instrument type: {instrument_type}")
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching {instrument_type} data: {e}")
            import traceback
            self.logger.error(f"❌ Traceback: {traceback.format_exc()}")
        
        return results
    
    def _fetch_futures(self, symbols: List[str], headers: Dict[str, str]) -> Dict[str, MarketDataPoint]:
        """Fetch futures data using /instruments/futures endpoint"""
        results = {}
        
        # Try multiple API approaches for futures
        # Approach 1: symbol[] query parameter (current)
        params = [('symbol[]', symbol) for symbol in symbols]
        
        api_url = "https://api.tastyworks.com/instruments/futures"
        self.logger.info(f"📡 Making futures API request for {len(symbols)} symbols: {symbols[:5]}...")
        
        response = requests.get(api_url, params=params, headers=headers, timeout=10)
        self.logger.info(f"📡 Futures API Response: Status {response.status_code}, Content-Length: {len(response.content)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                self.logger.info(f"📡 Found {len(items)} futures items in API response")
                
                # If empty result, try fallback to market-metrics for futures
                if len(items) == 0:
                    self.logger.warning(f"📡 Futures API returned empty items. Trying market-metrics fallback...")
                    return self._fetch_futures_fallback(symbols, headers)
                
                for item in items:
                    symbol = item.get('symbol', '')
                    if symbol in symbols:
                        # Futures may have different field names
                        last_price = self._safe_float(item.get('mark-price') or item.get('settlement-price') or item.get('last-price'))
                        
                        market_data = MarketDataPoint(
                            symbol=symbol,
                            timestamp=datetime.now(),
                            last_price=last_price,
                            bid_price=self._safe_float(item.get('bid-price')),
                            ask_price=self._safe_float(item.get('ask-price')),
                            volume=self._safe_int(item.get('volume')),
                            iv_rank=None,  # Futures don't have IV metrics
                            iv_index=None,
                            iv_5d_change=None,
                            historical_vol_30d=None,
                            beta=None,
                            liquidity_rank=None,
                            data_source='tastytrade_futures_api'
                        )
                        results[symbol] = market_data
                        
                self.logger.info(f"📡 Successfully processed {len(results)} futures from API")
                
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Failed to parse futures API response: {e}")
        else:
            self.logger.warning(f"⚠️ Futures API request failed with status {response.status_code}: {response.text[:200]}")
            # Try fallback approach
            return self._fetch_futures_fallback(symbols, headers)
        
        return results
    
    def _fetch_futures_fallback(self, symbols: List[str], headers: Dict[str, str]) -> Dict[str, MarketDataPoint]:
        """Fallback: Try to fetch futures using market-metrics API"""
        results = {}
        
        # Some futures might work with market-metrics API
        symbols_param = ','.join(symbols)
        api_url = "https://api.tastyworks.com/market-metrics"
        
        self.logger.info(f"📡 Trying futures fallback via market-metrics for {len(symbols)} symbols...")
        
        response = requests.get(api_url, params={'symbols': symbols_param}, headers=headers, timeout=10)
        self.logger.info(f"📡 Futures Fallback Response: Status {response.status_code}, Content-Length: {len(response.content)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                self.logger.info(f"📡 Found {len(items)} futures items in fallback response")
                
                for item in items:
                    symbol = item.get('symbol', '')
                    if symbol in symbols:
                        market_data_raw = item.get('market-data', {})
                        last_price = self._safe_float(market_data_raw.get('last-price'))
                        
                        # Debug: Log the actual structure for futures
                        self.logger.info(f"📊 Futures item structure for {symbol}: {list(item.keys())}")
                        self.logger.info(f"📊 Market data fields: {list(market_data_raw.keys()) if market_data_raw else 'No market-data'}")
                        if not market_data_raw or last_price is None:
                            # Try alternative field names for futures
                            alt_price = self._safe_float(
                                item.get('last-price') or 
                                item.get('settlement-price') or 
                                item.get('mark-price') or
                                item.get('price')
                            )
                            self.logger.info(f"📊 Alternative price fields for {symbol}: last={item.get('last-price')}, settlement={item.get('settlement-price')}, mark={item.get('mark-price')}")
                            if alt_price:
                                last_price = alt_price
                        
                        market_data = MarketDataPoint(
                            symbol=symbol,
                            timestamp=datetime.now(),
                            last_price=last_price,
                            bid_price=self._safe_float(market_data_raw.get('bid-price')),
                            ask_price=self._safe_float(market_data_raw.get('ask-price')),
                            volume=self._safe_int(market_data_raw.get('volume')),
                            iv_rank=None,  # Futures don't have IV metrics
                            iv_index=None,
                            iv_5d_change=None,
                            historical_vol_30d=None,
                            beta=None,
                            liquidity_rank=None,
                            data_source='tastytrade_futures_fallback'
                        )
                        results[symbol] = market_data
                
                self.logger.info(f"📡 Successfully processed {len(results)} futures from fallback")
                
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Failed to parse futures fallback response: {e}")
        else:
            self.logger.warning(f"⚠️ Futures fallback failed with status {response.status_code}")
        
        return results
    
    def _fetch_equities(self, symbols: List[str], headers: Dict[str, str]) -> Dict[str, MarketDataPoint]:
        """Fetch equities data using /market-metrics endpoint (existing logic)"""
        results = {}
        
        symbols_param = ','.join(symbols)
        api_url = "https://api.tastyworks.com/market-metrics"
        
        self.logger.info(f"📡 Making equities API request for {len(symbols)} symbols: {symbols[:5]}...")
        
        response = requests.get(api_url, params={'symbols': symbols_param}, headers=headers, timeout=10)
        self.logger.info(f"📡 Equities API Response: Status {response.status_code}, Content-Length: {len(response.content)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                self.logger.info(f"📡 Found {len(items)} equity items in API response")
                
                for item in items:
                    symbol = item.get('symbol', '')
                    if symbol in symbols:
                        market_data_raw = item.get('market-data', {})
                        last_price = self._safe_float(market_data_raw.get('last-price'))
                        
                        # Debug: Log equity data structure for first few symbols
                        if len(results) < 3:
                            self.logger.info(f"📊 Equity {symbol} structure: {list(item.keys())}")
                            self.logger.info(f"📊 Equity {symbol} market-data: {list(market_data_raw.keys()) if market_data_raw else 'No market-data'}")
                            if market_data_raw:
                                self.logger.info(f"📊 Equity {symbol} price fields: last-price={market_data_raw.get('last-price')}")
                        
                        # Extract and convert IV rank from decimal to percentage
                        iv_rank = self._safe_float(item.get('implied-volatility-index-rank'))
                        if iv_rank is not None:
                            iv_rank = iv_rank * 100
                        
                        market_data = MarketDataPoint(
                            symbol=symbol,
                            timestamp=datetime.now(),
                            last_price=last_price,
                            bid_price=self._safe_float(market_data_raw.get('bid-price')),
                            ask_price=self._safe_float(market_data_raw.get('ask-price')),
                            volume=self._safe_int(market_data_raw.get('volume')),
                            iv_rank=iv_rank,
                            iv_index=self._safe_float(item.get('implied-volatility-index')),
                            iv_5d_change=self._safe_float(item.get('implied-volatility-index-5-day-change')),
                            historical_vol_30d=self._safe_float(item.get('historical-volatility-30-day')),
                            beta=self._safe_float(item.get('beta')),
                            liquidity_rank=self._safe_float(item.get('liquidity-rank')),
                            data_source='tastytrade_api'
                        )
                        results[symbol] = market_data
                
                self.logger.info(f"📡 Successfully processed {len(results)} equities from API")
                
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Failed to parse equities API response: {e}")
        else:
            self.logger.warning(f"⚠️ Equities API request failed with status {response.status_code}: {response.text[:200]}")
        
        return results
    
    def _fetch_cryptocurrencies(self, symbols: List[str], headers: Dict[str, str]) -> Dict[str, MarketDataPoint]:
        """Fetch cryptocurrency data using /instruments/cryptocurrencies endpoint"""
        results = {}
        
        # Build query parameters for crypto API
        params = [('symbol[]', symbol) for symbol in symbols]
        
        api_url = "https://api.tastyworks.com/instruments/cryptocurrencies"
        self.logger.info(f"📡 Making crypto API request for {len(symbols)} symbols: {symbols[:5]}...")
        
        response = requests.get(api_url, params=params, headers=headers, timeout=10)
        self.logger.info(f"📡 Crypto API Response: Status {response.status_code}, Content-Length: {len(response.content)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                self.logger.info(f"📡 Found {len(items)} crypto items in API response")
                
                for item in items:
                    symbol = item.get('symbol', '')
                    if symbol in symbols:
                        last_price = self._safe_float(item.get('mark-price') or item.get('last-price'))
                        
                        market_data = MarketDataPoint(
                            symbol=symbol,
                            timestamp=datetime.now(),
                            last_price=last_price,
                            bid_price=self._safe_float(item.get('bid-price')),
                            ask_price=self._safe_float(item.get('ask-price')),
                            volume=self._safe_int(item.get('volume')),
                            iv_rank=None,  # Crypto doesn't have IV metrics
                            iv_index=None,
                            iv_5d_change=None,
                            historical_vol_30d=None,
                            beta=None,
                            liquidity_rank=None,
                            data_source='tastytrade_crypto_api'
                        )
                        results[symbol] = market_data
                
                self.logger.info(f"📡 Successfully processed {len(results)} cryptocurrencies from API")
                
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Failed to parse crypto API response: {e}")
        else:
            self.logger.warning(f"⚠️ Crypto API request failed with status {response.status_code}: {response.text[:200]}")
        
        return results
    
    def _store_in_caches(self, data: MarketDataPoint):
        """Store data in both memory and database caches"""
        # Store in memory cache
        self.memory_cache[data.symbol] = data
        
        # Store in database
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO market_data_cache (
                        symbol, timestamp, last_price, bid_price, ask_price, volume,
                        iv_rank, iv_index, iv_5d_change, historical_vol_30d, beta,
                        liquidity_rank, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data.symbol, data.timestamp.isoformat(), data.last_price,
                    data.bid_price, data.ask_price, data.volume, data.iv_rank,
                    data.iv_index, data.iv_5d_change, data.historical_vol_30d,
                    data.beta, data.liquidity_rank, data.data_source
                ))
                
        except Exception as e:
            self.logger.error(f"❌ Error storing data in database: {e}")
    
    def store_position_snapshot(self, account_number: str, positions: List[Dict]) -> int:
        """Store position snapshot in database"""
        try:
            # Calculate summary metrics
            total_notional = sum(pos.get('notional_value', 0) for pos in positions)
            total_delta = sum(pos.get('position_delta', 0) for pos in positions)
            net_liq_deployed = sum(pos.get('net_liq', 0) for pos in positions)
            
            positions_json = json.dumps(positions)
            timestamp = datetime.now()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO position_snapshots (
                        account_number, timestamp, positions_json, 
                        total_notional, total_delta, net_liq_deployed
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (account_number, timestamp.isoformat(), positions_json,
                      total_notional, total_delta, net_liq_deployed))
                
                snapshot_id = cursor.lastrowid
                self.logger.info(f"📸 Stored position snapshot {snapshot_id} for account {account_number}")
                return snapshot_id
                
        except Exception as e:
            self.logger.error(f"❌ Error storing position snapshot: {e}")
            return -1
    
    def get_latest_position_snapshot(self, account_number: str, max_age_minutes: int = 5) -> Optional[PositionSnapshot]:
        """Get latest position snapshot if within max age"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=max_age_minutes)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM position_snapshots 
                    WHERE account_number = ? AND timestamp >= ?
                    ORDER BY timestamp DESC LIMIT 1
                """, (account_number, cutoff_time))
                
                row = cursor.fetchone()
                if row:
                    return PositionSnapshot(
                        snapshot_id=row['snapshot_id'],
                        account_number=row['account_number'],
                        timestamp=datetime.fromisoformat(row['timestamp']),
                        positions_json=row['positions_json'],
                        total_notional=row['total_notional'],
                        total_delta=row['total_delta'],
                        net_liq_deployed=row['net_liq_deployed']
                    )
                    
        except Exception as e:
            self.logger.error(f"❌ Error reading position snapshot: {e}")
        
        return None
    
    def cleanup_old_data(self, days_to_keep: int = 7):
        """Clean up old cached data to manage database size"""
        try:
            cutoff_time = datetime.now() - timedelta(days=days_to_keep)
            
            with sqlite3.connect(self.db_path) as conn:
                # Clean market data cache
                cursor = conn.execute("""
                    DELETE FROM market_data_cache WHERE timestamp < ?
                """, (cutoff_time,))
                market_deleted = cursor.rowcount
                
                # Clean position snapshots (keep more - 30 days)
                position_cutoff = datetime.now() - timedelta(days=30)
                cursor = conn.execute("""
                    DELETE FROM position_snapshots WHERE timestamp < ?
                """, (position_cutoff,))
                position_deleted = cursor.rowcount
                
                # Clean account balances
                cursor = conn.execute("""
                    DELETE FROM account_balances WHERE timestamp < ?
                """, (cutoff_time,))
                balance_deleted = cursor.rowcount
                
                self.logger.info(f"🧹 Cleaned up old data: {market_deleted} market data, "
                               f"{position_deleted} position snapshots, {balance_deleted} balance records")
                
        except Exception as e:
            self.logger.error(f"❌ Error cleaning up old data: {e}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                stats = {}
                
                # Market data cache stats
                cursor = conn.execute("SELECT COUNT(*) FROM market_data_cache")
                stats['market_data_count'] = cursor.fetchone()[0]
                
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM market_data_cache 
                    WHERE timestamp >= datetime('now', '-1 hour')
                """)
                stats['recent_market_data'] = cursor.fetchone()[0]
                
                # Position snapshot stats
                cursor = conn.execute("SELECT COUNT(*) FROM position_snapshots")
                stats['position_snapshots'] = cursor.fetchone()[0]
                
                # Memory cache stats
                stats['memory_cache_size'] = len(self.memory_cache)
                
                return stats
                
        except Exception as e:
            self.logger.error(f"❌ Error getting cache stats: {e}")
            return {}
    
    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Safely convert value to float"""
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _safe_int(value) -> Optional[int]:
        """Safely convert value to int"""
        if value is None or value == '':
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None