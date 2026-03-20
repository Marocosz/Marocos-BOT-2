# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MarocosBot is a Discord bot for managing an internal League of Legends league. It handles player registration (via Riot API), a custom hybrid MMR system, match queue/draft management, and community XP/leveling.

## Commands

```bash
# Run the bot
python -m src.main

# Install dependencies
pip install -r requirements.txt

# Docker build and run
docker build -t marocos-bot .
docker run --env-file .env marocos-bot

# Database utilities (root-level scripts)
python force_tables.py      # Initialize/recreate tables
python migration_tool.py    # Run database migrations
python update_db.py         # Update database schema
python debug_api.py         # Debug Riot API responses
```

Environment variables are loaded from `.env` (copy and fill):
```
DISCORD_TOKEN=
RIOT_API_KEY=
RIOT_REGION=br1
DATABASE_URL=sqlite+aiosqlite:///./data/database.sqlite
DEBUG_GUILD_ID=
LOG_LEVEL=INFO
```

## Architecture

### Layer Structure

```
src/
├── main.py              # Entry point: initializes RobustBot, loads cogs, inits DB
├── bot/                 # Bot class definition (extends commands.Bot)
├── cogs/                # Discord command modules (loaded dynamically by main.py)
├── database/
│   ├── config.py        # SQLAlchemy async engine + session factory
│   ├── models.py        # ORM models
│   └── repositories.py  # All data access (PlayerRepository, MatchRepository, etc.)
├── services/
│   ├── riot_api.py      # Riot Games API client (rate limiting, semaphore)
│   ├── matchmaker.py    # MMR calculation & team balancing
│   └── queue_manager.py # Active match queue state
└── utils/
    └── views.py         # BaseInteractiveView + reusable Discord UI components
```

### Cogs

| Cog | Responsibility |
|-----|----------------|
| `auth.py` | `.registrar` — links Discord ↔ Riot account with icon verification |
| `lobby.py` | `.fila` queue, captain draft, team selection, match lifecycle (largest file) |
| `ranking.py` | `.ranking`, `.mmr` — leaderboards and stats display |
| `comunidade.py` | XP gain from messages/voice, level tracking, community profiles |
| `admin.py` | Organizer/admin management commands |
| `tracking.py` | Background task: monitors Elo changes and posts notifications |
| `general.py` | `.help` and informational commands |
| `zoeira.py` | Fun/meme commands |

### Key Data Models

- **Player** — Riot account link, SoloQ/Flex ranks (tier/rank/LP/wins/losses), internal `mmr`, main/secondary lanes
- **Match** — Guild ID, status (`OPEN`/`LIVE`/`FINISHED`/`CANCELLED`), winning side
- **MatchPlayer** — pivot: player↔match with side (BLUE/RED), captain flag, picked lane
- **CommunityProfile** — XP, level, message count, voice minutes
- **GuildConfig** — Per-server channel and role IDs

### MMR System

Hybrid Elo formula in `services/matchmaker.py`:
- Base score = Tier (0–2800) + Rank (0–300) + LP
- Queue multiplier: 0.85× for Flex, 1.0× for SoloQ
- Velocity bonus: `wr_diff * k_factor` where K scales 20→2 based on game count
- Final: `(base_score * queue_multiplier) + velocity_bonus`

### Match Flow

1. Players join queue via `.fila`
2. Admin starts draft → captains selected (manual or auto)
3. Coinflip determines sides → players pick lanes
4. Match status becomes `LIVE`
5. Admin records winner → MMR recalculated for all 10 players

### Discord UI Pattern

All interactive views extend `BaseInteractiveView` in `utils/views.py`, which handles timeout expiration with a "Tempo Expirado" state. Used for verification flows, captain selection, lane picks, and paginated rankings.

### Database Access Pattern

All DB operations go through repository classes in `repositories.py`. Cogs receive repository instances (or the session factory) and must use `async with async_session() as session:` scoping. Never access models directly from cogs.
