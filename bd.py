import logging
import sqlite3
from contextlib import contextmanager

from config import AVAILABLE_LEAGUES, DATABASE_PATH

logger = logging.getLogger(__name__)


def ensure_database():
	DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection():
	ensure_database()
	conn = sqlite3.connect(DATABASE_PATH)
	conn.execute("PRAGMA foreign_keys = ON")
	try:
		yield conn
		conn.commit()
	except Exception:
		conn.rollback()
		raise
	finally:
		conn.close()


def init_db():
	ensure_database()
	with get_connection() as conn:
		conn.executescript("""
			CREATE TABLE IF NOT EXISTS users (
				telegram_id INTEGER PRIMARY KEY,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS user_leagues (
				telegram_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
				league_name TEXT NOT NULL,
				PRIMARY KEY (telegram_id, league_name)
			);

			CREATE TABLE IF NOT EXISTS match_messages (
				telegram_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
				match_title TEXT NOT NULL,
				message_id INTEGER NOT NULL,
				PRIMARY KEY (telegram_id, match_title)
			);
		""")
	logger.info("SQLite база данных готова: %s", DATABASE_PATH)


def ensure_user(telegram_id: int):
	with get_connection() as conn:
		conn.execute(
			"INSERT INTO users (telegram_id) VALUES (?) ON CONFLICT DO NOTHING",
			(telegram_id,),
		)


def get_user_leagues(telegram_id: int) -> list[str]:
	with get_connection() as conn:
		cur = conn.execute(
			"SELECT league_name FROM user_leagues WHERE telegram_id = ? ORDER BY league_name",
			(telegram_id,),
		)
		return [row[0] for row in cur.fetchall()]


def toggle_user_league(telegram_id: int, league_name: str) -> bool:
	if league_name not in AVAILABLE_LEAGUES:
		raise ValueError(f"Неизвестная лига: {league_name}")

	ensure_user(telegram_id)

	with get_connection() as conn:
		cur = conn.execute(
			"SELECT 1 FROM user_leagues WHERE telegram_id = ? AND league_name = ?",
			(telegram_id, league_name),
		)
		exists = cur.fetchone() is not None

		if exists:
			conn.execute(
				"DELETE FROM user_leagues WHERE telegram_id = ? AND league_name = ?",
				(telegram_id, league_name),
			)
			return False

		conn.execute(
			"INSERT INTO user_leagues (telegram_id, league_name) VALUES (?, ?)",
			(telegram_id, league_name),
		)
		return True


def save_match_message(telegram_id: int, match_title: str, message_id: int):
	ensure_user(telegram_id)
	with get_connection() as conn:
		conn.execute(
			"""
			INSERT INTO match_messages (telegram_id, match_title, message_id)
			VALUES (?, ?, ?)
			ON CONFLICT (telegram_id, match_title)
			DO UPDATE SET message_id = excluded.message_id
			""",
			(telegram_id, match_title, message_id),
		)


def get_match_message_id(telegram_id: int, match_title: str) -> int | None:
	with get_connection() as conn:
		cur = conn.execute(
			"SELECT message_id FROM match_messages WHERE telegram_id = ? AND match_title = ?",
			(telegram_id, match_title),
		)
		row = cur.fetchone()
		return row[0] if row else None


def delete_match_message(telegram_id: int, match_title: str):
	with get_connection() as conn:
		conn.execute(
			"DELETE FROM match_messages WHERE telegram_id = ? AND match_title = ?",
			(telegram_id, match_title),
		)


def get_all_subscriptions() -> dict[int, list[str]]:
	with get_connection() as conn:
		cur = conn.execute("""
			SELECT telegram_id, league_name
			FROM user_leagues
			ORDER BY telegram_id, league_name
		""")
		subscriptions: dict[int, list[str]] = {}
		for telegram_id, league_name in cur.fetchall():
			subscriptions.setdefault(telegram_id, []).append(league_name)
		return subscriptions
