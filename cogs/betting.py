# cogs/betting.py
from typing import Optional, Dict, List
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import traceback
from datetime import datetime, timezone, timedelta
import json
import os
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import io
import numpy as np
from matplotlib import rcParams

from utils.logger import get_logger
from utils import config

# Set matplotlib to use a font that supports Korean
rcParams['font.family'] = ['DejaVu Sans', 'Arial Unicode MS', 'Malgun Gothic', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# Constants
BETTING_CONTROL_CHANNEL_ID = 1419346557232484352
BETTING_CATEGORY_ID = 1417712502220783716


class BettingControlView(discord.ui.View):
    """Control panel for creating new betting events"""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = get_logger("베팅 시스템")

    @discord.ui.button(
        label="새 베팅 생성",
        style=discord.ButtonStyle.green,
        custom_id="create_betting_event",
        emoji="🎲"
    )
    async def create_betting_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Button to create new betting event"""
        betting_cog = self.bot.get_cog('BettingCog')
        if not betting_cog:
            await interaction.response.send_message("베팅 시스템을 찾을 수 없습니다.", ephemeral=True)
            return

        # Check admin permissions
        if not betting_cog.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 기능을 사용할 권한이 없습니다.", ephemeral=True)
            return

        modal = BettingCreationModal(betting_cog)
        await interaction.response.send_modal(modal)


class BettingCreationModal(discord.ui.Modal):
    """Modal for creating betting events with all options"""

    def __init__(self, betting_cog):
        super().__init__(title="베팅 이벤트 생성")
        self.betting_cog = betting_cog

        self.title_input = discord.ui.TextInput(
            label="베팅 제목",
            placeholder="베팅 이벤트의 제목을 입력하세요",
            required=True,
            max_length=100
        )
        self.add_item(self.title_input)

        self.description_input = discord.ui.TextInput(
            label="설명 (선택사항)",
            placeholder="베팅 이벤트에 대한 추가 설명",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500
        )
        self.add_item(self.description_input)

        self.options_input = discord.ui.TextInput(
            label="선택지 (줄바꿈으로 구분)",
            placeholder="예시:\n승리\n패배\n무승부",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.options_input)

        self.end_time_input = discord.ui.TextInput(
            label="종료 시간 (분)",
            placeholder="베팅이 자동 종료될 시간을 분 단위로 입력 (예: 30)",
            required=True,
            max_length=10
        )
        self.add_item(self.end_time_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse duration
            try:
                duration_minutes = int(self.end_time_input.value)
                if duration_minutes < 1 or duration_minutes > 10080:  # Max 1 week
                    await interaction.response.send_message(
                        "지속 시간은 1분에서 10080분(1주) 사이여야 합니다.", ephemeral=True
                    )
                    return
            except ValueError:
                await interaction.response.send_message("올바른 숫자를 입력해주세요.", ephemeral=True)
                return

            # Parse options
            options_text = self.options_input.value.strip()
            if not options_text:
                await interaction.response.send_message("최소한 하나의 선택지를 입력해야 합니다.", ephemeral=True)
                return

            options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
            if len(options) < 2:
                await interaction.response.send_message("최소 2개의 선택지가 필요합니다.", ephemeral=True)
                return
            if len(options) > 8:
                await interaction.response.send_message("최대 8개의 선택지까지 가능합니다.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            # Create the betting event
            result = await self.betting_cog.create_betting_event_with_channel(
                guild_id=interaction.guild.id,
                title=self.title_input.value,
                description=self.description_input.value or None,
                options=[{'name': opt, 'description': None} for opt in options],
                creator_id=interaction.user.id,
                duration_minutes=duration_minutes
            )

            if result['success']:
                await interaction.followup.send(
                    f"✅ 베팅 이벤트 '{self.title_input.value}'가 생성되었습니다!\n"
                    f"채널: <#{result['channel_id']}>\n"
                    f"종료 시간: <t:{int(result['end_time'].timestamp())}:R>",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ 베팅 생성 실패: {result['reason']}", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 오류가 발생했습니다: {e}", ephemeral=True)
            self.betting_cog.logger.error(f"베팅 생성 모달 오류: {e}", extra={'guild_id': interaction.guild.id})


# Improved BettingView with better error handling and registration
class BettingView(discord.ui.View):
    def __init__(self, bot, event_data: dict):
        super().__init__(timeout=None)  # Never timeout
        self.bot = bot
        self.event_data = event_data
        self.logger = get_logger("베팅 시스템")

        # Store event_id for easier access
        self.event_id = event_data['event_id']

        # Dynamically create buttons based on number of options
        self.create_betting_buttons()

        # Add the status button
        self.add_status_button()

    def create_betting_buttons(self):
        """Create betting buttons dynamically based on number of options"""
        colors = [
            discord.ButtonStyle.primary,
            discord.ButtonStyle.secondary,
            discord.ButtonStyle.success,
            discord.ButtonStyle.danger
        ]

        for i, option in enumerate(self.event_data['options']):
            if i >= 7:  # Leave room for status button (max 5 action rows, each with max 5 components)
                break

            button = discord.ui.Button(
                label=f"{option['name']} (0명)",
                style=colors[i % len(colors)],
                custom_id=f"bet_{self.event_id}_{i}",  # Simplified but unique custom_id
                emoji="💰"
            )

            # Create a proper callback using closure
            async def make_bet_callback(option_index):
                async def bet_callback(interaction):
                    try:
                        await self.handle_bet(interaction, option_index)
                    except Exception as e:
                        self.logger.error(f"Button callback error for option {option_index}: {e}")
                        if not interaction.response.is_done():
                            await interaction.response.send_message("오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)

                return bet_callback

            button.callback = make_bet_callback(i)
            self.add_item(button)

    def add_status_button(self):
        """Add the betting status button"""
        status_button = discord.ui.Button(
            label="내 베팅 현황",
            style=discord.ButtonStyle.secondary,
            custom_id=f"status_{self.event_id}",
            emoji="📊"
        )

        async def status_callback(interaction):
            try:
                await self.show_betting_status(interaction)
            except Exception as e:
                self.logger.error(f"Status button callback error: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message("오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)

        status_button.callback = status_callback
        self.add_item(status_button)

    async def handle_bet(self, interaction: discord.Interaction, option_index: int):
        """Handle betting on an option"""
        try:
            guild_id = interaction.guild.id
            user_id = interaction.user.id

            self.logger.info(f"Processing bet from user {user_id} for option {option_index} on event {self.event_id}")

            # Check if the option index is valid for this event
            if option_index >= len(self.event_data['options']):
                await interaction.response.send_message("⛔ 유효하지 않은 베팅 옵션입니다.", ephemeral=True)
                return

            # Check if casino games are enabled
            if not config.is_feature_enabled(guild_id, 'casino_games'):
                await interaction.response.send_message(
                    "⛔ 이 서버에서는 베팅 시스템이 비활성화되어 있습니다.",
                    ephemeral=True
                )
                return

            # Get betting cog
            betting_cog = self.bot.get_cog('BettingCog')
            if not betting_cog:
                await interaction.response.send_message("⛔ 베팅 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            # Check if event is still active (refresh from database)
            event = await betting_cog.get_event(self.event_id, guild_id)
            if not event or event['status'] != 'active':
                await interaction.response.send_message("⛔ 이 베팅은 더 이상 활성화되어 있지 않습니다.", ephemeral=True)
                return

            # Show betting modal
            modal = BettingModal(betting_cog, event, option_index)
            await interaction.response.send_modal(modal)

        except Exception as e:
            self.logger.error(f"Error in handle_bet: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.send_message("베팅 처리 중 오류가 발생했습니다.", ephemeral=True)

    async def show_betting_status(self, interaction: discord.Interaction):
        """Show user's current bets on this event"""
        try:
            guild_id = interaction.guild.id
            user_id = interaction.user.id

            betting_cog = self.bot.get_cog('BettingCog')
            if not betting_cog:
                await interaction.response.send_message("⛔ 베팅 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            user_bets = await betting_cog.get_user_bets(user_id, self.event_id, guild_id)

            if not user_bets:
                await interaction.response.send_message("📊 이 이벤트에 베팅하지 않았습니다.", ephemeral=True)
                return

            embed = discord.Embed(
                title="📊 내 베팅 현황",
                description=f"**이벤트:** {self.event_data['title']}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            total_bet = 0
            for bet in user_bets:
                option_name = self.event_data['options'][bet['option_index']]['name']
                embed.add_field(
                    name=f"🎯 {option_name}",
                    value=f"{bet['amount']:,} 코인",
                    inline=True
                )
                total_bet += bet['amount']

            embed.add_field(name="💰 총 베팅액", value=f"{total_bet:,} 코인", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in show_betting_status: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("상태 조회 중 오류가 발생했습니다.", ephemeral=True)

    def update_button_labels(self, stats: dict):
        """Update button labels with current betting stats"""
        try:
            for child in self.children:
                if hasattr(child, 'custom_id') and child.custom_id.startswith(f'bet_{self.event_id}_'):
                    # Extract option index from custom_id
                    try:
                        option_index = int(child.custom_id.split('_')[-1])
                        if option_index < len(self.event_data['options']):
                            option_stats = stats['option_stats'].get(option_index, {'bettors': 0})
                            option_name = self.event_data['options'][option_index]['name']
                            child.label = f"{option_name} ({option_stats['bettors']}명)"
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            self.logger.error(f"Error updating button labels: {e}")

class BettingModal(discord.ui.Modal):
    """Modal for entering bet amount"""

    def __init__(self, betting_cog, event: dict, option_index: int):
        super().__init__(title="베팅하기")
        self.betting_cog = betting_cog
        self.event = event
        self.option_index = option_index

        option_name = event['options'][option_index]['name']

        self.bet_amount = discord.ui.TextInput(
            label=f"'{option_name}'에 베팅할 코인 수량",
            placeholder="베팅할 코인 수량을 입력하세요 (최소 10 코인)",
            required=True,
            max_length=10
        )
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bet_amount.value.replace(',', ''))
        except ValueError:
            await interaction.response.send_message("⛔ 올바른 숫자를 입력해주세요.", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("⛔ 최소 베팅 금액은 10 코인입니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Process the bet
        result = await self.betting_cog.place_bet(
            interaction.user.id,
            interaction.guild.id,
            self.event['event_id'],
            self.option_index,
            amount
        )

        if result['success']:
            option_name = self.event['options'][self.option_index]['name']
            embed = discord.Embed(
                title="✅ 베팅 성공!",
                description=f"**{option_name}**에 {amount:,} 코인을 베팅했습니다.",
                color=discord.Color.green()
            )
            embed.add_field(name="현재 잔액", value=f"{result['remaining_coins']:,} 코인", inline=True)

            if result.get('potential_payout'):
                embed.add_field(name="예상 수익", value=f"{result['potential_payout']:,} 코인", inline=True)

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Update the betting display and graph
            await self.betting_cog.update_betting_display(self.event['event_id'], interaction.guild.id)
        else:
            await interaction.followup.send(f"⛔ 베팅 실패: {result['reason']}", ephemeral=True)


# Improved AdminBettingView
class AdminBettingView(discord.ui.View):
    def __init__(self, bot, event_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.event_id = event_id
        self.logger = get_logger("베팅 시스템")

        close_button = discord.ui.Button(
            label="베팅 즉시 종료",
            style=discord.ButtonStyle.danger,
            custom_id=f"admin_close_{event_id}",
            emoji="⏹️"
        )

        async def close_callback(interaction):
            try:
                await self.close_betting(interaction)
            except Exception as e:
                self.logger.error(f"Admin close callback error: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message("오류가 발생했습니다.", ephemeral=True)

        close_button.callback = close_callback
        self.add_item(close_button)

    async def close_betting(self, interaction: discord.Interaction):
        """Close betting immediately"""
        try:
            betting_cog = self.bot.get_cog('BettingCog')
            if not betting_cog:
                await interaction.response.send_message("베팅 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            if not betting_cog.has_admin_permissions(interaction.user):
                await interaction.response.send_message("이 기능을 사용할 권한이 없습니다.", ephemeral=True)
                return

            await self.show_winner_selection(interaction)
        except Exception as e:
            self.logger.error(f"Error in close_betting: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("베팅 종료 처리 중 오류가 발생했습니다.", ephemeral=True)

    async def show_winner_selection(self, interaction: discord.Interaction):
        """Show dropdown to select winning option"""
        betting_cog = self.bot.get_cog('BettingCog')
        event_data = await betting_cog.get_event(self.event_id, interaction.guild.id)

        if not event_data or event_data['status'] not in ['active', 'expired']:
            await interaction.response.send_message("이미 종료된 베팅입니다.", ephemeral=True)
            return

        # Create dropdown with options
        options = []
        for i, option in enumerate(event_data['options']):
            options.append(discord.SelectOption(
                label=option['name'],
                value=str(i),
                description=f"선택지 {i + 1}"
            ))

        class WinnerSelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="승리한 선택지를 선택하세요...", options=options)

            async def callback(self, select_interaction):
                winning_index = int(self.values[0])
                await betting_cog.end_betting_event_internal(
                    select_interaction, self.event_id, winning_index
                )

        class WinnerView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
                self.add_item(WinnerSelect())

        embed = discord.Embed(
            title="🏆 승리 선택지 선택",
            description="베팅을 종료하고 승리한 선택지를 선택해주세요:",
            color=discord.Color.orange()
        )

        await interaction.response.send_message(embed=embed, view=WinnerView(), ephemeral=True)

class BettingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("베팅 시스템")

        # Store active betting events per guild
        self.active_events = {}
        self.betting_displays = {}

        self.logger.info("베팅 시스템이 초기화되었습니다.")
        self.bot.loop.create_task(self.wait_and_start_tasks())

    async def wait_and_start_tasks(self):
        """Wait for bot to be ready then start tasks"""
        await self.bot.wait_until_ready()
        await self.setup_database()
        await self.load_active_events()

        # FIXED: Reload persistent views after bot restart
        await self.reload_persistent_views()

        await self.setup_control_panel()
        self.cleanup_expired_events.start()
        self.update_graphs.start()

    async def setup_database(self):
        """Create necessary database tables"""
        try:
            # Betting events table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS betting_events (
                    event_id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    options JSONB NOT NULL,
                    creator_id BIGINT NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP WITH TIME ZONE,
                    resolved_at TIMESTAMP WITH TIME ZONE,
                    winning_option INTEGER,
                    message_id BIGINT,
                    channel_id BIGINT,
                    betting_channel_id BIGINT
                )
            """)

            # User bets table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_bets (
                    bet_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    event_id INTEGER REFERENCES betting_events(event_id) ON DELETE CASCADE,
                    option_index INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    potential_payout INTEGER,
                    placed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    resolved BOOLEAN DEFAULT FALSE,
                    payout_amount INTEGER DEFAULT 0
                )
            """)

            # Create indexes
            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_betting_events_guild_status 
                ON betting_events(guild_id, status);
            """)

            await self.bot.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_bets_user_event 
                ON user_bets(user_id, event_id);
            """)

            self.logger.info("✅ 베팅 데이터베이스 테이블이 준비되었습니다.")
        except Exception as e:
            self.logger.error(f"⛔ 데이터베이스 설정 실패: {e}")

    async def setup_control_panel(self):
        """Setup the persistent control panel in the designated channel"""
        try:
            channel = self.bot.get_channel(BETTING_CONTROL_CHANNEL_ID)
            if not channel:
                self.logger.warning(f"베팅 제어 채널 {BETTING_CONTROL_CHANNEL_ID}를 찾을 수 없습니다.")
                return

            # Check for existing control panel message
            control_message = None
            async for message in channel.history(limit=50):
                if (message.author == self.bot.user and
                        message.embeds and
                        message.embeds[0].title and
                        "베팅 제어 패널" in message.embeds[0].title):
                    control_message = message
                    break

            embed = self.create_control_panel_embed()
            view = BettingControlView(self.bot)

            if control_message:
                try:
                    await control_message.edit(embed=embed, view=view)
                    # FIXED: Add the view with the specific message ID
                    self.bot.add_view(view, message_id=control_message.id)
                    self.logger.info("기존 베팅 제어 패널을 업데이트했습니다.")
                except discord.NotFound:
                    # Message was deleted, create new one
                    control_message = await channel.send(embed=embed, view=view)
                    self.bot.add_view(view, message_id=control_message.id)
                    self.logger.info("새로운 베팅 제어 패널을 생성했습니다.")
            else:
                control_message = await channel.send(embed=embed, view=view)
                self.bot.add_view(view, message_id=control_message.id)
                self.logger.info("새로운 베팅 제어 패널을 생성했습니다.")

        except Exception as e:
            self.logger.error(f"베팅 제어 패널 설정 실패: {e}")

    def create_control_panel_embed(self):
        """Create embed for the control panel"""
        embed = discord.Embed(
            title="🎲 베팅 제어 패널",
            description="관리자용 베팅 이벤트 생성 패널입니다.\n아래 버튼을 클릭하여 새로운 베팅을 시작하세요.",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="🔧 사용 방법",
            value="• **새 베팅 생성** 버튼을 클릭\n"
                  "• 베팅 정보를 입력\n"
                  "• 자동으로 전용 채널이 생성됩니다\n"
                  "• 생성된 채널에서 베팅 진행",
            inline=False
        )

        embed.add_field(
            name="📋 기능",
            value="• 실시간 베팅 그래프\n"
                  "• 자동 시간 종료\n"
                  "• 관리자 수동 종료\n"
                  "• 자동 배당금 지급",
            inline=True
        )

        embed.set_footer(text="관리자 권한이 필요합니다")
        return embed

    async def load_active_events(self):
        """Load active betting events from database"""
        try:
            query = """
                SELECT event_id, guild_id, title, description, options, creator_id, 
                       status, created_at, ends_at, message_id, channel_id, betting_channel_id
                FROM betting_events 
                WHERE status = 'active'
            """
            events = await self.bot.pool.fetch(query)

            for event in events:
                guild_id = event['guild_id']
                event_id = event['event_id']

                if guild_id not in self.active_events:
                    self.active_events[guild_id] = {}

                self.active_events[guild_id][event_id] = {
                    'event_id': event_id,
                    'title': event['title'],
                    'description': event['description'],
                    'options': event['options'],
                    'creator_id': event['creator_id'],
                    'status': event['status'],
                    'created_at': event['created_at'],
                    'ends_at': event['ends_at'],
                    'message_id': event['message_id'],
                    'channel_id': event['channel_id'],
                    'betting_channel_id': event['betting_channel_id']
                }

                # Set up betting display tracking
                if guild_id not in self.betting_displays:
                    self.betting_displays[guild_id] = {}
                if event['message_id']:
                    self.betting_displays[guild_id][event_id] = event['message_id']

            self.logger.info(f"활성 베팅 이벤트 {len([e for g in self.active_events.values() for e in g.values()])}개를 로드했습니다.")
        except Exception as e:
            self.logger.error(f"활성 이벤트 로드 실패: {e}")

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

    async def create_betting_event_with_channel(self, guild_id: int, title: str, description: Optional[str],
                                                options: List[dict], creator_id: int, duration_minutes: int) -> dict:
        """Create a betting event with its own channel"""
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {'success': False, 'reason': '서버를 찾을 수 없습니다.'}

            # Get category and reference channel
            category = guild.get_channel(BETTING_CATEGORY_ID)
            reference_channel = guild.get_channel(BETTING_CONTROL_CHANNEL_ID)

            if not category:
                return {'success': False, 'reason': '베팅 카테고리를 찾을 수 없습니다.'}

            # Calculate end time
            current_time_utc = datetime.now(timezone.utc)
            duration_delta = timedelta(minutes=duration_minutes)
            end_time = current_time_utc + duration_delta

            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)

            # Create dedicated betting channel
            channel_name = f"╠ 📋┆베팅-{title.replace(' ', '-')[:20]}"

            betting_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=f"베팅: {title} | 종료: {end_time.strftime('%Y-%m-%d %H:%M UTC')}",
                reason=f"베팅 이벤트 채널 생성: {title}"
            )

            # Position the channel
            if reference_channel and reference_channel.category_id == category.id:
                try:
                    await betting_channel.edit(position=reference_channel.position + 1)
                except discord.HTTPException:
                    self.logger.warning("채널 위치 조정 실패, 기본 위치 사용")

            # Set permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    send_messages=False,
                    add_reactions=False,
                    create_public_threads=False,
                    create_private_threads=False
                ),
                guild.me: discord.PermissionOverwrite(
                    send_messages=True,
                    manage_messages=True,
                    embed_links=True,
                    attach_files=True
                )
            }

            # Add admin permissions
            admin_role_id = config.get_role_id(guild_id, 'admin_role')
            if admin_role_id:
                admin_role = guild.get_role(admin_role_id)
                if admin_role:
                    overwrites[admin_role] = discord.PermissionOverwrite(send_messages=True)

            staff_role_id = config.get_role_id(guild_id, 'staff_role')
            if staff_role_id:
                staff_role = guild.get_role(staff_role_id)
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(send_messages=True)

            await betting_channel.edit(overwrites=overwrites)

            # Create event in database
            try:
                event_id = await self.bot.pool.fetchval("""
                    INSERT INTO betting_events (guild_id, title, description, options, creator_id, ends_at, 
                                                channel_id, betting_channel_id)
                    VALUES ($1, $2, $3, $4, $5, $6::timestamptz, $7, $8)
                    RETURNING event_id
                """, guild_id, title, description, json.dumps(options), creator_id, end_time,
                                                        BETTING_CONTROL_CHANNEL_ID, betting_channel.id)
            except Exception as db_error:
                self.logger.error(f"Database insert failed: {db_error}")
                try:
                    await betting_channel.delete()
                except:
                    pass
                return {'success': False, 'reason': f'데이터베이스 오류: {db_error}'}

            # Create event data
            event_data = {
                'event_id': event_id,
                'title': title,
                'description': description,
                'options': options,
                'creator_id': creator_id,
                'status': 'active',
                'ends_at': end_time,
                'channel_id': BETTING_CONTROL_CHANNEL_ID,
                'betting_channel_id': betting_channel.id
            }

            # Store in active events
            if guild_id not in self.active_events:
                self.active_events[guild_id] = {}
            self.active_events[guild_id][event_id] = event_data

            # Create initial betting display
            await self.create_initial_betting_display(event_data, betting_channel)

            # Small delay to ensure everything is properly set up
            await asyncio.sleep(0.5)

            self.logger.info(f"베팅 이벤트 '{title}' 및 채널 생성됨 (ID: {event_id})", extra={'guild_id': guild_id})

            return {
                'success': True,
                'event_id': event_id,
                'channel_id': betting_channel.id,
                'end_time': end_time
            }

        except Exception as e:
            self.logger.error(f"베팅 이벤트 및 채널 생성 실패: {e}", extra={'guild_id': guild_id})
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {'success': False, 'reason': str(e)}

    async def create_initial_betting_display(self, event_data: dict, channel: discord.TextChannel):
        """Create the initial betting display in the dedicated channel"""
        try:
            self.logger.info(
                f"Creating initial betting display for event {event_data['event_id']} in channel {channel.id}")

            # Ensure event_data has all required fields for BettingView
            complete_event_data = {
                'event_id': event_data['event_id'],
                'title': event_data['title'],
                'description': event_data.get('description'),
                'options': event_data['options'],
                'creator_id': event_data['creator_id'],
                'status': event_data['status'],
                'ends_at': event_data['ends_at'],
                'betting_channel_id': channel.id,
                'message_id': None
            }

            # Create betting embed
            embed = await self.create_betting_embed(complete_event_data, channel.guild.id)

            # Create persistent views with proper callbacks
            view = BettingView(self.bot, complete_event_data)
            admin_view = AdminBettingView(self.bot, event_data['event_id'])

            # Send betting message first
            betting_message = await channel.send(embed=embed, view=view)
            self.logger.info(f"Created betting message {betting_message.id} for event {event_data['event_id']}")

            # Send admin message
            admin_embed = discord.Embed(
                title="🔧 관리자 제어",
                description="베팅을 수동으로 종료하려면 아래 버튼을 사용하세요.",
                color=discord.Color.orange()
            )
            admin_message = await channel.send(embed=admin_embed, view=admin_view)
            self.logger.info(f"Created admin message {admin_message.id} for event {event_data['event_id']}")

            # CRITICAL: Add views to bot with explicit message IDs
            try:
                self.bot.add_view(view, message_id=betting_message.id)
                self.logger.info(f"Registered betting view for message {betting_message.id}")

                self.bot.add_view(admin_view, message_id=admin_message.id)
                self.logger.info(f"Registered admin view for message {admin_message.id}")
            except Exception as view_error:
                self.logger.error(f"Failed to register views: {view_error}")
                raise

            # Update database with message ID
            await self.bot.pool.execute("""
                UPDATE betting_events SET message_id = $1 WHERE event_id = $2
            """, betting_message.id, event_data['event_id'])

            # Update tracking dictionaries
            guild_id = channel.guild.id
            if guild_id not in self.betting_displays:
                self.betting_displays[guild_id] = {}
            self.betting_displays[guild_id][event_data['event_id']] = betting_message.id

            # Update event_data for consistency
            event_data['message_id'] = betting_message.id
            complete_event_data['message_id'] = betting_message.id

            # Create initial graph
            await self.create_and_send_graph(event_data['event_id'], channel)

            self.logger.info(f"Successfully created initial betting display for event {event_data['event_id']}")

        except Exception as e:
            self.logger.error(f"초기 베팅 디스플레이 생성 실패: {e}", extra={'guild_id': channel.guild.id})
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise  # Re-raise so the calling function knows it failed

    async def reload_persistent_views(self):
        """Reload persistent views for active betting events"""
        try:
            self.logger.info("Starting to reload persistent views...")

            # Clear existing views for betting events to avoid duplicates
            views_to_remove = []
            for view in self.bot.persistent_views:
                if hasattr(view, 'event_id') or 'bet_' in str(getattr(view, 'custom_id', '')):
                    views_to_remove.append(view)

            for view in views_to_remove:
                try:
                    self.bot.persistent_views.remove(view)
                except ValueError:
                    pass  # View was already removed

            self.logger.info(f"Removed {len(views_to_remove)} old betting views")

            # Get all active betting events with valid channels and messages
            active_events = await self.bot.pool.fetch("""
                SELECT event_id, guild_id, title, options, message_id, betting_channel_id
                FROM betting_events 
                WHERE status IN ('active', 'expired') 
                AND message_id IS NOT NULL 
                AND betting_channel_id IS NOT NULL
            """)

            views_reloaded = 0
            admin_views_reloaded = 0

            for event_row in active_events:
                event_id = event_row['event_id']
                guild_id = event_row['guild_id']
                message_id = event_row['message_id']
                channel_id = event_row['betting_channel_id']

                # Check if channel exists
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    self.logger.warning(f"Channel {channel_id} not found for event {event_id}, skipping")
                    continue

                try:
                    # Try to fetch the main betting message
                    betting_message = await channel.fetch_message(message_id)

                    # Create complete event data structure
                    event_data = {
                        'event_id': event_id,
                        'title': event_row['title'],
                        'options': event_row['options'],
                        'message_id': message_id,
                        'betting_channel_id': channel_id,
                        'guild_id': guild_id
                    }

                    # Create and register betting view
                    betting_view = BettingView(self.bot, event_data)
                    self.bot.add_view(betting_view, message_id=message_id)
                    views_reloaded += 1

                    self.logger.info(f"Registered betting view for event {event_id}, message {message_id}")

                    # Update tracking
                    if guild_id not in self.betting_displays:
                        self.betting_displays[guild_id] = {}
                    self.betting_displays[guild_id][event_id] = message_id

                    # Search for admin control message
                    try:
                        admin_message = None
                        async for msg in channel.history(after=betting_message, limit=5):
                            if (msg.author == self.bot.user and msg.embeds and
                                    msg.embeds[0].title and "관리자 제어" in msg.embeds[0].title):
                                admin_message = msg
                                break

                        if admin_message:
                            admin_view = AdminBettingView(self.bot, event_id)
                            self.bot.add_view(admin_view, message_id=admin_message.id)
                            admin_views_reloaded += 1
                            self.logger.info(f"Registered admin view for event {event_id}, message {admin_message.id}")

                    except Exception as admin_error:
                        self.logger.debug(f"Could not reload admin view for event {event_id}: {admin_error}")

                except discord.NotFound:
                    # Message was deleted, clean up database
                    await self.bot.pool.execute("""
                        UPDATE betting_events 
                        SET message_id = NULL 
                        WHERE event_id = $1
                    """, event_id)
                    self.logger.info(f"Message {message_id} not found for event {event_id}, cleaned up database")

                except discord.Forbidden:
                    self.logger.warning(f"No permission to access message {message_id} for event {event_id}")

                except Exception as e:
                    self.logger.warning(f"Failed to reload view for event {event_id}: {e}")

            self.logger.info(
                f"Successfully reloaded {views_reloaded} betting views and {admin_views_reloaded} admin views")

            # Log current persistent views count for verification
            betting_views = sum(1 for view in self.bot.persistent_views if hasattr(view, 'event_id'))
            self.logger.info(f"Total betting persistent views after reload: {betting_views}")

        except Exception as e:
            self.logger.error(f"Failed to reload persistent views: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    async def create_and_send_graph(self, event_id: int, channel: discord.TextChannel):
        """Create and send betting statistics graph"""
        try:
            guild_id = channel.guild.id
            event_data = await self.get_event(event_id, guild_id)
            if not event_data:
                return

            stats = await self.get_betting_stats(event_id, guild_id)

            # Create matplotlib figure
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
            fig.patch.set_facecolor('#2f3136')

            # Pie chart for betting distribution
            if not isinstance(event_data['options'], list) or not isinstance(stats['option_stats'], dict):
                raise TypeError("베팅 데이터 형식이 올바르지 않습니다.")

            option_names = [opt['name'] for opt in event_data['options']]
            amounts = []
            colors = ['#7289da', '#43b581', '#faa61a', '#f04747', '#9b59b6', '#e67e22', '#11806a', '#992d22']

            for i, option in enumerate(event_data['options']):
                option_stats = stats['option_stats'].get(i, {'amount': 0, 'bettors': 0})
                amounts.append(option_stats['amount'] if option_stats['amount'] > 0 else 0.1)

            if sum(amounts) > 0:
                wedges, texts, autotexts = ax1.pie(amounts, labels=option_names, autopct='%1.1f%%',
                                                   colors=colors[:len(option_names)], startangle=90)
                for text in texts:
                    text.set_color('white')
                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_fontweight('bold')
            else:
                ax1.text(0.5, 0.5, '베팅 없음', ha='center', va='center', color='white', fontsize=16)

            ax1.set_title('베팅 분포', color='white', fontsize=14, fontweight='bold')
            ax1.set_facecolor('#2f3136')

            # Bar chart for participant count
            participant_counts = []
            for i, option in enumerate(event_data['options']):
                option_stats = stats['option_stats'].get(i, {'amount': 0, 'bettors': 0})
                participant_counts.append(option_stats['bettors'])

            bars = ax2.bar(range(len(option_names)), participant_counts,
                           color=colors[:len(option_names)], alpha=0.8)
            ax2.set_xlabel('선택지', color='white')
            ax2.set_ylabel('참여자 수', color='white')
            ax2.set_title('참여자 현황', color='white', fontsize=14, fontweight='bold')
            ax2.set_xticks(range(len(option_names)))
            ax2.set_xticklabels([name[:10] + '...' if len(name) > 10 else name for name in option_names],
                                rotation=45, ha='right', color='white')
            ax2.tick_params(colors='white')
            ax2.set_facecolor('#2f3136')

            # Add value labels on bars
            for bar, count in zip(bars, participant_counts):
                if count > 0:
                    ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1, str(count),
                             ha='center', va='bottom', color='white', fontweight='bold')

            plt.tight_layout()

            # Save to bytes
            buf = io.BytesIO()
            plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=150, bbox_inches='tight')
            buf.seek(0)
            plt.close()

            # Create embed for graph
            graph_embed = discord.Embed(
                title="📊 실시간 베팅 통계",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            graph_embed.add_field(
                name="💰 총 베팅액",
                value=f"{stats['total_amount']:,} 코인",
                inline=True
            )
            graph_embed.add_field(
                name="👥 총 참여자",
                value=f"{stats['unique_bettors']}명",
                inline=True
            )
            graph_embed.add_field(
                name="📈 총 베팅 수",
                value=f"{stats['total_bets']}건",
                inline=True
            )

            # Add end time
            if event_data['ends_at']:
                graph_embed.add_field(
                    name="⏰ 종료 시간",
                    value=f"<t:{int(event_data['ends_at'].timestamp())}:R>",
                    inline=False
                )
            graph_embed.set_footer(text="그래프는 5분마다 자동 업데이트됩니다")

            # Find and update existing graph message, or create new one
            graph_message = None
            async for message in channel.history(limit=20):
                if (message.author == self.bot.user and message.embeds and "실시간 베팅 통계" in message.embeds[0].title):
                    graph_message = message
                    break

            file = discord.File(buf, filename=f'betting_stats_{event_id}.png')
            graph_embed.set_image(url=f'attachment://betting_stats_{event_id}.png')

            if graph_message:
                await graph_message.edit(embed=graph_embed, attachments=[file])
            else:
                await channel.send(embed=graph_embed, file=file)

        except Exception as e:
            self.logger.error(f"베팅 그래프 생성 실패: {e}", extra={'guild_id': channel.guild.id})

    async def get_event(self, event_id: int, guild_id: int) -> Optional[dict]:
        """Get event data"""
        try:
            query = """
                SELECT event_id, guild_id, title, description, options, creator_id, 
                       status, created_at, ends_at, message_id, channel_id, betting_channel_id
                FROM betting_events 
                WHERE event_id = $1 AND guild_id = $2
            """
            event = await self.bot.pool.fetchrow(query, event_id, guild_id)

            if event:
                return {
                    'event_id': event['event_id'],
                    'title': event['title'],
                    'description': event['description'],
                    'options': event['options'],
                    'creator_id': event['creator_id'],
                    'status': event['status'],
                    'created_at': event['created_at'],
                    'ends_at': event['ends_at'],
                    'message_id': event['message_id'],
                    'channel_id': event['channel_id'],
                    'betting_channel_id': event['betting_channel_id']
                }
            return None
        except Exception as e:
            self.logger.error(f"이벤트 조회 실패: {e}", extra={'guild_id': guild_id})
            return None

    async def get_user_bets(self, user_id: int, event_id: int, guild_id: int) -> List[dict]:
        """Get user's bets for an event"""
        try:
            query = """
                SELECT bet_id, option_index, amount, potential_payout, placed_at
                FROM user_bets 
                WHERE user_id = $1 AND event_id = $2 AND guild_id = $3
            """
            bets = await self.bot.pool.fetch(query, user_id, event_id, guild_id)
            return [dict(bet) for bet in bets]
        except Exception as e:
            self.logger.error(f"사용자 베팅 조회 실패: {e}", extra={'guild_id': guild_id})
            return []

    async def place_bet(self, user_id: int, guild_id: int, event_id: int, option_index: int, amount: int) -> dict:
        """Place a bet on an event option"""
        try:
            # Check if user has sufficient coins
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return {'success': False, 'reason': '코인 시스템을 찾을 수 없습니다.'}

            user_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if user_coins < amount:
                return {'success': False, 'reason': f'코인이 부족합니다. (보유: {user_coins:,} 코인)'}

            # Check for loan restrictions
            from cogs.coins import check_user_casino_eligibility
            eligibility = await check_user_casino_eligibility(self.bot, user_id, guild_id)
            if not eligibility['allowed']:
                return {'success': False, 'reason': eligibility['message']}

            # Remove coins from user
            removed = await coins_cog.remove_coins(user_id, guild_id, amount, "betting",
                                                   f"베팅 (이벤트 ID: {event_id})")
            if not removed:
                return {'success': False, 'reason': '코인 차감에 실패했습니다.'}

            # Calculate potential payout
            total_bets = await self.get_total_bets_for_event(event_id, guild_id)
            option_bets = await self.get_option_bets(event_id, option_index, guild_id)

            if option_bets > 0:
                potential_payout = int((total_bets + amount) / (option_bets + amount) * amount)
            else:
                potential_payout = amount * 2

            # Record the bet
            await self.bot.pool.execute("""
                INSERT INTO user_bets (user_id, guild_id, event_id, option_index, amount, potential_payout)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, user_id, guild_id, event_id, option_index, amount, potential_payout)

            remaining_coins = await coins_cog.get_user_coins(user_id, guild_id)

            self.logger.info(f"사용자 {user_id}가 이벤트 {event_id}에 {amount} 코인 베팅", extra={'guild_id': guild_id})

            return {
                'success': True,
                'remaining_coins': remaining_coins,
                'potential_payout': potential_payout
            }

        except Exception as e:
            self.logger.error(f"베팅 처리 실패: {e}", extra={'guild_id': guild_id})
            # Refund coins if they were removed but bet failed
            if 'removed' in locals() and removed:
                await coins_cog.add_coins(user_id, guild_id, amount, "betting_refund",
                                          f"베팅 실패 환불 (이벤트 ID: {event_id})")
            return {'success': False, 'reason': '베팅 처리 중 오류가 발생했습니다.'}

    async def get_total_bets_for_event(self, event_id: int, guild_id: int) -> int:
        """Get total amount bet on an event"""
        try:
            result = await self.bot.pool.fetchrow("""
                SELECT COALESCE(SUM(amount), 0) as total
                FROM user_bets 
                WHERE event_id = $1 AND guild_id = $2
            """, event_id, guild_id)
            return result['total']
        except Exception as e:
            self.logger.error(f"총 베팅액 조회 실패: {e}", extra={'guild_id': guild_id})
            return 0

    async def get_option_bets(self, event_id: int, option_index: int, guild_id: int) -> int:
        """Get total amount bet on a specific option"""
        try:
            result = await self.bot.pool.fetchrow("""
                SELECT COALESCE(SUM(amount), 0) as total
                FROM user_bets 
                WHERE event_id = $1 AND option_index = $2 AND guild_id = $3
            """, event_id, option_index, guild_id)
            return result['total']
        except Exception as e:
            self.logger.error(f"옵션별 베팅액 조회 실패: {e}", extra={'guild_id': guild_id})
            return 0

    async def get_betting_stats(self, event_id: int, guild_id: int) -> dict:
        """Get detailed betting statistics for an event"""
        try:
            total_stats = await self.bot.pool.fetchrow("""
                SELECT COALESCE(SUM(amount), 0) as total_amount,
                       COUNT(DISTINCT user_id) as unique_bettors,
                       COUNT(*) as total_bets
                FROM user_bets 
                WHERE event_id = $1 AND guild_id = $2
            """, event_id, guild_id)

            option_stats = await self.bot.pool.fetch("""
                SELECT option_index, 
                       COALESCE(SUM(amount), 0) as total_amount,
                       COUNT(DISTINCT user_id) as unique_bettors
                FROM user_bets 
                WHERE event_id = $1 AND guild_id = $2
                GROUP BY option_index
                ORDER BY option_index
            """, event_id, guild_id)

            return {
                'total_amount': total_stats['total_amount'],
                'unique_bettors': total_stats['unique_bettors'],
                'total_bets': total_stats['total_bets'],
                'option_stats': {stat['option_index']: {
                    'amount': stat['total_amount'],
                    'bettors': stat['unique_bettors']
                } for stat in option_stats}
            }
        except Exception as e:
            self.logger.error(f"베팅 통계 조회 실패: {e}", extra={'guild_id': guild_id})
            return {'total_amount': 0, 'unique_bettors': 0, 'total_bets': 0, 'option_stats': {}}

    async def create_betting_embed(self, event_data: dict, guild_id: int) -> discord.Embed:
        """Create embed for betting display"""
        stats = await self.get_betting_stats(event_data['event_id'], guild_id)

        embed = discord.Embed(
            title=f"🎲 {event_data['title']}",
            description=event_data.get('description', '베팅에 참여하세요!'),
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="📊 베팅 현황",
            value=f"총 베팅액: **{stats['total_amount']:,} 코인**\n"
                  f"참여자: **{stats['unique_bettors']}명**\n"
                  f"총 베팅 수: **{stats['total_bets']}건**",
            inline=False
        )

        # Add options with current bets
        options_text = ""
        for i, option in enumerate(event_data['options']):
            option_stats = stats['option_stats'].get(i, {'amount': 0, 'bettors': 0})
            percentage = (option_stats['amount'] / stats['total_amount'] * 100) if stats['total_amount'] > 0 else 0

            bar_length = 10
            filled = int(percentage / 10)
            bar = "█" * filled + "░" * (bar_length - filled)

            options_text += f"**{option['name']}**\n"
            options_text += f"├ 베팅액: {option_stats['amount']:,} 코인 ({percentage:.1f}%)\n"
            options_text += f"├ 참여자: {option_stats['bettors']}명\n"
            options_text += f"└ {bar} {percentage:.1f}%\n\n"

        if options_text:
            embed.add_field(name="🎯 베팅 옵션", value=options_text, inline=False)

        if event_data.get('ends_at'):
            embed.add_field(
                name="⏰ 종료 시간",
                value=f"<t:{int(event_data['ends_at'].timestamp())}:R>",
                inline=True
            )

        embed.set_footer(text="아래 버튼을 클릭하여 베팅하세요")
        return embed

    async def update_betting_display(self, event_id: int, guild_id: int):
        """Update the betting display message"""
        try:
            if guild_id not in self.betting_displays or event_id not in self.betting_displays[guild_id]:
                return

            message_id = self.betting_displays[guild_id][event_id]
            event_data = await self.get_event(event_id, guild_id)

            if not event_data:
                return

            channel_id = event_data.get('betting_channel_id')
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                return

            try:
                message = await channel.fetch_message(message_id)
                embed = await self.create_betting_embed(event_data, guild_id)

                # Update button labels with bet counts
                stats = await self.get_betting_stats(event_id, guild_id)
                view = BettingView(self.bot, event_data)

                # Update the view with current stats
                view.update_button_labels(stats)

                await message.edit(embed=embed, view=view)

                # Update graph
                await self.create_and_send_graph(event_id, channel)

            except discord.NotFound:
                # Message was deleted, clean up
                del self.betting_displays[guild_id][event_id]
                await self.bot.pool.execute("""
                    UPDATE betting_events SET message_id = NULL WHERE event_id = $1
                """, event_id)
            except discord.HTTPException as e:
                if e.status != 429:  # Don't log rate limit errors
                    self.logger.error(f"베팅 디스플레이 업데이트 실패: {e}", extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error(f"베팅 디스플레이 업데이트 실패: {e}", extra={'guild_id': guild_id})

    async def end_betting_event_internal(self, interaction: discord.Interaction, event_id: int, winning_index: int):
        """Internal method to end betting event"""
        guild_id = interaction.guild.id

        try:
            await interaction.response.defer(ephemeral=True)

            event_data = await self.get_event(event_id, guild_id)
            if not event_data:
                await interaction.followup.send("베팅 이벤트를 찾을 수 없습니다.", ephemeral=True)
                return

            if event_data['status'] not in ['active', 'expired']:
                await interaction.followup.send("이미 종료된 베팅 이벤트입니다.", ephemeral=True)
                return

            winning_option_name = event_data['options'][winning_index]['name']

            # Update event status
            await self.bot.pool.execute("""
                UPDATE betting_events 
                SET status = 'resolved', resolved_at = $1, winning_option = $2
                WHERE event_id = $3
            """, datetime.now(timezone.utc), winning_index, event_id)

            # Process payouts
            await self.process_payouts(event_id, winning_index, guild_id)

            # Clean up active events
            if guild_id in self.active_events and event_id in self.active_events[guild_id]:
                del self.active_events[guild_id][event_id]

            # Update display message
            await self.update_final_betting_display(event_id, guild_id, winning_index)

            # Send result message
            stats = await self.get_betting_stats(event_id, guild_id)
            winners_count = await self.get_winners_count(event_id, winning_index, guild_id)

            result_embed = discord.Embed(
                title="🏆 베팅 결과 발표",
                description=f"**{event_data['title']}** 베팅이 종료되었습니다!",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )

            result_embed.add_field(
                name="🎯 승리 선택지",
                value=f"**{winning_option_name}**",
                inline=False
            )

            result_embed.add_field(name="총 베팅액", value=f"{stats['total_amount']:,} 코인", inline=True)
            result_embed.add_field(name="총 참여자", value=f"{stats['unique_bettors']}명", inline=True)
            result_embed.add_field(name="승리자", value=f"{winners_count}명", inline=True)

            # Send to betting channel
            betting_channel = self.bot.get_channel(event_data.get('betting_channel_id'))
            if betting_channel:
                await betting_channel.send(embed=result_embed)

            await interaction.followup.send("✅ 베팅이 성공적으로 종료되었습니다.", ephemeral=True)
            self.logger.info(f"베팅 이벤트 {event_id} 종료됨. 승리 선택지: {winning_option_name}", extra={'guild_id': guild_id})

        except Exception as e:
            await interaction.followup.send(f"베팅 종료 실패: {e}", ephemeral=True)
            self.logger.error(f"베팅 종료 실패: {e}", extra={'guild_id': guild_id})

    async def process_payouts(self, event_id: int, winning_index: int, guild_id: int):
        """Process payouts for winning bets"""
        try:
            winning_bets = await self.bot.pool.fetch("""
                SELECT bet_id, user_id, amount, potential_payout
                FROM user_bets 
                WHERE event_id = $1 AND option_index = $2 AND guild_id = $3
            """, event_id, winning_index, guild_id)

            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                self.logger.error("코인 시스템을 찾을 수 없어 배당금 지급 실패", extra={'guild_id': guild_id})
                return

            total_payout = 0
            winners_count = 0

            for bet in winning_bets:
                payout = bet['potential_payout']

                success = await coins_cog.add_coins(
                    bet['user_id'], guild_id, payout, "betting_win",
                    f"베팅 승리 배당금 (이벤트 ID: {event_id})"
                )

                if success:
                    await self.bot.pool.execute("""
                        UPDATE user_bets 
                        SET resolved = TRUE, payout_amount = $1
                        WHERE bet_id = $2
                    """, payout, bet['bet_id'])

                    total_payout += payout
                    winners_count += 1

            # Mark losing bets as resolved
            await self.bot.pool.execute("""
                UPDATE user_bets 
                SET resolved = TRUE, payout_amount = 0
                WHERE event_id = $1 AND option_index != $2 AND guild_id = $3
            """, event_id, winning_index, guild_id)

            self.logger.info(f"베팅 배당금 지급 완료: {winners_count}명에게 총 {total_payout:,} 코인",
                             extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error(f"배당금 처리 실패: {e}", extra={'guild_id': guild_id})

    async def get_winners_count(self, event_id: int, winning_index: int, guild_id: int) -> int:
        """Get number of winners for an event"""
        try:
            result = await self.bot.pool.fetchrow("""
                SELECT COUNT(DISTINCT user_id) as winners
                FROM user_bets 
                WHERE event_id = $1 AND option_index = $2 AND guild_id = $3
            """, event_id, winning_index, guild_id)
            return result['winners']
        except Exception:
            return 0

    async def update_final_betting_display(self, event_id: int, guild_id: int, winning_index: int):
        """Update betting display with final results"""
        try:
            if guild_id not in self.betting_displays or event_id not in self.betting_displays[guild_id]:
                return

            message_id = self.betting_displays[guild_id][event_id]
            event_data = await self.get_event(event_id, guild_id)

            if not event_data:
                return

            channel = self.bot.get_channel(event_data.get('betting_channel_id'))
            if not channel:
                return

            try:
                message = await channel.fetch_message(message_id)

                embed = discord.Embed(
                    title=f"🏁 {event_data['title']} (종료됨)",
                    description=event_data.get('description', '베팅이 종료되었습니다.'),
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )

                winning_option = event_data['options'][winning_index]['name']
                embed.add_field(
                    name="🏆 승리 선택지",
                    value=f"**{winning_option}**",
                    inline=False
                )

                stats = await self.get_betting_stats(event_id, guild_id)
                embed.add_field(
                    name="📊 최종 통계",
                    value=f"총 베팅액: **{stats['total_amount']:,} 코인**\n"
                          f"참여자: **{stats['unique_bettors']}명**\n"
                          f"총 베팅 수: **{stats['total_bets']}건**",
                    inline=False
                )

                # Show final betting distribution
                options_text = ""
                for i, option in enumerate(event_data['options']):
                    option_stats = stats['option_stats'].get(i, {'amount': 0, 'bettors': 0})
                    percentage = (option_stats['amount'] / stats['total_amount'] * 100) if stats[
                                                                                               'total_amount'] > 0 else 0

                    status_icon = "🏆" if i == winning_index else "❌"
                    options_text += f"{status_icon} **{option['name']}**\n"
                    options_text += f"├ 베팅액: {option_stats['amount']:,} 코인 ({percentage:.1f}%)\n"
                    options_text += f"└ 참여자: {option_stats['bettors']}명\n\n"

                if options_text:
                    embed.add_field(name="🎯 최종 결과", value=options_text, inline=False)

                embed.set_footer(text="베팅이 종료되어 더 이상 참여할 수 없습니다.")

                await message.edit(embed=embed, view=None)

                del self.betting_displays[guild_id][event_id]

            except discord.NotFound:
                del self.betting_displays[guild_id][event_id]

        except Exception as e:
            self.logger.error(f"최종 베팅 디스플레이 업데이트 실패: {e}", extra={'guild_id': guild_id})

    @tasks.loop(minutes=5)
    async def cleanup_expired_events(self):
        """Clean up expired events"""
        try:
            current_time = datetime.now(timezone.utc)

            expired_events = await self.bot.pool.fetch("""
                SELECT event_id, guild_id, betting_channel_id
                FROM betting_events 
                WHERE status = 'active' AND ends_at < $1
            """, current_time)

            for event in expired_events:
                event_id = event['event_id']
                guild_id = event['guild_id']

                # Mark as expired
                await self.bot.pool.execute("""
                    UPDATE betting_events 
                    SET status = 'expired' 
                    WHERE event_id = $1
                """, event_id)

                # Clean up from active events
                if guild_id in self.active_events and event_id in self.active_events[guild_id]:
                    del self.active_events[guild_id][event_id]

                # Update display to show expired status
                await self.update_expired_betting_display(event_id, guild_id)

                self.logger.info(f"베팅 이벤트 {event_id}가 만료되었습니다.", extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error(f"만료된 이벤트 정리 실패: {e}")

    @tasks.loop(minutes=5)
    async def update_graphs(self):
        """Update betting graphs every 5 minutes"""
        try:
            for guild_id, events in self.active_events.items():
                for event_id, event_data in events.items():
                    if event_data['status'] == 'active':
                        betting_channel_id = event_data.get('betting_channel_id')
                        if betting_channel_id:
                            channel = self.bot.get_channel(betting_channel_id)
                            if channel:
                                await self.create_and_send_graph(event_id, channel)
        except Exception as e:
            self.logger.error(f"그래프 업데이트 실패: {e}")

    async def update_expired_betting_display(self, event_id: int, guild_id: int):
        """Update betting display when event expires"""
        try:
            if guild_id not in self.betting_displays or event_id not in self.betting_displays[guild_id]:
                return

            message_id = self.betting_displays[guild_id][event_id]
            event_data = await self.get_event(event_id, guild_id)

            if not event_data:
                return

            channel = self.bot.get_channel(event_data.get('betting_channel_id'))
            if not channel:
                return

            try:
                message = await channel.fetch_message(message_id)

                embed = discord.Embed(
                    title=f"⏰ {event_data['title']} (시간 만료)",
                    description=f"{event_data.get('description', '베팅 시간이 만료되었습니다.')}\n\n**관리자가 수동으로 결과를 발표할 때까지 기다려주세요.**",
                    color=discord.Color.orange(),
                    timestamp=datetime.now(timezone.utc)
                )

                stats = await self.get_betting_stats(event_id, guild_id)
                embed.add_field(
                    name="📊 최종 통계",
                    value=f"총 베팅액: **{stats['total_amount']:,} 코인**\n"
                          f"참여자: **{stats['unique_bettors']}명**\n"
                          f"총 베팅 수: **{stats['total_bets']}건**",
                    inline=False
                )

                # Show final betting distribution
                options_text = ""
                for i, option in enumerate(event_data['options']):
                    option_stats = stats['option_stats'].get(i, {'amount': 0, 'bettors': 0})
                    percentage = (option_stats['amount'] / stats['total_amount'] * 100) if stats[
                                                                                               'total_amount'] > 0 else 0

                    options_text += f"⏳ **{option['name']}**\n"
                    options_text += f"├ 베팅액: {option_stats['amount']:,} 코인 ({percentage:.1f}%)\n"
                    options_text += f"└ 참여자: {option_stats['bettors']}명\n\n"

                if options_text:
                    embed.add_field(name="🎯 베팅 현황", value=options_text, inline=False)

                embed.set_footer(text="시간이 만료되어 더 이상 베팅할 수 없습니다. 관리자의 결과 발표를 기다려주세요.")

                # Remove betting buttons but keep admin controls
                await message.edit(embed=embed, view=None)

            except discord.NotFound:
                del self.betting_displays[guild_id][event_id]

        except Exception as e:
            self.logger.error(f"만료된 베팅 디스플레이 업데이트 실패: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="베팅종료", description="베팅 이벤트를 수동으로 종료합니다. (관리자 전용)")
    @app_commands.describe(
        event_id="종료할 베팅 이벤트 ID",
        winning_option="승리한 선택지 번호 (1부터 시작)"
    )
    async def manual_end_betting(self, interaction: discord.Interaction, event_id: int, winning_option: int):
        guild_id = interaction.guild.id

        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "이 서버에서는 베팅 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        event_data = await self.get_event(event_id, guild_id)
        if not event_data:
            await interaction.response.send_message("해당 베팅 이벤트를 찾을 수 없습니다.", ephemeral=True)
            return

        if event_data['status'] not in ['active', 'expired']:
            await interaction.response.send_message("이미 종료된 베팅 이벤트입니다.", ephemeral=True)
            return

        if winning_option < 1 or winning_option > len(event_data['options']):
            await interaction.response.send_message(f"올바르지 않은 선택지 번호입니다. (1-{len(event_data['options'])})",
                                                    ephemeral=True)
            return

        winning_index = winning_option - 1
        await self.end_betting_event_internal(interaction, event_id, winning_index)

    @app_commands.command(name="베팅목록", description="현재 활성화된 베팅 이벤트 목록을 확인합니다.")
    async def list_betting_events(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "이 서버에서는 베팅 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            active_events = await self.bot.pool.fetch("""
                SELECT event_id, title, description, created_at, ends_at, status, betting_channel_id
                FROM betting_events 
                WHERE guild_id = $1 AND status IN ('active', 'expired')
                ORDER BY created_at DESC
            """, guild_id)

            if not active_events:
                await interaction.followup.send("현재 활성화된 베팅 이벤트가 없습니다.", ephemeral=True)
                return

            embed = discord.Embed(
                title="베팅 이벤트 목록",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            for event in active_events:
                stats = await self.get_betting_stats(event['event_id'], guild_id)

                status_emoji = "🟢" if event['status'] == 'active' else "🟡"
                status_text = "진행중" if event['status'] == 'active' else "시간만료"

                field_value = f"ID: `{event['event_id']}` | 상태: {status_emoji} {status_text}\n"
                if event['description']:
                    field_value += f"설명: {event['description'][:50]}{'...' if len(event['description']) > 50 else ''}\n"
                field_value += f"생성: <t:{int(event['created_at'].timestamp())}:R>\n"
                field_value += f"종료: <t:{int(event['ends_at'].timestamp())}:R>\n"
                field_value += f"베팅액: {stats['total_amount']:,} 코인 ({stats['unique_bettors']}명 참여)"

                if event['betting_channel_id']:
                    field_value += f"\n채널: <#{event['betting_channel_id']}>"

                embed.add_field(
                    name=f"{event['title']}",
                    value=field_value,
                    inline=False
                )

            embed.set_footer(text=f"총 {len(active_events)}개의 이벤트")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"베팅 목록 조회 실패: {e}", ephemeral=True)
            self.logger.error(f"베팅 목록 조회 실패: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="내베팅", description="내가 참여한 베팅 내역을 확인합니다.")
    async def my_bets(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = interaction.user.id

        if not config.is_feature_enabled(guild_id, 'casino_games'):
            await interaction.response.send_message(
                "이 서버에서는 베팅 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            user_bets = await self.bot.pool.fetch("""
                SELECT ub.bet_id, ub.event_id, ub.option_index, ub.amount, 
                       ub.potential_payout, ub.placed_at, ub.resolved, ub.payout_amount,
                       be.title, be.options, be.status, be.winning_option, be.betting_channel_id
                FROM user_bets ub
                JOIN betting_events be ON ub.event_id = be.event_id
                WHERE ub.user_id = $1 AND ub.guild_id = $2
                ORDER BY ub.placed_at DESC
                LIMIT 10
            """, user_id, guild_id)

            if not user_bets:
                await interaction.followup.send("베팅 내역이 없습니다.", ephemeral=True)
                return

            embed = discord.Embed(
                title="내 베팅 내역",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            total_bet = 0
            total_payout = 0
            active_bets = 0

            for bet in user_bets:
                total_bet += bet['amount']

                option_name = bet['options'][bet['option_index']]['name']

                if bet['resolved']:
                    total_payout += bet['payout_amount']
                    if bet['payout_amount'] > 0:
                        status = f"🏆 승리 (+{bet['payout_amount']:,} 코인)"
                    else:
                        status = "❌ 패배"
                else:
                    active_bets += 1
                    if bet['status'] == 'active':
                        status = f"⏳ 진행 중 (예상: +{bet['potential_payout']:,} 코인)"
                    elif bet['status'] == 'expired':
                        status = "⏰ 시간만료 (결과 대기중)"
                    else:
                        status = "⏸️ 종료됨"

                field_value = f"베팅: **{option_name}**\n"
                field_value += f"금액: {bet['amount']:,} 코인\n"
                field_value += f"상태: {status}\n"
                field_value += f"시간: <t:{int(bet['placed_at'].timestamp())}:R>"

                if bet['betting_channel_id']:
                    field_value += f"\n채널: <#{bet['betting_channel_id']}>"

                embed.add_field(
                    name=f"{bet['title']}",
                    value=field_value,
                    inline=False
                )

            # Add summary
            net_result = total_payout - total_bet
            profit_emoji = "📈" if net_result > 0 else "📉" if net_result < 0 else "➡️"

            embed.add_field(
                name="요약",
                value=f"총 베팅액: {total_bet:,} 코인\n"
                      f"총 수익: {total_payout:,} 코인\n"
                      f"순손익: {profit_emoji} {net_result:,} 코인\n"
                      f"활성 베팅: {active_bets}개",
                inline=False
            )

            embed.set_footer(text="최근 10개의 베팅 내역")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"베팅 내역 조회 실패: {e}", ephemeral=True)
            self.logger.error(f"베팅 내역 조회 실패: {e}", extra={'guild_id': guild_id})

    @app_commands.command(name="베팅설정", description="서버의 베팅 관련 설정을 변경합니다. (관리자 전용)")
    @app_commands.describe(
        min_bet="최소 베팅 금액",
        max_bet="최대 베팅 금액",
        max_duration="최대 베팅 지속 시간 (분)"
    )
    @app_commands.default_permissions(administrator=True)
    async def configure_betting(self, interaction: discord.Interaction,
                                min_bet: Optional[int] = None,
                                max_bet: Optional[int] = None,
                                max_duration: Optional[int] = None):
        guild_id = interaction.guild.id

        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        current_config = config.get_server_config(guild_id)
        betting_settings = current_config.get('betting_settings', {})

        updated = False

        if min_bet is not None:
            if min_bet < 1:
                await interaction.followup.send("최소 베팅 금액은 1 코인 이상이어야 합니다.")
                return
            betting_settings['min_bet'] = min_bet
            updated = True

        if max_bet is not None:
            if max_bet < 10:
                await interaction.followup.send("최대 베팅 금액은 10 코인 이상이어야 합니다.")
                return
            betting_settings['max_bet'] = max_bet
            updated = True

        if max_duration is not None:
            if max_duration < 5 or max_duration > 10080:
                await interaction.followup.send("최대 지속 시간은 5분에서 10080분(1주) 사이여야 합니다.")
                return
            betting_settings['max_duration'] = max_duration
            updated = True

        if updated:
            current_config['betting_settings'] = betting_settings
            config.save_server_config(guild_id, current_config)

            embed = discord.Embed(
                title="베팅 설정 업데이트됨",
                color=discord.Color.green()
            )

            if min_bet is not None:
                embed.add_field(name="최소 베팅 금액", value=f"{min_bet:,} 코인", inline=True)
            if max_bet is not None:
                embed.add_field(name="최대 베팅 금액", value=f"{max_bet:,} 코인", inline=True)
            if max_duration is not None:
                embed.add_field(name="최대 지속 시간", value=f"{max_duration}분", inline=True)

            await interaction.followup.send(embed=embed)
            self.logger.info("베팅 설정이 업데이트되었습니다.", extra={'guild_id': guild_id})
        else:
            await interaction.followup.send("변경 사항이 없어 설정을 업데이트하지 않았습니다.")

    @commands.Cog.listener()
    async def on_ready(self):
        """Setup control panel when bot is ready"""
        if not hasattr(self, '_control_panel_setup'):
            await self.setup_control_panel()
            self._control_panel_setup = True

    # Add these methods to your BettingCog class for debugging

    @app_commands.command(name="베팅디버그", description="베팅 시스템 디버깅 정보를 표시합니다. (관리자 전용)")
    async def debug_betting(self, interaction: discord.Interaction):
        """Debug command to check betting system status"""
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = interaction.guild.id

            # Check active events
            active_events_db = await self.bot.pool.fetch("""
                SELECT event_id, title, status, message_id, betting_channel_id
                FROM betting_events 
                WHERE guild_id = $1 AND status IN ('active', 'expired')
            """, guild_id)

            # Check registered views
            registered_views = []
            for view in self.bot.persistent_views:
                if hasattr(view, 'event_id'):
                    registered_views.append(f"Event {view.event_id} - View type: {type(view).__name__}")

            embed = discord.Embed(
                title="🔧 베팅 시스템 디버그 정보",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )

            # Active events in database
            db_events = "\n".join([
                f"ID: {e['event_id']}, 상태: {e['status']}, 메시지: {e['message_id']}, 채널: <#{e['betting_channel_id']}>"
                for e in active_events_db
            ]) or "없음"
            embed.add_field(name="DB의 활성 이벤트", value=db_events[:1024], inline=False)

            # Active events in memory
            memory_events = []
            if guild_id in self.active_events:
                for event_id, event in self.active_events[guild_id].items():
                    memory_events.append(f"ID: {event_id}, 상태: {event['status']}")
            memory_text = "\n".join(memory_events) or "없음"
            embed.add_field(name="메모리의 활성 이벤트", value=memory_text[:1024], inline=False)

            # Betting displays tracking
            displays = []
            if guild_id in self.betting_displays:
                for event_id, message_id in self.betting_displays[guild_id].items():
                    displays.append(f"Event {event_id}: Message {message_id}")
            display_text = "\n".join(displays) or "없음"
            embed.add_field(name="추적 중인 베팅 디스플레이", value=display_text[:1024], inline=False)

            # Registered persistent views
            view_text = "\n".join(registered_views[:10]) or "없음"  # Limit to 10 for space
            embed.add_field(name="등록된 지속성 뷰 (최대 10개)", value=view_text[:1024], inline=False)

            # Bot persistent views count
            embed.add_field(
                name="총 지속성 뷰 수",
                value=f"{len(self.bot.persistent_views)}개",
                inline=True
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"디버그 정보 조회 실패: {e}", ephemeral=True)
            self.logger.error(f"Debug command failed: {e}")

    @app_commands.command(name="베팅정리", description="베팅 시스템 데이터를 정리합니다. (관리자 전용)")
    async def cleanup_betting_data(self, interaction: discord.Interaction):
        """Clean up inconsistent betting data"""
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = interaction.guild.id
            cleaned_events = 0

            # Get all active events for this guild
            active_events = await self.bot.pool.fetch("""
                SELECT event_id, betting_channel_id, message_id
                FROM betting_events 
                WHERE guild_id = $1 AND status IN ('active', 'expired')
            """, guild_id)

            for event in active_events:
                event_id = event['event_id']
                channel_id = event['betting_channel_id']
                message_id = event['message_id']

                should_clean = False

                # Check if channel exists
                if channel_id:
                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        self.logger.info(f"Channel {channel_id} not found for event {event_id}, marking as resolved")
                        should_clean = True
                    else:
                        # Check if message exists
                        if message_id:
                            try:
                                await channel.fetch_message(message_id)
                            except discord.NotFound:
                                self.logger.info(
                                    f"Message {message_id} not found for event {event_id}, clearing message_id")
                                await self.bot.pool.execute("""
                                    UPDATE betting_events SET message_id = NULL WHERE event_id = $1
                                """, event_id)
                else:
                    should_clean = True

                if should_clean:
                    # Mark event as resolved and clean up
                    await self.bot.pool.execute("""
                        UPDATE betting_events 
                        SET status = 'resolved', resolved_at = $1
                        WHERE event_id = $2
                    """, datetime.now(timezone.utc), event_id)

                    # Remove from memory
                    if guild_id in self.active_events and event_id in self.active_events[guild_id]:
                        del self.active_events[guild_id][event_id]

                    # Remove from displays tracking
                    if guild_id in self.betting_displays and event_id in self.betting_displays[guild_id]:
                        del self.betting_displays[guild_id][event_id]

                    cleaned_events += 1

            await interaction.followup.send(f"✅ {cleaned_events}개의 이벤트가 정리되었습니다.", ephemeral=True)
            self.logger.info(f"Cleaned up {cleaned_events} betting events for guild {guild_id}")

        except Exception as e:
            await interaction.followup.send(f"정리 실패: {e}", ephemeral=True)
            self.logger.error(f"Cleanup failed: {e}")
    @app_commands.command(name="뷰재등록", description="베팅 뷰를 강제로 재등록합니다. (관리자 전용)")
    @app_commands.describe(event_id="재등록할 이벤트 ID (선택사항)")
    async def force_reregister_views(self, interaction: discord.Interaction, event_id: Optional[int] = None):
        """Force re-register betting views"""
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = interaction.guild.id
            reregistered = 0

            if event_id:
                # Re-register specific event
                event_data = await self.get_event(event_id, guild_id)
                if not event_data:
                    await interaction.followup.send(f"이벤트 {event_id}를 찾을 수 없습니다.", ephemeral=True)
                    return

                if not event_data['message_id'] or not event_data['betting_channel_id']:
                    await interaction.followup.send(f"이벤트 {event_id}에 메시지 ID 또는 채널 ID가 없습니다.", ephemeral=True)
                    return

                channel = self.bot.get_channel(event_data['betting_channel_id'])
                if not channel:
                    await interaction.followup.send(f"채널을 찾을 수 없습니다.", ephemeral=True)
                    return

                try:
                    message = await channel.fetch_message(event_data['message_id'])

                    # Create and register new view
                    view = BettingView(self.bot, event_data)
                    self.bot.add_view(view, message_id=event_data['message_id'])

                    # Update the message with the new view
                    embed = await self.create_betting_embed(event_data, guild_id)
                    await message.edit(embed=embed, view=view)

                    reregistered = 1

                except discord.NotFound:
                    await interaction.followup.send(f"메시지 {event_data['message_id']}를 찾을 수 없습니다.", ephemeral=True)
                    return

            else:
                # Re-register all active events
                await self.reload_persistent_views()

                # Count registered views for this guild
                active_events = await self.bot.pool.fetch("""
                    SELECT event_id FROM betting_events 
                    WHERE guild_id = $1 AND status IN ('active', 'expired') AND message_id IS NOT NULL
                """, guild_id)
                reregistered = len(active_events)

            await interaction.followup.send(f"✅ {reregistered}개의 베팅 뷰가 재등록되었습니다.", ephemeral=True)
            self.logger.info(f"Force re-registered {reregistered} betting views for guild {guild_id}")

        except Exception as e:
            await interaction.followup.send(f"뷰 재등록 실패: {e}", ephemeral=True)
            self.logger.error(f"Force reregister failed: {e}")

    # Improved wait_and_start_tasks method
    async def wait_and_start_tasks(self):
        """Wait for bot to be ready then start tasks"""
        try:
            await self.bot.wait_until_ready()
            self.logger.info("Bot is ready, initializing betting system...")

            await self.setup_database()
            self.logger.info("Database setup completed")

            await self.load_active_events()
            self.logger.info("Active events loaded")

            # Small delay to ensure bot is fully ready
            await asyncio.sleep(2)

            await self.reload_persistent_views()
            self.logger.info("Persistent views reloaded")

            await self.setup_control_panel()
            self.logger.info("Control panel setup completed")

            self.cleanup_expired_events.start()
            self.update_graphs.start()
            self.logger.info("Background tasks started")

        except Exception as e:
            self.logger.error(f"Error in wait_and_start_tasks: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")


async def setup(bot):
    await bot.add_cog(BettingCog(bot))