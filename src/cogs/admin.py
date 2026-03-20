import discord
from discord.ext import commands
import asyncio
import logging
from src.database.repositories import PlayerRepository, GuildRepository
from src.services.matchmaker import MatchMaker

logger = logging.getLogger("admin")


# --- VIEW DE CONFIRMAÇÃO ---
class ClearConfirmationView(discord.ui.View):
    def __init__(self, admin_cog, ctx, mode):
        super().__init__(timeout=60)
        self.admin_cog = admin_cog
        self.ctx = ctx
        self.mode = mode
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("⛔ Apenas o Admin que iniciou pode interagir.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Você não tem permissão.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Sim, Tenho Certeza", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(content="🔄 Iniciando limpeza...", view=self)
        except:
            pass
        try:
            deleted_count = await self.admin_cog.execute_clear(self.ctx, self.mode)
            try:
                await self.ctx.message.delete()
            except:
                pass
            await interaction.message.delete()
            await self.ctx.channel.send(f"✅ Limpeza concluída! ({deleted_count} mensagens apagadas).", delete_after=5)
        except Exception as e:
            logger.error(f"Erro na limpeza: {e}")
            await self.ctx.channel.send(f"⛔ ERRO: {e}", delete_after=10)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Limpeza cancelada.", view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏰ Confirmação expirada.", view=None)
            except:
                pass


# --- VIEW DE CONFIRMAÇÃO DE RECÁLCULO ---
class RecalcConfirmView(discord.ui.View):
    def __init__(self, admin_cog, ctx):
        super().__init__(timeout=60)
        self.admin_cog = admin_cog
        self.ctx = ctx

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("⛔ Apenas o Admin pode confirmar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar Recálculo", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="⏳ Recalculando MMR de todos os jogadores...", view=self)

        try:
            updated, skipped = await self.admin_cog.execute_recalc_mmr()
            await interaction.message.edit(
                content=f"✅ MMR recalculado! **{updated}** jogador(es) atualizados, **{skipped}** sem rank ignorados.",
                view=None
            )
        except Exception as e:
            logger.error(f"Erro no recálculo: {e}")
            await interaction.message.edit(content=f"⛔ Erro durante recálculo: {e}", view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Recálculo cancelado.", view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏰ Confirmação expirada.", view=None)
            except:
                pass


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def execute_clear(self, ctx: commands.Context, mode: str) -> int:
        if mode == 'bot':
            check = lambda m: m.author == self.bot.user
            limit_val = 1000
        else:
            check = lambda m: True
            limit_val = 1000

        try:
            deleted = await ctx.channel.purge(limit=limit_val, check=check, before=ctx.message)
            return len(deleted)
        except discord.Forbidden:
            raise commands.CheckFailure("PERMISSAO_NEGADA")
        except Exception as e:
            logger.critical(f"Erro no purge: {e}")
            raise e

    async def execute_recalc_mmr(self) -> tuple:
        """
        Recalcula o MMR de todos os jogadores registrados com base no rank cached.
        Retorna (updated_count, skipped_count).
        """
        players = await PlayerRepository.get_all_players()
        updated = skipped = 0

        for player in players:
            try:
                # Prioriza SoloQ, fallback Flex
                if player.solo_tier and player.solo_tier.upper() not in ('UNRANKED', ''):
                    new_mmr = MatchMaker.calculate_adjusted_mmr(
                        player.solo_tier, player.solo_rank, player.solo_lp,
                        player.solo_wins, player.solo_losses, 'RANKED_SOLO_5x5'
                    )
                elif player.flex_tier and player.flex_tier.upper() not in ('UNRANKED', ''):
                    new_mmr = MatchMaker.calculate_adjusted_mmr(
                        player.flex_tier, player.flex_rank, player.flex_lp,
                        player.flex_wins, player.flex_losses, 'RANKED_FLEX_SR'
                    )
                else:
                    skipped += 1
                    continue

                await PlayerRepository.update_mmr_direct(player.discord_id, new_mmr)
                updated += 1

                # Pequena pausa para não sobrecarregar o banco
                await asyncio.sleep(0.05)

            except Exception as e:
                logger.error(f"Erro ao recalcular MMR de {player.discord_id}: {e}")
                skipped += 1

        return updated, skipped

    @commands.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def clear_bot_messages(self, ctx: commands.Context):
        """Apaga as mensagens do bot no canal (Últimas 1000)."""
        try:
            view = ClearConfirmationView(self, ctx, 'bot')
            confirmation_message = await ctx.reply(
                "⚠️ Tem certeza que deseja apagar **apenas as mensagens do BOT**?",
                view=view
            )
            view.message = confirmation_message
        except Exception as e:
            logger.error(f"Erro ao enviar confirmação: {e}")

    @commands.command(name="clear_all")
    @commands.has_permissions(administrator=True)
    async def clear_all_messages(self, ctx: commands.Context):
        """Apaga TODAS as mensagens do canal (Últimas 1000)."""
        try:
            view = ClearConfirmationView(self, ctx, 'all')
            confirmation_message = await ctx.reply(
                "🔴 ATENÇÃO! Tem certeza que deseja apagar **as últimas 1000 mensagens** deste canal?",
                view=view
            )
            view.message = confirmation_message
        except Exception as e:
            logger.error(f"Erro ao enviar confirmação: {e}")

    @commands.command(name="recalcular_mmr", aliases=["recalc_mmr", "resetar_mmr"])
    @commands.has_permissions(administrator=True)
    async def recalcular_mmr(self, ctx: commands.Context):
        """
        Recalcula o MMR de TODOS os jogadores registrados com base no rank cached.
        Útil após ajustar a fórmula ou forçar sincronização.
        """
        players = await PlayerRepository.get_all_players()
        total = len(players)

        if total == 0:
            return await ctx.reply("📭 Nenhum jogador registrado para recalcular.")

        embed = discord.Embed(
            title="⚠️ Recálculo de MMR em Massa",
            description=(
                f"Esta operação irá **recalcular o MMR de {total} jogador(es)** "
                f"com base nos ranks cached (último sync com a Riot).\n\n"
                f"Isso **não** consulta a Riot API — usa os dados já salvos no banco.\n\n"
                f"**Confirmar?**"
            ),
            color=0xff9900
        )
        embed.set_footer(text="Para atualizar ranks antes do recálculo, use .perfil ou aguarde a task de tracking.")

        view = RecalcConfirmView(self, ctx)
        msg = await ctx.reply(embed=embed, view=view)
        view.message = msg


    @commands.command(name="config_cargo")
    @commands.has_permissions(administrator=True)
    async def config_cargo(self, ctx: commands.Context, tipo: str, cargo: discord.Role):
        """
        Configura o cargo de vencedor ou perdedor da liga.
        Uso: .config_cargo vencedor @Cargo  |  .config_cargo perdedor @Cargo
        """
        tipo = tipo.lower()
        if tipo not in ('vencedor', 'perdedor'):
            return await ctx.reply("❌ Tipo inválido. Use `vencedor` ou `perdedor`.\nEx: `.config_cargo vencedor @Vencedor`")

        role_type = 'winner' if tipo == 'vencedor' else 'loser'
        await GuildRepository.set_match_role(ctx.guild.id, role_type, cargo.id)

        label = "Vencedor" if role_type == 'winner' else "Perdedor"
        await ctx.reply(f"✅ Cargo de **{label}** definido para {cargo.mention}.", delete_after=15)

    @config_cargo.error
    async def config_cargo_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("⛔ Apenas administradores podem usar este comando.", delete_after=8)
        elif isinstance(error, commands.RoleNotFound):
            await ctx.reply("❌ Cargo não encontrado. Mencione o cargo com @.", delete_after=8)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply("❌ Uso: `.config_cargo vencedor @Cargo` ou `.config_cargo perdedor @Cargo`", delete_after=10)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
