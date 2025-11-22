from sqlalchemy import select
from src.database.models import Player, Match, MatchPlayer, MatchStatus, TeamSide
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

class MatchRepository:
    
    @staticmethod
    async def create_match(guild_id: int, blue_team: list, red_team: list):
        async with get_session() as session:
            async with session.begin():
                new_match = Match(
                    guild_id=guild_id,
                    status=MatchStatus.IN_PROGRESS,
                    created_at=datetime.utcnow()
                )
                session.add(new_match)
                await session.flush() 

                for p in blue_team:
                    session.add(MatchPlayer(match_id=new_match.id, player_id=p['id'], side=TeamSide.BLUE))

                for p in red_team:
                    session.add(MatchPlayer(match_id=new_match.id, player_id=p['id'], side=TeamSide.RED))
                
                return new_match.id

    @staticmethod
    async def finish_match(match_id: int, winning_side: str):
        """
        Finaliza a partida.
        IMPORTANTE: Apenas incrementa Wins/Losses internas. NÃO altera o MMR.
        O MMR continua sendo o definido pelo Elo do LoL.
        """
        side_enum = TeamSide.BLUE if winning_side.upper() == 'BLUE' else TeamSide.RED
        
        async with get_session() as session:
            async with session.begin():
                stmt = select(Match).where(Match.id == match_id)
                result = await session.execute(stmt)
                match = result.scalar_one_or_none()

                if not match: return "NOT_FOUND"
                if match.status == MatchStatus.FINISHED: return "ALREADY_FINISHED"

                match.status = MatchStatus.FINISHED
                match.winning_side = side_enum
                match.finished_at = datetime.utcnow()

                # Atualiza estatísticas dos jogadores
                stmt_players = select(MatchPlayer).where(MatchPlayer.match_id == match_id)
                result_players = await session.execute(stmt_players)
                match_players = result_players.scalars().all()

                for mp in match_players:
                    player_stmt = select(Player).where(Player.discord_id == mp.player_id)
                    p_result = await session.execute(player_stmt)
                    player = p_result.scalar_one_or_none()
                    
                    if player:
                        # Apenas conta +1 no placar interno
                        if mp.side == side_enum:
                            player.wins += 1 
                        else:
                            player.losses += 1
                            
                return "SUCCESS"