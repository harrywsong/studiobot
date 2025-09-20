# cogs/casino_bingo.py - Updated for multi-server support with standardized embeds
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
from typing import Dict, List, Optional

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    is_server_configured
)
from cogs.coins import check_user_casino_eligibility # <--- ADD THIS LINE


class BingoCard:
    """Represents a bingo card"""

    def __init__(self):
        self.card = self.generate_card()
        self.marked = [[False for _ in range(5)] for _ in range(5)]
        # Mark the center space as free
        self.marked[2][2] = True

    def generate_card(self):
        """Generate a 5x5 bingo card"""
        card = []

        # B column: 1-15
        b_column = random.sample(range(1, 16), 5)
        # I column: 16-30
        i_column = random.sample(range(16, 31), 5)
        # N column: 31-45 (with center free space)
        n_column = random.sample(range(31, 46), 4)
        n_column.insert(2, 'FREE')  # Insert FREE in the middle
        # G column: 46-60
        g_column = random.sample(range(46, 61), 5)
        # O column: 61-75
        o_column = random.sample(range(61, 76), 5)

        # Combine columns into rows
        for i in range(5):
            row = [b_column[i], i_column[i], n_column[i], g_column[i], o_column[i]]
            card.append(row)

        return card

    def mark_number(self, number):
        """Mark a number on the card if it exists"""
        for i in range(5):
            for j in range(5):
                if self.card[i][j] == number:
                    self.marked[i][j] = True
                    return True
        return False

    def check_bingo(self):
        """Check if there's a bingo (line, column, or diagonal)"""
        # Check rows
        for row in self.marked:
            if all(row):
                return True

        # Check columns
        for j in range(5):
            if all(self.marked[i][j] for i in range(5)):
                return True

        # Check diagonals
        if all(self.marked[i][i] for i in range(5)):
            return True
        if all(self.marked[i][4 - i] for i in range(5)):
            return True

        return False

    def format_card_compact(self):
        """Format the card in a more compact, readable way"""
        lines = []
        lines.append(" B  I  N  G  O")

        for i in range(5):
            line = ""
            for j in range(5):
                cell = self.card[i][j]
                if cell == 'FREE':
                    display = "★"  # Star for free space
                else:
                    display = f"{cell:2d}"

                if self.marked[i][j]:
                    display = f"[{display}]"  # Brackets for marked
                else:
                    display = f" {display} "  # Spaces for unmarked

                line += display
            lines.append(line)

        return "```\n" + "\n".join(lines) + "\n```"


class BingoPlayer:
    """Represents a player in the bingo game"""

    def __init__(self, user_id: int, username: str, bet: int):
        self.user_id = user_id
        self.username = username
        self.bet = bet
        self.card = BingoCard()
        self.has_bingo = False
        self.bingo_achieved_at = None


class MultiBingoView(discord.ui.View):
    """Interactive multiplayer bingo game view - Multi-server aware"""

    def __init__(self, bot, guild_id: int, channel_id: int, initial_user_id: int, initial_bet: int):
        super().__init__(timeout=None)  # 3 minutes for joining
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.players: Dict[int, BingoPlayer] = {}
        self.called_numbers = []
        self.game_started = False
        self.game_over = False
        self.winners = []
        self.numbers_called = 0
        self.max_calls = 75  # All possible numbers
        self.join_phase = True
        self.game_message = None
        self.logger = get_logger("빙고")

        # Add the initial player
        self.add_player(initial_user_id, "Unknown", initial_bet)

    def add_player(self, user_id: int, username: str, bet: int):
        """Add a player to the game"""
        if user_id not in self.players and len(self.players) < 4:  # Max 4 players for better display
            self.players[user_id] = BingoPlayer(user_id, username, bet)
            return True
        return False

    def remove_player(self, user_id: int):
        """Remove a player from the game"""
        if user_id in self.players and not self.game_started:
            del self.players[user_id]
            return True
        return False

    def create_bingo_display(self, last_called=None):
        """Create standardized bingo display"""
        if last_called:
            # Determine letter based on number range
            if 1 <= last_called <= 15:
                letter = "B"
            elif 16 <= last_called <= 30:
                letter = "I"
            elif 31 <= last_called <= 45:
                letter = "N"
            elif 46 <= last_called <= 60:
                letter = "G"
            else:
                letter = "O"

            display = f"📢 **방금 호출: {letter}-{last_called}**\n\n"
        else:
            display = "🎲 **게임 진행 중**\n\n"

        # Show recently called numbers
        if self.called_numbers:
            recent = self.called_numbers[-8:]  # Last 8 numbers
            recent_str = " • ".join(str(n) for n in recent)
            if len(self.called_numbers) > 8:
                recent_str = "... • " + recent_str
            display += f"🔢 **최근 호출:** `{recent_str}`"
        else:
            display += "🎯 **호출된 번호가 없습니다**"

        return display

    async def start_game(self, interaction: discord.Interaction):
        """Start the bingo game"""
        self.join_phase = False
        self.game_started = True

        # Disable join/leave buttons, keep only emergency stop
        for item in self.children:
            if hasattr(item, 'custom_id'):
                if item.custom_id in ['join_game', 'leave_game', 'start_now']:
                    item.disabled = True

        # Show initial game state with all cards
        embed = self.create_game_embed()
        await interaction.edit_original_response(embed=embed, view=self)

        # Auto-call numbers every 4 seconds
        while not self.game_over and self.numbers_called < self.max_calls:
            await asyncio.sleep(4)

            if self.game_over:
                break

            await self.call_next_number(interaction)

        # Game timeout
        if not self.game_over:
            await self.end_game(interaction, "모든 번호 호출됨 - 승자 없음!")

    async def call_next_number(self, interaction: discord.Interaction):
        """Call the next bingo number and update ALL cards publicly"""
        # Generate list of uncalled numbers
        all_numbers = list(range(1, 76))
        available_numbers = [n for n in all_numbers if n not in self.called_numbers]

        if not available_numbers:
            await self.end_game(interaction, "모든 번호가 호출되었습니다!")
            return

        # Call a random number
        called_number = random.choice(available_numbers)
        self.called_numbers.append(called_number)
        self.numbers_called += 1

        # Mark the number on all players' cards and check for bingo
        new_winners = []
        for player in self.players.values():
            if not player.has_bingo:
                player.card.mark_number(called_number)
                if player.card.check_bingo():
                    player.has_bingo = True
                    player.bingo_achieved_at = self.numbers_called
                    new_winners.append(player)

        # If we have winners, end the game
        if new_winners:
            self.winners.extend(new_winners)
            await self.end_game(interaction, f"{len(new_winners)}명의 플레이어가 빙고를 달성했습니다!")
            return

        # Update the embed with all updated cards
        try:
            embed = self.create_game_embed(called_number)
            await interaction.edit_original_response(embed=embed, view=self)
        except Exception as e:
            # If Discord edit fails, log but continue game
            print(f"Failed to update bingo display: {e}")

    def create_game_embed(self, last_called=None):
        """Create the game display embed with standardized format"""
        if self.join_phase:
            title = "🎱 빙고 게임"
            color = discord.Color.blue()
        elif self.game_over:
            if self.winners:
                title = "🎱 빙고 게임 - 🎉 게임 완료!"
                color = discord.Color.green()
            else:
                title = "🎱 빙고 게임 - 💸 게임 종료"
                color = discord.Color.red()
        else:
            title = "🎱 빙고 게임 - 진행 중"
            color = discord.Color.blue()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        if self.join_phase:
            # STANDARDIZED FIELD 1: Game Display (during join phase)
            embed.add_field(
                name="🎯 게임 상태",
                value=f"🔄 **플레이어 대기 중**\n\n👥 **참가자:** {len(self.players)}/4명\n⏰ **자동 시작:** 30초 후",
                inline=False
            )

            # STANDARDIZED FIELD 2: Betting Info
            if self.players:
                required_bet = next(iter(self.players.values())).bet
                embed.add_field(
                    name="💳 베팅 정보",
                    value=f"💰 **베팅 금액:** {required_bet:,} 코인\n🎲 **상태:** 플레이어 모집 중",
                    inline=False
                )

            # Show player list during join phase
            if self.players:
                player_names = []
                for player in self.players.values():
                    player_names.append(f"🎲 {player.username}")

                embed.add_field(
                    name="👥 참가자 목록",
                    value="\n".join(player_names),
                    inline=False
                )

            # Game rules
            embed.add_field(
                name="📋 게임 규칙",
                value="• 가로, 세로, 대각선 중 한 줄을 완성하면 승리\n• 빠른 빙고일수록 높은 배당금\n• 다수 승자시 상금 분배\n• 중앙 칸(★)은 무료 스페이스\n• `[숫자]`는 호출된 번호",
                inline=False
            )

        elif self.game_started or self.game_over:
            # STANDARDIZED FIELD 1: Game Display
            embed.add_field(
                name="🎯 빙고 현황",
                value=self.create_bingo_display(last_called),
                inline=False
            )

            # STANDARDIZED FIELD 2: Betting Info
            if self.players:
                bet_amount = next(iter(self.players.values())).bet
                status = "게임 완료" if self.game_over else f"진행 중 ({self.numbers_called}/75 호출)"
                embed.add_field(
                    name="💳 베팅 정보",
                    value=f"💰 **베팅 금액:** {bet_amount:,} 코인\n🎲 **상태:** {status}",
                    inline=False
                )

            # Show ALL player cards publicly during game
            if self.players:
                cards_display = ""
                for i, player in enumerate(self.players.values()):
                    status_emoji = "🏆" if player.has_bingo else "🎯"
                    cards_display += f"{status_emoji} **{player.username}**\n{player.card.format_card_compact()}\n"

                embed.add_field(name="🎲 플레이어 카드", value=cards_display, inline=False)

            # STANDARDIZED FIELD 3: Game Results (if game over)
            if self.game_over:
                if self.winners:
                    winner_names = [p.username for p in self.winners]
                    result_text = f"🏆 **승자:** {', '.join(winner_names)}"
                    calls_text = f"📞 **호출 수:** {self.numbers_called}번"

                    # Show payouts
                    payout_info = []
                    for winner in self.winners:
                        payout = self.calculate_payout(winner)
                        payout_info.append(f"💰 {winner.username}: +{payout:,} 코인")

                    result_info = f"{result_text}\n{calls_text}\n\n" + "\n".join(payout_info)
                else:
                    result_info = f"💸 **승자 없음**\n📞 **총 호출:** {self.numbers_called}번\n\n아무도 빙고를 달성하지 못했습니다."

                embed.add_field(name="📊 게임 결과", value=result_info, inline=False)

        # Standardized footer
        embed.set_footer(text=f"Server: {self.bot.get_guild(self.guild_id).name}")

        return embed

    def calculate_payout(self, player: BingoPlayer):
        """Calculate payout based on how quickly bingo was achieved"""
        if not player.has_bingo or not self.winners:
            return 0

        # Base payout calculation
        if player.bingo_achieved_at <= 20:
            multiplier = 4.0
        elif player.bingo_achieved_at <= 35:
            multiplier = 2.5
        else:
            multiplier = 1.5

        base_payout = int(player.bet * multiplier)

        # If multiple winners, they share a bonus pot from all players
        total_pot = sum(p.bet for p in self.players.values())
        bonus_share = total_pot * 0.2 / len(self.winners)  # 20% bonus pot shared

        return base_payout + int(bonus_share)

    async def end_game(self, interaction: discord.Interaction, reason: str):
        """End the bingo game"""
        self.game_over = True

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Handle payouts
        coins_cog = self.bot.get_cog('CoinsCog')
        if coins_cog and self.winners:
            for winner in self.winners:
                payout = self.calculate_payout(winner)

                success = await coins_cog.add_coins(
                    winner.user_id,
                    interaction.guild.id,
                    payout,
                    "bingo_win",
                    f"멀티플레이어 빙고 승리 ({winner.bingo_achieved_at}번 호출)"
                )

                if not success:
                    self.logger.error(
                        f"Failed to add {payout} coins to user {winner.user_id} for bingo win",
                        extra={'guild_id': interaction.guild.id}
                    )

        embed = self.create_game_embed()

        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except discord.NotFound:
            pass

    @discord.ui.button(label="🎲 게임 참가", style=discord.ButtonStyle.green, custom_id="join_game")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.join_phase:
            await interaction.response.send_message("❌ 게임이 이미 시작되었습니다!", ephemeral=True)
            return

        if interaction.user.id in self.players:
            await interaction.response.send_message("❌ 이미 이 게임에 참가하셨습니다!", ephemeral=True)
            return

        if len(self.players) >= 4:
            await interaction.response.send_message("❌ 게임이 가득 찼습니다! (최대 4명)", ephemeral=True)
            return

        # =================================================================
        # LOAN RESTRICTION CHECK FOR JOINING PLAYERS
        # =================================================================
        restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
        if not restriction['allowed']:
            await interaction.response.send_message(restriction['message'], ephemeral=True)
            return
        # =================================================================

        # Get the bet amount from the first player (all players must match)
        if self.players:
            required_bet = next(iter(self.players.values())).bet
        else:
            required_bet = 50  # Default bet

        # Validate the player can afford the bet
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "bingo", required_bet, required_bet, required_bet
            )
            if not can_start:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

        # Deduct the bet
        coins_cog = self.bot.get_cog('CoinsCog')
        if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, required_bet, "bingo_bet",
                                            "멀티플레이어 빙고 베팅"):
            await interaction.response.send_message("❌ 베팅 처리에 실패했습니다!", ephemeral=True)
            return

        # Add player
        self.add_player(interaction.user.id, interaction.user.display_name, required_bet)

        embed = self.create_game_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="❌ 게임 나가기", style=discord.ButtonStyle.red, custom_id="leave_game")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.join_phase:
            await interaction.response.send_message("❌ 게임이 시작된 후에는 나갈 수 없습니다!", ephemeral=True)
            return

        if interaction.user.id not in self.players:
            await interaction.response.send_message("❌ 이 게임에 참가하지 않으셨습니다!", ephemeral=True)
            return

        # Refund the player
        player = self.players[interaction.user.id]
        coins_cog = self.bot.get_cog('CoinsCog')
        if coins_cog:
            success = await coins_cog.add_coins(
                interaction.user.id,
                interaction.guild.id,
                player.bet,
                "bingo_refund",
                "빙고 게임 나가기"
            )

            if not success:
                await interaction.response.send_message("❌ 환불 처리에 실패했습니다!", ephemeral=True)
                return

        # Remove player
        self.remove_player(interaction.user.id)

        # If no players left, disable the view
        if not self.players:
            for item in self.children:
                item.disabled = True

        embed = self.create_game_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🚀 지금 시작", style=discord.ButtonStyle.primary, custom_id="start_now")
    async def start_now_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.join_phase:
            await interaction.response.send_message("❌ 게임이 이미 시작되었습니다!", ephemeral=True)
            return

        if len(self.players) < 2:
            await interaction.response.send_message("❌ 최소 2명의 플레이어가 필요합니다!", ephemeral=True)
            return

        await interaction.response.defer()
        await self.start_game(interaction)


class BingoCog(commands.Cog):
    """Casino Bingo game - Multi-server aware with standardized embeds"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("빙고")
        self.active_games: Dict[int, MultiBingoView] = {}  # channel_id -> game
        self.logger.info("빙고 게임 시스템이 초기화되었습니다.")

    async def validate_game(self, interaction: discord.Interaction, bet: int):
        """Validate game using casino base"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        return await casino_base.validate_game_start(
            interaction, "bingo", bet, 30, 500
        )

    @app_commands.command(name="빙고", description="멀티플레이어 빙고 게임을 시작하거나 참가합니다")
    @app_commands.describe(bet="베팅 금액 (30-500코인)")
    async def bingo(self, interaction: discord.Interaction, bet: int = 50):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
        if not restriction['allowed']:
            await interaction.response.send_message(restriction['message'], ephemeral=True)
            return

        channel_id = interaction.channel_id

        # Check if there's already an active game in this channel
        if channel_id in self.active_games:
            existing_game = self.active_games[channel_id]
            if existing_game.join_phase:
                await interaction.response.send_message(
                    "🎱 이 채널에 이미 플레이어를 기다리고 있는 빙고 게임이 있습니다! 위의 '게임 참가' 버튼을 찾아보세요.",
                    ephemeral=True
                )
                return
            elif not existing_game.game_over:
                await interaction.response.send_message(
                    "🎱 이 채널에서 이미 빙고 게임이 진행 중입니다!",
                    ephemeral=True
                )
                return

        # Validate the bet
        can_start, error_msg = await self.validate_game(interaction, bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # Deduct the bet from the starter
        coins_cog = self.bot.get_cog('CoinsCog')
        if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, bet, "bingo_bet",
                                            "멀티플레이어 빙고 베팅"):
            await interaction.response.send_message("❌ 베팅 처리에 실패했습니다!", ephemeral=True)
            return

        # Create new game
        game_view = MultiBingoView(self.bot, interaction.guild.id, channel_id, interaction.user.id, bet)
        self.active_games[channel_id] = game_view

        # Update the first player with the actual username
        game_view.players[interaction.user.id].username = interaction.user.display_name

        embed = game_view.create_game_embed()
        await interaction.response.send_message(embed=embed, view=game_view)

        # Auto-start after 30 seconds if enough players
        await asyncio.sleep(30)

        if (channel_id in self.active_games and
                self.active_games[channel_id].join_phase and
                len(self.active_games[channel_id].players) >= 2):
            try:
                await self.active_games[channel_id].start_game(interaction)
            except:
                pass  # Game might have been manually started or cancelled

        # Clean up finished games
        if channel_id in self.active_games and self.active_games[channel_id].game_over:
            del self.active_games[channel_id]

        self.logger.info(
            f"{interaction.user}가 {bet}코인으로 멀티플레이어 빙고 게임을 시작했습니다",
            extra={'guild_id': interaction.guild.id}
        )


async def setup(bot):
    await bot.add_cog(BingoCog(bot))