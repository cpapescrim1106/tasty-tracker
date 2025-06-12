#!/usr/bin/env python3
"""
TastyTracker Position Manager
Automated stop-loss and profit-taking system for existing positions
"""

import os
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

# Import strategy rules engine
from strategy_rules_templates import StrategyRulesEngine

@dataclass
class PositionRule:
    """Stop-loss and profit-taking rule configuration"""
    position_key: str  # Account:Symbol identifier
    rule_id: str
    rule_type: str  # "stop_loss", "profit_target", "trailing_stop"
    trigger_type: str  # "price", "percentage", "delta"
    trigger_value: float  # Price level, percentage, or delta threshold
    action: str  # "close_position", "partial_close", "hedge"
    quantity_pct: float = 100.0  # Percentage of position to close
    is_active: bool = True
    created_at: datetime = None
    triggered_at: Optional[datetime] = None
    notes: str = ""

@dataclass
class TriggerEvent:
    """Position trigger event details"""
    position_key: str
    rule_id: str
    trigger_type: str
    current_value: float
    trigger_value: float
    action_required: str
    confidence: float
    timestamp: datetime
    warnings: List[str]

@dataclass
class PositionAlert:
    """Position monitoring alert"""
    position_key: str
    alert_type: str  # "approaching_stop", "profit_target_near", "high_risk"
    message: str
    urgency: str  # "low", "medium", "high", "critical"
    current_price: float
    trigger_price: float
    distance_pct: float
    timestamp: datetime

class TriggerType(Enum):
    """Trigger condition types"""
    STOP_LOSS = "stop_loss"
    PROFIT_TARGET = "profit_target"
    TRAILING_STOP = "trailing_stop"
    DELTA_HEDGE = "delta_hedge"
    TIME_DECAY = "time_decay"

class PositionManager:
    """Automated position monitoring and management system"""
    
    def __init__(self, tracker_instance):
        self.tracker = tracker_instance
        self.logger = logging.getLogger(__name__)
        
        # Rule storage
        self.position_rules = {}  # position_key -> list of rules
        self.triggered_rules = {}  # rule_id -> trigger event
        self.position_alerts = {}  # position_key -> list of alerts
        
        # Monitoring configuration
        self.monitoring_enabled = True
        self.check_interval = 10  # seconds
        self.alert_thresholds = {
            'stop_loss_distance_pct': 5.0,  # Alert when within 5% of stop
            'profit_target_distance_pct': 10.0,  # Alert when within 10% of target
            'high_risk_loss_pct': 15.0  # Alert when position loss > 15%
        }
        
        # Safety limits
        self.max_daily_trades = 10
        self.max_position_close_pct = 50.0  # Max % of position to close at once
        self.min_position_value = 100.0  # Min position value to manage
        
        # Tracking
        self.daily_trade_count = 0
        self.last_monitoring_check = datetime.now()
        self.position_history = {}
        
        # Strategy rules engine
        self.rules_engine = StrategyRulesEngine()
    
    def add_position_rule(self, position_key: str, rule_config: Dict[str, Any]) -> str:
        """Add a new position management rule"""
        try:
            rule_id = f"{position_key}_{rule_config['rule_type']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            rule = PositionRule(
                position_key=position_key,
                rule_id=rule_id,
                rule_type=rule_config['rule_type'],
                trigger_type=rule_config['trigger_type'],
                trigger_value=float(rule_config['trigger_value']),
                action=rule_config['action'],
                quantity_pct=float(rule_config.get('quantity_pct', 100.0)),
                is_active=True,
                created_at=datetime.now(),
                notes=rule_config.get('notes', '')
            )
            
            if position_key not in self.position_rules:
                self.position_rules[position_key] = []
            
            self.position_rules[position_key].append(rule)
            
            self.logger.info(f"📋 Added {rule.rule_type} rule for {position_key}: "
                           f"{rule.trigger_type} @ {rule.trigger_value}")
            
            return rule_id
            
        except Exception as e:
            self.logger.error(f"❌ Error adding position rule: {e}")
            raise
    
    def check_position_triggers(self, position_key: str) -> List[TriggerEvent]:
        """Check if any rules are triggered for a specific position"""
        try:
            if position_key not in self.position_rules:
                return []
            
            # Get current position data
            position = self._get_position_data(position_key)
            if not position:
                return []
            
            triggered_events = []
            
            for rule in self.position_rules[position_key]:
                if not rule.is_active or rule.triggered_at:
                    continue
                
                trigger_result = self._evaluate_trigger_condition(rule, position)
                if trigger_result:
                    triggered_events.append(trigger_result)
            
            return triggered_events
            
        except Exception as e:
            self.logger.error(f"❌ Error checking triggers for {position_key}: {e}")
            return []
    
    def monitor_all_positions(self) -> Dict[str, Any]:
        """Monitor all positions for trigger conditions and alerts"""
        try:
            if not self.monitoring_enabled:
                return {'status': 'monitoring_disabled'}
            
            monitoring_summary = {
                'total_positions': 0,
                'positions_with_rules': 0,
                'triggered_events': [],
                'new_alerts': [],
                'monitoring_timestamp': datetime.now().isoformat()
            }
            
            # Get all active positions
            with self.tracker.positions_lock:
                all_positions = list(self.tracker.positions.keys())
            
            monitoring_summary['total_positions'] = len(all_positions)
            
            for position_key in all_positions:
                # Check for triggered rules
                triggered_events = self.check_position_triggers(position_key)
                monitoring_summary['triggered_events'].extend(triggered_events)
                
                # Generate alerts
                alerts = self._generate_position_alerts(position_key)
                monitoring_summary['new_alerts'].extend(alerts)
                
                if position_key in self.position_rules:
                    monitoring_summary['positions_with_rules'] += 1
            
            self.last_monitoring_check = datetime.now()
            
            # Log summary if there are any events
            if monitoring_summary['triggered_events'] or monitoring_summary['new_alerts']:
                self.logger.info(f"📊 Position monitoring: {len(monitoring_summary['triggered_events'])} triggers, "
                               f"{len(monitoring_summary['new_alerts'])} alerts")
            
            return monitoring_summary
            
        except Exception as e:
            self.logger.error(f"❌ Error monitoring positions: {e}")
            return {'error': str(e)}
    
    def _evaluate_trigger_condition(self, rule: PositionRule, position: Dict[str, Any]) -> Optional[TriggerEvent]:
        """Evaluate if a rule's trigger condition is met"""
        try:
            current_price = position.get('price', 0)
            entry_price = position.get('entry_price', current_price)  # Would need to track this
            current_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
            
            triggered = False
            current_value = 0
            warnings = []
            
            if rule.trigger_type == 'price':
                current_value = current_price
                if rule.rule_type == 'stop_loss':
                    triggered = current_price <= rule.trigger_value
                elif rule.rule_type == 'profit_target':
                    triggered = current_price >= rule.trigger_value
                    
            elif rule.trigger_type == 'percentage':
                current_value = current_pnl_pct
                if rule.rule_type == 'stop_loss':
                    triggered = current_pnl_pct <= -abs(rule.trigger_value)
                elif rule.rule_type == 'profit_target':
                    triggered = current_pnl_pct >= rule.trigger_value
                    
            elif rule.trigger_type == 'delta':
                current_value = position.get('delta', 0)
                triggered = abs(current_value) >= abs(rule.trigger_value)
            
            # Calculate confidence based on how far past the trigger we are
            confidence = 1.0
            if triggered:
                if rule.trigger_type == 'price':
                    distance_pct = abs(current_value - rule.trigger_value) / rule.trigger_value * 100
                    confidence = min(1.0, 0.5 + (distance_pct / 10.0))  # Higher confidence for bigger moves
                
                # Add warnings for risky actions
                if rule.action == 'close_position' and rule.quantity_pct > 50:
                    warnings.append("⚠️ Large position closure - consider partial close")
                
                if position.get('net_liq', 0) < self.min_position_value:
                    warnings.append("⚠️ Position value below minimum threshold")
                    confidence *= 0.5
                
                return TriggerEvent(
                    position_key=rule.position_key,
                    rule_id=rule.rule_id,
                    trigger_type=rule.trigger_type,
                    current_value=current_value,
                    trigger_value=rule.trigger_value,
                    action_required=rule.action,
                    confidence=confidence,
                    timestamp=datetime.now(),
                    warnings=warnings
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error evaluating trigger condition: {e}")
            return None
    
    def _generate_position_alerts(self, position_key: str) -> List[PositionAlert]:
        """Generate alerts for position monitoring"""
        try:
            position = self._get_position_data(position_key)
            if not position:
                return []
            
            alerts = []
            current_price = position.get('price', 0)
            
            # Check rules for approaching triggers
            if position_key in self.position_rules:
                for rule in self.position_rules[position_key]:
                    if not rule.is_active or rule.triggered_at:
                        continue
                    
                    if rule.trigger_type == 'price':
                        distance_pct = abs(current_price - rule.trigger_value) / current_price * 100
                        
                        urgency = 'low'
                        if distance_pct <= 2.0:
                            urgency = 'critical'
                        elif distance_pct <= 5.0:
                            urgency = 'high'
                        elif distance_pct <= 10.0:
                            urgency = 'medium'
                        
                        if distance_pct <= self.alert_thresholds.get(f"{rule.rule_type}_distance_pct", 10.0):
                            alert = PositionAlert(
                                position_key=position_key,
                                alert_type=f"{rule.rule_type}_approaching",
                                message=f"{rule.rule_type.replace('_', ' ').title()} approaching: {distance_pct:.1f}% away",
                                urgency=urgency,
                                current_price=current_price,
                                trigger_price=rule.trigger_value,
                                distance_pct=distance_pct,
                                timestamp=datetime.now()
                            )
                            alerts.append(alert)
            
            # Check for high-risk positions (large unrealized losses)
            entry_price = position.get('entry_price', current_price)
            if entry_price > 0:
                pnl_pct = (current_price - entry_price) / entry_price * 100
                if pnl_pct <= -self.alert_thresholds['high_risk_loss_pct']:
                    alert = PositionAlert(
                        position_key=position_key,
                        alert_type='high_risk',
                        message=f"Large unrealized loss: {pnl_pct:.1f}%",
                        urgency='high',
                        current_price=current_price,
                        trigger_price=entry_price,
                        distance_pct=abs(pnl_pct),
                        timestamp=datetime.now()
                    )
                    alerts.append(alert)
            
            return alerts
            
        except Exception as e:
            self.logger.error(f"❌ Error generating alerts for {position_key}: {e}")
            return []
    
    def _get_position_data(self, position_key: str) -> Optional[Dict[str, Any]]:
        """Get current position data"""
        try:
            with self.tracker.positions_lock:
                return self.tracker.positions.get(position_key)
        except Exception as e:
            self.logger.error(f"❌ Error getting position data for {position_key}: {e}")
            return None
    
    def get_position_rules_summary(self, account_number: str = None) -> Dict[str, Any]:
        """Get summary of all position rules and their status"""
        try:
            summary = {
                'total_rules': 0,
                'active_rules': 0,
                'triggered_rules': 0,
                'positions_with_rules': [],
                'recent_alerts': [],
                'monitoring_status': {
                    'enabled': self.monitoring_enabled,
                    'last_check': self.last_monitoring_check.isoformat(),
                    'daily_trades': self.daily_trade_count
                }
            }
            
            for position_key, rules in self.position_rules.items():
                # Filter by account if specified
                if account_number and not position_key.startswith(f"{account_number}:"):
                    continue
                
                position_summary = {
                    'position_key': position_key,
                    'rules': []
                }
                
                for rule in rules:
                    summary['total_rules'] += 1
                    if rule.is_active:
                        summary['active_rules'] += 1
                    if rule.triggered_at:
                        summary['triggered_rules'] += 1
                    
                    rule_summary = {
                        'rule_id': rule.rule_id,
                        'rule_type': rule.rule_type,
                        'trigger_type': rule.trigger_type,
                        'trigger_value': rule.trigger_value,
                        'action': rule.action,
                        'quantity_pct': rule.quantity_pct,
                        'is_active': rule.is_active,
                        'triggered_at': rule.triggered_at.isoformat() if rule.triggered_at else None,
                        'created_at': rule.created_at.isoformat() if rule.created_at else None
                    }
                    position_summary['rules'].append(rule_summary)
                
                if position_summary['rules']:
                    summary['positions_with_rules'].append(position_summary)
            
            # Add recent alerts
            current_time = datetime.now()
            for position_key, alerts in self.position_alerts.items():
                for alert in alerts:
                    if (current_time - alert.timestamp).total_seconds() < 3600:  # Last hour
                        alert_summary = {
                            'position_key': alert.position_key,
                            'alert_type': alert.alert_type,
                            'message': alert.message,
                            'urgency': alert.urgency,
                            'timestamp': alert.timestamp.isoformat()
                        }
                        summary['recent_alerts'].append(alert_summary)
            
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ Error getting rules summary: {e}")
            return {'error': str(e)}
    
    def create_sample_rules(self, position_key: str) -> List[str]:
        """Create sample stop-loss and profit-taking rules for a position"""
        try:
            position = self._get_position_data(position_key)
            if not position:
                raise ValueError(f"Position {position_key} not found")
            
            current_price = position.get('price', 0)
            if current_price <= 0:
                raise ValueError(f"Invalid price for position {position_key}")
            
            # Create sample rules
            rule_configs = [
                {
                    'rule_type': 'stop_loss',
                    'trigger_type': 'percentage',
                    'trigger_value': 15.0,  # 15% loss
                    'action': 'close_position',
                    'quantity_pct': 100.0,
                    'notes': 'Sample stop-loss at 15% loss'
                },
                {
                    'rule_type': 'profit_target',
                    'trigger_type': 'percentage',
                    'trigger_value': 25.0,  # 25% profit
                    'action': 'partial_close',
                    'quantity_pct': 50.0,
                    'notes': 'Sample profit target at 25% gain (partial close)'
                },
                {
                    'rule_type': 'trailing_stop',
                    'trigger_type': 'price',
                    'trigger_value': current_price * 0.90,  # 10% below current
                    'action': 'close_position',
                    'quantity_pct': 100.0,
                    'notes': 'Sample trailing stop at 10% below current price'
                }
            ]
            
            created_rules = []
            for config in rule_configs:
                rule_id = self.add_position_rule(position_key, config)
                created_rules.append(rule_id)
            
            self.logger.info(f"📋 Created {len(created_rules)} sample rules for {position_key}")
            return created_rules
            
        except Exception as e:
            self.logger.error(f"❌ Error creating sample rules: {e}")
            raise
    
    def apply_strategy_rules_to_chains(self, position_chains: Dict[str, Dict]) -> Dict[str, Any]:
        """Apply automatic strategy rules to detected position chains"""
        try:
            results = {
                'total_chains_processed': 0,
                'rules_created': 0,
                'chains_with_rules': [],
                'errors': []
            }
            
            for underlying, chain_data in position_chains.items():
                chains = chain_data.get('chains', [])
                
                for chain in chains:
                    try:
                        results['total_chains_processed'] += 1
                        
                        # Convert chain object to dictionary for rules engine
                        chain_dict = {
                            'chain_id': chain.chain_id,
                            'chain_type': chain.chain_type,
                            'description': chain.description,
                            'legs': chain.legs,
                            'metrics': chain.metrics
                        }
                        
                        # Apply strategy rules
                        created_rules = self.rules_engine.apply_templates_to_chain(
                            chain_dict, self
                        )
                        
                        if created_rules:
                            results['rules_created'] += len(created_rules)
                            results['chains_with_rules'].append({
                                'chain_id': chain.chain_id,
                                'chain_type': chain.chain_type,
                                'description': chain.description,
                                'rules_applied': len(created_rules),
                                'rule_ids': created_rules
                            })
                            
                            self.logger.info(f"🎯 Applied {len(created_rules)} rules to {chain.description}")
                        
                    except Exception as e:
                        error_msg = f"Error applying rules to chain {chain.chain_id}: {e}"
                        results['errors'].append(error_msg)
                        self.logger.error(f"❌ {error_msg}")
            
            # Log summary
            self.logger.info(f"📊 Strategy rules applied: {results['rules_created']} rules "
                           f"across {len(results['chains_with_rules'])} chains")
            
            return results
            
        except Exception as e:
            self.logger.error(f"❌ Error applying strategy rules to chains: {e}")
            return {
                'error': str(e),
                'total_chains_processed': 0,
                'rules_created': 0
            }
    
    def get_strategy_rules_summary(self) -> Dict[str, Any]:
        """Get summary of available strategy rule templates"""
        try:
            return self.rules_engine.get_template_summary()
        except Exception as e:
            self.logger.error(f"❌ Error getting strategy rules summary: {e}")
            return {'error': str(e)}