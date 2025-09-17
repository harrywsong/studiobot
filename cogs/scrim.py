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

from utils.logger import get_logger
from utils import config


class ScrimSetupModal(discord.ui.Modal):
    """Modal for setting up a new scrim/internal match"""

    def __init__(self, bot, guild_id: int):
        super().__init__(title="내전 설정", timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.logger = get_logger("내전 시스템")

        # Game input
        self.game = discord.ui.TextInput(
            label="게임",
            placeholder="예: Valorant, League of Legends, TFT...",
            required=True,
            max_length=50
        )

        # Game mode input
        self.gamemode = discord.ui.TextInput(
            label="게임 모드",
            placeholder="예: 5v5, 6v6, 3v3...",
            required=True,
            max_length=20
        )

        # Tier range input
        self.tier_range = discord.ui.TextInput(
            label="티어 범위",
            placeholder="예: Gold~Diamond, Plat+, All tiers...",
            required=False,
            max_length=100
        )

        # Time input
        self.start_time = discord.ui.TextInput(
            label="시작 시간 (EST)",
            placeholder="예: 2024-01-15 19:30, 오늘 20:00, 1시간 후...",
            required=True,
            max_length=50
        )

        # Max players input
        self.max_players = discord.ui.TextInput(
            label="최대 인원",
            placeholder="예: 10 (5v5의 경우), 12 (6v6의 경우)...",
            required=True,
            max_length=3
        )

        self.add_item(self.game)
        self.add_item(self.gamemode)
        self.add_item(self.tier_range)
        self.add_item(self.start_time)
        self.add_item(self.max_players)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse max players
            max_players = int(self.max_players.value)
            if max_players < 2 or max_players > 50:
                await interaction.response.send_message("❌ 최대 인원은 2~50명 사이여야 합니다.", ephemeral=True)
                return

            # Parse start time
            eastern = pytz.timezone('America/New_York')
            parsed_time = await self.parse_time_input(self.start_time.value, eastern)
            if not parsed_time:
                await interaction.response.send_message("❌ 시간 형식이 올바르지 않습니다. 다시 시도해 주세요.", ephemeral=True)
                return

            # Check if time is in the future
            if parsed_time <= datetime.now(eastern):
                await interaction.response.send_message("❌ 시작 시간은 현재 시간 이후여야 합니다.", ephemeral=True)
                return

            # Get the scrim cog and create scrim
            scrim_cog = self.bot.get_cog('ScrimCog')
            if scrim_cog:
                scrim_id = await scrim_cog.create_scrim(
                    guild_id=self.guild_id,
                    organizer_id=interaction.user.id,
                    game=self.game.value,
                    gamemode=self.gamemode.value,
                    tier_range=self.tier_range.value or "All tiers",
                    start_time=parsed_time,
                    max_players=max_players,
                    channel_id=interaction.channel_id
                )

                if scrim_id:
                    await interaction.response.send_message("✅ 내전이 성공적으로 생성되었습니다!", ephemeral=True)
                    await scrim_cog.post_scrim_message(interaction.channel, scrim_id)
                else:
                    await interaction.response.send_message("❌ 내전 생성 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("❌ 최대 인원에는 숫자만 입력해 주세요.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error in scrim setup modal for guild {self.guild_id}: {e}",
                              extra={'guild_id': self.guild_id})
            await interaction.response.send_message("❌ 오류가 발생했습니다. 다시 시도해 주세요.", ephemeral=True)

    async def parse_time_input(self, time_input: str, timezone) -> Optional[datetime]:
        """Parse various time input formats"""
        time_input = time_input.strip().lower()
        now = datetime.now(timezone)

        try:
            # Format: "YYYY-MM-DD HH:MM"
            if len(time_input.split()) == 2 and '-' in time_input:
                return datetime.strptime(time_input, "%Y-%m-%d %H:%M").replace(tzinfo=timezone)

            # Format: "오늘 HH:MM"
            if time_input.startswith("오늘"):
                time_part = time_input.replace("오늘", "").strip()
                time_obj = datetime.strptime(time_part, "%H:%M").time()
                return datetime.combine(now.date(), time_obj).replace(tzinfo=timezone)

            # Format: "내일 HH:MM"
            if time_input.startswith("내일"):
                time_part = time_input.replace("내일", "").strip()
                time_obj = datetime.strptime(time_part, "%H:%M").time()
                tomorrow = now.date() + timedelta(days=1)
                return datetime.combine(tomorrow, time_obj).replace(tzinfo=timezone)

            # Format: "X시간 후"
            if "시간 후" in time_input:
                hours = int(time_input.replace("시간 후", "").strip())
                return now + timedelta(hours=hours)

            # Format: "X분 후"
            if "분 후" in time_input:
                minutes = int(time_input.replace("분 후", "").strip())
                return now + timedelta(minutes=minutes)

            # Format: "HH:MM" (today)
            if ':' in time_input and len(time_input.split(':')) == 2:
                time_obj = datetime.strptime(time_input, "%H:%M").time()
                result = datetime.combine(now.date(), time_obj).replace(tzinfo=timezone)
                # If time has passed today, assume tomorrow
                if result <= now:
                    result += timedelta(days=1)
                return result

        except (ValueError, TypeError):
            pass

        return None


class ScrimView(discord.ui.View):
    """Persistent view for scrim management"""

    def __init__(self, bot, scrim_data: Dict):
        super().__init__(timeout=None)
        self.bot = bot
        self.scrim_data = scrim_data
        self.scrim_id = scrim_data['id']
        self.guild_id = scrim_data['guild_id']
        self.logger = get_logger("내전 시스템")

        # Update button states based on scrim status
        self.update_button_states()

    def update_button_states(self):
        """Update button states based on current scrim status"""
        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)
        start_time = self.scrim_data['start_time']

        # Convert start_time to timezone-aware if needed
        if start_time.tzinfo is None:
            start_time = eastern.localize(start_time)

        time_until_start = start_time - now

        # Lock buttons 30 minutes before start
        buttons_locked = time_until_start <= timedelta(minutes=30)

        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id in ['join_scrim', 'leave_scrim', 'join_queue',
                                                                          'leave_queue']:
                item.disabled = buttons_locked

    @discord.ui.button(label="참가", style=discord.ButtonStyle.green, custom_id="join_scrim", emoji="✅")
    async def join_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.join_scrim(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                # Update the scrim message
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.red, custom_id="leave_scrim", emoji="❌")
    async def leave_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.leave_scrim(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                # Update the scrim message
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(label="대기열 참가", style=discord.ButtonStyle.secondary, custom_id="join_queue", emoji="⏳")
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.join_queue(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                # Update the scrim message
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(label="대기열 나가기", style=discord.ButtonStyle.secondary, custom_id="leave_queue", emoji="🚪")
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        scrim_cog = self.bot.get_cog('ScrimCog')
        if scrim_cog:
            success, message = await scrim_cog.leave_queue(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                # Update the scrim message
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger, custom_id="cancel_scrim", emoji="🗑️")
    async def cancel_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only organizer or staff can cancel
        scrim_cog = self.bot.get_cog('ScrimCog')
        if not scrim_cog:
            await interaction.response.send_message("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
            return

        # Check permissions
        is_organizer = interaction.user.id == self.scrim_data['organizer_id']
        is_staff = scrim_cog.has_staff_permissions(interaction.user)

        if not (is_organizer or is_staff):
            await interaction.response.send_message("❌ 내전을 취소할 권한이 없습니다.", ephemeral=True)
            return

        # Confirm cancellation
        embed = discord.Embed(
            title="⚠️ 내전 취소 확인",
            description="정말로 이 내전을 취소하시겠습니까?\n참가자들에게 취소 알림이 전송됩니다.",
            color=discord.Color.red()
        )

        view = discord.ui.View()
        confirm_button = discord.ui.Button(label="확인", style=discord.ButtonStyle.danger)
        cancel_button = discord.ui.Button(label="취소", style=discord.ButtonStyle.secondary)

        async def confirm_callback(confirm_interaction):
            await confirm_interaction.response.defer()
            success = await scrim_cog.cancel_scrim(self.scrim_id, interaction.user.id)
            if success:
                await confirm_interaction.followup.send("✅ 내전이 취소되었습니다.", ephemeral=True)
                # Update original message to show cancellation
                await scrim_cog.update_scrim_message(interaction.message, self.scrim_id)
            else:
                await confirm_interaction.followup.send("❌ 내전 취소 중 오류가 발생했습니다.", ephemeral=True)

        async def cancel_callback(cancel_interaction):
            await cancel_interaction.response.send_message("취소되었습니다.", ephemeral=True)

        confirm_button.callback = confirm_callback
        cancel_button.callback = cancel_callback
        view.add_item(confirm_button)
        view.add_item(cancel_button)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ScrimCreateView(discord.ui.View):
    """Persistent view with button to create new scrims"""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = get_logger("내전 시스템")

    @discord.ui.button(label="내전 생성", style=discord.ButtonStyle.primary, custom_id="create_scrim", emoji="🎮")
    async def create_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if feature is enabled
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 내전 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        # Show modal for scrim setup
        modal = ScrimSetupModal(self.bot, interaction.guild.id)
        await interaction.response.send_modal(modal)


class ScrimCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("내전 시스템")
        self.scrims_data = {}  # In-memory storage for active scrims
        self.scrims_file = "data/scrims.json"

        # Start tasks after bot is ready
        self.bot.loop.create_task(self.wait_and_start_tasks())

    async def wait_and_start_tasks(self):
        """Wait for bot to be ready then start tasks"""
        await self.bot.wait_until_ready()
        await self.load_scrims_data()
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
                        "내전 생성" in message.embeds[0].title):
                    # Update existing message with new view
                    await message.edit(view=ScrimCreateView(self.bot))
                    self.logger.info(f"Updated existing scrim panel in channel {channel.id}",
                                     extra={'guild_id': channel.guild.id})
                    return

            # Create new panel
            embed = discord.Embed(
                title="🎮 내전 생성 패널",
                description="아래 버튼을 클릭하여 새로운 내전을 생성하세요!\n\n"
                            "**지원 기능:**\n"
                            "• 다양한 게임 지원\n"
                            "• 자동 대기열 관리\n"
                            "• 시간 알림 시스템\n"
                            "• 참가자 관리",
                color=discord.Color.blue()
            )
            embed.set_footer(text="내전 시스템 v1.0")

            message = await channel.send(embed=embed, view=ScrimCreateView(self.bot))
            self.logger.info(f"Created new scrim panel in channel {channel.id}",
                             extra={'guild_id': channel.guild.id})

        except Exception as e:
            self.logger.error(f"Error setting up scrim panel in channel {channel.id}: {e}",
                              extra={'guild_id': channel.guild.id})

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
        """Create embed for scrim display"""
        eastern = pytz.timezone('America/New_York')

        # Convert start_time to timezone-aware if needed
        start_time = scrim_data['start_time']
        if start_time.tzinfo is None:
            start_time = eastern.localize(start_time)

        # Status color
        color = discord.Color.green()
        if scrim_data['status'] == 'cancelled':
            color = discord.Color.red()
        elif scrim_data['status'] == 'completed':
            color = discord.Color.blue()

        embed = discord.Embed(
            title=f"🎮 {scrim_data['game']} 내전",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )

        # Basic info
        embed.add_field(name="게임 모드", value=scrim_data['gamemode'], inline=True)
        embed.add_field(name="티어 범위", value=scrim_data['tier_range'], inline=True)
        embed.add_field(name="시작 시간", value=start_time.strftime("%Y-%m-%d %H:%M EST"), inline=True)

        # Participants info
        participants_count = len(scrim_data['participants'])
        max_players = scrim_data['max_players']
        queue_count = len(scrim_data['queue'])

        participants_text = f"{participants_count}/{max_players}"
        if participants_count >= max_players:
            participants_text += " ✅"

        embed.add_field(name="참가자", value=participants_text, inline=True)
        embed.add_field(name="대기열", value=str(queue_count), inline=True)

        # Status
        status_text = {
            'active': '🟢 모집 중',
            'cancelled': '🔴 취소됨',
            'completed': '🔵 완료됨'
        }
        embed.add_field(name="상태", value=status_text.get(scrim_data['status'], '❓ 알 수 없음'), inline=True)

        # Participants list
        if scrim_data['participants']:
            guild = self.bot.get_guild(scrim_data['guild_id'])
            participant_names = []
            for user_id in scrim_data['participants']:
                member = guild.get_member(user_id) if guild else None
                name = member.display_name if member else f"Unknown ({user_id})"
                participant_names.append(name)

            embed.add_field(
                name="📋 참가자 목록",
                value="\n".join([f"{i + 1}. {name}" for i, name in enumerate(participant_names)]) or "없음",
                inline=False
            )

        # Queue list
        if scrim_data['queue']:
            guild = self.bot.get_guild(scrim_data['guild_id'])
            queue_names = []
            for user_id in scrim_data['queue']:
                member = guild.get_member(user_id) if guild else None
                name = member.display_name if member else f"Unknown ({user_id})"
                queue_names.append(name)

            embed.add_field(
                name="⏳ 대기열",
                value="\n".join([f"{i + 1}. {name}" for i, name in enumerate(queue_names)]) or "없음",
                inline=False
            )

        # Time until start
        now = datetime.now(eastern)
        time_until_start = start_time - now
        if time_until_start.total_seconds() > 0:
            hours, remainder = divmod(int(time_until_start.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            if hours > 0:
                time_text = f"{hours}시간 {minutes}분 후 시작"
            else:
                time_text = f"{minutes}분 후 시작"
            embed.add_field(name="⏰ 시작까지", value=time_text, inline=True)

        # Organizer
        guild = self.bot.get_guild(scrim_data['guild_id'])
        organizer = guild.get_member(scrim_data['organizer_id']) if guild else None
        organizer_name = organizer.display_name if organizer else f"Unknown ({scrim_data['organizer_id']})"
        embed.add_field(name="주최자", value=organizer_name, inline=True)

        if scrim_data['status'] == 'cancelled':
            embed.add_field(name="⚠️", value="이 내전은 취소되었습니다.", inline=False)

        embed.set_footer(text=f"내전 ID: {scrim_data['id']}")

        return embed

    async def join_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Add user to scrim participants"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if scrim_data['status'] != 'active':
                return False, "❌ 이 내전은 더 이상 활성화되어 있지 않습니다."

            # Check if already participating
            if user_id in scrim_data['participants']:
                return False, "❌ 이미 참가하고 있습니다."

            # Remove from queue if in queue
            if user_id in scrim_data['queue']:
                scrim_data['queue'].remove(user_id)

            # Check if scrim is full
            if len(scrim_data['participants']) >= scrim_data['max_players']:
                return False, "❌ 내전이 가득 찼습니다. 대기열에 참가해 주세요."

            # Add to participants
            scrim_data['participants'].append(user_id)
            await self.save_scrims_data()

            self.logger.info(f"User {user_id} joined scrim {scrim_id}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ 내전에 참가했습니다!"

        except Exception as e:
            self.logger.error(f"Error joining scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 참가 중 오류가 발생했습니다."

    async def leave_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Remove user from scrim participants"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if user_id not in scrim_data['participants']:
                return False, "❌ 참가하고 있지 않습니다."

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
                                title="🎮 내전 참가 확정",
                                description=f"**{scrim_data['game']}** 내전에 자리가 생겨 자동으로 참가되었습니다!",
                                color=discord.Color.green()
                            )
                            await member.send(embed=embed)
                        except:
                            pass  # Can't send DM, that's okay

            await self.save_scrims_data()

            self.logger.info(f"User {user_id} left scrim {scrim_id}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ 내전에서 나갔습니다."

        except Exception as e:
            self.logger.error(f"Error leaving scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 나가기 중 오류가 발생했습니다."

    async def join_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Add user to scrim queue"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if scrim_data['status'] != 'active':
                return False, "❌ 이 내전은 더 이상 활성화되어 있지 않습니다."

            # Check if already in queue
            if user_id in scrim_data['queue']:
                return False, "❌ 이미 대기열에 있습니다."

            # Check if already participating
            if user_id in scrim_data['participants']:
                return False, "❌ 이미 참가하고 있습니다."

            # Check if there's space in main participants
            if len(scrim_data['participants']) < scrim_data['max_players']:
                return False, "❌ 아직 자리가 있습니다. 직접 참가해 주세요."

            # Add to queue
            scrim_data['queue'].append(user_id)
            await self.save_scrims_data()

            queue_position = len(scrim_data['queue'])
            self.logger.info(f"User {user_id} joined queue for scrim {scrim_id} at position {queue_position}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, f"✅ 대기열에 참가했습니다! (대기 순번: {queue_position})"

        except Exception as e:
            self.logger.error(f"Error joining queue for scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 대기열 참가 중 오류가 발생했습니다."

    async def leave_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """Remove user from scrim queue"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if user_id not in scrim_data['queue']:
                return False, "❌ 대기열에 있지 않습니다."

            # Remove from queue
            scrim_data['queue'].remove(user_id)
            await self.save_scrims_data()

            self.logger.info(f"User {user_id} left queue for scrim {scrim_id}",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ 대기열에서 나갔습니다."

        except Exception as e:
            self.logger.error(f"Error leaving queue for scrim {scrim_id}: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 대기열 나가기 중 오류가 발생했습니다."

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
                canceller_name = canceller.display_name if canceller else "관리자"

                for user_id in all_users:
                    member = guild.get_member(user_id)
                    if member:
                        try:
                            embed = discord.Embed(
                                title="❌ 내전 취소 알림",
                                description=f"**{scrim_data['game']}** 내전이 취소되었습니다.",
                                color=discord.Color.red()
                            )
                            embed.add_field(name="취소자", value=canceller_name, inline=True)
                            embed.add_field(name="원래 시작 시간",
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
            time_text = "10분" if notification_type == "10min" else "2분"

            # Create mention list
            mentions = []
            for user_id in scrim_data['participants']:
                mentions.append(f"<@{user_id}>")

            if not mentions:
                return

            # Create notification embed
            embed = discord.Embed(
                title=f"⏰ 내전 시작 {time_text} 전 알림",
                description=f"**{scrim_data['game']}** 내전이 곧 시작됩니다!",
                color=discord.Color.orange()
            )
            embed.add_field(name="게임 모드", value=scrim_data['gamemode'], inline=True)
            embed.add_field(name="시작 시간", value=scrim_data['start_time'].strftime("%H:%M EST"), inline=True)
            embed.add_field(name="참가자 수", value=f"{len(scrim_data['participants'])}/{scrim_data['max_players']}",
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

    @app_commands.command(name="내전목록", description="진행 중인 내전 목록을 확인합니다.")
    async def list_scrims(self, interaction: discord.Interaction):
        # Check if feature is enabled
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 내전 시스템이 비활성화되어 있습니다.",
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
            await interaction.followup.send("현재 진행 중인 내전이 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎮 진행 중인 내전 목록",
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
                time_text = "진행 중"

            participants_count = len(scrim_data['participants'])
            max_players = scrim_data['max_players']
            queue_count = len(scrim_data['queue'])

            embed.add_field(
                name=f"{scrim_data['game']} ({scrim_data['gamemode']})",
                value=f"시작: {start_time.strftime('%H:%M')} ({time_text})\n"
                      f"참가자: {participants_count}/{max_players}\n"
                      f"대기열: {queue_count}",
                inline=True
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="내전설정", description="내전 시스템 설정을 변경합니다. (관리자 전용)")
    @app_commands.describe(
        feature_enabled="내전 시스템 활성화/비활성화",
        scrim_channel="내전 생성 패널이 표시될 채널"
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
            await interaction.followup.send("✅ 내전 시스템 설정이 성공적으로 업데이트되었습니다.")

            # Setup scrim panel if channel was set and feature is enabled
            if scrim_channel is not None and features.get('scrim_system'):
                await self.setup_scrim_panel(scrim_channel)
        else:
            await interaction.followup.send("ℹ️ 변경 사항이 없어 설정을 업데이트하지 않았습니다.")

    @app_commands.command(name="내전강제취소", description="내전을 강제로 취소합니다. (스태프 전용)")
    @app_commands.describe(scrim_id="취소할 내전 ID")
    async def force_cancel_scrim(self, interaction: discord.Interaction, scrim_id: str):
        # Check permissions
        if not self.has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data:
            await interaction.followup.send("❌ 해당 내전을 찾을 수 없습니다.", ephemeral=True)
            return

        if scrim_data['guild_id'] != interaction.guild.id:
            await interaction.followup.send("❌ 이 서버의 내전이 아닙니다.", ephemeral=True)
            return

        success = await self.cancel_scrim(scrim_id, interaction.user.id)
        if success:
            await interaction.followup.send(f"✅ 내전 `{scrim_id}`가 취소되었습니다.", ephemeral=True)

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
            await interaction.followup.send("❌ 내전 취소 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="내전종료", description="내전 패널 메시지를 새로고침하고 맨 아래에 다시 게시합니다. (스태프 전용)")
    @app_commands.default_permissions(administrator=True)
    async def end_scrim(self, interaction: discord.Interaction):
        # Defer the interaction response
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        scrim_channel_id = config.get_channel_id(guild_id, 'scrim_channel')

        if not scrim_channel_id:
            await interaction.followup.send("❌ 내전 채널이 설정되지 않았습니다.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(scrim_channel_id)
        if not channel:
            await interaction.followup.send("❌ 내전 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        # Delete previous scrim panel messages
        deleted_count = 0
        async for message in channel.history(limit=50):
            if message.author == self.bot.user and message.embeds and "내전 생성 패널" in message.embeds[0].title:
                try:
                    await message.delete()
                    deleted_count += 1
                except discord.errors.NotFound:
                    continue  # Message was already deleted, continue
                except Exception as e:
                    self.logger.error(f"Error deleting old scrim panel message: {e}",
                                      extra={'guild_id': guild_id})
                    await interaction.followup.send("❌ 이전 메시지 삭제 중 오류가 발생했습니다.", ephemeral=True)
                    return

        # Post the new scrim panel
        await self.setup_scrim_panel(channel)

        # Acknowledge the user
        await interaction.followup.send("✅ 내전 패널이 성공적으로 새로고침되었습니다.", ephemeral=True)
async def setup(bot):
    await bot.add_cog(ScrimCog(bot))