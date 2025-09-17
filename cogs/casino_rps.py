# cogs/casino_rps.py - Rock Paper Scissors game
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from typing import Optional, Dict

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    is_server_configured
)


class RPSChoice:
    """Represents a Rock Paper Scissors choice"""

    ROCK = "바위"
    PAPER = "보"
    SCISSORS = "가위"

    CHOICES = [ROCK, PAPER, SCISSORS]
    EMOJIS = {
        ROCK: "🪨",
        PAPER: "📄",
        SCISSORS: "✂️"
    }

    @classmethod
    def get_winner(cls, player_choice: str, bot_choice: str) -> str:
        """Determine the winner of RPS match"""
        if player_choice == bot_choice:
            return "tie"

        winning_combinations = {
            (cls.ROCK, cls.SCISSORS): "player",
            (cls.PAPER, cls.ROCK): "player",
            (cls.SCISSORS, cls.PAPER): "player"
        }

        if (player_choice, bot_choice) in winning_combinations:
            return "player"
        else:
            return "bot"


class RPSView(discord.ui.View):
    """Interactive Rock Paper Scissors game view"""

    def __init__(self, bot, user_id: int, guild_id: int, bet: int = 10):
        super().__init__(timeout=30)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.bet = bet
        self.player_choice = None
        self.bot_choice = None
        self.game_over = False
        self.result = None

    async def make_choice(self, interaction: discord.Interaction, choice: str):
        """Handle player choice"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 이 게임은 당신의 게임이 아닙니다!", ephemeral=True)
            return

        if self.game_over:
            await interaction.response.send_message("❌ 게임이 이미 끝났습니다!", ephemeral=True)
            return

        # Make choices
        self.player_choice = choice
        self.bot_choice = random.choice(RPSChoice.CHOICES)
        self.result = RPSChoice.get_winner(self.player_choice, self.bot_choice)
        self.game_over = True

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Handle coin rewards/losses
        coins_cog = self.bot.get_cog('CoinsCog')
        payout_msg = ""

        if coins_cog:
            if self.result == "player":
                # Win: get 20 coins (plus return bet)
                total_payout = 20 + self.bet
                success = await coins_cog.add_coins(
                    self.user_id,
                    self.guild_id,
                    total_payout,
                    "rps_win",
                    f"가위바위보 승리 - {self.player_choice} vs {self.bot_choice}"
                )
                if success:
                    payout_msg = f"\n💰 **+{total_payout:,}코인** (승리 보상 20 + 베팅금 {self.bet})"
                else:
                    payout_msg = f"\n❌ 코인 지급에 실패했습니다"
            elif self.result == "tie":
                # Tie: return bet
                success = await coins_cog.add_coins(
                    self.user_id,
                    self.guild_id,
                    self.bet,
                    "rps_tie",
                    f"가위바위보 무승부 - {self.player_choice} vs {self.bot_choice}"
                )
                if success:
                    payout_msg = f"\n🔄 **베팅금 {self.bet:,}코인 반환** (무승부)"
                else:
                    payout_msg = f"\n❌ 베팅금 반환에 실패했습니다"
            # Loss: no payout (bet already deducted)
            else:
                payout_msg = f"\n💸 **-{self.bet:,}코인** (패배)"

        # Create result embed
        embed = self.create_result_embed(payout_msg)
        await interaction.response.edit_message(embed=embed, view=self)

    def create_result_embed(self, payout_msg: str = "") -> discord.Embed:
        """Create the result embed"""
        player_emoji = RPSChoice.EMOJIS[self.player_choice]
        bot_emoji = RPSChoice.EMOJIS[self.bot_choice]

        if self.result == "player":
            title = "🎉 승리!"
            color = discord.Color.green()
            description = f"축하합니다! 봇을 이겼습니다!"
        elif self.result == "tie":
            title = "🤝 무승부!"
            color = discord.Color.yellow()
            description = f"둘 다 같은 것을 냈네요!"
        else:
            title = "😔 패배..."
            color = discord.Color.red()
            description = f"아쉽게도 봇이 이겼습니다."

        embed = discord.Embed(title=title, description=description, color=color)

        # Show the choices
        embed.add_field(
            name="🎮 선택 결과",
            value=f"**당신:** {player_emoji} {self.player_choice}\n**봇:** {bot_emoji} {self.bot_choice}",
            inline=False
        )

        # Add payout information
        if payout_msg:
            embed.add_field(name="💰 코인 정산", value=payout_msg, inline=False)

        return embed

    def create_game_embed(self) -> discord.Embed:
        """Create the initial game embed"""
        embed = discord.Embed(
            title="🎮 가위바위보",
            description=f"**베팅금:** {self.bet:,}코인\n**승리 보상:** 20코인\n\n아래 버튼 중 하나를 선택하세요!",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="📋 게임 규칙",
            value="• 🪨 바위는 ✂️ 가위를 이김\n• 📄 보는 🪨 바위를 이김\n• ✂️ 가위는 📄 보를 이김\n• 승리시 20코인 + 베팅금 반환\n• 무승부시 베팅금만 반환\n• 패배시 베팅금 손실",
            inline=False
        )

        return embed

    async def on_timeout(self):
        """Handle timeout"""
        if not self.game_over:
            # Refund bet on timeout
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(
                    self.user_id,
                    self.guild_id,
                    self.bet,
                    "rps_timeout",
                    "가위바위보 시간 초과 - 베팅금 반환"
                )

            for item in self.children:
                item.disabled = True

    @discord.ui.button(label="🪨 바위", style=discord.ButtonStyle.secondary, emoji="🪨")
    async def rock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.make_choice(interaction, RPSChoice.ROCK)

    @discord.ui.button(label="📄 보", style=discord.ButtonStyle.secondary, emoji="📄")
    async def paper_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.make_choice(interaction, RPSChoice.PAPER)

    @discord.ui.button(label="✂️ 가위", style=discord.ButtonStyle.secondary, emoji="✂️")
    async def scissors_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.make_choice(interaction, RPSChoice.SCISSORS)


class RPSCog(commands.Cog):
    """Rock Paper Scissors casino game"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("가위바위보")
        self.active_games: Dict[int, RPSView] = {}  # user_id -> game
        self.logger.info("가위바위보 게임 시스템이 초기화되었습니다.")

    async def validate_game(self, interaction: discord.Interaction, bet: int):
        """Validate game using casino base"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        return await casino_base.validate_game_start(
            interaction, "rps", bet, 10, 100
        )

    @app_commands.command(name="가위바위보", description="봇과 가위바위보를 플레이합니다 (승리시 20코인)")
    @app_commands.describe(bet="베팅 금액 (10-100코인, 기본값: 10)")
    async def rps(self, interaction: discord.Interaction, bet: int = 10):
        # Validate game using casino base
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "rps", bet, 10, 100
            )
            if not can_start:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

        user_id = interaction.user.id

        # Check if user already has an active game
        if user_id in self.active_games:
            existing_game = self.active_games[user_id]
            if not existing_game.game_over:
                await interaction.response.send_message("❌ 이미 진행 중인 가위바위보 게임이 있습니다!", ephemeral=True)
                return
            else:
                # Clean up finished game
                del self.active_games[user_id]

        # Validate the bet
        can_start, error_msg = await self.validate_game(interaction, bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # Deduct the bet
        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            await interaction.response.send_message("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)
            return

        success = await coins_cog.remove_coins(
            user_id,
            interaction.guild.id,
            bet,
            "rps_bet",
            f"가위바위보 베팅 ({bet}코인)"
        )

        if not success:
            await interaction.response.send_message("❌ 베팅 처리에 실패했습니다!", ephemeral=True)
            return

        # Create and start the game
        game_view = RPSView(self.bot, user_id, interaction.guild.id, bet)
        self.active_games[user_id] = game_view

        embed = game_view.create_game_embed()
        await interaction.response.send_message(embed=embed, view=game_view)

        self.logger.info(
            f"{interaction.user}가 {bet}코인으로 가위바위보 게임을 시작했습니다",
            extra={'guild_id': interaction.guild.id}
        )

        # Clean up after game ends or timeout
        await asyncio.sleep(35)  # Wait a bit longer than timeout
        if user_id in self.active_games:
            if self.active_games[user_id].game_over:
                del self.active_games[user_id]


async def setup(bot):
    await bot.add_cog(RPSCog(bot))