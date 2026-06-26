import sqlite3
import math
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
import os

from database import init_db, get_db

# Initialize FastAPI app
app = FastAPI(
    title="Transaction Ranking API",
    description="Backend service demonstrating data consistency, idempotency, rate limiting, and fair ranking logic.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for maximum compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory sliding window rate limiter: 5 requests per 10 seconds
# Track rate limiting per user_id to prevent abuse on `/transaction`
rate_limit_store = defaultdict(list)
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 10  # in seconds
MAX_TIMESTAMP_AGE_DAYS = 365

# Ensure database is initialized on startup
@app.on_event("startup")
def startup_event():
    init_db()


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/ranking", "/summary", "/health", "/transaction")):
        response.headers["Cache-Control"] = "no-store"
    return response

# Pydantic Schemas for Request Validation
class TransactionCreate(BaseModel):
    transactionId: str = Field(..., min_length=1, max_length=100, description="Unique transaction identifier")
    userId: str = Field(..., min_length=1, max_length=50, description="User identifier")
    amount: float = Field(..., ge=0.10, le=10000.00, description="Transaction amount (0.10 to 10,000.00)")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of the transaction")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        try:
            # Parse ISO timestamp, replacing 'Z' with UTC offset representation if needed
            ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Timestamp must be in valid ISO 8601 format (e.g., YYYY-MM-DDTHH:MM:SSZ).")
        
        now = datetime.now(timezone.utc)
        if ts > now + timedelta(seconds=60):
            raise ValueError("Transaction timestamp cannot be in the future.")
        if ts < now - timedelta(days=MAX_TIMESTAMP_AGE_DAYS):
            raise ValueError(
                f"Transaction timestamp cannot be more than {MAX_TIMESTAMP_AGE_DAYS} days in the past."
            )

        return v

class TransactionResponse(BaseModel):
    status: str
    transaction_id: str
    points_awarded: int
    current_score: float

class UserSummaryResponse(BaseModel):
    user_id: str
    total_spent: float
    transaction_count: int
    average_transaction: float
    score: float
    rank: int

class RankingResponse(BaseModel):
    rank: int
    user_id: str
    score: float
    total_spent: float
    transaction_count: int
    active_days: int
    last_transaction_time: Optional[str]

# API Endpoints

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/transaction", response_model=TransactionResponse)
async def create_transaction(tx: TransactionCreate):
    # Abuse Prevention: Rate Limiting
    # Limit requests per user_id to prevent transaction spamming
    user_key = f"tx_limit:{tx.userId}"
    now_ts = time.time()
    
    # Clean up sliding window
    rate_limit_store[user_key] = [t for t in rate_limit_store[user_key] if now_ts - t < RATE_LIMIT_WINDOW]
    if len(rate_limit_store[user_key]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {RATE_LIMIT_MAX} transactions per {RATE_LIMIT_WINDOW} seconds per user is allowed."
        )
    rate_limit_store[user_key].append(now_ts)

    # Database insert and aggregate update (Data Consistency & Idempotency)
    with get_db() as conn:
        try:
            # Start immediate transaction to lock writes and prevent concurrency issues (race conditions)
            conn.execute("BEGIN IMMEDIATE")

            # 1. Attempt to insert transaction directly
            # Database UNIQUE constraint on transaction_id enforces idempotency.
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO transactions (transaction_id, user_id, amount, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tx.transactionId, tx.userId, tx.amount, tx.timestamp, now_iso)
            )

            # 2. Recalculate aggregates inside the same transaction block (Atomic Update)
            row = conn.execute(
                "SELECT SUM(amount) as total_spent, COUNT(*) as tx_count FROM transactions WHERE user_id = ?",
                (tx.userId,)
            ).fetchone()
            
            total_spent = row["total_spent"] or 0.0
            tx_count = row["tx_count"] or 0

            # Active days from server recorded time (created_at) to prevent backdating abuse.
            days_row = conn.execute(
                "SELECT COUNT(DISTINCT date(created_at)) as active_days FROM transactions WHERE user_id = ?",
                (tx.userId,)
            ).fetchone()
            active_days = days_row["active_days"] or 0

            last_tx_row = conn.execute(
                "SELECT MAX(timestamp) as last_transaction_time FROM transactions WHERE user_id = ?",
                (tx.userId,)
            ).fetchone()
            last_transaction_time = last_tx_row["last_transaction_time"]

            # Score = (Total Spent * 0.5) + (log2(1 + count) * 100) + (active_days * 5)
            score = (total_spent * 0.5) + (math.log2(1 + tx_count) * 100.0) + (active_days * 5.0)

            conn.execute(
                """
                INSERT INTO user_summaries (user_id, total_spent, transaction_count, active_days, score, last_transaction_time)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    total_spent = excluded.total_spent,
                    transaction_count = excluded.transaction_count,
                    active_days = excluded.active_days,
                    score = excluded.score,
                    last_transaction_time = excluded.last_transaction_time
                """,
                (tx.userId, total_spent, tx_count, active_days, score, last_transaction_time)
            )

            # Commit the transaction block atomically
            conn.commit()

            # Award points based on 10% of transaction amount (rounded to nearest integer)
            points_awarded = int(round(tx.amount * 0.1))

            return {
                "status": "success",
                "transaction_id": tx.transactionId,
                "points_awarded": points_awarded,
                "current_score": round(score, 2)
            }

        except sqlite3.IntegrityError:
            conn.rollback()
            # Duplicate was not processed — do not count it toward the rate limit
            if rate_limit_store[user_key]:
                rate_limit_store[user_key].pop()
            raise HTTPException(
                status_code=409,
                detail=f"Duplicate transaction: Transaction ID '{tx.transactionId}' has already been processed."
            )
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"Database transaction failed: {str(e)}")


@app.get("/summary/{userId}", response_model=UserSummaryResponse)
async def get_summary(userId: str):
    # Length validation on path parameter
    if len(userId) > 50 or len(userId) < 1:
        raise HTTPException(status_code=400, detail="User ID must be between 1 and 50 characters.")

    with get_db() as conn:
        # Calculate rank dynamically. Rank is (number of users with score > current user score) + 1.
        row = conn.execute(
            """
            SELECT 
                u.user_id, u.total_spent, u.transaction_count, u.score,
                (SELECT COUNT(*) FROM user_summaries WHERE score > u.score) + 1 AS rank
            FROM user_summaries u
            WHERE u.user_id = ?
            """,
            (userId,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"User '{userId}' has no transaction history.")

        average_transaction = 0.0
        if row["transaction_count"] > 0:
            average_transaction = row["total_spent"] / row["transaction_count"]

        return {
            "user_id": row["user_id"],
            "total_spent": round(row["total_spent"], 2),
            "transaction_count": row["transaction_count"],
            "average_transaction": round(average_transaction, 2),
            "score": round(row["score"], 2),
            "rank": row["rank"]
        }


@app.get("/ranking", response_model=List[RankingResponse])
async def get_ranking(limit: int = 100):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 500.")

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                user_id, total_spent, transaction_count, active_days, score, last_transaction_time,
                (SELECT COUNT(*) FROM user_summaries u2 WHERE u2.score > user_summaries.score) + 1 AS rank
            FROM user_summaries
            ORDER BY score DESC, last_transaction_time ASC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        return [
            {
                "rank": row["rank"],
                "user_id": row["user_id"],
                "score": round(row["score"], 2),
                "total_spent": round(row["total_spent"], 2),
                "transaction_count": row["transaction_count"],
                "active_days": row["active_days"],
                "last_transaction_time": row["last_transaction_time"],
            }
            for row in rows
        ]

# Serve Frontend static assets
# Ensure the directory exists or create it before mounting
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if not os.path.exists(frontend_dir):
    os.makedirs(frontend_dir)

# Mount the static directory
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def read_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Welcome to Transaction Ranking API. Frontend files are missing."}


@app.get("/admin/reset")
def reset_db():
    with get_db() as conn:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM user_summaries")
        conn.commit()

    return {"status": "reset"}
