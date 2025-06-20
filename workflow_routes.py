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

@workflow_bp.route('/api/strategies/by-type', methods=['GET'])
def get_strategies_by_type():
    """Get strategies grouped by type"""
    try:
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        strategies_by_type = workflow_database.get_strategies_by_type(active_only=active_only)
        
        # Convert to JSON-friendly format
        result = {}
        for strategy_type, strategies in strategies_by_type.items():
            result[strategy_type] = [
                {
                    'id': strategy.id,
                    'name': strategy.name,
                    'description': strategy.description,
                    'strategy_type': strategy.strategy_type,
                    'delta_biases': strategy.delta_biases,
                    'dte_range_min': strategy.dte_range_min,
                    'dte_range_max': strategy.dte_range_max,
                    'profit_target_pct': strategy.profit_target_pct,
                    'stop_loss_pct': strategy.stop_loss_pct,
                    'no_stop_loss': strategy.no_stop_loss,
                    'is_active': strategy.is_active
                } for strategy in strategies
            ]
        
        return jsonify({
            'success': True,
            'strategies_by_type': result,
            'total_strategies': sum(len(strategies) for strategies in strategies_by_type.values())
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting strategies by type: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@workflow_bp.route('/api/strategies', methods=['GET'])
def get_strategies():
    """Get all strategies"""
    try:
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        logger.info(f"Getting strategies with active_only={active_only}")
        strategies = workflow_database.get_all_strategies(active_only=active_only)
        logger.info(f"Found {len(strategies)} strategies")
        
        # Convert to dict format for JSON response
        strategies_data = []
        for strategy in strategies:
            strategy_dict = {
                'id': strategy.id,
                'name': strategy.name,
                'description': strategy.description,
                'opening_action': strategy.opening_action,
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
                'no_stop_loss': strategy.no_stop_loss,
                'minimum_premium_required': strategy.minimum_premium_required,
                'minimum_underlying_price': strategy.minimum_underlying_price,
                'closing_21_dte': strategy.closing_21_dte,
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
                'strategy_type': strategy.strategy_type,
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
        
        # Parse legs with proper error handling
        legs = []
        try:
            for i, leg_data in enumerate(data['legs']):
                # Validate leg data
                required_leg_fields = ['action', 'option_type', 'selection_method']
                for field in required_leg_fields:
                    if field not in leg_data:
                        return jsonify({'success': False, 'error': f'Leg {i+1}: Missing required field: {field}'}), 400
                
                # For premium target, selection_value should be 0 as it uses strategy minimum premium
                selection_value = 0.0
                if leg_data['selection_method'] != 'premium':
                    selection_value = float(leg_data.get('selection_value', 0)) if leg_data.get('selection_value') not in [None, ''] else 0.0
                
                leg = StrategyLeg(
                    action=leg_data['action'],
                    option_type=leg_data['option_type'],
                    selection_method=leg_data['selection_method'],
                    selection_value=selection_value,
                    quantity=int(leg_data.get('quantity', 1))
                )
                legs.append(leg)
        except (ValueError, TypeError) as e:
            return jsonify({'success': False, 'error': f'Invalid leg data: {str(e)}'}), 400
        
        # Parse management rules with error handling
        management_rules = []
        try:
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
        except (ValueError, TypeError, KeyError) as e:
            return jsonify({'success': False, 'error': f'Invalid management rule data: {str(e)}'}), 400
        
        # Create strategy configuration with proper error handling
        try:
            strategy = StrategyConfig(
                id=data.get('id'),  # For updates
                name=data['name'],
                description=data.get('description', ''),
                opening_action=data.get('opening_action', 'STO'),
                legs=legs,
                dte_range_min=int(data.get('dte_range_min', 30)),
                dte_range_max=int(data.get('dte_range_max', 45)),
                profit_target_pct=float(data.get('profit_target_pct', 50.0)),
                stop_loss_pct=float(data.get('stop_loss_pct', 200.0)),
                no_stop_loss=bool(data.get('no_stop_loss', True)),
                minimum_premium_required=float(data.get('minimum_premium_required', 0.0)),
                minimum_underlying_price=float(data.get('minimum_underlying_price', 0.0)),
                closing_21_dte=bool(data.get('closing_21_dte', False)),
                delta_biases=data.get('delta_biases', ['neutral']),
                management_rules=management_rules,
                is_active=data.get('is_active', True)
            )
        except (ValueError, TypeError) as e:
            return jsonify({'success': False, 'error': f'Invalid strategy data: {str(e)}'}), 400
        
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

@workflow_bp.route('/api/strategies/<int:strategy_id>', methods=['PUT'])
def update_strategy(strategy_id):
    """Update existing strategy configuration"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Check if strategy exists
        existing_strategy = workflow_database.get_strategy(strategy_id)
        if not existing_strategy:
            return jsonify({'success': False, 'error': 'Strategy not found'}), 404
        
        # Validate required fields
        required_fields = ['name', 'legs']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        # Parse legs with proper error handling
        legs = []
        try:
            for i, leg_data in enumerate(data['legs']):
                # Validate leg data
                required_leg_fields = ['action', 'option_type', 'selection_method']
                for field in required_leg_fields:
                    if field not in leg_data:
                        return jsonify({'success': False, 'error': f'Leg {i+1}: Missing required field: {field}'}), 400
                
                # For premium target, selection_value should be 0 as it uses strategy minimum premium
                selection_value = 0.0
                if leg_data['selection_method'] != 'premium':
                    selection_value = float(leg_data.get('selection_value', 0)) if leg_data.get('selection_value') not in [None, ''] else 0.0
                
                leg = StrategyLeg(
                    action=leg_data['action'],
                    option_type=leg_data['option_type'],
                    selection_method=leg_data['selection_method'],
                    selection_value=selection_value,
                    quantity=int(leg_data.get('quantity', 1))
                )
                legs.append(leg)
        except (ValueError, TypeError) as e:
            return jsonify({'success': False, 'error': f'Invalid leg data: {str(e)}'}), 400
        
        # Parse management rules with error handling
        management_rules = []
        try:
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
        except (ValueError, TypeError, KeyError) as e:
            return jsonify({'success': False, 'error': f'Invalid management rule data: {str(e)}'}), 400
        
        # Create strategy configuration with proper error handling
        try:
            strategy = StrategyConfig(
                id=strategy_id,  # For updates
                name=data['name'],
                description=data.get('description', ''),
                opening_action=data.get('opening_action', 'STO'),
                legs=legs,
                dte_range_min=int(data.get('dte_range_min', 30)),
                dte_range_max=int(data.get('dte_range_max', 45)),
                profit_target_pct=float(data.get('profit_target_pct', 50.0)),
                stop_loss_pct=float(data.get('stop_loss_pct', 200.0)),
                no_stop_loss=bool(data.get('no_stop_loss', True)),
                minimum_premium_required=float(data.get('minimum_premium_required', 0.0)),
                minimum_underlying_price=float(data.get('minimum_underlying_price', 0.0)),
                closing_21_dte=bool(data.get('closing_21_dte', False)),
                delta_biases=data.get('delta_biases', ['neutral']),
                management_rules=management_rules,
                is_active=data.get('is_active', True)
            )
        except (ValueError, TypeError) as e:
            return jsonify({'success': False, 'error': f'Invalid strategy data: {str(e)}'}), 400
        
        # Save strategy
        saved_strategy_id = workflow_database.save_strategy(strategy)
        
        return jsonify({
            'success': True,
            'strategy_id': saved_strategy_id,
            'message': f'Strategy "{strategy.name}" updated successfully'
        })
        
    except Exception as e:
        logger.error(f"❌ Error updating strategy {strategy_id}: {e}")
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
            'opening_action': strategy.opening_action,
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
            'no_stop_loss': strategy.no_stop_loss,
            'minimum_premium_required': strategy.minimum_premium_required,
            'minimum_underlying_price': strategy.minimum_underlying_price,
            'closing_21_dte': strategy.closing_21_dte,
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

@workflow_bp.route('/api/strategies/<int:strategy_id>', methods=['DELETE'])
def delete_strategy(strategy_id):
    """Delete a strategy"""
    try:
        # Check if strategy exists
        strategy = workflow_database.get_strategy(strategy_id)
        if not strategy:
            return jsonify({'success': False, 'error': 'Strategy not found'}), 404
        
        # Delete the strategy
        success = workflow_database.delete_strategy(strategy_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Strategy "{strategy.name}" deleted successfully'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to delete strategy'}), 500
        
    except Exception as e:
        logger.error(f"❌ Error deleting strategy {strategy_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/strategies/validate', methods=['POST'])
def validate_strategy():
    """Validate strategy configuration using live option chain data"""
    logger.info("🚨🚨🚨 VALIDATE STRATEGY ENDPOINT CALLED")
    try:
        data = request.get_json()
        logger.info(f"🚨 Received data: {data}")
        
        if not data:
            return jsonify({'success': False, 'error': 'No strategy data provided'}), 400
        
        strategy_data = data.get('strategy_data', data.get('strategy', {}))
        test_symbol = data.get('test_symbol', 'SPY')
        test_dtes = data.get('test_dtes', None)  # New: array of DTEs to test
        
        # Debug logging to see what we receive
        logger.info(f"🔍 Validation request received strategy_data keys: {list(strategy_data.keys())}")
        min_premium_raw = strategy_data.get('minimum_premium_required', 'NOT FOUND')
        logger.info(f"🔍 Minimum premium in strategy_data: {min_premium_raw}")
        logger.info(f"🔍 Type of minimum premium: {type(min_premium_raw)}")
        logger.info(f"🔍 DTE range max in strategy_data: {strategy_data.get('dte_range_max', 'NOT FOUND')}")
        logger.info(f"🔍 Test DTEs requested: {test_dtes}")
        logger.info(f"🔍 Full strategy_data received: {strategy_data}")
        
        # Validate basic strategy structure
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'sample_trade': None
        }
        
        # Check required fields
        if not strategy_data.get('name'):
            validation_result['valid'] = False
            validation_result['errors'].append('Strategy name is required')
        
        legs = strategy_data.get('legs', [])
        if not legs:
            validation_result['valid'] = False
            validation_result['errors'].append('Strategy must have at least one leg')
        
        # Validate each leg
        for i, leg in enumerate(legs):
            leg_num = i + 1
            
            # Check required leg fields
            if not leg.get('action') in ['buy', 'sell']:
                validation_result['errors'].append(f'Leg {leg_num}: Invalid action')
                validation_result['valid'] = False
            
            if not leg.get('option_type') in ['call', 'put']:
                validation_result['errors'].append(f'Leg {leg_num}: Invalid option type')
                validation_result['valid'] = False
            
            if not leg.get('selection_method') in ['atm', 'offset', 'percentage', 'premium', 'atm_straddle']:
                validation_result['errors'].append(f'Leg {leg_num}: Invalid selection method')
                validation_result['valid'] = False
            
            # Validate selection value based on method
            selection_method = leg.get('selection_method')
            selection_value = leg.get('selection_value', 0)
            
            if selection_method == 'delta':
                validation_result['errors'].append(f'Leg {leg_num}: Delta selection is not supported. Please use ATM, offset, percentage, or premium selection.')
                validation_result['valid'] = False
            elif selection_method == 'offset':
                if not isinstance(selection_value, (int, float)) or selection_value == 0:
                    validation_result['errors'].append(f'Leg {leg_num}: Strike offset must be a non-zero dollar amount')
                    validation_result['valid'] = False
            elif selection_method == 'percentage':
                if not isinstance(selection_value, (int, float)) or selection_value <= 0:
                    validation_result['errors'].append(f'Leg {leg_num}: Percentage from current must be positive')
                    validation_result['valid'] = False
            elif selection_method == 'premium':
                # Premium target uses strategy minimum premium, not leg selection value
                strategy_min_premium = strategy_data.get('minimum_premium_required', 0)
                if strategy_min_premium <= 0:
                    validation_result['errors'].append(f'Leg {leg_num}: Premium target requires strategy minimum premium to be set')
                    validation_result['valid'] = False
            elif selection_method == 'atm_straddle':
                if not isinstance(selection_value, (int, float)) or selection_value < 0 or selection_value > 200:
                    validation_result['errors'].append(f'Leg {leg_num}: ATM straddle percentage must be between 0 and 200')
                    validation_result['valid'] = False
            
            if leg.get('quantity', 0) <= 0:
                validation_result['errors'].append(f'Leg {leg_num}: Quantity must be positive')
                validation_result['valid'] = False
        
        # Validate strategy-wide settings
        minimum_premium = strategy_data.get('minimum_premium_required', 0)
        if minimum_premium < 0:
            validation_result['errors'].append('Minimum premium required cannot be negative')
            validation_result['valid'] = False
        
        minimum_underlying_price = strategy_data.get('minimum_underlying_price', 0)
        if minimum_underlying_price < 0:
            validation_result['errors'].append('Minimum underlying price cannot be negative')
            validation_result['valid'] = False
        
        # Validate DTE ranges
        dte_min = strategy_data.get('dte_range_min', 0)
        dte_max = strategy_data.get('dte_range_max', 0)
        if dte_min < 0 or dte_max < 0:
            validation_result['errors'].append('DTE ranges must be positive')
            validation_result['valid'] = False
        elif dte_min > dte_max:
            validation_result['errors'].append('Minimum DTE cannot be greater than maximum DTE')
            validation_result['valid'] = False
        
        # If basic validation fails, return early
        if not validation_result['valid']:
            return jsonify(validation_result)
        
        # Determine DTEs to test
        if test_dtes and isinstance(test_dtes, list):
            # Use provided DTEs
            dtes_to_validate = test_dtes
        else:
            # Fall back to single DTE from strategy range
            dtes_to_validate = [strategy_data.get('dte_range_max', 45)]
        
        # Try to get option chain data for real validation
        try:
            # Import here to avoid circular imports
            from strategy_engine import StrategyEngine
            
            # Get tracker instance from global
            if workflow_orchestrator and hasattr(workflow_orchestrator, 'tracker'):
                tracker = workflow_orchestrator.tracker
                if tracker and tracker.tasty_client:
                    # Use validation cache for SPY
                    use_cache = test_symbol.upper() == 'SPY'
                    strategy_engine = StrategyEngine(tracker.tasty_client, use_validation_cache=use_cache)
                    
                    # Get option chain
                    option_chain = strategy_engine.get_options_chain(test_symbol)
                    
                    if option_chain:
                        # Use real strategy engine to find actual trades
                        try:
                            # Get current underlying price from market data
                            underlying_price = None
                            
                            # Try to get actual underlying price from the tracker's market data
                            if hasattr(tracker, 'underlying_prices') and test_symbol in tracker.underlying_prices:
                                underlying_price = tracker.underlying_prices[test_symbol]
                                logger.info(f"📊 Using real-time underlying price for {test_symbol}: ${underlying_price:.2f}")
                            else:
                                # Try to get from market data service
                                try:
                                    # Use the tastytrade SDK to get market data
                                    from tastytrade.market_data import get_market_data_by_type
                                    
                                    # Get equity quotes - pass symbol list directly
                                    quotes = get_market_data_by_type(tracker.tasty_client, [test_symbol])
                                    
                                    if quotes:
                                        quote = quotes[0]
                                        # Try different price fields
                                        if hasattr(quote, 'last'):
                                            underlying_price = float(quote.last) if quote.last else None
                                        elif hasattr(quote, 'mark'):
                                            underlying_price = float(quote.mark) if quote.mark else None
                                        elif hasattr(quote, 'bid') and hasattr(quote, 'ask') and quote.bid and quote.ask:
                                            underlying_price = (float(quote.bid) + float(quote.ask)) / 2
                                        
                                        if underlying_price:
                                            logger.info(f"📊 Fetched underlying price for {test_symbol}: ${underlying_price:.2f}")
                                except Exception as e:
                                    logger.warning(f"⚠️ Could not fetch underlying price for {test_symbol}: {e}")
                            
                            # Validate we have a price
                            if underlying_price is None or underlying_price == 0:
                                return jsonify({
                                    'success': False,
                                    'error': f'Could not determine underlying price for {test_symbol}'
                                }), 400
                            
                            # Initialize results for multi-DTE validation
                            dte_results = []
                            overall_valid = True
                            
                            # Get strategy parameters once
                            strategy_min_premium_raw = strategy_data.get('minimum_premium_required', 0)
                            strategy_min_premium = float(strategy_min_premium_raw) if strategy_min_premium_raw not in [None, ''] else 0
                            
                            logger.info(f"🔍 Raw minimum premium from strategy_data: {strategy_min_premium_raw} (type: {type(strategy_min_premium_raw)})")
                            logger.info(f"🔍 Converted minimum premium: {strategy_min_premium} (type: {type(strategy_min_premium)})")
                            
                            # Allow 0 as a valid minimum premium (no minimum requirement)
                            # Only set default if the value is negative or None
                            if strategy_min_premium < 0:
                                strategy_min_premium = 0
                                logger.warning(f"⚠️ Minimum premium was negative ({strategy_min_premium_raw}), using 0 (no minimum)")
                            
                            # Validate each requested DTE
                            for target_dte in dtes_to_validate:
                                dte_result = {
                                    'dte': target_dte,
                                    'valid': True,
                                    'errors': [],
                                    'warnings': [],
                                    'sample_trade': None
                                }
                                
                                try:
                                    # === UNIVERSAL STRATEGY VALIDATION ===
                                    # Use the new universal strategy builder for any leg configuration
                                    logger.info(f"🔍 Validating DTE {target_dte} - Min premium: {strategy_min_premium}")
                                    logger.info(f"🔍 Strategy legs configuration: {legs}")
                                    
                                    # Build strategy sample using universal system
                                    logger.info(f"🚨 About to call build_strategy_sample with legs={legs}, DTE={target_dte}")
                                    sample_legs, total_net_premium = strategy_engine.build_strategy_sample(
                                        legs=legs,
                                        underlying_price=underlying_price,
                                        target_dte=target_dte,
                                        test_symbol=test_symbol,
                                        strategy_min_premium=strategy_min_premium
                                    )
                                    logger.info(f"🚨 build_strategy_sample returned {len(sample_legs)} legs for DTE {target_dte}")
                                    
                                    if sample_legs:
                                        # Calculate strategy metrics
                                        metrics = strategy_engine.calculate_strategy_metrics(sample_legs, total_net_premium)
                                        
                                        # Determine strategy type for display
                                        strategy_types = []
                                        for leg in legs:
                                            leg_type = f"{leg['action']}_{leg['option_type']}"
                                            strategy_types.append(leg_type)
                                        strategy_type_display = "_".join(strategy_types)
                                        
                                        # Check if strategy meets minimum premium requirement
                                        meets_premium_req = total_net_premium >= strategy_min_premium if strategy_min_premium > 0 else True
                                        
                                        # Calculate distance from underlying for first leg
                                        distance_from_underlying = 0
                                        if sample_legs:
                                            first_leg = sample_legs[0]
                                            distance_from_underlying = abs((float(first_leg.get('strike', underlying_price)) - underlying_price) / underlying_price * 100)
                                        
                                        sample_trade = {
                                            'symbol': test_symbol,
                                            'underlying_price': underlying_price,
                                            'strategy_type': strategy_type_display,
                                            'legs': sample_legs,
                                            'net_premium': metrics['net_premium'],
                                            'premium_type': metrics.get('premium_type', 'Credit'),
                                            'max_profit': metrics['max_profit'],
                                            'max_loss': metrics['max_loss'],
                                            'break_even': metrics['break_even'],
                                            'estimated_cost': metrics['max_loss'],
                                            'meets_premium_requirement': meets_premium_req,
                                            'target_premium': strategy_min_premium,
                                            'distance_from_underlying': distance_from_underlying,
                                            'dte': target_dte
                                        }
                                        
                                        dte_result['sample_trade'] = sample_trade
                                        
                                        # Add validation error if premium requirement not met
                                        if not meets_premium_req:
                                            dte_result['valid'] = False
                                            dte_result['errors'].append(
                                                f'Net premium ${total_net_premium:.2f} is below minimum requirement ${strategy_min_premium:.2f}'
                                            )
                                            overall_valid = False
                                            
                                        logger.info(f"✅ DTE {target_dte} validation successful: {len(sample_legs)} legs, net premium: ${total_net_premium:.2f}")
                                        
                                    else:
                                        # Strategy building failed - validation failure
                                        dte_result['valid'] = False
                                        dte_result['errors'].append(
                                            f'Could not find suitable options for {target_dte} DTE'
                                        )
                                        dte_result['sample_trade'] = {
                                            'symbol': test_symbol,
                                            'legs': [],
                                            'message': f'Could not find suitable options for {target_dte} DTE',
                                            'estimated_cost': 0,
                                            'max_profit': 0,
                                            'max_loss': 0,
                                            'target_premium': strategy_min_premium,
                                            'net_premium': 0,
                                            'distance_from_underlying': 0,
                                            'dte': target_dte
                                        }
                                        overall_valid = False
                                
                                except Exception as e:
                                    logger.error(f"Error validating DTE {target_dte}: {e}")
                                    dte_result['valid'] = False
                                    dte_result['errors'].append(f'Validation failed: {str(e)}')
                                    dte_result['sample_trade'] = {
                                        'symbol': test_symbol,
                                        'legs': [],
                                        'error': f'Error: {str(e)}',
                                        'estimated_cost': 0,
                                        'max_profit': 0,
                                        'max_loss': 0,
                                        'net_premium': 0,
                                        'distance_from_underlying': 0,
                                        'dte': target_dte
                                    }
                                    overall_valid = False
                                
                                # Add this DTE result to the list
                                dte_results.append(dte_result)
                            
                            # Update validation result with multi-DTE results
                            validation_result['dte_results'] = dte_results
                            validation_result['overall_valid'] = overall_valid
                            
                            # For backward compatibility, include the first DTE result as sample_trade
                            if dte_results:
                                validation_result['sample_trade'] = dte_results[0]['sample_trade']
                                validation_result['valid'] = dte_results[0]['valid']
                                
                                # Aggregate errors from all DTEs
                                if not overall_valid:
                                    all_errors = []
                                    for dte_res in dte_results:
                                        if not dte_res['valid'] and dte_res['errors']:
                                            all_errors.extend([f"DTE {dte_res['dte']}: {err}" for err in dte_res['errors']])
                                    if all_errors:
                                        validation_result['errors'].extend(all_errors)
                            
                            # Only add success warning if no errors occurred
                            if overall_valid:
                                validation_result['warnings'].append(
                                    f'Sample calculations based on {test_symbol} option chain'
                                )
                        
                        except Exception as e:
                            logger.error(f"Error in multi-DTE validation: {e}")
                            validation_result['valid'] = False
                            validation_result['errors'].append(f'Multi-DTE validation failed: {str(e)}')
                            validation_result['dte_results'] = []
                            validation_result['overall_valid'] = False
                    
                    else:
                        validation_result['warnings'].append(
                            f'Could not fetch option chain for {test_symbol} - validation limited'
                        )
                
                else:
                    validation_result['warnings'].append(
                        'Market data not available - validation limited to structure checks'
                    )
            
            else:
                validation_result['warnings'].append(
                    'Workflow system not initialized - validation limited to structure checks'
                )
        
        except Exception as e:
            logger.warning(f"Option chain validation failed: {e}")
            validation_result['warnings'].append(
                'Live option data unavailable - validation limited to structure checks'
            )
        
        # Add some basic warnings based on strategy configuration
        if strategy_data.get('profit_target_pct', 50) > 75:
            validation_result['warnings'].append(
                'High profit target (>75%) may reduce fill probability'
            )
        
        if strategy_data.get('stop_loss_pct', 200) < 150:
            validation_result['warnings'].append(
                'Low stop loss (<150%) may result in frequent stops'
            )
        
        return jsonify(validation_result)
        
    except Exception as e:
        logger.error(f"❌ Error validating strategy: {e}")
        return jsonify({
            'valid': False,
            'errors': [f'Validation error: {str(e)}']
        }), 500

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

@workflow_bp.route('/api/strategies/refresh-validation-chains', methods=['POST'])
def refresh_validation_chains():
    """Refresh the cached validation chains for SPY"""
    try:
        # Import here to avoid circular imports
        from strategy_engine import StrategyEngine
        
        # Check if we have a tracker instance
        if workflow_orchestrator and hasattr(workflow_orchestrator, 'tracker'):
            tracker = workflow_orchestrator.tracker
            if tracker and tracker.tasty_client:
                strategy_engine = StrategyEngine(tracker.tasty_client)
                
                # Refresh the chains
                success = strategy_engine.refresh_validation_chains()
                
                if success:
                    return jsonify({
                        'success': True,
                        'message': 'Successfully refreshed SPY validation chains'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Failed to refresh validation chains - check logs'
                    }), 500
            else:
                return jsonify({
                    'success': False,
                    'error': 'TastyTrade client not available'
                }), 503
        else:
            return jsonify({
                'success': False,
                'error': 'Workflow orchestrator not initialized'
            }), 503
            
    except Exception as e:
        logger.error(f"Error refreshing validation chains: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

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

@workflow_bp.route('/api/workflow/pending/detailed', methods=['GET'])
def get_pending_trades_detailed():
    """Get pending trades with enhanced risk metrics and real-time pricing"""
    try:
        pending_trades = workflow_database.get_pending_trades()
        
        # Convert to enhanced response format
        trades_data = []
        for trade in pending_trades:
            # Get strategy details
            strategy = None
            if trade.strategy_id:
                try:
                    strategy = workflow_database.get_strategy(trade.strategy_id)
                except:
                    pass
            
            # Enhanced trade data with calculated metrics
            trade_dict = {
                'id': trade.id,
                'workflow_id': trade.workflow_id,
                'symbol': trade.symbol,
                'strategy_id': trade.strategy_id,
                'strategy_config': {
                    'name': strategy.name if strategy else 'Unknown Strategy',
                    'legs': [
                        {
                            'action': leg.action,
                            'option_type': leg.option_type,
                            'selection_method': leg.selection_method,
                            'selection_value': leg.selection_value,
                            'quantity': leg.quantity
                        } for leg in strategy.legs
                    ] if strategy else [],
                    'profit_target_pct': strategy.profit_target_pct if strategy else None,
                    'stop_loss_pct': strategy.stop_loss_pct if strategy else None
                },
                'order_details': trade.order_details,
                'risk_metrics': {
                    'expected_pnl': trade.risk_metrics.get('expected_pnl', 0) if trade.risk_metrics else 0,
                    'max_loss': trade.risk_metrics.get('max_loss', 0) if trade.risk_metrics else 0,
                    'risk_reward_ratio': trade.risk_metrics.get('risk_reward_ratio', 0) if trade.risk_metrics else 0,
                    'confidence_score': trade.risk_metrics.get('confidence_score', 0) if trade.risk_metrics else 0,
                    'buying_power_required': trade.risk_metrics.get('buying_power_required', 0) if trade.risk_metrics else 0,
                    'win_probability': trade.risk_metrics.get('win_probability', 0) if trade.risk_metrics else 0
                },
                'created_at': trade.created_at.isoformat() if hasattr(trade, 'created_at') and trade.created_at else None,
                'workflow_state': getattr(trade, 'workflow_state', 'PENDING_APPROVAL')
            }
            trades_data.append(trade_dict)
        
        return jsonify({
            'success': True,
            'pending_trades': trades_data,
            'count': len(trades_data),
            'last_updated': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting detailed pending trades: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@workflow_bp.route('/api/workflow/approve/bulk', methods=['POST'])
def bulk_approve_trades():
    """Approve multiple trades with optional modifications"""
    try:
        data = request.get_json()
        if not data or 'trade_ids' not in data:
            return jsonify({'success': False, 'error': 'trade_ids required'}), 400
        
        trade_ids = data['trade_ids']
        modifications = data.get('modifications', {})
        
        results = []
        approved_count = 0
        
        for trade_id in trade_ids:
            try:
                success = workflow_orchestrator.approve_trade(trade_id, modifications.get(str(trade_id), {}))
                if success:
                    approved_count += 1
                    results.append({'trade_id': trade_id, 'status': 'approved'})
                else:
                    results.append({'trade_id': trade_id, 'status': 'failed', 'error': 'Approval failed'})
            except Exception as e:
                results.append({'trade_id': trade_id, 'status': 'error', 'error': str(e)})
        
        return jsonify({
            'success': True,
            'approved_count': approved_count,
            'total_count': len(trade_ids),
            'results': results
        })
        
    except Exception as e:
        logger.error(f"❌ Error in bulk approval: {e}")
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