#!/usr/bin/env python3
"""
Strategy Rules Templates
Defines automatic management rules for different option strategies
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

@dataclass
class RuleTemplate:
    """Template for automatic position management rules"""
    strategy_type: str
    rule_type: str  # "profit_target", "stop_loss", "time_based", "earnings_based"
    trigger_type: str  # "percentage", "price", "time", "event"
    trigger_value: float
    action: str  # "close_position", "partial_close", "roll_position"
    quantity_pct: float = 100.0
    priority: int = 1  # Lower numbers = higher priority
    description: str = ""
    conditions: Dict[str, Any] = None  # Additional conditions

class StrategyType(Enum):
    """Supported strategy types for rule templates"""
    PUT_CREDIT_SPREAD = "put_credit_spread"
    CALL_CREDIT_SPREAD = "call_credit_spread" 
    PUT_DEBIT_SPREAD = "put_debit_spread"
    CALL_DEBIT_SPREAD = "call_debit_spread"
    IRON_CONDOR = "iron_condor"
    LONG_STRADDLE = "long_straddle"
    SHORT_STRADDLE = "short_straddle"
    LONG_STRANGLE = "long_strangle"
    SHORT_STRANGLE = "short_strangle"
    LONG_CALL = "long_call"
    SHORT_CALL = "short_call"
    LONG_PUT = "long_put"
    SHORT_PUT = "short_put"
    CALL_CALENDAR = "call_calendar"
    PUT_CALENDAR = "put_calendar"

class StrategyRulesEngine:
    """Engine for applying automatic rules to detected option strategies"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.rule_templates = self._initialize_rule_templates()
        
    def _initialize_rule_templates(self) -> Dict[str, List[RuleTemplate]]:
        """Initialize default rule templates for each strategy type"""
        templates = {}
        
        # Put Credit Spreads - Manage at 50% profit
        templates[StrategyType.PUT_CREDIT_SPREAD.value] = [
            RuleTemplate(
                strategy_type=StrategyType.PUT_CREDIT_SPREAD.value,
                rule_type="profit_target",
                trigger_type="percentage",
                trigger_value=50.0,
                action="close_position",
                quantity_pct=100.0,
                priority=1,
                description="Close put credit spread at 50% of max profit",
                conditions={"min_dte": 0, "max_dte": 45}
            ),
            RuleTemplate(
                strategy_type=StrategyType.PUT_CREDIT_SPREAD.value,
                rule_type="stop_loss",
                trigger_type="percentage",
                trigger_value=-200.0,  # 2x max profit loss
                action="close_position",
                quantity_pct=100.0,
                priority=2,
                description="Stop loss at 200% of credit received"
            ),
            RuleTemplate(
                strategy_type=StrategyType.PUT_CREDIT_SPREAD.value,
                rule_type="time_based",
                trigger_type="time",
                trigger_value=21,  # 21 DTE
                action="close_position",
                quantity_pct=100.0,
                priority=3,
                description="Close at 21 DTE if not profitable"
            )
        ]
        
        # Call Credit Spreads - Manage at 30% profit
        templates[StrategyType.CALL_CREDIT_SPREAD.value] = [
            RuleTemplate(
                strategy_type=StrategyType.CALL_CREDIT_SPREAD.value,
                rule_type="profit_target",
                trigger_type="percentage",
                trigger_value=30.0,
                action="close_position",
                quantity_pct=100.0,
                priority=1,
                description="Close call credit spread at 30% of max profit"
            ),
            RuleTemplate(
                strategy_type=StrategyType.CALL_CREDIT_SPREAD.value,
                rule_type="stop_loss",
                trigger_type="percentage",
                trigger_value=-200.0,
                action="close_position",
                quantity_pct=100.0,
                priority=2,
                description="Stop loss at 200% of credit received"
            )
        ]
        
        # Iron Condors - Conservative management
        templates[StrategyType.IRON_CONDOR.value] = [
            RuleTemplate(
                strategy_type=StrategyType.IRON_CONDOR.value,
                rule_type="profit_target",
                trigger_type="percentage",
                trigger_value=25.0,
                action="close_position",
                quantity_pct=100.0,
                priority=1,
                description="Close iron condor at 25% of max profit"
            ),
            RuleTemplate(
                strategy_type=StrategyType.IRON_CONDOR.value,
                rule_type="stop_loss",
                trigger_type="percentage",
                trigger_value=-200.0,
                action="close_position",
                quantity_pct=100.0,
                priority=2,
                description="Stop loss at 200% of credit received"
            ),
            RuleTemplate(
                strategy_type=StrategyType.IRON_CONDOR.value,
                rule_type="time_based",
                trigger_type="time",
                trigger_value=21,
                action="close_position",
                quantity_pct=100.0,
                priority=3,
                description="Close at 21 DTE if not profitable"
            )
        ]
        
        # Long Calls - Trend following rules
        templates[StrategyType.LONG_CALL.value] = [
            RuleTemplate(
                strategy_type=StrategyType.LONG_CALL.value,
                rule_type="profit_target",
                trigger_type="percentage",
                trigger_value=100.0,
                action="partial_close",
                quantity_pct=50.0,
                priority=1,
                description="Take profits on half position at 100% gain"
            ),
            RuleTemplate(
                strategy_type=StrategyType.LONG_CALL.value,
                rule_type="stop_loss",
                trigger_type="percentage",
                trigger_value=-50.0,
                action="close_position",
                quantity_pct=100.0,
                priority=2,
                description="Stop loss at 50% of premium paid"
            ),
            RuleTemplate(
                strategy_type=StrategyType.LONG_CALL.value,
                rule_type="time_based",
                trigger_type="time",
                trigger_value=30,
                action="close_position",
                quantity_pct=100.0,
                priority=3,
                description="Close at 30 DTE to avoid time decay"
            )
        ]
        
        # Long Puts - Similar to long calls
        templates[StrategyType.LONG_PUT.value] = [
            RuleTemplate(
                strategy_type=StrategyType.LONG_PUT.value,
                rule_type="profit_target",
                trigger_type="percentage",
                trigger_value=100.0,
                action="partial_close",
                quantity_pct=50.0,
                priority=1,
                description="Take profits on half position at 100% gain"
            ),
            RuleTemplate(
                strategy_type=StrategyType.LONG_PUT.value,
                rule_type="stop_loss",
                trigger_type="percentage",
                trigger_value=-50.0,
                action="close_position",
                quantity_pct=100.0,
                priority=2,
                description="Stop loss at 50% of premium paid"
            )
        ]
        
        # Short Straddles/Strangles - High-maintenance strategies
        templates[StrategyType.SHORT_STRADDLE.value] = [
            RuleTemplate(
                strategy_type=StrategyType.SHORT_STRADDLE.value,
                rule_type="profit_target",
                trigger_type="percentage",
                trigger_value=25.0,
                action="close_position",
                quantity_pct=100.0,
                priority=1,
                description="Close short straddle at 25% of max profit"
            ),
            RuleTemplate(
                strategy_type=StrategyType.SHORT_STRADDLE.value,
                rule_type="stop_loss",
                trigger_type="percentage",
                trigger_value=-150.0,
                action="close_position",
                quantity_pct=100.0,
                priority=2,
                description="Stop loss at 150% of credit received"
            )
        ]
        
        templates[StrategyType.SHORT_STRANGLE.value] = [
            RuleTemplate(
                strategy_type=StrategyType.SHORT_STRANGLE.value,
                rule_type="profit_target",
                trigger_type="percentage",
                trigger_value=25.0,
                action="close_position",
                quantity_pct=100.0,
                priority=1,
                description="Close short strangle at 25% of max profit"
            ),
            RuleTemplate(
                strategy_type=StrategyType.SHORT_STRANGLE.value,
                rule_type="stop_loss",
                trigger_type="percentage",
                trigger_value=-150.0,
                action="close_position",
                quantity_pct=100.0,
                priority=2,
                description="Stop loss at 150% of credit received"
            )
        ]
        
        return templates
    
    def get_rules_for_strategy(self, strategy_type: str) -> List[RuleTemplate]:
        """Get rule templates for a specific strategy type"""
        return self.rule_templates.get(strategy_type, [])
    
    def create_earnings_rules(self, chain_data: Dict[str, Any]) -> List[RuleTemplate]:
        """Create special rules for earnings plays"""
        earnings_rules = []
        
        # Check if position involves earnings (would need earnings calendar integration)
        # For now, create generic earnings rules
        
        earnings_rule = RuleTemplate(
            strategy_type=chain_data.get('chain_type', 'unknown'),
            rule_type="earnings_based",
            trigger_type="event",
            trigger_value=0,  # Trigger immediately after earnings
            action="close_position",
            quantity_pct=100.0,
            priority=1,
            description="Close position morning after earnings announcement",
            conditions={
                "event_type": "earnings_announcement",
                "trigger_time": "market_open_next_day"
            }
        )
        earnings_rules.append(earnings_rule)
        
        return earnings_rules
    
    def apply_templates_to_chain(self, chain_data: Dict[str, Any], 
                                position_manager) -> List[str]:
        """Apply rule templates to a detected position chain"""
        try:
            strategy_type = chain_data.get('chain_type')
            if not strategy_type:
                self.logger.warning("⚠️ No strategy type found for chain")
                return []
            
            # Get templates for this strategy
            templates = self.get_rules_for_strategy(strategy_type)
            if not templates:
                self.logger.info(f"📋 No rule templates found for strategy: {strategy_type}")
                return []
            
            created_rules = []
            
            # Create rules for each leg in the chain
            for leg_key in chain_data.get('legs', []):
                for template in templates:
                    # Check if conditions are met
                    if self._check_template_conditions(template, chain_data):
                        rule_config = {
                            'rule_type': template.rule_type,
                            'trigger_type': template.trigger_type,
                            'trigger_value': template.trigger_value,
                            'action': template.action,
                            'quantity_pct': template.quantity_pct,
                            'notes': f"Auto-generated: {template.description}"
                        }
                        
                        # Create the rule
                        rule_id = position_manager.add_position_rule(leg_key, rule_config)
                        created_rules.append(rule_id)
                        
                        self.logger.info(f"📋 Applied {template.rule_type} rule to {leg_key}: "
                                       f"{template.description}")
            
            return created_rules
            
        except Exception as e:
            self.logger.error(f"❌ Error applying templates to chain: {e}")
            return []
    
    def _check_template_conditions(self, template: RuleTemplate, 
                                 chain_data: Dict[str, Any]) -> bool:
        """Check if template conditions are met for applying the rule"""
        try:
            if not template.conditions:
                return True
            
            # Check DTE conditions
            if 'min_dte' in template.conditions or 'max_dte' in template.conditions:
                chain_dte = chain_data.get('metrics', {}).get('days_to_expiration', 0)
                
                if 'min_dte' in template.conditions:
                    if chain_dte < template.conditions['min_dte']:
                        return False
                        
                if 'max_dte' in template.conditions:
                    if chain_dte > template.conditions['max_dte']:
                        return False
            
            # Check profit/loss conditions
            if 'min_profit_pct' in template.conditions:
                current_pnl = chain_data.get('metrics', {}).get('net_premium', 0)
                # Would need to calculate current P&L percentage
                pass
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error checking template conditions: {e}")
            return False
    
    def get_all_strategy_types(self) -> List[str]:
        """Get list of all supported strategy types"""
        return list(self.rule_templates.keys())
    
    def add_custom_template(self, strategy_type: str, template: RuleTemplate):
        """Add a custom rule template for a strategy type"""
        if strategy_type not in self.rule_templates:
            self.rule_templates[strategy_type] = []
        
        self.rule_templates[strategy_type].append(template)
        self.logger.info(f"📋 Added custom template for {strategy_type}: {template.description}")
    
    def get_template_summary(self) -> Dict[str, Any]:
        """Get summary of all available rule templates"""
        summary = {
            'total_strategy_types': len(self.rule_templates),
            'strategies': {}
        }
        
        for strategy_type, templates in self.rule_templates.items():
            summary['strategies'][strategy_type] = {
                'total_rules': len(templates),
                'rule_types': list(set(t.rule_type for t in templates)),
                'descriptions': [t.description for t in templates]
            }
        
        return summary