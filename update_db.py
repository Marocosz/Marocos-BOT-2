import sqlite3

DB_FILE = "data/database.sqlite"

def add_column(cursor, table, column, col_type, default=None):
    """Tenta adicionar uma coluna. Ignora silenciosamente se já existir."""
    try:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
        print(f"  [+] {table}.{column} adicionada.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"  [OK] {table}.{column} já existe.")
        else:
            print(f"  [ERRO] {table}.{column}: {e}")

def migrate():
    print(f"[*] Atualizando banco: {DB_FILE}...")

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # --- Migrações originais ---
        add_column(cursor, "guild_configs", "tracking_channel_id", "BIGINT")

        for col, tipo in [("solo_tier", "VARCHAR"), ("solo_rank", "VARCHAR"),
                          ("solo_lp", "INTEGER"), ("last_rank_update", "DATETIME")]:
            add_column(cursor, "players", col, tipo)

        # --- Novas colunas (v2) ---

        # Streaks de vitórias
        add_column(cursor, "players", "current_win_streak", "INTEGER", default=0)
        add_column(cursor, "players", "best_win_streak", "INTEGER", default=0)

        # Snapshot de MMR no momento da partida
        add_column(cursor, "match_players", "mmr_before", "INTEGER")

        # Contadores de MVP/iMVP
        add_column(cursor, "players", "mvp_count", "INTEGER", default=0)
        add_column(cursor, "players", "imvp_count", "INTEGER", default=0)

        # Nova tabela: estado da fila persistida
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lobby_states (
                guild_id INTEGER PRIMARY KEY,
                queue_json TEXT DEFAULT '[]',
                channel_id INTEGER,
                updated_at DATETIME
            )
        """)
        print("  [+] Tabela lobby_states verificada/criada.")

        conn.commit()
        conn.close()
        print("\n[OK] Banco atualizado com sucesso! Dados anteriores preservados.")

    except Exception as e:
        print(f"\n💥 Erro crítico: {e}")

if __name__ == "__main__":
    migrate()
