#!/usr/bin/env python3
"""
Rebalancing API Routes
Flask routes for automated portfolio rebalancing functionality
"""

import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from typing import Optional, Dict, Any

from automated_rebalancer import AutomatedRebalancer, RecommendationType, RecommendationPriority
from allocation_rules_manager import AllocationRulesManager, RuleType, AllocationRule
from portfolio_analyzer import PortfolioAnalyzer

# Create blueprint for rebalancing routes
rebalancing_bp = Blueprint('rebalancing', __name__)

# Global rebalancer instance (will be initialized when needed)
rebalancer = None
allocation_manager = None

def get_rebalancer(tracker_instance):
    """Get or create rebalancer instance"""
    global rebalancer, allocation_manager
    
    if rebalancer is None:
        # Get the global tracker instance if none provided
        if tracker_instance is None:
            try:
                from app import tracker as global_tracker
                tracker_instance = global_tracker
            except ImportError:
                # Fallback: try to get from delta_backend
                try:
                    from delta_backend import tracker as global_tracker
                    tracker_instance = global_tracker
                except ImportError:
                    logging.error("❌ Cannot find tracker instance - routes not properly initialized")
                    raise RuntimeError("Tracker instance not available - ensure rebalancing routes are properly initialized")
            
        rebalancer = AutomatedRebalancer(tracker_instance)
        allocation_manager = AllocationRulesManager()
        
        # Start fill monitoring
        rebalancer.start_fill_monitoring()
        
        logging.info("✅ Automated rebalancer initialized")
    
    return rebalancer, allocation_manager

@rebalancing_bp.route('/api/rebalancing/status')
def get_rebalancing_status():
    """Get current rebalancing status and recommendations"""
    try:
        rebalancer_instance, _ = get_rebalancer(None)
        current_event = rebalancer_instance.get_current_recommendations()
        
        if current_event is None:
            return jsonify({
                'success': True,
                'has_recommendations': False,
                'message': 'No active rebalancing recommendations'
            })
        
        # Convert recommendations to JSON-serializable format
        recommendations_data = []
        for rec in current_event.recommendations:
            rec_data = {
                'recommendation_id': rec.recommendation_id,
                'type': rec.recommendation_type.value,
                'priority': rec.priority.value,
                'symbol': rec.symbol,
                'underlying_symbol': rec.underlying_symbol,
                'strategy_type': rec.strategy_type,
                'action': rec.action,
                'entry_price': rec.entry_price,
                'max_price': rec.max_price,
                'quantity': rec.quantity,
                'dte_target': rec.dte_target,
                'delta_target': rec.delta_target,
                'buying_power_required': rec.buying_power_required,
                'expected_return': rec.expected_return,
                'max_risk': rec.max_risk,
                'confidence_score': rec.confidence_score,
                'reasoning': rec.reasoning,
                'market_context': rec.market_context,
                'created_at': rec.created_at.isoformat()
            }
            recommendations_data.append(rec_data)
        
        # Portfolio snapshot summary
        snapshot_summary = {
            'total_market_value': current_event.portfolio_snapshot.total_market_value,
            'total_buying_power': current_event.portfolio_snapshot.total_buying_power,
            'cash_balance': current_event.portfolio_snapshot.cash_balance,
            'total_positions': len(current_event.portfolio_snapshot.positions)
        }
        
        # Compliance summary
        compliance_summary = {
            'total_checks': len(current_event.compliance_checks),
            'violations': len([c for c in current_event.compliance_checks if c.status.value == 'violation']),
            'warnings': len([c for c in current_event.compliance_checks if c.status.value == 'warning']),
            'compliant': len([c for c in current_event.compliance_checks if c.status.value == 'compliant'])
        }
        
        return jsonify({
            'success': True,
            'has_recommendations': True,
            'event_id': current_event.event_id,
            'trigger_event': current_event.trigger_event,
            'status': current_event.status,
            'created_at': current_event.created_at.isoformat(),
            'recommendations': recommendations_data,
            'recommendations_count': len(recommendations_data),
            'total_buying_power_required': current_event.total_buying_power_required,
            'portfolio_snapshot': snapshot_summary,
            'compliance_summary': compliance_summary,
            'expected_impact': current_event.expected_portfolio_impact
        })
        
    except Exception as e:
        logging.error(f"❌ Error getting rebalancing status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/rebalancing/diagnostics')
def get_rebalancing_diagnostics():
    """Get diagnostic information about rebalancing system"""
    try:
        rebalancer_instance, allocation_manager = get_rebalancer(None)
        
        # Test screener rankings
        rankings_info = {}
        try:
            rankings = rebalancer_instance._get_cached_rankings()
            rankings_info = {
                'available': True,
                'count': len(rankings),
                'sample_symbols': [r['symbol'] for r in rankings[:5]] if rankings else []
            }
        except Exception as e:
            rankings_info = {
                'available': False,
                'error': str(e)
            }
        
        # Test portfolio analysis
        portfolio_info = {}
        try:
            snapshot = rebalancer_instance.portfolio_analyzer.analyze_current_portfolio()
            portfolio_info = {
                'available': True,
                'total_value': snapshot.total_market_value,
                'buying_power': snapshot.total_buying_power,
                'positions_count': len(snapshot.positions),
                'asset_allocation': snapshot.asset_allocation,
                'duration_allocation': snapshot.duration_allocation
            }
        except Exception as e:
            portfolio_info = {
                'available': False,
                'error': str(e)
            }
        
        # Test allocation rules
        rules_info = {}
        try:
            rules = allocation_manager.get_all_rules()
            rules_info = {
                'available': True,
                'count': len(rules),
                'rule_categories': [r.category for r in rules]
            }
        except Exception as e:
            rules_info = {
                'available': False,
                'error': str(e)
            }
        
        # Test gap identification
        gaps_info = {}
        if portfolio_info.get('available') and rules_info.get('available'):
            try:
                current_allocations = {
                    'asset_allocation': portfolio_info['asset_allocation'],
                    'duration_allocation': portfolio_info['duration_allocation'],
                    'strategy_allocation': {}
                }
                gaps = allocation_manager.identify_allocation_gaps(
                    current_allocations,
                    portfolio_info['total_value'],
                    portfolio_info['buying_power']
                )
                gaps_info = {
                    'available': True,
                    'count': len(gaps),
                    'gaps': [{
                        'category': gap.category,
                        'current_pct': gap.current_pct,
                        'target_pct': gap.target_pct,
                        'gap_pct': gap.gap_pct,
                        'gap_dollars': gap.required_allocation_dollars
                    } for gap in gaps]
                }
            except Exception as e:
                gaps_info = {
                    'available': False,
                    'error': str(e)
                }
        else:
            gaps_info = {'available': False, 'error': 'Portfolio or rules not available'}
        
        # Configuration info
        config_info = {
            'min_position_size': rebalancer_instance.min_position_size_dollars,
            'max_single_trade': rebalancer_instance.max_single_trade_dollars,
            'min_confidence': rebalancer_instance.min_confidence_threshold,
            'max_positions_per_gap': rebalancer_instance.max_positions_per_gap
        }
        
        return jsonify({
            'success': True,
            'rankings': rankings_info,
            'portfolio': portfolio_info,
            'rules': rules_info,
            'gaps': gaps_info,
            'config': config_info,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logging.error(f"❌ Error in diagnostics: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/rebalancing/debug-portfolio', methods=['GET'])
def debug_portfolio_analysis():
    """Debug endpoint to see portfolio analysis details"""
    try:
        rebalancer_instance, _ = get_rebalancer(None)
        portfolio_analyzer = rebalancer_instance.portfolio_analyzer
        
        # Get dashboard data directly
        dashboard_data = rebalancer_instance.tracker.get_dashboard_data()
        positions = dashboard_data.get('positions', [])
        
        # Convert positions for display
        portfolio_positions = portfolio_analyzer._convert_positions_for_display(positions)
        
        # Check some position details
        position_details = []
        total_market_value = 0
        
        for pos in portfolio_positions[:5]:  # First 5 positions
            total_market_value += pos.market_value
            position_details.append({
                'symbol': pos.symbol,
                'underlying': pos.underlying_symbol,
                'instrument_type': pos.instrument_type,
                'strategy_type': pos.strategy_type,
                'market_value': pos.market_value,
                'is_equity': pos.is_equity,
                'is_bullish': pos.is_bullish,
                'is_neutral': pos.is_neutral,
                'is_bearish': pos.is_bearish,
                'sector': pos.sector
            })
        
        # Calculate allocations manually
        equity_value = sum(pos.market_value for pos in portfolio_positions if pos.is_equity)
        non_equity_value = sum(pos.market_value for pos in portfolio_positions if not pos.is_equity)
        total_calculated = equity_value + non_equity_value
        
        return jsonify({
            'success': True,
            'raw_positions_count': len(positions),
            'converted_positions_count': len(portfolio_positions),
            'first_5_positions': position_details,
            'total_market_value_calculated': total_calculated,
            'equity_value': equity_value,
            'non_equity_value': non_equity_value,
            'equity_pct': (equity_value / total_calculated * 100) if total_calculated > 0 else 0,
            'non_equity_pct': (non_equity_value / total_calculated * 100) if total_calculated > 0 else 0
        })
        
    except Exception as e:
        logging.error(f"❌ Error in debug portfolio analysis: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/rebalancing/test-trigger', methods=['POST'])
def test_trigger_rebalancing():
    """Test trigger with relaxed thresholds for debugging"""
    try:
        rebalancer_instance, _ = get_rebalancer(None)
        
        data = request.get_json() or {}
        lower_thresholds = data.get('lower_thresholds', False)
        
        # Temporarily lower thresholds if requested
        original_min_position = rebalancer_instance.min_position_size_dollars
        original_gap_threshold = 1.0  # Default gap threshold
        
        if lower_thresholds:
            rebalancer_instance.min_position_size_dollars = 250  # Lower from 500 to 250
            logging.info("🧪 Test mode: Using lower thresholds (min position: $250)")
        
        # Also modify allocation manager gap threshold temporarily
        if lower_thresholds:
            # We'll need to patch the identify_allocation_gaps method
            from allocation_rules_manager import AllocationRulesManager
            original_method = AllocationRulesManager.identify_allocation_gaps
            
            def patched_identify_gaps(self, current_allocations, total_portfolio_value, available_buying_power):
                """Temporary version with lower thresholds"""
                gaps = []
                try:
                    compliance_checks = self.check_compliance(current_allocations, total_portfolio_value)
                    
                    for check in compliance_checks:
                        if check.status.value in ['warning', 'violation']:
                            gap_pct = check.target_pct - check.current_pct
                            
                            # Lower threshold to 0.25% for testing
                            if abs(gap_pct) > 0.25:
                                if gap_pct > 0:
                                    required_dollars = (gap_pct / 100.0) * total_portfolio_value
                                    required_dollars = min(required_dollars, available_buying_power)
                                else:
                                    required_dollars = abs(gap_pct / 100.0) * total_portfolio_value
                                
                                priority = 1 if check.status.value == 'violation' else (
                                    2 if abs(gap_pct) > 5.0 else (
                                        3 if abs(gap_pct) > 3.0 else 4
                                    )
                                )
                                
                                from allocation_rules_manager import AllocationGap
                                gap = AllocationGap(
                                    rule_type=check.rule.rule_type,
                                    category=check.rule.category,
                                    current_pct=check.current_pct,
                                    target_pct=check.target_pct,
                                    gap_pct=gap_pct,
                                    required_allocation_dollars=required_dollars,
                                    priority=priority
                                )
                                gaps.append(gap)
                                
                    logging.info(f"🧪 Test mode: Found {len(gaps)} gaps with 0.25% threshold")
                    return gaps
                    
                except Exception as e:
                    logging.error(f"❌ Error in patched gap identification: {e}")
                    return []
            
            # Temporarily patch the method
            AllocationRulesManager.identify_allocation_gaps = patched_identify_gaps
        
        try:
            # Trigger the rebalancing
            event_id = rebalancer_instance.trigger_rebalancing(
                trigger_event='test_manual',
                trigger_details={'reason': 'test_with_lower_thresholds', 'lower_thresholds': lower_thresholds}
            )
            
            return jsonify({
                'success': True,
                'event_id': event_id,
                'message': f'Test rebalancing analysis triggered (lower_thresholds: {lower_thresholds})',
                'test_mode': lower_thresholds
            })
            
        finally:
            # Restore original thresholds
            if lower_thresholds:
                rebalancer_instance.min_position_size_dollars = original_min_position
                # Restore original method
                AllocationRulesManager.identify_allocation_gaps = original_method
                logging.info("🧪 Test mode: Restored original thresholds")
        
    except Exception as e:
        logging.error(f"❌ Error in test trigger: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/rebalancing/trigger', methods=['POST'])
def trigger_rebalancing():
    """Manually trigger portfolio rebalancing"""
    try:
        data = request.get_json() or {}
        trigger_reason = data.get('reason', 'manual_trigger')
        
        logging.info(f"🔄 Rebalancing trigger requested: {trigger_reason}")
        
        # Try to get rebalancer instance
        try:
            rebalancer_instance, _ = get_rebalancer(None)
            if rebalancer_instance is None:
                raise RuntimeError("Rebalancer instance is None")
        except Exception as e:
            logging.error(f"❌ Failed to get rebalancer instance for trigger: {e}")
            return jsonify({'success': False, 'error': f'Rebalancer initialization failed: {str(e)}'}), 500
        
        # Try to trigger rebalancing
        try:
            event_id = rebalancer_instance.trigger_rebalancing(
                trigger_event='manual',
                trigger_details={'reason': trigger_reason, 'user_triggered': True}
            )
        except Exception as e:
            logging.error(f"❌ Failed to trigger rebalancing: {e}")
            return jsonify({'success': False, 'error': f'Rebalancing trigger failed: {str(e)}'}), 500
        
        logging.info(f"✅ Rebalancing triggered successfully: {event_id}")
        return jsonify({
            'success': True,
            'event_id': event_id,
            'message': 'Rebalancing analysis triggered successfully'
        })
        
    except Exception as e:
        logging.error(f"❌ Unexpected error triggering rebalancing: {e}")
        import traceback
        logging.error(f"❌ Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Unexpected error: {str(e)}'}), 500

@rebalancing_bp.route('/api/rebalancing/approve', methods=['POST'])
def approve_recommendations():
    """Approve specific recommendations for execution"""
    try:
        rebalancer_instance, _ = get_rebalancer(None)
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
            
        recommendation_ids = data.get('recommendation_ids', [])
        if not recommendation_ids:
            return jsonify({'success': False, 'error': 'No recommendation IDs provided'}), 400
        
        result = rebalancer_instance.approve_recommendations(recommendation_ids)
        
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"❌ Error approving recommendations: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/allocation-rules')
def get_allocation_rules():
    """Get all allocation rules"""
    try:
        _, allocation_manager_instance = get_rebalancer(None)
        
        rules = allocation_manager_instance.get_all_rules()
        
        rules_data = []
        for rule in rules:
            rule_data = {
                'rule_type': rule.rule_type.value,
                'category': rule.category,
                'target_pct': rule.target_pct,
                'min_pct': rule.min_pct,
                'max_pct': rule.max_pct,
                'tolerance_pct': rule.tolerance_pct,
                'created_at': rule.created_at.isoformat() if rule.created_at else None,
                'updated_at': rule.updated_at.isoformat() if rule.updated_at else None
            }
            rules_data.append(rule_data)
        
        # Group by rule type for easier frontend consumption
        grouped_rules = {
            'asset': [r for r in rules_data if r['rule_type'] == 'asset'],
            'duration': [r for r in rules_data if r['rule_type'] == 'duration'],
            'strategy': [r for r in rules_data if r['rule_type'] == 'strategy']
        }
        
        return jsonify({
            'success': True,
            'rules': rules_data,
            'grouped_rules': grouped_rules,
            'summary': allocation_manager_instance.get_compliance_summary()
        })
        
    except Exception as e:
        logging.error(f"❌ Error getting allocation rules: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/allocation-rules', methods=['PUT'])
def update_allocation_rules():
    """Update allocation rules"""
    try:
        _, allocation_manager_instance = get_rebalancer(None)
        
        data = request.get_json()
        if not data or 'rules' not in data:
            return jsonify({'success': False, 'error': 'No rules data provided'}), 400
        
        updated_count = 0
        errors = []
        
        for rule_data in data['rules']:
            try:
                rule = AllocationRule(
                    rule_type=RuleType(rule_data['rule_type']),
                    category=rule_data['category'],
                    target_pct=float(rule_data['target_pct']),
                    min_pct=float(rule_data['min_pct']),
                    max_pct=float(rule_data['max_pct']),
                    tolerance_pct=float(rule_data.get('tolerance_pct', 2.0))
                )
                
                if allocation_manager_instance.save_rule(rule):
                    updated_count += 1
                else:
                    errors.append(f"Failed to save rule: {rule.category}")
                    
            except Exception as e:
                errors.append(f"Error processing rule {rule_data.get('category', 'unknown')}: {str(e)}")
        
        return jsonify({
            'success': len(errors) == 0,
            'updated_count': updated_count,
            'errors': errors
        })
        
    except Exception as e:
        logging.error(f"❌ Error updating allocation rules: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/allocation-compliance')
def check_allocation_compliance():
    """Check current portfolio compliance against allocation rules"""
    try:
        rebalancer_instance, allocation_manager_instance = get_rebalancer(None)
        
        # Get current portfolio analysis using the rebalancer's portfolio analyzer
        # Use rebalanceable portfolio (excludes long-term) for compliance checking
        rebalancer_instance, allocation_manager_instance = get_rebalancer(None)
        portfolio_snapshot = rebalancer_instance.portfolio_analyzer.analyze_current_portfolio()
        
        # Check compliance
        current_allocations = {
            'asset_allocation': portfolio_snapshot.asset_allocation,
            'duration_allocation': portfolio_snapshot.duration_allocation,
            'strategy_allocation': portfolio_snapshot.strategy_allocation
        }
        
        compliance_checks = allocation_manager_instance.check_compliance(
            current_allocations, portfolio_snapshot.total_market_value
        )
        
        # Convert to JSON-serializable format
        compliance_data = []
        for check in compliance_checks:
            check_data = {
                'rule_type': check.rule.rule_type.value,
                'category': check.rule.category,
                'target_pct': check.target_pct,
                'current_pct': check.current_pct,
                'deviation_pct': check.deviation_pct,
                'status': check.status.value,
                'message': check.message,
                'min_pct': check.rule.min_pct,
                'max_pct': check.rule.max_pct,
                'tolerance_pct': check.rule.tolerance_pct
            }
            compliance_data.append(check_data)
        
        # Calculate summary statistics
        violations = [c for c in compliance_checks if c.status.value == 'violation']
        warnings = [c for c in compliance_checks if c.status.value == 'warning']
        compliant = [c for c in compliance_checks if c.status.value == 'compliant']
        
        return jsonify({
            'success': True,
            'compliance_checks': compliance_data,
            'summary': {
                'total_checks': len(compliance_checks),
                'violations': len(violations),
                'warnings': len(warnings),
                'compliant': len(compliant),
                'overall_status': 'violation' if violations else ('warning' if warnings else 'compliant')
            },
            'portfolio_value': portfolio_snapshot.total_market_value,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logging.error(f"❌ Error checking compliance: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/portfolio-analysis')
def get_portfolio_analysis():
    """Get detailed portfolio analysis"""
    try:
        # Get account filter from query parameters
        requested_accounts = request.args.getlist('accounts')
        
        logging.info(f"🔍 Portfolio analysis requested for accounts: {requested_accounts}")
        
        # Try to get rebalancer instance
        try:
            rebalancer_instance, _ = get_rebalancer(None)
            if rebalancer_instance is None:
                raise RuntimeError("Rebalancer instance is None")
        except Exception as e:
            logging.error(f"❌ Failed to get rebalancer instance: {e}")
            return jsonify({'success': False, 'error': f'Rebalancer initialization failed: {str(e)}'}), 500
        
        # Try to create portfolio analyzer
        try:
            portfolio_analyzer = PortfolioAnalyzer(rebalancer_instance.tracker)
        except Exception as e:
            logging.error(f"❌ Failed to create portfolio analyzer: {e}")
            return jsonify({'success': False, 'error': f'Portfolio analyzer creation failed: {str(e)}'}), 500
        
        # Try to analyze portfolio
        try:
            portfolio_snapshot = portfolio_analyzer.analyze_current_portfolio(
                account_numbers=requested_accounts if requested_accounts else None
            )
        except Exception as e:
            logging.error(f"❌ Failed to analyze portfolio: {e}")
            return jsonify({'success': False, 'error': f'Portfolio analysis failed: {str(e)}'}), 500
        
        # Try to get portfolio summary
        try:
            summary = portfolio_analyzer.get_portfolio_summary(portfolio_snapshot)
        except Exception as e:
            logging.error(f"❌ Failed to get portfolio summary: {e}")
            return jsonify({'success': False, 'error': f'Portfolio summary failed: {str(e)}'}), 500
        
        logging.info(f"✅ Portfolio analysis completed successfully")
        return jsonify({
            'success': True,
            'portfolio_summary': summary,
            'asset_allocation': portfolio_snapshot.asset_allocation,
            'duration_allocation': portfolio_snapshot.duration_allocation,
            'strategy_allocation': portfolio_snapshot.strategy_allocation,
            'sector_allocation': portfolio_snapshot.sector_allocation,
            'total_positions': len(portfolio_snapshot.positions),
            'timestamp': portfolio_snapshot.timestamp.isoformat()
        })
        
    except Exception as e:
        logging.error(f"❌ Unexpected error in portfolio analysis: {e}")
        import traceback
        logging.error(f"❌ Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Unexpected error: {str(e)}'}), 500

@rebalancing_bp.route('/api/rebalancing/configuration')
def get_rebalancing_configuration():
    """Get rebalancing configuration settings"""
    try:
        rebalancer_instance, _ = get_rebalancer(None)
        
        config = {
            'max_single_trade_dollars': rebalancer_instance.max_single_trade_dollars,
            'max_total_allocation_pct': rebalancer_instance.max_total_allocation_pct,
            'min_confidence_threshold': rebalancer_instance.min_confidence_threshold,
            'max_positions_per_gap': rebalancer_instance.max_positions_per_gap,
            'min_position_size_dollars': rebalancer_instance.min_position_size_dollars,
            'fill_check_interval': rebalancer_instance.fill_check_interval
        }
        
        return jsonify({
            'success': True,
            'configuration': config
        })
        
    except Exception as e:
        logging.error(f"❌ Error getting configuration: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/rebalancing/configuration', methods=['PUT'])
def update_rebalancing_configuration():
    """Update rebalancing configuration settings"""
    try:
        rebalancer_instance, _ = get_rebalancer(None)
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No configuration data provided'}), 400
        
        # Update configuration values
        if 'max_single_trade_dollars' in data:
            rebalancer_instance.max_single_trade_dollars = float(data['max_single_trade_dollars'])
        
        if 'max_total_allocation_pct' in data:
            rebalancer_instance.max_total_allocation_pct = float(data['max_total_allocation_pct'])
        
        if 'min_confidence_threshold' in data:
            rebalancer_instance.min_confidence_threshold = float(data['min_confidence_threshold'])
        
        if 'max_positions_per_gap' in data:
            rebalancer_instance.max_positions_per_gap = int(data['max_positions_per_gap'])
        
        if 'min_position_size_dollars' in data:
            rebalancer_instance.min_position_size_dollars = float(data['min_position_size_dollars'])
        
        if 'fill_check_interval' in data:
            rebalancer_instance.fill_check_interval = int(data['fill_check_interval'])
        
        return jsonify({
            'success': True,
            'message': 'Configuration updated successfully'
        })
        
    except Exception as e:
        logging.error(f"❌ Error updating configuration: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/rebalancing/debug-diagnostics')
def debug_diagnostics():
    """Simple diagnostics for debugging"""
    try:
        logging.info("🔍 Debug diagnostics requested")
        
        # Test basic functionality
        basic_info = {
            'endpoint_accessible': True,
            'timestamp': datetime.now().isoformat(),
            'routes_registered': True
        }
        
        # Try to get rebalancer instance
        try:
            rebalancer_instance, allocation_manager = get_rebalancer(None)
            basic_info['rebalancer_available'] = True
            basic_info['min_position_size'] = rebalancer_instance.min_position_size_dollars
        except Exception as e:
            basic_info['rebalancer_available'] = False
            basic_info['rebalancer_error'] = str(e)
            logging.error(f"❌ Rebalancer not available in diagnostics: {e}")
        
        logging.info(f"✅ Debug diagnostics completed")
        return jsonify({
            'success': True,
            'message': 'Debug diagnostics completed',
            'diagnostics': basic_info
        })
        
    except Exception as e:
        logging.error(f"❌ Error in debug diagnostics: {e}")
        import traceback
        logging.error(f"❌ Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500

@rebalancing_bp.route('/api/rebalancing/health')
def health_check():
    """Simple health check endpoint"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'message': 'Rebalancing routes are accessible'
    })



def create_rebalancing_routes(app, tracker):
    """Register rebalancing routes with the Flask app"""
    
    # Initialize rebalancer with tracker instance
    global rebalancer, allocation_manager
    if rebalancer is None:
        rebalancer = AutomatedRebalancer(tracker)
        allocation_manager = AllocationRulesManager()
        rebalancer.start_fill_monitoring()
        logging.info("✅ Automated rebalancer initialized with tracker")
    
    # Patch the get_rebalancer function to use the actual tracker
    def get_rebalancer_with_tracker(tracker_instance=None):
        return rebalancer, allocation_manager
    
    # Replace the global function
    globals()['get_rebalancer'] = get_rebalancer_with_tracker
    
    app.register_blueprint(rebalancing_bp)
    logging.info("✅ Rebalancing routes registered")