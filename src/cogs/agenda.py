import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import logging
from src.database.repositories import EventRepository

logger = logging.getLogger("agenda")

BRT = timezone(timedelta(hours=-3))


def parse_brazil_dt(date_str: str, time_str: str) -> datetime:
    """Converte DD/MM/YYYY e HH:MM (Brasília, UTC-3) para datetime UTC naive."""
    naive = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
    brt = naive.replace(tzinfo=BRT)
    return brt.astimezone(timezone.utc).replace(tzinfo=None)


def build_embed(event: dict, guild: discord.Guild) -> discord.Embed:
    """Constrói o embed do evento com a lista atualizada de confirmados."""
    status_icons  = {'open': '📅', 'cancelled': '🚫', 'started': '🚀'}
    status_colors = {'open': 0x3498db, 'cancelled': 0xe74c3c, 'started': 0x2ecc71}

    icon  = status_icons.get(event['status'], '📅')
    color = status_colors.get(event['status'], 0x3498db)

    ts = int(event['scheduled_for'].replace(tzinfo=timezone.utc).timestamp())

    embed = discord.Embed(title=f"{icon} {event['title']}", color=color)
    embed.description = (
        f"🗓️ **Data:** <t:{ts}:F>\n"
        f"⏰ **Quando:** <t:{ts}:R>"
    )
    if event.get('description'):
        embed.description += f"\n\n📝 {event['description']}"


    player_ids = event.get('player_ids', [])
    names = []
    for i, pid in enumerate(player_ids):
        member = guild.get_member(pid)
        display = member.display_name if member else f"Usuário ({pid})"
        names.append(f"`{i+1}.` {display}")

    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    total   = len(player_ids)
    max_p   = event['max_players']
    spots   = max_p - total
    header  = f"✅ Confirmados ({total}/{max_p})"
    value   = "\n".join(names) if names else "_Ninguém confirmado ainda._"
    embed.add_field(name=header, value=value, inline=False)

    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    if event['status'] == 'open':
        if spots > 0:
            embed.add_field(name="\n🆓 Vagas restantes", value=f"**{spots}**", inline=True)
        else:
            embed.add_field(name="🔒 Vagas", value="**Lotado!**", inline=True)

    status_labels = {'open': 'Aberto', 'cancelled': 'Cancelado', 'started': 'Iniciado'}
    embed.set_footer(text=f"Evento #{event['id']} · {status_labels.get(event['status'], '')}")
    return embed


# --- VIEW DOS BOTÕES (persistente) ---
class AgendaView(discord.ui.View):
    def __init__(self, event_id: int, max_players: int):
        super().__init__(timeout=None)
        self.event_id   = event_id
        self.max_players = max_players

        confirm_btn = discord.ui.Button(
            label="Confirmar Presença",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"agenda_confirm_{event_id}",
        )
        confirm_btn.callback = self.confirm_callback

        leave_btn = discord.ui.Button(
            label="Cancelar Presença",
            style=discord.ButtonStyle.secondary,
            emoji="❌",
            custom_id=f"agenda_leave_{event_id}",
        )
        leave_btn.callback = self.leave_callback

        self.add_item(confirm_btn)
        self.add_item(leave_btn)

    async def _refresh(self, interaction: discord.Interaction):
        event = await EventRepository.get_event(self.event_id)
        if not event or event['status'] != 'open':
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)
            return

        total = len(event.get('player_ids', []))
        for item in self.children:
            if hasattr(item, 'custom_id') and 'confirm' in item.custom_id:
                item.disabled = (total >= event['max_players'])

        embed = build_embed(event, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    async def confirm_callback(self, interaction: discord.Interaction):
        event = await EventRepository.get_event(self.event_id)
        if not event or event['status'] != 'open':
            return await interaction.response.send_message("❌ Este evento não está mais aberto.", ephemeral=True)
        if len(event['player_ids']) >= event['max_players']:
            return await interaction.response.send_message("❌ Evento lotado!", ephemeral=True)

        added = await EventRepository.add_player(self.event_id, interaction.user.id)
        if not added:
            return await interaction.response.send_message("✅ Você já está confirmado neste evento.", ephemeral=True)
        await self._refresh(interaction)

    async def leave_callback(self, interaction: discord.Interaction):
        removed = await EventRepository.remove_player(self.event_id, interaction.user.id)
        if not removed:
            return await interaction.response.send_message("❌ Você não está na lista deste evento.", ephemeral=True)
        await self._refresh(interaction)


# --- COG ---
class Agenda(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Re-registra views de eventos abertos para sobreviver a restarts
        try:
            # Busca todos os guilds conhecidos e recarrega eventos
            all_events_raw = []
            for guild in self.bot.guilds:
                events = await EventRepository.get_open_events(guild.id)
                all_events_raw.extend(events)

            for e in all_events_raw:
                view = AgendaView(e['id'], e['max_players'])
                self.bot.add_view(view)

            if all_events_raw:
                logger.info(f"Agenda: {len(all_events_raw)} evento(s) aberto(s) recarregados.")
        except Exception as ex:
            logger.warning(f"Agenda: erro ao recarregar eventos: {ex}")

        self.check_notifications.start()

    async def cog_unload(self):
        self.check_notifications.cancel()

    # --- TASK DE NOTIFICAÇÕES ---
    @tasks.loop(minutes=5)
    async def check_notifications(self):
        try:
            events = await EventRepository.get_events_needing_notification()
            now = datetime.utcnow()

            for event in events:
                dt   = event['scheduled_for']
                diff = dt - now

                if diff.total_seconds() < 0:
                    continue  # Evento já passou

                if (not event['notified_24h']
                        and timedelta(hours=23, minutes=29) <= diff <= timedelta(hours=24, minutes=31)):
                    await self._send_reminder(event, '24h')
                    await EventRepository.mark_notified(event['id'], '24h')

                elif (not event['notified_30min']
                        and timedelta(minutes=10) <= diff <= timedelta(minutes=45)):
                    await self._send_reminder(event, '30min')
                    await EventRepository.mark_notified(event['id'], '30min')

        except Exception as e:
            logger.error(f"Erro no check_notifications da Agenda: {e}")

    @check_notifications.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _send_reminder(self, event: dict, reminder_type: str):
        ts = int(event['scheduled_for'].replace(tzinfo=timezone.utc).timestamp())

        if reminder_type == '24h':
            title     = "⏰ Lembrete — 1 dia para o evento!"
            desc_extra = "O evento começa em aproximadamente **24 horas**. Não esqueça!"
            color     = 0xff9900
        else:
            title     = "🚨 Lembrete — 30 minutos para o evento!"
            desc_extra = "O evento começa em **30 minutos**. Prepare-se!"
            color     = 0xe74c3c

        channel_line = ""
        guild = self.bot.get_guild(event['guild_id'])
        if guild and event.get('channel_id'):
            ch = guild.get_channel(event['channel_id'])
            if ch:
                channel_line = f"\n📍 Canal: {ch.mention}"

        embed = discord.Embed(
            title=title,
            description=(
                f"**{event['title']}**\n"
                f"🗓️ <t:{ts}:F>\n\n"
                f"{desc_extra}"
                f"{channel_line}"
            ),
            color=color,
        )
        embed.set_footer(text=f"Evento #{event['id']} · Use o botão no canal para cancelar presença.")

        for pid in event.get('player_ids', []):
            try:
                user = self.bot.get_user(pid) or await self.bot.fetch_user(pid)
                if user:
                    await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass  # DM fechada — ignora silenciosamente

    # --- HELPER ---
    async def _get_and_validate_event(self, ctx, event_id: int, require_open: bool = True):
        """Busca evento e valida permissões/status. Retorna dict ou None."""
        event = await EventRepository.get_event(event_id)
        if not event:
            await ctx.reply(f"❌ Evento #{event_id} não encontrado.")
            return None
        if event['guild_id'] != ctx.guild.id:
            await ctx.reply("❌ Este evento não pertence a este servidor.")
            return None
        if require_open and event['status'] != 'open':
            status_map = {'cancelled': 'cancelado', 'started': 'já iniciado'}
            label = status_map.get(event['status'], event['status'])
            await ctx.reply(f"❌ Evento #{event_id} está {label}.")
            return None
        return event

    # --- COMANDOS ---

    @commands.command(name="agendar")
    @commands.has_permissions(administrator=True)
    async def agendar(self, ctx: commands.Context, data: str, hora: str, *, titulo: str):
        """
        Cria um evento agendado.
        Uso: .agendar DD/MM/YYYY HH:MM Título do Evento
        Ex:  .agendar 21/03/2025 21:00 Sexta Ranqueada
        """
        try:
            scheduled_for = parse_brazil_dt(data, hora)
        except ValueError:
            return await ctx.reply("❌ Data inválida. Use o formato `DD/MM/YYYY HH:MM`.\nEx: `.agendar 21/03/2025 21:00 Sexta Ranqueada`")

        if scheduled_for < datetime.utcnow():
            return await ctx.reply("❌ A data informada já passou.")

        event_id = await EventRepository.create_event(
            guild_id=ctx.guild.id,
            created_by=ctx.author.id,
            title=titulo.strip(),
            scheduled_for=scheduled_for,
            max_players=10,
        )

        event = await EventRepository.get_event(event_id)
        view  = AgendaView(event_id, 10)
        self.bot.add_view(view)

        embed = build_embed(event, ctx.guild)
        msg   = await ctx.send(embed=embed, view=view)
        await EventRepository.set_message(event_id, ctx.channel.id, msg.id)

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    @commands.command(name="agenda")
    async def agenda(self, ctx: commands.Context, event_id: int = None):
        """Lista eventos agendados ou exibe o embed completo de um evento específico."""

        # .agenda <ID> — reposta o embed com botões de um evento específico
        if event_id is not None:
            event = await EventRepository.get_event(event_id)
            if not event:
                return await ctx.reply(f"❌ Evento #{event_id} não encontrado.")
            if event['guild_id'] != ctx.guild.id:
                return await ctx.reply("❌ Este evento não pertence a este servidor.")

            view = AgendaView(event_id, event['max_players'])
            if event['status'] != 'open':
                for item in view.children:
                    item.disabled = True
            else:
                self.bot.add_view(view)

            msg = await ctx.send(embed=build_embed(event, ctx.guild), view=view)

            # Atualiza referência da mensagem para que _refresh_event_message funcione
            if event['status'] == 'open':
                await EventRepository.set_message(event_id, ctx.channel.id, msg.id)

            try:
                await ctx.message.delete()
            except discord.Forbidden:
                pass
            return

        # .agenda — lista resumo de todos os eventos abertos
        events = await EventRepository.get_open_events(ctx.guild.id)

        if not events:
            return await ctx.reply("📭 Nenhum evento agendado no momento.")

        status_icon = {'open': '📅', 'started': '🚀'}
        status_label = {'open': 'Aberto', 'started': 'Iniciado'}

        embed = discord.Embed(
            title="📅 Agenda de Eventos",
            color=0x3498db
        )
        embed.description = f"**{len(events)}** evento(s) ativo(s)"

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        for e in events[:10]:
            ts    = int(e['scheduled_for'].replace(tzinfo=timezone.utc).timestamp())
            total = len(e['player_ids'])
            icon  = status_icon.get(e['status'], '📅')
            label = status_label.get(e['status'], e['status'])
            vagas_str = f"· `{e['max_players'] - total}` vagas" if e['status'] == 'open' else "· **Inscrições encerradas**"
            embed.add_field(
                name=f"{icon} #{e['id']} — {e['title']} `{label}`",
                value=(
                    f"🗓️ <t:{ts}:F>\n"
                    f"⏰ <t:{ts}:R>\n"
                    f"👥 `{total}/{e['max_players']}` confirmados {vagas_str}"
                ),
                inline=False,
            )

        embed.set_footer(text=".agenda <ID> para ver detalhes · .cancelar_agenda <ID> para cancelar")
        await ctx.reply(embed=embed)

    @commands.command(name="anular_agenda")
    @commands.has_permissions(administrator=True)
    async def anular_agenda(self, ctx: commands.Context, event_id: int):
        """Anula um evento silenciosamente (sem DM para os confirmados)."""
        event = await self._get_and_validate_event(ctx, event_id)
        if not event:
            return

        await EventRepository.cancel_event(event_id)

        if event.get('channel_id') and event.get('message_id'):
            try:
                ch  = ctx.guild.get_channel(event['channel_id'])
                msg = await ch.fetch_message(event['message_id'])
                updated = await EventRepository.get_event(event_id)
                await msg.edit(embed=build_embed(updated, ctx.guild), view=discord.ui.View())
            except Exception:
                pass

        await ctx.reply(
            f"🗑️ Evento **#{event_id} — {event['title']}** anulado silenciosamente (sem notificação aos confirmados).",
        )
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    @commands.command(name="cancelar_agenda")
    @commands.has_permissions(administrator=True)
    async def cancelar_agenda(self, ctx: commands.Context, event_id: int):
        """Cancela um evento agendado e notifica os confirmados."""
        event = await self._get_and_validate_event(ctx, event_id)
        if not event:
            return

        await EventRepository.cancel_event(event_id)

        # Atualiza o embed original
        if event.get('channel_id') and event.get('message_id'):
            try:
                ch  = ctx.guild.get_channel(event['channel_id'])
                msg = await ch.fetch_message(event['message_id'])
                updated = await EventRepository.get_event(event_id)
                view = discord.ui.View()
                for item in AgendaView(event_id, event['max_players']).children:
                    item.disabled = True
                await msg.edit(embed=build_embed(updated, ctx.guild), view=view)
            except Exception:
                pass

        # DM para confirmados
        cancelled_embed = discord.Embed(
            title="🚫 Evento Cancelado",
            description=(
                f"O evento **{event['title']}** foi cancelado pelo organizador.\n"
                f"Fique de olho em novos agendamentos!"
            ),
            color=0xe74c3c,
        )
        sent = 0
        for pid in event.get('player_ids', []):
            try:
                user = self.bot.get_user(pid) or await self.bot.fetch_user(pid)
                if user:
                    await user.send(embed=cancelled_embed)
                    sent += 1
            except (discord.Forbidden, discord.HTTPException):
                pass

        await ctx.reply(
            f"✅ Evento **#{event_id} — {event['title']}** cancelado.\n"
            f"📩 {sent} confirmado(s) notificado(s) por DM."
        )

    @commands.command(name="add_agenda")
    @commands.has_permissions(administrator=True)
    async def add_agenda(self, ctx: commands.Context, event_id: int, membro: discord.Member):
        """Adiciona um membro manualmente a um evento."""
        event = await self._get_and_validate_event(ctx, event_id)
        if not event:
            return

        if len(event['player_ids']) >= event['max_players']:
            return await ctx.reply(f"❌ Evento #{event_id} está lotado ({event['max_players']}/{event['max_players']}).")

        added = await EventRepository.add_player(event_id, membro.id)
        if not added:
            return await ctx.reply(f"❌ **{membro.display_name}** já está confirmado no evento #{event_id}.")

        await self._refresh_event_message(ctx.guild, event_id, event)
        await ctx.reply(f"✅ **{membro.display_name}** adicionado ao evento **#{event_id}**.")

    @commands.command(name="kick_agenda")
    @commands.has_permissions(administrator=True)
    async def kick_agenda(self, ctx: commands.Context, event_id: int, membro: discord.Member):
        """Remove um membro de um evento."""
        event = await self._get_and_validate_event(ctx, event_id)
        if not event:
            return

        removed = await EventRepository.remove_player(event_id, membro.id)
        if not removed:
            return await ctx.reply(f"❌ **{membro.display_name}** não está confirmado no evento #{event_id}.")

        await self._refresh_event_message(ctx.guild, event_id, event)
        await ctx.reply(f"✅ **{membro.display_name}** removido do evento **#{event_id}**.")

    @commands.command(name="iniciar_agenda")
    @commands.has_permissions(administrator=True)
    async def iniciar_agenda(self, ctx: commands.Context, event_id: int):
        """Inicia o evento: pinga todos os confirmados e fecha as inscrições."""
        event = await self._get_and_validate_event(ctx, event_id)
        if not event:
            return

        if not event['player_ids']:
            return await ctx.reply(f"❌ Evento #{event_id} não tem nenhum confirmado.")

        await EventRepository.start_event(event_id)

        # Desabilita botões no embed original (silencioso se não encontrar a mensagem)
        await self._refresh_event_message(ctx.guild, event_id, await EventRepository.get_event(event_id))

        # Pinga todos os confirmados
        mentions = " ".join(f"<@{pid}>" for pid in event['player_ids'])
        total = len(event['player_ids'])
        embed = discord.Embed(
            title=f"📣 {event['title']}",
            description=f"O evento foi iniciado! **{total}** confirmado(s) convocado(s).",
            color=0x2ecc71
        )
        embed.add_field(name="Confirmados", value=mentions, inline=False)
        await ctx.send(embed=embed)

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    async def _refresh_event_message(self, guild: discord.Guild, event_id: int, old_event: dict):
        """Atualiza o embed da mensagem do evento no canal."""
        if not old_event.get('channel_id') or not old_event.get('message_id'):
            return
        try:
            ch    = guild.get_channel(old_event['channel_id'])
            msg   = await ch.fetch_message(old_event['message_id'])
            event = await EventRepository.get_event(event_id)
            view  = AgendaView(event_id, event['max_players'])
            if event['status'] != 'open':
                for item in view.children:
                    item.disabled = True
            await msg.edit(embed=build_embed(event, guild), view=view)
        except Exception as e:
            logger.warning(f"Não foi possível atualizar embed do evento #{event_id}: {e}")

    @commands.command(name="notificar_agenda")
    @commands.has_permissions(administrator=True)
    async def notificar_agenda(self, ctx: commands.Context, event_id: int):
        """Envia manualmente a notificação de um evento para todos os confirmados.
        Só funciona se o evento ainda não começou ou até 30 min após o início."""
        event = await self._get_and_validate_event(ctx, event_id, require_open=False)
        if not event:
            return

        if not event['player_ids']:
            return await ctx.reply(f"❌ Evento #{event_id} não tem nenhum confirmado.")

        now = datetime.utcnow()
        dt  = event['scheduled_for']
        diff_after_start = (now - dt).total_seconds()

        if diff_after_start > 1800:  # mais de 30 min após o início
            return await ctx.reply(
                f"❌ Não é possível notificar. O evento já começou há mais de 30 minutos "
                f"({int(diff_after_start // 60)} min atrás)."
            )

        await self._send_reminder(event, '30min')
        await ctx.reply(f"✅ Notificação enviada por DM para **{len(event['player_ids'])}** confirmado(s) do evento #{event_id}.")

    # --- ERROR HANDLERS ---
    @agendar.error
    @anular_agenda.error
    @cancelar_agenda.error
    @add_agenda.error
    @kick_agenda.error
    @iniciar_agenda.error
    @notificar_agenda.error
    async def agenda_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("⛔ Apenas administradores podem usar este comando.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ Membro não encontrado. Mencione alguém do servidor.")
        elif isinstance(error, commands.MissingRequiredArgument):
            examples = {
                'agendar': '`.agendar 21/03/2025 21:00 Sexta Ranqueada`',
                'anular_agenda': '`.anular_agenda <ID>`',
                'cancelar_agenda': '`.cancelar_agenda <ID>`',
                'add_agenda': '`.add_agenda <ID> @membro`',
                'kick_agenda': '`.kick_agenda <ID> @membro`',
                'iniciar_agenda': '`.iniciar_agenda <ID>`',
            }
            ex = examples.get(ctx.command.name, '')
            await ctx.reply(f"❌ Argumento faltando. Ex: {ex}")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Argumento inválido. O ID do evento deve ser um número.")
        else:
            logger.error(f"Erro em comando de agenda: {error}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Agenda(bot))
