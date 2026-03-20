from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from src.database.config import Base

# --- ENUMS ---
class MatchStatus(enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "live"
    FINISHED = "finished"
    CANCELLED = "cancelled"

class TeamSide(enum.Enum):
    BLUE = "blue"
    RED = "red"

class Lane(enum.Enum):
    TOP = "TOP"
    JUNGLE = "JUNGLE"
    MID = "MID"
    ADC = "ADC"
    SUPPORT = "SUPPORT"
    FILL = "FILL"

# --- TABELAS ---

class GuildConfig(Base):
    """Configurações específicas de cada servidor Discord"""
    __tablename__ = "guild_configs"

    guild_id = Column(BigInteger, primary_key=True)
    organizer_role_id = Column(BigInteger, nullable=True)
    match_channel_id = Column(BigInteger, nullable=True)
    ranking_channel_id = Column(BigInteger, nullable=True)
    tracking_channel_id = Column(BigInteger, nullable=True)


class Player(Base):
    """Dados do Jogador (Discord + Riot + Stats Internos)"""
    __tablename__ = "players"

    discord_id = Column(BigInteger, primary_key=True)

    # Riot Data
    riot_puuid = Column(String, nullable=True)
    riot_name = Column(String, nullable=True)
    riot_id_str = Column(String, nullable=True)
    riot_icon_id = Column(Integer, nullable=True)

    # Ranking Cache (Riot)
    solo_tier = Column(String, default="UNRANKED")
    solo_rank = Column(String, default="")
    solo_lp = Column(Integer, default=0)
    solo_wins = Column(Integer, default=0)
    solo_losses = Column(Integer, default=0)

    flex_tier = Column(String, default="UNRANKED")
    flex_rank = Column(String, default="")
    flex_lp = Column(Integer, default=0)
    flex_wins = Column(Integer, default=0)
    flex_losses = Column(Integer, default=0)

    last_rank_update = Column(DateTime, default=datetime.utcnow)

    # Stats Internos (Liga Interna)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    mmr = Column(Integer, default=1200)

    # Streaks (Liga Interna)
    current_win_streak = Column(Integer, default=0)
    best_win_streak = Column(Integer, default=0)

    # Prêmios de votação (Liga Interna)
    mvp_count = Column(Integer, default=0)
    imvp_count = Column(Integer, default=0)

    # Preferências
    main_lane = Column(SAEnum(Lane), nullable=True)
    secondary_lane = Column(SAEnum(Lane), nullable=True)

    matches = relationship("MatchPlayer", back_populates="player")


class Match(Base):
    """A Partida (Lobby)"""
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    status = Column(SAEnum(MatchStatus), default=MatchStatus.OPEN)
    winning_side = Column(SAEnum(TeamSide), nullable=True)

    players = relationship("MatchPlayer", back_populates="match", cascade="all, delete-orphan")


class MatchPlayer(Base):
    """Tabela Pivô: Quem jogou a partida X, em qual time"""
    __tablename__ = "match_players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"))
    player_id = Column(BigInteger, ForeignKey("players.discord_id"))

    side = Column(SAEnum(TeamSide), nullable=True)
    is_captain = Column(Boolean, default=False)
    picked_lane = Column(SAEnum(Lane), nullable=True)
    mmr_before = Column(Integer, nullable=True)  # Snapshot do MMR no momento da partida

    match = relationship("Match", back_populates="players")
    player = relationship("Player", back_populates="matches")


class CommunityProfile(Base):
    """Perfil Social e de Gamificação do Usuário"""
    __tablename__ = "community_profiles"

    discord_id = Column(BigInteger, primary_key=True)

    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    messages_sent = Column(Integer, default=0)
    media_sent = Column(Integer, default=0)
    voice_minutes = Column(Integer, default=0)

    last_message_at = Column(DateTime, default=datetime.utcnow)
    joined_at = Column(DateTime, default=datetime.utcnow)


class LobbyState(Base):
    """Persiste o estado da fila para sobreviver a reinicializações do bot"""
    __tablename__ = "lobby_states"

    guild_id = Column(BigInteger, primary_key=True)
    queue_json = Column(String, default="[]")   # Fila serializada em JSON
    channel_id = Column(BigInteger, nullable=True)  # Canal onde a fila foi aberta
    updated_at = Column(DateTime, default=datetime.utcnow)
