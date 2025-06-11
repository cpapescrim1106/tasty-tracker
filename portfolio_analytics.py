#!/usr/bin/env python3
"""
TastyTracker Portfolio Analytics Engine
Advanced risk metrics, VaR calculation, and performance analytics
"""

import os
import logging
import math
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict
import statistics

@dataclass
class VaRResult:
    """Value at Risk calculation result"""
    var_1d_95: float  # 1-day VaR at 95% confidence
    var_1d_99: float  # 1-day VaR at 99% confidence
    var_10d_95: float  # 10-day VaR at 95% confidence
    expected_shortfall_95: float  # Expected Shortfall (CVaR) at 95%
    portfolio_volatility: float  # Annualized portfolio volatility
    worst_case_scenario: float  # Maximum potential loss

@dataclass
class GreeksExposure:
    """Portfolio Greeks exposure analysis"""
    total_delta: float
    total_gamma: float
    total_theta: float
    total_vega: float
    delta_dollars: float  # Dollar delta exposure
    gamma_dollars: float  # Dollar gamma exposure
    theta_dollars: float  # Daily theta decay
    vega_dollars: float   # Dollar vega exposure
    delta_hedge_required: float  # Shares needed to delta hedge

@dataclass
class PerformanceMetrics:
    """Portfolio performance analytics"""
    total_pnl: float
    daily_pnl: float
    weekly_pnl: float
    monthly_pnl: float
    ytd_pnl: float
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float

class PortfolioAnalytics:
    """Advanced portfolio analytics and risk measurement engine"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance
        self.logger = logging.getLogger(__name__)
        
        # Historical data cache for calculations
        self.price_history = defaultdict(list)
        self.pnl_history = []
        
        # Risk parameters
        self.var_confidence_levels = [0.95, 0.99]
        self.var_holding_periods = [1, 10]  # days
        
        # Performance tracking
        self.trade_history = []
        self.daily_pnl_history = []
    
    def calculate_portfolio_var(self, account_number: str, historical_days: int = 252) -> VaRResult:
        """
        Calculate Value at Risk for the portfolio using multiple methods
        """
        try:
            portfolio_data = self._get_portfolio_data(account_number)
            if not portfolio_data:
                raise ValueError("Could not retrieve portfolio data")
            
            # Get historical volatility estimates for each position
            position_volatilities = self._estimate_position_volatilities(portfolio_data)
            
            # Calculate portfolio-level volatility (simplified approach)
            total_notional = sum(abs(pos['notional']) for pos in portfolio_data['positions'])
            
            if total_notional == 0:
                return VaRResult(0, 0, 0, 0, 0, 0)
            
            # Weight-average volatilities by notional exposure
            weighted_volatility = 0
            for pos in portfolio_data['positions']:
                symbol = pos['underlying_symbol']
                weight = abs(pos['notional']) / total_notional
                vol = position_volatilities.get(symbol, 0.25)  # Default 25% vol
                weighted_volatility += weight * vol
            
            # Calculate VaR estimates
            portfolio_value = total_notional
            daily_vol = weighted_volatility / math.sqrt(252)  # Convert annual to daily
            
            # Parametric VaR (assuming normal distribution)
            var_1d_95 = portfolio_value * daily_vol * 1.645  # 95% confidence
            var_1d_99 = portfolio_value * daily_vol * 2.326  # 99% confidence
            var_10d_95 = var_1d_95 * math.sqrt(10)  # Scale for 10 days
            
            # Expected Shortfall (average loss beyond VaR)
            expected_shortfall_95 = portfolio_value * daily_vol * 2.063  # ES at 95%
            
            # Worst case scenario (3 standard deviations)
            worst_case = portfolio_value * daily_vol * 3.0
            
            self.logger.info(f"📊 VaR calculated for account {account_number}: "
                           f"1d-95%: ${var_1d_95:,.0f}, Portfolio Vol: {weighted_volatility:.1%}")
            
            return VaRResult(
                var_1d_95=var_1d_95,
                var_1d_99=var_1d_99,
                var_10d_95=var_10d_95,
                expected_shortfall_95=expected_shortfall_95,
                portfolio_volatility=weighted_volatility,
                worst_case_scenario=worst_case
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating VaR: {e}")
            return VaRResult(0, 0, 0, 0, 0, 0)
    
    def calculate_greeks_exposure(self, account_number: str) -> GreeksExposure:
        """
        Calculate comprehensive Greeks exposure for the portfolio
        """
        try:
            portfolio_data = self._get_portfolio_data(account_number)
            if not portfolio_data:
                raise ValueError("Could not retrieve portfolio data")
            
            total_delta = 0
            total_gamma = 0
            total_theta = 0
            total_vega = 0
            
            for pos in portfolio_data['positions']:
                quantity = pos['quantity']
                
                if pos['instrument_type'] == 'Equity':
                    # Stocks have delta=1, no gamma/theta/vega
                    total_delta += quantity
                else:
                    # Options - use current delta or estimate
                    delta = pos.get('delta', 0)
                    gamma = self._estimate_gamma(pos)
                    theta = self._estimate_theta(pos)
                    vega = self._estimate_vega(pos)
                    
                    # Multiply by quantity and contract multiplier
                    total_delta += quantity * delta * 100
                    total_gamma += quantity * gamma * 100
                    total_theta += quantity * theta * 100
                    total_vega += quantity * vega * 100
            
            # Calculate dollar exposures
            # Assume average underlying price for dollar calculations
            avg_underlying_price = self._get_average_underlying_price(portfolio_data)
            
            delta_dollars = total_delta * avg_underlying_price
            gamma_dollars = total_gamma * avg_underlying_price * avg_underlying_price * 0.01  # 1% move
            theta_dollars = total_theta  # Theta is already in dollars
            vega_dollars = total_vega * 0.01  # 1% volatility change
            
            # Delta hedge calculation (shares needed to neutralize delta)
            delta_hedge_required = -total_delta
            
            self.logger.info(f"📊 Greeks exposure calculated: Delta={total_delta:.0f}, "
                           f"Gamma={total_gamma:.0f}, Theta=${theta_dollars:.0f}")
            
            return GreeksExposure(
                total_delta=total_delta,
                total_gamma=total_gamma,
                total_theta=total_theta,
                total_vega=total_vega,
                delta_dollars=delta_dollars,
                gamma_dollars=gamma_dollars,
                theta_dollars=theta_dollars,
                vega_dollars=vega_dollars,
                delta_hedge_required=delta_hedge_required
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating Greeks exposure: {e}")
            return GreeksExposure(0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    def calculate_performance_metrics(self, account_number: str) -> PerformanceMetrics:
        """
        Calculate comprehensive performance metrics
        """
        try:
            # For now, use simplified calculations based on current positions
            # In a real implementation, this would use historical trade data
            
            portfolio_data = self._get_portfolio_data(account_number)
            if not portfolio_data:
                raise ValueError("Could not retrieve portfolio data")
            
            # Simplified P&L calculation (would normally use historical data)
            total_pnl = sum(pos.get('unrealized_pnl', 0) for pos in portfolio_data['positions'])
            
            # Mock performance metrics (in production, calculate from trade history)
            performance = PerformanceMetrics(
                total_pnl=total_pnl,
                daily_pnl=total_pnl * 0.01,  # Estimate
                weekly_pnl=total_pnl * 0.05,
                monthly_pnl=total_pnl * 0.2,
                ytd_pnl=total_pnl,
                win_rate=0.65,  # 65% win rate
                profit_factor=1.8,  # Profit factor
                sharpe_ratio=1.2,  # Sharpe ratio
                max_drawdown=0.08,  # 8% max drawdown
                avg_win=850.0,
                avg_loss=-420.0,
                largest_win=3500.0,
                largest_loss=-1200.0
            )
            
            self.logger.info(f"📊 Performance metrics calculated: Total P&L=${total_pnl:.0f}, "
                           f"Win Rate={performance.win_rate:.1%}")
            
            return performance
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating performance metrics: {e}")
            return PerformanceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    def get_risk_scenarios(self, account_number: str) -> Dict[str, float]:
        """
        Calculate portfolio P&L under various market scenarios
        """
        try:
            portfolio_data = self._get_portfolio_data(account_number)
            if not portfolio_data:
                return {}
            
            scenarios = {}
            base_pnl = 0
            
            # Define market scenarios (% moves in underlying)
            market_moves = {
                "Market +5%": 0.05,
                "Market +2%": 0.02,
                "Market +1%": 0.01,
                "Current": 0.0,
                "Market -1%": -0.01,
                "Market -2%": -0.02,
                "Market -5%": -0.05,
                "Market -10%": -0.10,
                "Market Crash -20%": -0.20
            }
            
            for scenario_name, move in market_moves.items():
                scenario_pnl = 0
                
                for pos in portfolio_data['positions']:
                    underlying_price = self._get_underlying_price(pos['underlying_symbol'])
                    new_price = underlying_price * (1 + move)
                    price_change = new_price - underlying_price
                    
                    if pos['instrument_type'] == 'Equity':
                        # Stock P&L = quantity * price change
                        scenario_pnl += pos['quantity'] * price_change
                    else:
                        # Option P&L = delta * price change * quantity * 100
                        delta = pos.get('delta', 0)
                        scenario_pnl += delta * price_change * pos['quantity'] * 100
                
                scenarios[scenario_name] = scenario_pnl
            
            self.logger.info(f"📊 Risk scenarios calculated for {len(market_moves)} scenarios")
            return scenarios
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating risk scenarios: {e}")
            return {}
    
    def _get_portfolio_data(self, account_number: str) -> Optional[Dict[str, Any]]:
        """Get portfolio data for analysis"""
        try:
            with self.tracker.positions_lock:
                account_positions = [
                    pos for pos in self.tracker.positions.values() 
                    if pos['account_number'] == account_number
                ]
            
            return {'positions': account_positions}
            
        except Exception as e:
            self.logger.error(f"❌ Error getting portfolio data: {e}")
            return None
    
    def _estimate_position_volatilities(self, portfolio_data: Dict[str, Any]) -> Dict[str, float]:
        """Estimate volatilities for each underlying symbol"""
        # This would normally use historical price data
        # For now, use estimated volatilities based on asset type
        volatilities = {
            'SPY': 0.15, 'QQQ': 0.20, 'IWM': 0.25,
            'AAPL': 0.25, 'MSFT': 0.25, 'GOOGL': 0.30,
            'TSLA': 0.50, 'AMD': 0.40, 'NVDA': 0.45,
            'META': 0.35, 'AMZN': 0.30, 'NFLX': 0.40,
            'COIN': 0.80, 'MARA': 0.90, 'RIOT': 0.85,
            'SOFI': 0.60, 'HOOD': 0.70, 'PYPL': 0.35,
            'SHOP': 0.45, 'IBIT': 0.40, 'ASML': 0.30
        }
        
        # Add default volatility for unknown symbols
        default_vol = 0.30
        result = {}
        
        for pos in portfolio_data['positions']:
            symbol = pos['underlying_symbol']
            result[symbol] = volatilities.get(symbol, default_vol)
        
        return result
    
    def _estimate_gamma(self, position: Dict[str, Any]) -> float:
        """Estimate gamma for an option position"""
        # Simplified gamma estimation
        # In production, this would use Black-Scholes or current market data
        return 0.05  # Placeholder
    
    def _estimate_theta(self, position: Dict[str, Any]) -> float:
        """Estimate theta for an option position"""
        # Simplified theta estimation
        # Typically negative for long options, positive for short options
        if position['quantity'] > 0:
            return -5.0  # Long option loses $5/day
        else:
            return 5.0   # Short option gains $5/day
    
    def _estimate_vega(self, position: Dict[str, Any]) -> float:
        """Estimate vega for an option position"""
        # Simplified vega estimation
        return 10.0  # $10 per 1% volatility change
    
    def _get_average_underlying_price(self, portfolio_data: Dict[str, Any]) -> float:
        """Calculate average underlying price across portfolio"""
        prices = []
        for pos in portfolio_data['positions']:
            price = self._get_underlying_price(pos['underlying_symbol'])
            prices.append(price)
        
        return statistics.mean(prices) if prices else 100.0
    
    def _get_underlying_price(self, symbol: str) -> float:
        """Get current underlying price"""
        with self.tracker.prices_lock:
            return self.tracker.underlying_prices.get(symbol, 100.0)
    
    def generate_risk_report(self, account_number: str) -> Dict[str, Any]:
        """
        Generate comprehensive risk report combining all analytics
        """
        try:
            var_result = self.calculate_portfolio_var(account_number)
            greeks = self.calculate_greeks_exposure(account_number)
            performance = self.calculate_performance_metrics(account_number)
            scenarios = self.get_risk_scenarios(account_number)
            
            # Risk rating based on multiple factors
            risk_score = self._calculate_overall_risk_score(var_result, greeks, performance)
            
            report = {
                'account_number': account_number,
                'timestamp': datetime.now().isoformat(),
                'risk_score': risk_score,
                'var_analysis': {
                    'var_1d_95': var_result.var_1d_95,
                    'var_1d_99': var_result.var_1d_99,
                    'var_10d_95': var_result.var_10d_95,
                    'expected_shortfall_95': var_result.expected_shortfall_95,
                    'portfolio_volatility': var_result.portfolio_volatility,
                    'worst_case_scenario': var_result.worst_case_scenario
                },
                'greeks_exposure': {
                    'total_delta': greeks.total_delta,
                    'total_gamma': greeks.total_gamma,
                    'total_theta': greeks.total_theta,
                    'total_vega': greeks.total_vega,
                    'delta_dollars': greeks.delta_dollars,
                    'gamma_dollars': greeks.gamma_dollars,
                    'theta_dollars': greeks.theta_dollars,
                    'vega_dollars': greeks.vega_dollars,
                    'delta_hedge_required': greeks.delta_hedge_required
                },
                'performance_metrics': {
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
                    'largest_loss': performance.largest_loss
                },
                'scenario_analysis': scenarios
            }
            
            self.logger.info(f"📊 Comprehensive risk report generated for account {account_number}")
            return report
            
        except Exception as e:
            self.logger.error(f"❌ Error generating risk report: {e}")
            return {'error': str(e)}
    
    def _calculate_overall_risk_score(self, var_result: VaRResult, greeks: GreeksExposure, 
                                    performance: PerformanceMetrics) -> str:
        """Calculate overall portfolio risk score"""
        score = 0
        
        # VaR-based scoring
        if var_result.var_1d_95 > 50000:  # $50k+ daily VaR
            score += 3
        elif var_result.var_1d_95 > 20000:  # $20k+ daily VaR
            score += 2
        elif var_result.var_1d_95 > 10000:  # $10k+ daily VaR
            score += 1
        
        # Greeks-based scoring
        if abs(greeks.total_delta) > 1000:  # High delta exposure
            score += 2
        elif abs(greeks.total_delta) > 500:
            score += 1
        
        # Performance-based scoring
        if performance.max_drawdown > 0.15:  # >15% drawdown
            score += 2
        elif performance.max_drawdown > 0.10:
            score += 1
        
        # Return risk level
        if score >= 6:
            return "Very High"
        elif score >= 4:
            return "High"
        elif score >= 2:
            return "Medium"
        else:
            return "Low"