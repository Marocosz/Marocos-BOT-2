import discord
from discord.ext import commands
from src.utils.views import BaseInteractiveView


# --- BOTÃO DE FECHAR ---
class CloseButton(discord.ui.Button):
    def __init__(self, user_id: int):
        super().__init__(label="Fechar Painel", style=discord.ButtonStyle.secondary, emoji="❌", row=1)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Apenas o autor do comando pode fechar este painel.", ephemeral=True)
            return
        await interaction.message.delete()


# --- MENU DE NAVEGAÇÃO ---
class HelpSelect(discord.ui.Select):
    def __init__(self, bot, user_id: int):
        options = [
            discord.SelectOption(label="Início",                  description="Visão geral e primeiros passos.",              emoji="🏠", value="home"),
            discord.SelectOption(label="Jogador",                 description="Registro, Perfil, Ranking, MMR, Histórico.",   emoji="👤", value="player"),
            discord.SelectOption(label="Liga Interna",            description="Fila, Draft, Resultado, H2H, Histórico.",      emoji="🏆", value="lobby"),
            discord.SelectOption(label="Agenda",                  description="Agendamento de eventos e lembretes.",          emoji="📅", value="agenda"),
            discord.SelectOption(label="Comunidade & XP",         description="Perfil Social, Ranking de XP e Níveis.",       emoji="✨", value="community"),
            discord.SelectOption(label="Ferramentas de Meta",     description="Builds, Tier Lists, Patch Notes.",             emoji="🛠️", value="utils"),
            discord.SelectOption(label="Painel Admin",            description="Comandos para organizadores.",                 emoji="🛡️", value="admin"),
        ]
        super().__init__(placeholder="📚 Navegue pelo Manual da Liga...", min_values=1, max_values=1, options=options, row=0)
        self.bot = bot
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Apenas o autor do comando pode navegar no menu de ajuda.", ephemeral=True)
            return

        value = self.values[0]

        # ── HOME ──────────────────────────────────────────────────────────────
        if value == "home":
            embed = discord.Embed(title="🤖 Bem-vindo ao MarocosBot!", color=0x2b2d31)
            embed.description = (
                "Sou o sistema oficial da **Liga Interna** e assistente de LoL deste servidor.\n"
                "Organizo partidas, calculo MMR, faço drafts e mantenho o histórico da liga."
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            embed.add_field(
                name="⚡ Primeiros Passos",
                value=(
                    "1️⃣ **Registre-se:** `.registrar Nick#TAG Rota`\n"
                    "2️⃣ **Entre na fila:** `.fila` quando o admin abrir\n"
                    "3️⃣ **Acompanhe:** `.perfil` e `.ranking` para ver sua evolução"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            embed.add_field(
                name="📚 Categorias disponíveis",
                value=(
                    "👤 **Jogador** — registro, perfil, stats\n"
                    "🏆 **Liga Interna** — fila, partidas, histórico\n"
                    "📅 **Agenda** — eventos agendados com lembretes\n"
                    "✨ **Comunidade** — XP, níveis, ranking social\n"
                    "🛠️ **Ferramentas** — builds, meta, patch notes\n"
                    "🛡️ **Admin** — gestão de partidas e servidor"
                ),
                inline=False,
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.set_footer(text="Selecione uma categoria no menu abaixo.")

        # ── JOGADOR ───────────────────────────────────────────────────────────
        elif value == "player":
            embed = discord.Embed(title="👤 Identidade & Estatísticas", color=0x3498db)
            embed.description = "Comandos para gerenciar sua conta e acompanhar sua evolução."
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="📝 `.registrar <Nick#TAG> <Lane> [Lane2]`",
                value=(
                    "Vincula sua conta Riot com verificação de ícone.\n"
                    "**Ex:** `.registrar Faker#KR1 Mid` — só main lane\n"
                    "**Ex:** `.registrar Faker#KR1 Mid Top` — main + secondary"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="📊 `.perfil [@usuario]`",
                value=(
                    "Card completo do jogador:\n"
                    "• Elo Oficial atualizado (Solo/Flex)\n"
                    "• Top 3 campeões por maestria\n"
                    "• Stats da Liga: MMR, V/D, WR%, MVP, streaks"
                ),
                inline=True,
            )
            embed.add_field(
                name="🏆 `.ranking`",
                value=(
                    "Ranking interno paginado.\n"
                    "Ordenado por V > D > MMR.\n"
                    "Mostra 🔥 streak ≥ 3 vitórias."
                ),
                inline=True,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🧮 `.mmr [@usuario]`",
                value="Extrato detalhado do MMR: elo base, ajuste de fila, bônus de WR e fórmula aplicada.",
                inline=True,
            )
            embed.add_field(
                name="📜 `.historico [@usuario]`",
                value="Últimas 10 partidas ranqueadas da Riot API em grade.",
                inline=True,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🔴 `.live [@usuario]`",
                value="Verifica se o jogador está em partida agora e gera link do Spectator no OP.GG.",
                inline=False,
            )

        # ── LIGA INTERNA ──────────────────────────────────────────────────────
        elif value == "lobby":
            embed = discord.Embed(title="🏆 Liga Interna", color=0x9b59b6)
            embed.description = "Fluxo completo das partidas personalizadas e comandos de histórico."

            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="1️⃣ Fila (`.fila`)",
                value=(
                    "• Admin abre o painel com `.fila`\n"
                    "• Jogadores clicam **⚔️ Entrar** (máx. 10)\n"
                    "• Ao lotar, admin escolhe o modo de formação"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="2️⃣ Modos de Formação",
                value="\u200b",
                inline=False,
            )
            embed.add_field(
                name="⚖️ Auto-Balanceado",
                value="Snake distribution por MMR — times matematicamente equilibrados.",
                inline=True,
            )
            embed.add_field(
                name="👑 Capitães (Draft)",
                value="2 capitães escolhidos por elo ou aleatoriamente, draft alternado.",
                inline=True,
            )
            embed.add_field(
                name="👮 Manual",
                value="Admin seleciona os capitães via dropdown.",
                inline=True,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="3️⃣ Coinflip & Draft",
                value=(
                    "🔹 **Vencedor da moeda** → First Pick\n"
                    "🔹 **Perdedor da moeda** → Escolha de lado (Blue/Red)\n"
                    "• Draft alternado até completar 10 jogadores"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="4️⃣ Resultado & Pós-Jogo",
                value=(
                    "`.resultado <ID> Blue|Red` — registra vencedor\n"
                    "• MMR atualizado imediatamente para todos\n"
                    "• Streaks atualizados — marcos anunciados (3,5,7,10…)\n"
                    "• Votação MVP (melhor vencedor) e iMVP (pior perdedor) por 30 min"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="📋 Histórico & Dados",
                value=(
                    "**`.historico_liga [@user]`** — todas as partidas internas paginadas (10/pág)\n"
                    "**`.partida <ID>`** — detalhes: times, MMR na época, resultado\n"
                    "**`.h2h @user1 @user2`** — confronto direto: WR como adversários e parceiros"
                ),
                inline=False,
            )

        # ── AGENDA ────────────────────────────────────────────────────────────
        elif value == "agenda":
            embed = discord.Embed(title="📅 Sistema de Agenda", color=0x1abc9c)
            embed.description = (
                "Agende eventos com antecedência. Jogadores confirmam presença "
                "e recebem lembretes automáticos por DM."
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="📌 Criar Evento (admin)",
                value=(
                    "**`.agendar DD/MM/YYYY HH:MM Título`**\n"
                    "Posta um embed com botões de confirmação no canal.\n"
                    "**Ex:** `.agendar 21/03/2025 21:00 Sexta Ranqueada`\n"
                    "*(Horário de Brasília — UTC-3)*"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="📋 `.agenda`",
                value="Lista todos os eventos abertos com data, confirmados e vagas restantes.",
                inline=True,
            )
            embed.add_field(
                name="✅ Confirmar/Sair",
                value="Clique nos botões **Confirmar Presença** ou **Cancelar Presença** diretamente no embed do evento.",
                inline=True,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="🛡️ Controles do Admin",
                value=(
                    "**`.cancelar_agenda <ID>`** — cancela e envia DM para os confirmados\n"
                    "**`.add_agenda <ID> @user`** — adiciona membro manualmente\n"
                    "**`.kick_agenda <ID> @user`** — remove membro da lista\n"
                    "**`.iniciar_agenda <ID>`** — fecha inscrições e pinga todos no canal"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="🔔 Lembretes Automáticos (DM)",
                value=(
                    "O bot envia DM automaticamente para todos os confirmados:\n"
                    "• **24 horas antes** do evento\n"
                    "• **30 minutos antes** do evento\n"
                    "*(Se suas DMs estiverem fechadas, o lembrete é ignorado silenciosamente)*"
                ),
                inline=False,
            )

        # ── COMUNIDADE ────────────────────────────────────────────────────────
        elif value == "community":
            embed = discord.Embed(title="✨ Comunidade & Níveis", color=0xf1c40f)
            embed.description = "Sistema de XP e engajamento social do servidor."
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="💳 `.social [@usuario]`",
                value=(
                    "Cartão social completo:\n"
                    "• Nível atual com barra de XP\n"
                    "• Mensagens enviadas, mídia, tempo em voz\n"
                    "• Status de atividade e rank global"
                ),
                inline=True,
            )
            embed.add_field(
                name="🏆 `.ranking_xp`",
                value="Top 10 membros mais ativos do servidor por nível e XP.",
                inline=True,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="⭐ Como ganhar XP",
                value=(
                    "**Texto:** +15–25 XP por mensagem *(cooldown de 5s)*\n"
                    "**Voz:** +10 XP/minuto *(mínimo 2 pessoas no canal)*\n\n"
                    "Ao subir de nível o bot envia uma notificação no canal!"
                ),
                inline=False,
            )

        # ── FERRAMENTAS ───────────────────────────────────────────────────────
        elif value == "utils":
            embed = discord.Embed(title="🛠️ Ferramentas de Meta Game", color=0xe67e22)
            embed.description = "Dados do patch atual sem sair do Discord."
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🥊 `.build <campeão>`",
                value=(
                    "Skills (QWER), splash art e links de builds para o campeão.\n"
                    "Busca por similaridade — funciona mesmo com erros de digitação.\n"
                    "**Ex:** `.build lee sin`"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="🏆 `.meta <rota>`",
                value=(
                    "Links para tier lists filtradas por rota (U.GG, OP.GG, Lolalytics).\n"
                    "**Ex:** `.meta jungle`"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="⚙️ `.patch`",
                value="Versão atual do jogo e link para as notas de patch em PT-BR.",
                inline=False,
            )

        # ── ADMIN ─────────────────────────────────────────────────────────────
        elif value == "admin":
            embed = discord.Embed(title="🛡️ Painel do Administrador", color=0xff0000)
            embed.description = "Ferramentas de gestão de partidas, elo e servidor."
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(
                name="⚔️ Gestão de Partidas",
                value=(
                    "**`.fila`** — abre o painel de fila\n"
                    "**`.resultado <ID> Blue|Red`** — registra vencedor e atualiza MMR/streaks\n"
                    "**`.anular <ID>`** — cancela a partida sem pontuar\n"
                    "**`.recalcular_mmr`** — recalcula MMR de todos com dados cached da Riot"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="📅 Gestão de Agenda",
                value=(
                    "**`.agendar DD/MM/YYYY HH:MM Título`** — cria evento\n"
                    "**`.cancelar_agenda <ID>`** — cancela e notifica confirmados\n"
                    "**`.add_agenda <ID> @user`** — adiciona membro\n"
                    "**`.kick_agenda <ID> @user`** — remove membro\n"
                    "**`.iniciar_agenda <ID>`** — inicia o evento e pinga todos"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="📡 Rastreamento de Elo",
                value=(
                    "**`.config_aviso #canal`** — define canal de alertas de promoção/queda\n"
                    "**`.forcar_check`** — dispara a verificação de elo imediatamente\n"
                    "**`.fake_elo @user TIER RANK [SOLO|FLEX]`** — força elo para testes\n"
                    "*(Ex: `.fake_elo @Marcos GOLD I SOLO`)*"
                ),
                inline=False,
            )
            embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

            embed.add_field(
                name="🧹 Limpeza",
                value=(
                    "**`.clear`** — apaga últimas 1000 mensagens do bot (com confirmação)\n"
                    "**`.clear_all`** — apaga últimas 1000 mensagens de todos (com confirmação)"
                ),
                inline=False,
            )
            embed.set_footer(text="Todos os comandos acima exigem permissão de Administrador.")

        new_view = HelpView(self.bot, self.user_id)
        if isinstance(self.view, HelpView):
            new_view.message = self.view.message
        await interaction.response.edit_message(embed=embed, view=new_view)


class HelpView(BaseInteractiveView):
    def __init__(self, bot, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.add_item(HelpSelect(bot, user_id))
        self.add_item(CloseButton(user_id))


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ajuda", aliases=["help", "comandos"])
    async def ajuda(self, ctx):
        """Abre o painel de ajuda interativo"""
        embed = discord.Embed(
            title="🤖 Central de Ajuda — MarocosBot",
            description="Selecione uma categoria no menu abaixo para navegar.",
            color=0x2b2d31,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        view = HelpView(self.bot, ctx.author.id)
        sent_message = await ctx.send(embed=embed, view=view)
        view.message = sent_message


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
