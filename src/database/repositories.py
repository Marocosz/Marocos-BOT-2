from sqlalchemy import select, desc
from src.database.models import Player, Match, MatchPlayer, MatchStatus, TeamSide, GuildConfig
from src.database.config import get_session
from datetime import datetime

# --- REPOSITÓRIO DA GUILDA (CONFIGURAÇÕES) ---
class GuildRepository:
    @staticmethod
    async def set_tracking_channel(guild_id: int, channel_id: int):
        async with get_session() as session:
            stmt = select(GuildConfig).where(GuildConfig.guild_id == guild_id)
            result = await session.execute(stmt)
            config = result.scalar_one_or_none()
            
            if config:
                config.tracking_channel_id = channel_id
            else:
                config = GuildConfig(guild_id=guild_id, tracking_channel_id=channel_id)
                session.add(config)

    @staticmethod
    async def get_tracking_channel(guild_id: int):
        async with get_session() as session:
            stmt = select(GuildConfig).where(GuildConfig.guild_id == guild_id)
            result = await session.execute(stmt)
            config = result.scalar_one_or_none()
            return config.tracking_channel_id if config else None

# --- REPOSITÓRIO DE JOGADORES ---
class PlayerRepository:
    
    @staticmethod
    async def get_player_by_discord_id(discord_id: int):
        async with get_session() as session: 
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            return result.scalar_one_or_none()

    @staticmethod
    async def get_all_players_with_puuid():
        """Busca todos os jogadores registrados para o Tracking"""
        async with get_session() as session:
            stmt = select(Player).where(Player.riot_puuid.isnot(None))
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def upsert_player(discord_id: int, riot_data: dict, lane_main: str = None, lane_sec: str = None):
        async with get_session() as session:
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
    async def update_riot_rank(discord_id: int, tier: str, rank: str, lp: int, wins: int=0, losses: int=0, calculated_mmr: int=None, queue_type: str = "SOLO"):
        async with get_session() as session:
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            player = result.scalar_one_or_none()
            
            if player:
                # Decide qual fila atualizar: SOLO (padrão) ou FLEX
                if queue_type.upper() == 'RANKED_FLEX_SR':
                    player.flex_tier = tier
                    player.flex_rank = rank
                    player.flex_lp = lp
                    player.flex_wins = wins
                    player.flex_losses = losses
                else: 
                    player.solo_tier = tier
                    player.solo_rank = rank
                    player.solo_lp = lp
                    player.solo_wins = wins
                    player.solo_losses = losses

                if calculated_mmr: 
                    player.mmr = calculated_mmr
                
                player.last_rank_update = datetime.utcnow()

    @staticmethod
    async def get_internal_ranking(limit: int = None):
        async with get_session() as session:
            # O order_by Player.losses já está correto, pois o padrão é ASC (crescente).
            # Ou seja: Mais vitórias > Menos derrotas > Maior MMR.
            stmt = select(Player).order_by(desc(Player.wins), Player.losses, desc(Player.mmr))
            if limit: stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all()

# --- REPOSITÓRIO DE PARTIDAS ---
class MatchRepository:
    
    @staticmethod
    async def create_match(guild_id: int, blue_team: list, red_team: list):
        async with get_session() as session:
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
        side_enum = TeamSide.BLUE if winning_side.upper() == 'BLUE' else TeamSide.RED
        
        async with get_session() as session:
            stmt = select(Match).where(Match.id == match_id)
            result = await session.execute(stmt)
            match = result.scalar_one_or_none()

            if not match: return "NOT_FOUND"
            if match.status == MatchStatus.FINISHED: return "ALREADY_FINISHED"
            if match.status == MatchStatus.CANCELLED: return "ALREADY_CANCELLED"

            match.status = MatchStatus.FINISHED
            match.winning_side = side_enum
            match.finished_at = datetime.utcnow()

            # Busca todos os jogadores da partida
            stmt_players = select(MatchPlayer).where(MatchPlayer.match_id == match_id)
            result_players = await session.execute(stmt_players)
            match_players = result_players.scalars().all()

            # Processa vitórias e derrotas
            for mp in match_players:
                # É mais eficiente buscar o Player pelo ID em vez de executar uma nova query a cada iteração, 
                # mas mantemos a query atual por enquanto se a performance for aceitável.
                player_stmt = select(Player).where(Player.discord_id == mp.player_id)
                p_result = await session.execute(player_stmt)
                player = p_result.scalar_one_or_none()
                
                if player:
                    if mp.side == side_enum:
                        player.wins += 1 
                    else:
                        player.losses += 1
                        
            return "SUCCESS"

    @staticmethod
    async def cancel_match(match_id: int):
        async with get_session() as session:
            stmt = select(Match).where(Match.id == match_id)
            result = await session.execute(stmt)
            match = result.scalar_one_or_none()

            if not match: return "NOT_FOUND"
            if match.status != MatchStatus.IN_PROGRESS: return "NOT_ACTIVE"

            match.status = MatchStatus.CANCELLED
            match.finished_at = datetime.utcnow()
            return "SUCCESS"