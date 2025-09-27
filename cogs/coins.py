# cogs/coins.py
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import traceback
import json
import os
from datetime import datetime, timezone, timedelta
import pytz

from utils.logger import get_logger
from utils import config


class CoinsView(discord.ui.View):
    """Persistent view for claiming daily coins"""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        # FIX: Initialize logger here for guild-specific logging if needed in view methods
        self.logger = get_logger("코인 시스템")


    @discord.ui.button(label="💰 일일 코인 받기", style=discord.ButtonStyle.green, custom_id="claim_daily_coins")
    async def claim_daily_coins(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if casino games are enabled for this server
        if not config.is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 코인 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id
        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)  # This is timezone-aware
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)  # Still timezone-aware

        try:
            # Check if user already claimed today (guild-specific)
            check_query = """
                    SELECT last_claim_date FROM user_coins 
                    WHERE user_id = $1 AND guild_id = $2
                """
            row = await self.bot.pool.fetchrow(check_query, user_id, guild_id)

            if row and row['last_claim_date']:
                # The database returns a naive datetime, so we need to make it timezone-aware
                last_claim = row['last_claim_date']

                # If last_claim is naive, assume it's in EST and make it timezone-aware
                if last_claim.tzinfo is None:
                    last_claim = eastern.localize(last_claim)
                else:
                    # If it already has timezone info, convert to eastern
                    last_claim = last_claim.astimezone(eastern)

                if last_claim >= today_start:
                    next_claim = (today_start + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S EST")
                    await interaction.followup.send(
                        f"❌ 오늘은 이미 코인을 받았습니다!\n다음 받기: {next_claim}",
                        ephemeral=True
                    )
                    return

            # Get starting coins amount from server settings
            starting_coins = config.get_server_setting(guild_id, 'starting_coins', 50)

            # Give daily coins using the add_coins method to trigger leaderboard update
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                # Store as naive datetime in the database (convert timezone-aware to naive)
                naive_now = now.replace(tzinfo=None)

                # Update the database directly for daily claims to include last_claim_date
                update_query = """
                        INSERT INTO user_coins (user_id, guild_id, coins, last_claim_date, total_earned)
                        VALUES ($1, $2, $3, $4, $3)
                        ON CONFLICT (user_id, guild_id) 
                        DO UPDATE SET 
                            coins = user_coins.coins + $3,
                            total_earned = user_coins.total_earned + $3,
                            last_claim_date = EXCLUDED.last_claim_date
                        RETURNING coins
                    """
                result = await self.bot.pool.fetchrow(update_query, user_id, guild_id, starting_coins, naive_now)

                # Log transaction
                await self.bot.pool.execute("""
                        INSERT INTO coin_transactions (user_id, guild_id, amount, transaction_type, description)
                        VALUES ($1, $2, $3, $4, $5)
                    """, user_id, guild_id, starting_coins, "daily_claim", "Daily coin claim")

                # Trigger leaderboard update
                self.bot.loop.create_task(coins_cog.schedule_leaderboard_update(guild_id))

                embed = discord.Embed(
                    title="💰 일일 코인 지급!",
                    description=f"✅ {starting_coins} 코인을 받았습니다!\n현재 잔액: **{result['coins']} 코인**",
                    color=discord.Color.gold(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="다음 받기는 내일 자정(EST)에 가능합니다")

                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 오류가 발생했습니다: {e}", ephemeral=True)
            # FIX: Add guild_id to log message
            self.logger.error(f"Daily coin claim error for {user_id} in guild {guild_id}: {e}", extra={'guild_id': guild_id})


class LeaderboardView(discord.ui.View):
    """Persistent view for coin leaderboard navigation"""

    def __init__(self, bot, guild_id=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.current_page = 0
        self.users_per_page = 10
        # FIX: Initialize logger here
        self.logger = get_logger("코인 시스템")


    async def get_leaderboard_data(self):
        """Get leaderboard data from database for this guild"""
        query = """
            SELECT user_id, coins 
            FROM user_coins 
            WHERE coins > 0 AND guild_id = $1
            ORDER BY coins DESC 
            LIMIT 100
        """
        return await self.bot.pool.fetch(query, self.guild_id)

    async def create_leaderboard_embed(self, page=0):
        """Create leaderboard embed for specific page"""
        data = await self.get_leaderboard_data()

        if not data:
            embed = discord.Embed(
                title="🏆 코인 리더보드",
                description="아직 코인 데이터가 없습니다.",
                color=discord.Color.gold()
            )
            return embed

        total_pages = (len(data) - 1) // self.users_per_page + 1
        page = max(0, min(page, total_pages - 1))

        start_idx = page * self.users_per_page
        end_idx = start_idx + self.users_per_page
        page_data = data[start_idx:end_idx]

        embed = discord.Embed(
            title="🏆 코인 리더보드",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        leaderboard_text = ""
        for idx, record in enumerate(page_data, start=start_idx + 1):
            try:
                user = self.bot.get_user(record['user_id'])
                username = user.display_name if user else f"Unknown User ({record['user_id']})"

                # Add medal emojis for top 3
                if idx == 1:
                    medal = "🥇"
                elif idx == 2:
                    medal = "🥈"
                elif idx == 3:
                    medal = "🥉"
                else:
                    medal = f"`{idx:2d}.`"

                leaderboard_text += f"{medal} **{username}** - {record['coins']:,} 코인\n"
            except:
                # FIX: Add guild_id to log message
                self.logger.warning(f"Could not fetch user for leaderboard entry: User ID {record['user_id']}, Guild ID {self.guild_id}", extra={'guild_id': self.guild_id})
                leaderboard_text += f"`{idx:2d}.` Unknown User - {record['coins']:,} 코인\n"

        embed.description = leaderboard_text or "데이터를 불러올 수 없습니다."
        embed.set_footer(text=f"페이지 {page + 1}/{total_pages} • 총 {len(data)}명")

        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary, custom_id="leaderboard_prev")
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        # Get guild_id from interaction if not set
        if not self.guild_id:
            self.guild_id = interaction.guild.id

        if self.current_page > 0:
            self.current_page -= 1
            embed = await self.create_leaderboard_embed(self.current_page)
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary, custom_id="leaderboard_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        # Get guild_id from interaction if not set
        if not self.guild_id:
            self.guild_id = interaction.guild.id

        data = await self.get_leaderboard_data()
        total_pages = (len(data) - 1) // self.users_per_page + 1 if data else 1

        if self.current_page < total_pages - 1:
            self.current_page += 1
            embed = await self.create_leaderboard_embed(self.current_page)
            await interaction.edit_original_response(embed=embed, view=self)


class CoinsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # FIX: Logger initialization updated
        self.logger = get_logger("코인 시스템")

        # Spam protection - user_id: last_command_time
        self.last_command_time = {}
        self.cooldown_seconds = 3

        # Per-guild leaderboard management
        self.guild_leaderboard_data = {}  # guild_id: message_info
        self.guild_claim_data = {}  # guild_id: message_info

        # Real-time update controls per guild
        self.pending_leaderboard_updates = {}  # guild_id: bool
        self.update_delay = 3  # seconds to debounce updates
        self.last_leaderboard_cache = {}  # guild_id: data

        # Message ID persistence per guild
        self.message_ids_file = "data/guild_message_ids.json"

        self.logger.info("코인 시스템이 초기화되었습니다.")

        # Start tasks after bot is ready
        self.bot.loop.create_task(self.wait_and_start_tasks())

    def has_admin_permissions(self, member: discord.Member) -> bool:
        """Check if member has admin permissions"""
        # Check if user has administrator permissions
        if member.guild_permissions.administrator:
            return True

        # Check if user has the specific admin role for this guild
        admin_role_id = config.get_role_id(member.guild.id, 'admin_role')
        if admin_role_id:
            admin_role = discord.utils.get(member.roles, id=admin_role_id)
            return admin_role is not None

        # Fallback to staff role if admin role not configured
        staff_role_id = config.get_role_id(member.guild.id, 'staff_role')
        if staff_role_id:
            staff_role = discord.utils.get(member.roles, id=staff_role_id)
            return staff_role is not None

        return False

    async def wait_and_start_tasks(self):
        """Wait for bot to be ready then start tasks"""
        await self.bot.wait_until_ready()
        await self.setup_database()
        await self.load_message_ids()

        # Setup initial leaderboards for all configured guilds
        all_configs = config.get_all_server_configs()
        for guild_id_str, guild_config in all_configs.items():
            if guild_config.get('features', {}).get('casino_games'):
                guild_id = int(guild_id_str)
                await self.setup_initial_leaderboard(guild_id)

        # Start maintenance task
        self.maintenance_leaderboard_update.start()

    async def load_message_ids(self):
        """Load persistent message IDs from file"""
        try:
            if os.path.exists(self.message_ids_file):
                with open(self.message_ids_file, 'r') as f:
                    data = json.load(f)
                    self.guild_leaderboard_data = data.get('leaderboard', {})
                    self.guild_claim_data = data.get('claim', {})
                    # FIX: Add guild_id to log message (although this is global, context is useful)
                    self.logger.info("Loaded guild message IDs", extra={'guild_id': None}) # Using None as no specific guild context
        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error loading message IDs: {e}", extra={'guild_id': None})

    async def save_message_ids(self):
        """Save message IDs to file for persistence"""
        try:
            os.makedirs(os.path.dirname(self.message_ids_file), exist_ok=True)

            data = {
                'leaderboard': self.guild_leaderboard_data,
                'claim': self.guild_claim_data
            }

            with open(self.message_ids_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error saving message IDs: {e}", extra={'guild_id': None})

    async def setup_initial_leaderboard(self, guild_id: int):
        """Setup initial leaderboard and claim messages for a specific guild"""
        try:
            # Get leaderboard channel for this guild
            leaderboard_channel_id = config.get_channel_id(guild_id, 'leaderboard_channel')
            if not leaderboard_channel_id:
                # FIX: Add guild_id to log message
                self.logger.warning(f"No leaderboard channel configured for guild {guild_id}", extra={'guild_id': guild_id})
                return

            channel = self.bot.get_channel(leaderboard_channel_id)
            if not channel:
                # FIX: Add guild_id to log message
                self.logger.error(f"Leaderboard channel {leaderboard_channel_id} not found for guild {guild_id}", extra={'guild_id': guild_id})
                return

            guild_str = str(guild_id)

            # Verify existing message IDs are still valid
            if guild_str in self.guild_leaderboard_data:
                message_id = self.guild_leaderboard_data[guild_str]
                try:
                    await channel.fetch_message(message_id)
                    # FIX: Add guild_id to log message
                    self.logger.info(f"Found existing leaderboard message {message_id} for guild {guild_id}", extra={'guild_id': guild_id})
                except discord.NotFound:
                    # FIX: Add guild_id to log message
                    self.logger.warning(
                        f"Stored leaderboard message {message_id} no longer exists for guild {guild_id}", extra={'guild_id': guild_id})
                    del self.guild_leaderboard_data[guild_str]

            if guild_str in self.guild_claim_data:
                message_id = self.guild_claim_data[guild_str]
                try:
                    await channel.fetch_message(message_id)
                    # FIX: Add guild_id to log message
                    self.logger.info(f"Found existing claim message {message_id} for guild {guild_id}", extra={'guild_id': guild_id})
                except discord.NotFound:
                    # FIX: Add guild_id to log message
                    self.logger.warning(f"Stored claim message {message_id} no longer exists for guild {guild_id}", extra={'guild_id': guild_id})
                    del self.guild_claim_data[guild_str]

            # Update leaderboard (will find existing message if ID is None)
            await self.update_leaderboard_now(guild_id)

            # Setup claim message if needed
            if guild_str not in self.guild_claim_data:
                # Try to find existing claim message first
                found_claim = False
                async for msg in channel.history(limit=50):
                    if (msg.author == self.bot.user and
                            msg.embeds and
                            msg.embeds[0].title and
                            "일일 코인" in msg.embeds[0].title):
                        self.guild_claim_data[guild_str] = msg.id
                        await self.save_message_ids()
                        # Ensure the view is attached
                        await msg.edit(view=CoinsView(self.bot))
                        found_claim = True
                        # FIX: Add guild_id to log message
                        self.logger.info(f"Found and updated existing claim message {msg.id} for guild {guild_id}", extra={'guild_id': guild_id})
                        break

                # Create new claim message only if none found
                if not found_claim:
                    embed = discord.Embed(
                        title="💰 일일 코인",
                        description="매일 자정(EST)에 초기화됩니다.\n아래 버튼을 클릭하여 일일 코인을 받으세요!",
                        color=discord.Color.green()
                    )
                    message = await channel.send(embed=embed, view=CoinsView(self.bot))
                    self.guild_claim_data[guild_str] = message.id
                    await self.save_message_ids()
                    # FIX: Add guild_id to log message
                    self.logger.info(f"Created new claim message {message.id} for guild {guild_id}", extra={'guild_id': guild_id})

            # FIX: Add guild_id to log message
            self.logger.info(f"Initial leaderboard setup completed for guild {guild_id}", extra={'guild_id': guild_id})
        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error in initial leaderboard setup for guild {guild_id}: {e}", extra={'guild_id': guild_id})

    async def schedule_leaderboard_update(self, guild_id: int):
        """Schedule a delayed leaderboard update to debounce multiple changes"""
        if self.pending_leaderboard_updates.get(guild_id, False):
            return

        self.pending_leaderboard_updates[guild_id] = True

        # Wait for debounce period
        await asyncio.sleep(self.update_delay)

        try:
            await self.update_leaderboard_now(guild_id)
        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error in scheduled leaderboard update for guild {guild_id}: {e}", extra={'guild_id': guild_id})
        finally:
            self.pending_leaderboard_updates[guild_id] = False

    async def should_update_leaderboard(self, guild_id: int) -> bool:
        """Check if leaderboard actually needs updating by comparing data"""
        try:
            # Get current top 10 for comparison
            query = """
                SELECT user_id, coins 
                FROM user_coins 
                WHERE coins > 0 AND guild_id = $1
                ORDER BY coins DESC 
                LIMIT 10
            """
            current_data = await self.bot.pool.fetch(query, guild_id)

            # Convert to comparable format
            current_top = [(record['user_id'], record['coins']) for record in current_data]

            # Compare with cached data
            if self.last_leaderboard_cache.get(guild_id) == current_top:
                return False

            self.last_leaderboard_cache[guild_id] = current_top
            return True

        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error checking leaderboard changes for guild {guild_id}: {e}", extra={'guild_id': guild_id})
            return True  # Update on error to be safe

    async def update_leaderboard_now(self, guild_id: int):
        """Update leaderboard immediately using only message edits for specific guild"""
        # Get leaderboard channel for this guild
        leaderboard_channel_id = config.get_channel_id(guild_id, 'leaderboard_channel')
        if not leaderboard_channel_id:
            return

        # Check if update is actually needed
        if not await self.should_update_leaderboard(guild_id):
            return

        try:
            channel = self.bot.get_channel(leaderboard_channel_id)
            if not channel:
                # FIX: Add guild_id to log message
                self.logger.error(f"Leaderboard channel {leaderboard_channel_id} not found for guild {guild_id} during update.", extra={'guild_id': guild_id})
                return

            # Create new leaderboard
            leaderboard_view = LeaderboardView(self.bot, guild_id)
            leaderboard_embed = await leaderboard_view.create_leaderboard_embed()

            guild_str = str(guild_id)

            # Try to edit existing message first
            if guild_str in self.guild_leaderboard_data:
                try:
                    message_id = self.guild_leaderboard_data[guild_str]
                    message = await channel.fetch_message(message_id)
                    await message.edit(embed=leaderboard_embed, view=leaderboard_view)
                    # FIX: Add guild_id to log message
                    self.logger.info(f"Leaderboard updated via edit for guild {guild_id}", extra={'guild_id': guild_id})
                    return  # Successfully edited, exit early
                except discord.NotFound:
                    # FIX: Add guild_id to log message
                    self.logger.warning(
                        f"Leaderboard message {message_id} not found for guild {guild_id}, will search for existing message", extra={'guild_id': guild_id})
                    del self.guild_leaderboard_data[guild_str]  # Reset to search for existing
                except discord.HTTPException as e:
                    # Handle rate limits gracefully
                    if e.status == 429:
                        # FIX: Add guild_id to log message
                        self.logger.warning(f"Rate limited while updating leaderboard for guild {guild_id}", extra={'guild_id': guild_id})
                        return  # Skip this update due to rate limit
                    else:
                        # FIX: Add guild_id to log message
                        self.logger.error(f"HTTP error updating leaderboard for guild {guild_id}: {e}", extra={'guild_id': guild_id})
                        return

            # If no stored message ID, try to find existing leaderboard message
            async for msg in channel.history(limit=50):
                if (msg.author == self.bot.user and
                        msg.embeds and
                        msg.embeds[0].title and
                        "리더보드" in msg.embeds[0].title):
                    try:
                        await msg.edit(embed=leaderboard_embed, view=leaderboard_view)
                        self.guild_leaderboard_data[guild_str] = msg.id  # Store the found message ID
                        await self.save_message_ids()  # Persist the ID
                        # FIX: Add guild_id to log message
                        self.logger.info(
                            f"Found and updated existing leaderboard message {msg.id} for guild {guild_id}", extra={'guild_id': guild_id})
                        return
                    except discord.HTTPException:
                        continue  # Try next message if this one fails

            # Only create new message if we absolutely cannot find or edit an existing one
            message = await channel.send(embed=leaderboard_embed, view=leaderboard_view)
            self.guild_leaderboard_data[guild_str] = message.id
            await self.save_message_ids()  # Persist the new ID
            # FIX: Add guild_id to log message
            self.logger.info(
                f"Created new leaderboard message {message.id} for guild {guild_id} (no existing message found)", extra={'guild_id': guild_id})

        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error updating leaderboard for guild {guild_id}: {e}", extra={'guild_id': guild_id})

    async def setup_database(self):
        """Create necessary database tables with indexes for better performance"""
        try:
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_coins (
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    coins INTEGER DEFAULT 0,
                    last_claim_date TIMESTAMP,
                    total_earned INTEGER DEFAULT 0,
                    total_spent INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS coin_transactions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    transaction_type VARCHAR(50) NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for better performance
            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_coins_guild_coins ON user_coins(guild_id, coins DESC);
            """)

            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_coin_transactions_user_guild ON coin_transactions(user_id, guild_id);
            """)

            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_coin_transactions_guild_type ON coin_transactions(guild_id, transaction_type);
            """)

            self.logger.info("✅ 코인 데이터베이스 테이블이 준비되었습니다.")
        except Exception as e:
            # FIX: This is a global setup, so no specific guild_id to add to log
            self.logger.error(f"❌ 데이터베이스 설정 실패: {e}")

    def check_spam_protection(self, user_id: int) -> bool:
        """Check if user is spamming commands"""
        now = datetime.now()
        if user_id in self.last_command_time:
            time_diff = (now - self.last_command_time[user_id]).total_seconds()
            if time_diff < self.cooldown_seconds:
                return False

        self.last_command_time[user_id] = now
        return True

    async def get_user_coins(self, user_id: int, guild_id: int) -> int:
        """Get user's current coin balance for specific guild"""
        try:
            row = await self.bot.pool.fetchrow(
                "SELECT coins FROM user_coins WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            return row['coins'] if row else 0
        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error getting coins for {user_id} in guild {guild_id}: {e}", extra={'guild_id': guild_id})
            return 0

    async def add_coins(self, user_id: int, guild_id: int, amount: int, transaction_type: str = "earned",
                        description: str = ""):
        """Add coins to user account and trigger leaderboard update"""
        try:
            # Update user coins
            await self.bot.pool.execute("""
                INSERT INTO user_coins (user_id, guild_id, coins, total_earned)
                VALUES ($1, $2, $3, $3)
                ON CONFLICT (user_id, guild_id) 
                DO UPDATE SET 
                    coins = user_coins.coins + $3,
                    total_earned = user_coins.total_earned + $3
            """, user_id, guild_id, amount)

            # Log transaction
            await self.bot.pool.execute("""
                INSERT INTO coin_transactions (user_id, guild_id, amount, transaction_type, description)
                VALUES ($1, $2, $3, $4, $5)
            """, user_id, guild_id, amount, transaction_type, description)

            # Trigger real-time leaderboard update
            self.bot.loop.create_task(self.schedule_leaderboard_update(guild_id))

            # FIX: Add guild_id to log message
            self.logger.info(f"Added {amount} coins to user {user_id} in guild {guild_id}: {description}", extra={'guild_id': guild_id})
            return True
        except Exception as e:
            # FIX: Add guild_id to log message
            self.logger.error(f"Error adding coins to {user_id} in guild {guild_id}: {e}", extra={'guild_id': guild_id})
            return False

    async def remove_coins(self, user_id: int, guild_id: int, amount: int, transaction_type: str = "spent",
                           description: str = "") -> bool:
        """Atomically remove coins from a user's account and log the transaction."""
        try:
            # Use a transaction to ensure both update and log succeed or fail together
            async with self.bot.pool.transaction():
                # Atomically check and update the balance in one query
                result = await self.bot.pool.fetchval("""
                    UPDATE user_coins
                    SET 
                        coins = coins - $3,
                        total_spent = total_spent + $3
                    WHERE user_id = $1 AND guild_id = $2 AND coins >= $3
                    RETURNING coins
                """, user_id, guild_id, amount)

                # If result is None, it means the WHERE clause (coins >= amount) failed
                if result is None:
                    return False  # Not enough coins, transaction will be rolled back

                # If successful, log the transaction
                await self.bot.pool.execute("""
                    INSERT INTO coin_transactions (user_id, guild_id, amount, transaction_type, description)
                    VALUES ($1, $2, $3, $4, $5)
                """, user_id, guild_id, -amount, transaction_type, description)

            # If the transaction was successful, schedule the leaderboard update
            self.bot.loop.create_task(self.schedule_leaderboard_update(guild_id))
            self.logger.info(f"Removed {amount} coins from user {user_id}: {description}", extra={'guild_id': guild_id})
            return True

        except Exception as e:
            self.logger.error(f"Error removing coins from {user_id}: {e}", extra={'guild_id': guild_id})
            return False

    # Keep the original scheduled task as a backup/maintenance function
    @tasks.loop(hours=1)  # Reduced frequency since we have real-time updates
    async def maintenance_leaderboard_update(self):
        """Maintenance update every hour to ensure consistency for all guilds"""
        try:
            all_configs = config.get_all_server_configs()
            for guild_id_str, guild_config in all_configs.items():
                if guild_config.get('features', {}).get('casino_games'):
                    guild_id = int(guild_id_str)

                    # Get leaderboard channel for this guild
                    leaderboard_channel_id = config.get_channel_id(guild_id, 'leaderboard_channel')
                    if not leaderboard_channel_id:
                        continue

                    # Check if channel exists before proceeding
                    channel = self.bot.get_channel(leaderboard_channel_id)
                    if not channel:
                        # FIX: Add guild_id to log message
                        self.logger.warning(f"Maintenance task: Leaderboard channel {leaderboard_channel_id} not found for guild {guild_id}.", extra={'guild_id': guild_id})
                        continue

                    # Force update to ensure consistency
                    if guild_id in self.last_leaderboard_cache:
                        del self.last_leaderboard_cache[guild_id]
                    await self.update_leaderboard_now(guild_id)

                    # Also check if claim message needs maintenance
                    guild_str = str(guild_id)
                    if guild_str in self.guild_claim_data:
                        try:
                            message_id = self.guild_claim_data[guild_str]
                            message = await channel.fetch_message(message_id)
                            if not message.components:  # Re-add view if missing
                                await message.edit(view=CoinsView(self.bot))
                        except discord.NotFound:
                            # Recreate claim message if missing
                            embed = discord.Embed(
                                title="💰 일일 코인",
                                description="매일 자정(EST)에 초기화됩니다.\n아래 버튼을 클릭하여 일일 코인을 받으세요!",
                                color=discord.Color.green()
                            )
                            message = await channel.send(embed=embed, view=CoinsView(self.bot))
                            self.guild_claim_data[guild_str] = message.id
                            await self.save_message_ids()
                            # FIX: Add guild_id to log message
                            self.logger.info(f"Recreated missing claim message for guild {guild_id}", extra={'guild_id': guild_id})
                        except discord.HTTPException as e:
                            # FIX: Add guild_id to log message
                            self.logger.error(f"HTTP error during claim message maintenance for guild {guild_id}: {e}", extra={'guild_id': guild_id})

        except Exception as e:
            # FIX: This is a general maintenance task, no specific guild_id for this particular error
            self.logger.error(f"Error in maintenance leaderboard update: {e}")

    @app_commands.command(name="코인", description="현재 코인 잔액을 확인합니다.")
    async def check_coins(self, interaction: discord.Interaction, user: discord.Member = None):
        # Check if casino games are enabled
        if not config.is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 코인 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        if not self.check_spam_protection(interaction.user.id):
            await interaction.response.send_message("⏳ 잠시만 기다려주세요!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        target_user = user or interaction.user
        guild_id = interaction.guild.id
        coins = await self.get_user_coins(target_user.id, guild_id)

        try:
            # Get additional stats
            stats_query = """
                SELECT total_earned, total_spent, last_claim_date
                FROM user_coins WHERE user_id = $1 AND guild_id = $2
            """
            stats = await self.bot.pool.fetchrow(stats_query, target_user.id, guild_id)

            embed = discord.Embed(
                title=f"💰 {target_user.display_name}님의 코인 정보",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )

            embed.add_field(name="현재 잔액", value=f"{coins:,} 코인", inline=True)

            if stats:
                embed.add_field(name="총 획득", value=f"{stats['total_earned'] or 0:,} 코인", inline=True)
                embed.add_field(name="총 사용", value=f"{stats['total_spent'] or 0:,} 코인", inline=True)

                if stats['last_claim_date']:
                    # Ensure last_claim_date is timezone-aware for accurate formatting
                    last_claim_date_aware = stats['last_claim_date']
                    if last_claim_date_aware.tzinfo is None:
                        # Assume EST if naive, as per other parts of the cog
                        eastern = pytz.timezone('America/New_York')
                        last_claim_date_aware = eastern.localize(last_claim_date_aware)
                    else:
                        last_claim_date_aware = last_claim_date_aware.astimezone(pytz.utc) # Ensure consistent timezone before converting

                    # Format to display in EST
                    last_claim_formatted = last_claim_date_aware.astimezone(pytz.timezone('America/New_York')).strftime("%Y-%m-%d %H:%M EST")
                    embed.add_field(name="마지막 일일 코인", value=last_claim_formatted, inline=False)

            embed.set_thumbnail(url=target_user.display_avatar.url)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 오류가 발생했습니다: {e}", ephemeral=True)
            # FIX: Add guild_id to log message
            self.logger.error(f"Error in check_coins for user {target_user.id} in guild {guild_id}: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="코인주기", description="다른 사용자에게 코인을 전송합니다.")
    @app_commands.describe(
        user="코인을 받을 사용자",
        amount="전송할 코인 수량"
    )
    async def give_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        guild_id = interaction.guild.id

        # Check if casino games are enabled
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "⛔ 이 서버에서는 코인 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        if not self.check_spam_protection(interaction.user.id):
            await interaction.response.send_message("⏳ 잠시만 기다려주세요!", ephemeral=True)
            return

        if interaction.user == user:
            await interaction.response.send_message("⛔ 자기 자신에게 코인을 줄 수 없습니다.", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("⛔ 코인 수량은 0보다 커야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Check if recipient has overdue loan restrictions
            recipient_restrictions = await self.check_user_loan_restrictions(user.id, guild_id)

            if recipient_restrictions['restricted']:
                if recipient_restrictions['reason'] == 'overdue_loan':
                    embed = discord.Embed(
                        title="⛔ 코인 전송 제한",
                        description=f"{user.mention}님은 연체된 대출이 있어 다른 사용자로부터 코인을 받을 수 없습니다.",
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="제한 사유",
                        value="연체된 대출금 존재",
                        inline=True
                    )
                    embed.add_field(
                        name="남은 대출금",
                        value=f"{recipient_restrictions['remaining_amount']:,} 코인",
                        inline=True
                    )
                    embed.add_field(
                        name="해결 방법",
                        value="대상자가 대출금을 완전히 상환한 후 다시 시도해주세요.\n연체자는 일일 코인 수령만 가능합니다.",
                        inline=False
                    )

                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

            # Check if sender has enough coins
            sender_coins = await self.get_user_coins(interaction.user.id, guild_id)
            if sender_coins < amount:
                await interaction.followup.send(f"⛔ 코인이 부족합니다. 현재 잔액: {sender_coins:,} 코인", ephemeral=True)
                return

            # Attempt to remove coins from sender
            removed = await self.remove_coins(interaction.user.id, guild_id, amount, "given",
                                              f"Given to {user.display_name}")
            if not removed:
                await interaction.followup.send("⛔ 코인 전송 중 오류가 발생했습니다.", ephemeral=True)
                self.logger.error(
                    f"Failed to remove coins from sender {interaction.user.id} for give_coins command in guild {guild_id}",
                    extra={'guild_id': guild_id})
                return

            # Attempt to add coins to receiver
            added = await self.add_coins(user.id, guild_id, amount, "received",
                                         f"Received from {interaction.user.display_name}")
            if not added:
                # If adding coins fails, reverse the sender's deduction
                await self.add_coins(interaction.user.id, guild_id, amount, "refund",
                                     f"Refund for failed give to {user.display_name}")
                await interaction.followup.send("⛔ 코인 전송 중 오류가 발생했습니다. 잔액이 복구되었습니다.", ephemeral=True)
                self.logger.error(
                    f"Failed to add coins to receiver {user.id} for give_coins command in guild {guild_id}, attempted refund.",
                    extra={'guild_id': guild_id})
                return

            # Success
            await interaction.followup.send(f"✅ {user.mention}님께 {amount:,} 코인을 성공적으로 전송했습니다!")
            self.logger.info(f"User {interaction.user.id} gave {amount} coins to {user.id} in guild {guild_id}",
                             extra={'guild_id': guild_id})

        except Exception as e:
            await interaction.followup.send(f"⛔ 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"Error in give_coins command: {e}", extra={'guild_id': guild_id})

    # Add these admin commands to the CoinsCog class:

    @app_commands.command(name="코인추가", description="사용자에게 코인을 추가합니다. (관리자 전용)")
    @app_commands.describe(
        user="코인을 받을 사용자",
        amount="추가할 코인 수량",
        reason="추가 이유 (선택사항)"
    )
    async def admin_add_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                              reason: str = "Admin addition"):
        guild_id = interaction.guild.id

        # Check if casino games are enabled
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 코인 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        # Check admin permissions
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("❌ 코인 수량은 0보다 커야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Add coins
        success = await self.add_coins(user.id, guild_id, amount, "admin_add",
                                       f"Admin addition by {interaction.user.display_name}: {reason}")

        if success:
            new_balance = await self.get_user_coins(user.id, guild_id)
            await interaction.followup.send(
                f"✅ {user.mention}님에게 {amount:,} 코인을 추가했습니다.\n"
                f"현재 잔액: {new_balance:,} 코인\n"
                f"이유: {reason}",
            )
            self.logger.info(
                f"Admin {interaction.user.id} added {amount} coins to user {user.id} in guild {guild_id}: {reason}",
                extra={'guild_id': guild_id})

            # Post a public message to a specific channel and tag the role
            try:
                target_channel_id = 1418553048724406455
                target_role_id = 1417771791384051823

                channel = self.bot.get_channel(target_channel_id)
                if channel:
                    role_mention = f"<@&{target_role_id}>"
                    public_message = (
                        f"🎉 {role_mention}! **{user.display_name}**님에게 **{amount:,} 코인**이 "
                        f"관리자에 의해 추가되었습니다!\n"
                        f"현재 잔액: **{new_balance:,} 코인**\n"
                        f"이유: {reason}"
                    )
                    await channel.send(public_message)
            except Exception as e:
                self.logger.error(f"Failed to post public admin coin addition message: {e}",
                                  extra={'guild_id': guild_id})
        else:
            await interaction.followup.send("❌ 코인 추가 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="코인제거", description="사용자의 코인을 제거합니다. (관리자 전용)")
    @app_commands.describe(
        user="코인을 제거할 사용자",
        amount="제거할 코인 수량",
        reason="제거 이유 (선택사항)"
    )
    async def admin_remove_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                                 reason: str = "Admin removal"):
        guild_id = interaction.guild.id

        # Check if casino games are enabled
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 코인 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        # Check admin permissions
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("❌ 코인 수량은 0보다 커야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Check current balance
        current_balance = await self.get_user_coins(user.id, guild_id)

        # Remove coins (can go negative if admin chooses)
        success = await self.remove_coins(user.id, guild_id, amount, "admin_remove",
                                          f"Admin removal by {interaction.user.display_name}: {reason}")

        if success:
            new_balance = await self.get_user_coins(user.id, guild_id)
            await interaction.followup.send(
                f"✅ {user.mention}님에게서 {amount:,} 코인을 제거했습니다.\n"
                f"이전 잔액: {current_balance:,} 코인\n"
                f"현재 잔액: {new_balance:,} 코인\n"
                f"이유: {reason}",
            )
            self.logger.info(
                f"Admin {interaction.user.id} removed {amount} coins from user {user.id} in guild {guild_id}: {reason}",
                extra={'guild_id': guild_id})
        else:
            await interaction.followup.send(f"❌ 코인 제거에 실패했습니다. (현재 잔액: {current_balance:,} 코인)", ephemeral=True)

    @app_commands.command(name="코인설정값", description="사용자의 코인을 특정 값으로 설정합니다. (관리자 전용)")
    @app_commands.describe(
        user="코인을 설정할 사용자",
        amount="설정할 코인 수량",
        reason="설정 이유 (선택사항)"
    )
    async def admin_set_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                              reason: str = "Admin set"):
        guild_id = interaction.guild.id

        # Check if casino games are enabled
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 코인 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        # Check admin permissions
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        if amount < 0:
            await interaction.response.send_message("❌ 코인 수량은 0 이상이어야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Get current balance
            current_balance = await self.get_user_coins(user.id, guild_id)

            # Update user coins directly
            await self.bot.pool.execute("""
                INSERT INTO user_coins (user_id, guild_id, coins)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, guild_id) 
                DO UPDATE SET coins = EXCLUDED.coins
            """, user.id, guild_id, amount)

            # Log transaction
            difference = amount - current_balance
            await self.bot.pool.execute("""
                INSERT INTO coin_transactions (user_id, guild_id, amount, transaction_type, description)
                VALUES ($1, $2, $3, $4, $5)
            """, user.id, guild_id, difference, "admin_set", f"Admin set by {interaction.user.display_name}: {reason}")

            # Trigger leaderboard update
            self.bot.loop.create_task(self.schedule_leaderboard_update(guild_id))

            await interaction.followup.send(
                f"✅ {user.mention}님의 코인을 {amount:,} 코인으로 설정했습니다.\n"
                f"이전 잔액: {current_balance:,} 코인\n"
                f"현재 잔액: {amount:,} 코인\n"
                f"이유: {reason}",
                ephemeral=True
            )
            self.logger.info(
                f"Admin {interaction.user.id} set user {user.id} coins to {amount} in guild {guild_id}: {reason}",
                extra={'guild_id': guild_id})

        except Exception as e:
            await interaction.followup.send(f"❌ 코인 설정 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"Error in admin_set_coins for user {user.id} in guild {guild_id}: {e}",
                              extra={'guild_id': guild_id})
    @app_commands.command(name="코인거래내역", description="사용자의 코인 거래 내역을 확인합니다.")
    async def view_transactions(self, interaction: discord.Interaction, user: discord.Member = None):
        guild_id = interaction.guild.id

        # Check if casino games are enabled
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "❌ 이 서버에서는 코인 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        if not self.check_spam_protection(interaction.user.id):
            await interaction.response.send_message("⏳ 잠시만 기다려주세요!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        target_user = user or interaction.user

        try:
            query = """
                SELECT amount, transaction_type, description, created_at 
                FROM coin_transactions 
                WHERE user_id = $1 AND guild_id = $2 
                ORDER BY created_at DESC 
                LIMIT 20
            """
            transactions = await self.bot.pool.fetch(query, target_user.id, guild_id)

            if not transactions:
                await interaction.followup.send("📜 해당 사용자의 코인 거래 내역이 없습니다.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"📜 {target_user.display_name}님의 코인 거래 내역",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            transaction_details = []
            for tx in transactions:
                created_at_est = tx['created_at'].astimezone(pytz.timezone('America/New_York'))
                date_str = created_at_est.strftime("%Y-%m-%d %H:%M:%S EST")
                transaction_details.append(
                    f"**[{date_str}]**\n"
                    f"  유형: `{tx['transaction_type']}`\n"
                    f"  금액: `{tx['amount']:,} 코인`\n"
                    f"  설명: {tx['description'] or 'N/A'}\n"
                )

            embed.description = "\n".join(transaction_details)
            embed.set_footer(text=f"최신 20건의 거래 내역")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 오류가 발생했습니다: {e}", ephemeral=True)
            # FIX: Add guild_id to log message
            self.logger.error(f"Error in view_transactions for user {target_user.id} in guild {guild_id}: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="코인설정", description="서버의 코인 관련 설정을 변경합니다. (관리자 전용)")
    @app_commands.describe(
        feature_enabled="카지노 게임 기능 활성화/비활성화",
        starting_coins="일일 코인 지급 시 기본 코인 수량",
        leaderboard_channel="리더보드가 표시될 채널",
        admin_role="코인 관련 관리자 권한을 가질 역할",
        staff_role="코인 관련 스태프 권한을 가질 역할"
    )
    @app_commands.default_permissions(administrator=True)
    async def configure_coins(self, interaction: discord.Interaction,
                              feature_enabled: Optional[bool] = None,
                              starting_coins: Optional[int] = None,
                              leaderboard_channel: Optional[discord.TextChannel] = None,
                              admin_role: Optional[discord.Role] = None,
                              staff_role: Optional[discord.Role] = None):

        guild_id = interaction.guild.id
        await interaction.response.defer(ephemeral=True)

        # Get current settings
        current_config = config.get_server_config(guild_id)
        features = current_config.get('features', {})
        channels = current_config.get('channels', {})
        roles = current_config.get('roles', {})

        updated = False

        # Update feature setting
        if feature_enabled is not None:
            features['casino_games'] = feature_enabled
            updated = True
            # FIX: Add guild_id to log message
            self.logger.info(f"Casino games feature {'enabled' if feature_enabled else 'disabled'} for guild {guild_id}", extra={'guild_id': guild_id})

        # Update starting coins
        if starting_coins is not None:
            if starting_coins < 0:
                await interaction.followup.send("❌ 시작 코인 수량은 0 이상이어야 합니다.")
                return
            current_config['settings'] = current_config.get('settings', {})
            current_config['settings']['starting_coins'] = starting_coins
            updated = True
            # FIX: Add guild_id to log message
            self.logger.info(f"Starting coins set to {starting_coins} for guild {guild_id}", extra={'guild_id': guild_id})

        # Update leaderboard channel
        if leaderboard_channel is not None:
            channels['leaderboard_channel'] = {'id': leaderboard_channel.id, 'name': leaderboard_channel.name}
            updated = True
            # FIX: Add guild_id to log message
            self.logger.info(f"Leaderboard channel set to #{leaderboard_channel.name} ({leaderboard_channel.id}) for guild {guild_id}", extra={'guild_id': guild_id})

        # Update admin role
        if admin_role is not None:
            roles['admin_role'] = {'id': admin_role.id, 'name': admin_role.name}
            updated = True
            # FIX: Add guild_id to log message
            self.logger.info(f"Admin role set to @{admin_role.name} ({admin_role.id}) for guild {guild_id}", extra={'guild_id': guild_id})

        # Update staff role
        if staff_role is not None:
            roles['staff_role'] = {'id': staff_role.id, 'name': staff_role.name}
            updated = True
            # FIX: Add guild_id to log message
            self.logger.info(f"Staff role set to @{staff_role.name} ({staff_role.id}) for guild {guild_id}", extra={'guild_id': guild_id})

        if updated:
            current_config['features'] = features
            current_config['channels'] = channels
            current_config['roles'] = roles
            config.save_server_config(guild_id, current_config)
            await interaction.followup.send("✅ 코인 시스템 설정이 성공적으로 업데이트되었습니다.")

            # If casino feature was enabled/disabled or leaderboard channel changed, re-setup
            if (feature_enabled is not None and feature_enabled) or (leaderboard_channel is not None):
                await self.setup_initial_leaderboard(guild_id)
        else:
            await interaction.followup.send("ℹ️ 변경 사항이 없어 설정을 업데이트하지 않았습니다.")

    async def check_user_loan_restrictions(self, user_id: int, guild_id: int) -> dict:
        """
        Check if user has loan restrictions that prevent them from receiving coins or gambling.
        Returns a dict with restriction info.
        """
        try:
            # Check for overdue loans
            current_time = datetime.now(timezone.utc)

            overdue_loan_query = """
                SELECT loan_id, remaining_amount, due_date 
                FROM user_loans 
                WHERE user_id = $1 AND guild_id = $2 
                AND status IN ('active', 'defaulted') 
                AND due_date < $3
                ORDER BY due_date ASC
                LIMIT 1
            """

            overdue_loan = await self.bot.pool.fetchrow(overdue_loan_query, user_id, guild_id, current_time)

            if overdue_loan:
                return {
                    'restricted': True,
                    'reason': 'overdue_loan',
                    'loan_id': overdue_loan['loan_id'],
                    'remaining_amount': overdue_loan['remaining_amount'],
                    'due_date': overdue_loan['due_date']
                }

            return {'restricted': False}

        except Exception as e:
            self.logger.error(f"Error checking loan restrictions for user {user_id} in guild {guild_id}: {e}",
                              extra={'guild_id': guild_id})
            # In case of error, allow the operation (fail open)
            return {'restricted': False}

    async def check_casino_restrictions(self, user_id: int, guild_id: int) -> dict:
        """
        Check if user can participate in casino games based on loan status.
        This would be called by any casino game cogs before allowing gameplay.
        """
        try:
            restrictions = await self.check_user_loan_restrictions(user_id, guild_id)

            if restrictions['restricted'] and restrictions['reason'] == 'overdue_loan':
                return {
                    'allowed': False,
                    'reason': 'overdue_loan',
                    'message': f"⛔ 연체된 대출이 있어 카지노 게임에 참여할 수 없습니다.\n"
                               f"남은 대출금: {restrictions['remaining_amount']:,} 코인\n"
                               f"대출금을 완전히 상환한 후 다시 시도해주세요.",
                    'remaining_amount': restrictions['remaining_amount']
                }

            return {'allowed': True}

        except Exception as e:
            self.logger.error(f"Error checking casino restrictions for user {user_id}: {e}",
                              extra={'guild_id': guild_id})
            # In case of error, allow the operation (fail open)
            return {'allowed': True}


def get_coins_cog_from_bot(bot):
    """Helper function for other cogs to get the CoinsCog instance"""
    return bot.get_cog('CoinsCog')


async def check_user_casino_eligibility(bot, user_id: int, guild_id: int) -> dict:
    """
    Utility function that other cogs can import to check if a user can gamble.
    Returns dict with 'allowed' boolean and 'message' string.
    """
    coins_cog = get_coins_cog_from_bot(bot)
    if not coins_cog:
        return {'allowed': True}  # If coins cog not available, don't restrict

    return await coins_cog.check_casino_restrictions(user_id, guild_id)
async def setup(bot):
    await bot.add_cog(CoinsCog(bot))