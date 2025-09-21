# cogs/scrim.py
from typing import Optional, Dict, List
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
import pytz
import random

from utils.logger import get_logger
from utils import config


class GameSelectView(discord.ui.View):
    """Game selection view with role tagging support"""

    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=1800)  # 30 minutes for creation flow
        self.bot = bot
        self.guild_id = guild_id
        self.selected_game = None
        self.selected_role_id = None

        # Game options with role IDs
        self.game_options = [
            discord.SelectOption(
                label="Valorant",
                value="VAL:1209013681753563156",
                description="Tactical FPS by Riot Games",
                emoji="🎯"
            ),
            discord.SelectOption(
                label="Teamfight Tactics",
                value="TFT:1333664246608957461",
                description="Auto-battler strategy game",
                emoji="♟️"
            ),
            discord.SelectOption(
                label="League of Legends",
                value="LOL:1209014051317743626",
                description="MOBA by Riot Games",
                emoji="⚔️"
            ),
            discord.SelectOption(
                label="PUBG",
                value="PUBG:1417766140121186359",
                description="Battle Royale shooter",
                emoji="🔫"
            ),
            discord.SelectOption(
                label="Other Games",
                value="OG:1417766914003959878",
                description="Any other game",
                emoji="🎮"
            )
        ]

        self.game_select = discord.ui.Select(
            placeholder="Choose a game...",
            options=self.game_options,
            custom_id="game_select"
        )
        self.game_select.callback = self.game_selected
        self.add_item(self.game_select)

    async def game_selected(self, interaction: discord.Interaction):
        """Handle game selection"""
        selection = self.game_select.values[0]
        game_name, role_id = selection.split(":")

        # Map abbreviations to full names
        game_names = {
            "VAL": "Valorant",
            "TFT": "Teamfight Tactics",
            "LOL": "League of Legends",
            "PUBG": "PUBG",
            "OG": "Other Games"
        }

        self.selected_game = game_names.get(game_name, game_name)
        self.selected_role_id = int(role_id)

        # Continue to game mode selection
        gamemode_view = GameModeSelectView(
            self.bot, self.guild_id, self.selected_game, self.selected_role_id
        )

        embed = discord.Embed(
            title="🎮 Game Mode Selection",
            description=f"**Selected Game:** {self.selected_game}\n\nNow choose the game mode:",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=gamemode_view)


class GameModeSelectView(discord.ui.View):
    """Game mode selection view"""

    def __init__(self, bot, guild_id: int, game: str, role_id: int):
        super().__init__(timeout=1800)  # 30 minutes for creation flow
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.role_id = role_id
        self.selected_gamemode = None

        # Game mode options based on selected game
        gamemode_options = self.get_gamemode_options(game)

        self.gamemode_select = discord.ui.Select(
            placeholder="Choose game mode...",
            options=gamemode_options,
            custom_id="gamemode_select"
        )
        self.gamemode_select.callback = self.gamemode_selected
        self.add_item(self.gamemode_select)

        # Back button
        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_game_selection
        self.add_item(back_button)

    def get_gamemode_options(self, game: str) -> List[discord.SelectOption]:
        """Get game mode options based on selected game"""
        gamemode_map = {
            "Valorant": [
                discord.SelectOption(label="5v5 Competitive", value="5v5", emoji="🏆"),
                discord.SelectOption(label="5v5 Unrated", value="5v5 Unrated", emoji="🎯"),
                discord.SelectOption(label="Custom Game", value="Custom", emoji="⚙️")
            ],
            "League of Legends": [
                discord.SelectOption(label="5v5 Summoner's Rift", value="5v5 SR", emoji="🏰"),
                discord.SelectOption(label="5v5 ARAM", value="5v5 ARAM", emoji="❄️"),
                discord.SelectOption(label="Custom Game", value="Custom", emoji="⚙️")
            ],
            "Teamfight Tactics": [
                discord.SelectOption(label="8 Player Lobby", value="8P Lobby", emoji="♟️"),
                discord.SelectOption(label="Tournament", value="Tournament", emoji="🏆")
            ],
            "PUBG": [
                discord.SelectOption(label="Squad (4v4v...)", value="Squad", emoji="👥"),
                discord.SelectOption(label="Duo (2v2v...)", value="Duo", emoji="👫"),
                discord.SelectOption(label="Solo", value="Solo", emoji="🕴️"),
                discord.SelectOption(label="Custom Room", value="Custom", emoji="⚙️")
            ]
        }

        return gamemode_map.get(game, [
            discord.SelectOption(label="Standard", value="Standard", emoji="🎮"),
            discord.SelectOption(label="Custom", value="Custom", emoji="⚙️")
        ])

    async def gamemode_selected(self, interaction: discord.Interaction):
        """Handle game mode selection"""
        self.selected_gamemode = self.gamemode_select.values[0]

        # Continue to tier selection
        tier_view = TierSelectView(
            self.bot, self.guild_id, self.game, self.selected_gamemode, self.role_id
        )

        embed = discord.Embed(
            title="🏆 Tier Range Selection",
            description=f"**Game:** {self.game}\n**Mode:** {self.selected_gamemode}\n\nSelect the tier range:",
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(embed=embed, view=tier_view)

    async def back_to_game_selection(self, interaction: discord.Interaction):
        """Go back to game selection"""
        game_view = GameSelectView(self.bot, self.guild_id)

        embed = discord.Embed(
            title="🎮 Game Selection",
            description="Choose the game for your scrim:",
            color=discord.Color.green()
        )

        await interaction.response.edit_message(embed=embed, view=game_view)


class TierSelectView(discord.ui.View):
    """Tier range selection view"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, role_id: int):
        super().__init__(timeout=1800)  # 30 minutes for creation flow
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.role_id = role_id
        self.selected_tier = None

        # Tier options (generalized for all games)
        tier_options = [
            discord.SelectOption(label="All Tiers", value="All tiers", emoji="🌐"),
            discord.SelectOption(label="Iron - Bronze", value="Iron-Bronze", emoji="🥉"),
            discord.SelectOption(label="Silver - Gold", value="Silver-Gold", emoji="🥈"),
            discord.SelectOption(label="Gold - Platinum", value="Gold-Platinum", emoji="🥇"),
            discord.SelectOption(label="Platinum - Diamond", value="Plat-Diamond", emoji="💎"),
            discord.SelectOption(label="Diamond+", value="Diamond+", emoji="💎✨"),
            discord.SelectOption(label="Immortal+", value="Immortal+", emoji="⭐"),
            discord.SelectOption(label="Beginner Friendly", value="Beginner", emoji="🌱"),
            discord.SelectOption(label="Competitive", value="Competitive", emoji="🏆")
        ]

        self.tier_select = discord.ui.Select(
            placeholder="Choose tier range...",
            options=tier_options,
            custom_id="tier_select"
        )
        self.tier_select.callback = self.tier_selected
        self.add_item(self.tier_select)

        # Back button
        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_gamemode_selection
        self.add_item(back_button)

    async def tier_selected(self, interaction: discord.Interaction):
        """Handle tier selection"""
        self.selected_tier = self.tier_select.values[0]

        # Continue to time selection
        time_view = TimeSelectView(
            self.bot, self.guild_id, self.game, self.gamemode,
            self.selected_tier, self.role_id
        )

        embed = discord.Embed(
            title="⏰ Start Time Selection",
            description=f"**Game:** {self.game}\n**Mode:** {self.gamemode}\n**Tier:** {self.selected_tier}\n\nWhen should the scrim start?",
            color=discord.Color.orange()
        )

        await interaction.response.edit_message(embed=embed, view=time_view)

    async def back_to_gamemode_selection(self, interaction: discord.Interaction):
        """Go back to game mode selection"""
        gamemode_view = GameModeSelectView(self.bot, self.guild_id, self.game, self.role_id)

        embed = discord.Embed(
            title="🎮 Game Mode Selection",
            description=f"**Selected Game:** {self.game}\n\nNow choose the game mode:",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=gamemode_view)


class TimeSelectView(discord.ui.View):
    """Time selection view with quick options"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, role_id: int):
        super().__init__(timeout=1800)  # 30 minutes for creation flow
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.role_id = role_id
        self.selected_time = None

        # Quick time options
        time_options = [
            discord.SelectOption(label="In 30 minutes", value="30min", emoji="⏰"),
            discord.SelectOption(label="In 1 hour", value="1hour", emoji="🕐"),
            discord.SelectOption(label="In 2 hours", value="2hour", emoji="🕑"),
            discord.SelectOption(label="Tonight (8 PM EST)", value="tonight", emoji="🌙"),
            discord.SelectOption(label="Custom Time", value="custom", emoji="⚙️")
        ]

        self.time_select = discord.ui.Select(
            placeholder="Choose start time...",
            options=time_options,
            custom_id="time_select"
        )
        self.time_select.callback = self.time_selected
        self.add_item(self.time_select)

        # Back button
        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_tier_selection
        self.add_item(back_button)

    async def time_selected(self, interaction: discord.Interaction):
        """Handle time selection"""
        selection = self.time_select.values[0]

        if selection == "custom":
            # Show custom time modal
            modal = CustomTimeModal(
                self.bot, self.guild_id, self.game, self.gamemode,
                self.tier, self.role_id
            )
            await interaction.response.send_modal(modal)
            return

        # Calculate time based on selection
        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)

        if selection == "30min":
            self.selected_time = now + timedelta(minutes=30)
        elif selection == "1hour":
            self.selected_time = now + timedelta(hours=1)
        elif selection == "2hour":
            self.selected_time = now + timedelta(hours=2)
        elif selection == "tonight":
            tonight = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if tonight <= now:
                tonight += timedelta(days=1)
            self.selected_time = tonight

        # Continue to player count selection
        await self.continue_to_player_count(interaction)

    async def continue_to_player_count(self, interaction: discord.Interaction):
        """Continue to player count selection"""
        player_view = PlayerCountSelectView(
            self.bot, self.guild_id, self.game, self.gamemode,
            self.tier, self.selected_time, self.role_id
        )

        embed = discord.Embed(
            title="👥 Player Count Selection",
            description=f"**Game:** {self.game}\n**Mode:** {self.gamemode}\n**Tier:** {self.tier}\n**Time:** {self.selected_time.strftime('%Y-%m-%d %H:%M EST')}\n\nHow many players maximum?",
            color=discord.Color.purple()
        )

        await interaction.response.edit_message(embed=embed, view=player_view)

    async def back_to_tier_selection(self, interaction: discord.Interaction):
        """Go back to tier selection"""
        tier_view = TierSelectView(self.bot, self.guild_id, self.game, self.gamemode, self.role_id)

        embed = discord.Embed(
            title="🏆 Tier Range Selection",
            description=f"**Game:** {self.game}\n**Mode:** {self.gamemode}\n\nSelect the tier range:",
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(embed=embed, view=tier_view)


class CustomTimeModal(discord.ui.Modal):
    """Modal for custom time input"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, role_id: int):
        super().__init__(title="Custom Time", timeout=1800)  # 30 minutes for creation flow
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.role_id = role_id

        self.time_input = discord.ui.TextInput(
            label="Start Time (EST)",
            placeholder="Examples: 2024-12-25 19:30, today 20:00, tomorrow 15:00",
            required=True,
            max_length=50
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle custom time submission"""
        eastern = pytz.timezone('America/New_York')

        try:
            parsed_time = await self.parse_time_input(self.time_input.value, eastern)
            if not parsed_time:
                await interaction.response.send_message(
                    "❌ Invalid time format. Please try again.", ephemeral=True
                )
                return

            if parsed_time <= datetime.now(eastern):
                await interaction.response.send_message(
                    "❌ Start time must be in the future.", ephemeral=True
                )
                return

            # Continue to player count selection
            player_view = PlayerCountSelectView(
                self.bot, self.guild_id, self.game, self.gamemode,
                self.tier, parsed_time, self.role_id
            )

            embed = discord.Embed(
                title="👥 Player Count Selection",
                description=f"**Game:** {self.game}\n**Mode:** {self.gamemode}\n**Tier:** {self.tier}\n**Time:** {parsed_time.strftime('%Y-%m-%d %H:%M EST')}\n\nHow many players maximum?",
                color=discord.Color.purple()
            )

            await interaction.response.send_message(embed=embed, view=player_view, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                "❌ Error processing time. Please try again.", ephemeral=True
            )

    async def parse_time_input(self, time_input: str, timezone) -> Optional[datetime]:
        """Parse various time input formats"""
        time_input = time_input.strip().lower()
        now = datetime.now(timezone)

        try:
            # Format: "YYYY-MM-DD HH:MM"
            if len(time_input.split()) == 2 and '-' in time_input:
                return datetime.strptime(time_input, "%Y-%m-%d %H:%M").replace(tzinfo=timezone)

            # Format: "today HH:MM"
            if time_input.startswith("today"):
                time_part = time_input.replace("today", "").strip()
                time_obj = datetime.strptime(time_part, "%H:%M").time()
                return datetime.combine(now.date(), time_obj).replace(tzinfo=timezone)

            # Format: "tomorrow HH:MM"
            if time_input.startswith("tomorrow"):
                time_part = time_input.replace("tomorrow", "").strip()
                time_obj = datetime.strptime(time_part, "%H:%M").time()
                tomorrow = now.date() + timedelta(days=1)
                return datetime.combine(tomorrow, time_obj).replace(tzinfo=timezone)

            # Format: "HH:MM" (today)
            if ':' in time_input and len(time_input.split(':')) == 2:
                time_obj = datetime.strptime(time_input, "%H:%M").time()
                result = datetime.combine(now.date(), time_obj).replace(tzinfo=timezone)
                if result <= now:
                    result += timedelta(days=1)
                return result

        except (ValueError, TypeError):
            pass

        return None


class PlayerCountSelectView(discord.ui.View):
    """Player count selection view"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, start_time: datetime, role_id: int):
        super().__init__(timeout=1800)  # 30 minutes for creation flow
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.start_time = start_time
        self.role_id = role_id

        # Common player count options
        player_options = [
            discord.SelectOption(label="6 Players", value="6", emoji="👥"),
            discord.SelectOption(label="8 Players", value="8", emoji="👥"),
            discord.SelectOption(label="10 Players", value="10", emoji="👥"),
            discord.SelectOption(label="12 Players", value="12", emoji="👥"),
            discord.SelectOption(label="16 Players", value="16", emoji="👥"),
            discord.SelectOption(label="20 Players", value="20", emoji="👥"),
            discord.SelectOption(label="Custom Amount", value="custom", emoji="⚙️")
        ]

        self.player_select = discord.ui.Select(
            placeholder="Choose max players...",
            options=player_options,
            custom_id="player_select"
        )
        self.player_select.callback = self.player_count_selected
        self.add_item(self.player_select)

        # Back button
        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_time_selection
        self.add_item(back_button)

    async def player_count_selected(self, interaction: discord.Interaction):
        """Handle player count selection"""
        selection = self.player_select.values[0]

        if selection == "custom":
            # Show custom player count modal
            modal = CustomPlayerCountModal(
                self.bot, self.guild_id, self.game, self.gamemode,
                self.tier, self.start_time, self.role_id
            )
            await interaction.response.send_modal(modal)
            return

        max_players = int(selection)

        # Create the scrim
        await self.create_scrim(interaction, max_players)

    async def create_scrim(self, interaction: discord.Interaction, max_players: int):
        """Create the scrim with all selected options"""
        await interaction.response.defer(ephemeral=True)

        # Get the scrim cog and create scrim
        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            scrim_id = await scrim_cog.create_scrim(
                guild_id=self.guild_id,
                organizer_id=interaction.user.id,
                game=self.game,
                gamemode=self.gamemode,
                tier_range=self.tier,
                start_time=self.start_time,
                max_players=max_players,
                channel_id=interaction.channel_id
            )

            if scrim_id:
                await interaction.followup.send("✅ Scrim created successfully!", ephemeral=True)

                # Post scrim message and tag role
                await scrim_cog.post_scrim_message(interaction.channel, scrim_id)

                # Tag the appropriate role
                role = interaction.guild.get_role(self.role_id)
                if role:
                    role_mention = f"{role.mention}"
                    embed = discord.Embed(
                        title="🔔 New Scrim Available!",
                        description=f"A new **{self.game}** scrim has been created!",
                        color=discord.Color.green()
                    )
                    await interaction.channel.send(content=role_mention, embed=embed)
            else:
                await interaction.followup.send("❌ Error creating scrim.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Scrim system not found.", ephemeral=True)

    async def back_to_time_selection(self, interaction: discord.Interaction):
        """Go back to time selection"""
        time_view = TimeSelectView(
            self.bot, self.guild_id, self.game, self.gamemode, self.tier, self.role_id
        )

        embed = discord.Embed(
            title="⏰ Start Time Selection",
            description=f"**Game:** {self.game}\n**Mode:** {self.gamemode}\n**Tier:** {self.tier}\n\nWhen should the scrim start?",
            color=discord.Color.orange()
        )

        await interaction.response.edit_message(embed=embed, view=time_view)


class CustomPlayerCountModal(discord.ui.Modal):
    """Modal for custom player count input"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, start_time: datetime, role_id: int):
        super().__init__(title="Custom Player Count", timeout=1800)  # 30 minutes for creation flow
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.start_time = start_time
        self.role_id = role_id

        self.player_input = discord.ui.TextInput(
            label="Maximum Players",
            placeholder="Enter number between 2-50",
            required=True,
            max_length=2
        )
        self.add_item(self.player_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle custom player count submission"""
        try:
            max_players = int(self.player_input.value)
            if max_players < 2 or max_players > 50:
                await interaction.response.send_message(
                    "❌ Player count must be between 2-50.", ephemeral=True
                )
                return

            # Create the scrim
            player_view = PlayerCountSelectView(
                self.bot, self.guild_id, self.game, self.gamemode,
                self.tier, self.start_time, self.role_id
            )
            await player_view.create_scrim(interaction, max_players)

        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number.", ephemeral=True
            )


class MapPoolModal(discord.ui.Modal):
    """Modal for managing map pool"""

    def __init__(self, bot, guild_id: int, current_maps: List[str]):
        super().__init__(title="Map Pool Settings", timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.logger = get_logger("Internal Matches")

        # Create the current maps string, ensuring it's not too long
        current_maps_str = ", ".join(current_maps)
        if len(current_maps_str) > 490:  # Leave some room for safety
            current_maps_str = current_maps_str[:490] + "..."

        # Map pool input
        self.map_input = discord.ui.TextInput(
            label="Map List (separated by commas)",
            placeholder="Example: Bind, Haven, Split, Ascent...",
            default=current_maps_str,
            required=True,
            max_length=500,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.map_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse maps from input
            map_list = [map_name.strip() for map_name in self.map_input.value.split(',') if map_name.strip()]

            if len(map_list) < 2:
                await interaction.response.send_message("❌ At least 2 maps are required.", ephemeral=True)
                return

            # Get the scrim cog and update map pool
            scrim_cog = self.bot.get_cog('ScrimCog')
            if scrim_cog:
                success = await scrim_cog.update_map_pool(self.guild_id, map_list)
                if success:
                    # Create response message with truncation if too long
                    map_list_str = ', '.join(map_list)
                    if len(map_list_str) > 1500:
                        map_list_str = map_list_str[:1500] + "... (list too long, showing partial)"

                    await interaction.response.send_message(
                        f"✅ Map pool updated successfully!\n**Total {len(map_list)} maps**: {map_list_str}",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message("❌ Error updating map pool.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Scrim system not found.", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in map pool modal for guild {self.guild_id}: {e}",
                              extra={'guild_id': self.guild_id})
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        self.logger.error(f"Modal error for guild {self.guild_id}: {error}", extra={'guild_id': self.guild_id})
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)


class ScrimView(discord.ui.View):
    """Improved scrim view with better button styling"""

    def __init__(self, bot, scrim_data: Dict):
        super().__init__(timeout=None)
        self.bot = bot
        self.scrim_data = scrim_data
        self.scrim_id = scrim_data['id']
        self.guild_id = scrim_data['guild_id']
        self.logger = get_logger("Internal Matches")

        # Update button states
        self.update_button_states()

    def update_button_states(self):
        """Update button states based on current scrim status"""
        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)
        start_time = self.scrim_data['start_time']

        if start_time.tzinfo is None:
            start_time = eastern.localize(start_time)

        time_until_start = start_time - now
        buttons_locked = time_until_start <= timedelta(minutes=30)

        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id in [
                'join_scrim', 'leave_scrim', 'join_queue', 'leave_queue'
            ]:
                item.disabled = buttons_locked

    @discord.ui.button(
        label="Join",
        style=discord.ButtonStyle.success,
        custom_id="join_scrim",
        emoji="✅"
    )
    async def join_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Join the scrim"""
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.join_scrim(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(
        label="Leave",
        style=discord.ButtonStyle.danger,
        custom_id="leave_scrim",
        emoji="❌"
    )
    async def leave_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Leave the scrim"""
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.leave_scrim(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(
        label="Join Queue",
        style=discord.ButtonStyle.secondary,
        custom_id="join_queue",
        emoji="⏳"
    )
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Join the queue"""
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.join_queue(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(
        label="Leave Queue",
        style=discord.ButtonStyle.secondary,
        custom_id="leave_queue",
        emoji="🚪"
    )
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Leave the queue"""
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.leave_queue(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.danger,
        custom_id="cancel_scrim",
        emoji="🗑️"
    )
    async def cancel_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the scrim"""
        scrim_cog = self.bot.get_cog('ScrimCog')
        if not scrim_cog:
            await interaction.response.send_message("❌ Scrim system not found.", ephemeral=True)
            return

        # Check permissions
        is_organizer = interaction.user.id == self.scrim_data['organizer_id']
        is_staff = scrim_cog.has_staff_permissions(interaction.user)

        if not (is_organizer or is_staff):
            await interaction.response.send_message("❌ You don't have permission to cancel this scrim.", ephemeral=True)
            return

        # Confirmation embed
        embed = discord.Embed(
            title="⚠️ Confirm Scrim Cancellation",
            description="Are you sure you want to cancel this scrim?\nAll participants will be notified.",
            color=discord.Color.red()
        )

        view = discord.ui.View(timeout=60)
        confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
        cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        async def confirm_callback(confirm_interaction):
            await confirm_interaction.response.defer()
            success = await scrim_cog.cancel_scrim(self.scrim_id, interaction.user.id)
            if success:
                await confirm_interaction.followup.send("✅ Scrim cancelled.", ephemeral=True)
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)
            else:
                await confirm_interaction.followup.send("❌ Error cancelling scrim.", ephemeral=True)

        async def cancel_callback(cancel_interaction):
            await cancel_interaction.response.send_message("Cancelled.", ephemeral=True)

        confirm_button.callback = confirm_callback
        cancel_button.callback = cancel_callback
        view.add_item(confirm_button)
        view.add_item(cancel_button)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ScrimCreateView(discord.ui.View):
    """Improved persistent view with better styling"""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = get_logger("Internal Matches")

    @discord.ui.button(
        label="Create Scrim",
        style=discord.ButtonStyle.primary,
        custom_id="create_scrim_improved",
        emoji="🎮"
    )
    async def create_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Start the improved scrim creation process"""
        # Check if feature is enabled
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message(
                "❌ Scrim system is disabled on this server.",
                ephemeral=True
            )
            return

        # Start with game selection
        game_view = GameSelectView(self.bot, interaction.guild.id)

        embed = discord.Embed(
            title="🎮 Game Selection",
            description="Choose the game for your scrim:",
            color=discord.Color.green()
        )
        embed.set_footer(text="Use the dropdown below to select your game")

        await interaction.response.send_message(embed=embed, view=game_view, ephemeral=True)


class ScrimCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("Internal Matches")
        self.scrims_data = {}  # In-memory storage for active scrims
        self.scrims_file = "data/scrims.json"
        self.map_pools_file = "data/map_pools.json"
        self.map_pools = {}  # Guild ID -> List of maps

        # Default Valorant map pool
        self.default_valorant_maps = [
            "Bind", "Haven", "Split", "Ascent", "Icebox",
            "Breeze", "Fracture", "Pearl", "Lotus", "Sunset", "Abyss", "Corrado"
        ]

        # Start tasks after bot is ready
        self.bot.loop.create_task(self.wait_and_start_tasks())

    async def wait_and_start_tasks(self):
        """Wait for bot to be ready then start tasks"""
        await self.bot.wait_until_ready()
        await self.load_scrims_data()
        await self.load_map_pools()
        await self.setup_scrim_panels()

        # Start notification and cleanup tasks
        self.scrim_notifications.start()
        self.cleanup_old_scrims.start()

    def has_staff_permissions(self, member: discord.Member) -> bool:
        """Check if member has staff permissions"""
        if member.guild_permissions.administrator:
            return True

        admin_role_id = config.get_role_id(member.guild.id, 'admin_role')
        if admin_role_id:
            admin_role = discord.utils.get(member.roles, id=admin_role_id)
            if admin_role:
                return True

        staff_role_id = config.get_role_id(member.guild.id, 'staff_role')
        if staff_role_id:
            staff_role = discord.utils.get(member.roles, id=staff_role_id)
            return staff_role is not None

        return False

    async def load_scrims_data(self):
        """Load scrims data from file"""
        try:
            if os.path.exists(self.scrims_file):
                with open(self.scrims_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert string dates back to datetime objects
                    for scrim_id, scrim_data in data.items():
                        scrim_data['start_time'] = datetime.fromisoformat(scrim_data['start_time'])
                        scrim_data['created_at'] = datetime.fromisoformat(scrim_data['created_at'])
                    self.scrims_data = data
                self.logger.info("Loaded scrims data", extra={'guild_id': None})
        except Exception as e:
            self.logger.error(f"Error loading scrims data: {e}", extra={'guild_id': None})

    async def save_scrims_data(self):
        """Save scrims data to file"""
        try:
            os.makedirs(os.path.dirname(self.scrims_file), exist_ok=True)
            # Convert datetime objects to ISO format for JSON
            data_to_save = {}
            for scrim_id, scrim_data in self.scrims_data.items():
                data_copy = scrim_data.copy()
                data_copy['start_time'] = scrim_data['start_time'].isoformat()
                data_copy['created_at'] = scrim_data['created_at'].isoformat()
                data_to_save[scrim_id] = data_copy

            with open(self.scrims_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving scrims data: {e}", extra={'guild_id': None})

    async def load_map_pools(self):
        """Load map pools from file"""
        try:
            if os.path.exists(self.map_pools_file):
                with open(self.map_pools_file, 'r', encoding='utf-8') as f:
                    # Convert string keys back to int
                    data = json.load(f)
                    self.map_pools = {int(guild_id): maps for guild_id, maps in data.items()}
                self.logger.info("Loaded map pools data", extra={'guild_id': None})
            else:
                self.map_pools = {}
        except Exception as e:
            self.logger.error(f"Error loading map pools: {e}", extra={'guild_id': None})
            self.map_pools = {}

    async def save_map_pools(self):
        """Save map pools to file"""
        try:
            os.makedirs(os.path.dirname(self.map_pools_file), exist_ok=True)
            # Convert int keys to string for JSON
            data_to_save = {str(guild_id): maps for guild_id, maps in self.map_pools.items()}

            with open(self.map_pools_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving map pools: {e}", extra={'guild_id': None})

    def get_map_pool(self, guild_id: int) -> List[str]:
        """Get map pool for a guild, return default if not set"""
        return self.map_pools.get(guild_id, self.default_valorant_maps.copy())

    async def update_map_pool(self, guild_id: int, maps: List[str]) -> bool:
        """Update map pool for a guild"""
        try:
            self.map_pools[guild_id] = maps
            await self.save_map_pools()
            self.logger.info(f"Updated map pool for guild {guild_id}: {maps}", extra={'guild_id': guild_id})
            return True
        except Exception as e:
            self.logger.error(f"Error updating map pool for guild {guild_id}: {e}", extra={'guild_id': guild_id})
            return False

    async def setup_scrim_panels(self):
        """Setup scrim creation panels in configured channels"""
        all_configs = config.get_all_server_configs()
        for guild_id_str, guild_config in all_configs.items():
            if guild_config.get('features', {}).get('scrim_system'):
                guild_id = int(guild_id_str)
                scrim_channel_id = config.get_channel_id(guild_id, 'scrim_channel')

                if scrim_channel_id:
                    channel = self.bot.get_channel(scrim_channel_id)
                    if channel:
                        await self.setup_scrim_panel(channel)

    async def setup_scrim_panel(self, channel: discord.TextChannel):
        """Setup scrim creation panel in a specific channel"""
        try:
            # Look for existing panel message
            async for message in channel.history(limit=50):
                if (message.author == self.bot.user and
                        message.embeds and
                        "Scrim Creation Panel" in message.embeds[0].title):
                    # Update existing message with new view
                    await message.edit(embed=self.create_scrim_panel_embed(), view=ScrimCreateView(self.bot))
                    self.logger.info(f"Updated existing scrim panel in channel {channel.id}",
                                     extra={'guild_id': channel.guild.id})
                    return

            # Create new panel
            embed = self.create_scrim_panel_embed()
            message = await channel.send(embed=embed, view=ScrimCreateView(self.bot))
            self.logger.info(f"Created new scrim panel in channel {channel.id}",
                             extra={'guild_id': channel.guild.id})

        except Exception as e:
            self.logger.error(f"Error setting up scrim panel in channel {channel.id}: {e}",
                              extra={'guild_id': channel.guild.id})

    def create_scrim_panel_embed(self) -> discord.Embed:
        """Create an improved scrim creation panel embed"""
        embed = discord.Embed(
            title="🎮 Scrim Creation Panel",
            description=(
                "Welcome to the **improved scrim system**! Click the button below to create a new scrim.\n\n"
                "**✨ New Features:**\n"
                "• Easy game selection with role tagging\n"
                "• Quick time selection options\n"
                "• Smart tier range selection\n"
                "• Streamlined player count setup\n"
                "• Improved visual design\n\n"
                "**🎯 Supported Games:**\n"
                "• Valorant • League of Legends • Teamfight Tactics\n"
                "• PUBG • Other Games\n\n"
                "Ready to create your scrim?"
            ),
            color=discord.Color.blue()
        )

        embed.set_footer(text="Improved Scrim System v2.0 • Click the button to get started!")
        return embed

    async def create_scrim(self, guild_id: int, organizer_id: int, game: str, gamemode: str,
                           tier_range: str, start_time: datetime, max_players: int, channel_id: int) -> Optional[str]:
        """Create a new scrim"""
        try:
            eastern = pytz.timezone('America/New_York')
            scrim_id = f"{guild_id}_{int(datetime.now(eastern).timestamp())}"

            scrim_data = {
                'id': scrim_id,
                'guild_id': guild_id,
                'organizer_id': organizer_id,
                'game': game,
                'gamemode': gamemode,
                'tier_range': tier_range,
                'start_time': start_time,
                'max_players': max_players,
                'channel_id': channel_id,
                'participants': [],
                'queue': [],
                'status': 'active',  # active, cancelled, completed
                'created_at': datetime.now(eastern),
                'notifications_sent': {
                    '10min': False,
                    '2min': False
                }
            }

            self.scrims_data[scrim_id] = scrim_data
            await self.save_scrims_data()

            self.logger.info(f"Created new scrim {scrim_id} for game {game} in guild {guild_id}",
                             extra={'guild_id': guild_id})
            return scrim_id

        except Exception as e:
            self.logger.error(f"Error creating scrim in guild {guild_id}: {e}", extra={'guild_id': guild_id})
            return None

    async def post_scrim_message(self, channel: discord.TextChannel, scrim_id: str):
        """Post the scrim message with interactive buttons"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return

            embed = self.create_scrim_embed(scrim_data)
            view = ScrimView(self.bot, scrim_data)

            message = await channel.send(embed=embed, view=view)

            # Store message ID for later updates
            scrim_data['message_id'] = message.id
            await self.save_scrims_data()

            self.logger.info(f"Posted scrim message for {scrim_id} in channel {channel.id}",
                             extra={'guild_id': channel.guild.id})

        except Exception as e:
            self.logger.error(f"Error posting scrim message for {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})

    def create_scrim_embed(self, scrim_data: Dict) -> discord.Embed:
        """Create an improved, more visually appealing scrim embed"""
        eastern = pytz.timezone('America/New_York')

        # Convert start_time to timezone-aware if needed
        start_time = scrim_data['start_time']
        if start_time.tzinfo is None:
            start_time = eastern.localize(start_time)

        now = datetime.now(eastern)
        time_until_start = start_time - now

        # Status color and emoji
        status_colors = {
            'active': discord.Color.green(),
            'cancelled': discord.Color.red(),
            'completed': discord.Color.blue()
        }

        status_emojis = {
            'active': '🟢',
            'cancelled': '🔴',
            'completed': '🔵'
        }

        color = status_colors.get(scrim_data['status'], discord.Color.green())
        status_emoji = status_emojis.get(scrim_data['status'], '🟢')

        # Game emoji mapping
        game_emojis = {
            'Valorant': '🎯',
            'League of Legends': '⚔️',
            'Teamfight Tactics': '♟️',
            'PUBG': '🔫',
            'Other Games': '🎮'
        }

        game_emoji = game_emojis.get(scrim_data['game'], '🎮')

        # Create embed with improved styling
        embed = discord.Embed(
            title=f"{game_emoji} {scrim_data['game']} Scrim",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )

        # Main info in description for better visibility
        participants_count = len(scrim_data['participants'])
        max_players = scrim_data['max_players']
        queue_count = len(scrim_data['queue'])

        # Time until start
        if scrim_data['status'] == 'active' and time_until_start.total_seconds() > 0:
            hours, remainder = divmod(int(time_until_start.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            time_text = f" • Starts in {hours}h {minutes}m" if hours > 0 else f" • Starts in {minutes}m"
        else:
            time_text = ""

        # Status text
        status_texts = {
            'active': f'{status_emoji} Active • Recruiting',
            'cancelled': f'{status_emoji} Cancelled',
            'completed': f'{status_emoji} Completed'
        }

        status_text = status_texts.get(scrim_data['status'], f'{status_emoji} Unknown')

        embed.description = (
            f"**Mode:** {scrim_data['gamemode']}\n"
            f"**Tier Range:** {scrim_data['tier_range']}\n"
            f"**Start Time:** {start_time.strftime('%Y-%m-%d %H:%M EST')}{time_text}\n"
            f"**Status:** {status_text}\n"
            f"**Players:** {participants_count}/{max_players}"
            f"{' ✅' if participants_count >= max_players else ''}"
            f" • **Queue:** {queue_count}"
        )

        # Organizer info
        guild = self.bot.get_guild(scrim_data['guild_id'])
        organizer = guild.get_member(scrim_data['organizer_id']) if guild else None
        organizer_name = organizer.display_name if organizer else f"Unknown ({scrim_data['organizer_id']})"

        embed.add_field(
            name="👑 Organizer",
            value=organizer_name,
            inline=True
        )

        # Participants list with better formatting
        if scrim_data['participants']:
            participant_names = []
            for i, user_id in enumerate(scrim_data['participants']):
                member = guild.get_member(user_id) if guild else None
                name = member.display_name if member else f"Unknown ({user_id})"
                participant_names.append(f"`{i + 1}.` {name}")

            # Split into chunks to avoid field length limits
            participant_text = "\n".join(participant_names)
            if len(participant_text) > 1000:
                participant_text = participant_text[:997] + "..."

            embed.add_field(
                name="📋 Participants",
                value=participant_text or "None",
                inline=False
            )

        # Queue list with better formatting
        if scrim_data['queue']:
            queue_names = []
            for i, user_id in enumerate(scrim_data['queue']):
                member = guild.get_member(user_id) if guild else None
                name = member.display_name if member else f"Unknown ({user_id})"
                queue_names.append(f"`{i + 1}.` {name}")

            queue_text = "\n".join(queue_names)
            if len(queue_text) > 1000:
                queue_text = queue_text[:997] + "..."

            embed.add_field(
                name="⏳ Queue",
                value=queue_text,
                inline=False
            )

        # Special styling for cancelled scrims
        if scrim_data['status'] == 'cancelled':
            embed.add_field(
                name="⚠️ Notice",
                value="This scrim has been cancelled.",
                inline=False
            )

        # Footer with scrim ID
        embed.set_footer(
            text=f"Scrim ID: {scrim_data['id']} • Improved Scrim System v2.0"
        )

        return embed

    async def join_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Add user to scrim participants"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ Scrim not found."

            if scrim_data['status'] != 'active':
                return False, "❌ This scrim is no longer active."

            # Check if already participating
            if user_id in scrim_data['participants']:
                return False, "❌ You are already participating."

            # Remove from queue if in queue
            if user_id in scrim_data['queue']:
                scrim_data['queue'].remove(user_id)

            # Check if scrim is full
            if len(scrim_data['participants']) >= scrim_data['max_players']:
                return False, "❌ Scrim is full. Please join the queue."

            # Add to participants
            scrim_data['participants'].append(user_id)
            await self.save_scrims_data()

            self.logger.info(f"User {user_id} joined scrim {scrim_id}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ Successfully joined the scrim!"

        except Exception as e:
            self.logger.error(f"Error joining scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ Error joining scrim."

    async def leave_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Remove user from scrim participants"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ Scrim not found."

            if user_id not in scrim_data['participants']:
                return False, "❌ You are not participating."

            # Remove from participants
            scrim_data['participants'].remove(user_id)

            # Move first person from queue to participants if there's space
            if scrim_data['queue'] and len(scrim_data['participants']) < scrim_data['max_players']:
                next_user = scrim_data['queue'].pop(0)
                scrim_data['participants'].append(next_user)

                # Try to notify the user who was moved from queue
                guild = self.bot.get_guild(scrim_data['guild_id'])
                if guild:
                    member = guild.get_member(next_user)
                    if member:
                        try:
                            embed = discord.Embed(
                                title="🎮 Scrim Participation Confirmed",
                                description=f"A spot opened in the **{scrim_data['game']}** scrim and you've been automatically moved from the queue!",
                                color=discord.Color.green()
                            )
                            await member.send(embed=embed)
                        except:
                            pass  # Can't send DM, that's okay

            await self.save_scrims_data()

            self.logger.info(f"User {user_id} left scrim {scrim_id}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ Successfully left the scrim."

        except Exception as e:
            self.logger.error(f"Error leaving scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ Error leaving scrim."

    async def join_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Add user to scrim queue"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ Scrim not found."

            if scrim_data['status'] != 'active':
                return False, "❌ This scrim is no longer active."

            # Check if already in queue
            if user_id in scrim_data['queue']:
                return False, "❌ You are already in the queue."

            # Check if already participating
            if user_id in scrim_data['participants']:
                return False, "❌ You are already participating."

            # Check if there's space in main participants
            if len(scrim_data['participants']) < scrim_data['max_players']:
                return False, "❌ There are still spots available. Please join directly."

            # Add to queue
            scrim_data['queue'].append(user_id)
            await self.save_scrims_data()

            queue_position = len(scrim_data['queue'])
            self.logger.info(f"User {user_id} joined queue for scrim {scrim_id} at position {queue_position}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, f"✅ Successfully joined the queue! (Position: {queue_position})"

        except Exception as e:
            self.logger.error(f"Error joining queue for scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ Error joining queue."

    async def leave_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Remove user from scrim queue"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ Scrim not found."

            if user_id not in scrim_data['queue']:
                return False, "❌ You are not in the queue."

            # Remove from queue
            scrim_data['queue'].remove(user_id)
            await self.save_scrims_data()

            self.logger.info(f"User {user_id} left queue for scrim {scrim_id}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ Successfully left the queue."

        except Exception as e:
            self.logger.error(f"Error leaving queue for scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ Error leaving queue."

    async def cancel_scrim(self, scrim_id: str, canceller_id: int) -> bool:
        """Cancel a scrim"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False

            scrim_data['status'] = 'cancelled'
            await self.save_scrims_data()

            # Notify all participants and queue members
            guild = self.bot.get_guild(scrim_data['guild_id'])
            if guild:
                all_users = set(scrim_data['participants'] + scrim_data['queue'])
                canceller = guild.get_member(canceller_id)
                canceller_name = canceller.display_name if canceller else "Administrator"

                for user_id in all_users:
                    member = guild.get_member(user_id)
                    if member:
                        try:
                            embed = discord.Embed(
                                title="❌ Scrim Cancellation Notice",
                                description=f"The **{scrim_data['game']}** scrim has been cancelled.",
                                color=discord.Color.red()
                            )
                            embed.add_field(name="Cancelled by", value=canceller_name, inline=True)
                            embed.add_field(name="Original start time",
                                            value=scrim_data['start_time'].strftime("%Y-%m-%d %H:%M EST"),
                                            inline=True)
                            await member.send(embed=embed)
                        except:
                            pass  # Can't send DM, that's okay

            self.logger.info(f"Scrim {scrim_id} cancelled by user {canceller_id}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True

        except Exception as e:
            self.logger.error(f"Error cancelling scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False

    async def update_scrim_message(self, message: discord.Message, scrim_id: str):
        """Update the scrim message with current data"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return

            embed = self.create_scrim_embed(scrim_data)
            view = ScrimView(self.bot, scrim_data)

            await message.edit(embed=embed, view=view)

        except Exception as e:
            self.logger.error(f"Error updating scrim message for {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})

    @tasks.loop(minutes=1)
    async def scrim_notifications(self):
        """Send notifications before scrim start times"""
        try:
            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)

            for scrim_id, scrim_data in self.scrims_data.items():
                if scrim_data['status'] != 'active':
                    continue

                start_time = scrim_data['start_time']
                if start_time.tzinfo is None:
                    start_time = eastern.localize(start_time)

                time_until_start = start_time - now

                # Check if scrim is full for notifications
                is_full = len(scrim_data['participants']) >= scrim_data['max_players']

                # 10 minute notification
                if (5 <= time_until_start.total_seconds() / 60 <= 15 and
                        not scrim_data['notifications_sent']['10min'] and is_full):
                    await self.send_scrim_notification(scrim_data, "10min")
                    scrim_data['notifications_sent']['10min'] = True
                    await self.save_scrims_data()

                # 2 minute notification
                elif (0 <= time_until_start.total_seconds() / 60 <= 5 and
                      not scrim_data['notifications_sent']['2min'] and is_full):
                    await self.send_scrim_notification(scrim_data, "2min")
                    scrim_data['notifications_sent']['2min'] = True
                    await self.save_scrims_data()

                # Mark as completed if start time has passed
                elif time_until_start.total_seconds() <= 0 and scrim_data['status'] == 'active':
                    scrim_data['status'] = 'completed'
                    await self.save_scrims_data()

                    # Update the scrim message if it exists
                    if 'message_id' in scrim_data:
                        guild = self.bot.get_guild(scrim_data['guild_id'])
                        if guild:
                            channel = guild.get_channel(scrim_data['channel_id'])
                            if channel:
                                try:
                                    message = await channel.fetch_message(scrim_data['message_id'])
                                    await self.update_scrim_message(message, scrim_id)
                                except:
                                    pass

        except Exception as e:
            self.logger.error(f"Error in scrim notifications task: {e}", extra={'guild_id': None})

    async def send_scrim_notification(self, scrim_data: Dict, notification_type: str):
        """Send notification to scrim participants"""
        try:
            guild = self.bot.get_guild(scrim_data['guild_id'])
            if not guild:
                return

            # Time text
            time_text = "10 minutes" if notification_type == "10min" else "2 minutes"

            # Create mention list
            mentions = []
            for user_id in scrim_data['participants']:
                mentions.append(f"<@{user_id}>")

            if not mentions:
                return

            # Create notification embed
            embed = discord.Embed(
                title=f"⏰ Scrim Starting in {time_text}",
                description=f"**{scrim_data['game']}** scrim is about to begin!",
                color=discord.Color.orange()
            )
            embed.add_field(name="Game Mode", value=scrim_data['gamemode'], inline=True)
            embed.add_field(name="Start Time", value=scrim_data['start_time'].strftime("%H:%M EST"), inline=True)
            embed.add_field(name="Participants", value=f"{len(scrim_data['participants'])}/{scrim_data['max_players']}",
                            inline=True)

            # Send to channel
            channel = guild.get_channel(scrim_data['channel_id'])
            if channel:
                mention_text = " ".join(mentions)
                await channel.send(content=mention_text, embed=embed)

            self.logger.info(f"Sent {notification_type} notification for scrim {scrim_data['id']}",
                             extra={'guild_id': scrim_data['guild_id']})

        except Exception as e:
            self.logger.error(f"Error sending scrim notification: {e}",
                              extra={'guild_id': scrim_data.get('guild_id')})

    @tasks.loop(hours=6)
    async def cleanup_old_scrims(self):
        """Clean up old completed/cancelled scrims"""
        try:
            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)
            cutoff_time = now - timedelta(days=7)  # Keep scrims for 7 days

            scrims_to_remove = []
            for scrim_id, scrim_data in self.scrims_data.items():
                start_time = scrim_data['start_time']
                if start_time.tzinfo is None:
                    start_time = eastern.localize(start_time)

                # Remove old completed/cancelled scrims
                if (scrim_data['status'] in ['completed', 'cancelled'] and
                        start_time < cutoff_time):
                    scrims_to_remove.append(scrim_id)

            for scrim_id in scrims_to_remove:
                del self.scrims_data[scrim_id]
                self.logger.info(f"Cleaned up old scrim {scrim_id}", extra={'guild_id': None})

            if scrims_to_remove:
                await self.save_scrims_data()
                self.logger.info(f"Cleaned up {len(scrims_to_remove)} old scrims", extra={'guild_id': None})

        except Exception as e:
            self.logger.error(f"Error in cleanup task: {e}", extra={'guild_id': None})

    # Slash Commands
    @app_commands.command(name="random_map", description="Select random maps from the active map pool.")
    @app_commands.describe(count="Number of maps to select (default: 1)")
    async def random_map(self, interaction: discord.Interaction, count: Optional[int] = 1):
        # Check if feature is enabled
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message(
                "❌ Scrim system is disabled on this server.",
                ephemeral=True
            )
            return

        # Validate count
        if count < 1 or count > 10:
            await interaction.response.send_message("❌ Map count must be between 1-10.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        map_pool = self.get_map_pool(guild_id)

        if not map_pool:
            await interaction.response.send_message("❌ No map pool configured for this server.", ephemeral=True)
            return

        # Don't select more maps than available
        if count > len(map_pool):
            count = len(map_pool)

        # Select random maps
        selected_maps = random.sample(map_pool, count)

        embed = discord.Embed(
            title="🎯 Random Map Selection",
            color=discord.Color.green()
        )

        if count == 1:
            embed.description = f"**Selected Map:** {selected_maps[0]}"
        else:
            map_list = "\n".join([f"{i + 1}. **{map_name}**" for i, map_name in enumerate(selected_maps)])
            embed.description = f"**Selected Maps:**\n{map_list}"

        embed.add_field(name="Total Map Pool", value=f"{len(map_pool)} maps", inline=True)
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

        self.logger.info(f"Random map selection: {selected_maps} for guild {guild_id}",
                         extra={'guild_id': guild_id})

    @app_commands.command(name="set_map_pool", description="Set the server's map pool. (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def set_map_pool(self, interaction: discord.Interaction):
        try:
            guild_id = interaction.guild.id
            current_maps = self.get_map_pool(guild_id)

            # Show modal for map pool configuration
            modal = MapPoolModal(self.bot, guild_id, current_maps)
            await interaction.response.send_modal(modal)

        except Exception as e:
            self.logger.error(f"Error in set_map_pool command: {e}", extra={'guild_id': interaction.guild.id})
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Error occurred while setting up map pool.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Error occurred while setting up map pool.", ephemeral=True)

    @app_commands.command(name="show_map_pool", description="Show the current server's map pool.")
    async def show_map_pool(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        map_pool = self.get_map_pool(guild_id)

        embed = discord.Embed(
            title="🗺️ Current Map Pool",
            color=discord.Color.blue()
        )

        if map_pool:
            map_list = "\n".join([f"{i + 1}. **{map_name}**" for i, map_name in enumerate(map_pool)])
            embed.description = f"**Total {len(map_pool)} maps:**\n{map_list}"

            if map_pool == self.default_valorant_maps:
                embed.set_footer(text="Using default Valorant map pool")
            else:
                embed.set_footer(text="Using custom map pool")
        else:
            embed.description = "No maps configured."
            embed.color = discord.Color.red()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="list_scrims", description="View active scrims.")
    async def list_scrims(self, interaction: discord.Interaction):
        # Check if feature is enabled
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message(
                "❌ Scrim system is disabled on this server.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        active_scrims = [
            scrim_data for scrim_data in self.scrims_data.values()
            if scrim_data['guild_id'] == guild_id and scrim_data['status'] == 'active'
        ]

        if not active_scrims:
            await interaction.followup.send("No active scrims currently.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎮 Active Scrims",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)

        for scrim_data in sorted(active_scrims, key=lambda x: x['start_time']):
            start_time = scrim_data['start_time']
            if start_time.tzinfo is None:
                start_time = eastern.localize(start_time)

            time_until = start_time - now
            if time_until.total_seconds() > 0:
                hours, remainder = divmod(int(time_until.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                time_text = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            else:
                time_text = "In progress"

            participants_count = len(scrim_data['participants'])
            max_players = scrim_data['max_players']
            queue_count = len(scrim_data['queue'])

            embed.add_field(
                name=f"{scrim_data['game']} ({scrim_data['gamemode']})",
                value=f"Start: {start_time.strftime('%H:%M')} ({time_text})\n"
                      f"Players: {participants_count}/{max_players}\n"
                      f"Queue: {queue_count}",
                inline=True
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="configure_scrim", description="Configure scrim system settings. (Admin only)")
    @app_commands.describe(
        feature_enabled="Enable/disable scrim system",
        scrim_channel="Channel where scrim creation panel will be displayed"
    )
    @app_commands.default_permissions(administrator=True)
    async def configure_scrim(self, interaction: discord.Interaction,
                              feature_enabled: Optional[bool] = None,
                              scrim_channel: Optional[discord.TextChannel] = None):

        guild_id = interaction.guild.id
        await interaction.response.defer(ephemeral=True)

        # Get current settings
        current_config = config.load_server_config(guild_id)
        features = current_config.get('features', {})
        channels = current_config.get('channels', {})

        updated = False

        # Update feature setting
        if feature_enabled is not None:
            features['scrim_system'] = feature_enabled
            updated = True
            self.logger.info(f"Scrim system {'enabled' if feature_enabled else 'disabled'} for guild {guild_id}",
                             extra={'guild_id': guild_id})

        # Update scrim channel
        if scrim_channel is not None:
            channels['scrim_channel'] = {'id': scrim_channel.id, 'name': scrim_channel.name}
            updated = True
            self.logger.info(f"Scrim channel set to #{scrim_channel.name} ({scrim_channel.id}) for guild {guild_id}",
                             extra={'guild_id': guild_id})

        if updated:
            current_config['features'] = features
            current_config['channels'] = channels
            config.save_server_config(guild_id, current_config)
            await interaction.followup.send("✅ Scrim system configuration updated successfully.")

            # Setup scrim panel if channel was set and feature is enabled
            if scrim_channel is not None and features.get('scrim_system'):
                await self.setup_scrim_panel(scrim_channel)
        else:
            await interaction.followup.send("ℹ️ No changes made to configuration.")

    @app_commands.command(name="force_cancel_scrim", description="Force cancel a scrim. (Staff only)")
    @app_commands.describe(scrim_id="ID of the scrim to cancel")
    async def force_cancel_scrim(self, interaction: discord.Interaction, scrim_id: str):
        # Check permissions
        if not self.has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data:
            await interaction.followup.send("❌ Scrim not found.", ephemeral=True)
            return

        if scrim_data['guild_id'] != interaction.guild.id:
            await interaction.followup.send("❌ This scrim doesn't belong to this server.", ephemeral=True)
            return

        success = await self.cancel_scrim(scrim_id, interaction.user.id)
        if success:
            await interaction.followup.send(f"✅ Scrim `{scrim_id}` has been cancelled.", ephemeral=True)

            # Try to update the message if it exists
            if 'message_id' in scrim_data:
                try:
                    channel = interaction.guild.get_channel(scrim_data['channel_id'])
                    if channel:
                        message = await channel.fetch_message(scrim_data['message_id'])
                        await self.update_scrim_message(message, scrim_id)
                except:
                    pass
        else:
            await interaction.followup.send("❌ Error occurred while cancelling scrim.", ephemeral=True)

    @app_commands.command(name="refresh_scrim_panel",
                          description="Refresh the scrim panel message and repost it at the bottom. (Staff only)")
    @app_commands.default_permissions(administrator=True)
    async def refresh_scrim_panel(self, interaction: discord.Interaction):
        # Defer the interaction response
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        scrim_channel_id = config.get_channel_id(guild_id, 'scrim_channel')

        if not scrim_channel_id:
            await interaction.followup.send("❌ Scrim channel not configured.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(scrim_channel_id)
        if not channel:
            await interaction.followup.send("❌ Scrim channel not found.", ephemeral=True)
            return

        # Delete previous scrim panel messages
        deleted_count = 0
        async for message in channel.history(limit=50):
            if message.author == self.bot.user and message.embeds and "Scrim Creation Panel" in message.embeds[0].title:
                try:
                    await message.delete()
                    deleted_count += 1
                except discord.errors.NotFound:
                    continue  # Message was already deleted, continue
                except Exception as e:
                    self.logger.error(f"Error deleting old scrim panel message: {e}",
                                      extra={'guild_id': guild_id})
                    await interaction.followup.send("❌ Error occurred while deleting old messages.", ephemeral=True)
                    return

        # Post the new scrim panel
        await self.setup_scrim_panel(channel)

        # Acknowledge the user
        await interaction.followup.send("✅ Scrim panel refreshed successfully.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ScrimCog(bot))