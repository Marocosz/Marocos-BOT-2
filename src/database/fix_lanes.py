import asyncio
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Adiciona o diretório raiz do projeto ao PATH para que as importações funcionem
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Carrega as variáveis de ambiente
load_dotenv()

# Importações dos módulos do seu projeto
from src.database.config import get_session
from src.database.models import Player, Lane 

async def swap_all_lanes():
    """
    Busca todos os jogadores que têm Main e Secondary Lane definidas e inverte os valores.
    Isto corrige a inversão ocorrida no registro.
    """
    print("\n=== SCRIPT DE INVERSÃO DE LANES (MAIN <-> SEC) ===")
    
    # 1. Definindo o filtro: Apenas jogadores com ambas as lanes preenchidas
    # Isso evita alterar jogadores que só registraram 1 lane.
    stmt = (
        select(Player)
        .where(Player.main_lane.isnot(None))
        .where(Player.secondary_lane.isnot(None))
    )

    count_swapped = 0
    
    async with get_session() as session:
        # 2. Busca os jogadores
        result = await session.execute(stmt)
        players_to_swap = result.scalars().all()

        if not players_to_swap:
            print("✅ Concluído! Nenhum jogador com Main e Secondary Lane para inverter.")
            return

        print(f"🔄 Encontrados {len(players_to_swap)} jogadores com duas lanes para inversão...")

        # 3. Executa a Inversão
        for player in players_to_swap:
            old_main = player.main_lane.value
            old_sec = player.secondary_lane.value
            
            # Realiza a troca (Swap)
            player.main_lane = Lane[old_sec]
            player.secondary_lane = Lane[old_main]
            
            # Exibe o log
            print(f"   -> {player.riot_name}: {old_main}/{old_sec}  =>  {player.main_lane.value}/{player.secondary_lane.value}")
            count_swapped += 1
            
        # 4. O 'get_session' (do seu config.py) fará o commit automaticamente aqui.
        
    print(f"\n✅ SCRIPT EXECUTADO COM SUCESSO. {count_swapped} registros corrigidos.")

# --- Execução do Script ---

async def main():
    try:
        await swap_all_lanes()
    except Exception as e:
        print(f"\n❌ Erro crítico durante a execução: {e}")

if __name__ == "__main__":
    # Garante que o bot esteja parado ao rodar este script para evitar erros de SQLite.
    print("AVISO: Certifique-se de que o bot Discord não esteja rodando para evitar bloqueios do banco de dados.")
    asyncio.run(main())