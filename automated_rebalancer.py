#!/usr/bin/env python3
"""
Automated Portfolio Rebalancer
Detects fills and triggers comprehensive portfolio rebalancing
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from allocation_rules_manager import AllocationRulesManager, AllocationGap, ComplianceCheck
from portfolio_analyzer import PortfolioAnalyzer, PortfolioSnapshot
from screener_backend import ScreenerEngine

class RecommendationType(Enum):
    OPEN = "open"
    CLOSE = "close" 
    ROLL = "roll"
    ADJUST = "adjust"

class RecommendationPriority(Enum):
    CRITICAL = 1  # Compliance violations
    HIGH = 2      # Allocation gaps
    MEDIUM = 3    # Optimization
    LOW = 4       # Enhancement

@dataclass
class TradeRecommendation:
    """Individual trade recommendation"""
    recommendation_id: str
    recommendation_type: RecommendationType
    priority: RecommendationPriority
    
    # Position details
    symbol: str
    underlying_symbol: str
    strategy_type: str
    action: str  # 'BUY', 'SELL', 'BTO', 'STC', etc.
    
    # Trade specifics
    entry_price: float
    max_price: float
    quantity: int
    dte_target: int
    delta_target: float
    
    # Portfolio impact
    allocation_impact: Dict[str, float]  # How this affects allocations
    buying_power_required: float
    expected_return: float
    max_risk: float
    
    # Analysis
    confidence_score: float
    reasoning: str
    market_context: str
    
    # Metadata
    created_at: datetime
    expires_at: Optional[datetime] = None

@dataclass 
class RebalancingEvent:
    """Complete rebalancing event"""
    event_id: str
    trigger_event: str  # 'fill_detected', 'scheduled', 'manual'
    trigger_details: Dict[str, Any]
    
    # Portfolio state
    portfolio_snapshot: PortfolioSnapshot
    compliance_checks: List[ComplianceCheck]
    allocation_gaps: List[AllocationGap]
    
    # Recommendations
    recommendations: List[TradeRecommendation]
    total_buying_power_required: float
    expected_portfolio_impact: Dict[str, Any]
    
    # Status
    created_at: datetime
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    status: str = "pending"  # pending, approved, executed, rejected

class AutomatedRebalancer:
    """Main automated rebalancing engine"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance
        self.logger = logging.getLogger(__name__)
        
        # Core components
        self.allocation_manager = AllocationRulesManager()
        self.portfolio_analyzer = PortfolioAnalyzer(tracker_instance)
        self.screener_engine = ScreenerEngine(tracker_instance)
        
        # State management
        self.current_event: Optional[RebalancingEvent] = None
        self.current_sector_rankings: Dict[str, Any] = {'equity_sectors': [], 'non_equity_sectors': []}
        self.rebalancing_lock = threading.Lock()
        self.last_fill_check = datetime.now()
        
        # Configuration
        self.max_single_trade_dollars = 5000  # Max $5k per trade
        self.max_total_allocation_pct = 90    # Max 90% of buying power
        self.min_confidence_threshold = 60    # Min 60% confidence
        self.max_positions_per_gap = 5        # Max positions per allocation gap
        self.min_position_size_dollars = 500  # Min $500 per position
        
        # Fill detection
        self.known_fills = set()  # Track processed fills
        self.fill_check_interval = 30  # Check every 30 seconds
        
        # Performance optimization - cache rankings during rebalancing
        self._current_rankings_cache = None
        self._cache_timestamp = None
        self._cache_duration = 300  # 5 minute cache
        
    def start_fill_monitoring(self):
        """Start background fill monitoring"""
        monitoring_thread = threading.Thread(target=self._fill_monitoring_loop, daemon=True)
        monitoring_thread.start()
        self.logger.info("🚀 Started automated fill monitoring")
        
    def _fill_monitoring_loop(self):
        """Background loop to monitor for fills"""
        while True:
            try:
                self._check_for_new_fills()
                time.sleep(self.fill_check_interval)
            except Exception as e:
                self.logger.error(f"❌ Error in fill monitoring: {e}")
                time.sleep(self.fill_check_interval)
                
    def _check_for_new_fills(self):
        """Check for new fills since last check"""
        try:
            # This would integrate with trade journal to detect new fills
            # For now, simplified implementation
            current_time = datetime.now()
            
            # Check if any new fills in trade journal
            if hasattr(self.tracker, 'trade_journal_manager'):
                # Get recent fills from trade journal
                recent_fills = self._get_recent_fills()
                
                for fill in recent_fills:
                    fill_id = f"{fill.get('account')}:{fill.get('order_id')}"
                    
                    if fill_id not in self.known_fills:
                        self.known_fills.add(fill_id)
                        self.logger.info(f"📈 New fill detected: {fill_id}")
                        
                        # Trigger rebalancing
                        self.trigger_rebalancing(
                            trigger_event="fill_detected",
                            trigger_details=fill
                        )
                        
        except Exception as e:
            self.logger.error(f"❌ Error checking for fills: {e}")
            
    def _get_recent_fills(self) -> List[Dict[str, Any]]:
        """Get recent fills from trade journal or order tracking"""
        # Placeholder implementation
        # In reality would query trade journal for recent fills
        return []
        
    def _get_cached_rankings(self) -> List[Dict[str, Any]]:
        """Get cached rankings or fetch fresh ones if needed"""
        now = time.time()
        
        # Check if cache is still valid
        if (self._current_rankings_cache is not None and 
            self._cache_timestamp is not None and 
            now - self._cache_timestamp < self._cache_duration):
            self.logger.info("📊 Using cached rankings for rebalancing")
            return self._current_rankings_cache
        
        # Fetch fresh rankings
        self.logger.info("📊 Fetching fresh rankings for rebalancing (cache expired or empty)")
        
        try:
            rankings = self.screener_engine.rank_main_list_underlyings(max_symbols=50, timeout_seconds=30)
            
            # If no rankings or empty, use fallback symbols
            if not rankings:
                self.logger.warning("⚠️ No rankings from Main List, using fallback symbols")
                fallback_symbols = self._get_fallback_symbols()
                rankings = self._create_fallback_rankings(fallback_symbols)
                
        except Exception as e:
            self.logger.error(f"❌ Failed to get rankings: {e}")
            # Use fallback on error
            fallback_symbols = self._get_fallback_symbols()
            rankings = self._create_fallback_rankings(fallback_symbols)
        
        # Update cache
        self._current_rankings_cache = rankings
        self._cache_timestamp = now
        
        # Debug logging for first few rankings
        self.logger.info(f"📊 Cached {len(rankings)} rankings")
        if rankings:
            sample_size = min(3, len(rankings))
            self.logger.info(f"📊 Sample rankings (first {sample_size}):")
            for i, ranking in enumerate(rankings[:sample_size]):
                symbol = ranking.get('symbol', 'UNKNOWN')
                iv_rank = ranking.get('iv_rank', 'N/A')
                price = ranking.get('last_price', 'N/A')
                can_add = ranking.get('can_add_position', 'N/A')
                self.logger.info(f"  {i+1}. {symbol}: IV={iv_rank}, Price=${price}, CanAdd={can_add}")
        
        return rankings

    def trigger_rebalancing(self, trigger_event: str, 
                          trigger_details: Optional[Dict[str, Any]] = None) -> str:
        """Trigger complete portfolio rebalancing analysis"""
        try:
            with self.rebalancing_lock:
                event_id = f"rebal_{int(datetime.now().timestamp())}"
                
                self.logger.info(f"🔄 Starting rebalancing analysis: {event_id}")
                
                # Clear cache at start of rebalancing to ensure fresh data
                self._current_rankings_cache = None
                self._cache_timestamp = None
                
                # Step 1: Analyze current portfolio for display (including long-term positions)
                display_snapshot = self.portfolio_analyzer.analyze_portfolio_for_display()
                
                # Step 1.5: Analyze rebalanceable positions (excluding long-term)
                rebalance_snapshot = self.portfolio_analyzer.analyze_current_portfolio()
                
                # Step 1.6: Update sector rankings for informed recommendations
                self._update_sector_rankings()
                
                # Step 2: Check compliance based on REBALANCEABLE positions only (excludes long-term)
                # This ensures long-term positions don't create compliance violations
                current_allocations = {
                    'asset_allocation': rebalance_snapshot.asset_allocation,
                    'duration_allocation': rebalance_snapshot.duration_allocation,
                    'strategy_allocation': rebalance_snapshot.strategy_allocation
                }
                
                self.logger.info(f"🔍 Compliance check on rebalanceable portfolio:")
                self.logger.info(f"  - Rebalanceable positions: {len(rebalance_snapshot.positions)}")
                self.logger.info(f"  - Rebalanceable market value: ${rebalance_snapshot.total_market_value:,.0f}")
                self.logger.info(f"  - Long-term positions (display only): {len(display_snapshot.positions)}")
                self.logger.info(f"  - Total market value (display): ${display_snapshot.total_market_value:,.0f}")
                
                compliance_checks = self.allocation_manager.check_compliance(
                    current_allocations, rebalance_snapshot.total_market_value
                )
                
                # Step 3: Identify gaps based on TARGET portfolio vs TOTAL portfolio 
                # We want to achieve target allocations across the TOTAL portfolio (including long-term)
                # but only generate new positions to fill the gaps
                available_buying_power = max(display_snapshot.cash_balance, 0)
                self.logger.info(f"💰 Available buying power: ${available_buying_power:,.0f} (cash balance)")
                
                # Calculate gaps based on total portfolio vs targets
                total_allocations = {
                    'asset_allocation': display_snapshot.asset_allocation,
                    'duration_allocation': display_snapshot.duration_allocation,
                    'strategy_allocation': display_snapshot.strategy_allocation
                }
                
                allocation_gaps = self.allocation_manager.identify_allocation_gaps(
                    total_allocations, 
                    display_snapshot.total_market_value,
                    available_buying_power
                )
                
                # Step 4: Generate recommendations (only new positions, not touching long-term)
                recommendations = self._generate_recommendations(
                    display_snapshot, compliance_checks, allocation_gaps, available_buying_power
                )
                
                # Step 5: Create rebalancing event
                rebalancing_event = RebalancingEvent(
                    event_id=event_id,
                    trigger_event=trigger_event,
                    trigger_details=trigger_details or {},
                    portfolio_snapshot=display_snapshot,  # Use display snapshot for complete view
                    compliance_checks=compliance_checks,
                    allocation_gaps=allocation_gaps,
                    recommendations=recommendations,
                    total_buying_power_required=sum(r.buying_power_required for r in recommendations),
                    expected_portfolio_impact=self._calculate_portfolio_impact(recommendations),
                    created_at=datetime.now()
                )
                
                self.current_event = rebalancing_event
                
                self.logger.info(f"✅ Rebalancing analysis complete: {len(recommendations)} recommendations")
                return event_id
                
        except Exception as e:
            self.logger.error(f"❌ Failed to trigger rebalancing: {e}")
            raise
            
    def _generate_recommendations(self, 
                                snapshot: PortfolioSnapshot,
                                compliance_checks: List[ComplianceCheck],
                                allocation_gaps: List[AllocationGap],
                                available_buying_power: float) -> List[TradeRecommendation]:
        """Generate trade recommendations based only on what's needed to fill gaps"""
        recommendations = []
        
        try:
            # Log initial state
            self.logger.info(f"🔍 Starting recommendation generation:")
            self.logger.info(f"  - Portfolio value: ${snapshot.total_market_value:,.0f}")
            self.logger.info(f"  - Available buying power: ${available_buying_power:,.0f}")
            self.logger.info(f"  - Compliance checks: {len(compliance_checks)}")
            self.logger.info(f"  - Allocation gaps: {len(allocation_gaps)}")
            
            # Log gap details
            for gap in allocation_gaps:
                self.logger.info(f"  📊 Gap: {gap.rule_type.value}/{gap.category} - "
                               f"Current: {gap.current_pct:.1f}%, Target: {gap.target_pct:.1f}%, "
                               f"Gap: {gap.gap_pct:+.1f}%, ${gap.required_allocation_dollars:,.0f}")
            
            # Step 1: Handle compliance violations (closing overweight positions)
            closing_recs = self._generate_closing_recommendations(snapshot, compliance_checks)
            self.logger.info(f"  ✅ Generated {len(closing_recs)} closing recommendations")
            recommendations.extend(closing_recs)
            
            # Step 2: Handle allocation gaps (opening new positions)  
            # Only generate positions actually needed to fill gaps
            opening_recs = self._generate_opening_recommendations(snapshot, allocation_gaps)
            self.logger.info(f"  ✅ Generated {len(opening_recs)} opening recommendations")
            recommendations.extend(opening_recs)
            
            # Step 3: Handle expiring positions (rolling)
            rolling_recs = self._generate_rolling_recommendations(snapshot)
            self.logger.info(f"  ✅ Generated {len(rolling_recs)} rolling recommendations")
            recommendations.extend(rolling_recs)
            
            # Step 4: Optimize existing positions (adjustments)
            # Only if there are significant opportunities
            adjustment_recs = self._generate_adjustment_recommendations(snapshot)
            self.logger.info(f"  ✅ Generated {len(adjustment_recs)} adjustment recommendations")
            recommendations.extend(adjustment_recs)
            
            # Log before filtering
            self.logger.info(f"📊 Total recommendations before filtering: {len(recommendations)}")
            
            # Step 5: Filter and prioritize
            recommendations = self._filter_and_prioritize_recommendations(
                recommendations, available_buying_power
            )
            
            self.logger.info(f"📊 Generated {len(recommendations)} recommendations after filtering")
            
            return recommendations
            
        except Exception as e:
            self.logger.error(f"❌ Failed to generate recommendations: {e}", exc_info=True)
            return []
            
    def _generate_opening_recommendations(self, 
                                        snapshot: PortfolioSnapshot,
                                        gaps: List[AllocationGap]) -> List[TradeRecommendation]:
        """Generate opening position recommendations to fill gaps"""
        recommendations = []
        
        try:
            self.logger.info(f"🔍 Processing {len(gaps)} gaps for opening recommendations")
            
            # Process all gaps with lower threshold
            significant_gaps = [gap for gap in gaps if abs(gap.gap_pct) > 0.5]  # Lower threshold to 0.5%
            self.logger.info(f"  - Found {len(significant_gaps)} significant gaps (>0.5%)")
            
            for gap in significant_gaps:
                # Calculate positions needed based on gap size and constraints
                gap_dollars = gap.required_allocation_dollars
                self.logger.info(f"  📊 Processing gap: {gap.rule_type.value}/{gap.category}, ${gap_dollars:,.0f}")
                
                # Determine optimal position count for this gap
                if gap_dollars < self.min_position_size_dollars:
                    self.logger.info(f"    ⚠️ Skipping - gap too small (${gap_dollars:.0f} < ${self.min_position_size_dollars})")
                    continue  # Skip if gap too small
                
                # Only generate opening recommendations for underallocated categories
                if gap.gap_pct > 0:  # Underallocated - need opening positions
                    # Calculate positions needed: between 1 and max_positions_per_gap
                    ideal_position_size = min(self.max_single_trade_dollars, gap_dollars / 2)
                    positions_needed = max(1, min(
                        self.max_positions_per_gap,
                        int(gap_dollars / ideal_position_size)
                    ))
                    
                    self.logger.info(f"📈 Opening Gap: {gap.category} needs ${gap_dollars:.0f} → {positions_needed} positions")
                    
                    if gap.rule_type.value == 'asset':
                        # Asset allocation gap - need sector-specific recommendations
                        recs = self._generate_sector_recommendations(gap, positions_needed)
                        recommendations.extend(recs)
                        
                    elif gap.rule_type.value == 'duration':
                        # Duration gap - need specific DTE recommendations  
                        recs = self._generate_duration_recommendations(gap, positions_needed)
                        recommendations.extend(recs)
                        
                    elif gap.rule_type.value == 'strategy':
                        # Strategy bias gap - need directional recommendations
                        recs = self._generate_strategy_bias_recommendations(gap, positions_needed)
                        recommendations.extend(recs)
                else:
                    # Overallocated - log for now (closing logic would go here)
                    self.logger.info(f"📉 Closing Gap: {gap.category} has ${gap_dollars:.0f} excess (overallocated by {abs(gap.gap_pct):.1f}%)")
                    
            return recommendations
            
        except Exception as e:
            self.logger.error(f"❌ Failed to generate opening recommendations: {e}")
            return []
            
    def _generate_sector_recommendations(self, gap: AllocationGap, 
                                       positions_needed: int) -> List[TradeRecommendation]:
        """Generate recommendations for sector allocation gaps"""
        recommendations = []
        
        try:
            self.logger.info(f"    🎯 Generating {positions_needed} sector recommendations for {gap.category}")
            
            # Use screener to find best opportunities from Main List
            if gap.category == 'equities':
                self.logger.info(f"🚨 EQUITIES GAP PROCESSING STARTED - Category: {gap.category}")
                self.logger.info(f"🔍 Processing equities gap - fetching rankings...")
                # Get ranked Main List underlyings (already filtered and ranked)
                ranked_underlyings = self._get_cached_rankings()
                self.logger.info(f"🔍 Retrieved {len(ranked_underlyings) if ranked_underlyings else 0} rankings")
                
                # Debug: Show sample of rankings data structure
                if ranked_underlyings and len(ranked_underlyings) > 0:
                    sample = ranked_underlyings[0]
                    self.logger.info(f"📋 Sample ranking data keys: {list(sample.keys()) if isinstance(sample, dict) else 'Not a dict'}")
                    if isinstance(sample, dict):
                        self.logger.info(f"📋 Sample: {sample.get('symbol', 'NO_SYMBOL')} - IV:{sample.get('iv_rank', 'NO_IV')} Price:{sample.get('last_price', 'NO_PRICE')}")
                
                if not ranked_underlyings:
                    self.logger.warning("⚠️ No ranked underlyings available from Main List")
                    self.logger.info("    🔍 Attempting to fetch fresh rankings...")
                    # Force refresh of rankings
                    self._current_rankings_cache = None
                    self._cache_timestamp = None
                    ranked_underlyings = self._get_cached_rankings()
                    
                    if not ranked_underlyings:
                        self.logger.error("    ❌ Still no rankings after refresh attempt")
                        self.logger.info("    🔧 Generating basic fallback recommendations for testing")
                        # Create minimal fallback recommendations
                        fallback_symbols = ['AAPL', 'MSFT', 'SPY']
                        for symbol in fallback_symbols[:positions_needed]:
                            basic_result = {
                                'symbol': symbol,
                                'last_price': 100,
                                'iv_rank': 60,
                                'screening_score': 70,
                                'sector': 'Technology',
                                'can_add_position': True
                            }
                            rec = self._create_trade_recommendation_from_screener(
                                basic_result, gap, RecommendationPriority.HIGH
                            )
                            recommendations.append(rec)
                        return recommendations
                
                # Filter for equity positions only and apply basic criteria
                equity_opportunities = []
                self.logger.info(f"📊 Evaluating {len(ranked_underlyings)} ranked underlyings for equity opportunities")
                
                filter_stats = {'total': len(ranked_underlyings), 'iv_rank_fail': 0, 'price_fail': 0, 'can_add_fail': 0, 'passed': 0}
                
                for index, underlying in enumerate(ranked_underlyings):
                    # Get symbol first for error reporting
                    symbol = underlying.get('symbol', 'UNKNOWN')
                    
                    # Debug logging for all symbols to see what's happening
                    if index < 5:
                        self.logger.info(f"🔍 [{index}] Processing {symbol}...")
                    
                    try:
                        # Get all data safely
                        iv_rank = underlying.get('iv_rank')
                        last_price = underlying.get('last_price') 
                        can_add = underlying.get('can_add_position', True)
                        
                        # Debug logging for first few symbols
                        if index < 5:
                            self.logger.info(f"📊 [{index}] {symbol}: IV={iv_rank}, Price={last_price}, CanAdd={can_add}")
                        
                        # TEMPORARY: Skip all filtering to isolate the None issue
                        # Just check IV rank and accept everything else
                        
                        if iv_rank is None:
                            filter_stats['iv_rank_fail'] += 1
                            if index < 5:
                                self.logger.info(f"🚫 [{index}] Skipping {symbol} - no IV rank")
                            continue
                        
                        # Only check IV rank threshold, skip price filtering entirely for now
                        if iv_rank < 0.3:  # Very low threshold
                            filter_stats['iv_rank_fail'] += 1
                            if index < 5:
                                self.logger.info(f"🚫 [{index}] Skipping {symbol} - IV too low: {iv_rank}")
                            continue
                        
                        # Accept everything that has IV rank data, regardless of price
                        filter_stats['passed'] += 1
                        equity_opportunities.append(underlying)
                        
                        if index < 5:
                            self.logger.info(f"✅ [{index}] Added {symbol} - IV: {iv_rank}")
                        
                    except Exception as e:
                        self.logger.error(f"❌ Error filtering {symbol}: {e} - IV:{iv_rank}, Price:{last_price}")
                        filter_stats['price_fail'] += 1
                        continue
                
                self.logger.info(f"📊 Filter results: {filter_stats}")
                self.logger.info(f"📈 Found {len(equity_opportunities)} equity opportunities for gap")
                
                # Convert top results to recommendations - increase limit to get more opportunities
                max_recommendations = min(len(equity_opportunities), max(positions_needed, 10))  # At least 10 or all available
                self.logger.info(f"📊 Creating up to {max_recommendations} recommendations from {len(equity_opportunities)} opportunities")
                
                for i, result in enumerate(equity_opportunities[:max_recommendations]):
                    rec = self._create_trade_recommendation_from_screener(
                        result, gap, RecommendationPriority.HIGH
                    )
                    if rec:
                        recommendations.append(rec)
                        self.logger.info(f"✅ Created recommendation for {result.get('symbol', 'UNKNOWN')}")
                    else:
                        self.logger.warning(f"⚠️ Failed to create recommendation for {result.get('symbol', 'UNKNOWN')}")
                    
            elif gap.category == 'non_equities':
                # For now, use commodities/ETFs from Main List
                ranked_underlyings = self._get_cached_rankings()
                
                # Filter for non-equity symbols (ETFs, commodities, etc.)
                non_equity_opportunities = []
                for underlying in ranked_underlyings:
                    sector = underlying.get('sector', '')
                    symbol = underlying.get('symbol', '')
                    can_add = underlying.get('can_add_position', True)
                    
                    # Look for ETFs and commodities
                    if (can_add and (
                        'Index Fund' in underlying.get('industry', '') or
                        sector in ['Energy', 'Commodities', 'Real Estate'] or
                        symbol in ['GLD', 'SLV', 'TLT', 'VIX', 'XLE', 'XLF']
                    )):
                        non_equity_opportunities.append(underlying)
                
                self.logger.info(f"📊 Found {len(non_equity_opportunities)} non-equity opportunities")
                
                # Create recommendations for non-equity opportunities
                max_non_equity = min(len(non_equity_opportunities), max(positions_needed, 5))  # At least 5 or all available
                
                for i, result in enumerate(non_equity_opportunities[:max_non_equity]):
                    rec = self._create_trade_recommendation_from_screener(
                        result, gap, RecommendationPriority.HIGH
                    )
                    if rec:
                        recommendations.append(rec)
                        self.logger.info(f"✅ Created non-equity recommendation for {result.get('symbol', 'UNKNOWN')}")
                    else:
                        self.logger.warning(f"⚠️ Failed to create non-equity recommendation for {result.get('symbol', 'UNKNOWN')}")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to generate sector recommendations: {e}")
            
        return recommendations
        
    def _generate_duration_recommendations(self, gap: AllocationGap,
                                         positions_needed: int) -> List[TradeRecommendation]:
        """Generate recommendations for duration gaps"""
        recommendations = []
        
        try:
            # Map gap category to target DTE
            dte_map = {
                '0_dte': 0,
                '7_dte': 7, 
                '14_dte': 14,
                '45_dte': 45
            }
            
            target_dte = dte_map.get(gap.category, 30)
            
            # Use Main List ranked underlyings instead of hardcoded symbols
            ranked_underlyings = self._get_cached_rankings()
            
            if not ranked_underlyings:
                self.logger.warning("⚠️ No ranked underlyings available for duration recommendations")
                return recommendations
            
            # Filter for high IV rank opportunities suitable for duration-based strategies
            duration_opportunities = []
            for underlying in ranked_underlyings:
                iv_rank = underlying.get('iv_rank', 0)
                can_add = underlying.get('can_add_position', True)
                last_price = underlying.get('last_price', 0)
                
                # Higher IV rank threshold for duration plays
                if iv_rank >= 60 and can_add and last_price > 20:
                    duration_opportunities.append(underlying)
            
            self.logger.info(f"⏰ Found {len(duration_opportunities)} duration opportunities for {gap.category} (DTE: {target_dte})")
            
            for i, result in enumerate(duration_opportunities[:positions_needed]):
                rec = self._create_trade_recommendation_from_screener(
                    result, gap, RecommendationPriority.HIGH
                )
                rec.dte_target = target_dte
                recommendations.append(rec)
                
        except Exception as e:
            self.logger.error(f"❌ Failed to generate duration recommendations: {e}")
            
        return recommendations
        
    def _generate_strategy_bias_recommendations(self, gap: AllocationGap,
                                              positions_needed: int) -> List[TradeRecommendation]:
        """Generate recommendations for strategy bias gaps"""
        recommendations = []
        
        try:
            # Map bias to strategy types
            strategy_map = {
                'bullish': ['put_credit_spread', 'cash_secured_put', 'call_debit_spread'],
                'neutral': ['iron_condor', 'iron_butterfly', 'short_strangle'],
                'bearish': ['call_credit_spread', 'put_debit_spread']
            }
            
            preferred_strategies = strategy_map.get(gap.category, ['iron_condor'])
            
            # Use Main List ranked underlyings instead of hardcoded symbols
            ranked_underlyings = self._get_cached_rankings()
            
            if not ranked_underlyings:
                self.logger.warning("⚠️ No ranked underlyings available for strategy bias recommendations")
                return recommendations
            
            # Filter for opportunities suitable for preferred strategies
            strategy_opportunities = []
            for underlying in ranked_underlyings:
                iv_rank = underlying.get('iv_rank')
                can_add = underlying.get('can_add_position', True)
                last_price = underlying.get('last_price')
                
                # Strategy-specific filtering - fix IV rank scale (0-1 vs 0-100) and None handling
                if iv_rank is None or last_price is None:
                    continue  # Skip if missing data
                    
                iv_threshold_40 = 0.4 if iv_rank <= 1.0 else 40
                iv_threshold_50 = 0.5 if iv_rank <= 1.0 else 50
                iv_threshold_60 = 0.6 if iv_rank <= 1.0 else 60
                
                if gap.category == 'bullish':
                    # For bullish strategies, prefer moderate IV rank
                    if iv_rank >= iv_threshold_40 and can_add and last_price > 5:  # Very relaxed price
                        strategy_opportunities.append(underlying)
                elif gap.category == 'bearish':
                    # For bearish strategies, prefer higher IV rank
                    if iv_rank >= iv_threshold_60 and can_add and last_price > 5:
                        strategy_opportunities.append(underlying)
                else:  # neutral
                    # For neutral strategies, prefer high IV rank
                    if iv_rank >= iv_threshold_50 and can_add and last_price > 5:
                        strategy_opportunities.append(underlying)
            
            self.logger.info(f"🎯 Found {len(strategy_opportunities)} {gap.category} strategy opportunities")
            
            for i, result in enumerate(strategy_opportunities[:positions_needed]):
                rec = self._create_trade_recommendation_from_screener(
                    result, gap, RecommendationPriority.HIGH
                )
                rec.strategy_type = preferred_strategies[0]
                recommendations.append(rec)
                
        except Exception as e:
            self.logger.error(f"❌ Failed to generate strategy bias recommendations: {e}")
            
        return recommendations
        
    def _generate_closing_recommendations(self, snapshot: PortfolioSnapshot,
                                        compliance_checks: List[ComplianceCheck]) -> List[TradeRecommendation]:
        """Generate recommendations to close overweight positions"""
        recommendations = []
        
        try:
            # Identify positions that should be closed for compliance
            for check in compliance_checks:
                if check.deviation_pct > check.rule.tolerance_pct and check.current_pct > check.target_pct:
                    # Overweight - need to close some positions
                    excess_pct = check.current_pct - check.rule.max_pct
                    excess_dollars = (excess_pct / 100.0) * snapshot.total_market_value
                    
                    # Find positions to close
                    positions_to_close = self._identify_positions_to_close(
                        snapshot.positions, check.rule.rule_type, check.rule.category, excess_dollars
                    )
                    
                    for pos in positions_to_close:
                        rec = TradeRecommendation(
                            recommendation_id=f"close_{pos.symbol}_{int(datetime.now().timestamp())}",
                            recommendation_type=RecommendationType.CLOSE,
                            priority=RecommendationPriority.CRITICAL,
                            symbol=pos.symbol,
                            underlying_symbol=pos.underlying_symbol,
                            strategy_type=pos.strategy_type,
                            action="SELL" if pos.quantity > 0 else "BUY",
                            entry_price=0,  # Closing at market
                            max_price=0,
                            quantity=abs(pos.quantity),
                            dte_target=pos.dte or 0,
                            delta_target=0,
                            allocation_impact={},
                            buying_power_required=0,  # Closing frees up buying power
                            expected_return=0,
                            max_risk=0,
                            confidence_score=90,  # High confidence for compliance
                            reasoning=f"Close for {check.rule.rule_type.value} compliance",
                            market_context="Compliance required",
                            created_at=datetime.now()
                        )
                        recommendations.append(rec)
                        
        except Exception as e:
            self.logger.error(f"❌ Failed to generate closing recommendations: {e}")
            
        return recommendations
        
    def _generate_rolling_recommendations(self, snapshot: PortfolioSnapshot) -> List[TradeRecommendation]:
        """Generate recommendations for expiring positions"""
        recommendations = []
        
        try:
            # Find positions expiring within 7 days
            expiring_positions = [
                pos for pos in snapshot.positions 
                if pos.dte is not None and pos.dte <= 7
            ]
            
            for pos in expiring_positions:
                # Determine if position should be rolled or closed
                if self._should_roll_position(pos):
                    rec = TradeRecommendation(
                        recommendation_id=f"roll_{pos.symbol}_{int(datetime.now().timestamp())}",
                        recommendation_type=RecommendationType.ROLL,
                        priority=RecommendationPriority.MEDIUM,
                        symbol=pos.symbol,
                        underlying_symbol=pos.underlying_symbol,
                        strategy_type=pos.strategy_type,
                        action="ROLL",
                        entry_price=0,  # To be determined
                        max_price=0,
                        quantity=abs(pos.quantity),
                        dte_target=30,  # Roll to 30 days
                        delta_target=pos.delta,
                        allocation_impact={},
                        buying_power_required=0,
                        expected_return=0,
                        max_risk=0,
                        confidence_score=75,
                        reasoning=f"Roll expiring position (DTE={pos.dte})",
                        market_context="Position management",
                        created_at=datetime.now()
                    )
                    recommendations.append(rec)
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to generate rolling recommendations: {e}")
            
        return recommendations
        
    def _generate_adjustment_recommendations(self, snapshot: PortfolioSnapshot) -> List[TradeRecommendation]:
        """Generate recommendations for position adjustments"""
        recommendations = []
        
        try:
            # Look for positions that might benefit from adjustments
            # This is simplified - could include delta hedging, profit taking, etc.
            
            for pos in snapshot.positions:
                # Example: Close positions at 50% profit
                if pos.market_value > 0 and hasattr(pos, 'unrealized_pnl'):
                    if getattr(pos, 'unrealized_pnl', 0) > (pos.market_value * 0.5):
                        rec = TradeRecommendation(
                            recommendation_id=f"profit_{pos.symbol}_{int(datetime.now().timestamp())}",
                            recommendation_type=RecommendationType.CLOSE,
                            priority=RecommendationPriority.LOW,
                            symbol=pos.symbol,
                            underlying_symbol=pos.underlying_symbol,
                            strategy_type=pos.strategy_type,
                            action="CLOSE",
                            entry_price=0,
                            max_price=0,
                            quantity=abs(pos.quantity),
                            dte_target=0,
                            delta_target=0,
                            allocation_impact={},
                            buying_power_required=0,
                            expected_return=getattr(pos, 'unrealized_pnl', 0),
                            max_risk=0,
                            confidence_score=85,
                            reasoning="Take 50% profit",
                            market_context="Profit management",
                            created_at=datetime.now()
                        )
                        recommendations.append(rec)
                        
        except Exception as e:
            self.logger.error(f"❌ Failed to generate adjustment recommendations: {e}")
            
        return recommendations
        
    def _create_trade_recommendation_from_screener(self, screener_result: Dict[str, Any],
                                                  gap: AllocationGap,
                                                  priority: RecommendationPriority) -> TradeRecommendation:
        """Create trade recommendation from screener result"""
        
        symbol = screener_result.get('symbol', '')
        
        # Determine strategy based on screener result and gap
        strategy_type = self._determine_strategy_for_gap(screener_result, gap)
        
        # Calculate position sizing based on gap requirements
        # Size each position appropriately for the gap
        position_size = max(
            self.min_position_size_dollars,
            min(self.max_single_trade_dollars, gap.required_allocation_dollars / 3)  # Aim for 3 positions per gap
        )
        
        # Get last price and validate it's not None
        last_price = screener_result.get('last_price')
        if last_price is None or last_price <= 0:
            self.logger.warning(f"⚠️ Cannot create recommendation for {symbol}: invalid last_price={last_price}")
            return None
        
        rec = TradeRecommendation(
            recommendation_id=f"open_{symbol}_{int(datetime.now().timestamp())}",
            recommendation_type=RecommendationType.OPEN,
            priority=priority,
            symbol=symbol,
            underlying_symbol=symbol,
            strategy_type=strategy_type,
            action="BTO",  # Buy to open
            entry_price=last_price,
            max_price=last_price * 1.02,  # 2% slippage
            quantity=max(1, int(position_size / last_price)),
            dte_target=30,  # Default
            delta_target=0.16,  # Default
            allocation_impact={
                gap.rule_type.value: {gap.category: gap.gap_pct}
            },
            buying_power_required=position_size,
            expected_return=position_size * 0.02,  # Estimate 2% return
            max_risk=position_size * 0.10,  # Estimate 10% max risk
            confidence_score=screener_result.get('screening_score', 60),
            reasoning=f"Fill {gap.rule_type.value} gap: {gap.category}",
            market_context=f"IV Rank: {screener_result.get('iv_rank', 0):.0f}%",
            created_at=datetime.now()
        )
        
        return rec
        
    def _filter_and_prioritize_recommendations(self, 
                                             recommendations: List[TradeRecommendation],
                                             available_buying_power: float) -> List[TradeRecommendation]:
        """Filter and prioritize recommendations based on constraints"""
        
        self.logger.info(f"🔍 Filtering {len(recommendations)} recommendations")
        self.logger.info(f"  - Available buying power: ${available_buying_power:,.0f}")
        self.logger.info(f"  - Min confidence threshold: {self.min_confidence_threshold}%")
        
        # Filter by confidence threshold
        filtered = [r for r in recommendations if r.confidence_score >= self.min_confidence_threshold]
        filtered_out = len(recommendations) - len(filtered)
        if filtered_out > 0:
            self.logger.info(f"  ⚠️ Filtered out {filtered_out} recommendations due to low confidence")
            # Log details of filtered recommendations
            for r in recommendations:
                if r.confidence_score < self.min_confidence_threshold:
                    self.logger.debug(f"    - {r.symbol}: confidence {r.confidence_score:.1f}% < {self.min_confidence_threshold}%")
        
        # Sort by priority then confidence
        filtered.sort(key=lambda x: (x.priority.value, -x.confidence_score))
        
        # Apply buying power constraints
        total_bp_used = 0
        
        # Defensive check for buying power
        if available_buying_power <= 0:
            self.logger.warning(f"⚠️ Available buying power is ${available_buying_power:,.0f} - using minimum threshold of $1000 for testing")
            # Use a minimum threshold for testing when buying power calculation fails
            effective_buying_power = max(1000, available_buying_power)
        else:
            effective_buying_power = available_buying_power
            
        max_bp = effective_buying_power * (self.max_total_allocation_pct / 100.0)
        self.logger.info(f"  - Max buying power allowed: ${max_bp:,.0f} ({self.max_total_allocation_pct}% of ${effective_buying_power:,.0f})")
        
        final_recommendations = []
        bp_filtered_count = 0
        
        for rec in filtered:
            if total_bp_used + rec.buying_power_required <= max_bp:
                final_recommendations.append(rec)
                total_bp_used += rec.buying_power_required
                self.logger.debug(f"    ✅ Accepted {rec.symbol}: BP required ${rec.buying_power_required:,.0f}, total used ${total_bp_used:,.0f}")
            else:
                bp_filtered_count += 1
                self.logger.debug(f"    ❌ Rejected {rec.symbol}: Would exceed BP limit (${total_bp_used + rec.buying_power_required:,.0f} > ${max_bp:,.0f})")
                
        if bp_filtered_count > 0:
            self.logger.info(f"  ⚠️ Filtered out {bp_filtered_count} recommendations due to buying power limits")
                
        # Don't arbitrarily limit positions - only what's needed
        self.logger.info(f"✅ Final recommendations: {len(final_recommendations)} positions (using ${total_bp_used:,.0f} buying power)")
            
        return final_recommendations
        
    def _determine_strategy_for_gap(self, screener_result: Dict[str, Any], 
                                  gap: AllocationGap) -> str:
        """Determine appropriate strategy based on screener result and gap type"""
        
        iv_rank = screener_result.get('iv_rank', 50)
        
        if gap.rule_type.value == 'strategy':
            if gap.category == 'bullish':
                return 'put_credit_spread' if iv_rank > 50 else 'call_debit_spread'
            elif gap.category == 'bearish':
                return 'call_credit_spread' if iv_rank > 50 else 'put_debit_spread'
            else:  # neutral
                return 'iron_condor' if iv_rank > 50 else 'iron_butterfly'
        else:
            # Default strategy selection based on IV
            return 'put_credit_spread' if iv_rank > 60 else 'iron_condor'
            
    def _get_liquid_symbols(self) -> List[str]:
        """Get list of liquid symbols for screening"""
        return [
            'AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'TSLA', 'AMZN', 'SPY', 'QQQ', 'IWM',
            'XLE', 'XLF', 'XLK', 'GLD', 'TLT', 'VIX', 'AMD', 'NFLX', 'CRM', 'PYPL'
        ]
    
    def _get_fallback_symbols(self) -> List[str]:
        """Get fallback symbols when Main List is not available"""
        return self._get_liquid_symbols()
    
    def _create_fallback_rankings(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Create basic rankings for fallback symbols"""
        rankings = []
        
        for i, symbol in enumerate(symbols):
            # Create basic ranking data
            ranking = {
                'symbol': symbol,
                'screening_score': 70 - i,  # Decreasing score
                'sector': 'Technology' if symbol in ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD'] else 'Other',
                'last_price': 100,  # Placeholder
                'iv_rank': 50,  # Placeholder
                'can_add_position': True,
                'concentration_warning': None
            }
            rankings.append(ranking)
            
        self.logger.info(f"📊 Created {len(rankings)} fallback rankings")
        return rankings
        
    def _should_roll_position(self, position) -> bool:
        """Determine if position should be rolled"""
        # Simplified logic - could be much more sophisticated
        return position.dte is not None and position.dte <= 7 and position.market_value > 0
        
    def _identify_positions_to_close(self, positions, rule_type, category, target_dollars):
        """Identify specific positions to close for compliance"""
        # Simplified - would need more sophisticated logic
        return []
        
    def _calculate_portfolio_impact(self, recommendations: List[TradeRecommendation]) -> Dict[str, Any]:
        """Calculate expected portfolio impact from recommendations"""
        
        total_bp_required = sum(r.buying_power_required for r in recommendations)
        total_expected_return = sum(r.expected_return for r in recommendations)
        
        return {
            'total_buying_power_required': total_bp_required,
            'total_expected_return': total_expected_return,
            'new_positions_count': len([r for r in recommendations if r.recommendation_type == RecommendationType.OPEN]),
            'closing_positions_count': len([r for r in recommendations if r.recommendation_type == RecommendationType.CLOSE])
        }
        
    def get_current_recommendations(self) -> Optional[RebalancingEvent]:
        """Get current rebalancing recommendations"""
        return self.current_event
        
    def _update_sector_rankings(self):
        """Update sector rankings to inform recommendation generation"""
        try:
            self.logger.info("🎯 Skipping sector rankings update to prevent timeout")
            
            # TEMPORARY FIX: Skip the expensive sector rankings calculation
            # This was causing the rebalancing trigger to hang/timeout
            # TODO: Implement async sector rankings or add proper timeout
            
            # Set default/cached rankings if available
            if not hasattr(self, 'current_sector_rankings') or not self.current_sector_rankings:
                self.current_sector_rankings = {
                    'equity_sectors': [],
                    'non_equity_sectors': []
                }
            
            self.logger.info("✅ Sector rankings update skipped (performance optimization)")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to update sector rankings: {e}")
            # Continue without rankings rather than failing the entire rebalancing
            self.current_sector_rankings = {'equity_sectors': [], 'non_equity_sectors': []}

    def approve_recommendations(self, recommendation_ids: List[str]) -> Dict[str, Any]:
        """Approve specific recommendations for execution"""
        if not self.current_event:
            return {'success': False, 'error': 'No current rebalancing event'}
            
        approved_count = 0
        
        for rec in self.current_event.recommendations:
            if rec.recommendation_id in recommendation_ids:
                # Mark as approved - would integrate with order manager
                approved_count += 1
                
        self.current_event.approved_at = datetime.now()
        self.current_event.status = "approved"
        
        return {
            'success': True,
            'approved_count': approved_count,
            'total_recommendations': len(self.current_event.recommendations)
        }