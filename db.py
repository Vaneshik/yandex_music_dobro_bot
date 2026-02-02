import psycopg2
from psycopg2.extras import RealDictCursor


class UserRepository:
    def __init__(self, dsn: str):
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True
        self._create_table()

    def _create_table(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    token TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS file_id_cache (
                    track_id VARCHAR(255) PRIMARY KEY,
                    file_id VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )

    def insert(self, user_id: int, token: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, token)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET token = EXCLUDED.token;
                """,
                (user_id, token)
            )

    def get_by_user_id(self, user_id: int) -> dict | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, token
                FROM users
                WHERE user_id = %s;
                """,
                (user_id,)
            )
            return cur.fetchone()

    def get_cached_file_id(self, track_id: str) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT file_id FROM file_id_cache WHERE track_id = %s;
                """,
                (track_id,)
            )
            result = cur.fetchone()
            return result[0] if result else None

    def set_cached_file_id(self, track_id: str, file_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO file_id_cache (track_id, file_id)
                VALUES (%s, %s)
                ON CONFLICT (track_id) DO UPDATE SET file_id = EXCLUDED.file_id;
                """,
                (track_id, file_id)
            )

    def close(self):
        self.conn.close()
