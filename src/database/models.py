from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from src.database.config import Base

# --- ENUMS (Padronização) ---
class MatchStatus(enum.Enum):
    OPEN = "open"           # Fila aberta / Draft
    IN_PROGRESS = "live"    # Partida rolando
    FINISHED = "finished"   # Finalizada
    CANCELLED = "cancelled" # Cancelada por ADM

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
    organizer_role_id = Column(BigInteger, nullable=True) # ID do cargo de Organizador
    match_channel_id = Column(BigInteger, nullable=True)  # Canal onde rolam os jogos
    ranking_channel_id = Column(BigInteger, nullable=True) # Canal de atualizações de ranking
    tracking_channel_id = Column(BigInteger, nullable=True) # Novo: Canal de avisos de Elo

class Player(Base):
    """Dados do Jogador (Discord + Riot + Stats Internos)"""
    __tablename__ = "players"

    discord_id = Column(BigInteger, primary_key=True)
    
    # Riot Data
    riot_puuid = Column(String, nullable=True)
    riot_name = Column(String, nullable=True) # Nome#TAG
    riot_id_str = Column(String, nullable=True) # GameName
    riot_icon_id = Column(Integer, nullable=True)
    
    # --- DADOS DE RANKING (Cache da Riot para cálculo de MMR e Tracking) ---
    solo_tier = Column(String, default="UNRANKED")
    solo_rank = Column(String, default="")
    solo_lp = Column(Integer, default=0)
    solo_wins = Column(Integer, default=0)
    solo_losses = Column(Integer, default=0)
    last_rank_update = Column(DateTime, default=datetime.utcnow)

    # Stats Internos (Liga Interna)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    mmr = Column(Integer, default=1200) # Elo interno inicial
    
    # Preferências
    main_lane = Column(SAEnum(Lane), nullable=True)
    secondary_lane = Column(SAEnum(Lane), nullable=True)

    # Relacionamento reverso (Para saber partidas que jogou)
    matches = relationship("MatchPlayer", back_populates="player")

class Match(Base):
    """A Partida (Lobby)"""
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True) # O famoso Match ID
    guild_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    
    status = Column(SAEnum(MatchStatus), default=MatchStatus.OPEN)
    winning_side = Column(SAEnum(TeamSide), nullable=True) # Quem ganhou?
    
    # Relacionamento
    players = relationship("MatchPlayer", back_populates="match", cascade="all, delete-orphan")

class MatchPlayer(Base):
    """Tabela Pivô: Quem jogou a partida X, em qual time, e se era capitão"""
    __tablename__ = "match_players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"))
    player_id = Column(BigInteger, ForeignKey("players.discord_id"))
    
    side = Column(SAEnum(TeamSide), nullable=True) # Blue ou Red
    is_captain = Column(Boolean, default=False)
    picked_lane = Column(SAEnum(Lane), nullable=True) # Lane que jogou NESTA partida

    # Relacionamentos
    match = relationship("Match", back_populates="players")
    player = relationship("Player", back_populates="matches")