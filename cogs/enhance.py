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

# Assumed to exist based on original code. These provide logging and config loading.
from utils.logger import get_logger
from utils import config


# Centralized user check for Views.
# This prevents unauthorized users from clicking buttons on another user's interface.
class UserCheckView(discord.ui.View):
    def __init__(self, user_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사람의 메뉴는 조작할 수 없습니다.", ephemeral=True)
            return False
        return True


class EnhancementView(UserCheckView):
    """Interactive enhancement interface"""

    def __init__(self, bot, user_id, guild_id, item_data, item_row):
        # Pass user_id to the parent class for automatic checks.
        super().__init__(timeout=300, user_id=user_id)
        self.bot = bot
        self.guild_id = guild_id
        self.item_data = item_data
        self.item_row = item_row
        self.enhancement_cog = bot.get_cog('EnhancementCog')

    @discord.ui.button(label="⭐ 강화하기", style=discord.ButtonStyle.primary, emoji="⚡")
    async def enhance_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        # The user check is now handled automatically by UserCheckView.
        await self.enhancement_cog.handle_enhancement(interaction, self.item_row['item_id'])

    @discord.ui.button(label="📊 상세 정보", style=discord.ButtonStyle.secondary)
    async def detailed_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.show_detailed_item_info(interaction, self.item_row['item_id'])

    @discord.ui.button(label="💰 마켓에 판매", style=discord.ButtonStyle.success)
    async def sell_to_market(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.show_market_sell_confirmation(interaction, self.item_row['item_id'])


class MarketSellConfirmView(UserCheckView):
    """Confirmation view for automatic market pricing"""

    def __init__(self, bot, user_id: int, item_id: str, calculated_price: int):
        super().__init__(timeout=300, user_id=user_id)
        self.bot = bot
        self.item_id = item_id
        self.calculated_price = calculated_price

    @discord.ui.button(label="✅ 판매 확인", style=discord.ButtonStyle.success)
    async def confirm_sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        enhancement_cog = self.bot.get_cog('EnhancementCog')
        if enhancement_cog:
            await enhancement_cog.list_item_on_market(interaction, self.item_id, self.calculated_price)

    @discord.ui.button(label="❌ 취소", style=discord.ButtonStyle.danger)
    async def cancel_sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="판매가 취소되었습니다.", view=None, embed=None)


class EquipmentSelectView(UserCheckView):
    """Equipment slot selection view"""

    def __init__(self, bot, user_id, guild_id, items_by_slot):
        super().__init__(timeout=300, user_id=user_id)
        self.bot = bot
        self.guild_id = guild_id
        self.items_by_slot = items_by_slot
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        slot_emojis = {
            "무기": "⚔️", "보조무기": "🛡️", "모자": "👑", "상의": "👕",
            "하의": "👖", "신발": "👟", "장갑": "🧤", "망토": "🦹",
            "목걸이": "📿", "귀걸이": "💎", "반지": "💍", "벨트": "⚡"
        }

        # Improved button layout logic
        buttons_in_row = 0
        current_row = 0
        for slot_type, items in items_by_slot.items():
            if items:
                if buttons_in_row >= 4:
                    buttons_in_row = 0
                    current_row += 1

                button = discord.ui.Button(
                    label=f"{slot_emojis.get(slot_type, '📦')} {slot_type} ({len(items)})",
                    custom_id=f"equip_slot_{slot_type}",
                    style=discord.ButtonStyle.secondary,
                    row=current_row
                )
                button.callback = self.create_slot_callback(slot_type)
                self.add_item(button)
                buttons_in_row += 1

    def create_slot_callback(self, slot_type: str):
        async def slot_callback(interaction: discord.Interaction):
            await self.enhancement_cog.show_slot_items(interaction, slot_type, self.items_by_slot[slot_type])

        return slot_callback


class SlotItemsView(UserCheckView):
    """View for items in a specific slot"""

    def __init__(self, bot, user_id, guild_id, slot_type: str, items: List):
        super().__init__(timeout=300, user_id=user_id)
        self.bot = bot
        self.guild_id = guild_id
        self.slot_type = slot_type
        self.items = items
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        for i, item_data in enumerate(items[:25]):  # Discord limit is 25 components
            item_row, template = item_data
            enhancement_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
            equipped_text = " 🔒" if item_row['is_equipped'] else ""

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
            await self.enhancement_cog.show_item_management(interaction, item_id)

        return item_callback


class ItemManagementView(UserCheckView):
    """Individual item management view"""

    def __init__(self, bot, user_id, guild_id, item_row, template):
        super().__init__(timeout=300, user_id=user_id)
        self.bot = bot
        self.guild_id = guild_id
        self.item_row = item_row
        self.template = template
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        if item_row['is_equipped']:
            equip_button = discord.ui.Button(label="⚪ 장착 해제", style=discord.ButtonStyle.danger,
                                             custom_id="unequip_item")
            equip_button.callback = self.unequip_item
        else:
            equip_button = discord.ui.Button(label="🔹 장착하기", style=discord.ButtonStyle.success, custom_id="equip_item")
            equip_button.callback = self.equip_item
        self.add_item(equip_button)

        enhance_button = discord.ui.Button(label="⭐ 강화하기", style=discord.ButtonStyle.primary, custom_id="enhance_item",
                                           emoji="⚡")
        enhance_button.callback = self.enhance_item
        self.add_item(enhance_button)

        market_button = discord.ui.Button(label="💰 마켓 판매", style=discord.ButtonStyle.success, custom_id="market_sell")
        market_button.callback = self.market_sell
        self.add_item(market_button)

    async def equip_item(self, interaction: discord.Interaction):
        await self.enhancement_cog.equip_item(interaction, self.item_row['item_id'])

    async def unequip_item(self, interaction: discord.Interaction):
        await self.enhancement_cog.unequip_item(interaction, self.item_row['item_id'])

    async def enhance_item(self, interaction: discord.Interaction):
        await self.enhancement_cog.handle_enhancement(interaction, self.item_row['item_id'])

    async def market_sell(self, interaction: discord.Interaction):
        await self.enhancement_cog.show_market_sell_confirmation(interaction, self.item_row['item_id'])


class MarketplaceView(discord.ui.View):
    """Paginated marketplace with filtering and search capabilities"""

    def __init__(self, bot, guild_id, page=0, filter_slot=None, search_term=None, sort_by="price_low"):
        super().__init__(timeout=None)  # Persistent view should not time out
        self.bot = bot
        self.guild_id = guild_id
        self.page = page
        self.filter_slot = filter_slot
        self.search_term = search_term
        self.sort_by = sort_by
        self.items_per_page = 5  # Reduced to 5 to fit purchase buttons on screen
        self.enhancement_cog = bot.get_cog('EnhancementCog')

    async def get_filtered_items_and_count(self) -> Tuple[List, int]:
        """Get marketplace items and total count with filters applied"""
        base_query = "FROM marketplace m JOIN item_templates it ON m.template_id = it.id WHERE m.guild_id = $1"
        params = [self.guild_id]
        param_count = 2

        filter_clause = ""
        if self.filter_slot:
            filter_clause += f" AND it.slot_type = ${param_count}"
            params.append(self.filter_slot)
            param_count += 1
        if self.search_term:
            filter_clause += f" AND it.name ILIKE ${param_count}"
            params.append(f"%{self.search_term}%")
            param_count += 1

        count_query = f"SELECT COUNT(*) {base_query} {filter_clause}"
        total_items = await self.bot.pool.fetchval(count_query, *params) or 0

        sort_map = {
            "price_low": "ORDER BY m.price ASC", "price_high": "ORDER BY m.price DESC",
            "level_high": "ORDER BY m.enhancement_level DESC", "newest": "ORDER BY m.listed_at DESC"
        }
        sort_order = sort_map.get(self.sort_by, "ORDER BY m.listed_at DESC")

        select_query = f"""
            SELECT m.market_id, m.seller_id, m.template_id, m.enhancement_level, m.price, m.listed_at
            {base_query} {filter_clause} {sort_order}
            LIMIT {self.items_per_page} OFFSET {self.page * self.items_per_page}
        """
        rows = await self.bot.pool.fetch(select_query, *params)
        items = [(row, self.enhancement_cog.get_item_template(row['template_id'])) for row in rows if
                 self.enhancement_cog.get_item_template(row['template_id'])]
        return items, total_items

    async def refresh_view(self, interaction: discord.Interaction):
        """Refresh the marketplace view with current filters"""
        await interaction.response.defer()
        items, total_items = await self.get_filtered_items_and_count()
        total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)
        self.page = min(self.page, total_pages - 1) if total_pages > 0 else 0

        embed = discord.Embed(
            title="🏪 아이템 마켓플레이스",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        if not items:
            embed.description = "📦 조건에 맞는 아이템이 없습니다. 필터를 조정해보세요!"
        else:
            item_list = []
            for i, (market_entry, template) in enumerate(items):
                enhancement_text = f"+{market_entry['enhancement_level']}" if market_entry[
                                                                                  'enhancement_level'] > 0 else ""
                item_list.append(
                    f"**{self.page * self.items_per_page + i + 1}.** {template['emoji']} **{template['name']}** {enhancement_text}\n"
                    f"   └ 💰 **{market_entry['price']:,}** 코인 | 판매자: <@{market_entry['seller_id']}>"
                )
            embed.description = "\n".join(item_list)

        filter_info = [f"슬롯: {self.filter_slot}" if self.filter_slot else None,
                       f"검색: {self.search_term}" if self.search_term else None]
        filter_text = " | ".join(filter(None, filter_info)) or "필터 없음"
        embed.set_footer(text=f"페이지 {self.page + 1}/{total_pages} | 정렬: {self.get_sort_name()} | 필터: {filter_text}")

        self.clear_items()
        self.add_navigation_buttons(total_pages)
        self.add_filter_buttons()
        self.add_purchase_buttons(items)

        await interaction.edit_original_response(embed=embed, view=self)

    def get_sort_name(self):
        return {"price_low": "가격 낮은순", "price_high": "가격 높은순", "level_high": "강화 높은순", "newest": "최신순"}.get(
            self.sort_by, "최신순")

    def add_navigation_buttons(self, total_pages):
        prev_button = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page <= 0, row=0)
        prev_button.callback = self.previous_page
        self.add_item(prev_button)

        page_button = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary,
                                        disabled=True, row=0)
        self.add_item(page_button)

        next_button = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary,
                                        disabled=self.page >= total_pages - 1, row=0)
        next_button.callback = self.next_page
        self.add_item(next_button)

    def add_filter_buttons(self):
        sort_select = discord.ui.Select(placeholder="정렬 방식 선택...", row=1, options=[
            discord.SelectOption(label="가격 낮은순", value="price_low", emoji="💰"),
            discord.SelectOption(label="가격 높은순", value="price_high", emoji="💎"),
            discord.SelectOption(label="강화 높은순", value="level_high", emoji="⭐"),
            discord.SelectOption(label="최신순", value="newest", emoji="🕐"),
        ])
        sort_select.callback = self.change_sort
        self.add_item(sort_select)

        slot_options = [discord.SelectOption(label="모든 슬롯", value="all", emoji="📦")] + \
                       [discord.SelectOption(label=slot, value=slot) for slot in self.enhancement_cog.equipment_slots]
        slot_select = discord.ui.Select(placeholder="슬롯 필터...", options=slot_options[:25], row=2)
        slot_select.callback = self.change_slot_filter
        self.add_item(slot_select)

    def add_purchase_buttons(self, items):
        if not items: return

        options = []
        for i, (market_entry, template) in enumerate(items):
            enhancement_text = f" +{market_entry['enhancement_level']}" if market_entry['enhancement_level'] > 0 else ""
            options.append(discord.SelectOption(
                label=f"{template['name'][:20]}{enhancement_text} ({market_entry['price']:,} 코인)",
                value=market_entry['market_id'],
                emoji=template['emoji']
            ))

        purchase_select = discord.ui.Select(placeholder="구매할 아이템 선택...", options=options, row=3)
        purchase_select.callback = self.purchase_item
        self.add_item(purchase_select)

    async def purchase_item(self, interaction: discord.Interaction):
        market_id = interaction.data['values'][0]
        await self.enhancement_cog.handle_market_purchase(interaction, market_id)

    async def previous_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self.refresh_view(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        await self.refresh_view(interaction)

    async def change_sort(self, interaction: discord.Interaction):
        self.sort_by = interaction.data['values'][0]
        self.page = 0
        await self.refresh_view(interaction)

    async def change_slot_filter(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        self.filter_slot = None if value == "all" else value
        self.page = 0
        await self.refresh_view(interaction)


class CharacterView(UserCheckView):
    """Enhanced character sheet view"""

    def __init__(self, bot, user_id, guild_id):
        super().__init__(timeout=300, user_id=user_id)
        self.bot = bot
        self.guild_id = guild_id
        self.enhancement_cog = bot.get_cog('EnhancementCog')

    @discord.ui.button(label="🎒 인벤토리", style=discord.ButtonStyle.secondary)
    async def view_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.show_inventory(interaction)

    @discord.ui.button(label="⚔️ 장비 관리", style=discord.ButtonStyle.primary)
    async def manage_equipment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.show_equipment_manager(interaction)


class EnhancementResultView(UserCheckView):
    """View for enhancement results with action buttons"""

    def __init__(self, bot, user_id, guild_id, item_row, template):
        super().__init__(timeout=300, user_id=user_id)
        self.bot = bot
        self.guild_id = guild_id
        self.item_row = item_row
        self.template = template
        self.enhancement_cog = bot.get_cog('EnhancementCog')

        # Add buttons only if item still exists
        if self.item_row:
            self.add_item(discord.ui.Button(label="⚡ 다시 강화하기", style=discord.ButtonStyle.primary, emoji="⭐",
                                            custom_id="enhance_again"))
            self.add_item(discord.ui.Button(label="🔹 장착하기", style=discord.ButtonStyle.success, custom_id="equip_item"))
            self.add_item(
                discord.ui.Button(label="💰 마켓 판매", style=discord.ButtonStyle.secondary, custom_id="sell_item"))

    @discord.ui.button(label="⚡ 다시 강화하기", style=discord.ButtonStyle.primary, emoji="⭐")
    async def enhance_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.handle_enhancement(interaction, self.item_row['item_id'])

    @discord.ui.button(label="🔹 장착하기", style=discord.ButtonStyle.success)
    async def equip_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.equip_item(interaction, self.item_row['item_id'])

    @discord.ui.button(label="💰 마켓 판매", style=discord.ButtonStyle.secondary)
    async def sell_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.enhancement_cog.show_market_sell_confirmation(interaction, self.item_row['item_id'])


class EnhancementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("강화 시스템")

        # Config keys
        self.marketplace_channel_key = "marketplace_channel"
        self.showoff_channel_key = "showoff_channel"

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
            "일반": {"name": "일반", "color": 0xaaaaaa, "weight": 45},
            "고급": {"name": "고급", "color": 0x55ff55, "weight": 30},
            "희귀": {"name": "희귀", "color": 0x5555ff, "weight": 15},
            "영웅": {"name": "영웅", "color": 0xaa55ff, "weight": 7},
            "고유": {"name": "고유", "color": 0xffaa00, "weight": 2.5},
            "전설": {"name": "전설", "color": 0xff5555, "weight": 0.4},
            "신화": {"name": "신화", "color": 0xffd700, "weight": 0.1}
        }

        self.equipment_slots = [
            "무기", "보조무기", "모자", "상의", "하의", "신발",
            "장갑", "망토", "목걸이", "귀걸이", "반지", "벨트"
        ]

        self.starforce_rates = {
            # level: (success%, fail_maintain%, fail_decrease%, destroy%)
            0: (95, 5, 0, 0), 1: (90, 10, 0, 0), 2: (85, 15, 0, 0), 3: (85, 15, 0, 0), 4: (80, 20, 0, 0),
            5: (75, 25, 0, 0), 6: (70, 30, 0, 0), 7: (65, 35, 0, 0), 8: (60, 40, 0, 0), 9: (55, 45, 0, 0),
            10: (50, 50, 0, 0), 11: (45, 0, 55, 0), 12: (40, 0, 60, 0), 13: (35, 0, 65, 0), 14: (30, 0, 70, 0),
            15: (30, 67.9, 0, 2.1), 16: (30, 0, 67.9, 2.1), 17: (30, 0, 67.9, 2.1), 18: (30, 0, 67.2, 2.8),
            19: (30, 0, 67.2, 2.8),
            20: (30, 63, 0, 7), 21: (30, 0, 63, 7), 22: (3, 0, 77.6, 19.4), 23: (2, 0, 68.6, 29.4),
            24: (1, 0, 59.4, 39.6)
        }

        self.item_templates = {}
        self.bot.loop.create_task(self.load_item_templates())
        self.bot.loop.create_task(self.setup_system())

    async def load_item_templates(self):
        await self.bot.wait_until_ready()
        try:
            if await self.load_templates_from_db():
                self.logger.info("아이템 템플릿을 데이터베이스에서 로드했습니다.")
                return
            if await self.load_templates_from_json():
                self.logger.info("아이템 템플릿을 JSON 파일에서 로드했으며, DB에 저장합니다.")
                await self.save_templates_to_db()
                return
            await self.generate_initial_templates()
            self.logger.info("초기 아이템 템플릿을 생성하고 DB에 저장합니다.")
            await self.save_templates_to_db()
        except Exception as e:
            self.logger.error(f"아이템 템플릿 로드 실패: {e}")

    async def load_templates_from_db(self) -> bool:
        rows = await self.bot.pool.fetch("SELECT * FROM item_templates ORDER BY id")
        if not rows:
            return False
        for row in rows:
            self.item_templates[row['id']] = dict(row)
            self.item_templates[row['id']]['base_stats'] = json.loads(row['base_stats'])
        return len(self.item_templates) > 0

    async def load_templates_from_json(self) -> bool:
        json_path = os.path.join('data', 'items.json')
        if not os.path.exists(json_path): return False
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                templates = json.load(f)
            for template in templates:
                self.item_templates[template['id']] = template
            return len(self.item_templates) > 0
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"JSON 템플릿 로드 실패: {e}")
            return False

    async def save_templates_to_db(self):
        if not self.item_templates:
            return
        try:
            await self.bot.pool.execute("TRUNCATE TABLE item_templates RESTART IDENTITY CASCADE;")
            records_to_copy = [
                (t['id'], t['name'], t['slot_type'], t.get('class_req'), t['rarity'],
                 t['emoji'], json.dumps(t['base_stats']), t['base_price'])
                for t in self.item_templates.values()
            ]
            await self.bot.pool.copy_records_to_table(
                'item_templates',
                records=records_to_copy,
                columns=('id', 'name', 'slot_type', 'class_req', 'rarity', 'emoji', 'base_stats', 'base_price')
            )
            self.logger.info(f"{len(records_to_copy)}개의 템플릿을 데이터베이스에 저장했습니다.")
        except Exception as e:
            self.logger.error(f"DB 템플릿 저장 실패: {e}")

    async def generate_initial_templates(self):
        templates = []
        item_id_counter = 1
        weapon_types = {
            "무기": {"전사": ["대검", "도끼"], "법사": ["스태프", "완드"], "도적": ["단검", "클로"], "궁수": ["활", "석궁"], "해적": ["건", "너클"]}
        }
        for class_name, weapons in weapon_types["무기"].items():
            for weapon in weapons:
                for tier in range(3):
                    for rarity in ["일반", "고급", "희귀", "영웅"]:
                        name = f"{rarity} {weapon} T{tier + 1}"
                        templates.append({
                            "id": item_id_counter, "name": name, "slot_type": "무기", "class_req": class_name,
                            "rarity": rarity,
                            "emoji": self.get_weapon_emoji(weapon),
                            "base_stats": self.generate_weapon_stats(class_name, tier, rarity),
                            "base_price": self.calculate_base_price(rarity, tier)
                        })
                        item_id_counter += 1
        armor_slots = ["모자", "상의", "하의", "신발", "장갑", "망토"]
        for slot in armor_slots:
            for tier in range(3):
                for rarity in ["일반", "고급", "희귀", "영웅"]:
                    name = f"{rarity} {slot} T{tier + 1}"
                    templates.append({
                        "id": item_id_counter, "name": name, "slot_type": slot, "class_req": None, "rarity": rarity,
                        "emoji": self.get_armor_emoji(slot),
                        "base_stats": self.generate_armor_stats(slot, tier, rarity),
                        "base_price": self.calculate_base_price(rarity, tier)
                    })
                    item_id_counter += 1
        for t in templates:
            self.item_templates[t['id']] = t
        os.makedirs('data', exist_ok=True)
        with open('data/items.json', 'w', encoding='utf-8') as f:
            json.dump(templates, f, indent=2, ensure_ascii=False)

    def get_weapon_emoji(self, weapon: str) -> str:
        return {"대검": "⚔️", "도끼": "🪓", "둔기": "🔨", "스태프": "🔮", "완드": "🪄", "단검": "🗡️", "클로": "🐾", "활": "🏹", "석궁": "🎯",
                "건": "🔫", "너클": "👊"}.get(weapon, "⚔️")

    def get_armor_emoji(self, slot: str) -> str:
        return {"모자": "👑", "상의": "👕", "하의": "👖", "신발": "👟", "장갑": "🧤", "망토": "🦹"}.get(slot, "🛡️")

    def get_accessory_emoji(self, slot: str) -> str:
        return {"목걸이": "📿", "귀걸이": "💎", "반지": "💍", "벨트": "⚡"}.get(slot, "✨")

    def generate_weapon_stats(self, class_name: str, tier: int, rarity: str) -> Dict[str, int]:
        mult = (tier * 2 + 1) * self.get_rarity_multiplier(rarity)
        stats = {"str": 0, "dex": 0, "int": 0, "luk": 0, "att": 0, "m_att": 0}
        if class_name == "전사":
            stats["str"], stats["att"] = int(random.randint(8, 12) * mult), int(random.randint(10, 15) * mult)
        elif class_name == "법사":
            stats["int"], stats["m_att"] = int(random.randint(8, 12) * mult), int(random.randint(10, 15) * mult)
        elif class_name in ["도적", "궁수"]:
            stats["dex"], stats["att"] = int(random.randint(8, 12) * mult), int(random.randint(9, 13) * mult)
        elif class_name == "해적":
            stats["str"], stats["dex"], stats["att"] = int(random.randint(4, 7) * mult), int(
                random.randint(4, 7) * mult), int(random.randint(8, 12) * mult)
        return {k: v for k, v in stats.items() if v > 0}

    def generate_armor_stats(self, slot: str, tier: int, rarity: str) -> Dict[str, int]:
        mult = (tier * 1.5 + 1) * self.get_rarity_multiplier(rarity)
        stat_pool = int(random.randint(10, 15) * mult)
        stats = {"str": 0, "dex": 0, "int": 0, "luk": 0}
        for _ in range(random.randint(1, 3)):
            if stat_pool <= 1: break
            stat = random.choice(list(stats.keys()))
            value = random.randint(1, max(1, stat_pool // 2))
            stats[stat] += value
            stat_pool -= value
        return {k: v for k, v in stats.items() if v > 0}

    def get_rarity_multiplier(self, rarity: str) -> float:
        return {"일반": 1.0, "고급": 1.3, "희귀": 1.7, "영웅": 2.2, "고유": 2.8, "전설": 3.6, "신화": 4.5}.get(rarity, 1.0)

    def calculate_base_price(self, rarity: str, tier: int) -> int:
        rarity_prices = {"일반": 100, "고급": 250, "희귀": 500, "영웅": 1000, "고유": 2500, "전설": 6000, "신화": 15000}
        return int(rarity_prices.get(rarity, 100) * (tier + 1) ** 1.5)

    def calculate_enhancement_cost(self, template: Dict, current_level: int) -> int:
        base_price = template['base_price']
        level_multiplier = (current_level + 1) ** 1.8
        rarity_multiplier = self.get_rarity_multiplier(template['rarity'])
        cost = int((base_price / 20) * level_multiplier * rarity_multiplier)
        return max(50, cost)

    def get_enhancement_rates(self, current_level: int, fail_streak: int) -> Tuple[float, float, float, float]:
        if fail_streak >= 2 and current_level < 15:
            return 100.0, 0.0, 0.0, 0.0
        rates = self.starforce_rates.get(current_level, (1, 0, 59.4, 39.6))
        return rates[0], rates[1], rates[2], rates[3]

    def calculate_market_price(self, template: Dict, enhancement_level: int) -> int:
        base_price = template['base_price']
        total_enhancement_cost = sum(self.calculate_enhancement_cost(template, i) for i in range(enhancement_level))
        rarity_market_multipliers = {"일반": 1.0, "고급": 1.5, "희귀": 2.2, "영웅": 3.5, "고유": 5.5, "전설": 8.0, "신화": 12.0}
        rarity_multiplier = rarity_market_multipliers.get(template['rarity'], 1.0)
        enhancement_multiplier = 1.0 + (enhancement_level * 0.2) + (enhancement_level ** 2.5 * 0.01)
        risk_premium = 1.0 + (max(0, enhancement_level - 14) * 0.15)
        final_price = int(
            ((base_price * rarity_multiplier) + (total_enhancement_cost * 1.2)) * enhancement_multiplier * risk_premium)
        return max(final_price, base_price)

    def get_enhancement_cost_breakdown(self, template: dict, enhancement_level: int) -> Dict[str, int]:
        total_cost = sum(self.calculate_enhancement_cost(template, i) for i in range(enhancement_level))
        return {
            'total_enhancement_cost': total_cost,
            'cost_recovery_120pct': int(total_cost * 1.2),
            'next_level_cost': self.calculate_enhancement_cost(template,
                                                               enhancement_level) if enhancement_level < 24 else 0
        }

    def calculate_combat_power(self, stats: Dict[str, int]) -> int:
        power = 0
        power += (stats.get("str", 0) + stats.get("dex", 0) + stats.get("int", 0) + stats.get("luk", 0)) * 4
        power += (stats.get("att", 0) + stats.get("m_att", 0)) * 10
        return max(1, int(power))

    def get_random_item(self) -> Optional[Dict[str, Any]]:
        if not self.item_templates: return None
        rarities, weights = zip(*[(r, d['weight']) for r, d in self.item_rarities.items()])
        chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
        eligible_items = [t for t in self.item_templates.values() if t['rarity'] == chosen_rarity]
        return random.choice(eligible_items).copy() if eligible_items else None

    async def setup_system(self):
        await self.bot.wait_until_ready()
        await self.setup_database()
        self.bot.add_view(MarketplaceView(self.bot, 0))  # Guild ID is a placeholder, as it's set on interaction
        if not self.update_marketplace.is_running():
            self.update_marketplace.start()

    async def setup_database(self):
        self.logger.info("Checking database schema...")
        await self.bot.pool.execute("""
            CREATE TABLE IF NOT EXISTS item_templates (
                id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, slot_type VARCHAR(20) NOT NULL,
                class_req VARCHAR(20), rarity VARCHAR(20) NOT NULL, emoji VARCHAR(10) NOT NULL,
                base_stats JSONB NOT NULL, base_price INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_characters (
                user_id BIGINT, guild_id BIGINT, character_class VARCHAR(20) NOT NULL,
                last_class_change TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, guild_id)
            );
            CREATE TABLE IF NOT EXISTS user_items (
                item_id VARCHAR(36) PRIMARY KEY, user_id BIGINT NOT NULL, guild_id BIGINT NOT NULL,
                template_id INTEGER NOT NULL REFERENCES item_templates(id) ON DELETE CASCADE,
                enhancement_level INTEGER DEFAULT 0, is_equipped BOOLEAN DEFAULT FALSE,
                equipped_slot VARCHAR(20), fail_streak INTEGER DEFAULT 0, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_enhanced TIMESTAMPTZ
            );
            CREATE TABLE IF NOT EXISTS user_equipment (
                user_id BIGINT, guild_id BIGINT, slot_name VARCHAR(20), item_id VARCHAR(36) UNIQUE,
                equipped_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, guild_id, slot_name),
                FOREIGN KEY (item_id) REFERENCES user_items(item_id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS enhancement_logs (
                log_id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, guild_id BIGINT NOT NULL,
                item_id VARCHAR(36), old_level INTEGER NOT NULL, new_level INTEGER NOT NULL,
                result VARCHAR(20) NOT NULL, cost INTEGER NOT NULL, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS marketplace (
                market_id VARCHAR(36) PRIMARY KEY, seller_id BIGINT NOT NULL, guild_id BIGINT NOT NULL,
                item_id VARCHAR(36) NOT NULL UNIQUE REFERENCES user_items(item_id) ON DELETE CASCADE,
                template_id INTEGER NOT NULL, enhancement_level INTEGER NOT NULL, price BIGINT NOT NULL,
                listed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS guild_persistent_messages (
                guild_id BIGINT PRIMARY KEY,
                marketplace_message_id BIGINT
            );
        """)
        self.logger.info("강화 시스템 데이터베이스가 준비되었습니다.")

    @tasks.loop(minutes=10)
    async def update_marketplace(self):
        self.logger.info("Periodically updating marketplace messages...")
        rows = await self.bot.pool.fetch("SELECT guild_id FROM guild_persistent_messages")
        for row in rows:
            await self.update_or_create_marketplace_message(row['guild_id'])

    @update_marketplace.before_loop
    async def before_update_marketplace(self):
        await self.bot.wait_until_ready()

    async def update_or_create_marketplace_message(self, guild_id: int):
        channel_id = config.get_channel_id(guild_id, self.marketplace_channel_key)
        if not channel_id: return
        channel = self.bot.get_channel(channel_id)
        if not channel: return

        message_row = await self.bot.pool.fetchrow(
            "SELECT marketplace_message_id FROM guild_persistent_messages WHERE guild_id = $1", guild_id)
        message_id = message_row['marketplace_message_id'] if message_row else None

        # Build the view with the guild_id
        view = MarketplaceView(self.bot, guild_id)

        # We need to build a placeholder embed to send/edit. The view will handle the dynamic content.
        embed = discord.Embed(
            title="🏪 아이템 마켓플레이스",
            description="아이템을 구매하거나 필터를 적용하려면 아래 메뉴를 이용해주세요. 로딩 중...",
            color=discord.Color.gold()
        )

        message = None
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                self.logger.info(f"Updated marketplace message in guild {guild_id}")
            except (discord.NotFound, discord.Forbidden):
                message = None

        if not message:
            try:
                # Clean up old bot messages
                async for old_msg in channel.history(limit=10):
                    if old_msg.author == self.bot.user:
                        await old_msg.delete()
            except discord.Forbidden:
                pass

            try:
                new_message = await channel.send(embed=embed, view=view)
                await self.bot.pool.execute("""
                    INSERT INTO guild_persistent_messages (guild_id, marketplace_message_id) VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO UPDATE SET marketplace_message_id = $2
                """, guild_id, new_message.id)
                self.logger.info(f"Created new marketplace message in guild {guild_id}")
            except (discord.Forbidden, discord.HTTPException) as e:
                self.logger.error(f"Failed to create marketplace message in guild {guild_id}: {e}")

    async def get_user_character(self, user_id: int, guild_id: int) -> Optional[Dict]:
        return await self.bot.pool.fetchrow("SELECT * FROM user_characters WHERE user_id = $1 AND guild_id = $2",
                                            user_id, guild_id)

    async def create_item_in_db(self, user_id: int, guild_id: int, item_data: Dict) -> str:
        item_id = str(uuid.uuid4())
        await self.bot.pool.execute("""
            INSERT INTO user_items (item_id, user_id, guild_id, template_id)
            VALUES ($1, $2, $3, $4)
        """, item_id, user_id, guild_id, item_data['id'])
        return item_id

    def get_item_template(self, template_id: int) -> Optional[Dict]:
        return self.item_templates.get(template_id)

    async def handle_enhancement(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id

        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
                item_row = await conn.fetchrow(
                    "SELECT * FROM user_items WHERE item_id = $1 AND user_id = $2 FOR UPDATE", item_id, user_id)
                if not item_row:
                    return await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)

                template = self.get_item_template(item_row['template_id'])
                current_level, fail_streak = item_row['enhancement_level'], item_row['fail_streak']

                if current_level >= 24:
                    return await interaction.followup.send("❌ 이 아이템은 이미 최대 강화 레벨입니다.", ephemeral=True)

                cost = self.calculate_enhancement_cost(template, current_level)

                coins_cog = self.bot.get_cog('CoinsCog')
                if not coins_cog or not await coins_cog.remove_coins(user_id, guild_id, cost, "enhancement",
                                                                     f"아이템 강화: {template['name']}"):
                    return await interaction.followup.send(f"❌ 코인이 부족합니다. 필요: {cost:,} 코인", ephemeral=True)

                success_rate, maintain_rate, decrease_rate, destroy_rate = self.get_enhancement_rates(current_level,
                                                                                                      fail_streak)
                rand = random.uniform(0, 100)

                old_level, new_level, new_fail_streak = current_level, current_level, fail_streak

                if rand < success_rate:
                    result, new_level, new_fail_streak = "success", old_level + 1, 0
                elif rand < success_rate + destroy_rate:
                    result, new_level, new_fail_streak = "destroy", -1, 0
                elif rand < success_rate + destroy_rate + decrease_rate:
                    result, new_level, new_fail_streak = "decrease", max(0, old_level - 1), fail_streak + 1
                else:
                    result, new_level, new_fail_streak = "maintain", old_level, fail_streak + 1

                updated_item_row = None
                if result == "destroy":
                    await conn.execute("DELETE FROM user_items WHERE item_id = $1", item_id)
                else:
                    updated_item_row = await conn.fetchrow("""
                        UPDATE user_items SET enhancement_level = $1, fail_streak = $2, last_enhanced = NOW()
                        WHERE item_id = $3 RETURNING *
                    """, new_level, new_fail_streak, item_id)

                await conn.execute("""
                    INSERT INTO enhancement_logs (user_id, guild_id, item_id, old_level, new_level, result, cost)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, user_id, guild_id, item_id, old_level, new_level, result, cost)

        await self.send_enhancement_result(interaction, template, item_row, result, updated_item_row)
        if (result == "success" and new_level >= 10) or result in ["destroy", "decrease"]:
            await self.post_enhancement_to_showoff(guild_id, user_id, template, old_level, new_level, result)

    async def send_enhancement_result(self, interaction: discord.Interaction, template: Dict, old_item_row: Dict,
                                      result: str, new_item_row: Optional[Dict]):
        old_level = old_item_row['enhancement_level']
        result_map = {
            "success": ("✅ 강화 성공!", discord.Color.green()), "maintain": ("⏺️ 강화 실패 (등급 유지)", discord.Color.gold()),
            "decrease": ("🔽 강화 실패 (등급 하락)", discord.Color.orange()), "destroy": ("💥 아이템 파괴...", discord.Color.red())
        }
        title, color = result_map[result]
        embed = discord.Embed(title=title, color=color)
        level_text = f"+{old_level} → 파괴됨" if result == 'destroy' else f"+{old_level} → +{new_item_row['enhancement_level']}"
        embed.add_field(name="아이템", value=f"{template['emoji']} **{template['name']}**", inline=False)
        embed.add_field(name="강화 결과", value=level_text, inline=False)

        view = None
        if new_item_row:
            embed.set_footer(text="계속해서 강화하거나 장착, 판매할 수 있습니다.")
            view = EnhancementResultView(self.bot, interaction.user.id, interaction.guild.id, new_item_row, template)

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def post_enhancement_to_showoff(self, guild_id, user_id, template, old_level, new_level, result):
        channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
        if not channel_id or not (channel := self.bot.get_channel(channel_id)): return

        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        result_map = {"success": "강화 성공!", "decrease": "강화 등급 하락", "destroy": "아이템 파괴"}
        title = f"🎉 {user.display_name}님의 {result_map.get(result, '강화 결과')}"
        level_text = f"+{old_level} → +{new_level}" if result != "destroy" else f"+{old_level} → 💥파괴"

        embed = discord.Embed(title=title, color=discord.Color.blue())
        embed.add_field(name=f"{template['emoji']} {template['name']}", value=level_text)
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("EnhancementCog is ready.")
        if not self.update_marketplace.is_running():
            self.update_marketplace.start()

    # --- ALL APP COMMANDS ---

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
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id
        current_character = await self.get_user_character(user_id, guild_id)

        if current_character:
            last_change = current_character['last_class_change']
            if datetime.now(timezone.utc) - last_change < timedelta(days=30):
                days_remaining = 30 - (datetime.now(timezone.utc) - last_change).days
                return await interaction.followup.send(
                    f"❌ 직업 변경은 월 1회만 가능합니다. (남은 시간: {days_remaining}일)", ephemeral=True
                )

        await self.bot.pool.execute("""
            INSERT INTO user_characters (user_id, guild_id, character_class, last_class_change)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_id, guild_id) DO UPDATE SET 
                character_class = EXCLUDED.character_class, last_class_change = EXCLUDED.last_class_change
        """, user_id, guild_id, character_class)

        class_info = self.character_classes[character_class]
        embed = discord.Embed(title="✅ 직업 선택 완료!",
                              description=f"{class_info['emoji']} **{class_info['name']}**으로 전직했습니다!",
                              color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

        channel_id = config.get_channel_id(guild_id, self.showoff_channel_key)
        if channel_id and (channel := self.bot.get_channel(channel_id)):
            showoff_embed = discord.Embed(title=f"🎯 새로운 {character_class} 등장!", color=discord.Color.green())
            showoff_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            await channel.send(embed=showoff_embed)

    @app_commands.command(name="캐릭터", description="캐릭터 정보와 장착된 장비를 확인합니다.")
    @app_commands.describe(user="확인할 사용자 (비어두면 본인)")
    async def character_sheet(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        target_user = user or interaction.user
        guild_id = interaction.guild.id

        character_data = await self.get_user_character(target_user.id, guild_id)
        if not character_data:
            return await interaction.followup.send("`/직업선택` 명령어로 먼저 캐릭터를 생성해주세요!", ephemeral=True)

        total_stats = await self.calculate_total_stats(target_user.id, guild_id)
        combat_power = self.calculate_combat_power(total_stats)

        class_info = self.character_classes[character_data['character_class']]
        embed = discord.Embed(title=f"{class_info['emoji']} {target_user.display_name}의 캐릭터 정보",
                              color=discord.Color.blue())
        embed.set_author(name=target_user.display_name, icon_url=target_user.display_avatar.url)
        embed.add_field(name="직업", value=f"{class_info['emoji']} {class_info['name']}", inline=True)
        embed.add_field(name="⚔️ 전투력", value=f"**{combat_power:,}**", inline=True)

        stats_text = " | ".join(
            [f"{stat.upper()}: {value}" for stat, value in total_stats.items() if value > 0]) or "능력치 없음"
        embed.add_field(name="📊 총 능력치", value=stats_text, inline=False)

        equipped_items = await self.get_equipped_items(target_user.id, guild_id)
        equipment_text = []
        for slot in self.equipment_slots:
            if item_data := equipped_items.get(slot):
                template = self.get_item_template(item_data['template_id'])
                enhancement = f"+{item_data['enhancement_level']}"
                equipment_text.append(f"**{slot}**: {template['emoji']} {template['name']} {enhancement}")
            else:
                equipment_text.append(f"**{slot}**: -")
        embed.add_field(name="⚔️ 장착 장비", value="\n".join(equipment_text), inline=False)

        view = CharacterView(self.bot, interaction.user.id, guild_id) if target_user.id == interaction.user.id else None
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="아이템정보", description="보유한 아이템의 상세 정보를 확인합니다.")
    @app_commands.describe(item_id="확인할 아이템의 고유 ID")
    async def item_info(self, interaction: discord.Interaction, item_id: str):
        await self.show_item_management(interaction, item_id)

    @app_commands.command(name="마켓", description="아이템 마켓플레이스를 엽니다.")
    async def market(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Find the marketplace view and "click" it for the user
        channel_id = config.get_channel_id(interaction.guild_id, self.marketplace_channel_key)
        if not channel_id or not (channel := self.bot.get_channel(channel_id)):
            return await interaction.followup.send("마켓 채널이 설정되지 않았습니다.", ephemeral=True)

        row = await self.bot.pool.fetchrow(
            "SELECT marketplace_message_id FROM guild_persistent_messages WHERE guild_id = $1", interaction.guild_id)
        if not row:
            await self.update_or_create_marketplace_message(interaction.guild_id)
            return await interaction.followup.send("마켓 메시지를 생성했습니다. 다시 시도해주세요.", ephemeral=True)

        try:
            msg = await channel.fetch_message(row['marketplace_message_id'])
            await interaction.followup.send(f"마켓은 {msg.jump_url} 채널에서 확인해주세요!", ephemeral=True)
        except (discord.NotFound, discord.Forbidden):
            await self.update_or_create_marketplace_message(interaction.guild_id)
            await interaction.followup.send("마켓 메시지를 새로고침했습니다. 채널을 확인해주세요.", ephemeral=True)

    # --- HELPER METHODS FOR COMMANDS ---

    async def show_detailed_item_info(self, interaction: discord.Interaction, item_id: str):
        await self.show_item_management(interaction, item_id)

    async def get_equipped_items(self, user_id: int, guild_id: int) -> Dict[str, Dict]:
        rows = await self.bot.pool.fetch("""
            SELECT ue.slot_name, ui.template_id, ui.enhancement_level, ui.item_id
            FROM user_equipment ue JOIN user_items ui ON ue.item_id = ui.item_id
            WHERE ue.user_id = $1 AND ue.guild_id = $2
        """, user_id, guild_id)
        return {row['slot_name']: dict(row) for row in rows}

    async def calculate_total_stats(self, user_id: int, guild_id: int) -> Dict[str, int]:
        equipped_items = await self.get_equipped_items(user_id, guild_id)
        total_stats = {"str": 0, "dex": 0, "int": 0, "luk": 0, "att": 0, "m_att": 0}
        for item_data in equipped_items.values():
            template = self.get_item_template(item_data['template_id'])
            if template:
                for stat, value in template['base_stats'].items():
                    # Simplified enhancement bonus: 5% of base stat per level
                    enh_bonus = int(value * 0.05 * item_data['enhancement_level'])
                    total_stats[stat] += value + enh_bonus
        return total_stats

    async def show_inventory(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id
        items = await self.bot.pool.fetch("""
            SELECT item_id, template_id, enhancement_level, is_equipped FROM user_items
            WHERE user_id = $1 AND guild_id = $2 ORDER BY created_at DESC LIMIT 25
        """, user_id, guild_id)
        if not items:
            return await interaction.followup.send("🎒 인벤토리가 비어있습니다.", ephemeral=True)

        embed = discord.Embed(title=f"{interaction.user.display_name}의 인벤토리", color=discord.Color.blue())
        description = []
        for item in items:
            template = self.get_item_template(item['template_id'])
            enh = f"+{item['enhancement_level']}" if item['enhancement_level'] > 0 else ""
            eq = "🔒" if item['is_equipped'] else ""
            description.append(f"{template['emoji']} **{template['name']}** {enh} {eq} (`{item['item_id'][:6]}`)")
        embed.description = "\n".join(description)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def show_equipment_manager(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id
        items = await self.bot.pool.fetch("""
            SELECT item_id, template_id, enhancement_level, is_equipped FROM user_items
            WHERE user_id = $1 AND guild_id = $2 ORDER BY is_equipped DESC, created_at DESC
        """, user_id, guild_id)
        if not items:
            return await interaction.followup.send("📦 보유한 아이템이 없습니다.", ephemeral=True)

        items_by_slot = {slot: [] for slot in self.equipment_slots}
        for item in items:
            template = self.get_item_template(item['template_id'])
            if template and template['slot_type'] in items_by_slot:
                items_by_slot[template['slot_type']].append((item, template))

        embed = discord.Embed(title="⚔️ 장비 관리", description="관리할 장비의 종류를 선택하세요.", color=discord.Color.dark_grey())
        view = EquipmentSelectView(self.bot, user_id, guild_id, items_by_slot)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def show_slot_items(self, interaction: discord.Interaction, slot_type: str, items: List):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title=f"📦 {slot_type} 아이템 목록", description="관리할 아이템을 선택하세요.", color=discord.Color.blue())
        view = SlotItemsView(self.bot, interaction.user.id, interaction.guild.id, slot_type, items)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def show_item_management(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id
        item_row = await self.bot.pool.fetchrow(
            "SELECT * FROM user_items WHERE item_id = $1 AND (user_id = $2 OR user_id = 0)", item_id, user_id)
        if not item_row:
            return await interaction.followup.send("❌ 아이템을 찾을 수 없거나, 당신의 아이템이 아닙니다.", ephemeral=True)

        template = self.get_item_template(item_row['template_id'])
        rarity_info = self.item_rarities[template['rarity']]
        embed = discord.Embed(title=f"{template['emoji']} {template['name']}", color=rarity_info['color'])
        embed.add_field(name="강화", value=f"+{item_row['enhancement_level']}", inline=True)
        embed.add_field(name="등급", value=rarity_info['name'], inline=True)
        embed.add_field(name="종류", value=template['slot_type'], inline=True)

        stats = template['base_stats']
        stats_text = " | ".join([f"{k.upper()}: {v}" for k, v in stats.items()])
        embed.add_field(name="기본 능력치", value=stats_text, inline=False)

        if item_row['enhancement_level'] < 24:
            cost = self.calculate_enhancement_cost(template, item_row['enhancement_level'])
            rates = self.get_enhancement_rates(item_row['enhancement_level'], item_row['fail_streak'])
            enh_info = f"비용: {cost:,} 코인 | 성공: {rates[0]}% | 파괴: {rates[3]}%"
            embed.add_field(name="⚡ 다음 강화", value=enh_info, inline=False)

        view = ItemManagementView(self.bot, user_id, guild_id, item_row, template)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def equip_item(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id
        async with self.bot.pool.acquire() as conn, conn.transaction():
            item_row = await conn.fetchrow("SELECT * FROM user_items WHERE item_id = $1 AND user_id = $2 FOR UPDATE",
                                           item_id, user_id)
            if not item_row: return await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)
            if item_row['is_equipped']: return await interaction.followup.send("❌ 이미 장착된 아이템입니다.", ephemeral=True)

            template = self.get_item_template(item_row['template_id'])
            character = await self.get_user_character(user_id, guild_id)
            if template.get('class_req') and template['class_req'] != character['character_class']:
                return await interaction.followup.send(f"❌ 이 아이템은 {template['class_req']} 전용입니다.", ephemeral=True)

            # Unequip existing item in the same slot
            await conn.execute(
                "UPDATE user_items SET is_equipped = FALSE WHERE item_id = (SELECT item_id FROM user_equipment WHERE user_id=$1 AND guild_id=$2 AND slot_name=$3)",
                user_id, guild_id, template['slot_type'])

            # Equip new item
            await conn.execute("UPDATE user_items SET is_equipped = TRUE, equipped_slot = $1 WHERE item_id = $2",
                               template['slot_type'], item_id)
            await conn.execute("""
                INSERT INTO user_equipment (user_id, guild_id, slot_name, item_id) VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, guild_id, slot_name) DO UPDATE SET item_id = EXCLUDED.item_id
            """, user_id, guild_id, template['slot_type'], item_id)
        await interaction.followup.send(f"✅ {template['name']} 아이템을 장착했습니다.", ephemeral=True)

    async def unequip_item(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id
        async with self.bot.pool.acquire() as conn, conn.transaction():
            item_row = await conn.fetchrow("SELECT * FROM user_items WHERE item_id = $1 AND user_id = $2 FOR UPDATE",
                                           item_id, user_id)
            if not item_row or not item_row['is_equipped']:
                return await interaction.followup.send("❌ 장착된 아이템이 아닙니다.", ephemeral=True)

            await conn.execute("UPDATE user_items SET is_equipped = FALSE, equipped_slot = NULL WHERE item_id = $1",
                               item_id)
            await conn.execute("DELETE FROM user_equipment WHERE item_id = $1", item_id)

        template = self.get_item_template(item_row['template_id'])
        await interaction.followup.send(f"✅ {template['name']} 아이템을 장착 해제했습니다.", ephemeral=True)

    async def show_market_sell_confirmation(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        user_id, guild_id = interaction.user.id, interaction.guild.id
        item_row = await self.bot.pool.fetchrow("SELECT * FROM user_items WHERE item_id = $1 AND user_id = $2", item_id,
                                                user_id)
        if not item_row: return await interaction.followup.send("❌ 아이템을 찾을 수 없습니다.", ephemeral=True)

        template = self.get_item_template(item_row['template_id'])
        calculated_price = self.calculate_market_price(template, item_row['enhancement_level'])
        cost_breakdown = self.get_enhancement_cost_breakdown(template, item_row['enhancement_level'])

        embed = discord.Embed(title="🏪 마켓 판매 확인", color=self.item_rarities[template['rarity']]['color'])
        enh_text = f"+{item_row['enhancement_level']}" if item_row['enhancement_level'] > 0 else ""
        embed.add_field(name="판매 아이템", value=f"{template['emoji']} **{template['name']}** {enh_text}", inline=False)
        embed.add_field(name="💰 자동 계산 가격", value=f"{calculated_price:,} 코인", inline=True)

        seller_receives = int(calculated_price * 0.95)  # 5% fee
        embed.add_field(name="💳 실수령액 (수수료 5%)", value=f"{seller_receives:,} 코인", inline=True)

        profit = seller_receives - cost_breakdown['total_enhancement_cost'] - template['base_price']
        profit_text = f"이익: {profit:,}" if profit >= 0 else f"손해: {abs(profit):,}"
        embed.add_field(name="💸 예상 손익", value=profit_text, inline=True)

        view = MarketSellConfirmView(self.bot, user_id, item_id, calculated_price)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(EnhancementCog(bot))