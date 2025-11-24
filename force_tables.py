import asyncio
import os
import sys
from dotenv import load_dotenv

# Configura path
sys.path.insert(0, os.path.abspath(os.getcwd()))
load_dotenv()

from src.database.config import engine, Base
# IMPORTANTE: Importar todos os modelos para o SQLAlchemy reconhecê-los
from src.database.models import Player, Match, MatchPlayer, GuildConfig, CommunityProfile

async def force_create_tables():
    print("🔄 Verificando esquema do banco de dados...")
    async with engine.begin() as conn:
        # O comando create_all cria APENAS as tabelas que não existem.
        # Ele não apaga dados das tabelas que já existem.
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tabelas sincronizadas com sucesso! A tabela 'community_profiles' deve existir agora.")

if __name__ == "__main__":
    asyncio.run(force_create_tables())