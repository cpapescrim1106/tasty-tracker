// Trade Approval Dashboard React Component
// Main Trade Approval Dashboard Component
const TradeApprovalDashboard = ({ compact = false }) => {
    // State management
    const [pendingTrades, setPendingTrades] = React.useState([]);
    const [selectedTrades, setSelectedTrades] = React.useState(new Set());
    const [isLoading, setIsLoading] = React.useState(false);
    const [expandedTrade, setExpandedTrade] = React.useState(null);
    const [approvalHistory, setApprovalHistory] = React.useState([]);
    const [systemStats, setSystemStats] = React.useState({});
    const [lastUpdate, setLastUpdate] = React.useState(null);
    const [autoRefresh, setAutoRefresh] = React.useState(true);
    
    // Auto-refresh interval
    const refreshInterval = React.useRef(null);

    // Load pending trades and system data on mount
    React.useEffect(() => {
        loadPendingTrades();
        loadSystemStats();
        
        // Set up auto-refresh
        if (autoRefresh) {
            refreshInterval.current = setInterval(() => {
                loadPendingTrades();
                loadSystemStats();
            }, 30000); // 30 seconds
        }
        
        return () => {
            if (refreshInterval.current) {
                clearInterval(refreshInterval.current);
            }
        };
    }, [autoRefresh]);

    const loadPendingTrades = async () => {
        try {
            console.log('🔄 Loading pending trades...');
            setIsLoading(true);
            const response = await fetch('/api/workflow/pending');
            const data = await response.json();
            
            if (data.success) {
                console.log('✅ Loaded pending trades:', data.pending_trades.length);
                setPendingTrades(data.pending_trades || []);
                setLastUpdate(new Date());
            } else {
                console.error('❌ Failed to load pending trades:', data.error);
            }
        } catch (error) {
            console.error('❌ Error loading pending trades:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const loadSystemStats = async () => {
        try {
            const response = await fetch('/api/workflow/stats');
            const data = await response.json();
            
            if (data.success) {
                setSystemStats(data.stats || {});
            }
        } catch (error) {
            console.error('❌ Error loading system stats:', error);
        }
    };

    const approveTrade = async (tradeId, modifications = {}) => {
        try {
            console.log('✅ Approving trade:', tradeId);
            const response = await fetch(`/api/workflow/approve/${tradeId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modifications })
            });
            
            const result = await response.json();
            if (result.success) {
                console.log('✅ Trade approved successfully');
                loadPendingTrades(); // Refresh the list
                setSelectedTrades(prev => {
                    const newSet = new Set(prev);
                    newSet.delete(tradeId);
                    return newSet;
                });
            } else {
                alert('Failed to approve trade: ' + result.error);
            }
        } catch (error) {
            console.error('❌ Error approving trade:', error);
            alert('Error approving trade: ' + error.message);
        }
    };

    const bulkApproveTrades = async () => {
        if (selectedTrades.size === 0) {
            alert('Please select trades to approve');
            return;
        }
        
        const confirmed = confirm(`Approve ${selectedTrades.size} selected trades?`);
        if (!confirmed) return;
        
        try {
            for (const tradeId of selectedTrades) {
                await approveTrade(tradeId);
            }
            setSelectedTrades(new Set());
        } catch (error) {
            console.error('❌ Bulk approval error:', error);
        }
    };

    const toggleTradeSelection = (tradeId) => {
        setSelectedTrades(prev => {
            const newSet = new Set(prev);
            if (newSet.has(tradeId)) {
                newSet.delete(tradeId);
            } else {
                newSet.add(tradeId);
            }
            return newSet;
        });
    };

    const selectAllTrades = () => {
        if (selectedTrades.size === pendingTrades.length) {
            setSelectedTrades(new Set());
        } else {
            setSelectedTrades(new Set(pendingTrades.map(t => t.id)));
        }
    };

    const formatCurrency = (amount) => {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(amount || 0);
    };

    const formatPercentage = (value) => {
        return `${(value || 0).toFixed(1)}%`;
    };

    const getRiskColor = (riskReward) => {
        if (riskReward >= 2) return '#16c784'; // Green
        if (riskReward >= 1.5) return '#f59e0b'; // Yellow
        return '#ea3943'; // Red
    };

    const getConfidenceColor = (confidence) => {
        if (confidence >= 80) return '#16c784'; // Green
        if (confidence >= 60) return '#f59e0b'; // Yellow
        return '#ea3943'; // Red
    };

    // Component rendering
    return React.createElement('div', { 
        className: compact ? 'trade-approval-compact' : 'trade-approval-dashboard' 
    },
        // Header with stats and controls (simplified for compact mode)
        !compact && React.createElement('div', { className: 'approval-header' },
            React.createElement('div', { className: 'header-left' },
                React.createElement('h3', null, '🎯 Trade Approval Dashboard'),
                React.createElement('div', { className: 'stats-summary' },
                    React.createElement('span', { className: 'stat-item' },
                        `${pendingTrades.length} pending trades`
                    ),
                    systemStats.total_workflows && React.createElement('span', { className: 'stat-item' },
                        `${systemStats.active_workflows || 0} active workflows`
                    ),
                    lastUpdate && React.createElement('span', { className: 'stat-item last-update' },
                        `Updated: ${lastUpdate.toLocaleTimeString()}`
                    )
                )
            ),
            React.createElement('div', { className: 'header-controls' },
                React.createElement('label', { className: 'auto-refresh-toggle' },
                    React.createElement('input', {
                        type: 'checkbox',
                        checked: autoRefresh,
                        onChange: (e) => setAutoRefresh(e.target.checked)
                    }),
                    'Auto-refresh'
                ),
                React.createElement('button', {
                    className: 'btn btn-secondary',
                    onClick: loadPendingTrades,
                    disabled: isLoading
                }, isLoading ? '🔄 Loading...' : '🔄 Refresh'),
                selectedTrades.size > 0 && React.createElement('button', {
                    className: 'btn btn-primary bulk-approve-btn',
                    onClick: bulkApproveTrades
                }, `✅ Approve ${selectedTrades.size} Selected`)
            )
        ),

        // Compact header for integrated mode
        compact && React.createElement('div', { className: 'compact-header' },
            React.createElement('div', { className: 'compact-stats' },
                React.createElement('span', { className: 'trade-count' },
                    `${pendingTrades.length} pending trades`
                ),
                lastUpdate && React.createElement('span', { className: 'last-update' },
                    `Updated: ${lastUpdate.toLocaleTimeString()}`
                )
            ),
            React.createElement('div', { className: 'compact-actions' },
                selectedTrades.size > 0 && React.createElement('button', {
                    className: 'btn btn-primary btn-small',
                    onClick: bulkApproveTrades
                }, `✅ Approve ${selectedTrades.size} Selected`),
                React.createElement('button', {
                    className: 'btn btn-secondary btn-small',
                    onClick: loadPendingTrades,
                    disabled: isLoading
                }, isLoading ? '🔄' : '🔄')
            )
        ),

        // Bulk actions bar (hidden in compact mode)
        pendingTrades.length > 0 && !compact && React.createElement('div', { className: 'bulk-actions-bar' },
            React.createElement('label', { className: 'select-all-checkbox' },
                React.createElement('input', {
                    type: 'checkbox',
                    checked: selectedTrades.size === pendingTrades.length && pendingTrades.length > 0,
                    onChange: selectAllTrades
                }),
                'Select All'
            ),
            React.createElement('div', { className: 'selection-info' },
                `${selectedTrades.size} of ${pendingTrades.length} trades selected`
            )
        ),

        // Main content area
        pendingTrades.length === 0 ? (
            React.createElement('div', { className: 'empty-state' },
                isLoading ? 
                    React.createElement('div', { className: 'loading-state' },
                        React.createElement('div', { className: 'loading-spinner' }),
                        'Loading pending trades...'
                    ) :
                    React.createElement('div', { className: 'no-trades' },
                        React.createElement('div', { className: 'no-trades-icon' }, '📋'),
                        React.createElement('h4', null, 'No Pending Trades'),
                        React.createElement('p', null, 'All trades have been reviewed. New trades will appear here as workflows generate them.')
                    )
            )
        ) : (
            React.createElement('div', { className: 'trades-table-container' },
                React.createElement('table', { className: 'trades-table' },
                    React.createElement('thead', null,
                        React.createElement('tr', null,
                            React.createElement('th', { className: 'select-col' }, ''),
                            React.createElement('th', { className: 'symbol-col' }, 'Symbol'),
                            React.createElement('th', { className: 'strategy-col' }, 'Strategy'),
                            React.createElement('th', { className: 'pnl-col' }, 'Expected P&L'),
                            React.createElement('th', { className: 'risk-col' }, 'Risk/Reward'),
                            React.createElement('th', { className: 'confidence-col' }, 'Confidence'),
                            React.createElement('th', { className: 'created-col' }, 'Created'),
                            React.createElement('th', { className: 'actions-col' }, 'Actions')
                        )
                    ),
                    React.createElement('tbody', null,
                        pendingTrades.map(trade => 
                            React.createElement(React.Fragment, { key: trade.id },
                                // Main trade row
                                React.createElement('tr', { 
                                    className: `trade-row ${selectedTrades.has(trade.id) ? 'selected' : ''} ${expandedTrade === trade.id ? 'expanded' : ''}`,
                                    onClick: () => setExpandedTrade(expandedTrade === trade.id ? null : trade.id)
                                },
                                    React.createElement('td', { className: 'select-col' },
                                        React.createElement('input', {
                                            type: 'checkbox',
                                            checked: selectedTrades.has(trade.id),
                                            onChange: () => toggleTradeSelection(trade.id),
                                            onClick: (e) => e.stopPropagation()
                                        })
                                    ),
                                    React.createElement('td', { className: 'symbol-col' },
                                        React.createElement('span', { className: 'symbol' }, trade.symbol)
                                    ),
                                    React.createElement('td', { className: 'strategy-col' },
                                        React.createElement('span', { className: 'strategy-name' }, 
                                            trade.strategy_config?.name || 'Unknown Strategy'
                                        ),
                                        trade.strategy_config?.legs && React.createElement('span', { className: 'leg-count' },
                                            `${trade.strategy_config.legs.length} legs`
                                        )
                                    ),
                                    React.createElement('td', { className: 'pnl-col' },
                                        trade.risk_metrics?.expected_pnl ? 
                                            React.createElement('span', { 
                                                className: `pnl-value ${trade.risk_metrics.expected_pnl > 0 ? 'positive' : 'negative'}` 
                                            }, formatCurrency(trade.risk_metrics.expected_pnl)) :
                                            React.createElement('span', { className: 'no-data' }, '-')
                                    ),
                                    React.createElement('td', { className: 'risk-col' },
                                        trade.risk_metrics?.risk_reward_ratio ? 
                                            React.createElement('span', { 
                                                className: 'risk-reward',
                                                style: { color: getRiskColor(trade.risk_metrics.risk_reward_ratio) }
                                            }, `${trade.risk_metrics.risk_reward_ratio.toFixed(2)}:1`) :
                                            React.createElement('span', { className: 'no-data' }, '-')
                                    ),
                                    React.createElement('td', { className: 'confidence-col' },
                                        trade.risk_metrics?.confidence_score ? 
                                            React.createElement('span', { 
                                                className: 'confidence-score',
                                                style: { color: getConfidenceColor(trade.risk_metrics.confidence_score) }
                                            }, formatPercentage(trade.risk_metrics.confidence_score)) :
                                            React.createElement('span', { className: 'no-data' }, '-')
                                    ),
                                    React.createElement('td', { className: 'created-col' },
                                        trade.created_at ? 
                                            React.createElement('span', { className: 'created-time' },
                                                new Date(trade.created_at).toLocaleString()
                                            ) :
                                            React.createElement('span', { className: 'no-data' }, '-')
                                    ),
                                    React.createElement('td', { className: 'actions-col' },
                                        React.createElement('button', {
                                            className: 'btn btn-primary btn-small approve-btn',
                                            onClick: (e) => {
                                                e.stopPropagation();
                                                approveTrade(trade.id);
                                            }
                                        }, '✅ Approve'),
                                        React.createElement('button', {
                                            className: 'btn btn-secondary btn-small details-btn',
                                            onClick: (e) => {
                                                e.stopPropagation();
                                                setExpandedTrade(expandedTrade === trade.id ? null : trade.id);
                                            }
                                        }, expandedTrade === trade.id ? '🔼 Less' : '🔽 Details')
                                    )
                                ),
                                
                                // Expanded details row
                                expandedTrade === trade.id && React.createElement('tr', { 
                                    className: 'trade-details-row' 
                                },
                                    React.createElement('td', { colSpan: 8, className: 'details-content' },
                                        React.createElement('div', { className: 'trade-details' },
                                            // Strategy Details
                                            React.createElement('div', { className: 'details-section' },
                                                React.createElement('h5', null, '📋 Strategy Details'),
                                                trade.strategy_config?.legs && React.createElement('div', { className: 'legs-list' },
                                                    trade.strategy_config.legs.map((leg, idx) =>
                                                        React.createElement('div', { key: idx, className: 'leg-item' },
                                                            React.createElement('span', { className: 'leg-action' }, 
                                                                `${leg.action.toUpperCase()} ${leg.quantity}x`
                                                            ),
                                                            React.createElement('span', { className: 'leg-type' }, 
                                                                leg.option_type.toUpperCase()
                                                            ),
                                                            React.createElement('span', { className: 'leg-selection' }, 
                                                                leg.selection_method === 'delta' ? 
                                                                    `Δ ${leg.selection_value}` :
                                                                    leg.selection_method
                                                            )
                                                        )
                                                    )
                                                )
                                            ),
                                            
                                            // Risk Metrics
                                            trade.risk_metrics && React.createElement('div', { className: 'details-section' },
                                                React.createElement('h5', null, '📊 Risk Metrics'),
                                                React.createElement('div', { className: 'risk-grid' },
                                                    React.createElement('div', { className: 'risk-item' },
                                                        React.createElement('label', null, 'Max Loss:'),
                                                        React.createElement('span', null, formatCurrency(trade.risk_metrics.max_loss))
                                                    ),
                                                    React.createElement('div', { className: 'risk-item' },
                                                        React.createElement('label', null, 'Buying Power:'),
                                                        React.createElement('span', null, formatCurrency(trade.risk_metrics.buying_power_required))
                                                    ),
                                                    trade.risk_metrics.win_probability && React.createElement('div', { className: 'risk-item' },
                                                        React.createElement('label', null, 'Win Probability:'),
                                                        React.createElement('span', null, formatPercentage(trade.risk_metrics.win_probability))
                                                    )
                                                )
                                            ),
                                            
                                            // Order Details
                                            trade.order_details && React.createElement('div', { className: 'details-section' },
                                                React.createElement('h5', null, '📝 Order Details'),
                                                React.createElement('pre', { className: 'order-preview' },
                                                    JSON.stringify(trade.order_details, null, 2)
                                                )
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
    );
};

// Make TradeApprovalDashboard available globally
window.TradeApprovalDashboard = TradeApprovalDashboard;

// Initialize the Trade Approval Dashboard when the DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('🎯 Initializing Trade Approval Dashboard...');
    
    // Wait for React to be loaded
    const initializeApprovalDashboard = () => {
        console.log('🔍 Checking for React and container...');
        
        const container = document.getElementById('trade-approval-root');
        if (container && window.React && window.ReactDOM) {
            try {
                console.log('🎯 Creating Trade Approval Dashboard...');
                
                // Add loading content
                container.innerHTML = '<div style="color: yellow; padding: 20px;">🔄 Loading Trade Approval Dashboard...</div>';
                
                // Use modern createRoot if available, otherwise fallback to legacy render
                if (ReactDOM.createRoot) {
                    console.log('⚛️ Using ReactDOM.createRoot...');
                    const root = ReactDOM.createRoot(container);
                    root.render(React.createElement(TradeApprovalDashboard));
                } else {
                    console.log('⚛️ Using legacy ReactDOM.render...');
                    ReactDOM.render(React.createElement(TradeApprovalDashboard), container);
                }
                console.log('✅ Trade Approval Dashboard rendered successfully');
            } catch (error) {
                console.error('❌ Error creating Trade Approval Dashboard:', error);
                container.innerHTML = '<div style="color: red; padding: 20px; border: 1px solid red;">❌ Trade Approval Dashboard failed to load. Error: ' + error.message + '</div>';
            }
        } else {
            console.log('⏳ Missing dependencies - React:', !!window.React, 'ReactDOM:', !!window.ReactDOM, 'Container:', !!container);
            setTimeout(initializeApprovalDashboard, 100);
        }
    };
    
    initializeApprovalDashboard();
});

// Initialize integrated trade approval when Auto Recommendations tab is shown
document.addEventListener('click', (e) => {
    if (e.target.dataset.tab === 'recommendations') {
        console.log('🤖 Auto Recommendations tab clicked - checking for integrated approval');
        setTimeout(() => {
            const container = document.getElementById('integrated-trade-approval-root');
            if (container && !container.hasChildNodes() && window.React && window.ReactDOM) {
                console.log('🎯 Initializing integrated Trade Approval...');
                try {
                    if (ReactDOM.createRoot) {
                        const root = ReactDOM.createRoot(container);
                        root.render(React.createElement(TradeApprovalDashboard, { compact: true }));
                    } else {
                        ReactDOM.render(React.createElement(TradeApprovalDashboard, { compact: true }), container);
                    }
                    console.log('✅ Integrated Trade Approval initialized successfully');
                } catch (error) {
                    console.error('❌ Error initializing integrated approval:', error);
                    ReactDOM.render(React.createElement(TradeApprovalDashboard, { compact: true }), container);
                }
            }
        }, 100);
    }
});

// Function to show/hide the pending approvals section
window.showPendingApprovalsSection = function() {
    const section = document.getElementById('pending-approvals-section');
    if (section) {
        section.style.display = 'block';
        console.log('✅ Pending approvals section shown');
    }
};

window.hidePendingApprovalsSection = function() {
    const section = document.getElementById('pending-approvals-section');
    if (section) {
        section.style.display = 'none';
        console.log('✅ Pending approvals section hidden');
    }
};