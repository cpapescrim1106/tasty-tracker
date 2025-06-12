#!/usr/bin/env python3
"""
Trade Journal Flask Routes
Web API endpoints for the trade journal functionality
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, render_template
from typing import Optional, Dict, Any

# Import trade journal components
from trade_journal_manager import TradeJournalManager
from tastytrade import Session

# Create blueprint for trade journal routes
trade_journal_bp = Blueprint('trade_journal', __name__)

# Global trade journal manager (will be initialized when needed)
journal_manager = None

def get_journal_manager():
    """Get or create trade journal manager with TastyTrade session"""
    global journal_manager
    
    if journal_manager is None:
        try:
            # Get credentials from environment
            username = os.getenv('TASTYTRADE_LOGIN')
            password = os.getenv('TASTYTRADE_PASSWORD')
            
            logging.info(f"Trade journal init - username: {username is not None}, password: {password is not None}")
            
            if not username or not password:
                raise Exception("TastyTrade credentials not found in environment")
            
            # Create session and journal manager
            session = Session(username, password)
            journal_manager = TradeJournalManager(session)
            logging.info("✅ Trade journal manager initialized")
            
        except Exception as e:
            logging.error(f"❌ Failed to initialize trade journal: {e}")
            raise
    
    return journal_manager

@trade_journal_bp.route('/api/trade-journal/status')
def journal_status():
    """Get trade journal system status"""
    try:
        manager = get_journal_manager()
        status = manager.get_trade_journal_status()
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@trade_journal_bp.route('/api/trade-journal/process', methods=['POST'])
def process_trades():
    """Process account transactions into trade journal"""
    try:
        data = request.get_json() or {}
        account_number = data.get('account_number')
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        enhance_data = data.get('enhance_data', True)
        
        if not account_number:
            return jsonify({'success': False, 'error': 'Account number required'}), 400
        
        # Parse dates if provided
        start_date = None
        end_date = None
        
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        
        manager = get_journal_manager()
        result = manager.process_account_trades(
            account_number=account_number,
            start_date=start_date,
            end_date=end_date,
            enhance_data=enhance_data
        )
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        logging.error(f"Error processing trades: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trade_journal_bp.route('/api/trade-journal/trades')
def get_trades():
    """Get trade journal entries with optional filters"""
    try:
        account_number = request.args.get('account_number')
        symbol = request.args.get('symbol')
        status = request.args.get('status')
        limit = int(request.args.get('limit', 100))
        
        manager = get_journal_manager()
        trades = manager.journal.get_trades(
            account_number=account_number,
            symbol=symbol,
            status=status,
            limit=limit
        )
        
        # Convert trades to dictionaries for JSON serialization
        trades_data = []
        for trade in trades:
            trade_dict = {
                'trade_id': trade.trade_id,
                'account_number': trade.account_number,
                'underlying_symbol': trade.underlying_symbol,
                'strategy_type': trade.strategy_type,
                'entry_date': trade.entry_date.isoformat() if trade.entry_date else None,
                'exit_date': trade.exit_date.isoformat() if trade.exit_date else None,
                'status': trade.status.value if hasattr(trade.status, 'value') else str(trade.status),
                'dte_at_entry': trade.dte_at_entry,
                'dte_at_exit': trade.dte_at_exit,
                'underlying_price_entry': trade.underlying_price_entry,
                'underlying_price_exit': trade.underlying_price_exit,
                'strike_short': trade.strike_short,
                'strike_long': trade.strike_long,
                'strike_width': trade.strike_width,
                'contracts': trade.contracts,
                'entry_credit': trade.entry_credit,
                'entry_debit': trade.entry_debit,
                'exit_credit': trade.exit_credit,
                'exit_debit': trade.exit_debit,
                'max_profit': trade.max_profit,
                'max_loss': trade.max_loss,
                'realized_pnl': trade.realized_pnl,
                'realized_pnl_pct': trade.realized_pnl_pct,
                'return_on_capital': trade.return_on_capital,
                'days_held': trade.days_held,
                'winner': trade.winner,
                'outcome_tag': trade.outcome_tag,
                'pop_entry': trade.pop_entry,
                'p50_entry': trade.p50_entry,
                'pot_entry': trade.pot_entry,
                'vix_level_entry': trade.vix_level_entry,
                'spx_price_entry': trade.spx_price_entry,
                'iv_rank_entry': trade.iv_rank_entry,
                'total_commissions': trade.total_commissions,
                'total_fees': trade.total_fees,
                'net_pnl_after_fees': trade.net_pnl_after_fees,
                'managed_at_50pct': trade.managed_at_50pct,
                'trade_notes': trade.trade_notes,
                'delta_entry': trade.delta_entry,
                'theta_entry': trade.theta_entry,
                'gamma_entry': trade.gamma_entry,
                'vega_entry': trade.vega_entry
            }
            trades_data.append(trade_dict)
        
        return jsonify({'success': True, 'data': trades_data})
        
    except Exception as e:
        logging.error(f"Error getting trades: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trade_journal_bp.route('/api/trade-journal/report')
def generate_report():
    """Generate comprehensive trade performance report"""
    try:
        account_number = request.args.get('account_number')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        # Parse dates if provided
        start_date = None
        end_date = None
        
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        
        manager = get_journal_manager()
        report = manager.generate_comprehensive_report(
            account_number=account_number,
            start_date=start_date,
            end_date=end_date
        )
        
        return jsonify({'success': True, 'data': report})
        
    except Exception as e:
        logging.error(f"Error generating report: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trade_journal_bp.route('/api/trade-journal/enhance', methods=['POST'])
def enhance_trades():
    """Enhance existing trades with probability calculations and market context"""
    try:
        data = request.get_json() or {}
        account_number = data.get('account_number')
        trade_ids = data.get('trade_ids')  # Optional list of specific trade IDs
        
        manager = get_journal_manager()
        result = manager.enhance_all_trades(
            account_number=account_number,
            trade_ids=trade_ids
        )
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        logging.error(f"Error enhancing trades: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trade_journal_bp.route('/api/trade-journal/export')
def export_trades():
    """Export trades to CSV format"""
    try:
        account_number = request.args.get('account_number')
        
        manager = get_journal_manager()
        
        # Create temporary file for export
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as tmp_file:
            success = manager.export_trades_to_csv(tmp_file.name, account_number)
            
            if success:
                # Read the CSV content
                with open(tmp_file.name, 'r') as f:
                    csv_content = f.read()
                
                # Clean up temp file
                os.unlink(tmp_file.name)
                
                return jsonify({
                    'success': True,
                    'data': {
                        'csv_content': csv_content,
                        'filename': f'trades_{account_number or "all"}_{datetime.now().strftime("%Y%m%d")}.csv'
                    }
                })
            else:
                return jsonify({'success': False, 'error': 'Export failed'}), 500
                
    except Exception as e:
        logging.error(f"Error exporting trades: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trade_journal_bp.route('/api/trade-journal/summary')
def get_summary():
    """Get trade journal summary statistics"""
    try:
        account_number = request.args.get('account_number')
        
        manager = get_journal_manager()
        summary = manager.journal.get_trade_summary(account_number)
        
        return jsonify({'success': True, 'data': summary})
        
    except Exception as e:
        logging.error(f"Error getting summary: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trade_journal_bp.route('/api/trade-journal/market-snapshot', methods=['POST'])
def capture_market_snapshot():
    """Manually capture current market regime snapshot"""
    try:
        manager = get_journal_manager()
        
        # Capture current market regime
        regime = manager.market_capture.get_current_market_regime()
        
        # Save to database
        success = manager.market_capture.save_market_snapshot(regime, manager.db_path)
        
        if success:
            return jsonify({
                'success': True,
                'data': {
                    'timestamp': regime.timestamp.isoformat(),
                    'spx_price': regime.spx_price,
                    'vix_level': regime.vix_level,
                    'overall_regime': regime.overall_regime,
                    'volatility_regime': regime.volatility_regime
                }
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save market snapshot'}), 500
            
    except Exception as e:
        logging.error(f"Error capturing market snapshot: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def create_trade_journal_routes(app):
    """Register trade journal routes with the Flask app"""
    app.register_blueprint(trade_journal_bp)
    logging.info("✅ Trade journal routes registered")