import discord
import random
from discord.ext import commands
from datetime import datetime, timedelta
from src.database.repositories import CommunityRepository
from src.utils.views import BaseInteractiveView

class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cooldown simples em memória para evitar farm de XP (spam de texto)
        self.xp_cooldown = {} 
        
        # Dicionário para rastrear tempo de voz: {user_id: datetime_entrada}
        self.voice_sessions = {}

    def generate_progress_bar(self, current, total, length=12):
        """Gera uma barra visual estilo Gamer"""
        if total == 0: total = 1
        percent = min(1.0, current / total)
        filled = int(length * percent)
        # Caracteres de bloco para barra mais bonita
        bar = "█" * filled + "░" * (length - filled) 
        return f"`{bar}` **{int(percent * 100)}%**"

    def get_activity_status(self, last_msg_time):
        """Define o 'título' de atividade do usuário com emojis"""
        if not last_msg_time: return "👻 **Fantasma** (Inativo)"
        
        diff = datetime.utcnow() - last_msg_time
        
        if diff < timedelta(hours=1): return "🟢 **Online & Ativo**"
        if diff < timedelta(days=1): return "🟡 **Visto Hoje**"
        if diff < timedelta(days=7): return "🟠 **Casual**"
        if diff < timedelta(days=30): return "🔴 **Ausente**"
        return "💀 **Inativo**"

    # --- EVENTO DE TEXTO ---
    @commands.Cog.listener()
    async def on_message(self, message):
        """Engine de Ganho de XP por Texto"""
        if message.author.bot: return
        if not message.guild: return

        # Checa cooldown (5 segundos entre ganhos de XP)
        last_xp = self.xp_cooldown.get(message.author.id)
        if last_xp and (datetime.utcnow() - last_xp).total_seconds() < 5:
            return 

        xp_gain = random.randint(15, 25)
        has_media = len(message.attachments) > 0
        
        # Salva no banco
        leveled_up, new_level = await CommunityRepository.add_xp(message.author.id, xp_gain, has_media)
        self.xp_cooldown[message.author.id] = datetime.utcnow()

        if leveled_up:
            await message.add_reaction("🆙")

    # --- EVENTO DE VOZ ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Engine de Ganho de XP por Voz"""
        if member.bot: return

        # 1. Entrou em um canal
        if before.channel is None and after.channel is not None:
            if after.self_mute or after.self_deaf or (member.guild.afk_channel and after.channel.id == member.guild.afk_channel.id):
                return 
            self.voice_sessions[member.id] = datetime.utcnow()
            print(f"[Voice] {member.name} entrou.")

        # 2. Saiu de um canal
        elif before.channel is not None and after.channel is None:
            if member.id in self.voice_sessions:
                start_time = self.voice_sessions.pop(member.id)
                duration = datetime.utcnow() - start_time
                minutes = int(duration.total_seconds() / 60)
                
                if minutes >= 1: 
                    xp_earned = minutes * 10 
                    await CommunityRepository.add_xp(member.id, xp_earned, has_media=False)
                    print(f"[Voice] {member.name} ganhou {xp_earned} XP.")

        # 3. Mudou de status
        elif before.channel is not None and after.channel is not None:
            if not before.self_mute and after.self_mute:
                if member.id in self.voice_sessions:
                    start_time = self.voice_sessions.pop(member.id)
                    duration = datetime.utcnow() - start_time
                    minutes = int(duration.total_seconds() / 60)
                    if minutes >= 1:
                        await CommunityRepository.add_xp(member.id, minutes * 10)

            elif before.self_mute and not after.self_mute:
                self.voice_sessions[member.id] = datetime.utcnow()

    @commands.Cog.listener()
    async def on_ready(self):
        """Recupera sessões de voz se o bot reiniciar"""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            for member in guild.voice_channels[0].members if guild.voice_channels else []:
                if member.voice and not member.voice.self_mute and not member.voice.self_deaf and not member.bot:
                     self.voice_sessions[member.id] = datetime.utcnow()

    # --- COMANDO SOCIAL ---
    @commands.command(name="social", aliases=["perfil_social", "rank", "comunidade"])
    async def social_profile(self, ctx, member: discord.Member = None):
        """Exibe o Cartão de Comunidade do usuário"""
        target = member or ctx.author
        
        # Busca dados no Banco
        profile = await CommunityRepository.get_profile(target.id)
        
        if not profile:
            await CommunityRepository.add_xp(target.id, 0)
            profile = await CommunityRepository.get_profile(target.id)

        rank_pos = await CommunityRepository.get_ranking_position(target.id)
        
        # Cores dinâmicas
        status_color = {
            discord.Status.online: 0x43b581,
            discord.Status.idle: 0xfaa61a,
            discord.Status.dnd: 0xf04747,
            discord.Status.offline: 0x747f8d
        }.get(target.status, 0x2b2d31)

        # Criação do Embed Maior e Mais Bonito
        embed = discord.Embed(title=f"🛡️ Cartão de Membro: {target.display_name}", color=status_color)
        embed.set_thumbnail(url=target.display_avatar.url)

        # --- CÁLCULOS ---
        xp_next_level = int(profile.level * 100 * 1.2)
        xp_current_level_start = int((profile.level - 1) * 100 * 1.2) if profile.level > 1 else 0
        xp_in_level = profile.xp - xp_current_level_start
        if xp_in_level < 0: xp_in_level = 0
        
        progress_bar = self.generate_progress_bar(profile.xp, xp_next_level)

        hours = profile.voice_minutes // 60
        minutes = profile.voice_minutes % 60
        voice_time_str = f"{hours}h {minutes}m"

        # --- SEÇÃO 1: NÍVEL E PROGRESSO ---
        embed.add_field(
            name=f"🏆 Nível {profile.level}",
            value=f"{progress_bar}\nTarget: **{profile.xp}** / {xp_next_level} XP",
            inline=False
        )

        # --- SEÇÃO 2: ESTATÍSTICAS EM COLUNAS ---
        stats_msg = (
            f"✉️ **Mensagens:** `{profile.messages_sent}`\n"
            f"🖼️ **Mídia:** `{profile.media_sent}`\n"
            f"💎 **Rank Global:** `#{rank_pos}`"
        )
        embed.add_field(name="📊 Atividade", value=stats_msg, inline=True)

        # Coluna 2: Dados da Conta
        joined_at = f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "N/A"
        created_at = f"<t:{int(target.created_at.timestamp())}:d>"
        
        account_info = (
            f"📅 **Entrou:** {joined_at}\n"
            f"🎂 **Criada em:** {created_at}\n"
            f"🎙️ **Tempo Voz:** `{voice_time_str}`*"
        )
        embed.add_field(name="👤 Conta", value=account_info, inline=True)

        # --- SEÇÃO 3: STATUS E CARGOS ---
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)
        
        activity_status = self.get_activity_status(profile.last_message_at)
        
        # Roles
        roles = [r.mention for r in target.roles if r.name != "@everyone"]
        roles.reverse() 
        roles_str = " ".join(roles[:3]) if roles else "Sem cargos"
        if len(roles) > 3: roles_str += f" (+{len(roles)-3})"

        embed.add_field(name="📡 Status Atual", value=activity_status, inline=True)
        embed.add_field(name="🎭 Cargos Principais", value=roles_str, inline=True)

        embed.set_footer(text="*Tempo de voz estimado baseado no XP ganho.")
        
        view = BaseInteractiveView(timeout=60)
        view.message = await ctx.reply(embed=embed, view=view)


    # --- NOVO COMANDO: RANKING XP ---
    @commands.command(name="ranking_xp", aliases=["topxp", "top_social"])
    async def ranking_xp(self, ctx):
        """Mostra o Top 10 membros mais ativos da comunidade"""
        
        # Busca os top 10 perfis do banco
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
            # Tenta pegar o membro no servidor para mostrar o nome atual
            member = ctx.guild.get_member(p.discord_id)
            
            # Se o membro saiu do servidor, mostramos "Usuário Saiu"
            display_name = member.display_name if member else "Usuário Saiu"
            
            # Medalhas para o top 3
            if i == 0: icon = "🥇"
            elif i == 1: icon = "🥈"
            elif i == 2: icon = "🥉"
            else: icon = f"`{i+1}.`"

            rank_text += f"{icon} **{display_name}** • Nível **{p.level}** ({p.xp} XP)\n"

        embed.add_field(name="Top 10", value=rank_text, inline=False)
        embed.set_footer(text="Continue interagindo para subir no ranking!")
        
        view = BaseInteractiveView(timeout=60)
        view.message = await ctx.reply(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Community(bot))