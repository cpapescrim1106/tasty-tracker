#!/usr/bin/env python3
"""
TastyTracker Transaction Processor
Converts TastyTrade API transactions into structured trade journal entries
"""

import logging
import json
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict
import re

from trade_journal import TradeEntry, TradeStatus, StrategyType, TradeJournal
from tastytrade import Session

@dataclass
class TransactionLeg:
    """Individual transaction leg for multi-leg strategies"""
    transaction_id: str
    symbol: str
    underlying_symbol: str
    action: str  # BUY_TO_OPEN, SELL_TO_CLOSE, etc.
    quantity: int
    price: float
    executed_at: datetime
    commission: float
    fees: float
    option_type: Optional[str] = None  # CALL or PUT
    strike_price: Optional[float] = None
    expiration_date: Optional[date] = None

@dataclass
class GroupedTrade:
    """Grouped transaction legs forming a complete trade"""
    trade_key: str
    underlying_symbol: str
    strategy_type: str
    opening_legs: List[TransactionLeg]
    closing_legs: List[TransactionLeg]
    entry_date: datetime
    exit_date: Optional[datetime] = None
    is_complete: bool = False

class TransactionProcessor:
    """Processes TastyTrade transactions into trade journal entries"""
    
    def __init__(self, journal: TradeJournal):
        self.journal = journal
        self.logger = logging.getLogger(__name__)
        
        # Strategy detection patterns
        self.strategy_patterns = {
            'put_credit_spread': {
                'legs': 2,
                'actions': ['SELL_TO_OPEN', 'BUY_TO_OPEN'],
                'option_types': ['PUT', 'PUT']
            },
            'call_credit_spread': {
                'legs': 2, 
                'actions': ['SELL_TO_OPEN', 'BUY_TO_OPEN'],
                'option_types': ['CALL', 'CALL']
            },
            'iron_condor': {
                'legs': 4,
                'actions': ['SELL_TO_OPEN', 'BUY_TO_OPEN', 'SELL_TO_OPEN', 'BUY_TO_OPEN'],
                'option_types': ['PUT', 'PUT', 'CALL', 'CALL']
            },
            'naked_put': {
                'legs': 1,
                'actions': ['SELL_TO_OPEN'],
                'option_types': ['PUT']
            },
            'covered_call': {
                'legs': 2,
                'actions': ['SELL_TO_OPEN', 'BUY_TO_OPEN'],  # CC = short call + long stock
                'mixed': True  # Mix of stock and options
            }
        }
    
    def parse_option_symbol(self, symbol: str) -> Dict[str, Any]:
        """Parse TastyTrade option symbol to extract components"""
        try:
            # TastyTrade option format: AAPL  241220P00150000
            # Pattern: TICKER + SPACE + YYMMDD + C/P + STRIKE (8 digits)
            
            if ' ' not in symbol:
                # Not an option symbol
                return {
                    'underlying': symbol,
                    'is_option': False
                }
            
            parts = symbol.strip().split()
            if len(parts) != 2:
                return {'underlying': symbol, 'is_option': False}
            
            underlying = parts[0]
            option_part = parts[1]
            
            if len(option_part) < 15:  # Minimum length for option symbol
                return {'underlying': symbol, 'is_option': False}
            
            # Extract date (YYMMDD)
            date_str = option_part[:6]
            exp_year = 2000 + int(date_str[:2])
            exp_month = int(date_str[2:4])
            exp_day = int(date_str[4:6])
            expiration_date = date(exp_year, exp_month, exp_day)
            
            # Extract option type (C or P)
            option_type = option_part[6]
            if option_type not in ['C', 'P']:
                return {'underlying': symbol, 'is_option': False}
            
            # Extract strike price (last 8 digits, divide by 1000)
            strike_str = option_part[7:]
            if len(strike_str) != 8 or not strike_str.isdigit():
                return {'underlying': symbol, 'is_option': False}
            
            strike_price = int(strike_str) / 1000.0
            
            return {
                'underlying': underlying,
                'is_option': True,
                'option_type': 'CALL' if option_type == 'C' else 'PUT',
                'strike_price': strike_price,
                'expiration_date': expiration_date
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error parsing option symbol {symbol}: {e}")
            return {'underlying': symbol, 'is_option': False}
    
    def parse_transaction(self, transaction: Dict[str, Any]) -> Optional[TransactionLeg]:
        """Parse a single TastyTrade transaction into a TransactionLeg"""
        try:
            # Extract basic transaction data
            transaction_id = str(transaction.get('id', ''))
            symbol = transaction.get('symbol', '')
            action = transaction.get('action', '')
            quantity = transaction.get('quantity', 0)
            price = transaction.get('price', 0.0)
            commission = transaction.get('commission', 0.0)
            fees = transaction.get('regulatory-fees', 0.0) + transaction.get('clearing-fees', 0.0)
            
            # Parse execution timestamp
            executed_at_str = transaction.get('executed-at', '')
            if executed_at_str:
                executed_at = datetime.fromisoformat(executed_at_str.replace('Z', '+00:00'))
            else:
                executed_at = datetime.now()
            
            # Parse option symbol
            symbol_info = self.parse_option_symbol(symbol)
            underlying_symbol = symbol_info['underlying']
            
            leg = TransactionLeg(
                transaction_id=transaction_id,
                symbol=symbol,
                underlying_symbol=underlying_symbol,
                action=action,
                quantity=abs(quantity),  # Ensure positive
                price=abs(price),
                executed_at=executed_at,
                commission=abs(commission),
                fees=abs(fees)
            )
            
            # Add option-specific data if applicable
            if symbol_info['is_option']:
                leg.option_type = symbol_info['option_type']
                leg.strike_price = symbol_info['strike_price']
                leg.expiration_date = symbol_info['expiration_date']
            
            return leg
            
        except Exception as e:
            self.logger.error(f"❌ Error parsing transaction: {e}")
            return None
    
    def group_transactions_into_trades(self, transactions: List[Dict[str, Any]]) -> List[GroupedTrade]:
        """Group related transactions into complete trades"""
        try:
            # Parse all transactions into legs
            legs = []
            for transaction in transactions:
                leg = self.parse_transaction(transaction)
                if leg and leg.underlying_symbol:  # Only process valid legs with underlying
                    legs.append(leg)
            
            if not legs:
                return []
            
            # Group by underlying symbol and expiration date
            grouped_by_underlying = defaultdict(list)
            for leg in legs:
                # Create grouping key: underlying + expiration (if option)
                if leg.expiration_date:
                    key = f"{leg.underlying_symbol}_{leg.expiration_date.isoformat()}"
                else:
                    key = leg.underlying_symbol
                grouped_by_underlying[key].append(leg)
            
            trades = []
            for group_key, group_legs in grouped_by_underlying.items():
                # Sort legs by execution time
                group_legs.sort(key=lambda x: x.executed_at)
                
                # Separate opening and closing legs
                opening_legs = []
                closing_legs = []
                
                for leg in group_legs:
                    if 'OPEN' in leg.action:
                        opening_legs.append(leg)
                    elif 'CLOSE' in leg.action:
                        closing_legs.append(leg)
                
                if opening_legs:  # Must have at least opening legs
                    # Determine strategy type
                    strategy_type = self._detect_strategy_type(opening_legs)
                    
                    # Find earliest entry date
                    entry_date = min(leg.executed_at for leg in opening_legs)
                    
                    # Find latest exit date (if any closing legs)
                    exit_date = max(leg.executed_at for leg in closing_legs) if closing_legs else None
                    
                    trade = GroupedTrade(
                        trade_key=group_key,
                        underlying_symbol=opening_legs[0].underlying_symbol,
                        strategy_type=strategy_type,
                        opening_legs=opening_legs,
                        closing_legs=closing_legs,
                        entry_date=entry_date,
                        exit_date=exit_date,
                        is_complete=len(closing_legs) >= len(opening_legs)
                    )
                    
                    trades.append(trade)
            
            self.logger.info(f"✅ Grouped {len(transactions)} transactions into {len(trades)} trades")
            return trades
            
        except Exception as e:
            self.logger.error(f"❌ Error grouping transactions: {e}")
            return []
    
    def _detect_strategy_type(self, opening_legs: List[TransactionLeg]) -> str:
        """Detect the options strategy type from opening legs"""
        try:
            if len(opening_legs) == 1:
                leg = opening_legs[0]
                if leg.option_type == 'PUT' and leg.action == 'SELL_TO_OPEN':
                    return 'naked_put'
                elif leg.option_type == 'CALL' and leg.action == 'SELL_TO_OPEN':
                    return 'naked_call'
                elif not leg.option_type:  # Stock
                    return 'stock'
                else:
                    return 'single_option'
            
            elif len(opening_legs) == 2:
                # Sort by strike price for spreads
                option_legs = [leg for leg in opening_legs if leg.option_type]
                if len(option_legs) == 2:
                    option_legs.sort(key=lambda x: x.strike_price or 0)
                    
                    # Check for credit spreads
                    if (option_legs[0].action == 'SELL_TO_OPEN' and 
                        option_legs[1].action == 'BUY_TO_OPEN'):
                        
                        if all(leg.option_type == 'PUT' for leg in option_legs):
                            return 'put_credit_spread'
                        elif all(leg.option_type == 'CALL' for leg in option_legs):
                            return 'call_credit_spread'
                    
                    # Check for debit spreads
                    elif (option_legs[0].action == 'BUY_TO_OPEN' and 
                          option_legs[1].action == 'SELL_TO_OPEN'):
                        
                        if all(leg.option_type == 'PUT' for leg in option_legs):
                            return 'put_debit_spread'
                        elif all(leg.option_type == 'CALL' for leg in option_legs):
                            return 'call_debit_spread'
                
                return 'two_leg_strategy'
            
            elif len(opening_legs) == 4:
                # Likely iron condor or iron butterfly
                put_legs = [leg for leg in opening_legs if leg.option_type == 'PUT']
                call_legs = [leg for leg in opening_legs if leg.option_type == 'CALL']
                
                if len(put_legs) == 2 and len(call_legs) == 2:
                    return 'iron_condor'
                else:
                    return 'four_leg_strategy'
            
            else:
                return 'complex_strategy'
                
        except Exception as e:
            self.logger.error(f"❌ Error detecting strategy type: {e}")
            return 'unknown'
    
    def convert_to_journal_entry(self, grouped_trade: GroupedTrade) -> TradeEntry:
        """Convert a GroupedTrade into a TradeEntry for the journal"""
        try:
            # Generate trade ID
            trade_id = self.journal.generate_trade_id(
                account_number="default",  # TODO: Extract from transaction
                symbol=grouped_trade.underlying_symbol,
                entry_date=grouped_trade.entry_date
            )
            
            # Calculate position details
            contracts = sum(leg.quantity for leg in grouped_trade.opening_legs)
            
            # Calculate strikes for spreads
            strike_short = None
            strike_long = None
            strike_width = None
            
            option_legs = [leg for leg in grouped_trade.opening_legs if leg.option_type]
            if option_legs:
                strikes = sorted([leg.strike_price for leg in option_legs if leg.strike_price])
                if len(strikes) >= 2:
                    strike_short = strikes[0] if 'SELL_TO_OPEN' in [leg.action for leg in option_legs if leg.strike_price == strikes[0]] else strikes[1]
                    strike_long = strikes[1] if strike_short == strikes[0] else strikes[0]
                    strike_width = abs(strikes[1] - strikes[0])
                elif len(strikes) == 1:
                    # Single option
                    strike_short = strikes[0]
            
            # Calculate financial metrics
            entry_credit = 0.0
            entry_debit = 0.0
            total_commissions = 0.0
            total_fees = 0.0
            
            for leg in grouped_trade.opening_legs:
                total_commissions += leg.commission
                total_fees += leg.fees
                
                if leg.action == 'SELL_TO_OPEN':
                    entry_credit += leg.price * leg.quantity
                elif leg.action == 'BUY_TO_OPEN':
                    entry_debit += leg.price * leg.quantity
            
            # Net premium (positive for credit, negative for debit)
            net_premium = entry_credit - entry_debit
            
            # Calculate max profit/loss for spreads
            max_profit = 0.0
            max_loss = 0.0
            
            if grouped_trade.strategy_type in ['put_credit_spread', 'call_credit_spread']:
                max_profit = net_premium
                max_loss = (strike_width * 100 * contracts) - net_premium if strike_width else 0
            elif grouped_trade.strategy_type == 'naked_put':
                max_profit = net_premium
                max_loss = (strike_short * 100 * contracts) - net_premium if strike_short else 0
            
            # Calculate exit data if trade is closed
            exit_credit = 0.0
            exit_debit = 0.0
            realized_pnl = 0.0
            
            if grouped_trade.closing_legs:
                for leg in grouped_trade.closing_legs:
                    total_commissions += leg.commission
                    total_fees += leg.fees
                    
                    if leg.action == 'SELL_TO_CLOSE':
                        exit_credit += leg.price * leg.quantity
                    elif leg.action == 'BUY_TO_CLOSE':
                        exit_debit += leg.price * leg.quantity
                
                # For credit spreads: PnL = Entry Credit - Exit Cost
                if grouped_trade.strategy_type in ['put_credit_spread', 'call_credit_spread']:
                    exit_cost = exit_debit - exit_credit
                    realized_pnl = net_premium - exit_cost
                else:
                    realized_pnl = (exit_credit - exit_debit) - (entry_credit - entry_debit)
            
            # Calculate days held
            days_held = None
            if grouped_trade.exit_date:
                days_held = (grouped_trade.exit_date.date() - grouped_trade.entry_date.date()).days
            
            # Determine DTE at entry
            dte_at_entry = None
            expiration_date = None
            
            if option_legs and option_legs[0].expiration_date:
                expiration_date = option_legs[0].expiration_date
                dte_at_entry = (expiration_date - grouped_trade.entry_date.date()).days
            
            # Create trade entry
            trade = TradeEntry(
                trade_id=trade_id,
                account_number="default",  # TODO: Extract from transaction
                underlying_symbol=grouped_trade.underlying_symbol,
                strategy_type=grouped_trade.strategy_type,
                entry_date=grouped_trade.entry_date,
                expiration_date=expiration_date,
                dte_at_entry=dte_at_entry,
                contracts=contracts,
                strike_short=strike_short,
                strike_long=strike_long,
                strike_width=strike_width,
                entry_credit=entry_credit,
                entry_debit=entry_debit,
                max_profit=max_profit,
                max_loss=max_loss,
                total_commissions=total_commissions,
                total_fees=total_fees,
                status=TradeStatus.CLOSED if grouped_trade.is_complete else TradeStatus.OPEN,
                exit_date=grouped_trade.exit_date,
                exit_credit=exit_credit,
                exit_debit=exit_debit,
                realized_pnl=realized_pnl,
                realized_pnl_pct=(realized_pnl / abs(max_loss) * 100) if max_loss else 0,
                days_held=days_held,
                winner=realized_pnl > 0 if realized_pnl != 0 else False,
                outcome_tag="Winner" if realized_pnl > 0 else "Loser" if realized_pnl < 0 else "Breakeven",
                net_pnl_after_fees=realized_pnl - total_commissions - total_fees,
                transaction_ids=[leg.transaction_id for leg in grouped_trade.opening_legs + grouped_trade.closing_legs]
            )
            
            return trade
            
        except Exception as e:
            self.logger.error(f"❌ Error converting grouped trade to journal entry: {e}")
            raise
    
    def process_account_transactions(self, account_number: str, start_date: Optional[datetime] = None,
                                   end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Process all transactions for an account and create journal entries"""
        try:
            self.logger.info(f"🔄 Processing transactions for account {account_number}")
            
            # Fetch transactions from TastyTrade
            transactions = self.journal.fetch_account_transactions(
                account_number=account_number,
                start_date=start_date,
                end_date=end_date
            )
            
            if not transactions:
                return {
                    'success': False,
                    'message': 'No transactions found',
                    'trades_processed': 0
                }
            
            # Group transactions into trades
            grouped_trades = self.group_transactions_into_trades(transactions)
            
            if not grouped_trades:
                return {
                    'success': False,
                    'message': 'No valid trades identified from transactions',
                    'trades_processed': 0
                }
            
            # Convert to journal entries and save
            processed_trades = []
            failed_trades = []
            
            for grouped_trade in grouped_trades:
                try:
                    journal_entry = self.convert_to_journal_entry(grouped_trade)
                    
                    # Save to database
                    if self.journal.save_trade(journal_entry):
                        processed_trades.append(journal_entry.trade_id)
                    else:
                        failed_trades.append(f"Failed to save {journal_entry.trade_id}")
                        
                except Exception as e:
                    failed_trades.append(f"Failed to convert trade: {str(e)}")
            
            result = {
                'success': True,
                'message': f'Processed {len(processed_trades)} trades successfully',
                'trades_processed': len(processed_trades),
                'trades_failed': len(failed_trades),
                'processed_trade_ids': processed_trades,
                'errors': failed_trades
            }
            
            self.logger.info(f"✅ {result['message']}")
            
            if failed_trades:
                self.logger.warning(f"⚠️ {len(failed_trades)} trades failed to process")
                for error in failed_trades:
                    self.logger.warning(f"⚠️ {error}")
            
            return result
            
        except Exception as e:
            error_msg = f"Error processing account transactions: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'message': error_msg,
                'trades_processed': 0
            }