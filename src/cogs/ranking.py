import discord
import asyncio
from discord.ext import commands
from src.database.repositories import PlayerRepository
from src.services.riot_api import RiotAPI

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
        """Exibe o cartão de jogador COMPLETO."""
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
                
                solo = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
                flex = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)
                if solo:
                    await PlayerRepository.update_riot_rank(player.discord_id, solo['tier'], solo['rank'], solo['leaguePoints'])
                else:
                    await PlayerRepository.update_riot_rank(player.discord_id, "UNRANKED", "", 0)
                    
            except Exception as e:
                print(f"Erro API Riot: {e}")

            embed = discord.Embed(color=0x2b2d31)
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
                wins = data['wins']; losses = data['losses']; total = wins+losses; wr = (wins/total*100) if total>0 else 0
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

    # --- COMANDO HISTÓRICO (AJUSTADO: 2 COLUNAS REAIS + DETALHES) ---
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
            
            # Contador para controlar a grade
            valid_matches = [m for m in matches_data if m] # Filtra erros
            
            for i, match in enumerate(valid_matches):
                info = match['info']
                participant = next((p for p in info['participants'] if p['puuid'] == player.riot_puuid), None)
                if not participant: continue

                win = participant['win']
                champ = participant['championName']
                kills = participant['kills']
                deaths = participant['deaths']
                assists = participant['assists']
                
                # Modo Específico (Solo/Duo, Flex, ARAM)
                mode = self.get_queue_name(info['queueId'])
                
                ago = f"<t:{int(info['gameEndTimestamp']/1000)}:R>" 

                icon = "🟦" if win else "🟥"
                
                # Adiciona o campo (inline=True permite ficar lado a lado)
                embed.add_field(
                    name=f"{icon} {champ}",
                    value=f"**{kills}/{deaths}/{assists}**\n{mode}\n{ago}",
                    inline=True
                )

                # TRUQUE PARA FORÇAR 2 COLUNAS:
                # Se o índice for ímpar (significa que já tem 2 itens na linha: 0 e 1),
                # adicionamos um campo invisível que ocupa a linha inteira (inline=False),
                # forçando a próxima entrada para a linha de baixo.
                if (i + 1) % 2 == 0 and (i + 1) < len(valid_matches):
                    embed.add_field(name='\u200b', value='\u200b', inline=False)

            await ctx.reply(embed=embed)

    # --- COMANDO LIVE (MANTIDO INTACTO) ---
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