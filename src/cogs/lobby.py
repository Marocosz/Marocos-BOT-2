import discord
import random
from discord.ext import commands
from src.database.repositories import PlayerRepository, MatchRepository
from src.services.matchmaker import MatchMaker

# --- VIEW 1: BOTÕES DA FILA (PÚBLICO) ---
class LobbyView(discord.ui.View):
    def __init__(self, lobby_cog, disabled=False):
        super().__init__(timeout=None) 
        self.lobby_cog = lobby_cog
        
        # Se a fila estiver travada, desabilita os botões visuais
        if disabled:
            self.join_button.disabled = True
            self.leave_button.disabled = True
            self.join_button.style = discord.ButtonStyle.secondary
            self.leave_button.style = discord.ButtonStyle.secondary

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="lobby_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_join(interaction)

    @discord.ui.button(label="Sair", style=discord.ButtonStyle.danger, emoji="🏃", custom_id="lobby_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_leave(interaction)

    @discord.ui.button(label="Perfil", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="lobby_profile")
    async def profile_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Use `.perfil` para ver seus stats.", ephemeral=True)

# --- VIEW 2: ESCOLHA DE MODO DE JOGO (RESTRICTED: ADMIN ONLY) ---
class ModeSelectView(discord.ui.View):
    def __init__(self, lobby_cog, players):
        super().__init__(timeout=None)
        self.lobby_cog = lobby_cog
        self.players = players

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("⛔ Apenas Administradores podem iniciar!", ephemeral=True)
        return False

    @discord.ui.button(label="Auto-Balanceado (MMR)", style=discord.ButtonStyle.primary, emoji="⚖️")
    async def auto_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.start_match_balanced(interaction, self.players)
        self.stop()

    @discord.ui.button(label="Capitães (Top Elo)", style=discord.ButtonStyle.secondary, emoji="👑")
    async def captains_mmr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.start_match_captains(interaction, self.players, mode="mmr")
        self.stop()

    @discord.ui.button(label="Capitães (Aleatório)", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def captains_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.start_match_captains(interaction, self.players, mode="random")
        self.stop()

# --- LÓGICA PRINCIPAL ---
class Lobby(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = [] 
        self.lobby_message: discord.Message = None
        # CONFIGURAÇÃO DE LIMITE (Para teste mude aqui para 1, Produção = 10)
        self.QUEUE_LIMIT = 1 

    def get_queue_embed(self, locked=False):
        count = len(self.queue)
        
        if locked:
            color = 0x000000 # Preto/Escuro para indicar travado
            title = "🔒 LOBBY FECHADO - INICIANDO..."
            desc = "Aguarde o Admin configurar a partida."
        else:
            color = 0x3498db
            title = f"🏆 Lobby In-House ({count}/{self.QUEUE_LIMIT})"
            if count == 0:
                desc = "A fila está vazia."
            else:
                lines = []
                for i, p in enumerate(self.queue):
                    lane_icon = p.get('main_lane', '?').title()
                    lines.append(f"`{i+1}.` **{p['name']}** ({p['mmr']}) - {lane_icon}")
                desc = "\n".join(lines)

        embed = discord.Embed(title=title, description=desc, color=color)
        if not locked:
            embed.set_footer(text="Clique para entrar • Requer registro (.registrar)")
        return embed

    async def update_lobby_message(self, interaction: discord.Interaction = None, locked=False):
        embed = self.get_queue_embed(locked=locked)
        view = LobbyView(self, disabled=locked) # Passa o estado travado para a view
        
        try:
            if interaction and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            elif self.lobby_message:
                await self.lobby_message.edit(embed=embed, view=view)
        except: pass

    async def process_join(self, interaction: discord.Interaction):
        # 1. Check Rápido de Limite (Antes de processar tudo)
        if len(self.queue) >= self.QUEUE_LIMIT:
            return await interaction.response.send_message("A fila acabou de encher! Espere a próxima.", ephemeral=True)

        user = interaction.user
        if any(p['id'] == user.id for p in self.queue):
            return await interaction.response.send_message("Já está na fila.", ephemeral=True)
        
        player = await PlayerRepository.get_player_by_discord_id(user.id)
        if not player:
            return await interaction.response.send_message("🛑 Use `.registrar` primeiro.", ephemeral=True)

        self.queue.append({
            'id': user.id,
            'name': user.display_name,
            'mmr': player.mmr,
            'main_lane': player.main_lane.value if player.main_lane else "FILL"
        })
        
        # TRIGGER DE ADMIN (LIMIT)
        if len(self.queue) >= self.QUEUE_LIMIT:
            # 1. Trava visualmente a fila
            await self.update_lobby_message(interaction, locked=True)
            # 2. Manda o painel
            await self.prompt_game_mode(interaction.channel)
        else:
            # Só atualiza visualmente
            await self.update_lobby_message(interaction)

    async def process_leave(self, interaction: discord.Interaction):
        user = interaction.user
        self.queue = [p for p in self.queue if p['id'] != user.id]
        await self.update_lobby_message(interaction)

    # --- PASSO 2: MENU DO ADMIN ---
    async def prompt_game_mode(self, channel):
        # Copia os jogadores e limpa a fila lógica para a próxima rodada
        players_snapshot = self.queue.copy()
        self.queue = [] 
        
        # Lista os nomes para o Admin saber quem está nesse "pacote"
        player_names = ", ".join([f"**{p['name']}**" for p in players_snapshot])

        embed = discord.Embed(
            title="⚡ Painel de Controle da Partida",
            description="O Lobby encheu! Selecione como os times serão formados.",
            color=0xffd700
        )
        embed.add_field(name="Jogadores", value=player_names, inline=False)
        embed.add_field(name="Opções", value="⚖️ **Balanceado:** Bot define (Recomendado)\n👑 **Capitães:** Jogadores escolhem", inline=False)
        embed.set_footer(text="O ID da partida será gerado após a escolha.")
        
        view = ModeSelectView(self, players_snapshot)
        await channel.send(content="||@here|| 🔔 **Lobby Pronto!**", embed=embed, view=view)

    # --- OPÇÃO A: AUTOMÁTICO ---
    async def start_match_balanced(self, interaction, players):
        # Proteção para teste com 1 pessoa (não quebra o balanceamento, só cria times vazios ou com 1)
        team_blue, team_red = MatchMaker.balance_teams(players)
        
        match_id = await MatchRepository.create_match(
            guild_id=interaction.guild.id,
            blue_team=team_blue,
            red_team=team_red
        )
        
        embed = discord.Embed(title=f"⚔️ PARTIDA #{match_id} (Balanceada)", color=0x2ecc71)
        
        def fmt(team):
            if not team: return "Nenhum jogador"
            avg = sum(p['mmr'] for p in team) // len(team)
            return "\n".join([f"• {p['name']} ({p['mmr']})" for p in team]) + f"\n\n📊 **Média:** {avg}"

        embed.add_field(name="🔵 Time Azul", value=fmt(team_blue), inline=True)
        embed.add_field(name="🔴 Time Vermelho", value=fmt(team_red), inline=True)
        
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)
        embed.add_field(name="📢 Instruções", value=f"ID para registro: **{match_id}**\nUse `.resultado {match_id} Blue/Red` ao final.", inline=False)
        
        await interaction.followup.send(embed=embed)
        # Destrava a fila antiga (cria uma nova mensagem limpa)
        await self.update_lobby_message()

    # --- OPÇÃO B: CAPITÃES (CORRIGIDO O BUG DO 1 PLAYER) ---
    async def start_match_captains(self, interaction, players, mode="mmr"):
        # Proteção contra Crash em Teste (1 pessoa)
        if len(players) < 2:
            # Se for teste, clonamos o jogador só para não dar erro
            cap_blue = players[0]
            cap_red = players[0]
            pool = []
        else:
            if mode == "mmr":
                sorted_p = sorted(players, key=lambda x: x['mmr'], reverse=True)
                cap_blue = sorted_p[0]
                cap_red = sorted_p[1]
                pool = sorted_p[2:]
            else:
                random.shuffle(players)
                cap_blue = players[0]
                cap_red = players[1]
                pool = players[2:]

        # Salva no banco
        match_id = await MatchRepository.create_match(
            guild_id=interaction.guild.id,
            blue_team=[cap_blue], 
            red_team=[cap_red]
        )

        embed = discord.Embed(title=f"👑 PARTIDA #{match_id} (Draft)", color=0x9b59b6)
        embed.description = "**Fase de Picks!**\nCapitães definidos. Usem o chat de voz para escolher."
        
        embed.add_field(name="🔵 Capitão Azul", value=f"👑 **{cap_blue['name']}**\n({cap_blue['mmr']})", inline=True)
        embed.add_field(name="🔴 Capitão Vermelho", value=f"👑 **{cap_red['name']}**\n({cap_red['mmr']})", inline=True)
        
        if pool:
            pool_str = "\n".join([f"• {p['name']} ({p['mmr']})" for p in pool])
        else:
            pool_str = "Nenhum reserva (Modo Teste/1v1)"
            
        embed.add_field(name="📋 Banco de Reservas", value=pool_str, inline=False)
        embed.add_field(name="📢 Finalizar", value=f"ID: **{match_id}**\n`.resultado {match_id} Blue/Red`", inline=False)

        await interaction.followup.send(embed=embed)
        # Destrava a fila antiga
        await self.update_lobby_message()

    # --- COMANDOS ---
    @commands.command(name="fila")
    async def fila(self, ctx):
        if self.lobby_message:
            try: await self.lobby_message.delete()
            except: pass
        
        embed = self.get_queue_embed()
        view = LobbyView(self)
        self.lobby_message = await ctx.send(embed=embed, view=view)

    @commands.command(name="resetar")
    @commands.has_permissions(administrator=True)
    async def resetar(self, ctx):
        self.queue = []
        await self.update_lobby_message()
        await ctx.message.add_reaction("✅")

    @commands.command(name="resultado")
    @commands.has_permissions(administrator=True)
    async def resultado(self, ctx, match_id: int = None, winner: str = None):
        if match_id is None or winner is None:
            await ctx.reply("❌ Uso correto: `.resultado <ID> <Blue/Red>`")
            return

        winner = winner.upper()
        if winner not in ['BLUE', 'RED', 'AZUL', 'VERMELHO']:
            await ctx.reply("❌ Vencedor inválido. Use **Blue** ou **Red**.")
            return
        
        if winner == 'AZUL': winner = 'BLUE'
        if winner == 'VERMELHO': winner = 'RED'

        status = await MatchRepository.finish_match(match_id, winner)

        if status == "NOT_FOUND":
            await ctx.reply(f"❌ Partida **#{match_id}** não encontrada.")
        elif status == "ALREADY_FINISHED":
            await ctx.reply(f"🔒 A partida **#{match_id}** já foi finalizada!")
        elif status == "SUCCESS":
            color = 0x3498db if winner == 'BLUE' else 0xe74c3c
            emoji = "🔵" if winner == 'BLUE' else "🔴"
            
            embed = discord.Embed(
                title=f"{emoji} Partida #{match_id} Finalizada!",
                description=f"Vencedor: **TIME {winner}**",
                color=color
            )
            embed.add_field(name="Placar", value="✅ Vitórias/Derrotas atualizadas no ranking interno.", inline=False)
            embed.set_footer(text=f"Reportado por {ctx.author.display_name}")
            
            await ctx.reply(embed=embed)
        else:
            await ctx.reply("❌ Erro desconhecido.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Lobby(bot))