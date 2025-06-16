#!/usr/bin/env python3
"""
Route Verification Script
Checks if the underlyings routes are properly registered
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from flask import Flask
    from screener_backend import create_screener_routes
    
    # Create a test Flask app
    app = Flask(__name__)
    
    # Create a dummy tracker class for testing
    class DummyTracker:
        def __init__(self):
            self.tasty_client = None
    
    tracker = DummyTracker()
    
    # Register the routes
    create_screener_routes(app, tracker)
    
    # Get all registered routes
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append(f"{rule.methods} {rule.rule}")
    
    # Filter for underlyings routes
    underlyings_routes = [route for route in routes if 'underlyings' in route]
    
    print("🔍 Route Verification Results:")
    print("=" * 50)
    
    if underlyings_routes:
        print("✅ Underlyings routes found:")
        for route in underlyings_routes:
            print(f"   {route}")
    else:
        print("❌ No underlyings routes found!")
    
    print(f"\n📊 Total routes registered: {len(routes)}")
    
    # Check if the main route exists
    main_route_exists = any('/underlyings' in route and 'GET' in route for route in underlyings_routes)
    api_route_exists = any('/api/underlyings' in route and 'GET' in route for route in underlyings_routes)
    
    print(f"\n🎯 Route Status:")
    print(f"   Main route (/underlyings): {'✅ Found' if main_route_exists else '❌ Missing'}")
    print(f"   API route (/api/underlyings): {'✅ Found' if api_route_exists else '❌ Missing'}")
    
    # Check template file
    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'underlyings.html')
    template_exists = os.path.exists(template_path)
    print(f"   Template file: {'✅ Found' if template_exists else '❌ Missing'}")
    
    print("\n" + "=" * 50)
    if main_route_exists and template_exists:
        print("🎉 Setup looks correct! If you're getting 404, try:")
        print("   1. Restart the backend: pkill -f delta_backend.py && python3 delta_backend.py")
        print("   2. Access: http://localhost:5001/underlyings")
        print("   3. Check backend logs for any errors")
    else:
        print("❌ Issues found that need to be fixed!")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the TastyTracker directory")
except Exception as e:
    print(f"❌ Error: {e}")