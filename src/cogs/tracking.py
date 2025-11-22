import discord
import asyncio
import random
from discord.ext import commands, tasks
from src.services.riot_api import RiotAPI
from src.database.repositories import PlayerRepository, GuildRepository

class RankingTracking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()
        
        # Inicia o loop automático ao carregar a Cog
        self.check_ranks_loop.start()

    def cog_unload(self):
        self.check_ranks_loop.cancel()

    # --- MENSAGENS ALEATÓRIAS ---
    promotions = [
        "🚀 **{user}** acabou de subir para **{tier} {rank}**! Ninguém segura!",
        "🎉 Parabéns **{user}**! Alcançou **{tier} {rank}**. O topo é o limite.",
        "🔥 **{user}** está smurfando? Subiu para **{tier} {rank}**.",
        "📈 **{user}** promoveu para **{tier} {rank}**. Respeita!",
        "👑 **{user}** atingiu **{tier} {rank}**. Jogou muito!"
    ]

    demotions = [
        "📉 **{user}** caiu para **{tier} {rank}**. F no chat.",
        "💀 **{user}** foi rebaixado para **{tier} {rank}**. A SoloQ não perdoa.",
        "⚠️ **{user}** demoveu para **{tier} {rank}**. Hora de rever o replay.",
        "😭 **{user}** caiu para **{tier} {rank}**. Voltaremos mais fortes.",
        "📉 Alerta de queda! **{user}** agora é **{tier} {rank}**."
    ]

    # --- LÓGICA DE COMPARAÇÃO ---
    def elo_value(self, tier, rank):
        # Transforma Elo em número para comparar (Ex: Gold 4 < Gold 3)
        t_val = {'IRON': 0, 'BRONZE': 10, 'SILVER': 20, 'GOLD': 30, 'PLATINUM': 40, 'EMERALD': 50, 'DIAMOND': 60, 'MASTER': 70, 'GRANDMASTER': 80, 'CHALLENGER': 90, 'UNRANKED': -1}
        r_val = {'IV': 0, 'III': 1, 'II': 2, 'I': 3, '': 0}
        return t_val.get(tier, 0) + r_val.get(rank, 0)

    # --- LOOP AUTOMÁTICO (A CADA 10 MINUTOS) ---
    @tasks.loop(minutes=10)
    async def check_ranks_loop(self):
        await self.bot.wait_until_ready()
        
        # Para cada servidor que o bot está
        for guild in self.bot.guilds:
            channel_id = await GuildRepository.get_tracking_channel(guild.id)
            if not channel_id: continue # Se não configurou canal, pula
            
            channel = self.bot.get_channel(channel_id)
            if not channel: continue

            # Busca jogadores (Idealmente filtrar por guilda, mas como é bot privado, pega todos)
            players = await PlayerRepository.get_all_players_with_puuid()

            for p in players:
                try:
                    # Evita rate limit da Riot
                    await asyncio.sleep(1.5) 

                    # 1. Busca Elo Atual na Riot
                    riot_ranks = await self.riot_service.get_rank_by_puuid(p.riot_puuid)
                    data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
                    
                    if not data: continue # Se não tem SoloQ, ignora

                    # 2. Compara com o Banco
                    old_val = self.elo_value(p.solo_tier, p.solo_rank)
                    new_val = self.elo_value(data['tier'], data['rank'])

                    # Se o banco diz Unranked mas a Riot diz Gold, ele subiu
                    if p.solo_tier == "UNRANKED" and data['tier'] != "UNRANKED":
                        # Primeiro registro de elo (não avisa, só salva)
                        await PlayerRepository.update_riot_rank(p.discord_id, data['tier'], data['rank'], data['leaguePoints'], data['wins'], data['losses'], p.mmr)
                        continue

                    # Lógica de Subida/Descida
                    if new_val > old_val:
                        msg = random.choice(self.promotions).format(user=f"<@{p.discord_id}>", tier=data['tier'], rank=data['rank'])
                        embed = discord.Embed(description=msg, color=0x2ecc71) # Verde
                        await channel.send(embed=embed)
                        
                        # Atualiza DB
                        await PlayerRepository.update_riot_rank(p.discord_id, data['tier'], data['rank'], data['leaguePoints'], data['wins'], data['losses'], p.mmr)

                    elif new_val < old_val:
                        msg = random.choice(self.demotions).format(user=f"<@{p.discord_id}>", tier=data['tier'], rank=data['rank'])
                        embed = discord.Embed(description=msg, color=0xe74c3c) # Vermelho
                        await channel.send(embed=embed)
                        
                        # Atualiza DB
                        await PlayerRepository.update_riot_rank(p.discord_id, data['tier'], data['rank'], data['leaguePoints'], data['wins'], data['losses'], p.mmr)
                    
                    # Se for igual, só atualiza PDL silenciosamente se quiser (opcional)

                except Exception as e:
                    print(f"Erro check loop player {p.riot_name}: {e}")

    # --- COMANDOS DE CONFIGURAÇÃO E TESTE ---

    @commands.command(name="config_aviso")
    @commands.has_permissions(administrator=True)
    async def config_aviso(self, ctx, canal: discord.TextChannel):
        """Define onde os avisos de Elo vão aparecer"""
        await GuildRepository.set_tracking_channel(ctx.guild.id, canal.id)
        await ctx.reply(f"✅ Avisos de Elo configurados para o canal {canal.mention}")

    @commands.command(name="fake_elo")
    @commands.has_permissions(administrator=True)
    async def fake_elo(self, ctx, jogador: discord.Member, tier: str, rank: str):
        """
        Muda o elo no BANCO DE DADOS (para testar o aviso).
        Ex: .fake_elo @Marocos GOLD IV
        (Na próxima verificação, o bot vai ver que na Riot está diferente e vai avisar)
        """
        player = await PlayerRepository.get_player_by_discord_id(jogador.id)
        if not player: return await ctx.reply("❌ Jogador não registrado.")
        
        # Força atualização no banco com dados falsos/antigos
        await PlayerRepository.update_riot_rank(
            discord_id=player.discord_id,
            tier=tier.upper(),
            rank=rank.upper(),
            lp=0, wins=0, losses=0, calculated_mmr=player.mmr
        )
        
        await ctx.reply(f"🕵️ **Modo Teste:** O Elo de {jogador.display_name} no banco agora é **{tier} {rank}**.\n⏳ Aguarde o loop automático (ou force o check) para ver o aviso de mudança.")

    @commands.command(name="forcar_check")
    @commands.has_permissions(administrator=True)
    async def forcar_check(self, ctx):
        """Força o loop de verificação rodar agora"""
        await ctx.reply("🔄 Iniciando verificação forçada de Elos...")
        if self.check_ranks_loop.is_running():
            self.check_ranks_loop.restart()
        else:
            self.check_ranks_loop.start()

async def setup(bot: commands.Bot):
    await bot.add_cog(RankingTracking(bot))