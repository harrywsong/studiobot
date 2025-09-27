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
    if dt.tzinfo is None:
        # Assume naive datetime is in UTC
        return dt.replace(tzinfo=timezone.utc)
    return dt

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
            if not interaction.response.is_done():
                await interaction.response.send_message(f"연습전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"연습전 시작 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    @discord.ui.button(label="🏆 아레나 랭킹", style=discord.ButtonStyle.primary)
    async def arena_rankings(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.activities_cog.show_arena_rankings(interaction)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"랭킹 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"랭킹 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)


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


class PartyView(discord.ui.View):
    """Party formation and management"""

    def __init__(self, bot, user_id, guild_id, party_data=None):
        super().__init__(timeout=600)  # Longer timeout for party management
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.party_data = party_data or {}
        self.activities_cog = bot.get_cog('ActivitiesCog')

    @discord.ui.button(label="👥 파티 생성", style=discord.ButtonStyle.success)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("파티를 생성할 권한이 없습니다.", ephemeral=True)
            return
        await self.activities_cog.create_party(interaction)

    @discord.ui.button(label="🔍 파티 찾기", style=discord.ButtonStyle.primary)
    async def find_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.activities_cog.show_available_parties(interaction)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"파티 목록 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"파티 목록 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    @discord.ui.button(label="📋 내 파티", style=discord.ButtonStyle.secondary)
    async def my_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 파티를 볼 수 없습니다.", ephemeral=True)
            return
        try:
            await self.activities_cog.show_my_party(interaction)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"파티 정보 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"파티 정보 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)


class CreatePartyModal(discord.ui.Modal):
    """Modal for creating a new party"""

    def __init__(self, bot):
        super().__init__(title="새 파티 생성")
        self.bot = bot

        self.party_name = discord.ui.TextInput(
            label="파티 이름",
            placeholder="파티 이름을 입력하세요...",
            max_length=50,
            required=True
        )

        self.description = discord.ui.TextInput(
            label="파티 설명",
            placeholder="파티에 대한 간단한 설명 (선택사항)",
            style=discord.TextStyle.paragraph,
            max_length=200,
            required=False
        )

        self.min_power = discord.ui.TextInput(
            label="최소 전투력",
            placeholder="파티 참여에 필요한 최소 전투력",
            max_length=10,
            required=True
        )

        self.max_members = discord.ui.TextInput(
            label="최대 인원",
            placeholder="2-5 사이의 숫자를 입력하세요",
            max_length=1,
            required=True
        )

        self.add_item(self.party_name)
        self.add_item(self.description)
        self.add_item(self.min_power)
        self.add_item(self.max_members)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            min_power = int(self.min_power.value)
            max_members = int(self.max_members.value)

            if max_members < 2 or max_members > 5:
                await interaction.followup.send("최대 인원은 2-5 사이여야 합니다!", ephemeral=True)
                return

            if min_power < 0:
                await interaction.followup.send("최소 전투력은 0 이상이어야 합니다!", ephemeral=True)
                return

        except ValueError:
            await interaction.followup.send("숫자를 올바르게 입력해주세요!", ephemeral=True)
            return

        # Check if user is already in a party
        existing_party = await self.bot.pool.fetchrow("""
            SELECT party_id FROM party_members pm
            JOIN parties p ON pm.party_id = p.party_id
            WHERE pm.user_id = $1 AND p.guild_id = $2 AND p.is_active = TRUE
        """, user_id, guild_id)

        if existing_party:
            await interaction.followup.send("이미 파티에 속해있습니다! 먼저 현재 파티에서 탈퇴해주세요.", ephemeral=True)
            return

        # Check user's combat power
        activities_cog = self.bot.get_cog('ActivitiesCog')
        user_power = await activities_cog.get_user_combat_power(user_id, guild_id)

        if user_power < min_power:
            await interaction.followup.send(
                f"파티를 생성하려면 최소 전투력을 충족해야 합니다!\n필요: {min_power:,}\n현재: {user_power:,}",
                ephemeral=True
            )
            return

        # Create party
        party_id = str(uuid.uuid4())

        await self.bot.pool.execute("""
            INSERT INTO parties (party_id, leader_id, guild_id, name, description, max_members, min_power)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, party_id, user_id, guild_id, self.party_name.value, self.description.value or None, max_members, min_power)

        # Add creator as first member
        await self.bot.pool.execute("""
            INSERT INTO party_members (party_id, user_id, role)
            VALUES ($1, $2, 'leader')
        """, party_id, user_id)

        embed = discord.Embed(
            title="✅ 파티 생성 완료!",
            description=f"**{self.party_name.value}** 파티가 생성되었습니다!",
            color=discord.Color.green()
        )

        embed.add_field(name="파티장", value=interaction.user.display_name, inline=True)
        embed.add_field(name="최소 전투력", value=f"{min_power:,}", inline=True)
        embed.add_field(name="최대 인원", value=f"{max_members}명", inline=True)

        if self.description.value:
            embed.add_field(name="설명", value=self.description.value, inline=False)

        embed.set_footer(text=f"파티 ID: {party_id}")

        await interaction.followup.send(embed=embed)


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
    """Adventure, Arena, Dungeon, and Party system"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger(__name__)

        # Adventure definitions
        self.adventures = {
            "forest": {
                "id": "forest",
                "name": "신비한 숲 탐험",
                "emoji": "🌲",
                "min_power": 1000,
                "max_power": 5000,
                "duration": 300,  # 5 minutes
                "rewards": {"coins": (50, 200), "exp": (10, 40)},
                "description": "초보자를 위한 평화로운 숲 탐험"
            },
            "cave": {
                "id": "cave",
                "name": "어둠의 동굴",
                "emoji": "🕳️",
                "min_power": 3000,
                "max_power": 10000,
                "duration": 600,  # 10 minutes
                "rewards": {"coins": (100, 400), "exp": (20, 80)},
                "description": "위험하지만 보상이 풍부한 동굴"
            },
            "volcano": {
                "id": "volcano",
                "name": "화산 정상 도전",
                "emoji": "🌋",
                "min_power": 8000,
                "max_power": 25000,
                "duration": 900,  # 15 minutes
                "rewards": {"coins": (300, 800), "exp": (50, 150)},
                "description": "고수만이 도전할 수 있는 화산"
            },
            "abyss": {
                "id": "abyss",
                "name": "심연의 구멍",
                "emoji": "🕳️",
                "min_power": 20000,
                "max_power": 100000,
                "duration": 1800,  # 30 minutes
                "rewards": {"coins": (1000, 3000), "exp": (200, 500)},
                "description": "최강자만이 살아남을 수 있는 심연"
            }
        }

        # Dungeon definitions
        self.dungeons = {
            "goblin_den": {
                "id": "goblin_den",
                "name": "고블린 소굴",
                "emoji": "👹",
                "difficulty": "쉬움",
                "min_power": 2000,
                "party_size": (1, 3),
                "duration": 600,
                "rewards": {"coins": (200, 500), "items": ["common", "rare"]},
                "description": "고블린들이 서식하는 작은 소굴"
            },
            "orc_fortress": {
                "id": "orc_fortress",
                "name": "오크 요새",
                "emoji": "🏰",
                "difficulty": "보통",
                "min_power": 8000,
                "party_size": (2, 4),
                "duration": 1200,
                "rewards": {"coins": (500, 1200), "items": ["rare", "epic"]},
                "description": "강력한 오크들의 요새"
            },
            "dragon_lair": {
                "id": "dragon_lair",
                "name": "드래곤 둥지",
                "emoji": "🐉",
                "difficulty": "어려움",
                "min_power": 25000,
                "party_size": (3, 5),
                "duration": 2400,
                "rewards": {"coins": (1500, 3000), "items": ["epic", "legendary"]},
                "description": "고대 드래곤이 잠들어 있는 둥지"
            },
            "void_temple": {
                "id": "void_temple",
                "name": "공허의 신전",
                "emoji": "⛩️",
                "difficulty": "지옥",
                "min_power": 50000,
                "party_size": (4, 5),
                "duration": 3600,
                "rewards": {"coins": (3000, 8000), "items": ["legendary", "mythic"]},
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

        self.bot.loop.create_task(self.setup_activities_system())

    async def setup_activities_system(self):
        """Initialize the activities system"""
        await self.bot.wait_until_ready()
        await self.setup_activities_database()

        # Check for any adventures that should have completed while bot was offline
        await self.check_completed_adventures()

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
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP,
                    success BOOLEAN DEFAULT FALSE,
                    rewards_coins INTEGER DEFAULT 0,
                    rewards_exp INTEGER DEFAULT 0,
                    combat_power INTEGER DEFAULT 0
                )
            """)

            # Arena stats (already exists, but ensure it's there)
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS arena_stats (
                    user_id BIGINT,
                    guild_id BIGINT,
                    tier VARCHAR(20) DEFAULT 'bronze',
                    rating INTEGER DEFAULT 1000,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    last_battle TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            # Dungeon progress (already exists, but ensure it's there)
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS dungeon_progress (
                    user_id BIGINT,
                    guild_id BIGINT,
                    dungeon_name VARCHAR(50),
                    completions INTEGER DEFAULT 0,
                    best_time INTEGER DEFAULT 0,
                    last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id, dungeon_name)
                )
            """)

            # Add this to your setup_activities_database method
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

            # Party system
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS parties (
                    party_id VARCHAR(36) PRIMARY KEY,
                    leader_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    max_members INTEGER DEFAULT 5,
                    min_power INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)

            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS party_members (
                    party_id VARCHAR(36),
                    user_id BIGINT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    role VARCHAR(20) DEFAULT 'member',
                    PRIMARY KEY (party_id, user_id),
                    FOREIGN KEY (party_id) REFERENCES parties(party_id) ON DELETE CASCADE
                )
            """)

            # Active adventures tracking
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS active_adventures (
                    user_id BIGINT,
                    guild_id BIGINT,
                    adventure_id VARCHAR(50),
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP,
                    message_id BIGINT,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

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

        # Check if user is already on an adventure
        active = await self.bot.pool.fetchrow(
            "SELECT * FROM active_adventures WHERE user_id = $1 AND guild_id = $2",
            user_id, guild_id
        )

        if active:
            # FIXED: Ensure both datetimes are timezone-aware for comparison
            end_time = ensure_timezone_aware(active['end_time'])
            current_time = datetime.now(timezone.utc)  # Already timezone-aware
            remaining_time = end_time - current_time

            if remaining_time.total_seconds() > 0:
                minutes = int(remaining_time.total_seconds() // 60)
                seconds = int(remaining_time.total_seconds() % 60)
                await interaction.followup.send(
                    f"⏰ 이미 모험을 진행 중입니다!\n남은 시간: {minutes}분 {seconds}초",
                    ephemeral=True
                )
                return

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
                value=f"{adventure['description']}\n필요 전투력: {adventure['min_power']:,}\n소요시간: {adventure['duration'] // 60}분",
                inline=False
            )

        view = AdventureView(self.bot, user_id, guild_id, adventures_data)
        await interaction.followup.send(embed=embed, view=view)

    async def start_adventure(self, interaction: discord.Interaction, adventure_id: str):
        """Start an adventure"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Check daily limit
        daily_limit_check = await self.check_daily_activity_limit(user_id, guild_id, "adventure")
        if not daily_limit_check:
            await interaction.followup.send("⚠️ 일일 모험 한도에 도달했습니다! (하루 최대 10회)", ephemeral=True)
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

        # Create timezone-aware datetimes consistently
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(seconds=adventure['duration'])

        # Store active adventure
        await self.bot.pool.execute("""
            INSERT INTO active_adventures (user_id, guild_id, adventure_id, start_time, end_time)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, guild_id) DO UPDATE SET
            adventure_id = EXCLUDED.adventure_id,
            start_time = EXCLUDED.start_time,
            end_time = EXCLUDED.end_time
        """, user_id, guild_id, adventure_id, start_time, end_time)

        embed = discord.Embed(
            title=f"{adventure['emoji']} 모험 시작!",
            description=f"**{adventure['name']}**에 출발했습니다!",
            color=discord.Color.blue()
        )
        embed.add_field(name="예상 소요시간", value=f"{adventure['duration'] // 60}분", inline=True)
        embed.add_field(name="성공 확률", value=f"{base_success_chance:.1f}%", inline=True)
        embed.add_field(name="전투력", value=f"{combat_power:,}", inline=True)

        # Format time for display - use UTC time to avoid timezone issues
        embed.set_footer(text=f"모험 완료 시각: {end_time.strftime('%H:%M')} UTC")

        await interaction.followup.send(embed=embed)

        # Schedule adventure completion
        await asyncio.sleep(adventure['duration'])
        await self.complete_adventure(user_id, guild_id, adventure_id, base_success_chance, combat_power)
    async def complete_adventure(self, user_id: int, guild_id: int, adventure_id: str, success_chance: float, combat_power: int):
        """Complete an adventure and give rewards"""
        try:
            adventure = self.adventures.get(adventure_id)
            if not adventure:
                return

            # Roll for success
            success = random.random() * 100 < success_chance

            rewards_coins = 0
            rewards_exp = 0

            if success:
                # Calculate rewards
                coin_range = adventure['rewards']['coins']
                exp_range = adventure['rewards']['exp']

                rewards_coins = random.randint(coin_range[0], coin_range[1])
                rewards_exp = random.randint(exp_range[0], exp_range[1])

                # Bonus for higher combat power
                power_bonus = min(2.0, combat_power / adventure['min_power'])
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

    @app_commands.command(name="아레나", description="다른 플레이어와 전투를 펼치세요!")
    async def arena(self, interaction: discord.Interaction):
        try:
            guild_id = interaction.guild.id
            if not config.is_feature_enabled(guild_id, 'casino_games'):
                await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
                return
        except Exception as e:
            self.logger.error(f"Arena command error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("아레나 시스템에 오류가 발생했습니다.", ephemeral=True)
            return

        if not self.check_channel(interaction, ARENA_CHANNEL_ID):
            arena_channel = self.bot.get_channel(ARENA_CHANNEL_ID)
            channel_mention = arena_channel.mention if arena_channel else f"<#{ARENA_CHANNEL_ID}>"
            await interaction.response.send_message(
                f"⚔️ 아레나는 {channel_mention} 채널에서만 이용할 수 있습니다!",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        user_id = interaction.user.id

        # Get or create arena stats
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

        # Get current tier info
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

    async def start_ranked_battle(self, interaction: discord.Interaction):
        """Start a ranked battle"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Check daily limit for arena battles
        daily_limit_check = await self.check_daily_activity_limit(user_id, guild_id, "arena")
        if not daily_limit_check:
            await interaction.followup.send("⚠️ 일일 아레나 한도에 도달했습니다! (하루 최대 20회)", ephemeral=True)
            return

        # Find opponent with similar rating
        user_stats = await self.bot.pool.fetchrow(
            "SELECT * FROM arena_stats WHERE user_id = $1 AND guild_id = $2",
            user_id, guild_id
        )

        # Get potential opponents (±200 rating range)
        opponents = await self.bot.pool.fetch("""
            SELECT user_id, rating FROM arena_stats 
            WHERE guild_id = $1 AND user_id != $2 
            AND rating BETWEEN $3 AND $4
            ORDER BY ABS(rating - $5)
            LIMIT 10
        """, guild_id, user_id, user_stats['rating'] - 200, user_stats['rating'] + 200, user_stats['rating'])

        if not opponents:
            # Create AI opponent
            ai_rating = user_stats['rating'] + random.randint(-50, 50)
            await self.battle_ai_opponent(interaction, user_stats, ai_rating)
        else:
            # Battle random opponent
            opponent_data = random.choice(opponents)
            await self.battle_player_opponent(interaction, user_stats, opponent_data)

    async def battle_ai_opponent(self, interaction: discord.Interaction, user_stats: dict, ai_rating: int):
        """Battle against AI opponent"""
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
            # Give coins reward
            coins_reward = random.randint(50, 200) + (new_streak * 10)
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(user_id, guild_id, coins_reward, "arena_win", "아레나 승리")
            embed.add_field(name="보상", value=f"{coins_reward:,} 코인", inline=True)

        await interaction.followup.send(embed=embed)

        # Increment arena battle count
        await self.increment_arena_battle_count(user_id, guild_id)

    async def battle_player_opponent(self, interaction: discord.Interaction, user_stats: dict, opponent_data: dict):
        """Battle against another player (simulated)"""
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
            coins_reward = random.randint(100, 300) + (new_streak * 15)
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(user_id, guild_id, coins_reward, "arena_win", "아레나 승리")
            embed.add_field(name="보상", value=f"{coins_reward:,} 코인", inline=True)

        await interaction.followup.send(embed=embed)

        # Increment arena battle count
        await self.increment_arena_battle_count(user_id, guild_id)

    async def start_practice_battle(self, interaction: discord.Interaction):
        """Start a practice battle (no rating change)"""
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
        embed.add_field(name="보상", value="경험 획득 (레이팅 변화 없음)", inline=False)

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
                value=f"{dungeon['description']}\n필요 전투력: {dungeon['min_power']:,}\n파티 크기: {party_info}\n소요시간: {dungeon['duration'] // 60}분",
                inline=False
            )

        view = DungeonView(self.bot, user_id, guild_id, available_dungeons)
        await interaction.followup.send(embed=embed, view=view)

    async def start_dungeon(self, interaction: discord.Interaction, dungeon_id: str):
        """Start a dungeon (solo for now, party system can be expanded later)"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Check daily limit
        daily_limit_check = await self.check_daily_activity_limit(user_id, guild_id, "dungeon")
        if not daily_limit_check:
            await interaction.followup.send("⚠️ 일일 던전 한도에 도달했습니다! (하루 최대 5회)", ephemeral=True)
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

        # Simulate dungeon run
        success = random.random() * 100 < base_success_chance
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

        embed = discord.Embed(
            title=f"{dungeon['emoji']} 던전 결과",
            color=discord.Color.green() if success else discord.Color.red()
        )

        if success:
            # Calculate rewards
            coin_range = dungeon['rewards']['coins']
            coins_reward = random.randint(coin_range[0], coin_range[1])

            # Time bonus
            time_ratio = completion_time / dungeon['duration']
            time_bonus = max(1.0, 2.0 - time_ratio)  # Faster = more rewards
            coins_reward = int(coins_reward * time_bonus)

            # Give rewards
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(user_id, guild_id, coins_reward, "dungeon", f"던전: {dungeon['name']}")

            # Chance for item reward
            item_chance = 30 + (power_ratio - 1) * 10  # Better chance with higher power
            if random.random() * 100 < item_chance:
                enhancement_cog = self.bot.get_cog('EnhancementCog')
                if enhancement_cog:
                    item_data = enhancement_cog.get_random_item()
                    if item_data:
                        await enhancement_cog.create_item_in_db(user_id, guild_id, item_data)
                        embed.add_field(name="🎁 보너스 아이템", value=f"{item_data['emoji']} {item_data['name']}", inline=True)

            embed.description = f"**{dungeon['name']}**을 성공적으로 클리어했습니다!"
            embed.add_field(name="완료 시간", value=f"{completion_time // 60}분 {completion_time % 60}초", inline=True)
            embed.add_field(name="획득 코인", value=f"{coins_reward:,}", inline=True)

        else:
            embed.description = f"**{dungeon['name']}** 공략에 실패했습니다..."
            embed.add_field(name="결과", value="보상 없음", inline=True)

        embed.add_field(name="성공 확률", value=f"{base_success_chance:.1f}%", inline=True)
        embed.add_field(name="전투력", value=f"{combat_power:,}", inline=True)

        await interaction.followup.send(embed=embed)

    async def check_daily_activity_limit(self, user_id: int, guild_id: int, activity_type: str) -> bool:
        """Check if user has exceeded daily activity limits"""
        try:
            # Define daily limits
            daily_limits = {
                "adventure": 10,  # 10 adventures per day
                "dungeon": 5,  # 5 dungeons per day
                "arena": 20  # 20 arena battles per day
            }

            limit = daily_limits.get(activity_type, 10)

            if activity_type == "adventure":
                count = await self.bot.pool.fetchval("""
                    SELECT COUNT(*) FROM adventure_logs 
                    WHERE user_id = $1 AND guild_id = $2 
                    AND DATE(start_time AT TIME ZONE 'UTC') = CURRENT_DATE
                """, user_id, guild_id)

            elif activity_type == "dungeon":
                count = await self.bot.pool.fetchval("""
                    SELECT COUNT(*) FROM dungeon_progress 
                    WHERE user_id = $1 AND guild_id = $2 
                    AND DATE(last_attempt AT TIME ZONE 'UTC') = CURRENT_DATE
                """, user_id, guild_id)
                if count is None:
                    count = 0

            elif activity_type == "arena":
                # IMPROVED: Create a separate table or use a different approach for arena battles
                # For now, we'll check from a daily_activity_limits table
                count = await self.bot.pool.fetchval("""
                    SELECT arena_count FROM daily_activity_limits
                    WHERE user_id = $1 AND guild_id = $2 AND activity_date = CURRENT_DATE
                """, user_id, guild_id)
                if count is None:
                    count = 0

            else:
                return True  # Unknown activity type, allow it

            return count < limit

        except Exception as e:
            self.logger.error(f"Daily limit check error: {e}")
            return True  # Allow on error to prevent blocking gameplay

    async def increment_arena_battle_count(self, user_id: int, guild_id: int):
        """Increment the daily arena battle count"""
        try:
            await self.bot.pool.execute("""
                INSERT INTO daily_activity_limits (user_id, guild_id, activity_date, arena_count)
                VALUES ($1, $2, CURRENT_DATE, 1)
                ON CONFLICT (user_id, guild_id, activity_date) 
                DO UPDATE SET arena_count = daily_activity_limits.arena_count + 1
            """, user_id, guild_id)
        except Exception as e:
            self.logger.error(f"Error incrementing arena battle count: {e}")

    async def check_completed_adventures(self):
        """Check for adventures that should be completed but haven't been processed"""
        try:
            current_time = datetime.now(timezone.utc)  # Ensure timezone-aware

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
    @app_commands.command(name="파티", description="파티를 생성하고 관리하세요!")
    async def party(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        if not self.check_channel(interaction, GUILD_CHANNEL_ID):
            guild_channel = self.bot.get_channel(GUILD_CHANNEL_ID)
            channel_mention = guild_channel.mention if guild_channel else f"<#{GUILD_CHANNEL_ID}>"
            await interaction.response.send_message(
                f"👥 파티 시스템은 {channel_mention} 채널에서만 이용할 수 있습니다!",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        user_id = interaction.user.id

        # Check if user is already in a party
        current_party = await self.bot.pool.fetchrow("""
            SELECT p.party_id, p.name, p.leader_id, COUNT(pm.user_id) as member_count, p.max_members
            FROM parties p
            LEFT JOIN party_members pm ON p.party_id = pm.party_id
            WHERE pm.user_id = $1 AND p.guild_id = $2 AND p.is_active = TRUE
            GROUP BY p.party_id, p.name, p.leader_id, p.max_members
        """, user_id, guild_id)

        embed = discord.Embed(
            title="👥 파티 시스템",
            color=discord.Color.blue()
        )

        if current_party:
            is_leader = current_party['leader_id'] == user_id
            leader = interaction.guild.get_member(current_party['leader_id'])
            leader_name = leader.display_name if leader else "알 수 없는 사용자"

            embed.add_field(name="현재 파티", value=current_party['name'], inline=True)
            embed.add_field(name="파티장", value=leader_name, inline=True)
            embed.add_field(name="인원", value=f"{current_party['member_count']}/{current_party['max_members']}", inline=True)
            embed.add_field(name="권한", value="파티장" if is_leader else "파티원", inline=True)
        else:
            embed.description = "현재 파티에 속해있지 않습니다.\n파티를 생성하거나 기존 파티에 참여해보세요!"

        view = PartyView(self.bot, user_id, guild_id, current_party)
        await interaction.followup.send(embed=embed, view=view)

    async def create_party(self, interaction: discord.Interaction):
        """Create a new party"""
        await interaction.response.send_modal(CreatePartyModal(self.bot))

    async def show_available_parties(self, interaction: discord.Interaction):
        """Show available parties to join"""
        await interaction.response.defer()
        guild_id = interaction.guild.id

        # Get parties that aren't full
        parties = await self.bot.pool.fetch("""
            SELECT p.party_id, p.name, p.description, p.leader_id, p.min_power, p.created_at,
                   COUNT(pm.user_id) as current_members, p.max_members
            FROM parties p
            LEFT JOIN party_members pm ON p.party_id = pm.party_id
            WHERE p.guild_id = $1 AND p.is_active = TRUE
            GROUP BY p.party_id, p.name, p.description, p.leader_id, p.min_power, p.created_at, p.max_members
            HAVING COUNT(pm.user_id) < p.max_members
            ORDER BY p.created_at DESC
            LIMIT 10
        """, guild_id)

        if not parties:
            await interaction.followup.send("현재 참여 가능한 파티가 없습니다!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔍 참여 가능한 파티 목록",
            color=discord.Color.green()
        )

        guild = interaction.guild
        for party in parties:
            leader = guild.get_member(party['leader_id'])
            leader_name = leader.display_name if leader else "알 수 없는 사용자"

            party_info = f"파티장: {leader_name}\n"
            party_info += f"인원: {party['current_members']}/{party['max_members']}\n"
            party_info += f"최소 전투력: {party['min_power']:,}\n"
            if party['description']:
                party_info += f"설명: {party['description']}"

            embed.add_field(
                name=f"👥 {party['name']}",
                value=party_info,
                inline=False
            )

        await interaction.followup.send(embed=embed)

    async def show_my_party(self, interaction: discord.Interaction):
        """Show current party details"""
        await interaction.response.defer()
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Get party info with members
        party_info = await self.bot.pool.fetchrow("""
            SELECT p.party_id, p.name, p.description, p.leader_id, p.min_power, p.max_members, p.created_at
            FROM parties p
            JOIN party_members pm ON p.party_id = pm.party_id
            WHERE pm.user_id = $1 AND p.guild_id = $2 AND p.is_active = TRUE
        """, user_id, guild_id)

        if not party_info:
            await interaction.followup.send("현재 파티에 속해있지 않습니다!", ephemeral=True)
            return

        # Get all party members
        members = await self.bot.pool.fetch("""
            SELECT pm.user_id, pm.role, pm.joined_at
            FROM party_members pm
            WHERE pm.party_id = $1
            ORDER BY pm.joined_at
        """, party_info['party_id'])

        embed = discord.Embed(
            title=f"👥 {party_info['name']}",
            color=discord.Color.blue()
        )

        if party_info['description']:
            embed.description = party_info['description']

        guild = interaction.guild
        leader = guild.get_member(party_info['leader_id'])
        leader_name = leader.display_name if leader else "알 수 없는 사용자"

        embed.add_field(name="파티장", value=leader_name, inline=True)
        embed.add_field(name="최소 전투력", value=f"{party_info['min_power']:,}", inline=True)
        embed.add_field(name="생성일", value=party_info['created_at'].strftime("%Y-%m-%d"), inline=True)

        # List members with their combat power
        members_text = ""
        for member in members:
            member_user = guild.get_member(member['user_id'])
            if member_user:
                combat_power = await self.get_user_combat_power(member['user_id'], guild_id)
                role_emoji = "👑" if member['user_id'] == party_info['leader_id'] else "👤"
                members_text += f"{role_emoji} {member_user.display_name} (전투력: {combat_power:,})\n"

        embed.add_field(name=f"파티원 ({len(members)}/{party_info['max_members']})", value=members_text or "파티원 없음", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="파티참여", description="파티 ID로 파티에 참여합니다.")
    @app_commands.describe(party_id="참여할 파티의 ID")
    async def join_party(self, interaction: discord.Interaction, party_id: str):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id

        # Check if party exists and has space
        party_info = await self.bot.pool.fetchrow("""
            SELECT p.party_id, p.name, p.min_power, p.max_members, COUNT(pm.user_id) as current_members
            FROM parties p
            LEFT JOIN party_members pm ON p.party_id = pm.party_id
            WHERE p.party_id = $1 AND p.guild_id = $2 AND p.is_active = TRUE
            GROUP BY p.party_id, p.name, p.min_power, p.max_members
        """, party_id, guild_id)

        if not party_info:
            await interaction.followup.send("존재하지 않거나 비활성화된 파티입니다.", ephemeral=True)
            return

        if party_info['current_members'] >= party_info['max_members']:
            await interaction.followup.send("파티가 가득 찼습니다.", ephemeral=True)
            return

        # Check if user is already in a party
        existing = await self.bot.pool.fetchrow("""
            SELECT party_id FROM party_members pm
            JOIN parties p ON pm.party_id = p.party_id
            WHERE pm.user_id = $1 AND p.guild_id = $2 AND p.is_active = TRUE
        """, user_id, guild_id)

        if existing:
            await interaction.followup.send("이미 다른 파티에 속해있습니다!", ephemeral=True)
            return

        # Check combat power requirement
        user_power = await self.get_user_combat_power(user_id, guild_id)
        if user_power < party_info['min_power']:
            await interaction.followup.send(
                f"전투력이 부족합니다!\n필요: {party_info['min_power']:,}\n현재: {user_power:,}",
                ephemeral=True
            )
            return

        # Join party
        await self.bot.pool.execute("""
            INSERT INTO party_members (party_id, user_id, role)
            VALUES ($1, $2, 'member')
        """, party_id, user_id)

        embed = discord.Embed(
            title="✅ 파티 참여 완료!",
            description=f"**{party_info['name']}** 파티에 참여했습니다!",
            color=discord.Color.green()
        )

        embed.add_field(name="현재 인원", value=f"{party_info['current_members'] + 1}/{party_info['max_members']}", inline=True)
        embed.add_field(name="내 전투력", value=f"{user_power:,}", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="파티탈퇴", description="현재 파티에서 탈퇴합니다.")
    async def leave_party(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠️ 이 서버에서는 활동 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id

        # Get current party
        party_info = await self.bot.pool.fetchrow("""
            SELECT p.party_id, p.name, p.leader_id
            FROM parties p
            JOIN party_members pm ON p.party_id = pm.party_id
            WHERE pm.user_id = $1 AND p.guild_id = $2 AND p.is_active = TRUE
        """, user_id, guild_id)

        if not party_info:
            await interaction.followup.send("현재 파티에 속해있지 않습니다.", ephemeral=True)
            return

        # Check if user is the leader
        if party_info['leader_id'] == user_id:
            # Transfer leadership or disband party
            other_members = await self.bot.pool.fetch("""
                SELECT user_id FROM party_members
                WHERE party_id = $1 AND user_id != $2
                ORDER BY joined_at
                LIMIT 1
            """, party_info['party_id'], user_id)

            if other_members:
                # Transfer leadership to the earliest member
                new_leader_id = other_members[0]['user_id']
                await self.bot.pool.execute("""
                    UPDATE parties SET leader_id = $1 WHERE party_id = $2
                """, new_leader_id, party_info['party_id'])

                await self.bot.pool.execute("""
                    UPDATE party_members SET role = 'leader' WHERE party_id = $1 AND user_id = $2
                """, party_info['party_id'], new_leader_id)
            else:
                # No other members, disband party
                await self.bot.pool.execute("""
                    UPDATE parties SET is_active = FALSE WHERE party_id = $1
                """, party_info['party_id'])

        # Remove user from party
        await self.bot.pool.execute("""
            DELETE FROM party_members WHERE party_id = $1 AND user_id = $2
        """, party_info['party_id'], user_id)

        embed = discord.Embed(
            title="✅ 파티 탈퇴 완료!",
            description=f"**{party_info['name']}** 파티에서 탈퇴했습니다.",
            color=discord.Color.orange()
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

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

        combat_power = await self.get_user_combat_power(target_id, guild_id)

        embed = discord.Embed(
            title=f"📊 {target_user.display_name}의 활동 기록",
            color=discord.Color.blue()
        )

        embed.add_field(name="⚡ 현재 전투력", value=f"{combat_power:,}", inline=True)

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
                best_time_text = f"{dungeon['best_time'] // 60}분 {dungeon['best_time'] % 60}초" if dungeon['best_time'] > 0 else "기록 없음"
                dungeon_text += f"**{name}**: {dungeon['completions']}회 클리어\n최고 기록: {best_time_text}\n"
        else:
            dungeon_text = "던전 기록 없음"

        embed.add_field(name="🏰 던전 기록", value=dungeon_text or "던전 기록 없음", inline=False)

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ActivitiesCog(bot))