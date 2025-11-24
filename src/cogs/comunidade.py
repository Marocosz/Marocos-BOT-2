import discord
import random
from discord.ext import commands
from datetime import datetime, timedelta
from src.database.repositories import CommunityRepository
from src.utils.views import BaseInteractiveView

class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cooldown simples em memória para evitar farm de XP (spam)
        # Formato: {user_id: datetime_ultima_msg}
        self.xp_cooldown = {} 

    def generate_progress_bar(self, current, total, length=10):
        """Gera uma barra visual: [████░░░░░░]"""
        if total == 0: total = 1
        percent = min(1.0, current / total)
        filled = int(length * percent)
        bar = "█" * filled + "░" * (length - filled)
        return f"[{bar}] {int(percent * 100)}%"

    def get_activity_status(self, last_msg_time):
        """Define o 'título' de atividade do usuário"""
        if not last_msg_time: return "👻 Fantasma"
        
        diff = datetime.utcnow() - last_msg_time
        
        if diff < timedelta(hours=1): return "🔥 Viciado (Online agora)"
        if diff < timedelta(days=1): return "🟢 Ativo Diário"
        if diff < timedelta(days=7): return "🟡 Casual"
        if diff < timedelta(days=30): return "💤 Hibernando"
        return "💀 Morto-Vivo"

    @commands.Cog.listener()
    async def on_message(self, message):
        """Engine de Ganho de XP"""
        if message.author.bot: return
        if not message.guild: return

        # Checa cooldown (5 segundos entre ganhos de XP)
        last_xp = self.xp_cooldown.get(message.author.id)
        if last_xp and (datetime.utcnow() - last_xp).total_seconds() < 5:
            return # Mensagem muito rápida, não ganha XP

        # XP Aleatório entre 15 e 25
        xp_gain = random.randint(15, 25)
        has_media = len(message.attachments) > 0
        
        # Salva no banco
        leveled_up, new_level = await CommunityRepository.add_xp(message.author.id, xp_gain, has_media)
        
        # Atualiza cooldown
        self.xp_cooldown[message.author.id] = datetime.utcnow()

        # Notifica Level Up (Reação simples para não poluir chat)
        if leveled_up:
            await message.add_reaction("🆙")
            # Opcional: Mandar mensagem de parabéns
            # await message.channel.send(f"🎉 {message.author.mention} subiu para o **Nível {new_level}**!")

    @commands.command(name="social", aliases=["perfil_social", "rank", "comunidade"])
    async def social_profile(self, ctx, member: discord.Member = None):
        """Exibe o Cartão de Comunidade do usuário"""
        target = member or ctx.author
        
        # Busca dados no Banco
        profile = await CommunityRepository.get_profile(target.id)
        
        if not profile:
            await ctx.reply("📭 Este usuário ainda não possui registro social (precisa mandar mensagens no chat).")
            return

        # Busca Posição no Ranking
        rank_pos = await CommunityRepository.get_ranking_position(target.id)
        
        # Cores baseadas no status do Discord
        status_color = {
            discord.Status.online: 0x2ecc71,
            discord.Status.idle: 0xf1c40f,
            discord.Status.dnd: 0xe74c3c,
            discord.Status.offline: 0x95a5a6
        }.get(target.status, 0x2b2d31)

        embed = discord.Embed(color=status_color)
        
        # Cabeçalho
        embed.set_author(name=f"Perfil da Comunidade: {target.display_name}", icon_url=target.display_avatar.url)
        embed.set_thumbnail(url=target.display_avatar.url)

        # --- BARRA DE PROGRESSO E NÍVEL ---
        xp_next_level = int(profile.level * 100 * 1.2)
        progress_bar = self.generate_progress_bar(profile.xp, xp_next_level)
        
        embed.add_field(
            name=f"🏅 Nível {profile.level}",
            value=f"{progress_bar}\n`{profile.xp} / {xp_next_level} XP`",
            inline=False
        )

        # --- ESTATÍSTICAS ---
        stats_text = (
            f"🏆 **Rank:** #{rank_pos}\n"
            f"💬 **Mensagens:** {profile.messages_sent}\n"
            f"📸 **Mídia Enviada:** {profile.media_sent}"
        )
        embed.add_field(name="📊 Estatísticas", value=stats_text, inline=True)

        # --- INFOS DO DISCORD ---
        # Pega o cargo mais alto (excluindo @everyone)
        top_role = target.top_role.mention if target.top_role.name != "@everyone" else "Sem Cargo"
        
        # Formata datas
        joined_at = f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "N/A"
        created_at = f"<t:{int(target.created_at.timestamp())}:D>"
        
        activity_status = self.get_activity_status(profile.last_message_at)

        info_text = (
            f"🎭 **Cargo:** {top_role}\n"
            f"📅 **Entrou:** {joined_at}\n"
            f"🎂 **Criou Conta:** {created_at}\n"
            f"📡 **Status:** {activity_status}"
        )
        embed.add_field(name="🆔 Identidade", value=info_text, inline=True)

        # --- FOOTER ---
        embed.set_footer(text="Mande mensagens para ganhar XP • Imagens dão bônus!")
        
        # Usa a BaseView para ter o timeout caso queira adicionar botões futuros
        view = BaseInteractiveView(timeout=60)
        view.message = await ctx.reply(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Community(bot))