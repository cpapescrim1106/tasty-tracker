#!/usr/bin/env python3
"""
TastyTracker Market Data Capture
Captures market regime context for trade entries (SPX, VIX, rates, etc.)
"""

import os
import logging
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import time

# Tastytrade imports
from tastytrade import Session
from tastytrade.market_data import get_market_data_by_type

@dataclass
class MarketRegimeData:
    """Complete market regime snapshot"""
    timestamp: datetime
    
    # Core market indicators
    spx_price: Optional[float] = None
    spx_change_pct: Optional[float] = None
    vix_level: Optional[float] = None
    vix_change_pct: Optional[float] = None
    
    # Interest rates
    ten_year_yield: Optional[float] = None
    two_year_yield: Optional[float] = None
    yield_curve_spread: Optional[float] = None
    fed_funds_rate: Optional[float] = None
    
    # Currency & commodities
    dxy_level: Optional[float] = None  # Dollar Index
    gold_price: Optional[float] = None
    oil_price: Optional[float] = None
    
    # Market breadth
    spy_volume: Optional[int] = None
    qqq_volume: Optional[int] = None
    advance_decline_ratio: Optional[float] = None
    
    # Volatility term structure
    vix9d: Optional[float] = None  # 9-day VIX
    vix3m: Optional[float] = None  # 3-month VIX
    vix_contango: Optional[float] = None  # VIX term structure slope
    
    # Market regime classification
    volatility_regime: str = ""  # "low", "medium", "high", "extreme"
    trend_regime: str = ""      # "bullish", "bearish", "sideways"
    rate_regime: str = ""       # "rising", "falling", "stable"
    overall_regime: str = ""    # "risk_on", "risk_off", "transition"
    
    # Risk indicators
    credit_spreads: Optional[float] = None
    put_call_ratio: Optional[float] = None
    fear_greed_index: Optional[float] = None

@dataclass  
class SectorRotationData:
    """Sector performance snapshot"""
    timestamp: datetime
    technology: Optional[float] = None  # XLK
    financials: Optional[float] = None  # XLF
    healthcare: Optional[float] = None  # XLV
    energy: Optional[float] = None      # XLE
    industrials: Optional[float] = None # XLI
    utilities: Optional[float] = None   # XLU
    consumer_disc: Optional[float] = None # XLY
    consumer_staples: Optional[float] = None # XLP
    materials: Optional[float] = None   # XLB
    real_estate: Optional[float] = None # XLRE
    communication: Optional[float] = None # XLC

class MarketDataCapture:
    """Market regime and context data capture system"""
    
    def __init__(self, tasty_client: Session):
        self.tasty_client = tasty_client
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://api.tastyworks.com"
        
        # Market data symbols mapping
        self.core_symbols = {
            'SPX': '$SPX.X',      # S&P 500 Index
            'VIX': '$VIX.X',      # VIX Volatility Index
            'TNX': '$TNX.X',      # 10-Year Treasury
            'IRX': '$IRX.X',      # 3-Month Treasury
            'TYX': '$TYX.X',      # 30-Year Treasury
            'DXY': '$DXY.X',      # Dollar Index
            'SPY': 'SPY',         # SPY ETF
            'QQQ': 'QQQ',         # QQQ ETF
            'GLD': 'GLD',         # Gold ETF
            'USO': 'USO',         # Oil ETF
        }
        
        # VIX term structure symbols
        self.vix_symbols = {
            'VIX': '$VIX.X',
            'VIX9D': '$VIX9D.X',
            'VIX3M': '$VIX3M.X',
            'VIX6M': '$VIX6M.X'
        }
        
        # Sector ETF symbols
        self.sector_symbols = {
            'XLK': 'XLK',  # Technology
            'XLF': 'XLF',  # Financials
            'XLV': 'XLV',  # Healthcare
            'XLE': 'XLE',  # Energy
            'XLI': 'XLI',  # Industrials
            'XLU': 'XLU',  # Utilities
            'XLY': 'XLY',  # Consumer Discretionary
            'XLP': 'XLP',  # Consumer Staples
            'XLB': 'XLB',  # Materials
            'XLRE': 'XLRE', # Real Estate
            'XLC': 'XLC'   # Communication
        }
        
        # Cache for market data
        self.market_cache = {}
        self.cache_duration = 60  # 1 minute cache
        
        # Regime thresholds
        self.volatility_thresholds = {
            'low': 15.0,      # VIX < 15
            'medium': 25.0,   # VIX 15-25
            'high': 35.0,     # VIX 25-35
            'extreme': 50.0   # VIX > 35
        }
    
    def fetch_market_data_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch market data for multiple symbols using TastyTrade API"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Build symbol list for API call
            symbol_params = ','.join(symbols)
            
            response = requests.get(
                f"{self.base_url}/market-data/by-type",
                headers=headers,
                params={
                    'symbols': symbol_params,
                    'types': 'quote,greeks,stats'
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                market_data = {}
                
                # Parse response data
                if 'data' in data and 'items' in data['data']:
                    for item in data['data']['items']:
                        symbol = item.get('symbol', '')
                        if symbol:
                            market_data[symbol] = item
                
                self.logger.info(f"✅ Fetched market data for {len(market_data)} symbols")
                return market_data
            else:
                self.logger.error(f"❌ Market data fetch failed: HTTP {response.status_code}")
                return {}
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching market data: {e}")
            return {}
    
    def get_current_market_regime(self) -> MarketRegimeData:
        """Capture complete current market regime snapshot"""
        try:
            self.logger.info("📊 Capturing market regime snapshot")
            
            # Collect all symbols to fetch
            all_symbols = list(self.core_symbols.values()) + list(self.vix_symbols.values())
            
            # Fetch market data
            market_data = self.fetch_market_data_batch(all_symbols)
            
            if not market_data:
                self.logger.warning("⚠️ No market data received, using placeholder values")
                return self._get_placeholder_regime()
            
            # Create regime data object
            regime = MarketRegimeData(timestamp=datetime.now())
            
            # Parse SPX data
            spx_data = market_data.get(self.core_symbols['SPX'], {})
            if spx_data:
                quote = spx_data.get('quote', {})
                regime.spx_price = quote.get('last', 0.0)
                regime.spx_change_pct = quote.get('change-percent', 0.0)
            
            # Parse VIX data
            vix_data = market_data.get(self.core_symbols['VIX'], {})
            if vix_data:
                quote = vix_data.get('quote', {})
                regime.vix_level = quote.get('last', 0.0)
                regime.vix_change_pct = quote.get('change-percent', 0.0)
            
            # Parse VIX term structure
            vix9d_data = market_data.get(self.vix_symbols['VIX9D'], {})
            if vix9d_data:
                quote = vix9d_data.get('quote', {})
                regime.vix9d = quote.get('last', 0.0)
            
            vix3m_data = market_data.get(self.vix_symbols['VIX3M'], {})
            if vix3m_data:
                quote = vix3m_data.get('quote', {})
                regime.vix3m = quote.get('last', 0.0)
            
            # Calculate VIX contango/backwardation
            if regime.vix_level and regime.vix3m:
                regime.vix_contango = ((regime.vix3m - regime.vix_level) / regime.vix_level) * 100
            
            # Parse Treasury yields
            tnx_data = market_data.get(self.core_symbols['TNX'], {})
            if tnx_data:
                quote = tnx_data.get('quote', {})
                regime.ten_year_yield = quote.get('last', 0.0)
            
            irx_data = market_data.get(self.core_symbols['IRX'], {})
            if irx_data:
                quote = irx_data.get('quote', {})
                regime.two_year_yield = quote.get('last', 0.0)
            
            # Calculate yield curve spread
            if regime.ten_year_yield and regime.two_year_yield:
                regime.yield_curve_spread = regime.ten_year_yield - regime.two_year_yield
            
            # Parse Dollar Index
            dxy_data = market_data.get(self.core_symbols['DXY'], {})
            if dxy_data:
                quote = dxy_data.get('quote', {})
                regime.dxy_level = quote.get('last', 0.0)
            
            # Parse ETF volumes
            spy_data = market_data.get(self.core_symbols['SPY'], {})
            if spy_data:
                quote = spy_data.get('quote', {})
                regime.spy_volume = quote.get('volume', 0)
            
            qqq_data = market_data.get(self.core_symbols['QQQ'], {})
            if qqq_data:
                quote = qqq_data.get('quote', {})
                regime.qqq_volume = quote.get('volume', 0)
            
            # Classify market regimes
            regime.volatility_regime = self._classify_volatility_regime(regime.vix_level)
            regime.trend_regime = self._classify_trend_regime(regime.spx_change_pct)
            regime.rate_regime = self._classify_rate_regime(regime.ten_year_yield)
            regime.overall_regime = self._classify_overall_regime(regime)
            
            self.logger.info(f"✅ Market regime captured: {regime.overall_regime} "
                           f"(VIX: {regime.vix_level:.1f}, SPX: {regime.spx_price:.0f})")
            
            return regime
            
        except Exception as e:
            self.logger.error(f"❌ Error capturing market regime: {e}")
            return self._get_placeholder_regime()
    
    def get_sector_rotation_snapshot(self) -> SectorRotationData:
        """Capture sector performance snapshot"""
        try:
            sector_symbols = list(self.sector_symbols.values())
            market_data = self.fetch_market_data_batch(sector_symbols)
            
            sector_data = SectorRotationData(timestamp=datetime.now())
            
            # Map sector ETF performance
            sector_mapping = {
                'XLK': 'technology',
                'XLF': 'financials', 
                'XLV': 'healthcare',
                'XLE': 'energy',
                'XLI': 'industrials',
                'XLU': 'utilities',
                'XLY': 'consumer_disc',
                'XLP': 'consumer_staples',
                'XLB': 'materials',
                'XLRE': 'real_estate',
                'XLC': 'communication'
            }
            
            for etf_symbol, sector_field in sector_mapping.items():
                etf_data = market_data.get(etf_symbol, {})
                if etf_data:
                    quote = etf_data.get('quote', {})
                    change_pct = quote.get('change-percent', 0.0)
                    setattr(sector_data, sector_field, change_pct)
            
            return sector_data
            
        except Exception as e:
            self.logger.error(f"❌ Error capturing sector rotation: {e}")
            return SectorRotationData(timestamp=datetime.now())
    
    def _classify_volatility_regime(self, vix_level: Optional[float]) -> str:
        """Classify volatility regime based on VIX level"""
        if not vix_level:
            return "unknown"
        
        if vix_level < self.volatility_thresholds['low']:
            return "low"
        elif vix_level < self.volatility_thresholds['medium']:
            return "medium"
        elif vix_level < self.volatility_thresholds['high']:
            return "high"
        else:
            return "extreme"
    
    def _classify_trend_regime(self, spx_change_pct: Optional[float]) -> str:
        """Classify trend regime based on SPX daily change"""
        if not spx_change_pct:
            return "unknown"
        
        if spx_change_pct > 1.0:
            return "bullish"
        elif spx_change_pct < -1.0:
            return "bearish"
        else:
            return "sideways"
    
    def _classify_rate_regime(self, ten_year_yield: Optional[float]) -> str:
        """Classify interest rate regime (simplified)"""
        if not ten_year_yield:
            return "unknown"
        
        # This is very simplified - in practice you'd compare to historical levels
        if ten_year_yield > 4.5:
            return "rising"
        elif ten_year_yield < 3.0:
            return "falling"
        else:
            return "stable"
    
    def _classify_overall_regime(self, regime: MarketRegimeData) -> str:
        """Classify overall market regime"""
        try:
            risk_factors = 0
            
            # Count risk factors
            if regime.vix_level and regime.vix_level > 25:
                risk_factors += 1
            
            if regime.spx_change_pct and regime.spx_change_pct < -1.0:
                risk_factors += 1
            
            if regime.yield_curve_spread and regime.yield_curve_spread < 0:
                risk_factors += 1  # Inverted yield curve
            
            if regime.vix_contango and regime.vix_contango < -10:
                risk_factors += 1  # VIX backwardation
            
            # Classify based on risk factor count
            if risk_factors >= 3:
                return "risk_off"
            elif risk_factors <= 1:
                return "risk_on"
            else:
                return "transition"
                
        except Exception as e:
            self.logger.error(f"Error classifying overall regime: {e}")
            return "unknown"
    
    def _get_placeholder_regime(self) -> MarketRegimeData:
        """Return placeholder regime data when API fails"""
        return MarketRegimeData(
            timestamp=datetime.now(),
            spx_price=4500.0,
            vix_level=18.0,
            ten_year_yield=4.2,
            dxy_level=103.0,
            volatility_regime="medium",
            trend_regime="sideways",
            rate_regime="stable",
            overall_regime="risk_on"
        )
    
    def save_market_snapshot(self, regime: MarketRegimeData, db_path: str = "trade_journal.db") -> bool:
        """Save market regime snapshot to database"""
        try:
            import sqlite3
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                regime_dict = asdict(regime)
                regime_dict['timestamp'] = regime.timestamp.isoformat()
                
                # Insert market snapshot
                columns = ', '.join(regime_dict.keys())
                placeholders = ', '.join([f':{key}' for key in regime_dict.keys()])
                
                cursor.execute(f'''
                    INSERT OR REPLACE INTO market_snapshots ({columns})
                    VALUES ({placeholders})
                ''', regime_dict)
                
                conn.commit()
                self.logger.info("✅ Market snapshot saved to database")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ Error saving market snapshot: {e}")
            return False
    
    def get_historical_regime(self, target_date: datetime, db_path: str = "trade_journal.db") -> Optional[MarketRegimeData]:
        """Retrieve historical market regime for a specific date"""
        try:
            import sqlite3
            
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Find closest market snapshot to target date
                cursor.execute('''
                    SELECT * FROM market_snapshots 
                    WHERE date(timestamp) = date(?)
                    ORDER BY abs(julianday(timestamp) - julianday(?))
                    LIMIT 1
                ''', (target_date.isoformat(), target_date.isoformat()))
                
                row = cursor.fetchone()
                if row:
                    regime_dict = dict(row)
                    regime_dict['timestamp'] = datetime.fromisoformat(regime_dict['timestamp'])
                    return MarketRegimeData(**regime_dict)
                
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error retrieving historical regime: {e}")
            return None
    
    def calculate_regime_statistics(self, start_date: datetime, end_date: datetime, 
                                  db_path: str = "trade_journal.db") -> Dict[str, Any]:
        """Calculate market regime statistics over a period"""
        try:
            import sqlite3
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT volatility_regime, trend_regime, overall_regime,
                           AVG(vix_level) as avg_vix, AVG(spx_price) as avg_spx
                    FROM market_snapshots
                    WHERE timestamp BETWEEN ? AND ?
                    GROUP BY volatility_regime, trend_regime, overall_regime
                ''', (start_date.isoformat(), end_date.isoformat()))
                
                results = cursor.fetchall()
                
                stats = {
                    'period_start': start_date.isoformat(),
                    'period_end': end_date.isoformat(),
                    'regime_breakdown': [],
                    'avg_vix': 0,
                    'avg_spx': 0
                }
                
                for row in results:
                    stats['regime_breakdown'].append({
                        'volatility_regime': row[0],
                        'trend_regime': row[1], 
                        'overall_regime': row[2],
                        'avg_vix': row[3],
                        'avg_spx': row[4]
                    })
                
                return stats
                
        except Exception as e:
            self.logger.error(f"❌ Error calculating regime statistics: {e}")
            return {}