# TastyTracker Trade Journal

Automated trade logging and analysis system that captures **95% of your trade journal checklist automatically** from the TastyTrade API.

## 🎯 What It Captures Automatically

### ✅ **Available from TastyTrade API:**
- **All transaction data** (entries, exits, commissions, fills)
- **Greeks** (Delta, Theta, Gamma, Vega) from market data
- **IV Rank and 5-day IV change** 
- **Underlying prices** and market data
- **DTE calculations**
- **Multi-leg strategy detection** (put spreads, iron condors, etc.)
- **Trade matching** (links opens/closes correctly)

### ✅ **Calculated Automatically:**
- **POP/P50/POT** probability metrics using Black-Scholes
- **Max profit/loss** for each strategy
- **Return on capital**
- **Win rates by strategy**
- **Market regime context** (SPX, VIX, rates at entry time)
- **Trade duration and timing analysis**

### ⚠️ **Manual Input Required:**
- Trade notes and rationale
- "What went well" / "What to improve" 
- Rule compliance scoring
- Custom trade tags

## 🚀 Quick Start

### 1. Setup Environment
```bash
# Set your TastyTrade credentials
export TASTYTRADE_USERNAME="your_username"
export TASTYTRADE_PASSWORD="your_password"

# Install dependencies
pip install tastytrade scipy numpy
```

### 2. Process Your Trades
```bash
# Process all trades for your account
python journal_cli.py process --account YOUR_ACCOUNT_NUMBER

# Process specific date range
python journal_cli.py process --account YOUR_ACCOUNT_NUMBER --start-date 2024-01-01 --end-date 2024-12-31
```

### 3. Generate Reports
```bash
# Comprehensive performance report
python journal_cli.py report --account YOUR_ACCOUNT_NUMBER

# Export to Excel/CSV for analysis
python journal_cli.py export --account YOUR_ACCOUNT_NUMBER --output my_trades.csv
```

## 📊 Features

### **Automated Trade Detection**
- Automatically identifies strategy types (put credit spreads, iron condors, etc.)
- Links multi-leg opens and closes
- Handles partial fills and adjustments
- Tracks commission and fees

### **Probability Analysis**
- **POP (Probability of Profit)**: Black-Scholes calculation for each strategy
- **P50**: Probability of achieving 50% of max profit (tastytrade's management rule)
- **POT**: Probability of touching short strike (assignment risk)
- **Expected Value**: Risk-adjusted expected return

### **Market Context Capture**
- **Market Regime**: VIX level, SPX price, 10yr yields at entry
- **Volatility Environment**: Low/medium/high vol classification
- **Sector Rotation**: Performance of major sectors
- **Risk-On/Risk-Off**: Overall market sentiment

### **Performance Analytics**
- **Win Rate vs POP**: How accurate are your probability estimates?
- **Strategy Breakdown**: Which strategies work best for you?
- **Market Regime Analysis**: Performance in different volatility environments
- **Time-Based Analysis**: Monthly/quarterly performance trends
- **Rule Compliance**: Do you follow your exit rules?

## 🎯 Complete Trade Journal Data Points

Your automated journal captures all these data points from your comprehensive checklist:

### **A. Trade ID & Context**
- ✅ Trade ID / Tag
- ✅ Date & Local Time Opened  
- ✅ Account / Strategy Bucket
- ✅ Underlying Ticker & Sector
- ✅ Market-Regime Snapshot (SPX, VIX, 10yr)

### **B. Entry Setup** 
- ✅ Starting IV Rank
- ✅ 5-Day IV Change
- ✅ Underlying Price @ Entry
- ✅ Strategy Type (auto-detected)
- ✅ Contracts / Strikes / Width
- ✅ Entry Credit/Debit & BPR
- ✅ DTE at Entry
- ✅ Greeks @ Entry (Δ, Θ, Γ, Vega)
- ✅ **POP** (calculated)
- ✅ **P50** (calculated) 
- ✅ **POT** (calculated)
- ✅ Max Profit / Max Loss

### **C. Exit & Outcome**
- ✅ Exit Date & Time
- ✅ DTE at Exit
- ✅ Underlying Price @ Exit
- ✅ Realized P&L ($) and %
- ✅ % of Max Profit/Loss Captured
- ✅ Return on Capital (ROC)
- ✅ Total Commissions / Fees
- ✅ Winner/Loser classification

### **D. Performance Analysis**
- ✅ Trade Duration (days)
- ✅ % of Initial Credit Captured
- ✅ Winner Managed @ 50%? 
- ✅ Rule-Compliance tracking
- ✅ Slippage analysis

## 📈 Sample Reports

### **Overall Performance**
```
📈 TRADE JOURNAL SUMMARY
================================
Period: 2024-01-01 to 2024-12-31
Total Trades: 127
Closed Trades: 118
Win Rate: 72.3%
Total P&L: $8,450.00
Net P&L (after fees): $7,890.00
Avg P&L per Trade: $66.86
Avg Days Held: 28.4
Total Commissions: $560.00
```

### **Strategy Breakdown**
```
📋 STRATEGY BREAKDOWN
================================
put_credit_spread:
  Trades: 89
  Win Rate: 74.2%
  Avg P&L: $78.90
  Avg DTE: 32
  Avg POP: 68.5%

iron_condor:
  Trades: 23
  Win Rate: 65.2%
  Avg P&L: $45.30
  Avg DTE: 28
  Avg POP: 62.1%
```

### **POP vs Actual Performance**
```
🎯 POP vs ACTUAL PERFORMANCE
================================
High POP (>70%):
  Trades: 45
  Predicted Win Rate: 73.8%
  Actual Win Rate: 77.8%
  POP Accuracy: ±4.0%

Medium POP (50-70%):
  Trades: 58
  Predicted Win Rate: 61.2%
  Actual Win Rate: 65.5%
  POP Accuracy: ±4.3%
```

## 🔧 Advanced Usage

### **Python API Usage**
```python
from trade_journal_manager import TradeJournalManager
from tastytrade import Session

# Initialize
session = Session("username", "password")
journal = TradeJournalManager(session)

# Process trades
result = journal.process_account_trades("YOUR_ACCOUNT")

# Generate analysis
report = journal.generate_comprehensive_report()

# Custom analysis
trades = journal.journal.get_trades(symbol="TSLA", status="closed")
```

### **Custom Enhancement**
```python
# Add your own trade analysis
def analyze_earnings_trades(journal):
    trades = journal.get_trades()
    earnings_trades = [t for t in trades if "earnings" in t.trade_notes.lower()]
    # Custom analysis...
```

## 🎯 Benefits vs Manual Journaling

| Feature | Manual Journal | TastyTracker |
|---------|---------------|--------------|
| Data Entry Time | 10-15 min/trade | **Fully Automated** |
| Probability Calcs | Manual/Skip | **Auto Black-Scholes** |
| Market Context | Forget to capture | **Auto Snapshot** |
| Strategy Detection | Manual categorization | **Auto Detection** |
| Multi-leg Matching | Error-prone | **Perfect Matching** |
| Commission Tracking | Often missed | **Precise to the penny** |
| Historical Analysis | Excel gymnastics | **Rich Analytics** |
| POP Accuracy Testing | Never done | **Built-in Analysis** |

## 🛠 System Architecture

```
TastyTrade API
     ↓
Transaction Processor (groups trades)
     ↓
Trade Journal Database (SQLite)
     ↓
Enhancement Engine (probabilities, market data)
     ↓
Analytics Engine (reports, insights)
     ↓
Export/Visualization
```

## 📋 CLI Commands Reference

```bash
# Process account trades
journal_cli.py process --account 12345 --start-date 2024-01-01

# Generate comprehensive report  
journal_cli.py report --account 12345 --output report.json

# Export to CSV for Excel analysis
journal_cli.py export --account 12345 --output trades.csv

# Check system status
journal_cli.py status

# Enhance existing trades with latest calculations
journal_cli.py enhance --account 12345

# Verbose logging for debugging
journal_cli.py process --account 12345 --verbose
```

## 🔮 Future Enhancements

- [ ] **Real-time monitoring** of open positions
- [ ] **Automated rule compliance** alerts
- [ ] **Strategy optimization** recommendations  
- [ ] **Risk management** integration
- [ ] **Web dashboard** for visualization
- [ ] **Mobile app** for trade notes
- [ ] **Portfolio correlation** analysis
- [ ] **Backtesting** integration

## 🤝 Contributing

This trade journal system captures 95% of your checklist automatically, saving hours of manual data entry while providing insights impossible with manual tracking.

The remaining 5% (trade notes, lessons learned) are the human insights that make you a better trader - focus your time there instead of data entry!

---

**Questions? Issues? Enhancements?**
- Create issues for bugs or feature requests
- The goal is 100% automated trade journaling
- Help make options trading more systematic and profitable