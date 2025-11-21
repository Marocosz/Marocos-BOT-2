import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from src.database.config import init_db
import logging

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("main")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True 

class RobustBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=".", # <--- MUDADO PARA PONTO
            intents=intents,
            help_command=None,
            application_id=os.getenv("APP_ID")
        )

    async def setup_hook(self):
        logger.info("--- Iniciando Setup ---")
        await init_db()
        logger.info("Banco de Dados conectado.")

        # Carregar Cogs
        for filename in os.listdir("./src/cogs"):
            if filename.endswith(".py") and filename != "__init__.py":
                try:
                    await self.load_extension(f"src.cogs.{filename[:-3]}")
                    logger.info(f"Cog carregada: {filename}")
                except Exception as e:
                    logger.error(f"FALHA ao carregar {filename}: {e}")

        # NÃO PRECISAMOS MAIS DO self.tree.sync() POIS SÃO COMANDOS DE TEXTO
        logger.info("--- Setup Finalizado ---")

    async def on_ready(self):
        logger.info(f'Bot Online! Logado como: {self.user}')

async def main():
    bot = RobustBot()
    token = os.getenv("DISCORD_TOKEN")
    if not token: return
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass