# /cogs/warning_system.py

import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime
import asyncio
from typing import Optional
import logging

# Set up logger
logger = logging.getLogger(__name__)


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

            # Add the warning to database
            warning_id = await cog.add_warning(
                guild_id=interaction.guild.id,
                target_user=target_user,
                moderator=interaction.user,
                reason=self.reason.value,
                additional_info=self.additional_info.value if self.additional_info.value else None
            )

            # Get total warnings for this user
            total_warnings = await cog.get_user_warning_count(interaction.guild.id, target_user.id)

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
                name="총 경고 수",
                value=f"{total_warnings}회",
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
                name="총 경고 수",
                value=f"{total_warnings}회",
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

            # Try to send to the same channel
            try:
                await interaction.followup.send(embed=admin_embed)

                # Get the cog and repost the warning system embed
                cog = interaction.client.get_cog('WarningSystem')
                if cog:
                    await cog.repost_warning_system(interaction.guild)

            except:
                # If that fails, try to send to a log channel or the original channel
                logger.warning(f"Failed to send admin tracking embed in guild {interaction.guild.id}")

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

        # Add the persistent view
        self.bot.add_view(WarningView())

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
                    is_active BOOLEAN DEFAULT TRUE
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

            conn.commit()
            conn.close()
            logger.info("Warning database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to setup warning database: {e}")

    async def cog_load(self):
        """Called when the cog is loaded - check and setup warning embeds"""
        await self.bot.wait_until_ready()  # Wait for bot to be ready
        await self.check_and_setup_warning_embeds()

    async def check_and_setup_warning_embeds(self):
        """Check if warning embeds exist and create them if they don't"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            for guild in self.bot.guilds:
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

    async def add_warning(self, guild_id: int, target_user: discord.Member, moderator: discord.Member,
                          reason: str, additional_info: Optional[str] = None) -> int:
        """Add a warning to the database and return the warning ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO warnings 
                (guild_id, user_id, username, display_name, moderator_id, moderator_username, reason, additional_info)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                guild_id,
                target_user.id,
                target_user.name,
                target_user.display_name,
                moderator.id,
                moderator.name,
                reason,
                additional_info
            ))

            warning_id = cursor.lastrowid
            conn.commit()
            conn.close()

            logger.info(f"Warning {warning_id} added for user {target_user.id} in guild {guild_id}")
            return warning_id

        except Exception as e:
            logger.error(f"Failed to add warning: {e}")
            raise

    async def get_user_warning_count(self, guild_id: int, user_id: int) -> int:
        """Get the total number of active warnings for a user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT COUNT(*) FROM warnings 
                WHERE guild_id = ? AND user_id = ? AND is_active = TRUE
            ''', (guild_id, user_id))

            count = cursor.fetchone()[0]
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
                "• 총 경고 횟수\n"
                "• 고유 경고 ID"
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

        warnings = await self.get_user_warnings(interaction.guild.id, user.id)
        total_count = len(warnings)

        if total_count == 0:
            embed = discord.Embed(
                title=f"📋 {user.display_name}의 경고 내역",
                description="이 사용자는 경고 내역이 없습니다.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title=f"📋 {user.display_name}의 경고 내역",
                description=f"총 **{total_count}개**의 경고가 있습니다.",
                color=discord.Color.orange()
            )

            # Show last 5 warnings
            for i, warning in enumerate(warnings[:5]):
                warning_id, guild_id, user_id, username, display_name, mod_id, mod_username, reason, additional_info, created_at, is_active = warning

                embed.add_field(
                    name=f"경고 #{warning_id}",
                    value=(
                        f"**발행자:** {mod_username}\n"
                        f"**날짜:** {created_at}\n"
                        f"**사유:** {reason}\n"
                        f"**추가정보:** {additional_info or 'N/A'}"
                    ),
                    inline=False
                )

            if total_count > 5:
                embed.set_footer(text=f"최근 5개 경고만 표시됨 (총 {total_count}개)")

        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(WarningSystem(bot))