import discord
import random
import asyncio
from datetime import datetime, timedelta
from discord.ext import commands, tasks
import unicodedata
from src.utils.views import BaseInteractiveView

from src.services.riot_api import RiotAPI
from src.services.matchmaker import MatchMaker
from src.database.repositories import PlayerRepository

import logging
logger = logging.getLogger("auth")

VERIFY_TIMEOUT_MINUTES = 10
VERIFY_INTERVAL_SECONDS = 20


async def _complete_registration(discord_id, puuid, account_data, lanes, current_icon, riot_service, message):
    """Finaliza o registro: salva no banco, calcula MMR, edita o embed."""
    full_data = {**account_data, 'profileIconId': current_icon}

    await PlayerRepository.upsert_player(
        discord_id=discord_id,
        riot_data=full_data,
        lane_main=lanes['main'],
        lane_sec=lanes['sec']
    )

    try:
        riot_ranks = await riot_service.get_rank_by_puuid(puuid)
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
                discord_id=discord_id,
                tier=rank_data['tier'],
                rank=rank_data['rank'],
                lp=rank_data['leaguePoints'],
                wins=rank_data['wins'],
                losses=rank_data['losses'],
                calculated_mmr=initial_mmr,
                queue_type=queue_type
            )
        else:
            await PlayerRepository.update_riot_rank(discord_id, "UNRANKED", "", 0, 0, 0, 1000)
    except Exception as e:
        logger.error(f"Erro ao calcular MMR inicial: {e}")

    embed = discord.Embed(title="✅ Identidade Confirmada!", color=0x00ff00)
    embed.description = f"Conta **{account_data['gameName']}** vinculada com sucesso."
    embed.set_thumbnail(url=f"http://ddragon.leagueoflegends.com/cdn/{riot_service.ddragon_version}/img/profileicon/{current_icon}.png")

    try:
        await message.edit(embed=embed, view=None)
    except Exception:
        pass


class VerifyView(BaseInteractiveView):
    def __init__(self, auth_cog, ctx, puuid, target_icon_id, account_data, lanes):
        super().__init__(timeout=VERIFY_TIMEOUT_MINUTES * 60)
        self.auth_cog = auth_cog
        self.ctx = ctx
        self.puuid = puuid
        self.target_icon_id = target_icon_id
        self.account_data = account_data
        self.lanes = lanes

    @discord.ui.button(label="Já troquei! Verificar agora", style=discord.ButtonStyle.green)
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Ei, saia daqui! Use .registrar para fazer o seu.", ephemeral=True)
            return

        # Desabilita o botão imediatamente
        button.disabled = True
        button.label = "⏳ Verificando..."

        embed_aguardo = discord.Embed(
            title="⏳ Verificando seu ícone...",
            description=(
                f"Troca registrada! Aguardando a API da Riot confirmar o ícone **#{self.target_icon_id}**.\n\n"
                f"**Não troque o ícone** até o cadastro ser concluído.\n"
                f"O bot tenta a cada **{VERIFY_INTERVAL_SECONDS}s** por até **{VERIFY_TIMEOUT_MINUTES} minutos**."
            ),
            color=0xffcc00
        )
        embed_aguardo.set_thumbnail(url=self.message.embeds[0].thumbnail.url if self.message.embeds else discord.Embed.Empty)

        await interaction.response.edit_message(embed=embed_aguardo, view=self)

        # Marca que o botão foi clicado — background task já está rodando
        if self.ctx.author.id in self.auth_cog.pending_verifications:
            self.auth_cog.pending_verifications[self.ctx.author.id]['button_clicked'] = True

    async def on_timeout(self):
        v = self.auth_cog.pending_verifications.pop(self.ctx.author.id, None)
        channel = self.ctx.channel
        try:
            embed = discord.Embed(
                title="❌ Verificação Expirada",
                description=(
                    "O tempo de verificação esgotou sem que o ícone fosse detectado.\n\n"
                    "Possíveis causas:\n"
                    "• O ícone não foi trocado no cliente do LoL\n"
                    "• A API da Riot demorou mais que o esperado para atualizar\n\n"
                    "Use `.registrar` novamente para tentar."
                ),
                color=0xff0000
            )
            await self.message.edit(embed=embed, view=None)
        except Exception:
            pass

        # Pinga a pessoa no canal com explicação
        try:
            game_name = v['account_data']['gameName'] if v else "sua conta"
            await channel.send(
                f"{self.ctx.author.mention} A verificação de **{game_name}** expirou após {VERIFY_TIMEOUT_MINUTES} minutos sem detectar o ícone correto.\n"
                f"Use `.registrar` novamente. Se o problema persistir, pode ser instabilidade na API da Riot — tente mais tarde."
            )
        except Exception:
            pass


class Auth(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()
        # {discord_id: {puuid, target_icon_id, account_data, lanes, message, expires_at, channel, button_clicked}}
        self.pending_verifications: dict = {}

    async def cog_load(self):
        self.background_verify.start()

    async def cog_unload(self):
        self.background_verify.cancel()

    @tasks.loop(seconds=VERIFY_INTERVAL_SECONDS)
    async def background_verify(self):
        if not self.pending_verifications:
            return

        now = datetime.utcnow()

        for discord_id, v in list(self.pending_verifications.items()):
            # Expirou — on_timeout da view cuida da mensagem, só remove do dict
            if now >= v['expires_at']:
                self.pending_verifications.pop(discord_id, None)
                continue

            try:
                summoner_data = await self.riot_service.get_summoner_by_puuid(v['puuid'])
                if not summoner_data or summoner_data == "RIOT_SERVER_ERROR":
                    continue

                current_icon = summoner_data.get('profileIconId')
                logger.info(f"[BG] user={discord_id} ícone atual: {current_icon} | esperado: {v['target_icon_id']}")

                if current_icon == v['target_icon_id']:
                    self.pending_verifications.pop(discord_id, None)
                    await _complete_registration(
                        discord_id, v['puuid'], v['account_data'],
                        v['lanes'], current_icon, self.riot_service, v['message']
                    )

            except Exception as e:
                logger.error(f"Erro na verificação BG de {discord_id}: {e}")

    @background_verify.before_loop
    async def before_verify(self):
        await self.bot.wait_until_ready()

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
        remaining = list(parts)
        lane_tokens = []
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

        # Bloqueia se já tem verificação pendente
        if ctx.author.id in self.pending_verifications:
            v = self.pending_verifications[ctx.author.id]
            remaining = max(0, int((v['expires_at'] - datetime.utcnow()).total_seconds() / 60))
            return await ctx.reply(
                f"⏳ Você já tem uma verificação em andamento para **{v['account_data']['gameName']}**.\n"
                f"Aguarde até **{remaining} minuto(s)** ou peça ao admin para cancelar.",
                delete_after=20
            )

        lanes_data = {'main': main_lane, 'sec': sec_lane}
        msg_wait = await ctx.reply("⏳ Buscando conta na Riot...")

        try:
            game_name, tag_line = riot_id.split("#", 1)
            account_data = await self.riot_service.get_account_by_riot_id(game_name, tag_line)

            if not account_data:
                await msg_wait.edit(content=f"❌ Conta **{riot_id}** não encontrada.")
                return

            summoner_data = await self.riot_service.get_summoner_by_puuid(account_data['puuid'])
            if summoner_data == "RIOT_SERVER_ERROR":
                await msg_wait.edit(content="⚠️ Os servidores da Riot estão instáveis. Tente novamente em alguns minutos.")
                return
            if not summoner_data:
                await msg_wait.edit(content="❌ Conta encontrada, mas sem dados de summoner. A conta já jogou League of Legends?")
                return

            current_icon_id = summoner_data['profileIconId']

            BASE_ICONS = list(range(30))
            target_icon_id = current_icon_id
            while target_icon_id == current_icon_id:
                target_icon_id = random.choice(BASE_ICONS)

            await self.riot_service.update_version()
            ddragon_version = self.riot_service.ddragon_version
            icon_url = f"http://ddragon.leagueoflegends.com/cdn/{ddragon_version}/img/profileicon/{target_icon_id}.png"

            embed = discord.Embed(
                title="🛡️ Verificação de Segurança",
                description=(
                    f"Para confirmar **{riot_id}**, troque seu ícone no LoL para o da imagem ao lado.\n\n"
                    f"Depois clique em **Já troquei!** — o bot irá verificar automaticamente.\n\n"
                    f"**IMPORTANTE:** Não troque o ícone de volta até o cadastro ser concluído.\n"
                    f"Este ícone fica no final da lista de ícones dentro do LoL."
                ),
                color=0xffcc00
            )
            embed.set_thumbnail(url=icon_url)

            view = VerifyView(
                auth_cog=self,
                ctx=ctx,
                puuid=account_data['puuid'],
                target_icon_id=target_icon_id,
                account_data=account_data,
                lanes=lanes_data
            )

            await msg_wait.delete()
            sent_message = await ctx.reply(embed=embed, view=view)
            view.message = sent_message

            self.pending_verifications[ctx.author.id] = {
                'puuid': account_data['puuid'],
                'target_icon_id': target_icon_id,
                'account_data': account_data,
                'lanes': lanes_data,
                'message': sent_message,
                'channel': ctx.channel,
                'expires_at': datetime.utcnow() + timedelta(minutes=VERIFY_TIMEOUT_MINUTES),
                'button_clicked': False,
            }

        except Exception as e:
            logger.error(f"Erro .registrar: {e}")
            try:
                await msg_wait.delete()
            except Exception:
                pass
            await ctx.reply("💥 Erro interno ao conectar com a Riot.")


    @commands.command(name="desvincular", aliases=["desregistrar"])
    async def desvincular(self, ctx, membro: discord.Member = None):
        """
        Remove o vínculo de uma conta Riot do bot.
        Uso: .desvincular              → remove sua própria conta
             .desvincular @user        → admin remove a conta de outro usuário
        """
        # Admin pode desvincular qualquer um; usuário comum só a si mesmo
        if membro and membro != ctx.author:
            if not ctx.author.guild_permissions.administrator:
                return await ctx.reply("⛔ Apenas administradores podem desvincular a conta de outro usuário.", delete_after=10)
            target = membro
        else:
            target = ctx.author

        player = await PlayerRepository.get_player_by_discord_id(target.id)
        if not player:
            return await ctx.reply(f"❌ **{target.display_name}** não está registrado no bot.", delete_after=10)

        riot_name = player.riot_name or "conta desconhecida"

        # Cancela verificação pendente se houver
        self.pending_verifications.pop(target.id, None)

        await PlayerRepository.delete_player(target.id)

        if target == ctx.author:
            await ctx.reply(
                f"✅ Conta **{riot_name}** desvinculada com sucesso.\n"
                f"Use `.registrar` para vincular uma nova conta quando quiser."
            )
        else:
            await ctx.reply(f"✅ Conta **{riot_name}** de {target.mention} desvinculada pelo admin.")

    @desvincular.error
    async def desvincular_error(self, ctx, error):
        if isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ Membro não encontrado. Mencione alguém do servidor.", delete_after=8)


async def setup(bot: commands.Bot):
    await bot.add_cog(Auth(bot))
