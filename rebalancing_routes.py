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

@rebalancing_bp.route('/api/rebalancing/trigger', methods=['POST'])
def trigger_rebalancing():
    """Manually trigger portfolio rebalancing"""
    try:
        rebalancer_instance, _ = get_rebalancer(None)
        
        data = request.get_json() or {}
        trigger_reason = data.get('reason', 'manual_trigger')
        
        event_id = rebalancer_instance.trigger_rebalancing(
            trigger_event='manual',
            trigger_details={'reason': trigger_reason, 'user_triggered': True}
        )
        
        return jsonify({
            'success': True,
            'event_id': event_id,
            'message': 'Rebalancing analysis triggered successfully'
        })
        
    except Exception as e:
        logging.error(f"❌ Error triggering rebalancing: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
        
        # Get current portfolio analysis using the tracker
        rebalancer_instance, allocation_manager_instance = get_rebalancer(None)
        portfolio_analyzer = PortfolioAnalyzer(rebalancer_instance.tracker)
        portfolio_snapshot = portfolio_analyzer.analyze_current_portfolio()
        
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
        
        rebalancer_instance, _ = get_rebalancer(None)
        portfolio_analyzer = PortfolioAnalyzer(rebalancer_instance.tracker)
        portfolio_snapshot = portfolio_analyzer.analyze_current_portfolio(
            account_numbers=requested_accounts if requested_accounts else None
        )
        
        # Get portfolio summary
        summary = portfolio_analyzer.get_portfolio_summary(portfolio_snapshot)
        
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
        logging.error(f"❌ Error getting portfolio analysis: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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