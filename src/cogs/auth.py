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

# Timeout da verificação em background: 10 minutos
VERIFY_TIMEOUT_MINUTES = 10


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

        await interaction.response.defer(ephemeral=True)

        try:
            summoner_data = await self.auth_cog.riot_service.get_summoner_by_puuid(self.puuid)
            if summoner_data == "RIOT_SERVER_ERROR":
                await interaction.followup.send("⚠️ Servidores da Riot instáveis. A verificação automática continuará tentando em background.", ephemeral=True)
                return
            if not summoner_data:
                await interaction.followup.send("⚠️ Não foi possível conectar com a Riot API. A verificação automática tentará em breve.", ephemeral=True)
                return

            current_icon = summoner_data.get('profileIconId')
            logger.info(f"[Verificação manual] ícone atual: {current_icon} | esperado: {self.target_icon_id}")

            if current_icon == self.target_icon_id:
                self.auth_cog.pending_verifications.pop(self.ctx.author.id, None)
                self.stop()
                await _complete_registration(
                    self.ctx.author.id, self.puuid, self.account_data,
                    self.lanes, current_icon, self.auth_cog.riot_service, self.message
                )
            else:
                await interaction.followup.send(
                    f"⏳ Ícone ainda não atualizado na API da Riot.\n"
                    f"Atual: **{current_icon}** | Necessário: **{self.target_icon_id}**\n\n"
                    f"A verificação automática está rodando em background e vai confirmar assim que a API atualizar (pode levar até {VERIFY_TIMEOUT_MINUTES} minutos).",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Erro verify manual: {e}")
            await interaction.followup.send("💥 Erro interno ao verificar. A verificação automática continua rodando.", ephemeral=True)

    async def on_timeout(self):
        self.auth_cog.pending_verifications.pop(self.ctx.author.id, None)
        try:
            embed = discord.Embed(
                title="⏰ Verificação Expirada",
                description="O tempo de verificação expirou. Use `.registrar` novamente para tentar.",
                color=0xff0000
            )
            await self.message.edit(embed=embed, view=None)
        except Exception:
            pass


class Auth(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.riot_service = RiotAPI()
        # {discord_id: {puuid, target_icon_id, account_data, lanes, message, expires_at}}
        self.pending_verifications: dict = {}

    async def cog_load(self):
        self.background_verify.start()

    async def cog_unload(self):
        self.background_verify.cancel()

    @tasks.loop(seconds=60)
    async def background_verify(self):
        if not self.pending_verifications:
            return

        now = datetime.utcnow()
        expired = [uid for uid, v in self.pending_verifications.items() if now >= v['expires_at']]
        for uid in expired:
            self.pending_verifications.pop(uid, None)

        for discord_id, v in list(self.pending_verifications.items()):
            try:
                summoner_data = await self.riot_service.get_summoner_by_puuid(v['puuid'])
                if not summoner_data or summoner_data == "RIOT_SERVER_ERROR":
                    continue

                current_icon = summoner_data.get('profileIconId')
                logger.info(f"[Verificação BG] user={discord_id} ícone atual: {current_icon} | esperado: {v['target_icon_id']}")

                if current_icon == v['target_icon_id']:
                    self.pending_verifications.pop(discord_id, None)
                    await _complete_registration(
                        discord_id, v['puuid'], v['account_data'],
                        v['lanes'], current_icon, self.riot_service, v['message']
                    )
            except Exception as e:
                logger.error(f"Erro na verificação background de {discord_id}: {e}")

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

        # Bloqueia se já tem verificação pendente
        if ctx.author.id in self.pending_verifications:
            v = self.pending_verifications[ctx.author.id]
            remaining = int((v['expires_at'] - __import__('datetime').datetime.utcnow()).total_seconds() / 60)
            return await ctx.reply(
                f"⏳ Você já tem uma verificação em andamento para **{v['account_data']['gameName']}**.\n"
                f"O bot está verificando automaticamente — aguarde até **{remaining} minuto(s)**.\n"
                f"Se quiser cancelar e recomeçar, aguarde expirar ou peça ao admin.",
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
                await msg_wait.edit(content="⚠️ Os servidores da Riot estão instáveis no momento. Tente novamente em alguns minutos.")
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
                    f"Para confirmar **{riot_id}**, troque seu ícone no LoL para o mesmo da imagem ao lado.\n"
                    f"Depois clique no botão ou aguarde — **a verificação é automática**.\n\n"
                    f"O bot detecta a troca automaticamente a cada **1 minuto** por até **{VERIFY_TIMEOUT_MINUTES} minutos**.\n\n"
                    f"**IMPORTANTE:** Após a verificação, pode trocar o ícone de volta.\n"
                    f"Este ícone estará no final da sua lista de ícones dentro do LoL."
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

            # Registra verificação pendente para o background task
            self.pending_verifications[ctx.author.id] = {
                'puuid': account_data['puuid'],
                'target_icon_id': target_icon_id,
                'account_data': account_data,
                'lanes': lanes_data,
                'message': sent_message,
                'expires_at': datetime.utcnow() + timedelta(minutes=VERIFY_TIMEOUT_MINUTES),
            }

        except Exception as e:
            logger.error(f"Erro .registrar: {e}")
            try:
                await msg_wait.delete()
            except Exception:
                pass
            await ctx.reply("💥 Erro interno ao conectar com a Riot.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Auth(bot))
