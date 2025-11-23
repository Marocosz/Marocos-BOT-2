import discord
from discord.ext import commands
import asyncio # Necessário para tasks e sleeps

# --- VIEW DE CONFIRMAÇÃO ---
class ClearConfirmationView(discord.ui.View):
    def __init__(self, admin_cog, ctx, mode):
        super().__init__(timeout=30)
        self.admin_cog = admin_cog
        self.ctx = ctx
        self.mode = mode # 'bot' ou 'all'
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Apenas o autor do comando (Admin) pode confirmar
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("⛔ Apenas o autor do comando pode confirmar.", ephemeral=True)
            return False
        # Apenas Admins podem usar comandos de limpeza
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Você não tem permissão de administrador.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Sim, Tenho Certeza", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer() # Acknowledge o clique enquanto a limpeza acontece
        
        # Inicia a limpeza através do cog
        await self.admin_cog.execute_clear(self.ctx, self.mode)
        
        # Deleta a mensagem de confirmação
        await self.ctx.message.delete()
        await interaction.message.delete()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Limpeza cancelada.", view=None)

    async def on_timeout(self):
        # Limpa a view se o tempo acabar
        try:
            await self.ctx.message.edit(view=None)
        except:
            pass

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def execute_clear(self, ctx: commands.Context, mode: str):
        """Função que executa a limpeza real (chamada pelo botão)."""
        
        def is_bot_message(message: discord.Message):
            # Checa se a mensagem é do bot logado
            return message.author == self.bot.user

        # Se o modo for 'bot', usa o filtro; se for 'all', não usa filtro (apaga tudo).
        if mode == 'bot':
            # Filtro para apagar APENAS mensagens do bot
            check = is_bot_message
            feedback_msg = "✅ Mensagens do bot apagadas!"
        else: # mode == 'all'
            # Sem filtro (apaga todas as mensagens)
            check = lambda m: True
            feedback_msg = "✅ Todas as mensagens apagadas!"

        try:
            # Apaga as mensagens em lote
            # Note: fetch_before=True é crucial para obter mensagens anteriores à mensagem do comando.
            deleted = await ctx.channel.purge(limit=None, check=check, before=ctx.message)
            
            # Envia feedback (após o delete, o que pode ser problemático se o canal ficar vazio)
            await ctx.channel.send(f"{feedback_msg} ({len(deleted)} mensagens).", delete_after=5)

        except discord.Forbidden:
            await ctx.channel.send("⛔ Erro: Não tenho permissão para gerenciar mensagens neste canal.", delete_after=10)
        except Exception as e:
            await ctx.channel.send(f"⛔ Erro durante a limpeza: {e}", delete_after=10)


    @commands.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def clear_bot_messages(self, ctx: commands.Context):
        """Apaga apenas as mensagens enviadas por este bot no canal."""
        
        # Envia a confirmação
        await ctx.reply("⚠️ Tem certeza que deseja apagar **apenas as mensagens do BOT** neste canal?", 
                        view=ClearConfirmationView(self, ctx, 'bot'))

    @commands.command(name="clear_all")
    @commands.has_permissions(administrator=True)
    async def clear_all_messages(self, ctx: commands.Context):
        """Apaga TODAS as mensagens de todos os usuários no canal (Admin)."""
        
        # Envia a confirmação
        await ctx.reply("🔴 ATENÇÃO! Tem certeza que deseja apagar **TODAS** as mensagens neste canal? Esta ação é IRREVERSÍVEL.", 
                        view=ClearConfirmationView(self, ctx, 'all'))


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))