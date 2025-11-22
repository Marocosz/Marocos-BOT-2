import sqlite3
import os
import asyncio
from src.database.models import Player, Lane, TeamSide, MatchStatus # Importa todos os Models
from src.database.config import init_db, async_session
from datetime import datetime

DB_FILE = "data/database.sqlite"

async def rescue_and_restore():
    """
    Passo 1: Extrai dados do arquivo corrompido (DUMP).
    Passo 2: Deleta o arquivo antigo.
    Passo 3: Inicializa um novo DB limpo.
    Passo 4: Insere os dados de volta (RESTORE) usando a Session.
    """
    print("--- INICIANDO RESGATE DE DADOS ---")

    # [1] DUMP: Extrai os dados do DB Antigo (Usando sqlite3 nativo para garantir)
    saved_players = []
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Seleciona apenas as colunas essenciais de identificação e preferências
        cursor.execute("SELECT discord_id, riot_puuid, riot_name, main_lane, secondary_lane, mmr, wins, losses FROM players")
        
        for row in cursor.fetchall():
            saved_players.append({
                'discord_id': row[0],
                'riot_puuid': row[1],
                'riot_name': row[2],
                'main_lane': row[3],
                'secondary_lane': row[4],
                'mmr': row[5],
                'wins': row[6],
                'losses': row[7],
            })
        conn.close()
        print(f"✅ 1. Dados de {len(saved_players)} jogadores extraídos com sucesso.")
    except Exception as e:
        print(f"❌ ERRO no DUMP (Verifique se o arquivo {DB_FILE} existe ou está acessível): {e}")
        return # Não prossegue se o dump falhar

    # [2] DELETAR: Remove o arquivo antigo para forçar a criação do novo schema
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("✅ 2. Arquivo de banco de dados corrompido deletado.")

    # [3] RECONSTRUIR: Cria um novo DB com o schema CORRETO (models.py)
    await init_db()
    print("✅ 3. Nova estrutura de banco de dados criada (com coluna solo_wins).")

    # [4] RESTORE: Insere os dados de volta
    restored_count = 0
    # Usa a session assíncrona para inserir
    async with async_session() as session:
        for data in saved_players:
            # Cria um objeto Player, preenchendo dados antigos e usando DEFAULTS para os novos
            riot_name = data.get('riot_name', '')
            
            new_player = Player(
                discord_id=data['discord_id'],
                riot_puuid=data['riot_puuid'],
                riot_name=riot_name,
                # Tenta reconstruir o GameName (riot_id_str) a partir do riot_name
                riot_id_str=riot_name.split('#')[0] if '#' in riot_name else riot_name,
                
                # Dados de ranking (Novas colunas, usando DEFAULTS que são 0 / UNRANKED)
                solo_tier="UNRANKED",
                solo_rank="",
                solo_lp=0,
                solo_wins=0,
                solo_losses=0,
                last_rank_update=datetime.utcnow(),
                
                # Stats Internos (Restaurando os dados internos da liga)
                mmr=data.get('mmr', 1200),
                wins=data.get('wins', 0),
                losses=data.get('losses', 0),
                
                # Preferências de Lane
                main_lane=data['main_lane'],
                secondary_lane=data['secondary_lane'],
            )
            session.add(new_player)
            restored_count += 1

        await session.commit()
    
    print(f"\n✨ RESGATE CONCLUÍDO! {restored_count} jogadores restaurados com sucesso.")
    print("Agora você pode rodar o bot normalmente.")


if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(rescue_and_restore())