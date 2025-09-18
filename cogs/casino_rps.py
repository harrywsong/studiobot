import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from typing import Optional, Dict
import time  # Import the time module

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    get_server_setting
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

    def __init__(self, bot, user_id: int, guild_id: int, bet: int = 0):
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

        try:
            self.player_choice = choice
            self.bot_choice = random.choice(RPSChoice.CHOICES)
            self.result = RPSChoice.get_winner(self.player_choice, self.bot_choice)
            self.game_over = True

            for item in self.children:
                item.disabled = True

            coins_cog = self.bot.get_cog('CoinsCog')
            payout_msg = ""

            if coins_cog:
                if self.result == "player":
                    success = await coins_cog.add_coins(
                        self.user_id,
                        self.guild_id,
                        15,
                        "rps_win",
                        f"가위바위보 승리 - {self.player_choice} vs {self.bot_choice}"
                    )
                    if success:
                        payout_msg = f"\n💰 **+15코인** (승리 보상!)"
                    else:
                        payout_msg = f"\n❌ 코인 지급에 실패했습니다"
                elif self.result == "tie":
                    success = await coins_cog.add_coins(
                        self.user_id,
                        self.guild_id,
                        5,
                        "rps_tie",
                        f"가위바위보 무승부 - {self.player_choice} vs {self.bot_choice}"
                    )
                    if success:
                        payout_msg = f"\n🤝 **+5코인** (무승부 위로금)"
                    else:
                        payout_msg = f"\n❌ 코인 지급에 실패했습니다"
                else:
                    payout_msg = f"\n😔 **보상 없음** (다음엔 이길 수 있어요!)"

            embed = self.create_result_embed(payout_msg)
            await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            logger = get_logger("가위바위보")
            logger.error(f"Error in RPS choice handling: {e}", exc_info=True)
            try:
                await interaction.response.send_message("❌ 게임 처리 중 오류가 발생했습니다!", ephemeral=True)
            except:
                try:
                    await interaction.followup.send("❌ 게임 처리 중 오류가 발생했습니다!", ephemeral=True)
                except:
                    pass

    def create_result_embed(self, payout_msg: str = "") -> discord.Embed:
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
        embed.add_field(
            name="🎮 선택 결과",
            value=f"**당신:** {player_emoji} {self.player_choice}\n**봇:** {bot_emoji} {self.bot_choice}",
            inline=False
        )
        if payout_msg:
            embed.add_field(name="💰 코인 보상", value=payout_msg, inline=False)
        embed.add_field(
            name="⏰ 쿨다운",
            value="2분 후에 다시 플레이할 수 있습니다!",
            inline=False
        )
        embed.set_footer(
            text=f"Server: {self.bot.get_guild(self.guild_id).name if self.bot.get_guild(self.guild_id) else 'Unknown'}")
        return embed

    def create_game_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎮 가위바위보 (무료!)",
            description=f"봇과 가위바위보를 해서 코인을 얻어보세요!\n\n아래 버튼 중 하나를 선택하세요!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📋 게임 규칙",
            value="• 🪨 바위는 ✂️ 가위를 이김\n• 📄 보는 🪨 바위를 이김\n• ✂️ 가위는 📄 보를 이김\n\n**보상:**\n• 승리: 15코인 💰\n• 무승부: 5코인 🤝\n• 패배: 0코인 😔\n\n**쿨다운:** 2분",
            inline=False
        )
        embed.set_footer(
            text=f"Server: {self.bot.get_guild(self.guild_id).name if self.bot.get_guild(self.guild_id) else 'Unknown'}")
        return embed

    async def on_timeout(self):
        if not self.game_over:
            for item in self.children:
                item.disabled = True


class RPSCog(commands.Cog):
    """Rock Paper Scissors casino game"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("가위바위보")
        self.active_games: Dict[int, RPSView] = {}
        self.cooldowns: Dict[int, float] = {}  # Add a dictionary for cooldowns
        self.cooldown_time = 120  # 120 seconds = 2 minutes
        self.logger.info("가위바위보 게임 시스템이 초기화되었습니다.")

    @app_commands.command(name="가위바위보", description="봇과 가위바위보를 플레이합니다 (무료, 승리시 15코인)")
    async def rps(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = time.time()

        # Check cooldown
        if user_id in self.cooldowns:
            last_played = self.cooldowns[user_id]
            time_elapsed = now - last_played
            if time_elapsed < self.cooldown_time:
                remaining_time = self.cooldown_time - time_elapsed
                minutes = int(remaining_time // 60)
                seconds = int(remaining_time % 60)
                await interaction.response.send_message(f"❌ 가위바위보 쿨다운 중입니다! **{minutes}분 {seconds}초** 후에 다시 시도해주세요.",
                                                        ephemeral=True)
                return

        # Check for active game
        if user_id in self.active_games and not self.active_games[user_id].game_over:
            await interaction.response.send_message("❌ 이미 진행 중인 가위바위보 게임이 있습니다!", ephemeral=True)
            return

        # Start a new game
        self.cooldowns[user_id] = now  # Set the new cooldown timestamp

        game_view = RPSView(self.bot, user_id, interaction.guild.id, 0)
        self.active_games[user_id] = game_view

        embed = game_view.create_game_embed()
        await interaction.response.send_message(embed=embed, view=game_view)

        self.logger.info(
            f"{interaction.user}가 무료 가위바위보 게임을 시작했습니다",
            extra={'guild_id': interaction.guild.id}
        )

        # Clean up after game ends or timeout
        await game_view.wait()  # Wait for the view to finish
        if user_id in self.active_games:
            del self.active_games[user_id]


async def setup(bot):
    await bot.add_cog(RPSCog(bot))