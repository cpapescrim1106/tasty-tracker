#!/usr/bin/env python3
"""
Strategy-Aware Portfolio Analyzer
Integrates position strategies with allocation analysis for fast portfolio insights
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from enhanced_position_storage import (
    EnhancedStrategyPositionStorage, 
    PositionStrategyType
)
from position_chain_detector import PositionChainDetector
from allocation_rules_manager import AllocationRulesManager

class StrategyAwareAnalyzer:
    """Analyzes portfolio with strategy awareness for sub-100ms performance"""
    
    def __init__(self, storage: EnhancedStrategyPositionStorage, 
                 delta_tracker, chain_detector: PositionChainDetector):
        self.storage = storage
        self.tracker = delta_tracker
        self.chain_detector = chain_detector
        self.logger = logging.getLogger(__name__)
        
    def analyze_portfolio_complete(self, account_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
        """Complete portfolio analysis with strategy detection in <100ms"""
        
        start_time = time.time()
        
        # Step 1: Get live positions from memory (fast)
        with self.tracker.positions_lock:
            live_positions = dict(self.tracker.positions)
            
        # Step 2: Detect and store strategies (async if needed)
        position_list = list(live_positions.values())
        detected_strategies = self.storage.detect_and_store_strategy(
            position_list, self.chain_detector
        )
        
        # Step 3: Get enhanced positions with strategy info
        enhanced_positions = self.storage.get_positions_with_dynamic_data(
            account_numbers, live_positions
        )
        
        # Step 4: Calculate allocations using cache
        allocations = self.storage.calculate_allocation_summary(enhanced_positions)
        
        # Step 5: Get strategy insights
        strategy_insights = self._analyze_strategy_distribution(enhanced_positions)
        
        # Step 6: Calculate portfolio-wide metrics
        portfolio_metrics = self._calculate_portfolio_metrics(enhanced_positions)
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        return {
            'positions': enhanced_positions,
            'allocations': allocations,
            'strategy_insights': strategy_insights,
            'portfolio_metrics': portfolio_metrics,
            'detected_strategies': len(detected_strategies),
            'processing_time_ms': elapsed_ms,
            'timestamp': datetime.now().isoformat()
        }
        
    def _analyze_strategy_distribution(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze strategy distribution and risk metrics"""
        
        insights = {
            'total_strategies': 0,
            'strategies_by_type': defaultdict(int),
            'strategies_by_underlying': defaultdict(int),
            'single_positions': 0,
            'risk_metrics': {},
            'strategy_health': {}
        }
        
        # Count unique strategies and single positions
        unique_strategies = set()
        single_positions = []
        strategies_detail = defaultdict(list)
        
        for pos in positions:
            if pos.get('strategy_id'):
                unique_strategies.add(pos['strategy_id'])
                strategy_type = pos.get('strategy_type', 'unknown')
                insights['strategies_by_type'][strategy_type] += 1
                insights['strategies_by_underlying'][pos['underlying_symbol']] += 1
                strategies_detail[pos['strategy_id']].append(pos)
            else:
                single_positions.append(pos)
                
        insights['total_strategies'] = len(unique_strategies)
        insights['single_positions'] = len(single_positions)
        
        # Calculate risk metrics
        total_delta = sum(p['delta'] * p['quantity'] for p in positions if p.get('delta'))
        total_value = sum(p['market_value'] for p in positions if p.get('market_value'))
        
        insights['risk_metrics'] = {
            'total_portfolio_delta': round(total_delta, 2),
            'delta_per_10k': round((total_delta / total_value * 10000), 2) if total_value > 0 else 0,
            'strategies_with_protection': sum(1 for s in unique_strategies if 'spread' in s.lower()),
            'naked_positions': len([p for p in single_positions if 'option' in p.get('instrument_type', '').lower()])
        }
        
        # Analyze strategy health
        insights['strategy_health'] = self._analyze_strategy_health(strategies_detail)
        
        return dict(insights)
    
    def _analyze_strategy_health(self, strategies_detail: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Analyze health of individual strategies"""
        
        health_metrics = {
            'healthy_strategies': 0,
            'at_risk_strategies': 0,
            'expired_strategies': 0,
            'details': []
        }
        
        for strategy_id, positions in strategies_detail.items():
            # Calculate strategy metrics
            min_dte = min(p.get('dte', 999) for p in positions)
            total_value = sum(p.get('market_value', 0) for p in positions)
            total_delta = sum(p.get('delta', 0) * p.get('quantity', 0) for p in positions)
            
            # Determine health status
            if min_dte < 0:
                status = 'expired'
                health_metrics['expired_strategies'] += 1
            elif min_dte <= 7 or abs(total_delta) > 50:
                status = 'at_risk'
                health_metrics['at_risk_strategies'] += 1
            else:
                status = 'healthy'
                health_metrics['healthy_strategies'] += 1
            
            health_metrics['details'].append({
                'strategy_id': strategy_id,
                'status': status,
                'min_dte': min_dte,
                'total_value': round(total_value, 2),
                'total_delta': round(total_delta, 2)
            })
        
        return health_metrics
    
    def _calculate_portfolio_metrics(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate portfolio-wide metrics"""
        
        metrics = {
            'total_value': 0,
            'total_cost_basis': 0,
            'total_pnl': 0,
            'total_pnl_percent': 0,
            'positions_count': len(positions),
            'option_positions': 0,
            'equity_positions': 0,
            'average_dte': 0,
            'positions_by_dte': defaultdict(int)
        }
        
        dte_sum = 0
        dte_count = 0
        
        for pos in positions:
            # Value metrics
            market_value = pos.get('market_value', 0)
            cost_basis = pos.get('cost_basis', 0)
            
            metrics['total_value'] += market_value
            metrics['total_cost_basis'] += cost_basis
            
            # Position type counts
            if pos['asset_category'] == 'equity_option':
                metrics['option_positions'] += 1
            elif pos['asset_category'] == 'equity':
                metrics['equity_positions'] += 1
            
            # DTE metrics
            if pos.get('dte') is not None:
                dte = pos['dte']
                dte_sum += dte
                dte_count += 1
                metrics['positions_by_dte'][pos['duration_category']] += 1
        
        # Calculate derived metrics
        metrics['total_pnl'] = metrics['total_value'] - metrics['total_cost_basis']
        if metrics['total_cost_basis'] > 0:
            metrics['total_pnl_percent'] = (metrics['total_pnl'] / metrics['total_cost_basis']) * 100
        
        if dte_count > 0:
            metrics['average_dte'] = dte_sum / dte_count
        
        # Round for display
        metrics['total_value'] = round(metrics['total_value'], 2)
        metrics['total_cost_basis'] = round(metrics['total_cost_basis'], 2)
        metrics['total_pnl'] = round(metrics['total_pnl'], 2)
        metrics['total_pnl_percent'] = round(metrics['total_pnl_percent'], 2)
        metrics['average_dte'] = round(metrics['average_dte'], 1)
        
        return metrics

class StrategyAwareRebalancer:
    """Rebalancer that considers position strategies for intelligent recommendations"""
    
    def __init__(self, analyzer: StrategyAwareAnalyzer, 
                 rules_manager: AllocationRulesManager,
                 screener_engine=None):
        self.analyzer = analyzer
        self.rules_manager = rules_manager
        self.screener = screener_engine
        self.logger = logging.getLogger(__name__)
        
    def generate_strategy_aware_recommendations(self, 
                                              account_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
        """Generate recommendations considering existing strategies"""
        
        # Analyze current portfolio with strategies
        analysis = self.analyzer.analyze_portfolio_complete(account_numbers)
        
        # Check compliance with allocation rules
        total_value = analysis['portfolio_metrics']['total_value']
        compliance_checks = self.rules_manager.check_compliance(
            analysis['allocations'], total_value
        )
        
        # Identify allocation gaps
        available_bp = self._get_available_buying_power(account_numbers)
        gaps = self.rules_manager.identify_allocation_gaps(
            analysis['allocations'], total_value, available_bp
        )
        
        # Generate smart recommendations
        recommendations = self._generate_smart_recommendations(
            gaps, analysis['strategy_insights'], analysis['positions']
        )
        
        return {
            'analysis': analysis,
            'compliance_checks': compliance_checks,
            'gaps': gaps,
            'recommendations': recommendations,
            'timestamp': datetime.now().isoformat()
        }
        
    def _generate_smart_recommendations(self, gaps: List[Any], 
                                      strategy_insights: Dict[str, Any],
                                      current_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate recommendations considering existing strategies"""
        
        recommendations = []
        
        # Group current positions by underlying
        positions_by_underlying = defaultdict(list)
        for pos in current_positions:
            positions_by_underlying[pos['underlying_symbol']].append(pos)
            
        for gap in gaps:
            # Skip small gaps
            if abs(gap.gap_pct) < 2.0:
                continue
                
            # Determine appropriate action based on gap type
            if gap.gap_pct > 0:  # Need to increase allocation
                # Check if we should add to existing positions or open new ones
                rec_type = self._determine_recommendation_type(
                    gap, positions_by_underlying, strategy_insights
                )
                
                if rec_type == 'add_to_existing':
                    # Recommend adding to existing strategies
                    recs = self._recommend_additions_to_existing(gap, positions_by_underlying)
                    recommendations.extend(recs)
                else:
                    # Recommend new positions
                    recs = self._recommend_new_positions(gap, strategy_insights)
                    recommendations.extend(recs)
                    
            else:  # Need to decrease allocation
                # Recommend closing or reducing positions
                recs = self._recommend_position_reductions(gap, current_positions)
                recommendations.extend(recs)
                
        return recommendations
        
    def _determine_recommendation_type(self, gap, positions_by_underlying, 
                                     strategy_insights) -> str:
        """Determine whether to add to existing or open new positions"""
        
        # If we have existing positions in the category, prefer adding
        if gap.category in ['bullish', 'bearish', 'neutral']:
            # Check if we have existing strategies of this type
            relevant_strategies = strategy_insights['strategies_by_type']
            if self._has_matching_strategies(gap.category, relevant_strategies):
                return 'add_to_existing'
                
        return 'open_new'
        
    def _has_matching_strategies(self, category: str, strategies_by_type: Dict[str, int]) -> bool:
        """Check if we have strategies matching the category"""
        
        bullish_strategies = ['put_credit_spread', 'call_debit_spread', 'long_call', 'cash_secured_put']
        bearish_strategies = ['call_credit_spread', 'put_debit_spread', 'long_put']
        neutral_strategies = ['iron_condor', 'iron_butterfly', 'straddle', 'strangle']
        
        if category == 'bullish':
            return any(strategies_by_type.get(s, 0) > 0 for s in bullish_strategies)
        elif category == 'bearish':
            return any(strategies_by_type.get(s, 0) > 0 for s in bearish_strategies)
        elif category == 'neutral':
            return any(strategies_by_type.get(s, 0) > 0 for s in neutral_strategies)
            
        return False
        
    def _recommend_additions_to_existing(self, gap, positions_by_underlying) -> List[Dict[str, Any]]:
        """Recommend adding to existing positions"""
        
        recommendations = []
        
        # Find underlyings with existing positions matching the gap category
        for underlying, positions in positions_by_underlying.items():
            # Check if positions match the gap category
            if self._positions_match_category(positions, gap.category):
                # Calculate current allocation
                current_allocation = sum(p['market_value'] for p in positions)
                
                rec = {
                    'action': 'add_to_existing',
                    'underlying': underlying,
                    'category': gap.category,
                    'current_allocation': round(current_allocation, 2),
                    'recommended_addition': round(gap.required_allocation_dollars * 0.2, 2),  # 20% of gap
                    'reason': f"Add to existing {gap.category} position in {underlying}",
                    'priority': gap.priority,
                    'existing_strategy': positions[0].get('strategy_type', 'unknown')
                }
                recommendations.append(rec)
                
                # Limit to top 3 additions
                if len(recommendations) >= 3:
                    break
                    
        return recommendations
        
    def _positions_match_category(self, positions: List[Dict[str, Any]], category: str) -> bool:
        """Check if positions match the allocation category"""
        
        # Check strategy categories
        position_categories = [p.get('strategy_category') for p in positions]
        
        if category in ['bullish', 'bearish', 'neutral']:
            return category in position_categories
        elif category == 'equities':
            return any(p['asset_category'] == 'equity' for p in positions)
        elif category == 'non_equities':
            return any(p['asset_category'] == 'equity_option' for p in positions)
            
        # For duration categories
        return any(p.get('duration_category') == category for p in positions)
        
    def _recommend_new_positions(self, gap, strategy_insights) -> List[Dict[str, Any]]:
        """Recommend new positions to fill gaps"""
        
        # Determine appropriate strategies based on gap type and existing portfolio
        strategy_suggestion = self._suggest_strategy_for_category(gap.category, strategy_insights)
        
        return [{
            'action': 'open_new',
            'category': gap.category,
            'target_allocation': round(gap.required_allocation_dollars, 2),
            'strategy_suggestion': strategy_suggestion,
            'reason': f"Open new {gap.category} position to fill {gap.gap_pct:.1f}% gap",
            'priority': gap.priority,
            'diversification_note': self._get_diversification_note(gap.category, strategy_insights)
        }]
        
    def _suggest_strategy_for_category(self, category: str, strategy_insights: Dict[str, Any]) -> str:
        """Suggest appropriate strategy for category based on current portfolio"""
        
        # Get current strategy distribution
        current_strategies = strategy_insights.get('strategies_by_type', {})
        
        suggestions = {
            'bullish': ['put_credit_spread', 'cash_secured_put', 'call_debit_spread'],
            'bearish': ['call_credit_spread', 'put_debit_spread'],
            'neutral': ['iron_condor', 'iron_butterfly', 'strangle'],
            '22-45_dte': ['credit_spread', 'iron_condor'],
            '0-7_dte': ['close_position']
        }
        
        # Pick strategy not overrepresented in portfolio
        if category in suggestions:
            for strategy in suggestions[category]:
                if current_strategies.get(strategy, 0) < 3:  # Limit same strategy type
                    return strategy
            return suggestions[category][0]  # Default to first option
            
        return 'evaluate_opportunities'
        
    def _get_diversification_note(self, category: str, strategy_insights: Dict[str, Any]) -> str:
        """Get diversification recommendation"""
        
        # Check concentration
        by_underlying = strategy_insights.get('strategies_by_underlying', {})
        max_concentration = max(by_underlying.values()) if by_underlying else 0
        
        if max_concentration > 3:
            return "Consider different underlying to improve diversification"
        else:
            return "Well diversified across underlyings"
        
    def _recommend_position_reductions(self, gap, positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recommend position reductions for over-allocation"""
        
        # Find positions in the over-allocated category
        relevant_positions = [
            p for p in positions 
            if self._position_matches_gap_category(p, gap.category)
        ]
        
        # Sort by various criteria
        relevant_positions.sort(key=lambda p: (
            p.get('dte', 999),  # Close shorter DTE first
            -abs(p.get('pnl_percent', 0)),  # Then highest profit/loss
            -p.get('market_value', 0)  # Then larger positions
        ))
        
        recommendations = []
        remaining_reduction = abs(gap.required_allocation_dollars)
        
        for pos in relevant_positions[:5]:  # Limit to top 5 candidates
            if remaining_reduction <= 0:
                break
                
            # Calculate PnL for position
            pnl = pos.get('market_value', 0) - pos.get('cost_basis', 0)
            pnl_percent = (pnl / pos.get('cost_basis', 1)) * 100 if pos.get('cost_basis', 0) > 0 else 0
            
            rec = {
                'action': 'reduce_position',
                'position_key': pos['position_key'],
                'symbol': pos['symbol'],
                'underlying': pos['underlying_symbol'],
                'current_value': round(pos['market_value'], 2),
                'recommended_reduction': round(min(pos['market_value'], remaining_reduction), 2),
                'reason': f"Reduce {gap.category} allocation by {abs(gap.gap_pct):.1f}%",
                'priority': gap.priority,
                'dte': pos.get('dte'),
                'pnl': round(pnl, 2),
                'pnl_percent': round(pnl_percent, 2),
                'strategy_type': pos.get('strategy_type', 'single_position')
            }
            
            recommendations.append(rec)
            remaining_reduction -= pos['market_value']
            
        return recommendations
        
    def _position_matches_gap_category(self, position: Dict[str, Any], category: str) -> bool:
        """Check if position matches gap category"""
        
        if category in ['bullish', 'bearish', 'neutral']:
            return position.get('strategy_category') == category
        elif category == 'equities':
            return position['asset_category'] == 'equity'
        elif category == 'non_equities':
            return position['asset_category'] == 'equity_option'
        else:
            # Duration categories
            return position.get('duration_category') == category
            
    def _get_available_buying_power(self, account_numbers: List[str]) -> float:
        """Get available buying power from tracker"""
        try:
            total_bp = 0
            
            if hasattr(self.analyzer.tracker, 'account_data'):
                with self.analyzer.tracker.account_data_lock:
                    for account in account_numbers or []:
                        account_info = self.analyzer.tracker.account_data.get(account, {})
                        bp = account_info.get('available_trading_funds', 0)
                        total_bp += bp
                        
            return total_bp
        except:
            return 10000  # Default fallback