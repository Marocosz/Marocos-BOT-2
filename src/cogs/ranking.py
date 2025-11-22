import discord
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

    @commands.command(name="perfil")
    async def perfil(self, ctx, jogador: discord.Member = None):
        """
        Exibe o cartão do jogador.
        Uso: .perfil
        """
        async with ctx.typing():
            target_user = jogador or ctx.author
            
            player = await PlayerRepository.get_player_by_discord_id(target_user.id)
            if not player:
                await ctx.reply(f"❌ {target_user.mention} não está registrado. Use `.registrar`.")
                return

            riot_ranks = []
            top_mastery = []
            summoner_level = "N/A"
            # Variável para guardar o ícone ao vivo
            live_icon_id = player.riot_icon_id 

            try:
                # 1. Busca Dados Basicos (Level e Icone ATUAL)
                summoner_data = await self.riot_service.get_summoner_by_puuid(player.riot_puuid)
                if summoner_data:
                    summoner_level = summoner_data.get('summonerLevel', 'N/A')
                    live_icon_id = summoner_data.get('profileIconId') # <--- PEGA O NOVO AQUI

                # 2. Busca Rank e Maestria
                riot_ranks = await self.riot_service.get_rank_by_puuid(player.riot_puuid)
                top_mastery = await self.riot_service.get_top_mastery(player.riot_puuid)
                    
            except Exception as e:
                print(f"Erro API Riot: {e}")

            # --- DESIGN ---
            embed_color = 0x2b2d31 
            solo = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
            flex = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)

            if solo:
                tier_colors = {
                    'IRON': 0x564b49, 'BRONZE': 0x8c5133, 'SILVER': 0xc0c0c0, 'GOLD': 0xffd700, 
                    'PLATINUM': 0x2ecc71, 'EMERALD': 0x009475, 'DIAMOND': 0x3498db, 
                    'MASTER': 0x9b59b6, 'GRANDMASTER': 0xe74c3c, 'CHALLENGER': 0xf1c40f
                }
                embed_color = tier_colors.get(solo['tier'], 0x2b2d31)

            embed = discord.Embed(color=embed_color)
            riot_link = f"[{player.riot_name}](https://www.op.gg/summoners/br/{player.riot_name.replace('#', '-')})"
            embed.set_author(name=f"{target_user.display_name} • Nível {summoner_level}", icon_url=target_user.display_avatar.url)
            
            # Usa o live_icon_id em vez do player.riot_icon_id
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

            embed.add_field(name="\u200b", value="\u200b", inline=False)
           
            total_ih = player.wins + player.losses
            wr_ih = (player.wins / total_ih * 100) if total_ih > 0 else 0.0
            
            stats_block = (f"```yaml\nMMR:   {player.mmr}\nJogos: {total_ih}\nV/D:   {player.wins} - {player.losses}\nWin%:  {wr_ih:.1f}%\n```")
            embed.add_field(name="🏆 Liga Interna", value=stats_block, inline=False)
            embed.set_footer(text=f"System ID: {player.discord_id}")

            await ctx.reply(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Ranking(bot))