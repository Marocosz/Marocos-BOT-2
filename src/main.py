import discord
import os
import asyncio
import logging
import sys # Adicionado para manipulação de encerramento
from discord.ext import commands
from dotenv import load_dotenv

# Carregamento de variáveis de ambiente
load_dotenv()

# --- Configuração de Log ---
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("main")
# --------------------------

# Configuração de Intents (mantidas e necessárias para on_message e presenças)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True 

class RobustBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=".",
            intents=intents,
            help_command=None,
            application_id=os.getenv("APP_ID")
        )

    async def setup_hook(self):
        # NOTA: Importamos a config e o init_db AQUI para evitar problemas de importação circular
        # antes do setup de logging e environment.
        try:
            from src.database.config import init_db
        except ImportError:
            logger.error("Falha ao importar init_db. Verifique o path de src.database.config.")
            sys.exit(1) # Sai se não conseguir importar a base de dados
            
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

        logger.info("--- Setup Finalizado ---")

    async def on_ready(self):
        logger.info(f'Bot Online! Logado como: {self.user}')

async def main():
    # Assegura que o script seja executado a partir do diretório raiz do projeto
    if not os.path.exists("./src"):
        logger.error("Não foi possível encontrar o diretório 'src'. Execute o bot da raiz do projeto.")
        return 
        
    bot = RobustBot()
    token = os.getenv("DISCORD_TOKEN")
    
    if not token:
        logger.error("DISCORD_TOKEN não encontrado nas variáveis de ambiente (.env ou Coolify).")
        return
        
    async with bot:
        # Tenta iniciar o bot, garantindo que o client.close() seja chamado ao sair do bloco 'async with'
        await bot.start(token)

if __name__ == "__main__":
    try:
        # Execução principal
        asyncio.run(main())
    except KeyboardInterrupt:
        # Tratamento limpo para interrupções manuais (Ctrl+C)
        logger.info("Bot encerrado via interrupção manual.")
    except Exception as e:
        logger.critical(f"Erro fatal no ciclo de vida do bot: {e}")