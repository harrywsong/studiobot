# cogs/casino_tictactoe.py - Tic Tac Toe PvP game (FIXED)
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    get_server_setting
)


class TicTacToeBoard:
    """Represents a Tic Tac Toe game board"""

    def __init__(self):
        # 3x3 board, 0=empty, 1=X, 2=O
        self.board = [[0 for _ in range(3)] for _ in range(3)]
        self.moves = 0

    def make_move(self, row: int, col: int, player: int) -> bool:
        """Make a move on the board. Returns True if valid move."""
        if 0 <= row < 3 and 0 <= col < 3 and self.board[row][col] == 0:
            self.board[row][col] = player
            self.moves += 1
            return True
        return False

    def check_winner(self) -> int:
        """Check for winner. Returns 1 for X, 2 for O, 0 for no winner"""
        # Check rows
        for row in self.board:
            if row[0] == row[1] == row[2] != 0:
                return row[0]

        # Check columns
        for col in range(3):
            if self.board[0][col] == self.board[1][col] == self.board[2][col] != 0:
                return self.board[0][col]

        # Check diagonals
        if self.board[0][0] == self.board[1][1] == self.board[2][2] != 0:
            return self.board[0][0]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != 0:
            return self.board[0][2]

        return 0

    def is_full(self) -> bool:
        """Check if board is full"""
        return self.moves >= 9

    def get_display(self) -> str:
        """Get board display string"""
        symbols = {0: "⬜", 1: "❌", 2: "⭕"}
        lines = []
        for row in self.board:
            line = "".join(symbols[cell] for cell in row)
            lines.append(line)
        return "\n".join(lines)


class TicTacToeView(discord.ui.View):
    """Interactive Tic Tac Toe game view"""

    def __init__(self, bot, player1_id: int, player2_id: int, guild_id: int, bet: int):
        super().__init__(timeout=300)  # 5 minutes
        self.bot = bot
        self.player1_id = player1_id  # X player
        self.player2_id = player2_id  # O player
        self.guild_id = guild_id
        self.bet = bet
        self.board = TicTacToeBoard()
        self.current_turn = 1  # 1 = X (player1), 2 = O (player2)
        self.game_over = False
        self.winner = None
        self.is_tie = False

        # Create 3x3 grid of buttons
        for row in range(3):
            for col in range(3):
                button = TicTacToeButton(row, col)
                self.add_item(button)

    def get_current_player_id(self) -> int:
        """Get current player's user ID"""
        return self.player1_id if self.current_turn == 1 else self.player2_id

    def get_player_name(self, user_id: int) -> str:
        """Get player display name"""
        if user_id == self.player1_id:
            return "플레이어 1 (❌)"
        else:
            return "플레이어 2 (⭕)"

    async def make_move(self, interaction: discord.Interaction, row: int, col: int):
        """Handle a player move"""
        # Defer the response to avoid timeout
        await interaction.response.defer()

        if self.game_over:
            await interaction.followup.send_message("❌ 게임이 이미 끝났습니다!", ephemeral=True)
            return

        if interaction.user.id != self.get_current_player_id():
            current_player = self.get_player_name(self.get_current_player_id())
            await interaction.followup.send_message(f"❌ 지금은 {current_player}의 차례입니다!", ephemeral=True)
            return

        # Try to make the move
        if not self.board.make_move(row, col, self.current_turn):
            await interaction.followup.send_message("❌ 이미 선택된 칸입니다!", ephemeral=True)
            return

        # Update button to show the move
        for item in self.children:
            if hasattr(item, 'row') and item.row == row and item.col == col:
                item.label = "❌" if self.current_turn == 1 else "⭕"
                item.disabled = True
                break

        # Check for winner
        winner = self.board.check_winner()
        if winner:
            self.winner = winner
            self.game_over = True
            await self.end_game(interaction)
        elif self.board.is_full():
            self.is_tie = True
            self.game_over = True
            await self.end_game(interaction)
        else:
            # Switch turns
            self.current_turn = 2 if self.current_turn == 1 else 1

            embed = self.create_game_embed()
            await interaction.followup.edit_message(message=interaction.message, embed=embed, view=self)

    async def end_game(self, interaction: discord.Interaction):
        """End the game and handle payouts"""
        # Disable all buttons
        for item in self.children:
            item.disabled = True

        coins_cog = self.bot.get_cog('CoinsCog')

        if self.winner and coins_cog:
            # Determine winner
            winner_id = self.player1_id if self.winner == 1 else self.player2_id
            loser_id = self.player2_id if self.winner == 1 else self.player1_id

            # Pay winner (bet * 2)
            payout = self.bet * 2
            await coins_cog.add_coins(
                winner_id,
                self.guild_id,
                payout,
                "tictactoe_win",
                f"틱택토 승리 vs {self.bot.get_user(loser_id).display_name}"
            )
        elif self.is_tie and coins_cog:
            # Refund both players on tie
            await coins_cog.add_coins(
                self.player1_id,
                self.guild_id,
                self.bet,
                "tictactoe_tie",
                "틱택토 무승부 - 베팅금 반환"
            )
            await coins_cog.add_coins(
                self.player2_id,
                self.guild_id,
                self.bet,
                "tictactoe_tie",
                "틱택토 무승부 - 베팅금 반환"
            )

        embed = self.create_game_embed()
        await interaction.followup.edit_message(message=interaction.message, embed=embed, view=self)

    def create_game_embed(self) -> discord.Embed:
        """Create game status embed"""
        if self.game_over:
            if self.winner:
                winner_name = self.get_player_name(
                    self.player1_id if self.winner == 1 else self.player2_id
                )
                title = f"🎉 {winner_name} 승리!"
                color = discord.Color.green()
                description = f"**상금:** {self.bet * 2:,}코인"
            else:
                title = "🤝 무승부!"
                color = discord.Color.yellow()
                description = "양 플레이어 모두 베팅금을 돌려받습니다."
        else:
            current_player = self.get_player_name(self.get_current_player_id())
            title = "🎮 틱택토 게임"
            color = discord.Color.blue()
            description = f"**현재 차례:** {current_player}\n**베팅금:** {self.bet:,}코인"

        embed = discord.Embed(title=title, description=description, color=color)

        embed.add_field(
            name="🎯 게임판",
            value=self.board.get_display(),
            inline=False
        )

        if not self.game_over:
            embed.add_field(
                name="ℹ️ 플레이어",
                value=f"❌ <@{self.player1_id}>\n⭕ <@{self.player2_id}>",
                inline=True
            )
            embed.add_field(
                name="📋 규칙",
                value="• 3개를 한 줄로 만들면 승리\n• 승자가 모든 베팅금 획득\n• 무승부시 베팅금 반환",
                inline=True
            )

        embed.set_footer(
            text=f"Server: {self.bot.get_guild(self.guild_id).name if self.bot.get_guild(self.guild_id) else 'Unknown'}")
        return embed

    async def on_timeout(self):
        """Handle game timeout"""
        if not self.game_over:
            # Refund both players
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(
                    self.player1_id,
                    self.guild_id,
                    self.bet,
                    "tictactoe_timeout",
                    "틱택토 시간 초과 - 베팅금 반환"
                )
                await coins_cog.add_coins(
                    self.player2_id,
                    self.guild_id,
                    self.bet,
                    "tictactoe_timeout",
                    "틱택토 시간 초과 - 베팅금 반환"
                )


class TicTacToeButton(discord.ui.Button):
    """Individual button for Tic Tac Toe grid"""

    def __init__(self, row: int, col: int):
        self.row = row
        self.col = col
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="⬜",
            row=row  # Discord UI rows
        )

    async def callback(self, interaction: discord.Interaction):
        await self.view.make_move(interaction, self.row, self.col)


class TicTacToeCog(commands.Cog):
    """Tic Tac Toe PvP game"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("틱택토")
        self.active_games: Dict[int, TicTacToeView] = {}  # channel_id -> game
        self.pending_challenges: Dict[int, dict] = {}  # challenger_id -> challenge_info
        self.logger.info("틱택토 게임 시스템이 초기화되었습니다.")

    @app_commands.command(name="틱택토", description="다른 플레이어와 틱택토 대전을 합니다")
    @app_commands.describe(
        opponent="대전할 상대방",
        bet="베팅 금액 (10-500코인)"
    )
    async def tictactoe(
            self,
            interaction: discord.Interaction,
            opponent: discord.Member,
            bet: int = 50
    ):
        # Validate game using casino base
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "tictactoe", bet, 10, 500
            )
            if not can_start:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

        # Basic validation
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("❌ 자기 자신과는 대전할 수 없습니다!", ephemeral=True)
            return

        if opponent.bot:
            await interaction.response.send_message("❌ 봇과는 대전할 수 없습니다!", ephemeral=True)
            return

        channel_id = interaction.channel.id

        # Check if channel has active game
        if channel_id in self.active_games:
            if not self.active_games[channel_id].game_over:
                await interaction.response.send_message("❌ 이 채널에서 이미 틱택토 게임이 진행 중입니다!", ephemeral=True)
                return
            else:
                del self.active_games[channel_id]

        # Check if opponent can afford bet
        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            await interaction.response.send_message("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)
            return

        opponent_balance = await coins_cog.get_balance(opponent.id, interaction.guild.id)
        if opponent_balance < bet:
            await interaction.response.send_message(
                f"❌ {opponent.display_name}님의 코인이 부족합니다! (필요: {bet:,}, 보유: {opponent_balance:,})", ephemeral=True)
            return

        # Create challenge
        challenge_embed = discord.Embed(
            title="🎮 틱택토 대전 신청",
            description=f"**신청자:** {interaction.user.mention}\n**상대:** {opponent.mention}\n**베팅금:** {bet:,}코인\n\n{opponent.mention}님, 대전을 수락하시겠습니까?",
            color=discord.Color.blue()
        )

        challenge_view = TicTacToeChallenge(self, interaction.user.id, opponent.id, bet, channel_id)
        await interaction.response.send_message(embed=challenge_embed, view=challenge_view)

        self.logger.info(
            f"{interaction.user}가 {opponent}에게 {bet}코인으로 틱택토 대전을 신청했습니다",
            extra={'guild_id': interaction.guild.id}
        )


class TicTacToeChallenge(discord.ui.View):
    """Challenge acceptance view"""

    def __init__(self, cog, challenger_id: int, opponent_id: int, bet: int, channel_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.bet = bet
        self.channel_id = channel_id

    @discord.ui.button(label="✅ 수락", style=discord.ButtonStyle.green)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("❌ 대전 상대방만 수락할 수 있습니다!", ephemeral=True)
            return

        # Defer the response to avoid timeout
        await interaction.response.defer()

        # Deduct bets from both players
        coins_cog = self.cog.bot.get_cog('CoinsCog')

        # Deduct from challenger
        success1 = await coins_cog.remove_coins(
            self.challenger_id,
            interaction.guild.id,
            self.bet,
            "tictactoe_bet",
            f"틱택토 베팅 vs {interaction.user.display_name}"
        )

        # Deduct from opponent
        success2 = await coins_cog.remove_coins(
            self.opponent_id,
            interaction.guild.id,
            self.bet,
            "tictactoe_bet",
            f"틱택토 베팅 vs <@{self.challenger_id}>"
        )

        if not (success1 and success2):
            # Refund if either failed
            if success1:
                await coins_cog.add_coins(self.challenger_id, interaction.guild.id, self.bet, "tictactoe_refund",
                                          "틱택토 베팅 환불")
            await interaction.followup.send_message("❌ 베팅 처리에 실패했습니다!", ephemeral=True)
            return

        # Start the game
        game_view = TicTacToeView(
            self.cog.bot,
            self.challenger_id,
            self.opponent_id,
            interaction.guild.id,
            self.bet
        )

        self.cog.active_games[self.channel_id] = game_view

        embed = game_view.create_game_embed()
        # Use followup.edit_message after deferring
        await interaction.followup.edit_message(message=interaction.message, embed=embed, view=game_view)

        # Disable this view
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.red)
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("❌ 대전 상대방만 거절할 수 있습니다!", ephemeral=True)
            return

        # Defer the response to avoid timeout
        await interaction.response.defer()

        embed = discord.Embed(
            title="❌ 틱택토 대전 거절됨",
            description=f"{interaction.user.mention}님이 대전을 거절했습니다.",
            color=discord.Color.red()
        )

        # Use followup.edit_message after deferring
        await interaction.followup.edit_message(message=interaction.message, embed=embed, view=None)

    async def on_timeout(self):
        """Handle challenge timeout"""
        embed = discord.Embed(
            title="⏰ 틱택토 대전 시간 초과",
            description="대전 신청이 시간 초과되었습니다.",
            color=discord.Color.orange()
        )


async def setup(bot):
    await bot.add_cog(TicTacToeCog(bot))
