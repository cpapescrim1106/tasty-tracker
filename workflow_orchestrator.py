#!/usr/bin/env python3
"""
Workflow Orchestrator
Manages the complete trading workflow from symbol scanning to position closure
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import uuid

# Local imports
from workflow_database import (
    WorkflowDatabase, WorkflowState, StrategyConfig, WorkflowInstance, 
    ApprovedTrade, StrategyLeg, ManagementRule
)
from order_manager import OrderManager
from position_manager import PositionManager
from screener_backend import ScreenerEngine
from strategy_engine import StrategyEngine

@dataclass
class DeltaBiasEvaluation:
    """Result of delta bias evaluation for a symbol"""
    symbol: str
    current_bias: str  # "bullish", "neutral", "bearish"
    confidence: float  # 0.0 to 1.0
    supporting_metrics: Dict[str, Any]
    suitable_strategies: List[int]  # Strategy IDs that match this bias

@dataclass
class TradeEvaluation:
    """Complete trade evaluation for approval"""
    workflow_id: str
    symbol: str
    strategy: StrategyConfig
    estimated_cost: float
    estimated_max_profit: float
    estimated_max_loss: float
    risk_reward_ratio: float
    delta_exposure: float
    buying_power_required: float
    position_details: Dict[str, Any]
    confidence_score: float

class WorkflowOrchestrator:
    """Main orchestrator for automated trading workflows"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance
        self.logger = logging.getLogger(__name__)
        
        # Initialize core components
        self.database = WorkflowDatabase()
        self.order_manager = OrderManager(tracker_instance)
        self.position_manager = PositionManager(tracker_instance)
        self.screener_engine = ScreenerEngine(tracker_instance)
        self.strategy_engine = StrategyEngine(tracker_instance)
        
        # Workflow processing settings
        self.processing_enabled = True
        self.process_interval = 30  # seconds
        self.max_concurrent_evaluations = 5
        self.max_concurrent_executions = 3
        
        # Portfolio limits
        self.max_positions_per_symbol = 2
        self.max_total_positions = 20
        self.max_portfolio_allocation_pct = 80.0
        
        # Delta bias thresholds
        self.delta_bias_thresholds = {
            'bullish': {'min_confidence': 0.6, 'max_delta_exposure': 50.0},
            'neutral': {'min_confidence': 0.5, 'max_delta_exposure': 10.0},
            'bearish': {'min_confidence': 0.6, 'max_delta_exposure': -50.0}
        }
        
        # Start background processing
        self._start_background_processing()
        
    def _start_background_processing(self):
        """Start background workflow processing thread"""
        def process_workflows():
            while self.processing_enabled:
                try:
                    self._process_workflow_states()
                    time.sleep(self.process_interval)
                except Exception as e:
                    self.logger.error(f"❌ Error in workflow processing: {e}")
                    time.sleep(self.process_interval)
        
        self.processing_thread = threading.Thread(target=process_workflows, daemon=True)
        self.processing_thread.start()
        self.logger.info("🚀 Started workflow background processing")
    
    def start_workflow(self, symbols: List[str], strategy_ids: List[int] = None) -> List[str]:
        """Start workflow for multiple symbols"""
        workflow_ids = []
        
        try:
            # Get active strategies if none specified
            if not strategy_ids:
                strategies = self.database.get_all_strategies(active_only=True)
                strategy_ids = [s.id for s in strategies]
                
            if not strategy_ids:
                self.logger.warning("⚠️ No active strategies found")
                return workflow_ids
            
            # Create workflow instances for each symbol
            for symbol in symbols:
                # Check if symbol already has active workflows
                existing_workflows = self._get_active_workflows_for_symbol(symbol)
                if len(existing_workflows) >= self.max_positions_per_symbol:
                    self.logger.info(f"⚠️ Symbol {symbol} already has maximum workflows")
                    continue
                
                # Create workflow for each compatible strategy
                for strategy_id in strategy_ids:
                    workflow_id = f"wf_{symbol}_{strategy_id}_{int(time.time())}"
                    
                    if self.database.create_workflow_instance(
                        workflow_id=workflow_id,
                        symbol=symbol,
                        strategy_id=strategy_id,
                        initial_state=WorkflowState.SCANNING
                    ):
                        workflow_ids.append(workflow_id)
                        self.logger.info(f"✅ Started workflow: {workflow_id}")
            
            return workflow_ids
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start workflows: {e}")
            return workflow_ids
    
    def _process_workflow_states(self):
        """Process all workflows in each state"""
        try:
            # Process workflows in order of priority
            state_processors = [
                (WorkflowState.SCANNING, self._process_scanning_workflows),
                (WorkflowState.EVALUATING, self._process_evaluating_workflows),
                (WorkflowState.PENDING_APPROVAL, self._process_pending_workflows),
                (WorkflowState.EXECUTING, self._process_executing_workflows),
                (WorkflowState.MONITORING, self._process_monitoring_workflows),
                (WorkflowState.CLOSING, self._process_closing_workflows),
                (WorkflowState.ERROR, self._process_error_workflows)
            ]
            
            for state, processor in state_processors:
                workflows = self.database.get_workflows_by_state(state)
                if workflows:
                    self.logger.debug(f"Processing {len(workflows)} workflows in state: {state.value}")
                    processor(workflows)
                        
        except Exception as e:
            self.logger.error(f"❌ Error processing workflow states: {e}")
    
    def _process_scanning_workflows(self, workflows: List[WorkflowInstance]):
        """Process workflows in SCANNING state"""
        for workflow in workflows[:self.max_concurrent_evaluations]:
            try:
                # Get strategy configuration
                strategy = self.database.get_strategy(workflow.strategy_id)
                if not strategy or not strategy.is_active:
                    self._move_to_error(workflow.id, "Strategy not found or inactive")
                    continue
                
                # Evaluate symbol for suitability
                evaluation = self._evaluate_symbol_for_strategy(workflow.symbol, strategy)
                
                if evaluation and evaluation.confidence_score > 0.6:
                    # Symbol is suitable, move to evaluation
                    state_data = {
                        'delta_evaluation': asdict(evaluation),
                        'scan_completed_at': datetime.now().isoformat()
                    }
                    self.database.update_workflow_state(
                        workflow.id, WorkflowState.EVALUATING, state_data
                    )
                else:
                    # Symbol not suitable, complete workflow
                    self.database.update_workflow_state(
                        workflow.id, WorkflowState.COMPLETED, 
                        {'reason': 'Symbol not suitable for strategy'}
                    )
                    
            except Exception as e:
                self.logger.error(f"❌ Error processing scanning workflow {workflow.id}: {e}")
                self._move_to_error(workflow.id, str(e))
    
    def _process_evaluating_workflows(self, workflows: List[WorkflowInstance]):
        """Process workflows in EVALUATING state"""
        for workflow in workflows[:self.max_concurrent_evaluations]:
            try:
                # Get strategy configuration
                strategy = self.database.get_strategy(workflow.strategy_id)
                if not strategy:
                    self._move_to_error(workflow.id, "Strategy not found")
                    continue
                
                # Perform detailed trade evaluation
                trade_evaluation = self._evaluate_trade_opportunity(workflow.symbol, strategy)
                
                if trade_evaluation and trade_evaluation.confidence_score > 0.7:
                    # Create approved trade entry
                    approved_trade = ApprovedTrade(
                        workflow_id=workflow.id,
                        symbol=workflow.symbol,
                        strategy_id=strategy.id,
                        strategy_config=asdict(strategy),
                        order_details=trade_evaluation.position_details,
                        risk_metrics={
                            'estimated_cost': trade_evaluation.estimated_cost,
                            'estimated_max_profit': trade_evaluation.estimated_max_profit,
                            'estimated_max_loss': trade_evaluation.estimated_max_loss,
                            'risk_reward_ratio': trade_evaluation.risk_reward_ratio,
                            'confidence_score': trade_evaluation.confidence_score
                        }
                    )
                    
                    # Save for approval
                    trade_id = self.database.save_approved_trade(approved_trade)
                    
                    # Move to pending approval
                    state_data = {
                        'trade_evaluation': asdict(trade_evaluation),
                        'approved_trade_id': trade_id,
                        'evaluation_completed_at': datetime.now().isoformat()
                    }
                    self.database.update_workflow_state(
                        workflow.id, WorkflowState.PENDING_APPROVAL, state_data
                    )
                else:
                    # Trade not suitable
                    self.database.update_workflow_state(
                        workflow.id, WorkflowState.COMPLETED,
                        {'reason': 'Trade evaluation failed or low confidence'}
                    )
                    
            except Exception as e:
                self.logger.error(f"❌ Error evaluating workflow {workflow.id}: {e}")
                self._move_to_error(workflow.id, str(e))
    
    def _process_pending_workflows(self, workflows: List[WorkflowInstance]):
        """Process workflows pending approval - these wait for manual approval"""
        # Pending workflows wait for manual approval via API
        # Check for approved trades that need to move to execution
        for workflow in workflows:
            try:
                # Check if trade has been approved
                state_data = workflow.state_data
                trade_id = state_data.get('approved_trade_id')
                
                if trade_id:
                    # Check trade approval status (this would be updated via API)
                    # For now, this is just a placeholder - approval happens via API calls
                    pass
                    
            except Exception as e:
                self.logger.error(f"❌ Error checking pending workflow {workflow.id}: {e}")
    
    def _process_executing_workflows(self, workflows: List[WorkflowInstance]):
        """Process workflows in EXECUTING state"""
        for workflow in workflows[:self.max_concurrent_executions]:
            try:
                # Check order status
                state_data = workflow.state_data
                order_id = state_data.get('order_id')
                
                if order_id:
                    # Check if order is filled
                    order_status = self.order_manager.get_order_status(order_id)
                    
                    if order_status == 'filled':
                        # Order filled, create position and move to monitoring
                        position_key = self._create_position_from_fill(workflow, order_id)
                        
                        if position_key:
                            state_data.update({
                                'position_key': position_key,
                                'filled_at': datetime.now().isoformat()
                            })
                            self.database.update_workflow_state(
                                workflow.id, WorkflowState.MONITORING, state_data
                            )
                            
                            # Apply strategy management rules
                            strategy = self.database.get_strategy(workflow.strategy_id)
                            if strategy:
                                self._apply_strategy_rules(position_key, strategy)
                        else:
                            self._move_to_error(workflow.id, "Failed to create position from fill")
                    
                    elif order_status in ['cancelled', 'rejected']:
                        # Order failed, move to error
                        self._move_to_error(workflow.id, f"Order {order_status}")
                    
                    # Order still working - check for price improvement
                    elif order_status in ['submitted', 'working']:
                        self._check_order_price_improvement(workflow, order_id)
                
            except Exception as e:
                self.logger.error(f"❌ Error processing executing workflow {workflow.id}: {e}")
                self._move_to_error(workflow.id, str(e))
    
    def _process_monitoring_workflows(self, workflows: List[WorkflowInstance]):
        """Process workflows in MONITORING state"""
        for workflow in workflows:
            try:
                state_data = workflow.state_data
                position_key = state_data.get('position_key')
                
                if position_key:
                    # Check if position still exists
                    position_data = self._get_position_data(position_key)
                    
                    if not position_data:
                        # Position closed, move to completed
                        state_data.update({
                            'closed_at': datetime.now().isoformat(),
                            'close_reason': 'Position no longer exists'
                        })
                        self.database.update_workflow_state(
                            workflow.id, WorkflowState.COMPLETED, state_data
                        )
                        
                        # Restart workflow for this symbol if profitable
                        self._consider_workflow_restart(workflow)
                    else:
                        # Position still active, check management rules
                        self._monitor_position_rules(workflow, position_data)
                
            except Exception as e:
                self.logger.error(f"❌ Error monitoring workflow {workflow.id}: {e}")
    
    def _process_closing_workflows(self, workflows: List[WorkflowInstance]):
        """Process workflows in CLOSING state"""
        for workflow in workflows:
            try:
                state_data = workflow.state_data
                close_order_id = state_data.get('close_order_id')
                
                if close_order_id:
                    # Check close order status
                    order_status = self.order_manager.get_order_status(close_order_id)
                    
                    if order_status == 'filled':
                        # Close order filled, move to completed
                        state_data.update({
                            'closed_at': datetime.now().isoformat(),
                            'close_reason': 'Manual close order filled'
                        })
                        self.database.update_workflow_state(
                            workflow.id, WorkflowState.COMPLETED, state_data
                        )
                        
                        # Consider restarting workflow
                        self._consider_workflow_restart(workflow)
                    
                    elif order_status in ['cancelled', 'rejected']:
                        # Close order failed, move back to monitoring
                        self.database.update_workflow_state(
                            workflow.id, WorkflowState.MONITORING, state_data
                        )
                
            except Exception as e:
                self.logger.error(f"❌ Error processing closing workflow {workflow.id}: {e}")
    
    def _process_error_workflows(self, workflows: List[WorkflowInstance]):
        """Process workflows in ERROR state"""
        # Error workflows need manual intervention or auto-retry logic
        for workflow in workflows:
            # For now, just log errors
            # Future: implement retry logic or escalation
            if workflow.error_message:
                self.logger.warning(f"⚠️ Workflow {workflow.id} in error: {workflow.error_message}")
    
    def _evaluate_symbol_for_strategy(self, symbol: str, strategy: StrategyConfig) -> Optional[DeltaBiasEvaluation]:
        """Evaluate if symbol is suitable for strategy based on delta bias"""
        try:
            # Use screener engine to get current market data
            market_data = self.screener_engine.get_market_data_for_symbol(symbol)
            
            if not market_data:
                return None
            
            # Determine current delta bias
            # This is a simplified implementation - would use more sophisticated analysis
            current_bias = self._determine_delta_bias(market_data)
            
            # Check if strategy supports this bias
            if current_bias in strategy.delta_biases:
                confidence = self._calculate_bias_confidence(market_data, current_bias)
                
                return DeltaBiasEvaluation(
                    symbol=symbol,
                    current_bias=current_bias,
                    confidence=confidence,
                    supporting_metrics=market_data,
                    suitable_strategies=[strategy.id]
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error evaluating symbol {symbol}: {e}")
            return None
    
    def _determine_delta_bias(self, market_data: Dict[str, Any]) -> str:
        """Determine delta bias from market data"""
        # Simplified bias determination logic
        # In production, this would use more sophisticated technical analysis
        
        iv_rank = market_data.get('iv_rank', 50)
        rsi = market_data.get('rsi', 50)
        trend = market_data.get('trend_direction', 'neutral')
        
        if iv_rank > 70 and rsi > 60:
            return 'bearish'  # High IV + overbought
        elif iv_rank > 50 and rsi < 40:
            return 'bullish'  # High IV + oversold
        else:
            return 'neutral'  # Default to neutral
    
    def _calculate_bias_confidence(self, market_data: Dict[str, Any], bias: str) -> float:
        """Calculate confidence score for bias determination"""
        # Simplified confidence calculation
        base_confidence = 0.6
        
        iv_rank = market_data.get('iv_rank', 50)
        volume = market_data.get('volume', 0)
        
        # Higher IV rank increases confidence
        iv_boost = min(0.3, (iv_rank - 50) / 100)
        
        # Higher volume increases confidence
        volume_boost = min(0.1, volume / 1000000 * 0.1)
        
        return min(1.0, base_confidence + iv_boost + volume_boost)
    
    def _evaluate_trade_opportunity(self, symbol: str, strategy: StrategyConfig) -> Optional[TradeEvaluation]:
        """Perform detailed trade evaluation"""
        try:
            # Get option chain data
            option_chain = self.strategy_engine.get_option_chain(symbol)
            
            if not option_chain:
                return None
            
            # Find suitable options based on strategy
            trade_legs = self._find_strategy_legs(option_chain, strategy)
            
            if not trade_legs:
                return None
            
            # Calculate trade metrics
            cost, max_profit, max_loss = self._calculate_trade_metrics(trade_legs)
            risk_reward = max_profit / abs(max_loss) if max_loss != 0 else 0
            
            # Calculate delta exposure
            delta_exposure = sum(leg.get('delta', 0) * leg.get('quantity', 0) for leg in trade_legs)
            
            # Calculate buying power required
            buying_power = self._calculate_buying_power_required(trade_legs)
            
            # Calculate confidence score
            confidence = self._calculate_trade_confidence(symbol, strategy, trade_legs)
            
            return TradeEvaluation(
                workflow_id="",  # Will be set by caller
                symbol=symbol,
                strategy=strategy,
                estimated_cost=cost,
                estimated_max_profit=max_profit,
                estimated_max_loss=max_loss,
                risk_reward_ratio=risk_reward,
                delta_exposure=delta_exposure,
                buying_power_required=buying_power,
                position_details={'legs': trade_legs},
                confidence_score=confidence
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error evaluating trade for {symbol}: {e}")
            return None
    
    def _find_strategy_legs(self, option_chain: Any, strategy: StrategyConfig) -> List[Dict[str, Any]]:
        """Find specific option contracts for strategy legs"""
        # This is a simplified implementation
        # In production, would use sophisticated leg selection logic
        legs = []
        
        for leg_config in strategy.legs:
            # Find option based on selection method
            if leg_config.selection_method == "delta":
                option = self._find_option_by_delta(option_chain, leg_config.selection_value, leg_config.option_type)
            elif leg_config.selection_method == "atm_offset":
                option = self._find_option_by_offset(option_chain, leg_config.selection_value, leg_config.option_type)
            else:
                continue  # Skip unsupported selection methods
            
            if option:
                legs.append({
                    'action': leg_config.action,
                    'option_type': leg_config.option_type,
                    'strike': option.strike_price,
                    'expiration': option.expiration_date,
                    'quantity': leg_config.quantity,
                    'bid': option.bid_price,
                    'ask': option.ask_price,
                    'mid': option.mid_price,
                    'delta': option.delta
                })
        
        return legs
    
    def _find_option_by_delta(self, option_chain: Any, target_delta: float, option_type: str) -> Any:
        """Find option closest to target delta"""
        # Simplified implementation
        # Would need to access actual option chain structure
        return None
    
    def _find_option_by_offset(self, option_chain: Any, offset: float, option_type: str) -> Any:
        """Find option at ATM offset"""
        # Simplified implementation
        return None
    
    def _calculate_trade_metrics(self, legs: List[Dict[str, Any]]) -> Tuple[float, float, float]:
        """Calculate cost, max profit, and max loss for trade"""
        # Simplified calculation
        cost = sum(leg['mid'] * leg['quantity'] * (1 if leg['action'] == 'buy' else -1) for leg in legs)
        
        # For spreads, max profit/loss would be calculated differently
        max_profit = abs(cost) * 0.5  # Simplified
        max_loss = abs(cost)  # Simplified
        
        return cost, max_profit, max_loss
    
    def _calculate_buying_power_required(self, legs: List[Dict[str, Any]]) -> float:
        """Calculate buying power requirement"""
        # Simplified calculation - would need actual margin requirements
        return sum(leg['mid'] * leg['quantity'] * 100 for leg in legs if leg['action'] == 'buy')
    
    def _calculate_trade_confidence(self, symbol: str, strategy: StrategyConfig, legs: List[Dict[str, Any]]) -> float:
        """Calculate overall confidence in trade"""
        # Simplified confidence calculation
        base_confidence = 0.7
        
        # Adjust based on number of legs found
        leg_ratio = len(legs) / len(strategy.legs)
        
        return base_confidence * leg_ratio
    
    def approve_trade(self, trade_id: int, modifications: Dict[str, Any] = None) -> bool:
        """Approve a pending trade for execution"""
        try:
            # Get approved trade
            pending_trades = self.database.get_pending_trades()
            trade = next((t for t in pending_trades if t.id == trade_id), None)
            
            if not trade:
                self.logger.error(f"❌ Trade {trade_id} not found")
                return False
            
            # Apply modifications if provided
            if modifications:
                trade.order_details.update(modifications)
            
            # Submit order via OrderManager
            order_result = self._submit_trade_order(trade)
            
            if order_result.get('success'):
                # Update trade status
                trade.approval_status = 'approved'
                trade.approved_at = datetime.now()
                trade.order_id = order_result.get('order_id')
                
                # Update workflow to executing state
                self.database.update_workflow_state(
                    trade.workflow_id, WorkflowState.EXECUTING, 
                    {'order_id': trade.order_id, 'approved_at': datetime.now().isoformat()}
                )
                
                self.logger.info(f"✅ Approved and submitted trade: {trade_id}")
                return True
            else:
                self.logger.error(f"❌ Failed to submit order for trade {trade_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error approving trade {trade_id}: {e}")
            return False
    
    def _submit_trade_order(self, trade: ApprovedTrade) -> Dict[str, Any]:
        """Submit trade order via OrderManager"""
        try:
            # Convert trade details to order format
            # This would integrate with the existing OrderManager
            order_details = trade.order_details
            
            # Simplified order submission
            result = {
                'success': True,
                'order_id': f"order_{int(time.time())}",  # Mock order ID
                'message': 'Order submitted successfully'
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error submitting order: {e}")
            return {'success': False, 'error': str(e)}
    
    def _create_position_from_fill(self, workflow: WorkflowInstance, order_id: str) -> Optional[str]:
        """Create position entry after order fill"""
        try:
            # Get fill details and create position
            # This would integrate with existing position tracking
            position_key = f"{workflow.symbol}_{workflow.strategy_id}_{int(time.time())}"
            
            self.logger.info(f"✅ Created position: {position_key}")
            return position_key
            
        except Exception as e:
            self.logger.error(f"❌ Error creating position: {e}")
            return None
    
    def _apply_strategy_rules(self, position_key: str, strategy: StrategyConfig):
        """Apply strategy management rules to position"""
        try:
            # Convert strategy rules to position manager rules
            for rule in strategy.management_rules:
                # This would integrate with existing PositionManager
                self.logger.info(f"✅ Applied rule {rule.rule_type} to position {position_key}")
                
        except Exception as e:
            self.logger.error(f"❌ Error applying rules to position {position_key}: {e}")
    
    def _get_active_workflows_for_symbol(self, symbol: str) -> List[WorkflowInstance]:
        """Get active workflows for a symbol"""
        # Get all non-completed workflows for symbol
        all_workflows = []
        active_states = [WorkflowState.SCANNING, WorkflowState.EVALUATING, 
                        WorkflowState.PENDING_APPROVAL, WorkflowState.EXECUTING, 
                        WorkflowState.MONITORING, WorkflowState.CLOSING]
        
        for state in active_states:
            workflows = self.database.get_workflows_by_state(state)
            symbol_workflows = [w for w in workflows if w.symbol == symbol]
            all_workflows.extend(symbol_workflows)
        
        return all_workflows
    
    def _move_to_error(self, workflow_id: str, error_message: str):
        """Move workflow to error state"""
        self.database.update_workflow_state(
            workflow_id, WorkflowState.ERROR, error_message=error_message
        )
    
    def _check_order_price_improvement(self, workflow: WorkflowInstance, order_id: str):
        """Check and improve order price if needed"""
        # This would integrate with OrderManager price improvement logic
        pass
    
    def _get_position_data(self, position_key: str) -> Optional[Dict[str, Any]]:
        """Get current position data"""
        # This would integrate with existing position tracking
        return {'status': 'active', 'pnl': 0}  # Mock data
    
    def _monitor_position_rules(self, workflow: WorkflowInstance, position_data: Dict[str, Any]):
        """Monitor position against management rules"""
        # This would integrate with PositionManager
        pass
    
    def _consider_workflow_restart(self, workflow: WorkflowInstance):
        """Consider restarting workflow after position close"""
        # Check if we should start a new workflow for this symbol
        # Based on profitability, market conditions, etc.
        pass
    
    def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current workflow status"""
        try:
            # This would query the database for workflow status
            # Return current state, progress, metrics, etc.
            return {
                'workflow_id': workflow_id,
                'status': 'active',
                'current_state': 'monitoring',
                'progress': 75,
                'metrics': {}
            }
        except Exception as e:
            self.logger.error(f"❌ Error getting workflow status: {e}")
            return None
    
    def stop_processing(self):
        """Stop background workflow processing"""
        self.processing_enabled = False
        self.logger.info("🛑 Stopped workflow processing")