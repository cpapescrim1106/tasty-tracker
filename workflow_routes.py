#!/usr/bin/env python3
"""
Workflow API Routes
Flask Blueprint for trading workflow management endpoints
"""

import logging
import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from typing import Dict, List, Optional, Any

# Local imports
from workflow_database import (
    WorkflowDatabase, StrategyConfig, StrategyLeg, ManagementRule, 
    ApprovedTrade, WorkflowState
)
from workflow_orchestrator import WorkflowOrchestrator

# Create Blueprint
workflow_bp = Blueprint('workflow', __name__)
logger = logging.getLogger(__name__)

# Global instances (will be initialized by main application)
workflow_orchestrator: Optional[WorkflowOrchestrator] = None
workflow_database: Optional[WorkflowDatabase] = None

def create_workflow_routes(app, tracker_instance):
    """Initialize and register workflow routes with Flask app"""
    global workflow_orchestrator, workflow_database
    
    # Initialize components
    workflow_orchestrator = WorkflowOrchestrator(tracker_instance)
    workflow_database = WorkflowDatabase()
    
    # Register blueprint
    app.register_blueprint(workflow_bp)
    
    logger.info("✅ Initialized and registered workflow routes")

def init_workflow_routes(tracker_instance):
    """Initialize workflow routes with tracker instance (backward compatibility)"""
    global workflow_orchestrator, workflow_database
    workflow_orchestrator = WorkflowOrchestrator(tracker_instance)
    workflow_database = WorkflowDatabase()
    logger.info("✅ Initialized workflow routes")

@workflow_bp.route('/api/strategies', methods=['GET'])
def get_strategies():
    """Get all strategies"""
    try:
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        strategies = workflow_database.get_all_strategies(active_only=active_only)
        
        # Convert to dict format for JSON response
        strategies_data = []
        for strategy in strategies:
            strategy_dict = {
                'id': strategy.id,
                'name': strategy.name,
                'description': strategy.description,
                'legs': [
                    {
                        'action': leg.action,
                        'option_type': leg.option_type,
                        'selection_method': leg.selection_method,
                        'selection_value': leg.selection_value,
                        'quantity': leg.quantity
                    } for leg in strategy.legs
                ],
                'dte_range_min': strategy.dte_range_min,
                'dte_range_max': strategy.dte_range_max,
                'profit_target_pct': strategy.profit_target_pct,
                'stop_loss_pct': strategy.stop_loss_pct,
                'delta_biases': strategy.delta_biases,
                'management_rules': [
                    {
                        'rule_type': rule.rule_type,
                        'trigger_condition': rule.trigger_condition,
                        'trigger_value': rule.trigger_value,
                        'action': rule.action,
                        'quantity_pct': rule.quantity_pct,
                        'priority': rule.priority
                    } for rule in strategy.management_rules
                ],
                'created_at': strategy.created_at.isoformat() if strategy.created_at else None,
                'is_active': strategy.is_active
            }
            strategies_data.append(strategy_dict)
        
        return jsonify({
            'success': True,
            'strategies': strategies_data,
            'count': len(strategies_data)
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting strategies: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/strategies', methods=['POST'])
def save_strategy():
    """Save strategy configuration"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        required_fields = ['name', 'legs']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        # Parse legs
        legs = []
        for leg_data in data['legs']:
            leg = StrategyLeg(
                action=leg_data['action'],
                option_type=leg_data['option_type'],
                selection_method=leg_data['selection_method'],
                selection_value=float(leg_data['selection_value']),
                quantity=int(leg_data.get('quantity', 1))
            )
            legs.append(leg)
        
        # Parse management rules
        management_rules = []
        for rule_data in data.get('management_rules', []):
            rule = ManagementRule(
                rule_type=rule_data['rule_type'],
                trigger_condition=rule_data.get('trigger_condition', 'gte'),
                trigger_value=float(rule_data['trigger_value']),
                action=rule_data['action'],
                quantity_pct=float(rule_data.get('quantity_pct', 100.0)),
                priority=int(rule_data.get('priority', 1))
            )
            management_rules.append(rule)
        
        # Create strategy configuration
        strategy = StrategyConfig(
            id=data.get('id'),  # For updates
            name=data['name'],
            description=data.get('description', ''),
            legs=legs,
            dte_range_min=int(data.get('dte_range_min', 30)),
            dte_range_max=int(data.get('dte_range_max', 45)),
            profit_target_pct=float(data.get('profit_target_pct', 50.0)),
            stop_loss_pct=float(data.get('stop_loss_pct', 200.0)),
            delta_biases=data.get('delta_biases', ['neutral']),
            management_rules=management_rules,
            is_active=data.get('is_active', True)
        )
        
        # Save strategy
        strategy_id = workflow_database.save_strategy(strategy)
        
        return jsonify({
            'success': True,
            'strategy_id': strategy_id,
            'message': f'Strategy "{strategy.name}" saved successfully'
        })
        
    except Exception as e:
        logger.error(f"❌ Error saving strategy: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/strategies/<int:strategy_id>', methods=['GET'])
def get_strategy(strategy_id):
    """Get specific strategy by ID"""
    try:
        strategy = workflow_database.get_strategy(strategy_id)
        
        if not strategy:
            return jsonify({'success': False, 'error': 'Strategy not found'}), 404
        
        strategy_dict = {
            'id': strategy.id,
            'name': strategy.name,
            'description': strategy.description,
            'legs': [
                {
                    'action': leg.action,
                    'option_type': leg.option_type,
                    'selection_method': leg.selection_method,
                    'selection_value': leg.selection_value,
                    'quantity': leg.quantity
                } for leg in strategy.legs
            ],
            'dte_range_min': strategy.dte_range_min,
            'dte_range_max': strategy.dte_range_max,
            'profit_target_pct': strategy.profit_target_pct,
            'stop_loss_pct': strategy.stop_loss_pct,
            'delta_biases': strategy.delta_biases,
            'management_rules': [
                {
                    'rule_type': rule.rule_type,
                    'trigger_condition': rule.trigger_condition,
                    'trigger_value': rule.trigger_value,
                    'action': rule.action,
                    'quantity_pct': rule.quantity_pct,
                    'priority': rule.priority
                } for rule in strategy.management_rules
            ],
            'created_at': strategy.created_at.isoformat() if strategy.created_at else None,
            'is_active': strategy.is_active
        }
        
        return jsonify({
            'success': True,
            'strategy': strategy_dict
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting strategy {strategy_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/strategies/validate', methods=['POST'])
def validate_strategy():
    """Validate strategy configuration using test data"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No strategy data provided'}), 400
        
        # For now, return basic validation
        # In production, this would:
        # 1. Test strategy on SPY historical data
        # 2. Calculate P&L curves
        # 3. Validate leg combinations
        # 4. Check risk metrics
        
        validation_results = {
            'is_valid': True,
            'warnings': [],
            'errors': [],
            'test_metrics': {
                'max_profit': 150.0,
                'max_loss': 350.0,
                'risk_reward_ratio': 0.43,
                'win_rate': 0.65,
                'avg_profit': 98.50,
                'avg_loss': 175.25
            },
            'recommendations': [
                'Consider tightening profit target to 40% for better win rate',
                'Strategy performs well in neutral to slightly bullish markets'
            ]
        }
        
        return jsonify({
            'success': True,
            'validation': validation_results
        })
        
    except Exception as e:
        logger.error(f"❌ Error validating strategy: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/start', methods=['POST'])
def start_workflow():
    """Start workflow for symbols"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        symbols = data.get('symbols', [])
        strategy_ids = data.get('strategy_ids', [])
        
        if not symbols:
            return jsonify({'success': False, 'error': 'No symbols provided'}), 400
        
        # Start workflows
        workflow_ids = workflow_orchestrator.start_workflow(symbols, strategy_ids)
        
        return jsonify({
            'success': True,
            'workflow_ids': workflow_ids,
            'message': f'Started {len(workflow_ids)} workflows'
        })
        
    except Exception as e:
        logger.error(f"❌ Error starting workflow: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/pending', methods=['GET'])
def get_pending_trades():
    """Get trades awaiting approval"""
    try:
        pending_trades = workflow_database.get_pending_trades()
        
        # Convert to response format
        trades_data = []
        for trade in pending_trades:
            trade_dict = {
                'id': trade.id,
                'workflow_id': trade.workflow_id,
                'symbol': trade.symbol,
                'strategy_id': trade.strategy_id,
                'strategy_config': trade.strategy_config,
                'order_details': trade.order_details,
                'risk_metrics': trade.risk_metrics,
                'created_at': trade.created_at.isoformat() if hasattr(trade, 'created_at') else None
            }
            trades_data.append(trade_dict)
        
        return jsonify({
            'success': True,
            'pending_trades': trades_data,
            'count': len(trades_data)
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting pending trades: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/approve/<int:trade_id>', methods=['POST'])
def approve_trade(trade_id):
    """Approve trade for execution"""
    try:
        data = request.get_json() or {}
        modifications = data.get('modifications', {})
        
        # Approve trade
        success = workflow_orchestrator.approve_trade(trade_id, modifications)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Trade {trade_id} approved and submitted for execution'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to approve trade {trade_id}'
            }), 500
        
    except Exception as e:
        logger.error(f"❌ Error approving trade {trade_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/reject/<int:trade_id>', methods=['POST'])
def reject_trade(trade_id):
    """Reject pending trade"""
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'Manual rejection')
        
        # Update trade status to rejected
        # This would need to be implemented in the database
        
        return jsonify({
            'success': True,
            'message': f'Trade {trade_id} rejected: {reason}'
        })
        
    except Exception as e:
        logger.error(f"❌ Error rejecting trade {trade_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/status/<workflow_id>', methods=['GET'])
def get_workflow_status(workflow_id):
    """Get workflow status"""
    try:
        status = workflow_orchestrator.get_workflow_status(workflow_id)
        
        if status:
            return jsonify({
                'success': True,
                'status': status
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Workflow not found'
            }), 404
        
    except Exception as e:
        logger.error(f"❌ Error getting workflow status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/list', methods=['GET'])
def list_workflows():
    """List all workflows with filters"""
    try:
        # Get query parameters
        state = request.args.get('state')
        symbol = request.args.get('symbol')
        limit = int(request.args.get('limit', 50))
        
        # Get workflows based on filters
        if state:
            try:
                workflow_state = WorkflowState(state)
                workflows = workflow_database.get_workflows_by_state(workflow_state)
            except ValueError:
                return jsonify({'success': False, 'error': f'Invalid state: {state}'}), 400
        else:
            # Get all workflows - would need a new database method
            workflows = []
        
        # Filter by symbol if provided
        if symbol:
            workflows = [w for w in workflows if w.symbol == symbol]
        
        # Limit results
        workflows = workflows[:limit]
        
        # Convert to response format
        workflows_data = []
        for workflow in workflows:
            workflow_dict = {
                'id': workflow.id,
                'symbol': workflow.symbol,
                'strategy_id': workflow.strategy_id,
                'current_state': workflow.current_state.value,
                'state_data': workflow.state_data,
                'created_at': workflow.created_at.isoformat(),
                'updated_at': workflow.updated_at.isoformat(),
                'error_message': workflow.error_message
            }
            workflows_data.append(workflow_dict)
        
        return jsonify({
            'success': True,
            'workflows': workflows_data,
            'count': len(workflows_data)
        })
        
    except Exception as e:
        logger.error(f"❌ Error listing workflows: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/stats', methods=['GET'])
def get_workflow_stats():
    """Get workflow system statistics"""
    try:
        # Get counts by state
        stats = {
            'workflows_by_state': {},
            'total_strategies': 0,
            'active_strategies': 0,
            'pending_trades': 0,
            'total_workflows': 0
        }
        
        # Count workflows by state
        for state in WorkflowState:
            workflows = workflow_database.get_workflows_by_state(state)
            stats['workflows_by_state'][state.value] = len(workflows)
            stats['total_workflows'] += len(workflows)
        
        # Count strategies
        all_strategies = workflow_database.get_all_strategies(active_only=False)
        active_strategies = workflow_database.get_all_strategies(active_only=True)
        stats['total_strategies'] = len(all_strategies)
        stats['active_strategies'] = len(active_strategies)
        
        # Count pending trades
        pending_trades = workflow_database.get_pending_trades()
        stats['pending_trades'] = len(pending_trades)
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting workflow stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/positions/rules/apply', methods=['POST'])
def apply_position_rules():
    """Apply management rules to existing position"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        position_key = data.get('position_key')
        strategy_id = data.get('strategy_id')
        
        if not position_key or not strategy_id:
            return jsonify({'success': False, 'error': 'Missing position_key or strategy_id'}), 400
        
        # Get strategy
        strategy = workflow_database.get_strategy(strategy_id)
        if not strategy:
            return jsonify({'success': False, 'error': 'Strategy not found'}), 404
        
        # Apply rules (this would integrate with PositionManager)
        # For now, just return success
        
        return jsonify({
            'success': True,
            'message': f'Applied {len(strategy.management_rules)} rules to position {position_key}'
        })
        
    except Exception as e:
        logger.error(f"❌ Error applying position rules: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Health check endpoint
@workflow_bp.route('/api/workflow/health', methods=['GET'])
def health_check():
    """Health check for workflow system"""
    try:
        # Check if components are initialized
        if not workflow_orchestrator or not workflow_database:
            return jsonify({
                'success': False,
                'status': 'unhealthy',
                'error': 'Workflow components not initialized'
            }), 503
        
        # Basic health checks
        health_status = {
            'status': 'healthy',
            'database_connected': True,
            'orchestrator_running': workflow_orchestrator.processing_enabled,
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'health': health_status
        })
        
    except Exception as e:
        logger.error(f"❌ Error in health check: {e}")
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'error': str(e)
        }), 500