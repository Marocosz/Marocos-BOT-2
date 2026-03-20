import discord
import asyncio
import urllib.parse
from discord.ext import commands
from src.database.repositories import PlayerRepository, MatchRepository
from src.services.riot_api import RiotAPI
from src.services.matchmaker import MatchMaker
from src.utils.views import BaseInteractiveView


# --- VIEW DE PAGINAÇÃO ---
class RankingPaginationView(BaseInteractiveView):
    def __init__(self, players, ctx, per_page=10):
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
            rank_pos = start + i + 1
            if rank_pos == 1: icon = "🥇"
            elif rank_pos == 2: icon = "🥈"
            elif rank_pos == 3: icon = "🥉"
            else: icon = f"`{rank_pos}.`"

            total = p.wins + p.losses
            wr = (p.wins / total * 100) if total > 0 else 0

            streak_str = ""
            streak = getattr(p, 'current_win_streak', 0) or 0
            if streak >= 3:
                streak_str = f" 🔥{streak}"

            lista_fmt += (
                f"{icon} **{p.riot_name}**{streak_str}\n"
                f"└ `{p.wins}V` - `{p.losses}D` ({wr:.0f}%) • **{p.mmr}** MMR\n"
            )

        if not batch:
            lista_fmt = "Nenhum jogador nesta página."

        embed.add_field(name="Jogadores", value=lista_fmt, inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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


class HistoryPaginationView(BaseInteractiveView):
    PER_PAGE = 10

    def __init__(self, history: list, player_name: str, ctx):
        super().__init__(timeout=120)
        self.history = history
        self.player_name = player_name
        self.ctx = ctx
        self.current_page = 0
        self.total_pages = max(1, (len(history) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.total_wins = sum(1 for h in history if h['won'] is True)
        self.total_losses = sum(1 for h in history if h['won'] is False)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page == self.total_pages - 1)
        self.counter_button.label = f"{self.current_page + 1}/{self.total_pages}"
        if self.total_pages == 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True

    def create_embed(self):
        total = len(self.history)
        wr = (self.total_wins / total * 100) if total > 0 else 0

        embed = discord.Embed(
            title=f"📜 Histórico Interno — {self.player_name}",
            color=0x3498db
        )
        embed.description = (
            f"**{total}** partida(s) registradas\n"
            f"`{self.total_wins}V` `{self.total_losses}D` • **{wr:.0f}%** WR"
        )

        start = self.current_page * self.PER_PAGE
        batch = self.history[start:start + self.PER_PAGE]

        lines = []
        for h in batch:
            if h['won'] is True:
                result_icon, result_label = "🟦", "Vitória"
            elif h['won'] is False:
                result_icon, result_label = "🟥", "Derrota"
            else:
                result_icon, result_label = "⬜", "N/A"

            side_str = f"· {h['side'].capitalize()}" if h['side'] else ""
            ts = f"<t:{int(h['finished_at'].timestamp())}:R>" if h.get('finished_at') else "N/A"
            lines.append(f"{result_icon} **#{h['match_id']}** — {result_label} {side_str}\n└ {ts}")

        embed.add_field(name="\u200b", value="\n".join(lines), inline=False)
        embed.set_footer(text="Use .partida <ID> para detalhes · 10 por página")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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
        queues = {420: "Solo/Duo", 440: "Flex 5v5", 450: "ARAM", 490: "Quickplay", 1700: "Arena", 1900: "URF"}
        return queues.get(queue_id, "Normal")

    # --- RANKING ---
    @commands.command(name="ranking", aliases=["top", "leaderboard"])
    async def ranking(self, ctx):
        players = await PlayerRepository.get_internal_ranking(limit=None)

        if not players:
            embed = discord.Embed(title="🏆 Ranking da Liga Interna", color=0x3498db)
            embed.description = "Nenhuma partida foi jogada ainda."
            await ctx.reply(embed=embed)
            return

        view = RankingPaginationView(players, ctx=ctx, per_page=10)
        sent_message = await ctx.reply(embed=view.create_embed(), view=view)
        view.message = sent_message

    # --- PERFIL ---
    @commands.command(name="perfil")
    async def perfil(self, ctx, jogador: discord.Member = None):
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
                summoner_data = await self.riot_service.get_summoner_by_puuid(player.riot_puuid)
                if summoner_data:
                    summoner_level = summoner_data.get('summonerLevel', 'N/A')
                    live_icon_id = summoner_data.get('profileIconId')

                riot_ranks = await self.riot_service.get_rank_by_puuid(player.riot_puuid)
                top_mastery = await self.riot_service.get_top_mastery(player.riot_puuid)

                mmr_source = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
                if not mmr_source:
                    mmr_source = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)

                if mmr_source:
                    new_mmr = MatchMaker.calculate_adjusted_mmr(
                        tier=mmr_source['tier'],
                        rank=mmr_source['rank'],
                        lp=mmr_source['leaguePoints'],
                        wins=mmr_source['wins'],
                        losses=mmr_source['losses'],
                        queue_type=mmr_source['queueType']
                    )

                    if solo_rank_data := next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None):
                        await PlayerRepository.update_riot_rank(
                            discord_id=player.discord_id,
                            tier=solo_rank_data['tier'],
                            rank=solo_rank_data['rank'],
                            lp=solo_rank_data['leaguePoints'],
                            wins=solo_rank_data['wins'],
                            losses=solo_rank_data['losses'],
                            calculated_mmr=new_mmr,
                            queue_type='RANKED_SOLO_5x5'
                        )

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

                player = await PlayerRepository.get_player_by_discord_id(target_user.id)

            except Exception as e:
                print(f"Erro API Riot durante perfil/update: {e}")

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

            url_friendly_name = player.riot_name.replace(' ', '-').replace('#', '-')
            riot_link = f"[{player.riot_name}](https://www.op.gg/summoners/br/{url_friendly_name})"

            embed.set_author(name=f"{target_user.display_name} • Nível {summoner_level}", icon_url=target_user.display_avatar.url)
            if live_icon_id:
                embed.set_thumbnail(url=f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{live_icon_id}.png")

            main_lane = player.main_lane.value.capitalize() if player.main_lane else "N/A"
            sec_lane = player.secondary_lane.value.capitalize() if player.secondary_lane else "N/A"

            streak = getattr(player, 'current_win_streak', 0) or 0
            best_streak = getattr(player, 'best_win_streak', 0) or 0

            embed.description = f"🆔 **Conta:** {riot_link}\n🗺️ **Rotas:** {main_lane} / {sec_lane}"
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            def format_rank_detailed(data):
                if data['tier'] == "UNRANKED": return "```st\nUnranked\n```"
                wins, losses = data['wins'], data['losses']
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

            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            total_ih = player.wins + player.losses
            wr_ih = (player.wins / total_ih * 100) if total_ih > 0 else 0.0

            mvp_count = getattr(player, 'mvp_count', 0) or 0
            imvp_count = getattr(player, 'imvp_count', 0) or 0

            stats_block = (
                f"```yaml\n"
                f"MMR:   {player.mmr}\n"
                f"Jogos: {total_ih}\n"
                f"V/D:   {player.wins} - {player.losses}\n"
                f"Win%:  {wr_ih:.1f}%\n"
                f"```"
            )
            embed.add_field(name="🏆 Liga Interna", value=stats_block, inline=True)

            awards_lines = []
            if mvp_count > 0:
                awards_lines.append(f"⭐ MVP — **{mvp_count}x**")
            if imvp_count > 0:
                awards_lines.append(f"💀 iMVP — **{imvp_count}x**")
            if streak >= 3:
                awards_lines.append(f"🔥 Sequência — **{streak} seguidas**")
            if best_streak > 0:
                awards_lines.append(f"🏅 Recorde — **{best_streak} seguidas**")

            if awards_lines:
                embed.add_field(name="🎖️ Conquistas", value="\n".join(awards_lines), inline=True)
            else:
                embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.set_footer(text=f"System ID: {player.discord_id}")

            await ctx.reply(embed=embed)

    # --- MMR ---
    @commands.command(name="mmr")
    async def mmr(self, ctx, jogador: discord.Member = None):
        target_user = jogador or ctx.author
        player = await PlayerRepository.get_player_by_discord_id(target_user.id)
        if not player: return await ctx.reply("❌ Jogador não registrado.")

        riot_ranks = await self.riot_service.get_rank_by_puuid(player.riot_puuid)

        data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
        is_flex = False

        if not data:
            data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)
            is_flex = True

        if not data:
            await ctx.reply(f"🔍 **{player.riot_name}** é Unranked. MMR Base: 1000.")
            return

        tier_score = MatchMaker.TIER_VALUES.get(data['tier'], 1000)
        rank_score = MatchMaker.RANK_VALUES.get(data['rank'], 0)
        base_raw = tier_score + rank_score + data['leaguePoints']

        queue_mod = 0.85 if is_flex else 1.0
        base_adjusted = int(base_raw * queue_mod)
        penalty_val = base_raw - base_adjusted

        total_games = data['wins'] + data['losses']
        winrate = (data['wins'] / total_games * 100) if total_games > 0 else 0
        wr_diff = winrate - 50

        if total_games < 50: k_factor, phase = 20, "Calibração (Smurf?)"
        elif total_games < 100: k_factor, phase = 12, "Subida Rápida"
        elif total_games < 150: k_factor, phase = 8, "Estabilizando"
        elif total_games < 200: k_factor, phase = 4, "Consolidação"
        else: k_factor, phase = 2, "Elo Definido"

        bonus = int(wr_diff * k_factor)
        final = max(0, int(base_adjusted + bonus))

        queue_type_str = 'RANKED_FLEX_SR' if is_flex else 'RANKED_SOLO_5x5'
        await PlayerRepository.update_riot_rank(
            discord_id=player.discord_id,
            tier=data['tier'], rank=data['rank'], lp=data['leaguePoints'],
            wins=data['wins'], losses=data['losses'],
            calculated_mmr=final, queue_type=queue_type_str
        )

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
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

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
            f"[ Base Ajustada ]  [ Bônus WR ]   [ MMR FINAL ]\n"
            f"  {base_adjusted:<5}    +  {bonus:<5}   =  {final}\n"
            f"```"
        )
        embed.add_field(name="🏁 Fórmula Aplicada", value=formula_visual, inline=False)
        embed.set_footer(text="Cálculo: (Elo Base x Peso Fila) + ((Winrate - 50) x Fator Jogos)")
        await ctx.reply(embed=embed)

    # --- HISTÓRICO RIOT ---
    @commands.command(name="historico")
    async def historico(self, ctx, jogador: discord.Member = None):
        async with ctx.typing():
            target_user = jogador or ctx.author
            player = await PlayerRepository.get_player_by_discord_id(target_user.id)
            if not player:
                await ctx.reply("❌ Jogador não registrado.")
                return

            match_ids = await self.riot_service.get_match_ids(player.riot_puuid, count=10)
            if not match_ids:
                await ctx.reply("❌ Nenhuma partida recente encontrada.")
                return

            tasks = [self.riot_service.get_match_detail(mid) for mid in match_ids]
            matches_data = await asyncio.gather(*tasks)

            embed = discord.Embed(title=f"📜 Histórico (Últimas 10) - {player.riot_name}", color=0x3498db)
            valid_matches = [m for m in matches_data if m]

            for i, match in enumerate(valid_matches):
                info = match['info']
                participant = next((p for p in info['participants'] if p['puuid'] == player.riot_puuid), None)
                if not participant: continue

                win = participant['win']
                champ = participant['championName']
                kills, deaths, assists = participant['kills'], participant['deaths'], participant['assists']
                mode = self.get_queue_name(info['queueId'])
                ago = f"<t:{int(info['gameEndTimestamp']/1000)}:R>"
                icon = "🟦" if win else "🟥"

                embed.add_field(
                    name=f"{icon} {champ}",
                    value=f"**{kills}/{deaths}/{assists}**\n{mode}\n{ago}",
                    inline=True
                )
                if (i + 1) % 2 == 0 and (i + 1) < len(valid_matches):
                    embed.add_field(name='\u200b', value='\u200b', inline=False)

            await ctx.reply(embed=embed)

    # --- LIVE ---
    @commands.command(name="live")
    async def live(self, ctx, jogador: discord.Member = None):
        target_user = jogador or ctx.author
        player = await PlayerRepository.get_player_by_discord_id(target_user.id)
        if not player:
            await ctx.reply("❌ Jogador não registrado.")
            return

        data = await self.riot_service.get_active_game(player.riot_puuid)
        if not data:
            await ctx.reply(f"💤 **{player.riot_name}** não está jogando no momento.")
            return

        mode = self.get_queue_name(data['gameQueueConfigId'])
        start_time = data['gameStartTime']
        me = next((p for p in data['participants'] if p.get('puuid') == player.riot_puuid), None)
        champ_name = "Desconhecido"
        if me:
            champ_name = await self.riot_service.get_champion_name(me['championId'])

        duration = f"<t:{int(start_time/1000)}:R>" if start_time != 0 else "Carregando..."

        embed = discord.Embed(title="🔴 Partida Ao Vivo Encontrada!", color=0xe74c3c)
        embed.description = f"**{player.riot_name}** está jogando agora."
        embed.add_field(name="Campeão", value=f"**{champ_name}**", inline=True)
        embed.add_field(name="Modo", value=mode, inline=True)
        embed.add_field(name="Início", value=duration, inline=True)

        formatted_name = player.riot_name.replace('#', '-')
        safe_url = urllib.parse.quote(formatted_name)
        opgg_live = f"https://www.op.gg/summoners/br/{safe_url}/ingame"
        embed.add_field(name="Links", value=f"[🎥 Assistir no OP.GG]({opgg_live})", inline=False)
        await ctx.reply(embed=embed)

    # --- DETALHES DE UMA PARTIDA INTERNA ---
    @commands.command(name="partida")
    async def partida(self, ctx, match_id: int = None):
        """Exibe os detalhes completos de uma partida interna pelo ID."""
        if not match_id:
            return await ctx.reply("❌ Uso: `.partida <ID>`")

        match = await MatchRepository.get_match_by_id(match_id)
        if not match:
            return await ctx.reply(f"❌ Partida #{match_id} não encontrada.")

        status_map = {
            'live': ('🟡 Em andamento', 0xffd700),
            'finished': ('✅ Finalizada', 0x2ecc71),
            'cancelled': ('🚫 Anulada', 0xe74c3c),
            'open': ('🔵 Aberta', 0x3498db),
        }
        status_label, color = status_map.get(match['status'], ('❓ Desconhecido', 0x2b2d31))

        embed = discord.Embed(title=f"⚔️ Partida #{match_id}", color=color)

        created_ts = f"<t:{int(match['created_at'].timestamp())}:F>" if match.get('created_at') else "N/A"
        finished_ts = f"<t:{int(match['finished_at'].timestamp())}:R>" if match.get('finished_at') else "—"

        embed.description = (
            f"{status_label}\n"
            f"🕐 **Criada:** {created_ts}\n"
            f"🏁 **Encerrada:** {finished_ts}"
        )

        if match['winning_side']:
            winner_emoji = "🔵" if match['winning_side'] == 'blue' else "🔴"
            winner_name = "BLUE" if match['winning_side'] == 'blue' else "RED"
            embed.description += f"\n\n🏆 **Vencedor:** {winner_emoji} Time **{winner_name}**"

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        def fmt_team(team):
            if not team:
                return "Nenhum jogador registrado."
            lines = []
            for p in team:
                mmr_str = f"({p['mmr_before']} MMR)" if p.get('mmr_before') else f"({p['mmr']} MMR)"
                lines.append(f"• **{p['name']}** — `{mmr_str}`")
            real_players = [p for p in team if p.get('mmr_before') or p.get('mmr')]
            mmrs = [p.get('mmr_before') or p.get('mmr', 0) for p in real_players]
            avg = sum(mmrs) // len(mmrs) if mmrs else 0
            lines.append(f"─────────────\n📊 Média: **{avg} MMR**")
            return "\n".join(lines)

        embed.add_field(name="🔵 Time Azul", value=fmt_team(match['blue_team']), inline=True)
        embed.add_field(name="🔴 Time Vermelho", value=fmt_team(match['red_team']), inline=True)
        embed.set_footer(text=f"Use .resultado {match_id} Blue/Red para registrar o resultado")

        await ctx.reply(embed=embed)

    # --- HISTÓRICO INTERNO DA LIGA ---
    @commands.command(name="historico_liga", aliases=["hliga", "liga_historico"])
    async def historico_liga(self, ctx, jogador: discord.Member = None):
        """Exibe o histórico de partidas internas do jogador."""
        target_user = jogador or ctx.author

        player = await PlayerRepository.get_player_by_discord_id(target_user.id)
        if not player:
            return await ctx.reply(f"❌ {target_user.mention} não está registrado.")

        history = await MatchRepository.get_player_internal_history(player.discord_id)
        if not history:
            return await ctx.reply(f"📭 **{player.riot_name}** ainda não jogou nenhuma partida na Liga.")

        view = HistoryPaginationView(history, player.riot_name, ctx)
        msg = await ctx.reply(embed=view.create_embed(), view=view)
        view.message = msg

    # --- CONFRONTO DIRETO (H2H) ---
    @commands.command(name="h2h")
    async def h2h(self, ctx, jogador1: discord.Member = None, jogador2: discord.Member = None):
        """Estatísticas de confronto direto entre dois jogadores da Liga."""
        if not jogador1 or not jogador2:
            return await ctx.reply("❌ Uso: `.h2h @jogador1 @jogador2`")

        if jogador1.id == jogador2.id:
            return await ctx.reply("❌ Selecione dois jogadores diferentes.")

        p1 = await PlayerRepository.get_player_by_discord_id(jogador1.id)
        p2 = await PlayerRepository.get_player_by_discord_id(jogador2.id)

        if not p1:
            return await ctx.reply(f"❌ {jogador1.mention} não está registrado.")
        if not p2:
            return await ctx.reply(f"❌ {jogador2.mention} não está registrado.")

        async with ctx.typing():
            data = await MatchRepository.get_h2h_data(p1.discord_id, p2.discord_id)

        if data['total'] == 0:
            return await ctx.reply(f"📭 **{p1.riot_name}** e **{p2.riot_name}** ainda não jogaram nenhuma partida juntos na Liga.")

        embed = discord.Embed(
            title=f"⚔️ H2H — {p1.riot_name} vs {p2.riot_name}",
            color=0x9b59b6
        )

        embed.description = (
            f"**{data['total']}** partida(s) em comum na Liga\n"
            f"Adversários: **{data['as_opponents']}** · Parceiros: **{data['as_teammates']}**"
        )

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        # Como adversários
        if data['as_opponents'] > 0:
            p1_wr = (data['p1_wins'] / data['as_opponents'] * 100) if data['as_opponents'] > 0 else 0
            p2_wr = (data['p2_wins'] / data['as_opponents'] * 100) if data['as_opponents'] > 0 else 0

            if data['p1_wins'] > data['p2_wins']:
                leader = f"🏆 **{p1.riot_name}** lidera o confronto!"
            elif data['p2_wins'] > data['p1_wins']:
                leader = f"🏆 **{p2.riot_name}** lidera o confronto!"
            else:
                leader = "🤝 **Empate** no confronto direto!"

            vs_block = (
                f"```yaml\n"
                f"{p1.riot_name:<20} {data['p1_wins']}V ({p1_wr:.0f}%)\n"
                f"{p2.riot_name:<20} {data['p2_wins']}V ({p2_wr:.0f}%)\n"
                f"```"
                f"{leader}"
            )

            embed.add_field(
                name=f"⚔️ Como Adversários ({data['as_opponents']} jogo(s))",
                value=vs_block,
                inline=False
            )

        # Como aliados
        if data['as_teammates'] > 0:
            duo_total = data['together_wins'] + data['together_losses']
            duo_wr = (data['together_wins'] / duo_total * 100) if duo_total > 0 else 0
            embed.add_field(
                name=f"🤝 Como Parceiros ({data['as_teammates']} jogo(s))",
                value=f"`{data['together_wins']}V` `{data['together_losses']}D` — **{duo_wr:.0f}%** WR juntos",
                inline=False
            )

        # Últimas partidas em comum
        recent = data['matches'][:5]
        if recent:
            lines = []
            for m in recent:
                if m['same_team']:
                    tag = "🤝 Aliados"
                    result = "✅ Ganharam" if m['p1_won'] else "❌ Perderam"
                else:
                    if m['p1_won']:
                        tag = f"⚔️ {p1.riot_name} venceu"
                    elif m['p2_won']:
                        tag = f"⚔️ {p2.riot_name} venceu"
                    else:
                        tag = "⚔️ Adversários"
                    result = ""

                ts = f"<t:{int(m['finished_at'].timestamp())}:R>" if m.get('finished_at') else ""
                lines.append(f"`#{m['match_id']}` {tag} {result} {ts}")

            embed.add_field(
                name="📋 Últimas Partidas em Comum",
                value="\n".join(lines),
                inline=False
            )

        embed.set_footer(text=f"Total de {data['total']} partida(s) em comum")
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ranking(bot))
