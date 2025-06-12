#!/usr/bin/env python3
"""
TastyTracker Trade Journal Manager
Main orchestrator for automated trade logging, analysis, and reporting
"""

import os
import logging
import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import asdict

# Local imports
from trade_journal import TradeJournal, TradeEntry, TradeStatus
from transaction_processor import TransactionProcessor
from probability_calculator import ProbabilityCalculator, OptionData, SpreadData, ProbabilityMetrics
from market_data_capture import MarketDataCapture, MarketRegimeData
from tastytrade import Session

class TradeJournalManager:
    """Main trade journal management system"""
    
    def __init__(self, tasty_client: Session, db_path: str = "trade_journal.db"):
        self.tasty_client = tasty_client
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        
        # Initialize components
        self.journal = TradeJournal(tasty_client, db_path)
        self.processor = TransactionProcessor(self.journal)
        self.prob_calc = ProbabilityCalculator()
        self.market_capture = MarketDataCapture(tasty_client)
        
        # Auto-processing settings
        self.auto_capture_enabled = True
        self.auto_probability_calc = True
        self.auto_market_snapshot = True
        
        self.logger.info("✅ Trade Journal Manager initialized")
    
    def process_account_trades(self, account_number: str, start_date: Optional[datetime] = None,
                              end_date: Optional[datetime] = None, enhance_data: bool = True) -> Dict[str, Any]:
        """Process all trades for an account with full data enhancement"""
        try:
            self.logger.info(f"🔄 Processing trades for account {account_number}")
            
            # Step 1: Process transactions into trade entries
            result = self.processor.process_account_transactions(
                account_number=account_number,
                start_date=start_date,
                end_date=end_date
            )
            
            if not result['success']:
                return result
            
            # Step 2: Enhance trades with additional data if requested
            if enhance_data and result['trades_processed'] > 0:
                self.logger.info("🔧 Enhancing trade data with probabilities and market context")
                
                enhancement_result = self.enhance_all_trades(
                    account_number=account_number,
                    trade_ids=result.get('processed_trade_ids', [])
                )
                
                result['enhancement_summary'] = enhancement_result
            
            return result
            
        except Exception as e:
            error_msg = f"Error processing account trades: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'message': error_msg,
                'trades_processed': 0
            }
    
    def enhance_all_trades(self, account_number: str, trade_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Enhance trades with probability calculations and market context"""
        try:
            # Get trades to enhance
            if trade_ids:
                trades_to_enhance = []
                for trade_id in trade_ids:
                    trades = self.journal.get_trades(limit=1000)  # Get all, then filter
                    trade = next((t for t in trades if t.trade_id == trade_id), None)
                    if trade:
                        trades_to_enhance.append(trade)
            else:
                trades_to_enhance = self.journal.get_trades(account_number=account_number, limit=1000)
            
            enhanced_count = 0
            failed_count = 0
            enhancement_log = []
            
            for trade in trades_to_enhance:
                try:
                    enhanced = False
                    
                    # Calculate probabilities if missing
                    if self.auto_probability_calc and not trade.pop_entry:
                        prob_result = self.calculate_trade_probabilities(trade)
                        if prob_result:
                            trade.pop_entry = prob_result.pop
                            trade.p50_entry = prob_result.p50
                            trade.pot_entry = prob_result.pot
                            enhanced = True
                    
                    # Capture market context if missing
                    if self.auto_market_snapshot and not trade.spx_price_entry:
                        market_context = self.get_trade_market_context(trade)
                        if market_context:
                            trade.spx_price_entry = market_context.spx_price
                            trade.vix_level_entry = market_context.vix_level
                            trade.ten_year_yield_entry = market_context.ten_year_yield
                            enhanced = True
                    
                    # Calculate additional metrics
                    if enhanced or not trade.return_on_capital:
                        self.calculate_additional_metrics(trade)
                        enhanced = True
                    
                    # Save enhanced trade
                    if enhanced:
                        if self.journal.save_trade(trade):
                            enhanced_count += 1
                            enhancement_log.append(f"Enhanced {trade.trade_id}")
                        else:
                            failed_count += 1
                            enhancement_log.append(f"Failed to save {trade.trade_id}")
                    
                except Exception as e:
                    failed_count += 1
                    error_msg = f"Failed to enhance {trade.trade_id}: {str(e)}"
                    enhancement_log.append(error_msg)
                    self.logger.error(f"❌ {error_msg}")
            
            result = {
                'trades_enhanced': enhanced_count,
                'trades_failed': failed_count,
                'enhancement_log': enhancement_log
            }
            
            self.logger.info(f"✅ Enhanced {enhanced_count} trades, {failed_count} failed")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error enhancing trades: {e}")
            return {
                'trades_enhanced': 0,
                'trades_failed': 0,
                'error': str(e)
            }
    
    def calculate_trade_probabilities(self, trade: TradeEntry) -> Optional[ProbabilityMetrics]:
        """Calculate probability metrics for a trade"""
        try:
            if not all([trade.underlying_price_entry, trade.dte_at_entry]):
                return None
            
            # Convert DTE to years
            time_to_expiry = trade.dte_at_entry / 365.0
            
            # Get volatility estimate (use IV rank if available, otherwise default)
            volatility = (trade.iv_rank_entry or 25.0) / 100.0
            
            # Calculate probabilities based on strategy type
            if trade.strategy_type in ['put_credit_spread', 'call_credit_spread']:
                if not all([trade.strike_short, trade.strike_long, trade.entry_credit]):
                    return None
                
                spread_data = SpreadData(
                    underlying_price=trade.underlying_price_entry,
                    short_strike=trade.strike_short,
                    long_strike=trade.strike_long,
                    time_to_expiry=time_to_expiry,
                    risk_free_rate=0.05,  # Default 5%
                    volatility=volatility,
                    strategy_type=trade.strategy_type,
                    credit_received=trade.entry_credit
                )
                
                return self.prob_calc.calculate_spread_probabilities(spread_data)
            
            elif trade.strategy_type in ['naked_put', 'naked_call']:
                if not trade.strike_short:
                    return None
                
                option_data = OptionData(
                    underlying_price=trade.underlying_price_entry,
                    strike_price=trade.strike_short,
                    time_to_expiry=time_to_expiry,
                    risk_free_rate=0.05,
                    volatility=volatility,
                    option_type='put' if 'put' in trade.strategy_type else 'call'
                )
                
                return self.prob_calc.calculate_single_option_probabilities(
                    option_data, trade.entry_credit
                )
            
            else:
                # For other strategies, return basic calculations
                return ProbabilityMetrics(
                    pop=50.0,  # Placeholder
                    p50=25.0,  # Placeholder
                    pot=30.0   # Placeholder
                )
                
        except Exception as e:
            self.logger.error(f"❌ Error calculating probabilities for {trade.trade_id}: {e}")
            return None
    
    def get_trade_market_context(self, trade: TradeEntry) -> Optional[MarketRegimeData]:
        """Get market context for a trade's entry date"""
        try:
            if not trade.entry_date:
                return None
            
            # Try to get historical market data for the trade date
            historical_regime = self.market_capture.get_historical_regime(
                trade.entry_date, self.db_path
            )
            
            if historical_regime:
                return historical_regime
            
            # If no historical data, capture current regime as fallback
            # (This would be the case for recent trades)
            time_diff = datetime.now() - trade.entry_date
            if time_diff.days <= 1:  # Recent trade
                current_regime = self.market_capture.get_current_market_regime()
                # Save it for future reference
                self.market_capture.save_market_snapshot(current_regime, self.db_path)
                return current_regime
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error getting market context for {trade.trade_id}: {e}")
            return None
    
    def calculate_additional_metrics(self, trade: TradeEntry):
        """Calculate additional performance metrics"""
        try:
            # Return on Capital
            if trade.buying_power_reduction > 0 and trade.realized_pnl != 0:
                trade.return_on_capital = (trade.realized_pnl / trade.buying_power_reduction) * 100
            
            # Percentage of max profit/loss captured
            if trade.status == TradeStatus.CLOSED:
                if trade.max_profit > 0:
                    trade.pct_max_profit_captured = (trade.realized_pnl / trade.max_profit) * 100
                
                if trade.max_loss > 0:
                    trade.pct_max_loss_captured = (abs(trade.realized_pnl) / trade.max_loss) * 100
            
            # Days held calculation
            if trade.exit_date and trade.entry_date:
                trade.days_held = (trade.exit_date.date() - trade.entry_date.date()).days
            
            # Winner/loser classification
            if trade.realized_pnl > 0:
                trade.winner = True
                trade.outcome_tag = "Winner"
            elif trade.realized_pnl < 0:
                trade.winner = False
                trade.outcome_tag = "Loser"
            else:
                trade.winner = False
                trade.outcome_tag = "Breakeven"
            
            # Net P&L after fees
            trade.net_pnl_after_fees = trade.realized_pnl - trade.total_commissions - trade.total_fees
            
            # Check if managed at 50%
            if trade.pct_max_profit_captured and 45 <= trade.pct_max_profit_captured <= 55:
                trade.managed_at_50pct = True
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating additional metrics for {trade.trade_id}: {e}")
    
    def generate_comprehensive_report(self, account_number: Optional[str] = None,
                                    start_date: Optional[datetime] = None,
                                    end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Generate comprehensive trade journal report"""
        try:
            self.logger.info("📊 Generating comprehensive trade report")
            
            # Get trades for analysis
            trades = self.journal.get_trades(account_number=account_number, limit=1000)
            
            # Filter by date range if specified
            if start_date or end_date:
                filtered_trades = []
                for trade in trades:
                    if trade.entry_date:
                        if start_date and trade.entry_date < start_date:
                            continue
                        if end_date and trade.entry_date > end_date:
                            continue
                        filtered_trades.append(trade)
                trades = filtered_trades
            
            if not trades:
                return {'error': 'No trades found for analysis'}
            
            # Basic statistics
            closed_trades = [t for t in trades if t.status == TradeStatus.CLOSED]
            winners = [t for t in closed_trades if t.winner]
            
            # Strategy breakdown
            strategy_stats = {}
            for trade in closed_trades:
                strategy = trade.strategy_type
                if strategy not in strategy_stats:
                    strategy_stats[strategy] = {
                        'count': 0, 'winners': 0, 'total_pnl': 0,
                        'avg_dte': [], 'avg_pop': [], 'managed_at_50pct': 0
                    }
                
                stats = strategy_stats[strategy]
                stats['count'] += 1
                if trade.winner:
                    stats['winners'] += 1
                stats['total_pnl'] += trade.realized_pnl
                
                if trade.dte_at_entry:
                    stats['avg_dte'].append(trade.dte_at_entry)
                if trade.pop_entry:
                    stats['avg_pop'].append(trade.pop_entry)
                if trade.managed_at_50pct:
                    stats['managed_at_50pct'] += 1
            
            # Calculate averages and win rates
            for strategy, stats in strategy_stats.items():
                stats['win_rate'] = (stats['winners'] / stats['count']) * 100 if stats['count'] > 0 else 0
                stats['avg_pnl'] = stats['total_pnl'] / stats['count'] if stats['count'] > 0 else 0
                stats['avg_dte'] = sum(stats['avg_dte']) / len(stats['avg_dte']) if stats['avg_dte'] else 0
                stats['avg_pop'] = sum(stats['avg_pop']) / len(stats['avg_pop']) if stats['avg_pop'] else 0
                stats['pct_managed_50'] = (stats['managed_at_50pct'] / stats['count']) * 100 if stats['count'] > 0 else 0
            
            # POP vs Actual Performance Analysis
            pop_analysis = self._analyze_pop_performance(closed_trades)
            
            # Market regime analysis
            regime_analysis = self._analyze_by_market_regime(closed_trades)
            
            # Time-based analysis
            time_analysis = self._analyze_by_time_periods(closed_trades)
            
            report = {
                'report_generated': datetime.now().isoformat(),
                'analysis_period': {
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'total_trades': len(trades),
                    'closed_trades': len(closed_trades),
                    'open_trades': len(trades) - len(closed_trades)
                },
                'overall_performance': {
                    'win_rate': (len(winners) / len(closed_trades)) * 100 if closed_trades else 0,
                    'total_pnl': sum(t.realized_pnl for t in closed_trades),
                    'avg_pnl_per_trade': sum(t.realized_pnl for t in closed_trades) / len(closed_trades) if closed_trades else 0,
                    'total_commissions': sum(t.total_commissions for t in closed_trades),
                    'net_pnl_after_fees': sum(t.net_pnl_after_fees for t in closed_trades),
                    'avg_days_held': sum(t.days_held for t in closed_trades if t.days_held) / len(closed_trades) if closed_trades else 0,
                    'largest_winner': max((t.realized_pnl for t in closed_trades), default=0),
                    'largest_loser': min((t.realized_pnl for t in closed_trades), default=0)
                },
                'strategy_breakdown': strategy_stats,
                'pop_analysis': pop_analysis,
                'market_regime_analysis': regime_analysis,
                'time_analysis': time_analysis
            }
            
            self.logger.info(f"✅ Generated report for {len(trades)} trades")
            return report
            
        except Exception as e:
            self.logger.error(f"❌ Error generating report: {e}")
            return {'error': str(e)}
    
    def _analyze_pop_performance(self, trades: List[TradeEntry]) -> Dict[str, Any]:
        """Analyze actual performance vs predicted POP"""
        try:
            pop_buckets = {
                'high_pop': {'trades': [], 'threshold': 70},
                'medium_pop': {'trades': [], 'threshold': 50},
                'low_pop': {'trades': [], 'threshold': 0}
            }
            
            for trade in trades:
                if trade.pop_entry:
                    if trade.pop_entry >= 70:
                        pop_buckets['high_pop']['trades'].append(trade)
                    elif trade.pop_entry >= 50:
                        pop_buckets['medium_pop']['trades'].append(trade)
                    else:
                        pop_buckets['low_pop']['trades'].append(trade)
            
            analysis = {}
            for bucket_name, bucket_data in pop_buckets.items():
                bucket_trades = bucket_data['trades']
                if bucket_trades:
                    winners = [t for t in bucket_trades if t.winner]
                    actual_win_rate = (len(winners) / len(bucket_trades)) * 100
                    avg_predicted_pop = sum(t.pop_entry for t in bucket_trades) / len(bucket_trades)
                    
                    analysis[bucket_name] = {
                        'trade_count': len(bucket_trades),
                        'actual_win_rate': actual_win_rate,
                        'predicted_win_rate': avg_predicted_pop,
                        'pop_accuracy': abs(actual_win_rate - avg_predicted_pop),
                        'avg_pnl': sum(t.realized_pnl for t in bucket_trades) / len(bucket_trades)
                    }
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error in POP analysis: {e}")
            return {}
    
    def _analyze_by_market_regime(self, trades: List[TradeEntry]) -> Dict[str, Any]:
        """Analyze performance by market regime"""
        try:
            regime_buckets = {}
            
            for trade in trades:
                # Use VIX level as proxy for regime if available
                if trade.vix_level_entry:
                    if trade.vix_level_entry < 20:
                        regime = 'low_vol'
                    elif trade.vix_level_entry < 30:
                        regime = 'medium_vol'
                    else:
                        regime = 'high_vol'
                    
                    if regime not in regime_buckets:
                        regime_buckets[regime] = []
                    regime_buckets[regime].append(trade)
            
            analysis = {}
            for regime, regime_trades in regime_buckets.items():
                if regime_trades:
                    winners = [t for t in regime_trades if t.winner]
                    analysis[regime] = {
                        'trade_count': len(regime_trades),
                        'win_rate': (len(winners) / len(regime_trades)) * 100,
                        'avg_pnl': sum(t.realized_pnl for t in regime_trades) / len(regime_trades),
                        'avg_vix': sum(t.vix_level_entry for t in regime_trades if t.vix_level_entry) / len(regime_trades)
                    }
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error in regime analysis: {e}")
            return {}
    
    def _analyze_by_time_periods(self, trades: List[TradeEntry]) -> Dict[str, Any]:
        """Analyze performance by time periods (monthly, quarterly)"""
        try:
            monthly_data = {}
            
            for trade in trades:
                if trade.entry_date:
                    month_key = trade.entry_date.strftime('%Y-%m')
                    if month_key not in monthly_data:
                        monthly_data[month_key] = []
                    monthly_data[month_key].append(trade)
            
            monthly_analysis = {}
            for month, month_trades in monthly_data.items():
                if month_trades:
                    winners = [t for t in month_trades if t.winner]
                    monthly_analysis[month] = {
                        'trade_count': len(month_trades),
                        'win_rate': (len(winners) / len(month_trades)) * 100,
                        'total_pnl': sum(t.realized_pnl for t in month_trades),
                        'avg_pnl': sum(t.realized_pnl for t in month_trades) / len(month_trades)
                    }
            
            return {'monthly': monthly_analysis}
            
        except Exception as e:
            self.logger.error(f"Error in time analysis: {e}")
            return {}
    
    def export_trades_to_csv(self, file_path: str, account_number: Optional[str] = None) -> bool:
        """Export trade journal to CSV file"""
        try:
            import csv
            
            trades = self.journal.get_trades(account_number=account_number, limit=10000)
            
            if not trades:
                self.logger.warning("No trades to export")
                return False
            
            # Define CSV headers based on TradeEntry fields
            headers = [
                'trade_id', 'account_number', 'underlying_symbol', 'strategy_type',
                'entry_date', 'exit_date', 'dte_at_entry', 'dte_at_exit',
                'underlying_price_entry', 'underlying_price_exit',
                'strike_short', 'strike_long', 'strike_width', 'contracts',
                'entry_credit', 'entry_debit', 'exit_credit', 'exit_debit',
                'max_profit', 'max_loss', 'realized_pnl', 'realized_pnl_pct',
                'return_on_capital', 'days_held', 'winner', 'outcome_tag',
                'pop_entry', 'p50_entry', 'pot_entry',
                'vix_level_entry', 'spx_price_entry', 'iv_rank_entry',
                'total_commissions', 'total_fees', 'net_pnl_after_fees',
                'managed_at_50pct', 'trade_notes'
            ]
            
            with open(file_path, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                
                for trade in trades:
                    row = {}
                    for header in headers:
                        value = getattr(trade, header, '')
                        if isinstance(value, (datetime, date)):
                            value = value.isoformat() if value else ''
                        elif isinstance(value, bool):
                            value = 'Yes' if value else 'No'
                        elif value is None:
                            value = ''
                        row[header] = value
                    
                    writer.writerow(row)
            
            self.logger.info(f"✅ Exported {len(trades)} trades to {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error exporting to CSV: {e}")
            return False
    
    def get_trade_journal_status(self) -> Dict[str, Any]:
        """Get current status of the trade journal system"""
        try:
            summary = self.journal.get_trade_summary()
            
            # Add system status information
            status = {
                'database_path': self.db_path,
                'auto_capture_enabled': self.auto_capture_enabled,
                'auto_probability_calc': self.auto_probability_calc,
                'auto_market_snapshot': self.auto_market_snapshot,
                'trade_summary': summary,
                'last_market_snapshot': self._get_last_market_snapshot_time(),
                'system_health': 'healthy'  # Could add more sophisticated health checks
            }
            
            return status
            
        except Exception as e:
            self.logger.error(f"❌ Error getting system status: {e}")
            return {'error': str(e)}
    
    def _get_last_market_snapshot_time(self) -> Optional[str]:
        """Get timestamp of last market snapshot"""
        try:
            import sqlite3
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT MAX(timestamp) FROM market_snapshots')
                result = cursor.fetchone()
                return result[0] if result and result[0] else None
                
        except Exception as e:
            self.logger.error(f"Error getting last snapshot time: {e}")
            return None