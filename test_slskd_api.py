#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SLSKD API Connection Test Script
Tests the SLSKD API endpoint with proper authentication
"""

import requests
import json
import sys

# Your SLSKD configuration
SLSKD_API_KEY = "PV1RixwWGOi91oVYfSMhd7JNVy1hj6jpcBOcdM+z1mKB+JnIQ2c4nwVWLgYi2JHd"
SLSKD_HOST = "http://10.0.0.100:5030"

def test_slskd_connection():
    """Test SLSKD API connectivity and authentication"""
    
    print("=" * 60)
    print("SLSKD API Connection Test")
    print("=" * 60)
    
    headers = {"X-API-Key": SLSKD_API_KEY}
    
    # Test 1: Application endpoint
    print("\n[TEST 1] Testing /api/v0/application endpoint...")
    try:
        url = f"{SLSKD_HOST}/api/v0/application"
        print(f"URL: {url}")
        
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("✓ SUCCESS - Application endpoint working")
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2)}")
        elif response.status_code == 401:
            print("✗ FAILED - Authentication failed (401)")
            print("Check if your API key is correct in SLSKD config")
            return False
        else:
            print(f"✗ FAILED - Unexpected status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError as e:
        print(f"✗ FAILED - Cannot connect to SLSKD")
        print(f"Error: {e}")
        print(f"Make sure SLSKD is running and accessible at {SLSKD_HOST}")
        return False
    except Exception as e:
        print(f"✗ FAILED - Unexpected error: {e}")
        return False
    
    # Test 2: Transfers endpoint
    print("\n[TEST 2] Testing /api/v0/transfers endpoint...")
    try:
        url = f"{SLSKD_HOST}/api/v0/transfers"
        print(f"URL: {url}")
        
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("✓ SUCCESS - Transfers endpoint working")
            data = response.json()
            print(f"Found {len(data)} transfers")
            
            # Show active transfers
            active = [t for t in data if t.get("state") not in ("completed", "succeeded")]
            print(f"Active transfers: {len(active)}")
            
            if active:
                print("\nActive transfer details:")
                for t in active[:5]:  # Show first 5
                    print(f"  - {t.get('username', 'Unknown')}: {t.get('filename', 'Unknown')}")
                    print(f"    State: {t.get('state', 'Unknown')}")
                    print(f"    Progress: {t.get('bytesTransferred', 0)}/{t.get('size', 0)} bytes")
            else:
                print("No active transfers currently")
                
            return True
        else:
            print(f"✗ FAILED - Status code: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return False
            
    except Exception as e:
        print(f"✗ FAILED - Error: {e}")
        return False
    
    # Test 3: Session endpoint
    print("\n[TEST 3] Testing /api/v0/session endpoint...")
    try:
        url = f"{SLSKD_HOST}/api/v0/session"
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("✓ SUCCESS - Session endpoint working")
            data = response.json()
            print(f"Username: {data.get('username', 'N/A')}")
            print(f"Listening: {data.get('listening', False)}")
        else:
            print(f"Status code: {response.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    try:
        success = test_slskd_connection()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
