# cogs/casino_rps.py - Rock Paper Scissors game (FIXED)
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from typing import Optional, Dict

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
        self.bet = bet  # Always 0 for free play
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
            # Make choices
            self.player_choice = choice
            self.bot_choice = random.choice(RPSChoice.CHOICES)
            self.result = RPSChoice.get_winner(self.player_choice, self.bot_choice)
            self.game_over = True

            # Disable all buttons
            for item in self.children:
                item.disabled = True

            # Handle coin rewards (no bet to deduct since it's free)
            coins_cog = self.bot.get_cog('CoinsCog')
            payout_msg = ""

            if coins_cog:
                if self.result == "player":
                    # Win: get 15 coins
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
                    # Tie: get 5 coins as consolation
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
                # Loss: no reward but no loss either
                else:
                    payout_msg = f"\n😔 **보상 없음** (다음엔 이길 수 있어요!)"

            # Create result embed
            embed = self.create_result_embed(payout_msg)
            await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            # Log the error
            logger = get_logger("가위바위보")
            logger.error(f"Error in RPS choice handling: {e}", exc_info=True)

            # Send error message
            try:
                await interaction.response.send_message("❌ 게임 처리 중 오류가 발생했습니다!", ephemeral=True)
            except:
                # If response already sent, try followup
                try:
                    await interaction.followup.send("❌ 게임 처리 중 오류가 발생했습니다!", ephemeral=True)
                except:
                    pass

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
            embed.add_field(name="💰 코인 보상", value=payout_msg, inline=False)

        # Add cooldown reminder
        embed.add_field(
            name="⏰ 쿨다운",
            value="2분 후에 다시 플레이할 수 있습니다!",
            inline=False
        )

        embed.set_footer(
            text=f"Server: {self.bot.get_guild(self.guild_id).name if self.bot.get_guild(self.guild_id) else 'Unknown'}")
        return embed

    def create_game_embed(self) -> discord.Embed:
        """Create the initial game embed"""
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
        """Handle timeout - no refund needed since it's free"""
        if not self.game_over:
            # Disable all buttons
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

    @app_commands.command(name="가위바위보", description="봇과 가위바위보를 플레이합니다 (무료, 승리시 15코인)")
    async def rps(self, interaction: discord.Interaction):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        # Check cooldown (2 minutes)
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            if not casino_base.check_game_cooldown(interaction.user.id, "rps"):
                await interaction.response.send_message("⏳ 가위바위보는 2분마다 한 번씩만 플레이할 수 있습니다!", ephemeral=True)
                return

            # Check channel restriction
            allowed, channel_msg = casino_base.check_channel_restriction(
                interaction.guild.id, "rps", interaction.channel.id
            )
            if not allowed:
                await interaction.response.send_message(channel_msg, ephemeral=True)
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

        # No bet required - this is a free game for earning coins
        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            await interaction.response.send_message("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)
            return

        # Create and start the game (bet = 0 for free play)
        game_view = RPSView(self.bot, user_id, interaction.guild.id, 0)
        self.active_games[user_id] = game_view

        embed = game_view.create_game_embed()
        await interaction.response.send_message(embed=embed, view=game_view)

        self.logger.info(
            f"{interaction.user}가 무료 가위바위보 게임을 시작했습니다",
            extra={'guild_id': interaction.guild.id}
        )

        # Clean up after game ends or timeout
        await asyncio.sleep(35)  # Wait a bit longer than timeout
        if user_id in self.active_games:
            if self.active_games[user_id].game_over:
                del self.active_games[user_id]


async def setup(bot):
    await bot.add_cog(RPSCog(bot))