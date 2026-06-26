# LedgerBoard: Fair Ranking & Concurrency Engine

A high-performance Python-based transaction ranking service and interactive simulation frontend built to demonstrate API design, concurrency handling, database-level idempotency, and abuse-resistant ranking rules.

### 🎯 Quick Links

- **Live URL**: [https://ledgerboard-fair-ranking-and-concurrency.onrender.com](https://ledgerboard-fair-ranking-and-concurrency.onrender.com)
- **Demo Video**: [Watch 5-minute technical walkthrough](https://drive.google.com/file/d/1AuBapk966Vj3XYTG0pJaug-l3-uHimiT/view?usp=sharing)

---

## ⚡ Quick Start: How to Run

You can spin up the entire application (both frontend and backend) with a single command. 

### Prerequisites
- Python 3.10+ installed.

### Start the Server
Run the automation script from the project root:
```bash
python run.py
```
This script will:
1. Initialize a Python virtual environment (`.venv`).
2. Upgrade `pip` and install all dependencies from `requirements.txt`.
3. Launch the FastAPI server at `http://0.0.0.0:8000` (accessible locally at `http://127.0.0.1:8000`) with hot-reloading active.

### Accessing the App
- **Interactive UI (Frontend)**: Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.
- **Interactive Swagger Docs**: Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to test endpoints without Postman.
- **Health Check**: `GET /health` returns `{"status": "ok"}`.

---

## 🌐 Live Deployment

The app is a single FastAPI service that serves both the API and frontend static files, so one deployment covers everything.

### Option A: Render (recommended)

1. Push this repo to GitHub.
2. Create a new **Web Service** on [Render](https://render.com).
3. Connect the repo — Render will detect `render.yaml` automatically.
4. Deploy. Render sets `PORT` and starts: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
5. Copy your live URL (e.g. `https://ledgerboard.onrender.com`) into the section below.

### Option B: Docker

```bash
docker build -t ledgerboard .
docker run -p 8000:8000 ledgerboard
```

Open `http://localhost:8000`.

> **Note:** Render's free tier spins down after ~15 minutes of inactivity. The first request after sleep can take ~30–60 seconds and may briefly return `404`/`503` while the service wakes. The frontend retries automatically; posting a transaction also wakes the server.

---

## 🛠️ System Architecture & Schema

The backend uses **FastAPI** for route management and validation, alongside **SQLite** running in **WAL (Write-Ahead Logging) mode** with a `busy_timeout` of `5000`ms. This setup guarantees that concurrent read and write operations are processed safely without deadlock.

### Database Schema

#### 1. `transactions` Table
Tracks every validated transaction.
```sql
CREATE TABLE transactions (
    transaction_id TEXT PRIMARY KEY,   -- Enforces idempotency at the DB layer
    user_id TEXT NOT NULL,             -- Indexed for rapid aggregations
    amount REAL NOT NULL,
    timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

#### 2. `user_summaries` Table
Holds real-time aggregated metrics and calculated fair scores.
```sql
CREATE TABLE user_summaries (
    user_id TEXT PRIMARY KEY,
    total_spent REAL NOT NULL DEFAULT 0.0,
    transaction_count INTEGER NOT NULL DEFAULT 0,
    active_days INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0.0,   -- Indexed descending for fast leaderboard fetches
    last_transaction_time TEXT
);
```

---

## 📈 Fair Ranking Logic

To prevent leaderboard manipulation (such as spamming micro-transactions or submitting single massive anomalies), we use a three-part scoring formula:

$$\text{Score} = (\text{Total Spent} \times 0.5) + (\log_2(1 + \text{Transaction Count}) \times 100) + (\text{Active Days} \times 5)$$

### Score Components
1. **Spend Volume (`Total Spent * 0.5`)**:
   Spend volume is the primary metric, rewarding users who drive transaction value.
2. **Frequency (`log2(1 + Transaction Count) * 100`)**:
   Rewards active users, but uses a logarithmic scale to enforce diminishing returns. This prevents users from spamming 10,000 tiny transactions to inflate their score.
3. **Consistency (`Active Days * 5`)**:
   Counts unique calendar days from server-recorded `created_at` timestamps (not client `timestamp`). This rewards users who submit transactions on different days while preventing backdating abuse.

`points_awarded` in the transaction response is a display metric (10% of amount, rounded) returned to the client only — it is not stored and does not affect ranking.

### Rank Tie-Breaking
Both `/ranking` and `/summary` use **competition ranking**: users with the same score share the same rank (e.g. two users at rank 1, next user is rank 3). When scores tie on the leaderboard, users are ordered by earliest `last_transaction_time` (derived from `MAX(timestamp)` per user).

### Abuse Prevention Rules
- **Floor Limits**: Transactions under `$0.10` are rejected (prevents micro-spam).
- **Ceiling Limits**: Transactions over `$10,000.00` are rejected (prevents artificial score bloating).
- **String Boundaries**: `userId` is capped at 50 characters, and `transactionId` is capped at 100 characters to prevent SQL payload abuse.
- **Future Dates**: Transactions with timestamps dated more than 60 seconds into the future are rejected.
- **Past Dates**: Timestamps more than 365 days in the past are rejected.
- **Rate Limiting**: Users are capped at a maximum of **5 transactions per 10 seconds**. Requests exceeding this return a `429 Too Many Requests` error. Duplicate requests are rolled back and removed from rate-limit accounting whenever possible.

---

## 🛡️ Concurrency & Duplicate Prevention

### 1. Database-Level Idempotency
We avoid using a pre-flight duplicate check (which is vulnerable to race conditions where two simultaneous check requests both see "no duplicate" and then both write).
Instead, the database is the single source of truth. We try to execute an `INSERT` statement directly:
- If the `transaction_id` is unique, the database writes it.
- If the `transaction_id` already exists, SQLite raises an `IntegrityError` due to the primary key constraint. The backend catches this exception, rolls back the transaction immediately, and returns an `HTTP 409 Conflict` response to the client.

### 2. Atomic Aggregations & Locks
To prevent lost updates (e.g., when two concurrent requests for the same user try to update `total_spent` at the exact same millisecond), we wrap the operations inside an explicit **`BEGIN IMMEDIATE`** transaction. 

This lock ensures that once a write transaction starts, no other thread can begin a write block until the current transaction commits. Aggregates are recalculated and written inside this atomic lock block:
```python
# Inside the connection context block:
conn.execute("BEGIN IMMEDIATE")
# 1. Insert transaction (fails here on duplicate key)
conn.execute("INSERT INTO transactions ...")
# 2. Recalculate values
row = conn.execute("SELECT SUM(amount)...")
active_days = conn.execute("SELECT COUNT(DISTINCT date(created_at))...")
last_tx = conn.execute("SELECT MAX(timestamp) ...")
# 3. Write summary
conn.execute("INSERT ... ON CONFLICT DO UPDATE ...")
# 4. Commit atomically
conn.commit()
```

---

## 🔌 API Documentation

### 1. Record Transaction
* **Endpoint**: `POST /transaction`
* **Request Body**:
  ```json
  {
    "transactionId": "tx-unique-uuid-12345",
    "userId": "user_dev",
    "amount": 250.00,
    "timestamp": "2026-06-25T03:52:33Z"
  }
  ```
* **Success Response (HTTP 200)**:
  ```json
  {
    "status": "success",
    "transaction_id": "tx-unique-uuid-12345",
    "points_awarded": 25,
    "current_score": 230.0
  }
  ```
* **Duplicate Error (HTTP 409)**:
  ```json
  {
    "detail": "Duplicate transaction: Transaction ID 'tx-unique-uuid-12345' has already been processed."
  }
  ```
* **Rate Limit Error (HTTP 429)**:
  ```json
  {
    "detail": "Rate limit exceeded. Maximum 5 transactions per 10 seconds per user is allowed."
  }
  ```

### 2. Get User Summary
* **Endpoint**: `GET /summary/{userId}`
* **Success Response (HTTP 200)**:
  ```json
  {
    "user_id": "user_dev",
    "total_spent": 250.0,
    "transaction_count": 1,
    "average_transaction": 250.0,
    "score": 230.0,
    "rank": 1
  }
  ```

### 3. Get Leaderboard Rankings
* **Endpoint**: `GET /ranking`
* **Query Params**: `limit` (default: 100, max: 500)
* **Success Response (HTTP 200)**:
  ```json
  [
    {
      "rank": 1,
      "user_id": "user_dev",
      "score": 230.0,
      "total_spent": 250.0,
      "transaction_count": 1,
      "active_days": 1,
      "last_transaction_time": "2026-06-25T03:52:33Z"
    }
  ]
  ```

---

## 🧪 Running Automated Verification Tests

Verify all concurrency and idempotency mechanics using the automated test suite:
1. Ensure the backend server is running (`python run.py`).
2. Run the test script in a separate terminal:
```bash
python test_concurrency.py
```
This runs:
- **Idempotency Test**: Fires 5 identical transaction payloads concurrently. Verifies that exactly 1 succeeds and 4 are blocked with HTTP 409.
- **Concurrency Test**: Fires 5 unique transaction payloads for the same user concurrently. Verifies that all 5 succeed and that the user's final aggregates are 100% consistent (no lost updates).

The frontend simulator mirrors these same 5-request concurrency checks, and also includes a separate rate-limit test that sends 7 rapid requests to trigger the 5 requests per 10 seconds rule.

---

## 📋 Assumptions & Limitations

| Topic | Decision |
|-------|----------|
| **Database** | Single-file SQLite (`app.db`). Suitable for demo/single-instance deploys; not horizontally scaled. |
| **Rate limiter** | In-memory sliding window per `userId`. Resets on restart; not shared across multiple server workers. |
| **Active days** | Based on server `created_at`, so consistency reflects when transactions were recorded by this service. |
| **Client timestamp** | Used for display and `last_transaction_time` (`MAX(timestamp)`); validated to be within ±365 days / +60s of server time. |
| **Amounts** | Stored as SQLite `REAL` (floating point). Acceptable for this assignment; production would use decimal types. |
| **Authentication** | None — endpoints are open for demonstration. Rate limits and validation provide basic abuse resistance. |
| **Idempotent retries** | Duplicate `transactionId` returns `409 Conflict` (not `200` with cached response). Processing is still prevented at the DB layer. |
