import discord
from discord.ext import commands
import random
import asyncio

class Zoeira(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.TONHAO_NAME = "Tonhão Calabresa"
        self.TORRES_MENTION = "<@123456789012345678>" 

        # Lista de mensagens estruturadas (Target: None para não marcar)
        self.insults = [
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, você é tão inutil que até a desgraça tenta se afastar de você pra não pegar sua energia de fracasso.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, tua existência é tão vexatória que até tua família te apresenta como 'um erro que passou no filtro'.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, você é o tipo de pessoa que até quando tenta ajudar, fode tudo com uma maestria digna de um filho da puta profissional.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, se incompetência fosse crime, você estaria cumprindo três prisões perpétuas e ainda devendo cadeia.", 'tag': None},
            {'target': self.TONHAO_NAME, 'text': f"{self.TONHAO_NAME}, tomar no cu perto de você seria um upgrade de caráter, porque hoje você só serve como exemplo do que não ser na vida.", 'tag': None},

            {'target': 'Torres', 'text': "Torres, você é tão fofuxo, o meu salame boyzinho, lindinho.", 'tag': self.TORRES_MENTION}
        ]

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