#!/usr/bin/env python3
"""
Order Price Adjustment Service
Background service for automatic price improvements on working orders
"""

import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class TrackedOrder:
    """Represents an order being tracked for price adjustments"""
    order_id: str
    account_number: str
    symbol: str
    strategy_type: str
    current_price: float
    original_mid_price: float
    is_credit: bool
    created_at: datetime
    last_adjustment: Optional[datetime] = None
    adjustment_count: int = 0
    max_adjustments: int = 6  # Maximum 6 adjustments = 1 hour
    
class OrderPriceAdjustmentService:
    """Background service for automatic order price adjustments"""
    
    def __init__(self, order_manager):
        self.order_manager = order_manager
        self.logger = logging.getLogger(__name__)
        
        # Service state
        self.running = False
        self.check_interval = 60  # Check every minute
        self.tracked_orders = {}  # order_id -> TrackedOrder
        
        # Threading
        self.adjustment_thread = None
        self.lock = threading.Lock()
        
    def start(self):
        """Start the background adjustment service"""
        if self.running:
            self.logger.warning("⚠️ Price adjustment service already running")
            return
            
        self.running = True
        self.adjustment_thread = threading.Thread(target=self._adjustment_loop, daemon=True)
        self.adjustment_thread.start()
        self.logger.info("🚀 Price adjustment service started")
        
    def stop(self):
        """Stop the background adjustment service"""
        self.running = False
        if self.adjustment_thread:
            self.adjustment_thread.join(timeout=5)
        self.logger.info("🛑 Price adjustment service stopped")
        
    def track_order(self, order_id: str, account_number: str, symbol: str, 
                   strategy_type: str, initial_price: float, mid_price: float, 
                   is_credit: bool = True):
        """Add an order to be tracked for price adjustments"""
        with self.lock:
            tracked_order = TrackedOrder(
                order_id=order_id,
                account_number=account_number,
                symbol=symbol,
                strategy_type=strategy_type,
                current_price=initial_price,
                original_mid_price=mid_price,
                is_credit=is_credit,
                created_at=datetime.now()
            )
            
            self.tracked_orders[order_id] = tracked_order
            self.logger.info(f"📊 Now tracking order {order_id} for price adjustments")
            
    def untrack_order(self, order_id: str, reason: str = "Unknown"):
        """Remove an order from tracking"""
        with self.lock:
            if order_id in self.tracked_orders:
                del self.tracked_orders[order_id]
                self.logger.info(f"📉 Stopped tracking order {order_id}: {reason}")
                
    def _adjustment_loop(self):
        """Main loop for checking and adjusting order prices"""
        while self.running:
            try:
                self._check_and_adjust_orders()
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.error(f"❌ Error in adjustment loop: {e}")
                time.sleep(self.check_interval)
                
    def _check_and_adjust_orders(self):
        """Check all tracked orders and adjust prices if needed"""
        with self.lock:
            orders_to_check = list(self.tracked_orders.items())
            
        for order_id, tracked_order in orders_to_check:
            try:
                # Check if order still exists and is working
                if not self._is_order_still_working(order_id, tracked_order.account_number):
                    self.untrack_order(order_id, "Order no longer working")
                    continue
                
                # Check if it's time for an adjustment
                if not self._should_adjust_order(tracked_order):
                    continue
                    
                # Calculate next price
                next_price = self.order_manager.smart_pricing.calculate_next_price(
                    current_price=tracked_order.current_price,
                    mid_price=tracked_order.original_mid_price,
                    strategy_type=tracked_order.strategy_type,
                    is_credit=tracked_order.is_credit,
                    adjustment_count=tracked_order.adjustment_count
                )
                
                if next_price is None:
                    self.logger.info(f"📊 Order {order_id} reached maximum price improvement")
                    self.untrack_order(order_id, "Maximum price improvement reached")
                    continue
                
                # Attempt price adjustment
                self._adjust_order_price(tracked_order, next_price)
                
            except Exception as e:
                self.logger.error(f"❌ Error processing order {order_id}: {e}")
                
    def _is_order_still_working(self, order_id: str, account_number: str) -> bool:
        """Check if order is still working (not filled/cancelled)"""
        try:
            working_orders = self.order_manager.get_working_orders(account_number)
            return any(order.get('id') == order_id for order in working_orders)
        except Exception as e:
            self.logger.error(f"❌ Error checking order status: {e}")
            return False
            
    def _should_adjust_order(self, tracked_order: TrackedOrder) -> bool:
        """Check if order should be adjusted based on timing and limits"""
        # Check adjustment count limit
        if tracked_order.adjustment_count >= tracked_order.max_adjustments:
            return False
            
        # Check timing using smart pricing logic
        return self.order_manager.smart_pricing.should_adjust_price(
            order_created_at=tracked_order.created_at,
            last_adjustment=tracked_order.last_adjustment
        )
        
    def _adjust_order_price(self, tracked_order: TrackedOrder, new_price: float):
        """Adjust order price and update tracking info"""
        try:
            result = self.order_manager.update_working_order_price(
                order_id=tracked_order.order_id,
                account_number=tracked_order.account_number,
                new_price=new_price
            )
            
            if result.get('success'):
                # Update tracking info
                with self.lock:
                    tracked_order.current_price = new_price
                    tracked_order.last_adjustment = datetime.now()
                    tracked_order.adjustment_count += 1
                    
                self.logger.info(
                    f"📈 Adjusted order {tracked_order.order_id} price: "
                    f"${tracked_order.current_price:.2f} -> ${new_price:.2f} "
                    f"(Adjustment #{tracked_order.adjustment_count})"
                )
            else:
                self.logger.error(f"❌ Failed to adjust order {tracked_order.order_id}: {result.get('error')}")
                
        except Exception as e:
            self.logger.error(f"❌ Error adjusting order price: {e}")
            
    def get_tracking_status(self) -> Dict[str, Any]:
        """Get current tracking status for monitoring"""
        with self.lock:
            return {
                'service_running': self.running,
                'tracked_orders_count': len(self.tracked_orders),
                'tracked_orders': [
                    {
                        'order_id': order_id,
                        'symbol': order.symbol,
                        'current_price': order.current_price,
                        'adjustment_count': order.adjustment_count,
                        'created_at': order.created_at.isoformat(),
                        'last_adjustment': order.last_adjustment.isoformat() if order.last_adjustment else None
                    }
                    for order_id, order in self.tracked_orders.items()
                ]
            }