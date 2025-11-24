import discord
from discord.ext import commands
import asyncio
import logging # Adicionado para logging

logger = logging.getLogger("admin")

# --- VIEW DE CONFIRMAÇÃO ---
class ClearConfirmationView(discord.ui.View):
    def __init__(self, admin_cog, ctx, mode):
        # Aumentado o timeout para dar tempo de resposta
        super().__init__(timeout=60) 
        self.admin_cog = admin_cog
        self.ctx = ctx
        self.mode = mode # 'bot' ou 'all'
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 1. Checagem de Concorrência: Apenas o Admin original e o Admin que clicou.
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("⛔ Apenas o Admin que iniciou este comando pode interagir.", ephemeral=True)
            return False
        
        # 2. Checagem de Permissão (redundante, mas seguro)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Você não tem permissão de administrador.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Sim, Tenho Certeza", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop() # Encerra o View

        # 1. BLOQUEIO DE CONCORRÊNCIA e FEEDBACK DE PROGRESSO
        # Desativa todos os botões Imediatamente (Anticoncorrência)
        for item in self.children:
            item.disabled = True
        
        try:
            await interaction.response.edit_message(
                content="🔄 Iniciando limpeza... Aguarde (o bot pode demorar dependendo do volume).", 
                view=self # Edita com os botões desativados
            )
        except Exception as e:
            logger.error(f"Falha ao editar mensagem de progresso: {e}")
            # Se a interação falhar aqui, executamos a limpeza mesmo assim, mas o feedback visual será perdido.
            pass

        try:
            # 2. Executa a limpeza real
            deleted_count = await self.admin_cog.execute_clear(self.ctx, self.mode)
            
            # 3. Limpeza Final: Apaga a mensagem de confirmação e a mensagem original do comando.
            # Nota: Apagamos a mensagem do comando original ctx.message antes do feedback final.
            await self.ctx.message.delete()
            await interaction.message.delete()
            
            # 4. Envia feedback final (delete_after garante que não fique spam)
            await self.ctx.channel.send(f"✅ Limpeza concluída! ({deleted_count} mensagens apagadas).", delete_after=5)

        except Exception as e:
            logger.error(f"Erro fatal na execução da limpeza: {e}")
            await self.ctx.channel.send(f"⛔ ERRO FATAL: Falha ao apagar mensagens. Verifique as permissões do bot. Detalhe: {e}", delete_after=10)


    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Limpeza cancelada.", view=None)

    async def on_timeout(self):
        # Limpa a view se o tempo acabar, dando feedback de que a sessão acabou.
        if self.message:
            try:
                await self.message.edit(content="⏰ Confirmação expirada. Use o comando novamente.", view=None)
            except:
                pass

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def execute_clear(self, ctx: commands.Context, mode: str) -> int:
        """Função que executa a limpeza real (chamada pelo botão)."""
        
        def is_bot_message(message: discord.Message):
            # Filtro: Apaga APENAS mensagens do bot
            return message.author == self.bot.user

        # Define o filtro
        if mode == 'bot':
            check = is_bot_message
        else: # mode == 'all'
            # Filtro: Apaga TODAS as mensagens
            check = lambda m: True

        try:
            # Apaga as mensagens em lote
            # O limit=None tenta apagar o máximo permitido pelo Discord (geralmente 14 dias atrás)
            # Retorna uma lista de mensagens deletadas
            deleted = await ctx.channel.purge(limit=None, check=check, before=ctx.message)
            return len(deleted)

        except discord.Forbidden:
            # Propaga o erro para o handler principal tratar o feedback visual
            raise commands.CheckFailure("PERMISSAO_NEGADA")
        except Exception as e:
            logger.critical(f"Erro no purge: {e}")
            raise e


    @commands.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def clear_bot_messages(self, ctx: commands.Context):
        """Apaga apenas as mensagens enviadas por este bot no canal."""
        
        try:
            # Envia a confirmação
            confirmation_message = await ctx.reply("⚠️ Tem certeza que deseja apagar **apenas as mensagens do BOT** neste canal?", 
                                                    view=ClearConfirmationView(self, ctx, 'bot'))
            # Captura a referência para o on_timeout
            ClearConfirmationView(self, ctx, 'bot').message = confirmation_message
        except Exception as e:
            logger.error(f"Erro ao enviar confirmação de clear: {e}")


    @commands.command(name="clear_all")
    @commands.has_permissions(administrator=True)
    async def clear_all_messages(self, ctx: commands.Context):
        """Apaga TODAS as mensagens de todos os usuários no canal (Admin)."""
        
        try:
            # Envia a confirmação
            confirmation_message = await ctx.reply("🔴 ATENÇÃO! Tem certeza que deseja apagar **TODAS** as mensagens neste canal? Esta ação é IRREVERSÍVEL.", 
                                                    view=ClearConfirmationView(self, ctx, 'all'))
            # Captura a referência para o on_timeout
            ClearConfirmationView(self, ctx, 'all').message = confirmation_message
        except Exception as e:
            logger.error(f"Erro ao enviar confirmação de clear_all: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))