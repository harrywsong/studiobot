# cogs/enhance.py
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


class EnhancementView(discord.ui.View):
    """Interactive enhancement interface"""

    def __init__(self, bot, user_id, guild_id, item_data, item_row):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.item_data = item_data
        self.item_row = item_row
        self.enhancement_cog = bot.get_cog('EnhancementCog')
        self.message = None # <--- ADD THIS LINE


    async def on_timeout(self) -> None:
        # Disable all buttons when the view times out
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        # Try to edit the message to reflect the change, but don't fail if the message is gone
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass  # Message was deleted

    @discord.ui.button(label="⭐ 강화하기", style=discord.ButtonStyle.primary, emoji="⚡")
    async def enhance_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 강화할 수 없습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        await self.enhancement_cog.handle_enhancement(interaction, self.item_row['item_id'])

    @discord.ui.button(label="🔍 상세정보", style=discord.ButtonStyle.secondary, emoji="🔎")
    async def detailed_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 조회할 수 없습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        await self.enhancement_cog.show_item_details(interaction, self.item_row)

    @discord.ui.button(label="💰 마켓 판매", style=discord.ButtonStyle.secondary)
    async def sell_to_market(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 판매할 수 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        await self.enhancement_cog.show_market_sell_confirmation(interaction, self.item_row['item_id'])


class MarketSellConfirmView(discord.ui.View):
    """Confirmation view for automatic market pricing"""

    def __init__(self, bot, item_id: str, calculated_price: int, template: dict, enhancement_level: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.item_id = item_id
        self.calculated_price = calculated_price
        self.template = template
        self.enhancement_level = enhancement_level

    @discord.ui.button(label="✅ 판매 확인", style=discord.ButtonStyle.success)
    async def confirm_sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        enhancement_cog = self.bot.get_cog('EnhancementCog')
        if enhancement_cog:
            await enhancement_cog.list_item_on_market(interaction, self.item_id, self.calculated_price)

    @discord.ui.button(label="❌ 취소", style=discord.ButtonStyle.danger)
    async def cancel_sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("판매가 취소되었습니다.", ephemeral=True)


class EquipmentSelectView(discord.ui.View):
    """Equipment slot selection view"""

    def __init__(self, bot, user_id, guild_id, items_by_slot):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.items_by_slot = items_by_slot
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        # Add buttons for each slot type
        slot_emojis = {
            "무기": "⚔️", "보조무기": "🛡️", "모자": "👑", "상의": "👕",
            "하의": "👖", "신발": "👟", "장갑": "🧤", "망토": "🦹",
            "목걸이": "📿", "귀걸이": "💎", "반지": "💍", "벨트": "⚡"
        }

        row = 0
        for slot_type, items in items_by_slot.items():
            if len(items) > 0:
                button = discord.ui.Button(
                    label=f"{slot_emojis.get(slot_type, '📦')} {slot_type} ({len(items)})",
                    custom_id=f"equip_slot_{slot_type}",
                    style=discord.ButtonStyle.secondary,
                    row=row
                )
                button.callback = self.create_slot_callback(slot_type)
                self.add_item(button)

                row = (row + 1) % 4  # Max 4 rows

    def create_slot_callback(self, slot_type: str):
        async def slot_callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("다른 사용자의 장비를 관리할 수 없습니다.", ephemeral=True)
                return

            await self.enhancement_cog.show_slot_items(interaction, slot_type, self.items_by_slot[slot_type])

        return slot_callback


class SlotItemsView(discord.ui.View):
    """View for items in a specific slot"""

    def __init__(self, bot, user_id, guild_id, slot_type: str, items: List):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.slot_type = slot_type
        self.items = items
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        # Add buttons for each item
        for i, item_data in enumerate(items[:20]):  # Limit to 20 items
            item_row, template = item_data
            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            equipped_text = "🔒" if item_row['is_equipped'] else ""

            button = discord.ui.Button(
                label=f"{template['emoji']}{template['name'][:15]}{enhancement_text}{equipped_text}",
                custom_id=f"item_{item_row['item_id']}",
                style=discord.ButtonStyle.primary if item_row['is_equipped'] else discord.ButtonStyle.secondary,
                row=i // 5
            )
            button.callback = self.create_item_callback(item_row['item_id'])
            self.add_item(button)

    def create_item_callback(self, item_id: str):
        async def item_callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("다른 사용자의 아이템을 관리할 수 없습니다.", ephemeral=True)
                return

            await self.enhancement_cog.show_item_management(interaction, item_id)

        return item_callback


class ItemManagementView(discord.ui.View):
    """Individual item management view"""

    def __init__(self, bot, user_id, guild_id, item_row, template):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.item_row = item_row
        self.template = template
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        # --- REORDERED BUTTONS FOR CONSISTENCY ---
        # Order: Enhance, Equip/Unequip, Sell

        # Enhancement button
        enhance_button = discord.ui.Button(
            label="⭐ 강화하기",
            style=discord.ButtonStyle.primary,
            custom_id="enhance_item",
            emoji="⚡"
        )
        enhance_button.callback = self.enhance_item
        self.add_item(enhance_button)

        # Equip/Unequip button
        if item_row['is_equipped']:
            equip_button = discord.ui.Button(
                label="⚪ 장착 해제",
                style=discord.ButtonStyle.danger,
                custom_id="unequip_item"
            )
        else:
            equip_button = discord.ui.Button(
                label="🔹 장착하기",
                style=discord.ButtonStyle.success,
                custom_id="equip_item"
            )
        equip_button.callback = self.toggle_equip
        self.add_item(equip_button)

        # Market sell button
        market_button = discord.ui.Button(
            label="💰 마켓 판매",
            style=discord.ButtonStyle.secondary,
            custom_id="market_sell"
        )
        market_button.callback = self.market_sell
        self.add_item(market_button)

    async def toggle_equip(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 장비를 관리할 수 없습니다.", ephemeral=True)
            return

        if self.item_row['is_equipped']:
            await self.enhancement_cog.unequip_item(interaction, self.item_row['item_id'])
        else:
            await self.enhancement_cog.equip_item(interaction, self.item_row['item_id'])

    async def enhance_item(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 강화할 수 없습니다.", ephemeral=True)
            return

        await self.enhancement_cog.handle_enhancement(interaction, self.item_row['item_id'])

    async def market_sell(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 판매할 수 없습니다.", ephemeral=True)
            return

        await self.enhancement_cog.show_market_sell_confirmation(interaction, self.item_row['item_id'])

    async def on_timeout(self) -> None:
        # Disable all buttons when the view times out
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


class MarketplaceView(discord.ui.View):
    """Marketplace viewing and purchasing interface"""

    def __init__(self, bot, market_items: List):
        super().__init__(timeout=None)
        self.bot = bot
        self.market_items = market_items
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        # Add purchase buttons for each item
        for i, item_data in enumerate(market_items[:20]):  # Limit to 20 items
            market_entry, template = item_data
            enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry[
                                                                              'enhancement_level'] > 0 else ""

            button = discord.ui.Button(
                label=f"{template['emoji']}{template['name'][:12]}{enhancement_text} {market_entry['price']:,}💰",
                custom_id=f"buy_{market_entry['market_id']}",
                style=discord.ButtonStyle.success,
                row=i // 5
            )
            button.callback = self.create_purchase_callback(market_entry['market_id'])
            self.add_item(button)

    def create_purchase_callback(self, market_id: str):
        async def purchase_callback(interaction: discord.Interaction):
            await self.enhancement_cog.handle_market_purchase(interaction, market_id)

        return purchase_callback


class CharacterView(discord.ui.View):
    """Enhanced character sheet view"""

    def __init__(self, bot, user_id, guild_id, character_data, equipped_items):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.character_data = character_data
        self.equipped_items = equipped_items

    @discord.ui.button(label="🎒 인벤토리", style=discord.ButtonStyle.secondary)
    async def view_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 인벤토리를 볼 수 없습니다.", ephemeral=True)
            return

        enhancement_cog = self.bot.get_cog('EnhancementCog')
        if enhancement_cog:
            await enhancement_cog.show_inventory(interaction)

    @discord.ui.button(label="⚔️ 장비 관리", style=discord.ButtonStyle.primary)
    async def manage_equipment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 장비를 관리할 수 없습니다.", ephemeral=True)
            return

        enhancement_cog = self.bot.get_cog('EnhancementCog')
        if enhancement_cog:
            await enhancement_cog.show_equipment_manager(interaction)


class EnhancementCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger(__name__)
        self.item_pool = self.load_item_pool()

        self.character_classes = {
            "전사": {"name": "전사", "emoji": "⚔️", "primary_stats": ["str", "att"],
                   "description": "강력한 물리 공격력을 가진 근접 전투의 달인"},
            "법사": {"name": "법사", "emoji": "🔮", "primary_stats": ["int", "m_att"],
                   "description": "마법으로 적을 제압하는 지적인 전투원"},
            "도적": {"name": "도적", "emoji": "🗡️", "primary_stats": ["dex", "att"], "description": "민첩함과 치명타로 승부하는 암살자"},
            "궁수": {"name": "궁수", "emoji": "🏹", "primary_stats": ["dex", "att"], "description": "원거리에서 정확한 공격을 가하는 저격수"},
            "해적": {"name": "해적", "emoji": "🏴‍☠️", "primary_stats": ["str", "dex"],
                   "description": "다양한 무기와 스킬을 활용하는 자유로운 모험가"}
        }

        self.item_rarities = {
            "일반": {"name": "일반", "color": 0x808080, "weight": 45},
            "고급": {"name": "고급", "color": 0x00FF00, "weight": 30},
            "희귀": {"name": "희귀", "color": 0x0080FF, "weight": 15},
            "영웅": {"name": "영웅", "color": 0x8000FF, "weight": 7},
            "고유": {"name": "고유", "color": 0xFF8000, "weight": 2.5},
            "전설": {"name": "전설", "color": 0xFF0000, "weight": 0.4},
            "신화": {"name": "신화", "color": 0xFFD700, "weight": 0.1}
        }

        self.equipment_slots = [
            "무기", "보조무기", "모자", "상의", "하의", "신발",
            "장갑", "망토", "목걸이", "귀걸이", "반지", "벨트"
        ]

        self.starforce_rates = {
            0: (95, 5, 0), 1: (90, 10, 0), 2: (85, 15, 0), 3: (85, 15, 0), 4: (80, 20, 0),
            5: (75, 25, 0), 6: (70, 30, 0), 7: (65, 35, 0), 8: (60, 40, 0), 9: (55, 45, 0),
            10: (50, 45, 5), 11: (45, 50, 5), 12: (40, 55, 5), 13: (35, 60, 5), 14: (30, 63, 7),
            15: (30, 67, 3), 16: (30, 67.9, 2.1), 17: (30, 67.9, 2.1), 18: (30, 67.2, 2.8), 19: (30, 67.2, 2.8),
            20: (30, 63, 7), 21: (30, 63, 7), 22: (3, 77.6, 19.4), 23: (2, 68.6, 29.4), 24: (1, 59.4, 39.6)
        }

        self.enhancement_costs = {
            0: 10, 1: 15, 2: 20, 3: 25, 4: 30,
            5: 35, 6: 40, 7: 45, 8: 50, 9: 60,
            10: 70, 11: 80, 12: 90, 13: 100, 14: 120,
            15: 140, 16: 160, 17: 180, 18: 200, 19: 220,
            20: 250, 21: 280, 22: 350, 23: 450, 24: 600
        }

        self.fail_streaks = {}
        self.marketplace_channel_id = 1421286971623477422
        self.showoff_channel_id = 1421290649277435904
        self.bot.loop.create_task(self.setup_system())

    def load_item_pool(self) -> List[Dict]:
        """Load the massive item pool from a static JSON file."""
        cog_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(cog_dir, '..', 'data', 'item_templates.json')

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                items = json.load(f)
                valid_items = []
                for item in items:
                    if 'id' in item and item['id'] is not None:
                        if isinstance(item['id'], str):
                            try:
                                item['id'] = int(item['id'])
                            except ValueError:
                                self.logger.warning(
                                    f"Skipping item with non-integer ID: {item.get('name', 'Unnamed Item')}")
                                continue
                        valid_items.append(item)
                    else:
                        self.logger.warning(
                            f"Skipping item due to missing 'id': {item.get('name', 'Unnamed Item')}")
                self.logger.info(f"Loaded {len(valid_items)} valid items from {file_path}.")
                return valid_items
        except FileNotFoundError:
            self.logger.error(f"FATAL: item_templates.json not found at {file_path}. The item pool is empty.")
            return []
        except Exception as e:
            self.logger.error(f"Error loading item_templates.json: {e}")
            return []

    # ... (all other helper functions like show_detailed_item_info, get_rarity_multiplier, etc. remain the same) ...
    async def show_detailed_item_info(self, interaction: discord.Interaction, item_id: str):
        """Show detailed item information"""
        await self.show_item_management(interaction, item_id)

    def get_rarity_multiplier(self, rarity: str) -> float:
        """Get stat multiplier based on rarity"""
        multipliers = {
            "일반": 1.0, "고급": 1.3, "희귀": 1.6, "영웅": 2.0,
            "고유": 2.5, "전설": 3.2, "신화": 4.0
        }
        return multipliers.get(rarity, 1.0)

    def calculate_base_price(self, rarity: str, tier: int) -> int:
        """Calculate base selling price"""
        rarity_prices = {
            "일반": 100, "고급": 250, "희귀": 500, "영웅": 1000,
            "고유": 2000, "전설": 5000, "신화": 10000
        }
        base = rarity_prices.get(rarity, 100)
        return int(base * (tier + 1) * 1.5)

    def calculate_market_price(self, template: Dict, enhancement_level: int) -> int:
        """Calculate automatic market price based on item stats and enhancement"""
        base_price = template['base_price']
        enhancement_multiplier = 1 + (enhancement_level * 0.15)
        rarity_market_multipliers = {
            "일반": 1.0, "고급": 1.5, "희귀": 2.2, "영웅": 3.5,
            "고유": 5.5, "전설": 8.0, "신화": 12.0
        }
        rarity_multiplier = rarity_market_multipliers.get(template['rarity'], 1.0)
        final_price = int(base_price * enhancement_multiplier * rarity_multiplier)
        min_price = 5 + (enhancement_level * 10)
        return max(final_price, min_price)

    def calculate_combat_power(self, stats: Dict[str, int], character_class: str) -> int:
        """Calculate total combat power based on stats and class"""
        power = 0
        power += stats["str"] * 4
        power += stats["dex"] * 4
        power += stats["int"] * 4
        power += stats["luk"] * 3
        power += stats["att"] * 15
        power += stats["m_att"] * 15
        class_multipliers = {
            "전사": {"str": 1.5, "att": 1.3},
            "법사": {"int": 1.5, "m_att": 1.3},
            "도적": {"dex": 1.4, "att": 1.2, "luk": 1.3},
            "궁수": {"dex": 1.5, "att": 1.2},
            "해적": {"str": 1.2, "dex": 1.2, "att": 1.1}
        }
        multipliers = class_multipliers.get(character_class, {})
        for stat, value in stats.items():
            if stat in multipliers:
                power += int(value * multipliers[stat])
        return max(1, int(power))

    def get_random_item(self) -> Dict[str, Any]:
        """Get a random item based on rarity weights using random.choices."""
        items = self.item_pool
        if not items:
            return None
        rarity_weights = {
            r: data['weight'] for r, data in self.item_rarities.items()
        }
        weights = [rarity_weights.get(item['rarity'], 0) for item in items]
        chosen_item = random.choices(items, weights=weights, k=1)[0]
        return chosen_item.copy()

    async def setup_system(self):
        """시스템 초기화"""
        await self.bot.wait_until_ready()
        await self.setup_database()
        await self.setup_marketplace_message()

    async def setup_database(self):
        """데이터베이스 테이블 생성"""
        try:
            # Character table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_characters (
                    user_id BIGINT, guild_id BIGINT, character_class VARCHAR(20) NOT NULL,
                    last_class_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            # Enhanced items table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_items (
                    item_id VARCHAR(50) PRIMARY KEY, user_id BIGINT NOT NULL, guild_id BIGINT NOT NULL,
                    template_id INTEGER NOT NULL, enhancement_level INTEGER DEFAULT 0, is_equipped BOOLEAN DEFAULT FALSE,
                    equipped_slot VARCHAR(20), fail_streak INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_enhanced TIMESTAMP
                )
            """)
            # Equipment slots table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_equipment (
                    user_id BIGINT, guild_id BIGINT, slot_name VARCHAR(20), item_id VARCHAR(50),
                    equipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, guild_id, slot_name),
                    FOREIGN KEY (item_id) REFERENCES user_items(item_id) ON DELETE SET NULL
                )
            """)
            # Enhancement logs
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS enhancement_logs (
                    log_id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, guild_id BIGINT NOT NULL,
                    item_id VARCHAR(50) NOT NULL, old_level INTEGER NOT NULL, new_level INTEGER NOT NULL,
                    result VARCHAR(20) NOT NULL, cost INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Marketplace table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS marketplace (
                    market_id VARCHAR(50) PRIMARY KEY, seller_id BIGINT NOT NULL, guild_id BIGINT NOT NULL,
                    item_id VARCHAR(50) NOT NULL, template_id INTEGER NOT NULL, enhancement_level INTEGER NOT NULL,
                    price INTEGER NOT NULL, listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES user_items(item_id) ON DELETE CASCADE
                )
            """)
            # Create indexes
            await self.bot.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_items_user_guild ON user_items(user_id, guild_id);")
            await self.bot.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_equipment_user_guild ON user_equipment(user_id, guild_id);")
            await self.bot.pool.execute(
                "CREATE INDEX IF NOT EXISTS idx_marketplace_guild ON marketplace(guild_id, listed_at DESC);")
            self.logger.info("강화 시스템 데이터베이스가 준비되었습니다.")
        except Exception as e:
            self.logger.error(f"데이터베이스 설정 실패: {e}")

    async def setup_marketplace_message(self):
        """Setup marketplace message"""
        try:
            channel = self.bot.get_channel(self.marketplace_channel_id)
            if not channel:
                self.logger.error(f"Marketplace channel {self.marketplace_channel_id} not found")
                return
            async for message in channel.history(limit=10):
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                        await asyncio.sleep(0.5)
                    except:
                        pass
            await self.create_marketplace_message()
        except Exception as e:
            self.logger.error(f"Marketplace setup error: {e}")

    async def create_marketplace_message(self):
        """Create/update marketplace message"""
        try:
            channel = self.bot.get_channel(self.marketplace_channel_id)
            if not channel: return
            market_items = await self.get_marketplace_items()
            embed = discord.Embed(title="🏪 아이템 마켓플레이스", description="다른 플레이어들이 판매하는 아이템을 구매해보세요!",
                                  color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
            if not market_items:
                embed.add_field(name="📦 현재 판매중인 아이템이 없습니다", value="다른 플레이어들이 아이템을 올릴 때까지 기다려주세요!", inline=False)
                await channel.send(embed=embed)
                return
            items_text = ""
            for i, (market_entry, template) in enumerate(market_items[:10]):
                rarity_info = self.item_rarities[template['rarity']]
                enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry[
                                                                                  'enhancement_level'] > 0 else ""
                items_text += f"**{i + 1}.** {template['emoji']} **{template['name']}** {enhancement_text}\n"
                items_text += f"   {rarity_info['name']} | {template['slot_type']} | 💰 **{market_entry['price']:,}** 코인\n"
                items_text += f"   판매자: <@{market_entry['seller_id']}>\n\n"
            embed.add_field(name="🛒 판매중인 아이템", value=items_text or "판매중인 아이템이 없습니다.", inline=False)
            embed.set_footer(text="아래 버튼을 눌러 아이템을 구매하세요! (10분마다 자동 갱신)")
            view = MarketplaceView(self.bot, market_items[:10])
            await channel.send(embed=embed, view=view)
        except Exception as e:
            self.logger.error(f"Marketplace message creation error: {e}")

    async def get_marketplace_items(self) -> List[Tuple]:
        """Get current marketplace items"""
        try:
            query = "SELECT m.market_id, m.seller_id, m.template_id, m.enhancement_level, m.price, m.listed_at, m.guild_id FROM marketplace m ORDER BY m.listed_at DESC LIMIT 20"
            rows = await self.bot.pool.fetch(query)
            items = []
            for row in rows:
                template = self.get_item_template(row['template_id'])
                if template:
                    items.append((row, template))
            return items
        except Exception as e:
            self.logger.error(f"Error getting marketplace items: {e}")
            return []

    async def get_user_character(self, user_id: int, guild_id: int) -> Optional[Dict]:
        """사용자 캐릭터 정보 조회"""
        try:
            query = "SELECT character_class, last_class_change, created_at FROM user_characters WHERE user_id = $1 AND guild_id = $2"
            row = await self.bot.pool.fetchrow(query, user_id, guild_id)
            if row:
                return {'class': row['character_class'], 'last_change': row['last_class_change'],
                        'created_at': row['created_at']}
            return None
        except Exception as e:
            self.logger.error(f"캐릭터 조회 오류: {e}", extra={'guild_id': guild_id})
            return None

    async def create_item_in_db(self, user_id: int, guild_id: int, item_data: Dict) -> str:
        """데이터베이스에 아이템 생성"""
        try:
            item_id = str(uuid.uuid4())[:8]
            await self.bot.pool.execute(
                "INSERT INTO user_items (item_id, user_id, guild_id, template_id, enhancement_level) VALUES ($1, $2, $3, $4, $5)",
                item_id, user_id, guild_id, item_data['id'], 0)
            return item_id
        except Exception as e:
            self.logger.error(f"아이템 생성 오류: {e}", extra={'guild_id': guild_id})
            return ""

    def get_item_template(self, template_id: int) -> Optional[Dict]:
        """아이템 템플릿 조회"""
        for item in self.item_pool:
            if item['id'] == template_id:
                return item
        return None

    async def handle_enhancement(self, interaction: discord.Interaction, item_id: str):
        """Handle item enhancement with MapleStory-style rates"""

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            # First, get item information
            item_row = await self.bot.pool.fetchrow(
                "SELECT item_id, template_id, enhancement_level, fail_streak, user_id FROM user_items WHERE item_id = $1 AND user_id = $2 AND guild_id = $3",
                item_id, user_id, guild_id)

            if not item_row:
                await interaction.followup.send("⚠ 아이템을 찾을 수 없습니다.")
                return

            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("⚠ 아이템 정보를 불러올 수 없습니다.")
                return

            current_level = item_row['enhancement_level']
            if current_level >= 24:
                await interaction.followup.send("⚠ 최대 강화 레벨에 도달했습니다.")
                return

            cost = self.enhancement_costs.get(current_level, 1000)
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                await interaction.followup.send("⚠ 코인 시스템을 사용할 수 없습니다.")
                return

            # Check if user has enough coins
            current_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if current_coins < cost:
                await interaction.followup.send(
                    f"⚠ 강화 비용이 부족합니다!\n필요: {cost:,} 코인\n보유: {current_coins:,} 코인"
                )
                return

            # Calculate enhancement result
            fail_streak = item_row['fail_streak'] or 0
            rates = self.starforce_rates.get(current_level, (30, 67, 3))
            result, new_level, new_fail_streak, result_text, result_color = "", 0, 0, "", discord.Color.default()

            if fail_streak >= 2:
                result, new_level, new_fail_streak, result_text, result_color = (
                    "success", current_level + 1, 0, "✨ **보장된 성공!** ✨", discord.Color.gold()
                )
            else:
                success_rate, fail_rate, _ = rates
                roll = random.uniform(0, 100)
                if roll <= success_rate:
                    result, new_level, new_fail_streak, result_text, result_color = (
                        "success", current_level + 1, 0, "✅ **강화 성공!**", discord.Color.green()
                    )
                elif roll <= success_rate + fail_rate:
                    new_level_on_fail = current_level - 1 if current_level in [15, 20] else current_level
                    result, new_level, new_fail_streak, result_text, result_color = (
                        "fail", new_level_on_fail, fail_streak + 1, "⚠ **강화 실패**", discord.Color.red()
                    )
                else:
                    result, new_level, new_fail_streak, result_text, result_color = (
                        "destroy", -1, 0, "💥 **아이템 파괴!**", discord.Color.dark_red()
                    )

            # Deduct coins
            description = f"강화: {template['name']}"
            coin_removal_success = await coins_cog.remove_coins(user_id, guild_id, cost, "enhancement", description)
            if not coin_removal_success:
                current_coins_recheck = await coins_cog.get_user_coins(user_id, guild_id)
                await interaction.followup.send(
                    f"⚠ 코인 차감에 실패했습니다.\n현재 잔액: {current_coins_recheck:,} 코인\n필요: {cost:,} 코인"
                )
                return

            # Update item state
            if result in ["success", "fail"]:
                await self.bot.pool.execute(
                    "UPDATE user_items SET enhancement_level = $1, fail_streak = $2, last_enhanced = CURRENT_TIMESTAMP WHERE item_id = $3",
                    new_level, new_fail_streak, item_id
                )
            elif result == "destroy":
                await self.bot.pool.execute("DELETE FROM user_items WHERE item_id = $1", item_id)

            # Log the enhancement
            await self.bot.pool.execute(
                "INSERT INTO enhancement_logs (user_id, guild_id, item_id, old_level, new_level, result, cost) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                user_id, guild_id, item_id, current_level, new_level, result, cost
            )

            # Create embed
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(title=result_text, color=result_color, timestamp=datetime.now(timezone.utc))
            embed.add_field(name="아이템", value=f"{template['emoji']} **{template['name']}**", inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            embed.add_field(
                name="레벨 변화",
                value=f"{current_level} → **{new_level if result != 'destroy' else '파괴'}**",
                inline=True
            )

            if result != "destroy":
                max_stars = 25
                filled = "⭐" * new_level
                empty = "☆" * (max_stars - new_level)
                stars = filled + empty

                groups = [stars[i:i + 5] for i in range(0, max_stars, 5)]
                top_row = "  ".join(groups[:3])
                bottom_row = "  ".join(groups[3:])
                star_display = f"{top_row}\n{bottom_row}"

                embed.add_field(name="강화 단계", value=star_display, inline=False)

            if result == "success":
                embed.add_field(name="🎉 성공!", value="강화 레벨이 상승했습니다!", inline=False)
            elif result == "fail":
                embed.add_field(name="💔 실패", value=f"연속 실패: {new_fail_streak}회", inline=False)
                if new_fail_streak >= 2:
                    embed.add_field(name="✨ 다음 강화 보장!", value="다음 강화는 100% 성공합니다!", inline=False)
            else:
                embed.add_field(name="💥 파괴", value="아이템이 파괴되었습니다!", inline=False)

            refreshed_coins = await coins_cog.get_user_coins(user_id, guild_id)
            embed.add_field(name="💰 소모 코인", value=f"{cost:,} 코인", inline=True)
            embed.add_field(name="💳 남은 코인", value=f"{refreshed_coins:,} 코인", inline=True)
            embed.set_footer(text=f"강화 확률: 성공 {rates[0]}% | 실패 {rates[1]}% | 파괴 {rates[2]}%")

            # Post result (not ephemeral anymore)
            await interaction.followup.send(embed=embed)

            # Send to showoff channel if not destroyed
            if result != 'destroy':
                showoff_channel = self.bot.get_channel(self.showoff_channel_id)
                if showoff_channel:
                    public_embed = embed.copy()
                    public_embed.add_field(name="플레이어", value=interaction.user.mention, inline=True)
                    updated_item_row = await self.bot.pool.fetchrow("SELECT * FROM user_items WHERE item_id = $1",
                                                                    item_id)
                    if updated_item_row:
                        view = EnhancementResultView(self.bot, user_id, guild_id, dict(updated_item_row), template)
                        await showoff_channel.send(embed=public_embed, view=view)
                    else:
                        await showoff_channel.send(embed=public_embed)

            self.logger.info(
                f"사용자 {user_id}가 {template['name']} 강화: {current_level}→{new_level if result != 'destroy' else '파괴'} ({result})",
                extra={'guild_id': guild_id}
            )

        except Exception as e:
            self.logger.error(f"강화 처리 중 심각한 오류 발생: {e}", extra={'guild_id': guild_id}, exc_info=True)
            await interaction.followup.send(f"⚠ 강화 처리 중 예측하지 못한 오류가 발생했습니다: {e}")

    async def equip_item(self, interaction: discord.Interaction, item_id: str):
        """Equip an item"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            item_row = await self.bot.pool.fetchrow(
                "SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped FROM user_items ui WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3",
                item_id, user_id, guild_id)
            if not item_row:
                await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return
            if item_row['is_equipped']:
                await interaction.followup.send("❌ 이미 장착된 아이템입니다.", ephemeral=True)
                return
            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            character = await self.get_user_character(user_id, guild_id)
            if not character:
                await interaction.followup.send("❌ 캐릭터를 먼저 생성해주세요.", ephemeral=True)
                return
            if template.get('class_req') and template['class_req'] != character['class']:
                await interaction.followup.send(f"❌ 이 아이템은 {template['class_req']} 전용입니다. (현재: {character['class']})",
                                                ephemeral=True)
                return
            slot_type = template['slot_type']
            await self.bot.pool.execute(
                "UPDATE user_items SET is_equipped = FALSE, equipped_slot = NULL FROM user_equipment ue WHERE user_items.item_id = ue.item_id AND ue.user_id = $1 AND ue.guild_id = $2 AND ue.slot_name = $3",
                user_id, guild_id, slot_type)
            await self.bot.pool.execute(
                "DELETE FROM user_equipment WHERE user_id = $1 AND guild_id = $2 AND slot_name = $3", user_id, guild_id,
                slot_type)
            await self.bot.pool.execute(
                "UPDATE user_items SET is_equipped = TRUE, equipped_slot = $1 WHERE item_id = $2", slot_type, item_id)
            await self.bot.pool.execute(
                "INSERT INTO user_equipment (user_id, guild_id, slot_name, item_id) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, guild_id, slot_name) DO UPDATE SET item_id = EXCLUDED.item_id, equipped_at = CURRENT_TIMESTAMP",
                user_id, guild_id, slot_type, item_id)
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(title="✅ 장착 완료!", color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"
            embed.add_field(name="장착된 아이템", value=item_display, inline=False)
            embed.add_field(name="장착 슬롯", value=slot_type, inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            showoff_channel = self.bot.get_channel(self.showoff_channel_id)
            if showoff_channel:
                embed.add_field(name="플레이어", value=interaction.user.mention, inline=True)
                await showoff_channel.send(embed=embed)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            self.logger.error(f"장착 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 장착 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def unequip_item(self, interaction: discord.Interaction, item_id: str):
        """Unequip an item"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            item_row = await self.bot.pool.fetchrow(
                "SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped, ui.equipped_slot FROM user_items ui WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3",
                item_id, user_id, guild_id)
            if not item_row:
                await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return
            if not item_row['is_equipped']:
                await interaction.followup.send("❌ 장착되지 않은 아이템입니다.", ephemeral=True)
                return
            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            await self.bot.pool.execute(
                "UPDATE user_items SET is_equipped = FALSE, equipped_slot = NULL WHERE item_id = $1", item_id)
            await self.bot.pool.execute(
                "DELETE FROM user_equipment WHERE user_id = $1 AND guild_id = $2 AND slot_name = $3", user_id, guild_id,
                item_row['equipped_slot'])
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(title="⚪ 장착 해제 완료!", color=discord.Color.orange(),
                                  timestamp=datetime.now(timezone.utc))
            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"
            embed.add_field(name="해제된 아이템", value=item_display, inline=False)
            embed.add_field(name="해제된 슬롯", value=item_row['equipped_slot'], inline=True)
            showoff_channel = self.bot.get_channel(self.showoff_channel_id)
            if showoff_channel:
                embed.add_field(name="플레이어", value=interaction.user.mention, inline=True)
                await showoff_channel.send(embed=embed)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            self.logger.error(f"장착 해제 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 장착 해제 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def show_market_sell_confirmation(self, interaction: discord.Interaction, item_id: str):
        """Show automatic price calculation and confirmation"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            item_row = await self.bot.pool.fetchrow(
                "SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped FROM user_items ui WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3",
                item_id, user_id, guild_id)
            if not item_row:
                await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return
            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            calculated_price = self.calculate_market_price(template, item_row['enhancement_level'])
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(title="🏪 마켓 판매 확인", color=rarity_info['color'], timestamp=datetime.now(timezone.utc))
            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"
            embed.add_field(name="판매할 아이템", value=item_display, inline=False)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            embed.add_field(name="강화 레벨", value=f"+{item_row['enhancement_level']}", inline=True)
            embed.add_field(name="💰 자동 계산된 가격", value=f"{calculated_price:,} 코인", inline=True)
            embed.set_footer(text="가격은 아이템의 등급, 강화 레벨, 기본 능력치를 바탕으로 자동 계산됩니다.")
            view = MarketSellConfirmView(self.bot, item_id, calculated_price, template, item_row['enhancement_level'])
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            self.logger.error(f"마켓 가격 계산 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 가격 계산 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def list_item_on_market(self, interaction: discord.Interaction, item_id: str, price: int):
        """List item on marketplace"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            item_row = await self.bot.pool.fetchrow(
                "SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped FROM user_items ui WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3",
                item_id, user_id, guild_id)
            if not item_row:
                await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return
            if item_row['is_equipped']:
                await interaction.followup.send("❌ 장착된 아이템은 판매할 수 없습니다. 먼저 장착을 해제해주세요.", ephemeral=True)
                return
            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            market_id = str(uuid.uuid4())[:8]
            await self.bot.pool.execute(
                "INSERT INTO marketplace (market_id, seller_id, guild_id, item_id, template_id, enhancement_level, price) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                market_id, user_id, guild_id, item_id, item_row['template_id'], item_row['enhancement_level'], price)
            await self.bot.pool.execute("UPDATE user_items SET user_id = -1 WHERE item_id = $1", item_id)
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(title="🏪 마켓 등록 완료!", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"
            embed.add_field(name="등록된 아이템", value=item_display, inline=False)
            embed.add_field(name="판매 가격", value=f"{price:,} 코인", inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            embed.set_footer(text="다른 플레이어들이 구매할 수 있습니다!")
            await interaction.followup.send("마켓 등록이 완료되었습니다! 자랑 채널에 게시되었습니다.", ephemeral=True)
            showoff_channel = self.bot.get_channel(self.showoff_channel_id)
            if showoff_channel:
                embed.add_field(name="판매자", value=interaction.user.mention, inline=True)
                embed.title = "🏪 새로운 아이템이 마켓에 등록되었습니다!"
                await showoff_channel.send(embed=embed)
            await self.create_marketplace_message()
        except Exception as e:
            self.logger.error(f"마켓 등록 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 마켓 등록 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def handle_market_purchase(self, interaction: discord.Interaction, market_id: str):
        """Handle marketplace item purchase"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            market_entry = await self.bot.pool.fetchrow(
                "SELECT m.market_id, m.seller_id, m.item_id, m.template_id, m.enhancement_level, m.price, m.guild_id FROM marketplace m WHERE m.market_id = $1",
                market_id)
            if not market_entry:
                await interaction.followup.send("❌ 해당 아이템이 이미 판매되었거나 존재하지 않습니다.", ephemeral=True)
                return
            if market_entry['seller_id'] == user_id:
                await interaction.followup.send("❌ 자신이 판매한 아이템은 구매할 수 없습니다.", ephemeral=True)
                return
            template = self.get_item_template(market_entry['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            price = market_entry['price']
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                await interaction.followup.send("❌ 코인 시스템을 사용할 수 없습니다.", ephemeral=True)
                return
            current_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if current_coins < price:
                await interaction.followup.send(f"❌ 코인이 부족합니다!\n필요: {price:,} 코인\n보유: {current_coins:,} 코인",
                                                ephemeral=True)
                return
            if not await coins_cog.remove_coins(user_id, guild_id, price, "market_purchase",
                                                f"마켓 구매: {template['name']}"):
                await interaction.followup.send("❌ 코인 차감 중 오류가 발생했습니다.", ephemeral=True)
                return
            seller_amount = int(price * 0.9)
            await coins_cog.add_coins(market_entry['seller_id'], guild_id, seller_amount, "market_sale",
                                      f"마켓 판매: {template['name']}")
            await self.bot.pool.execute(
                "UPDATE user_items SET user_id = $1, is_equipped = FALSE, equipped_slot = NULL WHERE item_id = $2",
                user_id, market_entry['item_id'])
            await self.bot.pool.execute("DELETE FROM marketplace WHERE market_id = $1", market_id)
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(title="🛒 구매 완료!", color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
            enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"
            embed.add_field(name="구매한 아이템", value=item_display, inline=False)
            embed.add_field(name="💰 지불 금액", value=f"{price:,} 코인", inline=True)
            embed.add_field(name="💳 남은 코인", value=f"{current_coins - price:,} 코인", inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            embed.set_footer(text="아이템이 인벤토리에 추가되었습니다!")
            await interaction.followup.send("구매가 완료되었습니다! 자랑 채널에 게시되었습니다.", ephemeral=True)
            showoff_channel = self.bot.get_channel(self.showoff_channel_id)
            if showoff_channel:
                embed.add_field(name="구매자", value=interaction.user.mention, inline=True)
                embed.title = "🛒 마켓에서 아이템 구매!"
                await showoff_channel.send(embed=embed)
            try:
                seller = self.bot.get_user(market_entry['seller_id'])
                if seller:
                    seller_embed = discord.Embed(title="💰 아이템 판매 완료!",
                                                 description=f"{item_display}이(가) {price:,} 코인에 판매되었습니다!",
                                                 color=discord.Color.gold())
                    seller_embed.add_field(name="수수료 차감 후 수익", value=f"{seller_amount:,} 코인", inline=True)
                    await seller.send(embed=seller_embed)
            except:
                pass
            await self.create_marketplace_message()
            self.logger.info(f"마켓 거래 완료: {user_id}가 {template['name']}을 {price:,} 코인에 구매", extra={'guild_id': guild_id})
        except Exception as e:
            self.logger.error(f"마켓 구매 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 구매 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def get_equipped_items(self, user_id: int, guild_id: int) -> Dict[str, Dict]:
        """장착된 아이템 조회"""
        try:
            query = "SELECT ue.slot_name, ui.template_id, ui.enhancement_level, ui.item_id FROM user_equipment ue JOIN user_items ui ON ue.item_id = ui.item_id WHERE ue.user_id = $1 AND ue.guild_id = $2"
            rows = await self.bot.pool.fetch(query, user_id, guild_id)
            equipped = {}
            for row in rows:
                equipped[row['slot_name']] = {'template_id': row['template_id'],
                                              'enhancement_level': row['enhancement_level'], 'item_id': row['item_id']}
            return equipped
        except Exception as e:
            self.logger.error(f"장착 아이템 조회 오류: {e}", extra={'guild_id': guild_id})
            return {}

    async def calculate_total_stats(self, user_id: int, guild_id: int) -> Dict[str, int]:
        """총 능력치 계산"""
        try:
            equipped_items = await self.get_equipped_items(user_id, guild_id)
            total_stats = {"str": 0, "dex": 0, "int": 0, "luk": 0, "att": 0, "m_att": 0}
            for slot, item_data in equipped_items.items():
                template = self.get_item_template(item_data['template_id'])
                if template:
                    enhancement_level = item_data['enhancement_level']
                    enhancement_multiplier = 1 + (enhancement_level * 0.1)
                    for stat, value in template['base_stats'].items():
                        if value > 0:
                            enhanced_value = int(value * enhancement_multiplier)
                            total_stats[stat] += enhanced_value
            return total_stats
        except Exception as e:
            self.logger.error(f"능력치 계산 오류: {e}", extra={'guild_id': guild_id})
            return {"str": 0, "dex": 0, "int": 0, "luk": 0, "att": 0, "m_att": 0}

    async def show_inventory(self, interaction: discord.Interaction):
        """인벤토리 표시"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            items = await self.bot.pool.fetch(
                "SELECT item_id, template_id, enhancement_level, is_equipped, created_at FROM user_items WHERE user_id = $1 AND guild_id = $2 ORDER BY created_at DESC LIMIT 20",
                user_id, guild_id)
            if not items:
                await interaction.followup.send("🎒 인벤토리가 비어있습니다.", ephemeral=True)
                return
            embed = discord.Embed(title="🎒 인벤토리", color=discord.Color.blue())
            items_text = ""
            for item_row in items:
                template = self.get_item_template(item_row['template_id'])
                if template:
                    rarity_info = self.item_rarities[template['rarity']]
                    enhancement = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
                    equipped = "🔒" if item_row['is_equipped'] else ""
                    items_text += f"{template['emoji']} **{template['name']}** {enhancement} {equipped}\n"
                    items_text += f"   {rarity_info['name']} | {template['slot_type']} | ID: `{item_row['item_id']}`\n\n"
            embed.description = items_text
            embed.set_footer(text=f"총 {len(items)}개 아이템 (최근 20개만 표시)")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 인벤토리 조회 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"인벤토리 조회 오류: {e}", extra={'guild_id': guild_id})

    async def show_equipment_manager(self, interaction: discord.Interaction):
        """장비 관리 화면 표시"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            items = await self.bot.pool.fetch(
                "SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped FROM user_items ui WHERE ui.user_id = $1 AND ui.guild_id = $2 AND ui.is_equipped = FALSE ORDER BY ui.created_at DESC",
                user_id, guild_id)
            if not items:
                await interaction.followup.send("📦 장착 가능한 아이템이 없습니다.", ephemeral=True)
                return
            items_by_slot = {}
            for item_row in items:
                template = self.get_item_template(item_row['template_id'])
                if template:
                    slot_type = template['slot_type']
                    if slot_type not in items_by_slot:
                        items_by_slot[slot_type] = []
                    items_by_slot[slot_type].append((item_row, template))
            embed = discord.Embed(title="⚔️ 장비 관리", description="장착할 슬롯을 선택해주세요.", color=discord.Color.blue())
            for slot_type, items_list in items_by_slot.items():
                embed.add_field(name=f"{slot_type}", value=f"{len(items_list)}개 아이템", inline=True)
            view = EquipmentSelectView(self.bot, user_id, guild_id, items_by_slot)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 장비 관리 화면 로드 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"장비 관리 오류: {e}", extra={'guild_id': guild_id})

    async def show_slot_items(self, interaction: discord.Interaction, slot_type: str, items: List):
        """특정 슬롯의 아이템들 표시"""
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title=f"📦 {slot_type} 아이템", description="장착할 아이템을 선택해주세요.", color=discord.Color.blue())
        items_text = ""
        for item_row, template in items[:10]:
            rarity_info = self.item_rarities[template['rarity']]
            enhancement = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            items_text += f"{template['emoji']} **{template['name']}** {enhancement}\n"
            items_text += f"   {rarity_info['name']} | ID: `{item_row['item_id']}`\n\n"
        embed.description = items_text
        view = SlotItemsView(self.bot, interaction.user.id, interaction.guild.id, slot_type, items)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def show_item_management(self, interaction: discord.Interaction, item_id: str):
        """개별 아이템 관리 화면"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        try:
            item_row = await self.bot.pool.fetchrow(
                "SELECT item_id, template_id, enhancement_level, is_equipped, equipped_slot, fail_streak FROM user_items WHERE item_id = $1 AND user_id = $2 AND guild_id = $3",
                item_id, user_id, guild_id)
            if not item_row:
                await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return
            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(title=f"{template['emoji']} {template['name']}", color=rarity_info['color'])
            enhancement_level = item_row['enhancement_level']
            enhancement_text = f"+{enhancement_level}" if enhancement_level > 0 else "강화 안됨"

            # ⭐ Two-row star grid (3 groups of 5 on top, 2 on bottom)
            max_stars = 25
            filled = "⭐" * enhancement_level
            empty = "☆" * (max_stars - enhancement_level)
            stars = filled + empty
            groups = [stars[i:i + 5] for i in range(0, max_stars, 5)]
            top_row = "  ".join(groups[:3])
            bottom_row = "  ".join(groups[3:])
            star_display = f"{top_row}\n{bottom_row}"

            embed.add_field(name="강화", value=f"{enhancement_text}\n{star_display}", inline=False)

            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            embed.add_field(name="종류", value=template['slot_type'], inline=True)
            if template.get('class_req'):
                embed.add_field(name="직업 제한", value=template['class_req'], inline=True)
            enhanced_stats = template['base_stats'].copy()
            enhancement_multiplier = 1 + (item_row['enhancement_level'] * 0.1)
            stats_text = ""
            for stat, value in enhanced_stats.items():
                if value > 0:
                    enhanced_value = int(value * enhancement_multiplier)
                    stats_text += f"**{stat.upper()}**: {enhanced_value}\n"
            if stats_text:
                embed.add_field(name="📊 현재 능력치", value=stats_text, inline=False)
            if item_row['enhancement_level'] < 24:
                current_level = item_row['enhancement_level']
                rates = self.starforce_rates.get(current_level, (30, 67, 3))
                cost = self.enhancement_costs.get(current_level, 1000)
                fail_streak = item_row['fail_streak'] or 0
                if fail_streak >= 2:
                    embed.add_field(name="⚡ 다음 강화", value="🎯 **100% 성공 보장!**", inline=False)
                else:
                    embed.add_field(name="⚡ 다음 강화 정보",
                                    value=f"비용: {cost:,} 코인\n성공: {rates[0]}% | 실패: {rates[1]}% | 파괴: {rates[2]}%\n연속실패: {fail_streak}회",
                                    inline=False)
            embed.add_field(name="상태", value="🔒 장착중" if item_row['is_equipped'] else "📦 보관중", inline=True)
            view = ItemManagementView(self.bot, user_id, guild_id, item_row, template)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 아이템 관리 화면 로드 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"아이템 관리 오류: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="직업선택", description="캐릭터 직업을 선택하거나 변경합니다. (월 1회 제한)")
    @app_commands.describe(character_class="선택할 직업")
    @app_commands.choices(character_class=[
        app_commands.Choice(name="⚔️ 전사", value="전사"), app_commands.Choice(name="🔮 법사", value="법사"),
        app_commands.Choice(name="🗡️ 도적", value="도적"), app_commands.Choice(name="🏹 궁수", value="궁수"),
        app_commands.Choice(name="🏴‍☠️ 해적", value="해적")
    ])
    async def select_class(self, interaction: discord.Interaction, character_class: str):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 강화 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        current_character = await self.get_user_character(user_id, guild_id)
        if current_character:
            last_change = current_character['last_change']
            now = datetime.now(timezone.utc)
            time_diff = now - last_change.replace(tzinfo=timezone.utc)
            if time_diff.days < 30:
                days_remaining = 30 - time_diff.days
                await interaction.followup.send(
                    f"❌ 직업 변경은 월 1회만 가능합니다.\n다음 변경 가능일: {days_remaining}일 후\n현재 직업: {self.character_classes[current_character['class']]['emoji']} {current_character['class']}",
                    ephemeral=True)
                return
        try:
            await self.bot.pool.execute(
                "INSERT INTO user_characters (user_id, guild_id, character_class, last_class_change) VALUES ($1, $2, $3, CURRENT_TIMESTAMP) ON CONFLICT (user_id, guild_id) DO UPDATE SET character_class = EXCLUDED.character_class, last_class_change = EXCLUDED.last_class_change",
                user_id, guild_id, character_class)
            class_info = self.character_classes[character_class]
            embed = discord.Embed(title="✅ 직업 선택 완료!",
                                  description=f"{class_info['emoji']} **{class_info['name']}**으로 전직했습니다!",
                                  color=discord.Color.green())
            embed.add_field(name="직업 설명", value=class_info['description'], inline=False)
            embed.add_field(name="주요 능력치", value=" / ".join(class_info['primary_stats']), inline=True)
            embed.add_field(name="다음 변경 가능", value="30일 후", inline=True)
            await interaction.followup.send("직업 선택이 완료되었습니다! 자랑 채널에 게시되었습니다.", ephemeral=True)
            showoff_channel = self.bot.get_channel(self.showoff_channel_id)
            if showoff_channel:
                embed.add_field(name="플레이어", value=interaction.user.mention, inline=True)
                embed.title = f"🎯 새로운 {character_class}이(가) 탄생했습니다!"
                await showoff_channel.send(embed=embed)
            self.logger.info(f"사용자 {user_id}가 {character_class}로 전직했습니다.", extra={'guild_id': guild_id})
        except Exception as e:
            await interaction.followup.send(f"❌ 직업 선택 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"직업 선택 오류: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="캐릭터", description="캐릭터 정보와 장착된 장비를 확인합니다.")
    @app_commands.describe(user="확인할 사용자 (비어두면 본인)")
    async def character_sheet(self, interaction: discord.Interaction, user: discord.Member = None):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 강화 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        target_user = user or interaction.user
        character_data = await self.get_user_character(target_user.id, guild_id)
        if not character_data:
            embed = discord.Embed(title="❗ 캐릭터 미생성", description="`/직업선택` 명령어로 먼저 캐릭터를 생성해주세요!",
                                  color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        equipped_items = await self.get_equipped_items(target_user.id, guild_id)
        total_stats = await self.calculate_total_stats(target_user.id, guild_id)
        combat_power = self.calculate_combat_power(total_stats, character_data['class'])
        class_info = self.character_classes[character_data['class']]
        embed = discord.Embed(title=f"{class_info['emoji']} {target_user.display_name}의 캐릭터",
                              color=discord.Color.blue())
        embed.add_field(name="직업", value=f"{class_info['emoji']} {class_info['name']}", inline=True)
        embed.add_field(name="⚔️ 전투력", value=f"**{combat_power:,}**", inline=True)
        embed.add_field(name="생성일", value=character_data['created_at'].strftime("%Y-%m-%d"), inline=True)
        stats_text = ""
        for stat, value in total_stats.items():
            if value > 0:
                stats_text += f"**{stat.upper()}**: {value:,}\n"
        if stats_text:
            embed.add_field(name="📊 총 능력치", value=stats_text, inline=False)
        equipment_text = ""
        slot_emojis = {
            "무기": "⚔️", "보조무기": "🛡️", "모자": "👑", "상의": "👕", "하의": "👖", "신발": "👟",
            "장갑": "🧤", "망토": "🦹", "목걸이": "📿", "귀걸이": "💎", "반지": "💍", "벨트": "⚡"
        }
        for slot in self.equipment_slots:
            slot_emoji = slot_emojis.get(slot, "📦")
            if slot in equipped_items:
                item_data = equipped_items[slot]
                template = self.get_item_template(item_data['template_id'])
                if template:
                    enhancement = f"+{item_data['enhancement_level']}" if item_data['enhancement_level'] > 0 else ""
                    equipment_text += f"{slot_emoji} **{slot}**: {template['emoji']} {template['name']} {enhancement}\n"
            else:
                equipment_text += f"{slot_emoji} **{slot}**: -\n"
        embed.add_field(name="⚔️ 장착 장비", value=equipment_text or "장착된 장비가 없습니다.", inline=False)
        if target_user.id == interaction.user.id:
            view = CharacterView(self.bot, interaction.user.id, guild_id, character_data, equipped_items)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="아이템정보", description="특정 아이템의 상세 정보를 확인합니다.")
    @app_commands.describe(item_id="확인할 아이템 ID")
    async def item_info(self, interaction: discord.Interaction, item_id: str):
        guild_id = interaction.guild.id
        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 강화 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            item_row = await self.bot.pool.fetchrow(
                "SELECT template_id, enhancement_level, is_equipped, created_at, fail_streak FROM user_items WHERE item_id = $1 AND user_id = $2 AND guild_id = $3",
                item_id, interaction.user.id, guild_id)
            if not item_row:
                await interaction.followup.send("❌ 해당 ID의 아이템을 찾을 수 없습니다.", ephemeral=True)
                return
            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            await self.show_item_management(interaction, item_id)
        except Exception as e:
            await interaction.followup.send(f"❌ 아이템 정보 조회 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"아이템 정보 조회 오류: {e}", extra={'guild_id': guild_id})

    @tasks.loop(minutes=10)
    async def update_marketplace(self):
        """Update marketplace message every 10 minutes"""
        try:
            await self.create_marketplace_message()
        except Exception as e:
            self.logger.error(f"Marketplace update error: {e}")

    @update_marketplace.before_loop
    async def before_marketplace_update(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        """Setup when bot is ready"""
        if not self.update_marketplace.is_running():
            self.update_marketplace.start()


class EnhancementResultView(discord.ui.View):
    """View for enhancement results with action buttons"""

    def __init__(self, bot, user_id, guild_id, item_row, template):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.item_row = item_row
        self.template = template
        self.enhancement_cog = bot.get_cog('EnhancementCog')

    @discord.ui.button(label="⭐ 강화하기", style=discord.ButtonStyle.primary)
    async def enhance_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 강화할 수 없습니다.", ephemeral=True)
            return
        try:
            await self.enhancement_cog.handle_enhancement(interaction, self.item_row['item_id'])
        except Exception as e:
            await interaction.response.send_message(f"오류가 발생했습니다: {e}", ephemeral=True)

    @discord.ui.button(label="🔹 장착하기", style=discord.ButtonStyle.success)
    async def equip_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 장착할 수 없습니다.", ephemeral=True)
            return
        try:
            await self.enhancement_cog.equip_item(interaction, self.item_row['item_id'])
        except Exception as e:
            await interaction.response.send_message(f"오류가 발생했습니다: {e}", ephemeral=True)

    @discord.ui.button(label="💰 마켓 판매", style=discord.ButtonStyle.secondary)
    async def sell_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 판매할 수 없습니다.", ephemeral=True)
            return
        try:
            await self.enhancement_cog.show_market_sell_confirmation(interaction, self.item_row['item_id'])
        except Exception as e:
            await interaction.response.send_message(f"오류가 발생했습니다: {e}", ephemeral=True)

    async def on_timeout(self) -> None:
        # Disable all buttons when the view times out
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


async def setup(bot):
    await bot.add_cog(EnhancementCog(bot))