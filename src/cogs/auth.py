import discord
import random
from discord.ext import commands
import unicodedata

from src.services.riot_api import RiotAPI
from src.database.repositories import PlayerRepository


# View do Botão (Continua igual, pois botões são ótimos para segurança)
class VerifyView(discord.ui.View):
    def __init__(self, bot, ctx, riot_service, puuid, target_icon_id, account_data, lanes):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
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

        await interaction.response.defer()

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
                    f"❌ Ícone incorreto! Atual: **{current_icon}** | Necessário: **{self.target_icon_id}**.",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Erro verify: {e}")


class Auth(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()

    # Remove caracteres invisíveis (problema comum vindo de celular)
    def remove_invisible(self, text: str):
        if not text:
            return text
        return "".join(
            c for c in text
            if unicodedata.category(c) != "Cf"
        )

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
    async def registrar(self, ctx, *, args: str = None):
        """
        Uso: .registrar Nick#TAG MainLane [SecLane]
        Ex: .registrar Marocos#BR1 Mid Top
        """

        # --- PARSER NOVO (ACEITA ESPAÇOS + EMOJIS + UNICODE) ---

        if not args:
            embed = discord.Embed(title="❌ Formato Inválido", color=0xff0000)
            embed.description = (
                "Você precisa informar o Nick e a Lane Principal.\n\n"
                "**Exemplo:**\n"
                "`.registrar Faker#KR1 Mid`\n"
                "`.registrar Eric ツ#2000 Jungle Top`"
            )
            await ctx.reply(embed=embed)
            return

        parts = args.split()

        if len(parts) < 2:
            await ctx.reply("❌ Você precisa informar pelo menos Nick#TAG e a lane principal.")
            return

        main_lane = parts[-1]
        sec_lane = None

        if len(parts) >= 3:
            possible_sec = parts[-2]
            if self.clean_lane(possible_sec):
                sec_lane = possible_sec
                riot_id = " ".join(parts[:-2])
            else:
                riot_id = " ".join(parts[:-1])
        else:
            riot_id = " ".join(parts[:-1])

        # --- REMOVE CARACTERES INVISÍVEIS ← IMPORTANTE! ---
        riot_id = self.remove_invisible(riot_id).strip()

        # ---------------------------------------------------------

        if "#" not in riot_id:
            await ctx.reply("❌ O Nick deve ter a TAG. Ex: `Nome#BR1`")
            return

        # Limpeza das lanes
        m_lane_clean = self.clean_lane(main_lane)
        s_lane_clean = self.clean_lane(sec_lane)

        if not m_lane_clean:
            await ctx.reply("❌ Lane principal inválida! Use: Top, Jungle, Mid, Adc ou Sup.")
            return

        msg_wait = await ctx.reply("⏳ Buscando conta na Riot...")

        try:
            game_name, tag_line = riot_id.split("#", 1)
            account_data = await self.riot_service.get_account_by_riot_id(game_name, tag_line)

            if not account_data:
                await msg_wait.edit(content=f"❌ Conta **{riot_id}** não encontrada.")
                return

            summoner_data = await self.riot_service.get_summoner_by_puuid(account_data['puuid'])
            current_icon_id = summoner_data['profileIconId']

            target_icon_id = current_icon_id
            while target_icon_id == current_icon_id:
                target_icon_id = random.randint(0, 28)

            icon_url = f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{target_icon_id}.png"

            embed = discord.Embed(
                title="🛡️ Verificação de Segurança",
                description=(
                    f"Para confirmar **{riot_id}**, troque seu ícone no LoL para o mesmo da imagem ao lado.\n"
                    f"Depois clique no botão **Verificar**.\n"
                    f"\n"
                    f"Esse ícone aleatório ajuda a garantir que você é o dono da conta.\n"
                    f"**IMPORTANTE:** Após a verificação, você pode trocar o ícone de volta normalmente.\n"
                    f"\n\n"
                    f"Este ícone estará no final da sua lista de ícones dentro do lol."
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

            await msg_wait.delete()
            await ctx.reply(embed=embed, view=view)

        except Exception as e:
            print(f"Erro .registrar: {e}")
            await ctx.reply("💥 Erro interno ao conectar com a Riot.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Auth(bot))
