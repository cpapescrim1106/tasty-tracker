// Strategy Builder React Component
const { useState, useEffect, useRef } = React;

// Main Strategy Builder Component
const StrategyBuilder = () => {
    // State management
    const [strategies, setStrategies] = useState([]);
    const [currentStrategy, setCurrentStrategy] = useState({
        name: '',
        description: '',
        strategy_type: 'custom',
        opening_action: 'STO',
        legs: [],
        dte_range_min: 30,
        dte_range_max: 45,
        profit_target_pct: 50,
        stop_loss_pct: 200,
        no_stop_loss: true,
        minimum_premium_required: 0,
        minimum_underlying_price: 0,
        closing_21_dte: false,
        delta_biases: [],
        management_rules: []
    });
    
    const [activeTab, setActiveTab] = useState('basic');
    const [validationResult, setValidationResult] = useState(null);
    const [isValidating, setIsValidating] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [selectedStrategyId, setSelectedStrategyId] = useState(null);

    // Load saved strategies on mount
    useEffect(() => {
        loadStrategies();
    }, []);

    const loadStrategies = async () => {
        try {
            console.log('Loading strategies from API...');
            const response = await fetch('/api/strategies');
            const data = await response.json();
            console.log('Strategies API response:', data);
            console.log('Strategies count:', data.strategies?.length || 0);
            setStrategies(data.strategies || []);
        } catch (error) {
            console.error('Error loading strategies:', error);
        }
    };

    // Update strategy field
    const updateStrategy = (field, value) => {
        setCurrentStrategy(prev => ({
            ...prev,
            [field]: value
        }));
    };

    // Leg management
    const addLeg = () => {
        const newLeg = {
            action: 'sell',
            option_type: 'put',
            selection_method: 'percentage',
            selection_value: 5,
            quantity: 1,
        };
        setCurrentStrategy(prev => ({
            ...prev,
            legs: [...prev.legs, newLeg]
        }));
    };

    const updateLeg = (index, field, value) => {
        setCurrentStrategy(prev => ({
            ...prev,
            legs: prev.legs.map((leg, i) => {
                if (i === index) {
                    const updatedLeg = { ...leg, [field]: value };
                    // If changing to premium target, clear selection_value
                    if (field === 'selection_method' && value === 'premium') {
                        updatedLeg.selection_value = 0;
                    }
                    return updatedLeg;
                }
                return leg;
            })
        }));
    };

    const removeLeg = (index) => {
        setCurrentStrategy(prev => ({
            ...prev,
            legs: prev.legs.filter((_, i) => i !== index)
        }));
    };

    // Management rule functions
    const addManagementRule = () => {
        const newRule = {
            rule_type: 'profit_target',
            trigger_condition: 'pnl_percent',
            trigger_value: 50,
            action: 'close_position',
            action_params: { quantity_pct: 100 }
        };
        setCurrentStrategy(prev => ({
            ...prev,
            management_rules: [...prev.management_rules, newRule]
        }));
    };

    const updateManagementRule = (index, field, value) => {
        setCurrentStrategy(prev => ({
            ...prev,
            management_rules: prev.management_rules.map((rule, i) => 
                i === index ? { ...rule, [field]: value } : rule
            )
        }));
    };

    const removeManagementRule = (index) => {
        setCurrentStrategy(prev => ({
            ...prev,
            management_rules: prev.management_rules.filter((_, i) => i !== index)
        }));
    };

    // Validation
    const validateStrategy = async () => {
        setIsValidating(true);
        setValidationResult(null);
        
        try {
            // Debug logging to see what we're sending
            console.log('🔍 Frontend validation request - currentStrategy:', currentStrategy);
            console.log('🔍 Minimum premium being sent:', currentStrategy.minimum_premium_required);
            console.log('🔍 Type of minimum premium:', typeof currentStrategy.minimum_premium_required);
            console.log('🔍 Stringified strategy object:', JSON.stringify(currentStrategy, null, 2));
            
            const response = await fetch('/api/strategies/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    strategy: currentStrategy,
                    test_symbol: 'SPY'
                })
            });
            
            const result = await response.json();
            setValidationResult(result);
        } catch (error) {
            console.error('Validation error:', error);
            setValidationResult({ 
                valid: false, 
                errors: ['Failed to validate strategy: ' + error.message] 
            });
        } finally {
            setIsValidating(false);
        }
    };

    // Save strategy
    const saveStrategy = async () => {
        if (!currentStrategy.name) {
            alert('Please enter a strategy name');
            return;
        }
        
        if (currentStrategy.legs.length === 0) {
            alert('Please add at least one leg to the strategy');
            return;
        }
        
        // Validate ATM straddle percentages
        for (let i = 0; i < currentStrategy.legs.length; i++) {
            const leg = currentStrategy.legs[i];
            if (leg.selection_method === 'atm_straddle') {
                if (leg.selection_value < 0 || leg.selection_value > 200) {
                    alert(`Leg ${i + 1}: ATM Straddle % must be between 0 and 200 (current value: ${leg.selection_value}%)`);
                    return;
                }
            }
        }
        
        setIsSaving(true);
        
        try {
            const method = selectedStrategyId ? 'PUT' : 'POST';
            const url = selectedStrategyId 
                ? `/api/strategies/${selectedStrategyId}` 
                : '/api/strategies';
            
            // Debug logging
            console.log('Saving strategy:', {
                method,
                url,
                strategyData: currentStrategy
            });
                
            const response = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentStrategy)
            });
            
            console.log('Response status:', response.status);
            console.log('Response headers:', response.headers);
            
            if (response.ok) {
                const result = await response.json();
                console.log('Save successful:', result);
                alert('Strategy saved successfully!');
                loadStrategies();
                clearStrategy();
            } else {
                // Try to parse as JSON first, but handle HTML error pages
                const contentType = response.headers.get('content-type');
                console.log('Error response content-type:', contentType);
                
                let errorMessage = 'Unknown error';
                if (contentType && contentType.includes('application/json')) {
                    try {
                        const error = await response.json();
                        errorMessage = error.error || error.message || 'Unknown error';
                        console.log('JSON error response:', error);
                    } catch (jsonError) {
                        console.error('Failed to parse JSON error response:', jsonError);
                        errorMessage = `HTTP ${response.status}: ${response.statusText}`;
                    }
                } else {
                    // Handle HTML error pages
                    const errorText = await response.text();
                    console.log('HTML error response:', errorText);
                    errorMessage = `HTTP ${response.status}: ${response.statusText}`;
                    
                    // Extract useful info from HTML error if possible
                    if (errorText.includes('Internal Server Error')) {
                        errorMessage = 'Internal Server Error - Check server logs for details';
                    } else if (errorText.includes('404')) {
                        errorMessage = 'API endpoint not found';
                    }
                }
                
                alert('Failed to save strategy: ' + errorMessage);
            }
        } catch (error) {
            console.error('Save error:', error);
            alert('Failed to save strategy: ' + error.message);
        } finally {
            setIsSaving(false);
        }
    };

    // Clear current strategy
    const clearStrategy = () => {
        setCurrentStrategy({
            name: '',
            description: '',
            strategy_type: 'custom',
            opening_action: 'STO',
            legs: [],
            dte_range_min: 30,
            dte_range_max: 45,
            profit_target_pct: 50,
            stop_loss_pct: 200,
            no_stop_loss: true,
            minimum_premium_required: 0,
            minimum_underlying_price: 0,
            closing_21_dte: false,
            delta_biases: [],
            management_rules: []
        });
        setSelectedStrategyId(null);
        setValidationResult(null);
    };

    // Load existing strategy for editing
    const loadStrategy = (strategy) => {
        console.log('Loading strategy for editing:', strategy);
        
        // Convert management rules to expected format
        const managementRules = (strategy.management_rules || []).map(rule => ({
            rule_type: rule.rule_type,
            trigger_condition: rule.trigger_condition,
            trigger_value: rule.trigger_value,
            action: rule.action,
            action_params: { quantity_pct: rule.quantity_pct || 100 }
        }));
        
        setCurrentStrategy({
            name: strategy.name,
            description: strategy.description || '',
            strategy_type: strategy.strategy_type || 'custom',
            opening_action: strategy.opening_action || 'STO',
            legs: strategy.legs || [],
            dte_range_min: strategy.dte_range_min || 30,
            dte_range_max: strategy.dte_range_max || 45,
            profit_target_pct: strategy.profit_target_pct || 50,
            stop_loss_pct: strategy.stop_loss_pct || 200,
            no_stop_loss: strategy.no_stop_loss !== undefined ? strategy.no_stop_loss : true,
            minimum_premium_required: strategy.minimum_premium_required || 0,
            minimum_underlying_price: strategy.minimum_underlying_price || 0,
            closing_21_dte: strategy.closing_21_dte || false,
            delta_biases: strategy.delta_biases || [],
            management_rules: managementRules
        });
        setSelectedStrategyId(strategy.id);
        setActiveTab('basic');
        console.log('Strategy loaded, current state updated');
    };

    const deleteStrategy = async (strategyId, strategyName) => {
        if (!confirm(`Are you sure you want to delete "${strategyName}"? This action cannot be undone.`)) {
            return;
        }

        try {
            const response = await fetch(`/api/strategies/${strategyId}`, {
                method: 'DELETE'
            });
            const data = await response.json();
            
            if (data.success) {
                console.log('Strategy deleted successfully:', data.message);
                // Reload strategies list
                loadStrategies();
                // Clear current strategy if it was the deleted one
                if (selectedStrategyId === strategyId) {
                    setCurrentStrategy({
                        name: '',
                        description: '',
                        strategy_type: 'custom',
                        opening_action: 'STO',
                        legs: [],
                        dte_range_min: 30,
                        dte_range_max: 45,
                        profit_target_pct: 50,
                        stop_loss_pct: 200,
                        no_stop_loss: true,
                        minimum_premium_required: 0,
                        minimum_underlying_price: 0,
                        closing_21_dte: false,
                        delta_biases: [],
                        management_rules: []
                    });
                    setSelectedStrategyId(null);
                }
            } else {
                alert(`Failed to delete strategy: ${data.error}`);
            }
        } catch (error) {
            console.error('Error deleting strategy:', error);
            alert('Error deleting strategy. Please try again.');
        }
    };

    // Component rendering
    return React.createElement('div', { className: 'strategy-builder' },
        // Header
        React.createElement('div', { className: 'strategy-header' },
            React.createElement('h3', null, 'Create and Manage Trading Strategies'),
            React.createElement('div', { className: 'strategy-actions' },
                React.createElement('button', {
                    className: 'btn btn-secondary',
                    onClick: clearStrategy
                }, '🆕 New Strategy'),
                React.createElement('button', {
                    className: 'btn btn-primary',
                    onClick: saveStrategy,
                    disabled: isSaving
                }, isSaving ? '💾 Saving...' : '💾 Save Strategy')
            )
        ),

        // Saved Strategies List
        strategies.length > 0 && React.createElement('div', { className: 'saved-strategies' },
            React.createElement('h4', null, '📚 Saved Strategies'),
            React.createElement('div', { className: 'strategy-list' },
                strategies.map(strategy => 
                    React.createElement('div', {
                        key: strategy.id,
                        className: 'strategy-item'
                    },
                        React.createElement('div', {
                            className: 'strategy-info',
                            onClick: () => loadStrategy(strategy)
                        },
                            React.createElement('span', { className: 'strategy-name' }, strategy.name),
                            React.createElement('span', { className: 'strategy-type' }, strategy.strategy_type),
                            React.createElement('span', { className: 'strategy-legs' }, 
                                `${strategy.legs.length} legs`
                            )
                        ),
                        React.createElement('button', {
                            className: 'btn btn-danger btn-small delete-btn',
                            onClick: (e) => {
                                e.stopPropagation();
                                deleteStrategy(strategy.id, strategy.name);
                            },
                            title: 'Delete strategy'
                        }, '🗑️')
                    )
                )
            )
        ),

        // Tab Navigation
        React.createElement('div', { className: 'strategy-tabs' },
            ['basic', 'legs', 'management', 'validation'].map(tab =>
                React.createElement('button', {
                    key: tab,
                    className: `tab-btn ${activeTab === tab ? 'active' : ''}`,
                    onClick: () => setActiveTab(tab)
                }, 
                    tab === 'basic' ? '📋 Basic Info' :
                    tab === 'legs' ? '🦵 Legs Configuration' :
                    tab === 'management' ? '📊 Management Rules' :
                    '✅ Validation'
                )
            )
        ),

        // Tab Content
        React.createElement('div', { className: 'strategy-tab-content' },
            // Basic Info Tab
            activeTab === 'basic' && React.createElement('div', { className: 'basic-info-tab' },
                React.createElement('div', { className: 'form-group' },
                    React.createElement('label', null, 'Strategy Name *'),
                    React.createElement('input', {
                        type: 'text',
                        className: 'form-control',
                        value: currentStrategy.name,
                        onChange: (e) => updateStrategy('name', e.target.value),
                        placeholder: 'e.g., Put Credit Spread 30 DTE'
                    })
                ),

                React.createElement('div', { className: 'form-group' },
                    React.createElement('label', null, 'Description'),
                    React.createElement('textarea', {
                        className: 'form-control',
                        value: currentStrategy.description,
                        onChange: (e) => updateStrategy('description', e.target.value),
                        placeholder: 'Describe your strategy...',
                        rows: 3
                    })
                ),

                React.createElement('div', { className: 'form-group' },
                    React.createElement('label', null, 'Strategy Type'),
                    React.createElement('select', {
                        className: 'form-control',
                        value: currentStrategy.strategy_type,
                        onChange: (e) => updateStrategy('strategy_type', e.target.value)
                    },
                        React.createElement('option', { value: 'custom' }, 'Custom'),
                        React.createElement('option', { value: 'credit_spread' }, 'Credit Spread'),
                        React.createElement('option', { value: 'iron_condor' }, 'Iron Condor'),
                        React.createElement('option', { value: 'butterfly' }, 'Butterfly'),
                        React.createElement('option', { value: 'strangle' }, 'Strangle'),
                        React.createElement('option', { value: 'straddle' }, 'Straddle')
                    )
                ),

                React.createElement('div', { className: 'form-group' },
                    React.createElement('label', null, 'Opening Action *'),
                    React.createElement('select', {
                        className: 'form-control',
                        value: currentStrategy.opening_action,
                        onChange: (e) => updateStrategy('opening_action', e.target.value)
                    },
                        React.createElement('option', { value: 'STO' }, 'STO (Sell to Open)'),
                        React.createElement('option', { value: 'BTO' }, 'BTO (Buy to Open)')
                    )
                ),

                React.createElement('div', { className: 'form-row' },
                    React.createElement('div', { className: 'form-group' },
                        React.createElement('label', null, 'DTE Range'),
                        React.createElement('div', { className: 'dte-inputs' },
                            React.createElement('input', {
                                type: 'number',
                                className: 'form-control',
                                value: currentStrategy.dte_range_min,
                                onChange: (e) => updateStrategy('dte_range_min', parseInt(e.target.value) || 0),
                                min: 0,
                                max: 90,
                                placeholder: 'Min'
                            }),
                            React.createElement('span', { className: 'range-separator' }, ' to '),
                            React.createElement('input', {
                                type: 'number',
                                className: 'form-control',
                                value: currentStrategy.dte_range_max,
                                onChange: (e) => updateStrategy('dte_range_max', parseInt(e.target.value) || 0),
                                min: 0,
                                max: 90,
                                placeholder: 'Max'
                            })
                        )
                    )
                ),

                React.createElement('div', { className: 'form-row' },
                    React.createElement('div', { className: 'form-group' },
                        React.createElement('label', null, `Profit Target: ${currentStrategy.profit_target_pct}%`),
                        React.createElement('input', {
                            type: 'range',
                            className: 'form-range',
                            value: currentStrategy.profit_target_pct,
                            onChange: (e) => updateStrategy('profit_target_pct', parseInt(e.target.value)),
                            min: 10,
                            max: 100,
                            step: 5
                        })
                    ),
                    React.createElement('div', { className: 'form-group' },
                        React.createElement('div', { className: 'checkbox-group' },
                            React.createElement('label', null,
                                React.createElement('input', {
                                    type: 'checkbox',
                                    checked: currentStrategy.no_stop_loss,
                                    onChange: (e) => updateStrategy('no_stop_loss', e.target.checked)
                                }),
                                ' No Stop Loss'
                            )
                        ),
                        !currentStrategy.no_stop_loss && React.createElement('div', null,
                            React.createElement('label', null, `Stop Loss: ${currentStrategy.stop_loss_pct}%`),
                            React.createElement('input', {
                                type: 'range',
                                className: 'form-range',
                                value: currentStrategy.stop_loss_pct,
                                onChange: (e) => updateStrategy('stop_loss_pct', parseInt(e.target.value)),
                                min: 100,
                                max: 500,
                                step: 25
                            })
                        )
                    )
                ),

                React.createElement('div', { className: 'form-row' },
                    React.createElement('div', { className: 'form-group' },
                        React.createElement('label', null, 'Minimum Premium Required ($)'),
                        React.createElement('input', {
                            type: 'number',
                            className: 'form-control',
                            value: currentStrategy.minimum_premium_required,
                            onChange: (e) => updateStrategy('minimum_premium_required', parseFloat(e.target.value) || 0),
                            step: 0.01,
                            min: 0,
                            placeholder: '1.00'
                        })
                    ),
                    React.createElement('div', { className: 'form-group' },
                        React.createElement('label', null, 'Minimum Underlying Price ($)'),
                        React.createElement('input', {
                            type: 'number',
                            className: 'form-control',
                            value: currentStrategy.minimum_underlying_price,
                            onChange: (e) => updateStrategy('minimum_underlying_price', parseFloat(e.target.value) || 0),
                            step: 1,
                            min: 0,
                            placeholder: '45'
                        })
                    )
                ),

                React.createElement('div', { className: 'form-group' },
                    React.createElement('label', null, 'Closing Options'),
                    React.createElement('div', { className: 'checkbox-group' },
                        React.createElement('label', null,
                            React.createElement('input', {
                                type: 'checkbox',
                                checked: currentStrategy.closing_21_dte,
                                onChange: (e) => updateStrategy('closing_21_dte', e.target.checked)
                            }),
                            ' Close at 21 DTE'
                        )
                    )
                )
            ),

            // Legs Configuration Tab
            activeTab === 'legs' && React.createElement('div', { className: 'legs-tab' },
                React.createElement('div', { className: 'legs-header' },
                    React.createElement('h4', null, 'Option Legs Configuration'),
                    React.createElement('button', {
                        className: 'btn btn-primary',
                        onClick: addLeg
                    }, '➕ Add Leg')
                ),

                currentStrategy.legs.length === 0 && React.createElement('div', { className: 'empty-legs' },
                    'No legs configured. Click "Add Leg" to start building your strategy.'
                ),

                currentStrategy.legs.length > 0 && React.createElement('div', { className: 'legs-table-container' },
                    React.createElement('table', { className: 'legs-table' },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', null, 'Leg'),
                                React.createElement('th', null, 'Action'),
                                React.createElement('th', null, 'Type'),
                                React.createElement('th', null, 'Quantity'),
                                React.createElement('th', null, 'Strike Selection Method'),
                                React.createElement('th', null, 'Selection Value'),
                                React.createElement('th', null, 'Actions')
                            )
                        ),
                        React.createElement('tbody', null,
                            currentStrategy.legs.map((leg, index) => 
                                React.createElement('tr', { key: index },
                                    React.createElement('td', null, `Leg ${index + 1}`),
                                    React.createElement('td', null,
                                        React.createElement('select', {
                                            className: 'form-control table-select',
                                            value: leg.action,
                                            onChange: (e) => updateLeg(index, 'action', e.target.value)
                                        },
                                            React.createElement('option', { value: 'buy' }, 'Buy'),
                                            React.createElement('option', { value: 'sell' }, 'Sell')
                                        )
                                    ),
                                    React.createElement('td', null,
                                        React.createElement('select', {
                                            className: 'form-control table-select',
                                            value: leg.option_type,
                                            onChange: (e) => updateLeg(index, 'option_type', e.target.value)
                                        },
                                            React.createElement('option', { value: 'call' }, 'Call'),
                                            React.createElement('option', { value: 'put' }, 'Put')
                                        )
                                    ),
                                    React.createElement('td', null,
                                        React.createElement('input', {
                                            type: 'number',
                                            className: 'form-control table-input',
                                            value: leg.quantity,
                                            onChange: (e) => updateLeg(index, 'quantity', parseInt(e.target.value) || 1),
                                            min: 1
                                        })
                                    ),
                                    React.createElement('td', null,
                                        React.createElement('select', {
                                            className: 'form-control table-select',
                                            value: leg.selection_method,
                                            onChange: (e) => updateLeg(index, 'selection_method', e.target.value)
                                        },
                                            React.createElement('option', { value: 'atm' }, 'At The Money (ATM)'),
                                            React.createElement('option', { value: 'offset' }, 'Strike Offset'),
                                            React.createElement('option', { value: 'percentage' }, 'Percentage from Current'),
                                            React.createElement('option', { value: 'premium' }, 'Premium Target'),
                                            React.createElement('option', { value: 'atm_straddle' }, 'ATM Straddle %')
                                        )
                                    ),
                                    React.createElement('td', null,
                                        (leg.selection_method === 'offset' || leg.selection_method === 'percentage' || leg.selection_method === 'atm_straddle') &&
                                        React.createElement('input', {
                                            type: 'number',
                                            className: 'form-control table-input',
                                            value: leg.selection_value || '',
                                            onChange: (e) => updateLeg(index, 'selection_value', parseFloat(e.target.value) || 0),
                                            step: leg.selection_method === 'offset' ? 1 : 0.01,
                                            placeholder: leg.selection_method === 'offset' ? '$5' : (leg.selection_method === 'atm_straddle' ? '100%' : '5%'),
                                            min: leg.selection_method === 'atm_straddle' ? 0 : undefined,
                                            max: leg.selection_method === 'atm_straddle' ? 200 : undefined,
                                            title: leg.selection_method === 'atm_straddle' ? '% of ATM straddle price (0-200%)' : ''
                                        }),
                                        leg.selection_method === 'premium' &&
                                        React.createElement('span', { 
                                            className: 'premium-target-info',
                                            title: 'Uses strategy minimum premium'
                                        }, 'Strategy Min Premium')
                                    ),
                                    React.createElement('td', null,
                                        React.createElement('button', {
                                            className: 'btn btn-danger btn-small',
                                            onClick: () => removeLeg(index)
                                        }, '🗑️')
                                    )
                                )
                            )
                        )
                    )
                )
            ),

            // Validation Tab
            activeTab === 'validation' && React.createElement('div', { className: 'validation-tab' },
                React.createElement('div', { className: 'validation-header' },
                    React.createElement('h4', null, 'Strategy Validation'),
                    React.createElement('p', null, 'Test your strategy configuration with live option chain data from SPY')
                ),

                React.createElement('div', { className: 'validation-actions' },
                    React.createElement('button', {
                        className: 'btn btn-primary',
                        onClick: validateStrategy,
                        disabled: isValidating || currentStrategy.legs.length === 0
                    }, isValidating ? '🔄 Validating...' : '✅ Validate Strategy')
                ),

                currentStrategy.legs.length === 0 && React.createElement('div', { className: 'validation-warning' },
                    '⚠️ Please add at least one leg to validate the strategy'
                ),

                validationResult && React.createElement('div', { 
                    className: `validation-result ${validationResult.valid ? 'valid' : 'invalid'}` 
                },
                    React.createElement('h5', null, 
                        validationResult.valid ? '✅ Strategy is Valid' : '❌ Validation Failed'
                    ),

                    validationResult.errors && validationResult.errors.length > 0 && 
                    React.createElement('div', { className: 'validation-errors' },
                        React.createElement('h6', null, 'Errors:'),
                        React.createElement('ul', null,
                            validationResult.errors.map((error, idx) =>
                                React.createElement('li', { key: idx }, error)
                            )
                        )
                    ),

                    validationResult.sample_trade && React.createElement('div', { className: 'sample-trade' },
                        React.createElement('h6', null, 'Sample Trade Parameters:'),
                        React.createElement('pre', null, 
                            JSON.stringify(validationResult.sample_trade, null, 2)
                        )
                    )
                )
            )
        )
    );
};

// Initialize the Strategy Builder when the DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 DOM loaded, initializing Strategy Builder...');
    console.log('📊 Current URL:', window.location.href);
    console.log('📱 User agent:', navigator.userAgent);
    
    // Wait for React to be loaded
    const initializeStrategyBuilder = () => {
        console.log('🔍 Checking for React and container...');
        console.log('⚛️ React available:', !!window.React, window.React);
        console.log('🔗 ReactDOM available:', !!window.ReactDOM, window.ReactDOM);
        
        const container = document.getElementById('strategy-builder-root');
        console.log('📦 Container found:', !!container, container);
        if (container) {
            console.log('📦 Container parent:', container.parentElement);
            console.log('📦 Container innerHTML:', container.innerHTML);
        }
        
        if (container && window.React && window.ReactDOM) {
            try {
                console.log('🎯 Creating Strategy Builder...');
                console.log('📦 Container visibility:', window.getComputedStyle(container).display);
                console.log('📦 Container parent visibility:', window.getComputedStyle(container.parentElement).display);
                
                // Add immediate fallback content
                container.innerHTML = '<div style="color: yellow; padding: 20px;">🔄 Loading Strategy Builder...</div>';
                
                // Use modern createRoot if available, otherwise fallback to legacy render
                if (ReactDOM.createRoot) {
                    console.log('⚛️ Using ReactDOM.createRoot...');
                    const root = ReactDOM.createRoot(container);
                    root.render(React.createElement(StrategyBuilder));
                } else {
                    console.log('⚛️ Using legacy ReactDOM.render...');
                    ReactDOM.render(React.createElement(StrategyBuilder), container);
                }
                console.log('✅ Strategy Builder React component rendered successfully');
            } catch (error) {
                console.error('❌ Error creating Strategy Builder:', error);
                console.error('❌ Error stack:', error.stack);
                // Last resort fallback
                try {
                    console.log('🔄 Trying fallback render...');
                    ReactDOM.render(React.createElement(StrategyBuilder), container);
                    console.log('✅ Strategy Builder initialized with fallback render');
                } catch (legacyError) {
                    console.error('❌ All render methods failed:', legacyError);
                    console.error('❌ Fallback error stack:', legacyError.stack);
                    // Show error message to user
                    container.innerHTML = '<div style="color: red; padding: 20px; border: 1px solid red;">❌ Strategy Builder failed to load. Error: ' + error.message + '</div>';
                }
            }
        } else {
            console.log('⏳ Missing dependencies - React:', !!window.React, 'ReactDOM:', !!window.ReactDOM, 'Container:', !!container);
            if (!container) {
                console.error('❌ Container element not found! Looking for #strategy-builder-root');
                const allElements = document.querySelectorAll('[id*="strategy"]');
                console.log('🔍 Found strategy-related elements:', allElements);
            }
            // Retry after a short delay if React isn't loaded yet
            setTimeout(initializeStrategyBuilder, 100);
        }
    };
    
    initializeStrategyBuilder();
});

// Also try to initialize when the strategy builder tab is clicked
document.addEventListener('click', (e) => {
    if (e.target.dataset.tab === 'strategy-builder') {
        console.log('Strategy Builder tab clicked');
        setTimeout(() => {
            const container = document.getElementById('strategy-builder-root');
            if (container && !container.hasChildNodes() && window.React && window.ReactDOM) {
                console.log('Re-initializing Strategy Builder...');
                try {
                    if (ReactDOM.createRoot) {
                        const root = ReactDOM.createRoot(container);
                        root.render(React.createElement(StrategyBuilder));
                    } else {
                        ReactDOM.render(React.createElement(StrategyBuilder), container);
                    }
                    console.log('✅ Strategy Builder re-initialized successfully');
                } catch (error) {
                    console.error('❌ Error re-initializing:', error);
                    ReactDOM.render(React.createElement(StrategyBuilder), container);
                }
            }
        }, 100);
    }
});