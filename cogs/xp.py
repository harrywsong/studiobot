# cogs/xp_system.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Set
import math

from utils.logger import get_logger
from utils import config


class XPLeaderboardView(discord.ui.View):
    """Persistent view for XP leaderboard navigation"""

    def __init__(self, bot, guild_id=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.current_page = 0
        self.users_per_page = 10
        self.logger = get_logger("경험치 시스템")

    async def get_leaderboard_data(self):
        """Get XP leaderboard data from database for this guild"""
        query = """
            SELECT user_id, xp, level 
            FROM user_xp 
            WHERE xp > 0 AND guild_id = $1
            ORDER BY xp DESC 
            LIMIT 100
        """
        return await self.bot.pool.fetch(query, self.guild_id)

    def calculate_level_from_xp(self, xp: int) -> int:
        """Calculate level from XP using a progressive formula"""
        if xp <= 0:
            return 1

        # New faster progression formula: level = floor(xp / (50 + level * 25)) + 1
        # This creates much shorter level requirements that scale reasonably
        level = 1
        total_xp_needed = 0

        while True:
            xp_for_this_level = 50 + (level - 1) * 25  # Level 1: 50, Level 2: 75, Level 3: 100, etc.
            if total_xp_needed + xp_for_this_level > xp:
                break
            total_xp_needed += xp_for_this_level
            level += 1

        return level

    def calculate_xp_for_level(self, level: int) -> int:
        """Calculate minimum XP required for a level"""
        if level <= 1:
            return 0

        total_xp = 0
        for i in range(1, level):
            total_xp += 50 + (i - 1) * 25
        return total_xp

    async def create_leaderboard_embed(self, page=0):
        """Create leaderboard embed for specific page"""
        data = await self.get_leaderboard_data()

        if not data:
            embed = discord.Embed(
                title="🏆 경험치 리더보드",
                description="아직 경험치 데이터가 없습니다.",
                color=discord.Color.purple()
            )
            return embed

        total_pages = (len(data) - 1) // self.users_per_page + 1
        page = max(0, min(page, total_pages - 1))

        start_idx = page * self.users_per_page
        end_idx = start_idx + self.users_per_page
        page_data = data[start_idx:end_idx]

        embed = discord.Embed(
            title="🏆 경험치 리더보드",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )

        leaderboard_text = ""
        for idx, record in enumerate(page_data, start=start_idx + 1):
            try:
                user = self.bot.get_user(record['user_id'])
                username = user.display_name if user else f"Unknown User ({record['user_id']})"

                level = self.calculate_level_from_xp(record['xp'])
                next_level_xp = self.calculate_xp_for_level(level + 1)
                progress_xp = record['xp'] - self.calculate_xp_for_level(level)
                xp_needed = next_level_xp - self.calculate_xp_for_level(level)

                # Add medal emojis for top 3
                if idx == 1:
                    medal = "🥇"
                elif idx == 2:
                    medal = "🥈"
                elif idx == 3:
                    medal = "🥉"
                else:
                    medal = f"`{idx:2d}.`"

                leaderboard_text += f"{medal} **{username}**\n"
                leaderboard_text += f"    레벨 {level} | {record['xp']:,} XP\n"
                leaderboard_text += f"    다음 레벨까지: {next_level_xp - record['xp']:,} XP\n\n"

            except Exception as e:
                self.logger.warning(
                    f"Could not fetch user for XP leaderboard: User ID {record['user_id']}, Guild ID {self.guild_id}",
                    extra={'guild_id': self.guild_id})
                level = self.calculate_level_from_xp(record['xp'])
                leaderboard_text += f"`{idx:2d}.` Unknown User - 레벨 {level} | {record['xp']:,} XP\n\n"

        embed.description = leaderboard_text or "데이터를 불러올 수 없습니다."
        embed.set_footer(text=f"페이지 {page + 1}/{total_pages} • 총 {len(data)}명")

        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary, custom_id="xp_leaderboard_prev")
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        if not self.guild_id:
            self.guild_id = interaction.guild.id

        if self.current_page > 0:
            self.current_page -= 1
            embed = await self.create_leaderboard_embed(self.current_page)
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary, custom_id="xp_leaderboard_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        if not self.guild_id:
            self.guild_id = interaction.guild.id

        data = await self.get_leaderboard_data()
        total_pages = (len(data) - 1) // self.users_per_page + 1 if data else 1

        if self.current_page < total_pages - 1:
            self.current_page += 1
            embed = await self.create_leaderboard_embed(self.current_page)
            await interaction.edit_original_response(embed=embed, view=self)


class XPSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("경험치 시스템")

        # Track users currently in voice channels
        self.voice_users: Dict[int, Dict[int, datetime]] = {}  # guild_id -> {user_id: join_time}

        # XP boost tracking
        self.xp_boost_users: Set[int] = set()  # Users with XP boost active

        # Leaderboard management
        self.guild_leaderboard_data = {}  # guild_id: message_info
        self.pending_leaderboard_updates = {}  # guild_id: bool
        self.update_delay = 5  # seconds
        self.last_leaderboard_cache = {}  # guild_id: data

        # Message persistence
        import json
        import os
        self.message_ids_file = "data/xp_leaderboard_ids.json"

        self.logger.info("경험치 시스템이 초기화되었습니다.")

    def has_admin_permissions(self, member: discord.Member) -> bool:
        """Check if member has admin permissions"""
        if member.guild_permissions.administrator:
            return True

        admin_role_id = config.get_role_id(member.guild.id, 'admin_role')
        if admin_role_id:
            admin_role = discord.utils.get(member.roles, id=admin_role_id)
            return admin_role is not None

        staff_role_id = config.get_role_id(member.guild.id, 'staff_role')
        if staff_role_id:
            staff_role = discord.utils.get(member.roles, id=staff_role_id)
            return staff_role is not None

        return False

    async def setup_database(self):
        """Create necessary database tables for XP system"""
        try:
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_xp (
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    total_voice_time INTEGER DEFAULT 0,
                    last_xp_gain TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS xp_transactions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    xp_change INTEGER NOT NULL,
                    transaction_type VARCHAR(50) NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes
            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_xp_guild_xp ON user_xp(guild_id, xp DESC);
            """)

            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_xp_transactions_user_guild ON xp_transactions(user_id, guild_id);
            """)

            self.logger.info("경험치 데이터베이스 테이블이 준비되었습니다.")
        except Exception as e:
            self.logger.error(f"데이터베이스 설정 실패: {e}", exc_info=True)

    def calculate_level_from_xp(self, xp: int) -> int:
        """Calculate level from XP using a progressive formula"""
        if xp <= 0:
            return 1
        return int(math.sqrt(xp / 100)) + 1

    def calculate_xp_for_level(self, level: int) -> int:
        """Calculate minimum XP required for a level"""
        if level <= 1:
            return 0
        return (level - 1) ** 2 * 100

    async def get_user_xp(self, user_id: int, guild_id: int) -> Dict:
        """Get user's XP data"""
        try:
            row = await self.bot.pool.fetchrow(
                "SELECT xp, level, total_voice_time FROM user_xp WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            if row:
                return {
                    'xp': row['xp'],
                    'level': row['level'],
                    'total_voice_time': row['total_voice_time']
                }
            return {'xp': 0, 'level': 1, 'total_voice_time': 0}
        except Exception as e:
            self.logger.error(f"Error getting XP for {user_id} in guild {guild_id}: {e}", extra={'guild_id': guild_id})
            return {'xp': 0, 'level': 1, 'total_voice_time': 0}

    async def add_xp(self, user_id: int, guild_id: int, xp_amount: int, transaction_type: str = "voice_chat",
                     description: str = ""):
        """Add XP to user and check for level up"""
        try:
            # Get current data
            current_data = await self.get_user_xp(user_id, guild_id)
            new_xp = current_data['xp'] + xp_amount
            new_level = self.calculate_level_from_xp(new_xp)
            old_level = current_data['level']

            # Update database
            await self.bot.pool.execute("""
                INSERT INTO user_xp (user_id, guild_id, xp, level, last_xp_gain)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, guild_id) 
                DO UPDATE SET 
                    xp = user_xp.xp + $3,
                    level = $4,
                    last_xp_gain = CURRENT_TIMESTAMP
            """, user_id, guild_id, xp_amount, new_level)

            # Log transaction
            await self.bot.pool.execute("""
                INSERT INTO xp_transactions (user_id, guild_id, xp_change, transaction_type, description)
                VALUES ($1, $2, $3, $4, $5)
            """, user_id, guild_id, xp_amount, transaction_type, description)

            # Check for level up
            if new_level > old_level:
                await self.handle_level_up(user_id, guild_id, old_level, new_level)

            # Schedule leaderboard update
            self.bot.loop.create_task(self.schedule_leaderboard_update(guild_id))

            self.logger.info(f"Added {xp_amount} XP to user {user_id} in guild {guild_id}: {description}",
                             extra={'guild_id': guild_id})
            return True
        except Exception as e:
            self.logger.error(f"Error adding XP to {user_id} in guild {guild_id}: {e}", extra={'guild_id': guild_id})
            return False

    async def handle_level_up(self, user_id: int, guild_id: int, old_level: int, new_level: int):
        """Handle level up notification"""
        try:
            user = self.bot.get_user(user_id)
            if not user:
                return

            # You can customize this to send to a specific channel or as a DM
            guild = self.bot.get_guild(guild_id)
            if guild:
                # Try to find a general channel to announce level up
                channel = None
                for ch in guild.text_channels:
                    if ch.name in ['general', '일반', 'chat', '채팅'] and ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break

                if channel:
                    embed = discord.Embed(
                        title="🎉 레벨 업!",
                        description=f"축하합니다! {user.mention}님이 레벨 {new_level}에 도달했습니다!",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="이전 레벨", value=f"레벨 {old_level}", inline=True)
                    embed.add_field(name="새 레벨", value=f"레벨 {new_level}", inline=True)

                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass

        except Exception as e:
            self.logger.error(f"Error handling level up for user {user_id}: {e}", extra={'guild_id': guild_id})

    async def schedule_leaderboard_update(self, guild_id: int):
        """Schedule a delayed leaderboard update"""
        if self.pending_leaderboard_updates.get(guild_id, False):
            return

        self.pending_leaderboard_updates[guild_id] = True
        await asyncio.sleep(self.update_delay)

        try:
            await self.update_leaderboard_now(guild_id)
        except Exception as e:
            self.logger.error(f"Error in scheduled XP leaderboard update for guild {guild_id}: {e}",
                              extra={'guild_id': guild_id})
        finally:
            self.pending_leaderboard_updates[guild_id] = False

    async def should_update_leaderboard(self, guild_id: int) -> bool:
        """Check if leaderboard needs updating"""
        try:
            query = """
                SELECT user_id, xp 
                FROM user_xp 
                WHERE xp > 0 AND guild_id = $1
                ORDER BY xp DESC 
                LIMIT 10
            """
            current_data = await self.bot.pool.fetch(query, guild_id)
            current_top = [(record['user_id'], record['xp']) for record in current_data]

            if self.last_leaderboard_cache.get(guild_id) == current_top:
                return False

            self.last_leaderboard_cache[guild_id] = current_top
            return True
        except Exception as e:
            self.logger.error(f"Error checking XP leaderboard changes for guild {guild_id}: {e}",
                              extra={'guild_id': guild_id})
            return True

    async def update_leaderboard_now(self, guild_id: int):
        """Update XP leaderboard message"""
        # Hardcoded channel ID as requested
        leaderboard_channel_id = 1421263904809553982

        if not await self.should_update_leaderboard(guild_id):
            return

        try:
            channel = self.bot.get_channel(leaderboard_channel_id)
            if not channel:
                self.logger.error(f"XP leaderboard channel {leaderboard_channel_id} not found for guild {guild_id}",
                                  extra={'guild_id': guild_id})
                return

            # Create new leaderboard
            leaderboard_view = XPLeaderboardView(self.bot, guild_id)
            leaderboard_embed = await leaderboard_view.create_leaderboard_embed()

            guild_str = str(guild_id)

            # Try to edit existing message
            if guild_str in self.guild_leaderboard_data:
                try:
                    message_id = self.guild_leaderboard_data[guild_str]
                    message = await channel.fetch_message(message_id)
                    await message.edit(embed=leaderboard_embed, view=leaderboard_view)
                    self.logger.info(f"XP leaderboard updated via edit for guild {guild_id}",
                                     extra={'guild_id': guild_id})
                    return
                except discord.NotFound:
                    self.logger.warning(f"XP leaderboard message {message_id} not found for guild {guild_id}",
                                        extra={'guild_id': guild_id})
                    del self.guild_leaderboard_data[guild_str]

            # Find existing XP leaderboard message
            async for msg in channel.history(limit=50):
                if (msg.author == self.bot.user and
                        msg.embeds and
                        msg.embeds[0].title and
                        "경험치 리더보드" in msg.embeds[0].title):
                    try:
                        await msg.edit(embed=leaderboard_embed, view=leaderboard_view)
                        self.guild_leaderboard_data[guild_str] = msg.id
                        await self.save_message_ids()
                        self.logger.info(f"Found and updated existing XP leaderboard message for guild {guild_id}",
                                         extra={'guild_id': guild_id})
                        return
                    except discord.HTTPException:
                        continue

            # Create new message
            message = await channel.send(embed=leaderboard_embed, view=leaderboard_view)
            self.guild_leaderboard_data[guild_str] = message.id
            await self.save_message_ids()
            self.logger.info(f"Created new XP leaderboard message for guild {guild_id}", extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error(f"Error updating XP leaderboard for guild {guild_id}: {e}", extra={'guild_id': guild_id})

    async def save_message_ids(self):
        """Save message IDs for persistence"""
        try:
            import os
            import json
            os.makedirs(os.path.dirname(self.message_ids_file), exist_ok=True)
            with open(self.message_ids_file, 'w') as f:
                json.dump(self.guild_leaderboard_data, f)
        except Exception as e:
            self.logger.error(f"Error saving XP message IDs: {e}")

    async def load_message_ids(self):
        """Load message IDs from file"""
        try:
            import os
            import json
            if os.path.exists(self.message_ids_file):
                with open(self.message_ids_file, 'r') as f:
                    self.guild_leaderboard_data = json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading XP message IDs: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Setup when bot is ready"""
        await self.setup_database()
        await self.load_message_ids()

        # Check for users with XP boost role
        xp_boost_role_id = 1421264239900889118
        for guild in self.bot.guilds:
            role = guild.get_role(xp_boost_role_id)
            if role:
                for member in role.members:
                    self.xp_boost_users.add(member.id)

        # Start XP gain task
        if not self.xp_gain_task.is_running():
            self.xp_gain_task.start()

        # Clean up and setup leaderboards for all configured servers
        all_configs = config.get_all_server_configs()
        for guild_id_str in all_configs.keys():
            guild_id = int(guild_id_str)

            # Delete old messages first
            await self.delete_old_leaderboard_messages(guild_id)

            # Clear stored message ID
            if guild_id_str in self.guild_leaderboard_data:
                del self.guild_leaderboard_data[guild_id_str]

            # Wait a moment then create new leaderboard
            await asyncio.sleep(1)
            await self.update_leaderboard_now(guild_id)

        # Save updated message IDs
        await self.save_message_ids()
        self.logger.info("XP system reloaded - cleaned up old messages and created fresh leaderboards")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track voice channel activity"""
        if member.bot:
            return

        guild_id = member.guild.id
        user_id = member.id
        now = datetime.now(timezone.utc)

        # Initialize guild tracking
        if guild_id not in self.voice_users:
            self.voice_users[guild_id] = {}

        # User joined a voice channel
        if before.channel is None and after.channel is not None:
            self.voice_users[guild_id][user_id] = now
            self.logger.info(f"User {user_id} joined voice channel in guild {guild_id}", extra={'guild_id': guild_id})

        # User left a voice channel
        elif before.channel is not None and after.channel is None:
            if user_id in self.voice_users[guild_id]:
                join_time = self.voice_users[guild_id][user_id]
                duration = (now - join_time).total_seconds()

                # Award XP based on duration (1 XP per minute)
                xp_gained = max(1, int(duration / 60))

                # Apply XP boost if user has the role
                if user_id in self.xp_boost_users:
                    xp_gained *= 2

                await self.add_xp(user_id, guild_id, xp_gained, "voice_chat", f"Voice chat for {duration:.0f} seconds")

                # Update total voice time
                try:
                    await self.bot.pool.execute("""
                        UPDATE user_xp 
                        SET total_voice_time = total_voice_time + $3
                        WHERE user_id = $1 AND guild_id = $2
                    """, user_id, guild_id, int(duration))
                except Exception as e:
                    self.logger.error(f"Error updating voice time for {user_id}: {e}", extra={'guild_id': guild_id})

                del self.voice_users[guild_id][user_id]
                self.logger.info(f"User {user_id} left voice channel, gained {xp_gained} XP",
                                 extra={'guild_id': guild_id})

        # User switched channels (no XP change, just update time)
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            if user_id in self.voice_users[guild_id]:
                # Award XP for time in previous channel
                join_time = self.voice_users[guild_id][user_id]
                duration = (now - join_time).total_seconds()

                if duration > 60:  # Only if they were in for more than a minute
                    xp_gained = max(1, int(duration / 60))

                    if user_id in self.xp_boost_users:
                        xp_gained *= 2

                    await self.add_xp(user_id, guild_id, xp_gained, "voice_chat",
                                      f"Voice chat for {duration:.0f} seconds")

                    try:
                        await self.bot.pool.execute("""
                            UPDATE user_xp 
                            SET total_voice_time = total_voice_time + $3
                            WHERE user_id = $1 AND guild_id = $2
                        """, user_id, guild_id, int(duration))
                    except Exception as e:
                        self.logger.error(f"Error updating voice time for {user_id}: {e}", extra={'guild_id': guild_id})

                # Reset timer for new channel
                self.voice_users[guild_id][user_id] = now

    @tasks.loop(minutes=1)
    async def xp_gain_task(self):
        """Award XP to users currently in voice channels"""
        try:
            for guild_id, users in self.voice_users.items():
                for user_id, join_time in list(users.items()):
                    # Award 1 XP per minute (with boost if applicable)
                    xp_to_award = 2 if user_id in self.xp_boost_users else 1

                    await self.add_xp(user_id, guild_id, xp_to_award, "voice_chat_periodic", "1분 보이스 채팅")

                    # Update voice time
                    try:
                        await self.bot.pool.execute("""
                            UPDATE user_xp 
                            SET total_voice_time = total_voice_time + 60
                            WHERE user_id = $1 AND guild_id = $2
                        """, user_id, guild_id)
                    except Exception as e:
                        self.logger.error(f"Error updating periodic voice time for {user_id}: {e}",
                                          extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error(f"Error in XP gain task: {e}")

    # Slash Commands
    @app_commands.command(name="경험치", description="자신 또는 다른 사용자의 경험치와 레벨을 확인합니다.")
    @app_commands.describe(user="경험치를 확인할 사용자 (생략시 본인)")
    async def check_xp(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer(ephemeral=True)

        target_user = user or interaction.user
        guild_id = interaction.guild.id

        try:
            # Get user XP data
            user_data = await self.get_user_xp(target_user.id, guild_id)
            xp = user_data['xp']
            level = user_data['level']
            total_voice_time = user_data['total_voice_time']

            # Get user rank
            rank_query = """
                SELECT COUNT(*) + 1 as rank
                FROM user_xp
                WHERE guild_id = $1 AND xp > $2
            """
            rank_result = await self.bot.pool.fetchrow(rank_query, guild_id, xp)
            rank = rank_result['rank'] if rank_result else 1

            # Calculate level progress
            current_level_xp = self.calculate_xp_for_level(level)
            next_level_xp = self.calculate_xp_for_level(level + 1)
            progress_xp = xp - current_level_xp
            needed_xp = next_level_xp - current_level_xp
            progress_percentage = (progress_xp / needed_xp) * 100 if needed_xp > 0 else 100

            embed = discord.Embed(
                title=f"📊 {target_user.display_name}님의 경험치 정보",
                color=discord.Color.purple(),
                timestamp=datetime.now(timezone.utc)
            )

            embed.add_field(name="현재 레벨", value=f"**레벨 {level}**", inline=True)
            embed.add_field(name="총 경험치", value=f"{xp:,} XP", inline=True)
            embed.add_field(name="서버 순위", value=f"**#{rank}**", inline=True)

            # Progress bar
            progress_bar_length = 20
            filled_length = int(progress_bar_length * progress_percentage / 100)
            bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)

            embed.add_field(
                name="다음 레벨까지의 진행도",
                value=f"`{bar}` {progress_percentage:.1f}%\n"
                      f"{progress_xp:,} / {needed_xp:,} XP\n"
                      f"({next_level_xp - xp:,} XP 남음)",
                inline=False
            )

            # Voice time stats
            hours = total_voice_time // 3600
            minutes = (total_voice_time % 3600) // 60
            embed.add_field(
                name="총 보이스 채팅 시간",
                value=f"{hours}시간 {minutes}분",
                inline=True
            )

            # XP boost status
            if target_user.id in self.xp_boost_users:
                embed.add_field(
                    name="부스터 상태",
                    value="🚀 2배 경험치 활성화!",
                    inline=True
                )

            embed.set_thumbnail(url=target_user.display_avatar.url)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"Error in check_xp command: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="경험치추가", description="사용자에게 경험치를 추가합니다. (관리자 전용)")
    @app_commands.describe(
        user="경험치를 받을 사용자",
        amount="추가할 경험치 양",
        reason="추가 이유 (선택사항)"
    )
    async def admin_add_xp(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                           reason: str = "관리자 추가"):
        guild_id = interaction.guild.id

        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("경험치 양은 0보다 커야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success = await self.add_xp(user.id, guild_id, amount, "admin_add",
                                    f"관리자 추가 by {interaction.user.display_name}: {reason}")

        if success:
            user_data = await self.get_user_xp(user.id, guild_id)
            await interaction.followup.send(
                f"✅ {user.mention}님에게 {amount:,} 경험치를 추가했습니다.\n"
                f"현재 레벨: {user_data['level']}\n"
                f"총 경험치: {user_data['xp']:,} XP\n"
                f"이유: {reason}",
                ephemeral=True
            )
            self.logger.info(
                f"Admin {interaction.user.id} added {amount} XP to user {user.id} in guild {guild_id}: {reason}",
                extra={'guild_id': guild_id})
        else:
            await interaction.followup.send("경험치 추가 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="경험치설정", description="사용자의 경험치를 특정 값으로 설정합니다. (관리자 전용)")
    @app_commands.describe(
        user="경험치를 설정할 사용자",
        amount="설정할 경험치 양",
        reason="설정 이유 (선택사항)"
    )
    async def admin_set_xp(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                           reason: str = "관리자 설정"):
        guild_id = interaction.guild.id

        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        if amount < 0:
            await interaction.response.send_message("경험치 양은 0 이상이어야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Get current XP
            current_data = await self.get_user_xp(user.id, guild_id)
            current_xp = current_data['xp']
            new_level = self.calculate_level_from_xp(amount)

            # Update database
            await self.bot.pool.execute("""
                INSERT INTO user_xp (user_id, guild_id, xp, level)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, guild_id) 
                DO UPDATE SET xp = EXCLUDED.xp, level = EXCLUDED.level
            """, user.id, guild_id, amount, new_level)

            # Log transaction
            xp_difference = amount - current_xp
            await self.bot.pool.execute("""
                INSERT INTO xp_transactions (user_id, guild_id, xp_change, transaction_type, description)
                VALUES ($1, $2, $3, $4, $5)
            """, user.id, guild_id, xp_difference, "admin_set", f"관리자 설정 by {interaction.user.display_name}: {reason}")

            # Trigger leaderboard update
            self.bot.loop.create_task(self.schedule_leaderboard_update(guild_id))

            await interaction.followup.send(
                f"✅ {user.mention}님의 경험치를 {amount:,} XP로 설정했습니다.\n"
                f"이전 경험치: {current_xp:,} XP\n"
                f"현재 레벨: {new_level}\n"
                f"이유: {reason}",
                ephemeral=True
            )
            self.logger.info(
                f"Admin {interaction.user.id} set user {user.id} XP to {amount} in guild {guild_id}: {reason}",
                extra={'guild_id': guild_id})

        except Exception as e:
            await interaction.followup.send(f"경험치 설정 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"Error in admin_set_xp for user {user.id} in guild {guild_id}: {e}",
                              extra={'guild_id': guild_id})

    async def delete_old_leaderboard_messages(self, guild_id: int):
        """Delete old leaderboard messages from the channel"""
        try:
            # Hardcoded channel ID as in your original code
            leaderboard_channel_id = 1421263904809553982
            channel = self.bot.get_channel(leaderboard_channel_id)

            if not channel:
                self.logger.error(f"XP leaderboard channel {leaderboard_channel_id} not found for guild {guild_id}",
                                  extra={'guild_id': guild_id})
                return False

            deleted_count = 0
            async for message in channel.history(limit=50):
                if (message.author == self.bot.user and
                        message.embeds and
                        message.embeds[0].title and
                        "경험치 리더보드" in message.embeds[0].title):
                    try:
                        await message.delete()
                        deleted_count += 1
                        await asyncio.sleep(0.5)  # Rate limit protection
                    except discord.NotFound:
                        pass  # Message already deleted
                    except discord.Forbidden:
                        self.logger.warning(f"No permission to delete message in channel {leaderboard_channel_id}",
                                            extra={'guild_id': guild_id})
                        break

            self.logger.info(f"Deleted {deleted_count} old XP leaderboard messages in guild {guild_id}",
                             extra={'guild_id': guild_id})
            return True

        except Exception as e:
            self.logger.error(f"Error deleting old XP leaderboard messages for guild {guild_id}: {e}",
                              extra={'guild_id': guild_id})
            return False

async def setup(bot):
    await bot.add_cog(XPSystemCog(bot))