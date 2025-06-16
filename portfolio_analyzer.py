#!/usr/bin/env python3
"""
Portfolio Analyzer
Analyzes current portfolio state and calculates allocations for compliance checking
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class PortfolioPosition:
    """Individual position in portfolio"""
    symbol: str
    underlying_symbol: str
    instrument_type: str  # 'Equity', 'Equity Option'
    strategy_type: str   # 'covered_call', 'put_credit_spread', etc.
    quantity: float
    market_value: float
    delta: float
    dte: Optional[int]  # Days to expiration
    is_equity: bool
    is_bullish: bool
    is_neutral: bool
    is_bearish: bool
    sector: Optional[str] = None
    
@dataclass 
class PortfolioSnapshot:
    """Complete portfolio snapshot"""
    total_market_value: float
    total_buying_power: float
    cash_balance: float
    positions: List[PortfolioPosition]
    
    # Calculated allocations
    asset_allocation: Dict[str, float]
    duration_allocation: Dict[str, float] 
    strategy_allocation: Dict[str, float]
    sector_allocation: Dict[str, float]
    
    timestamp: datetime

class PortfolioAnalyzer:
    """Analyzes portfolio for allocation compliance"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance
        self.logger = logging.getLogger(__name__)
        
        # Strategy bias mapping
        self.strategy_bias_map = {
            'covered_call': 'neutral',
            'cash_secured_put': 'bullish', 
            'put_credit_spread': 'bullish',
            'call_credit_spread': 'bearish',
            'iron_condor': 'neutral',
            'iron_butterfly': 'neutral',
            'short_strangle': 'neutral',
            'call_debit_spread': 'bullish',
            'put_debit_spread': 'bearish',
            'long_call': 'bullish',
            'long_put': 'bearish',
            'short_put': 'bullish',
            'short_call': 'bearish'
        }
        
        # Sector mapping (simplified)
        self.sector_map = {
            'AAPL': 'Technology', 'MSFT': 'Technology', 'GOOGL': 'Technology', 'META': 'Technology',
            'NVDA': 'Technology', 'AMD': 'Technology', 'INTC': 'Technology',
            'TSLA': 'Consumer Discretionary', 'AMZN': 'Consumer Discretionary',
            'JPM': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials',
            'XLE': 'Energy', 'XLF': 'Financials', 'XLK': 'Technology',
            'SPY': 'Broad Market', 'QQQ': 'Technology', 'IWM': 'Small Cap'
        }
        
    def analyze_current_portfolio(self, account_numbers: Optional[List[str]] = None) -> PortfolioSnapshot:
        """Analyze current portfolio and calculate allocations"""
        try:
            # Get current dashboard data
            dashboard_data = self.tracker.get_dashboard_data(filter_accounts=account_numbers)
            
            # Get account balances
            balances = self._get_account_balances(account_numbers)
            
            # Convert positions to portfolio positions
            portfolio_positions = self._convert_positions(dashboard_data.get('positions', []))
            
            # Calculate total values
            total_market_value = sum(pos.market_value for pos in portfolio_positions)
            total_buying_power = sum(balance.get('buying_power', 0) for balance in balances.values())
            cash_balance = sum(balance.get('cash_balance', 0) for balance in balances.values())
            
            # Calculate allocations
            asset_allocation = self._calculate_asset_allocation(portfolio_positions, total_market_value)
            duration_allocation = self._calculate_duration_allocation(portfolio_positions, total_market_value)
            strategy_allocation = self._calculate_strategy_allocation(portfolio_positions, total_market_value)
            sector_allocation = self._calculate_sector_allocation(portfolio_positions, total_market_value)
            
            snapshot = PortfolioSnapshot(
                total_market_value=total_market_value,
                total_buying_power=total_buying_power,
                cash_balance=cash_balance,
                positions=portfolio_positions,
                asset_allocation=asset_allocation,
                duration_allocation=duration_allocation,
                strategy_allocation=strategy_allocation,
                sector_allocation=sector_allocation,
                timestamp=datetime.now()
            )
            
            return snapshot
            
        except Exception as e:
            self.logger.error(f"❌ Failed to analyze portfolio: {e}")
            raise
            
    def _convert_positions(self, positions: List[Dict]) -> List[PortfolioPosition]:
        """Convert raw positions to portfolio position objects"""
        portfolio_positions = []
        
        try:
            for pos in positions:
                # Skip summary rows
                if pos.get('is_summary', False):
                    continue
                    
                # Determine strategy type and bias
                strategy_type = self._identify_strategy_type(pos)
                bias = self._get_strategy_bias(strategy_type)
                
                # Calculate DTE if option
                dte = self._calculate_dte(pos) if pos.get('instrument_type') == 'Equity Option' else None
                
                portfolio_pos = PortfolioPosition(
                    symbol=pos.get('symbol_occ', pos.get('underlying_symbol', '')),
                    underlying_symbol=pos.get('underlying_symbol', ''),
                    instrument_type=pos.get('instrument_type', ''),
                    strategy_type=strategy_type,
                    quantity=pos.get('quantity', 0),
                    market_value=abs(pos.get('net_liq', 0)),  # Use absolute value
                    delta=pos.get('position_delta', 0),
                    dte=dte,
                    is_equity=(pos.get('instrument_type') == 'Equity'),
                    is_bullish=(bias == 'bullish'),
                    is_neutral=(bias == 'neutral'),
                    is_bearish=(bias == 'bearish'),
                    sector=self.sector_map.get(pos.get('underlying_symbol', ''), 'Other')
                )
                
                portfolio_positions.append(portfolio_pos)
                
            return portfolio_positions
            
        except Exception as e:
            self.logger.error(f"❌ Failed to convert positions: {e}")
            return []
            
    def _identify_strategy_type(self, position: Dict) -> str:
        """Identify strategy type from position data"""
        # This is simplified - in reality would need more sophisticated logic
        # to identify complex strategies by analyzing multiple legs
        
        instrument_type = position.get('instrument_type', '')
        quantity = position.get('quantity', 0)
        
        if instrument_type == 'Equity':
            return 'long_stock' if quantity > 0 else 'short_stock'
        elif instrument_type == 'Equity Option':
            # Simplified option strategy identification
            if quantity > 0:
                # Long option
                if position.get('option_type') == 'C':
                    return 'long_call'
                else:
                    return 'long_put'
            else:
                # Short option
                if position.get('option_type') == 'C':
                    return 'short_call'
                else:
                    return 'short_put'
        
        return 'unknown'
        
    def _get_strategy_bias(self, strategy_type: str) -> str:
        """Get directional bias for strategy"""
        return self.strategy_bias_map.get(strategy_type, 'neutral')
        
    def _calculate_dte(self, position: Dict) -> Optional[int]:
        """Calculate days to expiration for options"""
        try:
            expires_at = position.get('expires_at')
            if expires_at:
                expiry_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                dte = (expiry_date.date() - datetime.now().date()).days
                return max(0, dte)
        except:
            pass
        return None
        
    def _calculate_asset_allocation(self, positions: List[PortfolioPosition], 
                                  total_value: float) -> Dict[str, float]:
        """Calculate asset allocation percentages"""
        if total_value == 0:
            return {}
            
        equity_value = sum(pos.market_value for pos in positions if pos.is_equity)
        non_equity_value = sum(pos.market_value for pos in positions if not pos.is_equity)
        
        return {
            'equities': (equity_value / total_value) * 100,
            'non_equities': (non_equity_value / total_value) * 100
        }
        
    def _calculate_duration_allocation(self, positions: List[PortfolioPosition],
                                     total_value: float) -> Dict[str, float]:
        """Calculate duration allocation percentages"""
        if total_value == 0:
            return {}
            
        duration_buckets = defaultdict(float)
        
        for pos in positions:
            if pos.dte is not None:
                # Categorize by DTE
                if pos.dte == 0:
                    bucket = '0_dte'
                elif pos.dte <= 7:
                    bucket = '7_dte'
                elif pos.dte <= 14:
                    bucket = '14_dte'
                else:
                    bucket = '45_dte'
                    
                duration_buckets[bucket] += pos.market_value
            else:
                # Non-expiring positions (stocks)
                duration_buckets['non_expiring'] = duration_buckets.get('non_expiring', 0) + pos.market_value
                
        # Convert to percentages
        return {bucket: (value / total_value) * 100 
                for bucket, value in duration_buckets.items()}
                
    def _calculate_strategy_allocation(self, positions: List[PortfolioPosition],
                                     total_value: float) -> Dict[str, float]:
        """Calculate strategy bias allocation percentages"""
        if total_value == 0:
            return {}
            
        bullish_value = sum(pos.market_value for pos in positions if pos.is_bullish)
        neutral_value = sum(pos.market_value for pos in positions if pos.is_neutral)
        bearish_value = sum(pos.market_value for pos in positions if pos.is_bearish)
        
        return {
            'bullish': (bullish_value / total_value) * 100,
            'neutral': (neutral_value / total_value) * 100,
            'bearish': (bearish_value / total_value) * 100
        }
        
    def _calculate_sector_allocation(self, positions: List[PortfolioPosition],
                                   total_value: float) -> Dict[str, float]:
        """Calculate sector allocation percentages"""
        if total_value == 0:
            return {}
            
        sector_values = defaultdict(float)
        
        for pos in positions:
            sector = pos.sector or 'Other'
            sector_values[sector] += pos.market_value
            
        return {sector: (value / total_value) * 100 
                for sector, value in sector_values.items()}
                
    def _get_account_balances(self, account_numbers: Optional[List[str]] = None) -> Dict[str, Dict]:
        """Get account balance information"""
        try:
            balances = {}
            
            with self.tracker.balances_lock:
                for account_num, balance_obj in self.tracker.account_balances.items():
                    if account_numbers is None or account_num in account_numbers:
                        balances[account_num] = {
                            'net_liquidating_value': getattr(balance_obj, 'net_liquidating_value', 0),
                            'buying_power': getattr(balance_obj, 'option_buying_power', 0),
                            'cash_balance': getattr(balance_obj, 'cash_balance', 0)
                        }
                        
            return balances
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get account balances: {e}")
            return {}
            
    def get_portfolio_summary(self, snapshot: PortfolioSnapshot) -> Dict[str, Any]:
        """Get high-level portfolio summary"""
        try:
            return {
                'total_positions': len(snapshot.positions),
                'total_market_value': snapshot.total_market_value,
                'total_buying_power': snapshot.total_buying_power,
                'cash_percentage': (snapshot.cash_balance / snapshot.total_market_value * 100) if snapshot.total_market_value > 0 else 0,
                'equity_positions': len([p for p in snapshot.positions if p.is_equity]),
                'option_positions': len([p for p in snapshot.positions if not p.is_equity]),
                'total_delta': sum(p.delta for p in snapshot.positions),
                'sectors_represented': len(set(p.sector for p in snapshot.positions if p.sector)),
                'timestamp': snapshot.timestamp.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get portfolio summary: {e}")
            return {}