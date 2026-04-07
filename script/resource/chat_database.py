import psycopg2
import psycopg2.extras
import os
from typing import List, Dict, Any

def get_database() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        sslmode="require"
    )

def start_database() -> None:
    with get_database() as conn:
        with conn.cursor() as cur:

            cur.execute("CREATE SCHEMA IF NOT EXISTS chat")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat.chats (
                    thread_id  TEXT PRIMARY KEY,
                    title      TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat.messages (
                    id         SERIAL PRIMARY KEY,
                    thread_id  TEXT NOT NULL REFERENCES chat.chats(thread_id),
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()

def save_chat(thread_id: str, title: str) -> None:
    with get_database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat.chats (thread_id, title) VALUES (%s, %s) ON CONFLICT (thread_id) DO NOTHING",
                (thread_id, title)
            )
        conn.commit()

def save_message(thread_id: str, role: str, content: str) -> None:
    with get_database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat.messages (thread_id, role, content) VALUES (%s, %s, %s)",
                (thread_id, role, content)
            )
        conn.commit()

def get_all_chats() -> List[Dict[str, Any]]:
    with get_database() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT thread_id, title, created_at FROM chat.chats ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

def get_messages_by_thread(thread_id: str) -> List[Dict[str, Any]]:
    with get_database() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT role, content FROM chat.messages WHERE thread_id = %s ORDER BY id ASC",
                (thread_id,)
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

def delete_chat_by_thread(thread_id: str) -> None:
    with get_database() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat.messages WHERE thread_id = %s", (thread_id,))
            cur.execute("DELETE FROM chat.chats    WHERE thread_id = %s", (thread_id,))
        conn.commit()