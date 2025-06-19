# Claude Code Implementation Prompt: Enhanced Position Storage with Strategy Tracking

## Project Context
I have a TastyTracker portfolio management system that currently recalculates allocation attributes (bullish/bearish/neutral, DTE buckets) every time the "Analyze Portfolio" button is clicked. This is inefficient. I want to implement an enhanced position storage system that:

1. Stores static attributes (asset type, option details, strategy assignments)
2. Calculates dynamic attributes on-demand (strategy category based on current delta, duration category based on current date)
3. Detects and tracks position strategies (spreads, condors, etc.)
4. Integrates with existing allocation rules for smarter rebalancing

## Current System Structure
```
delta_backend.py - Live position tracking with delta/price updates
portfolio_analyzer.py - Calculates allocations (currently inefficient)
allocation_rules_manager.py - Manages allocation rules and compliance
position_chain_detector.py - Detects option strategies from positions
automated_rebalancer.py - Generates rebalancing recommendations
templates/dashboard.html - UI with "Analyze Portfolio" button
```

## Implementation Requirements

### Phase 1: Database Setup
1. Create new SQLite database `positions_strategy_enhanced.db` with tables:
   - `positions_enhanced` - Static position data with strategy links
   - `strategy_groups` - Detected strategies with metadata
   - `position_chains` - Chain detection results
   - `allocation_cache` - Performance cache

2. Implement `EnhancedStrategyPositionStorage` class with methods:
   - `update_position_with_strategy()` - Store static attributes
   - `detect_and_store_strategy()` - Use chain detector to identify strategies
   - `get_positions_with_dynamic_data()` - Merge static + live data
   - `calculate_allocation_summary()` - Fast allocation calculation

### Phase 2: Integration Layer
1. Create `StrategyAwareAnalyzer` that:
   - Syncs live positions from delta_backend
   - Detects strategies using position_chain_detector
   - Calculates dynamic attributes (delta-based strategy category, date-based DTE)
   - Returns comprehensive analysis in <100ms

2. Modify `automated_rebalancer.py` to:
   - Use pre-calculated allocations from enhanced storage
   - Consider existing strategies when making recommendations
   - Avoid duplicating strategies in same underlying

### Phase 3: API Routes
1. Add new Flask routes in `rebalancing_routes.py`:
   - `/api/rebalancing/analyze-fast` - Uses enhanced storage
   - `/api/rebalancing/sync-strategies` - Manual strategy detection
   - `/api/positions/strategy-summary` - Get strategy breakdown

2. Deprecate old `/api/rebalancing/trigger` endpoint

### Phase 4: Frontend Updates
1. Modify dashboard.html JavaScript:
   - Update `analyzePortfolio()` to use new fast endpoint
   - Add strategy visualization in auto recommendations
   - Show processing time improvement

### Phase 5: Migration & Testing
1. Create migration script to:
   - Load existing positions from delta_backend
   - Detect current strategies
   - Populate enhanced storage
   - Verify data integrity

2. Add background sync process:
   - Update static attributes every 5 minutes
   - Clear cache when positions change
   - Log performance metrics

## Key Design Decisions

### Static vs Dynamic Attributes
**Static (stored once):**
- Asset category (equity/option)
- Option details (strike, expiration, type)
- Strategy assignments and group IDs
- Sector classification

**Dynamic (calculated on-demand):**
- Strategy category (bullish/bearish/neutral) - changes with delta
- Duration category (DTE buckets) - changes daily
- Market values and Greeks - from live data

### Performance Targets
- Portfolio analysis: <100ms (from 1-2 seconds)
- Strategy detection: Run async, not blocking UI
- Cache TTL: 60 seconds for allocations

## Implementation Order
1. First, create database schema and storage classes
2. Build integration layer with existing position chain detector
3. Add parallel API routes (keep old ones working)
4. Update frontend to use new endpoints
5. Run migration and verify performance
6. Deprecate old code paths

## Testing Checklist
- [ ] Verify strategy detection accuracy
- [ ] Confirm allocation calculations match old system
- [ ] Test performance improvement (target 20x faster)
- [ ] Validate dynamic attributes update correctly
- [ ] Check cache invalidation on position changes
- [ ] Ensure backward compatibility during migration

## Example Code Structure
```python
# enhanced_position_storage.py
class EnhancedStrategyPositionStorage:
    def __init__(self, db_path="positions_strategy_enhanced.db"):
        # Initialize database with proper indexes
        
    def update_position_with_strategy(self, position, strategy_info):
        # Store static attributes only
        
    def calculate_dynamic_attributes(self, position, live_data):
        # Calculate strategy category from current delta
        # Calculate duration category from current date vs expiration

# strategy_aware_analyzer.py  
class StrategyAwareAnalyzer:
    def analyze_portfolio_complete(self, account_numbers):
        # 1. Get live positions (in memory)
        # 2. Detect strategies if needed
        # 3. Merge static + dynamic data
        # 4. Return comprehensive analysis
```

## Success Criteria
1. "Analyze Portfolio" responds in <100ms
2. Strategy assignments persist between sessions
3. Recommendations consider existing strategies
4. No data loss during migration
5. UI shows detected strategies clearly

Please help me implement this system step by step, starting with the database schema and storage classes. Make sure to preserve all existing functionality while adding these improvements.