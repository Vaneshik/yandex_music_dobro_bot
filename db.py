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

    def close(self):
        self.conn.close()
