import discord
from discord.ext import commands

# --- BOTÃO DE FECHAR ---
class CloseButton(discord.ui.Button):
    def __init__(self, user_id: int): # Adicionado user_id
        super().__init__(label="Fechar Painel", style=discord.ButtonStyle.red, emoji="❌", row=1)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        # Apenas quem invocou o comando pode fechar
        if interaction.user.id != self.user_id: # Checagem simplificada
            await interaction.response.send_message("Apenas o autor do comando pode fechar este painel.", ephemeral=True)
            return

        # Remove a mensagem de ajuda
        await interaction.message.delete()
        
# --- MENU DE NAVEGAÇÃO ---
class HelpSelect(discord.ui.Select):
    def __init__(self, bot, user_id: int): # Adicionado user_id
        options = [
            discord.SelectOption(
                label="Início", 
                description="Visão geral do sistema.", 
                emoji="🏠", value="home"
            ),
            discord.SelectOption(
                label="Comandos de Jogador", 
                description="Registro, Perfil, Histórico, MMR.", 
                emoji="👤", value="player"
            ),
            discord.SelectOption(
                label="Ferramentas de Meta", 
                description="Builds, Tier Lists, Patch Notes.", 
                emoji="🛠️", value="utils"
            ),
            discord.SelectOption(
                label="Sistema da Liga Interna", 
                description="Como funciona a Fila, Capitães e Draft.", 
                emoji="🏆", value="lobby"
            ),
            discord.SelectOption(
                label="Painel Admin", 
                description="Comandos para organizadores.", 
                emoji="🛡️", value="admin"
            ),
        ]
        super().__init__(placeholder="📚 Navegue pelo Manual da Liga...", min_values=1, max_values=1, options=options, row=0)
        self.bot = bot
        self.user_id = user_id # Guarda o user_id

    async def callback(self, interaction: discord.Interaction):
        # Impedir que outro usuário use o Select Menu
        if interaction.user.id != self.user_id: # Checagem simplificada
            await interaction.response.send_message("Apenas o autor do comando pode navegar no menu de ajuda.", ephemeral=True)
            return

        value = self.values[0]
        
        if value == "home":
            embed = discord.Embed(title="🤖 Bem-vindo ao MarcosBot!", color=0x2b2d31)
            embed.description = (
                "Eu sou o sistema oficial da **Liga Interna** e assistente de LoL deste servidor.\n\n"
                "Minha função é organizar partidas competitivas justas, calcular seu **MMR Real** "
                "baseado no seu desempenho e fornecer ferramentas para sua evolução."
            )
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            embed.add_field(
                name="⚡ Primeiros Passos",
                value=(
                    "1️⃣ **Registre-se:** Use `.registrar` para criar sua identidade.\n"
                    "2️⃣ **Entre na Liga:** Use `.fila` para buscar partidas internas.\n"
                    "3️⃣ **Evolua:** Acompanhe seu `.perfil` e `.mmr` subindo."
                ),
                inline=False
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.set_footer(text="Selecione uma categoria abaixo para detalhes profundos.")

        elif value == "player":
            embed = discord.Embed(title="👤 Identidade & Estatísticas", color=0x3498db)
            embed.description = "Comandos essenciais para gerenciar sua conta na Liga."
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="📝 `.registrar <Nick#TAG> <Lane1> [Lane2]`",
                value=(
                    "Vincula sua conta Riot. Exige verificação de ícone para segurança.\n"
                    "**Ex:** `.registrar Faker#KR1 Mid` (Apenas main lane)\n"
                    "**Ex:** `.registrar Faker#KR1 Mid Top` (Main e Secondary)"
                ),
                inline=False
            )
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="📊 `.perfil [@usuario]`",
                value=(
                    "Gera seu **Card de Jogador** completo:\n"
                    "• Elo Oficial (Solo/Flex ao vivo).\n"
                    "• Top 3 Campeões (Maestria).\n"
                    "• Stats na Liga Interna (MMR, Vitórias)."
                ),
                inline=True
            )
            
            embed.add_field(
                name="🏆 `.ranking`",
                value="Exibe o **Top 10 Jogadores** da Liga Interna (Vitórias > Derrotas > MMR).",
                inline=True
            )

            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            embed.add_field(
                name="📈 `.mmr`",
                value="Relatório financeiro da sua pontuação (Explica ganhos, perdas e bônus de desempenho).",
                inline=True
            )

            embed.add_field(
                name="📜 `.historico`",
                value="Mostra suas últimas 10 partidas do LoL em grade.",
                inline=True
            )

            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🔴 `.live`",
                value="Espião: Verifica se você (ou alguém) está em partida agora e gera link do Spectator.",
                inline=False
            )

        elif value == "utils":
            embed = discord.Embed(title="🛠️ Ferramentas de Meta Game", color=0xe67e22)
            embed.description = "Dados do patch atual sem sair do Discord."
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🥊 Hub do Campeão (.build)",
                value=(
                    "Mostra a ordem de skills (QWER), splash art e botões diretos para as melhores builds.\n"
                    "**Uso:** `.build <campeao>`\n"
                    "**Ex:** `.build lee sin` (Gera links U.GG/OP.GG filtrados)"
                ),
                inline=False
            )
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            embed.add_field(
                name="🏆 Tier Lists (.meta)",
                value=(
                    "Gera um painel com links para as Tier Lists mais confiáveis do momento, filtradas por rota.\n"
                    "**Uso:** `.meta <rota>`\n"
                    "**Ex:** `.meta jungle`"
                ),
                inline=False
            )
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            embed.add_field(
                name="⚙️ Notas de Atualização (.patch)",
                value="Mostra a versão atual do servidor (Ex: 15.23) e o link oficial das notas.",
                inline=False
            )

        elif value == "lobby":
            embed = discord.Embed(title="🏆 Guia da Liga Interna", color=0x9b59b6)
            embed.description = "Entenda o fluxo completo das partidas personalizadas."

            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="1️⃣ O Lobby (.fila)",
                value=(
                    "• O Admin digita `.fila` para abrir o painel.\n"
                    "• Jogadores clicam em **[⚔️ Entrar]**.\n"
                    "• O sistema valida o registro e calcula o MMR na hora.\n"
                    "• Ao bater **10 Jogadores**, a fila trava e chama o Admin."
                ),
                inline=False
            )
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            embed.add_field(
                name="2️⃣ Decisão do Modo (Admin)",
                value="Quando a fila enche, o Admin escolhe como formar os times:",
                inline=False
            )
            embed.add_field(
                name="⚖️ Modo Auto-Balanceado",
                value="O Bot usa o MMR de todos para montar matematicamente os dois times mais justos possíveis (50% chance de vitória para cada).",
                inline=True
            )
            embed.add_field(
                name="👑 Modo Capitães (Draft)",
                value="O Bot define 2 líderes e inicia o modo interativo de escolha.",
                inline=True
            )
            embed.add_field(
                name="👮 Modo Manual",
                value="O Admin escolhe manualmente quem serão os 2 capitães.",
                inline=True
            )

            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="3️⃣ A Mecânica do Coinflip (Moeda)",
                value=(
                    "Para ser justo, o bot sorteia uma moeda entre os capitães:\n"
                    "🔹 **Vencedor da Moeda:** Ganha o **First Pick** (Escolhe o 1º jogador da lista).\n"
                    "🔹 **Perdedor da Moeda:** Ganha a **Escolha de Lado** (Define se quer Blue ou Red Side)."
                ),
                inline=False
            )

            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="4️⃣ O Draft e Jogo",
                value=(
                    "• O Capitão da vez escolhe no **Menu Suspenso**.\n"
                    "• Ao final, o Bot gera um **ID da Partida** (ex: #50).\n"
                    "• Vocês criam a sala personalizada no LoL.\n"
                    "• Ao fim, o Admin usa `.resultado 50 Blue` (ou Red) para computar os pontos."
                ),
                inline=False
            )

        elif value == "admin":
            embed = discord.Embed(title="🛡️ Painel do Administrador", color=0xff0000)
            embed.description = "Ferramentas de gestão de partidas e monitoramento da Liga."
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🔹 Gestão de Fila",
                value=(
                    "• **`.fila`**: Cria o painel visual no canal.\n"
                    "• **Resetar**: Use o botão vermelho 🗑️ no próprio painel da fila para limpar a lista."
                ),
                inline=False
            )
            
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🔹 Gestão de Resultados",
                value=(
                    "• **`.resultado <ID> <Vencedor>`**: Finaliza o jogo.\n"
                    "*(Ex: `.resultado 40 Blue`)*\n"
                    "• **`.anular <ID>`**: Cancela a partida (ninguém pontua).\n"
                    "*(Ex: `.anular 40`)*"
                ),
                inline=False
            )
            
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="🚨 Rastreamento de Elo (Tracking)",
                value=(
                    "• **`.config_aviso #canal`**: Define o canal para alertas de Promoção/Queda.\n"
                    "• **`.forcar_check`**: Inicia a verificação de Elo imediatamente.\n"
                    "• **`.fake_elo @user TIER RANK [FILA]`**: Força um Elo no DB para testes de aviso. "
                    "*(Ex: `.fake_elo @Marcos GOLD I SOLO`)*"
                ),
                inline=False
            )


            embed.set_footer(text="Apenas usuários com permissão de Administrador podem usar.")

        # Recria o view para resetar o Select Menu ao placeholder
        # Adiciona o botão de fechar
        new_view = HelpView(self.bot, self.user_id) # <-- Deve usar self.user_id
        await interaction.response.edit_message(embed=embed, view=new_view)

class HelpView(discord.ui.View):
    def __init__(self, bot, user_id: int): # Adicionado user_id
        super().__init__(timeout=120)
        self.user_id = user_id # Guarda user_id
        self.add_item(HelpSelect(bot, user_id)) # Passa user_id
        self.add_item(CloseButton(user_id)) # Passa user_id

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ajuda", aliases=["help", "comandos"])
    async def ajuda(self, ctx):
        """Abre o painel de ajuda interativo"""
        embed = discord.Embed(
            title="🤖 Central de Ajuda - Liga Interna",
            description="Selecione uma categoria no menu abaixo para acessar os tutoriais e lista de comandos.",
            color=0x2b2d31
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        view = HelpView(self.bot, ctx.author.id) # Passa o ID do autor
        await ctx.send(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))