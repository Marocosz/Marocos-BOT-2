import discord
import asyncio

class BaseInteractiveView(discord.ui.View):
    """
    Classe Base para Views interativas do bot.
    Responsável por garantir que o status 'Expirado' seja exibido
    ao invés de simplesmente remover os botões.
    """
    # O timeout padrão do Discord é 180s (3 minutos)
    def __init__(self, timeout=180, **kwargs):
        super().__init__(timeout=timeout) 
        self.message = None # Atributo para armazenar a referência da mensagem

    async def on_timeout(self):
        """Função chamada quando o tempo acaba."""
        if self.message:
            self.clear_items()
            
            # Botão de aviso que não pode ser clicado
            timeout_button = discord.ui.Button(
                label="Tempo Expirado / Interação Encerrada", 
                style=discord.ButtonStyle.gray, 
                emoji="⏰", 
                disabled=True
            )
            self.add_item(timeout_button)
            
            try:
                # Edita a mensagem original (self.message)
                await self.message.edit(view=self)
            except discord.NotFound:
                pass # Ignora se a mensagem foi deletada
            except Exception as e:
                print(f"Erro ao editar mensagem expirada: {e}")