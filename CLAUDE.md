# Claude Code Instructions

Comprehensive guidelines for working on the **Tastytrade Advanced Portfolio Management System** - a Flask app that monitors portfolios, provides real-time delta tracking, and auto-recommends trades for diversified active trading portfolios.

## I. Communication & Response Style

- **Always answer in short, concise responses unless explicitly asked for detailed explanations**
- Use notes/scratch pad to avoid losing plans during multi-step changes
- **Read entire files instead of just parts** - understand full context before changes

## II. Critical Testing Protocol

### **ALWAYS Test Changes**
1. Make code changes
2. **Restart backend after every functional change**
3. Test the specific functionality modified
4. Verify fix actually works as intended
5. Check for regressions

## III. Highest Priority: SDK & Codebase First

### **CRITICAL: Check These First**
1. **tastytrade-sdk-reference docs** - always reference before writing custom code
2. **Existing codebase** - look for reusable functions/classes
3. Use existing patterns and SDK methods when possible
4. Only create new code if SDK doesn't provide functionality

## IV. Code Quality Essentials

### Core Principles
- **DRY**: Reuse existing code, suggest abstractions for 3+ repetitions
- **KISS**: Simple solutions unless complexity justified
- **No hardcoded secrets** - use environment variables
- **Never overwrite .env without explicit user confirmation**

### Error Handling
- Wrap API calls and file I/O in try-catch blocks
- Save error logs to `.txt` files for debugging
- Provide user-friendly error messages for novices

### Debugging Approach
**Avoid jumping to conclusions:**
1. Identify 2-3 potential causes
2. Analyze logs and code context
3. Cross-reference with existing codebase
4. Suggest fix with explanation

## V. Project-Specific Guidelines

### Tastytrade Integration
- Handle authentication tokens properly
- Implement retry logic for API failures
- Use fallback mechanisms for missing data
- Validate API responses before processing

### Portfolio Management Features
- Validate financial calculations thoroughly
- Handle multiple account types correctly
- Implement proper delta and risk calculations
- Ensure trade recommendations are well-documented

### WebSocket & Real-time Data
- Handle connection lifecycle properly
- Implement reconnection logic
- Process real-time updates efficiently
- Handle dual-channel subscriptions

### Flask Application
- Follow RESTful principles for routes
- Return consistent JSON responses
- Use appropriate HTTP status codes
- Implement proper session management

## VI. Security & Risk Management

- Treat all trading data as sensitive
- Implement data validation for financial calculations
- **Provide disclaimers about informational use only**
- Monitor for unusual API usage patterns
- Use secure token storage methods

## VII. File Structure & Dependencies

### Python Standards
- Follow PEP 8 conventions
- Use Poetry for dependency management
- Keep files under 200-300 lines
- Use meaningful variable/function names

### Error Categories to Handle
- **API Errors**: Network, auth, rate limiting, invalid responses
- **Data Processing**: Missing data, calculation errors, type conversion
- **WebSocket**: Connection drops, parsing failures, stream interruptions
- **Application**: Template rendering, routing, configuration issues

## VIII. Development Workflow

### Before Making Changes
1. Check tastytrade-sdk-reference docs
2. Review existing codebase for similar functionality
3. Plan changes using notes/scratch pad
4. Read entire relevant files

### After Making Changes
1. Restart backend
2. Test specific functionality
3. Verify fix works
4. Check for side effects
5. Document significant changes

---

**Remember**: This is a financial trading system. Prioritize accuracy, test thoroughly, and always verify calculations. When in doubt, provide detailed explanations for financial logic.