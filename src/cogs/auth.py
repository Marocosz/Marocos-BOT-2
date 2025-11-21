import discord
import random
from discord.ext import commands
from src.services.riot_api import RiotAPI
from src.database.repositories import PlayerRepository

# View do Botão (Continua igual, pois botões são ótimos para segurança)
class VerifyView(discord.ui.View):
    def __init__(self, bot, ctx, riot_service, puuid, target_icon_id, account_data, lanes):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx # Contexto do comando de texto
        self.riot_service = riot_service
        self.puuid = puuid
        self.target_icon_id = target_icon_id
        self.account_data = account_data
        self.lanes = lanes

    @discord.ui.button(label="Já troquei! Verificar", style=discord.ButtonStyle.green)
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Ei, saia daqui! Use .registrar para fazer o seu.", ephemeral=True)
            return

        await interaction.response.defer() # Carregando...

        try:
            summoner_data = await self.riot_service.get_summoner_by_puuid(self.puuid)
            current_icon = summoner_data.get('profileIconId')

            if current_icon == self.target_icon_id:
                full_data = {**self.account_data, 'profileIconId': current_icon}
                
                await PlayerRepository.upsert_player(
                    discord_id=self.ctx.author.id,
                    riot_data=full_data,
                    lane_main=self.lanes['main'],
                    lane_sec=self.lanes['sec']
                )

                embed = discord.Embed(title="✅ Identidade Confirmada!", color=0x00ff00)
                embed.description = f"Conta **{self.account_data['gameName']}** vinculada com sucesso."
                embed.set_thumbnail(url=f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{current_icon}.png")
                
                self.clear_items()
                await interaction.edit_original_response(embed=embed, view=self)
                self.stop()
            else:
                await interaction.followup.send(
                    f"❌ Ícone incorreto! Atual: **{current_icon}** | Necessário: **{self.target_icon_id}**.", ephemeral=True
                )
        except Exception as e:
            print(f"Erro verify: {e}")

class Auth(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()

    # Helper para limpar o texto que o usuário digita
    def clean_lane(self, lane_input: str):
        if not lane_input: return None
        l = lane_input.lower().strip()
        if l in ['top', 'topo']: return 'TOP'
        if l in ['jungle', 'jg', 'selva']: return 'JUNGLE'
        if l in ['mid', 'meio']: return 'MID'
        if l in ['adc', 'bot', 'atirador']: return 'ADC'
        if l in ['sup', 'support', 'suporte']: return 'SUPPORT'
        if l in ['fill', 'todos']: return 'FILL'
        return None

    @commands.command(name="registrar")
    async def registrar(self, ctx, riot_id: str = None, main_lane: str = None, sec_lane: str = None):
        """
        Uso: .registrar Nick#TAG MainLane [SecLane]
        Ex: .registrar Marocos#BR1 Mid Top
        """
        # Validação de Argumentos
        if not riot_id or not main_lane:
            embed = discord.Embed(title="❌ Formato Inválido", color=0xff0000)
            embed.description = (
                "Você precisa informar o Nick e a Lane Principal.\n\n"
                "**Exemplo de uso:**\n"
                "`.registrar Faker#KR1 Mid`\n"
                "`.registrar Marocos#BR1 Jungle Top`"
            )
            await ctx.reply(embed=embed)
            return

        if "#" not in riot_id:
            await ctx.reply("❌ O Nick deve ter a TAG. Ex: `Nome#BR1`")
            return

        # Limpeza das Lanes
        m_lane_clean = self.clean_lane(main_lane)
        s_lane_clean = self.clean_lane(sec_lane)

        if not m_lane_clean:
            await ctx.reply("❌ Lane principal inválida! Use: Top, Jungle, Mid, Adc ou Sup.")
            return

        # Processo de Registro (API)
        msg_wait = await ctx.reply("⏳ Buscando conta na Riot...")
        
        try:
            game_name, tag_line = riot_id.split("#", 1)
            account_data = await self.riot_service.get_account_by_riot_id(game_name, tag_line)
            
            if not account_data:
                await msg_wait.edit(content=f"❌ Conta **{riot_id}** não encontrada.")
                return

            summoner_data = await self.riot_service.get_summoner_by_puuid(account_data['puuid'])
            current_icon_id = summoner_data['profileIconId']

            # Lógica do Desafio de Ícone
            target_icon_id = current_icon_id
            while target_icon_id == current_icon_id:
                target_icon_id = random.randint(0, 28)

            icon_url = f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{target_icon_id}.png"
            
            embed = discord.Embed(
                title="🛡️ Verificação de Segurança",
                description=(
                    f"Para confirmar **{riot_id}**, troque seu ícone no LoL para a imagem abaixo.\n"
                    f"Depois clique no botão **Verificar**."
                ),
                color=0xffcc00
            )
            embed.set_thumbnail(url=icon_url)
            
            view = VerifyView(
                bot=self.bot,
                ctx=ctx,
                riot_service=self.riot_service,
                puuid=account_data['puuid'],
                target_icon_id=target_icon_id,
                account_data=account_data,
                lanes={'main': m_lane_clean, 'sec': s_lane_clean}
            )

            await msg_wait.delete() # Apaga a msg de "carregando"
            await ctx.reply(embed=embed, view=view)

        except Exception as e:
            print(f"Erro .registrar: {e}")
            await ctx.reply("💥 Erro interno ao conectar com a Riot.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Auth(bot))