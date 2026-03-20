import discord
import random
from discord.ext import commands
from src.database.repositories import PlayerRepository, MatchRepository, LobbyRepository, GuildRepository
from src.services.matchmaker import MatchMaker
import asyncio
from src.utils.views import BaseInteractiveView

from sqlalchemy import select, func
from src.database.config import get_session
from src.database.models import Match as MatchModel, MatchStatus


# Marcos de sequência que merecem anúncio
STREAK_MILESTONES = {3, 5, 7, 10, 15, 20}


# --- COMPONENTE DE SELEÇÃO DE JOGADOR ---
class PlayerSelect(discord.ui.Select):
    def __init__(self, players, placeholder):
        options = [
            discord.SelectOption(label=p['name'], value=str(p['id']), description=f"MMR: {p['mmr']}")
            for p in players[:25]
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.process_pick(interaction, self.values[0])


# --- VIEW DE SELEÇÃO DE CAPITÃO MANUAL ---
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


class ManualCaptainView(BaseInteractiveView):
    def __init__(self, lobby_cog, players, interaction):
        super().__init__(timeout=900)
        self.lobby_cog = lobby_cog
        self.players = players
        self.admin_interaction = interaction
        self.cap1 = None
        self.add_item(ManualCaptainSelect(players, "Selecione o Capitão 1", True))
        self.add_cancel_button()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.admin_interaction.user.id:
            return True
        await interaction.response.send_message("⛔ Apenas o Admin que iniciou pode escolher.", ephemeral=True)
        return False

    async def process_selection(self, interaction, selected_id, is_first_cap):
        player = next((p for p in self.players if str(p['id']) == selected_id), None)
        if is_first_cap:
            self.cap1 = player
            remaining = [p for p in self.players if p['id'] != player['id']]
            self.clear_items()
            self.add_item(ManualCaptainSelect(remaining, "Selecione o Capitão 2", False))
            self.add_cancel_button()
            await interaction.response.edit_message(content=f"✅ Capitão 1: **{player['name']}**. Escolha o segundo:", view=self)
        else:
            cap2 = player
            await interaction.response.edit_message(content=f"✅ Capitães: **{self.cap1['name']}** vs **{cap2['name']}**", view=None)
            await self.lobby_cog.start_coinflip_phase(self.admin_interaction, self.players, self.cap1, cap2)

    def add_cancel_button(self):
        btn = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary, row=2, emoji="✖️")
        btn.callback = self.cancel_callback
        self.add_item(btn)

    async def cancel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.edit_message(content="❌ Seleção cancelada. Fila reaberta.", view=None)
        self.stop()


# --- VIEW DO DRAFT ---
class DraftView(BaseInteractiveView):
    def __init__(self, lobby_cog, guild_id, cap_blue, cap_red, pool, first_pick_side):
        super().__init__(timeout=900)
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
        cancel_btn = discord.ui.Button(label="Cancelar Draft (Admin)", style=discord.ButtonStyle.secondary, row=2, emoji="✖️")
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)

    async def cancel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Apenas Administradores podem cancelar o draft!", ephemeral=True)
            return
        embed = discord.Embed(title="❌ Draft Cancelado", description=f"Cancelado por {interaction.user.mention}. Fila reaberta.", color=0xff0000)
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()
        await self.lobby_cog.reset_lobby_state()

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
            real_players = [p for p in team if p['id'] > 0]
            avg = sum(p['mmr'] for p in real_players) // len(real_players) if real_players else 0
            names = "\n".join([f"• {p['name']} ({p['mmr']})" for p in team])
            return f"{names}\n\n📊 **Média:** {avg}"

        embed.add_field(name=f"🔵 Time Azul (Cap. {self.cap_blue['name']})", value=fmt(self.team_blue), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {self.cap_red['name']})", value=fmt(self.team_red), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="📢 Instruções", value=f"ID: **{match_id}**\n`.resultado {match_id} Blue/Red`", inline=False)

        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()
        self.lobby_cog.current_match_id = 0
        await self.lobby_cog.update_lobby_message(locked=True)
        # Limpa a fila persistida, pois a partida já foi criada
        if interaction.guild:
            await LobbyRepository.clear_state(interaction.guild.id)

    def get_embed(self):
        color = 0x3498db if self.turn == 'BLUE' else 0xe74c3c
        picker = self.cap_blue['name'] if self.turn == 'BLUE' else self.cap_red['name']
        embed = discord.Embed(title="👑 Draft em Andamento", description=f"**Vez de:** {picker} escolher!", color=color)
        b_str = "\n".join([p['name'] for p in self.team_blue])
        r_str = "\n".join([p['name'] for p in self.team_red])
        p_str = ", ".join([f"`{p['name']}`" for p in self.pool])
        embed.add_field(name="🔵 Time Azul", value=b_str, inline=True)
        embed.add_field(name="🔴 Time Vermelho", value=r_str, inline=True)
        if p_str: embed.add_field(name="📋 Disponíveis", value=p_str, inline=False)
        return embed


# --- VIEW DE ESCOLHA DE LADO (COINFLIP) ---
class SideSelectView(BaseInteractiveView):
    def __init__(self, lobby_cog, cap_priority, cap_secondary, pool):
        super().__init__(timeout=900)
        self.lobby_cog = lobby_cog
        self.cap_priority = cap_priority
        self.cap_secondary = cap_secondary
        self.pool = pool

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator: return True
        if interaction.user.id == self.cap_secondary['id'] and self.cap_secondary['id'] > 0: return True
        await interaction.response.send_message(f"✋ Apenas {self.cap_secondary['name']} pode escolher o lado!", ephemeral=True)
        return False

    async def start_draft_phase(self, interaction, cap_blue, cap_red, first_pick_side):
        try: await interaction.message.edit(view=None)
        except: pass
        view = DraftView(self.lobby_cog, interaction.guild.id, cap_blue, cap_red, self.pool, first_pick_side)
        await interaction.response.send_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Quero Lado Azul", style=discord.ButtonStyle.primary, emoji="🔵")
    async def blue_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_secondary, cap_red=self.cap_priority, first_pick_side='RED')

    @discord.ui.button(label="Quero Lado Vermelho", style=discord.ButtonStyle.secondary, emoji="🔴")
    async def red_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_draft_phase(interaction, cap_blue=self.cap_priority, cap_red=self.cap_secondary, first_pick_side='BLUE')

    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", row=2)
    async def cancel_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.edit_message(content="❌ Processo cancelado. Fila reaberta.", embed=None, view=None)
        self.stop()


# --- VIEW DE ESCOLHA DE LADO (BALANCEADO) ---
class BalancedSideSelectView(BaseInteractiveView):
    def __init__(self, lobby_cog, guild_id, winning_cap, winning_team, losing_cap, losing_team):
        super().__init__(timeout=900)
        self.lobby_cog = lobby_cog
        self.guild_id = guild_id
        self.winning_cap = winning_cap
        self.winning_team = winning_team
        self.losing_cap = losing_cap
        self.losing_team = losing_team

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator: return True
        if interaction.user.id == self.winning_cap['id'] and self.winning_cap['id'] > 0: return True
        await interaction.response.send_message(f"✋ Apenas {self.winning_cap['name']} pode escolher o lado!", ephemeral=True)
        return False

    async def finalize_match(self, interaction, blue_team, red_team):
        try: await interaction.message.edit(view=None)
        except: pass

        real_blue = [p for p in blue_team if p['id'] > 0]
        real_red = [p for p in red_team if p['id'] > 0]

        match_id = await MatchRepository.create_match(self.guild_id, real_blue, real_red)
        embed = discord.Embed(title=f"⚔️ PARTIDA #{match_id} (Balanceada)", color=0x2ecc71)

        def fmt(team):
            real_players = [p for p in team if p['id'] > 0]
            avg = sum(p['mmr'] for p in real_players) // len(real_players) if real_players else 0
            return "\n".join([f"• {p['name']} ({p['mmr']})" for p in team]) + f"\n\n📊 **Média:** {avg}"

        cap_blue_name = max(blue_team, key=lambda x: x['mmr'])['name']
        cap_red_name = max(red_team, key=lambda x: x['mmr'])['name']

        embed.add_field(name=f"🔵 Time Azul (Cap. {cap_blue_name})", value=fmt(blue_team), inline=True)
        embed.add_field(name=f"🔴 Time Vermelho (Cap. {cap_red_name})", value=fmt(red_team), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="📢 Instruções", value=f"ID: **{match_id}**\n`.resultado {match_id} Blue/Red`", inline=False)

        await interaction.response.send_message(embed=embed)
        await self.lobby_cog.reset_lobby_state(match_id)
        # Limpa a fila persistida
        await LobbyRepository.clear_state(self.guild_id)

    @discord.ui.button(label="Escolher BLUE", style=discord.ButtonStyle.primary, emoji="🔵")
    async def choose_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.winning_team, red_team=self.losing_team)

    @discord.ui.button(label="Escolher RED", style=discord.ButtonStyle.secondary, emoji="🔴")
    async def choose_red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_match(interaction, blue_team=self.losing_team, red_team=self.winning_team)

    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", row=2)
    async def cancel_bal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Admins.", ephemeral=True)
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.edit_message(content="❌ Criação cancelada. Fila reaberta.", embed=None, view=None)
        self.stop()


# --- VIEW DO LOBBY ---
class LobbyView(BaseInteractiveView):
    def __init__(self, lobby_cog, disabled=False):
        super().__init__(timeout=None)
        self.lobby_cog = lobby_cog
        if disabled:
            self.clear_items()

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="lobby_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_join(interaction)

    @discord.ui.button(label="Sair", style=discord.ButtonStyle.secondary, emoji="🏃", custom_id="lobby_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.process_leave(interaction)

    @discord.ui.button(label="Perfil", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="lobby_profile")
    async def profile_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Use `.perfil` para ver seus stats.", ephemeral=True)

    @discord.ui.button(label="Cancelar Fila (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", custom_id="lobby_cancel", row=1)
    async def cancel_queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Administradores podem cancelar a fila.", ephemeral=True)
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.send_message("❌ Fila cancelada e lobby reaberto.", ephemeral=True)

    @discord.ui.button(label="Resetar Fila (Admin)", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="lobby_reset", row=1)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Apenas Administradores podem resetar a fila.", ephemeral=True)
        await self.lobby_cog.reset_lobby_state()
        await interaction.response.send_message("✅ Fila resetada. Lobby reaberto.", ephemeral=True)


# --- VIEW DE SELEÇÃO DE MODO ---
class ModeSelectView(BaseInteractiveView):
    def __init__(self, lobby_cog, players):
        super().__init__(timeout=900)
        self.lobby_cog = lobby_cog
        self.players = players

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("⛔ Apenas Administradores podem iniciar.", ephemeral=True)
        return False

    async def cleanup(self, interaction: discord.Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(view=None)
            else:
                await interaction.message.edit(view=None)
        except:
            pass

    @discord.ui.button(label="Auto-Balanceado", style=discord.ButtonStyle.primary, emoji="⚖️")
    async def auto_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.start_match_balanced(interaction, self.players)
        await self.cleanup(interaction)
        self.stop()

    @discord.ui.button(label="Capitães (Top Elo)", style=discord.ButtonStyle.secondary, emoji="👑")
    async def captains_mmr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.setup_captains_phase(interaction, self.players, mode="mmr")
        await self.cleanup(interaction)
        self.stop()

    @discord.ui.button(label="Capitães (Aleatório)", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def captains_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.lobby_cog.setup_captains_phase(interaction, self.players, mode="random")
        await self.cleanup(interaction)
        self.stop()

    @discord.ui.button(label="Capitães (Manual)", style=discord.ButtonStyle.secondary, emoji="👮")
    async def captains_manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.setup_captains_manual(interaction, self.players)
        await self.cleanup(interaction)
        self.stop()

    @discord.ui.button(label="Cancelar (Admin)", style=discord.ButtonStyle.secondary, emoji="✖️", row=2)
    async def cancel_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby_cog.reset_lobby_state()
        await self.cleanup(interaction)
        await interaction.followup.send("❌ Setup cancelado e fila reaberta.")
        self.stop()


# --- LOBBY COG ---
class Lobby(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = []
        self.lobby_message: discord.Message = None

        self.current_match_id = 0
        self.lobby_locked = False

        self.DEBUG_QUEUE_LIMIT = 10
        self.DEBUG_FILL_ENABLE = False
        self.QUEUE_LIMIT = self.DEBUG_QUEUE_LIMIT

        self.VOTE_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']

        # Recupera estado ao iniciar
        self.bot.loop.create_task(self.initialize_state())

    # --- INICIALIZAÇÃO DE ESTADO ---
    async def initialize_state(self):
        """
        Recupera o estado do lobby ao iniciar o bot:
        - Verifica partidas IN_PROGRESS para travar o lobby corretamente
        - Restaura a fila persistida se não houver partida ativa
        """
        await self.bot.wait_until_ready()
        try:
            async with get_session() as session:
                stmt = select(func.max(MatchModel.id))
                result = await session.execute(stmt)
                last_id = result.scalar() or 0

                if last_id > 0:
                    stmt_check = select(MatchModel).where(
                        MatchModel.id == last_id,
                        MatchModel.status == MatchStatus.IN_PROGRESS
                    )
                    result_check = await session.execute(stmt_check)
                    active_match = result_check.scalar_one_or_none()

                    if active_match:
                        self.current_match_id = last_id
                        self.lobby_locked = True
                        print(f"✅ [Lobby] Partida #{last_id} EM ANDAMENTO. Lobby travado.")
                        return  # Não restaura fila pois já tem partida ativa
                    else:
                        self.current_match_id = last_id + 1
                        print(f"✅ [Lobby] Próxima partida: #{self.current_match_id}")
                else:
                    self.current_match_id = 1
                    print("✅ [Lobby] Nenhuma partida anterior. Início em #1.")

            # Restaura fila se não há partida ativa
            await self._restore_queue_from_db()

        except Exception as e:
            print(f"❌ [Lobby] Erro ao recuperar estado: {e}")
            self.current_match_id = 1

    async def _restore_queue_from_db(self):
        """Restaura a fila do banco de dados se houver jogadores salvos."""
        for guild in self.bot.guilds:
            try:
                state = await LobbyRepository.get_state(guild.id)
                if state and state['queue']:
                    self.queue = state['queue']
                    print(f"✅ [Lobby] Fila restaurada com {len(self.queue)} jogador(es) no servidor {guild.name}.")
            except Exception as e:
                print(f"❌ [Lobby] Erro ao restaurar fila do servidor {guild.id}: {e}")

    # --- EMBED DO LOBBY ---
    def get_queue_embed(self, locked=False, finished_match_id: int = 0):
        count = len(self.queue)
        limit = self.QUEUE_LIMIT

        if finished_match_id > 0:
            title = f"❌ LOBBY ENCERRADO | Partida #{finished_match_id}"
            color = 0xe74c3c
            desc = f"A Partida #{finished_match_id} foi finalizada/anulada. Use `.fila` para a próxima."
        elif self.current_match_id > 0:
            match_ref = f" #{self.current_match_id}"
            if locked:
                color = 0x000000
                title = f"🔒 LOBBY FECHADO{match_ref}"
                desc = "Aguarde o Admin configurar a partida..."
            else:
                color = 0x3498db
                title = f"🏆 Fila para Partida{match_ref} ({count}/{limit})"
                if count == 0:
                    desc = "A fila está vazia."
                else:
                    lines = [f"`{i+1}.` **{p['name']}** ({p['mmr']}) - {p.get('main_lane','?').title()}" for i, p in enumerate(self.queue)]
                    desc = "\n".join(lines)
        else:
            color = 0x3498db
            title = f"🏆 Fila para Partida #1 ({count}/{limit})"
            if count == 0:
                desc = "A fila está vazia."
            else:
                lines = [f"`{i+1}.` **{p['name']}** ({p['mmr']}) - {p.get('main_lane','?').title()}" for i, p in enumerate(self.queue)]
                desc = "\n".join(lines)

        embed = discord.Embed(title=title, description=desc, color=color)
        if finished_match_id == 0:
            embed.set_footer(text="Clique para entrar • Requer registro (.registrar)")
        return embed

    async def update_lobby_message(self, interaction: discord.Interaction = None, locked=False, finished_match_id: int = 0):
        if locked:
            self.lobby_locked = True

        embed = self.get_queue_embed(locked=locked, finished_match_id=finished_match_id)
        view_disabled = (finished_match_id > 0) or locked
        view = LobbyView(self, disabled=view_disabled)

        try:
            if interaction and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            elif self.lobby_message:
                await self.lobby_message.edit(embed=embed, view=view)
        except:
            pass

    async def reset_lobby_state(self, finished_match_id: int = 0):
        """Reinicia o estado da fila."""
        self.queue = []
        self.lobby_locked = False

        if finished_match_id > 0:
            self.current_match_id = finished_match_id + 1
            await self.update_lobby_message(finished_match_id=finished_match_id)
        else:
            await self.update_lobby_message()

    # --- ENTRAR/SAIR DA FILA ---
    async def process_join(self, interaction: discord.Interaction):
        if len(self.queue) >= self.QUEUE_LIMIT:
            return await interaction.response.send_message("Fila cheia!", ephemeral=True)
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

        # Persiste a fila no banco
        await LobbyRepository.save_state(interaction.guild.id, self.queue, interaction.channel.id)

        if len(self.queue) >= self.QUEUE_LIMIT:
            await self.update_lobby_message(interaction, locked=True)
            await self.prompt_game_mode(interaction.channel)
        else:
            await self.update_lobby_message(interaction)

    async def process_leave(self, interaction: discord.Interaction):
        user = interaction.user
        self.queue = [p for p in self.queue if p['id'] != user.id]
        # Persiste a fila atualizada
        await LobbyRepository.save_state(interaction.guild.id, self.queue, interaction.channel.id)
        await self.update_lobby_message(interaction)

    async def prompt_game_mode(self, channel):
        players_snapshot = self.queue.copy()
        player_names = ", ".join([f"**{p['name']}**" for p in players_snapshot])
        embed = discord.Embed(
            title=f"⚡ Painel de Controle | Partida #{self.current_match_id}",
            description="O Lobby encheu! Escolha o modo:",
            color=0xffd700
        )
        embed.add_field(name="Jogadores", value=player_names, inline=False)
        view = ModeSelectView(self, players_snapshot)
        await channel.send(content="||@here|| 🔔 **Lobby Pronto!**", embed=embed, view=view)

    # --- MODOS DE CRIAÇÃO DE TIMES ---
    async def start_match_balanced(self, interaction, players):
        all_participants = players.copy()
        if self.DEBUG_FILL_ENABLE and len(all_participants) < 10:
            for i in range(10 - len(all_participants)):
                all_participants.append({'id': -1*(i+500), 'name': f'Bot Bal {i}', 'mmr': random.randint(800, 1500), 'main_lane': 'FILL'})

        team_blue, team_red = MatchMaker.balance_teams(all_participants)

        real_blue = [p for p in team_blue if p['id'] > 0]
        real_red = [p for p in team_red if p['id'] > 0]

        cap_blue = max(real_blue, key=lambda x: x['mmr']) if real_blue else team_blue[0]
        cap_red = max(real_red, key=lambda x: x['mmr']) if real_red else team_red[0]

        if random.choice([True, False]):
            win, lose, w_team, l_team = cap_blue, cap_red, team_blue, team_red
        else:
            win, lose, w_team, l_team = cap_red, cap_blue, team_red, team_blue

        embed = discord.Embed(title="⚖️ Times Balanceados! (Sorteio)", color=0xff9900)
        embed.description = f"**{win['name']}** venceu o cara-ou-coroa e escolhe o **LADO**."
        view = BalancedSideSelectView(self, interaction.guild.id, win, w_team, lose, l_team)
        await interaction.followup.send(embed=embed, view=view)

    async def setup_captains_phase(self, interaction, players, mode="mmr"):
        all_participants = players.copy()
        if self.DEBUG_FILL_ENABLE and len(all_participants) < 10:
            for i in range(10 - len(all_participants)):
                all_participants.append({'id': -1*(i+100), 'name': f'Bot Teste {i+1}', 'mmr': random.randint(800, 1500), 'main_lane': 'FILL'})

        if mode == "mmr":
            real_players = [p for p in all_participants if p['id'] > 0]
            if len(real_players) >= 2:
                sorted_p = sorted(real_players, key=lambda x: x['mmr'], reverse=True)
                cap1, cap2 = sorted_p[0], sorted_p[1]
            else:
                random.shuffle(all_participants)
                cap1, cap2 = all_participants[0], all_participants[1]
        else:
            random.shuffle(all_participants)
            cap1, cap2 = all_participants[0], all_participants[1]

        await self.start_coinflip_phase(interaction, all_participants, cap1, cap2)

    async def setup_captains_manual(self, interaction, players):
        if self.DEBUG_FILL_ENABLE and len(players) < 10:
            all_participants = players.copy()
            for i in range(10 - len(all_participants)):
                all_participants.append({'id': -1*(i+100), 'name': f'Bot {i+1}', 'mmr': random.randint(800, 1500), 'main_lane': 'FILL'})
            view = ManualCaptainView(self, all_participants, interaction)
        else:
            view = ManualCaptainView(self, players, interaction)
        await interaction.response.send_message("Selecione os capitães abaixo:", view=view, ephemeral=True)

    async def start_coinflip_phase(self, interaction, all_players, cap1, cap2):
        pool = [p for p in all_players if p['id'] != cap1['id'] and p['id'] != cap2['id']]
        if random.choice([True, False]):
            cap_priority, cap_secondary = cap1, cap2
        else:
            cap_priority, cap_secondary = cap2, cap1

        embed = discord.Embed(title="🪙 Moeda Girada!", color=0xff9900)
        embed.description = f"**{cap_priority['name']}** tem prioridade de Pick (First Pick).\n**{cap_secondary['name']}** escolhe o **Lado**."
        embed.set_footer(text=f"Aguardando {cap_secondary['name']} escolher o lado...")

        view = SideSelectView(self, cap_priority, cap_secondary, pool)

        if interaction.response.is_done():
            sent_message = await interaction.followup.send(embed=embed, view=view)
        else:
            sent_message = await interaction.response.send_message(embed=embed, view=view)

        view.message = sent_message

    # --- MVP / iMVP ---
    async def _start_mvp_polls(self, channel: discord.TextChannel, match_id: int, winner_side: str, match_details: dict):
        if winner_side == 'BLUE':
            winning_team = match_details['blue_team']
            losing_team = match_details['red_team']
            winning_color = 0x3498db
            losing_color = 0xe74c3c
        else:
            winning_team = match_details['red_team']
            losing_team = match_details['blue_team']
            winning_color = 0xe74c3c
            losing_color = 0x3498db

        real_winning_team = [p for p in winning_team if p['id'] > 0]
        real_losing_team = [p for p in losing_team if p['id'] > 0]

        if not real_winning_team or not real_losing_team:
            return

        loser_side = 'BLUE' if winner_side == 'RED' else 'RED'

        mvp_desc = "**Vote no Jogador Mais Valioso (MVP)** do time vencedor:\n\n"
        mvp_players_list = [f"{self.VOTE_EMOJIS[i]} {p['name']} ({p['mmr']})" for i, p in enumerate(real_winning_team)]
        mvp_embed = discord.Embed(
            title=f"⭐ ENQUETE MVP | Partida #{match_id} (Time {winner_side})",
            description=mvp_desc + "\n".join(mvp_players_list),
            color=winning_color
        )
        mvp_embed.set_footer(text="A votação dura 30 minutos.")
        mvp_message = await channel.send(content="||@here||", embed=mvp_embed)
        for i in range(len(real_winning_team)):
            await mvp_message.add_reaction(self.VOTE_EMOJIS[i])

        imvp_desc = "**Vote no Jogador Inverso (iMVP)** do time perdedor:\n\n"
        imvp_players_list = [f"{self.VOTE_EMOJIS[i]} {p['name']} ({p['mmr']})" for i, p in enumerate(real_losing_team)]
        imvp_embed = discord.Embed(
            title=f"👎 ENQUETE iMVP | Partida #{match_id} (Time {loser_side})",
            description=imvp_desc + "\n".join(imvp_players_list),
            color=losing_color
        )
        imvp_embed.set_footer(text="A votação dura 30 minutos.")
        imvp_message = await channel.send(embed=imvp_embed)
        for i in range(len(real_losing_team)):
            await imvp_message.add_reaction(self.VOTE_EMOJIS[i])

        self.bot.loop.create_task(self._finalize_poll_after_delay(
            channel, match_id,
            mvp_message.id, imvp_message.id,
            real_winning_team, real_losing_team
        ))

    async def _calculate_poll_result(self, message: discord.Message, team: list) -> tuple:
        """
        Conta votos reais (exclui bots) usando iteração assíncrona sobre usuários.
        Retorna (texto_resultado: str, winner_ids: list[int]) onde winner_ids são
        os discord_ids dos vencedores (pode ser empate com mais de um).
        """
        # Re-busca a mensagem para ter as reações atualizadas
        try:
            message = await message.channel.fetch_message(message.id)
        except:
            pass

        max_votes = -1
        winner_names = "Ninguém votou!"
        winner_ids = []

        for reaction in message.reactions:
            try:
                emoji_index = self.VOTE_EMOJIS.index(str(reaction.emoji))
            except ValueError:
                continue

            if emoji_index >= len(team):
                continue

            # Conta apenas usuários não-bot
            vote_count = 0
            async for user in reaction.users():
                if not user.bot:
                    vote_count += 1

            player = team[emoji_index]
            player_name = player['name']

            if vote_count > max_votes:
                max_votes = vote_count
                winner_names = f"**{player_name}** com {vote_count} voto(s)."
                winner_ids = [player['id']]
            elif vote_count == max_votes and max_votes > 0:
                winner_names += f" e **{player_name}** (Empate)"
                winner_ids.append(player['id'])

        if max_votes <= 0:
            return "Ninguém votou!", []
        return winner_names, winner_ids

    async def _finalize_poll_after_delay(self, channel, match_id, mvp_msg_id, imvp_msg_id, winning_team, losing_team, delay_minutes=30):
        await asyncio.sleep(delay_minutes * 60)
        try:
            mvp_msg = await channel.fetch_message(mvp_msg_id)
            imvp_msg = await channel.fetch_message(imvp_msg_id)

            mvp_result, mvp_ids = await self._calculate_poll_result(mvp_msg, winning_team)
            imvp_result, imvp_ids = await self._calculate_poll_result(imvp_msg, losing_team)

            # Salva MVP/iMVP no banco (apenas o primeiro em caso de empate)
            for pid in mvp_ids[:1]:
                if pid > 0:
                    await PlayerRepository.increment_mvp(pid)
            for pid in imvp_ids[:1]:
                if pid > 0:
                    await PlayerRepository.increment_imvp(pid)

            final_embed = discord.Embed(
                title=f"🗳️ RESULTADO FINAL | Partida #{match_id}",
                description=f"Votação encerrada após **{delay_minutes} minutos**.",
                color=0x2ecc71
            )
            final_embed.add_field(name="🏆 MVP do Time Vencedor", value=mvp_result, inline=False)
            final_embed.add_field(name="💀 iMVP do Time Perdedor", value=imvp_result, inline=False)
            await channel.send(embed=final_embed)

            await mvp_msg.edit(embed=mvp_msg.embeds[0].set_footer(text="Votação ENCERRADA."), view=None)
            await imvp_msg.edit(embed=imvp_msg.embeds[0].set_footer(text="Votação ENCERRADA."), view=None)

        except discord.NotFound:
            await channel.send(f"❌ Mensagens da enquete da Partida #{match_id} não encontradas.")
        except Exception as e:
            print(f"Erro ao finalizar enquete #{match_id}: {e}")

    # --- ATUALIZAÇÃO DE MMR PÓS-PARTIDA ---
    async def _update_players_mmr_after_match(self, match_details: dict):
        """Recalcula e atualiza o MMR de todos os participantes com base no rank cached."""
        all_players = match_details['blue_team'] + match_details['red_team']
        updated = 0
        for player_data in all_players:
            if player_data['id'] <= 0:
                continue
            player = await PlayerRepository.get_player_by_discord_id(player_data['id'])
            if not player:
                continue

            # Prioriza SoloQ, fallback Flex
            if player.solo_tier and player.solo_tier.upper() not in ('UNRANKED', ''):
                new_mmr = MatchMaker.calculate_adjusted_mmr(
                    player.solo_tier, player.solo_rank, player.solo_lp,
                    player.solo_wins, player.solo_losses, 'RANKED_SOLO_5x5'
                )
            elif player.flex_tier and player.flex_tier.upper() not in ('UNRANKED', ''):
                new_mmr = MatchMaker.calculate_adjusted_mmr(
                    player.flex_tier, player.flex_rank, player.flex_lp,
                    player.flex_wins, player.flex_losses, 'RANKED_FLEX_SR'
                )
            else:
                continue

            await PlayerRepository.update_mmr_direct(player_data['id'], new_mmr)
            updated += 1

        print(f"[Lobby] MMR atualizado para {updated} jogador(es) após resultado.")

    # --- CARGOS ---
    async def _assign_match_roles(self, guild: discord.Guild, match_details: dict, winner_side: str):
        """Remove cargos anteriores dos 10 jogadores e reatribui conforme resultado."""
        winner_role_id, loser_role_id = await GuildRepository.get_match_roles(guild.id)
        if not winner_role_id and not loser_role_id:
            return  # Nenhum cargo configurado — ignora silenciosamente

        winner_role = guild.get_role(winner_role_id) if winner_role_id else None
        loser_role  = guild.get_role(loser_role_id)  if loser_role_id  else None

        winning_team = match_details['blue_team'] if winner_side == 'BLUE' else match_details['red_team']
        losing_team  = match_details['red_team']  if winner_side == 'BLUE' else match_details['blue_team']

        all_players = winning_team + losing_team
        roles_to_clear = [r for r in (winner_role, loser_role) if r]

        for p in all_players:
            member = guild.get_member(p['id'])
            if not member:
                continue
            try:
                # Remove ambos os cargos primeiro
                if roles_to_clear:
                    await member.remove_roles(*roles_to_clear, reason="Liga Interna — resultado da partida")
                # Atribui o cargo correto
                if p in winning_team and winner_role:
                    await member.add_roles(winner_role, reason="Liga Interna — vencedor")
                elif p in losing_team and loser_role:
                    await member.add_roles(loser_role, reason="Liga Interna — perdedor")
            except discord.Forbidden:
                print(f"[Roles] Sem permissão para atribuir cargo a {p['name']}")
            except Exception as e:
                print(f"[Roles] Erro ao atribuir cargo a {p['name']}: {e}")

        print(f"[Roles] Cargos atualizados para {len(all_players)} jogador(es).")

    # --- STREAKS ---
    async def _update_and_announce_streaks(self, channel: discord.TextChannel, match_details: dict, winner_side: str):
        """Atualiza streaks e anuncia marcos alcançados."""
        winning_team = match_details['blue_team'] if winner_side == 'BLUE' else match_details['red_team']
        losing_team = match_details['red_team'] if winner_side == 'BLUE' else match_details['blue_team']

        announcements = []

        for p in winning_team:
            if p['id'] <= 0:
                continue
            streak, best = await PlayerRepository.update_streak(p['id'], won=True)
            if streak in STREAK_MILESTONES:
                announcements.append((p['name'], streak, True))

        for p in losing_team:
            if p['id'] <= 0:
                continue
            await PlayerRepository.update_streak(p['id'], won=False)

        if announcements:
            for name, streak, is_win in announcements:
                if streak >= 10:
                    title = "👑 DOMINÂNCIA ABSOLUTA!"
                    desc = f"**{name}** está imparável com **{streak} vitórias seguidas**!\nAlguém para esse monstro?"
                    color = 0xffd700
                else:
                    title = "🔥 SEQUÊNCIA DE VITÓRIAS!"
                    desc = f"**{name}** está em chamas na Liga!\n**{streak} vitórias seguidas** e contando..."
                    color = 0xff4500

                embed = discord.Embed(title=title, description=desc, color=color)
                embed.set_footer(text=f"Use .perfil para ver o histórico de conquistas")
                await channel.send(embed=embed)

    # --- COMANDOS ---
    @commands.command(name="fila")
    async def fila(self, ctx):
        if self.current_match_id > 0 and await MatchRepository.get_match_details(self.current_match_id):
            return await ctx.reply(f"⚠️ Já existe uma partida em andamento (ID #{self.current_match_id}). Finalize-a antes de criar nova fila.")

        if self.lobby_locked:
            return await ctx.reply("⚠️ Um lobby já está sendo configurado. Aguarde ou cancele o atual.")

        if self.current_match_id == 0:
            self.current_match_id = 1

        if self.lobby_message:
            try: await self.lobby_message.delete()
            except: pass

        embed = self.get_queue_embed()
        view = LobbyView(self)
        self.lobby_message = await ctx.send(embed=embed, view=view)

        # Persiste canal da fila
        await LobbyRepository.save_state(ctx.guild.id, self.queue, ctx.channel.id)

    @commands.command(name="resetar")
    async def resetar(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("⛔ Apenas Administradores.")

        if self.QUEUE_LIMIT == 10:
            self.QUEUE_LIMIT = self.DEBUG_QUEUE_LIMIT
            await ctx.reply(f"✅ Modo DEBUG ativado. Limite: **{self.QUEUE_LIMIT}**.")
        else:
            self.QUEUE_LIMIT = 10
            await ctx.reply(f"✅ Modo PRODUÇÃO ativado. Limite: **{self.QUEUE_LIMIT}**.")

        await self.reset_lobby_state()

    @commands.command(name="resultado")
    async def resultado(self, ctx, match_id: int = None, winner: str = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id or not winner:
            return await ctx.reply("❌ Uso: `.resultado <ID> <Blue/Red>`")

        winner = winner.upper()
        if winner == 'AZUL': winner = 'BLUE'
        if winner == 'VERMELHO': winner = 'RED'
        if winner not in ['BLUE', 'RED']:
            return await ctx.reply("❌ Lado inválido. Use Blue ou Red.")

        match_details = await MatchRepository.get_match_details(match_id)
        if not match_details:
            return await ctx.reply(f"❌ Partida #{match_id} não encontrada ou já finalizada/anulada.")

        status = await MatchRepository.finish_match(match_id, winner)

        if status == "SUCCESS":
            embed = discord.Embed(
                title=f"✅ Partida #{match_id} Finalizada!",
                description=f"Vencedor: **TIME {winner}**",
                color=0x2ecc71
            )
            await ctx.reply(embed=embed)

            # 1. Atualiza MMR de todos os participantes
            await self._update_players_mmr_after_match(match_details)

            # 2. Atualiza e anuncia streaks
            await self._update_and_announce_streaks(ctx.channel, match_details, winner)

            # 3. Atribui cargos de vencedor/perdedor
            await self._assign_match_roles(ctx.guild, match_details, winner)

            # 4. Inicia votações MVP/iMVP
            await self._start_mvp_polls(ctx.channel, match_id, winner, match_details)

            # 5. Reseta o lobby
            await self.reset_lobby_state(match_id)

        elif status == "ALREADY_FINISHED":
            await ctx.reply(f"🔒 Partida #{match_id} já foi finalizada.")
        else:
            await ctx.reply(f"❌ Não foi possível finalizar a Partida #{match_id}.")

    @commands.command(name="anular")
    async def anular(self, ctx, match_id: int = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("⛔ Apenas Administradores.")
        if not match_id:
            return await ctx.reply("❌ Uso: `.anular <ID>`")

        status = await MatchRepository.cancel_match(match_id)

        if status == "SUCCESS":
            await ctx.reply(f"🚫 Partida **#{match_id}** ANULADA.")
            await self.reset_lobby_state(match_id)
        elif status == "NOT_ACTIVE":
            await ctx.reply("❌ Partida não está ativa.")
        else:
            await ctx.reply("❌ Partida não encontrada.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Lobby(bot))
