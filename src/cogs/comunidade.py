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
        
        # Salva no banco (add_xp cria o perfil se não existir)
        leveled_up, new_level = await CommunityRepository.add_xp(message.author.id, xp_gain, has_media)
        self.xp_cooldown[message.author.id] = datetime.utcnow()

        if leveled_up:
            await message.add_reaction("🆙")

    # --- EVENTO DE VOZ ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Engine de Ganho de XP por Voz"""
        if member.bot: return

        # 1. Entrou em um canal (e não estava em nenhum antes)
        if before.channel is None and after.channel is not None:
            # Ignora se entrar mutado/ensurdecido ou no canal de AFK
            if after.self_mute or after.self_deaf or (member.guild.afk_channel and after.channel.id == member.guild.afk_channel.id):
                return 
            
            self.voice_sessions[member.id] = datetime.utcnow()
            print(f"[Voice XP] {member.name} entrou no canal {after.channel.name}. Contando...")

        # 2. Saiu de um canal (ou desconectou)
        elif before.channel is not None and after.channel is None:
            if member.id in self.voice_sessions:
                start_time = self.voice_sessions.pop(member.id)
                duration = datetime.utcnow() - start_time
                minutes = int(duration.total_seconds() / 60)
                
                if minutes >= 1: # Mínimo 1 minuto para ganhar XP
                    # Cálculo: 10 XP por minuto falado
                    xp_earned = minutes * 10 
                    
                    leveled_up, new_lvl = await CommunityRepository.add_xp(member.id, xp_earned, has_media=False)
                    print(f"[Voice XP] {member.name} ganhou {xp_earned} XP por {minutes} minutos em call.")

        # 3. Mudou de status (Mutou/Desmutou no meio da call)
        elif before.channel is not None and after.channel is not None:
            # Se o usuário se mutou/ensurdeceu agora: Para de contar
            if not before.self_mute and after.self_mute:
                if member.id in self.voice_sessions:
                    start_time = self.voice_sessions.pop(member.id)
                    duration = datetime.utcnow() - start_time
                    minutes = int(duration.total_seconds() / 60)
                    if minutes >= 1:
                        await CommunityRepository.add_xp(member.id, minutes * 10)
                        print(f"[Voice XP] {member.name} mutou. Sessão encerrada com {minutes * 10} XP.")

            # Se o usuário se desmutou: Começa a contar de novo
            elif before.self_mute and not after.self_mute:
                self.voice_sessions[member.id] = datetime.utcnow()
                print(f"[Voice XP] {member.name} desmutou. Iniciando nova sessão.")


    @commands.Cog.listener()
    async def on_ready(self):
        """Recupera sessões de voz se o bot reiniciar"""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            for member in guild.voice_channels[0].members if guild.voice_channels else []:
                # Se o membro já está em call e não está mutado, começa a contar de agora
                if member.voice and not member.voice.self_mute and not member.voice.self_deaf and not member.bot:
                     self.voice_sessions[member.id] = datetime.utcnow()

    # --- COMANDOS ---
    @commands.command(name="social", aliases=["perfil_social", "rank", "comunidade"])
    async def social_profile(self, ctx, member: discord.Member = None):
        """Exibe o Cartão de Comunidade do usuário"""
        target = member or ctx.author
        
        # Busca dados no Banco
        profile = await CommunityRepository.get_profile(target.id)
        
        # --- CORREÇÃO: CRIA PERFIL SE NÃO EXISTIR ---
        if not profile:
            # Adiciona 0 de XP para forçar a criação do registro no banco
            await CommunityRepository.add_xp(target.id, 0)
            # Busca novamente agora que o registro existe
            profile = await CommunityRepository.get_profile(target.id)
        # --------------------------------------------

        # Busca Posição no Ranking
        rank_pos = await CommunityRepository.get_ranking_position(target.id)
        
        status_color = {
            discord.Status.online: 0x2ecc71,
            discord.Status.idle: 0xf1c40f,
            discord.Status.dnd: 0xe74c3c,
            discord.Status.offline: 0x95a5a6
        }.get(target.status, 0x2b2d31)

        embed = discord.Embed(color=status_color)
        embed.set_author(name=f"Perfil da Comunidade: {target.display_name}", icon_url=target.display_avatar.url)
        embed.set_thumbnail(url=target.display_avatar.url)

        # Calcula XP para próximo nível
        xp_next_level = int(profile.level * 100 * 1.2)
        progress_bar = self.generate_progress_bar(profile.xp, xp_next_level)
        
        embed.add_field(
            name=f"🏅 Nível {profile.level}",
            value=f"{progress_bar}\n`{profile.xp} / {xp_next_level} XP`",
            inline=False
        )

        stats_text = (
            f"🏆 **Rank:** #{rank_pos}\n"
            f"💬 **Mensagens:** {profile.messages_sent}\n"
            f"📸 **Mídia Enviada:** {profile.media_sent}"
        )
        embed.add_field(name="📊 Estatísticas", value=stats_text, inline=True)

        top_role = target.top_role.mention if target.top_role.name != "@everyone" else "Sem Cargo"
        joined_at = f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "N/A"
        created_at = f"<t:{int(target.created_at.timestamp())}:D>"
        
        # Se o usuário acabou de ser criado, last_message_at pode ser None ou igual a joined_at
        # A função get_activity_status lida com None, mas aqui garantimos que funcione
        activity_status = self.get_activity_status(profile.last_message_at)

        info_text = (
            f"🎭 **Cargo:** {top_role}\n"
            f"📅 **Entrou:** {joined_at}\n"
            f"🎂 **Criou Conta:** {created_at}\n"
            f"📡 **Status:** {activity_status}"
        )
        embed.add_field(name="🆔 Identidade", value=info_text, inline=True)
        embed.set_footer(text="Mande mensagens para ganhar XP • Imagens dão bônus!")
        
        view = BaseInteractiveView(timeout=60)
        view.message = await ctx.reply(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Community(bot))