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

    @discord.ui.button(label="⭐ 강화하기", style=discord.ButtonStyle.primary, emoji="⚡")
    async def enhance_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 강화할 수 없습니다.", ephemeral=True)
            return

        await self.enhancement_cog.handle_enhancement(interaction, self.item_row['item_id'])

    @discord.ui.button(label="📊 상세 정보", style=discord.ButtonStyle.secondary)
    async def detailed_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.show_detailed_item_info(interaction, self.item_row['item_id'])

    @discord.ui.button(label="💰 마켓에 판매", style=discord.ButtonStyle.success)
    async def sell_to_market(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사용자의 아이템을 판매할 수 없습니다.", ephemeral=True)
            return

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

        # Enhancement button
        enhance_button = discord.ui.Button(
            label="⭐ 강화하기",
            style=discord.ButtonStyle.primary,
            custom_id="enhance_item",
            emoji="⚡"
        )
        enhance_button.callback = self.enhance_item
        self.add_item(enhance_button)

        # Market sell button
        market_button = discord.ui.Button(
            label="💰 마켓 판매",
            style=discord.ButtonStyle.success,
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


class MarketplaceView(discord.ui.View):
    """Paginated marketplace with filtering and search capabilities"""

    def __init__(self, bot, guild_id, page=0, filter_slot=None, filter_rarity=None, search_term=None,
                 sort_by="price_low"):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.page = page
        self.filter_slot = filter_slot
        self.filter_rarity = filter_rarity
        self.search_term = search_term
        self.sort_by = sort_by
        self.items_per_page = 10
        self.enhancement_cog = bot.get_cog('EnhancementCog')

    async def get_filtered_items(self):
        """Get marketplace items with filters applied"""
        base_query = """
            SELECT m.market_id, m.seller_id, m.template_id, m.enhancement_level, 
                   m.price, m.listed_at, m.guild_id
            FROM marketplace m
            WHERE m.guild_id = $1
        """
        params = [self.guild_id]
        param_count = 1

        # Apply filters
        if self.filter_slot:
            # We'll filter by slot_type after getting templates
            pass

        if self.filter_rarity:
            # We'll filter by rarity after getting templates
            pass

        # Add sorting
        if self.sort_by == "price_low":
            base_query += " ORDER BY m.price ASC"
        elif self.sort_by == "price_high":
            base_query += " ORDER BY m.price DESC"
        elif self.sort_by == "level_high":
            base_query += " ORDER BY m.enhancement_level DESC"
        else:  # newest
            base_query += " ORDER BY m.listed_at DESC"

        # Add pagination
        base_query += f" LIMIT {self.items_per_page} OFFSET {self.page * self.items_per_page}"

        try:
            rows = await self.bot.pool.fetch(base_query, *params)

            # Get templates and apply client-side filters
            items = []
            for row in rows:
                template = self.enhancement_cog.get_item_template(row['template_id'])
                if not template:
                    continue

                # Apply slot filter
                if self.filter_slot and template['slot_type'] != self.filter_slot:
                    continue

                # Apply rarity filter
                if self.filter_rarity and template['rarity'] != self.filter_rarity:
                    continue

                # Apply search term filter
                if self.search_term and self.search_term.lower() not in template['name'].lower():
                    continue

                items.append((row, template))

            return items
        except Exception as e:
            self.enhancement_cog.logger.error(f"Error getting filtered items: {e}")
            return []
    async def get_total_items(self):
        """Get total count for pagination"""
        query = "SELECT COUNT(*) FROM marketplace WHERE guild_id = $1"
        return await self.bot.pool.fetchval(query, self.guild_id)

    async def refresh_view(self, interaction):
        """Refresh the marketplace view with current filters"""
        items = await self.get_filtered_items()
        total_items = await self.get_total_items()
        total_pages = (total_items + self.items_per_page - 1) // self.items_per_page

        embed = discord.Embed(
            title="🏪 아이템 마켓플레이스",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        if not items:
            embed.add_field(
                name="📦 조건에 맞는 아이템이 없습니다",
                value="필터를 조정하거나 다른 페이지를 확인해보세요!",
                inline=False
            )
        else:
            items_text = ""
            for i, (market_entry, template) in enumerate(items):
                rarity_info = self.enhancement_cog.item_rarities[template['rarity']]
                enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry[
                                                                                  'enhancement_level'] > 0 else ""

                page_num = (self.page * self.items_per_page) + i + 1
                items_text += f"**{page_num}.** {template['emoji']} **{template['name']}** {enhancement_text}\n"
                items_text += f"   {rarity_info['name']} | {template['slot_type']} | 💰 **{market_entry['price']:,}** 코인\n"
                items_text += f"   판매자: <@{market_entry['seller_id']}>\n\n"

            embed.add_field(name="🛒 판매중인 아이템", value=items_text, inline=False)

        # Add filter info
        filter_info = []
        if self.filter_slot:
            filter_info.append(f"슬롯: {self.filter_slot}")
        if self.filter_rarity:
            filter_info.append(f"등급: {self.filter_rarity}")
        if self.search_term:
            filter_info.append(f"검색: {self.search_term}")

        filter_text = " | ".join(filter_info) if filter_info else "필터 없음"
        embed.add_field(name="🔍 현재 필터", value=filter_text, inline=True)
        embed.add_field(name="📄 페이지", value=f"{self.page + 1}/{max(total_pages, 1)}", inline=True)
        embed.add_field(name="📊 정렬", value=self.get_sort_name(), inline=True)

        embed.set_footer(text="아래 버튼으로 페이지 이동, 필터 설정, 아이템 구매")

        # Update view buttons
        self.clear_items()
        self.add_navigation_buttons(total_pages)
        self.add_filter_buttons()
        self.add_purchase_buttons(items)

        if hasattr(interaction, 'response') and hasattr(interaction.response, 'edit_message'):
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            # For direct message editing (not from interaction)
            await interaction.edit(embed=embed, view=self)
    def get_sort_name(self):
        sort_names = {
            "price_low": "가격 낮은순",
            "price_high": "가격 높은순",
            "level_high": "강화 높은순",
            "newest": "최신순"
        }
        return sort_names.get(self.sort_by, "최신순")

    def add_navigation_buttons(self, total_pages):
        """Add page navigation buttons"""
        # Previous page
        prev_button = discord.ui.Button(
            label="◀ 이전",
            style=discord.ButtonStyle.secondary,
            disabled=self.page <= 0,
            row=0
        )
        prev_button.callback = self.previous_page
        self.add_item(prev_button)

        # Page indicator
        page_button = discord.ui.Button(
            label=f"{self.page + 1}/{max(total_pages, 1)}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=0
        )
        self.add_item(page_button)

        # Next page
        next_button = discord.ui.Button(
            label="다음 ▶",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= total_pages - 1,
            row=0
        )
        next_button.callback = self.next_page
        self.add_item(next_button)

    def add_filter_buttons(self):
        """Add filter and sort buttons"""
        # Sort dropdown
        sort_select = discord.ui.Select(
            placeholder="정렬 방식 선택...",
            options=[
                discord.SelectOption(label="가격 낮은순", value="price_low", emoji="💰"),
                discord.SelectOption(label="가격 높은순", value="price_high", emoji="💎"),
                discord.SelectOption(label="강화 높은순", value="level_high", emoji="⭐"),
                discord.SelectOption(label="최신순", value="newest", emoji="🕐"),
            ],
            row=1
        )
        sort_select.callback = self.change_sort
        self.add_item(sort_select)

        # Slot filter dropdown
        slot_options = [discord.SelectOption(label="모든 슬롯", value="all", emoji="📦")]
        for slot in self.enhancement_cog.equipment_slots:
            slot_options.append(discord.SelectOption(label=slot, value=slot))

        slot_select = discord.ui.Select(
            placeholder="슬롯 필터...",
            options=slot_options[:25],  # Discord limit
            row=2
        )
        slot_select.callback = self.change_slot_filter
        self.add_item(slot_select)

    def add_purchase_buttons(self, items):
        """Add purchase buttons for visible items"""
        for i, (market_entry, template) in enumerate(items[:5]):  # Max 5 purchase buttons
            enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry['enhancement_level'] > 0 else ""

            button = discord.ui.Button(
                label=f"{template['name'][:12]}{enhancement_text} {market_entry['price']:,}💰",
                style=discord.ButtonStyle.success,
                emoji=template['emoji'],
                row=3 if i < 3 else 4
            )
            button.callback = self.create_purchase_callback(market_entry['market_id'])
            self.add_item(button)

    def create_purchase_callback(self, market_id: str):
        async def purchase_callback(interaction: discord.Interaction):
            await self.enhancement_cog.handle_market_purchase(interaction, market_id)
            # Refresh the view after purchase
            await self.refresh_view(interaction)

        return purchase_callback

    async def previous_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self.refresh_view(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        await self.refresh_view(interaction)

    async def change_sort(self, interaction: discord.Interaction):
        self.sort_by = interaction.data['values'][0]
        self.page = 0  # Reset to first page
        await self.refresh_view(interaction)

    async def change_slot_filter(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        self.filter_slot = None if value == "all" else value
        self.page = 0  # Reset to first page
        await self.refresh_view(interaction)

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
        self.logger = get_logger("강화 시스템")

        # Character classes
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

        # Item rarities with Korean names and colors
        self.item_rarities = {
            "일반": {"name": "일반", "color": 0x808080, "weight": 45},
            "고급": {"name": "고급", "color": 0x00FF00, "weight": 30},
            "희귀": {"name": "희귀", "color": 0x0080FF, "weight": 15},
            "영웅": {"name": "영웅", "color": 0x8000FF, "weight": 7},
            "고유": {"name": "고유", "color": 0xFF8000, "weight": 2.5},
            "전설": {"name": "전설", "color": 0xFF0000, "weight": 0.4},
            "신화": {"name": "신화", "color": 0xFFD700, "weight": 0.1}
        }

        # Equipment slots
        self.equipment_slots = [
            "무기", "보조무기", "모자", "상의", "하의", "신발",
            "장갑", "망토", "목걸이", "귀걸이", "반지", "벨트"
        ]

        # MapleStory-style StarForce rates
        self.starforce_rates = {
            # Format: level: (success%, fail_maintain%, fail_decrease%, destroy%)
            0: (95, 5, 0, 0), 1: (90, 10, 0, 0), 2: (85, 15, 0, 0), 3: (85, 15, 0, 0), 4: (80, 20, 0, 0),
            5: (75, 25, 0, 0), 6: (70, 30, 0, 0), 7: (65, 35, 0, 0), 8: (60, 40, 0, 0), 9: (55, 45, 0, 0),
            10: (50, 50, 0, 0), 11: (45, 55, 0, 0), 12: (40, 60, 0, 0), 13: (35, 65, 0, 0), 14: (30, 70, 0, 0),
            15: (30, 67.9, 0, 2.1), 16: (30, 0, 67.9, 2.1), 17: (30, 0, 67.9, 2.1), 18: (30, 0, 67.2, 2.8),
            19: (30, 0, 67.2, 2.8),
            20: (30, 63, 0, 7), 21: (30, 0, 63, 7), 22: (3, 0, 77.6, 19.4), 23: (2, 0, 68.6, 29.4),
            24: (1, 0, 59.4, 39.6)
        }

        # Enhancement costs (in coins)
        self.enhancement_costs = {
            0: 10, 1: 15, 2: 20, 3: 25, 4: 30,
            5: 35, 6: 40, 7: 45, 8: 50, 9: 60,
            10: 70, 11: 80, 12: 90, 13: 100, 14: 120,
            15: 140, 16: 160, 17: 180, 18: 200, 19: 220,
            20: 250, 21: 280, 22: 350, 23: 450, 24: 600
        }

        # Fail streak tracking for guaranteed success
        self.fail_streaks = {}  # user_id: consecutive_fails

        # Massive item pool (300+ items)
        # Item templates will be loaded from database/JSON
        self.item_templates = {}
        self.bot.loop.create_task(self.load_item_templates())
        # Marketplace channel ID
        self.marketplace_channel_id = 1421286971623477422
        # Show-off channel ID for enhancement results and sales
        self.showoff_channel_id = 1421290649277435904

        self.bot.loop.create_task(self.setup_system())

    async def load_item_templates(self):
        """Load item templates from database or JSON file"""
        await self.bot.wait_until_ready()

        try:
            # First try to load from database
            if await self.load_templates_from_db():
                self.logger.info("아이템 템플릿을 데이터베이스에서 로드했습니다.")
                return

            # If no DB templates, load from JSON file
            if await self.load_templates_from_json():
                self.logger.info("아이템 템플릿을 JSON 파일에서 로드했습니다.")
                # Optionally save to DB for future use
                await self.save_templates_to_db()
                return

            # If neither exists, generate initial templates
            await self.generate_initial_templates()
            self.logger.info("초기 아이템 템플릿을 생성했습니다.")

        except Exception as e:
            self.logger.error(f"아이템 템플릿 로드 실패: {e}")

    async def load_templates_from_db(self) -> bool:
        """Load item templates from database"""
        try:
            query = "SELECT * FROM item_templates ORDER BY id"
            rows = await self.bot.pool.fetch(query)

            for row in rows:
                self.item_templates[row['id']] = {
                    'id': row['id'],
                    'name': row['name'],
                    'slot_type': row['slot_type'],
                    'class_req': row['class_req'],
                    'rarity': row['rarity'],
                    'emoji': row['emoji'],
                    'base_stats': json.loads(row['base_stats']),
                    'base_price': row['base_price']
                }

            return len(self.item_templates) > 0

        except Exception as e:
            self.logger.error(f"DB 템플릿 로드 실패: {e}")
            return False

    async def load_templates_from_json(self) -> bool:
        """Load item templates from JSON file"""
        try:
            json_path = os.path.join('data', 'items.json')
            if not os.path.exists(json_path):
                return False

            with open(json_path, 'r', encoding='utf-8') as f:
                templates = json.load(f)

            for template in templates:
                self.item_templates[template['id']] = template

            return len(self.item_templates) > 0

        except Exception as e:
            self.logger.error(f"JSON 템플릿 로드 실패: {e}")
            return False

    async def generate_initial_templates(self):
        """Generate initial item templates and save them"""
        templates = []
        item_id = 1

        # Generate a smaller, more manageable set of items (50-100 instead of 300+)
        weapon_types = {
            "무기": {
                "전사": ["대검", "도끼", "둔기"],
                "법사": ["스태프", "완드"],
                "도적": ["단검", "클로"],
                "궁수": ["활", "석궁"],
                "해적": ["건", "너클"]
            }
        }

        # Generate weapons (fewer variations)
        for class_name, weapons in weapon_types["무기"].items():
            for weapon in weapons:
                for tier in range(3):  # Only 3 tiers instead of 5
                    for rarity in ["일반", "고급", "희귀", "영웅"]:  # Fewer rarities initially
                        name = f"{weapon} Lv.{tier * 15 + 15}"
                        template = {
                            "id": item_id,
                            "name": name,
                            "slot_type": "무기",
                            "class_req": class_name,
                            "rarity": rarity,
                            "emoji": self.get_weapon_emoji(weapon),
                            "base_stats": self.generate_weapon_stats(class_name, tier, rarity),
                            "base_price": self.calculate_base_price(rarity, tier)
                        }
                        templates.append(template)
                        self.item_templates[item_id] = template
                        item_id += 1

        # Save to JSON file
        os.makedirs('data', exist_ok=True)
        with open('data/items.json', 'w', encoding='utf-8') as f:
            json.dump(templates, f, indent=2, ensure_ascii=False)

    async def save_templates_to_db(self):
        """Save item templates from memory to database"""
        try:
            for template in self.item_templates.values():
                await self.bot.pool.execute("""
                    INSERT INTO item_templates (id, name, slot_type, class_req, rarity, emoji, base_stats, base_price)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (id) DO NOTHING
                """,
                                            template['id'], template['name'], template['slot_type'],
                                            template.get('class_req'), template['rarity'], template['emoji'],
                                            json.dumps(template['base_stats']), template['base_price'])

            self.logger.info("템플릿을 데이터베이스에 저장했습니다.")
        except Exception as e:
            self.logger.error(f"DB 템플릿 저장 실패: {e}")
    def get_weapon_emoji(self, weapon: str) -> str:
        emoji_map = {
            "대검": "⚔️", "도끼": "🪓", "둔기": "🔨", "창": "🔱", "검": "⚔️",
            "스태프": "🔮", "완드": "🪄", "마도서": "📖",
            "단검": "🗡️", "클로": "🗡️",
            "활": "🏹", "석궁": "🏹", "투척무기": "🔪",
            "건": "🔫", "너클": "👊", "총": "🔫"
        }
        return emoji_map.get(weapon, "⚔️")

    def get_armor_emoji(self, slot: str) -> str:
        emoji_map = {
            "모자": "👑", "상의": "👕", "하의": "👖",
            "신발": "👟", "장갑": "🧤", "망토": "🦹"
        }
        return emoji_map.get(slot, "🛡️")

    def get_accessory_emoji(self, slot: str) -> str:
        emoji_map = {
            "목걸이": "📿", "귀걸이": "💎", "반지": "💍", "벨트": "⚡"
        }
        return emoji_map.get(slot, "💎")

    def generate_weapon_stats(self, class_name: str, tier: int, rarity: str) -> Dict[str, int]:
        """Generate weapon stats based on class and tier"""
        base_multiplier = (tier + 1) * self.get_rarity_multiplier(rarity)

        stats = {"str": 0, "dex": 0, "int": 0, "luk": 0, "att": 0, "m_att": 0}

        if class_name == "전사":
            stats["str"] = random.randint(int(10 * base_multiplier), int(20 * base_multiplier))
            stats["att"] = random.randint(int(15 * base_multiplier), int(30 * base_multiplier))
        elif class_name == "법사":
            stats["int"] = random.randint(int(10 * base_multiplier), int(20 * base_multiplier))
            stats["m_att"] = random.randint(int(15 * base_multiplier), int(30 * base_multiplier))
        elif class_name in ["도적", "궁수"]:
            stats["dex"] = random.randint(int(10 * base_multiplier), int(20 * base_multiplier))
            stats["att"] = random.randint(int(12 * base_multiplier), int(25 * base_multiplier))
        elif class_name == "해적":
            stats["str"] = random.randint(int(5 * base_multiplier), int(15 * base_multiplier))
            stats["dex"] = random.randint(int(5 * base_multiplier), int(15 * base_multiplier))
            stats["att"] = random.randint(int(10 * base_multiplier), int(25 * base_multiplier))

        # Add random secondary stats
        if random.random() < 0.3:
            secondary_stats = ["str", "dex", "int", "luk"]
            chosen_stat = random.choice(secondary_stats)
            stats[chosen_stat] += random.randint(1, int(5 * base_multiplier))

        return stats

    def generate_armor_stats(self, slot: str, tier: int, rarity: str) -> Dict[str, int]:
        """Generate armor stats"""
        base_multiplier = (tier + 1) * self.get_rarity_multiplier(rarity)
        stats = {"str": 0, "dex": 0, "int": 0, "luk": 0, "att": 0, "m_att": 0}

        # Random stat distribution for armor
        stat_pool = random.randint(int(5 * base_multiplier), int(15 * base_multiplier))
        stat_names = ["str", "dex", "int", "luk"]

        for _ in range(random.randint(1, 3)):  # 1-3 different stats
            if stat_pool <= 0:
                break
            stat = random.choice(stat_names)
            value = random.randint(1, min(stat_pool, int(8 * base_multiplier)))
            stats[stat] += value
            stat_pool -= value

        return stats

    def generate_accessory_stats(self, tier: int, rarity: str) -> Dict[str, int]:
        """Generate accessory stats (usually higher and more varied)"""
        base_multiplier = (tier + 1) * self.get_rarity_multiplier(rarity)
        stats = {"str": 0, "dex": 0, "int": 0, "luk": 0, "att": 0, "m_att": 0}

        # Accessories have more diverse stats
        stat_pool = random.randint(int(8 * base_multiplier), int(20 * base_multiplier))
        all_stats = ["str", "dex", "int", "luk", "att", "m_att"]

        for _ in range(random.randint(2, 4)):  # 2-4 different stats
            if stat_pool <= 0:
                break
            stat = random.choice(all_stats)
            value = random.randint(1, min(stat_pool, int(10 * base_multiplier)))
            stats[stat] += value
            stat_pool -= value

        return stats

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
        """Calculate automatic market price based on item stats, enhancement costs, and risk"""
        base_price = template['base_price']

        # Calculate total enhancement costs invested
        total_enhancement_cost = 0
        for level in range(enhancement_level):
            total_enhancement_cost += self.enhancement_costs.get(level, 1000)

        # Rarity multiplier for market pricing
        rarity_market_multipliers = {
            "일반": 1.0, "고급": 1.5, "희귀": 2.2, "영웅": 3.5,
            "고유": 5.5, "전설": 8.0, "신화": 12.0
        }

        rarity_multiplier = rarity_market_multipliers.get(template['rarity'], 1.0)

        # Enhancement value multiplier (exponential scaling for higher levels)
        if enhancement_level == 0:
            enhancement_multiplier = 1.0
        elif enhancement_level <= 10:
            # Linear scaling for low levels (20% per level)
            enhancement_multiplier = 1 + (enhancement_level * 0.2)
        elif enhancement_level <= 15:
            # Moderate scaling for mid levels (30% per level above 10)
            enhancement_multiplier = 3.0 + ((enhancement_level - 10) * 0.3)
        elif enhancement_level <= 20:
            # High scaling for high levels (50% per level above 15)
            enhancement_multiplier = 4.5 + ((enhancement_level - 15) * 0.5)
        else:
            # Extreme scaling for max levels (100% per level above 20)
            enhancement_multiplier = 7.0 + ((enhancement_level - 20) * 1.0)

        # Risk premium for high enhancement levels (accounts for destruction chance)
        risk_premium = 1.0
        if enhancement_level >= 15:
            # Items at 15+ have destruction risk, so they're worth more
            risk_premium = 1.2 + ((enhancement_level - 15) * 0.1)
        if enhancement_level >= 22:
            # Ultra high risk items get massive premium
            risk_premium = 1.9 + ((enhancement_level - 22) * 0.3)

        # Base item value (rarity adjusted)
        item_base_value = int(base_price * rarity_multiplier)

        # Enhancement value (cost recovery + premium for success)
        enhancement_value = int(total_enhancement_cost * 1.5)  # 150% cost recovery

        # Enhancement level premium (for the power gained)
        level_premium = int(item_base_value * (enhancement_multiplier - 1))

        # Apply risk premium
        final_price = int((item_base_value + enhancement_value + level_premium) * risk_premium)

        # Minimum price ensures even +0 items have reasonable value
        min_price = max(
            item_base_value,  # At least base item value
            5 + (enhancement_level * 20)  # Or level-based minimum
        )

        return max(final_price, min_price)

    def get_enhancement_cost_breakdown(self, enhancement_level: int) -> Dict[str, int]:
        """Get detailed breakdown of enhancement costs and market value"""
        total_cost = 0
        for level in range(enhancement_level):
            total_cost += self.enhancement_costs.get(level, 1000)

        return {
            'total_enhancement_cost': total_cost,
            'cost_recovery_150pct': int(total_cost * 1.5),
            'levels_completed': enhancement_level,
            'next_level_cost': self.enhancement_costs.get(enhancement_level, 1000) if enhancement_level < 24 else 0
        }
    def calculate_combat_power(self, stats: Dict[str, int], character_class: str) -> int:
        """Calculate total combat power based on stats and class"""
        power = 0

        # Base stat power
        power += stats["str"] * 4
        power += stats["dex"] * 4
        power += stats["int"] * 4
        power += stats["luk"] * 3

        # Attack power (main component)
        power += stats["att"] * 15
        power += stats["m_att"] * 15

        # Class-specific bonuses
        class_multipliers = {
            "전사": {"str": 1.5, "att": 1.3},
            "법사": {"int": 1.5, "m_att": 1.3},
            "도적": {"dex": 1.4, "att": 1.2, "luk": 1.3},
            "궁수": {"dex": 1.5, "att": 1.2},
            "해적": {"str": 1.2, "dex": 1.2, "att": 1.1}
        }

        # Apply class multipliers
        multipliers = class_multipliers.get(character_class, {})
        for stat, value in stats.items():
            if stat in multipliers:
                power += int(value * multipliers[stat])

        return max(1, int(power))

    def get_random_item(self) -> Dict[str, Any]:
        """Get a random item based on rarity weights"""
        if not self.item_templates:
            return None

        # Create weighted list
        weighted_items = []
        for item in self.item_templates.values():
            weight = self.item_rarities[item['rarity']]['weight']
            weighted_items.extend([item] * int(weight * 10))

        return random.choice(weighted_items).copy() if weighted_items else None

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
                    user_id BIGINT,
                    guild_id BIGINT,
                    character_class VARCHAR(20) NOT NULL,
                    last_class_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            # Enhanced items table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_items (
                    item_id VARCHAR(50) PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    template_id INTEGER NOT NULL,
                    enhancement_level INTEGER DEFAULT 0,
                    is_equipped BOOLEAN DEFAULT FALSE,
                    equipped_slot VARCHAR(20),
                    fail_streak INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_enhanced TIMESTAMP
                )
            """)

            # Equipment slots table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_equipment (
                    user_id BIGINT,
                    guild_id BIGINT,
                    slot_name VARCHAR(20),
                    item_id VARCHAR(50),
                    equipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id, slot_name),
                    FOREIGN KEY (item_id) REFERENCES user_items(item_id) ON DELETE SET NULL
                )
            """)

            # Enhancement logs
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS enhancement_logs (
                    log_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    item_id VARCHAR(50) NOT NULL,
                    old_level INTEGER NOT NULL,
                    new_level INTEGER NOT NULL,
                    result VARCHAR(20) NOT NULL,
                    cost INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Marketplace table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS marketplace (
                    market_id VARCHAR(50) PRIMARY KEY,
                    seller_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    item_id VARCHAR(50) NOT NULL,
                    template_id INTEGER NOT NULL,
                    enhancement_level INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES user_items(item_id) ON DELETE CASCADE
                )
            """)

            # Create indexes
            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_items_user_guild ON user_items(user_id, guild_id);
            """)
            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_equipment_user_guild ON user_equipment(user_id, guild_id);
            """)
            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_marketplace_guild ON marketplace(guild_id, listed_at DESC);
            """)

            await self.bot.pool.execute("""
                            CREATE TABLE IF NOT EXISTS item_templates (
                                id INTEGER PRIMARY KEY,
                                name VARCHAR(100) NOT NULL,
                                slot_type VARCHAR(20) NOT NULL,
                                class_req VARCHAR(20),
                                rarity VARCHAR(20) NOT NULL,
                                emoji VARCHAR(10) NOT NULL,
                                base_stats JSON NOT NULL,
                                base_price INTEGER NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """)

            self.logger.info("강화 시스템 데이터베이스가 준비되었습니다.")

        except Exception as e:
            self.logger.error(f"데이터베이스 설정 실패: {e}")

    async def setup_marketplace_message(self):
        """Setup marketplace message"""
        try:
            # Get guild_id from a channel if available, or use a default
            guild_id = None
            channel_id = None

            for guild in self.bot.guilds:
                temp_channel_id = config.get_channel_id(guild.id, self.marketplace_channel_key)
                if temp_channel_id:
                    guild_id = guild.id
                    channel_id = temp_channel_id
                    break

            if not guild_id or not channel_id:
                self.logger.error("No configured marketplace channel found")
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                self.logger.error(f"Marketplace channel {channel_id} not found")
                return

            # Delete old marketplace messages
            async for message in channel.history(limit=10):
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                        await asyncio.sleep(0.5)
                    except:
                        pass

            # Create new marketplace message
            await self.create_marketplace_message()

        except Exception as e:
            self.logger.error(f"Marketplace setup error: {e}")

    async def create_marketplace_message(self):
        """Create/update marketplace message with improved pagination"""
        try:
            # Get guild_id from a channel if available, or use a default
            guild_id = None
            channel_id = None

            for guild in self.bot.guilds:
                temp_channel_id = config.get_channel_id(guild.id, self.marketplace_channel_key)
                if temp_channel_id:
                    guild_id = guild.id
                    channel_id = temp_channel_id
                    break

            if not guild_id or not channel_id:
                self.logger.error("No configured marketplace channel found")
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                return

            # Get marketplace items
            market_items = await self.get_marketplace_items()

            embed = discord.Embed(
                title="🏪 아이템 마켓플레이스",
                description="다른 플레이어들이 판매하는 아이템을 구매해보세요!",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )

            if not market_items:
                embed.add_field(
                    name="📦 현재 판매중인 아이템이 없습니다",
                    value="다른 플레이어들이 아이템을 올릴 때까지 기다려주세요!",
                    inline=False
                )
                await channel.send(embed=embed)
                return

            # Display items
            items_text = ""
            for i, (market_entry, template) in enumerate(market_items[:10]):  # Show top 10
                rarity_info = self.item_rarities[template['rarity']]
                enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry[
                                                                                  'enhancement_level'] > 0 else ""

                items_text += f"**{i + 1}.** {template['emoji']} **{template['name']}** {enhancement_text}\n"
                items_text += f"   {rarity_info['name']} | {template['slot_type']} | 💰 **{market_entry['price']:,}** 코인\n"
                items_text += f"   판매자: <@{market_entry['seller_id']}>\n\n"

            embed.add_field(name="🛒 판매중인 아이템", value=items_text or "판매중인 아이템이 없습니다.", inline=False)
            embed.set_footer(text="아래 버튼을 눌러 아이템을 구매하세요! (10분마다 자동 갱신)")

            view = MarketplaceView(self.bot, channel.guild.id)
            await channel.send(embed=embed, view=view)

        except Exception as e:
            self.logger.error(f"Marketplace message creation error: {e}")
    async def get_marketplace_items(self) -> List[Tuple]:
        """Get current marketplace items"""
        try:
            query = """
                SELECT m.market_id, m.seller_id, m.template_id, m.enhancement_level, 
                       m.price, m.listed_at, m.guild_id
                FROM marketplace m
                ORDER BY m.listed_at DESC
                LIMIT 20
            """
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
            query = """
                SELECT character_class, last_class_change, created_at
                FROM user_characters 
                WHERE user_id = $1 AND guild_id = $2
            """
            row = await self.bot.pool.fetchrow(query, user_id, guild_id)
            if row:
                return {
                    'class': row['character_class'],
                    'last_change': row['last_class_change'],
                    'created_at': row['created_at']
                }
            return None
        except Exception as e:
            self.logger.error(f"캐릭터 조회 오류: {e}", extra={'guild_id': guild_id})
            return None

    async def create_item_in_db(self, user_id: int, guild_id: int, item_data: Dict) -> str:
        """데이터베이스에 아이템 생성"""
        try:
            item_id = str(uuid.uuid4())[:8]

            await self.bot.pool.execute("""
                INSERT INTO user_items (item_id, user_id, guild_id, template_id, enhancement_level)
                VALUES ($1, $2, $3, $4, $5)
            """, item_id, user_id, guild_id, item_data['id'], 0)

            return item_id
        except Exception as e:
            self.logger.error(f"아이템 생성 오류: {e}", extra={'guild_id': guild_id})
            return ""

    def get_item_template(self, template_id: int) -> Optional[Dict]:
        """아이템 템플릿 조회"""
        return self.item_templates.get(template_id)

    async def handle_enhancement(self, interaction: discord.Interaction, item_id: str):
        """Handle item enhancement with MapleStory-style rates"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            # Get item info
            query = """
                SELECT item_id, template_id, enhancement_level, fail_streak, user_id
                FROM user_items
                WHERE item_id = $1 AND user_id = $2 AND guild_id = $3
            """
            item_row = await self.bot.pool.fetchrow(query, item_id, user_id, guild_id)

            if not item_row:
                await interaction.followup.send("⚠ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return

            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("⚠ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return

            current_level = item_row['enhancement_level']
            fail_streak = item_row['fail_streak'] or 0

            if current_level >= 24:
                await interaction.followup.send("⚠ 최대 강화 레벨에 도달했습니다.", ephemeral=True)
                return

            # Get enhancement cost
            cost = self.enhancement_costs.get(current_level, 1000)

            # Check coins
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                await interaction.followup.send("⚠ 코인 시스템을 사용할 수 없습니다.", ephemeral=True)
                return

            current_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if current_coins < cost:
                await interaction.followup.send(
                    f"⚠ 강화 비용이 부족합니다!\n필요: {cost:,} 코인\n보유: {current_coins:,} 코인",
                    ephemeral=True
                )
                return

            # Deduct coins
            if not await coins_cog.remove_coins(user_id, guild_id, cost, "enhancement", f"강화 시도: {template['name']}"):
                await interaction.followup.send("⚠ 코인 차감 중 오류가 발생했습니다.", ephemeral=True)
                return

            # Get rates for display (needed for footer)
            rates = self.starforce_rates.get(current_level, (30, 67, 3))

            # Calculate enhancement result
            if fail_streak >= 2:
                # Guaranteed success after 2 consecutive fails
                result = "success"
                new_level = current_level + 1
                new_fail_streak = 0
                result_text = "✨ **보장된 성공!** ✨"
                result_color = discord.Color.gold()
            else:
                # Normal rates - now with 4 outcomes
                success_rate, fail_maintain_rate, fail_decrease_rate, destroy_rate = rates

                roll = random.randint(1, 100)

                if roll <= success_rate:
                    result = "success"
                    new_level = current_level + 1
                    new_fail_streak = 0
                    result_text = "✅ **강화 성공!**"
                    result_color = discord.Color.green()
                elif roll <= success_rate + fail_maintain_rate:
                    result = "fail_maintain"
                    new_level = current_level  # Level stays the same
                    new_fail_streak = fail_streak + 1
                    result_text = "⚠️ **강화 실패 (레벨 유지)**"
                    result_color = discord.Color.orange()
                elif roll <= success_rate + fail_maintain_rate + fail_decrease_rate:
                    result = "fail_decrease"
                    new_level = current_level - 1  # Level decreases
                    new_fail_streak = fail_streak + 1
                    result_text = "⚠ **강화 실패 (레벨 감소)**"
                    result_color = discord.Color.red()
                else:
                    result = "destroy"
                    new_level = 0  # Item will be deleted, but we set this for logging
                    new_fail_streak = 0
                    result_text = "💥 **아이템 파괴!**"
                    result_color = discord.Color.dark_red()

            # Handle item destruction
            if result == "destroy":
                # Delete the item entirely from database
                await self.bot.pool.execute("""
                    DELETE FROM user_items WHERE item_id = $1
                """, item_id)

                # Also remove from equipment if it was equipped
                await self.bot.pool.execute("""
                    DELETE FROM user_equipment 
                    WHERE user_id = $1 AND guild_id = $2 AND item_id = $3
                """, user_id, guild_id, item_id)

                # Log destruction
                await self.bot.pool.execute("""
                    INSERT INTO enhancement_logs (user_id, guild_id, item_id, old_level, new_level, result, cost)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, user_id, guild_id, item_id, current_level, 0, result, cost)

            else:
                # Update item in database (for non-destroy results)
                await self.bot.pool.execute("""
                    UPDATE user_items 
                    SET enhancement_level = $1, fail_streak = $2, last_enhanced = CURRENT_TIMESTAMP
                    WHERE item_id = $3
                """, new_level, new_fail_streak, item_id)

                # Log enhancement attempt
                await self.bot.pool.execute("""
                    INSERT INTO enhancement_logs (user_id, guild_id, item_id, old_level, new_level, result, cost)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, user_id, guild_id, item_id, current_level, new_level, result, cost)

            # Create result embed with visual effects
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(
                title=result_text,
                color=result_color,
                timestamp=datetime.now(timezone.utc)
            )

            # Add visual flair based on result
            if result == "success":
                if new_level >= 15:
                    embed.description = "✨⭐✨⭐✨⭐✨⭐✨⭐✨"
                else:
                    embed.description = "⚡💫⚡💫⚡💫⚡💫⚡"
            elif result in ["fail_maintain", "fail_decrease"]:
                embed.description = "💔😢💔😢💔😢💔😢💔"
            else:  # destroy
                embed.description = "💥💀💥💀💥💀💥💀💥"

            item_display = f"{template['emoji']} **{template['name']}**"
            embed.add_field(name="아이템", value=item_display, inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)

            if result == "destroy":
                embed.add_field(name="레벨 변화", value=f"{current_level} → **파괴됨**", inline=True)
            else:
                embed.add_field(name="레벨 변화", value=f"{current_level} → **{new_level}**", inline=True)

            if result == "success":
                embed.add_field(name="🎉 성공!", value="강화 레벨이 상승했습니다!", inline=False)
            elif result == "fail_maintain":
                embed.add_field(name="⚠️ 실패 (레벨 유지)", value=f"연속 실패: {new_fail_streak}회", inline=False)
                if new_fail_streak >= 2:
                    embed.add_field(name="✨ 다음 강화 보장!", value="다음 강화는 100% 성공합니다!", inline=False)
            elif result == "fail_decrease":
                embed.add_field(name="⚠ 실패 (레벨 감소)", value=f"연속 실패: {new_fail_streak}회", inline=False)
                if new_fail_streak >= 2:
                    embed.add_field(name="✨ 다음 강화 보장!", value="다음 강화는 100% 성공합니다!", inline=False)
            else:  # destroy
                embed.add_field(name="💥 파괴", value="아이템이 완전히 파괴되어 사라졌습니다!", inline=False)

            embed.add_field(name="💰 소모 코인", value=f"{cost:,} 코인", inline=True)
            embed.add_field(name="💳 남은 코인", value=f"{current_coins - cost:,} 코인", inline=True)

            # Show stats preview only if item wasn't destroyed
            if result != "destroy":
                enhanced_stats = template['base_stats'].copy()
                enhancement_multiplier = 1 + (new_level * 0.1)

                stats_text = ""
                for stat, value in enhanced_stats.items():
                    if value > 0:
                        enhanced_value = int(value * enhancement_multiplier)
                        stats_text += f"{stat.upper()}: {enhanced_value} "

                if stats_text:
                    embed.add_field(name="📊 현재 능력치", value=stats_text.strip(), inline=False)

            embed.set_footer(text=f"강화 확률: 성공 {rates[0]}% | 유지 {rates[1]}% | 감소 {rates[2]}% | 파괴 {rates[3]}%")

            # Post result to show-off channel
            showoff_channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
            showoff_channel = self.bot.get_channel(showoff_channel_id) if showoff_channel_id else None
            if showoff_channel:
                embed.add_field(name="플레이어", value=interaction.user.mention, inline=True)

                # Only create action buttons if item wasn't destroyed
                if result != "destroy":
                    # Get updated item info for the view
                    updated_item_query = """
                        SELECT item_id, template_id, enhancement_level, is_equipped, equipped_slot, fail_streak
                        FROM user_items
                        WHERE item_id = $1
                    """
                    updated_item_row = await self.bot.pool.fetchrow(updated_item_query, item_id)

                    if updated_item_row:
                        # Create view with action buttons - convert to dict for easier access
                        item_dict = {
                            'item_id': updated_item_row['item_id'],
                            'template_id': updated_item_row['template_id'],
                            'enhancement_level': updated_item_row['enhancement_level'],
                            'is_equipped': updated_item_row['is_equipped'],
                            'equipped_slot': updated_item_row['equipped_slot'],
                            'fail_streak': updated_item_row['fail_streak']
                        }
                        view = EnhancementResultView(self.bot, user_id, guild_id, item_dict, template)
                        await showoff_channel.send(embed=embed, view=view)
                    else:
                        await showoff_channel.send(embed=embed)
                else:
                    # Item was destroyed, no action buttons
                    await showoff_channel.send(embed=embed)

            # Send brief confirmation to user
            if result == "destroy":
                await interaction.followup.send("💥 아이템이 파괴되었습니다! 자랑 채널에 게시되었습니다.", ephemeral=True)
            else:
                await interaction.followup.send("강화 결과가 자랑 채널에 게시되었습니다!", ephemeral=True)

            self.logger.info(
                f"사용자 {user_id}가 {template['name']} 강화: {current_level}→{new_level if result != 'destroy' else 'DESTROYED'} ({result})",
                extra={'guild_id': guild_id}
            )

        except Exception as e:
            self.logger.error(f"강화 처리 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"⚠ 강화 처리 중 오류가 발생했습니다: {e}", ephemeral=True)
    async def equip_item(self, interaction: discord.Interaction, item_id: str):
        """Equip an item"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            # Get item info
            query = """
                SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped
                FROM user_items ui
                WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3
            """
            item_row = await self.bot.pool.fetchrow(query, item_id, user_id, guild_id)

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

            # Check class requirement
            character = await self.get_user_character(user_id, guild_id)
            if not character:
                await interaction.followup.send("❌ 캐릭터를 먼저 생성해주세요.", ephemeral=True)
                return

            if template.get('class_req') and template['class_req'] != character['class']:
                await interaction.followup.send(
                    f"❌ 이 아이템은 {template['class_req']} 전용입니다. (현재: {character['class']})",
                    ephemeral=True
                )
                return

            slot_type = template['slot_type']

            # Unequip existing item in the same slot
            await self.bot.pool.execute("""
                UPDATE user_items 
                SET is_equipped = FALSE, equipped_slot = NULL
                FROM user_equipment ue
                WHERE user_items.item_id = ue.item_id 
                AND ue.user_id = $1 AND ue.guild_id = $2 AND ue.slot_name = $3
            """, user_id, guild_id, slot_type)

            await self.bot.pool.execute("""
                DELETE FROM user_equipment 
                WHERE user_id = $1 AND guild_id = $2 AND slot_name = $3
            """, user_id, guild_id, slot_type)

            # Equip new item
            await self.bot.pool.execute("""
                UPDATE user_items 
                SET is_equipped = TRUE, equipped_slot = $1
                WHERE item_id = $2
            """, slot_type, item_id)

            await self.bot.pool.execute("""
                INSERT INTO user_equipment (user_id, guild_id, slot_name, item_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, guild_id, slot_name)
                DO UPDATE SET item_id = EXCLUDED.item_id, equipped_at = CURRENT_TIMESTAMP
            """, user_id, guild_id, slot_type, item_id)

            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(
                title="✅ 장착 완료!",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )

            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"

            embed.add_field(name="장착된 아이템", value=item_display, inline=False)
            embed.add_field(name="장착 슬롯", value=slot_type, inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)

            showoff_channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
            showoff_channel = self.bot.get_channel(showoff_channel_id) if showoff_channel_id else None
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
            # Get item info
            query = """
                SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped, ui.equipped_slot
                FROM user_items ui
                WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3
            """
            item_row = await self.bot.pool.fetchrow(query, item_id, user_id, guild_id)

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

            # Unequip item
            await self.bot.pool.execute("""
                UPDATE user_items 
                SET is_equipped = FALSE, equipped_slot = NULL
                WHERE item_id = $1
            """, item_id)

            await self.bot.pool.execute("""
                DELETE FROM user_equipment 
                WHERE user_id = $1 AND guild_id = $2 AND slot_name = $3
            """, user_id, guild_id, item_row['equipped_slot'])

            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(
                title="⚪ 장착 해제 완료!",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )

            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"

            embed.add_field(name="해제된 아이템", value=item_display, inline=False)
            embed.add_field(name="해제된 슬롯", value=item_row['equipped_slot'], inline=True)

            showoff_channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
            showoff_channel = self.bot.get_channel(showoff_channel_id) if showoff_channel_id else None
            if showoff_channel:
                embed.add_field(name="플레이어", value=interaction.user.mention, inline=True)
                await showoff_channel.send(embed=embed)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"장착 해제 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 장착 해제 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def show_market_sell_confirmation(self, interaction: discord.Interaction, item_id: str):
        """Show automatic price calculation and confirmation with detailed breakdown"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            # Get item info
            query = """
                SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped
                FROM user_items ui
                WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3
            """
            item_row = await self.bot.pool.fetchrow(query, item_id, user_id, guild_id)

            if not item_row:
                await interaction.followup.send("⚠ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return

            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("⚠ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return

            # Calculate automatic price and get breakdown
            calculated_price = self.calculate_market_price(template, item_row['enhancement_level'])
            cost_breakdown = self.get_enhancement_cost_breakdown(item_row['enhancement_level'])

            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(
                title="🏪 마켓 판매 확인",
                color=rarity_info['color'],
                timestamp=datetime.now(timezone.utc)
            )

            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"

            embed.add_field(name="판매할 아이템", value=item_display, inline=False)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            embed.add_field(name="강화 레벨", value=f"+{item_row['enhancement_level']}", inline=True)
            embed.add_field(name="💰 자동 계산된 가격", value=f"{calculated_price:,} 코인", inline=True)

            # Add pricing breakdown for enhanced items
            if item_row['enhancement_level'] > 0:
                breakdown_text = f"**기본 아이템 가치**: {template['base_price']:,} 코인\n"
                breakdown_text += f"**총 강화 비용**: {cost_breakdown['total_enhancement_cost']:,} 코인\n"
                breakdown_text += f"**비용 회수 (150%)**: {cost_breakdown['cost_recovery_150pct']:,} 코인\n"

                if item_row['enhancement_level'] >= 15:
                    breakdown_text += f"**고위험 프리미엄**: 파괴 위험으로 인한 추가 가치\n"

                embed.add_field(name="📊 가격 산정 근거", value=breakdown_text, inline=False)

                # Show potential profit/loss
                profit_loss = calculated_price - cost_breakdown['total_enhancement_cost'] - template['base_price']
                profit_text = f"**예상 수익**: {profit_loss:,} 코인" if profit_loss > 0 else f"**예상 손실**: {abs(profit_loss):,} 코인"
                embed.add_field(name="💹 투자 대비 수익", value=profit_text, inline=True)

            # Show market fee
            seller_receives = int(calculated_price * 0.9)
            market_fee = calculated_price - seller_receives

            embed.add_field(name="💳 실제 수령액", value=f"{seller_receives:,} 코인", inline=True)
            embed.add_field(name="🏦 마켓 수수료 (10%)", value=f"{market_fee:,} 코인", inline=True)

            embed.set_footer(text="가격은 아이템의 등급, 강화 레벨, 투자 비용, 위험도를 바탕으로 자동 계산됩니다.")

            view = MarketSellConfirmView(self.bot, item_id, calculated_price, template, item_row['enhancement_level'])
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.logger.error(f"마켓 가격 계산 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"⚠ 가격 계산 중 오류가 발생했습니다: {e}", ephemeral=True)
    async def list_item_on_market(self, interaction: discord.Interaction, item_id: str, price: int):
        """List item on marketplace"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        try:
            # Check if item exists and is owned by user
            query = """
                SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped
                FROM user_items ui
                WHERE ui.item_id = $1 AND ui.user_id = $2 AND ui.guild_id = $3
            """
            item_row = await self.bot.pool.fetchrow(query, item_id, user_id, guild_id)

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

            # Create marketplace entry
            market_id = str(uuid.uuid4())[:8]

            await self.bot.pool.execute("""
                INSERT INTO marketplace (market_id, seller_id, guild_id, item_id, template_id, enhancement_level, price)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, market_id, user_id, guild_id, item_id, item_row['template_id'], item_row['enhancement_level'], price)

            # Remove item from user's inventory
            await self.bot.pool.execute("""
                UPDATE user_items 
                SET user_id = -1  -- Mark as marketplace item
                WHERE item_id = $1
            """, item_id)

            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(
                title="🏪 마켓 등록 완료!",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )

            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"

            embed.add_field(name="등록된 아이템", value=item_display, inline=False)
            embed.add_field(name="판매 가격", value=f"{price:,} 코인", inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)

            embed.set_footer(text="다른 플레이어들이 구매할 수 있습니다!")

            # Send confirmation to user
            await interaction.followup.send("마켓 등록이 완료되었습니다! 자랑 채널에 게시되었습니다.", ephemeral=True)

            # Post to show-off channel
            showoff_channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
            showoff_channel = self.bot.get_channel(showoff_channel_id) if showoff_channel_id else None
            if showoff_channel:
                embed.add_field(name="판매자", value=interaction.user.mention, inline=True)
                embed.title = "🏪 새로운 아이템이 마켓에 등록되었습니다!"
                await showoff_channel.send(embed=embed)

            # Update marketplace message
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
            # Get marketplace item info
            query = """
                SELECT m.market_id, m.seller_id, m.item_id, m.template_id, 
                       m.enhancement_level, m.price, m.guild_id
                FROM marketplace m
                WHERE m.market_id = $1
            """
            market_entry = await self.bot.pool.fetchrow(query, market_id)

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

            # Check coins
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                await interaction.followup.send("❌ 코인 시스템을 사용할 수 없습니다.", ephemeral=True)
                return

            current_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if current_coins < price:
                await interaction.followup.send(
                    f"❌ 코인이 부족합니다!\n필요: {price:,} 코인\n보유: {current_coins:,} 코인",
                    ephemeral=True
                )
                return

            # Process transaction
            # Deduct coins from buyer
            if not await coins_cog.remove_coins(user_id, guild_id, price, "market_purchase",
                                                f"마켓 구매: {template['name']}"):
                await interaction.followup.send("❌ 코인 차감 중 오류가 발생했습니다.", ephemeral=True)
                return

            # Add coins to seller (90% - 10% market fee)
            seller_amount = int(price * 0.9)
            await coins_cog.add_coins(market_entry['seller_id'], guild_id, seller_amount, "market_sale",
                                      f"마켓 판매: {template['name']}")

            # Transfer item to buyer
            await self.bot.pool.execute("""
                UPDATE user_items 
                SET user_id = $1, is_equipped = FALSE, equipped_slot = NULL
                WHERE item_id = $2
            """, user_id, market_entry['item_id'])

            # Remove from marketplace
            await self.bot.pool.execute("""
                DELETE FROM marketplace WHERE market_id = $1
            """, market_id)

            # Success message
            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(
                title="🛒 구매 완료!",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )

            enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry['enhancement_level'] > 0 else ""
            item_display = f"{template['emoji']} **{template['name']}** {enhancement_text}"

            embed.add_field(name="구매한 아이템", value=item_display, inline=False)
            embed.add_field(name="💰 지불 금액", value=f"{price:,} 코인", inline=True)
            embed.add_field(name="💳 남은 코인", value=f"{current_coins - price:,} 코인", inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)

            embed.set_footer(text="아이템이 인벤토리에 추가되었습니다!")

            # Send confirmation to user
            await interaction.followup.send("구매가 완료되었습니다! 자랑 채널에 게시되었습니다.", ephemeral=True)

            # Post to show-off channel
            showoff_channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
            showoff_channel = self.bot.get_channel(showoff_channel_id) if showoff_channel_id else None
            if showoff_channel:
                embed.add_field(name="구매자", value=interaction.user.mention, inline=True)
                embed.title = "🛒 마켓에서 아이템 구매!"
                await showoff_channel.send(embed=embed)

            # Notify seller via DM
            try:
                seller = self.bot.get_user(market_entry['seller_id'])
                if seller:
                    seller_embed = discord.Embed(
                        title="💰 아이템 판매 완료!",
                        description=f"{item_display}이(가) {price:,} 코인에 판매되었습니다!",
                        color=discord.Color.gold()
                    )
                    seller_embed.add_field(name="수수료 차감 후 수익", value=f"{seller_amount:,} 코인", inline=True)
                    await seller.send(embed=seller_embed)
            except:
                pass  # Ignore if can't send DM

            # Update marketplace message
            await self.create_marketplace_message()

            self.logger.info(f"마켓 거래 완료: {user_id}가 {template['name']}을 {price:,} 코인에 구매", extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error(f"마켓 구매 오류: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"❌ 구매 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def get_equipped_items(self, user_id: int, guild_id: int) -> Dict[str, Dict]:
        """장착된 아이템 조회"""
        try:
            query = """
                SELECT ue.slot_name, ui.template_id, ui.enhancement_level, ui.item_id
                FROM user_equipment ue
                JOIN user_items ui ON ue.item_id = ui.item_id
                WHERE ue.user_id = $1 AND ue.guild_id = $2
            """
            rows = await self.bot.pool.fetch(query, user_id, guild_id)

            equipped = {}
            for row in rows:
                equipped[row['slot_name']] = {
                    'template_id': row['template_id'],
                    'enhancement_level': row['enhancement_level'],
                    'item_id': row['item_id']
                }

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

                    # Base stats with enhancement bonus (10% per level)
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
            query = """
                SELECT item_id, template_id, enhancement_level, is_equipped, created_at
                FROM user_items
                WHERE user_id = $1 AND guild_id = $2
                ORDER BY created_at DESC
                LIMIT 20
            """
            items = await self.bot.pool.fetch(query, user_id, guild_id)

            if not items:
                await interaction.followup.send("🎒 인벤토리가 비어있습니다.", ephemeral=True)
                return

            embed = discord.Embed(
                title="🎒 인벤토리",
                color=discord.Color.blue()
            )

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
            # Get unequipped items by slot type
            query = """
                SELECT ui.item_id, ui.template_id, ui.enhancement_level, ui.is_equipped
                FROM user_items ui
                WHERE ui.user_id = $1 AND ui.guild_id = $2 AND ui.is_equipped = FALSE
                ORDER BY ui.created_at DESC
            """
            items = await self.bot.pool.fetch(query, user_id, guild_id)

            if not items:
                await interaction.followup.send("📦 장착 가능한 아이템이 없습니다.", ephemeral=True)
                return

            # Group items by slot type
            items_by_slot = {}
            for item_row in items:
                template = self.get_item_template(item_row['template_id'])
                if template:
                    slot_type = template['slot_type']
                    if slot_type not in items_by_slot:
                        items_by_slot[slot_type] = []
                    items_by_slot[slot_type].append((item_row, template))

            embed = discord.Embed(
                title="⚔️ 장비 관리",
                description="장착할 슬롯을 선택해주세요.",
                color=discord.Color.blue()
            )

            for slot_type, items_list in items_by_slot.items():
                embed.add_field(
                    name=f"{slot_type}",
                    value=f"{len(items_list)}개 아이템",
                    inline=True
                )

            view = EquipmentSelectView(self.bot, user_id, guild_id, items_by_slot)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 장비 관리 화면 로드 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"장비 관리 오류: {e}", extra={'guild_id': guild_id})

    async def show_slot_items(self, interaction: discord.Interaction, slot_type: str, items: List):
        """특정 슬롯의 아이템들 표시"""
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title=f"📦 {slot_type} 아이템",
            description="장착할 아이템을 선택해주세요.",
            color=discord.Color.blue()
        )

        items_text = ""
        for item_row, template in items[:10]:  # Show up to 10 items
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
            # Get item info
            query = """
                SELECT item_id, template_id, enhancement_level, is_equipped, equipped_slot, fail_streak
                FROM user_items
                WHERE item_id = $1 AND user_id = $2 AND guild_id = $3
            """
            item_row = await self.bot.pool.fetchrow(query, item_id, user_id, guild_id)

            if not item_row:
                await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)
                return

            template = self.get_item_template(item_row['template_id'])
            if not template:
                await interaction.followup.send("❌ 아이템 정보를 불러올 수 없습니다.", ephemeral=True)
                return

            rarity_info = self.item_rarities[template['rarity']]
            embed = discord.Embed(
                title=f"{template['emoji']} {template['name']}",
                color=rarity_info['color']
            )

            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else "강화 안됨"
            embed.add_field(name="강화", value=enhancement_text, inline=True)
            embed.add_field(name="등급", value=rarity_info['name'], inline=True)
            embed.add_field(name="종류", value=template['slot_type'], inline=True)

            if template.get('class_req'):
                embed.add_field(name="직업 제한", value=template['class_req'], inline=True)

            # Calculate current stats with enhancement
            enhanced_stats = template['base_stats'].copy()
            enhancement_multiplier = 1 + (item_row['enhancement_level'] * 0.1)

            stats_text = ""
            for stat, value in enhanced_stats.items():
                if value > 0:
                    enhanced_value = int(value * enhancement_multiplier)
                    stats_text += f"**{stat.upper()}**: {enhanced_value}\n"

            if stats_text:
                embed.add_field(name="📊 현재 능력치", value=stats_text, inline=False)

            # Enhancement info
            if item_row['enhancement_level'] < 24:
                current_level = item_row['enhancement_level']
                rates = self.starforce_rates.get(current_level, (30, 0, 67, 3))
                cost = self.enhancement_costs.get(current_level, 1000)
                fail_streak = item_row['fail_streak'] or 0

                if fail_streak >= 2:
                    embed.add_field(name="⚡ 다음 강화", value="🎯 **100% 성공 보장!**", inline=False)
                else:
                    embed.add_field(
                        name="⚡ 다음 강화 정보",
                        value=f"비용: {cost:,} 코인\n성공: {rates[0]}% | 유지: {rates[1]}% | 감소: {rates[2]}% | 파괴: {rates[3]}%\n연속실패: {fail_streak}회",
                        inline=False
                    )

            embed.add_field(name="상태", value="🔒 장착중" if item_row['is_equipped'] else "📦 보관중", inline=True)

            view = ItemManagementView(self.bot, user_id, guild_id, item_row, template)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 아이템 관리 화면 로드 중 오류가 발생했습니다: {e}", ephemeral=True)
            self.logger.error(f"아이템 관리 오류: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="직업선택", description="캐릭터 직업을 선택하거나 변경합니다. (월 1회 제한)")
    @app_commands.describe(character_class="선택할 직업")
    @app_commands.choices(character_class=[
        app_commands.Choice(name="⚔️ 전사", value="전사"),
        app_commands.Choice(name="🔮 법사", value="법사"),
        app_commands.Choice(name="🗡️ 도적", value="도적"),
        app_commands.Choice(name="🏹 궁수", value="궁수"),
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

        # Check if user can change class (monthly limit)
        if current_character:
            last_change = current_character['last_change']
            now = datetime.now(timezone.utc)
            time_diff = now - last_change.replace(tzinfo=timezone.utc)

            if time_diff.days < 30:
                days_remaining = 30 - time_diff.days
                await interaction.followup.send(
                    f"❌ 직업 변경은 월 1회만 가능합니다.\n"
                    f"다음 변경 가능일: {days_remaining}일 후\n"
                    f"현재 직업: {self.character_classes[current_character['class']]['emoji']} {current_character['class']}",
                    ephemeral=True
                )
                return

        try:
            # Update or create character
            await self.bot.pool.execute("""
                INSERT INTO user_characters (user_id, guild_id, character_class, last_class_change)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, guild_id)
                DO UPDATE SET 
                    character_class = EXCLUDED.character_class,
                    last_class_change = EXCLUDED.last_class_change
            """, user_id, guild_id, character_class)

            class_info = self.character_classes[character_class]
            embed = discord.Embed(
                title="✅ 직업 선택 완료!",
                description=f"{class_info['emoji']} **{class_info['name']}**으로 전직했습니다!",
                color=discord.Color.green()
            )
            embed.add_field(name="직업 설명", value=class_info['description'], inline=False)
            embed.add_field(name="주요 능력치", value=" / ".join(class_info['primary_stats']), inline=True)
            embed.add_field(name="다음 변경 가능", value="30일 후", inline=True)

            # Send confirmation to user
            await interaction.followup.send("직업 선택이 완료되었습니다! 자랑 채널에 게시되었습니다.", ephemeral=True)

            # Post to show-off channel
            showoff_channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
            showoff_channel = self.bot.get_channel(showoff_channel_id) if showoff_channel_id else None
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
            embed = discord.Embed(
                title="❗ 캐릭터 미생성",
                description="`/직업선택` 명령어로 먼저 캐릭터를 생성해주세요!",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Get equipped items and stats
        equipped_items = await self.get_equipped_items(target_user.id, guild_id)
        total_stats = await self.calculate_total_stats(target_user.id, guild_id)
        combat_power = self.calculate_combat_power(total_stats, character_data['class'])

        class_info = self.character_classes[character_data['class']]
        embed = discord.Embed(
            title=f"{class_info['emoji']} {target_user.display_name}의 캐릭터",
            color=discord.Color.blue()
        )

        embed.add_field(name="직업", value=f"{class_info['emoji']} {class_info['name']}", inline=True)
        embed.add_field(name="⚔️ 전투력", value=f"**{combat_power:,}**", inline=True)
        embed.add_field(name="생성일", value=character_data['created_at'].strftime("%Y-%m-%d"), inline=True)

        # Total stats
        stats_text = ""
        for stat, value in total_stats.items():
            if value > 0:
                stats_text += f"**{stat.upper()}**: {value:,}\n"

        if stats_text:
            embed.add_field(name="📊 총 능력치", value=stats_text, inline=False)

        # Equipment display
        equipment_text = ""
        slot_emojis = {
            "무기": "⚔️", "보조무기": "🛡️", "모자": "👑", "상의": "👕",
            "하의": "👖", "신발": "👟", "장갑": "🧤", "망토": "🦹",
            "목걸이": "📿", "귀걸이": "💎", "반지": "💍", "벨트": "⚡"
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

        # Only show management buttons if it's the user's own character
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
            query = """
                SELECT template_id, enhancement_level, is_equipped, created_at, fail_streak
                FROM user_items
                WHERE item_id = $1 AND user_id = $2 AND guild_id = $3
            """
            item_row = await self.bot.pool.fetchrow(query, item_id, interaction.user.id, guild_id)

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

    @app_commands.command(name="마켓검색", description="마켓플레이스에서 특정 아이템을 검색합니다.")
    @app_commands.describe(
        search_term="검색할 아이템 이름",
        slot_type="슬롯 타입 필터",
        rarity="등급 필터",
        min_price="최소 가격",
        max_price="최대 가격"
    )
    async def search_market(self, interaction: discord.Interaction, search_term: str = None,
                            slot_type: str = None, rarity: str = None,
                            min_price: int = None, max_price: int = None):
        """Advanced marketplace search"""
        guild_id = interaction.guild.id

        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message("⚠ 이 서버에서는 강화 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Build search query with filters
            query = """
                SELECT m.market_id, m.seller_id, m.template_id, m.enhancement_level, 
                       m.price, m.listed_at, m.guild_id
                FROM marketplace m
                WHERE m.guild_id = $1
            """
            params = [guild_id]
            param_count = 1

            if min_price:
                param_count += 1
                query += f" AND m.price >= ${param_count}"
                params.append(min_price)

            if max_price:
                param_count += 1
                query += f" AND m.price <= ${param_count}"
                params.append(max_price)

            query += " ORDER BY m.price ASC LIMIT 20"

            rows = await self.bot.pool.fetch(query, *params)

            # Apply template-based filters
            filtered_items = []
            for row in rows:
                template = self.get_item_template(row['template_id'])
                if not template:
                    continue

                if slot_type and template['slot_type'] != slot_type:
                    continue
                if rarity and template['rarity'] != rarity:
                    continue
                if search_term and search_term.lower() not in template['name'].lower():
                    continue

                filtered_items.append((row, template))

            if not filtered_items:
                await interaction.followup.send("🔍 검색 조건에 맞는 아이템이 없습니다.", ephemeral=True)
                return

            # Display results
            embed = discord.Embed(
                title="🔍 마켓 검색 결과",
                color=discord.Color.blue()
            )

            items_text = ""
            for i, (market_entry, template) in enumerate(filtered_items[:10]):
                rarity_info = self.item_rarities[template['rarity']]
                enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry[
                                                                                  'enhancement_level'] > 0 else ""

                items_text += f"**{i + 1}.** {template['emoji']} **{template['name']}** {enhancement_text}\n"
                items_text += f"   {rarity_info['name']} | {template['slot_type']} | 💰 {market_entry['price']:,} 코인\n"
                items_text += f"   ID: `{market_entry['market_id']}` | 판매자: <@{market_entry['seller_id']}>\n\n"

            embed.description = items_text
            embed.set_footer(text=f"총 {len(filtered_items)}개 아이템 발견 (최대 10개 표시)")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Market search error: {e}", extra={'guild_id': guild_id})
            await interaction.followup.send(f"⚠ 검색 중 오류가 발생했습니다: {e}", ephemeral=True)
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

    @discord.ui.button(label="⚡ 강화하기", style=discord.ButtonStyle.primary, emoji="⭐")
    async def enhance_again(self, interaction: discord.Interaction, button: discord.ui.Button):
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

async def setup(bot):
    await bot.add_cog(EnhancementCog(bot))