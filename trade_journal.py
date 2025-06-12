#!/usr/bin/env python3
"""
TastyTracker Trade Journal
Automated trade logging and analysis system with comprehensive trade data capture
"""

import os
import logging
import sqlite3
import json
import math
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict
from enum import Enum
import requests
from scipy.stats import norm

# Tastytrade imports
from tastytrade import Session

class TradeStatus(Enum):
    """Trade lifecycle status"""
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"
    ROLLED = "rolled"
    ASSIGNED = "assigned"
    EXPIRED = "expired"

class StrategyType(Enum):
    """Options strategy types"""
    PUT_CREDIT_SPREAD = "put_credit_spread"
    CALL_CREDIT_SPREAD = "call_credit_spread"
    IRON_CONDOR = "iron_condor"
    IRON_BUTTERFLY = "iron_butterfly"
    NAKED_PUT = "naked_put"
    COVERED_CALL = "covered_call"
    STRADDLE = "straddle"
    STRANGLE = "strangle"
    STOCK = "stock"
    OTHER = "other"

@dataclass
class TradeEntry:
    """Complete trade entry record with all journal data points"""
    # Trade ID & Context
    trade_id: str
    account_number: str
    underlying_symbol: str
    strategy_type: str
    sector: Optional[str] = None
    trade_tag: Optional[str] = None
    
    # Entry Timing
    entry_date: datetime = None
    entry_local_time: str = ""
    expiration_date: Optional[date] = None
    dte_at_entry: Optional[int] = None
    
    # Entry Market Context
    underlying_price_entry: float = 0.0
    spx_price_entry: Optional[float] = None
    vix_level_entry: Optional[float] = None
    ten_year_yield_entry: Optional[float] = None
    iv_rank_entry: Optional[float] = None
    iv_5day_change_entry: Optional[float] = None
    
    # Position Details
    contracts: int = 0
    strike_short: Optional[float] = None
    strike_long: Optional[float] = None
    strike_width: Optional[float] = None
    
    # Entry Financial Data
    entry_credit: float = 0.0  # Total credit received (positive for credit spreads)
    entry_debit: float = 0.0   # Total debit paid (positive for debit spreads)
    max_profit: float = 0.0
    max_loss: float = 0.0
    buying_power_reduction: float = 0.0
    break_even_price: Optional[float] = None
    
    # Entry Greeks
    delta_entry: float = 0.0
    theta_entry: float = 0.0
    gamma_entry: float = 0.0
    vega_entry: float = 0.0
    
    # Probability Metrics (calculated)
    pop_entry: Optional[float] = None  # Probability of Profit
    p50_entry: Optional[float] = None  # Probability of 50% max profit
    pot_entry: Optional[float] = None  # Probability of touching short strike
    
    # Entry Plan & Rules
    target_profit_pct: Optional[float] = None
    target_dte_exit: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    directional_assumption: str = ""
    iv_assumption: str = ""  # contraction/expansion
    entry_rationale: str = ""
    
    # Management & Exit
    status: TradeStatus = TradeStatus.OPEN
    exit_date: Optional[datetime] = None
    exit_local_time: str = ""
    dte_at_exit: Optional[int] = None
    
    # Exit Market Context
    underlying_price_exit: Optional[float] = None
    
    # Exit Financial Data
    exit_credit: float = 0.0  # Credit received on close
    exit_debit: float = 0.0   # Debit paid on close
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    pct_max_profit_captured: Optional[float] = None
    pct_max_loss_captured: Optional[float] = None
    return_on_capital: Optional[float] = None
    
    # Commissions & Fees
    total_commissions: float = 0.0
    total_fees: float = 0.0
    net_pnl_after_fees: float = 0.0
    
    # Trade Management
    managed_at_50pct: bool = False
    followed_exit_rules: bool = True
    adjustment_count: int = 0
    adjustment_log: str = ""
    
    # Performance Analysis
    days_held: Optional[int] = None
    winner: bool = False
    outcome_tag: str = ""  # Winner, Loser, Breakeven, Early Exit, Assignment
    slippage_cost: float = 0.0
    
    # Notes & Review
    trade_notes: str = ""
    what_went_well: str = ""
    what_to_improve: str = ""
    rule_compliance_score: Optional[float] = None
    next_action: str = ""
    
    # Internal tracking
    created_at: datetime = None
    updated_at: datetime = None
    transaction_ids: List[str] = None  # List of TastyTrade transaction IDs
    
    def __post_init__(self):
        """Initialize default values and derived fields"""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
        if self.transaction_ids is None:
            self.transaction_ids = []
        if self.entry_date is None:
            self.entry_date = datetime.now()

@dataclass
class MarketSnapshot:
    """Market context snapshot for trade entries"""
    timestamp: datetime
    spx_price: float
    vix_level: float
    ten_year_yield: float
    dollar_index: Optional[float] = None
    market_regime: str = ""  # "low_vol", "high_vol", "trending", "choppy"

class BlackScholesCalculator:
    """Black-Scholes option pricing and probability calculations"""
    
    @staticmethod
    def calculate_pop(spot_price: float, strike_price: float, time_to_expiry: float, 
                     risk_free_rate: float, volatility: float, option_type: str = 'put') -> float:
        """Calculate Probability of Profit for an option position"""
        try:
            if time_to_expiry <= 0 or volatility <= 0:
                return 0.0
            
            d2 = (math.log(spot_price / strike_price) + 
                  (risk_free_rate - 0.5 * volatility**2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
            
            if option_type.lower() == 'put':
                # For put, profit if price < strike
                pop = norm.cdf(-d2)
            else:
                # For call, profit if price > strike  
                pop = norm.cdf(d2)
            
            return round(pop * 100, 2)
        except Exception as e:
            logging.error(f"Error calculating POP: {e}")
            return 0.0
    
    @staticmethod
    def calculate_prob_touch(spot_price: float, strike_price: float, time_to_expiry: float,
                           volatility: float) -> float:
        """Calculate probability of touching strike price before expiration"""
        try:
            if time_to_expiry <= 0 or volatility <= 0:
                return 0.0
            
            # Probability of touching barrier
            barrier_ratio = strike_price / spot_price
            vol_sqrt_t = volatility * math.sqrt(time_to_expiry)
            
            prob_touch = 2 * norm.cdf(abs(math.log(barrier_ratio)) / vol_sqrt_t)
            
            return round(prob_touch * 100, 2)
        except Exception as e:
            logging.error(f"Error calculating probability of touch: {e}")
            return 0.0
    
    @staticmethod
    def calculate_p50(spot_price: float, strike_price: float, time_to_expiry: float,
                     risk_free_rate: float, volatility: float, credit_received: float) -> float:
        """Calculate probability of achieving 50% of max profit"""
        try:
            if time_to_expiry <= 0 or volatility <= 0 or credit_received <= 0:
                return 0.0
            
            # For credit spread, 50% profit = keeping 50% of credit
            target_price = strike_price + (credit_received * 0.5)  # Adjust based on strategy
            
            d2 = (math.log(spot_price / target_price) + 
                  (risk_free_rate - 0.5 * volatility**2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
            
            p50 = norm.cdf(-d2)  # Probability price stays below target
            
            return round(p50 * 100, 2)
        except Exception as e:
            logging.error(f"Error calculating P50: {e}")
            return 0.0

class TradeJournal:
    """Main trade journal system for automated trade logging and analysis"""
    
    def __init__(self, tasty_client: Session, db_path: str = "trade_journal.db"):
        self.tasty_client = tasty_client
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://api.tastyworks.com"
        
        # Initialize database
        self._init_database()
        
        # Cache for performance
        self.market_data_cache = {}
        self.cache_duration = 300  # 5 minutes
        
        # Risk-free rate assumption (for Black-Scholes)
        self.risk_free_rate = 0.05  # 5% - should be updated from actual rates
        
        # Market data symbols for context
        self.market_symbols = {
            'SPX': '$SPX.X',
            'VIX': '$VIX.X', 
            'TNX': '$TNX.X'  # 10-year treasury
        }
    
    def _init_database(self):
        """Initialize SQLite database with trade journal schema"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create main trades table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trades (
                        trade_id TEXT PRIMARY KEY,
                        account_number TEXT NOT NULL,
                        underlying_symbol TEXT NOT NULL,
                        strategy_type TEXT NOT NULL,
                        sector TEXT,
                        trade_tag TEXT,
                        
                        -- Entry timing
                        entry_date TEXT,
                        entry_local_time TEXT,
                        expiration_date TEXT,
                        dte_at_entry INTEGER,
                        
                        -- Entry market context
                        underlying_price_entry REAL,
                        spx_price_entry REAL,
                        vix_level_entry REAL,
                        ten_year_yield_entry REAL,
                        iv_rank_entry REAL,
                        iv_5day_change_entry REAL,
                        
                        -- Position details
                        contracts INTEGER,
                        strike_short REAL,
                        strike_long REAL,  
                        strike_width REAL,
                        
                        -- Entry financial
                        entry_credit REAL,
                        entry_debit REAL,
                        max_profit REAL,
                        max_loss REAL,
                        buying_power_reduction REAL,
                        break_even_price REAL,
                        
                        -- Entry Greeks
                        delta_entry REAL,
                        theta_entry REAL,
                        gamma_entry REAL,
                        vega_entry REAL,
                        
                        -- Probability metrics
                        pop_entry REAL,
                        p50_entry REAL,
                        pot_entry REAL,
                        
                        -- Entry plan
                        target_profit_pct REAL,
                        target_dte_exit INTEGER,
                        stop_loss_pct REAL,
                        directional_assumption TEXT,
                        iv_assumption TEXT,
                        entry_rationale TEXT,
                        
                        -- Exit data
                        status TEXT DEFAULT 'open',
                        exit_date TEXT,
                        exit_local_time TEXT,
                        dte_at_exit INTEGER,
                        underlying_price_exit REAL,
                        exit_credit REAL,
                        exit_debit REAL,
                        realized_pnl REAL,
                        realized_pnl_pct REAL,
                        pct_max_profit_captured REAL,
                        pct_max_loss_captured REAL,
                        return_on_capital REAL,
                        
                        -- Costs
                        total_commissions REAL,
                        total_fees REAL,
                        net_pnl_after_fees REAL,
                        
                        -- Management
                        managed_at_50pct BOOLEAN DEFAULT FALSE,
                        followed_exit_rules BOOLEAN DEFAULT TRUE,
                        adjustment_count INTEGER DEFAULT 0,
                        adjustment_log TEXT,
                        
                        -- Performance
                        days_held INTEGER,
                        winner BOOLEAN,
                        outcome_tag TEXT,
                        slippage_cost REAL,
                        
                        -- Notes
                        trade_notes TEXT,
                        what_went_well TEXT,
                        what_to_improve TEXT,
                        rule_compliance_score REAL,
                        next_action TEXT,
                        
                        -- Tracking
                        created_at TEXT,
                        updated_at TEXT,
                        transaction_ids TEXT,  -- JSON array of transaction IDs
                        
                        UNIQUE(trade_id)
                    )
                ''')
                
                # Create market snapshots table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS market_snapshots (
                        id INTEGER PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        spx_price REAL,
                        vix_level REAL,
                        ten_year_yield REAL,
                        dollar_index REAL,
                        market_regime TEXT,
                        UNIQUE(timestamp)
                    )
                ''')
                
                # Create transaction tracking table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS transaction_log (
                        transaction_id TEXT PRIMARY KEY,
                        trade_id TEXT,
                        account_number TEXT,
                        symbol TEXT,
                        action TEXT,
                        quantity INTEGER,
                        price REAL,
                        executed_at TEXT,
                        commission REAL,
                        fees REAL,
                        processed BOOLEAN DEFAULT FALSE,
                        FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
                    )
                ''')
                
                # Create indexes for performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(underlying_symbol)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(entry_date)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_number)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
                
                conn.commit()
                self.logger.info("✅ Trade journal database initialized")
                
        except Exception as e:
            self.logger.error(f"❌ Error initializing database: {e}")
            raise
    
    def fetch_account_transactions(self, account_number: str, start_date: Optional[datetime] = None, 
                                 end_date: Optional[datetime] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch transaction history from TastyTrade API"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            params = {
                'per-page': limit,
                'sort': 'Desc'
            }
            
            # Add date filters if provided
            if start_date:
                params['start-date'] = start_date.strftime('%Y-%m-%d')
            if end_date:
                params['end-date'] = end_date.strftime('%Y-%m-%d')
            
            self.logger.info(f"🔍 Fetching transactions for account {account_number}")
            
            response = requests.get(
                f"{self.base_url}/accounts/{account_number}/transactions",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                transactions = data.get('data', [])
                
                self.logger.info(f"✅ Retrieved {len(transactions)} transactions")
                return transactions
            else:
                error_msg = f"Failed to fetch transactions: HTTP {response.status_code}"
                self.logger.error(f"❌ {error_msg}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching transactions: {e}")
            return []
    
    def save_trade(self, trade: TradeEntry) -> bool:
        """Save or update a trade entry in the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Convert trade to dictionary for database insertion  
                trade_dict = asdict(trade)
                
                # Handle special fields
                trade_dict['transaction_ids'] = json.dumps(trade.transaction_ids)
                trade_dict['entry_date'] = trade.entry_date.isoformat() if trade.entry_date else None
                trade_dict['exit_date'] = trade.exit_date.isoformat() if trade.exit_date else None
                trade_dict['expiration_date'] = trade.expiration_date.isoformat() if trade.expiration_date else None
                trade_dict['created_at'] = trade.created_at.isoformat() if trade.created_at else None
                trade_dict['updated_at'] = datetime.now().isoformat()
                trade_dict['status'] = trade.status.value if isinstance(trade.status, TradeStatus) else trade.status
                
                # Upsert trade
                columns = ', '.join(trade_dict.keys())
                placeholders = ', '.join([f':{key}' for key in trade_dict.keys()])
                
                cursor.execute(f'''
                    INSERT OR REPLACE INTO trades ({columns})
                    VALUES ({placeholders})
                ''', trade_dict)
                
                conn.commit()
                self.logger.info(f"✅ Saved trade {trade.trade_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ Error saving trade {trade.trade_id}: {e}")
            return False
    
    def get_market_snapshot(self) -> MarketSnapshot:
        """Capture current market context for trade entry"""
        try:
            # This would fetch current SPX, VIX, TNX data
            # For now, return placeholder - will implement in next phase
            return MarketSnapshot(
                timestamp=datetime.now(),
                spx_price=4500.0,  # Placeholder
                vix_level=18.0,    # Placeholder 
                ten_year_yield=4.5, # Placeholder
                market_regime="low_vol"
            )
        except Exception as e:
            self.logger.error(f"❌ Error capturing market snapshot: {e}")
            return None
    
    def calculate_probabilities(self, trade: TradeEntry) -> Tuple[float, float, float]:
        """Calculate POP, P50, and POT for a trade"""
        try:
            if not all([trade.underlying_price_entry, trade.strike_short, 
                       trade.dte_at_entry, trade.iv_rank_entry]):
                return 0.0, 0.0, 0.0
            
            # Convert DTE to years
            time_to_expiry = trade.dte_at_entry / 365.0
            
            # Use IV rank as volatility proxy (needs refinement)
            volatility = (trade.iv_rank_entry or 20.0) / 100.0
            
            calc = BlackScholesCalculator()
            
            # Calculate POP (assuming put credit spread)
            pop = calc.calculate_pop(
                spot_price=trade.underlying_price_entry,
                strike_price=trade.strike_short,
                time_to_expiry=time_to_expiry,
                risk_free_rate=self.risk_free_rate,
                volatility=volatility,
                option_type='put'
            )
            
            # Calculate P50
            p50 = calc.calculate_p50(
                spot_price=trade.underlying_price_entry,
                strike_price=trade.strike_short,
                time_to_expiry=time_to_expiry,
                risk_free_rate=self.risk_free_rate,
                volatility=volatility,
                credit_received=trade.entry_credit
            )
            
            # Calculate POT
            pot = calc.calculate_prob_touch(
                spot_price=trade.underlying_price_entry,
                strike_price=trade.strike_short,
                time_to_expiry=time_to_expiry,
                volatility=volatility
            )
            
            return pop, p50, pot
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating probabilities: {e}")
            return 0.0, 0.0, 0.0
    
    def get_trades(self, account_number: Optional[str] = None, 
                  symbol: Optional[str] = None, status: Optional[str] = None,
                  limit: int = 100) -> List[TradeEntry]:
        """Retrieve trades from database with optional filters"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                query = "SELECT * FROM trades WHERE 1=1"
                params = []
                
                if account_number:
                    query += " AND account_number = ?"
                    params.append(account_number)
                
                if symbol:
                    query += " AND underlying_symbol = ?"
                    params.append(symbol)
                
                if status:
                    query += " AND status = ?"
                    params.append(status)
                
                query += " ORDER BY entry_date DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                trades = []
                for row in rows:
                    # Convert row to TradeEntry object
                    trade_dict = dict(row)
                    
                    # Handle special field conversions
                    if trade_dict['transaction_ids']:
                        trade_dict['transaction_ids'] = json.loads(trade_dict['transaction_ids'])
                    
                    # Convert string dates back to datetime objects
                    for date_field in ['entry_date', 'exit_date', 'created_at', 'updated_at']:
                        if trade_dict[date_field]:
                            trade_dict[date_field] = datetime.fromisoformat(trade_dict[date_field])
                    
                    if trade_dict['expiration_date']:
                        trade_dict['expiration_date'] = date.fromisoformat(trade_dict['expiration_date'])
                    
                    trade_dict['status'] = TradeStatus(trade_dict['status'])
                    
                    # Remove None values that would cause dataclass issues
                    trade_dict = {k: v for k, v in trade_dict.items() if v is not None or k in TradeEntry.__dataclass_fields__}
                    
                    trades.append(TradeEntry(**trade_dict))
                
                return trades
                
        except Exception as e:
            self.logger.error(f"❌ Error retrieving trades: {e}")
            return []
    
    def generate_trade_id(self, account_number: str, symbol: str, entry_date: datetime) -> str:
        """Generate unique trade ID"""
        date_str = entry_date.strftime('%Y%m%d_%H%M%S')
        return f"{account_number}_{symbol}_{date_str}"
    
    def get_trade_summary(self, account_number: Optional[str] = None) -> Dict[str, Any]:
        """Generate trade performance summary"""
        try:
            trades = self.get_trades(account_number=account_number, limit=1000)
            
            if not trades:
                return {'error': 'No trades found'}
            
            closed_trades = [t for t in trades if t.status == TradeStatus.CLOSED]
            winners = [t for t in closed_trades if t.winner]
            
            summary = {
                'total_trades': len(trades),
                'open_trades': len([t for t in trades if t.status == TradeStatus.OPEN]),
                'closed_trades': len(closed_trades),
                'win_rate': (len(winners) / len(closed_trades) * 100) if closed_trades else 0,
                'total_pnl': sum(t.realized_pnl for t in closed_trades),
                'total_commissions': sum(t.total_commissions for t in closed_trades),
                'avg_days_held': sum(t.days_held for t in closed_trades if t.days_held) / len(closed_trades) if closed_trades else 0,
                'strategies': {}
            }
            
            # Strategy breakdown
            for trade in closed_trades:
                if trade.strategy_type not in summary['strategies']:
                    summary['strategies'][trade.strategy_type] = {
                        'count': 0, 'winners': 0, 'total_pnl': 0
                    }
                
                strat = summary['strategies'][trade.strategy_type]
                strat['count'] += 1
                if trade.winner:
                    strat['winners'] += 1
                strat['total_pnl'] += trade.realized_pnl
                strat['win_rate'] = (strat['winners'] / strat['count']) * 100
            
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ Error generating trade summary: {e}")
            return {'error': str(e)}