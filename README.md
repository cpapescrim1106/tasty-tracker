# 🎯 TastyTracker

**Real-time options portfolio delta tracking and risk management dashboard for Tastytrade accounts.**

TastyTracker provides live portfolio monitoring with real-time delta calculations, notional exposure tracking, and net liquidation values. Built with Python Flask backend and modern web dashboard.

## ✨ Features

### 📊 **Real-time Portfolio Metrics**
- **Portfolio Delta**: Live aggregated delta across all positions
- **Total Notional Exposure**: Real-time notional value calculations (Position Delta × Underlying Price)
- **Net Liquidation Value**: Current market value of all positions
- **Position Count**: Active positions tracking

### 📈 **Interactive Dashboard**
- **Live Updates**: 5-second refresh with WebSocket data streaming
- **Account Selection**: Toggle between multiple accounts (Joint/IRA)
- **Visual Charts**: Interactive pie charts with percentage labels for notional and net liq allocation
- **Responsive Design**: Modern, mobile-friendly interface

### 🔄 **Real-time Data Streaming**
- **Dual Channel WebSocket**: Greeks data + Quote data via Tastytrade DXLink
- **Live Greeks**: Real-time option deltas, prices, and Greeks
- **Live Quotes**: Real-time underlying asset price updates
- **Automatic Reconnection**: Robust connection handling with fallback pricing

### 💼 **Position Management**
- **Grouped by Symbol**: Positions organized by underlying asset
- **Detailed Views**: Expandable position details with strike, expiration, account info
- **Real-time Updates**: Live price and delta updates for each position
- **Support for**: Stocks, calls, puts across multiple accounts

## 🚀 Installation

### Prerequisites
- Python 3.7+
- Tastytrade account with API access
- Modern web browser

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/tastytracker.git
   cd tastytracker
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure credentials**
   Create environment variables or modify the script with your Tastytrade credentials:
   ```bash
   export TASTYTRADE_USERNAME="your_username"
   export TASTYTRADE_PASSWORD="your_password"
   ```

4. **Run the application**
   ```bash
   python3 delta_backend.py
   ```

5. **Access the dashboard**
   Open http://localhost:5001 in your browser

## 📱 Usage

### Dashboard Navigation
- **Portfolio Stats**: Top cards show current delta, notional, net liq, and position count
- **Account Selection**: Checkboxes to filter by specific accounts
- **Position Table**: Click symbols to expand/collapse detailed position views
- **Allocation Charts**: Visual breakdown of notional and net liquidation by symbol

### Key Metrics Explained
- **Portfolio Delta**: Aggregate delta exposure (positive = long bias, negative = short bias)
- **Total Notional**: Risk exposure calculated as Position Delta × Underlying Price
- **Net Liquidation**: Current market value of all positions
- **Position Delta**: Per-position delta calculated as Delta per Contract × Quantity × 100 (for options)

### Real-time Updates
- **Live Prices**: Underlying asset prices update continuously via market data feed
- **Live Greeks**: Option deltas and prices update in real-time
- **Notional Calculations**: Automatically recalculated as underlying prices change
- **Visual Indicators**: Green/red colors indicate positive/negative deltas

## 🛠 Technical Architecture

### Backend (Python Flask)
- **Tastytrade API Integration**: Authentication and position fetching
- **WebSocket Data Streaming**: Real-time Greeks and quotes via DXLink protocol
- **Delta Calculations**: Live position delta and notional value calculations
- **REST API**: JSON endpoints for dashboard data

### Frontend (HTML/JavaScript)
- **Chart.js**: Interactive doughnut charts with percentage labels
- **Real-time Updates**: Auto-refresh every 5 seconds with cache-busting
- **Responsive Design**: Mobile-friendly interface with CSS Grid/Flexbox
- **Smooth Animations**: Chart updates without flickering/regeneration

### Data Flow
1. **Position Fetching**: Initial positions loaded from Tastytrade API
2. **WebSocket Subscription**: Dual-channel subscription (Greeks + Quotes)
3. **Real-time Processing**: Live delta and price updates
4. **Notional Calculation**: Position Delta × Underlying Price
5. **Dashboard Updates**: Live data served via Flask API

## 📊 API Endpoints

- `GET /` - Main dashboard interface
- `GET /api/data?accounts=5WX84566,5WU39639` - Portfolio data with account filtering
- `GET /api/debug` - Debug information and raw position data
- `GET /api/calculate_netliq` - Force recalculation of net liquidation values

## ⚙️ Configuration

### Account Management
The system automatically detects multiple accounts and provides filtering options:
- Joint Tenant accounts
- IRA accounts
- Individual accounts

### Fallback Pricing
Built-in fallback prices for major symbols ensure continuous operation:
- AMD, AMZN, ASML, GOOGL, HOOD, IBIT, META, PYPL, QQQ, SHOP, SOFI, TSLA

## 🔧 Development

### Adding New Features
1. Backend changes: Modify `delta_backend.py`
2. Frontend changes: Update `templates/dashboard.html`
3. Dependencies: Add to `requirements.txt`

### Debugging
- Enable debug logs in the backend
- Use `/api/debug` endpoint for raw data inspection
- Check browser developer tools for frontend issues

## 📈 Performance

- **Real-time Updates**: 5-second refresh cycle
- **WebSocket Efficiency**: Dual-channel streaming optimized for market data
- **Chart Performance**: Updates existing charts instead of regenerating
- **Memory Management**: Automatic cleanup and reconnection handling

## 🚨 Risk Management

**Important**: This tool is for informational purposes only. Always verify calculations independently before making trading decisions. The software is provided as-is without warranty.

- Monitor portfolio delta exposure
- Track notional risk across positions
- Use net liquidation for position sizing
- Set appropriate stop-losses and risk limits

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Tastytrade for API access and market data
- Chart.js for visualization components
- Python Flask community for web framework

---

**⚠️ Disclaimer**: This software is for educational and informational purposes only. Trading involves risk of loss. Past performance does not guarantee future results. Use at your own risk. 