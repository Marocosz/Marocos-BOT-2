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
        
        # Se for Mestre+ o Rank é ignorado, a pontuação é fixa no TIER_VALUE.
        if tier.upper() in ['MASTER', 'GRANDMASTER', 'CHALLENGER']:
            # Master/GM/Challenger usam LP para diferenciacao, mas para promocao/democao, a mudanca de tier é o suficiente.
            return t_val.get(tier.upper(), 0) + 1 # Adiciona um pequeno valor fixo para diferenciar de Diamond I
        
        return t_val.get(tier.upper(), 0) + r_val.get(rank.upper(), 0)

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
                    
                    # Filtra filas ativas
                    solo_data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
                    flex_data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)
                    
                    active_queue = None
                    queue_type = None
                    old_tier, old_rank = "UNRANKED", "" # Default

                    # PRIORIDADE: SoloQ
                    if solo_data:
                        active_queue = solo_data
                        queue_type = 'RANKED_SOLO_5x5'
                        old_tier, old_rank = p.solo_tier, p.solo_rank
                    # FALLBACK: Flex
                    elif flex_data:
                        active_queue = flex_data
                        queue_type = 'RANKED_FLEX_SR'
                        old_tier, old_rank = p.flex_tier, p.flex_rank
                    else:
                        continue # Não tem rank em nenhuma fila

                    # 2. Compara com o Banco
                    old_val = self.elo_value(old_tier, old_rank)
                    new_val = self.elo_value(active_queue['tier'], active_queue['rank'])
                    
                    current_tier = active_queue['tier']
                    current_rank = active_queue['rank']
                    
                    # 3. Lógica de Promoção/Rebaixamento (Verifica apenas mudança de Tier ou Divisão)

                    # Se o banco está desatualizado (por exemplo, "UNRANKED" ou Elo antigo)
                    if old_val <= self.elo_value("UNRANKED", "") and new_val > self.elo_value("UNRANKED", ""):
                        # Primeiro registro de elo (não avisa, só salva o estado inicial)
                        await PlayerRepository.update_riot_rank(
                            p.discord_id, current_tier, current_rank, active_queue['leaguePoints'], 
                            active_queue['wins'], active_queue['losses'], p.mmr, queue_type=queue_type
                        )
                        continue

                    if new_val != old_val:
                        
                        action = "promotions" if new_val > old_val else "demotions"
                        color = 0x2ecc71 if new_val > old_val else 0xe74c3c
                        
                        queue_name = "Solo/Duo" if queue_type == 'RANKED_SOLO_5x5' else "Flex 5v5"
                        
                        msg = random.choice(getattr(self, action)).format(
                            user=f"<@{p.discord_id}>", 
                            tier=f"{current_tier} ({queue_name})", 
                            rank=current_rank
                        )
                        embed = discord.Embed(description=msg, color=color)
                        await channel.send(embed=embed)
                        
                        # Atualiza DB
                        await PlayerRepository.update_riot_rank(
                            p.discord_id, current_tier, current_rank, active_queue['leaguePoints'], 
                            active_queue['wins'], active_queue['losses'], p.mmr, queue_type=queue_type
                        )
                    
                    # Se o elo não mudou (new_val == old_val), mas os dados (LP/Wins/Losses) podem ter mudado
                    else:
                         await PlayerRepository.update_riot_rank(
                            p.discord_id, current_tier, current_rank, active_queue['leaguePoints'], 
                            active_queue['wins'], active_queue['losses'], p.mmr, queue_type=queue_type
                        )

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
    async def fake_elo(self, ctx, jogador: discord.Member, tier: str, rank: str, fila: str = "SOLO"):
        """
        Muda o elo no BANCO DE DADOS (para testar o aviso).
        Ex: .fake_elo @Marocos GOLD IV SOLO
        """
        player = await PlayerRepository.get_player_by_discord_id(jogador.id)
        if not player: return await ctx.reply("❌ Jogador não registrado.")
        
        # Mapeia a fila para o formato do repositório
        queue_type = 'RANKED_FLEX_SR' if fila.upper() == 'FLEX' else 'RANKED_SOLO_5x5'
        
        # Força atualização no banco com dados falsos/antigos
        await PlayerRepository.update_riot_rank(
            discord_id=player.discord_id,
            tier=tier.upper(),
            rank=rank.upper(),
            lp=0, wins=0, losses=0, calculated_mmr=player.mmr,
            queue_type=queue_type
        )
        
        await ctx.reply(f"🕵️ **Modo Teste:** O Elo {fila.upper()} de {jogador.display_name} no banco agora é **{tier} {rank}**.\n⏳ Aguarde o loop automático (ou force o check) para ver o aviso de mudança.")

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