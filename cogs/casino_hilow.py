# =============================================================================
# cogs/casino_hilow.py - Updated with consistent embed layout
# =============================================================================

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

class HiLowCog(commands.Cog):
    """Hi-Low dice game - Multi-server aware with standardized embeds"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("하이로우")
        self.logger.info("하이로우 게임 시스템이 초기화되었습니다.")

    def get_dice_visual(self, value):
        """Get visual representation of dice value"""
        dice_visuals = {
            1: "🔴[1]",
            2: "🟠[2]",
            3: "🟡[3]",
            4: "🟢[4]",
            5: "🔵[5]",
            6: "🟣[6]"
        }
        return dice_visuals.get(value, f"🎲[{value}]")

    def create_dice_display(self, die1, die2, total, rolling=False):
        """Create standardized visual dice display with total analysis"""
        dice_display = f"{self.get_dice_visual(die1)} {self.get_dice_visual(die2)}"

        if rolling:
            return f"{dice_display}\n\n🔄 **굴리는 중...**"

        # Add visual indicator for hi/low
        if total > 7:
            indicator = "📈 HIGH"
            color_emoji = "🔥"
        elif total < 7:
            indicator = "📉 LOW"
            color_emoji = "❄️"
        else:
            indicator = "🎯 SEVEN"
            color_emoji = "⚡"

        return f"{dice_display}\n\n🎯 **합계: {total}** {color_emoji}\n{indicator}"

    async def validate_game(self, interaction: discord.Interaction, bet: int):
        """Validate game using casino base"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        # Get server-specific limits
        min_bet = get_server_setting(interaction.guild.id, 'hilow_min_bet', 10)
        max_bet = get_server_setting(interaction.guild.id, 'hilow_max_bet', 200)

        return await casino_base.validate_game_start(
            interaction, "hilow", bet, min_bet, max_bet
        )

    @app_commands.command(name="하이로우", description="7을 기준으로 높음/낮음 맞히기")
    @app_commands.describe(
        bet="베팅 금액",
        choice="7보다 높을지(high) 낮을지(low)"
    )
    @app_commands.choices(choice=[
        app_commands.Choice(name="📈 높음 (8-12)", value="high"),
        app_commands.Choice(name="📉 낮음 (2-6)", value="low")
    ])
    async def hilow(self, interaction: discord.Interaction, bet: int, choice: str):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        # Check for overdue loan restrictions
        restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
        if not restriction['allowed']:
            await interaction.response.send_message(restriction['message'], ephemeral=True)
            return

        can_start, error_msg = await self.validate_game(interaction, bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        coins_cog = self.bot.get_cog('CoinsCog')
        if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, bet, "hilow_bet", "Hi-Low bet"):
            await interaction.response.send_message("베팅 처리 실패!", ephemeral=True)
            return

        await interaction.response.defer()

        choice_display = {"high": "📈 높음 (8-12)", "low": "📉 낮음 (2-6)"}

        # Initial embed with betting info
        embed = discord.Embed(
            title="🎲 하이로우",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # STANDARDIZED FIELD 2: Betting Info (shown during rolling)
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상:** {choice_display[choice]}\n⚡ **기준점:** 7",
            inline=False
        )

        embed.set_footer(text=f"Server: {interaction.guild.name}")
        await interaction.edit_original_response(embed=embed)
        await asyncio.sleep(1.5)

        # Rolling animation
        for i in range(4):
            temp_die1 = random.randint(1, 6)
            temp_die2 = random.randint(1, 6)

            embed = discord.Embed(
                title="🎲 하이로우",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )

            # STANDARDIZED FIELD 1: Game Display (during rolling)
            embed.add_field(
                name="🎯 주사위 결과",
                value=self.create_dice_display(temp_die1, temp_die2, 0, rolling=True),
                inline=False
            )

            # STANDARDIZED FIELD 2: Betting Info
            embed.add_field(
                name="💳 베팅 정보",
                value=f"💰 **베팅 금액:** {bet:,} 코인\n🎲 **상태:** 굴리는 중... `{i + 1}/4`",
                inline=False
            )

            embed.set_footer(text=f"Server: {interaction.guild.name}")
            await interaction.edit_original_response(embed=embed)
            await asyncio.sleep(0.7)

        # Final result
        die1 = random.randint(1, 6)
        die2 = random.randint(1, 6)
        total = die1 + die2

        won = False
        result_type = ""
        payout = 0

        if choice == "high" and total > 7:
            won = True
            result_type = "win"
        elif choice == "low" and total < 7:
            won = True
            result_type = "win"
        elif total == 7:
            result_type = "push"
            # Push - return bet
            payout = bet
            await coins_cog.add_coins(interaction.user.id, interaction.guild.id, bet, "hilow_push", "Hi-Low push (7)")
        else:
            result_type = "loss"

        if won:
            # Get server-specific payout multiplier
            payout_multiplier = get_server_setting(interaction.guild.id, 'hilow_payout', 2.0)
            payout = int(bet * payout_multiplier)
            await coins_cog.add_coins(interaction.user.id, interaction.guild.id, payout, "hilow_win",
                                      f"Hi-Low win: {total}")

        # Standardized title and color logic
        if total == 7:
            title = "🎲 하이로우 - 🤝 무승부!"
            color = discord.Color.blue()
        elif won:
            title = "🎲 하이로우 - 🎉 승리!"
            color = discord.Color.green()
        else:
            title = "🎲 하이로우 - 😞 패배!"
            color = discord.Color.red()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        embed.add_field(
            name="🎯 주사위 결과",
            value=self.create_dice_display(die1, die2, total),
            inline=False
        )

        # STANDARDIZED FIELD 2: Betting Info
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상:** {choice_display[choice]}",
            inline=False
        )

        # STANDARDIZED FIELD 3: Game Results
        if total == 7:
            result_text = f"⚡ **정확히 7이 나왔습니다!**"
            result_info = f"{result_text}\n\n💰 **수익:** {payout:,} 코인\n🤝 **무승부** (베팅 반환)"
        elif won:
            payout_multiplier = get_server_setting(interaction.guild.id, 'hilow_payout', 2.0)
            result_text = f"🎯 **예상 적중!** {payout_multiplier}배 배당"
            profit = payout - bet
            result_info = f"{result_text}\n\n💰 **수익:** {payout:,} 코인\n📈 **순이익:** +{profit:,} 코인"
        else:
            result_text = f"❌ **예상 실패!**"
            result_info = f"{result_text}\n\n💸 **손실:** {bet:,} 코인"

        embed.add_field(name="📊 게임 결과", value=result_info, inline=False)

        # STANDARDIZED FIELD 4: Balance Info
        new_balance = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)
        embed.add_field(name="", value=f"🏦 **현재 잔액:** {new_balance:,} 코인", inline=False)

        # Standardized footer
        embed.set_footer(text=f"플레이어: {interaction.user.display_name} | Server: {interaction.guild.name}")

        await interaction.edit_original_response(embed=embed)

        result_status = '승리' if won else '패배' if total != 7 else '무승부'
        self.logger.info(
            f"{interaction.user}가 하이로우에서 {bet} 코인 {result_status} (결과: {total})",
            extra={'guild_id': interaction.guild.id}
        )


async def setup(bot):
    await bot.add_cog(HiLowCog(bot))