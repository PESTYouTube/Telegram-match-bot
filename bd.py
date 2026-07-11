import logging
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

import psycopg2
from psycopg2 import OperationalError
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from config import AVAILABLE_LEAGUES, DATABASE_URL

logger = logging.getLogger(__name__)


def parse_database_url(url: str) -> dict:
	parsed = urlparse(url)
	return {
		'host': parsed.hostname or 'localhost',
		'port': parsed.port or 5432,
		'dbname': parsed.path.lstrip('/') or 'postgres',
		'user': parsed.username or 'postgres',
		'password': unquote(parsed.password or ''),
	}


def _connect(dbname: str | None = None):
	params = parse_database_url(DATABASE_URL)
	if dbname:
		params['dbname'] = dbname

	try:
		return psycopg2.connect(**params)
	except UnicodeDecodeError as exc:
		raise OperationalError(
			'Не удалось подключиться к PostgreSQL. '
			'Проверьте DB_PASSWORD в файле .env и что сервер запущен.'
		) from exc


@contextmanager
def get_connection():
	conn = _connect()
	try:
		yield conn
		conn.commit()
	except Exception:
		conn.rollback()
		raise
	finally:
		conn.close()


def ensure_database():
	target_db = parse_database_url(DATABASE_URL)['dbname']
	if target_db == 'postgres':
		return

	try:
		_connect(dbname=target_db).close()
		return
	except OperationalError as exc:
		if 'does not exist' not in str(exc).lower() and 'не существует' not in str(exc).lower():
			raise

	logger.info('База данных "%s" не найдена, создаю...', target_db)
	conn = _connect(dbname='postgres')
	try:
		conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
		with conn.cursor() as cur:
			cur.execute(f'CREATE DATABASE "{target_db}"')
	finally:
		conn.close()


def init_db():
	ensure_database()
	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute("""
				CREATE TABLE IF NOT EXISTS users (
					telegram_id BIGINT PRIMARY KEY,
					created_at TIMESTAMPTZ DEFAULT NOW()
				)
			""")
			cur.execute("""
				CREATE TABLE IF NOT EXISTS user_leagues (
					telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
					league_name VARCHAR(100) NOT NULL,
					PRIMARY KEY (telegram_id, league_name)
				)
			""")
			cur.execute("""
				CREATE TABLE IF NOT EXISTS match_messages (
					telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
					match_title VARCHAR(255) NOT NULL,
					message_id BIGINT NOT NULL,
					PRIMARY KEY (telegram_id, match_title)
				)
			""")


def ensure_user(telegram_id: int):
	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT DO NOTHING",
				(telegram_id,),
			)


def get_user_leagues(telegram_id: int) -> list[str]:
	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"SELECT league_name FROM user_leagues WHERE telegram_id = %s ORDER BY league_name",
				(telegram_id,),
			)
			return [row[0] for row in cur.fetchall()]


def toggle_user_league(telegram_id: int, league_name: str) -> bool:
	if league_name not in AVAILABLE_LEAGUES:
		raise ValueError(f"Неизвестная лига: {league_name}")

	ensure_user(telegram_id)

	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"SELECT 1 FROM user_leagues WHERE telegram_id = %s AND league_name = %s",
				(telegram_id, league_name),
			)
			exists = cur.fetchone() is not None

			if exists:
				cur.execute(
					"DELETE FROM user_leagues WHERE telegram_id = %s AND league_name = %s",
					(telegram_id, league_name),
				)
				return False

			cur.execute(
				"INSERT INTO user_leagues (telegram_id, league_name) VALUES (%s, %s)",
				(telegram_id, league_name),
			)
			return True


def save_match_message(telegram_id: int, match_title: str, message_id: int):
	ensure_user(telegram_id)
	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO match_messages (telegram_id, match_title, message_id)
				VALUES (%s, %s, %s)
				ON CONFLICT (telegram_id, match_title)
				DO UPDATE SET message_id = EXCLUDED.message_id
				""",
				(telegram_id, match_title, message_id),
			)


def get_match_message_id(telegram_id: int, match_title: str) -> int | None:
	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"SELECT message_id FROM match_messages WHERE telegram_id = %s AND match_title = %s",
				(telegram_id, match_title),
			)
			row = cur.fetchone()
			return row[0] if row else None


def delete_match_message(telegram_id: int, match_title: str):
	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"DELETE FROM match_messages WHERE telegram_id = %s AND match_title = %s",
				(telegram_id, match_title),
			)


def get_all_subscriptions() -> dict[int, list[str]]:
	with get_connection() as conn:
		with conn.cursor() as cur:
			cur.execute("""
				SELECT telegram_id, league_name
				FROM user_leagues
				ORDER BY telegram_id, league_name
			""")
			subscriptions: dict[int, list[str]] = {}
			for telegram_id, league_name in cur.fetchall():
				subscriptions.setdefault(telegram_id, []).append(league_name)
			return subscriptions
