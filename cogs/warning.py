# /cogs/warning_system.py

import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import datetime
import asyncio
from typing import Optional
import logging

# Set up logger
logger = logging.getLogger(__name__)

# Role IDs for warning system
WARNING_1X_ROLE_ID = 1368442950069129267
WARNING_2X_ROLE_ID = 1368443461233279138
BAN_NOTIFICATION_CHANNEL_ID = 1059248496730976307


class WarningModal(discord.ui.Modal, title='경고 추가 - Add Warning'):
    def __init__(self):
        super().__init__(timeout=300)  # 5 minute timeout

    # User input field
    user_input = discord.ui.TextInput(
        label='경고받을 사용자 (User to warn)',
        placeholder='@사용자명, 사용자ID, 또는 사용자명을 입력하세요...',
        required=True,
        max_length=100
    )

    # Reason input field
    reason = discord.ui.TextInput(
        label='경고 사유 (Warning Reason)',
        placeholder='경고 사유를 입력하세요...',
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph
    )

    # Additional information field
    additional_info = discord.ui.TextInput(
        label='추가 정보 (Additional Information)',
        placeholder='추가 정보가 있다면 입력하세요 (선택사항)...',
        required=False,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Defer the response to prevent timeout
            await interaction.response.defer(ephemeral=True)

            # Try to find the user
            target_user = await self.resolve_user(interaction, self.user_input.value)
            if not target_user:
                await interaction.followup.send(
                    "❌ 사용자를 찾을 수 없습니다. 사용자명, ID, 또는 멘션을 정확히 입력해주세요.",
                    ephemeral=True
                )
                return

            # Get the cog instance
            cog = interaction.client.get_cog('WarningSystem')
            if not cog:
                await interaction.followup.send("❌ 경고 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            # Add the warning to database and handle role management
            warning_id, new_warning_count = await cog.add_warning(
                guild_id=interaction.guild.id,
                target_user=target_user,
                moderator=interaction.user,
                reason=self.reason.value,
                additional_info=self.additional_info.value if self.additional_info.value else None
            )

            # Create success embed
            success_embed = discord.Embed(
                title="✅ 경고가 성공적으로 추가되었습니다",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            success_embed.add_field(
                name="대상 사용자",
                value=f"{target_user.mention} ({target_user.display_name})",
                inline=False
            )
            success_embed.add_field(
                name="경고 사유",
                value=self.reason.value,
                inline=False
            )
            if self.additional_info.value:
                success_embed.add_field(
                    name="추가 정보",
                    value=self.additional_info.value,
                    inline=False
                )
            success_embed.add_field(
                name="현재 활성 경고 수",
                value=f"{new_warning_count}회",
                inline=True
            )
            success_embed.add_field(
                name="경고 ID",
                value=f"#{warning_id}",
                inline=True
            )

            await interaction.followup.send(embed=success_embed, ephemeral=True)

            # Create admin tracking embed
            admin_embed = discord.Embed(
                title="🚨 새로운 경고 기록",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now()
            )
            admin_embed.add_field(
                name="대상 사용자",
                value=f"{target_user.mention}\n**이름:** {target_user.display_name}\n**사용자명:** {target_user.name}\n**ID:** {target_user.id}",
                inline=False
            )
            admin_embed.add_field(
                name="경고 발행자",
                value=f"{interaction.user.mention}\n**ID:** {interaction.user.id}",
                inline=True
            )
            admin_embed.add_field(
                name="현재 활성 경고 수",
                value=f"{new_warning_count}회",
                inline=True
            )
            admin_embed.add_field(
                name="경고 사유",
                value=self.reason.value,
                inline=False
            )
            if self.additional_info.value:
                admin_embed.add_field(
                    name="추가 정보",
                    value=self.additional_info.value,
                    inline=False
                )
            admin_embed.add_field(
                name="경고 ID",
                value=f"#{warning_id}",
                inline=True
            )
            admin_embed.add_field(
                name="서버",
                value=f"{interaction.guild.name} ({interaction.guild.id})",
                inline=True
            )

            # Try to send the admin tracking embed
            try:
                await interaction.followup.send(embed=admin_embed)
            except Exception as e:
                logger.warning(f"Failed to send admin tracking embed in guild {interaction.guild.id}: {e}")
                # The warning system will still repost the main embed below, so this is non-critical.

            # Repost the warning system embed regardless of whether the admin embed send succeeded.
            try:
                cog = interaction.client.get_cog('WarningSystem')
                if cog:
                    await cog.repost_warning_system(interaction.guild)
                else:
                    logger.error("WarningSystem cog not found during repost attempt.")
            except Exception as e:
                logger.error(f"Error reposting warning system embed after modal submission: {e}")

        except Exception as e:
            logger.error(f"Error in warning modal submit: {e}")
            try:
                await interaction.followup.send(
                    f"❌ 경고 처리 중 오류가 발생했습니다: {str(e)}",
                    ephemeral=True
                )
            except:
                pass

    async def resolve_user(self, interaction: discord.Interaction, user_input: str) -> Optional[discord.Member]:
        """Try to resolve a user from various input formats"""
        user_input = user_input.strip()

        # Try to get user by mention
        if user_input.startswith('<@') and user_input.endswith('>'):
            user_id = user_input[2:-1]
            if user_id.startswith('!'):
                user_id = user_id[1:]
            try:
                return interaction.guild.get_member(int(user_id))
            except ValueError:
                pass

        # Try to get user by ID
        if user_input.isdigit():
            return interaction.guild.get_member(int(user_input))

        # Try to get user by username or display name
        for member in interaction.guild.members:
            if (member.name.lower() == user_input.lower() or
                    member.display_name.lower() == user_input.lower()):
                return member

        # Try partial matching
        for member in interaction.guild.members:
            if (user_input.lower() in member.name.lower() or
                    user_input.lower() in member.display_name.lower()):
                return member

        return None


class WarningView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view

    @discord.ui.button(
        label='경고 추가 (Add Warning)',
        style=discord.ButtonStyle.red,
        emoji='⚠️',
        custom_id='add_warning_button'
    )
    async def add_warning(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user has appropriate permissions
        if not (interaction.user.guild_permissions.moderate_members or
                interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(
                "❌ 이 기능을 사용하려면 멤버 관리 권한이 필요합니다.",
                ephemeral=True
            )
            return

        # Show the warning modal
        modal = WarningModal()
        await interaction.response.send_modal(modal)


class WarningSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "warnings.db"
        self.warning_channel_id = 1368795110439129108  # Your target channel ID
        self.warning_embed_message_id = None  # Store the message ID
        self.setup_database()

        # Start the warning expiration check task
        self.warning_expiration_check.start()

    def setup_database(self):
        """Initialize the warnings database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    moderator_username TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    additional_info TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    can_expire BOOLEAN DEFAULT TRUE
                )
            ''')

            # Create table to store warning embed message IDs per guild
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS warning_embeds (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create table to track user warning states and timers
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_warning_states (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    active_warnings INTEGER DEFAULT 0,
                    timer_started_at TIMESTAMP,
                    timer_expires_at TIMESTAMP,
                    can_lose_warnings BOOLEAN DEFAULT TRUE,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')

            # Add new columns to existing warnings table if they don't exist
            try:
                cursor.execute('ALTER TABLE warnings ADD COLUMN expires_at TIMESTAMP')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE warnings ADD COLUMN can_expire BOOLEAN DEFAULT TRUE')
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.commit()
            conn.close()
            logger.info("Warning database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to setup warning database: {e}")

    async def cog_load(self):
        """Called when the cog is loaded - check and setup warning embeds"""
        try:
            # Add the persistent view when cog loads
            self.bot.add_view(WarningView())

            # Schedule the embed check to run after bot is ready
            self.bot.loop.create_task(self.delayed_setup())
        except Exception as e:
            logger.error(f"Error in cog_load: {e}")

    async def delayed_setup(self):
        """Delayed setup to ensure bot is fully ready"""
        try:
            await self.bot.wait_until_ready()  # Wait for bot to be ready
            await asyncio.sleep(2)  # Additional delay to ensure everything is loaded
            await self.check_and_setup_warning_embeds()
        except Exception as e:
            logger.error(f"Error in delayed_setup: {e}")

    @tasks.loop(minutes=5)  # Check every 5 minutes
    async def warning_expiration_check(self):
        """Check for expired warnings and update user roles accordingly"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.datetime.now()

            # Get all user warning states that have expired timers
            cursor.execute('''
                SELECT guild_id, user_id, active_warnings, timer_expires_at, can_lose_warnings
                FROM user_warning_states 
                WHERE timer_expires_at <= ? AND timer_expires_at IS NOT NULL AND can_lose_warnings = TRUE
            ''', (now,))

            expired_states = cursor.fetchall()

            for guild_id, user_id, active_warnings, timer_expires_at, can_lose_warnings in expired_states:
                try:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    member = guild.get_member(user_id)
                    if not member:
                        # User left the server, clean up their warning state
                        cursor.execute('DELETE FROM user_warning_states WHERE guild_id = ? AND user_id = ?',
                                       (guild_id, user_id))
                        continue

                    await self.handle_warning_expiration(guild, member, active_warnings, cursor)

                except Exception as e:
                    logger.error(f"Error processing expired warning for user {user_id} in guild {guild_id}: {e}")
                    continue

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Error in warning expiration check: {e}")

    @warning_expiration_check.before_loop
    async def before_warning_expiration_check(self):
        await self.bot.wait_until_ready()

    async def handle_warning_expiration(self, guild: discord.Guild, member: discord.Member,
                                        active_warnings: int, cursor):
        """Handle what happens when a user's warning timer expires"""
        try:
            warning_1x_role = guild.get_role(WARNING_1X_ROLE_ID)
            warning_2x_role = guild.get_role(WARNING_2X_ROLE_ID)

            if active_warnings == 2:
                # User had 2 warnings, remove 2x role and go back to 1x
                if warning_2x_role and warning_2x_role in member.roles:
                    await member.remove_roles(warning_2x_role,
                                              reason="Warning timer expired - downgraded to 1x warning")

                # Start new 14-day timer for the remaining 1 warning
                new_timer_expires = datetime.datetime.now() + datetime.timedelta(days=14)
                cursor.execute('''
                    UPDATE user_warning_states 
                    SET active_warnings = 1, timer_started_at = ?, timer_expires_at = ?
                    WHERE guild_id = ? AND user_id = ?
                ''', (datetime.datetime.now(), new_timer_expires, guild.id, member.id))

                logger.info(f"User {member.id} in guild {guild.id} downgraded from 2x to 1x warning")

            elif active_warnings == 1:
                # User had 1 warning, remove 1x role and clear all warnings
                if warning_1x_role and warning_1x_role in member.roles:
                    await member.remove_roles(warning_1x_role, reason="Warning timer expired - all warnings cleared")

                # Clear the user's warning state
                cursor.execute('DELETE FROM user_warning_states WHERE guild_id = ? AND user_id = ?',
                               (guild.id, member.id))

                logger.info(f"User {member.id} in guild {guild.id} had all warnings cleared")

        except Exception as e:
            logger.error(f"Error handling warning expiration for {member.id} in {guild.id}: {e}")

    async def add_warning(self, guild_id: int, target_user: discord.Member, moderator: discord.Member,
                          reason: str, additional_info: Optional[str] = None) -> tuple[int, int]:
        """Add a warning to the database, handle role management, and return the warning ID and new warning count"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.datetime.now()

            # Get current warning state
            cursor.execute('''
                SELECT active_warnings, can_lose_warnings FROM user_warning_states 
                WHERE guild_id = ? AND user_id = ?
            ''', (guild_id, target_user.id))

            state_result = cursor.fetchone()
            current_warnings = state_result[0] if state_result else 0
            can_lose_warnings = state_result[1] if state_result else True

            new_warning_count = current_warnings + 1

            # Determine if this warning can expire (it can't if user reaches 3 warnings)
            can_expire = new_warning_count < 3
            expires_at = now + datetime.timedelta(days=14) if can_expire else None

            # Add warning to database
            cursor.execute('''
                INSERT INTO warnings 
                (guild_id, user_id, username, display_name, moderator_id, moderator_username, 
                 reason, additional_info, expires_at, can_expire)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                guild_id,
                target_user.id,
                target_user.name,
                target_user.display_name,
                moderator.id,
                moderator.name,
                reason,
                additional_info,
                expires_at,
                can_expire
            ))

            warning_id = cursor.lastrowid

            # Handle role management based on warning count
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self.manage_warning_roles(guild, target_user, current_warnings, new_warning_count)

            # Update or create user warning state
            if new_warning_count >= 3:
                # User reached 3 warnings - send ban notification and stop timer
                timer_expires = None
                can_lose = False
                await self.send_ban_notification(guild, target_user, new_warning_count)
            else:
                # Reset 14-day timer
                timer_expires = now + datetime.timedelta(days=14)
                can_lose = True

            cursor.execute('''
                INSERT OR REPLACE INTO user_warning_states 
                (guild_id, user_id, active_warnings, timer_started_at, timer_expires_at, can_lose_warnings)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (guild_id, target_user.id, new_warning_count, now, timer_expires, can_lose))

            conn.commit()
            conn.close()

            logger.info(
                f"Warning {warning_id} added for user {target_user.id} in guild {guild_id}. New count: {new_warning_count}")
            return warning_id, new_warning_count

        except Exception as e:
            logger.error(f"Failed to add warning: {e}")
            raise

    async def manage_warning_roles(self, guild: discord.Guild, member: discord.Member,
                                   old_count: int, new_count: int):
        """Manage warning roles based on warning count"""
        try:
            warning_1x_role = guild.get_role(WARNING_1X_ROLE_ID)
            warning_2x_role = guild.get_role(WARNING_2X_ROLE_ID)

            if not warning_1x_role or not warning_2x_role:
                logger.error(f"Warning roles not found in guild {guild.id}")
                return

            if new_count == 1:
                # First warning - add 1x role
                if warning_1x_role not in member.roles:
                    await member.add_roles(warning_1x_role, reason="First warning received")
                    logger.info(f"Added 1x warning role to {member.id} in guild {guild.id}")

            elif new_count == 2:
                # Second warning - add 2x role, remove 1x role
                if warning_1x_role in member.roles:
                    await member.remove_roles(warning_1x_role, reason="Upgraded to 2x warning")
                if warning_2x_role not in member.roles:
                    await member.add_roles(warning_2x_role, reason="Second warning received")
                    logger.info(f"Added 2x warning role to {member.id} in guild {guild.id}")

        except Exception as e:
            logger.error(f"Error managing warning roles for {member.id}: {e}")

    async def send_ban_notification(self, guild: discord.Guild, member: discord.Member, warning_count: int):
        """Send ban notification when user reaches 3 warnings"""
        try:
            ban_channel = guild.get_channel(BAN_NOTIFICATION_CHANNEL_ID)
            if not ban_channel:
                logger.error(f"Ban notification channel {BAN_NOTIFICATION_CHANNEL_ID} not found in guild {guild.id}")
                return

            embed = discord.Embed(
                title="🚨 밴 권고 알림 (Ban Recommendation)",
                description=f"사용자가 **3회 경고**를 누적하여 서버 밴이 권장됩니다.",
                color=discord.Color.dark_red(),
                timestamp=datetime.datetime.now()
            )

            embed.add_field(
                name="대상 사용자",
                value=f"{member.mention}\n**이름:** {member.display_name}\n**사용자명:** {member.name}\n**ID:** {member.id}",
                inline=False
            )

            embed.add_field(
                name="누적 경고 수",
                value=f"**{warning_count}회**",
                inline=True
            )

            embed.add_field(
                name="권장 조치",
                value="서버에서 밴 처리",
                inline=True
            )

            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"서버: {guild.name}")

            await ban_channel.send(embed=embed)
            logger.info(f"Ban notification sent for user {member.id} in guild {guild.id}")

        except Exception as e:
            logger.error(f"Error sending ban notification for {member.id}: {e}")

    async def get_user_warning_count(self, guild_id: int, user_id: int) -> int:
        """Get the current active warning count for a user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT active_warnings FROM user_warning_states 
                WHERE guild_id = ? AND user_id = ?
            ''', (guild_id, user_id))

            result = cursor.fetchone()
            count = result[0] if result else 0
            conn.close()

            return count

        except Exception as e:
            logger.error(f"Failed to get warning count: {e}")
            return 0

    async def get_user_warnings(self, guild_id: int, user_id: int) -> list:
        """Get all warnings for a specific user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT * FROM warnings 
                WHERE guild_id = ? AND user_id = ? AND is_active = TRUE
                ORDER BY created_at DESC
            ''', (guild_id, user_id))

            warnings = cursor.fetchall()
            conn.close()

            return warnings

        except Exception as e:
            logger.error(f"Failed to get user warnings: {e}")
            return []

    async def check_and_setup_warning_embeds(self):
        """Check if warning embeds exist and create them if they don't"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            for guild in self.bot.guilds:
                try:
                    # Check if this guild has a warning embed recorded
                    cursor.execute('SELECT channel_id, message_id FROM warning_embeds WHERE guild_id = ?', (guild.id,))
                    result = cursor.fetchone()

                    warning_channel = guild.get_channel(self.warning_channel_id)
                    if not warning_channel:
                        logger.info(
                            f"Warning channel {self.warning_channel_id} not found in guild {guild.name} ({guild.id})")
                        continue

                    embed_exists = False

                    if result:
                        channel_id, message_id = result
                        try:
                            # Check if the message still exists
                            message = await warning_channel.fetch_message(message_id)
                            if message and message.embeds and len(message.components) > 0:
                                embed_exists = True
                                logger.info(f"Warning embed already exists in guild {guild.name} ({guild.id})")
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            # Message doesn't exist anymore, remove from database
                            cursor.execute('DELETE FROM warning_embeds WHERE guild_id = ?', (guild.id,))
                            logger.info(f"Removed stale warning embed record for guild {guild.name} ({guild.id})")

                    if not embed_exists:
                        # Create new warning embed
                        await self.create_warning_embed(guild, warning_channel)
                        logger.info(f"Created warning embed for guild {guild.name} ({guild.id})")

                except Exception as e:
                    logger.error(f"Error processing guild {guild.name} ({guild.id}): {e}")
                    continue

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Error checking and setting up warning embeds: {e}")

    async def create_warning_embed(self, guild: discord.Guild, channel: discord.TextChannel):
        """Create and send the warning system embed to the specified channel"""
        try:
            embed = self.create_warning_system_embed()
            view = WarningView()

            message = await channel.send(embed=embed, view=view)

            # Save the message ID to database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO warning_embeds (guild_id, channel_id, message_id)
                VALUES (?, ?, ?)
            ''', (guild.id, channel.id, message.id))
            conn.commit()
            conn.close()

            self.warning_embed_message_id = message.id
            logger.info(f"Warning embed created with ID {message.id} in guild {guild.name}")

        except Exception as e:
            logger.error(f"Failed to create warning embed in guild {guild.name}: {e}")

    async def repost_warning_system(self, guild: discord.Guild):
        """Delete the old warning system embed and repost it to keep it at the bottom"""
        try:
            warning_channel = guild.get_channel(self.warning_channel_id)
            if not warning_channel:
                logger.warning(f"Warning channel {self.warning_channel_id} not found in guild {guild.id}")
                return

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get the current embed message ID
            cursor.execute('SELECT message_id FROM warning_embeds WHERE guild_id = ?', (guild.id,))
            result = cursor.fetchone()

            if result:
                message_id = result[0]
                try:
                    old_message = await warning_channel.fetch_message(message_id)
                    await old_message.delete()
                    logger.info(f"Deleted old warning system embed {message_id}")
                except discord.NotFound:
                    logger.info("Old warning system embed not found, probably already deleted")
                except discord.Forbidden:
                    logger.warning("Missing permissions to delete old warning system embed")
                except Exception as e:
                    logger.error(f"Error deleting old warning system embed: {e}")

            # Create and send the new embed
            embed = self.create_warning_system_embed()
            view = WarningView()

            new_message = await warning_channel.send(embed=embed, view=view)

            # Update the database with new message ID
            cursor.execute('''
                INSERT OR REPLACE INTO warning_embeds (guild_id, channel_id, message_id)
                VALUES (?, ?, ?)
            ''', (guild.id, warning_channel.id, new_message.id))

            conn.commit()
            conn.close()

            self.warning_embed_message_id = new_message.id
            logger.info(f"Reposted warning system embed with ID {new_message.id}")

        except Exception as e:
            logger.error(f"Failed to repost warning system embed: {e}")

    def create_warning_system_embed(self) -> discord.Embed:
        """Create the warning system instruction embed"""
        embed = discord.Embed(
            title="🚨 경고 시스템 (Warning System)",
            description="이 시스템을 통해 서버 멤버들에게 경고를 발행하고 관리할 수 있습니다.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )

        embed.add_field(
            name="📋 사용 방법",
            value=(
                "1️⃣ 아래 **경고 추가** 버튼을 클릭하세요\n"
                "2️⃣ 경고를 받을 사용자를 입력하세요\n"
                "3️⃣ 경고 사유를 입력하세요\n"
                "4️⃣ 필요시 추가 정보를 입력하세요\n"
                "5️⃣ 제출하면 자동으로 기록됩니다"
            ),
            inline=False
        )

        embed.add_field(
            name="⚠️ 경고 시스템 규칙",
            value=(
                "• **1회 경고**: Warning 1x 역할 부여, 14일 후 자동 해제\n"
                "• **2회 경고**: Warning 2x 역할 부여, 14일 타이머 리셋\n"
                "• **3회 경고**: 밴 권고 알림, 타이머 정지"
            ),
            inline=False
        )

        embed.add_field(
            name="⚠️ 권한 요구사항",
            value="이 시스템을 사용하려면 **멤버 관리** 권한이 필요합니다.",
            inline=False
        )

        embed.add_field(
            name="📊 추적 정보",
            value=(
                "• 경고 받은 사용자의 모든 정보\n"
                "• 경고 발행자 정보\n"
                "• 경고 날짜 및 시간\n"
                "• 경고 사유 및 추가 정보\n"
                "• 현재 활성 경고 횟수\n"
                "• 고유 경고 ID\n"
                "• 자동 만료 시간"
            ),
            inline=False
        )

        embed.set_footer(text="경고 시스템 | 관리자 전용")
        return embed

    @commands.command(name='경고설정')
    @commands.has_permissions(administrator=True)
    async def setup_warnings(self, ctx):
        """Setup the warning system in the specified channel (manual command)"""
        target_channel = ctx.guild.get_channel(self.warning_channel_id)

        if not target_channel:
            await ctx.send(f"❌ 채널을 찾을 수 없습니다 (ID: {self.warning_channel_id})")
            return

        await self.create_warning_embed(ctx.guild, target_channel)
        await ctx.send(f"✅ 경고 시스템이 {target_channel.mention}에 설정되었습니다!")

    @commands.command(name='경고체크')
    @commands.has_permissions(moderate_members=True)
    async def check_warning_embed(self, ctx):
        """Check if warning embed exists and recreate if necessary"""
        await self.check_and_setup_warning_embeds()
        await ctx.send("✅ 경고 시스템 임베드 상태를 확인하고 필요시 재생성했습니다.")

    @commands.command(name='경고만료체크')
    @commands.has_permissions(moderate_members=True)
    async def force_expiration_check(self, ctx):
        """Manually trigger warning expiration check"""
        await self.warning_expiration_check()
        await ctx.send("✅ 경고 만료 상태를 수동으로 확인했습니다.")

    @app_commands.command(name="경고기록", description="특정 사용자의 경고 내역을 조회합니다")
    @app_commands.describe(user="경고 내역을 조회할 사용자")
    async def check_warnings(self, interaction: discord.Interaction, user: discord.Member):
        """Check warnings for a specific user"""
        if not (interaction.user.guild_permissions.moderate_members or
                interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(
                "❌ 이 명령어를 사용하려면 멤버 관리 권한이 필요합니다.",
                ephemeral=True
            )
            return

        # Get current active warning count
        active_count = await self.get_user_warning_count(interaction.guild.id, user.id)

        # Get all warnings for detailed view
        warnings = await self.get_user_warnings(interaction.guild.id, user.id)

        if active_count == 0:
            embed = discord.Embed(
                title=f"📋 {user.display_name}의 경고 내역",
                description="이 사용자는 현재 활성 경고가 없습니다.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title=f"📋 {user.display_name}의 경고 내역",
                description=f"현재 **{active_count}개**의 활성 경고가 있습니다.",
                color=discord.Color.orange()
            )

            # Get warning state info
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                            SELECT timer_expires_at, can_lose_warnings FROM user_warning_states 
                            WHERE guild_id = ? AND user_id = ?
                        ''', (interaction.guild.id, user.id))

                state_result = cursor.fetchone()
                if state_result:
                    timer_expires_at, can_lose_warnings = state_result
                    if timer_expires_at and can_lose_warnings:
                        expire_time = datetime.datetime.fromisoformat(timer_expires_at)
                        embed.add_field(
                            name="⏰ 타이머 정보",
                            value=f"다음 만료 시간: {expire_time.strftime('%Y-%m-%d %H:%M:%S')}",
                            inline=False
                        )
                    elif not can_lose_warnings:
                        embed.add_field(
                            name="🔒 상태",
                            value="3회 경고 달성 - 타이머 정지됨",
                            inline=False
                        )

                conn.close()
            except Exception as e:
                logger.error(f"Error getting warning state: {e}")

            # Show last 5 warnings
            for i, warning in enumerate(warnings[:5]):
                warning_id = warning[0]
                reason = warning[7]
                additional_info = warning[8]
                created_at = warning[9]
                expires_at = warning[10]
                can_expire = warning[11]

                expire_info = ""
                if can_expire and expires_at:
                    expire_info = f"\n**만료일:** {expires_at}"
                elif not can_expire:
                    expire_info = f"\n**상태:** 영구 경고"

                embed.add_field(
                    name=f"경고 #{warning_id}",
                    value=(
                        f"**날짜:** {created_at}\n"
                        f"**사유:** {reason}\n"
                        f"**추가정보:** {additional_info or 'N/A'}"
                        f"{expire_info}"
                    ),
                    inline=False
                )

            if len(warnings) > 5:
                embed.set_footer(text=f"최근 5개 경고만 표시됨 (총 {len(warnings)}개)")

        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="경고제거", description="특정 사용자의 모든 경고를 제거합니다 (관리자 전용)")
    @app_commands.describe(user="경고를 제거할 사용자")
    async def remove_warnings(self, interaction: discord.Interaction, user: discord.Member):
        """Remove all warnings for a specific user (admin only)"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ 이 명령어를 사용하려면 관리자 권한이 필요합니다.",
                ephemeral=True
            )
            return

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get current warning count
            current_count = await self.get_user_warning_count(interaction.guild.id, user.id)

            if current_count == 0:
                await interaction.response.send_message(
                    f"ℹ️ {user.display_name}님은 현재 활성 경고가 없습니다.",
                    ephemeral=True
                )
                return

            # Remove all warning roles
            warning_1x_role = interaction.guild.get_role(WARNING_1X_ROLE_ID)
            warning_2x_role = interaction.guild.get_role(WARNING_2X_ROLE_ID)

            roles_to_remove = []
            if warning_1x_role and warning_1x_role in user.roles:
                roles_to_remove.append(warning_1x_role)
            if warning_2x_role and warning_2x_role in user.roles:
                roles_to_remove.append(warning_2x_role)

            if roles_to_remove:
                await user.remove_roles(*roles_to_remove, reason=f"All warnings removed by {interaction.user.name}")

            # Clear user warning state
            cursor.execute('DELETE FROM user_warning_states WHERE guild_id = ? AND user_id = ?',
                           (interaction.guild.id, user.id))

            # Deactivate all warnings for this user (keep for records)
            cursor.execute('''
                        UPDATE warnings SET is_active = FALSE 
                        WHERE guild_id = ? AND user_id = ? AND is_active = TRUE
                    ''', (interaction.guild.id, user.id))

            conn.commit()
            conn.close()

            embed = discord.Embed(
                title="✅ 경고 제거 완료",
                description=f"{user.display_name}님의 모든 경고({current_count}개)가 제거되었습니다.",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(
                name="제거된 경고 수",
                value=f"{current_count}개",
                inline=True
            )
            embed.add_field(
                name="실행자",
                value=interaction.user.mention,
                inline=True
            )

            await interaction.response.send_message(embed=embed)
            logger.info(
                f"All warnings removed for user {user.id} by {interaction.user.id} in guild {interaction.guild.id}")

        except Exception as e:
            logger.error(f"Error removing warnings: {e}")
            await interaction.response.send_message(
                f"❌ 경고 제거 중 오류가 발생했습니다: {str(e)}",
                ephemeral=True
            )

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.warning_expiration_check.cancel()


async def setup(bot):
    await bot.add_cog(WarningSystem(bot))