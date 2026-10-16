#!/usr/bin/env python3
"""
scripts/lessons.py — Zero-latency local Lessons Learned Guidance Engine for Kronos.
Stores, queries, and stages lessons in an embedded SQLite database (data/lessons.db).
Output is strictly optimized for minimal LLM token consumption (< 40 tokens per query).
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "lessons.db"

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=2.0)
    conn.execute("PRAGMA busy_timeout = 2000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Active Verified Lessons Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT CHECK(category IN ('coding', 'app', 'trading')),
        trigger_keyword TEXT NOT NULL,
        symptom TEXT NOT NULL,
        fatal_cause TEXT NOT NULL,
        mandatory_fix TEXT NOT NULL,
        severity TEXT CHECK(severity IN ('CRITICAL', 'WARNING', 'INFO')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # FTS5 Index for Fast Keyword Retrieval
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
        trigger_keyword, symptom, fatal_cause, mandatory_fix, content='lessons', content_rowid='id'
    );
    """)

    # Staging Table for Unverified Candidate Lessons
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staging_lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT CHECK(category IN ('coding', 'app', 'trading')),
        trigger_keyword TEXT NOT NULL,
        symptom TEXT NOT NULL,
        fatal_cause TEXT NOT NULL,
        proposed_fix TEXT NOT NULL,
        test_proof TEXT,
        promoted INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Trigger to keep FTS5 synchronized
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS lessons_ai AFTER INSERT ON lessons BEGIN
        INSERT INTO lessons_fts(rowid, trigger_keyword, symptom, fatal_cause, mandatory_fix)
        VALUES (new.id, new.trigger_keyword, new.symptom, new.fatal_cause, new.mandatory_fix);
    END;
    """)

    # Seed Initial Foundation Lessons if empty
    cursor.execute("SELECT COUNT(*) FROM lessons;")
    if cursor.fetchone()[0] == 0:
        seed_lessons = [
            (
                "coding",
                "kronos_context_lookback_512",
                "KronosPredictor fails or produces stale forecasts with > 512 candles.",
                "Naive slicing data[:512] captures oldest bars and drops latest price action.",
                "Always slice from the tail: data.iloc[-512:].copy(). Never slice head.",
                "CRITICAL"
            ),
            (
                "coding",
                "zero_float_financial_math",
                "Cumulative rounding errors in balance, fee, and order size tracking.",
                "Using IEEE 754 float types for financial arithmetic.",
                "Use decimal.Decimal for all monetary metrics. Cast via str: Decimal(str(val)).",
                "CRITICAL"
            ),
            (
                "app",
                "graphify_multimodal_credit_burn",
                "Graphify burns API credits while mapping workspace.",
                "Scanning figures/ or PDF files triggers multimodal semantic pass.",
                "Pass --code-only flag to graphify and exclude figures/ and data/ directories.",
                "WARNING"
            ),
            (
                "trading",
                "net_ev_vs_raw_winrate",
                "Strategy reports 85% win rate but account balance bleeds capital.",
                "Buying heavy favorites (e.g. 0.90) loses money after exchange taker fees.",
                "Optimize Net Expected Value (EV) net of fees. Win rate is only a diagnostic.",
                "CRITICAL"
            )
        ]
        cursor.executemany("""
        INSERT INTO lessons (category, trigger_keyword, symptom, fatal_cause, mandatory_fix, severity)
        VALUES (?, ?, ?, ?, ?, ?);
        """, seed_lessons)
        conn.commit()
        print(f"[OK] Database initialized and seeded with {len(seed_lessons)} core lessons at {DB_PATH}")
    else:
        conn.commit()
        print(f"[OK] Database verified at {DB_PATH}")
    conn.close()

def query_lessons(category=None, search=None, limit=3):
    if not DB_PATH.exists():
        init_db()
    conn = get_connection()
    cursor = conn.cursor()

    if search:
        # Sanitize search term for FTS5
        clean_search = "".join(c for c in search if c.isalnum() or c.isspace()).strip()
        fts_query = f'"{clean_search}"' if clean_search else "*"
        sql = """
        SELECT l.id, l.category, l.severity, l.trigger_keyword, l.symptom, l.mandatory_fix
        FROM lessons_fts f
        JOIN lessons l ON f.rowid = l.id
        WHERE (? IS NULL OR l.category = ?)
        AND lessons_fts MATCH ?
        LIMIT ?;
        """
        cursor.execute(sql, (category, category, fts_query, limit))
    else:
        sql = """
        SELECT id, category, severity, trigger_keyword, symptom, mandatory_fix
        FROM lessons
        WHERE (? IS NULL OR category = ?)
        ORDER BY id DESC
        LIMIT ?;
        """
        cursor.execute(sql, (category, category, limit))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"[NONE] No prior lessons found for category='{category}' search='{search}'.")
        return

    # Ultra-lean token format
    for r in rows:
        lid, cat, sev, kw, sym, fix = r
        print(f"[{sev} #{lid}] {kw}: {sym}")
        print(f"   Fix -> {fix}")

def stage_lesson(category, keyword, symptom, cause, fix, proof=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO staging_lessons (category, trigger_keyword, symptom, fatal_cause, proposed_fix, test_proof)
    VALUES (?, ?, ?, ?, ?, ?);
    """, (category, keyword, symptom, cause, fix, proof))
    sid = cursor.lastrowid
    conn.commit()
    conn.close()
    print(f"[STAGED #{sid}] Lesson staged for '{keyword}'. Run 'promote --id {sid}' after verification.")

def promote_lesson(staging_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT category, trigger_keyword, symptom, fatal_cause, proposed_fix FROM staging_lessons WHERE id = ?;", (staging_id,))
    row = cursor.fetchone()
    if not row:
        print(f"[ERROR] Staging lesson #{staging_id} not found.")
        conn.close()
        return

    cat, kw, sym, cause, fix = row
    cursor.execute("""
    INSERT INTO lessons (category, trigger_keyword, symptom, fatal_cause, mandatory_fix, severity)
    VALUES (?, ?, ?, ?, ?, 'CRITICAL');
    """, (cat, kw, sym, cause, fix))
    lid = cursor.lastrowid
    cursor.execute("UPDATE staging_lessons SET promoted = 1 WHERE id = ?;", (staging_id,))
    conn.commit()
    conn.close()
    print(f"[PROMOTED] Staged #{staging_id} promoted to Active Lesson #{lid}.")

def main():
    parser = argparse.ArgumentParser(description="Kronos Lessons Learned Guidance Engine")
    subparsers = parser.add_subparsers(dest="command")

    # init
    subparsers.add_parser("init", help="Initialize the database")

    # query
    q_parser = subparsers.add_parser("query", help="Query active lessons")
    q_parser.add_argument("--category", choices=["coding", "app", "trading"], default=None)
    q_parser.add_argument("--search", type=str, default=None)
    q_parser.add_argument("--limit", type=int, default=3)

    # stage
    s_parser = subparsers.add_parser("stage", help="Stage an unverified lesson")
    s_parser.add_argument("--category", choices=["coding", "app", "trading"], required=True)
    s_parser.add_argument("--keyword", required=True)
    s_parser.add_argument("--symptom", required=True)
    s_parser.add_argument("--cause", required=True)
    s_parser.add_argument("--fix", required=True)
    s_parser.add_argument("--proof", default=None)

    # promote
    p_parser = subparsers.add_parser("promote", help="Promote a staged lesson to active")
    p_parser.add_argument("--id", type=int, required=True)

    args = parser.parse_args()

    if args.command == "init" or not args.command:
        init_db()
    elif args.command == "query":
        query_lessons(category=args.category, search=args.search, limit=args.limit)
    elif args.command == "stage":
        stage_lesson(args.category, args.keyword, args.symptom, args.cause, args.fix, args.proof)
    elif args.command == "promote":
        promote_lesson(args.id)

if __name__ == "__main__":
    main()
