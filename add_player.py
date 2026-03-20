#!/usr/bin/env python3
"""
Script para adicionar/registrar um jogador manualmente no banco de dados.
Uso: python add_player.py <discord_id> <riot_name#tag> [lane_main] [lane_sec]

Exemplos:
  python add_player.py 123456789012345678 NomeNoLol#BR1
  python add_player.py 123456789012345678 NomeNoLol#BR1 MID ADC
"""

import asyncio
import sys
import os
from dotenv import load_dotenv

load_dotenv()

# Adiciona o diretório raiz ao path para importar src/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.config import init_db
from src.services.riot_api import RiotAPI
from src.services.matchmaker import MatchMaker
from src.database.repositories import PlayerRepository
from sqlalchemy import select
from src.database.config import get_session
from src.database.models import Player

VALID_LANES = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT", "FILL"]


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    discord_id_str = sys.argv[1]
    riot_id = sys.argv[2]
    lane_main = sys.argv[3].upper() if len(sys.argv) > 3 else None
    lane_sec = sys.argv[4].upper() if len(sys.argv) > 4 else None

    # Validações básicas
    if not discord_id_str.isdigit():
        print(f"❌ Discord ID inválido: '{discord_id_str}' (deve ser numérico)")
        sys.exit(1)

    if "#" not in riot_id:
        print(f"❌ Riot ID inválido: '{riot_id}' (formato esperado: Nome#TAG)")
        sys.exit(1)

    if lane_main and lane_main not in VALID_LANES:
        print(f"❌ Lane principal inválida: '{lane_main}'. Opções: {', '.join(VALID_LANES)}")
        sys.exit(1)

    if lane_sec and lane_sec not in VALID_LANES:
        print(f"❌ Lane secundária inválida: '{lane_sec}'. Opções: {', '.join(VALID_LANES)}")
        sys.exit(1)

    discord_id = int(discord_id_str)
    game_name, tag_line = riot_id.rsplit("#", 1)

    print(f"\n🔍 Buscando conta Riot: {game_name}#{tag_line} ...")

    # Inicializa o banco de dados
    await init_db()

    riot = RiotAPI()

    # 1. Busca account (PUUID + profileIconId)
    account = await riot.get_account_by_riot_id(game_name, tag_line)
    if not account:
        print(f"❌ Conta Riot não encontrada: {game_name}#{tag_line}")
        sys.exit(1)

    puuid = account["puuid"]
    print(f"✅ Conta encontrada — PUUID: {puuid[:16]}...")

    riot_data = {
        "puuid": puuid,
        "gameName": account.get("gameName", game_name),
        "tagLine": account.get("tagLine", tag_line),
        "profileIconId": None,
    }

    # 2. Busca summoner para pegar o profileIconId
    summoner = await riot.get_summoner_by_puuid(puuid)
    if summoner:
        riot_data["profileIconId"] = summoner.get("profileIconId")
        print(f"✅ Summoner ID obtido — Ícone: {riot_data['profileIconId']}")
    else:
        print("⚠️  Summoner não encontrado — ícone ficará vazio.")

    # 3. Busca rank
    rank_entries = await riot.get_rank_by_puuid(puuid)

    solo_data = {"tier": "UNRANKED", "rank": "", "lp": 0, "wins": 0, "losses": 0}
    flex_data = {"tier": "UNRANKED", "rank": "", "lp": 0, "wins": 0, "losses": 0}

    if rank_entries:
        for entry in rank_entries:
            if entry.get("queueType") == "RANKED_SOLO_5x5":
                solo_data = {
                    "tier": entry["tier"],
                    "rank": entry["rank"],
                    "lp": entry["leaguePoints"],
                    "wins": entry["wins"],
                    "losses": entry["losses"],
                }
            elif entry.get("queueType") == "RANKED_FLEX_SR":
                flex_data = {
                    "tier": entry["tier"],
                    "rank": entry["rank"],
                    "lp": entry["leaguePoints"],
                    "wins": entry["wins"],
                    "losses": entry["losses"],
                }

    print(f"✅ SoloQ: {solo_data['tier']} {solo_data['rank']} {solo_data['lp']} LP  ({solo_data['wins']}W/{solo_data['losses']}L)")
    print(f"✅ Flex:  {flex_data['tier']} {flex_data['rank']} {flex_data['lp']} LP  ({flex_data['wins']}W/{flex_data['losses']}L)")

    # 4. Calcula MMR com base no SoloQ (prioridade) ou Flex
    if solo_data["tier"] != "UNRANKED":
        mmr = MatchMaker.calculate_adjusted_mmr(
            solo_data["tier"], solo_data["rank"], solo_data["lp"],
            solo_data["wins"], solo_data["losses"], "RANKED_SOLO_5x5"
        )
    elif flex_data["tier"] != "UNRANKED":
        mmr = MatchMaker.calculate_adjusted_mmr(
            flex_data["tier"], flex_data["rank"], flex_data["lp"],
            flex_data["wins"], flex_data["losses"], "RANKED_FLEX_SR"
        )
    else:
        mmr = 1200  # Padrão para unranked
    print(f"✅ MMR calculado: {mmr}")

    # 5. Verifica se o jogador já existe
    async with get_session() as session:
        result = await session.execute(select(Player).where(Player.discord_id == discord_id))
        existing = result.scalar_one_or_none()

    if existing:
        print(f"\n⚠️  Jogador já existe no banco (Discord ID: {discord_id})")
        confirm = input("   Deseja sobrescrever os dados? [s/N]: ").strip().lower()
        if confirm != "s":
            print("❌ Operação cancelada.")
            sys.exit(0)

    # 6. Upsert no banco
    await PlayerRepository.upsert_player(discord_id, riot_data, lane_main, lane_sec)

    # 7. Atualiza ranks e MMR
    await PlayerRepository.update_riot_rank(
        discord_id,
        solo_data["tier"], solo_data["rank"], solo_data["lp"],
        solo_data["wins"], solo_data["losses"],
        calculated_mmr=mmr,
        queue_type="RANKED_SOLO_5x5"
    )
    await PlayerRepository.update_riot_rank(
        discord_id,
        flex_data["tier"], flex_data["rank"], flex_data["lp"],
        flex_data["wins"], flex_data["losses"],
        queue_type="RANKED_FLEX_SR"
    )

    # 8. Confirmação final
    async with get_session() as session:
        result = await session.execute(select(Player).where(Player.discord_id == discord_id))
        player = result.scalar_one_or_none()

    if player:
        print(f"""
╔══════════════════════════════════════════╗
║         JOGADOR REGISTRADO COM SUCESSO   ║
╠══════════════════════════════════════════╣
  Discord ID : {player.discord_id}
  Riot Name  : {player.riot_name}
  PUUID      : {player.riot_puuid[:20]}...
  SoloQ      : {player.solo_tier} {player.solo_rank} {player.solo_lp} LP
  Flex       : {player.flex_tier} {player.flex_rank} {player.flex_lp} LP
  MMR        : {player.mmr}
  Lane Main  : {player.main_lane.value if player.main_lane else '—'}
  Lane Sec   : {player.secondary_lane.value if player.secondary_lane else '—'}
╚══════════════════════════════════════════╝
""")
    else:
        print("❌ Erro: jogador não encontrado após inserção.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
