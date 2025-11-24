import sqlite3
import json
import asyncio
import os
import sys
from datetime import datetime

# Configuração de caminhos
DB_PATH = './data/database.sqlite'
BACKUP_PATH = './data/players_backup.json'

# --- PARTE 1: BACKUP (Extração Segura) ---
def backup_data():
    print(f"📦 [BACKUP] Iniciando backup de {DB_PATH}...")
    
    if not os.path.exists(DB_PATH):
        print("❌ Erro: Arquivo de banco de dados não encontrado.")
        return

    try:
        # Conecta usando SQLite puro para ignorar erros de Schema do SQLAlchemy
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row # Para acessar colunas por nome
        cursor = conn.cursor()
        
        # Pega todos os jogadores
        cursor.execute("SELECT * FROM players")
        rows = cursor.fetchall()
        
        players_data = []
        for row in rows:
            # Converte a linha (Row) em um dicionário Python
            p_dict = dict(row)
            
            # Tratamento de datas (Converter string para ser serializável em JSON se necessário)
            # SQLite geralmente salva datas como strings, então json.dump aceita bem.
            players_data.append(p_dict)
            
        conn.close()
        
        # Salva no arquivo JSON
        with open(BACKUP_PATH, 'w', encoding='utf-8') as f:
            json.dump(players_data, f, indent=4, default=str)
            
        print(f"✅ [BACKUP] Sucesso! {len(players_data)} jogadores salvos em '{BACKUP_PATH}'.")
        
    except Exception as e:
        print(f"❌ [BACKUP] Erro fatal: {e}")

# --- PARTE 2: RESTORE (Reinserção Inteligente) ---
async def restore_data():
    print(f"♻️ [RESTORE] Iniciando restauração a partir de '{BACKUP_PATH}'...")
    
    if not os.path.exists(BACKUP_PATH):
        print("❌ Erro: Arquivo de backup não encontrado.")
        return

    # Setup do ambiente SQLAlchemy
    sys.path.insert(0, os.path.abspath(os.getcwd())) # Garante que achamos o src
    from src.database.config import get_session
    from src.database.models import Player, Lane

    try:
        with open(BACKUP_PATH, 'r', encoding='utf-8') as f:
            backup_list = json.load(f)
            
        print(f"📂 Carregados {len(backup_list)} registros do JSON.")
        
        async with get_session() as session:
            count = 0
            for item in backup_list:
                # Cria um novo objeto Player usando o modelo NOVO (que tem as colunas Flex)
                # Mapeamos os dados antigos para os campos novos.
                
                # Tratamento de Enums (Main Lane / Secondary Lane)
                # O banco antigo salvou como string (ex: 'MID'), o novo precisa do Enum.
                m_lane = None
                s_lane = None
                if item.get('main_lane'):
                    # Remove 'Lane.' se existir na string velha (safety)
                    val = item['main_lane'].replace('Lane.', '')
                    if val in Lane.__members__: m_lane = Lane[val]

                if item.get('secondary_lane'):
                    val = item['secondary_lane'].replace('Lane.', '')
                    if val in Lane.__members__: s_lane = Lane[val]

                new_player = Player(
                    discord_id=item['discord_id'],
                    riot_puuid=item.get('riot_puuid'),
                    riot_name=item.get('riot_name'),
                    riot_id_str=item.get('riot_id_str'),
                    riot_icon_id=item.get('riot_icon_id'),
                    
                    # Dados de Rank (Mapeando o antigo 'solo_' para o novo 'solo_')
                    solo_tier=item.get('solo_tier', 'UNRANKED'),
                    solo_rank=item.get('solo_rank', ''),
                    solo_lp=item.get('solo_lp', 0),
                    solo_wins=item.get('solo_wins', 0),
                    solo_losses=item.get('solo_losses', 0),
                    
                    # Dados de Flex (Novos - Preenchemos com padrão pois o backup não tem)
                    flex_tier='UNRANKED',
                    flex_rank='',
                    flex_lp=0,
                    flex_wins=0,
                    flex_losses=0,
                    
                    # Stats Internos
                    wins=item.get('wins', 0),
                    losses=item.get('losses', 0),
                    mmr=item.get('mmr', 1200),
                    
                    # Lanes
                    main_lane=m_lane,
                    secondary_lane=s_lane,
                    
                    # Datas (Pode precisar de parse se o JSON salvou como string)
                    # O SQLAlchemy costuma lidar bem se for ISO string, senão datetime.fromisoformat
                )
                
                # Merge é melhor que Add aqui, pois se o ID já existir (por algum motivo), ele atualiza
                await session.merge(new_player)
                count += 1
            
            # O get_session faz commit automático
            
        print(f"✅ [RESTORE] Sucesso! {count} jogadores restaurados no novo banco de dados.")
        
    except Exception as e:
        print(f"❌ [RESTORE] Erro: {e}")
        import traceback
        traceback.print_exc()

# --- SELETOR DE MODO ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python migration_tool.py [backup|restore]")
    else:
        mode = sys.argv[1]
        if mode == "backup":
            backup_data()
        elif mode == "restore":
            asyncio.run(restore_data())
        else:
            print("Modo inválido. Use 'backup' ou 'restore'.")