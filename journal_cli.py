#!/usr/bin/env python3
"""
TastyTracker Trade Journal CLI
Command-line interface for trade journal operations
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from trade_journal_manager import TradeJournalManager
from tastytrade import Session

def setup_logging(verbose: bool = False):
    """Setup logging configuration"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def get_tastytrade_session() -> Session:
    """Initialize TastyTrade session"""
    try:
        # Get credentials from environment variables
        username = os.getenv('TASTYTRADE_USERNAME')
        password = os.getenv('TASTYTRADE_PASSWORD')
        
        if not username or not password:
            print("❌ Please set TASTYTRADE_USERNAME and TASTYTRADE_PASSWORD environment variables")
            sys.exit(1)
        
        session = Session(username, password)
        print("✅ Connected to TastyTrade API")
        return session
        
    except Exception as e:
        print(f"❌ Failed to connect to TastyTrade: {e}")
        sys.exit(1)

def process_account_command(args):
    """Process trades for an account"""
    session = get_tastytrade_session()
    manager = TradeJournalManager(session, args.database)
    
    start_date = None
    end_date = None
    
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    
    print(f"🔄 Processing trades for account {args.account}")
    
    result = manager.process_account_trades(
        account_number=args.account,
        start_date=start_date,
        end_date=end_date,
        enhance_data=not args.no_enhance
    )
    
    if result['success']:
        print(f"✅ {result['message']}")
        if 'enhancement_summary' in result:
            enhancement = result['enhancement_summary']
            print(f"📊 Enhanced {enhancement['trades_enhanced']} trades")
            if enhancement['trades_failed'] > 0:
                print(f"⚠️ {enhancement['trades_failed']} trades failed enhancement")
    else:
        print(f"❌ {result['message']}")

def generate_report_command(args):
    """Generate comprehensive trade report"""
    session = get_tastytrade_session()
    manager = TradeJournalManager(session, args.database)
    
    start_date = None
    end_date = None
    
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    
    print("📊 Generating comprehensive trade report...")
    
    report = manager.generate_comprehensive_report(
        account_number=args.account,
        start_date=start_date,
        end_date=end_date
    )
    
    if 'error' in report:
        print(f"❌ Error generating report: {report['error']}")
        return
    
    # Print summary
    overall = report['overall_performance']
    print(f"\n📈 TRADE JOURNAL SUMMARY")
    print(f"=" * 50)
    print(f"Period: {args.start_date or 'All time'} to {args.end_date or 'Present'}")
    print(f"Total Trades: {report['analysis_period']['total_trades']}")
    print(f"Closed Trades: {report['analysis_period']['closed_trades']}")
    print(f"Win Rate: {overall['win_rate']:.1f}%")
    print(f"Total P&L: ${overall['total_pnl']:.2f}")
    print(f"Net P&L (after fees): ${overall['net_pnl_after_fees']:.2f}")
    print(f"Avg P&L per Trade: ${overall['avg_pnl_per_trade']:.2f}")
    print(f"Avg Days Held: {overall['avg_days_held']:.1f}")
    print(f"Total Commissions: ${overall['total_commissions']:.2f}")
    
    # Strategy breakdown
    if report['strategy_breakdown']:
        print(f"\n📋 STRATEGY BREAKDOWN")
        print(f"=" * 50)
        for strategy, stats in report['strategy_breakdown'].items():
            print(f"{strategy}:")
            print(f"  Trades: {stats['count']}")
            print(f"  Win Rate: {stats['win_rate']:.1f}%")
            print(f"  Avg P&L: ${stats['avg_pnl']:.2f}")
            print(f"  Avg DTE: {stats['avg_dte']:.0f}")
            if stats['avg_pop'] > 0:
                print(f"  Avg POP: {stats['avg_pop']:.1f}%")
            print()
    
    # POP Analysis
    if report['pop_analysis']:
        print(f"\n🎯 POP vs ACTUAL PERFORMANCE")
        print(f"=" * 50)
        for bucket, analysis in report['pop_analysis'].items():
            print(f"{bucket.replace('_', ' ').title()}:")
            print(f"  Trades: {analysis['trade_count']}")
            print(f"  Predicted Win Rate: {analysis['predicted_win_rate']:.1f}%")
            print(f"  Actual Win Rate: {analysis['actual_win_rate']:.1f}%")
            print(f"  POP Accuracy: ±{analysis['pop_accuracy']:.1f}%")
            print()
    
    # Save detailed report if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"📄 Detailed report saved to {args.output}")

def export_command(args):
    """Export trades to CSV"""
    session = get_tastytrade_session()
    manager = TradeJournalManager(session, args.database)
    
    print(f"📤 Exporting trades to {args.output}")
    
    success = manager.export_trades_to_csv(
        file_path=args.output,
        account_number=args.account
    )
    
    if success:
        print("✅ Export completed successfully")
    else:
        print("❌ Export failed")

def status_command(args):
    """Show trade journal system status"""
    session = get_tastytrade_session()
    manager = TradeJournalManager(session, args.database)
    
    print("🔍 Trade Journal System Status")
    print("=" * 40)
    
    status = manager.get_trade_journal_status()
    
    if 'error' in status:
        print(f"❌ Error: {status['error']}")
        return
    
    print(f"Database: {status['database_path']}")
    print(f"Auto Capture: {'Enabled' if status['auto_capture_enabled'] else 'Disabled'}")
    print(f"Auto Probabilities: {'Enabled' if status['auto_probability_calc'] else 'Disabled'}")
    print(f"Auto Market Data: {'Enabled' if status['auto_market_snapshot'] else 'Disabled'}")
    print(f"System Health: {status['system_health']}")
    
    if status['last_market_snapshot']:
        print(f"Last Market Snapshot: {status['last_market_snapshot']}")
    
    if 'trade_summary' in status:
        summary = status['trade_summary']
        print(f"\nTrade Summary:")
        print(f"  Total Trades: {summary.get('total_trades', 0)}")
        print(f"  Open Trades: {summary.get('open_trades', 0)}")
        print(f"  Closed Trades: {summary.get('closed_trades', 0)}")
        print(f"  Win Rate: {summary.get('win_rate', 0):.1f}%")
        print(f"  Total P&L: ${summary.get('total_pnl', 0):.2f}")

def enhance_command(args):
    """Enhance existing trades with additional data"""
    session = get_tastytrade_session()
    manager = TradeJournalManager(session, args.database)
    
    print(f"🔧 Enhancing trades with probabilities and market context")
    
    result = manager.enhance_all_trades(account_number=args.account)
    
    print(f"✅ Enhanced {result['trades_enhanced']} trades")
    if result['trades_failed'] > 0:
        print(f"⚠️ {result['trades_failed']} trades failed enhancement")

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='TastyTracker Trade Journal CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all trades for an account
  python journal_cli.py process --account 12345678
  
  # Process trades for a specific date range
  python journal_cli.py process --account 12345678 --start-date 2024-01-01 --end-date 2024-12-31
  
  # Generate a comprehensive report
  python journal_cli.py report --account 12345678 --output report.json
  
  # Export trades to CSV
  python journal_cli.py export --account 12345678 --output trades.csv
  
  # Check system status
  python journal_cli.py status
  
  # Enhance existing trades
  python journal_cli.py enhance --account 12345678
        """
    )
    
    parser.add_argument('--database', '-d', default='trade_journal.db',
                       help='Path to trade journal database (default: trade_journal.db)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Process command
    process_parser = subparsers.add_parser('process', help='Process account transactions into trade journal')
    process_parser.add_argument('--account', '-a', required=True,
                               help='TastyTrade account number')
    process_parser.add_argument('--start-date', '-s',
                               help='Start date for processing (YYYY-MM-DD)')
    process_parser.add_argument('--end-date', '-e',
                               help='End date for processing (YYYY-MM-DD)')
    process_parser.add_argument('--no-enhance', action='store_true',
                               help='Skip data enhancement (probabilities, market context)')
    
    # Report command
    report_parser = subparsers.add_parser('report', help='Generate comprehensive trade report')
    report_parser.add_argument('--account', '-a',
                              help='TastyTrade account number (optional)')
    report_parser.add_argument('--start-date', '-s',
                              help='Start date for report (YYYY-MM-DD)')
    report_parser.add_argument('--end-date', '-e',
                              help='End date for report (YYYY-MM-DD)')
    report_parser.add_argument('--output', '-o',
                              help='Save detailed report to JSON file')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export trades to CSV')
    export_parser.add_argument('--account', '-a',
                              help='TastyTrade account number (optional)')
    export_parser.add_argument('--output', '-o', required=True,
                              help='Output CSV file path')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show system status')
    
    # Enhance command
    enhance_parser = subparsers.add_parser('enhance', help='Enhance existing trades with additional data')
    enhance_parser.add_argument('--account', '-a',
                               help='TastyTrade account number (optional)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Setup logging
    setup_logging(args.verbose)
    
    # Execute command
    try:
        if args.command == 'process':
            process_account_command(args)
        elif args.command == 'report':
            generate_report_command(args)
        elif args.command == 'export':
            export_command(args)
        elif args.command == 'status':
            status_command(args)
        elif args.command == 'enhance':
            enhance_command(args)
        else:
            print(f"Unknown command: {args.command}")
            parser.print_help()
    
    except KeyboardInterrupt:
        print("\n🛑 Operation cancelled by user")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()