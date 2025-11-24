import discord
import asyncio
import random
from discord.ext import commands, tasks
from src.services.riot_api import RiotAPI
from src.database.repositories import PlayerRepository, GuildRepository
# NOVO: Importar o MatchMaker para recalcular o MMR no loop
from src.services.matchmaker import MatchMaker 

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
        "🚀 **{user}** acabou de subir para **{tier} {rank} ({queue})**! Ninguém segura!",
        "🎉 Parabéns **{user}**! Alcançou **{tier} {rank} ({queue})**. O topo é o limite.",
        "🔥 **{user}** está smurfando? Subiu para **{tier} {rank} ({queue})**.",
        "📈 **{user}** promoveu para **{tier} {rank} ({queue})**. Respeita!",
        "👑 **{user}** atingiu **{tier} {rank} ({queue})**. Jogou muito!"
    ]

    demotions = [
        "📉 **{user}** caiu para **{tier} {rank} ({queue})**. F no chat.",
        "💀 **{user}** foi rebaixado para **{tier} {rank} ({queue})**. A SoloQ não perdoa.",
        "⚠️ **{user}** demoveu para **{tier} {rank} ({queue})**. Hora de rever o replay.",
        "😭 **{user}** caiu para **{tier} {rank} ({queue})**. Voltaremos mais fortes.",
        "📉 Alerta de queda! **{user}** agora é **{tier} {rank} ({queue})**."
    ]

    # --- LÓGICA DE COMPARAÇÃO ---
    def elo_value(self, tier, rank):
        t_val = {'IRON': 0, 'BRONZE': 10, 'SILVER': 20, 'GOLD': 30, 'PLATINUM': 40, 'EMERALD': 50, 'DIAMOND': 60, 'MASTER': 70, 'GRANDMASTER': 80, 'CHALLENGER': 90, 'UNRANKED': -1}
        r_val = {'IV': 0, 'III': 1, 'II': 2, 'I': 3, '': 0}
        
        if tier.upper() in ['MASTER', 'GRANDMASTER', 'CHALLENGER']:
            return t_val.get(tier.upper(), 0) + 1
        
        return t_val.get(tier.upper(), 0) + r_val.get(rank.upper(), 0)

    # --- LOOP AUTOMÁTICO (A CADA 10 MINUTOS) ---
    @tasks.loop(minutes=10)
    async def check_ranks_loop(self):
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            channel_id = await GuildRepository.get_tracking_channel(guild.id)
            # Mesmo se não tiver canal configurado, queremos atualizar o MMR no banco
            channel = self.bot.get_channel(channel_id) if channel_id else None

            players = await PlayerRepository.get_all_players_with_puuid()

            for p in players:
                try:
                    await asyncio.sleep(1.5) # Rate limit

                    # 1. Busca Elo Atual na Riot
                    riot_ranks = await self.riot_service.get_rank_by_puuid(p.riot_puuid)
                    
                    solo_data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
                    flex_data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)
                    
                    active_queue = None
                    queue_type_str = None
                    old_tier, old_rank = "UNRANKED", "" 

                    # PRIORIDADE: SoloQ
                    if solo_data:
                        active_queue = solo_data
                        queue_type_str = 'RANKED_SOLO_5x5'
                        old_tier, old_rank = p.solo_tier, p.solo_rank
                    # FALLBACK: Flex
                    elif flex_data:
                        active_queue = flex_data
                        queue_type_str = 'RANKED_FLEX_SR'
                        old_tier, old_rank = p.flex_tier, p.flex_rank
                    else:
                        continue 

                    # --- NOVO: RECALCULA O MMR SEMPRE ---
                    # Isso garante que o .ranking esteja sempre atualizado, mesmo sem mudar de elo
                    new_calculated_mmr = MatchMaker.calculate_adjusted_mmr(
                        tier=active_queue['tier'],
                        rank=active_queue['rank'],
                        lp=active_queue['leaguePoints'],
                        wins=active_queue['wins'],
                        losses=active_queue['losses'],
                        queue_type=queue_type_str
                    )
                    # ------------------------------------

                    # 2. Compara para Notificação
                    old_val = self.elo_value(old_tier, old_rank)
                    new_val = self.elo_value(active_queue['tier'], active_queue['rank'])
                    
                    current_tier = active_queue['tier']
                    current_rank = active_queue['rank']
                    
                    queue_name = "Solo/Duo" if queue_type_str == 'RANKED_SOLO_5x5' else "Flex 5v5"

                    # Se é o primeiro registro
                    if old_val <= self.elo_value("UNRANKED", "") and new_val > self.elo_value("UNRANKED", ""):
                        await PlayerRepository.update_riot_rank(
                            p.discord_id, current_tier, current_rank, active_queue['leaguePoints'], 
                            active_queue['wins'], active_queue['losses'], 
                            new_calculated_mmr, # Usa o novo MMR calculado
                            queue_type=queue_type_str
                        )
                        continue

                    # Mudança de Elo (Notificação)
                    if new_val != old_val:
                        action = "promotions" if new_val > old_val else "demotions"
                        color = 0x2ecc71 if new_val > old_val else 0xe74c3c
                        
                        # Só envia msg se tiver canal configurado
                        if channel:
                            msg = random.choice(getattr(self, action)).format(
                                user=f"<@{p.discord_id}>", 
                                tier=current_tier, 
                                rank=current_rank,
                                queue=queue_name
                            )
                            embed = discord.Embed(description=msg, color=color)
                            await channel.send(embed=embed)
                        
                        # Atualiza DB com novo MMR
                        await PlayerRepository.update_riot_rank(
                            p.discord_id, current_tier, current_rank, active_queue['leaguePoints'], 
                            active_queue['wins'], active_queue['losses'], 
                            new_calculated_mmr, # Usa o novo MMR calculado
                            queue_type=queue_type_str
                        )

                    # Se o elo não mudou, mas atualizamos o MMR/LP (ESSA É A PARTE QUE FALTAVA)
                    else:
                         await PlayerRepository.update_riot_rank(
                            p.discord_id, current_tier, current_rank, active_queue['leaguePoints'], 
                            active_queue['wins'], active_queue['losses'], 
                            new_calculated_mmr, # Usa o novo MMR calculado e SALVA
                            queue_type=queue_type_str
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
        
        queue_type = 'RANKED_FLEX_SR' if fila.upper() == 'FLEX' else 'RANKED_SOLO_5x5'
        
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