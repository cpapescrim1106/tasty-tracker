#!/usr/bin/env python3
"""
TastyTracker Delta Hedging Engine
Automated portfolio rebalancing based on delta neutrality targets
"""

import os
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

@dataclass
class HedgeRecommendation:
    """Delta hedge recommendation"""
    account_number: str
    current_delta: float
    target_delta: float
    delta_imbalance: float
    hedge_required: bool
    recommended_action: str  # "BUY", "SELL", "NONE"
    hedge_symbol: str  # Symbol to hedge with (SPY, QQQ, etc.)
    hedge_quantity: int  # Shares to buy/sell
    hedge_cost: float  # Estimated cost of hedge
    confidence: float  # Confidence in recommendation (0-1)
    warnings: List[str]

@dataclass
class RebalanceTarget:
    """Portfolio rebalancing target configuration"""
    target_delta: float = 0.0  # Target portfolio delta
    delta_tolerance: float = 50.0  # Delta tolerance before hedging
    max_hedge_cost_pct: float = 1.0  # Max hedge cost as % of portfolio
    hedge_symbols: List[str] = None  # Preferred hedging instruments
    auto_execute: bool = False  # Whether to auto-execute hedges
    rebalance_frequency: str = "daily"  # daily, weekly, monthly

class HedgeEngine:
    """Delta hedging and portfolio rebalancing engine"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance
        self.logger = logging.getLogger(__name__)
        
        # Default hedge symbols (liquid ETFs)
        self.default_hedge_symbols = ["SPY", "QQQ", "IWM", "DIA"]
        
        # Delta calculation cache
        self.delta_cache = {}
        self.last_calculation = {}
        
        # Hedge execution tracking
        self.pending_hedges = {}
        self.hedge_history = []
    
    def calculate_portfolio_delta(self, account_number: str) -> Dict[str, float]:
        """Calculate comprehensive portfolio delta metrics"""
        try:
            with self.tracker.positions_lock:
                account_positions = [
                    pos for pos in self.tracker.positions.values() 
                    if pos['account_number'] == account_number
                ]
            
            if not account_positions:
                return {'total_delta': 0, 'equity_delta': 0, 'options_delta': 0, 'symbol_deltas': {}}
            
            total_delta = 0
            equity_delta = 0
            options_delta = 0
            symbol_deltas = {}
            
            for pos in account_positions:
                position_delta = pos.get('position_delta', 0)
                symbol = pos['underlying_symbol']
                
                # Accumulate by symbol
                if symbol not in symbol_deltas:
                    symbol_deltas[symbol] = 0
                symbol_deltas[symbol] += position_delta
                
                # Accumulate by instrument type
                if pos['instrument_type'] == 'Equity':
                    equity_delta += position_delta
                else:
                    options_delta += position_delta
                
                total_delta += position_delta
            
            return {
                'total_delta': float(total_delta),
                'equity_delta': float(equity_delta),
                'options_delta': float(options_delta),
                'symbol_deltas': {k: float(v) for k, v in symbol_deltas.items()},
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating portfolio delta: {e}")
            return {'total_delta': 0, 'equity_delta': 0, 'options_delta': 0, 'symbol_deltas': {}}
    
    def analyze_hedge_requirement(self, account_number: str, 
                                target: RebalanceTarget) -> HedgeRecommendation:
        """Analyze if hedging is needed and recommend action"""
        try:
            delta_metrics = self.calculate_portfolio_delta(account_number)
            current_delta = delta_metrics['total_delta']
            target_delta = target.target_delta
            delta_imbalance = current_delta - target_delta
            
            # Check if hedge is required
            hedge_required = abs(delta_imbalance) > target.delta_tolerance
            
            if not hedge_required:
                return HedgeRecommendation(
                    account_number=account_number,
                    current_delta=current_delta,
                    target_delta=target_delta,
                    delta_imbalance=delta_imbalance,
                    hedge_required=False,
                    recommended_action="NONE",
                    hedge_symbol="",
                    hedge_quantity=0,
                    hedge_cost=0,
                    confidence=1.0,
                    warnings=[]
                )
            
            # Determine hedge direction and symbol
            if delta_imbalance > 0:
                # Portfolio is too long delta, need to sell hedge instrument
                recommended_action = "SELL"
            else:
                # Portfolio is too short delta, need to buy hedge instrument
                recommended_action = "BUY"
            
            # Select best hedge symbol
            hedge_symbol = self._select_hedge_symbol(account_number, target.hedge_symbols)
            
            # Calculate hedge quantity
            hedge_quantity = self._calculate_hedge_quantity(
                delta_imbalance, hedge_symbol, recommended_action
            )
            
            # Estimate hedge cost
            hedge_cost = self._estimate_hedge_cost(hedge_symbol, hedge_quantity)
            
            # Calculate confidence
            confidence = self._calculate_hedge_confidence(
                account_number, hedge_symbol, hedge_quantity, hedge_cost, target
            )
            
            # Generate warnings
            warnings = self._generate_hedge_warnings(
                account_number, hedge_cost, target
            )
            
            self.logger.info(f"📊 Hedge analysis for {account_number}: "
                           f"Current Δ={current_delta:.0f}, Target Δ={target_delta:.0f}, "
                           f"Imbalance={delta_imbalance:.0f}, Action={recommended_action} "
                           f"{hedge_quantity} {hedge_symbol}")
            
            return HedgeRecommendation(
                account_number=account_number,
                current_delta=current_delta,
                target_delta=target_delta,
                delta_imbalance=delta_imbalance,
                hedge_required=hedge_required,
                recommended_action=recommended_action,
                hedge_symbol=hedge_symbol,
                hedge_quantity=hedge_quantity,
                hedge_cost=hedge_cost,
                confidence=confidence,
                warnings=warnings
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error analyzing hedge requirement: {e}")
            return HedgeRecommendation(
                account_number=account_number,
                current_delta=0,
                target_delta=target.target_delta,
                delta_imbalance=0,
                hedge_required=False,
                recommended_action="ERROR",
                hedge_symbol="",
                hedge_quantity=0,
                hedge_cost=0,
                confidence=0,
                warnings=[f"Analysis error: {str(e)}"]
            )
    
    def _select_hedge_symbol(self, account_number: str, 
                           preferred_symbols: Optional[List[str]] = None) -> str:
        """Select the best hedge symbol based on portfolio composition"""
        try:
            # Get portfolio symbol exposure
            delta_metrics = self.calculate_portfolio_delta(account_number)
            symbol_deltas = delta_metrics.get('symbol_deltas', {})
            
            # If no specific preferences, use defaults
            candidates = preferred_symbols or self.default_hedge_symbols
            
            # Score each candidate based on portfolio correlation
            best_symbol = "SPY"  # Default fallback
            best_score = 0
            
            for symbol in candidates:
                score = self._score_hedge_symbol(symbol, symbol_deltas)
                if score > best_score:
                    best_score = score
                    best_symbol = symbol
            
            return best_symbol
            
        except Exception as e:
            self.logger.error(f"❌ Error selecting hedge symbol: {e}")
            return "SPY"  # Safe default
    
    def _score_hedge_symbol(self, hedge_symbol: str, symbol_deltas: Dict[str, float]) -> float:
        """Score a hedge symbol based on portfolio composition"""
        # Simple scoring based on symbol coverage
        score = 0.5  # Base score
        
        # Tech-heavy portfolio → prefer QQQ
        tech_symbols = ["AAPL", "MSFT", "GOOGL", "META", "TSLA", "NVDA", "AMD"]
        tech_exposure = sum(abs(symbol_deltas.get(sym, 0)) for sym in tech_symbols)
        
        if hedge_symbol == "QQQ" and tech_exposure > 100:
            score += 0.3
        
        # Broad market → prefer SPY
        if hedge_symbol == "SPY":
            score += 0.2  # Always good default
        
        # Small cap exposure → prefer IWM
        small_cap_symbols = ["IWM", "SHOP", "SOFI", "HOOD"]
        small_cap_exposure = sum(abs(symbol_deltas.get(sym, 0)) for sym in small_cap_symbols)
        
        if hedge_symbol == "IWM" and small_cap_exposure > 50:
            score += 0.2
        
        return score
    
    def _calculate_hedge_quantity(self, delta_imbalance: float, 
                                hedge_symbol: str, action: str) -> int:
        """Calculate the number of shares needed to hedge delta"""
        try:
            # Get current price of hedge symbol
            with self.tracker.prices_lock:
                hedge_price = self.tracker.underlying_prices.get(hedge_symbol, 100.0)
            
            # For equity hedging, delta = 1 per share
            # So shares needed = delta_imbalance
            raw_quantity = abs(delta_imbalance)
            
            # Round to reasonable lot sizes
            if raw_quantity < 10:
                return int(raw_quantity)
            elif raw_quantity < 100:
                return int(round(raw_quantity / 5) * 5)  # Round to 5s
            else:
                return int(round(raw_quantity / 10) * 10)  # Round to 10s
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating hedge quantity: {e}")
            return 0
    
    def _estimate_hedge_cost(self, hedge_symbol: str, quantity: int) -> float:
        """Estimate the cost of executing the hedge"""
        try:
            with self.tracker.prices_lock:
                price = self.tracker.underlying_prices.get(hedge_symbol, 100.0)
            
            # Base cost
            cost = abs(quantity) * price
            
            # Add estimated transaction costs (spread + commission)
            spread_cost = cost * 0.001  # 0.1% for spread
            commission = 1.0  # $1 commission estimate
            
            return cost + spread_cost + commission
            
        except Exception as e:
            self.logger.error(f"❌ Error estimating hedge cost: {e}")
            return 0
    
    def _calculate_hedge_confidence(self, account_number: str, hedge_symbol: str,
                                  quantity: int, cost: float, target: RebalanceTarget) -> float:
        """Calculate confidence in the hedge recommendation"""
        confidence = 1.0
        
        try:
            # Get account data
            with self.tracker.balances_lock:
                balance = self.tracker.account_balances.get(account_number)
                if balance:
                    net_liq = float(balance.net_liquidating_value)
                    cost_pct = (cost / net_liq) * 100
                    
                    # Reduce confidence if cost is high
                    if cost_pct > target.max_hedge_cost_pct:
                        confidence *= 0.5
                    
                    # Reduce confidence for very small hedges (may not be worth it)
                    if quantity < 5:
                        confidence *= 0.7
                    
                    # Reduce confidence for very large hedges
                    if cost_pct > 5.0:
                        confidence *= 0.3
            
            return max(0.1, confidence)  # Minimum 10% confidence
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating hedge confidence: {e}")
            return 0.5
    
    def _generate_hedge_warnings(self, account_number: str, hedge_cost: float,
                               target: RebalanceTarget) -> List[str]:
        """Generate warnings for hedge recommendation"""
        warnings = []
        
        try:
            with self.tracker.balances_lock:
                balance = self.tracker.account_balances.get(account_number)
                if balance:
                    net_liq = float(balance.net_liquidating_value)
                    cost_pct = (hedge_cost / net_liq) * 100
                    
                    if cost_pct > target.max_hedge_cost_pct:
                        warnings.append(f"⚠️ Hedge cost ({cost_pct:.1f}%) exceeds target limit ({target.max_hedge_cost_pct:.1f}%)")
                    
                    if cost_pct > 5.0:
                        warnings.append(f"⚠️ Large hedge cost: ${hedge_cost:,.0f} ({cost_pct:.1f}% of portfolio)")
                    
                    # Check buying power
                    buying_power = getattr(balance, 'buying_power', net_liq * 0.5)
                    if hedge_cost > float(buying_power) * 0.8:
                        warnings.append(f"⚠️ Hedge may require significant buying power: ${hedge_cost:,.0f}")
            
        except Exception as e:
            warnings.append(f"⚠️ Could not validate hedge parameters: {str(e)}")
        
        return warnings
    
    def get_portfolio_rebalance_summary(self, account_number: str) -> Dict[str, Any]:
        """Get comprehensive portfolio rebalancing summary"""
        try:
            # Calculate current delta metrics
            delta_metrics = self.calculate_portfolio_delta(account_number)
            
            # Analyze with different target configurations
            conservative_target = RebalanceTarget(target_delta=0, delta_tolerance=25)
            moderate_target = RebalanceTarget(target_delta=0, delta_tolerance=50)
            aggressive_target = RebalanceTarget(target_delta=0, delta_tolerance=100)
            
            hedge_scenarios = {
                'conservative': self.analyze_hedge_requirement(account_number, conservative_target),
                'moderate': self.analyze_hedge_requirement(account_number, moderate_target),
                'aggressive': self.analyze_hedge_requirement(account_number, aggressive_target)
            }
            
            # Calculate portfolio exposure by symbol
            symbol_exposures = []
            for symbol, delta in delta_metrics['symbol_deltas'].items():
                with self.tracker.prices_lock:
                    price = self.tracker.underlying_prices.get(symbol, 0)
                
                exposure = {
                    'symbol': symbol,
                    'delta': delta,
                    'dollar_exposure': delta * price,
                    'percentage': (abs(delta) / max(abs(delta_metrics['total_delta']), 1)) * 100
                }
                symbol_exposures.append(exposure)
            
            # Sort by absolute delta exposure
            symbol_exposures.sort(key=lambda x: abs(x['delta']), reverse=True)
            
            return {
                'account_number': account_number,
                'delta_metrics': delta_metrics,
                'hedge_scenarios': {
                    scenario: {
                        'hedge_required': rec.hedge_required,
                        'recommended_action': rec.recommended_action,
                        'hedge_symbol': rec.hedge_symbol,
                        'hedge_quantity': rec.hedge_quantity,
                        'hedge_cost': rec.hedge_cost,
                        'confidence': rec.confidence,
                        'warnings': rec.warnings,
                        'delta_imbalance': rec.delta_imbalance
                    } for scenario, rec in hedge_scenarios.items()
                },
                'symbol_exposures': symbol_exposures[:10],  # Top 10 exposures
                'rebalance_status': self._assess_rebalance_urgency(delta_metrics['total_delta']),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error generating rebalance summary: {e}")
            return {'error': str(e)}
    
    def _assess_rebalance_urgency(self, total_delta: float) -> Dict[str, Any]:
        """Assess urgency of portfolio rebalancing"""
        abs_delta = abs(total_delta)
        
        if abs_delta < 25:
            status = "LOW"
            urgency = "Portfolio delta is well balanced"
        elif abs_delta < 50:
            status = "MEDIUM"
            urgency = "Consider rebalancing if trend continues"
        elif abs_delta < 100:
            status = "HIGH"
            urgency = "Rebalancing recommended"
        else:
            status = "CRITICAL"
            urgency = "Immediate rebalancing strongly recommended"
        
        return {
            'status': status,
            'urgency': urgency,
            'delta_magnitude': abs_delta
        }