import discord
from discord.ext import commands
from src.services.riot_api import RiotAPI
import difflib

class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()
        self.champions_cache = {} 

    async def _load_champions(self):
        if not self.champions_cache:
            data = await self.riot_service.get_all_champions_data()
            if data:
                for key, info in data['data'].items():
                    self.champions_cache[info['name'].lower()] = key
                    self.champions_cache[key.lower()] = key

    def find_champion_key(self, search: str):
        search = search.lower().replace(" ", "").replace("'", "")
        if search in self.champions_cache:
            return self.champions_cache[search]
        matches = difflib.get_close_matches(search, self.champions_cache.keys(), n=1, cutoff=0.6)
        if matches:
            return self.champions_cache[matches[0]]
        return None

    # Helper para limpar lanes
    def normalize_lane(self, lane: str):
        l = lane.lower().strip()
        if l in ['top', 'topo']: return 'top_lane', 'Top Lane'
        if l in ['jungle', 'jg', 'selva']: return 'jungle', 'Jungle'
        if l in ['mid', 'meio']: return 'mid_lane', 'Mid Lane'
        if l in ['adc', 'bot', 'bottom']: return 'adc', 'ADC'
        if l in ['sup', 'support', 'suporte']: return 'support', 'Support'
        return None, None

    @commands.command(name="meta")
    async def meta(self, ctx, lane: str = None):
        """
        Mostra onde encontrar os melhores campeões do patch atual por rota.
        Uso: .meta jg
        """
        if not lane:
            await ctx.reply("❌ Informe a rota. Ex: `.meta jg`, `.meta mid`, `.meta adc`")
            return

        slug, pretty_name = self.normalize_lane(lane)
        
        if not slug:
            await ctx.reply("❌ Rota inválida. Use: Top, Jg, Mid, Adc ou Sup.")
            return

        # Gera links profundos (Deep Links) já filtrados
        slug_ugg = "jungle" if slug == "jungle" else slug.replace("_lane", "") # u.gg usa 'top', 'mid'
        slug_opgg = "jungle" if slug == "jungle" else slug.replace("_lane", "")

        ugg_url = f"https://u.gg/lol/jungle-tier-list" if slug == 'jungle' else f"https://u.gg/lol/{slug_ugg}-tier-list"
        opgg_url = f"https://www.op.gg/champions?position={slug_opgg}"
        lolalytics_url = f"https://lolalytics.com/lol/tierlist/?lane={slug_opgg}"

        embed = discord.Embed(
            title=f"🏆 Meta Report: {pretty_name}", 
            description=f"Confira os campeões com maior Winrate no **Patch {self.riot_service.ddragon_version}**:",
            color=0xff00ff
        )
        
        links = (
            f"🦅 [**U.GG** (Tier List {pretty_name})]({ugg_url})\n"
            f"🔵 [**OP.GG** (Estatísticas)]({opgg_url})\n"
            f"📊 [**Lolalytics** (Análise Profunda)]({lolalytics_url})"
        )
        
        embed.add_field(name="Fontes Confiáveis", value=links, inline=False)
        embed.set_footer(text="Dados baseados em Platina+ Mundial")

        await ctx.reply(embed=embed)

    @commands.command(name="build")
    async def build(self, ctx, *, campeao: str = None):
        if not campeao:
            await ctx.reply("❌ Digite o nome do campeão. Ex: `.build yasuo`")
            return

        await self._load_champions()
        key = self.find_champion_key(campeao)

        if not key:
            await ctx.reply(f"❌ Campeão **{campeao}** não encontrado.")
            return

        data = await self.riot_service.get_champion_detail(key)
        if not data:
            await ctx.reply("❌ Erro ao baixar dados.")
            return

        title = f"{data['name']} - {data['title'].title()}"
        desc = data.get('lore', '')[:250] + "..."
        version = self.riot_service.ddragon_version
        
        embed = discord.Embed(title=title, description=desc, color=0xf1c40f)
        embed.set_thumbnail(url=f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{key}.png")

        spells_text = f"**P** - {data['passive']['name']}\n"
        keys_btn = ['Q', 'W', 'E', 'R']
        for i, spell in enumerate(data['spells']):
            spells_text += f"**{keys_btn[i]}** - {spell['name']}\n"
        embed.add_field(name="✨ Skills", value=spells_text, inline=True)

        # Links de Build
        ugg_url = f"https://u.gg/lol/champions/{key.lower()}/build"
        opgg_url = f"https://www.op.gg/champions/{key.lower()}/build"
        
        links = f"[🦅 U.GG]({ugg_url}) | [🔵 OP.GG]({opgg_url})"
        embed.add_field(name="🛠️ Builds & Runas", value=links, inline=False)
        
        embed.set_image(url=f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key}_0.jpg")
        await ctx.reply(embed=embed)

    @commands.command(name="patch")
    async def patch(self, ctx):
        """Mostra a versão atual e link CORRIGIDO"""
        await self.riot_service.update_version()
        v = self.riot_service.ddragon_version # Ex: 15.23.1
        
        # Lógica de Link Inteligente
        # Pega só os dois primeiros números (15.23) e troca ponto por traço
        version_parts = v.split(".")
        major_minor = f"{version_parts[0]}-{version_parts[1]}" # 15-23
        
        # Tenta o link padrão brasileiro
        link_br = f"https://www.leagueoflegends.com/pt-br/news/game-updates/patch-{major_minor}-notes/"
        # Link genérico de notícias caso o específico falhe
        link_news = "https://www.leagueoflegends.com/pt-br/news/game-updates/"

        embed = discord.Embed(title=f"⚙️ Patch {v}", color=0xe67e22)
        embed.description = (
            f"O servidor está rodando na versão **{v}**.\n\n"
            f"📄 [Ler Notas do Patch {major_minor}]({link_br})\n"
            f"🔗 [Ver Todas as Notícias]({link_news})"
        )
        embed.set_footer(text="Se o link 1 der 404, use o link 2 (A Riot muda urls as vezes).")
        
        await ctx.reply(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))