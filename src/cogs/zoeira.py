import discord
from discord.ext import commands
import random
import asyncio
import logging

log = logging.getLogger(__name__)

class Zoeira(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.TONHAO_NAME = "Tonhão Calabresa"
        self.TORRES_MENTION = "<@410171778971992085>"
        self.TORRES_ID = 410171778971992085

        # --- TOGGLE: reagir com 🍅 em toda msg do Torres ---
        self.torres_tomate_ativo = True

        # Lista de mensagens estruturadas (Target: None para não marcar)
        self.insults = [
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, você é tão inutil que até a desgraça tenta se afastar de você pra não pegar sua energia de fracasso.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, tua existência é tão vexatória que até tua família te apresenta como 'um erro que passou no filtro'.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, você é o tipo de pessoa que até quando tenta ajudar, fode tudo com uma maestria digna de um filho da puta profissional.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, se incompetência fosse crime, você estaria cumprindo três prisões perpétuas e ainda devendo cadeia.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, tomar no cu perto de você seria um upgrade de caráter, porque hoje você só serve como exemplo do que não ser na vida.", 'tag': None},

            {'target': 'Torres', 'text': "Torres, você é tão fofuxo, o meu salame boyzinho, lindinho.", 'tag': self.TORRES_MENTION}
        ]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if random.random() < 0.10:  # ~1 em cada 10 msgs
            try:
                await message.add_reaction("<:marocosbot1:1484889563192234044>")
                log.info(f"[Zoeira] Reagiu com marocosbot1 na msg de {message.author} em #{message.channel}")
            except Exception as e:
                log.warning(f"[Zoeira] Falhou ao reagir com marocosbot1: {e}")

        if self.torres_tomate_ativo and message.author.id == self.TORRES_ID:
            try:
                await message.add_reaction("🍅")
                log.info(f"[Zoeira] Reagiu com 🍅 na msg do Torres em #{message.channel}")
            except Exception as e:
                log.warning(f"[Zoeira] Falhou ao reagir com tomate: {e}")

    @commands.command(name="fdp")
    async def fdp_command(self, ctx: commands.Context):
        """Manda uma piada interna aleatória xingando o Tonhão ou o Torres."""
        
        # 1. Escolhe uma piada aleatoriamente
        insult = random.choice(self.insults)
        
        message = insult['text']
        
        # 2. Aplica a marcação se o target for Torres
        if insult['tag']:
            # Se for Torres, a menção deve ir primeiro para garantir o ping
            message = f"{insult['tag']} {message}" 
        
        await ctx.send(message)

async def setup(bot: commands.Bot):
    await bot.add_cog(Zoeira(bot))