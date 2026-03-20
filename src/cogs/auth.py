import discord
import random
from discord.ext import commands
import unicodedata
from src.utils.views import BaseInteractiveView

from src.services.riot_api import RiotAPI
from src.services.matchmaker import MatchMaker
from src.database.repositories import PlayerRepository


class VerifyView(BaseInteractiveView):
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

        await interaction.response.defer(ephemeral=True)

        try:
            summoner_data = await self.riot_service.get_summoner_by_puuid(self.puuid)

            if not summoner_data:
                await interaction.followup.send(
                    "⚠️ Não foi possível conectar com a Riot API agora. Tente novamente em instantes.",
                    ephemeral=True
                )
                return

            current_icon = summoner_data.get('profileIconId')

            if current_icon == self.target_icon_id:
                full_data = {**self.account_data, 'profileIconId': current_icon}

                await PlayerRepository.upsert_player(
                    discord_id=self.ctx.author.id,
                    riot_data=full_data,
                    lane_main=self.lanes['main'],
                    lane_sec=self.lanes['sec']
                )

                # Busca e calcula MMR inicial
                try:
                    riot_ranks = await self.riot_service.get_rank_by_puuid(self.puuid)

                    rank_data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_SOLO_5x5'), None)
                    queue_type = 'RANKED_SOLO_5x5'

                    if not rank_data:
                        rank_data = next((r for r in (riot_ranks or []) if r['queueType'] == 'RANKED_FLEX_SR'), None)
                        queue_type = 'RANKED_FLEX_SR'

                    if rank_data:
                        initial_mmr = MatchMaker.calculate_adjusted_mmr(
                            tier=rank_data['tier'],
                            rank=rank_data['rank'],
                            lp=rank_data['leaguePoints'],
                            wins=rank_data['wins'],
                            losses=rank_data['losses'],
                            queue_type=queue_type
                        )
                        await PlayerRepository.update_riot_rank(
                            discord_id=self.ctx.author.id,
                            tier=rank_data['tier'],
                            rank=rank_data['rank'],
                            lp=rank_data['leaguePoints'],
                            wins=rank_data['wins'],
                            losses=rank_data['losses'],
                            calculated_mmr=initial_mmr,
                            queue_type=queue_type
                        )
                    else:
                        await PlayerRepository.update_riot_rank(self.ctx.author.id, "UNRANKED", "", 0, 0, 0, 1000)

                except Exception as e:
                    print(f"Erro ao calcular MMR inicial no registro: {e}")

                embed = discord.Embed(title="✅ Identidade Confirmada!", color=0x00ff00)
                embed.description = f"Conta **{self.account_data['gameName']}** vinculada com sucesso."
                embed.set_thumbnail(url=f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{current_icon}.png")

                self.clear_items()
                await interaction.edit_original_response(embed=embed, view=self)
                self.stop()
            else:
                await interaction.followup.send(
                    f"❌ Ícone incorreto!\n"
                    f"Atual: **{current_icon}** | Necessário: **{self.target_icon_id}**\n\n"
                    f"⏳ A Riot pode demorar **1-2 minutos** para atualizar após a troca. Aguarde e tente novamente.",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Erro verify: {e}")
            await interaction.followup.send(
                "💥 Erro interno ao verificar. Tente novamente em alguns instantes.",
                ephemeral=True
            )


class Auth(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()

    def remove_invisible(self, text: str):
        if not text:
            return text
        return "".join(c for c in text if unicodedata.category(c) != "Cf")

    def clean_lane(self, lane_input: str):
        if not lane_input:
            return None
        l = lane_input.lower().strip()
        if l in ['top', 'topo']: return 'TOP'
        if l in ['jungle', 'jg', 'selva']: return 'JUNGLE'
        if l in ['mid', 'meio']: return 'MID'
        if l in ['adc', 'bot', 'atirador']: return 'ADC'
        if l in ['sup', 'support', 'suporte']: return 'SUPPORT'
        if l in ['fill', 'todos']: return 'FILL'
        return None

    def parse_lanes_and_riot_id(self, parts: list):
        """
        Extrai lanes e Riot ID dos argumentos da direita para a esquerda.
        Usuário digita: RiotID MainLane [SecLane]
        Retorna: (riot_id_str, main_lane, sec_lane)
        """
        remaining = list(parts)
        lane_tokens = []

        # Coleta até 2 tokens de lane, da direita para a esquerda
        while remaining and len(lane_tokens) < 2:
            if self.clean_lane(remaining[-1]):
                lane_tokens.insert(0, remaining.pop())
            else:
                break

        riot_id = " ".join(remaining).strip()
        main_lane = self.clean_lane(lane_tokens[0]) if len(lane_tokens) >= 1 else None
        sec_lane = self.clean_lane(lane_tokens[1]) if len(lane_tokens) >= 2 else None

        return riot_id, main_lane, sec_lane

    @commands.command(name="registrar")
    async def registrar(self, ctx, *, args: str = None):
        """
        Uso: .registrar Nick#TAG MainLane [SecLane]
        Ex: .registrar Faker#KR1 Mid Top
        """
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

        cleaned = self.remove_invisible(args).strip()
        parts = cleaned.split()

        if len(parts) < 2:
            await ctx.reply("❌ Você precisa informar pelo menos Nick#TAG e a lane principal.")
            return

        riot_id, main_lane, sec_lane = self.parse_lanes_and_riot_id(parts)

        if not riot_id or "#" not in riot_id:
            await ctx.reply("❌ O Nick deve ter a TAG. Ex: `Nome#BR1`")
            return

        if not main_lane:
            await ctx.reply("❌ Lane principal inválida! Use: Top, Jungle, Mid, Adc ou Sup.")
            return

        lanes_data = {'main': main_lane, 'sec': sec_lane}

        msg_wait = await ctx.reply("⏳ Buscando conta na Riot...")

        try:
            game_name, tag_line = riot_id.split("#", 1)
            account_data = await self.riot_service.get_account_by_riot_id(game_name, tag_line)

            if not account_data:
                await msg_wait.edit(content=f"❌ Conta **{riot_id}** não encontrada.")
                return

            summoner_data = await self.riot_service.get_summoner_by_puuid(account_data['puuid'])
            current_icon_id = summoner_data['profileIconId']

            # Ícones básicos garantidamente existentes no LoL
            BASE_ICONS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29]
            target_icon_id = current_icon_id
            while target_icon_id == current_icon_id:
                target_icon_id = random.choice(BASE_ICONS)

            icon_url = f"http://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{target_icon_id}.png"

            embed = discord.Embed(
                title="🛡️ Verificação de Segurança",
                description=(
                    f"Para confirmar **{riot_id}**, troque seu ícone no LoL para o mesmo da imagem ao lado.\n"
                    f"Depois clique no botão **Verificar**.\n\n"
                    f"Esse ícone aleatório garante que você é o dono da conta.\n"
                    f"**IMPORTANTE:** Após a verificação, pode trocar o ícone de volta.\n\n"
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
                lanes=lanes_data
            )

            await msg_wait.delete()
            sent_message = await ctx.reply(embed=embed, view=view)
            view.message = sent_message

        except Exception as e:
            print(f"Erro .registrar: {e}")
            await ctx.reply("💥 Erro interno ao conectar com a Riot.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Auth(bot))
