#!/usr/bin/env python3
"""
Position Chain Detector
Analyzes current positions to detect related option strategies and group them into logical chains
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict
import re

@dataclass
class PositionChain:
    """Represents a group of related positions forming a strategy"""
    chain_id: str
    chain_type: str
    description: str
    legs: List[str]  # List of position keys
    metrics: Dict[str, Any]
    detected_at: datetime
    
@dataclass
class ChainLeg:
    """Represents a single leg in a chain for analysis"""
    position_key: str
    symbol: str
    underlying: str
    strike: float
    expiration: str
    option_type: str  # 'C' or 'P'
    quantity: int
    position_data: Dict[str, Any]
    # Enhanced fields for better grouping
    created_at: Optional[datetime] = None
    cost_effect: Optional[str] = None
    average_open_price: Optional[float] = None

class PositionChainDetector:
    """Analyzes current positions to detect related option strategies"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Strategy detection rules
        self.STRATEGY_PATTERNS = {
            'vertical_spread': self._detect_vertical_spreads,
            'calendar_spread': self._detect_calendar_spreads,
            'iron_condor': self._detect_iron_condors,
            'straddle': self._detect_straddles,
            'strangle': self._detect_strangles,
            'single_option': self._detect_single_options,
            'covered_position': self._detect_covered_positions
        }
    
    def detect_chains(self, positions: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        Group positions into logical chains/strategies
        
        :param positions: Dictionary of position_key -> position_data
        :return: Dictionary grouped by underlying symbol with detected chains
        """
        try:
            # First, parse and group positions by underlying
            grouped_positions = self._group_by_underlying(positions)
            
            # Detect chains for each underlying
            results = {}
            for underlying, pos_list in grouped_positions.items():
                chains = []
                used_positions = set()
                
                # Group positions by time windows for better detection
                time_groups = self._group_by_time_windows(pos_list)
                
                # Process each time group separately for spread detection
                for time_group in time_groups:
                    # Try to detect complex strategies within each time group
                    for strategy_type, detector_func in self.STRATEGY_PATTERNS.items():
                        if strategy_type == 'single_option':
                            continue  # Do single options last
                        
                        detected = detector_func(time_group, used_positions)
                        chains.extend(detected)
                        for chain in detected:
                            used_positions.update(chain.legs)
                
                # Finally, detect remaining single options
                single_options = self._detect_single_options(pos_list, used_positions)
                
                results[underlying] = {
                    'chains': chains,
                    'single_options': single_options,
                    'total_positions': len(pos_list)
                }
                
                self.logger.info(f"📊 Detected {len(chains)} chains and {len(single_options)} "
                               f"single options for {underlying}")
            
            return results
            
        except Exception as e:
            self.logger.error(f"❌ Error detecting position chains: {e}")
            return {}
    
    def _group_by_underlying(self, positions: Dict[str, Dict]) -> Dict[str, List[ChainLeg]]:
        """Group and parse positions by underlying symbol"""
        grouped = defaultdict(list)
        
        for pos_key, pos_data in positions.items():
            if pos_data.get('instrument_type') != 'Equity Option':
                continue
            
            try:
                # Parse option symbol
                parsed = self._parse_option_symbol(pos_data['symbol_occ'])
                if parsed:
                    # Parse created_at timestamp if available
                    created_at = None
                    if pos_data.get('created_at'):
                        try:
                            created_at = datetime.fromisoformat(pos_data['created_at'].replace('Z', '+00:00'))
                        except:
                            pass
                    
                    chain_leg = ChainLeg(
                        position_key=pos_key,
                        symbol=pos_data['symbol_occ'],
                        underlying=pos_data['underlying_symbol'],
                        strike=parsed['strike'],
                        expiration=parsed['expiration'],
                        option_type=parsed['option_type'],
                        quantity=int(pos_data['quantity']),
                        position_data=pos_data,
                        # Enhanced fields
                        created_at=created_at,
                        cost_effect=pos_data.get('cost_effect'),
                        average_open_price=pos_data.get('average_open_price')
                    )
                    grouped[pos_data['underlying_symbol']].append(chain_leg)
            except Exception as e:
                self.logger.warning(f"⚠️ Could not parse position {pos_key}: {e}")
        
        return dict(grouped)
    
    def _group_by_time_windows(self, positions: List[ChainLeg]) -> List[List[ChainLeg]]:
        """Group positions by time windows to identify related trades"""
        if not positions:
            return []
        
        # Sort positions by creation time
        positions_with_time = [p for p in positions if p.created_at]
        positions_without_time = [p for p in positions if not p.created_at]
        
        # Sort by creation time
        positions_with_time.sort(key=lambda x: x.created_at)
        
        # Group into time windows (60 seconds)
        time_window_seconds = 60
        time_groups = []
        current_group = []
        current_group_start = None
        
        for position in positions_with_time:
            if current_group_start is None:
                # Start new group
                current_group = [position]
                current_group_start = position.created_at
            else:
                # Check if position is within time window
                time_diff = (position.created_at - current_group_start).total_seconds()
                if time_diff <= time_window_seconds:
                    # Add to current group
                    current_group.append(position)
                else:
                    # Start new group
                    time_groups.append(current_group)
                    current_group = [position]
                    current_group_start = position.created_at
        
        # Add the last group
        if current_group:
            time_groups.append(current_group)
        
        # Add positions without timestamps as individual groups
        for position in positions_without_time:
            time_groups.append([position])
        
        return time_groups
    
    def _parse_option_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Parse OCC option symbol format"""
        # OCC format: AAPL  241220C00150000
        # Match pattern: SYMBOL + spaces + YYMMDD + C/P + strike price (8 digits)
        pattern = r'^(.+?)\s+(\d{6})([CP])(\d{8})$'
        match = re.match(pattern, symbol)
        
        if match:
            underlying = match.group(1).strip()
            date_str = match.group(2)
            option_type = match.group(3)
            strike_str = match.group(4)
            
            # Parse date
            year = 2000 + int(date_str[:2])
            month = int(date_str[2:4])
            day = int(date_str[4:6])
            expiration = f"{year}-{month:02d}-{day:02d}"
            
            # Parse strike (last 8 digits represent price * 1000)
            strike = float(strike_str) / 1000
            
            return {
                'underlying': underlying,
                'expiration': expiration,
                'option_type': option_type,
                'strike': strike
            }
        return None
    
    def _detect_vertical_spreads(self, positions: List[ChainLeg], 
                                used_positions: set) -> List[PositionChain]:
        """Detect vertical spreads (same expiration, different strikes) with quantity awareness"""
        chains = []
        
        # Group by expiration and option type
        by_exp_type = defaultdict(list)
        for leg in positions:
            if leg.position_key not in used_positions:
                key = (leg.expiration, leg.option_type)
                by_exp_type[key].append(leg)
        
        # Look for pairs with opposite quantities (enhanced logic)
        for (exp, opt_type), legs in by_exp_type.items():
            if len(legs) < 2:
                continue
            
            # Sort by strike
            legs.sort(key=lambda x: x.strike)
            
            # Find pairs that could form spreads
            for i in range(len(legs)):
                if legs[i].position_key in used_positions:
                    continue
                    
                for j in range(i + 1, len(legs)):
                    if legs[j].position_key in used_positions:
                        continue
                    
                    # Enhanced matching logic for spreads
                    leg1, leg2 = legs[i], legs[j]
                    
                    # Check for spread patterns:
                    # 1. Same absolute quantity with opposite signs
                    # 2. OR complementary cost effects (Credit/Debit pair)
                    # 3. OR similar creation times
                    
                    is_spread = False
                    spread_quantity = 0
                    
                    # Traditional opposite quantities
                    if leg1.quantity + leg2.quantity == 0 and abs(leg1.quantity) > 0:
                        is_spread = True
                        spread_quantity = abs(leg1.quantity)
                    # Same quantities with complementary cost effects (indicating spread)
                    elif (abs(leg1.quantity) == abs(leg2.quantity) and 
                          leg1.cost_effect and leg2.cost_effect and
                          leg1.cost_effect != leg2.cost_effect and
                          leg1.quantity * leg2.quantity < 0):  # Opposite signs
                        is_spread = True
                        spread_quantity = abs(leg1.quantity)
                    
                    if is_spread:
                        # Determine spread type
                        long_leg = leg1 if leg1.quantity > 0 else leg2
                        short_leg = leg2 if leg2.quantity > 0 else leg1
                        
                        if opt_type == 'C':
                            if long_leg.strike < short_leg.strike:
                                spread_type = 'call_debit_spread'
                                spread_name = 'Call Debit Spread'
                            else:
                                spread_type = 'call_credit_spread'
                                spread_name = 'Call Credit Spread'
                        else:  # Put
                            if long_leg.strike > short_leg.strike:
                                spread_type = 'put_debit_spread'
                                spread_name = 'Put Debit Spread'
                            else:
                                spread_type = 'put_credit_spread'
                                spread_name = 'Put Credit Spread'
                        
                        # Calculate metrics with quantity awareness
                        spread_width = abs(leg1.strike - leg2.strike)
                        net_premium = (long_leg.position_data.get('net_liq', 0) + 
                                     short_leg.position_data.get('net_liq', 0))
                        
                        # Calculate max profit/loss based on spread type and quantity
                        if 'credit' in spread_type:
                            max_profit = abs(net_premium)
                            max_loss = (spread_width * 100 * spread_quantity) - max_profit
                        else:  # debit spread
                            max_loss = abs(net_premium)
                            max_profit = (spread_width * 100 * spread_quantity) - max_loss
                        
                        # Enhanced description with quantity
                        quantity_desc = f"{spread_quantity}x " if spread_quantity > 1 else ""
                        description = f"{long_leg.underlying} {self._format_date(exp)} {quantity_desc}{int(min(leg1.strike, leg2.strike))}/{int(max(leg1.strike, leg2.strike))} {spread_name}"
                        
                        chain = PositionChain(
                            chain_id=f"{long_leg.underlying}_VERTICAL_{exp}_{int(min(leg1.strike, leg2.strike))}_{int(max(leg1.strike, leg2.strike))}",
                            chain_type=spread_type,
                            description=description,
                            legs=[leg1.position_key, leg2.position_key],
                            metrics={
                                'spread_width': spread_width,
                                'spread_quantity': spread_quantity,
                                'net_premium': net_premium,
                                'max_profit': max_profit,
                                'max_loss': max_loss,
                                'net_delta': (leg1.position_data.get('position_delta', 0) + 
                                            leg2.position_data.get('position_delta', 0)),
                                'days_to_expiration': self._calculate_dte(exp),
                                'created_time_diff': abs((leg1.created_at - leg2.created_at).total_seconds()) if leg1.created_at and leg2.created_at else None
                            },
                            detected_at=datetime.now()
                        )
                        chains.append(chain)
                        
                        self.logger.info(f"🔄 Detected {quantity_desc}{spread_name}: {description}")
        
        return chains
    
    def _detect_calendar_spreads(self, positions: List[ChainLeg], 
                                used_positions: set) -> List[PositionChain]:
        """Detect calendar spreads (same strike, different expirations)"""
        chains = []
        
        # Group by strike and option type
        by_strike_type = defaultdict(list)
        for leg in positions:
            if leg.position_key not in used_positions:
                key = (leg.strike, leg.option_type)
                by_strike_type[key].append(leg)
        
        # Look for same strike, different expirations
        for (strike, opt_type), legs in by_strike_type.items():
            if len(legs) < 2:
                continue
            
            # Sort by expiration
            legs.sort(key=lambda x: x.expiration)
            
            for i in range(len(legs)):
                if legs[i].position_key in used_positions:
                    continue
                    
                for j in range(i + 1, len(legs)):
                    if legs[j].position_key in used_positions:
                        continue
                    
                    # Check if one is long and one is short
                    if legs[i].quantity * legs[j].quantity < 0:
                        long_leg = legs[i] if legs[i].quantity > 0 else legs[j]
                        short_leg = legs[j] if legs[j].quantity > 0 else legs[i]
                        
                        calendar_type = 'call_calendar' if opt_type == 'C' else 'put_calendar'
                        
                        chain = PositionChain(
                            chain_id=f"{long_leg.underlying}_CALENDAR_{opt_type}_{int(strike)}_{short_leg.expiration}_{long_leg.expiration}",
                            chain_type=calendar_type,
                            description=f"{long_leg.underlying} {int(strike)} {opt_type} Calendar ({self._format_date(short_leg.expiration)}/{self._format_date(long_leg.expiration)})",
                            legs=[legs[i].position_key, legs[j].position_key],
                            metrics={
                                'strike': strike,
                                'net_premium': (long_leg.position_data['net_liq'] + 
                                              short_leg.position_data['net_liq']),
                                'short_dte': self._calculate_dte(short_leg.expiration),
                                'long_dte': self._calculate_dte(long_leg.expiration),
                                'net_delta': (legs[i].position_data.get('position_delta', 0) + 
                                            legs[j].position_data.get('position_delta', 0))
                            },
                            detected_at=datetime.now()
                        )
                        chains.append(chain)
                        
                        self.logger.info(f"📅 Detected Calendar Spread: {chain.description}")
        
        return chains
    
    def _detect_iron_condors(self, positions: List[ChainLeg], 
                            used_positions: set) -> List[PositionChain]:
        """Detect iron condors (call spread + put spread)"""
        chains = []
        
        # First find all vertical spreads
        verticals = self._detect_vertical_spreads(positions, used_positions)
        
        # Group by expiration
        by_exp = defaultdict(list)
        for v in verticals:
            # Extract expiration from first leg
            first_leg_key = v.legs[0]
            for leg in positions:
                if leg.position_key == first_leg_key:
                    by_exp[leg.expiration].append(v)
                    break
        
        # Look for call + put credit spreads
        for exp, spreads in by_exp.items():
            call_credits = [s for s in spreads if s.chain_type == 'call_credit_spread']
            put_credits = [s for s in spreads if s.chain_type == 'put_credit_spread']
            
            for call_spread in call_credits:
                for put_spread in put_credits:
                    # Combine into iron condor
                    all_legs = call_spread.legs + put_spread.legs
                    
                    chain = PositionChain(
                        chain_id=f"{positions[0].underlying}_IRON_CONDOR_{exp}",
                        chain_type='iron_condor',
                        description=f"{positions[0].underlying} {self._format_date(exp)} Iron Condor",
                        legs=all_legs,
                        metrics={
                            'call_spread': call_spread.metrics,
                            'put_spread': put_spread.metrics,
                            'total_credit': (call_spread.metrics['net_premium'] + 
                                           put_spread.metrics['net_premium']),
                            'max_profit': (call_spread.metrics['max_profit'] + 
                                         put_spread.metrics['max_profit']),
                            'max_loss': max(call_spread.metrics['max_loss'], 
                                          put_spread.metrics['max_loss']),
                            'days_to_expiration': self._calculate_dte(exp)
                        },
                        detected_at=datetime.now()
                    )
                    chains.append(chain)
                    
                    # Mark spreads as used
                    used_positions.update(all_legs)
                    
                    self.logger.info(f"🦅 Detected Iron Condor: {chain.description}")
        
        return chains
    
    def _detect_straddles(self, positions: List[ChainLeg], 
                         used_positions: set) -> List[PositionChain]:
        """Detect straddles (call + put at same strike)"""
        chains = []
        
        # Group by strike and expiration
        by_strike_exp = defaultdict(lambda: {'C': [], 'P': []})
        for leg in positions:
            if leg.position_key not in used_positions:
                key = (leg.strike, leg.expiration)
                by_strike_exp[key][leg.option_type].append(leg)
        
        # Look for call + put pairs
        for (strike, exp), options in by_strike_exp.items():
            if options['C'] and options['P']:
                for call in options['C']:
                    for put in options['P']:
                        # Check if same quantity and direction
                        if call.quantity == put.quantity:
                            straddle_type = 'long_straddle' if call.quantity > 0 else 'short_straddle'
                            
                            chain = PositionChain(
                                chain_id=f"{call.underlying}_STRADDLE_{exp}_{int(strike)}",
                                chain_type=straddle_type,
                                description=f"{call.underlying} {self._format_date(exp)} {int(strike)} Straddle",
                                legs=[call.position_key, put.position_key],
                                metrics={
                                    'strike': strike,
                                    'net_premium': (call.position_data['net_liq'] + 
                                                  put.position_data['net_liq']),
                                    'net_delta': (call.position_data.get('position_delta', 0) + 
                                                put.position_data.get('position_delta', 0)),
                                    'quantity': abs(call.quantity),
                                    'days_to_expiration': self._calculate_dte(exp)
                                },
                                detected_at=datetime.now()
                            )
                            chains.append(chain)
                            
                            self.logger.info(f"🎯 Detected Straddle: {chain.description}")
        
        return chains
    
    def _detect_strangles(self, positions: List[ChainLeg], 
                         used_positions: set) -> List[PositionChain]:
        """Detect strangles (call + put at different strikes)"""
        chains = []
        
        # Group by expiration
        by_exp = defaultdict(lambda: {'C': [], 'P': []})
        for leg in positions:
            if leg.position_key not in used_positions:
                by_exp[leg.expiration][leg.option_type].append(leg)
        
        # Look for call + put pairs with different strikes
        for exp, options in by_exp.items():
            if options['C'] and options['P']:
                for call in options['C']:
                    for put in options['P']:
                        # Check if same quantity and direction, different strikes
                        if (call.quantity == put.quantity and 
                            call.strike != put.strike):
                            strangle_type = 'long_strangle' if call.quantity > 0 else 'short_strangle'
                            
                            chain = PositionChain(
                                chain_id=f"{call.underlying}_STRANGLE_{exp}_{int(put.strike)}_{int(call.strike)}",
                                chain_type=strangle_type,
                                description=f"{call.underlying} {self._format_date(exp)} {int(put.strike)}/{int(call.strike)} Strangle",
                                legs=[call.position_key, put.position_key],
                                metrics={
                                    'put_strike': put.strike,
                                    'call_strike': call.strike,
                                    'strike_width': call.strike - put.strike,
                                    'net_premium': (call.position_data['net_liq'] + 
                                                  put.position_data['net_liq']),
                                    'net_delta': (call.position_data.get('position_delta', 0) + 
                                                put.position_data.get('position_delta', 0)),
                                    'quantity': abs(call.quantity),
                                    'days_to_expiration': self._calculate_dte(exp)
                                },
                                detected_at=datetime.now()
                            )
                            chains.append(chain)
                            
                            self.logger.info(f"🎭 Detected Strangle: {chain.description}")
        
        return chains
    
    def _detect_single_options(self, positions: List[ChainLeg], 
                              used_positions: set) -> List[PositionChain]:
        """Detect remaining single options with quantity awareness"""
        singles = []
        
        for leg in positions:
            if leg.position_key not in used_positions:
                option_type = 'call' if leg.option_type == 'C' else 'put'
                direction = 'long' if leg.quantity > 0 else 'short'
                
                # Add quantity to description if > 1
                quantity_desc = f"{abs(leg.quantity)}x " if abs(leg.quantity) > 1 else ""
                description = f"{leg.underlying} {self._format_date(leg.expiration)} {quantity_desc}{int(leg.strike)} {option_type.title()}"
                
                chain = PositionChain(
                    chain_id=f"{leg.underlying}_SINGLE_{leg.expiration}_{int(leg.strike)}_{leg.option_type}",
                    chain_type=f"{direction}_{option_type}",
                    description=description,
                    legs=[leg.position_key],
                    metrics={
                        'strike': leg.strike,
                        'quantity': leg.quantity,
                        'net_liq': leg.position_data['net_liq'],
                        'delta': leg.position_data.get('delta', 0),
                        'position_delta': leg.position_data.get('position_delta', 0),
                        'days_to_expiration': self._calculate_dte(leg.expiration)
                    },
                    detected_at=datetime.now()
                )
                singles.append(chain)
        
        return singles
    
    def _detect_covered_positions(self, positions: List[ChainLeg], 
                                 used_positions: set) -> List[PositionChain]:
        """Detect covered calls/puts (stock + options)"""
        # This would require access to stock positions as well
        # For now, returning empty list
        return []
    
    def _calculate_dte(self, expiration: str) -> int:
        """Calculate days to expiration"""
        try:
            exp_date = datetime.strptime(expiration, '%Y-%m-%d')
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            return (exp_date - today).days
        except:
            return 0
    
    def _format_date(self, date_str: str) -> str:
        """Format date string for display"""
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            return date_obj.strftime('%b %d')
        except:
            return date_str