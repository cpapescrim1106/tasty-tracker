# Plan: Add ATM Straddle-Based Strike Selection to Strategy Builder

## Overview
Add ATM straddle-based strike selection where the selection value (0-200%) represents a percentage of the ATM straddle price to add/subtract from the underlying price for strike selection.

## Current System Analysis

### Existing Strike Selection Methods
1. **`atm`** - At The Money (closest to underlying)
2. **`offset`** - Strike offset (±N strikes from ATM)
3. **`percentage`** - Percentage from current price
4. **`premium`** - Premium target selection

### Key Findings
- Delta selection was removed due to API limitations (greeks only via WebSocket)
- Option chains are cached for 5 minutes
- Multi-leg strategies use `StrategyLeg` dataclass
- No existing straddle calculation code

## Implementation Plan

### Step 1: Add ATM Straddle Calculation Method
**File**: `strategy_engine.py`
**Location**: Add after `find_closest_to_strike()` method (around line 870)

```python
def calculate_atm_straddle_price(self, symbol: str, underlying_price: float, 
                                 expiration_date: str, all_options: list) -> float:
    """Calculate ATM straddle price (call + put at ATM strike)"""
    try:
        # Find ATM strike
        strikes = sorted(set(opt['strike-price'] for opt in all_options))
        atm_strike = min(strikes, key=lambda x: abs(x - underlying_price))
        
        # Get ATM call and put
        atm_call = next((opt for opt in all_options 
                        if opt['strike-price'] == atm_strike 
                        and opt['option-type'] == 'C'), None)
        atm_put = next((opt for opt in all_options 
                       if opt['strike-price'] == atm_strike 
                       and opt['option-type'] == 'P'), None)
        
        if atm_call and atm_put:
            # Calculate mid prices
            call_mid = (atm_call['bid'] + atm_call['ask']) / 2
            put_mid = (atm_put['bid'] + atm_put['ask']) / 2
            return call_mid + put_mid
        
        return 0.0
    except Exception as e:
        logger.error(f"Error calculating ATM straddle: {e}")
        return 0.0
```

### Step 2: Update Strike Selection Logic
**File**: `strategy_engine.py`
**Location**: `find_option_for_leg()` method (line 825)

Add new case after the `premium` case:
```python
elif selection_method == 'atm_straddle':
    # Calculate ATM straddle price
    atm_straddle_price = self.calculate_atm_straddle_price(
        symbol, underlying_price, expiration_date, all_options
    )
    
    if atm_straddle_price == 0:
        logger.error("Failed to calculate ATM straddle price")
        return None
    
    # Calculate offset (0-200% of straddle price)
    offset = atm_straddle_price * (selection_value / 100.0)
    
    # Determine target price based on option type
    if option_type == 'C':  # Calls go above
        target_price = underlying_price + offset
    else:  # Puts go below
        target_price = underlying_price - offset
    
    # Find closest strike to target price
    return self.find_closest_to_strike(all_options, target_price)
```

### Step 3: Update Frontend UI
**File**: `static/js/strategy-builder.js`
**Location**: Strike selection dropdown (line 646)

Add new option:
```javascript
React.createElement('option', { value: 'atm_straddle' }, 'ATM Straddle %')
```

Update help text (around line 660):
```javascript
const helpTexts = {
    atm: 'Select the strike closest to current price',
    offset: 'Select strikes N positions away from ATM',
    percentage: 'Select strike X% away from current price',
    premium: 'Select strike with minimum premium',
    atm_straddle: 'Select strike based on % of ATM straddle price (0-200%)'
};
```

Add validation for 0-200% range:
```javascript
if (leg.selection_method === 'atm_straddle' && 
    (parseFloat(value) < 0 || parseFloat(value) > 200)) {
    alert('ATM Straddle % must be between 0 and 200');
    return;
}
```

### Step 4: Update Database Schema Documentation
**File**: `workflow_database.py`
**Location**: StrategyLeg dataclass comment (line 30)

Update comment:
```python
selection_method: str  # "atm", "offset", "percentage", "premium", "atm_straddle"
```

### Step 5: Add Default Strategy Examples
**File**: `init_default_strategies.py`
**Location**: Add new strategy after existing ones

```python
# ATM Straddle-Based Iron Condor
{
    "name": "ATM Straddle Iron Condor",
    "description": "Iron condor with strikes based on ATM straddle price",
    "legs": [
        {"action": "sell", "option_type": "call", "selection_method": "atm_straddle", 
         "selection_value": 100, "quantity": 1},
        {"action": "buy", "option_type": "call", "selection_method": "atm_straddle", 
         "selection_value": 150, "quantity": 1},
        {"action": "sell", "option_type": "put", "selection_method": "atm_straddle", 
         "selection_value": 100, "quantity": 1},
        {"action": "buy", "option_type": "put", "selection_method": "atm_straddle", 
         "selection_value": 150, "quantity": 1}
    ],
    "is_manual": False
}
```

### Step 6: Testing & Validation
1. Test with various percentages (0%, 50%, 100%, 150%, 200%)
2. Verify strike selection for both calls and puts
3. Test multi-leg strategies (iron condors, butterflies)
4. Handle edge cases (no ATM available, wide spreads)
5. Verify caching works correctly

## Benefits
- More dynamic strike selection based on market volatility
- ATM straddle price reflects current implied volatility
- Perfect for iron condors and other volatility strategies
- Scales with market conditions automatically

## Next Steps
1. Implement ATM straddle calculation method
2. Update strike selection logic
3. Modify frontend UI
4. Test with live market data
5. Document usage examples

## Strategy Engine Fix Plan (Phase 2)

### Issues Identified

1. **Delta Fields Still Present**
   - Delta shows as 0 in output with note about "approximation"
   - Delta selection was removed but fields remain in data structures
   - Confusing for users since delta isn't actually available

2. **Iron Condor Strike Selection Logic Error**
   - When using offset method, long call strike ends up BELOW short call strike
   - Example: Short call at 640, Long call at 585 (should be reversed)
   - Root cause: Offset logic doesn't account for iron condor structure

3. **Validation Logic Contradiction**
   - Returns `valid: true` but also says "doesn't meet requirements"
   - `meets_premium_requirement: false` but validation still passes
   - Missing logic to fail validation when business rules aren't met

4. **Negative Net Premium Display**
   - Shows net premium as negative for debit spreads
   - While technically correct, it's confusing for users
   - Should show absolute value with clear credit/debit indicator

5. **Dead Code**
   - Lines 713-780: Commented delta selection code
   - Confusing and makes file harder to maintain

### Detailed Fix Implementation

#### Fix 1: Remove Delta Fields
**File**: `strategy_engine.py`

1. **Remove from OptionContract dataclass** (line 35):
   ```python
   # DELETE THIS LINE:
   delta: float = 0.0
   ```

2. **Remove from build_leg_data** (line 856):
   ```python
   # DELETE THIS LINE:
   'delta': option.delta,
   ```

3. **Remove from SpreadStrategy dataclass** (lines 628-629):
   ```python
   # DELETE THESE LINES:
   'net_delta': round((spread.short_leg.delta or 0) - (spread.long_leg.delta or 0), 4),
   ```

4. **Remove delta approximation warning** in `workflow_routes.py` (lines 571-599):
   ```python
   # DELETE OR UPDATE THESE LINES:
   has_delta_approximation = any(leg.get('delta', 0) == 0 for leg in sample_legs)
   'delta_approximated': has_delta_approximation
   ```

#### Fix 2: Iron Condor Strike Logic
**File**: `strategy_engine.py`

Add validation in `build_strategy_sample` method (after line 920):
```python
# Validate iron condor strike relationships
if len(legs) == 4:  # Potential iron condor
    put_legs = [(i, l) for i, l in enumerate(sample_legs) if l['option_type'] == 'put']
    call_legs = [(i, l) for i, l in enumerate(sample_legs) if l['option_type'] == 'call']
    
    if len(put_legs) == 2 and len(call_legs) == 2:
        # Sort by strike
        put_legs.sort(key=lambda x: x[1]['strike'])
        call_legs.sort(key=lambda x: x[1]['strike'])
        
        # Verify correct ordering
        short_put = next((l for _, l in put_legs if l['action'] == 'sell'), None)
        long_put = next((l for _, l in put_legs if l['action'] == 'buy'), None)
        short_call = next((l for _, l in call_legs if l['action'] == 'sell'), None)
        long_call = next((l for _, l in call_legs if l['action'] == 'buy'), None)
        
        if all([short_put, long_put, short_call, long_call]):
            # Fix strike ordering if needed
            if long_put['strike'] > short_put['strike']:
                self.logger.warning("⚠️ Fixing put spread strike order")
                put_legs[0][1]['strike'], put_legs[1][1]['strike'] = put_legs[1][1]['strike'], put_legs[0][1]['strike']
            
            if long_call['strike'] < short_call['strike']:
                self.logger.warning("⚠️ Fixing call spread strike order")
                call_legs[0][1]['strike'], call_legs[1][1]['strike'] = call_legs[1][1]['strike'], call_legs[0][1]['strike']
```

#### Fix 3: Validation Logic
**File**: `workflow_routes.py`

Update validation logic (around line 594):
```python
# After calculating meets_premium_req
if not meets_premium_req:
    validation_result['valid'] = False
    validation_result['errors'].append(
        f'Strategy net premium ${total_net_premium:.2f} is below minimum requirement ${strategy_min_premium:.2f}'
    )
```

#### Fix 4: Premium Display
**File**: `strategy_engine.py`

In `calculate_strategy_metrics` method (around line 950):
```python
# Add credit/debit indicator
is_credit = total_net_premium > 0
strategy_type_display = "Credit" if is_credit else "Debit"

return {
    'net_premium': abs(total_net_premium),  # Show absolute value
    'premium_type': strategy_type_display,   # "Credit" or "Debit"
    'max_profit': max_profit,
    'max_loss': abs(max_loss),  # Always positive
    # ... rest of metrics
}
```

#### Fix 5: Clean Dead Code
**File**: `strategy_engine.py`

Delete lines 713-780 (entire commented delta selection section)

### Testing Plan

1. **Test Iron Condor Creation**:
   ```json
   {
     "legs": [
       {"action": "sell", "option_type": "put", "selection_method": "atm_straddle", "selection_value": 100},
       {"action": "buy", "option_type": "put", "selection_method": "atm_straddle", "selection_value": 150},
       {"action": "sell", "option_type": "call", "selection_method": "atm_straddle", "selection_value": 100},
       {"action": "buy", "option_type": "call", "selection_method": "atm_straddle", "selection_value": 150}
     ]
   }
   ```
   - Verify: Long put strike < Short put strike < Short call strike < Long call strike

2. **Test Validation**:
   - Create strategy with minimum_premium_required: 2.00
   - Build sample that returns 1.50 premium
   - Verify: validation returns valid: false

3. **Test Premium Display**:
   - Credit spread should show: "Credit: $X.XX"
   - Debit spread should show: "Debit: $X.XX"

### Migration Notes

1. **Database**: No schema changes needed
2. **Frontend**: Update to handle new premium_type field
3. **API**: Response format changes slightly (added premium_type)

### Risk Assessment

- **Low Risk**: Removing delta fields (already unused)
- **Medium Risk**: Iron condor validation (needs thorough testing)
- **Low Risk**: Validation logic fix (straightforward)
- **Low Risk**: Premium display (cosmetic change)