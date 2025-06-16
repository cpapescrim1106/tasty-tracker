#!/usr/bin/env python3
"""
TastyTracker Order Manager
Handles order construction and execution for automated trading
"""

import os
import logging
import requests
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

# Tastytrade imports
from tastytrade import Session
from tastytrade.order import OrderAction

class OrderJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for order objects"""
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)

class OrderStatus(Enum):
    """Order status enumeration"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    PARTIAL = "partial"

class SmartPricingStrategy:
    """Intelligent order pricing that improves fill rates while maintaining favorable pricing"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Pricing rules for different strategy types
        self.pricing_rules = {
            'directional': {
                'initial_offset': 0.03,  # $0.03 from mid-price
                'min_offset': 0.01,      # Minimum $0.01 from mid-price
                'adjustment_interval': 600,  # 10 minutes in seconds
                'adjustment_step': 0.01  # Move $0.01 closer each interval
            },
            'neutral': {
                'initial_offset': 0.01,  # $0.01 from mid-price
                'min_offset': 0.00,      # Can go to mid-price
                'adjustment_interval': 600,  # 10 minutes
                'adjustment_step': 0.01
            }
        }
    
    def calculate_initial_price(self, mid_price: float, strategy_type: str = 'directional', 
                              is_credit: bool = True) -> float:
        """Calculate initial order price with favorable offset from mid"""
        rules = self.pricing_rules.get(strategy_type, self.pricing_rules['directional'])
        offset = rules['initial_offset']
        
        if is_credit:
            # For credit spreads, start below mid-price (more favorable to us)
            initial_price = mid_price - offset
        else:
            # For debit spreads, start above mid-price (more favorable to us) 
            initial_price = mid_price + offset
            
        return round(max(0.01, initial_price), 2)  # Minimum price of $0.01
    
    def calculate_next_price(self, current_price: float, mid_price: float, 
                           strategy_type: str = 'directional', is_credit: bool = True,
                           adjustment_count: int = 1) -> Optional[float]:
        """Calculate next price adjustment toward mid-price"""
        rules = self.pricing_rules.get(strategy_type, self.pricing_rules['directional'])
        step = rules['adjustment_step']
        min_offset = rules['min_offset']
        
        if is_credit:
            # Move price up toward mid (less favorable but better fill probability)
            next_price = current_price + step
            # Don't go above mid-price minus minimum offset
            max_price = mid_price - min_offset
            if next_price > max_price:
                next_price = max_price
        else:
            # Move price down toward mid (less favorable but better fill probability)
            next_price = current_price - step
            # Don't go below mid-price plus minimum offset
            min_price = mid_price + min_offset
            if next_price < min_price:
                next_price = min_price
        
        # Round to nearest cent
        next_price = round(next_price, 2)
        
        # Return None if we can't improve further
        if abs(next_price - current_price) < 0.005:  # Less than half a cent difference
            return None
            
        return next_price
    
    def should_adjust_price(self, order_created_at: datetime, last_adjustment: Optional[datetime] = None) -> bool:
        """Check if enough time has passed for price adjustment"""
        now = datetime.now()
        
        # Use last adjustment time if available, otherwise order creation time
        reference_time = last_adjustment or order_created_at
        
        # Check if adjustment interval has passed
        time_elapsed = (now - reference_time).total_seconds()
        return time_elapsed >= self.pricing_rules['directional']['adjustment_interval']

@dataclass
class OrderLeg:
    """Represents a single leg of an order"""
    symbol: str
    quantity: int
    action: OrderAction
    order_type: str = "Limit"
    price: float = 0.0

@dataclass
class TradeOrder:
    """Represents a complete trade order"""
    order_id: Optional[str]
    account_number: str
    symbol: str
    strategy_type: str
    legs: List[OrderLeg]
    order_type: str
    price_type: str
    price: float
    quantity: int
    time_in_force: str
    status: OrderStatus
    created_at: datetime
    filled_at: Optional[datetime] = None
    error_message: Optional[str] = None

class OrderManager:
    """Main class for managing order creation and execution"""
    
    def __init__(self, tasty_client: Session):
        self.tasty_client = tasty_client
        self.base_url = "https://api.tastyworks.com"
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Order tracking
        self.pending_orders = {}
        self.completed_orders = {}
        
        # Smart pricing strategy
        self.smart_pricing = SmartPricingStrategy()
        
        # Default order settings
        self.default_time_in_force = "Day"
        self.default_order_type = "Limit"
    
    def _order_to_dict(self, order: TradeOrder) -> Dict[str, Any]:
        """Convert a TradeOrder object to a JSON-serializable dictionary"""
        return {
            'order_id': order.order_id,
            'account_number': order.account_number,
            'symbol': order.symbol,
            'strategy_type': order.strategy_type,
            'legs': [
                {
                    'symbol': leg.symbol,
                    'quantity': leg.quantity,
                    'action': leg.action.value if isinstance(leg.action, Enum) else leg.action,
                    'order_type': leg.order_type,
                    'price': leg.price
                }
                for leg in order.legs
            ],
            'order_type': order.order_type,
            'price_type': order.price_type,
            'price': order.price,
            'quantity': order.quantity,
            'time_in_force': order.time_in_force,
            'status': order.status.value if isinstance(order.status, Enum) else order.status,
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'filled_at': order.filled_at.isoformat() if order.filled_at else None,
            'error_message': order.error_message
        }
        
    def create_put_credit_spread_order(self, account_number: str, strategy_data: Dict[str, Any], 
                                     quantity: int = 1, price_adjustment: float = 0.0) -> TradeOrder:
        """Create a put credit spread order from strategy analysis"""
        
        try:
            short_leg_data = strategy_data['short_leg']
            long_leg_data = strategy_data['long_leg']
            
            # Calculate net premium with adjustment
            base_premium = strategy_data['net_premium']
            order_price = round(base_premium + price_adjustment, 2)
            
            # Create order legs
            # Leg 1: Sell to Open (short put) - collect premium
            short_leg = OrderLeg(
                symbol=short_leg_data['symbol'],
                quantity=quantity,
                action=OrderAction.SELL_TO_OPEN,
                order_type="Limit",
                price=short_leg_data['bid_price']
            )
            
            # Leg 2: Buy to Open (long put) - pay premium
            long_leg = OrderLeg(
                symbol=long_leg_data['symbol'],
                quantity=quantity,
                action=OrderAction.BUY_TO_OPEN,
                order_type="Limit", 
                price=long_leg_data['ask_price']
            )
            
            # Create the complete order
            order = TradeOrder(
                order_id=None,
                account_number=account_number,
                symbol=strategy_data.get('underlying_symbol', ''),
                strategy_type="Put Credit Spread",
                legs=[short_leg, long_leg],
                order_type="Limit",
                price_type="Net Credit",
                price=order_price,
                quantity=quantity,
                time_in_force=self.default_time_in_force,
                status=OrderStatus.PENDING,
                created_at=datetime.now()
            )
            
            self.logger.info(f"✅ Created put credit spread order for {strategy_data.get('underlying_symbol')} at ${order_price:.2f}")
            return order
            
        except Exception as e:
            self.logger.error(f"❌ Error creating put credit spread order: {e}")
            raise
    
    def validate_order(self, order: TradeOrder) -> Dict[str, Any]:
        """Validate an order before submission"""
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            # Check basic order requirements
            if not order.account_number:
                validation_result['errors'].append("Account number is required")
            
            if not order.legs or len(order.legs) == 0:
                validation_result['errors'].append("Order must have at least one leg")
            
            if order.quantity <= 0:
                validation_result['errors'].append("Quantity must be positive")
            
            if order.price <= 0 and order.order_type == "Limit":
                validation_result['errors'].append("Limit orders must have a positive price")
            
            # Validate each leg
            for i, leg in enumerate(order.legs):
                if not leg.symbol:
                    validation_result['errors'].append(f"Leg {i+1}: Symbol is required")
                
                if leg.quantity <= 0:
                    validation_result['errors'].append(f"Leg {i+1}: Quantity must be positive")
            
            # Strategy-specific validations
            if order.strategy_type == "Put Credit Spread":
                if len(order.legs) != 2:
                    validation_result['errors'].append("Put credit spread must have exactly 2 legs")
                elif len(order.legs) == 2:
                    # Check that we have one sell and one buy
                    actions = [leg.action for leg in order.legs]
                    if OrderAction.SELL_TO_OPEN not in actions or OrderAction.BUY_TO_OPEN not in actions:
                        validation_result['errors'].append("Put credit spread must have one sell to open and one buy to open")
            
            # Check for warnings
            if order.price < 0.50:
                validation_result['warnings'].append("Premium is less than $0.50 - consider if this trade is worth the risk")
            
            # Set final validation status
            validation_result['valid'] = len(validation_result['errors']) == 0
            
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Validation error: {str(e)}")
        
        return validation_result
    
    def submit_order_dry_run(self, order: TradeOrder) -> Dict[str, Any]:
        """Submit order for dry run validation (doesn't actually place the order)"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Build order payload
            order_payload = self._build_order_payload(order, dry_run=True)
            
            # Debug logging
            self.logger.info(f"🔍 Dry run payload for {order.symbol}: {json.dumps(order_payload, indent=2)}")
            
            response = requests.post(
                f"{self.base_url}/accounts/{order.account_number}/orders/dry-run",
                headers=headers,
                json=order_payload
            )
            
            if response.status_code == 201:
                result = response.json()
                self.logger.info(f"✅ Dry run successful for {order.symbol}")
                return {
                    'success': True,
                    'message': 'Order validation passed',
                    'data': result.get('data', {}),
                    'buying_power_required': result.get('data', {}).get('buying-power-effect', {}).get('change-in-buying-power', 0)
                }
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('error', {}).get('message', f"HTTP {response.status_code}")
                self.logger.error(f"❌ Dry run failed for {order.symbol}: {error_msg}")
                self.logger.error(f"❌ Full error response: {json.dumps(error_data, indent=2)}")
                return {
                    'success': False,
                    'message': f'Dry run failed: {error_msg}',
                    'data': error_data
                }
                
        except Exception as e:
            self.logger.error(f"❌ Error in dry run for {order.symbol}: {e}")
            return {
                'success': False,
                'message': f'Dry run error: {str(e)}',
                'data': {}
            }
    
    def submit_order(self, order: TradeOrder, force: bool = False) -> Dict[str, Any]:
        """Submit an order for execution"""
        try:
            # Validate order first
            if not force:
                validation = self.validate_order(order)
                if not validation['valid']:
                    return {
                        'success': False,
                        'message': f"Order validation failed: {', '.join(validation['errors'])}",
                        'order_id': None
                    }
            
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Build order payload
            order_payload = self._build_order_payload(order, dry_run=False)
            
            response = requests.post(
                f"{self.base_url}/accounts/{order.account_number}/orders",
                headers=headers,
                json=order_payload
            )
            
            if response.status_code == 201:
                result = response.json()
                order_data = result.get('data', {})
                order_id = order_data.get('id')
                
                # Update order with ID and status
                order.order_id = order_id
                order.status = OrderStatus.SUBMITTED
                
                # Track the order
                self.pending_orders[order_id] = order
                
                self.logger.info(f"✅ Order submitted successfully for {order.symbol} - ID: {order_id}")
                return {
                    'success': True,
                    'message': 'Order submitted successfully',
                    'order_id': order_id,
                    'data': order_data
                }
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('error', {}).get('message', f"HTTP {response.status_code}")
                
                order.status = OrderStatus.REJECTED
                order.error_message = error_msg
                
                self.logger.error(f"❌ Order submission failed for {order.symbol}: {error_msg}")
                return {
                    'success': False,
                    'message': f'Order submission failed: {error_msg}',
                    'order_id': None,
                    'data': error_data
                }
                
        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.error_message = str(e)
            
            self.logger.error(f"❌ Error submitting order for {order.symbol}: {e}")
            return {
                'success': False,
                'message': f'Order submission error: {str(e)}',
                'order_id': None
            }
    
    def _build_order_payload(self, order: TradeOrder, dry_run: bool = False) -> Dict[str, Any]:
        """Build the JSON payload for order submission"""
        
        legs_payload = []
        for leg in order.legs:
            leg_data = {
                "instrument-type": "Equity Option",
                "symbol": leg.symbol,
                "quantity": str(leg.quantity)
            }
            
            # Use the full action string value
            leg_data["action"] = leg.action.value
            
            legs_payload.append(leg_data)
        
        payload = {
            "order-type": order.order_type,
            "time-in-force": order.time_in_force,
            "legs": legs_payload
        }
        
        # Add price for limit orders
        if order.order_type == "Limit":
            payload["price"] = str(order.price)
            payload["price-effect"] = "Credit" if order.price_type == "Net Credit" else "Debit"
        
        # Add dry run flag if needed
        if dry_run:
            payload["dry-run"] = True
        
        return payload
    
    def get_order_status(self, order_id: str, account_number: str) -> Dict[str, Any]:
        """Get the current status of an order"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"{self.base_url}/accounts/{account_number}/orders/{order_id}",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                order_data = data.get('data', {})
                
                return {
                    'success': True,
                    'order_id': order_id,
                    'status': order_data.get('status', 'Unknown'),
                    'filled_quantity': order_data.get('filled-quantity', 0),
                    'remaining_quantity': order_data.get('remaining-quantity', 0),
                    'data': order_data
                }
            else:
                return {
                    'success': False,
                    'message': f"Failed to get order status: HTTP {response.status_code}"
                }
                
        except Exception as e:
            self.logger.error(f"❌ Error getting order status for {order_id}: {e}")
            return {
                'success': False,
                'message': f"Error getting order status: {str(e)}"
            }
    
    def cancel_order(self, order_id: str, account_number: str) -> Dict[str, Any]:
        """Cancel a pending order"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.delete(
                f"{self.base_url}/accounts/{account_number}/orders/{order_id}",
                headers=headers
            )
            
            if response.status_code == 204:
                # Update local tracking
                if order_id in self.pending_orders:
                    self.pending_orders[order_id].status = OrderStatus.CANCELLED
                
                self.logger.info(f"✅ Order {order_id} cancelled successfully")
                return {
                    'success': True,
                    'message': 'Order cancelled successfully'
                }
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('error', {}).get('message', f"HTTP {response.status_code}")
                
                self.logger.error(f"❌ Failed to cancel order {order_id}: {error_msg}")
                return {
                    'success': False,
                    'message': f'Cancel failed: {error_msg}'
                }
                
        except Exception as e:
            self.logger.error(f"❌ Error cancelling order {order_id}: {e}")
            return {
                'success': False,
                'message': f'Cancel error: {str(e)}'
            }
    
    def get_account_orders(self, account_number: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent orders for an account"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"{self.base_url}/accounts/{account_number}/orders",
                params={'per-page': limit},
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                orders = data.get('data', {}).get('items', [])
                return orders
            else:
                self.logger.error(f"❌ Failed to get account orders: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Error getting account orders: {e}")
            return []
    
    def create_bulk_orders(self, account_number: str, strategies: List[Dict[str, Any]], 
                          quantity: int = 1, price_adjustment: float = 0.0) -> Dict[str, Any]:
        """Create multiple orders from a list of strategies"""
        results = {
            'total_strategies': len(strategies),
            'orders_created': 0,
            'orders_submitted': 0,
            'orders_failed': 0,
            'orders': [],
            'errors': []
        }
        
        for strategy in strategies:
            try:
                # Create the order
                order = self.create_put_credit_spread_order(
                    account_number, strategy, quantity, price_adjustment
                )
                results['orders_created'] += 1
                
                # Validate and submit (dry run first)
                dry_run_result = self.submit_order_dry_run(order)
                
                if dry_run_result['success']:
                    # If dry run passes, submit the real order
                    submit_result = self.submit_order(order)
                    
                    order_result = {
                        'symbol': strategy.get('underlying_symbol'),
                        'order': self._order_to_dict(order),
                        'dry_run': dry_run_result,
                        'submission': submit_result
                    }
                    
                    if submit_result['success']:
                        results['orders_submitted'] += 1
                    else:
                        results['orders_failed'] += 1
                        results['errors'].append(f"{strategy.get('underlying_symbol')}: {submit_result['message']}")
                        
                else:
                    results['orders_failed'] += 1
                    results['errors'].append(f"{strategy.get('underlying_symbol')}: Dry run failed - {dry_run_result['message']}")
                    
                    order_result = {
                        'symbol': strategy.get('underlying_symbol'),
                        'order': self._order_to_dict(order),
                        'dry_run': dry_run_result,
                        'submission': {'success': False, 'message': 'Skipped due to dry run failure'}
                    }
                
                results['orders'].append(order_result)
                
            except Exception as e:
                results['orders_failed'] += 1
                error_msg = f"{strategy.get('underlying_symbol', 'Unknown')}: {str(e)}"
                results['errors'].append(error_msg)
                self.logger.error(f"❌ Error creating bulk order: {error_msg}")
        
        self.logger.info(f"✅ Bulk order creation complete: {results['orders_submitted']}/{results['total_strategies']} submitted")
        return results
    
    # Smart Pricing Methods
    
    def update_working_order_price(self, order_id: str, account_number: str, new_price: float) -> Dict[str, Any]:
        """Update price of working order using TastyTrade API"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            # Determine price effect based on price value
            price_effect = "Credit" if new_price > 0 else "Debit"
            
            payload = {
                "price": str(new_price),
                "price-effect": price_effect
            }
            
            self.logger.info(f"🔄 Updating order {order_id} price to ${new_price:.2f}")
            
            response = requests.put(
                f"{self.base_url}/accounts/{account_number}/orders/{order_id}",
                headers=headers,
                json=payload
            )
            
            if response.status_code == 200:
                self.logger.info(f"✅ Order {order_id} price updated successfully")
                return {
                    'success': True,
                    'order_id': order_id,
                    'new_price': new_price,
                    'response': response.json()
                }
            else:
                error_msg = f"Failed to update order price: {response.status_code} - {response.text}"
                self.logger.error(f"❌ {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'status_code': response.status_code
                }
                
        except Exception as e:
            error_msg = f"Error updating order price: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
    
    def get_working_orders(self, account_number: str) -> List[Dict[str, Any]]:
        """Get all working (unfilled) orders for an account"""
        try:
            headers = {
                'Authorization': self.tasty_client.session_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"{self.base_url}/accounts/{account_number}/orders",
                headers=headers,
                params={'status': 'Live'}  # Only get live/working orders
            )
            
            if response.status_code == 200:
                data = response.json()
                orders = data.get('data', {}).get('items', [])
                
                # Filter for orders that can be modified
                working_orders = []
                for order in orders:
                    status = order.get('status', '').lower()
                    if status in ['received', 'live', 'partially-filled']:
                        working_orders.append(order)
                
                self.logger.info(f"📊 Found {len(working_orders)} working orders")
                return working_orders
            else:
                self.logger.error(f"❌ Failed to fetch working orders: {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Error fetching working orders: {e}")
            return []
    
    def calculate_mid_price_from_quotes(self, quotes: Dict[str, Any]) -> Optional[float]:
        """Calculate mid-price from bid/ask quotes"""
        try:
            bid = float(quotes.get('bid-price', 0))
            ask = float(quotes.get('ask-price', 0))
            
            if bid > 0 and ask > 0 and ask > bid:
                mid_price = (bid + ask) / 2.0
                return round(mid_price, 2)
            
            return None
        except (ValueError, TypeError):
            return None
    
    def create_order_with_smart_pricing(self, account_number: str, strategy_data: Dict[str, Any], 
                                       quantity: int = 1, strategy_type: str = 'directional') -> TradeOrder:
        """Create order using smart pricing strategy"""
        try:
            # Get current market mid-price (you'll need to implement quote fetching)
            base_premium = strategy_data.get('net_premium', 0)
            
            # Use smart pricing to determine initial order price
            initial_price = self.smart_pricing.calculate_initial_price(
                mid_price=base_premium,
                strategy_type=strategy_type,
                is_credit=True  # Assuming credit spread for now
            )
            
            # Create order with smart initial price
            strategy_data_adjusted = strategy_data.copy()
            strategy_data_adjusted['net_premium'] = initial_price
            
            # Use existing method but with smart pricing
            order = self.create_put_credit_spread_order(
                account_number=account_number,
                strategy_data=strategy_data_adjusted,
                quantity=quantity,
                price_adjustment=0.0  # Already included in smart pricing
            )
            
            # Track that this order uses smart pricing
            order.smart_pricing_enabled = True
            order.initial_smart_price = initial_price
            order.original_mid_price = base_premium
            
            self.logger.info(f"📈 Created smart-priced order: Mid=${base_premium:.2f}, Initial=${initial_price:.2f}")
            
            return order
            
        except Exception as e:
            self.logger.error(f"❌ Error creating smart-priced order: {e}")
            # Fallback to regular order creation
            return self.create_put_credit_spread_order(account_number, strategy_data, quantity)