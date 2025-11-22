import discord
import random
from discord.ext import commands
from src.database.repositories import PlayerRepository, MatchRepository
from src.services.matchmaker import MatchMaker

# --- COMPONENTE DE SELEÇÃO DE JOGADOR (PICK) ---
class PlayerSelect(discord.ui.Select):
    def __init__(self, players, placeholder):
        options = [
            discord.SelectOption(label=p['name'], value=str(p['id']), description=f"MMR: {p['mmr']}")
            for p in players[:25]
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.process_pick(interaction, self.values[0])

# --- VIEW DE SELEÇÃO DE CAPITÃO MANUAL (NOVO) ---
class ManualCaptainSelect(discord.ui.Select):
    def __init__(self, players, placeholder, is_first_cap=True):
        self.is_first_cap = is_first_cap
        options = [
            discord.SelectOption(label=p['name'], value=str(p['id']))
            for p in players[:25]
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.process_selection(interaction, self.values[0], self.is_first_cap)

class ManualCaptainView(discord.ui.View):
    def __init__(self, lobby_cog, players, interaction):
        super().__init__(timeout=120)
        self.lobby_cog = lobby_cog
        self.players = players
        self.admin_interaction = interaction # Guarda quem iniciou
        self.cap1 = None
        
        # Inicia pedindo o Capitão 1
        self.add_item(ManualCaptainSelect(players, "Selecione o Capitão 1 (Azul)", True))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.admin_interaction.user.id:
            return True
        await interaction.response.send_message("⛔ Apenas o Admin que iniciou pode escolher.", ephemeral=True)
        return False

    async def process_selection(self, interaction, selected_id, is_first_cap):
        player = next((p for p in self.players if str(p['id']) == selected_id), None)
        
        if is_first_cap:
            self.cap1 = player
            # Remove o cap1 da lista para não ser escolhido de novo
            remaining = [p for p in self.players if p['id'] != player['id']]
            
            # Atualiza a View para pedir o Capitão 2
            self.clear_items()
            self.add_item(ManualCaptainSelect(remaining, "Selecione o Capitão 2 (Vermelho)", False))
            
            await interaction.response.edit_message(content=f"✅ Capitão 1 definido: **{player['name']}**. Escolha o segundo:", view=self)
        else:
            cap2 = player
            # Inicia o fluxo normal de Coinflip
            await self.lobby_cog.start_coinflip_phase(interaction, self.players, self.cap1, cap2)

# --- VIEW 3: O DRAFT ---
class DraftView(discord.ui.View):
    def __init__(self, lobby_cog, guild_id, cap_blue, cap_red, pool, first_pick_side):
        super().__init__(timeout=600)
        self.lobby_cog = lobby_cog 
        self.guild_id = guild_id
        self.cap_blue = cap_blue
        self.cap_red = cap_red
        self.pool = pool
        self.turn = first_pick_side 
        self.team_blue = [cap_blue]
        self.team_red = [cap_red]
        self.update_components()

    def update_components(self):
        self.clear_items()
        if self.pool:
            picker_name = self.cap_blue['name'] if self.turn == 'BLUE' else self.cap_red['name']
            self.add_item(PlayerSelect(self.pool, placeholder=f"Vez de {picker_name} escolher..."))
        
        cancel_btn = discord.ui.Button(label="Cancelar Draft (Admin)", style=discord.ButtonStyle.danger, row=2, emoji="✖️")
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)

    async def cancel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
            return
        embed = discord.Embed(title="❌ Draft Cancelado", description=f"Cancelado por {interaction.user.mention}.", color=0xff0000)
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()
        self.lobby_cog.queue = []
        await self.lobby_cog.update_lobby_message()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        picker_id = self.cap_blue['id'] if self.turn == 'BLUE' else self.cap_red['id']
        if interaction.user.guild_permissions.administrator: return True
        if picker_id < 0: return True
        if interaction.user.id == picker_id: return True
        await interaction.response.send_message(f"✋ Espere sua vez! Agora é a vez do Capitão {self.turn}.", ephemeral=True)
        return False

    async def process_pick(self, interaction: discord.Interaction, picked_id: str):
        picked_player = next((p for p in self.pool if str(p['id']) == picked_id), None)
        if not picked_player: return

        if self.turn == 'BLUE':
            self.team_blue.append(picked_player)
            self.turn = 'RED'
        else:
            self.team_red.append(picked_player)
            self.turn = 'BLUE'
        
        self.pool.remove(picked_player)
        
        if not self.pool:
            await self.finish_draft(interaction)
        else:
            self.update_components()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def finish_draft(self, interaction: discord.Interaction):
        real_blue = [p for p in self.team_blue if p['id'] > 0]
        real_red = [p for p in self.team_red if p['id'] > 0]

        match_id = await MatchRepository.create_match(
            guild_id=self.guild_id,
            blue_team=real_blue,
            red_team=real_red
        )
        
        embed = discord.Embed(title=f"⚔️ PARTIDA #{match_id} (Draft Finalizado)", color=0x2ecc71)
        def fmt(team):
            if not team: return "Vazio"
            avg = sum(p['mmr'] for p in team) // len(team)
            names = "\n".join([f"• {p['name']} ({p['mmr']})" for p in team])
            return f"{names}\n\n📊 **Média:** {avg}"

        embed.add_field(name=f"🔵 Time Azul (Cap. {self.cap_blue['name']})", value=fmt(self.team_blue), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {self.cap_red['name']})", value=fmt(self.team_red), inline=True)
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)
        embed.add_field(name="📢 Instruções", value=f"Resultado: `.resultado {match_id} Blue/Red`", inline=False)
        
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    def get_embed(self):
        color = 0x3498db if self.turn == 'BLUE' else 0xe74c3c
        picker = self.cap_blue['name'] if self.turn == 'BLUE' else self.cap_red['name']
        embed = discord.Embed(title="👑 Draft em Andamento", description=f"**Vez de:** {picker} escolher jogador!", color=color)
        b_str = "\n".join([p['name'] for p in self.team_blue])
        r_str = "\n".join([p['name'] for p in self.team_red])
        p_str = ", ".join([f"`{p['name']}`" for p in self.pool])
        embed.add_field(name="🔵 Time Azul", value=b_str, inline=True)
        embed.add_field(name="🔴 Time Vermelho", value=r_str, inline=True)
        if p_str: embed.add_field(name="📋 Disponíveis", value=p_str, inline=False)
        return embed

# --- VIEW INTERMEDIÁRIA: ESCOLHA DE LADO (COINFLIP) ---
class SideSelectView(discord.ui.View):
    def __init__(self, lobby_cog, cap_priority, cap_secondary, pool):
        super().__init__(timeout=120)
        self.lobby_cog = lobby_cog
        self.cap_priority = cap_priority
        self.cap_secondary = cap_secondary
        self.pool = pool

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.cap_secondary['id'] or interaction.user.guild_permissions.administrator or self.cap_secondary['id'] < 0:
            return True
        await interaction.response.send_message(f"✋ Apenas {self.cap_secondary['name']} pode escolher o lado!", ephemeral=True)
        return False

    async def start_draft_phase(self, interaction, cap_blue, cap_red, first_pick_side):
        view = DraftView(self.lobby_cog, interaction.guild.id, cap_blue, cap_red, self.pool, first_pick_side)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Quero Lado Azul", style=discord.ButtonStyle.primary, emoji="🔵")
    async def blue_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_secondary, cap_red=self.cap_priority, first_pick_side='RED')

    @discord.ui.button(label="Quero Lado Vermelho", style=discord.ButtonStyle.danger, emoji="🔴")
    async def red_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_priority, cap_red=self.cap_secondary, first_pick_side='BLUE')

# --- VIEW NOVO: ESCOLHA DE LADO (BALANCEADO) ---
class BalancedSideSelectView(discord.ui.View):
    def __init__(self, lobby_cog, guild_id, winning_cap, winning_team, losing_cap, losing_team):
        super().__init__(timeout=180)
        self.lobby_cog = lobby_cog
        self.guild_id = guild_id
        self.winning_cap = winning_cap
        self.winning_team = winning_team
        self.losing_cap = losing_cap
        self.losing_team = losing_team

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.winning_cap['id'] or interaction.user.guild_permissions.administrator or self.winning_cap['id'] < 0:
            return True
        await interaction.response.send_message(f"✋ Apenas {self.winning_cap['name']} pode escolher o lado!", ephemeral=True)
        return False

    async def finalize_match(self, interaction, blue_team, red_team):
        match_id = await MatchRepository.create_match(self.guild_id, blue_team, red_team)
        embed = discord.Embed(title=f"⚔️ PARTIDA #{match_id} (Balanceada)", color=0x2ecc71)
        def fmt(team):
            avg = sum(p['mmr'] for p in team) // len(team)
            return "\n".join([f"• {p['name']} ({p['mmr']})" for p in team]) + f"\n\n📊 **Média:** {avg}"

        cap_blue_name = max(blue_team, key=lambda x: x['mmr'])['name']
        cap_red_name = max(red_team, key=lambda x: x['mmr'])['name']

        embed.add_field(name=f"🔵 Time Azul (Cap. {cap_blue_name})", value=fmt(blue_team), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {cap_red_name})", value=fmt(red_team), inline=True)
        embed.add_field(name="\u200b", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)
        embed.add_field(name="📢 Instruções", value=f"ID: **{match_id}**\n`.resultado {match_id} Blue/Red`", inline=False)
        
        await interaction.response.edit_message(embed=embed, view=None)
        await self.lobby_cog.update_lobby_message()

    @discord.ui.button(label="Escolher BLUE", style=discord.ButtonStyle.primary, emoji="🔵")
    async def choose_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.winning_team, red_team=self.losing_team)

    @discord.ui.button(label="Escolher RED", style=discord.ButtonStyle.danger, emoji="🔴")
    async def choose_red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.losing_team, red_team=self.winning_team)

# --- VIEW 1: LOBBY ---
class LobbyView(discord.ui.View):
    def __init__(self, lobby_cog, disabled=False):
        super().__init__(timeout=None) 
        self.lobby_cog = lobby_cog
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

# --- VIEW 2: MODO SELECT (ATUALIZADO COM MANUAL) ---
class ModeSelectView(discord.ui.View):
    def __init__(self, lobby_cog, players):
        super().__init__(timeout=None)
        self.lobby_cog = lobby_cog
        self.players = players

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("⛔ Apenas Administradores podem iniciar.", ephemeral=True)
        return False

    @discord.ui.button(label="Auto-Balanceado", style=discord.ButtonStyle.primary, emoji="⚖️")
    async def auto_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.start_match_balanced(interaction, self.players)
        self.stop()

    @discord.ui.button(label="Capitães (Top Elo)", style=discord.ButtonStyle.secondary, emoji="👑")
    async def captains_mmr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.setup_captains_auto(interaction, self.players, mode="mmr")
        self.stop()

    @discord.ui.button(label="Capitães (Aleatório)", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def captains_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.setup_captains_auto(interaction, self.players, mode="random")
        self.stop()

    # --- NOVO BOTÃO ---
    @discord.ui.button(label="Capitães (Manual)", style=discord.ButtonStyle.secondary, emoji="👮")
    async def captains_manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Não deferimos aqui porque a view de seleção manual é efemera/especial
        await self.lobby_cog.setup_captains_manual(interaction, self.players)
        self.stop()

# --- LOBBY COG ---
class Lobby(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = [] 
        self.lobby_message: discord.Message = None
        self.QUEUE_LIMIT = 1 # Configurado para 1 para teste

    def get_queue_embed(self, locked=False):
        count = len(self.queue)
        if locked:
            color = 0x000000 
            title = "🔒 LOBBY FECHADO"
            desc = "Aguarde o Admin configurar a partida."
        else:
            color = 0x3498db
            title = f"🏆 Lobby In-House ({count}/{self.QUEUE_LIMIT})"
            if count == 0: desc = "A fila está vazia."
            else:
                lines = [f"`{i+1}.` **{p['name']}** ({p['mmr']}) - {p.get('main_lane','?').title()}" for i, p in enumerate(self.queue)]
                desc = "\n".join(lines)
        embed = discord.Embed(title=title, description=desc, color=color)
        if not locked: embed.set_footer(text="Clique para entrar • Requer registro (.registrar)")
        return embed

    async def update_lobby_message(self, interaction: discord.Interaction = None, locked=False):
        embed = self.get_queue_embed(locked=locked)
        view = LobbyView(self, disabled=locked)
        try:
            if interaction and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            elif self.lobby_message:
                await self.lobby_message.edit(embed=embed, view=view)
        except: pass

    async def process_join(self, interaction: discord.Interaction):
        if len(self.queue) >= self.QUEUE_LIMIT:
            return await interaction.response.send_message("Fila cheia!", ephemeral=True)
        user = interaction.user
        if any(p['id'] == user.id for p in self.queue):
            return await interaction.response.send_message("Já está na fila.", ephemeral=True)
        player = await PlayerRepository.get_player_by_discord_id(user.id)
        if not player: return await interaction.response.send_message("🛑 Use `.registrar` primeiro.", ephemeral=True)

        self.queue.append({'id': user.id, 'name': user.display_name, 'mmr': player.mmr, 'main_lane': player.main_lane.value if player.main_lane else "FILL"})
        
        if len(self.queue) >= self.QUEUE_LIMIT:
            await self.update_lobby_message(interaction, locked=True)
            await self.prompt_game_mode(interaction.channel)
        else:
            await self.update_lobby_message(interaction)

    async def process_leave(self, interaction: discord.Interaction):
        user = interaction.user
        self.queue = [p for p in self.queue if p['id'] != user.id]
        await self.update_lobby_message(interaction)

    async def prompt_game_mode(self, channel):
        players_snapshot = self.queue.copy()
        self.queue = [] 
        player_names = ", ".join([f"**{p['name']}**" for p in players_snapshot])
        embed = discord.Embed(title="⚡ Painel de Controle", description="O Lobby encheu! Escolha o modo:", color=0xffd700)
        embed.add_field(name="Jogadores", value=player_names, inline=False)
        view = ModeSelectView(self, players_snapshot)
        await channel.send(content="||@here|| 🔔 **Lobby Pronto!**", embed=embed, view=view)

    # --- OPÇÃO A: AUTOMÁTICO ---
    async def start_match_balanced(self, interaction, players):
        team_blue, team_red = MatchMaker.balance_teams(players)
        
        # Define Capitães (Top MMR) para o sorteio
        if team_blue: cap_blue = max(team_blue, key=lambda x: x['mmr'])
        else: cap_blue = {'id': -1, 'name': 'Bot Blue', 'mmr': 1000}
        
        if team_red: cap_red = max(team_red, key=lambda x: x['mmr'])
        else: cap_red = {'id': -2, 'name': 'Bot Red', 'mmr': 1000}

        # Sorteio de Lado (Balanced)
        if random.choice([True, False]):
            win, lose = cap_blue, cap_red
            win_team, lose_team = team_blue, team_red
        else:
            win, lose = cap_red, cap_blue
            win_team, lose_team = team_red, team_blue

        embed = discord.Embed(title="⚖️ Times Balanceados! (Sorteio)", color=0xff9900)
        embed.description = f"**{win['name']}** venceu o cara-ou-coroa e escolhe o **LADO**."
        view = BalancedSideSelectView(self, interaction.guild.id, win, win_team, lose, lose_team)
        await interaction.followup.send(embed=embed, view=view)

    # --- OPÇÃO B: CAPITÃES (AUTO/RANDOM) ---
    async def setup_captains_auto(self, interaction, players, mode="mmr"):
        # Debug: Cria bots se faltar gente
        if len(players) < 10: 
            cap1 = players[0]
            cap2 = players[0] if len(players) == 1 else players[1]
            pool = players[2:] if len(players) > 2 else []
            for i in range(8 - len(pool)):
                pool.append({'id': -1 * (i+100), 'name': f'Bot {i+1}', 'mmr': 1000, 'main_lane': 'FILL'})
        else:
            if mode == "mmr":
                sorted_p = sorted(players, key=lambda x: x['mmr'], reverse=True)
                cap1, cap2, pool = sorted_p[0], sorted_p[1], sorted_p[2:]
            else:
                random.shuffle(players)
                cap1, cap2, pool = players[0], players[1], players[2:]

        await self.start_coinflip_phase(interaction, players, cap1, cap2)

    # --- OPÇÃO C: CAPITÃES (MANUAL) ---
    async def setup_captains_manual(self, interaction, players):
        # Debug Bots para teste manual
        if len(players) < 10:
            for i in range(10 - len(players)):
                players.append({'id': -1 * (i+100), 'name': f'Bot {i+1}', 'mmr': 1000})
        
        view = ManualCaptainView(self, players, interaction)
        await interaction.response.send_message("Selecione os capitães abaixo:", view=view, ephemeral=True)

    # --- FASE COMUM: MOEDA GIRADA ---
    async def start_coinflip_phase(self, interaction, all_players, cap1, cap2):
        # Reconstrói a pool removendo os capitães (importante para o manual)
        pool = [p for p in all_players if p['id'] != cap1['id'] and p['id'] != cap2['id']]

        if random.choice([True, False]):
            cap_priority, cap_secondary = cap1, cap2
        else:
            cap_priority, cap_secondary = cap2, cap1

        embed = discord.Embed(title="🪙 Moeda Girada!", color=0xff9900)
        embed.description = (
            f"**{cap_priority['name']}** prioridade de Pick.\n"
            f"**{cap_secondary['name']}** escolhe o **Lado**."
        )
        view = SideSelectView(self, cap_priority, cap_secondary, pool)
        
        # Se a interação já foi respondida (caso do manual), usa followup
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, view=view)
            
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
    async def resetar(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("⛔ Apenas Administradores.")
        self.queue = []
        await self.update_lobby_message()
        await ctx.message.add_reaction("✅")

    @commands.command(name="resultado")
    async def resultado(self, ctx, match_id: int = None, winner: str = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id or not winner: return await ctx.reply("❌ Uso: `.resultado <ID> <Blue/Red>`")
        
        winner = winner.upper()
        if winner not in ['BLUE', 'RED', 'AZUL', 'VERMELHO']: return await ctx.reply("❌ Inválido.")
        if winner == 'AZUL': winner = 'BLUE'
        if winner == 'VERMELHO': winner = 'RED'

        status = await MatchRepository.finish_match(match_id, winner)
        if status == "SUCCESS":
            embed = discord.Embed(title=f"✅ Partida #{match_id} Finalizada!", description=f"Vencedor: **TIME {winner}**", color=0x2ecc71)
            await ctx.reply(embed=embed)
        elif status == "ALREADY_FINISHED": await ctx.reply(f"🔒 Já finalizada.")
        else: await ctx.reply("❌ Partida não encontrada.")

    @commands.command(name="anular")
    async def anular(self, ctx, match_id: int = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id: return await ctx.reply("❌ Uso: `.anular <ID>`")

        status = await MatchRepository.cancel_match(match_id)
        if status == "SUCCESS": await ctx.reply(f"🚫 Partida **#{match_id}** ANULADA.")
        elif status == "NOT_ACTIVE": await ctx.reply(f"❌ Partida não ativa.")
        else: await ctx.reply("❌ Não encontrada.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Lobby(bot))