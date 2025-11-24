import discord
import asyncio
from discord.ext import commands
from src.database.repositories import PlayerRepository
from src.services.riot_api import RiotAPI
from src.services.matchmaker import MatchMaker
from src.utils.views import BaseInteractiveView # <-- NOVO: Importa a Base View

# --- VIEW DE PAGINAÇÃO (MODIFICADA PARA HERANÇA) ---
class RankingPaginationView(BaseInteractiveView): # <-- HERDA DA BASE
    def __init__(self, players, ctx, per_page=10): 
        # O timeout de 120s (2 min) é mantido, passando-o para a Base
        super().__init__(timeout=120) 
        self.players = players
        self.per_page = per_page
        self.current_page = 0
        self.ctx = ctx
        self.total_pages = max(1, (len(players) + per_page - 1) // per_page)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page == self.total_pages - 1)
        self.counter_button.label = f"{self.current_page + 1}/{self.total_pages}"
        
        if self.total_pages == 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True

    def create_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        batch = self.players[start:end]

        embed = discord.Embed(title="🏆 Ranking da Liga Interna", color=0xffd700)
        embed.description = "Classificação por **Vitórias** > **Derrotas** > **MMR**."

        lista_fmt = ""
        for i, p in enumerate(batch):
            # Calcula a posição real (ex: página 2 começa no 11)
            rank_pos = start + i + 1
            
            if rank_pos == 1: icon = "🥇"
            elif rank_pos == 2: icon = "🥈"
            elif rank_pos == 3: icon = "🥉"
            else: icon = f"`{rank_pos}.`"

            total = p.wins + p.losses
            wr = (p.wins / total * 100) if total > 0 else 0
            
            lista_fmt += (
                f"{icon} **{p.riot_name}**\n"
                f"└ `{p.wins}V` - `{p.losses}D` ({wr:.0f}%) • **{p.mmr}** MMR\n"
            )
        
        if not batch:
            lista_fmt = "Nenhum jogador nesta página."

        embed.add_field(name="Jogadores", value=lista_fmt, inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Apenas o autor do comando pode interagir
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("✋ Apenas o autor do comando pode navegar aqui.", ephemeral=True)
        return False

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.gray, disabled=True)
    async def counter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass 

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


class Ranking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()

    def get_tier_emoji(self, tier: str) -> str:
        tier = tier.upper()
        emoji_map = {
            'IRON': '🟤', 'BRONZE': '🟤', 'SILVER': '⚪', 'GOLD': '🟡',
            'PLATINUM': '🟢', 'EMERALD': '💚', 'DIAMOND': '💎',
            'MASTER': '🟣', 'GRANDMASTER': '🔴', 'CHALLENGER': '👑'
        }
        return emoji_map.get(tier, '⚫')

    def get_queue_name(self, queue_id: int):
        # Nomes mais específicos e curtos para caber na coluna
        queues = {
            420: "Solo/Duo", 
            440: "Flex 5v5", 
            450: "ARAM", 
            490: "Quickplay", 
            1700: "Arena", 
            1900: "URF"
        }
        return queues.get(queue_id, "Normal")

    # --- COMANDO 1: RANKING (ATUALIZADO COM PAGINAÇÃO) ---
    @commands.command(name="ranking", aliases=["top", "leaderboard"])
    async def ranking(self, ctx):
        """Mostra TODOS os jogadores da Liga Interna (Paginado)"""
        # Busca sem limite (limit=None) para pegar todo mundo
        players = await PlayerRepository.get_internal_ranking(limit=None)
        
        if not players:
            embed = discord.Embed(title="🏆 Ranking da Liga Interna", color=0x3498db)
            embed.description = "Nenhuma partida foi jogada ainda ou ninguém pontuou."
            await ctx.reply(embed=embed)
            return

        # Cria a View de Paginação
        view = RankingPaginationView(players, ctx=ctx, per_page=10)
        
        # Envia a primeira página e SALVA A REFERÊNCIA
        sent_message = await ctx.reply(embed=view.create_embed(), view=view)
        view.message = sent_message # <--- Captura a referência para o on_timeout

    # --- COMANDO 2: PERFIL (CORRIGIDO LINK OP.GG) ---
    @commands.command(name="perfil")
    async def perfil(self, ctx, jogador: discord.Member = None):
        """Exibe o cartão de jogador COMPLETO e Atualiza MMR."""
        async with ctx.typing():
            target_user = jogador or ctx.author
            
            player = await PlayerRepository.get_player_by_discord_id(target_user.id)
            if not player:
                await ctx.reply(f"❌ {target_user.mention} não está registrado. Use `.registrar`.")
                return

            riot_ranks = []
            top_mastery = []
            summoner_level = "N/A"
            live_icon_id = player.riot_icon_id 

            try:
                # 1. Busca Dados Basicos (Level e Icone ATUAL)
                summoner_data = await self.riot_service.get_summoner_by_puuid(player.riot_puuid)
                if summoner_data:
                    summoner_level = summoner_data.get('summonerLevel', 'N/A')
                    live_icon_id = summoner_data.get('profileIconId')

                # 2. Busca Rank e Maestria
                riot_ranks = await self.riot_service.get_rank_by_puuid(player.riot_puuid)
                top_mastery = await self.riot_service.get_top_mastery(player.riot_puuid)
                
                # --- ATUALIZAÇÃO DE MMR (LÓGICA NOVA) ---
                # Tenta usar SoloQ para o MMR. Se não tiver, usa Flex como fallback.
                mmr_source = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
                
                if not mmr_source:
                    mmr_source = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)

                if mmr_source:
                    # Calcula usando a nova classe MatchMaker V2 (com peso de fila e winrate)
                    new_mmr = MatchMaker.calculate_adjusted_mmr(
                        tier=mmr_source['tier'], 
                        rank=mmr_source['rank'], 
                        lp=mmr_source['leaguePoints'], 
                        wins=mmr_source['wins'], 
                        losses=mmr_source['losses'],
                        queue_type=mmr_source['queueType'] # Passamos o tipo da fila para aplicar penalidade se for Flex
                    )
                    
                    # Salva no Banco (Lógica para SoloQ)
                    if solo_rank_data := next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None):
                        await PlayerRepository.update_riot_rank(
                            discord_id=player.discord_id, 
                            tier=solo_rank_data['tier'], 
                            rank=solo_rank_data['rank'], 
                            lp=solo_rank_data['leaguePoints'],
                            wins=solo_rank_data['wins'],
                            losses=solo_rank_data['losses'],
                            calculated_mmr=new_mmr, # Salva o MMR calculado com base na fonte prioritária (SoloQ)
                            queue_type='RANKED_SOLO_5x5' 
                        )
                    
                    # Salva no Banco (Lógica para Flex)
                    if flex_rank_data := next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None):
                        await PlayerRepository.update_riot_rank(
                            discord_id=player.discord_id, 
                            tier=flex_rank_data['tier'], 
                            rank=flex_rank_data['rank'], 
                            lp=flex_rank_data['leaguePoints'],
                            wins=flex_rank_data['wins'],
                            losses=flex_rank_data['losses'],
                            queue_type='RANKED_FLEX_SR'
                        )
                    
                
                # Se Unranked total, atualiza com MMR base
                if not solo_rank_data and not flex_rank_data and mmr_source:
                    await PlayerRepository.update_riot_rank(player.discord_id, "UNRANKED", "", 0, 0, 0, 1000)

                # Rebusca o objeto Player do banco para refletir TODAS as atualizações
                player = await PlayerRepository.get_player_by_discord_id(target_user.id)
                    
            except Exception as e:
                print(f"Erro API Riot durante perfil/update: {e}")

            # --- DESIGN DO CARD ---
            embed_color = 0x2b2d31 
            
            solo_data = {'tier': player.solo_tier, 'rank': player.solo_rank, 'lp': player.solo_lp, 'wins': player.solo_wins, 'losses': player.solo_losses}
            flex_data = {'tier': player.flex_tier, 'rank': player.flex_rank, 'lp': player.flex_lp, 'wins': player.flex_wins, 'losses': player.flex_losses}
            
            if player.solo_tier != "UNRANKED":
                tier_colors = {
                    'IRON': 0x564b49, 'BRONZE': 0x8c5133, 'SILVER': 0xc0c0c0, 'GOLD': 0xffd700, 
                    'PLATINUM': 0x2ecc71, 'EMERALD': 0x009475, 'DIAMOND': 0x3498db, 
                    'MASTER': 0x9b59b6, 'GRANDMASTER': 0xe74c3c, 'CHALLENGER': 0xf1c40f
                }
                embed_color = tier_colors.get(player.solo_tier, 0x2b2d31)

            embed = discord.Embed(color=embed_color)
            
            # --- CORREÇÃO DE LINK OP.GG ---
            name_and_tag = player.riot_name 
            url_friendly_name = name_and_tag.replace(' ', '-')
            final_url_path = url_friendly_name.replace('#', '-')
            riot_link = f"[{name_and_tag}](https://www.op.gg/summoners/br/{final_url_path})"
            # -----------------------------
            
            embed.set_author(name=f"{target_user.display_name} • Nível {summoner_level}", icon_url=target_user.display_avatar.url)
            
            if live_icon_id:
                embed.set_thumbnail(url=f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{live_icon_id}.png")

            main_lane = player.main_lane.value.capitalize() if player.main_lane else "N/A"
            sec_lane = player.secondary_lane.value.capitalize() if player.secondary_lane else "N/A"
            embed.description = f"🆔 **Conta:** {riot_link}\n🗺️ **Rotas:** {main_lane} / {sec_lane}"
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            def format_rank_detailed(data):
                if data['tier'] == "UNRANKED": return "```st\nUnranked\n```"
                wins = data['wins']
                losses = data['losses']
                total = wins + losses
                wr = (wins / total * 100) if total > 0 else 0
                return (f"{self.get_tier_emoji(data['tier'])} **{data['tier']} {data['rank']}**\n"
                        f"Info: `{data['lp']} PDL` • `{wr:.0f}% WR`\n"
                        f"Score: `{wins}V` - `{losses}D`")

            embed.add_field(name="🛡️ Solo/Duo", value=format_rank_detailed(solo_data), inline=True)
            embed.add_field(name="⚔️ Flex 5v5", value=format_rank_detailed(flex_data), inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            if top_mastery:
                m_list = []
                for i, c in enumerate(top_mastery):
                    name = await self.riot_service.get_champion_name(c['championId'])
                    points = int(c['championPoints'])
                    pts_str = f"{points/1000:.1f}k" if points > 1000 else str(points)
                    m_list.append(f"`#{i+1}` **{name}** (M{c['championLevel']}) • {pts_str}")
                embed.add_field(name="🔥 Top Maestrias", value="\n".join(m_list), inline=False)

            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            total_ih = player.wins + player.losses
            wr_ih = (player.wins / total_ih * 100) if total_ih > 0 else 0.0
            
            stats_block = (
                f"```yaml\n"
                f"MMR: {player.mmr}\n"
                f"Jogos: {total_ih}\n"
                f"V/D: {player.wins} - {player.losses}\n"
                f"Win%: {wr_ih:.1f}%\n"
                f"```"
            )
            
            embed.add_field(name="🏆 Liga Interna", value=stats_block, inline=False)
            embed.set_footer(text=f"System ID: {player.discord_id}")

            await ctx.reply(embed=embed)

    # --- COMANDO 3: MMR (AUDITORIA DETALHADA) ---
    @commands.command(name="mmr")
    async def mmr(self, ctx, jogador: discord.Member = None):
        """Relatório detalhado da pontuação"""
        target_user = jogador or ctx.author
        player = await PlayerRepository.get_player_by_discord_id(target_user.id)
        if not player: return await ctx.reply("❌ Jogador não registrado.")

        # Busca dados frescos
        riot_ranks = await self.riot_service.get_rank_by_puuid(player.riot_puuid)
        
        # Prioriza SoloQ
        data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
        is_flex = False
        
        # Fallback Flex
        if not data:
            data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)
            is_flex = True
        
        if not data:
            await ctx.reply(f"🔍 **{player.riot_name}** é Unranked. MMR Base: 1000.")
            return

        # Recálculo para Exibição Passo a Passo
        tier_score = MatchMaker.TIER_VALUES.get(data['tier'], 1000)
        rank_score = MatchMaker.RANK_VALUES.get(data['rank'], 0)
        base_raw = tier_score + rank_score + data['leaguePoints']
        
        queue_mod = 0.85 if is_flex else 1.0
        base_adjusted = int(base_raw * queue_mod)
        penalty_val = base_raw - base_adjusted 
        
        total_games = data['wins'] + data['losses']
        winrate = (data['wins'] / total_games * 100) if total_games > 0 else 0
        wr_diff = winrate - 50
        
        # Escada de K-Factor (Velocity)
        phase = "Veterano"
        k_factor = 2
        
        if total_games < 50: 
            k_factor = 20
            phase = "Calibração (Smurf?)"
        elif total_games < 100: 
            k_factor = 12
            phase = "Subida Rápida"
        elif total_games < 150: 
            k_factor = 8
            phase = "Estabilizando"
        elif total_games < 200: 
            k_factor = 4
            phase = "Consolidação"
        else:     
            k_factor = 2
            phase = "Elo Definido"
        
        bonus = int(wr_diff * k_factor)
        final = int(base_adjusted + bonus)
        final = max(0, final)

        # Montagem do Embed
        embed = discord.Embed(title=f"🧮 Extrato de MMR: {player.riot_name}", color=0x2b2d31)
        
        embed.add_field(
            name="1️⃣ Elo Oficial",
            value=f"**{data['tier']} {data['rank']}** ({data['leaguePoints']} PDL)\nValor Bruto: `{base_raw}` pontos",
            inline=True
        )

        if is_flex:
            q_text = f"```diff\n- {penalty_val} pts (Nerf Flex 15%)\n```"
            q_desc = "Fila Flex tem peso reduzido."
        else:
            q_text = f"```diff\n+ 100% (Solo/Duo)\n```"
            q_desc = "Fila Solo conta integralmente."
            
        embed.add_field(name="2️⃣ Ajuste de Fila", value=f"{q_text}{q_desc}", inline=True)
        
        embed.add_field(name="\u200b", value="\u200b", inline=False)

        sinal = "+" if bonus >= 0 else ""
        perf_explain = (
            f"**Jogos:** {total_games} ({phase})\n"
            f"**Winrate:** {winrate:.1f}% (Dif. da média: {wr_diff:.1f}%)\n"
            f"**Multiplicador:** {k_factor}x\n"
        )
        
        bonus_block = f"```diff\n{sinal} {bonus} pts de Ajuste\n```"
        embed.add_field(name="3️⃣ Desempenho (Velocity)", value=perf_explain + bonus_block, inline=False)

        formula_visual = (
            f"```ini\n"
            f"[ Base Ajustada ] [ Bônus WR ]  [ MMR FINAL ]\n"
            f" {base_adjusted:<5}  + {bonus:<5}  = {final}\n"
            f"```"
        )
        
        embed.add_field(name="🏁 Fórmula Aplicada", value=formula_visual, inline=False)
        embed.set_footer(text=f"Cálculo: (Elo Base x Peso Fila) + ((Winrate - 50) x Fator Jogos)")

        await ctx.reply(embed=embed)

    # --- COMANDO 4: HISTÓRICO (MANTIDO INTACTO) ---
    @commands.command(name="historico")
    async def historico(self, ctx, jogador: discord.Member = None):
        """Mostra as últimas 10 partidas em grade"""
        async with ctx.typing():
            target_user = jogador or ctx.author
            player = await PlayerRepository.get_player_by_discord_id(target_user.id)
            
            if not player:
                await ctx.reply("❌ Jogador não registrado.")
                return

            match_ids = await self.riot_service.get_match_ids(player.riot_puuid, count=10)
            if not match_ids:
                await ctx.reply("❌ Nenhuma partida recente encontrada ou erro na API.")
                return

            tasks = [self.riot_service.get_match_detail(mid) for mid in match_ids]
            matches_data = await asyncio.gather(*tasks)

            embed = discord.Embed(title=f"📜 Histórico (Últimas 10) - {player.riot_name}", color=0x3498db)
            
            # Filtra partidas inválidas (None)
            valid_matches = [m for m in matches_data if m] 
            
            for i, match in enumerate(valid_matches):
                info = match['info']
                participant = next((p for p in info['participants'] if p['puuid'] == player.riot_puuid), None)
                if not participant: continue

                win = participant['win']
                champ = participant['championName']
                kills = participant['kills']
                deaths = participant['deaths']
                assists = participant['assists']
                
                mode = self.get_queue_name(info['queueId'])
                ago = f"<t:{int(info['gameEndTimestamp']/1000)}:R>" 
                icon = "🟦" if win else "🟥"
                
                embed.add_field(
                    name=f"{icon} {champ}",
                    value=f"**{kills}/{deaths}/{assists}**\n{mode}\n{ago}",
                    inline=True
                )

                # Força 2 colunas (adiciona quebra a cada 2 itens)
                if (i + 1) % 2 == 0 and (i + 1) < len(valid_matches):
                    embed.add_field(name='\u200b', value='\u200b', inline=False)

            await ctx.reply(embed=embed)

    # --- COMANDO 5: LIVE (MANTIDO INTACTO) ---
    @commands.command(name="live")
    async def live(self, ctx, jogador: discord.Member = None):
        """Verifica se o jogador está em partida agora"""
        target_user = jogador or ctx.author
        player = await PlayerRepository.get_player_by_discord_id(target_user.id)
        
        if not player:
            await ctx.reply("❌ Jogador não registrado.")
            return

        # 1. Obter Summoner ID do PUUID
        summoner_data = await self.riot_service.get_summoner_by_puuid(player.riot_puuid)
        if not summoner_data:
            await ctx.reply("❌ Não foi possível obter os dados da conta Riot. Tente `.perfil`.")
            return
            
        summoner_id = summoner_data.get('id')
        
        # 2. Usar Summoner ID para buscar a partida ativa (Fluxo CORRETO)
        data = await self.riot_service.get_active_game(summoner_id)
        
        if not data:
            await ctx.reply(f"💤 **{player.riot_name}** não está jogando no momento.")
            return

        mode = self.get_queue_name(data['gameQueueConfigId'])
        start_time = data['gameStartTime']
        
        me = next((p for p in data['participants'] if p.get('puuid') == player.riot_puuid), None)
        
        champ_name = "Desconhecido"
        if me:
            champ_name = await self.riot_service.get_champion_name(me['championId'])

        if start_time == 0:
            duration = "Carregando..."
        else:
            duration = f"<t:{int(start_time/1000)}:R>"

        embed = discord.Embed(title="🔴 Partida Ao Vivo Encontrada!", color=0xe74c3c)
        embed.description = f"**{player.riot_name}** está jogando agora."
        
        embed.add_field(name="Campeão", value=f"**{champ_name}**", inline=True)
        embed.add_field(name="Modo", value=mode, inline=True)
        embed.add_field(name="Início", value=duration, inline=True)
        
        opgg_live = f"https://www.op.gg/summoners/br/{player.riot_name.replace('#', '-')}/ingame"
        embed.add_field(name="Links", value=f"[🎥 Assistir no OP.GG]({opgg_live})", inline=False)

        await ctx.reply(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Ranking(bot))