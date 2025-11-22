import sqlite3

# Nome do arquivo do banco
DB_FILE = "data/database.sqlite"

def migrate():
    print(f"🔧 Iniciando atualização do banco de dados: {DB_FILE}...")
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 1. Adicionar coluna de Rastreamento na tabela de Configuração
        try:
            print("> Tentando adicionar 'tracking_channel_id' em 'guild_configs'...")
            cursor.execute("ALTER TABLE guild_configs ADD COLUMN tracking_channel_id BIGINT")
            print("  ✅ Sucesso!")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("  ⚠️ Coluna já existe (ignorando).")
            else:
                print(f"  ❌ Erro (Tabela talvez não exista ainda): {e}")

        # 2. (Prevenção) Adicionar colunas de Rank caso você não tenha resetado no passo anterior
        colunas_player = [
            ("solo_tier", "VARCHAR"),
            ("solo_rank", "VARCHAR"),
            ("solo_lp", "INTEGER"),
            ("last_rank_update", "DATETIME")
        ]

        for col, tipo in colunas_player:
            try:
                print(f"> Tentando adicionar '{col}' em 'players'...")
                cursor.execute(f"ALTER TABLE players ADD COLUMN {col} {tipo}")
                print("  ✅ Sucesso!")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print("  ⚠️ Coluna já existe (ignorando).")
                else:
                    print(f"  ❌ Erro: {e}")

        conn.commit()
        conn.close()
        print("\n✨ Banco de dados atualizado com sucesso! Seus dados foram mantidos.")
        
    except Exception as e:
        print(f"\n💥 Erro crítico ao abrir o banco: {e}")

if __name__ == "__main__":
    migrate()