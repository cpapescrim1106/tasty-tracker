#!/usr/bin/env python3
"""
Initialize Default Strategies
Creates sample strategies for testing the workflow system
"""

import logging
from datetime import datetime
from workflow_database import (
    WorkflowDatabase, StrategyConfig, StrategyLeg, ManagementRule
)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_default_strategies():
    """Create default strategies for testing"""
    
    # Initialize database
    db = WorkflowDatabase()
    
    strategies = [
        {
            'name': 'Put Credit Spread - 30 DTE',
            'description': 'Bullish/neutral strategy selling puts 16 delta, buying puts 5 strikes below',
            'legs': [
                StrategyLeg(
                    action='sell',
                    option_type='put',
                    selection_method='delta',
                    selection_value=-0.16,
                    quantity=1
                ),
                StrategyLeg(
                    action='buy', 
                    option_type='put',
                    selection_method='atm_offset',
                    selection_value=-5,  # 5 strikes below
                    quantity=1
                )
            ],
            'dte_range_min': 25,
            'dte_range_max': 35,
            'profit_target_pct': 50.0,
            'stop_loss_pct': 200.0,
            'delta_biases': ['bullish', 'neutral'],
            'management_rules': [
                ManagementRule(
                    rule_type='profit_target',
                    trigger_condition='gte',
                    trigger_value=50.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='stop_loss',
                    trigger_condition='lte',
                    trigger_value=-200.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='time_exit',
                    trigger_condition='lte',
                    trigger_value=21,  # 21 DTE
                    action='close_position',
                    quantity_pct=100.0,
                    priority=2
                )
            ]
        },
        
        {
            'name': 'Call Credit Spread - 30 DTE',
            'description': 'Bearish/neutral strategy selling calls 16 delta, buying calls 5 strikes above',
            'legs': [
                StrategyLeg(
                    action='sell',
                    option_type='call',
                    selection_method='delta',
                    selection_value=0.16,
                    quantity=1
                ),
                StrategyLeg(
                    action='buy',
                    option_type='call', 
                    selection_method='atm_offset',
                    selection_value=5,  # 5 strikes above
                    quantity=1
                )
            ],
            'dte_range_min': 25,
            'dte_range_max': 35,
            'profit_target_pct': 50.0,
            'stop_loss_pct': 200.0,
            'delta_biases': ['bearish', 'neutral'],
            'management_rules': [
                ManagementRule(
                    rule_type='profit_target',
                    trigger_condition='gte',
                    trigger_value=50.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='stop_loss',
                    trigger_condition='lte',
                    trigger_value=-200.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='time_exit',
                    trigger_condition='lte',
                    trigger_value=21,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=2
                )
            ]
        },
        
        {
            'name': 'Iron Condor - 45 DTE',
            'description': 'Neutral strategy with put and call credit spreads',
            'legs': [
                # Put credit spread
                StrategyLeg(
                    action='sell',
                    option_type='put',
                    selection_method='delta',
                    selection_value=-0.16,
                    quantity=1
                ),
                StrategyLeg(
                    action='buy',
                    option_type='put',
                    selection_method='atm_offset',
                    selection_value=-10,
                    quantity=1
                ),
                # Call credit spread
                StrategyLeg(
                    action='sell',
                    option_type='call',
                    selection_method='delta',
                    selection_value=0.16,
                    quantity=1
                ),
                StrategyLeg(
                    action='buy',
                    option_type='call',
                    selection_method='atm_offset',
                    selection_value=10,
                    quantity=1
                )
            ],
            'dte_range_min': 40,
            'dte_range_max': 50,
            'profit_target_pct': 25.0,  # Lower target for iron condors
            'stop_loss_pct': 200.0,
            'delta_biases': ['neutral'],
            'management_rules': [
                ManagementRule(
                    rule_type='profit_target',
                    trigger_condition='gte',
                    trigger_value=25.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='stop_loss',
                    trigger_condition='lte',
                    trigger_value=-200.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='time_exit',
                    trigger_condition='lte',
                    trigger_value=21,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=2
                )
            ]
        },
        
        {
            'name': 'Short Strangle - 30 DTE',
            'description': 'Neutral strategy selling puts and calls around 16 delta',
            'legs': [
                StrategyLeg(
                    action='sell',
                    option_type='put',
                    selection_method='delta',
                    selection_value=-0.16,
                    quantity=1
                ),
                StrategyLeg(
                    action='sell',
                    option_type='call',
                    selection_method='delta',
                    selection_value=0.16,
                    quantity=1
                )
            ],
            'dte_range_min': 25,
            'dte_range_max': 35,
            'profit_target_pct': 50.0,
            'stop_loss_pct': 200.0,
            'delta_biases': ['neutral'],
            'management_rules': [
                ManagementRule(
                    rule_type='profit_target',
                    trigger_condition='gte',
                    trigger_value=50.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='stop_loss',
                    trigger_condition='lte',
                    trigger_value=-200.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='time_exit',
                    trigger_condition='lte',
                    trigger_value=21,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=2
                ),
                ManagementRule(
                    rule_type='delta_breach',
                    trigger_condition='gte',
                    trigger_value=0.25,  # Close if delta gets too high
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                )
            ]
        },
        
        {
            'name': 'Cash Secured Put - 30 DTE',
            'description': 'Bullish strategy selling puts to acquire stock',
            'legs': [
                StrategyLeg(
                    action='sell',
                    option_type='put',
                    selection_method='delta',
                    selection_value=-0.20,
                    quantity=1
                )
            ],
            'dte_range_min': 25,
            'dte_range_max': 35,
            'profit_target_pct': 50.0,
            'stop_loss_pct': 300.0,  # Higher tolerance for CSPs
            'delta_biases': ['bullish'],
            'management_rules': [
                ManagementRule(
                    rule_type='profit_target',
                    trigger_condition='gte',
                    trigger_value=50.0,
                    action='close_position',
                    quantity_pct=100.0,
                    priority=1
                ),
                ManagementRule(
                    rule_type='time_exit',
                    trigger_condition='lte',
                    trigger_value=7,  # Close at 7 DTE
                    action='close_position',
                    quantity_pct=100.0,
                    priority=2
                )
            ]
        }
    ]
    
    # Create strategies
    created_strategies = []
    for strategy_data in strategies:
        try:
            strategy = StrategyConfig(
                name=strategy_data['name'],
                description=strategy_data['description'],
                legs=strategy_data['legs'],
                dte_range_min=strategy_data['dte_range_min'],
                dte_range_max=strategy_data['dte_range_max'],
                profit_target_pct=strategy_data['profit_target_pct'],
                stop_loss_pct=strategy_data['stop_loss_pct'],
                delta_biases=strategy_data['delta_biases'],
                management_rules=strategy_data['management_rules']
            )
            
            strategy_id = db.save_strategy(strategy)
            created_strategies.append((strategy_id, strategy.name))
            logger.info(f"✅ Created strategy: {strategy.name} (ID: {strategy_id})")
            
        except Exception as e:
            logger.error(f"❌ Failed to create strategy {strategy_data['name']}: {e}")
    
    return created_strategies

def main():
    """Main function"""
    logger.info("🚀 Initializing default strategies...")
    
    try:
        strategies = create_default_strategies()
        
        logger.info(f"✅ Successfully created {len(strategies)} default strategies:")
        for strategy_id, name in strategies:
            logger.info(f"   - {name} (ID: {strategy_id})")
        
        logger.info("🎯 Default strategies initialization complete!")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize default strategies: {e}")
        raise

if __name__ == '__main__':
    main()