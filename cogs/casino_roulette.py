# cogs/casino_roulette.py - Updated with consistent embed layout
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    get_server_setting
)
from cogs.coins import check_user_casino_eligibility

class RouletteSimpleCog(commands.Cog):
    """Simple roulette game with single command - Multi-server aware with standardized embeds"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("룰렛")

        # Roulette setup
        self.red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

        self.logger.info("룰렛 게임 시스템이 초기화되었습니다.")

    def create_roulette_display(self, number, color, spinning=False):
        """Create standardized roulette display"""
        color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]

        if spinning:
            return f"🎡 **{color_emoji} {number}** 🎡\n\n🔄 **스피닝 중...**"
        else:
            return f"🎡 **{color_emoji} {number}** 🎡\n\n🎊 **결과 확정!**"

    async def validate_game(self, interaction: discord.Interaction, bet: int, min_bet: int, max_bet: int):
        """Validate game using casino base"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        return await casino_base.validate_game_start(
            interaction, "roulette", bet, min_bet, max_bet
        )

    @app_commands.command(name="룰렛", description="룰렛 게임 (색깔 또는 숫자)")
    @app_commands.describe(
        bet="베팅 금액",
        bet_type="베팅 타입",
        value="베팅할 값 (색깔: red/black, 숫자: 0-36)"
    )
    @app_commands.choices(bet_type=[
        app_commands.Choice(name="색깔 (2배)", value="color"),
        app_commands.Choice(name="숫자 (36배)", value="number")
    ])
    async def roulette(self, interaction: discord.Interaction, bet: int, bet_type: str, value: str):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        # Check for overdue loan restrictions
        restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
        if not restriction['allowed']:
            await interaction.response.send_message(restriction['message'], ephemeral=True)
            return

        # Validation based on bet type
        if bet_type == "color":
            if value.lower() not in ["red", "black"]:
                await interaction.response.send_message("색깔은 'red' 또는 'black'만 가능합니다!", ephemeral=True)
                return
            # Get server-specific limits for color bets
            min_bet = get_server_setting(interaction.guild.id, 'roulette_color_min_bet', 20)
            max_bet = get_server_setting(interaction.guild.id, 'roulette_color_max_bet', 200)
        else:  # number
            try:
                num_value = int(value)
                if not (0 <= num_value <= 36):
                    await interaction.response.send_message("숫자는 0-36 사이만 가능합니다!", ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message("유효한 숫자를 입력해주세요!", ephemeral=True)
                return
            # Get server-specific limits for number bets
            min_bet = get_server_setting(interaction.guild.id, 'roulette_number_min_bet', 10)
            max_bet = get_server_setting(interaction.guild.id, 'roulette_number_max_bet', 500)

        can_start, error_msg = await self.validate_game(interaction, bet, min_bet, max_bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        coins_cog = self.bot.get_cog('CoinsCog')
        if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, bet, "roulette_bet",
                                            "Roulette bet"):
            await interaction.response.send_message("베팅 처리 실패!", ephemeral=True)
            return

        await interaction.response.defer()

        # Display bet type nicely
        bet_display = f"🔴 **Red**" if value.lower() == "red" else f"⚫ **Black**" if value.lower() == "black" else f"🔢 **{value}**"
        multiplier_text = "2배 배당" if bet_type == "color" else "36배 배당"

        # Initial embed with betting info
        embed = discord.Embed(
            title="🎡 룰렛",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # STANDARDIZED FIELD 2: Betting Info (shown during setup)
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상:** {bet_display} ({multiplier_text})",
            inline=False
        )

        embed.set_footer(text=f"Server: {interaction.guild.name}")
        await interaction.edit_original_response(embed=embed)
        await asyncio.sleep(1)

        # Spinning animation
        for i in range(4):
            temp_num = random.randint(0, 36)
            temp_color = "green" if temp_num == 0 else ("red" if temp_num in self.red_numbers else "black")

            embed = discord.Embed(
                title="🎡 룰렛",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )

            # STANDARDIZED FIELD 1: Game Display (during spinning)
            embed.add_field(
                name="🎯 룰렛 결과",
                value=self.create_roulette_display(temp_num, temp_color, spinning=True),
                inline=False
            )

            # STANDARDIZED FIELD 2: Betting Info
            embed.add_field(
                name="💳 베팅 정보",
                value=f"💰 **베팅 금액:** {bet:,} 코인\n🎡 **상태:** 스피닝 중... `{i + 1}/4`",
                inline=False
            )

            embed.set_footer(text=f"Server: {interaction.guild.name}")
            await interaction.edit_original_response(embed=embed)
            await asyncio.sleep(0.6)

        # Final result
        winning_number = random.randint(0, 36)
        winning_color = "green" if winning_number == 0 else ("red" if winning_number in self.red_numbers else "black")

        won = False
        payout = 0

        # Get server-specific payout multipliers
        color_multiplier = get_server_setting(interaction.guild.id, 'roulette_color_multiplier', 2)
        number_multiplier = get_server_setting(interaction.guild.id, 'roulette_number_multiplier', 36)

        if bet_type == "color" and value.lower() == winning_color:
            won = True
            payout = bet * color_multiplier
        elif bet_type == "number" and int(value) == winning_number:
            won = True
            payout = bet * number_multiplier

        if won:
            await coins_cog.add_coins(interaction.user.id, interaction.guild.id, payout, "roulette_win",
                                      f"Roulette win: {winning_number}")

        # Standardized title and color logic
        if won:
            if bet_type == "number":
                title = "🎡 룰렛 - 🔥 잭팟!"
                color = discord.Color.gold()
            else:
                title = "🎡 룰렛 - 🎉 승리!"
                color = discord.Color.green()
        else:
            title = "🎡 룰렛 - 😞 패배!"
            color = discord.Color.red()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        embed.add_field(
            name="🎯 룰렛 결과",
            value=self.create_roulette_display(winning_number, winning_color),
            inline=False
        )

        # STANDARDIZED FIELD 2: Betting Info
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상:** {bet_display}",
            inline=False
        )

        # STANDARDIZED FIELD 3: Game Results
        if won:
            if bet_type == "color":
                result_text = f"🎯 **색깔 적중!** {color_multiplier}배 배당"
            else:
                result_text = f"🔥 **숫자 적중!** {number_multiplier}배 배당"
            profit = payout - bet
            result_info = f"{result_text}\n\n💰 **수익:** {payout:,} 코인\n📈 **순이익:** +{profit:,} 코인"
        else:
            winning_display = f"🟢 **{winning_number}**" if winning_color == "green" else f"🔴 **{winning_number}**" if winning_color == "red" else f"⚫ **{winning_number}**"
            result_text = f"❌ **예상 실패!** (결과: {winning_display})"
            result_info = f"{result_text}\n\n💸 **손실:** {bet:,} 코인"

        embed.add_field(name="📊 게임 결과", value=result_info, inline=False)

        # STANDARDIZED FIELD 4: Balance Info
        new_balance = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)
        embed.add_field(name="", value=f"🏦 **현재 잔액:** {new_balance:,} 코인", inline=False)

        # Standardized footer
        embed.set_footer(text=f"플레이어: {interaction.user.display_name} | Server: {interaction.guild.name}")

        await interaction.edit_original_response(embed=embed)

        self.logger.info(
            f"{interaction.user}가 룰렛에서 {bet} 코인 {'승리' if won else '패배'} (베팅: {bet_type}={value}, 결과: {winning_number})",
            extra={'guild_id': interaction.guild.id}
        )


async def setup(bot):
    await bot.add_cog(RouletteSimpleCog(bot))