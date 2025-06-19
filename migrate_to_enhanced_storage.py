#!/usr/bin/env python3
"""
Migration Script for Enhanced Position Storage
Migrates existing positions to the new enhanced storage system
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any

from delta_backend import DeltaBackend
from enhanced_position_storage import EnhancedStrategyPositionStorage
from position_chain_detector import PositionChainDetector
from strategy_aware_analyzer import StrategyAwareAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def migrate_positions():
    """Migrate positions from live tracker to enhanced storage"""
    
    logger.info("🚀 Starting migration to enhanced position storage")
    
    try:
        # Initialize components
        logger.info("📦 Initializing components...")
        
        # Create delta backend instance
        tracker = DeltaBackend()
        
        # Initialize storage and analyzer
        storage = EnhancedStrategyPositionStorage()
        chain_detector = PositionChainDetector()
        analyzer = StrategyAwareAnalyzer(storage, tracker, chain_detector)
        
        # Start the tracker to get live positions
        logger.info("🔄 Starting position tracker...")
        tracker.initialize()
        
        # Wait for positions to load
        logger.info("⏳ Waiting for positions to load...")
        time.sleep(5)
        
        # Get current positions
        with tracker.positions_lock:
            positions = list(tracker.positions.values())
        
        logger.info(f"📊 Found {len(positions)} positions to migrate")
        
        # Migrate positions
        migrated_count = 0
        for position in positions:
            try:
                # Store position in enhanced storage
                success = storage.update_position_with_strategy(position)
                if success:
                    migrated_count += 1
                else:
                    logger.warning(f"⚠️ Failed to migrate position: {position.get('position_key')}")
            except Exception as e:
                logger.error(f"❌ Error migrating position {position.get('position_key')}: {e}")
        
        logger.info(f"✅ Migrated {migrated_count}/{len(positions)} positions")
        
        # Detect and store strategies
        logger.info("🔍 Detecting position strategies...")
        detected_strategies = storage.detect_and_store_strategy(positions, chain_detector)
        logger.info(f"✅ Detected {len(detected_strategies)} strategies")
        
        # Test performance
        logger.info("⚡ Testing performance...")
        
        # Test 1: Old method (portfolio analyzer)
        from portfolio_analyzer import PortfolioAnalyzer
        old_analyzer = PortfolioAnalyzer(tracker)
        
        start_time = time.time()
        old_snapshot = old_analyzer.analyze_current_portfolio()
        old_time = (time.time() - start_time) * 1000
        logger.info(f"🐌 Old analysis time: {old_time:.1f}ms")
        
        # Test 2: New method (enhanced storage)
        start_time = time.time()
        new_analysis = analyzer.analyze_portfolio_complete()
        new_time = new_analysis['processing_time_ms']
        logger.info(f"🚀 New analysis time: {new_time:.1f}ms")
        
        # Calculate improvement
        improvement = (old_time / new_time) if new_time > 0 else 0
        logger.info(f"📈 Performance improvement: {improvement:.1f}x faster!")
        
        # Verify data integrity
        logger.info("🔍 Verifying data integrity...")
        
        # Compare allocations
        old_allocations = {
            'asset': old_snapshot.asset_allocation,
            'duration': old_snapshot.duration_allocation,
            'strategy': old_snapshot.strategy_allocation
        }
        
        new_allocations = new_analysis['allocations']
        
        # Check for major discrepancies
        discrepancies = []
        for alloc_type in ['asset_allocation', 'duration_allocation', 'strategy_allocation']:
            old_data = old_allocations.get(alloc_type.replace('_allocation', ''), {})
            new_data = new_allocations.get(alloc_type, {})
            
            for category in set(list(old_data.keys()) + list(new_data.keys())):
                old_pct = old_data.get(category, 0)
                new_pct = new_data.get(category, 0)
                
                if abs(old_pct - new_pct) > 0.1:  # More than 0.1% difference
                    discrepancies.append(f"{alloc_type} - {category}: Old={old_pct:.2f}%, New={new_pct:.2f}%")
        
        if discrepancies:
            logger.warning("⚠️ Found allocation discrepancies:")
            for disc in discrepancies:
                logger.warning(f"  - {disc}")
        else:
            logger.info("✅ Data integrity verified - allocations match!")
        
        # Summary
        logger.info("\n" + "="*50)
        logger.info("📊 MIGRATION SUMMARY")
        logger.info("="*50)
        logger.info(f"✅ Positions migrated: {migrated_count}/{len(positions)}")
        logger.info(f"✅ Strategies detected: {len(detected_strategies)}")
        logger.info(f"✅ Performance improvement: {improvement:.1f}x")
        logger.info(f"✅ Old analysis time: {old_time:.1f}ms")
        logger.info(f"✅ New analysis time: {new_time:.1f}ms")
        logger.info("="*50)
        
        # Provide strategy breakdown
        if detected_strategies:
            logger.info("\n📈 Strategy Breakdown:")
            strategy_types = {}
            for strategy in detected_strategies:
                st = strategy['type']
                strategy_types[st] = strategy_types.get(st, 0) + 1
            
            for st, count in sorted(strategy_types.items()):
                logger.info(f"  - {st}: {count}")
        
        logger.info("\n✅ Migration completed successfully!")
        
        # Stop the tracker
        tracker.stop()
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise

def test_api_endpoints():
    """Test the new API endpoints"""
    import requests
    
    logger.info("\n🧪 Testing new API endpoints...")
    
    base_url = "http://localhost:5001"
    
    # Test 1: Fast analysis
    logger.info("Testing /api/rebalancing/analyze-fast...")
    try:
        response = requests.post(f"{base_url}/api/rebalancing/analyze-fast", json={})
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                logger.info(f"✅ Fast analysis: {data['performance']['processing_time_ms']:.1f}ms")
            else:
                logger.error(f"❌ Fast analysis failed: {data.get('error')}")
        else:
            logger.error(f"❌ Fast analysis returned {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Failed to test fast analysis: {e}")
    
    # Test 2: Strategy summary
    logger.info("Testing /api/positions/strategy-summary...")
    try:
        response = requests.get(f"{base_url}/api/positions/strategy-summary")
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                summary = data.get('summary', {})
                logger.info(f"✅ Strategy summary: {summary.get('total_strategies', 0)} strategies")
            else:
                logger.error(f"❌ Strategy summary failed: {data.get('error')}")
        else:
            logger.error(f"❌ Strategy summary returned {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Failed to test strategy summary: {e}")
    
    # Test 3: Smart recommendations
    logger.info("Testing /api/rebalancing/recommendations-smart...")
    try:
        response = requests.post(f"{base_url}/api/rebalancing/recommendations-smart", json={})
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                recs = data.get('recommendations', [])
                logger.info(f"✅ Smart recommendations: {len(recs)} recommendations")
            else:
                logger.error(f"❌ Smart recommendations failed: {data.get('error')}")
        else:
            logger.error(f"❌ Smart recommendations returned {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Failed to test smart recommendations: {e}")

if __name__ == "__main__":
    # Run migration
    migrate_positions()
    
    # Test API endpoints if server is running
    logger.info("\n🧪 Would you like to test the API endpoints? Make sure the server is running on port 5001.")
    logger.info("Press Enter to test, or Ctrl+C to skip...")
    try:
        input()
        test_api_endpoints()
    except KeyboardInterrupt:
        logger.info("\n✅ Migration completed. API testing skipped.")