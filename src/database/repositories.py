from sqlalchemy import select
from src.database.models import Player
from src.database.config import get_session

class PlayerRepository:
    
    @staticmethod
    async def get_player_by_discord_id(discord_id: int):
        # Agora o Pylance entende isso nativamente:
        async with get_session() as session: 
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            return result.scalar_one_or_none()

    @staticmethod
    async def upsert_player(discord_id: int, riot_data: dict, lane_main: str = None, lane_sec: str = None):
        async with get_session() as session:
            async with session.begin(): # Inicia transação
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
                # O commit acontece automaticamente ao sair do 'async with session.begin()'
                # Mas precisamos retornar o objeto atualizado
                return player