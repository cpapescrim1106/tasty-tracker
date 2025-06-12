#!/usr/bin/env python3
"""
TastyTracker Probability Calculator
Enhanced Black-Scholes calculations for POP, P50, POT and other probability metrics
"""

import math
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date
import numpy as np
from scipy.stats import norm
from dataclasses import dataclass

@dataclass
class ProbabilityMetrics:
    """Container for all probability calculations"""
    pop: float = 0.0  # Probability of Profit
    p50: float = 0.0  # Probability of 50% max profit  
    pot: float = 0.0  # Probability of Touching
    prob_itm: float = 0.0  # Probability of finishing in-the-money
    prob_max_profit: float = 0.0  # Probability of maximum profit
    expected_value: float = 0.0  # Expected value of trade
    kelly_criterion: float = 0.0  # Kelly criterion bet sizing
    confidence_interval: Tuple[float, float] = (0.0, 0.0)  # 95% CI for final price

@dataclass
class OptionData:
    """Option contract data for calculations"""
    underlying_price: float
    strike_price: float
    time_to_expiry: float  # in years
    risk_free_rate: float
    volatility: float
    option_type: str  # 'call' or 'put'
    dividend_yield: float = 0.0

@dataclass
class SpreadData:
    """Data for spread strategy calculations"""
    underlying_price: float
    short_strike: float
    long_strike: float
    time_to_expiry: float
    risk_free_rate: float
    volatility: float
    strategy_type: str  # 'put_credit_spread', 'call_credit_spread', etc.
    credit_received: float = 0.0
    debit_paid: float = 0.0
    dividend_yield: float = 0.0

class EnhancedBlackScholes:
    """Enhanced Black-Scholes calculator with additional probability metrics"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def calculate_d1_d2(self, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> Tuple[float, float]:
        """Calculate d1 and d2 for Black-Scholes formula"""
        try:
            if T <= 0 or sigma <= 0:
                return 0.0, 0.0
            
            d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            
            return d1, d2
        except Exception as e:
            self.logger.error(f"Error calculating d1/d2: {e}")
            return 0.0, 0.0
    
    def calculate_option_price(self, option_data: OptionData) -> float:
        """Calculate theoretical option price using Black-Scholes"""
        try:
            S = option_data.underlying_price
            K = option_data.strike_price
            T = option_data.time_to_expiry
            r = option_data.risk_free_rate
            sigma = option_data.volatility
            q = option_data.dividend_yield
            
            d1, d2 = self.calculate_d1_d2(S, K, T, r, sigma, q)
            
            if option_data.option_type.lower() == 'call':
                price = (S * math.exp(-q * T) * norm.cdf(d1) - 
                        K * math.exp(-r * T) * norm.cdf(d2))
            else:  # put
                price = (K * math.exp(-r * T) * norm.cdf(-d2) - 
                        S * math.exp(-q * T) * norm.cdf(-d1))
            
            return max(price, 0.0)
            
        except Exception as e:
            self.logger.error(f"Error calculating option price: {e}")
            return 0.0
    
    def calculate_greeks(self, option_data: OptionData) -> Dict[str, float]:
        """Calculate option Greeks"""
        try:
            S = option_data.underlying_price
            K = option_data.strike_price  
            T = option_data.time_to_expiry
            r = option_data.risk_free_rate
            sigma = option_data.volatility
            q = option_data.dividend_yield
            
            if T <= 0:
                return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0}
            
            d1, d2 = self.calculate_d1_d2(S, K, T, r, sigma, q)
            
            # Delta
            if option_data.option_type.lower() == 'call':
                delta = math.exp(-q * T) * norm.cdf(d1)
            else:
                delta = -math.exp(-q * T) * norm.cdf(-d1)
            
            # Gamma (same for calls and puts)
            gamma = (math.exp(-q * T) * norm.pdf(d1)) / (S * sigma * math.sqrt(T))
            
            # Theta
            theta_term1 = -(S * norm.pdf(d1) * sigma * math.exp(-q * T)) / (2 * math.sqrt(T))
            
            if option_data.option_type.lower() == 'call':
                theta_term2 = r * K * math.exp(-r * T) * norm.cdf(d2)
                theta_term3 = -q * S * math.exp(-q * T) * norm.cdf(d1)
                theta = (theta_term1 - theta_term2 + theta_term3) / 365
            else:
                theta_term2 = -r * K * math.exp(-r * T) * norm.cdf(-d2)
                theta_term3 = q * S * math.exp(-q * T) * norm.cdf(-d1)
                theta = (theta_term1 + theta_term2 + theta_term3) / 365
            
            # Vega (same for calls and puts)
            vega = S * math.exp(-q * T) * norm.pdf(d1) * math.sqrt(T) / 100
            
            # Rho
            if option_data.option_type.lower() == 'call':
                rho = K * T * math.exp(-r * T) * norm.cdf(d2) / 100
            else:
                rho = -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100
            
            return {
                'delta': round(delta, 4),
                'gamma': round(gamma, 4),
                'theta': round(theta, 4),
                'vega': round(vega, 4),
                'rho': round(rho, 4)
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating Greeks: {e}")
            return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0}

class ProbabilityCalculator:
    """Main probability calculator for options strategies"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.bs = EnhancedBlackScholes()
    
    def calculate_single_option_probabilities(self, option_data: OptionData, 
                                            credit_received: float = 0.0) -> ProbabilityMetrics:
        """Calculate probabilities for single option positions"""
        try:
            S = option_data.underlying_price
            K = option_data.strike_price
            T = option_data.time_to_expiry
            r = option_data.risk_free_rate
            sigma = option_data.volatility
            
            if T <= 0:
                return ProbabilityMetrics()
            
            d1, d2 = self.bs.calculate_d1_d2(S, K, T, r, sigma, option_data.dividend_yield)
            
            metrics = ProbabilityMetrics()
            
            # Probability of finishing ITM
            if option_data.option_type.lower() == 'call':
                metrics.prob_itm = norm.cdf(d2) * 100
                metrics.pop = norm.cdf(-d2) * 100  # For short call: profit if price < strike
            else:  # put
                metrics.prob_itm = norm.cdf(-d2) * 100
                metrics.pop = norm.cdf(d2) * 100   # For short put: profit if price > strike
            
            # Probability of touching strike (barrier option formula)
            if S != K:
                barrier_prob = 2 * norm.cdf(abs(math.log(K/S)) / (sigma * math.sqrt(T)))
                metrics.pot = min(barrier_prob * 100, 100.0)
            else:
                metrics.pot = 50.0
            
            # P50 calculation for credit strategies
            if credit_received > 0:
                # For credit spreads: need underlying to stay away from short strike
                # P50 = probability of keeping 50% of credit
                target_profit = credit_received * 0.5
                
                if option_data.option_type.lower() == 'put':
                    # For short put: profit decreases as price goes down
                    target_price = K + target_profit  # Simplified
                    if target_price > 0:
                        d2_target = (math.log(S / target_price) + 
                                   (r - option_data.dividend_yield - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                        metrics.p50 = norm.cdf(d2_target) * 100
                else:  # call
                    target_price = K - target_profit  # Simplified
                    if target_price > 0:
                        d2_target = (math.log(S / target_price) + 
                                   (r - option_data.dividend_yield - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                        metrics.p50 = norm.cdf(-d2_target) * 100
            
            # Confidence interval for final price (95%)
            price_std = S * sigma * math.sqrt(T)
            lower_bound = S * math.exp((r - option_data.dividend_yield - 0.5 * sigma**2) * T - 1.96 * sigma * math.sqrt(T))
            upper_bound = S * math.exp((r - option_data.dividend_yield - 0.5 * sigma**2) * T + 1.96 * sigma * math.sqrt(T))
            metrics.confidence_interval = (round(lower_bound, 2), round(upper_bound, 2))
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"Error calculating single option probabilities: {e}")
            return ProbabilityMetrics()
    
    def calculate_spread_probabilities(self, spread_data: SpreadData) -> ProbabilityMetrics:
        """Calculate probabilities for spread strategies"""
        try:
            S = spread_data.underlying_price
            short_strike = spread_data.short_strike
            long_strike = spread_data.long_strike
            T = spread_data.time_to_expiry
            sigma = spread_data.volatility
            r = spread_data.risk_free_rate
            q = spread_data.dividend_yield
            
            if T <= 0:
                return ProbabilityMetrics()
            
            metrics = ProbabilityMetrics()
            
            # Determine strategy direction
            is_credit_spread = spread_data.credit_received > 0
            strategy_type = spread_data.strategy_type.lower()
            
            if 'put' in strategy_type:
                # Put spread
                if is_credit_spread:
                    # Put credit spread: profit if price stays above short strike
                    d2_short = (math.log(S / short_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.pop = norm.cdf(d2_short) * 100
                    
                    # Max profit if price stays above long strike  
                    d2_long = (math.log(S / long_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.prob_max_profit = norm.cdf(d2_long) * 100
                else:
                    # Put debit spread: profit if price goes below long strike
                    d2_long = (math.log(S / long_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.pop = norm.cdf(-d2_long) * 100
                    
                    # Max profit if price goes below short strike
                    d2_short = (math.log(S / short_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.prob_max_profit = norm.cdf(-d2_short) * 100
            
            elif 'call' in strategy_type:
                # Call spread
                if is_credit_spread:
                    # Call credit spread: profit if price stays below short strike
                    d2_short = (math.log(S / short_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.pop = norm.cdf(-d2_short) * 100
                    
                    # Max profit if price stays below long strike
                    d2_long = (math.log(S / long_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.prob_max_profit = norm.cdf(-d2_long) * 100
                else:
                    # Call debit spread: profit if price goes above long strike
                    d2_long = (math.log(S / long_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.pop = norm.cdf(d2_long) * 100
                    
                    # Max profit if price goes above short strike
                    d2_short = (math.log(S / short_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    metrics.prob_max_profit = norm.cdf(d2_short) * 100
            
            # Probability of touching short strike (early assignment risk)
            if S != short_strike:
                barrier_prob = 2 * norm.cdf(abs(math.log(short_strike/S)) / (sigma * math.sqrt(T)))
                metrics.pot = min(barrier_prob * 100, 100.0)
            
            # P50 calculation - probability of achieving 50% of max profit
            if is_credit_spread and spread_data.credit_received > 0:
                # For credit spreads: keep 50% of credit = make 50% profit
                target_profit_pct = 50.0
                
                # Interpolate strike price for 50% profit
                strike_width = abs(long_strike - short_strike)
                if strike_width > 0:
                    credit_per_point = spread_data.credit_received / strike_width
                    target_strike_distance = (spread_data.credit_received * 0.5) / credit_per_point
                    
                    if 'put' in strategy_type:
                        target_strike = short_strike + target_strike_distance
                        d2_target = (math.log(S / target_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                        metrics.p50 = norm.cdf(d2_target) * 100
                    else:  # call
                        target_strike = short_strike - target_strike_distance
                        d2_target = (math.log(S / target_strike) + (r - q - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                        metrics.p50 = norm.cdf(-d2_target) * 100
            
            # Expected value calculation (simplified)
            max_profit = spread_data.credit_received if is_credit_spread else abs(long_strike - short_strike) - spread_data.debit_paid
            max_loss = abs(long_strike - short_strike) - max_profit
            
            if max_profit > 0 and max_loss > 0:
                prob_profit = metrics.pop / 100.0
                prob_loss = 1.0 - prob_profit
                metrics.expected_value = (prob_profit * max_profit) - (prob_loss * max_loss)
                
                # Kelly criterion (simplified)
                if max_loss > 0:
                    win_rate = prob_profit
                    avg_win = max_profit
                    avg_loss = max_loss
                    kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_loss
                    metrics.kelly_criterion = max(0, min(kelly, 0.25))  # Cap at 25%
            
            # Confidence interval for underlying price
            lower_bound = S * math.exp((r - q - 0.5 * sigma**2) * T - 1.96 * sigma * math.sqrt(T))
            upper_bound = S * math.exp((r - q - 0.5 * sigma**2) * T + 1.96 * sigma * math.sqrt(T))
            metrics.confidence_interval = (round(lower_bound, 2), round(upper_bound, 2))
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"Error calculating spread probabilities: {e}")
            return ProbabilityMetrics()
    
    def calculate_iron_condor_probabilities(self, underlying_price: float, 
                                          put_short_strike: float, put_long_strike: float,
                                          call_short_strike: float, call_long_strike: float,
                                          time_to_expiry: float, volatility: float,
                                          risk_free_rate: float = 0.05) -> ProbabilityMetrics:
        """Calculate probabilities for iron condor strategy"""
        try:
            S = underlying_price
            T = time_to_expiry
            sigma = volatility
            r = risk_free_rate
            
            if T <= 0:
                return ProbabilityMetrics()
            
            metrics = ProbabilityMetrics()
            
            # Iron condor profits if price stays between short strikes
            d2_put = (math.log(S / put_short_strike) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2_call = (math.log(S / call_short_strike) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            
            # POP = probability price stays between short strikes
            prob_above_put = norm.cdf(d2_put)
            prob_below_call = norm.cdf(-d2_call)
            metrics.pop = (prob_above_put - (1 - prob_below_call)) * 100
            metrics.pop = max(0, min(metrics.pop, 100))
            
            # Max profit if price stays between long strikes
            d2_put_long = (math.log(S / put_long_strike) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2_call_long = (math.log(S / call_long_strike) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            
            prob_above_put_long = norm.cdf(d2_put_long)
            prob_below_call_long = norm.cdf(-d2_call_long)
            metrics.prob_max_profit = (prob_above_put_long - (1 - prob_below_call_long)) * 100
            metrics.prob_max_profit = max(0, min(metrics.prob_max_profit, 100))
            
            # POT = probability of touching either short strike
            pot_put = 2 * norm.cdf(abs(math.log(put_short_strike/S)) / (sigma * math.sqrt(T))) if S != put_short_strike else 1.0
            pot_call = 2 * norm.cdf(abs(math.log(call_short_strike/S)) / (sigma * math.sqrt(T))) if S != call_short_strike else 1.0
            metrics.pot = min((pot_put + pot_call) * 100, 100.0)
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"Error calculating iron condor probabilities: {e}")
            return ProbabilityMetrics()
    
    def validate_inputs(self, underlying_price: float, strike_price: float, 
                       time_to_expiry: float, volatility: float) -> bool:
        """Validate inputs for probability calculations"""
        try:
            if underlying_price <= 0:
                self.logger.error("Underlying price must be positive")
                return False
            
            if strike_price <= 0:
                self.logger.error("Strike price must be positive")
                return False
            
            if time_to_expiry <= 0:
                self.logger.error("Time to expiry must be positive")
                return False
            
            if volatility <= 0 or volatility > 5.0:  # 500% vol seems excessive
                self.logger.error("Volatility must be positive and reasonable")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating inputs: {e}")
            return False