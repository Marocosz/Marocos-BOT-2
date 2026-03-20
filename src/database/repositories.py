import json
from sqlalchemy import select, desc
from sqlalchemy.orm import aliased
from src.database.models import Player, Match, MatchPlayer, MatchStatus, TeamSide, GuildConfig, CommunityProfile, LobbyState
from src.database.config import get_session
from datetime import datetime


# --- REPOSITÓRIO DA GUILDA ---
class GuildRepository:
    @staticmethod
    async def set_tracking_channel(guild_id: int, channel_id: int):
        async with get_session() as session:
            result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
            config = result.scalar_one_or_none()
            if config:
                config.tracking_channel_id = channel_id
            else:
                session.add(GuildConfig(guild_id=guild_id, tracking_channel_id=channel_id))

    @staticmethod
    async def get_tracking_channel(guild_id: int):
        async with get_session() as session:
            result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
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
        async with get_session() as session:
            result = await session.execute(select(Player).where(Player.riot_puuid.isnot(None)))
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
    async def update_riot_rank(discord_id: int, tier: str, rank: str, lp: int, wins: int = 0, losses: int = 0, calculated_mmr: int = None, queue_type: str = "SOLO"):
        async with get_session() as session:
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            player = result.scalar_one_or_none()
            if player:
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
                if calculated_mmr is not None:
                    player.mmr = calculated_mmr
                player.last_rank_update = datetime.utcnow()

    @staticmethod
    async def update_mmr_direct(discord_id: int, new_mmr: int):
        """Atualiza o MMR interno diretamente (usado após resultado de partida)."""
        async with get_session() as session:
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            player = result.scalar_one_or_none()
            if player:
                player.mmr = max(0, new_mmr)

    @staticmethod
    async def update_streak(discord_id: int, won: bool) -> tuple:
        """
        Atualiza a sequência de vitórias/derrotas.
        Retorna (current_streak, best_streak).
        """
        async with get_session() as session:
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            player = result.scalar_one_or_none()
            if not player:
                return 0, 0

            # Garante que campos nunca são None (legado)
            if player.current_win_streak is None: player.current_win_streak = 0
            if player.best_win_streak is None: player.best_win_streak = 0

            if won:
                player.current_win_streak += 1
                if player.current_win_streak > player.best_win_streak:
                    player.best_win_streak = player.current_win_streak
            else:
                player.current_win_streak = 0

            return player.current_win_streak, player.best_win_streak

    @staticmethod
    async def increment_mvp(discord_id: int):
        """Incrementa o contador de MVPs do jogador."""
        async with get_session() as session:
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            player = result.scalar_one_or_none()
            if player:
                player.mvp_count = (player.mvp_count or 0) + 1

    @staticmethod
    async def increment_imvp(discord_id: int):
        """Incrementa o contador de iMVPs do jogador."""
        async with get_session() as session:
            result = await session.execute(select(Player).where(Player.discord_id == discord_id))
            player = result.scalar_one_or_none()
            if player:
                player.imvp_count = (player.imvp_count or 0) + 1

    @staticmethod
    async def get_internal_ranking(limit: int = None):
        async with get_session() as session:
            stmt = select(Player).order_by(desc(Player.wins), Player.losses, desc(Player.mmr))
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_all_players():
        """Retorna todos os jogadores registrados (para recálculo de MMR em massa)."""
        async with get_session() as session:
            result = await session.execute(select(Player))
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
                session.add(MatchPlayer(
                    match_id=new_match.id,
                    player_id=p['id'],
                    side=TeamSide.BLUE,
                    mmr_before=p.get('mmr')
                ))
            for p in red_team:
                session.add(MatchPlayer(
                    match_id=new_match.id,
                    player_id=p['id'],
                    side=TeamSide.RED,
                    mmr_before=p.get('mmr')
                ))

            return new_match.id

    @staticmethod
    async def get_match_details(match_id: int):
        """Retorna detalhes de uma partida IN_PROGRESS (usado para validação de resultado)."""
        async with get_session() as session:
            result = await session.execute(select(Match).where(Match.id == match_id))
            match = result.scalar_one_or_none()

            if not match or match.status != MatchStatus.IN_PROGRESS:
                return None

            result_players = await session.execute(select(MatchPlayer).where(MatchPlayer.match_id == match_id))
            match_players = result_players.scalars().all()

            player_ids = [mp.player_id for mp in match_players]
            result_data = await session.execute(select(Player).where(Player.discord_id.in_(player_ids)))
            players_data = {p.discord_id: p for p in result_data.scalars().all()}

            blue_team, red_team = [], []
            for mp in match_players:
                p = players_data.get(mp.player_id)
                if p:
                    info = {'id': p.discord_id, 'name': p.riot_name, 'mmr': p.mmr}
                    (blue_team if mp.side == TeamSide.BLUE else red_team).append(info)

            return {'status': match.status.value, 'blue_team': blue_team, 'red_team': red_team}

    @staticmethod
    async def get_match_by_id(match_id: int):
        """Retorna detalhes completos de qualquer partida independente do status."""
        async with get_session() as session:
            result = await session.execute(select(Match).where(Match.id == match_id))
            match = result.scalar_one_or_none()
            if not match:
                return None

            result_players = await session.execute(select(MatchPlayer).where(MatchPlayer.match_id == match_id))
            match_players = result_players.scalars().all()

            player_ids = [mp.player_id for mp in match_players if mp.player_id and mp.player_id > 0]
            players_data = {}
            if player_ids:
                result_data = await session.execute(select(Player).where(Player.discord_id.in_(player_ids)))
                players_data = {p.discord_id: p for p in result_data.scalars().all()}

            blue_team, red_team = [], []
            for mp in match_players:
                p = players_data.get(mp.player_id)
                if p:
                    info = {
                        'id': p.discord_id,
                        'name': p.riot_name,
                        'mmr': p.mmr,
                        'mmr_before': mp.mmr_before,
                        'is_captain': mp.is_captain,
                    }
                    (blue_team if mp.side == TeamSide.BLUE else red_team).append(info)

            return {
                'id': match.id,
                'status': match.status.value,
                'winning_side': match.winning_side.value if match.winning_side else None,
                'created_at': match.created_at,
                'finished_at': match.finished_at,
                'blue_team': blue_team,
                'red_team': red_team,
            }

    @staticmethod
    async def get_player_internal_history(discord_id: int):
        """Retorna todo o histórico de partidas internas de um jogador."""
        async with get_session() as session:
            result_mp = await session.execute(
                select(MatchPlayer)
                .where(MatchPlayer.player_id == discord_id)
            )
            player_entries = result_mp.scalars().all()
            if not player_entries:
                return []

            match_ids = [mp.match_id for mp in player_entries]
            player_sides = {mp.match_id: mp.side for mp in player_entries}

            result_matches = await session.execute(
                select(Match)
                .where(Match.id.in_(match_ids))
                .where(Match.status == MatchStatus.FINISHED)
                .order_by(desc(Match.finished_at))
            )
            matches = result_matches.scalars().all()

            history = []
            for match in matches:
                p_side = player_sides.get(match.id)
                won = (match.winning_side == p_side) if match.winning_side and p_side else None
                history.append({
                    'match_id': match.id,
                    'won': won,
                    'side': p_side.value if p_side else None,
                    'finished_at': match.finished_at,
                })
            return history

    @staticmethod
    async def get_h2h_data(discord_id_1: int, discord_id_2: int):
        """Retorna estatísticas de confronto direto entre dois jogadores."""
        async with get_session() as session:
            mp1 = aliased(MatchPlayer)
            mp2 = aliased(MatchPlayer)

            stmt = (
                select(Match, mp1.side.label('p1_side'), mp2.side.label('p2_side'))
                .join(mp1, mp1.match_id == Match.id)
                .join(mp2, mp2.match_id == Match.id)
                .where(mp1.player_id == discord_id_1)
                .where(mp2.player_id == discord_id_2)
                .where(Match.status == MatchStatus.FINISHED)
                .order_by(desc(Match.finished_at))
            )
            result = await session.execute(stmt)
            rows = result.all()

            if not rows:
                return {'total': 0, 'as_opponents': 0, 'as_teammates': 0,
                        'p1_wins': 0, 'p2_wins': 0, 'together_wins': 0, 'together_losses': 0, 'matches': []}

            p1_wins = p2_wins = as_opponents = as_teammates = together_wins = together_losses = 0
            match_results = []

            for match, p1_side, p2_side in rows:
                same_team = (p1_side == p2_side)
                p1_won = (match.winning_side == p1_side) if match.winning_side else None
                p2_won = (match.winning_side == p2_side) if match.winning_side else None

                if same_team:
                    as_teammates += 1
                    if p1_won: together_wins += 1
                    else: together_losses += 1
                else:
                    as_opponents += 1
                    if p1_won: p1_wins += 1
                    elif p2_won: p2_wins += 1

                match_results.append({
                    'match_id': match.id,
                    'same_team': same_team,
                    'p1_won': p1_won,
                    'p2_won': p2_won,
                    'finished_at': match.finished_at,
                })

            return {
                'total': len(rows),
                'as_opponents': as_opponents,
                'as_teammates': as_teammates,
                'p1_wins': p1_wins,
                'p2_wins': p2_wins,
                'together_wins': together_wins,
                'together_losses': together_losses,
                'matches': match_results,
            }

    @staticmethod
    async def finish_match(match_id: int, winning_side: str):
        side_enum = TeamSide.BLUE if winning_side.upper() == 'BLUE' else TeamSide.RED

        async with get_session() as session:
            result = await session.execute(select(Match).where(Match.id == match_id))
            match = result.scalar_one_or_none()

            if not match: return "NOT_FOUND"
            if match.status == MatchStatus.FINISHED: return "ALREADY_FINISHED"
            if match.status == MatchStatus.CANCELLED: return "ALREADY_CANCELLED"

            match.status = MatchStatus.FINISHED
            match.winning_side = side_enum
            match.finished_at = datetime.utcnow()

            result_players = await session.execute(select(MatchPlayer).where(MatchPlayer.match_id == match_id))
            match_players = result_players.scalars().all()

            for mp in match_players:
                p_result = await session.execute(select(Player).where(Player.discord_id == mp.player_id))
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
            result = await session.execute(select(Match).where(Match.id == match_id))
            match = result.scalar_one_or_none()

            if not match: return "NOT_FOUND"
            if match.status != MatchStatus.IN_PROGRESS: return "NOT_ACTIVE"

            match.status = MatchStatus.CANCELLED
            match.finished_at = datetime.utcnow()
            return "SUCCESS"


# --- REPOSITÓRIO DO LOBBY ---
class LobbyRepository:

    @staticmethod
    async def save_state(guild_id: int, queue: list, channel_id: int = None):
        """Persiste a fila atual no banco de dados."""
        async with get_session() as session:
            result = await session.execute(select(LobbyState).where(LobbyState.guild_id == guild_id))
            state = result.scalar_one_or_none()

            queue_serializable = []
            for p in queue:
                entry = dict(p)
                # Garante que main_lane é string serializável
                if hasattr(entry.get('main_lane'), 'value'):
                    entry['main_lane'] = entry['main_lane'].value
                queue_serializable.append(entry)

            if state:
                state.queue_json = json.dumps(queue_serializable)
                if channel_id:
                    state.channel_id = channel_id
                state.updated_at = datetime.utcnow()
            else:
                state = LobbyState(
                    guild_id=guild_id,
                    queue_json=json.dumps(queue_serializable),
                    channel_id=channel_id,
                    updated_at=datetime.utcnow()
                )
                session.add(state)

    @staticmethod
    async def get_state(guild_id: int):
        """Recupera o estado da fila do banco de dados."""
        async with get_session() as session:
            result = await session.execute(select(LobbyState).where(LobbyState.guild_id == guild_id))
            state = result.scalar_one_or_none()
            if not state:
                return None
            return {
                'queue': json.loads(state.queue_json or '[]'),
                'channel_id': state.channel_id,
            }

    @staticmethod
    async def clear_state(guild_id: int):
        """Limpa a fila persistida (após partida iniciar ou ser cancelada)."""
        async with get_session() as session:
            result = await session.execute(select(LobbyState).where(LobbyState.guild_id == guild_id))
            state = result.scalar_one_or_none()
            if state:
                state.queue_json = "[]"
                state.updated_at = datetime.utcnow()


# --- REPOSITÓRIO DA COMUNIDADE ---
class CommunityRepository:

    @staticmethod
    async def add_xp(discord_id: int, xp_amount: int, has_media: bool = False, voice_minutes: int = 0):
        """Adiciona XP e tempo de voz. Retorna (leveled_up, new_level)."""
        async with get_session() as session:
            result = await session.execute(select(CommunityProfile).where(CommunityProfile.discord_id == discord_id))
            profile = result.scalar_one_or_none()

            if not profile:
                profile = CommunityProfile(
                    discord_id=discord_id,
                    joined_at=datetime.utcnow(),
                    xp=0, level=1, messages_sent=0, media_sent=0, voice_minutes=0
                )
                session.add(profile)

            # Tratamento de Nulos (Legado)
            if profile.messages_sent is None: profile.messages_sent = 0
            if profile.xp is None: profile.xp = 0
            if profile.media_sent is None: profile.media_sent = 0
            if profile.level is None: profile.level = 1
            if profile.voice_minutes is None: profile.voice_minutes = 0

            if xp_amount > 0 and voice_minutes == 0:
                profile.messages_sent += 1
                if has_media:
                    profile.media_sent += 1

            profile.xp += xp_amount

            if voice_minutes > 0:
                profile.voice_minutes += voice_minutes

            profile.last_message_at = datetime.utcnow()

            # Level Up
            xp_needed = int(profile.level * 100 * 1.2)
            leveled_up = False
            if profile.xp >= xp_needed:
                profile.xp -= xp_needed
                profile.level += 1
                leveled_up = True

            return leveled_up, profile.level

    @staticmethod
    async def get_profile(discord_id: int):
        async with get_session() as session:
            result = await session.execute(select(CommunityProfile).where(CommunityProfile.discord_id == discord_id))
            return result.scalar_one_or_none()

    @staticmethod
    async def get_ranking_position(discord_id: int):
        async with get_session() as session:
            result = await session.execute(
                select(CommunityProfile.discord_id)
                .order_by(desc(CommunityProfile.level), desc(CommunityProfile.xp))
            )
            ids = result.scalars().all()
            try:
                return ids.index(discord_id) + 1
            except ValueError:
                return 0

    @staticmethod
    async def get_top_xp(limit: int = 10):
        async with get_session() as session:
            result = await session.execute(
                select(CommunityProfile)
                .order_by(desc(CommunityProfile.level), desc(CommunityProfile.xp))
                .limit(limit)
            )
            return result.scalars().all()
