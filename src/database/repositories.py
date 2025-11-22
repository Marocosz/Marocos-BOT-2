from sqlalchemy import select
from src.database.models import Player, Lane
from src.database.config import get_session
from datetime import datetime

class PlayerRepository:
    
    @staticmethod
    async def get_player_by_discord_id(discord_id: int):
        async with get_session() as session: 
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            return result.scalar_one_or_none()

    @staticmethod
    async def upsert_player(discord_id: int, riot_data: dict, lane_main: str = None, lane_sec: str = None):
        async with get_session() as session:
            async with session.begin():
                result = await session.execute(select(Player).where(Player.discord_id == discord_id))
                player = result.scalar_one_or_none()

                if player:
                    player.riot_puuid = riot_data.get('puuid')
                    player.riot_name = f"{riot_data.get('gameName')}#{riot_data.get('tagLine')}"
                    player.riot_icon_id = riot_data.get('profileIconId')
                    if lane_main: player.main_lane = lane_main
                    if lane_sec: player.secondary_lane = lane_sec
                else:
                    player = Player(
                        discord_id=discord_id,
                        riot_puuid=riot_data.get('puuid'),
                        riot_name=f"{riot_data.get('gameName')}#{riot_data.get('tagLine')}",
                        riot_icon_id=riot_data.get('profileIconId'),
                        main_lane=lane_main,
                        secondary_lane=lane_sec
                    )
                    session.add(player)
                return player

    # --- ATUALIZADO: Agora salva Wins, Losses e o MMR Calculado ---
    @staticmethod
    async def update_riot_rank(discord_id: int, tier: str, rank: str, lp: int, wins: int, losses: int, calculated_mmr: int):
        async with get_session() as session:
            async with session.begin():
                result = await session.execute(select(Player).where(Player.discord_id == discord_id))
                player = result.scalar_one_or_none()
                if player:
                    player.solo_tier = tier
                    player.solo_rank = rank
                    player.solo_lp = lp
                    player.solo_wins = wins
                    player.solo_losses = losses
                    player.mmr = calculated_mmr  
                    player.last_rank_update = datetime.utcnow()