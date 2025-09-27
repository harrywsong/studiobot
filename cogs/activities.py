# cogs/activities.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
import json
import os
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
import uuid
import math

from utils.logger import get_logger
from utils import config

# Channel IDs for different activities
ADVENTURE_CHANNEL_ID = 1421505588088537303  # Replace with actual channel ID
ARENA_CHANNEL_ID = 1421505650202116186  # Replace with actual channel ID
DUNGEON_CHANNEL_ID = 1421505682250666034  # Replace with actual channel ID
GUILD_CHANNEL_ID = 1421505709509443759  # Replace with actual channel ID


def ensure_timezone_aware(dt):
    """Ensure datetime object is timezone-aware (UTC)"""
    if dt is None:
        return None

    # If it's already timezone-aware, return as-is
    if dt.tzinfo is not None:
        return dt

    # If it's naive, assume it's UTC and make it aware
    return dt.replace(tzinfo=timezone.utc)


class AdventureView(discord.ui.View):
    """Adventure selection and management view"""

    def __init__(self, bot, user_id, guild_id, adventures_data):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.adventures_data = adventures_data
        self.activities_cog = bot.get_cog('ActivitiesCog')

        # Add adventure buttons
        for i, adventure in enumerate(adventures_data[:4]):  # Max 4 adventures per row
            button = discord.ui.Button(
                label=f"{adventure['emoji']} {adventure['name']}",
                style=discord.ButtonStyle.primary if adventure['recommended'] else discord.ButtonStyle.secondary,
                custom_id=f"adventure_{adventure['id']}",
                row=i // 2
            )
            button.callback = self.create_adventure_callback(adventure['id'])
            self.add_item(button)

    def create_adventure_callback(self, adventure_id: str):
        async def adventure_callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("다른 사용자의 모험을 시작할 수 없습니다.", ephemeral=True)
                return
            try:
                await self.activities_cog.start_adventure(interaction, adventure_id)
            except Exception as e:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"모험 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"모험 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

        return adventure_callback


class ArenaView(discord.ui.View):
    """Arena battle interface"""

    def __init__(self, bot, user_id, guild_id, arena_data):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.arena_data = arena_data
        self.activities_cog = bot.get_cog('ActivitiesCog')

    @discord.ui.button(label="⚔️ 랭크전 참여", style=discord.ButtonStyle.danger)
    async def ranked_battle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아레나에 참여할 수 없습니다.", ephemeral=True)
            return
        try:
            await self.activities_cog.start_ranked_battle(interaction)
        except Exception as e:
            self.activities_cog.logger.error(f"Ranked battle error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"랭크전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"랭크전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    @discord.ui.button(label="🎯 연습전", style=discord.ButtonStyle.secondary)
    async def practice_battle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아레나에 참여할 수 없습니다.", ephemeral=True)
            return
        try:
            await self.activities_cog.start_practice_battle(interaction)
        except Exception as e:
            self.activities_cog.logger.error(f"Practice battle error: {e}")
            if not interaction.response.send_message.is_done():
                await interaction.response.send_message(f"연습전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"연습전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    @discord.ui.button(label="🏆 아레나 랭킹", style=discord.ButtonStyle.primary)
    async def arena_rankings(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.activities_cog.show_arena_rankings(interaction)
        except Exception as e:
            self.activities_cog.logger.error(f"Arena rankings error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"랭킹 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"랭킹 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)


# cogs/activities.py
# ... (기존 import)
# ... (기존 AdventureView 클래스)

# 아레나 PvP 도전 수락/거절 뷰
class ArenaChallengeView(discord.ui.View):
    def __init__(self, challenger_id: int, target_id: int, cog_instance: Any, *args, **kwargs):
        """
        :param challenger_id: 도전을 건 사용자 ID
        :param target_id: 도전을 받은 사용자 ID
        :param cog_instance: Activities Cog 인스턴스 (매치 시작 로직 호출용)
        """
        super().__init__(*args, **kwargs, timeout=300)  # 5분 타임아웃
        self.challenger_id = challenger_id
        self.target_id = target_id
        self.cog = cog_instance

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 오직 도전을 받은 사용자(target)만 버튼을 클릭할 수 있도록 합니다.
        if interaction.user.id != self.target_id:
            await interaction.response.send_message(
                f"⚠️ 이 도전은 <@{self.target_id}>님을 위한 것입니다. 당신은 응답할 수 없습니다.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="수락", style=discord.ButtonStyle.green)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=f"**✅ 도전 수락!** 아레나 매치를 시작합니다...", view=self)
        self.stop()

        # handle wager if present
        wager = getattr(self, "wager", None)
        if wager:
            coins_cog = self.cog.bot.get_cog('CoinsCog')
            if coins_cog:
                # withdraw from both players; handle insufficient balance, refunds, etc.
                await coins_cog.remove_coins(self.challenger_id, interaction.guild.id, wager, "arena_wager",
                                             f"아레나 내기 vs {self.target_id}")
                await coins_cog.remove_coins(self.target_id, interaction.guild.id, wager, "arena_wager",
                                             f"아레나 내기 vs {self.challenger_id}")

        await self.cog.start_arena_match(self.challenger_id, self.target_id, interaction.channel, wager=wager)

    @discord.ui.button(label="거절", style=discord.ButtonStyle.red)
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(content=f"**❌ 도전 거절.** <@{self.target_id}>님이 도전을 거절했습니다.", view=self)
        self.stop()

        # 도전 상태 정리
        if self.target_id in self.cog.active_challenges:
            del self.cog.active_challenges[self.target_id]
class DungeonView(discord.ui.View):
    """Dungeon exploration interface"""

    def __init__(self, bot, user_id, guild_id, dungeons_data):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.dungeons_data = dungeons_data
        self.activities_cog = bot.get_cog('ActivitiesCog')

        # Add dungeon buttons
        for i, dungeon in enumerate(dungeons_data[:4]):
            difficulty_colors = {
                "쉬움": discord.ButtonStyle.success,
                "보통": discord.ButtonStyle.primary,
                "어려움": discord.ButtonStyle.danger,
                "지옥": discord.ButtonStyle.secondary
            }

            button = discord.ui.Button(
                label=f"{dungeon['emoji']} {dungeon['name']} ({dungeon['difficulty']})",
                style=difficulty_colors.get(dungeon['difficulty'], discord.ButtonStyle.secondary),
                custom_id=f"dungeon_{dungeon['id']}",
                row=i // 2
            )
            button.callback = self.create_dungeon_callback(dungeon['id'])
            self.add_item(button)

    def create_dungeon_callback(self, dungeon_id: str):
        async def dungeon_callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("다른 사용자의 던전에 참여할 수 없습니다.", ephemeral=True)
                return
            try:
                await self.activities_cog.start_dungeon(interaction, dungeon_id)
            except Exception as e:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"던전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"던전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

        return dungeon_callback

class GuildRaidView(discord.ui.View):
    """Guild raid interface for future implementation"""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.activities_cog = bot.get_cog('ActivitiesCog')

    @discord.ui.button(label="⚔️ 길드 레이드 참여", style=discord.ButtonStyle.danger, disabled=True)
    async def join_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("길드 레이드는 곧 추가될 예정입니다!", ephemeral=True)

    @discord.ui.button(label="🏆 레이드 기록", style=discord.ButtonStyle.secondary, disabled=True)
    async def raid_records(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("길드 레이드는 곧 추가될 예정입니다!", ephemeral=True)


class ActivitiesCog(commands.Cog):
    """Adventure, Arena, Dungeon, and Party system with balanced economy"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger(__name__)
        self.active_challenges: Dict[int, int] = {}

        # Add cleanup task
        @tasks.loop(minutes=70)
        async def cleanup_expired_challenges(self):
            """Clean up expired challenges"""
            current_time = datetime.now(timezone.utc)
            # Remove challenges older than 10 minutes
            # This would require storing timestamps with challenges

        # Adventure definitions - BALANCED REWARDS
        self.adventures = {
            "forest": {
                "id": "forest",
                "name": "신비한 숲 탐험",
                "emoji": "🌲",
                "min_power": 1000,
                "max_power": 5000,
                "duration": 300,  # 5 minutes
                "rewards": {"coins": (10, 30), "exp": (5, 15)},  # Reduced from (50, 200)
                "description": "초보자를 위한 평화로운 숲 탐험"
            },
            "cave": {
                "id": "cave",
                "name": "어둠의 동굴",
                "emoji": "🕳️",
                "min_power": 3000,
                "max_power": 10000,
                "duration": 600,  # 10 minutes
                "rewards": {"coins": (25, 60), "exp": (10, 25)},  # Reduced from (100, 400)
                "description": "위험하지만 보상이 풍부한 동굴"
            },
            "volcano": {
                "id": "volcano",
                "name": "화산 정상 도전",
                "emoji": "🌋",
                "min_power": 8000,
                "max_power": 25000,
                "duration": 900,  # 15 minutes
                "rewards": {"coins": (75, 150), "exp": (25, 50)},  # Reduced from (300, 800)
                "description": "고수만이 도전할 수 있는 화산"
            },
            "abyss": {
                "id": "abyss",
                "name": "심연의 구멍",
                "emoji": "🕳️",
                "min_power": 20000,
                "max_power": 100000,
                "duration": 1800,  # 30 minutes
                "rewards": {"coins": (200, 400), "exp": (75, 150)},  # Reduced from (1000, 3000)
                "description": "최강자만이 살아남을 수 있는 심연"
            }
        }

        # Dungeon definitions - BALANCED REWARDS AND PROPER TIMING
        self.dungeons = {
            "goblin_den": {
                "id": "goblin_den",
                "name": "고블린 소굴",
                "emoji": "👹",
                "difficulty": "쉬움",
                "min_power": 2000,
                "party_size": (1, 3),
                "duration": 600,  # 10 minutes actual time
                "rewards": {"coins": (30, 80), "items": ["common", "rare"]},  # Reduced from (200, 500)
                "description": "고블린들이 서식하는 작은 소굴"
            },
            "orc_fortress": {
                "id": "orc_fortress",
                "name": "오크 요새",
                "emoji": "🏰",
                "difficulty": "보통",
                "min_power": 8000,
                "party_size": (2, 4),
                "duration": 1200,  # 20 minutes actual time
                "rewards": {"coins": (80, 180), "items": ["rare", "epic"]},  # Reduced from (500, 1200)
                "description": "강력한 오크들의 요새"
            },
            "dragon_lair": {
                "id": "dragon_lair",
                "name": "드래곤 둥지",
                "emoji": "🐉",
                "difficulty": "어려움",
                "min_power": 25000,
                "party_size": (3, 5),
                "duration": 2400,  # 40 minutes actual time
                "rewards": {"coins": (200, 400), "items": ["epic", "legendary"]},  # Reduced from (1500, 3000)
                "description": "고대 드래곤이 잠들어 있는 둥지"
            },
            "void_temple": {
                "id": "void_temple",
                "name": "공허의 신전",
                "emoji": "⛩️",
                "difficulty": "지옥",
                "min_power": 50000,
                "party_size": (4, 5),
                "duration": 3600,  # 60 minutes actual time
                "rewards": {"coins": (400, 800), "items": ["legendary", "mythic"]},  # Reduced from (3000, 8000)
                "description": "공허의 힘이 깃든 금단의 신전"
            }
        }

        # Arena tiers
        self.arena_tiers = {
            "bronze": {"name": "브론즈", "emoji": "🥉", "min_rating": 0},
            "silver": {"name": "실버", "emoji": "🥈", "min_rating": 1200},
            "gold": {"name": "골드", "emoji": "🥇", "min_rating": 1500},
            "platinum": {"name": "플래티넘", "emoji": "💎", "min_rating": 1800},
            "diamond": {"name": "다이아몬드", "emoji": "💍", "min_rating": 2100},
            "master": {"name": "마스터", "emoji": "⭐", "min_rating": 2400},
            "grandmaster": {"name": "그랜드마스터", "emoji": "🌟", "min_rating": 2700}
        }

        # Daily limits for balanced economy
        self.daily_limits = {
            "adventure": 5,  # Max 5 adventures per day
            "dungeon": 3,  # Max 3 dungeons per day
            "arena": 15  # Max 15 arena battles per day
        }

        self.bot.loop.create_task(self.setup_activities_system())

    async def setup_activities_system(self):
        """Initialize the activities system"""
        await self.bot.wait_until_ready()
        await self.setup_activities_database()

        # Check for any adventures that should have completed while bot was offline
        await self.check_completed_adventures()

    async def _check_concurrent_activity(self, user_id: int, guild_id: int) -> Optional[str]:
        """
        Enhanced check for concurrent activities with proper guild filtering
        Returns the name of the active activity or None
        """
        try:
            # Check for active adventure with guild filter
            adventure_check = await self.bot.pool.fetchrow(
                "SELECT adventure_id FROM active_adventures WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            if adventure_check:
                return "모험"

            # Check for active dungeon with guild filter
            dungeon_check = await self.bot.pool.fetchrow(
                "SELECT dungeon_id FROM active_dungeons WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            if dungeon_check:
                return "던전"

            return None
        except Exception as e:
            self.logger.error(f"Error checking concurrent activity: {e}")
            return None
    async def setup_activities_database(self):
        """Setup database tables for activities"""
        try:
            # Adventure logs
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS adventure_logs (
                    log_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    adventure_id VARCHAR(50) NOT NULL,
                    start_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMPTZ,
                    success BOOLEAN DEFAULT FALSE,
                    rewards_coins INTEGER DEFAULT 0,
                    rewards_exp INTEGER DEFAULT 0,
                    combat_power INTEGER DEFAULT 0
                )
            """)

            # Arena stats - complete table with combat_power column
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS arena_stats (
                    user_id BIGINT,
                    guild_id BIGINT,
                    tier VARCHAR(20) DEFAULT 'bronze',
                    rating INTEGER DEFAULT 1000,
                    combat_power INTEGER DEFAULT 100,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    last_battle TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            # Dungeon progress - fix timestamp column
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS dungeon_progress (
                    user_id BIGINT,
                    guild_id BIGINT,
                    dungeon_name VARCHAR(50),
                    completions INTEGER DEFAULT 0,
                    best_time INTEGER DEFAULT 0,
                    last_attempt TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id, dungeon_name)
                )
            """)

            # Daily activity limits - ENHANCED
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS daily_activity_limits (
                    user_id BIGINT,
                    guild_id BIGINT,
                    activity_date DATE DEFAULT CURRENT_DATE,
                    adventure_count INTEGER DEFAULT 0,
                    dungeon_count INTEGER DEFAULT 0,
                    arena_count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id, activity_date)
                )
            """)

            # Active dungeons tracking - WITH PROPER TIMING
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS active_dungeons (
                    user_id BIGINT,
                    guild_id BIGINT,
                    dungeon_id VARCHAR(50),
                    start_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMPTZ,
                    message_id BIGINT,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            # Party system - fix timestamp columns
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS parties (
                    party_id VARCHAR(36) PRIMARY KEY,
                    leader_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    max_members INTEGER DEFAULT 5,
                    min_power INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)

            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS party_members (
                    party_id VARCHAR(36),
                    user_id BIGINT,
                    joined_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    role VARCHAR(20) DEFAULT 'member',
                    PRIMARY KEY (party_id, user_id),
                    FOREIGN KEY (party_id) REFERENCES parties(party_id) ON DELETE CASCADE
                )
            """)

            # Active adventures tracking - MOST IMPORTANT FIX
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS active_adventures (
                    user_id BIGINT,
                    guild_id BIGINT,
                    adventure_id VARCHAR(50),
                    start_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMPTZ,
                    message_id BIGINT,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            # If tables already exist, alter them to use TIMESTAMPTZ
            try:
                await self.bot.pool.execute("ALTER TABLE active_adventures ALTER COLUMN start_time TYPE TIMESTAMPTZ")
                await self.bot.pool.execute("ALTER TABLE active_adventures ALTER COLUMN end_time TYPE TIMESTAMPTZ")
            except:
                pass  # Columns might already be correct type

            self.logger.info("활동 시스템 데이터베이스가 준비되었습니다.")
        except Exception as e:
            self.logger.error(f"활동 데이터베이스 설정 실패: {e}")

    def check_channel(self, interaction: discord.Interaction, required_channel_id: int) -> bool:
        """Check if command is used in correct channel"""
        if interaction.channel_id != required_channel_id:
            return False
        return True

    async def get_user_combat_power(self, user_id: int, guild_id: int) -> int:
        """Get user's combat power from enhancement cog"""
        try:
            enhancement_cog = self.bot.get_cog('EnhancementCog')
            if enhancement_cog:
                character = await enhancement_cog.get_user_character(user_id, guild_id)
                if character:
                    stats = await enhancement_cog.calculate_total_stats(user_id, guild_id)
                    return enhancement_cog.calculate_combat_power(stats, character['class'])
        except Exception as e:
            self.logger.error(f"Error getting combat power for user {user_id}: {e}")
        return 100  # Default minimum power


    def get_recommended_adventures(self, combat_power: int) -> List[Dict]:
        """Get recommended adventures based on combat power"""
        recommended = []
        for adventure in self.adventures.values():
            adventure_copy = adventure.copy()
            if adventure['min_power'] <= combat_power <= adventure['max_power'] * 2:
                adventure_copy['recommended'] = True
                recommended.append(adventure_copy)
            else:
                adventure_copy['recommended'] = False
                recommended.append(adventure_copy)

        # Sort by recommendation and difficulty
        recommended.sort(key=lambda x: (not x['recommended'], x['min_power']))
        return recommended

    async def start_adventure(self, interaction: discord.Interaction, adventure_id: str):
        """Start an adventure with enhanced concurrent activity prevention"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Double-check daily limit
        if not await self.check_daily_activity_limit(user_id, guild_id, "adventure"):
            await interaction.followup.send(
                f"⚠️ 일일 모험 한도에 도달했습니다! (하루 최대 {self.daily_limits['adventure']}회)",
                ephemeral=True
            )
            return

        # Double-check for concurrent activities right before starting
        active_activity = await self._check_concurrent_activity(user_id, guild_id)
        if active_activity:
            await interaction.followup.send(
                f"⚠️ 이미 {active_activity}을 진행 중입니다. 동시에 여러 활동을 할 수 없습니다!",
                ephemeral=True
            )
            return

        adventure = self.adventures.get(adventure_id)
        if not adventure:
            await interaction.followup.send("⚠️ 유효하지 않은 모험입니다.", ephemeral=True)
            return

        combat_power = await self.get_user_combat_power(user_id, guild_id)

        if combat_power < adventure['min_power']:
            await interaction.followup.send(
                f"⚠️ 전투력이 부족합니다!\n필요: {adventure['min_power']:,}\n현재: {combat_power:,}",
                ephemeral=True
            )
            return

        # Calculate success chance based on combat power
        power_ratio = combat_power / adventure['min_power']
        base_success_chance = min(95, 50 + (power_ratio - 1) * 30)

        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(seconds=adventure['duration'])

        try:
            # CRITICAL: Use INSERT with ON CONFLICT to prevent race conditions
            await self.bot.pool.execute("""
                INSERT INTO active_adventures (user_id, guild_id, adventure_id, start_time, end_time)
                VALUES ($1, $2, $3, $4::timestamptz, $5::timestamptz)
                ON CONFLICT (user_id, guild_id) DO NOTHING
            """, user_id, guild_id, adventure_id, start_time, end_time)

            # Verify the insertion was successful (not blocked by conflict)
            verification = await self.bot.pool.fetchrow(
                "SELECT adventure_id FROM active_adventures WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )

            if not verification or verification['adventure_id'] != adventure_id:
                await interaction.followup.send(
                    "⚠️ 다른 활동이 진행 중이어서 모험을 시작할 수 없습니다.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"{adventure['emoji']} 모험 시작!",
                description=f"**{adventure['name']}**에 출발했습니다!",
                color=discord.Color.blue()
            )
            embed.add_field(name="예상 소요시간", value=f"{adventure['duration'] // 60}분", inline=True)
            embed.add_field(name="성공 확률", value=f"{base_success_chance:.1f}%", inline=True)
            embed.add_field(name="전투력", value=f"{combat_power:,}", inline=True)
            embed.set_footer(text=f"모험 완료 시각: {end_time.strftime('%H:%M')} UTC")

            await interaction.followup.send(embed=embed)

            # Increment activity count
            await self.increment_activity_count(user_id, guild_id, "adventure")

            # Schedule adventure completion
            await asyncio.sleep(adventure['duration'])
            await self.complete_adventure(user_id, guild_id, adventure_id, base_success_chance, combat_power)

        except Exception as e:
            self.logger.error(f"Adventure start error: {e}")
            await interaction.followup.send(f"모험 시작 중 오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)
            # Clean up on error
            await self.bot.pool.execute(
                "DELETE FROM active_adventures WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )

    async def _get_player_stats(self, user_id: int, guild_id: int) -> dict:
        """사용자의 전투력, 레이팅, 티어 등을 arena_stats 테이블에서 가져옵니다."""
        try:
            # First get current combat power from enhancement system
            combat_power = await self.get_user_combat_power(user_id, guild_id)

            query = """
                SELECT user_id, rating, tier, wins, losses 
                FROM arena_stats 
                WHERE user_id = $1 AND guild_id = $2
            """
            record = await self.bot.pool.fetchrow(query, user_id, guild_id)

            if record is None:
                # Create new record with current combat power
                await self.bot.pool.execute("""
                    INSERT INTO arena_stats (user_id, guild_id, combat_power, rating, tier)
                    VALUES ($1, $2, $3, 1000, 'bronze')
                """, user_id, guild_id, combat_power)

                return {
                    'user_id': user_id,
                    'combat_power': combat_power,
                    'rating': 1000,
                    'tier': 'bronze',
                    'wins': 0,
                    'losses': 0
                }

            # Update combat power in database
            await self.bot.pool.execute("""
                UPDATE arena_stats SET combat_power = $1 WHERE user_id = $2 AND guild_id = $3
            """, combat_power, user_id, guild_id)

            result = dict(record)
            result['combat_power'] = combat_power
            return result

        except Exception as e:
            self.logger.error(f"사용자 {user_id}의 아레나 스탯 조회 오류: {e}")
            return {'user_id': user_id, 'combat_power': 100, 'rating': 1000, 'tier': 'bronze', 'wins': 0, 'losses': 0}
    async def _simulate_match(self, player_a_stats: dict, player_b_stats: dict) -> Tuple[int, int, int]:
        """전투력 기반으로 승패를 결정하고 Elo 레이팅 변화를 계산합니다."""

        power_a = player_a_stats['combat_power']
        power_b = player_b_stats['combat_power']

        total_power = power_a + power_b
        chance_a = power_a / total_power if total_power > 0 else 0.5

        if random.random() < chance_a:
            winner_stats, loser_stats = player_a_stats, player_b_stats
            winner_id = player_a_stats['user_id']
        else:
            winner_stats, loser_stats = player_b_stats, player_a_stats
            winner_id = player_b_stats['user_id']

        R_winner = winner_stats['rating']
        R_loser = loser_stats['rating']
        K_FACTOR = 32

        E_winner = 1 / (1 + 10 ** ((R_loser - R_winner) / 400))
        S_winner = 1

        rating_change_winner = round(K_FACTOR * (S_winner - E_winner))
        rating_change_loser = -rating_change_winner

        return winner_id, rating_change_winner, rating_change_loser

    async def _update_arena_stats(self, user_id: int, guild_id: int, is_winner: bool, rating_change: int):
        """플레이어의 승/패 및 레이팅을 업데이트합니다."""
        try:
            field_to_update = 'wins' if is_winner else 'losses'

            query = f"""
                INSERT INTO arena_stats (user_id, guild_id, rating, {field_to_update})
                VALUES ($1, $2, 1000 + $3, 1)
                ON CONFLICT (user_id, guild_id) DO UPDATE
                SET 
                    rating = arena_stats.rating + $3,
                    {field_to_update} = arena_stats.{field_to_update} + 1;
            """

            await self.bot.pool.execute(query, user_id, guild_id, rating_change)

        except Exception as e:
            self.logger.error(f"사용자 {user_id}의 아레나 스탯 업데이트 오류: {e}")

    async def start_arena_match(self, challenger_id: int, target_id: int, channel: discord.TextChannel,
                                wager: int = None):
        """도전이 수락되면 실제 전투를 실행하고 결과를 채널에 게시합니다."""

        guild_id = channel.guild.id

        # 도전 상태 정리
        if target_id in self.active_challenges and self.active_challenges.get(target_id) == challenger_id:
            del self.active_challenges[target_id]

        challenger = self.bot.get_user(challenger_id)
        target = self.bot.get_user(target_id)

        await channel.send(f"**⚔️ 매치 시작!** {challenger.mention} vs. {target.mention}...")

        try:
            # 1. 스탯 가져오기
            challenger_stats = await self._get_player_stats(challenger_id, guild_id)
            target_stats = await self._get_player_stats(target_id, guild_id)

            # 2. 매치 시뮬레이션
            winner_id, winner_rating_change, loser_rating_change = await self._simulate_match(
                challenger_stats, target_stats
            )

            # 승자/패자 객체 및 이전 스탯 설정
            if winner_id == challenger_id:
                winner, loser = challenger, target
                winner_stats_old = challenger_stats
                loser_stats_old = target_stats
            else:
                winner, loser = target, challenger
                winner_stats_old = target_stats
                loser_stats_old = challenger_stats

            # 3. 데이터베이스 업데이트
            await self._update_arena_stats(winner.id, guild_id, True, winner_rating_change)
            await self._update_arena_stats(loser.id, guild_id, False, loser_rating_change)

            # 4. 결과 메시지 구성
            winner_rating_new = winner_stats_old['rating'] + winner_rating_change
            loser_rating_new = loser_stats_old['rating'] + loser_rating_change

            embed = discord.Embed(
                title="🏆 아레나 매치 결과 🏆",
                description=f"치열한 승부 끝에 **{winner.display_name}**님이 **승리**했습니다!",
                color=discord.Color.gold()
            )
            embed.add_field(
                name=f"🥇 {winner.display_name} (승리)",
                value=(
                    f"전투력: `{winner_stats_old['combat_power']}`\n"
                    f"레이팅: `{winner_stats_old['rating']} -> {winner_rating_new}` (`+{winner_rating_change}`)"
                ),
                inline=False
            )
            embed.add_field(
                name=f"💀 {loser.display_name} (패배)",
                value=(
                    f"전투력: `{loser_stats_old['combat_power']}`\n"
                    f"레이팅: `{loser_stats_old['rating']} -> {loser_rating_new}` (`{loser_rating_change}`)"
                ),
                inline=False
            )

            await channel.send(embed=embed)

        except Exception as e:
            self.logger.error(f"아레나 매치 실행 중 치명적인 오류 발생: {e}")
            await channel.send(f"⚠️ 아레나 매치 실행 중 예상치 못한 오류가 발생했습니다. 개발자에게 보고해 주세요: `{e}`")

    # ENHANCED DAILY LIMIT CHECKING
    async def check_daily_activity_limit(self, user_id: int, guild_id: int, activity_type: str) -> bool:
        """Check if user has exceeded daily activity limits - ENHANCED"""
        try:
            limit = self.daily_limits.get(activity_type, 10)

            # Get current count for today
            current_count = await self.bot.pool.fetchval("""
                SELECT COALESCE(
                    CASE 
                        WHEN $3 = 'adventure' THEN adventure_count
                        WHEN $3 = 'dungeon' THEN dungeon_count
                        WHEN $3 = 'arena' THEN arena_count
                        ELSE 0
                    END, 0
                ) as count
                FROM daily_activity_limits
                WHERE user_id = $1 AND guild_id = $2 AND activity_date = CURRENT_DATE
            """, user_id, guild_id, activity_type)

            if current_count is None:
                current_count = 0

            return current_count < limit

        except Exception as e:
            self.logger.error(f"Daily limit check error: {e}")
            return True  # Allow on error to prevent blocking gameplay

    async def increment_activity_count(self, user_id: int, guild_id: int, activity_type: str):
        """Increment the daily activity count"""
        try:
            column_name = f"{activity_type}_count"
            await self.bot.pool.execute(f"""
                INSERT INTO daily_activity_limits (user_id, guild_id, activity_date, {column_name})
                VALUES ($1, $2, CURRENT_DATE, 1)
                ON CONFLICT (user_id, guild_id, activity_date) 
                DO UPDATE SET {column_name} = daily_activity_limits.{column_name} + 1
            """, user_id, guild_id)
        except Exception as e:
            self.logger.error(f"Error incrementing {activity_type} count: {e}")

    @app_commands.command(name="모험", description="모험을 떠나 경험치와 코인을 획득하세요!")
    async def adventure(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        if not self.check_channel(interaction, ADVENTURE_CHANNEL_ID):
            adventure_channel = self.bot.get_channel(ADVENTURE_CHANNEL_ID)
            channel_mention = adventure_channel.mention if adventure_channel else f"<#{ADVENTURE_CHANNEL_ID}>"
            await interaction.response.send_message(
                f"🗺️ 모험은 {channel_mention} 채널에서만 이용할 수 있습니다!",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        user_id = interaction.user.id

        # Check daily limit first
        if not await self.check_daily_activity_limit(user_id, guild_id, "adventure"):
            await interaction.followup.send(
                f"⚠️ 일일 모험 한도에 도달했습니다! (하루 최대 {self.daily_limits['adventure']}회)",
                ephemeral=True
            )
            return

        # ENHANCED: Check for ANY concurrent activity
        active_activity = await self._check_concurrent_activity(user_id, guild_id)
        if active_activity:
            await interaction.followup.send(
                f"⚠️ 이미 {active_activity}을 진행 중입니다. 동시에 여러 활동을 할 수 없습니다!",
                ephemeral=True
            )
            return

        # Rest of the adventure method remains the same...
        combat_power = await self.get_user_combat_power(user_id, guild_id)
        adventures_data = self.get_recommended_adventures(combat_power)

        embed = discord.Embed(
            title="🗺️ 모험 선택",
            description=f"현재 전투력: **{combat_power:,}**\n적절한 모험을 선택해주세요!",
            color=discord.Color.green()
        )

        for adventure in adventures_data:
            status = "✅ 추천" if adventure['recommended'] else "⚠️ 주의"
            embed.add_field(
                name=f"{adventure['emoji']} {adventure['name']} {status}",
                value=f"{adventure['description']}\n필요 전투력: {adventure['min_power']:,}\n소요시간: {adventure['duration'] // 60}분\n코인: {adventure['rewards']['coins'][0]}-{adventure['rewards']['coins'][1]}",
                inline=False
            )

        view = AdventureView(self.bot, user_id, guild_id, adventures_data)
        await interaction.followup.send(embed=embed, view=view)

    async def complete_adventure(self, user_id: int, guild_id: int, adventure_id: str, success_chance: float,
                                 combat_power: int):
        """Complete an adventure and give rewards - BALANCED"""
        try:
            adventure = self.adventures.get(adventure_id)
            if not adventure:
                return

            # Roll for success
            success = random.random() * 100 < success_chance

            rewards_coins = 0
            rewards_exp = 0

            if success:
                coin_range = adventure['rewards']['coins']
                exp_range = adventure['rewards']['exp']

                rewards_coins = random.randint(coin_range[0], coin_range[1])
                rewards_exp = random.randint(exp_range[0], exp_range[1])

                # BALANCED power bonus - max 1.5x instead of 2x
                power_bonus = min(1.5, combat_power / adventure['min_power'])
                rewards_coins = int(rewards_coins * power_bonus)
                rewards_exp = int(rewards_exp * power_bonus)

                # Give rewards
                coins_cog = self.bot.get_cog('CoinsCog')
                if coins_cog:
                    await coins_cog.add_coins(user_id, guild_id, rewards_coins, "adventure", f"모험: {adventure['name']}")

            # Log adventure
            await self.bot.pool.execute("""
                INSERT INTO adventure_logs (user_id, guild_id, adventure_id, end_time, success, rewards_coins, rewards_exp, combat_power)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, $4, $5, $6, $7)
            """, user_id, guild_id, adventure_id, success, rewards_coins, rewards_exp, combat_power)

            # Remove from active adventures
            await self.bot.pool.execute(
                "DELETE FROM active_adventures WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )

            # Send completion message
            guild = self.bot.get_guild(guild_id)
            user = guild.get_member(user_id) if guild else None

            if user:
                embed = discord.Embed(
                    title=f"{adventure['emoji']} 모험 완료!",
                    color=discord.Color.green() if success else discord.Color.red()
                )

                if success:
                    embed.description = f"**{adventure['name']}** 모험을 성공적으로 완료했습니다!"
                    embed.add_field(name="🪙 획득 코인", value=f"{rewards_coins:,}", inline=True)
                    embed.add_field(name="⭐ 획득 경험치", value=f"{rewards_exp:,}", inline=True)
                else:
                    embed.description = f"**{adventure['name']}** 모험에 실패했습니다..."
                    embed.add_field(name="💔 결과", value="보상 없음", inline=True)

                adventure_channel = self.bot.get_channel(ADVENTURE_CHANNEL_ID)
                if adventure_channel:
                    await adventure_channel.send(f"{user.mention}", embed=embed)

        except Exception as e:
            self.logger.error(f"모험 완료 처리 오류: {e}")

    @app_commands.command(name="던전", description="파티와 함께 던전을 탐험하세요!")
    async def dungeon(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        if not self.check_channel(interaction, DUNGEON_CHANNEL_ID):
            dungeon_channel = self.bot.get_channel(DUNGEON_CHANNEL_ID)
            channel_mention = dungeon_channel.mention if dungeon_channel else f"<#{DUNGEON_CHANNEL_ID}>"
            await interaction.response.send_message(
                f"🏰 던전은 {channel_mention} 채널에서만 이용할 수 있습니다!",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        user_id = interaction.user.id

        # Check daily limit first
        if not await self.check_daily_activity_limit(user_id, guild_id, "dungeon"):
            await interaction.followup.send(
                f"⚠️ 일일 던전 한도에 도달했습니다! (하루 최대 {self.daily_limits['dungeon']}회)",
                ephemeral=True
            )
            return

        # ENHANCED: Check for ANY concurrent activity
        active_activity = await self._check_concurrent_activity(user_id, guild_id)
        if active_activity:
            await interaction.followup.send(
                f"⚠️ 이미 {active_activity}을 진행 중입니다. 동시에 여러 활동을 할 수 없습니다!",
                ephemeral=True
            )
            return

        # Rest of the dungeon method remains the same...
        combat_power = await self.get_user_combat_power(user_id, guild_id)

        # Get available dungeons
        available_dungeons = []
        for dungeon in self.dungeons.values():
            dungeon_copy = dungeon.copy()
            if combat_power >= dungeon['min_power']:
                dungeon_copy['available'] = True
            else:
                dungeon_copy['available'] = False
            available_dungeons.append(dungeon_copy)

        embed = discord.Embed(
            title="🏰 던전 선택",
            description=f"현재 전투력: **{combat_power:,}**\n도전할 던전을 선택하세요!",
            color=discord.Color.dark_blue()
        )

        for dungeon in available_dungeons:
            status = "✅ 도전 가능" if dungeon['available'] else "🔒 전투력 부족"
            party_info = f"{dungeon['party_size'][0]}-{dungeon['party_size'][1]}명"

            embed.add_field(
                name=f"{dungeon['emoji']} {dungeon['name']} ({dungeon['difficulty']}) {status}",
                value=f"{dungeon['description']}\n필요 전투력: {dungeon['min_power']:,}\n파티 크기: {party_info}\n소요시간: {dungeon['duration'] // 60}분\n코인: {dungeon['rewards']['coins'][0]}-{dungeon['rewards']['coins'][1]}",
                inline=False
            )

        view = DungeonView(self.bot, user_id, guild_id, available_dungeons)
        await interaction.followup.send(embed=embed, view=view)

    async def start_dungeon(self, interaction: discord.Interaction, dungeon_id: str):
        """Start a dungeon with enhanced concurrent activity prevention"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Double-check daily limit
        if not await self.check_daily_activity_limit(user_id, guild_id, "dungeon"):
            await interaction.followup.send(
                f"⚠️ 일일 던전 한도에 도달했습니다! (하루 최대 {self.daily_limits['dungeon']}회)",
                ephemeral=True
            )
            return

        # Double-check for concurrent activities right before starting
        active_activity = await self._check_concurrent_activity(user_id, guild_id)
        if active_activity:
            await interaction.followup.send(
                f"⚠️ 이미 {active_activity}을 진행 중입니다. 동시에 여러 활동을 할 수 없습니다!",
                ephemeral=True
            )
            return

        dungeon = self.dungeons.get(dungeon_id)
        if not dungeon:
            await interaction.followup.send("⚠️ 유효하지 않은 던전입니다.", ephemeral=True)
            return

        combat_power = await self.get_user_combat_power(user_id, guild_id)

        if combat_power < dungeon['min_power']:
            await interaction.followup.send(
                f"⚠️ 전투력이 부족합니다!\n필요: {dungeon['min_power']:,}\n현재: {combat_power:,}",
                ephemeral=True
            )
            return

        # Calculate success chance
        power_ratio = combat_power / dungeon['min_power']
        base_success_chance = min(85, 30 + (power_ratio - 1) * 40)

        # Start dungeon with ACTUAL timing
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(seconds=dungeon['duration'])

        try:
            # CRITICAL: Use INSERT with ON CONFLICT to prevent race conditions
            await self.bot.pool.execute("""
                INSERT INTO active_dungeons (user_id, guild_id, dungeon_id, start_time, end_time)
                VALUES ($1, $2, $3, $4::timestamptz, $5::timestamptz)
                ON CONFLICT (user_id, guild_id) DO NOTHING
            """, user_id, guild_id, dungeon_id, start_time, end_time)

            # Verify the insertion was successful (not blocked by conflict)
            verification = await self.bot.pool.fetchrow(
                "SELECT dungeon_id FROM active_dungeons WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )

            if not verification or verification['dungeon_id'] != dungeon_id:
                await interaction.followup.send(
                    "⚠️ 다른 활동이 진행 중이어서 던전을 시작할 수 없습니다.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"{dungeon['emoji']} 던전 시작!",
                description=f"**{dungeon['name']}** 던전에 입장했습니다!",
                color=discord.Color.dark_blue()
            )
            embed.add_field(name="소요 시간", value=f"{dungeon['duration'] // 60}분", inline=True)
            embed.add_field(name="성공 확률", value=f"{base_success_chance:.1f}%", inline=True)
            embed.add_field(name="전투력", value=f"{combat_power:,}", inline=True)
            embed.set_footer(text=f"던전 완료 예정: {end_time.strftime('%H:%M')} UTC")

            await interaction.followup.send(embed=embed)

            # Increment activity count
            await self.increment_activity_count(user_id, guild_id, "dungeon")

            # Schedule dungeon completion - ACTUAL TIME
            await asyncio.sleep(dungeon['duration'])
            await self.complete_dungeon(user_id, guild_id, dungeon_id, base_success_chance, combat_power)

        except Exception as e:
            self.logger.error(f"Dungeon start error: {e}")
            await interaction.followup.send(f"던전 시작 중 오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)
            # Clean up on error
            await self.bot.pool.execute(
                "DELETE FROM active_dungeons WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
    async def complete_dungeon(self, user_id: int, guild_id: int, dungeon_id: str, success_chance: float,
                               combat_power: int):
        """Complete a dungeon - BALANCED REWARDS"""
        try:
            dungeon = self.dungeons.get(dungeon_id)
            if not dungeon:
                return

            # Roll for success
            success = random.random() * 100 < success_chance
            completion_time = random.randint(dungeon['duration'] // 2, dungeon['duration'])

            # Update progress
            await self.bot.pool.execute("""
                INSERT INTO dungeon_progress (user_id, guild_id, dungeon_name, completions, best_time, last_attempt)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, guild_id, dungeon_name) DO UPDATE SET
                completions = dungeon_progress.completions + $4,
                best_time = CASE WHEN $4 > 0 THEN 
                    CASE WHEN dungeon_progress.best_time = 0 OR $5 < dungeon_progress.best_time 
                    THEN $5 ELSE dungeon_progress.best_time END
                    ELSE dungeon_progress.best_time END,
                last_attempt = CURRENT_TIMESTAMP
            """, user_id, guild_id, dungeon_id, 1 if success else 0, completion_time if success else 0)

            # Remove from active dungeons
            await self.bot.pool.execute(
                "DELETE FROM active_dungeons WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )

            embed = discord.Embed(
                title=f"{dungeon['emoji']} 던전 결과",
                color=discord.Color.green() if success else discord.Color.red()
            )

            if success:
                # BALANCED rewards calculation
                coin_range = dungeon['rewards']['coins']
                coins_reward = random.randint(coin_range[0], coin_range[1])

                # BALANCED time bonus - max 1.3x instead of 2x
                time_ratio = completion_time / dungeon['duration']
                time_bonus = max(1.0, 1.3 - (time_ratio * 0.3))
                coins_reward = int(coins_reward * time_bonus)

                # Give rewards
                coins_cog = self.bot.get_cog('CoinsCog')
                if coins_cog:
                    await coins_cog.add_coins(user_id, guild_id, coins_reward, "dungeon", f"던전: {dungeon['name']}")

                # BALANCED item chance - reduced
                item_chance = 20 + min(15, (combat_power / dungeon['min_power'] - 1) * 10)  # Max 35% instead of 40%+
                if random.random() * 100 < item_chance:
                    enhancement_cog = self.bot.get_cog('EnhancementCog')
                    if enhancement_cog:
                        item_data = enhancement_cog.get_random_item()
                        if item_data:
                            await enhancement_cog.create_item_in_db(user_id, guild_id, item_data)
                            embed.add_field(name="🎁 보너스 아이템", value=f"{item_data['emoji']} {item_data['name']}",
                                            inline=True)

                embed.description = f"**{dungeon['name']}**을 성공적으로 클리어했습니다!"
                embed.add_field(name="완료 시간", value=f"{completion_time // 60}분 {completion_time % 60}초", inline=True)
                embed.add_field(name="획득 코인", value=f"{coins_reward:,}", inline=True)

            else:
                embed.description = f"**{dungeon['name']}** 공략에 실패했습니다..."
                embed.add_field(name="결과", value="보상 없음", inline=True)

            embed.add_field(name="성공 확률", value=f"{success_chance:.1f}%", inline=True)
            embed.add_field(name="전투력", value=f"{combat_power:,}", inline=True)

            # Send result to dungeon channel
            dungeon_channel = self.bot.get_channel(DUNGEON_CHANNEL_ID)
            if dungeon_channel:
                user = self.bot.get_user(user_id)
                if user:
                    await dungeon_channel.send(f"{user.mention}", embed=embed)

        except Exception as e:
            self.logger.error(f"Dungeon completion error: {e}")

    # Add at top if not already: from typing import Optional

    @app_commands.command(name="아레나", description="다른 플레이어와 전투를 펼치세요! (대상/내기 선택 가능)")
    @app_commands.describe(target="도전할 플레이어를 선택하세요 (선택사항).", wager="내기 코인 (선택사항)", note="짧은 메모 (선택사항)")
    async def arena(self, interaction: discord.Interaction, target: Optional[discord.Member] = None,
                    wager: Optional[int] = None, note: Optional[str] = None):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        # If a target is provided, treat this as a challenge request
        if target is not None:
            # Reuse most of challenge_player validation/flow
            challenger = interaction.user

            # Channel check
            if not self.check_channel(interaction, ARENA_CHANNEL_ID):
                arena_channel = self.bot.get_channel(ARENA_CHANNEL_ID)
                channel_mention = arena_channel.mention if arena_channel else f"<#{ARENA_CHANNEL_ID}>"
                await interaction.response.send_message(
                    f"⚔️ 아레나 도전은 {channel_mention} 채널에서만 이용할 수 있습니다!",
                    ephemeral=True
                )
                return

            if challenger.id == target.id:
                return await interaction.response.send_message("자신에게 도전할 수 없습니다!", ephemeral=True)
            if target.bot:
                return await interaction.response.send_message("봇에게 도전할 수 없습니다!", ephemeral=True)

            # Wager validation (if present)
            if wager is not None:
                if wager < 0:
                    return await interaction.response.send_message("내기는 0 이상의 값이어야 합니다.", ephemeral=True)
                # Optionally: check challenger has enough coins (if you have CoinsCog)
                coins_cog = self.bot.get_cog('CoinsCog')
                if coins_cog:
                    balance = await coins_cog.get_user_coins(challenger.id, guild_id)
                    if balance is not None and balance < wager:
                        return await interaction.response.send_message("내기에 필요한 코인이 부족합니다.", ephemeral=True)

            # check existing active challenges
            if target.id in self.active_challenges:
                return await interaction.response.send_message(f"**{target.display_name}**님은 이미 다른 도전을 받고 있습니다.",
                                                               ephemeral=True)
            if challenger.id in self.active_challenges.values():
                return await interaction.response.send_message("이미 진행 중인 도전이 있습니다. 응답을 기다려주세요.", ephemeral=True)

            # store active challenge
            self.active_challenges[target.id] = challenger.id

            # Create a challenge message including wager/note
            wager_text = f"\n💰 내기: {wager:,} 코인" if wager is not None else ""
            note_text = f"\n📝 메모: {note}" if note else ""

            challenge_message = (
                f"**⚔️ 아레나 도전! (ARENA CHALLENGE)**\n\n"
                f"<@{target.id}>님, **{challenger.display_name}**님이 아레나 PvP 매치를 신청했습니다!"
                f"{wager_text}{note_text}\n\n"
                f"도전을 수락하시겠습니까?"
            )

            # Create view that can carry extra metadata (wager/note)
            view = ArenaChallengeView(
                challenger_id=challenger.id,
                target_id=target.id,
                cog_instance=self
            )
            # Attach optional metadata to view instance for later reference
            view.wager = wager
            view.note = note

            await interaction.response.send_message(content=challenge_message, view=view,
                                                    allowed_mentions=discord.AllowedMentions(users=[target]))
            timed_out = await view.wait()
            if timed_out:
                if target.id in self.active_challenges and self.active_challenges.get(target.id) == challenger.id:
                    del self.active_challenges[target.id]
                    await interaction.followup.send(f"⚠️ **도전 시간 초과.** <@{target.id}>님의 응답이 없어 도전이 취소되었습니다.",
                                                    ephemeral=False)

            return  # challenge flow finished

        # --- If no target provided: show the standard arena UI (unchanged) ---
        try:
            await interaction.response.defer()
            user_id = interaction.user.id

            # Get or create arena stats (same logic as before)
            arena_stats = await self.bot.pool.fetchrow(
                "SELECT * FROM arena_stats WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )

            if not arena_stats:
                await self.bot.pool.execute("""
                    INSERT INTO arena_stats (user_id, guild_id, tier, rating)
                    VALUES ($1, $2, 'bronze', 1000)
                """, user_id, guild_id)
                arena_stats = await self.bot.pool.fetchrow(
                    "SELECT * FROM arena_stats WHERE user_id = $1 AND guild_id = $2",
                    user_id, guild_id
                )

            # determine current tier
            current_tier = None
            for tier_id, tier_info in self.arena_tiers.items():
                if arena_stats['rating'] >= tier_info['min_rating']:
                    current_tier = tier_info
                else:
                    break
            if not current_tier:
                current_tier = self.arena_tiers['bronze']

            combat_power = await self.get_user_combat_power(user_id, guild_id)

            embed = discord.Embed(
                title="⚔️ 아레나 입장",
                description="전투를 통해 실력을 증명하세요!",
                color=discord.Color.red()
            )
            embed.add_field(name="현재 티어", value=f"{current_tier['emoji']} {current_tier['name']}", inline=True)
            embed.add_field(name="레이팅", value=f"{arena_stats['rating']}", inline=True)
            embed.add_field(name="전투력", value=f"{combat_power:,}", inline=True)
            embed.add_field(name="전적", value=f"{arena_stats['wins']}승 {arena_stats['losses']}패", inline=True)
            embed.add_field(name="연승", value=f"{arena_stats['current_streak']}연승", inline=True)
            embed.add_field(name="최고 연승", value=f"{arena_stats['best_streak']}연승", inline=True)

            view = ArenaView(self.bot, user_id, guild_id, arena_stats)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            self.logger.error(f"Arena command error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"아레나 명령어 처리 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"아레나 명령어 처리 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    async def start_ranked_battle(self, interaction: discord.Interaction):
        """Start a ranked battle - ENHANCED"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Check daily limit for arena battles
        if not await self.check_daily_activity_limit(user_id, guild_id, "arena"):
            await interaction.followup.send(
                f"⚠️ Daily arena limit reached! (Max {self.daily_limits['arena']} per day)",
                ephemeral=True
            )
            return

        # Get the player's stats using our helper method
        user_stats = await self._get_player_stats(user_id, guild_id)

        # Force AI battle only
        ai_rating = user_stats['rating'] + random.randint(-50, 50)
        await self.battle_ai_opponent(interaction, user_stats, ai_rating)

    async def battle_ai_opponent(self, interaction: discord.Interaction, user_stats: dict, ai_rating: int):
        """Battle against AI opponent - BALANCED REWARDS"""
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        user_power = await self.get_user_combat_power(user_id, guild_id)
        ai_power = int(user_power * (ai_rating / user_stats['rating']) * random.uniform(0.8, 1.2))

        # Calculate battle outcome
        power_ratio = user_power / max(ai_power, 1)
        win_chance = 50 + (power_ratio - 1) * 30
        win_chance = max(10, min(90, win_chance))  # Clamp between 10-90%

        won = random.random() * 100 < win_chance

        # Calculate rating change
        expected_score = 1 / (1 + 10 ** ((ai_rating - user_stats['rating']) / 400))
        actual_score = 1 if won else 0
        k_factor = 32
        rating_change = int(k_factor * (actual_score - expected_score))

        new_rating = max(0, user_stats['rating'] + rating_change)
        new_streak = user_stats['current_streak'] + 1 if won else 0
        best_streak = max(user_stats['best_streak'], new_streak)

        # Update stats
        await self.bot.pool.execute("""
            UPDATE arena_stats SET 
            rating = $1, 
            wins = wins + $2, 
            losses = losses + $3,
            current_streak = $4,
            best_streak = $5,
            last_battle = CURRENT_TIMESTAMP
            WHERE user_id = $6 AND guild_id = $7
        """, new_rating, 1 if won else 0, 0 if won else 1, new_streak, best_streak, user_id, guild_id)

        # Create result embed
        embed = discord.Embed(
            title="⚔️ 아레나 전투 결과",
            color=discord.Color.green() if won else discord.Color.red()
        )

        result_text = "승리!" if won else "패배..."
        embed.add_field(name="결과", value=result_text, inline=True)
        embed.add_field(name="상대", value="AI 전사", inline=True)
        embed.add_field(name="레이팅 변화", value=f"{user_stats['rating']} → {new_rating} ({rating_change:+d})", inline=True)
        embed.add_field(name="전투력", value=f"{user_power:,} vs {ai_power:,}", inline=True)
        embed.add_field(name="연승", value=f"{new_streak}연승", inline=True)

        if won:
            # BALANCED coins reward - much lower
            coins_reward = random.randint(15, 40) + (new_streak * 5)  # Reduced from 50-200 + streak*10
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(user_id, guild_id, coins_reward, "arena_win", "아레나 승리")
            embed.add_field(name="보상", value=f"{coins_reward:,} 코인", inline=True)

        await interaction.followup.send(embed=embed)

        # Increment arena battle count
        await self.increment_activity_count(user_id, guild_id, "arena")

    async def battle_player_opponent(self, interaction: discord.Interaction, user_stats: dict, opponent_data: dict):
        """Battle against another player (simulated) - BALANCED REWARDS"""
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        opponent_id = opponent_data['user_id']

        user_power = await self.get_user_combat_power(user_id, guild_id)
        opponent_power = await self.get_user_combat_power(opponent_id, guild_id)

        # Calculate battle outcome
        power_ratio = user_power / max(opponent_power, 1)
        win_chance = 50 + (power_ratio - 1) * 25
        win_chance = max(15, min(85, win_chance))  # More balanced for PvP

        won = random.random() * 100 < win_chance

        # Get opponent user
        guild = self.bot.get_guild(guild_id)
        opponent_user = guild.get_member(opponent_id) if guild else None
        opponent_name = opponent_user.display_name if opponent_user else "알 수 없는 플레이어"

        # Rating calculations (simplified ELO)
        expected_score = 1 / (1 + 10 ** ((opponent_data['rating'] - user_stats['rating']) / 400))
        actual_score = 1 if won else 0
        k_factor = 32
        rating_change = int(k_factor * (actual_score - expected_score))

        new_rating = max(0, user_stats['rating'] + rating_change)
        new_streak = user_stats['current_streak'] + 1 if won else 0
        best_streak = max(user_stats['best_streak'], new_streak)

        # Update user stats
        await self.bot.pool.execute("""
            UPDATE arena_stats SET 
            rating = $1, 
            wins = wins + $2, 
            losses = losses + $3,
            current_streak = $4,
            best_streak = $5,
            last_battle = CURRENT_TIMESTAMP
            WHERE user_id = $6 AND guild_id = $7
        """, new_rating, 1 if won else 0, 0 if won else 1, new_streak, best_streak, user_id, guild_id)

        # Update opponent stats (reverse outcome)
        opponent_rating_change = -rating_change
        await self.bot.pool.execute("""
            UPDATE arena_stats SET 
            rating = GREATEST(0, rating + $1), 
            wins = wins + $2, 
            losses = losses + $3,
            current_streak = CASE WHEN $4 THEN 0 ELSE current_streak + 1 END,
            last_battle = CURRENT_TIMESTAMP
            WHERE user_id = $5 AND guild_id = $6
        """, opponent_rating_change, 0 if won else 1, 1 if won else 0, won, opponent_id, guild_id)

        # Create result embed
        embed = discord.Embed(
            title="⚔️ 아레나 전투 결과",
            color=discord.Color.green() if won else discord.Color.red()
        )

        result_text = "승리!" if won else "패배..."
        embed.add_field(name="결과", value=result_text, inline=True)
        embed.add_field(name="상대", value=opponent_name, inline=True)
        embed.add_field(name="레이팅 변화", value=f"{user_stats['rating']} → {new_rating} ({rating_change:+d})", inline=True)
        embed.add_field(name="전투력", value=f"{user_power:,} vs {opponent_power:,}", inline=True)
        embed.add_field(name="연승", value=f"{new_streak}연승", inline=True)

        if won:
            # BALANCED coins reward for PvP - slightly higher than AI but still reasonable
            coins_reward = random.randint(25, 60) + (new_streak * 8)  # Reduced from 100-300 + streak*15
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(user_id, guild_id, coins_reward, "arena_win", "아레나 승리")
            embed.add_field(name="보상", value=f"{coins_reward:,} 코인", inline=True)

        await interaction.followup.send(embed=embed)

        # Increment arena battle count
        await self.increment_activity_count(user_id, guild_id, "arena")

    async def start_practice_battle(self, interaction: discord.Interaction):
        """Start a practice battle (no rating change) - NO COIN REWARDS"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        user_power = await self.get_user_combat_power(user_id, guild_id)
        dummy_power = int(user_power * random.uniform(0.7, 1.3))

        win_chance = 60  # Slightly favorable for practice
        won = random.random() * 100 < win_chance

        embed = discord.Embed(
            title="🎯 연습전 결과",
            color=discord.Color.blue()
        )

        result_text = "승리!" if won else "패배..."
        embed.add_field(name="결과", value=result_text, inline=True)
        embed.add_field(name="상대", value="연습용 더미", inline=True)
        embed.add_field(name="전투력", value=f"{user_power:,} vs {dummy_power:,}", inline=True)
        embed.add_field(name="보상", value="경험 획득 (레이팅 변화 없음, 코인 없음)", inline=False)

        await interaction.followup.send(embed=embed)

    async def show_arena_rankings(self, interaction: discord.Interaction):
        """Show arena rankings"""
        await interaction.response.defer()
        guild_id = interaction.guild.id

        # Get top 10 players
        rankings = await self.bot.pool.fetch("""
            SELECT user_id, rating, wins, losses, current_streak, best_streak
            FROM arena_stats 
            WHERE guild_id = $1 
            ORDER BY rating DESC 
            LIMIT 10
        """, guild_id)

        if not rankings:
            await interaction.followup.send("🏆 아직 아레나 랭킹이 없습니다!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 아레나 랭킹",
            color=discord.Color.gold()
        )

        guild = interaction.guild
        ranking_text = ""

        for i, player in enumerate(rankings, 1):
            user = guild.get_member(player['user_id'])
            username = user.display_name if user else "알 수 없는 사용자"

            # Get tier
            tier_info = self.arena_tiers['bronze']
            for tier_id, tier_data in self.arena_tiers.items():
                if player['rating'] >= tier_data['min_rating']:
                    tier_info = tier_data
                else:
                    break

            rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
            ranking_text += f"{rank_emoji} **{username}** {tier_info['emoji']}\n"
            ranking_text += f"    레이팅: {player['rating']} | {player['wins']}승 {player['losses']}패 | {player['current_streak']}연승\n\n"

        embed.description = ranking_text
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="활동기록", description="모험, 아레나, 던전 활동 기록을 확인합니다.")
    @app_commands.describe(user="확인할 사용자 (비워두면 본인)")
    async def activity_records(self, interaction: discord.Interaction, user: discord.Member = None):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        await interaction.response.defer()
        target_user = user or interaction.user
        target_id = target_user.id

        # Get adventure stats
        adventure_stats = await self.bot.pool.fetchrow("""
            SELECT COUNT(*) as total_adventures, 
                   COUNT(CASE WHEN success THEN 1 END) as successful_adventures,
                   SUM(rewards_coins) as total_coins_earned
            FROM adventure_logs 
            WHERE user_id = $1 AND guild_id = $2
        """, target_id, guild_id)

        # Get arena stats
        arena_stats = await self.bot.pool.fetchrow("""
            SELECT * FROM arena_stats WHERE user_id = $1 AND guild_id = $2
        """, target_id, guild_id)

        # Get dungeon stats
        dungeon_stats = await self.bot.pool.fetch("""
            SELECT dungeon_name, completions, best_time FROM dungeon_progress
            WHERE user_id = $1 AND guild_id = $2 AND completions > 0
            ORDER BY completions DESC
        """, target_id, guild_id)

        # Get daily limits remaining
        today_counts = await self.bot.pool.fetchrow("""
            SELECT adventure_count, dungeon_count, arena_count
            FROM daily_activity_limits
            WHERE user_id = $1 AND guild_id = $2 AND activity_date = CURRENT_DATE
        """, target_id, guild_id)

        combat_power = await self.get_user_combat_power(target_id, guild_id)

        embed = discord.Embed(
            title=f"📊 {target_user.display_name}의 활동 기록",
            color=discord.Color.blue()
        )

        embed.add_field(name="⚡ 현재 전투력", value=f"{combat_power:,}", inline=True)

        # Daily limits status
        if today_counts:
            adventure_remaining = self.daily_limits['adventure'] - (today_counts['adventure_count'] or 0)
            dungeon_remaining = self.daily_limits['dungeon'] - (today_counts['dungeon_count'] or 0)
            arena_remaining = self.daily_limits['arena'] - (today_counts['arena_count'] or 0)
        else:
            adventure_remaining = self.daily_limits['adventure']
            dungeon_remaining = self.daily_limits['dungeon']
            arena_remaining = self.daily_limits['arena']

        limits_text = f"모험: {max(0, adventure_remaining)}/{self.daily_limits['adventure']}\n"
        limits_text += f"던전: {max(0, dungeon_remaining)}/{self.daily_limits['dungeon']}\n"
        limits_text += f"아레나: {max(0, arena_remaining)}/{self.daily_limits['arena']}"
        embed.add_field(name="📅 오늘 남은 횟수", value=limits_text, inline=True)

        # Adventure stats
        if adventure_stats and adventure_stats['total_adventures']:
            success_rate = (adventure_stats['successful_adventures'] / adventure_stats['total_adventures']) * 100
            adventure_text = f"총 {adventure_stats['total_adventures']}회\n"
            adventure_text += f"성공 {adventure_stats['successful_adventures']}회 ({success_rate:.1f}%)\n"
            adventure_text += f"획득 코인: {adventure_stats['total_coins_earned'] or 0:,}"
        else:
            adventure_text = "모험 기록 없음"

        embed.add_field(name="🗺️ 모험 기록", value=adventure_text, inline=True)

        # Arena stats
        if arena_stats:
            total_battles = arena_stats['wins'] + arena_stats['losses']
            win_rate = (arena_stats['wins'] / total_battles * 100) if total_battles > 0 else 0

            # Get current tier
            current_tier = self.arena_tiers['bronze']
            for tier_id, tier_info in self.arena_tiers.items():
                if arena_stats['rating'] >= tier_info['min_rating']:
                    current_tier = tier_info
                else:
                    break

            arena_text = f"{current_tier['emoji']} {current_tier['name']}\n"
            arena_text += f"레이팅: {arena_stats['rating']}\n"
            arena_text += f"{arena_stats['wins']}승 {arena_stats['losses']}패 ({win_rate:.1f}%)\n"
            arena_text += f"최고 연승: {arena_stats['best_streak']}"
        else:
            arena_text = "아레나 기록 없음"

        embed.add_field(name="⚔️ 아레나 기록", value=arena_text, inline=True)

        # Dungeon stats
        if dungeon_stats:
            dungeon_text = ""
            for dungeon in dungeon_stats[:3]:  # Top 3 dungeons
                dungeon_info = self.dungeons.get(dungeon['dungeon_name'])
                name = dungeon_info['name'] if dungeon_info else dungeon['dungeon_name']
                best_time_text = f"{dungeon['best_time'] // 60}분 {dungeon['best_time'] % 60}초" if dungeon[
                                                                                                      'best_time'] > 0 else "기록 없음"
                dungeon_text += f"**{name}**: {dungeon['completions']}회 클리어\n최고 기록: {best_time_text}\n"
        else:
            dungeon_text = "던전 기록 없음"

        embed.add_field(name="🏰 던전 기록", value=dungeon_text or "던전 기록 없음", inline=False)

        await interaction.followup.send(embed=embed)

    async def check_completed_adventures(self):
        """Check for adventures that should be completed but haven't been processed"""
        try:
            current_time = datetime.now(timezone.utc)

            # Find adventures that should be completed
            completed_adventures = await self.bot.pool.fetch("""
                SELECT user_id, guild_id, adventure_id, start_time, end_time 
                FROM active_adventures 
                WHERE end_time <= $1
            """, current_time)

            for adventure in completed_adventures:
                # Calculate what the success chance and combat power would have been
                adventure_data = self.adventures.get(adventure['adventure_id'])
                if adventure_data:
                    # Get combat power (might be different now, but we'll use current)
                    combat_power = await self.get_user_combat_power(
                        adventure['user_id'], adventure['guild_id']
                    )

                    power_ratio = combat_power / adventure_data['min_power']
                    success_chance = min(95, 50 + (power_ratio - 1) * 30)

                    # Complete the adventure
                    await self.complete_adventure(
                        adventure['user_id'],
                        adventure['guild_id'],
                        adventure['adventure_id'],
                        success_chance,
                        combat_power
                    )

        except Exception as e:
            self.logger.error(f"Error checking completed adventures: {e}")

    # DAILY RESET TASK FOR ACTIVITY LIMITS
    @tasks.loop(hours=24)
    async def reset_daily_limits(self):
        """Reset daily activity limits at midnight UTC"""
        try:
            # Clean up old daily limit records (keep last 7 days for statistics)
            await self.bot.pool.execute("""
                DELETE FROM daily_activity_limits 
                WHERE activity_date < CURRENT_DATE - INTERVAL '7 days'
            """)

            self.logger.info("Daily activity limits cleaned up")
        except Exception as e:
            self.logger.error(f"Error resetting daily limits: {e}")

    @reset_daily_limits.before_loop
    async def before_reset_daily_limits(self):
        """Wait until bot is ready before starting the daily reset task"""
        await self.bot.wait_until_ready()

    async def cog_load(self):
        """Start the daily reset task when cog loads"""
        self.reset_daily_limits.start()

    async def cog_unload(self):
        """Stop the daily reset task when cog unloads"""
        self.reset_daily_limits.cancel()


async def setup(bot):
    await bot.add_cog(ActivitiesCog(bot))
