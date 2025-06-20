#!/usr/bin/env python3
"""
Workflow Database Manager
Manages database schema and operations for the trading workflow system
"""

import sqlite3
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict

class WorkflowState(Enum):
    SCANNING = "scanning"
    EVALUATING = "evaluating"
    PENDING_APPROVAL = "pending_approval"
    EXECUTING = "executing"
    MONITORING = "monitoring"
    CLOSING = "closing"
    COMPLETED = "completed"
    ERROR = "error"

@dataclass
class StrategyLeg:
    """Individual leg of a multi-leg strategy"""
    action: str  # "buy", "sell"
    option_type: str  # "call", "put"
    selection_method: str  # "atm", "offset", "percentage", "premium", "atm_straddle"
    selection_value: float  # offset, percentage, or premium amount
    quantity: int = 1

@dataclass
class ManagementRule:
    """Position management rule"""
    rule_type: str  # "profit_target", "stop_loss", "time_exit", "delta_breach"
    trigger_condition: str  # "gte", "lte", "equals"
    trigger_value: float  # percentage, price, or other value
    action: str  # "close_position", "partial_close", "roll", "adjust"
    quantity_pct: float = 100.0  # percentage of position to affect
    priority: int = 1  # execution priority (1 = highest)

@dataclass
class StrategyConfig:
    """Complete strategy configuration"""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    opening_action: str = "STO"  # "BTO" or "STO"
    legs: List[StrategyLeg] = None
    dte_range_min: int = 30
    dte_range_max: int = 45
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 200.0
    no_stop_loss: bool = True  # Default to no stop loss
    minimum_premium_required: float = 0.0  # Minimum total strategy premium
    minimum_underlying_price: float = 0.0  # Minimum underlying price filter
    closing_21_dte: bool = False  # Close positions at 21 DTE
    delta_biases: List[str] = None  # ["bullish", "neutral", "bearish"]
    management_rules: List[ManagementRule] = None
    created_at: Optional[datetime] = None
    is_active: bool = True
    strategy_type: Optional[str] = None  # Classified strategy type
    
    def __post_init__(self):
        if self.legs is None:
            self.legs = []
        if self.delta_biases is None:
            self.delta_biases = ["neutral"]
        if self.management_rules is None:
            self.management_rules = []

@dataclass
class WorkflowInstance:
    """Individual workflow instance tracking"""
    id: str
    symbol: str
    strategy_id: int
    current_state: WorkflowState
    state_data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None

@dataclass
class ApprovedTrade:
    """Trade approved for execution"""
    id: Optional[int] = None
    workflow_id: str = ""
    symbol: str = ""
    strategy_id: int = 0
    strategy_config: Dict[str, Any] = None
    order_details: Dict[str, Any] = None
    approval_status: str = "pending"  # "pending", "approved", "rejected", "executed"
    approved_at: Optional[datetime] = None
    order_id: Optional[str] = None
    position_key: Optional[str] = None
    risk_metrics: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.strategy_config is None:
            self.strategy_config = {}
        if self.order_details is None:
            self.order_details = {}
        if self.risk_metrics is None:
            self.risk_metrics = {}

class WorkflowDatabase:
    """Database manager for workflow system"""
    
    def __init__(self, db_path: str = "workflow.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._initialize_database()
        
    def _initialize_database(self):
        """Initialize database schema"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if opening_action column exists, add if missing
            cursor.execute("PRAGMA table_info(strategies)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'opening_action' not in columns:
                cursor.execute("ALTER TABLE strategies ADD COLUMN opening_action TEXT DEFAULT 'STO'")
                self.logger.info("✅ Added opening_action column to existing strategies table")
            
            # Add new strategy enhancement columns if missing
            if 'no_stop_loss' not in columns:
                cursor.execute("ALTER TABLE strategies ADD COLUMN no_stop_loss BOOLEAN DEFAULT true")
                self.logger.info("✅ Added no_stop_loss column to existing strategies table")
            
            if 'minimum_premium_required' not in columns:
                cursor.execute("ALTER TABLE strategies ADD COLUMN minimum_premium_required REAL DEFAULT 0.0")
                self.logger.info("✅ Added minimum_premium_required column to existing strategies table")
            
            if 'minimum_underlying_price' not in columns:
                cursor.execute("ALTER TABLE strategies ADD COLUMN minimum_underlying_price REAL DEFAULT 0.0")
                self.logger.info("✅ Added minimum_underlying_price column to existing strategies table")
            
            if 'closing_21_dte' not in columns:
                cursor.execute("ALTER TABLE strategies ADD COLUMN closing_21_dte BOOLEAN DEFAULT false")
                self.logger.info("✅ Added closing_21_dte column to existing strategies table")
            
            if 'strategy_type' not in columns:
                cursor.execute("ALTER TABLE strategies ADD COLUMN strategy_type TEXT")
                self.logger.info("✅ Added strategy_type column to existing strategies table")
            
            # Strategies table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    opening_action TEXT DEFAULT 'STO',  -- 'BTO' or 'STO'
                    legs_config TEXT NOT NULL,  -- JSON
                    dte_range_min INTEGER DEFAULT 30,
                    dte_range_max INTEGER DEFAULT 45,
                    profit_target_pct REAL DEFAULT 50.0,
                    stop_loss_pct REAL DEFAULT 200.0,
                    no_stop_loss BOOLEAN DEFAULT true,
                    minimum_premium_required REAL DEFAULT 0.0,
                    minimum_underlying_price REAL DEFAULT 0.0,
                    closing_21_dte BOOLEAN DEFAULT false,
                    delta_biases TEXT DEFAULT '["neutral"]',  -- JSON array
                    management_rules TEXT DEFAULT '[]',  -- JSON array
                    strategy_type TEXT,  -- Classified strategy type
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT true
                )
            ''')
            
            # Workflow instances table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS workflow_instances (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    strategy_id INTEGER NOT NULL,
                    current_state TEXT NOT NULL,
                    state_data TEXT DEFAULT '{}',  -- JSON
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT,
                    FOREIGN KEY (strategy_id) REFERENCES strategies (id)
                )
            ''')
            
            # Approved trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS approved_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy_id INTEGER NOT NULL,
                    strategy_config TEXT NOT NULL,  -- JSON
                    order_details TEXT DEFAULT '{}',  -- JSON
                    approval_status TEXT DEFAULT 'pending',
                    approved_at TIMESTAMP,
                    order_id TEXT,
                    position_key TEXT,
                    risk_metrics TEXT DEFAULT '{}',  -- JSON
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (workflow_id) REFERENCES workflow_instances (id),
                    FOREIGN KEY (strategy_id) REFERENCES strategies (id)
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_workflow_state ON workflow_instances(current_state)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_workflow_symbol ON workflow_instances(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_approved_status ON approved_trades(approval_status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_approved_symbol ON approved_trades(symbol)')
            
            conn.commit()
            conn.close()
            
            self.logger.info("✅ Workflow database initialized successfully")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize workflow database: {e}")
            raise
    
    def classify_strategy_type(self, strategy: StrategyConfig) -> str:
        """Classify strategy type based on legs configuration"""
        if not strategy.legs:
            return "unknown"
        
        leg_count = len(strategy.legs)
        
        if leg_count == 1:
            leg = strategy.legs[0]
            if leg.action == "sell" and leg.option_type == "put":
                return "cash_secured_put"
            elif leg.action == "sell" and leg.option_type == "call":
                return "naked_call"
            elif leg.action == "buy" and leg.option_type == "call":
                return "long_call"
            elif leg.action == "buy" and leg.option_type == "put":
                return "long_put"
        
        elif leg_count == 2:
            # Sort legs by action (sell first, then buy)
            sorted_legs = sorted(strategy.legs, key=lambda x: 0 if x.action == "sell" else 1)
            
            # Check for credit spreads
            if sorted_legs[0].action == "sell" and sorted_legs[1].action == "buy":
                if sorted_legs[0].option_type == sorted_legs[1].option_type:
                    if sorted_legs[0].option_type == "put":
                        return "put_credit_spread"
                    elif sorted_legs[0].option_type == "call":
                        return "call_credit_spread"
            
            # Check for debit spreads
            elif sorted_legs[0].action == "buy" and sorted_legs[1].action == "sell":
                if sorted_legs[0].option_type == sorted_legs[1].option_type:
                    if sorted_legs[0].option_type == "put":
                        return "put_debit_spread"
                    elif sorted_legs[0].option_type == "call":
                        return "call_debit_spread"
            
            # Check for straddles/strangles
            elif all(leg.action == sorted_legs[0].action for leg in sorted_legs):
                if sorted_legs[0].option_type != sorted_legs[1].option_type:
                    # Both ATM = straddle, otherwise strangle
                    if all(leg.selection_method == "atm" for leg in sorted_legs):
                        return "straddle"
                    else:
                        return "strangle"
        
        elif leg_count == 4:
            # Check for iron condor/butterfly
            put_legs = [leg for leg in strategy.legs if leg.option_type == "put"]
            call_legs = [leg for leg in strategy.legs if leg.option_type == "call"]
            
            if len(put_legs) == 2 and len(call_legs) == 2:
                # Check if we have one sell and one buy for each type
                put_sells = sum(1 for leg in put_legs if leg.action == "sell")
                put_buys = sum(1 for leg in put_legs if leg.action == "buy")
                call_sells = sum(1 for leg in call_legs if leg.action == "sell")
                call_buys = sum(1 for leg in call_legs if leg.action == "buy")
                
                if put_sells == 1 and put_buys == 1 and call_sells == 1 and call_buys == 1:
                    # Check if all legs are equidistant (butterfly) or not (condor)
                    # For now, assume iron condor (more common)
                    return "iron_condor"
        
        return "custom_strategy"
    
    def save_strategy(self, strategy: StrategyConfig) -> int:
        """Save strategy configuration"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Classify strategy type if not already set
            if not strategy.strategy_type:
                strategy.strategy_type = self.classify_strategy_type(strategy)
            
            # Convert complex objects to JSON
            legs_json = json.dumps([asdict(leg) for leg in strategy.legs])
            management_rules_json = json.dumps([asdict(rule) for rule in strategy.management_rules])
            delta_biases_json = json.dumps(strategy.delta_biases)
            
            if strategy.id:
                # Update existing strategy
                cursor.execute('''
                    UPDATE strategies SET
                        name = ?, description = ?, opening_action = ?, legs_config = ?, 
                        dte_range_min = ?, dte_range_max = ?,
                        profit_target_pct = ?, stop_loss_pct = ?, no_stop_loss = ?,
                        minimum_premium_required = ?, minimum_underlying_price = ?, closing_21_dte = ?,
                        delta_biases = ?, management_rules = ?, strategy_type = ?, is_active = ?
                    WHERE id = ?
                ''', (
                    strategy.name, strategy.description, strategy.opening_action, legs_json,
                    strategy.dte_range_min, strategy.dte_range_max,
                    strategy.profit_target_pct, strategy.stop_loss_pct, strategy.no_stop_loss,
                    strategy.minimum_premium_required, strategy.minimum_underlying_price, strategy.closing_21_dte,
                    delta_biases_json, management_rules_json, strategy.strategy_type, strategy.is_active,
                    strategy.id
                ))
                strategy_id = strategy.id
            else:
                # Insert new strategy
                cursor.execute('''
                    INSERT INTO strategies 
                    (name, description, opening_action, legs_config, dte_range_min, dte_range_max,
                     profit_target_pct, stop_loss_pct, no_stop_loss, minimum_premium_required, 
                     minimum_underlying_price, closing_21_dte, delta_biases, management_rules, 
                     strategy_type, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    strategy.name, strategy.description, strategy.opening_action, legs_json,
                    strategy.dte_range_min, strategy.dte_range_max,
                    strategy.profit_target_pct, strategy.stop_loss_pct, strategy.no_stop_loss,
                    strategy.minimum_premium_required, strategy.minimum_underlying_price, strategy.closing_21_dte,
                    delta_biases_json, management_rules_json, strategy.strategy_type, strategy.is_active
                ))
                strategy_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"✅ Saved strategy: {strategy.name} (ID: {strategy_id})")
            return strategy_id
            
        except Exception as e:
            self.logger.error(f"❌ Failed to save strategy: {e}")
            raise
    
    def get_strategy(self, strategy_id: int) -> Optional[StrategyConfig]:
        """Get strategy by ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, name, description, opening_action, legs_config, dte_range_min, dte_range_max,
                       profit_target_pct, stop_loss_pct, no_stop_loss, minimum_premium_required,
                       minimum_underlying_price, closing_21_dte, delta_biases, management_rules,
                       strategy_type, created_at, is_active
                FROM strategies WHERE id = ?
            ''', (strategy_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return None
            
            # Parse JSON fields
            legs_data = json.loads(row[4])
            legs = [StrategyLeg(**leg_data) for leg_data in legs_data]
            
            management_rules_data = json.loads(row[14])
            management_rules = [ManagementRule(**rule_data) for rule_data in management_rules_data]
            
            delta_biases = json.loads(row[13])
            
            return StrategyConfig(
                id=row[0],
                name=row[1],
                description=row[2],
                opening_action=row[3],
                legs=legs,
                dte_range_min=row[5],
                dte_range_max=row[6],
                profit_target_pct=row[7],
                stop_loss_pct=row[8],
                no_stop_loss=bool(row[9]) if row[9] is not None else True,
                minimum_premium_required=row[10] if row[10] is not None else 0.0,
                minimum_underlying_price=row[11] if row[11] is not None else 0.0,
                closing_21_dte=bool(row[12]) if row[12] is not None else False,
                delta_biases=delta_biases,
                management_rules=management_rules,
                strategy_type=row[15],
                created_at=datetime.fromisoformat(row[16]) if row[16] else None,
                is_active=bool(row[17])
            )
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get strategy {strategy_id}: {e}")
            return None
    
    def get_all_strategies(self, active_only: bool = True) -> List[StrategyConfig]:
        """Get all strategies"""
        try:
            self.logger.info(f"Getting strategies from {self.db_path}, active_only={active_only}")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query = '''
                SELECT id, name, description, opening_action, legs_config, dte_range_min, dte_range_max,
                       profit_target_pct, stop_loss_pct, no_stop_loss, minimum_premium_required,
                       minimum_underlying_price, closing_21_dte, delta_biases, management_rules,
                       strategy_type, created_at, is_active
                FROM strategies
            '''
            
            if active_only:
                query += ' WHERE is_active = 1'
            
            query += ' ORDER BY created_at DESC'
            
            cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()
            
            self.logger.info(f"Query returned {len(rows)} rows")
            strategies = []
            for row in rows:
                legs_data = json.loads(row[4])
                legs = [StrategyLeg(**leg_data) for leg_data in legs_data]
                
                management_rules_data = json.loads(row[14])
                management_rules = [ManagementRule(**rule_data) for rule_data in management_rules_data]
                
                delta_biases = json.loads(row[13])
                
                strategy = StrategyConfig(
                    id=row[0],
                    name=row[1],
                    description=row[2],
                    opening_action=row[3],
                    legs=legs,
                    dte_range_min=row[5],
                    dte_range_max=row[6],
                    profit_target_pct=row[7],
                    stop_loss_pct=row[8],
                    no_stop_loss=bool(row[9]) if row[9] is not None else True,
                    minimum_premium_required=row[10] if row[10] is not None else 0.0,
                    minimum_underlying_price=row[11] if row[11] is not None else 0.0,
                    closing_21_dte=bool(row[12]) if row[12] is not None else False,
                    delta_biases=delta_biases,
                    management_rules=management_rules,
                    strategy_type=row[15],
                    created_at=datetime.fromisoformat(row[16]) if row[16] else None,
                    is_active=bool(row[17])
                )
                strategies.append(strategy)
            
            self.logger.info(f"Successfully loaded {len(strategies)} strategies")
            return strategies
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get strategies: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def get_strategies_by_type(self, active_only: bool = True) -> Dict[str, List[StrategyConfig]]:
        """Get strategies grouped by strategy type"""
        try:
            strategies = self.get_all_strategies(active_only)
            
            # Group strategies by type
            strategies_by_type = defaultdict(list)
            for strategy in strategies:
                # Ensure strategy has a type
                if not strategy.strategy_type:
                    strategy.strategy_type = self.classify_strategy_type(strategy)
                
                strategies_by_type[strategy.strategy_type].append(strategy)
            
            return dict(strategies_by_type)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get strategies by type: {e}")
            return {}
    
    def delete_strategy(self, strategy_id: int) -> bool:
        """Delete strategy by ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if strategy exists
            cursor.execute("SELECT name FROM strategies WHERE id = ?", (strategy_id,))
            result = cursor.fetchone()
            
            if not result:
                conn.close()
                self.logger.warning(f"⚠️ Strategy {strategy_id} not found for deletion")
                return False
            
            strategy_name = result[0]
            
            # Delete the strategy
            cursor.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
            
            if cursor.rowcount > 0:
                conn.commit()
                conn.close()
                self.logger.info(f"✅ Deleted strategy: {strategy_name} (ID: {strategy_id})")
                return True
            else:
                conn.close()
                self.logger.error(f"❌ Failed to delete strategy {strategy_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Failed to delete strategy {strategy_id}: {e}")
            return False
    
    def create_workflow_instance(self, workflow_id: str, symbol: str, strategy_id: int,
                                initial_state: WorkflowState = WorkflowState.SCANNING,
                                state_data: Dict[str, Any] = None) -> bool:
        """Create new workflow instance"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if state_data is None:
                state_data = {}
            
            cursor.execute('''
                INSERT INTO workflow_instances 
                (id, symbol, strategy_id, current_state, state_data)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                workflow_id, symbol, strategy_id, initial_state.value,
                json.dumps(state_data)
            ))
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"✅ Created workflow instance: {workflow_id} for {symbol}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create workflow instance: {e}")
            return False
    
    def update_workflow_state(self, workflow_id: str, new_state: WorkflowState,
                             state_data: Dict[str, Any] = None, 
                             error_message: str = None) -> bool:
        """Update workflow state"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if state_data is None:
                state_data = {}
            
            cursor.execute('''
                UPDATE workflow_instances SET
                    current_state = ?, state_data = ?, updated_at = CURRENT_TIMESTAMP,
                    error_message = ?
                WHERE id = ?
            ''', (
                new_state.value, json.dumps(state_data), error_message, workflow_id
            ))
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"✅ Updated workflow {workflow_id} to state: {new_state.value}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to update workflow state: {e}")
            return False
    
    def get_workflows_by_state(self, state: WorkflowState) -> List[WorkflowInstance]:
        """Get all workflows in a specific state"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, symbol, strategy_id, current_state, state_data,
                       created_at, updated_at, error_message
                FROM workflow_instances 
                WHERE current_state = ?
                ORDER BY updated_at ASC
            ''', (state.value,))
            
            rows = cursor.fetchall()
            conn.close()
            
            workflows = []
            for row in rows:
                workflow = WorkflowInstance(
                    id=row[0],
                    symbol=row[1],
                    strategy_id=row[2],
                    current_state=WorkflowState(row[3]),
                    state_data=json.loads(row[4]),
                    created_at=datetime.fromisoformat(row[5]),
                    updated_at=datetime.fromisoformat(row[6]),
                    error_message=row[7]
                )
                workflows.append(workflow)
            
            return workflows
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get workflows by state: {e}")
            return []
    
    def save_approved_trade(self, trade: ApprovedTrade) -> int:
        """Save approved trade"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO approved_trades 
                (workflow_id, symbol, strategy_id, strategy_config, order_details,
                 approval_status, approved_at, order_id, position_key, risk_metrics)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.workflow_id, trade.symbol, trade.strategy_id,
                json.dumps(trade.strategy_config), json.dumps(trade.order_details),
                trade.approval_status, trade.approved_at, trade.order_id,
                trade.position_key, json.dumps(trade.risk_metrics)
            ))
            
            trade_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            self.logger.info(f"✅ Saved approved trade: {trade_id} for {trade.symbol}")
            return trade_id
            
        except Exception as e:
            self.logger.error(f"❌ Failed to save approved trade: {e}")
            raise
    
    def get_pending_trades(self) -> List[ApprovedTrade]:
        """Get all pending trades awaiting approval"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, workflow_id, symbol, strategy_id, strategy_config,
                       order_details, approval_status, approved_at, order_id,
                       position_key, risk_metrics, created_at
                FROM approved_trades 
                WHERE approval_status = 'pending'
                ORDER BY created_at ASC
            ''')
            
            rows = cursor.fetchall()
            conn.close()
            
            trades = []
            for row in rows:
                trade = ApprovedTrade(
                    id=row[0],
                    workflow_id=row[1],
                    symbol=row[2],
                    strategy_id=row[3],
                    strategy_config=json.loads(row[4]),
                    order_details=json.loads(row[5]),
                    approval_status=row[6],
                    approved_at=datetime.fromisoformat(row[7]) if row[7] else None,
                    order_id=row[8],
                    position_key=row[9],
                    risk_metrics=json.loads(row[10])
                )
                trades.append(trade)
            
            return trades
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get pending trades: {e}")
            return []