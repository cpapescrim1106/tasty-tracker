#!/usr/bin/env python3
"""
TastyTracker Risk Manager
Portfolio risk management and position sizing calculator
"""

import os
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

@dataclass
class RiskParameters:
    """Risk management parameters for portfolio optimization"""
    max_portfolio_risk_pct: float = 2.0  # Max % of portfolio to risk per trade
    max_single_position_pct: float = 5.0  # Max % of portfolio in single position
    max_sector_concentration_pct: float = 15.0  # Max % in single sector/symbol
    target_delta_range: Tuple[float, float] = (-50, 50)  # Target portfolio delta range
    max_buying_power_usage_pct: float = 50.0  # Max % of buying power to use
    min_trade_premium: float = 0.25  # Minimum premium per trade
    max_trade_premium: float = 5.00  # Maximum premium per trade

@dataclass
class PositionSizeRecommendation:
    """Position sizing recommendation output"""
    recommended_quantity: int
    max_loss_amount: float
    max_loss_percentage: float
    buying_power_required: float
    risk_score: str  # "Low", "Medium", "High"
    warnings: List[str]
    concentration_impact: Dict[str, float]
    delta_impact: float

class RiskLevel(Enum):
    """Risk level classifications"""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"

class RiskManager:
    """Main risk management and position sizing engine"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance
        self.logger = logging.getLogger(__name__)
        
        # Risk profiles
        self.risk_profiles = {
            RiskLevel.CONSERVATIVE: RiskParameters(
                max_portfolio_risk_pct=1.0,
                max_single_position_pct=3.0,
                max_sector_concentration_pct=10.0,
                target_delta_range=(-25, 25),
                max_buying_power_usage_pct=30.0
            ),
            RiskLevel.MODERATE: RiskParameters(
                max_portfolio_risk_pct=2.0,
                max_single_position_pct=5.0,
                max_sector_concentration_pct=15.0,
                target_delta_range=(-50, 50),
                max_buying_power_usage_pct=50.0
            ),
            RiskLevel.AGGRESSIVE: RiskParameters(
                max_portfolio_risk_pct=5.0,
                max_single_position_pct=10.0,
                max_sector_concentration_pct=25.0,
                target_delta_range=(-100, 100),
                max_buying_power_usage_pct=70.0
            )
        }
    
    def calculate_position_size(self, account_number: str, strategy_data: Dict[str, Any], 
                              risk_level: RiskLevel = RiskLevel.MODERATE,
                              custom_risk_pct: Optional[float] = None) -> PositionSizeRecommendation:
        """
        Calculate optimal position size based on account balance, risk parameters, and strategy
        """
        try:
            # Get risk parameters
            risk_params = self.risk_profiles[risk_level]
            if custom_risk_pct:
                risk_params.max_portfolio_risk_pct = custom_risk_pct
            
            # Get account data
            account_data = self._get_account_data(account_number)
            if not account_data:
                raise ValueError(f"Could not retrieve data for account {account_number}")
            
            net_liq = account_data['net_liquidation_value']
            buying_power = account_data.get('buying_power', net_liq * 0.5)
            
            # Get current portfolio data
            portfolio_data = self._get_portfolio_analysis(account_number)
            
            # Extract strategy risk metrics
            strategy_risk = self._analyze_strategy_risk(strategy_data)
            
            # Calculate base position size based on risk percentage
            max_risk_amount = net_liq * (risk_params.max_portfolio_risk_pct / 100)
            base_quantity = int(max_risk_amount / strategy_risk['max_loss_per_contract'])
            
            # Apply position size constraints
            constrained_quantity = self._apply_position_constraints(
                base_quantity, strategy_data, portfolio_data, risk_params, account_data
            )
            
            # Calculate final metrics
            final_max_loss = constrained_quantity * strategy_risk['max_loss_per_contract']
            final_max_loss_pct = (final_max_loss / net_liq) * 100
            
            # Calculate buying power requirement
            buying_power_required = self._calculate_buying_power_requirement(
                constrained_quantity, strategy_data
            )
            
            # Assess concentration impact
            concentration_impact = self._assess_concentration_impact(
                strategy_data, constrained_quantity, portfolio_data
            )
            
            # Calculate delta impact
            delta_impact = constrained_quantity * strategy_data.get('net_delta', 0) * 100
            
            # Generate warnings
            warnings = self._generate_risk_warnings(
                constrained_quantity, final_max_loss_pct, concentration_impact,
                buying_power_required, buying_power, risk_params
            )
            
            # Determine risk score
            risk_score = self._calculate_risk_score(final_max_loss_pct, concentration_impact)
            
            self.logger.info(f"📊 Position sizing for {strategy_data.get('underlying_symbol')}: "
                           f"{constrained_quantity} contracts, ${final_max_loss:.2f} max loss "
                           f"({final_max_loss_pct:.2f}%)")
            
            return PositionSizeRecommendation(
                recommended_quantity=constrained_quantity,
                max_loss_amount=final_max_loss,
                max_loss_percentage=final_max_loss_pct,
                buying_power_required=buying_power_required,
                risk_score=risk_score,
                warnings=warnings,
                concentration_impact=concentration_impact,
                delta_impact=delta_impact
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating position size: {e}")
            raise
    
    def _get_account_data(self, account_number: str) -> Optional[Dict[str, Any]]:
        """Get account balance and buying power data"""
        try:
            with self.tracker.balances_lock:
                balance = self.tracker.account_balances.get(account_number)
                if balance:
                    # Convert Decimal to float to avoid type issues
                    net_liq = float(balance.net_liquidating_value)
                    buying_power = float(getattr(balance, 'buying_power', net_liq * 0.5))
                    cash_balance = float(getattr(balance, 'cash_balance', 0))
                    day_trading_bp = float(getattr(balance, 'day_trading_buying_power', 0))
                    
                    return {
                        'net_liquidation_value': net_liq,
                        'buying_power': buying_power,
                        'cash_balance': cash_balance,
                        'day_trading_buying_power': day_trading_bp
                    }
            return None
        except Exception as e:
            self.logger.error(f"❌ Error getting account data: {e}")
            return None
    
    def _get_portfolio_analysis(self, account_number: str) -> Dict[str, Any]:
        """Analyze current portfolio composition and risk metrics"""
        try:
            with self.tracker.positions_lock:
                account_positions = [
                    pos for pos in self.tracker.positions.values() 
                    if pos['account_number'] == account_number
                ]
            
            # Calculate portfolio metrics
            total_notional = sum(pos['notional'] for pos in account_positions)
            total_delta = sum(pos['position_delta'] for pos in account_positions)
            
            # Calculate concentration by symbol
            symbol_exposure = {}
            for pos in account_positions:
                symbol = pos['underlying_symbol']
                symbol_exposure[symbol] = symbol_exposure.get(symbol, 0) + abs(pos['notional'])
            
            return {
                'total_positions': len(account_positions),
                'total_notional': total_notional,
                'total_delta': total_delta,
                'symbol_exposure': symbol_exposure,
                'positions': account_positions
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error analyzing portfolio: {e}")
            return {}
    
    def _analyze_strategy_risk(self, strategy_data: Dict[str, Any]) -> Dict[str, float]:
        """Analyze risk metrics for a specific strategy"""
        try:
            # For put credit spreads
            if strategy_data.get('strategy_type') == 'put_credit_spread':
                short_strike = strategy_data.get('short_leg', {}).get('strike_price', 0)
                long_strike = strategy_data.get('long_leg', {}).get('strike_price', 0)
                net_premium = strategy_data.get('net_premium', 0)
                
                # Max loss = spread width - premium received
                spread_width = short_strike - long_strike
                max_loss_per_contract = (spread_width - net_premium) * 100
                
                return {
                    'max_loss_per_contract': max(max_loss_per_contract, 50),  # Minimum $50 risk
                    'max_profit_per_contract': net_premium * 100,
                    'profit_probability': strategy_data.get('profit_probability', 0.7),
                    'spread_width': spread_width,
                    'net_premium': net_premium
                }
            
            # Default fallback
            return {
                'max_loss_per_contract': 500,  # Default $500 max loss
                'max_profit_per_contract': 100,
                'profit_probability': 0.5,
                'spread_width': 5,
                'net_premium': 1.0
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error analyzing strategy risk: {e}")
            return {'max_loss_per_contract': 500, 'max_profit_per_contract': 100, 'profit_probability': 0.5}
    
    def _apply_position_constraints(self, base_quantity: int, strategy_data: Dict[str, Any],
                                  portfolio_data: Dict[str, Any], risk_params: RiskParameters,
                                  account_data: Dict[str, Any]) -> int:
        """Apply various position size constraints"""
        
        constrained_quantity = base_quantity
        net_liq = account_data['net_liquidation_value']
        
        # Constraint 1: Maximum single position size
        strategy_notional_per_contract = strategy_data.get('notional_per_contract', 5000)
        max_position_value = net_liq * (risk_params.max_single_position_pct / 100)
        max_qty_by_position_size = int(max_position_value / strategy_notional_per_contract)
        constrained_quantity = min(constrained_quantity, max_qty_by_position_size)
        
        # Constraint 2: Symbol concentration limits
        symbol = strategy_data.get('underlying_symbol', '')
        current_symbol_exposure = portfolio_data.get('symbol_exposure', {}).get(symbol, 0)
        max_symbol_exposure = net_liq * (risk_params.max_sector_concentration_pct / 100)
        additional_exposure_allowed = max_symbol_exposure - current_symbol_exposure
        max_qty_by_concentration = int(additional_exposure_allowed / strategy_notional_per_contract)
        constrained_quantity = min(constrained_quantity, max(0, max_qty_by_concentration))
        
        # Constraint 3: Buying power limits
        buying_power_per_contract = self._estimate_buying_power_per_contract(strategy_data)
        max_buying_power_usage = account_data['buying_power'] * (risk_params.max_buying_power_usage_pct / 100)
        max_qty_by_buying_power = int(max_buying_power_usage / buying_power_per_contract)
        constrained_quantity = min(constrained_quantity, max_qty_by_buying_power)
        
        # Constraint 4: Premium limits
        net_premium = strategy_data.get('net_premium', 1.0)
        if net_premium < risk_params.min_trade_premium:
            constrained_quantity = 0  # Skip trades with too little premium
        elif net_premium > risk_params.max_trade_premium:
            # Reduce size for very high premium trades
            constrained_quantity = int(constrained_quantity * 0.5)
        
        # Minimum quantity of 1 if any constraints allow it
        return max(0, constrained_quantity)
    
    def _calculate_buying_power_requirement(self, quantity: int, strategy_data: Dict[str, Any]) -> float:
        """Estimate buying power requirement for the trade"""
        if strategy_data.get('strategy_type') == 'put_credit_spread':
            # For credit spreads, buying power ≈ max loss potential
            short_strike = strategy_data.get('short_leg', {}).get('strike_price', 0)
            long_strike = strategy_data.get('long_leg', {}).get('strike_price', 0)
            net_premium = strategy_data.get('net_premium', 0)
            
            spread_width = short_strike - long_strike
            max_loss_per_contract = (spread_width - net_premium) * 100
            
            return quantity * max_loss_per_contract
        
        # Default estimate
        return quantity * 1000
    
    def _estimate_buying_power_per_contract(self, strategy_data: Dict[str, Any]) -> float:
        """Estimate buying power requirement per contract"""
        return self._calculate_buying_power_requirement(1, strategy_data)
    
    def _assess_concentration_impact(self, strategy_data: Dict[str, Any], quantity: int,
                                   portfolio_data: Dict[str, Any]) -> Dict[str, float]:
        """Assess the concentration impact of adding this position"""
        symbol = strategy_data.get('underlying_symbol', '')
        strategy_notional_per_contract = strategy_data.get('notional_per_contract', 5000)
        new_exposure = quantity * strategy_notional_per_contract
        
        current_symbol_exposure = portfolio_data.get('symbol_exposure', {}).get(symbol, 0)
        total_portfolio_notional = portfolio_data.get('total_notional', 1)
        
        # Calculate concentration percentages
        current_concentration = (current_symbol_exposure / total_portfolio_notional) * 100 if total_portfolio_notional > 0 else 0
        new_concentration = ((current_symbol_exposure + new_exposure) / (total_portfolio_notional + new_exposure)) * 100
        
        return {
            'symbol': symbol,
            'current_concentration_pct': current_concentration,
            'new_concentration_pct': new_concentration,
            'concentration_increase_pct': new_concentration - current_concentration
        }
    
    def _generate_risk_warnings(self, quantity: int, max_loss_pct: float,
                              concentration_impact: Dict[str, float], buying_power_required: float,
                              available_buying_power: float, risk_params: RiskParameters) -> List[str]:
        """Generate risk warnings based on position analysis"""
        warnings = []
        
        if quantity == 0:
            warnings.append("❌ Position size reduced to zero due to risk constraints")
            return warnings
        
        if max_loss_pct > risk_params.max_portfolio_risk_pct:
            warnings.append(f"⚠️ Max loss ({max_loss_pct:.1f}%) exceeds target risk ({risk_params.max_portfolio_risk_pct:.1f}%)")
        
        if concentration_impact.get('new_concentration_pct', 0) > risk_params.max_sector_concentration_pct:
            symbol = concentration_impact.get('symbol', 'Unknown')
            conc_pct = concentration_impact.get('new_concentration_pct', 0)
            warnings.append(f"⚠️ {symbol} concentration ({conc_pct:.1f}%) exceeds limit ({risk_params.max_sector_concentration_pct:.1f}%)")
        
        if buying_power_required > available_buying_power * 0.8:
            warnings.append(f"⚠️ High buying power usage: ${buying_power_required:,.0f} of ${available_buying_power:,.0f}")
        
        return warnings
    
    def _calculate_risk_score(self, max_loss_pct: float, concentration_impact: Dict[str, float]) -> str:
        """Calculate overall risk score for the position"""
        score = 0
        
        # Risk from portfolio percentage
        if max_loss_pct > 3.0:
            score += 2
        elif max_loss_pct > 1.5:
            score += 1
        
        # Risk from concentration
        if concentration_impact.get('new_concentration_pct', 0) > 20:
            score += 2
        elif concentration_impact.get('new_concentration_pct', 0) > 10:
            score += 1
        
        # Return risk level
        if score >= 3:
            return "High"
        elif score >= 1:
            return "Medium"
        else:
            return "Low"
    
    def get_portfolio_risk_summary(self, account_number: str) -> Dict[str, Any]:
        """Generate comprehensive portfolio risk summary"""
        try:
            account_data = self._get_account_data(account_number)
            portfolio_data = self._get_portfolio_analysis(account_number)
            
            if not account_data or not portfolio_data:
                return {'error': 'Could not retrieve portfolio data'}
            
            net_liq = account_data['net_liquidation_value']
            total_notional = portfolio_data['total_notional']
            
            # Calculate portfolio metrics (ensure all values are float)
            net_liq = float(net_liq)
            total_notional = float(total_notional)
            portfolio_leverage = (total_notional / net_liq) if net_liq > 0 else 0
            delta_exposure = float(portfolio_data['total_delta'])
            
            # Symbol concentration analysis
            symbol_concentrations = {}
            for symbol, exposure in portfolio_data.get('symbol_exposure', {}).items():
                exposure = float(exposure)
                concentration_pct = (exposure / total_notional) * 100 if total_notional > 0 else 0
                symbol_concentrations[symbol] = {
                    'exposure': exposure,
                    'concentration_pct': concentration_pct
                }
            
            # Risk level assessment
            risk_flags = []
            if portfolio_leverage > 2.0:
                risk_flags.append("High leverage")
            if abs(delta_exposure) > 100:
                risk_flags.append("High delta exposure")
            
            # Top concentrations
            top_concentrations = sorted(
                symbol_concentrations.items(), 
                key=lambda x: x[1]['concentration_pct'], 
                reverse=True
            )[:5]
            
            return {
                'account_number': account_number,
                'net_liquidation_value': net_liq,
                'total_notional': total_notional,
                'portfolio_leverage': portfolio_leverage,
                'delta_exposure': delta_exposure,
                'total_positions': portfolio_data['total_positions'],
                'symbol_concentrations': symbol_concentrations,
                'top_concentrations': top_concentrations,
                'risk_flags': risk_flags,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error generating portfolio risk summary: {e}")
            return {'error': str(e)}