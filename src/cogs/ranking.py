import discord
import asyncio
from discord.ext import commands
from src.database.repositories import PlayerRepository
from src.services.riot_api import RiotAPI
from src.services.matchmaker import MatchMaker

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

    # --- COMANDO PERFIL (MANTIDO INTACTO) ---
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
                    
                    # Salva no Banco
                    await PlayerRepository.update_riot_rank(
                        discord_id=player.discord_id, 
                        tier=mmr_source['tier'], 
                        rank=mmr_source['rank'], 
                        lp=mmr_source['leaguePoints'],
                        wins=mmr_source['wins'],
                        losses=mmr_source['losses'],
                        calculated_mmr=new_mmr
                    )
                    
                    # Atualiza objeto local para o card mostrar o valor novo
                    player.mmr = new_mmr
                    player.solo_wins = mmr_source['wins']
                    player.solo_losses = mmr_source['losses']
                else:
                    # Se for Unranked total
                    await PlayerRepository.update_riot_rank(player.discord_id, "UNRANKED", "", 0, 0, 0, 1000)
                    player.mmr = 1000
                    
            except Exception as e:
                print(f"Erro API Riot: {e}")

            # --- DESIGN DO CARD (MANTIDO ORIGINAL) ---
            embed_color = 0x2b2d31 
            solo = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
            flex = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)

            if solo:
                tier_colors = {
                    'IRON': 0x564b49, 
                    'BRONZE': 0x8c5133, 
                    'SILVER': 0xc0c0c0, 
                    'GOLD': 0xffd700, 
                    'PLATINUM': 0x2ecc71, 
                    'EMERALD': 0x009475, 
                    'DIAMOND': 0x3498db, 
                    'MASTER': 0x9b59b6, 
                    'GRANDMASTER': 0xe74c3c, 
                    'CHALLENGER': 0xf1c40f
                }
                embed_color = tier_colors.get(solo['tier'], 0x2b2d31)

            embed = discord.Embed(color=embed_color)
            riot_link = f"[{player.riot_name}](https://www.op.gg/summoners/br/{player.riot_name.replace('#', '-')})"
            embed.set_author(name=f"{target_user.display_name} • Nível {summoner_level}", icon_url=target_user.display_avatar.url)
            
            if live_icon_id:
                embed.set_thumbnail(url=f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{live_icon_id}.png")

            main_lane = player.main_lane.value.capitalize() if player.main_lane else "N/A"
            sec_lane = player.secondary_lane.value.capitalize() if player.secondary_lane else "N/A"
            embed.description = f"🆔 **Conta:** {riot_link}\n🗺️ **Rotas:** {main_lane} / {sec_lane}"
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            def format_rank_detailed(data):
                if not data: return "```st\nUnranked\n```"
                wins = data['wins']
                losses = data['losses']
                total = wins + losses
                wr = (wins / total * 100) if total > 0 else 0
                return (f"{self.get_tier_emoji(data['tier'])} **{data['tier']} {data['rank']}**\n"
                        f"Info: `{data['leaguePoints']} PDL` • `{wr:.0f}% WR`\n"
                        f"Score: `{wins}V` - `{losses}D`")

            embed.add_field(name="🛡️ Solo/Duo", value=format_rank_detailed(solo), inline=True)
            embed.add_field(name="⚔️ Flex 5v5", value=format_rank_detailed(flex), inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            if top_mastery:
                m_list = []
                for i, c in enumerate(top_mastery):
                    name = await self.riot_service.get_champion_name(c['championId'])
                    points = int(c['championPoints'])
                    pts_str = f"{points/1000:.1f}k" if points > 1000 else str(points)
                    m_list.append(f"`#{i+1}` **{name}** (M{c['championLevel']}) • {pts_str}")
                embed.add_field(name="🔥 Top Maestrias", value="\n".join(m_list), inline=False)

            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)
            
            total_ih = player.wins + player.losses
            wr_ih = (player.wins / total_ih * 100) if total_ih > 0 else 0.0
            
            stats_block = (f"```yaml\nMMR:   {player.mmr}\nJogos: {total_ih}\nV/D:   {player.wins} - {player.losses}\nWin%:  {wr_ih:.1f}%\n```")
            embed.add_field(name="🏆 Liga Interna", value=stats_block, inline=False)
            embed.set_footer(text=f"System ID: {player.discord_id}")

            await ctx.reply(embed=embed)

    # --- COMANDO MMR (VISUAL ANALÍTICO DETALHADO) ---
    @commands.command(name="mmr")
    async def mmr(self, ctx, jogador: discord.Member = None):
        """Relatório detalhado da pontuação"""
        target_user = jogador or ctx.author
        player = await PlayerRepository.get_player_by_discord_id(target_user.id)
        if not player: return await ctx.reply("❌ Jogador não registrado.")

        # 1. Busca Dados Frescos
        riot_ranks = await self.riot_service.get_rank_by_puuid(player.riot_puuid)
        
        data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
        source_name = "Solo/Duo"
        is_flex = False
        
        if not data:
            data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)
            source_name = "Flex 5v5"
            is_flex = True
        
        if not data:
            await ctx.reply(f"🔍 **{player.riot_name}** é Unranked. MMR Base: 1000.")
            return

        # 2. Recálculo para Exibição (Passo a Passo)
        
        # Passo A: Valor do Elo
        tier_score = MatchMaker.TIER_VALUES.get(data['tier'], 1000)
        rank_score = MatchMaker.RANK_VALUES.get(data['rank'], 0)
        base_raw = tier_score + rank_score + data['leaguePoints']
        
        # Passo B: Penalidade de Fila
        queue_mod = 0.85 if is_flex else 1.0
        base_adjusted = int(base_raw * queue_mod)
        penalty_val = base_raw - base_adjusted # Quanto perdeu
        
        # Passo C: Desempenho (Winrate + Velocity)
        total_games = data['wins'] + data['losses']
        winrate = (data['wins'] / total_games * 100) if total_games > 0 else 0
        wr_diff = winrate - 50
        
        # Define o Fator K (Incerteza)
        if total_games < 50:   k_factor = 20; phase = "Calibração (Smurf?)"
        elif total_games < 100: k_factor = 12; phase = "Subida Rápida"
        elif total_games < 150: k_factor = 8;  phase = "Estabilizando"
        elif total_games < 200: k_factor = 4;  phase = "Consolidação"
        else:                   k_factor = 2;  phase = "Elo Definido"
        
        bonus = int(wr_diff * k_factor)
        
        # Resultado Final
        final = int(base_adjusted + bonus)
        final = max(0, final)

        # --- MONTAGEM DO EMBED ---
        embed = discord.Embed(title=f"🧮 Extrato de MMR: {player.riot_name}", color=0x2b2d31)
        
        # 1. O Elo Bruto
        embed.add_field(
            name="1️⃣ Elo Oficial",
            value=f"**{data['tier']} {data['rank']}** ({data['leaguePoints']} PDL)\nValor Bruto: `{base_raw}` pontos",
            inline=True
        )

        # 2. Ajuste da Fila (Visual diff para mostrar perda se houver)
        if is_flex:
            q_text = f"```diff\n- {penalty_val} pts (Nerf Flex 15%)\n```"
            q_desc = "Fila Flex tem peso reduzido."
        else:
            q_text = f"```diff\n+ 100% (Solo/Duo)\n```"
            q_desc = "Fila Solo conta integralmente."
            
        embed.add_field(name="2️⃣ Ajuste de Fila", value=f"{q_text}{q_desc}", inline=True)

        # Separador
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

        # 3. Análise de Desempenho
        # Formata sinal de + ou -
        sinal = "+" if bonus >= 0 else ""
        
        perf_explain = (
            f"**Jogos:** {total_games} ({phase})\n"
            f"**Winrate:** {winrate:.1f}% (Dif. da média: {wr_diff:.1f}%)\n"
            f"**Multiplicador:** {k_factor}x\n"
        )
        
        # Caixa de código para o bônus ficar destacado
        bonus_block = f"```diff\n{sinal} {bonus} pts de Ajuste\n```"
        
        embed.add_field(name="3️⃣ Desempenho (Velocity)", value=perf_explain + bonus_block, inline=False)

        # 4. A FÓRMULA FINAL (O que você pediu)
        # Mostra a matemática exata com os números do usuário
        
        formula_visual = (
            f"```ini\n"
            f"[ Base Ajustada ]   [ Bônus WR ]     [ MMR FINAL ]\n"
            f"    {base_adjusted:<5}       +    {bonus:<5}      =    {final}\n"
            f"```"
        )
        
        embed.add_field(name="🏁 Fórmula Aplicada", value=formula_visual, inline=False)
        
        # Rodapé explicativo
        embed.set_footer(text=f"Cálculo: (Elo Base x Peso Fila) + ((Winrate - 50) x Fator Jogos)")

        await ctx.reply(embed=embed)

    # --- COMANDO HISTÓRICO (MANTIDO 10 JOGOS / COLUNAS) ---
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

    # --- COMANDO LIVE (MANTIDO) ---
    @commands.command(name="live")
    async def live(self, ctx, jogador: discord.Member = None):
        """Verifica se o jogador está em partida agora"""
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