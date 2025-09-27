# cogs/shop_system.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import json
import os

from utils.logger import get_logger
from utils import config


class ShopView(discord.ui.View):
    """Persistent view for the shop system"""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = get_logger("상점 시스템")
        self.shop_items = self.get_shop_items()

    def get_shop_items(self) -> Dict:
        """Define shop items and their properties"""
        return {
            "xp_boost_3h": {
                "name": "2배 경험치 부스터 (3시간)",
                "description": "3시간 동안 보이스 채팅에서 2배 경험치를 획득합니다.",
                "price": 1000,
                "emoji": "🚀",
                "duration_hours": 3,
                "role_id": 1421264239900889118
            },
            "xp_boost_6h": {
                "name": "2배 경험치 부스터 (6시간)",
                "description": "6시간 동안 보이스 채팅에서 2배 경험치를 획득합니다.",
                "price": 1800,
                "emoji": "⚡",
                "duration_hours": 6,
                "role_id": 1421264239900889118
            },
            "xp_boost_12h": {
                "name": "2배 경험치 부스터 (12시간)",
                "description": "12시간 동안 보이스 채팅에서 2배 경험치를 획득합니다.",
                "price": 3200,
                "emoji": "🔥",
                "duration_hours": 12,
                "role_id": 1421264239900889118
            }
        }

    def create_shop_embed(self) -> discord.Embed:
        """Create the main shop embed"""
        embed = discord.Embed(
            title="🛒 코인 상점",
            description="코인을 사용해서 다양한 아이템을 구매하세요!",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        # XP Boosters section
        booster_text = ""
        for item_id, item in self.shop_items.items():
            booster_text += f"{item['emoji']} **{item['name']}**\n"
            booster_text += f"{item['description']}\n💰 **가격:** {item['price']:,} 코인\n\n"

        embed.add_field(
            name="🚀 경험치 부스터",
            value=booster_text,
            inline=False
        )

        # Item Gacha section
        embed.add_field(
            name="🎁 아이템 뽑기",
            value=(
                "🎰 **랜덤 아이템 뽑기**\n"
                "200 코인으로 랜덤 장비를 획득하세요!\n"
                "모든 등급의 아이템이 나올 수 있습니다.\n"
                "💰 **가격:** 200 코인\n\n"
                "📊 **확률:**\n"
                "일반 45% | 고급 30% | 희귀 15%\n"
                "영웅 7% | 고유 2.5% | 전설 0.4% | 신화 0.1%"
            ),
            inline=False
        )

        embed.set_footer(text="아래 버튼을 클릭하여 아이템을 구매하세요!")
        return embed

    @discord.ui.button(label="🚀 3시간 부스터", style=discord.ButtonStyle.green, custom_id="buy_xp_boost_3h", row=0)
    async def buy_3h_booster(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_purchase(interaction, "xp_boost_3h")

    @discord.ui.button(label="⚡ 6시간 부스터", style=discord.ButtonStyle.green, custom_id="buy_xp_boost_6h", row=0)
    async def buy_6h_booster(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_purchase(interaction, "xp_boost_6h")

    @discord.ui.button(label="🔥 12시간 부스터", style=discord.ButtonStyle.green, custom_id="buy_xp_boost_12h", row=0)
    async def buy_12h_booster(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_purchase(interaction, "xp_boost_12h")

    @discord.ui.button(label="🎁 아이템 뽑기 (200코인)", style=discord.ButtonStyle.primary, custom_id="item_gacha_pull", row=1)
    async def pull_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_item_gacha(interaction)

    async def handle_purchase(self, interaction: discord.Interaction, item_id: str):
        """Handle item purchase"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id
        item = self.shop_items.get(item_id)

        if not item:
            await interaction.followup.send("❌ 잘못된 아이템입니다.", ephemeral=True)
            return

        try:
            # Check if user already has the boost active
            role = interaction.guild.get_role(item['role_id'])
            if role and role in interaction.user.roles:
                await interaction.followup.send(
                    f"❌ 이미 {item['name']}이 활성화되어 있습니다!\n"
                    f"현재 부스터가 만료된 후에 다시 구매해주세요.",
                    ephemeral=True
                )
                return

            # Get coins cog to check balance and deduct coins
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                await interaction.followup.send("❌ 코인 시스템을 사용할 수 없습니다.", ephemeral=True)
                return

            # Check user's coin balance
            current_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if current_coins < item['price']:
                await interaction.followup.send(
                    f"❌ 코인이 부족합니다!\n"
                    f"필요한 코인: {item['price']:,}\n"
                    f"현재 코인: {current_coins:,}\n"
                    f"부족한 코인: {item['price'] - current_coins:,}",
                    ephemeral=True
                )
                return

            # Deduct coins
            success = await coins_cog.remove_coins(
                user_id, guild_id, item['price'],
                "shop_purchase", f"구매: {item['name']}"
            )

            if not success:
                await interaction.followup.send("❌ 결제 처리 중 오류가 발생했습니다.", ephemeral=True)
                return

            # Give the user the boost role
            if role:
                await interaction.user.add_roles(role, reason=f"상점에서 {item['name']} 구매")

            # Record the purchase in database
            shop_cog = self.bot.get_cog('ShopSystemCog')
            if shop_cog:
                await shop_cog.record_purchase(user_id, guild_id, item_id, item['duration_hours'])

            # Update XP boost tracking if XP cog is available
            xp_cog = self.bot.get_cog('XPSystemCog')
            if xp_cog:
                xp_cog.xp_boost_users.add(user_id)

            # Send success message
            embed = discord.Embed(
                title="✅ 구매 성공!",
                description=f"{item['emoji']} **{item['name']}**을(를) 구매했습니다!",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )

            embed.add_field(name="💰 소모된 코인", value=f"{item['price']:,} 코인", inline=True)
            embed.add_field(name="💳 남은 코인", value=f"{current_coins - item['price']:,} 코인", inline=True)
            embed.add_field(name="⏰ 지속 시간", value=f"{item['duration_hours']}시간", inline=True)

            expiry_time = datetime.now(timezone.utc) + timedelta(hours=item['duration_hours'])
            embed.add_field(
                name="⏳ 만료 시각",
                value=discord.utils.format_dt(expiry_time, 'F'),
                inline=False
            )

            embed.set_footer(text="부스터가 활성화되었습니다! 보이스 채팅에서 2배 경험치를 획득하세요!")

            await interaction.followup.send(embed=embed, ephemeral=True)

            self.logger.info(
                f"User {user_id} purchased {item_id} for {item['price']} coins in guild {guild_id}",
                extra={'guild_id': guild_id}
            )

        except Exception as e:
            self.logger.error(f"Error handling purchase for user {user_id}: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 구매 처리 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def handle_item_gacha(self, interaction: discord.Interaction):
        """Handle item gacha pull"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id
        price = 200

        try:
            # Check if enhancement system is available
            enhancement_cog = self.bot.get_cog('EnhancementCog')
            if not enhancement_cog:
                await interaction.followup.send("❌ 강화 시스템을 사용할 수 없습니다.", ephemeral=True)
                return

            # Check if user has a character
            character_data = await enhancement_cog.get_user_character(user_id, guild_id)
            if not character_data:
                await interaction.followup.send(
                    "❌ 먼저 `/직업선택` 명령어로 캐릭터를 생성해주세요!",
                    ephemeral=True
                )
                return

            # Check coins
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                await interaction.followup.send("❌ 코인 시스템을 사용할 수 없습니다.", ephemeral=True)
                return

            current_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if current_coins < price:
                await interaction.followup.send(
                    f"❌ 코인이 부족합니다!\n필요 코인: {price:,}\n보유 코인: {current_coins:,}",
                    ephemeral=True
                )
                return

            # Deduct coins
            if not await coins_cog.remove_coins(user_id, guild_id, price, "item_gacha", "아이템 뽑기"):
                await interaction.followup.send("❌ 코인 차감 중 오류가 발생했습니다.", ephemeral=True)
                return

            # Get random item
            item_data = enhancement_cog.get_random_item()
            item_id = await enhancement_cog.create_item_in_db(user_id, guild_id, item_data)

            if not item_id:
                # Refund coins if item creation failed
                await coins_cog.add_coins(user_id, guild_id, price, "gacha_refund", "아이템 뽑기 실패 환불")
                await interaction.followup.send("❌ 아이템 생성 중 오류가 발생했습니다. 코인이 환불되었습니다.", ephemeral=True)
                return

            # Create result embed
            rarity_info = enhancement_cog.item_rarities[item_data['rarity']]
            embed = discord.Embed(
                title="🎁 아이템 획득!",
                color=rarity_info['color'],
                timestamp=datetime.now(timezone.utc)
            )

            # Add sparkle effect for higher rarities
            sparkle = ""
            if item_data['rarity'] in ['전설', '신화']:
                sparkle = "✨ "
            elif item_data['rarity'] in ['고유', '영웅']:
                sparkle = "⭐ "

            item_display = f"{sparkle}{item_data['emoji']} **{item_data['name']}**"
            embed.add_field(name="획득 아이템", value=item_display, inline=False)
            embed.add_field(name="등급", value=f"{rarity_info['name']}", inline=True)
            embed.add_field(name="종류", value=f"{item_data['slot_type']}", inline=True)
            embed.add_field(name="아이템 ID", value=f"`{item_id}`", inline=True)

            # Show base stats
            stats_text = ""
            for stat, value in item_data['base_stats'].items():
                if value > 0:
                    stats_text += f"{stat.upper()}: +{value} "

            if stats_text:
                embed.add_field(name="기본 능력치", value=stats_text.strip(), inline=False)

            # Show class requirement if any
            if item_data.get('class_req'):
                embed.add_field(name="직업 제한", value=item_data['class_req'], inline=True)

            embed.add_field(name="💰 소모 코인", value=f"{price} 코인", inline=True)
            embed.add_field(name="💳 남은 코인", value=f"{current_coins - price:,} 코인", inline=True)

            embed.set_footer(text="인벤토리에서 아이템을 확인하고 장비해보세요!")

            await interaction.followup.send(embed=embed, ephemeral=True)

            self.logger.info(
                f"사용자 {user_id}가 아이템 뽑기로 {item_data['name']}({item_data['rarity']})을 획득했습니다.",
                extra={'guild_id': guild_id}
            )

        except Exception as e:
            self.logger.error(f"아이템 뽑기 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 아이템 뽑기 중 오류가 발생했습니다: {e}", ephemeral=True)


class ShopSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("상점 시스템")

        # Shop message management
        self.shop_message_id = None
        self.shop_channel_id = 1421265263944536195  # Hardcoded as requested

        # Active purchases tracking
        self.active_purchases = {}  # user_id: expiry_time

        self.logger.info("상점 시스템이 초기화되었습니다.")

    async def setup_database(self):
        """Create necessary database tables for shop system"""
        try:
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS shop_purchases (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    item_id VARCHAR(50) NOT NULL,
                    price INTEGER NOT NULL,
                    duration_hours INTEGER,
                    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    status VARCHAR(20) DEFAULT 'active'
                )
            """)

            # Create index for faster queries
            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_shop_purchases_user_status 
                ON shop_purchases(user_id, status, expires_at);
            """)

            self.logger.info("상점 데이터베이스 테이블이 준비되었습니다.")
        except Exception as e:
            self.logger.error(f"상점 데이터베이스 설정 실패: {e}", exc_info=True)

    async def record_purchase(self, user_id: int, guild_id: int, item_id: str, duration_hours: int):
        """Record a purchase in the database"""
        try:
            shop_view = ShopView(self.bot)
            item = shop_view.shop_items.get(item_id)
            if not item:
                return

            expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)

            await self.bot.pool.execute("""
                INSERT INTO shop_purchases (user_id, guild_id, item_id, price, duration_hours, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, user_id, guild_id, item_id, item['price'], duration_hours, expires_at)

            # Track active purchase
            self.active_purchases[user_id] = expires_at

            self.logger.info(f"Recorded purchase: {item_id} for user {user_id}", extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error(f"Error recording purchase: {e}", extra={'guild_id': guild_id})

    async def setup_shop_message(self, force_new=False):
        """Setup the persistent shop message"""
        try:
            channel = self.bot.get_channel(self.shop_channel_id)
            if not channel:
                self.logger.error(f"Shop channel {self.shop_channel_id} not found")
                return

            shop_view = ShopView(self.bot)
            embed = shop_view.create_shop_embed()

            # If force_new is True (like during reload), delete old messages first
            if force_new:
                await self.delete_old_shop_messages()
                self.shop_message_id = None
                await asyncio.sleep(1)  # Wait for deletions

            # Only search for existing message if not forcing new
            if not force_new:
                # Try to find existing shop message
                async for message in channel.history(limit=50):
                    if (message.author == self.bot.user and
                            message.embeds and
                            message.embeds[0].title and
                            "상점" in message.embeds[0].title):
                        try:
                            await message.edit(embed=embed, view=shop_view)
                            self.shop_message_id = message.id
                            self.logger.info("Updated existing shop message")
                            return
                        except discord.HTTPException:
                            continue

            # Create new shop message
            message = await channel.send(embed=embed, view=shop_view)
            self.shop_message_id = message.id
            self.logger.info("Created new shop message")

        except Exception as e:
            self.logger.error(f"Error setting up shop message: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Setup when bot is ready"""
        await self.setup_database()

        # Setup shop message with cleanup (force new message)
        await self.setup_shop_message(force_new=True)

        # Load active purchases
        await self.load_active_purchases()

        # Start expiry check task
        if not self.check_expired_purchases.is_running():
            self.check_expired_purchases.start()

        self.logger.info("Shop system reloaded - cleaned up old messages and created fresh shop interface")

    async def load_active_purchases(self):
        """Load active purchases from database"""
        try:
            query = """
                SELECT user_id, expires_at
                FROM shop_purchases
                WHERE status = 'active' AND expires_at > CURRENT_TIMESTAMP
            """
            records = await self.bot.pool.fetch(query)

            for record in records:
                self.active_purchases[record['user_id']] = record['expires_at']

                # Update XP boost tracking
                xp_cog = self.bot.get_cog('XPSystemCog')
                if xp_cog:
                    xp_cog.xp_boost_users.add(record['user_id'])

            self.logger.info(f"Loaded {len(records)} active purchases")

        except Exception as e:
            self.logger.error(f"Error loading active purchases: {e}")

    @tasks.loop(minutes=5)
    async def check_expired_purchases(self):
        """Check for expired purchases and remove boosts"""
        try:
            current_time = datetime.now(timezone.utc)
            expired_users = []

            for user_id, expiry_time in list(self.active_purchases.items()):
                if current_time >= expiry_time:
                    expired_users.append(user_id)
                    del self.active_purchases[user_id]

            if expired_users:
                # Update database
                await self.bot.pool.execute("""
                    UPDATE shop_purchases 
                    SET status = 'expired'
                    WHERE user_id = ANY($1) AND status = 'active' AND expires_at <= $2
                """, expired_users, current_time)

                # Remove roles and update XP tracking
                xp_boost_role_id = 1421264239900889118
                xp_cog = self.bot.get_cog('XPSystemCog')

                for guild in self.bot.guilds:
                    role = guild.get_role(xp_boost_role_id)
                    if not role:
                        continue

                    for user_id in expired_users:
                        member = guild.get_member(user_id)
                        if member and role in member.roles:
                            try:
                                await member.remove_roles(role, reason="부스터 만료")

                                # Send DM notification
                                try:
                                    embed = discord.Embed(
                                        title="⏰ 부스터 만료",
                                        description="2배 경험치 부스터가 만료되었습니다.",
                                        color=discord.Color.orange()
                                    )
                                    embed.add_field(
                                        name="🛒 다시 구매하기",
                                        value=f"<#{self.shop_channel_id}>에서 새로운 부스터를 구매하세요!",
                                        inline=False
                                    )
                                    await member.send(embed=embed)
                                except discord.Forbidden:
                                    pass  # Can't send DM

                            except discord.Forbidden:
                                pass  # Can't modify roles

                        # Remove from XP boost tracking
                        if xp_cog and user_id in xp_cog.xp_boost_users:
                            xp_cog.xp_boost_users.remove(user_id)

                self.logger.info(f"Processed {len(expired_users)} expired purchases")

        except Exception as e:
            self.logger.error(f"Error checking expired purchases: {e}")

    @app_commands.command(name="내구매내역", description="자신의 상점 구매 내역을 확인합니다.")
    async def my_purchases(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            query = """
                SELECT item_id, price, purchased_at, expires_at, status
                FROM shop_purchases
                WHERE user_id = $1 AND guild_id = $2
                ORDER BY purchased_at DESC
                LIMIT 10
            """
            records = await self.bot.pool.fetch(query, user_id, guild_id)

            if not records:
                await interaction.followup.send("📦 구매 내역이 없습니다.", ephemeral=True)
                return

            embed = discord.Embed(
                title="📦 나의 구매 내역",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            shop_view = ShopView(self.bot)

            purchase_text = ""
            for record in records[:5]:  # Show last 5 purchases
                item = shop_view.shop_items.get(record['item_id'])
                if not item:
                    continue

                status_emoji = "✅" if record['status'] == 'active' else "⏰"
                purchased_date = record['purchased_at'].strftime("%Y-%m-%d %H:%M")

                purchase_text += f"{status_emoji} **{item['name']}**\n"
                purchase_text += f"   💰 {record['price']:,} 코인 | {purchased_date}\n"

                if record['status'] == 'active' and record['expires_at']:
                    purchase_text += f"   ⏳ 만료: {discord.utils.format_dt(record['expires_at'], 'R')}\n"

                purchase_text += "\n"

            embed.description = purchase_text or "구매 내역이 없습니다."

            # Show active boosts
            active_count = sum(1 for r in records if r['status'] == 'active')
            if active_count > 0:
                embed.add_field(
                    name="🚀 활성화된 부스터",
                    value=f"{active_count}개의 부스터가 활성화되어 있습니다.",
                    inline=True
                )

            embed.set_footer(text=f"최근 {len(records)}개 구매 내역")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 구매 내역 조회 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"Error in my_purchases command: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="부스터상태", description="현재 활성화된 부스터 상태를 확인합니다.")
    async def booster_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            # Check if user has active boost
            xp_boost_role_id = 1421264239900889118
            role = interaction.guild.get_role(xp_boost_role_id)
            has_boost = role and role in interaction.user.roles

            if not has_boost:
                embed = discord.Embed(
                    title="🚫 활성화된 부스터 없음",
                    description="현재 활성화된 경험치 부스터가 없습니다.",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="🛒 부스터 구매하기",
                    value=f"<#{self.shop_channel_id}>에서 경험치 부스터를 구매하세요!",
                    inline=False
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Get active purchase info
            query = """
                SELECT item_id, expires_at, purchased_at
                FROM shop_purchases
                WHERE user_id = $1 AND guild_id = $2 AND status = 'active'
                ORDER BY expires_at DESC
                LIMIT 1
            """
            record = await self.bot.pool.fetchrow(query, user_id, guild_id)

            if not record:
                embed = discord.Embed(
                    title="⚠️ 부스터 정보 없음",
                    description="부스터 역할은 있지만 구매 정보를 찾을 수 없습니다.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            shop_view = ShopView(self.bot)
            item = shop_view.shop_items.get(record['item_id'])

            embed = discord.Embed(
                title="🚀 부스터 활성화됨!",
                description="2배 경험치 부스터가 활성화되어 있습니다!",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )

            if item:
                embed.add_field(name="📦 부스터 종류", value=item['name'], inline=True)

            embed.add_field(
                name="🕑 구매 시각",
                value=discord.utils.format_dt(record['purchased_at'], 'F'),
                inline=True
            )

            if record['expires_at']:
                embed.add_field(
                    name="⏰ 만료 시각",
                    value=discord.utils.format_dt(record['expires_at'], 'F'),
                    inline=False
                )

                embed.add_field(
                    name="⏳ 남은 시간",
                    value=discord.utils.format_dt(record['expires_at'], 'R'),
                    inline=True
                )

            embed.set_footer(text="보이스 채팅에 참여하여 2배 경험치를 획득하세요!")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 부스터 상태 확인 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"Error in booster_status command: {e}", extra={'guild_id': guild_id})

    async def delete_old_shop_messages(self):
        """Delete old shop messages from the channel"""
        try:
            channel = self.bot.get_channel(self.shop_channel_id)
            if not channel:
                self.logger.error(f"Shop channel {self.shop_channel_id} not found")
                return False

            deleted_count = 0
            async for message in channel.history(limit=50):
                if (message.author == self.bot.user and
                        message.embeds and
                        message.embeds[0].title and
                        "상점" in message.embeds[0].title):
                    try:
                        await message.delete()
                        deleted_count += 1
                        await asyncio.sleep(0.5)  # Rate limit protection
                    except discord.NotFound:
                        pass  # Message already deleted
                    except discord.Forbidden:
                        self.logger.warning(f"No permission to delete message in shop channel {self.shop_channel_id}")
                        break

            self.logger.info(f"Deleted {deleted_count} old shop messages")
            return True

        except Exception as e:
            self.logger.error(f"Error deleting old shop messages: {e}")
            return False

async def setup(bot):
    await bot.add_cog(ShopSystemCog(bot))