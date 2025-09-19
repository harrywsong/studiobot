# cogs/casino_crash.py - Updated with consistent embed layout and responsible gaming improvements
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
import math
import os
import io
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager
from typing import Dict

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    get_channel_id,
    get_server_setting
)

# Font setup for Korean text
here = os.path.dirname(os.path.dirname(__file__))
font_path = os.path.join(here, "assets", "fonts", "NotoSansKR-Bold.ttf")

# Load font file into Matplotlib if it exists
if os.path.exists(font_path):
    font_manager.fontManager.addfont(font_path)
    font_name = font_manager.FontProperties(fname=font_path).get_name()
    plt.rcParams['font.family'] = font_name
    plt.rcParams['axes.unicode_minus'] = False
    font_prop = font_manager.FontProperties(fname=font_path)
    matplotlib.rc('font', family=font_prop.get_name())
    matplotlib.rcParams['axes.unicode_minus'] = False
else:
    font_prop = None


class CrashGame:
    """Shared crash game instance for multiple players"""

    def __init__(self, bot, crash_point: float, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.crash_point = crash_point
        self.players: Dict[int, dict] = {}
        self.current_multiplier = 1.0
        self.game_started = False
        self.game_over = False
        self.start_time = None
        self.history: list[float] = [1.0]
        self.min_cashout_multiplier = get_server_setting(guild_id, 'crash_min_cashout_multiplier', 1.4)

    def add_player(self, user_id: int, bet: int):
        """Add a player to the game"""
        self.players[user_id] = {
            'bet': bet,
            'cashed_out': False,
            'cash_out_multiplier': 0.0
        }

    def cash_out_player(self, user_id: int) -> bool:
        """Cash out a player with proper validation"""
        if user_id not in self.players:
            return False
        if self.players[user_id]['cashed_out']:
            return False
        if self.game_over or not self.game_started:
            return False

        current_mult_rounded = round(self.current_multiplier, 2)
        min_mult_rounded = round(self.min_cashout_multiplier, 2)

        if current_mult_rounded < min_mult_rounded:
            return False

        self.players[user_id]['cashed_out'] = True
        self.players[user_id]['cash_out_multiplier'] = current_mult_rounded
        return True

    def get_active_players_count(self) -> int:
        """Get count of players who haven't cashed out"""
        return sum(1 for p in self.players.values() if not p['cashed_out'])

    def update_multiplier(self, new_multiplier: float):
        """Update multiplier and add to history"""
        self.current_multiplier = new_multiplier
        self.history.append(new_multiplier)


class JoinBetModal(discord.ui.Modal, title="크래시 게임 참가"):
    """Modal for a player to enter their bet amount."""
    bet_amount = discord.ui.TextInput(
        label="베팅 금액",
        placeholder="베팅할 금액을 입력하세요 (예: 100)",
        min_length=1,
        max_length=10,
    )

    def __init__(self, cog: 'CrashCog', game: CrashGame, view: 'CrashView'):
        super().__init__()
        self.cog = cog
        self.game = game
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            bet = int(self.bet_amount.value.strip())
            if bet <= 0:
                await interaction.followup.send("베팅 금액은 0보다 커야 합니다.", ephemeral=True)
                return

            if not self.game or self.game != self.cog.server_games.get(interaction.guild.id):
                await interaction.followup.send("게임을 찾을 수 없거나 이미 종료되었습니다.", ephemeral=True)
                return

            if interaction.user.id in self.game.players:
                await interaction.followup.send("이미 현재 게임에 참가 중입니다!", ephemeral=True)
                return

            if self.game.game_started:
                await interaction.followup.send("이미 게임이 시작되었습니다.", ephemeral=True)
                return

            can_start, error_msg = await self.cog.validate_game(interaction, bet)
            if not can_start:
                await interaction.followup.send(error_msg, ephemeral=True)
                return

            coins_cog = self.cog.bot.get_cog('CoinsCog')
            if not coins_cog:
                await interaction.followup.send("코인 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, bet, "crash_bet",
                                                "Crash game bet"):
                await interaction.followup.send("베팅 처리에 실패했습니다. 잔액을 확인해주세요.", ephemeral=True)
                return

            self.game.add_player(interaction.user.id, bet)

            try:
                embed = await self.view.create_embed(interaction)
                chart_file = await self.view.create_chart()
                game_message = self.cog.server_messages.get(interaction.guild.id)
                if game_message:
                    await game_message.edit(embed=embed, view=self.view, attachments=[chart_file] if chart_file else [])
            except discord.HTTPException as e:
                self.cog.logger.error(f"게임 메시지 업데이트 실패: {e}")

            await interaction.followup.send(f"게임에 참가했습니다! ({bet:,} 코인)", ephemeral=True)

            self.cog.logger.info(f"{interaction.user}가 {bet} 코인으로 크래시 게임 참가", extra={'guild_id': interaction.guild.id})

        except ValueError:
            await interaction.followup.send("유효한 숫자를 입력해주세요.", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"크래시 게임 참가 중 오류: {e}", exc_info=True)
            try:
                await interaction.followup.send("게임 참가 중 오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)
            except:
                pass


class CrashView(discord.ui.View):
    """Interactive crash game view with standardized embeds"""

    def __init__(self, cog: 'CrashCog', game: CrashGame):
        super().__init__(timeout=None)
        self.cog = cog
        self.bot = cog.bot
        self.game = game
        self.update_button_states()

    def update_button_states(self):
        """Update button states based on game state"""
        if not self.game.game_started and not self.game.game_over:
            self.join_button.disabled = False
            self.leave_button.disabled = False
            self.start_button.disabled = False
            self.cash_out_button.disabled = True
        elif self.game.game_started and not self.game.game_over:
            self.join_button.disabled = True
            self.leave_button.disabled = True
            self.start_button.disabled = True
            self.cash_out_button.disabled = False
        else:
            self.join_button.disabled = True
            self.leave_button.disabled = True
            self.start_button.disabled = True
            self.cash_out_button.disabled = True

    def draw_chart(self) -> io.BytesIO:
        """Create a chart showing the multiplier progression"""
        plt.figure(figsize=(10, 6))

        time_points = list(range(len(self.game.history)))
        plt.plot(time_points, self.game.history, 'b-', linewidth=2, label='배수')

        if self.game.game_over:
            plt.axhline(y=self.game.crash_point, color='r', linestyle='--',
                        linewidth=2, alpha=0.7, label=f'크래시 지점: {self.game.crash_point:.2f}x')

        # Mark cashout points
        for user_id, player_data in self.game.players.items():
            if player_data['cashed_out']:
                cashout_time_point = 0
                for i, hist_multiplier in enumerate(self.game.history):
                    if hist_multiplier <= player_data['cash_out_multiplier']:
                        cashout_time_point = i
                    else:
                        break
                plt.scatter(cashout_time_point, player_data['cash_out_multiplier'],
                            color='green', s=100, zorder=5, alpha=0.8)

        if self.game.game_started or not self.game.game_over:
            plt.axhline(y=self.game.min_cashout_multiplier, color='gold', linestyle=':',
                        linewidth=2, alpha=0.8, label=f'최소 캐시아웃: {self.game.min_cashout_multiplier:.2f}x')

        plt.xlabel('시간 (초)', fontproperties=font_prop if font_prop else None)
        plt.ylabel('배수', fontproperties=font_prop if font_prop else None)
        plt.title(f'크래시 게임 진행 상황 - 현재: {self.game.current_multiplier:.2f}x',
                  fontproperties=font_prop if font_prop else None)
        plt.grid(True, alpha=0.3)
        plt.legend(prop=font_prop if font_prop else None)

        max_y = max(self.game.current_multiplier * 1.2, 2.0)
        plt.ylim(1.0, max_y)

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        plt.close()
        buf.seek(0)
        return buf

    async def create_chart(self) -> discord.File:
        """Create chart file for Discord"""
        try:
            buf = self.draw_chart()
            return discord.File(buf, filename="crash_chart.png")
        except Exception as e:
            self.cog.logger.error(f"차트 생성 실패: {e}")
            return None

    def create_crash_display(self, interaction: discord.Interaction, final: bool = False) -> str:
        """Create standardized crash game display"""
        if final and self.game.game_over:
            return f"🚀 **최종 결과**\n로켓이 **{self.game.crash_point:.2f}x**에서 추락했습니다!\n\n💥 **게임 종료**"
        elif self.game.game_started:
            return f"🚀 **현재 배수: {self.game.current_multiplier:.2f}x**\n\n⚡ **상승 중...** (최소 캐시아웃: {self.game.min_cashout_multiplier:.2f}x)"
        else:
            return f"🚀 **게임 대기 중**\n\n⏰ **30초 후 자동 시작** 또는 '지금 시작' 클릭"

    async def create_embed(self, interaction: discord.Interaction, final: bool = False) -> discord.Embed:
        """Create standardized game embed"""
        # Standardized title and color logic
        if self.game.game_over and final:
            title = f"🚀 크래시 - 💥 로켓이 {self.game.crash_point:.2f}x에서 추락!"
            color = discord.Color.red()
        elif self.game.game_started:
            title = f"🚀 크래시 - ⚡ 진행 중... {self.game.current_multiplier:.2f}x"
            color = discord.Color.orange()
        else:
            title = "🚀 크래시 - 🔄 대기 중..."
            color = discord.Color.blue()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        embed.add_field(
            name="🎯 게임 현황",
            value=self.create_crash_display(interaction, final),
            inline=False
        )

        # STANDARDIZED FIELD 2: Betting Info
        player_count = len(self.game.players)
        active_count = self.game.get_active_players_count()

        if self.game.game_started:
            status_info = f"👥 **총 플레이어:** {player_count}명\n⚡ **활성 플레이어:** {active_count}명\n📈 **현재 배수:** {self.game.current_multiplier:.2f}x"
        else:
            status_info = f"👥 **대기 중인 플레이어:** {player_count}명\n⏰ **게임 시작까지:** 30초 이내"

        embed.add_field(name="💳 게임 정보", value=status_info, inline=False)

        # Display players (up to 10)
        if self.game.players:
            player_info = []
            for user_id, player_data in list(self.game.players.items())[:10]:
                try:
                    user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                    username = user.display_name if user else f"User {user_id}"

                    if player_data['cashed_out']:
                        payout = int(player_data['bet'] * player_data['cash_out_multiplier'])
                        player_info.append(f"{username}: ✅ {player_data['cash_out_multiplier']:.2f}x (+{payout:,})")
                    elif self.game.game_over:
                        player_info.append(f"{username}: 💥 추락 (-{player_data['bet']:,})")
                    else:
                        can_cashout = self.game.current_multiplier >= self.game.min_cashout_multiplier
                        status = " ✅ 캐시아웃 가능" if can_cashout else f" ⏳ {self.game.min_cashout_multiplier:.2f}x까지 대기"
                        player_info.append(f"{username}: 🎲 대기중 ({player_data['bet']:,}){status}")
                except Exception:
                    continue

            if player_info:
                embed.add_field(name=f"👥 플레이어 현황", value="\n".join(player_info), inline=False)

        if not self.game.game_started and not final:
            # Game rules field
            embed.add_field(
                name="📋 게임 규칙",
                value=f"• '게임 참가'를 눌러 베팅하세요\n• 로켓이 **{self.game.min_cashout_multiplier:.2f}x** 이상 도달 후 캐시아웃 가능\n• '지금 시작' 또는 30초 후 자동 시작\n• 로켓이 추락하기 전에 캐시아웃하세요!",
                inline=False
            )

        # Standardized footer
        embed.set_footer(text=f"플레이어: Multiple | Server: {interaction.guild.name} | 📊 실시간 차트 첨부")
        return embed

    @discord.ui.button(label="게임 참가", style=discord.ButtonStyle.green, emoji="🎲", custom_id="join_game")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.game_started:
            await interaction.response.send_message("이미 게임이 시작되었습니다.", ephemeral=True)
            return
        if interaction.user.id in self.game.players:
            await interaction.response.send_message("이미 현재 게임에 참가 중입니다!", ephemeral=True)
            return
        if self.game != self.cog.server_games.get(interaction.guild.id):
            await interaction.response.send_message("게임이 더 이상 활성화되어 있지 않습니다.", ephemeral=True)
            return

        modal = JoinBetModal(self.cog, self.game, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="게임 나가기", style=discord.ButtonStyle.red, emoji="❌", custom_id="leave_game")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        if self.game.game_started:
            await interaction.followup.send("이미 게임이 시작되었습니다.", ephemeral=True)
            return

        player_data = self.game.players.get(interaction.user.id)
        if not player_data:
            await interaction.followup.send("이 게임에 참가하지 않았습니다!", ephemeral=True)
            return

        bet_amount = player_data['bet']
        del self.game.players[interaction.user.id]

        coins_cog = self.cog.bot.get_cog('CoinsCog')
        if coins_cog:
            await coins_cog.add_coins(interaction.user.id, interaction.guild.id, bet_amount, "crash_leave",
                                      "Crash game leave refund")

        try:
            embed = await self.create_embed(interaction)
            chart_file = await self.create_chart()
            game_message = self.cog.server_messages.get(interaction.guild.id)
            if game_message:
                await game_message.edit(embed=embed, view=self, attachments=[chart_file] if chart_file else [])
        except Exception as e:
            self.cog.logger.error(f"게임 메시지 업데이트 실패: {e}")

        await interaction.followup.send(f"게임에서 나갔습니다. {bet_amount:,} 코인이 환불되었습니다.", ephemeral=True)

    @discord.ui.button(label="지금 시작", style=discord.ButtonStyle.blurple, emoji="🚀", custom_id="start_game_now")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.game_started:
            await interaction.response.send_message("이미 게임이 시작되었습니다.", ephemeral=True)
            return
        if not self.game.players:
            await interaction.response.send_message("참가한 플레이어가 없어 게임을 시작할 수 없습니다.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        start_event = self.cog.start_events.get(guild_id)
        if start_event:
            start_event.set()
            await interaction.response.send_message("게임을 곧 시작합니다!", ephemeral=True)
        else:
            await interaction.response.send_message("게임 시작 이벤트를 찾을 수 없습니다.", ephemeral=True)

    @discord.ui.button(label="캐시아웃", style=discord.ButtonStyle.success, emoji="💸", custom_id="cash_out")
    async def cash_out_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        if not self.game.game_started:
            await interaction.followup.send("아직 게임이 시작되지 않았습니다!", ephemeral=True)
            return
        if interaction.user.id not in self.game.players:
            await interaction.followup.send("이 게임에 참가하지 않았습니다!", ephemeral=True)
            return
        if self.game.players[interaction.user.id]['cashed_out']:
            await interaction.followup.send("이미 캐시아웃했습니다!", ephemeral=True)
            return

        current_mult_rounded = round(self.game.current_multiplier, 2)
        min_mult_rounded = round(self.game.min_cashout_multiplier, 2)

        if current_mult_rounded < min_mult_rounded:
            await interaction.followup.send(
                f"최소 캐시아웃 배수인 **{min_mult_rounded:.2f}x**에 도달해야 캐시아웃할 수 있습니다.\n현재 배수: **{current_mult_rounded:.2f}x**",
                ephemeral=True
            )
            return

        cashout_success = self.game.cash_out_player(interaction.user.id)

        if cashout_success:
            player_data = self.game.players[interaction.user.id]
            payout = int(player_data['bet'] * player_data['cash_out_multiplier'])

            coins_cog = self.cog.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(interaction.user.id, interaction.guild.id, payout, "crash_win",
                                          f"Crash cashout at {player_data['cash_out_multiplier']:.2f}x")

            await interaction.followup.send(
                f"{interaction.user.mention}님이 **{player_data['cash_out_multiplier']:.2f}x**에서 캐시아웃! {payout:,} 코인 획득!",
                ephemeral=False
            )
        else:
            await interaction.followup.send("캐시아웃에 실패했습니다. 게임이 이미 종료되었을 수 있습니다.", ephemeral=True)


class CrashCog(commands.Cog):
    """Crash multiplier prediction game - Multi-server aware with responsible gaming features"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("크래시")
        self.server_games: Dict[int, CrashGame] = {}
        self.server_messages: Dict[int, discord.Message] = {}
        self.server_views: Dict[int, CrashView] = {}
        self.start_events: Dict[int, asyncio.Event] = {}
        self.logger.info("크래시 게임 시스템이 초기화되었습니다.")

    async def validate_game(self, interaction: discord.Interaction, bet: int):
        """Validate game using casino base with responsible gaming limits"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        # More conservative limits for crash games due to their addictive potential
        min_bet = get_server_setting(interaction.guild.id, 'crash_min_bet', 10)
        max_bet = get_server_setting(interaction.guild.id, 'crash_max_bet', 100)  # Lower max bet

        return await casino_base.validate_game_start(interaction, "crash", bet, min_bet, max_bet)

    def generate_crash_point(self) -> float:
        """Generate crash point with more balanced distribution"""
        rand = random.random()

        # More conservative distribution to reduce extreme wins/losses
        if rand <= 0.60:  # 60% chance for 1.1x - 1.8x
            return round(random.uniform(1.1, 1.8), 2)
        elif rand <= 0.85:  # 25% chance for 1.8x - 2.5x
            return round(random.uniform(1.8, 2.5), 2)
        elif rand <= 0.95:  # 10% chance for 2.5x - 4.0x
            return round(random.uniform(2.5, 4.0), 2)
        else:  # 5% chance for 4.0x - 8.0x (reduced from 10.0x)
            return round(random.uniform(4.0, 8.0), 2)

    async def game_lifecycle_task(self, guild_id: int):
        """Manages the game lifecycle with responsible gaming considerations"""
        try:
            current_game = self.server_games.get(guild_id)
            if not current_game:
                return

            game_view = self.server_views.get(guild_id)
            game_message = self.server_messages.get(guild_id)
            start_event = self.start_events.get(guild_id)

            if not all([game_view, game_message, start_event]):
                return

            # Wait for game start
            try:
                await asyncio.wait_for(start_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                pass

            if not current_game.players:
                if game_message:
                    try:
                        await game_message.edit(content="참가자가 없어 게임이 취소되었습니다.", embed=None, view=None, attachments=[])
                    except discord.NotFound:
                        pass
                self.cleanup_server_game(guild_id)
                return

            current_game.game_started = True
            game_view.update_button_states()

            # Create initial game interaction for embed
            initial_interaction = type('MockInteraction', (), {
                'guild': type('MockGuild', (), {
                    'name': self.bot.get_guild(guild_id).name if self.bot.get_guild(guild_id) else 'Unknown'})()
            })()

            try:
                embed = await game_view.create_embed(initial_interaction)
                chart_file = await game_view.create_chart()
                await game_message.edit(embed=embed, view=game_view, attachments=[chart_file] if chart_file else [])
            except Exception as e:
                self.logger.error(f"게임 시작 메시지 업데이트 실패: {e}")

            await self.run_crash_game(guild_id)

        except Exception as e:
            self.logger.error(f"Game lifecycle error: {e}", exc_info=True)

    async def run_crash_game(self, guild_id: int):
        """Run the crash game with slower, more controlled progression"""
        current_game = self.server_games.get(guild_id)
        game_message = self.server_messages.get(guild_id)
        game_view = self.server_views.get(guild_id)

        if not all([current_game, game_message, game_view]):
            return

        # Create mock interaction for embed updates
        mock_interaction = type('MockInteraction', (), {
            'guild': type('MockGuild', (),
                          {'name': self.bot.get_guild(guild_id).name if self.bot.get_guild(guild_id) else 'Unknown'})()
        })()

        while (current_game.current_multiplier < current_game.crash_point and
               current_game.get_active_players_count() > 0):

            await asyncio.sleep(1.0)  # Slower progression for better control

            # More gradual increment progression
            increment = 0.01 + (current_game.current_multiplier / 50)  # Slower scaling
            new_multiplier = current_game.current_multiplier + increment
            new_multiplier = round(new_multiplier, 2)
            current_game.update_multiplier(new_multiplier)

            try:
                embed = await game_view.create_embed(mock_interaction)
                chart_file = await game_view.create_chart()
                await game_message.edit(embed=embed, view=game_view, attachments=[chart_file] if chart_file else [])
            except Exception as e:
                self.logger.error(f"게임 플레이 중 메시지 업데이트 실패: {e}")
                break

        await self.end_crash_game(guild_id)

    async def end_crash_game(self, guild_id: int):
        """End the crash game with final results"""
        current_game = self.server_games.get(guild_id)
        game_message = self.server_messages.get(guild_id)
        game_view = self.server_views.get(guild_id)

        if not current_game:
            return

        current_game.game_over = True

        if game_message and game_view:
            try:
                # Create mock interaction for final embed
                mock_interaction = type('MockInteraction', (), {
                    'guild': type('MockGuild', (), {
                        'name': self.bot.get_guild(guild_id).name if self.bot.get_guild(guild_id) else 'Unknown'})()
                })()

                game_view.update_button_states()
                embed = await game_view.create_embed(mock_interaction, final=True)
                chart_file = await game_view.create_chart()
                await game_message.edit(embed=embed, view=game_view, attachments=[chart_file] if chart_file else [])
            except Exception as e:
                self.logger.error(f"게임 종료 중 메시지 업데이트 실패: {e}")

        self.cleanup_server_game(guild_id)

    def cleanup_server_game(self, guild_id: int):
        """Clean up server-specific game data"""
        if guild_id in self.server_games:
            del self.server_games[guild_id]
        if guild_id in self.server_messages:
            del self.server_messages[guild_id]
        if guild_id in self.server_views:
            del self.server_views[guild_id]
        if guild_id in self.start_events:
            del self.start_events[guild_id]

    @app_commands.command(name="크래시", description="로켓이 추락하기 전에 캐시아웃하는 게임 (주의: 중독성이 높을 수 있음)")
    @app_commands.describe(bet="베팅 금액")
    async def crash(self, interaction: discord.Interaction, bet: int):
        # Check if casino games are enabled
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        guild_id = interaction.guild.id

        # Check for existing game
        if guild_id in self.server_games:
            await interaction.response.send_message("⚠ 이 서버에서 다른 크래시 게임이 이미 진행 중이거나 대기 중입니다.", ephemeral=True)
            return

        can_start, error_msg = await self.validate_game(interaction, bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        coins_cog = self.bot.get_cog('CoinsCog')
        if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, bet, "crash_bet", "Crash game bet"):
            await interaction.response.send_message("베팅 처리 실패!", ephemeral=True)
            return

        # Create server-specific game
        self.start_events[guild_id] = asyncio.Event()
        crash_point = self.generate_crash_point()
        self.server_games[guild_id] = CrashGame(self.bot, crash_point, guild_id)
        self.server_games[guild_id].add_player(interaction.user.id, bet)

        self.server_views[guild_id] = CrashView(self, self.server_games[guild_id])
        embed = await self.server_views[guild_id].create_embed(interaction)
        chart_file = await self.server_views[guild_id].create_chart()

        await interaction.response.send_message(embed=embed, view=self.server_views[guild_id], file=chart_file)
        self.server_messages[guild_id] = await interaction.original_response()

        self.logger.info(f"{interaction.user}가 {bet} 코인으로 크래시 게임 시작", extra={'guild_id': guild_id})

        # Start the game lifecycle
        asyncio.create_task(self.game_lifecycle_task(guild_id))


async def setup(bot):
    await bot.add_cog(CrashCog(bot))