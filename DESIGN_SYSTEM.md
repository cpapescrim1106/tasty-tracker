# TastyTracker Design System

## Overview
This design system defines the visual language and component standards for TastyTracker, inspired by Tastytrade's compact, data-dense interface design. The goal is to maximize information density while maintaining readability and usability.

## Core Design Principles

### 1. **Density First**
- Maximize data per screen without scrolling
- Minimize whitespace while maintaining visual hierarchy
- Use horizontal layouts over vertical stacking
- Target 70% space reduction compared to typical web apps

### 2. **Professional Trading Interface**
- Dark theme optimized for extended viewing
- High contrast for critical data
- Subtle visual indicators over heavy borders
- Real-time data visualization

### 3. **Efficiency**
- Inline editing wherever possible
- No unnecessary modals or dialogs
- Quick actions always visible
- Keyboard shortcuts for power users

## Typography

### Font Stack
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
```

### Font Sizes (Compact Mode)
- **Base text**: 13px (line-height: 1.3)
- **Section headers**: 14px (uppercase, letter-spacing: 0.5px)
- **Table headers**: 12px (uppercase)
- **Small labels**: 12px
- **Button text**: 12px
- **Tooltips**: 12px
- **Data values**: 13px
- **Status text**: 11px

### Font Weights
- **Regular**: 400 (body text, data)
- **Medium**: 500 (buttons, important values)
- **Semibold**: 600 (headers, emphasis)

## Color Palette

### Primary Colors
```css
--primary-bg: #1a1f2e;        /* Main background */
--secondary-bg: #1e2936;      /* Card backgrounds */
--tertiary-bg: #252d3d;       /* Nested elements */
--border-color: #2a3f5f;      /* Subtle borders */
```

### Text Colors
```css
--text-primary: #e1e5eb;      /* Main text */
--text-secondary: #a0aec0;    /* Labels */
--text-muted: #8b98a8;        /* Muted text */
--text-accent: #60a5fa;       /* Links, highlights */
```

### Status Colors
```css
--status-positive: #10b981;   /* Profit, success */
--status-negative: #ef4444;   /* Loss, error */
--status-warning: #f59e0b;    /* Warning */
--status-info: #3b82f6;       /* Information */
--status-neutral: #6b7280;    /* Neutral state */
```

### Accent Colors
```css
--accent-purple: #8b5cf6;     /* Special actions */
--accent-blue: #3b82f6;       /* Primary actions */
--accent-green: #10b981;      /* Positive actions */
```

## Layout & Spacing

### Grid System
- **Desktop**: 3-column layout (320px | 1fr | 280px)
- **Tablet**: 2-column layout
- **Mobile**: Single column stack

### Spacing Scale
```css
--space-xs: 4px;
--space-sm: 6px;
--space-md: 8px;
--space-lg: 12px;
--space-xl: 16px;
--space-2xl: 20px;
```

### Component Spacing
- **Table cell padding**: 3px 6px
- **Button padding**: 4px 10px
- **Input padding**: 2px 4px
- **Card padding**: 8px
- **Section margin**: 12px

## Components

### Tables (Compact)
```css
.compact-table {
    font-size: 13px;
    border-collapse: collapse;
}

.compact-table th {
    background: var(--primary-bg);
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    padding: 4px 6px;
    border-bottom: 1px solid var(--border-color);
}

.compact-table td {
    padding: 3px 6px;
    border-bottom: 1px solid rgba(42, 63, 95, 0.3);
    color: var(--text-primary);
}
```

### Inputs (Inline)
```css
.inline-input {
    background: var(--primary-bg);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 2px 4px;
    font-size: 13px;
    width: 60px;
    border-radius: 2px;
}

.inline-input:focus {
    outline: none;
    border-color: var(--text-accent);
}
```

### Buttons (Compact)
```css
.compact-btn {
    padding: 4px 10px;
    font-size: 12px;
    border: none;
    border-radius: 2px;
    cursor: pointer;
    transition: all 0.1s;
    font-weight: 500;
}

.compact-btn-primary {
    background: var(--accent-blue);
    color: white;
}

.compact-btn-save {
    background: var(--accent-green);
    color: white;
}
```

### Status Indicators
```css
.status-indicator {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 4px;
}

.status-compliant { background: var(--status-positive); }
.status-warning { background: var(--status-warning); }
.status-violation { background: var(--status-negative); }
```

## Layout Patterns

### 3-Column Dense Layout
```html
<div class="allocation-container">
    <!-- Left: Configuration (320px) -->
    <div class="config-panel">...</div>
    
    <!-- Center: Main Content (flexible) -->
    <div class="main-content">...</div>
    
    <!-- Right: Actions/Status (280px) -->
    <div class="action-panel">...</div>
</div>
```

### Inline Form Pattern
```html
<div class="limit-row">
    <span class="limit-label">Max Single Trade</span>
    <input type="number" class="inline-input" value="5000">
    <span class="percent-display">$</span>
</div>
```

### Fixed Action Bar
```html
<div class="action-bar">
    <div class="action-group">
        <!-- Status indicators -->
    </div>
    <div class="action-group">
        <!-- Action buttons -->
    </div>
</div>
```

## Responsive Breakpoints
- **Desktop**: > 1400px (full 3-column)
- **Laptop**: 1200-1400px (compressed 3-column)
- **Tablet**: 768-1200px (2-column)
- **Mobile**: < 768px (single column)

## Animation & Transitions
- **Hover effects**: 0.1s ease
- **State changes**: 0.2s ease
- **Page transitions**: 0.3s ease
- Keep animations subtle and functional

## Accessibility Guidelines
- **Contrast ratios**: Minimum 4.5:1 for normal text
- **Focus indicators**: Visible outline on all interactive elements
- **Keyboard navigation**: Full support with logical tab order
- **Screen reader**: Proper ARIA labels on complex components

## Implementation Notes

### CSS Architecture
1. Use CSS custom properties for theming
2. Component-based CSS organization
3. Mobile-first responsive design
4. Minimize specificity chains

### Performance
- Optimize for 60fps scrolling
- Lazy load heavy components
- Use CSS transforms for animations
- Minimize reflows and repaints

### Best Practices
1. Always use semantic HTML
2. Prefer CSS Grid/Flexbox over absolute positioning
3. Use rem/em for scalable sizing
4. Test on multiple screen sizes
5. Validate color contrast ratios

## Component Library

### Data Tables
- Use `.compact-table` class
- Sticky headers for long lists
- Hover states on rows
- Inline editing capabilities

### Form Controls
- Inline inputs for space efficiency
- Range sliders for percentages
- Compact checkboxes (12px)
- No unnecessary labels

### Navigation
- Tab-based interfaces
- Fixed position controls
- Breadcrumb trails for deep navigation
- Keyboard shortcuts displayed

## Usage Examples

### Compact Allocation Table
```html
<table class="compact-table">
    <thead>
        <tr>
            <th>Symbol</th>
            <th>Max%</th>
            <th>Current%</th>
            <th>Status</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>SPY</td>
            <td><input class="inline-input" value="15"></td>
            <td>14.2</td>
            <td><span class="status-indicator status-compliant"></span></td>
        </tr>
    </tbody>
</table>
```

### Delta Range Slider
```html
<div class="delta-range-item">
    <span class="compact-label">Bullish</span>
    <input type="range" class="delta-range-slider" min="0" max="100" value="60">
    <span class="percent-display">60%</span>
</div>
```

## Version History
- **v1.0** - Initial design system based on Tastytrade-inspired compact interface
- **v1.1** - Increased all font sizes by 2pt for improved readability

---

*This design system should be treated as a living document and updated as new patterns emerge or requirements change.*