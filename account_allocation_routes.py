#!/usr/bin/env python3
"""
Account Allocation Routes
Flask routes for managing per-account portfolio limits and allocations
"""

import logging
from flask import Blueprint, jsonify, request
from typing import Optional, Dict, Any, List

# Import position chain detector if available
try:
    from position_chain_detector import PositionChainDetector
except ImportError:
    PositionChainDetector = None

# Create blueprint
account_allocation_bp = Blueprint('account_allocation', __name__)
logger = logging.getLogger(__name__)

# Global tracker instance (will be set by main app)
tracker_instance = None

# Account portfolio limits (stored in memory for now, should be in database)
ACCOUNT_LIMITS = {
    '5WX84566': 30000,  # Joint account - $30K active trading limit
    '5WU39639': 0       # Roth IRA - No active trading
}

def init_account_allocation_routes(tracker):
    """Initialize routes with tracker instance"""
    global tracker_instance
    tracker_instance = tracker
    logger.info("✅ Initialized account allocation routes")

@account_allocation_bp.route('/api/account-limits', methods=['POST'])
def update_account_limit():
    """Update portfolio limit for an account"""
    try:
        data = request.get_json()
        account_number = data.get('account_number')
        portfolio_limit = float(data.get('portfolio_limit', 0))
        
        if not account_number:
            return jsonify({'success': False, 'error': 'Account number required'}), 400
            
        # Update limit in memory (should be persisted to database)
        ACCOUNT_LIMITS[account_number] = portfolio_limit
        
        logger.info(f"💰 Updated portfolio limit for {account_number}: ${portfolio_limit:,.0f}")
        
        return jsonify({
            'success': True,
            'account_number': account_number,
            'portfolio_limit': portfolio_limit
        })
        
    except Exception as e:
        logger.error(f"❌ Error updating account limit: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@account_allocation_bp.route('/api/account-allocations', methods=['GET'])
def get_account_allocations():
    """Get current allocation status for all accounts"""
    try:
        if not tracker_instance:
            return jsonify({'success': False, 'error': 'Tracker not initialized'}), 500
            
        allocations = []
        
        # Get positions from tracker
        positions = tracker_instance.positions_data if hasattr(tracker_instance, 'positions_data') else {}
        
        for account_number, limit in ACCOUNT_LIMITS.items():
            # Calculate active allocation (non-long-term positions)
            active_allocation = 0
            long_term_net_liq = 0
            equities_allocation = 0
            total_allocation = 0
            
            # Get positions for this account
            account_positions = positions.get(account_number, {})
            
            for symbol, position in account_positions.items():
                net_liq = position.get('net_liquidation_value', 0)
                total_allocation += net_liq
                
                # Check if position is marked as long-term
                is_long_term = _is_position_long_term(account_number, symbol)
                
                if is_long_term:
                    long_term_net_liq += net_liq
                else:
                    active_allocation += abs(net_liq)  # Use absolute value for short positions
                    
                # Check if equity position
                if _is_equity_position(symbol):
                    equities_allocation += abs(net_liq)
            
            # Calculate percentages
            equities_pct = (equities_allocation / total_allocation * 100) if total_allocation > 0 else 0
            
            allocations.append({
                'account_number': account_number,
                'portfolio_limit': limit,
                'active_allocation': active_allocation,
                'long_term_net_liq': long_term_net_liq,
                'total_allocation': total_allocation,
                'equities_pct': equities_pct,
                'equities_allocation': equities_allocation,
                'utilization_pct': (active_allocation / limit * 100) if limit > 0 else 0
            })
        
        return jsonify({
            'success': True,
            'allocations': allocations
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting account allocations: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def _is_position_long_term(account: str, symbol: str) -> bool:
    """Check if position is marked as long-term"""
    # This should check the long-term flags from screener_backend
    # For now, return False as default
    if hasattr(tracker_instance, 'screener_engine'):
        return tracker_instance.screener_engine.is_position_long_term(account, symbol)
    return False

def _is_equity_position(symbol: str) -> bool:
    """Check if position is an equity (stock) position"""
    # Simple check - if no special characters, it's likely a stock
    # Options have spaces, futures have slashes, etc.
    return ' ' not in symbol and '/' not in symbol and len(symbol) <= 5