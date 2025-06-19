#!/usr/bin/env python3
"""
Enhanced Position Storage with Strategy Tracking
Stores static position attributes and calculates dynamic attributes on-demand
"""

import sqlite3
import json
import time
import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict

class PositionStrategyType(Enum):
    """Known position strategy types"""
    PUT_CREDIT_SPREAD = "put_credit_spread"
    CALL_CREDIT_SPREAD = "call_credit_spread"
    PUT_DEBIT_SPREAD = "put_debit_spread"
    CALL_DEBIT_SPREAD = "call_debit_spread"
    IRON_CONDOR = "iron_condor"
    IRON_BUTTERFLY = "iron_butterfly"
    STRADDLE = "straddle"
    STRANGLE = "strangle"
    COVERED_CALL = "covered_call"
    CASH_SECURED_PUT = "cash_secured_put"
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    SHORT_CALL = "short_call"
    SHORT_PUT = "short_put"
    SINGLE_POSITION = "single_position"
    UNKNOWN = "unknown"

@dataclass
class EnhancedPosition:
    """Enhanced position with static and dynamic attributes"""
    # Static attributes (stored)
    position_key: str
    account_number: str
    symbol: str
    underlying_symbol: str
    instrument_type: str
    asset_category: str  # equity, equity_option
    quantity: int
    
    # Option-specific static attributes
    strike_price: Optional[float] = None
    expiration_date: Optional[str] = None
    option_type: Optional[str] = None  # CALL, PUT
    
    # Strategy attributes
    strategy_id: Optional[str] = None
    strategy_type: Optional[str] = None
    strategy_role: Optional[str] = None  # long_leg, short_leg, protective, etc.
    
    # Classification
    sector: Optional[str] = None
    exclude_from_rebalancing: bool = False
    
    # Dynamic attributes (calculated)
    delta: Optional[float] = None
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    dte: Optional[int] = None
    strategy_category: Optional[str] = None  # bullish/bearish/neutral
    duration_category: Optional[str] = None  # 0-7_dte, 8-21_dte, etc.

class EnhancedStrategyPositionStorage:
    """Storage system for enhanced position tracking with strategy awareness"""
    
    def __init__(self, db_path: str = "positions_strategy_enhanced.db", 
                 sector_mappings_file: str = "sector_mappings.json"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.cache_ttl = 60  # seconds
        self._allocation_cache = {}
        self._cache_timestamp = 0
        self._init_database()
        
        # Load sector mappings
        self.sector_mappings = self._load_sector_mappings(sector_mappings_file)
        
    def _init_database(self):
        """Initialize database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Positions enhanced table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions_enhanced (
                    position_key TEXT PRIMARY KEY,
                    account_number TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    underlying_symbol TEXT NOT NULL,
                    instrument_type TEXT NOT NULL,
                    asset_category TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    strike_price REAL,
                    expiration_date TEXT,
                    option_type TEXT,
                    strategy_id TEXT,
                    strategy_type TEXT,
                    strategy_role TEXT,
                    sector TEXT,
                    exclude_from_rebalancing INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (strategy_id) REFERENCES strategy_groups(strategy_id)
                )
            """)
            
            # Strategy groups table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_groups (
                    strategy_id TEXT PRIMARY KEY,
                    strategy_type TEXT NOT NULL,
                    underlying_symbol TEXT NOT NULL,
                    account_number TEXT NOT NULL,
                    legs_count INTEGER NOT NULL,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            
            # Position chains table for detection results
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_chains (
                    chain_id TEXT PRIMARY KEY,
                    underlying_symbol TEXT NOT NULL,
                    account_number TEXT NOT NULL,
                    chain_type TEXT NOT NULL,
                    positions TEXT NOT NULL,
                    detected_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Allocation cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS allocation_cache (
                    cache_key TEXT PRIMARY KEY,
                    allocation_data TEXT NOT NULL,
                    created_timestamp INTEGER NOT NULL
                )
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_account ON positions_enhanced(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_underlying ON positions_enhanced(underlying_symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_strategy ON positions_enhanced(strategy_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategies_account ON strategy_groups(account_number)")
            
            conn.commit()
    
    def update_position_with_strategy(self, position: Dict[str, Any], 
                                    strategy_info: Optional[Dict[str, Any]] = None) -> bool:
        """Store or update position with static attributes only"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Extract static attributes
                static_data = {
                    'position_key': position['position_key'],
                    'account_number': position['account_number'],
                    'symbol': position['symbol'],
                    'underlying_symbol': position.get('underlying_symbol', position['symbol']),
                    'instrument_type': position['instrument_type'],
                    'asset_category': self._determine_asset_category(position),
                    'quantity': position['quantity'],
                    'strike_price': position.get('strike_price'),
                    'expiration_date': position.get('expiration_date'),
                    'option_type': position.get('option_type'),
                    'sector': self._get_sector_for_underlying(position.get('underlying_symbol', position.get('symbol'))),
                    'exclude_from_rebalancing': int(position.get('exclude_from_rebalancing', False))
                }
                
                # Add strategy info if provided
                if strategy_info:
                    static_data.update({
                        'strategy_id': strategy_info.get('strategy_id'),
                        'strategy_type': strategy_info.get('strategy_type'),
                        'strategy_role': strategy_info.get('strategy_role')
                    })
                
                # Upsert position
                cursor.execute("""
                    INSERT OR REPLACE INTO positions_enhanced 
                    (position_key, account_number, symbol, underlying_symbol, instrument_type,
                     asset_category, quantity, strike_price, expiration_date, option_type,
                     strategy_id, strategy_type, strategy_role, sector, exclude_from_rebalancing)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    static_data['position_key'], static_data['account_number'],
                    static_data['symbol'], static_data['underlying_symbol'],
                    static_data['instrument_type'], static_data['asset_category'],
                    static_data['quantity'], static_data['strike_price'],
                    static_data['expiration_date'], static_data['option_type'],
                    static_data.get('strategy_id'), static_data.get('strategy_type'),
                    static_data.get('strategy_role'), static_data['sector'],
                    static_data['exclude_from_rebalancing']
                ))
                
                conn.commit()
                self._invalidate_cache()
                return True
                
        except Exception as e:
            self.logger.error(f"Error updating position: {e}")
            return False
    
    def detect_and_store_strategy(self, positions: List[Dict[str, Any]], 
                                 chain_detector) -> List[Dict[str, Any]]:
        """Detect strategies using chain detector and store results"""
        try:
            # Group positions by underlying and account
            positions_by_key = defaultdict(list)
            for pos in positions:
                key = (pos['underlying_symbol'], pos['account_number'])
                positions_by_key[key].append(pos)
            
            detected_strategies = []
            
            for (underlying, account), position_group in positions_by_key.items():
                # Skip if too few positions for a strategy
                if len(position_group) < 2:
                    continue
                
                # Detect chains
                chains = chain_detector.detect_chains(position_group)
                
                for chain in chains:
                    if chain['chain_type'] != 'unknown':
                        strategy_id = f"{underlying}_{account}_{chain['chain_type']}_{int(time.time())}"
                        
                        # Store strategy group
                        self._store_strategy_group(strategy_id, chain, underlying, account)
                        
                        # Update positions with strategy info
                        for pos_key in chain['position_keys']:
                            pos = next((p for p in position_group if p['position_key'] == pos_key), None)
                            if pos:
                                strategy_info = {
                                    'strategy_id': strategy_id,
                                    'strategy_type': chain['chain_type'],
                                    'strategy_role': self._determine_position_role(pos, chain)
                                }
                                self.update_position_with_strategy(pos, strategy_info)
                        
                        detected_strategies.append({
                            'strategy_id': strategy_id,
                            'type': chain['chain_type'],
                            'underlying': underlying,
                            'positions': len(chain['position_keys'])
                        })
            
            return detected_strategies
            
        except Exception as e:
            self.logger.error(f"Error detecting strategies: {e}")
            return []
    
    def get_positions_with_dynamic_data(self, account_numbers: Optional[List[str]] = None,
                                      live_positions: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get positions with static data from DB and dynamic data calculated on-demand"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Build query
                query = "SELECT * FROM positions_enhanced"
                params = []
                
                if account_numbers:
                    placeholders = ','.join(['?' for _ in account_numbers])
                    query += f" WHERE account_number IN ({placeholders})"
                    params = account_numbers
                
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                stored_positions = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # Merge with live data and calculate dynamic attributes
            enhanced_positions = []
            
            for stored_pos in stored_positions:
                # Get live data if available
                live_data = live_positions.get(stored_pos['position_key'], {}) if live_positions else {}
                
                # Create enhanced position
                enhanced_pos = stored_pos.copy()
                
                # Add live data
                enhanced_pos['delta'] = live_data.get('delta', 0)
                enhanced_pos['market_value'] = live_data.get('market_value', 0)
                enhanced_pos['cost_basis'] = live_data.get('cost_basis', 0)
                
                # Calculate dynamic attributes
                enhanced_pos['dte'] = self._calculate_dte(stored_pos.get('expiration_date'))
                enhanced_pos['strategy_category'] = self._calculate_strategy_category(
                    enhanced_pos, live_data.get('delta', 0)
                )
                enhanced_pos['duration_category'] = self._calculate_duration_category(
                    enhanced_pos['dte']
                )
                
                enhanced_positions.append(enhanced_pos)
            
            return enhanced_positions
            
        except Exception as e:
            self.logger.error(f"Error getting positions with dynamic data: {e}")
            return []
    
    def calculate_allocation_summary(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate allocation summary with caching for performance"""
        # Check cache
        cache_key = "allocation_summary"
        if self._is_cache_valid():
            cached = self._get_cached_allocation(cache_key)
            if cached:
                return cached
        
        # Calculate allocations
        total_value = sum(p['market_value'] for p in positions 
                         if not p.get('exclude_from_rebalancing', False))
        
        if total_value == 0:
            return {
                'asset_allocation': {},
                'strategy_allocation': {},
                'duration_allocation': {},
                'strategy_type_allocation': {},
                'sector_allocation': {}
            }
        
        allocations = defaultdict(lambda: defaultdict(float))
        
        for pos in positions:
            if pos.get('exclude_from_rebalancing', False):
                continue
            
            value = pos['market_value']
            pct = (value / total_value) * 100
            
            # Asset allocation
            allocations['asset_allocation'][pos['asset_category']] += pct
            
            # Strategy allocation (bullish/bearish/neutral)
            allocations['strategy_allocation'][pos['strategy_category']] += pct
            
            # Duration allocation
            allocations['duration_allocation'][pos['duration_category']] += pct
            
            # Strategy type allocation
            strategy_type = pos.get('strategy_type', 'single_position')
            allocations['strategy_type_allocation'][strategy_type] += pct
            
            # Sector allocation
            sector = pos.get('sector', 'Other')
            allocations['sector_allocation'][sector] += pct
        
        result = dict(allocations)
        
        # Cache result
        self._cache_allocation(cache_key, result)
        
        return result
    
    def _determine_asset_category(self, position: Dict[str, Any]) -> str:
        """Determine asset category from position data"""
        instrument_type = position.get('instrument_type', '').upper()
        if 'EQUITY' in instrument_type and 'OPTION' not in instrument_type:
            return 'equity'
        elif 'OPTION' in instrument_type:
            return 'equity_option'
        else:
            return 'other'
    
    def _calculate_dte(self, expiration_date: Optional[str]) -> Optional[int]:
        """Calculate days to expiration"""
        if not expiration_date:
            return None
        
        try:
            exp_date = datetime.strptime(expiration_date, '%Y-%m-%d').date()
            today = date.today()
            return (exp_date - today).days
        except:
            return None
    
    def _calculate_strategy_category(self, position: Dict[str, Any], delta: float) -> str:
        """Calculate strategy category based on position type and current delta"""
        if position['asset_category'] == 'equity':
            return 'bullish' if position['quantity'] > 0 else 'bearish'
        
        # For options, consider strategy type and delta
        strategy_type = position.get('strategy_type', '')
        
        # Known bullish strategies
        if strategy_type in ['put_credit_spread', 'call_debit_spread', 'cash_secured_put']:
            return 'bullish'
        
        # Known bearish strategies
        elif strategy_type in ['call_credit_spread', 'put_debit_spread']:
            return 'bearish'
        
        # Known neutral strategies
        elif strategy_type in ['iron_condor', 'iron_butterfly', 'straddle', 'strangle']:
            return 'neutral'
        
        # For single options, use delta
        elif position['option_type'] == 'CALL':
            if position['quantity'] > 0:
                return 'bullish' if delta > 0.3 else 'neutral'
            else:
                return 'bearish' if delta < -0.3 else 'neutral'
        
        elif position['option_type'] == 'PUT':
            if position['quantity'] > 0:
                return 'bearish' if delta < -0.3 else 'neutral'
            else:
                return 'bullish' if delta > 0.3 else 'neutral'
        
        return 'neutral'
    
    def _calculate_duration_category(self, dte: Optional[int]) -> str:
        """Calculate duration category based on DTE"""
        if dte is None:
            return 'no_expiration'
        elif dte < 0:
            return 'expired'
        elif dte <= 7:
            return '0-7_dte'
        elif dte <= 21:
            return '8-21_dte'
        elif dte <= 45:
            return '22-45_dte'
        else:
            return '45+_dte'
    
    def _store_strategy_group(self, strategy_id: str, chain: Dict[str, Any],
                            underlying: str, account: str):
        """Store detected strategy group"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                metadata = json.dumps({
                    'detection_confidence': chain.get('confidence', 0),
                    'positions': chain.get('position_keys', []),
                    'details': chain.get('details', {})
                })
                
                cursor.execute("""
                    INSERT OR REPLACE INTO strategy_groups
                    (strategy_id, strategy_type, underlying_symbol, account_number, 
                     legs_count, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    strategy_id, chain['chain_type'], underlying, account,
                    len(chain.get('position_keys', [])), metadata
                ))
                
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"Error storing strategy group: {e}")
    
    def _determine_position_role(self, position: Dict[str, Any], chain: Dict[str, Any]) -> str:
        """Determine position's role in the strategy"""
        # This would be more sophisticated based on chain type
        if position['quantity'] > 0:
            return 'long_leg'
        else:
            return 'short_leg'
    
    def _invalidate_cache(self):
        """Invalidate allocation cache"""
        self._allocation_cache = {}
        self._cache_timestamp = 0
    
    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        return (time.time() - self._cache_timestamp) < self.cache_ttl
    
    def _get_cached_allocation(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached allocation data"""
        return self._allocation_cache.get(cache_key)
    
    def _cache_allocation(self, cache_key: str, data: Dict[str, Any]):
        """Cache allocation data"""
        self._allocation_cache[cache_key] = data
        self._cache_timestamp = time.time()
    
    def get_strategy_summary(self, account_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get summary of all detected strategies"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Build query
                query = """
                    SELECT sg.*, COUNT(pe.position_key) as position_count
                    FROM strategy_groups sg
                    LEFT JOIN positions_enhanced pe ON sg.strategy_id = pe.strategy_id
                """
                params = []
                
                if account_numbers:
                    placeholders = ','.join(['?' for _ in account_numbers])
                    query += f" WHERE sg.account_number IN ({placeholders})"
                    params = account_numbers
                
                query += " GROUP BY sg.strategy_id ORDER BY sg.created_date DESC"
                
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                strategies = [dict(zip(columns, row)) for row in cursor.fetchall()]
                
                # Parse metadata
                for strategy in strategies:
                    if strategy.get('metadata'):
                        strategy['metadata'] = json.loads(strategy['metadata'])
                
                return {
                    'total_strategies': len(strategies),
                    'strategies': strategies,
                    'by_type': self._group_strategies_by_type(strategies),
                    'by_underlying': self._group_strategies_by_underlying(strategies)
                }
                
        except Exception as e:
            self.logger.error(f"Error getting strategy summary: {e}")
            return {'total_strategies': 0, 'strategies': []}
    
    def _group_strategies_by_type(self, strategies: List[Dict[str, Any]]) -> Dict[str, int]:
        """Group strategies by type"""
        by_type = defaultdict(int)
        for strategy in strategies:
            by_type[strategy['strategy_type']] += 1
        return dict(by_type)
    
    def _group_strategies_by_underlying(self, strategies: List[Dict[str, Any]]) -> Dict[str, int]:
        """Group strategies by underlying"""
        by_underlying = defaultdict(int)
        for strategy in strategies:
            by_underlying[strategy['underlying_symbol']] += 1
        return dict(by_underlying)
    
    def _load_sector_mappings(self, file_path: str) -> Dict[str, str]:
        """Load sector mappings from JSON file"""
        try:
            with open(file_path, 'r') as f:
                mappings_data = json.load(f)
            
            # Extract just the sector for each symbol
            sector_map = {}
            for symbol, data in mappings_data.items():
                if isinstance(data, dict) and 'sector' in data:
                    sector_map[symbol] = data['sector']
            
            self.logger.info(f"Loaded sector mappings for {len(sector_map)} symbols")
            return sector_map
            
        except FileNotFoundError:
            self.logger.warning(f"Sector mappings file not found: {file_path}")
            return {}
        except Exception as e:
            self.logger.error(f"Error loading sector mappings: {e}")
            return {}
    
    def _get_sector_for_underlying(self, underlying_symbol: str) -> str:
        """Get sector for an underlying symbol"""
        if not underlying_symbol:
            return 'Other'
        
        # Clean the symbol (remove any option-specific parts)
        clean_symbol = underlying_symbol.upper().strip()
        
        # Look up in sector mappings
        return self.sector_mappings.get(clean_symbol, 'Other')