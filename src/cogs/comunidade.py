import discord
import random
from discord.ext import commands
from datetime import datetime, timedelta
from src.database.repositories import CommunityRepository
from src.utils.views import BaseInteractiveView


class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.xp_cooldown = {}
        self.voice_sessions = {}

    def generate_progress_bar(self, current, total, length=21):
        if total == 0: total = 1
        percent = min(1.0, current / total)
        filled = int(length * percent)
        return "█" * filled + "░" * (length - filled)

    def get_activity_status(self, last_msg_time):
        if not last_msg_time: return "👻 **Fantasma**"
        diff = datetime.utcnow() - last_msg_time
        if diff < timedelta(hours=1): return "🟢 **Online & Ativo**"
        if diff < timedelta(days=1): return "🟡 **Visto Hoje**"
        if diff < timedelta(days=7): return "🟠 **Casual**"
        if diff < timedelta(days=30): return "🔴 **Ausente**"
        return "💀 **Inativo**"

    async def _finish_voice_session(self, member):
        """Finaliza a sessão de um membro, calcula XP e remove do tracker."""
        if member.id in self.voice_sessions:
            start_time = self.voice_sessions.pop(member.id)
            duration = datetime.utcnow() - start_time
            minutes = int(duration.total_seconds() / 60)
            if minutes >= 1:
                xp_earned = minutes * 10
                await CommunityRepository.add_xp(member.id, xp_earned, has_media=False, voice_minutes=minutes)
                print(f"[Voice] {member.name} ganhou {xp_earned} XP (sessão finalizada).")
            return True
        return False

    @commands.Cog.listener()
    async def on_message(self, message):
        """Engine de Ganho de XP por Texto"""
        if message.author.bot: return
        if not message.guild: return

        last_xp = self.xp_cooldown.get(message.author.id)
        if last_xp and (datetime.utcnow() - last_xp).total_seconds() < 5:
            return

        xp_gain = random.randint(15, 25)
        has_media = len(message.attachments) > 0

        leveled_up, new_level = await CommunityRepository.add_xp(message.author.id, xp_gain, has_media)
        self.xp_cooldown[message.author.id] = datetime.utcnow()

        if leveled_up:
            await message.add_reaction("🆙")
            # Notificação de level up com embed
            xp_next = int(new_level * 100 * 1.2)
            embed = discord.Embed(
                title="⬆️ LEVEL UP!",
                description=f"🎉 {message.author.mention} subiu para o **Nível {new_level}**!",
                color=0xffd700
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_footer(text=f"Próximo nível em {xp_next} XP")
            await message.channel.send(embed=embed, delete_after=20)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Engine de Ganho de XP por Voz com verificação de 2+ pessoas"""
        if member.bot: return

        # Lógica de saída / mute / troca de canal
        if (before.channel is not None and after.channel is None) or \
           (before.channel is not None and not before.self_mute and after.self_mute) or \
           (before.channel is not None and before.channel != after.channel):

            await self._finish_voice_session(member)

            old_channel = before.channel
            if old_channel:
                valid_members = [m for m in old_channel.members if not m.bot]
                if len(valid_members) < 2:
                    for remaining in valid_members:
                        if remaining.id in self.voice_sessions:
                            await self._finish_voice_session(remaining)
                            print(f"[Voice] Contagem parada para {remaining.name} (ficou sozinho).")

        # Lógica de entrada / desmute / troca de canal
        if (after.channel is not None and before.channel is None) or \
           (after.channel is not None and before.self_mute and not after.self_mute) or \
           (after.channel is not None and before.channel != after.channel):

            current_channel = after.channel

            if after.self_mute or after.self_deaf or \
               (member.guild.afk_channel and current_channel.id == member.guild.afk_channel.id):
                return

            valid_members = [m for m in current_channel.members if not m.bot]

            if len(valid_members) >= 2:
                if member.id not in self.voice_sessions:
                    self.voice_sessions[member.id] = datetime.utcnow()
                    print(f"[Voice] {member.name} começou a ganhar XP ({len(valid_members)} pessoas).")

                for existing in valid_members:
                    if existing.id != member.id:
                        if not existing.voice.self_mute and not existing.voice.self_deaf:
                            if existing.id not in self.voice_sessions:
                                self.voice_sessions[existing.id] = datetime.utcnow()
                                print(f"[Voice] {existing.name} começou a ganhar XP (chegou companhia).")

    @commands.Cog.listener()
    async def on_ready(self):
        """Recupera sessões de voz ativas ao reiniciar o bot."""
        await self.bot.wait_until_ready()
        self.voice_sessions = {}

        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                valid_members = [m for m in channel.members if not m.bot]
                if len(valid_members) >= 2:
                    for member in valid_members:
                        if member.voice and not member.voice.self_mute and not member.voice.self_deaf:
                            self.voice_sessions[member.id] = datetime.utcnow()
                            print(f"[Voice Restore] Sessão recuperada para {member.name}")

    @commands.command(name="social", aliases=["perfil_social", "rank", "comunidade"])
    async def social_profile(self, ctx, member: discord.Member = None):
        """Exibe o Cartão de Comunidade do usuário"""
        target = member or ctx.author

        profile = await CommunityRepository.get_profile(target.id)
        if not profile:
            await CommunityRepository.add_xp(target.id, 0)
            profile = await CommunityRepository.get_profile(target.id)

        rank_pos = await CommunityRepository.get_ranking_position(target.id)

        status_color = {
            discord.Status.online: 0x43b581,
            discord.Status.idle: 0xfaa61a,
            discord.Status.dnd: 0xf04747,
            discord.Status.offline: 0x747f8d
        }.get(target.status, 0x2b2d31)

        embed = discord.Embed(title=f"🛡️ Cartão de Membro: {target.display_name}", color=status_color)
        embed.set_thumbnail(url=target.display_avatar.url)

        xp_next_level = int(profile.level * 100 * 1.2)
        progress_bar_visual = self.generate_progress_bar(profile.xp, xp_next_level)
        percent_val = int((profile.xp / xp_next_level) * 100) if xp_next_level > 0 else 100

        hours = profile.voice_minutes // 60
        minutes = profile.voice_minutes % 60
        voice_time_str = f"{hours}h {minutes}m"

        level_info = (
            f"```ini\n"
            f"[{progress_bar_visual}] {percent_val}%\n"
            f"[ XP Atual: {profile.xp} / {xp_next_level} ]\n"
            f"```"
        )
        embed.add_field(name=f"🏆 Nível {profile.level}", value=level_info, inline=False)

        stats_block = (
            f"```yaml\n"
            f"Rank Global:   #{rank_pos}\n"
            f"Tempo Voz:     {voice_time_str}\n"
            f"Mensagens:     {profile.messages_sent}\n"
            f"Mídia Env.:    {profile.media_sent}\n"
            f"```"
        )
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="📊 Estatísticas de Atividade", value=stats_block, inline=False)

        joined_at = f"<t:{int(target.joined_at.timestamp())}:D>" if target.joined_at else "N/A"
        created_at = f"<t:{int(target.created_at.timestamp())}:D>"
        activity_status = self.get_activity_status(profile.last_message_at)

        roles = [r.mention for r in target.roles if r.name != "@everyone"]
        roles.reverse()
        roles_str = " ".join(roles[:3]) if roles else "Sem cargos"
        if len(roles) > 3: roles_str += f" (+{len(roles)-3})"

        embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="📅 Entrou em", value=joined_at, inline=True)
        embed.add_field(name="🎂 Criou em", value=created_at, inline=True)
        embed.add_field(name="📡 Status", value=activity_status, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="🎭 Cargos", value=roles_str, inline=False)
        embed.set_footer(text=f"ID do Usuário: {target.id}")

        view = BaseInteractiveView(timeout=60)
        view.message = await ctx.reply(embed=embed, view=view)

    @commands.command(name="ranking_xp", aliases=["topxp", "top_social"])
    async def ranking_xp(self, ctx):
        """Mostra o Top 10 membros mais ativos da comunidade"""
        top_profiles = await CommunityRepository.get_top_xp(10)

        if not top_profiles:
            return await ctx.reply("📭 O ranking de comunidade ainda está vazio.")

        embed = discord.Embed(
            title="🏆 Ranking de Atividade da Comunidade",
            description="Os membros mais ativos (Texto e Voz)",
            color=0xffd700
        )

        rank_text = ""
        for i, p in enumerate(top_profiles):
            member = ctx.guild.get_member(p.discord_id)
            display_name = member.display_name if member else f"User {p.discord_id}"

            if i == 0: icon = "🥇"
            elif i == 1: icon = "🥈"
            elif i == 2: icon = "🥉"
            else: icon = f"`{i+1}.`"

            hours = p.voice_minutes // 60
            mins = p.voice_minutes % 60
            voice_str = f"{hours}h{mins}m" if hours > 0 else f"{mins}m"

            rank_text += f"{icon} **{display_name}** • Nível **{p.level}** • 🎙️ {voice_str}\n"

        embed.add_field(name="Top 10 Geral", value=rank_text, inline=False)
        embed.set_footer(text="Continue interagindo para subir no ranking!")

        view = BaseInteractiveView(timeout=60)
        view.message = await ctx.reply(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Community(bot))
