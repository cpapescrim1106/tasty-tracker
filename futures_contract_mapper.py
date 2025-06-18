#!/usr/bin/env python3
"""
Futures Contract Mapper
Automatically maps generic futures symbols to active front-month contracts
"""

import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import calendar

@dataclass
class ContractInfo:
    """Information about a futures contract"""
    generic_symbol: str      # e.g., "/CL"
    active_symbol: str       # e.g., "/CLQ5"
    expiry_date: datetime
    roll_date: datetime
    volume: Optional[int] = None
    open_interest: Optional[int] = None

class FuturesContractMapper:
    """Maps generic futures symbols to active front-month contracts"""
    
    # Month codes for futures contracts
    MONTH_CODES = {
        1: 'F',   # January
        2: 'G',   # February  
        3: 'H',   # March
        4: 'J',   # April
        5: 'K',   # May
        6: 'M',   # June
        7: 'N',   # July
        8: 'Q',   # August
        9: 'U',   # September
        10: 'V',  # October
        11: 'X',  # November
        12: 'Z'   # December
    }
    
    # Contract specifications for different asset classes
    CONTRACT_SPECS = {
        '/CL': {
            'name': 'Crude Oil',
            'months': [1,2,3,4,5,6,7,8,9,10,11,12],  # All months
            'last_trade_rule': 'third_business_day_before_25th_prior_month',
            'roll_days_before_expiry': 10
        },
        '/ES': {
            'name': 'E-mini S&P 500',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'third_friday_of_month',
            'roll_days_before_expiry': 8
        },
        '/NQ': {
            'name': 'E-mini NASDAQ 100',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'third_friday_of_month',
            'roll_days_before_expiry': 8
        },
        '/GC': {
            'name': 'Gold',
            'months': [2,4,6,8,10,12],  # Even months
            'last_trade_rule': 'third_last_business_day',
            'roll_days_before_expiry': 30
        },
        '/ZN': {
            'name': '10-Year Treasury Note',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'seventh_business_day_before_month_end',
            'roll_days_before_expiry': 60
        },
        '/PL': {
            'name': 'Platinum',
            'months': [1,4,7,10],  # Quarterly (Jan, Apr, Jul, Oct)
            'last_trade_rule': 'third_last_business_day',
            'roll_days_before_expiry': 30
        },
        '/M2K': {
            'name': 'Micro E-mini Russell 2000',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'third_friday_of_month',
            'roll_days_before_expiry': 8
        },
        '/HG': {
            'name': 'Copper',
            'months': [3,5,7,9,12],  # Mar, May, Jul, Sep, Dec
            'last_trade_rule': 'third_last_business_day',
            'roll_days_before_expiry': 30
        },
        '/ZS': {
            'name': 'Soybeans',
            'months': [1,3,5,7,8,9,11],  # Jan, Mar, May, Jul, Aug, Sep, Nov
            'last_trade_rule': 'business_day_before_15th_prior_month',
            'roll_days_before_expiry': 15
        },
        '/ZC': {
            'name': 'Corn',
            'months': [3,5,7,9,12],  # Mar, May, Jul, Sep, Dec
            'last_trade_rule': 'business_day_before_15th_prior_month', 
            'roll_days_before_expiry': 15
        },
        '/ZW': {
            'name': 'Wheat',
            'months': [3,5,7,9,12],  # Mar, May, Jul, Sep, Dec
            'last_trade_rule': 'business_day_before_15th_prior_month',
            'roll_days_before_expiry': 15
        },
        '/SI': {
            'name': 'Silver',
            'months': [3,5,7,9,12],  # Mar, May, Jul, Sep, Dec
            'last_trade_rule': 'third_last_business_day',
            'roll_days_before_expiry': 30
        },
        '/RTY': {
            'name': 'E-mini Russell 2000',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'third_friday_of_month',
            'roll_days_before_expiry': 8
        },
        '/MES': {
            'name': 'Micro E-mini S&P 500',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'third_friday_of_month',
            'roll_days_before_expiry': 8
        },
        '/MNQ': {
            'name': 'Micro E-mini NASDAQ 100',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'third_friday_of_month',
            'roll_days_before_expiry': 8
        },
        '/BTC': {
            'name': 'Bitcoin Futures',
            'months': [1,2,3,4,5,6,7,8,9,10,11,12],  # All months
            'last_trade_rule': 'last_friday_of_month',
            'roll_days_before_expiry': 5
        },
        '/ETH': {
            'name': 'Ethereum Futures',
            'months': [1,2,3,4,5,6,7,8,9,10,11,12],  # All months
            'last_trade_rule': 'last_friday_of_month',
            'roll_days_before_expiry': 5
        },
        '/ZB': {
            'name': '30-Year Treasury Bond',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'seventh_business_day_before_month_end',
            'roll_days_before_expiry': 60
        },
        '/ZT': {
            'name': '2-Year Treasury Note',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'month_end',
            'roll_days_before_expiry': 60
        },
        '/ZF': {
            'name': '5-Year Treasury Note',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'month_end',
            'roll_days_before_expiry': 60
        },
        '/6E': {
            'name': 'Euro FX',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'second_business_day_before_third_wednesday',
            'roll_days_before_expiry': 10
        },
        '/6A': {
            'name': 'Australian Dollar',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'second_business_day_before_third_wednesday',
            'roll_days_before_expiry': 10
        },
        '/6B': {
            'name': 'British Pound',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'second_business_day_before_third_wednesday',
            'roll_days_before_expiry': 10
        },
        '/6C': {
            'name': 'Canadian Dollar',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'second_business_day_before_third_wednesday',
            'roll_days_before_expiry': 10
        },
        '/6J': {
            'name': 'Japanese Yen',
            'months': [3,6,9,12],  # Quarterly
            'last_trade_rule': 'second_business_day_before_third_wednesday',
            'roll_days_before_expiry': 10
        },
        '/LE': {
            'name': 'Live Cattle',
            'months': [2,4,6,8,10,12],  # Even months
            'last_trade_rule': 'last_business_day_of_month',
            'roll_days_before_expiry': 5
        },
        '/HE': {
            'name': 'Lean Hogs',
            'months': [2,4,5,6,7,8,10,12],  # Feb, Apr, May, Jun, Jul, Aug, Oct, Dec
            'last_trade_rule': 'tenth_business_day_of_month',
            'roll_days_before_expiry': 5
        }
    }
    
    def __init__(self, tracker=None):
        self.tracker = tracker
        self.logger = logging.getLogger(__name__)
        self.contract_cache = {}
        self.last_update = None
        
    def get_active_contract(self, generic_symbol: str) -> Optional[str]:
        """Get the active front-month contract for a generic symbol"""
        try:
            if generic_symbol not in self.CONTRACT_SPECS:
                self.logger.warning(f"⚠️ No contract specification for {generic_symbol}")
                return None
            
            # Check cache first
            if self._is_cache_valid(generic_symbol):
                cached_contract = self.contract_cache.get(generic_symbol)
                if cached_contract:
                    self.logger.debug(f"📋 Using cached active contract: {generic_symbol} -> {cached_contract}")
                    return cached_contract
            
            # Determine active contract
            active_contract = self._find_active_contract(generic_symbol)
            
            if active_contract:
                self.contract_cache[generic_symbol] = active_contract
                self.last_update = datetime.now()
                self.logger.info(f"✅ Active contract for {generic_symbol}: {active_contract}")
                return active_contract
            else:
                self.logger.error(f"❌ Could not determine active contract for {generic_symbol}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error getting active contract for {generic_symbol}: {e}")
            return None
    
    def _is_cache_valid(self, generic_symbol: str) -> bool:
        """Check if cached contract is still valid (within 1 hour)"""
        if not self.last_update or generic_symbol not in self.contract_cache:
            return False
        
        age = datetime.now() - self.last_update
        return age.total_seconds() < 3600  # 1 hour cache
    
    def _find_active_contract(self, generic_symbol: str) -> Optional[str]:
        """Find the active front-month contract using volume/open interest data"""
        try:
            spec = self.CONTRACT_SPECS[generic_symbol]
            
            # Generate potential contracts for next few months
            potential_contracts = self._generate_potential_contracts(generic_symbol, months_ahead=6)
            
            if not potential_contracts:
                self.logger.warning(f"⚠️ No potential contracts generated for {generic_symbol}")
                return None
            
            # Try to get volume/open interest data from API
            contract_data = self._fetch_contract_data(potential_contracts)
            
            if contract_data:
                # Find active contract based on volume
                active_contract = self._select_active_by_volume(contract_data, spec)
                if active_contract:
                    return active_contract
            
            # Fallback: Use rule-based selection
            self.logger.info(f"📊 No volume data available, using rule-based selection for {generic_symbol}")
            return self._select_active_by_rules(generic_symbol, potential_contracts)
            
        except Exception as e:
            self.logger.error(f"❌ Error finding active contract for {generic_symbol}: {e}")
            return None
    
    def _generate_potential_contracts(self, generic_symbol: str, months_ahead: int = 6) -> List[str]:
        """Generate list of potential contract symbols for the next few months"""
        try:
            spec = self.CONTRACT_SPECS[generic_symbol]
            base_symbol = generic_symbol  # e.g., "/CL"
            
            contracts = []
            current_date = datetime.now()
            
            # Look ahead for the specified number of months
            for i in range(months_ahead):
                check_date = current_date + timedelta(days=30 * i)
                month = check_date.month
                year = check_date.year
                
                # Only include months that trade for this contract
                if month in spec['months']:
                    month_code = self.MONTH_CODES[month]
                    year_suffix = str(year)[-1]  # Last digit of year
                    
                    contract_symbol = f"{base_symbol}{month_code}{year_suffix}"
                    contracts.append(contract_symbol)
            
            self.logger.debug(f"📋 Generated potential contracts for {generic_symbol}: {contracts}")
            return contracts
            
        except Exception as e:
            self.logger.error(f"❌ Error generating potential contracts: {e}")
            return []
    
    def _fetch_contract_data(self, contracts: List[str]) -> Dict[str, ContractInfo]:
        """Fetch volume and open interest data for contracts"""
        try:
            if not self.tracker or not hasattr(self.tracker, 'tasty_client'):
                self.logger.warning("⚠️ No tracker available for API calls")
                return {}
            
            headers = {
                'Authorization': self.tracker.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Try to get data from /instruments/futures
            params = [('symbol[]', symbol) for symbol in contracts]
            response = requests.get(
                "https://api.tastyworks.com/instruments/futures",
                params=params,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                
                contract_data = {}
                for item in items:
                    symbol = item.get('symbol')
                    if symbol in contracts:
                        contract_data[symbol] = ContractInfo(
                            generic_symbol="",  # Will be set by caller
                            active_symbol=symbol,
                            expiry_date=datetime.now(),  # Placeholder
                            roll_date=datetime.now(),    # Placeholder
                            volume=item.get('volume'),
                            open_interest=item.get('open-interest')
                        )
                
                self.logger.info(f"📊 Fetched contract data for {len(contract_data)} contracts")
                return contract_data
            else:
                self.logger.warning(f"⚠️ Failed to fetch contract data: {response.status_code}")
                return {}
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching contract data: {e}")
            return {}
    
    def _select_active_by_volume(self, contract_data: Dict[str, ContractInfo], spec: Dict) -> Optional[str]:
        """Select active contract based on volume (highest volume wins)"""
        try:
            # Filter contracts with volume data
            volume_contracts = [(symbol, info) for symbol, info in contract_data.items() 
                              if info.volume is not None and info.volume > 0]
            
            if not volume_contracts:
                self.logger.warning("⚠️ No contracts with volume data found")
                return None
            
            # Sort by volume (highest first)
            volume_contracts.sort(key=lambda x: x[1].volume, reverse=True)
            
            active_symbol = volume_contracts[0][0]
            active_volume = volume_contracts[0][1].volume
            
            self.logger.info(f"📊 Selected active contract by volume: {active_symbol} (volume: {active_volume:,})")
            return active_symbol
            
        except Exception as e:
            self.logger.error(f"❌ Error selecting active contract by volume: {e}")
            return None
    
    def _select_active_by_rules(self, generic_symbol: str, potential_contracts: List[str]) -> Optional[str]:
        """Select active contract using rule-based approach"""
        try:
            if not potential_contracts:
                return None
            
            spec = self.CONTRACT_SPECS[generic_symbol]
            current_date = datetime.now()
            
            # For now, simple rule: pick the nearest month that hasn't expired
            # This is a fallback when volume data isn't available
            
            for contract in potential_contracts:
                # Extract month and year from contract symbol
                # e.g., "/CLQ5" -> Q (August), 5 (2025)
                if len(contract) >= 4:
                    month_code = contract[-2]
                    year_digit = contract[-1]
                    
                    # Convert back to month number
                    month_num = None
                    for num, code in self.MONTH_CODES.items():
                        if code == month_code:
                            month_num = num
                            break
                    
                    if month_num:
                        # Assume year is 2020+ (adjust logic as needed)
                        year = 2020 + int(year_digit)
                        contract_date = datetime(year, month_num, 1)
                        
                        # If contract month is in the future or current month, it's likely active
                        if contract_date >= current_date.replace(day=1):
                            self.logger.info(f"📅 Selected active contract by rules: {contract}")
                            return contract
            
            # If no future contracts found, return the first one as fallback
            fallback = potential_contracts[0]
            self.logger.warning(f"⚠️ Using fallback contract: {fallback}")
            return fallback
            
        except Exception as e:
            self.logger.error(f"❌ Error selecting active contract by rules: {e}")
            return potential_contracts[0] if potential_contracts else None
    
    def map_symbols(self, symbols: List[str]) -> Dict[str, str]:
        """Map a list of symbols, converting generic futures to active contracts"""
        mapping = {}
        
        for symbol in symbols:
            if symbol in self.CONTRACT_SPECS:
                # This is a generic futures symbol, map it to active contract
                active_contract = self.get_active_contract(symbol)
                if active_contract:
                    mapping[symbol] = active_contract
                    self.logger.info(f"🔄 Mapped {symbol} -> {active_contract}")
                else:
                    # Keep original if mapping fails
                    mapping[symbol] = symbol
                    self.logger.warning(f"⚠️ Could not map {symbol}, keeping original")
            else:
                # Not a generic futures symbol, keep as-is
                mapping[symbol] = symbol
        
        return mapping
    
    def get_mapped_symbols(self, symbols: List[str]) -> List[str]:
        """Get list of symbols with generic futures mapped to active contracts"""
        mapping = self.map_symbols(symbols)
        return [mapping[symbol] for symbol in symbols]

# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    mapper = FuturesContractMapper()
    
    # Test mapping
    test_symbols = ['/CL', '/ES', '/GC', 'AAPL', 'TSLA']
    
    print("🔄 Testing Futures Contract Mapping")
    print("=" * 50)
    
    mapped_symbols = mapper.get_mapped_symbols(test_symbols)
    
    print(f"Original symbols: {test_symbols}")
    print(f"Mapped symbols:   {mapped_symbols}")
    
    # Test individual mappings
    for symbol in ['/CL', '/ES', '/GC']:
        active = mapper.get_active_contract(symbol)
        print(f"{symbol} -> {active}")