#!/usr/bin/env python3
"""
Sector Classifier
Auto-expanding sector classification system using cached lookups and yfinance fallback
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import pandas as pd

class SectorClassifier:
    """Sector classification with self-expanding cache system"""
    
    def __init__(self, cache_file: str = "sector_mappings.json"):
        self.cache_file = cache_file
        self.logger = logging.getLogger(__name__)
        self.sector_cache = self._load_cache()
        
        # Cache expiry (refresh sector data after 30 days)
        self.cache_expiry_days = 30
        
        # Initialize futures mapping
        self.futures_mapping = self._init_futures_mapping()
        
        # Initialize cache if empty
        if not self.sector_cache:
            self.logger.info("🔄 Initializing sector cache from S&P 500...")
            self.initialize_cache_from_sp500()
    
    def get_symbol_sector(self, symbol: str) -> Dict[str, Any]:
        """
        Get sector information for a symbol with auto-expanding cache
        
        Returns:
            Dict with keys: sector, industry, last_updated, source
        """
        try:
            symbol = symbol.upper().strip()
            
            # Check cache first - if exists, use it (no expiry check for existing complete database)
            if symbol in self.sector_cache:
                cached_data = self.sector_cache[symbol]
                self.logger.debug(f"📊 Cache hit for {symbol}: {cached_data['sector']}")
                return cached_data
            
            # Check if it's a futures symbol (starts with /)
            if symbol.startswith('/'):
                futures_data = self._get_futures_sector(symbol)
                if futures_data:
                    # Cache the futures data
                    self.sector_cache[symbol] = futures_data
                    self._save_cache()
                    self.logger.info(f"✅ Mapped futures symbol {symbol}: {futures_data['sector']}")
                    return futures_data
            
            # Cache miss - fetch from yfinance for equity symbols
            self.logger.info(f"🔍 Fetching sector data for {symbol} from yfinance...")
            sector_data = self._fetch_from_yfinance(symbol)
            
            if sector_data:
                # Save to cache
                self.sector_cache[symbol] = sector_data
                self._save_cache()
                self.logger.info(f"✅ Cached sector data for {symbol}: {sector_data['sector']}")
                return sector_data
            else:
                # Return unknown if can't classify
                unknown_data = {
                    'sector': 'Unknown',
                    'industry': 'Unknown',
                    'last_updated': datetime.now().isoformat(),
                    'source': 'unknown'
                }
                self.logger.warning(f"⚠️ Could not classify {symbol}, returning Unknown")
                return unknown_data
                
        except Exception as e:
            self.logger.error(f"❌ Error getting sector for {symbol}: {e}")
            return {
                'sector': 'Unknown',
                'industry': 'Unknown', 
                'last_updated': datetime.now().isoformat(),
                'source': 'error'
            }
    
    def _fetch_from_yfinance(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch sector data from yfinance API"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            sector = info.get('sector', 'Unknown')
            industry = info.get('industry', 'Unknown')
            
            if sector and sector != 'Unknown':
                return {
                    'sector': sector,
                    'industry': industry,
                    'last_updated': datetime.now().isoformat(),
                    'source': 'yfinance'
                }
            
            return None
            
        except ImportError:
            self.logger.error("❌ yfinance not installed. Run: pip install yfinance")
            return None
        except Exception as e:
            self.logger.error(f"❌ yfinance error for {symbol}: {e}")
            return None
    
    def initialize_cache_from_sp500(self) -> None:
        """Initialize cache with S&P 500 companies from Wikipedia"""
        try:
            self.logger.info("🔄 Fetching S&P 500 data from Wikipedia...")
            
            # Get S&P 500 list from Wikipedia
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            tables = pd.read_html(url)
            sp500_df = tables[0]
            
            # Expected columns: Symbol, Security, GICS Sector, GICS Sub-Industry
            count = 0
            for _, row in sp500_df.iterrows():
                symbol = str(row.get('Symbol', '')).strip()
                sector = str(row.get('GICS Sector', '')).strip()
                industry = str(row.get('GICS Sub Industry', row.get('GICS Sub-Industry', ''))).strip()
                
                if symbol and sector and sector != 'nan':
                    self.sector_cache[symbol] = {
                        'sector': sector,
                        'industry': industry,
                        'last_updated': datetime.now().isoformat(),
                        'source': 'wikipedia_sp500'
                    }
                    count += 1
            
            # Save cache
            self._save_cache()
            self.logger.info(f"✅ Initialized cache with {count} S&P 500 companies")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize S&P 500 cache: {e}")
            # Create minimal cache with common stocks
            self._create_minimal_cache()
    
    def _create_minimal_cache(self) -> None:
        """Create minimal cache with most common stocks"""
        minimal_mapping = {
            'AAPL': {'sector': 'Technology', 'industry': 'Consumer Electronics'},
            'MSFT': {'sector': 'Technology', 'industry': 'Software'},
            'GOOGL': {'sector': 'Communication Services', 'industry': 'Internet Content & Information'},
            'AMZN': {'sector': 'Consumer Discretionary', 'industry': 'Internet & Direct Marketing Retail'},
            'TSLA': {'sector': 'Consumer Discretionary', 'industry': 'Auto Manufacturers'},
            'META': {'sector': 'Communication Services', 'industry': 'Interactive Media & Services'},
            'NVDA': {'sector': 'Technology', 'industry': 'Semiconductors'},
            'AMD': {'sector': 'Technology', 'industry': 'Semiconductors'},
            'INTC': {'sector': 'Technology', 'industry': 'Semiconductors'},
            'JPM': {'sector': 'Financials', 'industry': 'Banks'},
            'BAC': {'sector': 'Financials', 'industry': 'Banks'},
            'V': {'sector': 'Financials', 'industry': 'Credit Services'},
            'MA': {'sector': 'Financials', 'industry': 'Credit Services'},
            'SPY': {'sector': 'Broad Market', 'industry': 'Index Fund'},
            'QQQ': {'sector': 'Technology', 'industry': 'Index Fund'},
            'IWM': {'sector': 'Broad Market', 'industry': 'Index Fund'},
            'XLE': {'sector': 'Energy', 'industry': 'Index Fund'},
            'XLF': {'sector': 'Financials', 'industry': 'Index Fund'},
            'XLK': {'sector': 'Technology', 'industry': 'Index Fund'},
            'XLV': {'sector': 'Healthcare', 'industry': 'Index Fund'}
        }
        
        for symbol, data in minimal_mapping.items():
            self.sector_cache[symbol] = {
                'sector': data['sector'],
                'industry': data['industry'],
                'last_updated': datetime.now().isoformat(),
                'source': 'minimal_cache'
            }
        
        self._save_cache()
        self.logger.info(f"✅ Created minimal cache with {len(minimal_mapping)} symbols")
    
    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        """Load sector cache from JSON file"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                self.logger.info(f"📊 Loaded sector cache with {len(cache)} symbols")
                return cache
            else:
                self.logger.info("📁 No existing cache file found, starting fresh")
                return {}
        except Exception as e:
            self.logger.error(f"❌ Failed to load cache: {e}")
            return {}
    
    def _save_cache(self) -> None:
        """Save sector cache to JSON file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.sector_cache, f, indent=2)
            self.logger.debug(f"💾 Saved cache with {len(self.sector_cache)} symbols")
        except Exception as e:
            self.logger.error(f"❌ Failed to save cache: {e}")
    
    def _is_cache_fresh(self, cached_data: Dict[str, Any]) -> bool:
        """Check if cached data is still fresh"""
        try:
            last_updated = datetime.fromisoformat(cached_data['last_updated'])
            expiry_date = last_updated + timedelta(days=self.cache_expiry_days)
            return datetime.now() < expiry_date
        except:
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.sector_cache:
            return {'total_symbols': 0, 'sources': {}}
        
        sources = {}
        for data in self.sector_cache.values():
            source = data.get('source', 'unknown')
            sources[source] = sources.get(source, 0) + 1
        
        return {
            'total_symbols': len(self.sector_cache),
            'sources': sources,
            'cache_file': self.cache_file
        }
    
    def refresh_symbol(self, symbol: str) -> bool:
        """Force refresh a symbol's sector data"""
        try:
            symbol = symbol.upper().strip()
            
            # Remove from cache to force refresh
            if symbol in self.sector_cache:
                del self.sector_cache[symbol]
            
            # Fetch fresh data
            fresh_data = self.get_symbol_sector(symbol)
            return fresh_data.get('sector') != 'Unknown'
            
        except Exception as e:
            self.logger.error(f"❌ Failed to refresh {symbol}: {e}")
            return False
    
    def _init_futures_mapping(self) -> Dict[str, Dict[str, str]]:
        """Initialize futures symbol sector mapping"""
        return {
            # Energy Futures
            '/CL': {'sector': 'Energy', 'industry': 'Crude Oil Futures'},
            '/RB': {'sector': 'Energy', 'industry': 'Gasoline Futures'},
            '/HO': {'sector': 'Energy', 'industry': 'Heating Oil Futures'},
            '/NG': {'sector': 'Energy', 'industry': 'Natural Gas Futures'},
            '/BZ': {'sector': 'Energy', 'industry': 'Brent Crude Oil Futures'},
            
            # Agricultural Futures
            '/ZC': {'sector': 'Agricultural', 'industry': 'Corn Futures'},
            '/ZS': {'sector': 'Agricultural', 'industry': 'Soybean Futures'},
            '/ZW': {'sector': 'Agricultural', 'industry': 'Wheat Futures'},
            '/ZL': {'sector': 'Agricultural', 'industry': 'Soybean Oil Futures'},
            '/ZM': {'sector': 'Agricultural', 'industry': 'Soybean Meal Futures'},
            '/CC': {'sector': 'Agricultural', 'industry': 'Cocoa Futures'},
            '/CT': {'sector': 'Agricultural', 'industry': 'Cotton Futures'},
            '/KC': {'sector': 'Agricultural', 'industry': 'Coffee Futures'},
            '/SB': {'sector': 'Agricultural', 'industry': 'Sugar Futures'},
            '/OJ': {'sector': 'Agricultural', 'industry': 'Orange Juice Futures'},
            '/LE': {'sector': 'Agricultural', 'industry': 'Live Cattle Futures'},
            '/HE': {'sector': 'Agricultural', 'industry': 'Lean Hogs Futures'},
            '/GF': {'sector': 'Agricultural', 'industry': 'Feeder Cattle Futures'},
            
            # Metals Futures
            '/GC': {'sector': 'Metals', 'industry': 'Gold Futures'},
            '/SI': {'sector': 'Metals', 'industry': 'Silver Futures'},
            '/PL': {'sector': 'Metals', 'industry': 'Platinum Futures'},
            '/PA': {'sector': 'Metals', 'industry': 'Palladium Futures'},
            '/HG': {'sector': 'Metals', 'industry': 'Copper Futures'},
            
            # Interest Rate / Financial Futures
            '/ZB': {'sector': 'Financial', 'industry': '30-Year Treasury Bond Futures'},
            '/ZN': {'sector': 'Financial', 'industry': '10-Year Treasury Note Futures'},
            '/ZF': {'sector': 'Financial', 'industry': '5-Year Treasury Note Futures'},
            '/ZT': {'sector': 'Financial', 'industry': '2-Year Treasury Note Futures'},
            '/GE': {'sector': 'Financial', 'industry': 'Eurodollar Futures'},
            '/ZQ': {'sector': 'Financial', 'industry': '30-Day Fed Fund Futures'},
            
            # Equity Index Futures
            '/ES': {'sector': 'Equity Index', 'industry': 'E-mini S&P 500 Futures'},
            '/NQ': {'sector': 'Equity Index', 'industry': 'E-mini NASDAQ 100 Futures'},
            '/YM': {'sector': 'Equity Index', 'industry': 'E-mini Dow Jones Futures'},
            '/RTY': {'sector': 'Equity Index', 'industry': 'E-mini Russell 2000 Futures'},
            '/EMD': {'sector': 'Equity Index', 'industry': 'E-mini S&P MidCap 400 Futures'},
            
            # Currency Futures
            '/6E': {'sector': 'Currency', 'industry': 'Euro Futures'},
            '/6B': {'sector': 'Currency', 'industry': 'British Pound Futures'},
            '/6J': {'sector': 'Currency', 'industry': 'Japanese Yen Futures'},
            '/6C': {'sector': 'Currency', 'industry': 'Canadian Dollar Futures'},
            '/6A': {'sector': 'Currency', 'industry': 'Australian Dollar Futures'},
            '/6S': {'sector': 'Currency', 'industry': 'Swiss Franc Futures'},
            '/6N': {'sector': 'Currency', 'industry': 'New Zealand Dollar Futures'},
            '/6M': {'sector': 'Currency', 'industry': 'Mexican Peso Futures'},
            '/DX': {'sector': 'Currency', 'industry': 'US Dollar Index Futures'},
            
            # Crypto Futures
            '/BTC': {'sector': 'Cryptocurrency', 'industry': 'Bitcoin Futures'},
            '/ETH': {'sector': 'Cryptocurrency', 'industry': 'Ethereum Futures'},
            '/MBT': {'sector': 'Cryptocurrency', 'industry': 'Micro Bitcoin Futures'},
            '/MET': {'sector': 'Cryptocurrency', 'industry': 'Micro Ethereum Futures'},
            
            # Volatility
            '/VIX': {'sector': 'Volatility', 'industry': 'VIX Futures'},
            '/VX': {'sector': 'Volatility', 'industry': 'VIX Futures (Legacy)'},
            
            # Real Estate
            '/RS': {'sector': 'Real Estate', 'industry': 'Case-Shiller Real Estate Futures'}
        }
    
    def _get_futures_sector(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get sector information for futures symbols"""
        try:
            # Direct mapping check (for generic symbols like /CL)
            if symbol in self.futures_mapping:
                mapping = self.futures_mapping[symbol]
                return {
                    'sector': mapping['sector'],
                    'industry': mapping['industry'],
                    'last_updated': datetime.now().isoformat(),
                    'source': 'futures_mapping'
                }
            
            # Contract-specific symbol check (for symbols like /CLQ5)
            # Try to extract base symbol from contract-specific symbols
            if symbol.startswith('/') and len(symbol) > 3:
                # Common futures contract patterns:
                # /CLQ5 -> /CL (remove month/year suffix)
                # /ESU5 -> /ES (remove month/year suffix)
                # /6EU5 -> /6E (currency futures)
                
                # Try 2-character base first (most common)
                base_symbol_2 = symbol[:3]  # /CL from /CLQ5
                if base_symbol_2 in self.futures_mapping:
                    mapping = self.futures_mapping[base_symbol_2]
                    self.logger.debug(f"🎯 Mapped contract {symbol} to base {base_symbol_2}")
                    return {
                        'sector': mapping['sector'],
                        'industry': mapping['industry'],
                        'last_updated': datetime.now().isoformat(),
                        'source': 'futures_mapping_base'
                    }
                
                # Try 3-character base for currencies (/6EU5 -> /6E)
                if len(symbol) >= 4:
                    base_symbol_3 = symbol[:4]  # /6E from /6EU5
                    if base_symbol_3 in self.futures_mapping:
                        mapping = self.futures_mapping[base_symbol_3]
                        self.logger.debug(f"🎯 Mapped contract {symbol} to base {base_symbol_3}")
                        return {
                            'sector': mapping['sector'],
                            'industry': mapping['industry'],
                            'last_updated': datetime.now().isoformat(),
                            'source': 'futures_mapping_base'
                        }
            
            # For unknown futures symbols, try to infer from the symbol
            base_symbol = symbol[1:] if symbol.startswith('/') else symbol
            
            # Default futures classification
            self.logger.warning(f"⚠️ Unknown futures symbol {symbol}, using default classification")
            return {
                'sector': 'Futures',
                'industry': f'{base_symbol} Futures',
                'last_updated': datetime.now().isoformat(),
                'source': 'futures_default'
            }
                
        except Exception as e:
            self.logger.error(f"❌ Error getting futures sector for {symbol}: {e}")
            return None
    
