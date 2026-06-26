import json
import os
import urllib.request
import urllib.error
import threading
import uuid
import time
from datetime import datetime, timezone

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")

def send_transaction(payload):
    url = f"{API_BASE}/transaction"
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        data = json.dumps(payload).encode('utf-8')
        with urllib.request.urlopen(req, data=data) as response:
            return response.getcode(), json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.getcode(), json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.getcode(), {"detail": e.reason}
    except Exception as e:
        return 500, {"detail": str(e)}

def get_summary(user_id):
    url = f"{API_BASE}/summary/{user_id}"
    try:
        with urllib.request.urlopen(url) as response:
            return response.getcode(), json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.getcode(), json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.getcode(), {"detail": e.reason}
    except Exception as e:
        return 500, {"detail": str(e)}

def test_idempotency():
    print("\n--- Running Test 1: Database-level Idempotency ---")
    tx_id = f"test-idemp-{uuid.uuid4()}"
    user_id = f"user-idemp-{uuid.uuid4()}"
    amount = 150.0
    timestamp = datetime.now(timezone.utc).isoformat()
    
    payload = {
        "transactionId": tx_id,
        "userId": user_id,
        "amount": amount,
        "timestamp": timestamp
    }
    
    results = []
    threads = []
    
    def worker():
        status, body = send_transaction(payload)
        results.append((status, body))
        
    # Fire 5 parallel threads with the EXACT same transaction payload
    # (Matches our rate limit limit of 5 requests per 10 seconds)
    for _ in range(5):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    successes = [r for r in results if r[0] == 200]
    conflicts = [r for r in results if r[0] == 409]
    
    print(f"Total requests: {len(results)}")
    print(f"Success responses (HTTP 200): {len(successes)}")
    print(f"Conflict responses (HTTP 409): {len(conflicts)}")
    
    # Assertions
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(conflicts) == 4, f"Expected exactly 4 conflicts, got {len(conflicts)}"
    print("[PASS] Test 1 Passed: Database-level unique constraint successfully blocked duplicate transaction processing!")

def test_concurrency_consistency():
    print("\n--- Running Test 2: Concurrency & Database Write Locks ---")
    user_id = f"user-concur-{uuid.uuid4()}"
    amount = 50.0
    timestamp = datetime.now(timezone.utc).isoformat()
    
    results = []
    threads = []
    
    def worker(tx_id):
        payload = {
            "transactionId": tx_id,
            "userId": user_id,
            "amount": amount,
            "timestamp": timestamp
        }
        status, body = send_transaction(payload)
        results.append((status, body))
        
    # Fire 5 concurrent requests for the SAME user, but with UNIQUE transaction IDs
    # (Matches our rate limit limit of 5 requests per 10 seconds)
    for _ in range(5):
        tx_id = f"tx-concur-{uuid.uuid4()}"
        t = threading.Thread(target=worker, args=(tx_id,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    successes = [r for r in results if r[0] == 200]
    print(f"Total requests sent: 5")
    print(f"Success responses (HTTP 200): {len(successes)}")
    
    assert len(successes) == 5, f"Expected all 5 transactions to succeed, got {len(successes)}"
    
    # Verify summary consistency
    time.sleep(0.5) # Small pause to let DB commit finish
    status, summary = get_summary(user_id)
    assert status == 200, f"Failed to get user summary: {summary}"
    
    expected_total_spent = 50.0 * 5.0 # 250.0
    actual_total_spent = summary["total_spent"]
    actual_tx_count = summary["transaction_count"]
    
    print(f"Expected total spent: ${expected_total_spent:.2f}")
    print(f"Actual total spent:   ${actual_total_spent:.2f}")
    print(f"Actual transaction count: {actual_tx_count}")
    
    # Assert consistency
    assert actual_total_spent == expected_total_spent, f"Data consistency failure! Total spent mismatch. Expected {expected_total_spent}, got {actual_total_spent}"
    assert actual_tx_count == 5, f"Data consistency failure! Count mismatch. Expected 5, got {actual_tx_count}"
    print("[PASS] Test 2 Passed: Concurrent write locks prevented lost updates. Aggregates are 100% consistent!")

if __name__ == "__main__":
    print("Starting Concurrency & Idempotency verification suite...")
    try:
        test_idempotency()
        test_concurrency_consistency()
        print("\n[SUCCESS] All automated tests completed successfully!")
    except AssertionError as e:
        print(f"\n[FAIL] Test verification failed: {str(e)}")
    except Exception as e:
        print(f"\n[ERROR] An error occurred: {str(e)}")
