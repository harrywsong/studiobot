# cogs/casino_rps.py - Rock Paper Scissors game with standardized embeds
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from datetime import datetime, timedelta
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
    """Interactive Rock Paper Scissors game view with standardized embeds"""

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

    def create_rps_display(self):
        """Create standardized RPS display"""
        if not self.player_choice or not self.bot_choice:
            return "🎲 **선택을 기다리는 중...**\n\n아래 버튼 중 하나를 선택하세요!"

        player_emoji = RPSChoice.EMOJIS[self.player_choice]
        bot_emoji = RPSChoice.EMOJIS[self.bot_choice]

        display = f"🎯 **대결 결과**\n\n"
        display += f"**당신:** {player_emoji} {self.player_choice}\n"
        display += f"**봇:** {bot_emoji} {self.bot_choice}\n\n"

        if self.result == "player":
            display += "🎉 **승리!**"
        elif self.result == "tie":
            display += "🤝 **무승부!**"
        else:
            display += "😞 **패배...**"

        return display

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
            payout = 0

            if coins_cog:
                if self.result == "player":
                    # Win: get 20 coins
                    payout = 20
                    success = await coins_cog.add_coins(
                        self.user_id,
                        self.guild_id,
                        payout,
                        "rps_win",
                        f"가위바위보 승리 - {self.player_choice} vs {self.bot_choice}"
                    )
                elif self.result == "tie":
                    # Tie: get 10 coins as consolation
                    payout = 10
                    success = await coins_cog.add_coins(
                        self.user_id,
                        self.guild_id,
                        payout,
                        "rps_tie",
                        f"가위바위보 무승부 - {self.player_choice} vs {self.bot_choice}"
                    )
                # Loss: no reward but no loss either

            # Create result embed
            embed = self.create_result_embed(payout)
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

    def create_result_embed(self, payout: int = 0) -> discord.Embed:
        """Create the result embed with standardized format"""
        if self.result == "player":
            title = "🎮 가위바위보 - 🎉 승리!"
            color = discord.Color.green()
        elif self.result == "tie":
            title = "🎮 가위바위보 - 🤝 무승부!"
            color = discord.Color.yellow()
        else:
            title = "🎮 가위바위보 - 😞 패배!"
            color = discord.Color.red()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        embed.add_field(
            name="🎯 게임 결과",
            value=self.create_rps_display(),
            inline=False
        )

        # STANDARDIZED FIELD 2: Betting Info
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** 무료!\n🎲 **상태:** 게임 완료",
            inline=False
        )

        # STANDARDIZED FIELD 3: Game Results
        if self.result == "player":
            result_text = f"🎯 **승리!** 봇을 이겼습니다!"
            result_info = f"{result_text}\n\n💰 **획득:** {payout:,}코인\n📈 **순이익:** +{payout:,}코인"
        elif self.result == "tie":
            result_text = f"🤝 **무승부!** 둘 다 같은 것을 냈네요!"
            result_info = f"{result_text}\n\n💰 **위로금:** {payout:,}코인"
        else:
            result_text = f"😞 **패배...** 아쉽게도 봇이 이겼습니다"
            result_info = f"{result_text}\n\n💸 **손실:** 0코인 (무료 게임!)"

        embed.add_field(name="📊 게임 결과", value=result_info, inline=False)

        # STANDARDIZED FIELD 4: Balance Info
        embed.add_field(
            name="⏰ 쿨다운",
            value="2분 후에 다시 플레이할 수 있습니다!",
            inline=False
        )

        # Standardized footer
        embed.set_footer(
            text=f"플레이어: {self.bot.get_user(self.user_id).display_name if self.bot.get_user(self.user_id) else 'Unknown'} | Server: {self.bot.get_guild(self.guild_id).name if self.bot.get_guild(self.guild_id) else 'Unknown'}")

        return embed

    def create_game_embed(self) -> discord.Embed:
        """Create the initial game embed with standardized format"""
        title = "🎮 가위바위보"
        color = discord.Color.blue()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        embed.add_field(
            name="🎯 게임 상태",
            value=self.create_rps_display(),
            inline=False
        )

        # STANDARDIZED FIELD 2: Betting Info
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** 무료!\n🎲 **상태:** 선택 대기 중",
            inline=False
        )

        # Game rules
        embed.add_field(
            name="📋 게임 규칙",
            value="• 🪨 바위는 ✂️ 가위를 이김\n• 📄 보는 🪨 바위를 이김\n• ✂️ 가위는 📄 보를 이김\n\n**보상:**\n• 승리: 20코인 💰\n• 무승부: 10코인 🤝\n• 패배: 0코인 😞\n\n**쿨다운:** 2분",
            inline=False
        )

        # Standardized footer
        embed.set_footer(
            text=f"플레이어: {self.bot.get_user(self.user_id).display_name if self.bot.get_user(self.user_id) else 'Unknown'} | Server: {self.bot.get_guild(self.guild_id).name if self.bot.get_guild(self.guild_id) else 'Unknown'}")

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
    """Rock Paper Scissors casino game with standardized embeds"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("가위바위보")
        # Proper cooldown tracking with timestamps per user
        self.user_cooldowns: Dict[int, datetime] = {}  # user_id -> last_play_time
        self.cooldown_duration = timedelta(minutes=2)  # 2 minute cooldown
        self.logger.info("가위바위보 게임 시스템이 초기화되었습니다.")

    def is_on_cooldown(self, user_id: int) -> tuple[bool, int]:
        """Check if user is on cooldown. Returns (is_on_cooldown, seconds_remaining)"""
        if user_id not in self.user_cooldowns:
            return False, 0

        time_since_last = datetime.now() - self.user_cooldowns[user_id]
        if time_since_last < self.cooldown_duration:
            seconds_remaining = int((self.cooldown_duration - time_since_last).total_seconds())
            return True, seconds_remaining

        return False, 0

    def set_cooldown(self, user_id: int):
        """Set cooldown for user"""
        self.user_cooldowns[user_id] = datetime.now()

    @app_commands.command(name="가위바위보", description="봇과 가위바위보를 플레이합니다 (무료, 승리시 20코인)")
    async def rps(self, interaction: discord.Interaction):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            await interaction.response.send_message("❌ 카지노 시스템을 찾을 수 없습니다!", ephemeral=True)
            return

        # Check our own cooldown first before casino base validation
        on_cooldown, seconds_remaining = self.is_on_cooldown(interaction.user.id)
        if on_cooldown:
            minutes = seconds_remaining // 60
            seconds = seconds_remaining % 60
            await interaction.response.send_message(
                f"⏰ 아직 쿨다운 중입니다! {minutes}분 {seconds}초 후에 다시 시도해주세요.",
                ephemeral=True
            )
            return

        # Use the centralized validation method from CasinoBaseCog
        # Explicitly set min_bet=0 to allow this free game to pass validation
        can_start, error_msg = await casino_base.validate_game_start(interaction, "rps", bet=0, min_bet=0)

        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        user_id = interaction.user.id

        # No bet required - this is a free game for earning coins
        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            await interaction.response.send_message("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)
            return

        # Set cooldown immediately when game starts
        self.set_cooldown(user_id)

        # Create and start the game (bet = 0 for free play)
        game_view = RPSView(self.bot, user_id, interaction.guild.id, 0)

        embed = game_view.create_game_embed()
        await interaction.response.send_message(embed=embed, view=game_view)

        self.logger.info(
            f"{interaction.user}가 무료 가위바위보 게임을 시작했습니다",
            extra={'guild_id': interaction.guild.id}
        )


async def setup(bot):
    await bot.add_cog(RPSCog(bot))